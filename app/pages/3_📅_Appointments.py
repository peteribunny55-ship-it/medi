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

user = page_requires_role(["Admin", "Doctor", "Nurse", "Patient"])
apply_custom_css()

st.title("📅 Appointments")
disclaimer_banner()

try:
    with get_db() as conn:
        depts = conn.execute("SELECT id, name FROM departments ORDER BY name").fetchall()
        dept_map = {int(r["id"]): r["name"] for r in depts}
        doctors = conn.execute(
            """SELECT d.id, u.full_name, d.department_id
               FROM doctors d JOIN users u ON u.id = d.user_id ORDER BY u.full_name"""
        ).fetchall()
        doc_map = {int(r["id"]): f"{r['full_name']} ({dept_map.get(int(r['department_id']), '?')})" for r in doctors}
        patients = conn.execute("SELECT id, patient_id, first_name, last_name FROM patients ORDER BY id DESC LIMIT 300").fetchall()
        pat_map = {int(r["id"]): f"{r['patient_id']} — {r['first_name']} {r['last_name']}" for r in patients}

        tab1, tab2, tab3 = st.tabs(["📖 View Appointments", "➕ Book Appointment", "🔄 Reschedule / Cancel"])

        with tab1:
            st.markdown("### Appointments List")
            fc1, fc2, fc3, fc4 = st.columns(4)
            with fc1:
                f_status = st.selectbox("Status", ["", "Scheduled", "Confirmed", "Completed", "Missed", "Cancelled"])
            with fc2:
                f_dept = st.selectbox("Department", [0] + list(dept_map.keys()),
                                      format_func=lambda k: "All" if k == 0 else dept_map[k], index=0)
            with fc3:
                f_df = st.date_input("Date From", value=None)
            with fc4:
                f_dt = st.date_input("Date To", value=None)

            from app.core.appointments import list_appointments

            appts = list_appointments(
                conn, user,
                dept_id=(None if f_dept == 0 else int(f_dept)),
                status=(f_status or None),
                date_from=str(f_df) if f_df else None,
                date_to=str(f_dt) if f_dt else None,
                limit=500,
            )
            df = pd.DataFrame(appts)
            if len(df):
                df["patient"] = df["patient_first_name"].fillna("") + " " + df["patient_last_name"].fillna("")
                show = ["id", "appointment_date", "appointment_time", "patient_code", "patient",
                        "doctor_name", "dept_name", "status", "reason"]
                show = [c for c in show if c in df.columns]
                df_show = df[show].copy()
                if "status" in df_show.columns:
                    df_show["status"] = df_show["status"].apply(lambda s: status_badge(str(s)))
                    st.markdown(df_show.to_html(escape=False, index=False), unsafe_allow_html=True)
                else:
                    st.dataframe(df_show, use_container_width=True, hide_index=True)
                csv_download(df, "appointments.csv", "📥 Download Appointments CSV")
            else:
                st.info("No appointments matching criteria.")

        with tab2:
            st.markdown("### Book New Appointment")
            with st.form("book_appt_form", clear_on_submit=True):
                b1, b2 = st.columns(2)
                with b1:
                    sel_pid = st.selectbox("Patient", list(pat_map.keys()), format_func=lambda k: pat_map[k], index=0)
                    sel_did = st.selectbox("Doctor", list(doc_map.keys()), format_func=lambda k: doc_map[k], index=0)
                    sel_dept = st.selectbox("Department", list(dept_map.keys()), format_func=lambda k: dept_map[k], index=0)
                with b2:
                    sel_date = st.date_input("Appointment Date")
                    sel_time = st.time_input("Appointment Time", value=None)
                    sel_reason = st.text_area("Reason / Notes", height=80)
                book_submit = st.form_submit_button("Book Appointment", type="primary")
                if book_submit:
                    try:
                        from app.core.appointments import book_appointment, appointment_conflict_exists
                        t_str = sel_time.strftime("%H:%M") if sel_time else ""
                        conflict = appointment_conflict_exists(conn, int(sel_did), str(sel_date), t_str)
                        if conflict:
                            st.error("❌ Time conflict — this doctor already has an appointment at that slot.")
                        else:
                            result = book_appointment(
                                conn, user,
                                patient_id=int(sel_pid),
                                doctor_id=int(sel_did),
                                dept_id=int(sel_dept),
                                appt_date=str(sel_date),
                                appt_time=t_str,
                                reason=sel_reason or "",
                            )
                            st.success(f"✅ Appointment #{result['id']} booked for {result['appointment_date']} {result['appointment_time']}")
                    except Exception as e:
                        st.error(f"Booking failed: {e}")

        with tab3:
            st.markdown("### Reschedule or Cancel")
            active_appts = [a for a in list_appointments(conn, user, limit=200)
                            if a.get("status") not in ("Cancelled", "Completed")]
            if not active_appts:
                st.info("No active appointments to reschedule/cancel.")
            else:
                adf = pd.DataFrame(active_appts)
                adf["label"] = "#" + adf["id"].astype(str) + " — " + adf["patient_code"] + " on " + adf["appointment_date"] + " " + adf["appointment_time"]
                sel_id = st.selectbox("Select Appointment", list(adf["id"].values),
                                      format_func=lambda i: adf.loc[adf["id"] == i, "label"].iloc[0], index=0)
                action = st.radio("Action", ["Reschedule", "Cancel"], horizontal=True)

                if action == "Reschedule":
                    with st.form("resched_form", clear_on_submit=False):
                        r1, r2 = st.columns(2)
                        with r1:
                            nd = st.date_input("New Date")
                        with r2:
                            nt = st.time_input("New Time", value=None)
                        rs = st.form_submit_button("Reschedule", type="primary")
                        if rs:
                            try:
                                from app.core.appointments import reschedule_appointment
                                nt_str = nt.strftime("%H:%M") if nt else ""
                                reschedule_appointment(conn, user, int(sel_id), str(nd), nt_str)
                                st.success("✅ Appointment rescheduled.")
                                st.rerun()
                            except Exception as e:
                                st.error(f"Reschedule failed: {e}")
                else:
                    with st.form("cancel_form"):
                        reason = st.text_area("Cancellation Reason (optional)")
                        cs = st.form_submit_button("Cancel Appointment", type="primary")
                        if cs:
                            try:
                                from app.core.appointments import cancel_appointment
                                cancel_appointment(conn, user, int(sel_id), reason)
                                st.success("✅ Appointment cancelled.")
                                st.rerun()
                            except Exception as e:
                                st.error(f"Cancel failed: {e}")
except Exception as e:
    st.error(f"Appointments page error: {e}")
