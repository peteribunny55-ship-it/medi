from __future__ import annotations

import os
import sys

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

import pandas as pd
import streamlit as st

from app.utils.ui import page_requires_role, apply_custom_css, disclaimer_banner, status_badge
from app.utils.exporters import csv_download
from app.db.database import get_db

user = page_requires_role(["Admin", "Doctor", "Nurse"])
apply_custom_css()

st.title("🧪 Laboratory")
disclaimer_banner()

try:
    with get_db() as conn:
        depts = conn.execute("SELECT id, name FROM departments ORDER BY name").fetchall()
        dept_map = {int(r["id"]): r["name"] for r in depts}
        k1, k2, k3, k4 = st.columns(4)
        from app.core.lab import list_requests, TAT_stats
        all_req = list_requests(conn, limit=1000)
        pending_count = sum(1 for r in all_req if r.get("status") in ("Requested", "Collected", "InProgress"))
        completed_count = sum(1 for r in all_req if r.get("status") == "Completed")
        delayed_count = sum(1 for r in all_req if r.get("delayed"))
        try:
            tat = TAT_stats(conn, days=30)
            mean_tat = tat.get("mean_tat_min", 0)
        except Exception:
            mean_tat = 0
        from app.utils.ui import metric_card
        with k1: metric_card("Pending", pending_count, icon="⏳", variant="warn")
        with k2: metric_card("Completed (30d)", completed_count, icon="✅", variant="occup")
        with k3: metric_card("Delayed", delayed_count, icon="⚠️", variant="alert")
        with k4: metric_card("Mean TAT (min)", f"{mean_tat:.0f}", icon="⏱️", variant="info")

        tab1, tab2, tab3 = st.tabs(["📋 Lab Requests List", "➕ Create Request", "🔄 Update Status"])

        with tab1:
            st.markdown("### Lab Requests")
            c1, c2, c3, c4 = st.columns(4)
            with c1:
                fs = st.selectbox("Status Filter", ["", "Requested", "Collected", "InProgress", "Completed", "Cancelled"], index=0)
            with c2:
                fd = st.selectbox("Department", [0] + list(dept_map.keys()),
                                  format_func=lambda k: "All" if k == 0 else dept_map[k], index=0)
            with c3:
                fdel = st.checkbox("Delayed Only (>24h)", value=False)
            with c4:
                fp = st.selectbox("Priority", ["", "Routine", "Stat"], index=0)
            reqs = list_requests(
                conn,
                status=(fs or None),
                dept_id=(None if fd == 0 else int(fd)),
                delayed_only=fdel,
                limit=1000,
            )
            if fp:
                reqs = [r for r in reqs if str(r.get("priority", "")) == fp]
            rdf = pd.DataFrame(reqs)
            if len(rdf):
                patients = conn.execute("SELECT id, patient_id, first_name, last_name FROM patients").fetchall()
                pmap = {int(r["id"]): f"{r['patient_id']} — {r['first_name']} {r['last_name']}" for r in patients}
                users = conn.execute("SELECT id, full_name FROM users").fetchall()
                umap = {int(r["id"]): r["full_name"] for r in users}
                rdf["patient"] = rdf["patient_id"].map(pmap).fillna("?")
                rdf["requester"] = rdf["requested_by"].map(umap).fillna("?")
                rdf["delayed_flag"] = rdf["delayed"].apply(
                    lambda d: f'<span class="live-badge sim">DELAYED</span>' if d else '<span class="live-badge live">On Track</span>')
                show = ["id", "patient", "test_type", "test_category", "priority",
                        "status", "delayed_flag", "requester", "ordered_at", "resulted_at", "turnaround_minutes"]
                show = [c for c in show if c in rdf.columns]
                dfs = rdf[show].copy()
                dfs["status"] = dfs["status"].apply(lambda s: status_badge(str(s)))
                dfs["priority"] = dfs["priority"].apply(lambda s: status_badge(str(s)))
                st.markdown(dfs.to_html(escape=False, index=False), unsafe_allow_html=True)
                csv_download(rdf, "lab_requests.csv", "📥 Download Lab Requests CSV")
            else:
                st.info("No lab requests matching criteria.")

        with tab2:
            st.markdown("### Create Lab Request")
            patients = conn.execute("SELECT id, patient_id, first_name, last_name FROM patients ORDER BY id DESC LIMIT 500").fetchall()
            pmap = {int(r["id"]): f"{r['patient_id']} — {r['first_name']} {r['last_name']}" for r in patients}
            with st.form("lab_req_form", clear_on_submit=True):
                l1, l2 = st.columns(2)
                with l1:
                    lp = st.selectbox("Patient", list(pmap.keys()), format_func=lambda k: pmap[k], index=0 if pmap else 0)
                    ltype = st.text_input("Test Type * (e.g. CBC, X-Ray, ECG)")
                    lcat = st.text_input("Test Category (e.g. Hematology, Radiology)")
                with l2:
                    lprio = st.selectbox("Priority", ["Routine", "Stat"], index=0)
                sub = st.form_submit_button("Create Lab Request", type="primary")
                if sub:
                    if not ltype or not pmap:
                        st.error("Test type and patient are required.")
                    else:
                        try:
                            from app.core.lab import create_request
                            result = create_request(
                                conn, user,
                                patient_id=int(lp),
                                test_type=ltype,
                                test_category=lcat or "",
                                priority=lprio,
                            )
                            st.success(f"✅ Lab request #{result['id']} created: {result['test_type']} [{result['priority']}]")
                        except Exception as e:
                            st.error(f"Failed to create request: {e}")

        with tab3:
            st.markdown("### Update Status")
            open_lab = list_requests(conn, limit=300)
            open_lab = [r for r in open_lab if r.get("status") not in ("Completed", "Cancelled")]
            if not open_lab:
                st.info("No pending lab requests to update.")
            else:
                oldf = pd.DataFrame(open_lab)
                oldf["patient"] = oldf["patient_id"].map(pmap).fillna("?")
                oldf["label"] = "#" + oldf["id"].astype(str) + " — " + oldf["patient"] + " / " + oldf["test_type"] + f" [{oldf['status']}]"
                sid = st.selectbox("Select Request", list(oldf["id"].values),
                                   format_func=lambda i: oldf.loc[oldf["id"] == i, "label"].iloc[0], index=0)
                cur_status_row = next(r for r in open_lab if int(r["id"]) == int(sid))
                cur = cur_status_row["status"]
                allowed = {
                    "Requested": ["Collected", "InProgress", "Cancelled"],
                    "Collected": ["InProgress", "Cancelled"],
                    "InProgress": ["Completed", "Cancelled"],
                    "Cancelled": [],
                    "Completed": [],
                }
                opts = allowed.get(cur, [])
                nstat = st.selectbox(f"Current status: {cur}. New Status", opts, index=0 if opts else 0)
                notes = st.text_area("Result Notes (applied when Completed)")
                if st.button("Update Status", type="primary") and nstat:
                    try:
                        from app.core.lab import update_status
                        update_status(conn, user, int(sid), nstat, notes or None)
                        st.success(f"✅ Request #{sid} → {nstat}")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Update failed: {e}")
except Exception as e:
    st.error(f"Laboratory page error: {e}")
