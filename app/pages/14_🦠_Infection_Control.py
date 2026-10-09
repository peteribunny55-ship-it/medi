from __future__ import annotations

import os
import sys

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

import json
import pandas as pd
import streamlit as st

from app.utils.ui import page_requires_role, apply_custom_css, disclaimer_banner, status_badge
from app.utils.exporters import csv_download
from app.db.database import get_db

user = page_requires_role(["Admin", "Doctor", "Nurse"])
apply_custom_css()

st.title("🦠 Infection Control")
disclaimer_banner()
st.caption("⚠ Checklist completions are recorded for compliance audit. AI flagging = prototype; clinical validation required.")

try:
    with get_db() as conn:
        depts = conn.execute("SELECT id, name FROM departments ORDER BY name").fetchall()
        dept_map = {int(r["id"]): r["name"] for r in depts}
        users = conn.execute("SELECT id, full_name FROM users ORDER BY full_name").fetchall()
        user_map = {int(r["id"]): r["full_name"] for r in users}

        from app.core.infection_control import list_templates, list_records, ensure_default_templates
        ensure_default_templates(conn)
        templates = list_templates(conn)
        records = list_records(conn, limit=200)
        completed_today = sum(1 for r in records if pd.Timestamp(str(r.get("completed_at", ""))[:10]).date() == pd.Timestamp.now().date())
        incomplete = sum(1 for r in records if r.get("incomplete"))
        from app.utils.ui import metric_card
        k1, k2, k3 = st.columns(3)
        with k1: metric_card("Checklist Templates", len(templates), icon="📋", variant="info")
        with k2: metric_card("Completions Today", completed_today, icon="✅", variant="occup")
        with k3: metric_card("Records with Gaps", incomplete, icon="⚠️", variant="alert")

        tab1, tab2, tab3 = st.tabs(["📋 Templates & History", "✍ Complete Checklist", "📊 Compliance Overview"])

        with tab1:
            st.markdown("### Checklist Templates")
            if len(templates):
                trows = []
                for t in templates:
                    trows.append({
                        "id": t["id"],
                        "name": t["name"],
                        "dept": dept_map.get(int(t.get("department_id") or 0), "Global"),
                        "items_count": len(t.get("items", [])),
                    })
                tdf = pd.DataFrame(trows)
                st.dataframe(tdf, use_container_width=True, hide_index=True)
                with st.expander("View Template Details"):
                    for t in templates:
                        st.markdown(f"#### 📝 {t['name']} ({dept_map.get(int(t.get('department_id') or 0), 'Global')})")
                        items = t.get("items", [])
                        for idx, it in enumerate(items, 1):
                            st.write(f"{idx}. **{it.get('item','?')}** — _{it.get('guideline','')}_")
            else:
                st.info("No templates. Defaults should be auto-created.")

            st.markdown("#### Completion History")
            hdept = st.selectbox("Filter Department", [0] + list(dept_map.keys()),
                                 format_func=lambda k: "All" if k == 0 else dept_map[k], index=0, key="icdept")
            filt_rec = records
            if hdept != 0:
                filt_rec = [r for r in records if int(r.get("department_id") or 0) == int(hdept)]
            rdf = pd.DataFrame(filt_rec)
            if len(rdf):
                rdf["dept"] = rdf["department_id"].map(dept_map).fillna("?")
                rdf["by_user"] = rdf["completed_by"].map(user_map).fillna("?")
                rdf["template_name"] = rdf["template_id"].map({int(t["id"]): t["name"] for t in templates}).fillna("?")
                rdf["compliance_badge"] = rdf["incomplete"].apply(
                    lambda i: f'<span class="live-badge sim">GAPS</span>' if i else '<span class="live-badge live">COMPLETE</span>')
                show = ["id", "template_name", "ward", "dept", "by_user", "completed_at", "notes", "compliance_badge"]
                show = [c for c in show if c in rdf.columns]
                dfs = rdf[show].copy()
                st.markdown(dfs.to_html(escape=False, index=False), unsafe_allow_html=True)
                csv_download(rdf, "ic_records.csv", "📥 Download IC Records CSV")
            else:
                st.info("No IC records.")

        with tab2:
            st.markdown("### Complete Checklist")
            tpl_opts = {int(t["id"]): t["name"] for t in templates}
            sel_tpl = st.selectbox("Select Template", list(tpl_opts.keys()),
                                   format_func=lambda k: tpl_opts[k], index=0)
            cur_tpl = next((t for t in templates if int(t["id"]) == int(sel_tpl)), None)
            with st.form("ic_checklist_form", clear_on_submit=True):
                cc1, cc2 = st.columns(2)
                with cc1:
                    ward = st.text_input("Ward / Unit *", value="General")
                    dpt = st.selectbox("Department *", list(dept_map.keys()), format_func=lambda k: dept_map[k], index=0)
                with cc2:
                    notes = st.text_area("Notes", height=80)
                st.markdown("#### Checklist Items — mark Passed or N/A:")
                results_ui = []
                if cur_tpl:
                    for idx, it in enumerate(cur_tpl.get("items", [])):
                        item_text = it.get("item", f"Item {idx+1}")
                        guideline = it.get("guideline", "")
                        st.markdown(f"**{idx+1}. {item_text}**  \n<small>{guideline}</small>", unsafe_allow_html=True)
                        ci1, ci2 = st.columns([1, 1])
                        with ci1:
                            passed = st.checkbox("✅ Passed", value=True, key=f"pass_{sel_tpl}_{idx}")
                        with ci2:
                            na = st.checkbox("N/A", value=False, key=f"na_{sel_tpl}_{idx}")
                        results_ui.append({"item": item_text, "passed": passed and not na, "na": na})
                submitted = st.form_submit_button("Submit Checklist Completion", type="primary")
                if submitted:
                    if not ward:
                        st.error("Ward is required.")
                    elif not cur_tpl:
                        st.error("No template selected.")
                    else:
                        try:
                            from app.core.infection_control import submit_record
                            r = submit_record(conn, user, int(sel_tpl), ward, int(dpt), results_ui, notes or "")
                            if r.get("incomplete"):
                                st.warning("⚠ Checklist submitted but has non-passed items (gaps flagged).")
                            else:
                                st.success(f"✅ Checklist record #{r['id']} saved — fully compliant.")
                            st.rerun()
                        except Exception as e:
                            st.error(f"Failed to save checklist: {e}")

        with tab3:
            st.markdown("### Compliance Overview")
            total_r = len(records)
            compliant_r = sum(1 for r in records if not r.get("incomplete"))
            rate = round((compliant_r / total_r) * 100, 1) if total_r > 0 else 0.0
            m1, m2, m3 = st.columns(3)
            with m1: metric_card("Total Records", total_r, icon="📝", variant="info")
            with m2: metric_card("Fully Compliant", compliant_r, icon="✅", variant="occup")
            with m3: metric_card("Compliance Rate", f"{rate}%", icon="📊", variant="warn" if rate < 85 else "info")

            st.markdown("#### Per Template Breakdown")
            breakdown = []
            for t in templates:
                trecs = [r for r in records if int(r.get("template_id") or 0) == int(t["id"])]
                tc = len(trecs)
                tpass = sum(1 for r in trecs if not r.get("incomplete"))
                trate = round((tpass / tc) * 100, 1) if tc > 0 else None
                breakdown.append({
                    "Template": t["name"],
                    "Completions": tc,
                    "Compliant": tpass,
                    "Compliance %": trate if trate is not None else 0,
                })
            bdf = pd.DataFrame(breakdown)
            st.dataframe(bdf, use_container_width=True, hide_index=True)

            st.markdown("#### Per Department (last 30 records)")
            d_break = []
            for did in dept_map:
                dr = [r for r in records if int(r.get("department_id") or 0) == int(did)]
                d_total = len(dr)
                d_pass = sum(1 for r in dr if not r.get("incomplete"))
                d_rate = round((d_pass / d_total) * 100, 1) if d_total > 0 else None
                d_break.append({
                    "Department": dept_map[did],
                    "Completions": d_total,
                    "Compliant": d_pass,
                    "Compliance %": d_rate if d_rate is not None else 0,
                })
            ddf = pd.DataFrame(d_break)
            st.dataframe(ddf, use_container_width=True, hide_index=True)
except Exception as e:
    st.error(f"Infection control page error: {e}")
