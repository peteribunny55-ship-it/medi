from __future__ import annotations

import os
import sys

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

import datetime as dt
import pandas as pd
import streamlit as st

st.set_page_config(
    page_title="My Appointments — Medi",
    page_icon="🩺",
    layout="wide",
)

from app.utils.ui import (
    apply_custom_css,
    disclaimer_banner,
    role_header,
    status_badge,
    page_requires_role,
    live_vs_sim_badge,
)
from app.db.database import get_db
from app.core.auth import get_patient_user_link
from app.core.appointments import (
    book_appointment,
    list_appointments,
    cancel_appointment,
    appointment_conflict_exists,
)
from app.utils.exporters import csv_download

apply_custom_css()

user = page_requires_role(["Patient"])
role_header()
disclaimer_banner()

try:
    with get_db() as conn:
        pid = get_patient_user_link(conn, int(user["id"]))
        if not pid:
            st.warning("Your account is not linked to a patient record. Please contact administration.")
            st.stop()

        today_str = dt.date.today().strftime("%Y-%m-%d")

        st.markdown("### 🩺 My Appointments")

        all_appts = list_appointments(conn, user, patient_id=pid)
        upcoming = [a for a in all_appts if a["appointment_date"] >= today_str and a["status"] != "Cancelled"]
        past = [a for a in all_appts if a["appointment_date"] < today_str or a["status"] == "Cancelled"]

        k1, k2, k3 = st.columns(3)
        with k1:
            st.metric("Total Appointments", len(all_appts))
        with k2:
            st.metric("Upcoming", len(upcoming))
        with k3:
            st.metric("Past / Cancelled", len(past))

        tab_up, tab_past, tab_book = st.tabs(["📅 Upcoming", "📜 Past & Cancelled", "➕ Book New"])

        with tab_up:
            if upcoming:
                up_df = pd.DataFrame([{
                    "ID": a["id"],
                    "Date": a["appointment_date"],
                    "Time": a["appointment_time"],
                    "Department": a.get("dept_name", ""),
                    "Doctor": a.get("doctor_name", ""),
                    "Reason": a.get("reason", ""),
                    "Status": status_badge(a["status"]),
                } for a in upcoming])
                st.markdown(up_df.to_html(escape=False, index=False), unsafe_allow_html=True)

                st.markdown("#### ❌ Cancel Appointment")
                with st.form("cancel_form"):
                    cancel_ids = [f"{a['id']} — {a['appointment_date']} {a['appointment_time']} ({a.get('dept_name','')})"
                                  for a in upcoming if a["status"] not in ("Completed", "Cancelled")]
                    if cancel_ids:
                        sel = st.selectbox("Select appointment to cancel", cancel_ids)
                        cancel_reason = st.text_input("Cancellation reason (optional)", "")
                        sub_cancel = st.form_submit_button("Cancel Appointment", type="secondary")
                        if sub_cancel:
                            try:
                                appt_id_cancel = int(sel.split("—")[0].strip())
                                cancel_appointment(conn, user, appt_id_cancel, cancel_reason)
                                st.success("✅ Appointment cancelled successfully.")
                                st.rerun()
                            except Exception as ce:
                                st.error(f"Failed to cancel: {ce}")
                    else:
                        st.info("No cancellable upcoming appointments.")
                        st.form_submit_button("Cancel Appointment", disabled=True)
            else:
                st.info("No upcoming appointments.")

        with tab_past:
            if past:
                past_df = pd.DataFrame([{
                    "Date": a["appointment_date"],
                    "Time": a["appointment_time"],
                    "Department": a.get("dept_name", ""),
                    "Doctor": a.get("doctor_name", ""),
                    "Reason": a.get("reason", ""),
                    "Status": status_badge(a["status"]),
                } for a in past])
                st.markdown(past_df.to_html(escape=False, index=False), unsafe_allow_html=True)
            else:
                st.info("No past appointments.")

            st.markdown("---")
            if all_appts:
                export_df = pd.DataFrame([{
                    "Appointment ID": a["id"],
                    "Date": a["appointment_date"],
                    "Time": a["appointment_time"],
                    "Department": a.get("dept_name", ""),
                    "Doctor": a.get("doctor_name", ""),
                    "Reason": a.get("reason", ""),
                    "Status": a["status"],
                    "Created At": a.get("created_at", ""),
                    "Cancelled At": a.get("cancelled_at", ""),
                } for a in all_appts])
                csv_download(export_df, f"my_appointments_{dt.date.today()}.csv", "📥 Download All Appointments CSV")

        with tab_book:
            st.markdown(f"#### Book New Appointment {live_vs_sim_badge(True, 'SCHEDULE')}")
            dept_rows = conn.execute("SELECT id, name FROM departments ORDER BY name").fetchall()
            dept_options = {d["name"]: int(d["id"]) for d in dept_rows}

            with st.form("book_appt_form"):
                c1, c2 = st.columns(2)
                with c1:
                    dept_name = st.selectbox("Department", sorted(dept_options.keys()))
                    dept_id = dept_options[dept_name]
                with c2:
                    doc_rows = conn.execute(
                        """SELECT doc.id, u.full_name, doc.specialization
                           FROM doctors doc JOIN users u ON u.id=doc.user_id
                           WHERE doc.department_id=? ORDER BY u.full_name""",
                        (dept_id,),
                    ).fetchall()
                    doc_options = {f"{d['full_name']} — {d.get('specialization','')}": int(d["id"]) for d in doc_rows}
                    if not doc_options:
                        st.info("No doctors available in this department.")
                    doctor_sel = st.selectbox("Doctor", list(doc_options.keys()) if doc_options else ["—"])
                    doctor_id = doc_options[doctor_sel] if doc_options else None

                c3, c4 = st.columns(2)
                with c3:
                    min_date = dt.date.today()
                    appt_date = st.date_input("Appointment Date", min_value=min_date, value=min_date)
                with c4:
                    time_slots = [f"{h:02d}:{m:02d}" for h in range(8, 18) for m in (0, 30)]
                    appt_time = st.selectbox("Appointment Time", time_slots)

                reason = st.text_area("Reason for visit", height=80, placeholder="E.g. Follow-up checkup, headache, annual physical")
                submitted = st.form_submit_button("📅 Book Appointment", type="primary", use_container_width=True)

                if submitted:
                    if not doctor_id:
                        st.error("Please select a valid department with available doctors.")
                    else:
                        try:
                            conflict = appointment_conflict_exists(
                                conn, doctor_id, appt_date.strftime("%Y-%m-%d"), appt_time
                            )
                            if conflict:
                                st.error("❌ Conflict: This doctor already has an appointment at the selected date/time. Please choose another slot.")
                            else:
                                result = book_appointment(
                                    conn,
                                    user=user,
                                    patient_id=pid,
                                    doctor_id=doctor_id,
                                    dept_id=dept_id,
                                    appt_date=appt_date.strftime("%Y-%m-%d"),
                                    appt_time=appt_time,
                                    reason=reason,
                                )
                                st.success(f"✅ Appointment #{result['id']} booked successfully! Date: {result['appointment_date']} Time: {result['appointment_time']}")
                                st.rerun()
                        except Exception as be:
                            st.error(f"Booking failed: {be}")

except Exception as e:
    st.error(f"Page error: {e}")
