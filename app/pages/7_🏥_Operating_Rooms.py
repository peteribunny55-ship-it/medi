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

user = page_requires_role(["Admin", "Doctor"])
apply_custom_css()

st.title("🏥 Operating Rooms")
disclaimer_banner()

try:
    with get_db() as conn:
        depts = conn.execute("SELECT id, name FROM departments ORDER BY name").fetchall()
        dept_map = {int(r["id"]): r["name"] for r in depts}

        from app.core.or_scheduling import list_operating_rooms
        ors = list_operating_rooms(conn)
        odf = pd.DataFrame(ors)
        if "department_id" in odf.columns:
            odf["dept_name"] = odf["department_id"].map(dept_map).fillna("—")
        k1, k2, k3 = st.columns(3)
        total_or = len(odf) if len(odf) else 0
        avail_or = (odf["status"] == "Available").sum() if len(odf) else 0
        today = pd.Timestamp.now().strftime("%Y-%m-%d")
        booked_today = conn.execute("SELECT COUNT(*) FROM or_schedules WHERE date(planned_start)=date('now') AND status!='Cancelled'").fetchone()[0]
        from app.utils.ui import metric_card
        with k1: metric_card("Total ORs", total_or, icon="🏥", variant="info")
        with k2: metric_card("Available", avail_or, icon="✅", variant="occup")
        with k3: metric_card("Booked Today", booked_today, icon="📋", variant="warn")

        tab1, tab2, tab3 = st.tabs(["🩺 OR List & Bookings", "📝 Schedule Procedure", "✅ Approve Schedules"])

        with tab1:
            st.markdown("#### Operating Rooms")
            if len(odf):
                show = ["room_no", "dept_name", "status", "last_cleaned_at"]
                show = [c for c in show if c in odf.columns]
                dfs = odf[show].copy()
                dfs["status"] = dfs["status"].apply(lambda s: status_badge(str(s)))
                st.markdown(dfs.to_html(escape=False, index=False), unsafe_allow_html=True)
            else:
                st.info("No OR records.")
            st.markdown("#### Upcoming OR Schedules")
            f1, f2 = st.columns(2)
            with f1:
                df_or = st.date_input("From", value=pd.Timestamp.now().to_pydatetime())
            with f2:
                dt_or = st.date_input("To", value=(pd.Timestamp.now() + pd.Timedelta(days=14)).to_pydatetime())
            from app.core.or_scheduling import list_or_schedule
            scheds = list_or_schedule(conn, str(df_or), str(dt_or))
            sdf = pd.DataFrame(scheds)
            if len(sdf):
                docs = conn.execute("SELECT d.id, u.full_name FROM doctors d JOIN users u ON u.id=d.user_id").fetchall()
                doc_map = {int(r["id"]): r["full_name"] for r in docs}
                or_room_map = {int(r["id"]): r["room_no"] for r in ors}
                sdf["room_no"] = sdf["or_id"].map(or_room_map).fillna("?")
                sdf["doctor_name"] = sdf["assigned_doctor_id"].map(doc_map).fillna("—")
                sdf["requires_approval_flag"] = sdf["requires_approval"].apply(
                    lambda x: '<span class="live-badge sim">REQUIRES HUMAN APPROVAL</span>' if x else '<span class="live-badge live">APPROVED</span>')
                show = ["id", "room_no", "patient_id", "procedure_name", "procedure_type",
                        "planned_start", "planned_end", "estimated_duration_min", "doctor_name", "status", "requires_approval_flag"]
                show = [c for c in show if c in sdf.columns]
                dfs = sdf[show].copy()
                dfs["status"] = dfs["status"].apply(lambda s: status_badge(str(s)))
                st.markdown(dfs.to_html(escape=False, index=False), unsafe_allow_html=True)
                csv_download(sdf, "or_schedules.csv", "📥 Download OR Schedule CSV")
            else:
                st.info("No scheduled procedures.")

        with tab2:
            st.markdown("### Schedule Procedure")
            patients = conn.execute("SELECT id, patient_id, first_name, last_name FROM patients ORDER BY id DESC LIMIT 500").fetchall()
            pat_map = {int(r["id"]): f"{r['patient_id']} — {r['first_name']} {r['last_name']}" for r in patients}
            doctors = conn.execute("SELECT d.id, u.full_name FROM doctors d JOIN users u ON u.id=d.user_id ORDER BY u.full_name").fetchall()
            doc_map = {int(r["id"]): r["full_name"] for r in doctors}
            or_map = {int(r["id"]): r["room_no"] + f" ({dept_map.get(int(r['department_id']),'?')})" for r in ors}
            with st.form("or_proc_form", clear_on_submit=True):
                c1, c2 = st.columns(2)
                with c1:
                    p_or = st.selectbox("Operating Room", list(or_map.keys()), format_func=lambda k: or_map[k], index=0)
                    p_pat = st.selectbox("Patient", list(pat_map.keys()), format_func=lambda k: pat_map[k], index=0)
                    p_doc = st.selectbox("Assigned Doctor", list(doc_map.keys()), format_func=lambda k: doc_map[k], index=0)
                    p_type = st.selectbox("Procedure Type", ["Elective", "Emergency", "Diagnostic", "Therapeutic"])
                with c2:
                    p_name = st.text_input("Procedure Name *")
                    p_start_date = st.date_input("Planned Start Date")
                    p_start_time = st.time_input("Planned Start Time")
                    p_dur = st.number_input("Estimated Duration (minutes)", min_value=15, step=15, value=60)
                submitted = st.form_submit_button("Schedule Procedure (Draft)", type="primary")
                if submitted:
                    if not p_name:
                        st.error("Procedure name is required.")
                    else:
                        try:
                            import datetime as _dt
                            sd = pd.Timestamp(str(p_start_date)) + pd.Timedelta(hours=p_start_time.hour, minutes=p_start_time.minute)
                            start_iso = sd.strftime("%Y-%m-%d %H:%M:%S")
                            end_dt = sd + pd.Timedelta(minutes=int(p_dur))
                            end_iso = end_dt.strftime("%Y-%m-%d %H:%M:%S")
                            from app.core.or_scheduling import book_or_procedure
                            result = book_or_procedure(
                                conn, user,
                                or_id=int(p_or),
                                patient_id=int(p_pat),
                                procedure_name=p_name,
                                procedure_type=p_type,
                                planned_start_iso=start_iso,
                                planned_end_iso=end_iso,
                                estimated_min=int(p_dur),
                                assigned_doctor_id=int(p_doc),
                            )
                            st.success(f"✅ Procedure #{result['id']} scheduled as Draft.  <span class='live-badge sim'>HUMAN APPROVAL REQUIRED</span>", unsafe_allow_html=True)
                        except Exception as e:
                            st.error(f"Scheduling failed: {e}")

        with tab3:
            st.markdown("### Approve Schedules")
            pending = conn.execute(
                """SELECT os.*, or_.room_no FROM or_schedules os
                   LEFT JOIN operating_rooms or_ ON or_.id = os.or_id
                   WHERE os.requires_approval=1 OR os.status IN ('Draft','Approved')
                   ORDER BY os.id DESC LIMIT 200"""
            ).fetchall()
            pdf = pd.DataFrame([dict(r) for r in pending])
            if not len(pdf):
                st.info("No schedules pending approval.")
            else:
                pdf["label"] = "#" + pdf["id"].astype(str) + " / " + pdf["room_no"].fillna("?") + " — " + pdf["procedure_name"] + " on " + pdf["planned_start"]
                sid = st.selectbox("Select Schedule to Approve", list(pdf["id"].values),
                                   format_func=lambda i: pdf.loc[pdf["id"] == i, "label"].iloc[0], index=0)
                if st.button("✅ Approve / Progress Status", type="primary"):
                    try:
                        from app.core.or_scheduling import approve_or_schedule
                        r = approve_or_schedule(conn, user, int(sid))
                        st.success(f"✅ Schedule status updated to: {r['status']}")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Approval failed: {e}")
                st.markdown("#### All Pending Records")
                show_cols = ["id", "room_no", "procedure_name", "procedure_type", "planned_start", "status", "requires_approval"]
                show_cols = [c for c in show_cols if c in pdf.columns]
                dfs = pdf[show_cols].copy()
                dfs["status"] = dfs["status"].apply(lambda s: status_badge(str(s)))
                dfs["requires_approval"] = dfs["requires_approval"].apply(
                    lambda x: '<span class="live-badge sim">YES</span>' if x else '<span class="live-badge live">NO</span>')
                st.markdown(dfs.to_html(escape=False, index=False), unsafe_allow_html=True)
except Exception as e:
    st.error(f"Operating rooms page error: {e}")
