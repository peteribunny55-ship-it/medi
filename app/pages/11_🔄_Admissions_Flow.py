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

st.title("🔄 Admissions Flow")
disclaimer_banner()

try:
    with get_db() as conn:
        depts = conn.execute("SELECT id, name FROM departments ORDER BY name").fetchall()
        dept_map = {int(r["id"]): r["name"] for r in depts}

        active_sql = """SELECT COUNT(*) FROM admissions WHERE status != 'Discharged'"""
        active_count = conn.execute(active_sql).fetchone()[0]
        em_count = conn.execute("SELECT COUNT(*) FROM admissions WHERE status!='Discharged' AND admission_type='Emergency'").fetchone()[0]
        disch_today = conn.execute("SELECT COUNT(*) FROM admissions WHERE date(discharged_at)=date('now')").fetchone()[0]
        from app.utils.ui import metric_card
        k1, k2, k3 = st.columns(3)
        with k1: metric_card("Active Admissions", active_count, icon="🏥", variant="info")
        with k2: metric_card("Active Emergency", em_count, icon="🚑", variant="alert")
        with k3: metric_card("Discharged Today", disch_today, icon="✅", variant="occup")

        tab1, tab2, tab3 = st.tabs(["📋 Admissions List", "🏥 Admit / Discharge", "🔍 Bottleneck Detection"])

        with tab1:
            st.markdown("### Admissions")
            c1, c2, c3 = st.columns(3)
            with c1:
                fs = st.selectbox("Status", ["", "Admitted", "Triage", "InTreatment", "DischargePending", "Discharged"], index=0)
            with c2:
                fd = st.selectbox("Department (via bed)", [0] + list(dept_map.keys()),
                                  format_func=lambda k: "All" if k == 0 else dept_map[k], index=0)
            with c3:
                fmt = st.selectbox("Admission Type", ["", "Elective", "Emergency", "Transfer"], index=0)
            sql = """SELECT a.*, b.bed_no, b.department_id AS bed_dept, d.name AS dept_name,
                            p.patient_id, p.first_name, p.last_name
                     FROM admissions a
                     LEFT JOIN beds b ON b.id = a.bed_id
                     LEFT JOIN departments d ON d.id = b.department_id
                     LEFT JOIN patients p ON p.id = a.patient_id
                     WHERE 1=1"""
            params = []
            if fs:
                sql += " AND a.status = ?"
                params.append(fs)
            if fd != 0:
                sql += " AND b.department_id = ?"
                params.append(int(fd))
            if fmt:
                sql += " AND a.admission_type = ?"
                params.append(fmt)
            sql += " ORDER BY a.id DESC LIMIT 500"
            rows = conn.execute(sql, params).fetchall()
            adf = pd.DataFrame([dict(r) for r in rows])
            if len(adf):
                adf["patient"] = adf["patient_id"].fillna("") + " — " + adf["first_name"].fillna("") + " " + adf["last_name"].fillna("")
                show = ["id", "patient", "bed_no", "dept_name", "admission_type", "triage_level",
                        "diagnosis", "status", "admitted_at", "discharged_at"]
                show = [c for c in show if c in adf.columns]
                dfs = adf[show].copy()
                dfs["status"] = dfs["status"].apply(lambda s: status_badge(str(s)))
                st.markdown(dfs.to_html(escape=False, index=False), unsafe_allow_html=True)
                csv_download(adf, "admissions.csv", "📥 Download Admissions CSV")
            else:
                st.info("No admissions matching criteria.")

        with tab2:
            st.markdown("### Quick Admit / Discharge")
            act = st.radio("Action", ["Admit Patient", "Discharge Admission"], horizontal=True)
            if act == "Admit Patient":
                patients = conn.execute(
                    """SELECT id, patient_id, first_name, last_name FROM patients
                       WHERE id NOT IN (SELECT patient_id FROM admissions WHERE status NOT IN ('Discharged'))
                       ORDER BY id DESC LIMIT 500"""
                ).fetchall()
                pmap = {int(r["id"]): f"{r['patient_id']} — {r['first_name']} {r['last_name']}" for r in patients}
                from app.core.beds import list_beds as lbeds
                avail_beds = lbeds(conn, status="Available")
                bmap = {int(b["id"]): f"{b['bed_no']} ({b.get('dept_name','?')}, {b.get('bed_type','?')})" for b in avail_beds}
                doctors = conn.execute("SELECT d.id, u.full_name FROM doctors d JOIN users u ON u.id=d.user_id ORDER BY u.full_name").fetchall()
                dmap = {0: "None"} | {int(r["id"]): r["full_name"] for r in doctors}
                with st.form("adm_form", clear_on_submit=True):
                    a1, a2 = st.columns(2)
                    with a1:
                        sp = st.selectbox("Patient", list(pmap.keys()), format_func=lambda k: pmap.get(k, "?"), index=0 if pmap else 0)
                        sb = st.selectbox("Available Bed", list(bmap.keys()), format_func=lambda k: bmap.get(k, "?"), index=0 if bmap else 0)
                        sd = st.selectbox("Attending Doctor", list(dmap.keys()), format_func=lambda k: dmap[k], index=0)
                    with a2:
                        stype = st.selectbox("Admission Type", ["Elective", "Emergency", "Transfer"], index=0)
                        diag = st.text_area("Diagnosis", height=80)
                    ab = st.form_submit_button("Admit Patient", type="primary")
                    if ab:
                        if not pmap or not bmap:
                            st.error("Need at least one eligible patient and one available bed.")
                        else:
                            try:
                                from app.core.admissions import allocate_bed
                                r = allocate_bed(conn, user, patient_id=int(sp), bed_id=int(sb),
                                                 doctor_id=(None if sd == 0 else int(sd)),
                                                 admission_type=stype, diagnosis=diag or None)
                                st.success(f"✅ Admission #{r['id']} created.")
                                st.rerun()
                            except Exception as e:
                                st.error(f"Admit failed: {e}")
            else:
                open_sql = """SELECT a.id, a.status, p.patient_id, p.first_name, p.last_name, b.bed_no
                              FROM admissions a
                              LEFT JOIN patients p ON p.id=a.patient_id
                              LEFT JOIN beds b ON b.id=a.bed_id
                              WHERE a.status!='Discharged' ORDER BY a.id DESC"""
                open_a = conn.execute(open_sql).fetchall()
                odf = pd.DataFrame([dict(r) for r in open_a])
                if not len(odf):
                    st.info("No active admissions.")
                else:
                    odf["label"] = "#" + odf["id"].astype(str) + " — " + odf["patient_id"] + " " + odf["first_name"] + " " + odf["last_name"] + " / Bed " + odf["bed_no"].fillna("?")
                    sa = st.selectbox("Select Admission to Discharge", list(odf["id"].values),
                                      format_func=lambda i: odf.loc[odf["id"] == i, "label"].iloc[0], index=0)
                    if st.button("Confirm Discharge", type="primary"):
                        try:
                            from app.core.admissions import discharge
                            discharge(conn, user, int(sa))
                            st.success("✅ Patient discharged — bed freed.")
                            st.rerun()
                        except Exception as e:
                            st.error(f"Discharge failed: {e}")

        with tab3:
            st.markdown("### Bottleneck Detection (AI Analysis)")
            st.caption("Analyzes workflow dwell times for Order→Lab Pickup, Admission→Discharge, Queue→Service steps.")
            lookback = st.slider("Lookback Days", 7, 90, 30)
            if st.button("🔍 Run Bottleneck Analysis", type="primary"):
                try:
                    from app.core.admissions import bottleneck_detection
                    bns = bottleneck_detection(conn, lookback_days=int(lookback))
                    bdf = pd.DataFrame(bns)
                    if len(bdf):
                        if "department_id" in bdf.columns:
                            bdf["department"] = bdf["department_id"].map(dept_map).fillna("All")
                        bdf["alert"] = bdf["alert_level"].apply(lambda a: status_badge(str(a)))
                        show = ["workflow_step", "department", "median_dwell_minutes", "alert", "sample_count"]
                        show = [c for c in show if c in bdf.columns]
                        st.dataframe(bdf[show], use_container_width=True, hide_index=True)
                        crit = len(bdf[bdf["alert_level"] == "Critical"]) if "alert_level" in bdf.columns else 0
                        warn = len(bdf[bdf["alert_level"] == "Warning"]) if "alert_level" in bdf.columns else 0
                        if crit:
                            st.error(f"🚨 {crit} CRITICAL bottleneck(s) detected — requires immediate attention.")
                        if warn:
                            st.warning(f"⚠ {warn} WARNING-level bottleneck(s).")
                        if not crit and not warn:
                            st.success("✅ No significant bottlenecks detected.")
                        csv_download(bdf, "bottlenecks.csv", "📥 Download Bottleneck CSV")
                    else:
                        st.info("Insufficient data for bottleneck detection in this period.")
                except Exception as e:
                    st.error(f"Bottleneck analysis failed: {e}")
            st.markdown("#### Historical Bottleneck Records")
            hist = conn.execute(
                "SELECT * FROM bottleneck_records ORDER BY id DESC LIMIT 100"
            ).fetchall()
            hdf = pd.DataFrame([dict(r) for r in hist])
            if len(hdf):
                if "department_id" in hdf.columns:
                    hdf["department"] = hdf["department_id"].map(dept_map).fillna("All")
                hdf["alert"] = hdf["alert_level"].apply(lambda a: status_badge(str(a)))
                show = ["workflow_step", "department", "median_dwell_minutes", "alert", "sample_count", "observed_at"]
                show = [c for c in show if c in hdf.columns]
                st.dataframe(hdf[show], use_container_width=True, hide_index=True)
            else:
                st.caption("No historical bottleneck records yet. Run an analysis to populate.")
except Exception as e:
    st.error(f"Admissions page error: {e}")
