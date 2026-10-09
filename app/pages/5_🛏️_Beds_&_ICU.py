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

user = page_requires_role(["Admin", "Nurse", "Doctor"])
apply_custom_css()

st.title("🛏️ Beds & ICU Management")
disclaimer_banner()

try:
    with get_db() as conn:
        depts = conn.execute("SELECT id, name FROM departments ORDER BY name").fetchall()
        dept_map = {0: "All"} | {int(r["id"]): r["name"] for r in depts}

        from app.core.beds import bed_utilization
        util = bed_utilization(conn)
        udf = pd.DataFrame(util)
        c1, c2, c3, c4 = st.columns(4)
        total_b = udf["total"].sum() if len(udf) else 0
        occ_b = udf["occupied"].sum() if len(udf) else 0
        av_b = udf["available"].sum() if len(udf) else 0
        mnt_b = udf["maintenance"].sum() if len(udf) else 0
        from app.utils.ui import metric_card
        with c1: metric_card("Total Beds", total_b, icon="🛏️", variant="info")
        with c2: metric_card("Occupied", occ_b, icon="🔴", variant="alert")
        with c3: metric_card("Available", av_b, icon="✅", variant="occup")
        with c4: metric_card("Maintenance", mnt_b, icon="🔧", variant="warn")

        tab1, tab2, tab3 = st.tabs(["📋 Bed Inventory", "🏥 Allocate / Admit", "🚪 Discharge / Transfer"])

        with tab1:
            st.markdown("### Bed List")
            b1, b2, b3, b4 = st.columns(4)
            with b1:
                s_dept = st.selectbox("Department", list(dept_map.keys()),
                                      format_func=lambda k: dept_map[k], index=0)
            with b2:
                s_status = st.selectbox("Status", ["", "Available", "Occupied", "Maintenance"])
            with b3:
                s_type = st.selectbox("Bed Type", ["", "General", "ICU", "VIP", "Pediatric", "Maternity", "Emergency"])
            with b4:
                s_ward = st.text_input("Ward")

            from app.core.beds import list_beds
            beds = list_beds(
                conn,
                status=(s_status or None),
                dept_id=(None if s_dept == 0 else int(s_dept)),
                bed_type=(s_type or None),
                ward=(s_ward or None),
            )
            bdf = pd.DataFrame(beds)
            if len(bdf):
                bdf["patient"] = bdf["patient_first_name"].fillna("") + " " + bdf["patient_last_name"].fillna("")
                show = ["bed_no", "dept_name", "ward", "bed_type", "status", "patient", "patient_code"]
                show = [c for c in show if c in bdf.columns]
                dfs = bdf[show].copy()
                dfs["status"] = dfs["status"].apply(lambda s: status_badge(str(s)))
                st.markdown(dfs.to_html(escape=False, index=False), unsafe_allow_html=True)
                csv_download(bdf, "beds.csv", "📥 Download Bed List CSV")
            else:
                st.info("No beds matching criteria.")
            if len(udf):
                st.markdown("#### Department Utilization")
                st.dataframe(udf, use_container_width=True, hide_index=True)

        with tab2:
            st.markdown("### Allocate Bed to Patient")
            with st.form("allocate_form", clear_on_submit=True):
                a1, a2 = st.columns(2)
                patients = conn.execute(
                    """SELECT id, patient_id, first_name, last_name FROM patients
                       WHERE id NOT IN (SELECT patient_id FROM admissions WHERE status IN ('Admitted','Triage','InTreatment','DischargePending'))
                       ORDER BY id DESC LIMIT 500"""
                ).fetchall()
                pat_options = {int(r["id"]): f"{r['patient_id']} — {r['first_name']} {r['last_name']}" for r in patients}
                available_beds = list_beds(conn, status="Available")
                bed_options = {int(b["id"]): f"{b['bed_no']} ({b.get('dept_name','?')}, {b.get('bed_type','?')})" for b in available_beds}
                docs = conn.execute(
                    """SELECT d.id, u.full_name FROM doctors d JOIN users u ON u.id=d.user_id ORDER BY u.full_name"""
                ).fetchall()
                doc_options = {0: "None"} | {int(r["id"]): r["full_name"] for r in docs}

                with a1:
                    sel_patient = st.selectbox("Patient", list(pat_options.keys()), format_func=lambda k: pat_options.get(k, "?"), index=0 if pat_options else 0)
                    sel_doc = st.selectbox("Attending Doctor", list(doc_options.keys()), format_func=lambda k: doc_options[k], index=0)
                    diag = st.text_area("Diagnosis", height=70)
                with a2:
                    sel_bed = st.selectbox("Available Bed", list(bed_options.keys()), format_func=lambda k: bed_options.get(k, "?"), index=0 if bed_options else 0)
                    adm_type = st.selectbox("Admission Type", ["Elective", "Emergency", "Transfer"])
                    triage = st.selectbox("Triage Level (1 worst)", [0, 1, 2, 3, 4, 5], index=0)
                alloc_btn = st.form_submit_button("Allocate Bed & Admit", type="primary")
                if alloc_btn:
                    if not pat_options or not bed_options:
                        st.error("Either no available patients or no available beds.")
                    else:
                        try:
                            from app.core.beds import allocate_bed
                            result = allocate_bed(
                                conn, user,
                                bed_id=int(sel_bed),
                                patient_id=int(sel_patient),
                                doctor_id=(None if sel_doc == 0 else int(sel_doc)),
                                diagnosis=diag or "",
                                admission_type=adm_type,
                                triage_level=(None if triage == 0 else int(triage)),
                            )
                            st.success(f"✅ Admission #{result['id']} created — bed allocated.")
                        except Exception as e:
                            st.error(f"Allocation failed: {e}")

        with tab3:
            st.markdown("### Discharge or Transfer")
            active_sql = """SELECT a.*, b.bed_no, d.name AS dept_name,
                                   p.first_name, p.last_name, p.patient_id AS patient_code
                            FROM admissions a
                            LEFT JOIN beds b ON b.id = a.bed_id
                            LEFT JOIN departments d ON d.id = b.department_id
                            LEFT JOIN patients p ON p.id = a.patient_id
                            WHERE a.status != 'Discharged' ORDER BY a.id DESC"""
            active = conn.execute(active_sql).fetchall()
            adf = pd.DataFrame([dict(r) for r in active])
            if not len(adf):
                st.info("No active admissions.")
            else:
                adf["label"] = "#" + adf["id"].astype(str) + " — " + adf["patient_code"] + " / Bed " + adf["bed_no"].fillna("?")
                sel_aid = st.selectbox("Select Admission", list(adf["id"].values),
                                       format_func=lambda i: adf.loc[adf["id"] == i, "label"].iloc[0], index=0)
                act = st.radio("Action", ["Discharge", "Transfer"], horizontal=True)

                if act == "Discharge":
                    if st.button("Discharge Patient", type="primary"):
                        try:
                            from app.core.beds import discharge_bed
                            discharge_bed(conn, user, int(sel_aid))
                            st.success("✅ Patient discharged — bed freed.")
                            st.rerun()
                        except Exception as e:
                            st.error(f"Discharge failed: {e}")
                else:
                    avail_transfer = list_beds(conn, status="Available")
                    transfer_opts = {int(b["id"]): f"{b['bed_no']} ({b.get('dept_name','?')}, {b.get('bed_type','?')})" for b in avail_transfer}
                    t2 = st.text_input("Transfer Reason")
                    sel_tgt = st.selectbox("Destination Bed", list(transfer_opts.keys()),
                                           format_func=lambda k: transfer_opts.get(k, "?"), index=0 if transfer_opts else 0)
                    if st.button("Transfer Patient", type="primary"):
                        if not transfer_opts:
                            st.error("No available beds for transfer.")
                        else:
                            try:
                                from app.core.beds import transfer_patient
                                transfer_patient(conn, user, int(sel_aid), int(sel_tgt), t2 or "")
                                st.success("✅ Patient transferred to new bed.")
                                st.rerun()
                            except Exception as e:
                                st.error(f"Transfer failed: {e}")
except Exception as e:
    st.error(f"Beds page error: {e}")
