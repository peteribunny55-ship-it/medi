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
    page_title="My Records — Medi",
    page_icon="📋",
    layout="wide",
)

from app.utils.ui import (
    apply_custom_css,
    disclaimer_banner,
    role_header,
    status_badge,
    page_requires_role,
    metric_card,
)
from app.db.database import get_db
from app.core.auth import get_patient_user_link
from app.core.patients import get_patient_visit_history
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

        prow = conn.execute(
            "SELECT * FROM patients WHERE id=?", (pid,)
        ).fetchone()
        if not prow:
            st.error("Patient record not found.")
            st.stop()

        st.markdown("### 📋 My Patient Records")

        st.markdown("---")
        st.markdown("#### 👤 Patient Demographics")
        d1, d2 = st.columns(2)
        with d1:
            st.write(f"**Patient ID:** {prow['patient_id']}  \n"
                     f"**Full Name:** {prow['first_name']} {prow['last_name']}  \n"
                     f"**Date of Birth:** {prow['dob'] or '—'}  \n"
                     f"**Gender:** {prow['gender'] or '—'}")
        with d2:
            st.write(f"**Phone:** {prow['phone'] or '—'}  \n"
                     f"**Email:** {prow['email'] or '—'}  \n"
                     f"**Address:** {prow['address'] or '—'}  \n"
                     f"**Emergency Contact:** {prow['emergency_contact'] or '—'}")

        st.caption("🔒 Protected Health Information (PHI) view — capped summary. Full records require clinician authorization.")

        history = get_patient_visit_history(conn, user, pid)
        appts = history.get("appointments", [])
        admissions = history.get("admissions", [])
        lab_reqs = history.get("lab_requests", [])

        k1, k2, k3, k4 = st.columns(4)
        with k1:
            metric_card("Total Visits", len(appts), icon="🏥")
        with k2:
            metric_card("Admissions", len(admissions), icon="🛏️", variant="info")
        with k3:
            metric_card("Lab Requests", len(lab_reqs), icon="🧪", variant="info")
        with k4:
            confirmed = [a for a in appts if a["status"] in ("Completed", "Confirmed")]
            metric_card("Completed Visits", len(confirmed), icon="✅", variant="occup")

        tab_timeline, tab_appts, tab_adm, tab_lab, tab_export = st.tabs([
            "🕒 Visit Timeline", "📅 Appointments", "🏥 Admissions", "🧪 Lab Requests", "📤 Export CSV"
        ])

        with tab_timeline:
            timeline_items = []
            for a in appts:
                timeline_items.append({
                    "Date": a["appointment_date"],
                    "Type": "Appointment",
                    "Details": f"{a.get('dept_name','')} — {a.get('doctor_name','')}",
                    "Status": a["status"],
                    "Notes": a.get("reason", "") or "",
                })
            for adm in admissions:
                timeline_items.append({
                    "Date": (adm.get("admitted_at", "") or "")[:10],
                    "Type": "Admission",
                    "Details": f"{adm.get('dept_name','')} — Bed {adm.get('bed_no','')}",
                    "Status": adm["status"],
                    "Notes": adm.get("diagnosis", "") or "",
                })
            for lab in lab_reqs:
                timeline_items.append({
                    "Date": (lab.get("ordered_at", "") or "")[:10],
                    "Type": "Lab Request",
                    "Details": f"{lab['test_type']} ({lab.get('test_category','')})",
                    "Status": lab["status"],
                    "Notes": lab.get("result_note", "") or "",
                })
            timeline_items.sort(key=lambda x: x["Date"] or "", reverse=True)
            capped = timeline_items[:50]
            if timeline_items:
                tl_df = pd.DataFrame(capped)
                tl_df["Status"] = tl_df["Status"].apply(lambda s: status_badge(str(s)))
                st.markdown(tl_df.to_html(escape=False, index=False), unsafe_allow_html=True)
                if len(timeline_items) > 50:
                    st.info(f"Showing 50 of {len(timeline_items)} timeline entries. Use the Export tab for the full record.")
            else:
                st.info("No visit history available yet.")

        with tab_appts:
            if appts:
                adf = pd.DataFrame([{
                    "Date": a["appointment_date"],
                    "Time": a["appointment_time"],
                    "Department": a.get("dept_name", ""),
                    "Doctor": a.get("doctor_name", ""),
                    "Reason": a.get("reason", "") or "—",
                    "Status": status_badge(a["status"]),
                } for a in appts])
                st.markdown(adf.to_html(escape=False, index=False), unsafe_allow_html=True)
            else:
                st.info("No appointment records.")

        with tab_adm:
            if admissions:
                admdf = pd.DataFrame([{
                    "Admitted": (a.get("admitted_at", "") or "")[:16],
                    "Discharged": (a.get("discharged_at", "") or "—")[:16] if a.get("discharged_at") else "—",
                    "Department": a.get("dept_name", ""),
                    "Bed / Ward": f"{a.get('bed_no','')} ({a.get('ward','')})",
                    "Type": a.get("admission_type", ""),
                    "Diagnosis": (a.get("diagnosis", "") or "")[:80] + ("…" if a.get("diagnosis") and len(a["diagnosis"]) > 80 else ""),
                    "Status": status_badge(a["status"]),
                } for a in admissions])
                st.markdown(admdf.to_html(escape=False, index=False), unsafe_allow_html=True)
                st.caption("Diagnosis field capped at 80 chars for PHI-safe summary view.")
            else:
                st.info("No admission records.")

        with tab_lab:
            if lab_reqs:
                ldf = pd.DataFrame([{
                    "Ordered At": (l.get("ordered_at", "") or "")[:16],
                    "Test Type": l["test_type"],
                    "Category": l.get("test_category", "") or "—",
                    "Priority": status_badge(l.get("priority", "")),
                    "Ordered By": l.get("ordered_by_name", "") or "—",
                    "Resulted": (l.get("resulted_at", "") or "—")[:16] if l.get("resulted_at") else "—",
                    "Status": status_badge(l["status"]),
                    "Notes": (l.get("result_note", "") or "")[:60] + ("…" if l.get("result_note") and len(l["result_note"]) > 60 else ""),
                } for l in lab_reqs])
                st.markdown(ldf.to_html(escape=False, index=False), unsafe_allow_html=True)
                st.caption("Result notes capped at 60 chars. Full lab reports require authorized access.")
            else:
                st.info("No lab request records.")

        with tab_export:
            st.markdown("#### 📤 Export Patient Records (CSV)")
            export_all = []
            for a in appts:
                export_all.append({
                    "Record Type": "Appointment",
                    "Date": a["appointment_date"],
                    "Time": a["appointment_time"],
                    "Department": a.get("dept_name", ""),
                    "Doctor/Staff": a.get("doctor_name", ""),
                    "Status": a["status"],
                    "Details/Reason": a.get("reason", "") or "",
                })
            for adm in admissions:
                export_all.append({
                    "Record Type": "Admission",
                    "Date": (adm.get("admitted_at", "") or "")[:10],
                    "Time": "",
                    "Department": adm.get("dept_name", ""),
                    "Doctor/Staff": "",
                    "Status": adm["status"],
                    "Details/Reason": adm.get("diagnosis", "") or "",
                })
            for lab in lab_reqs:
                export_all.append({
                    "Record Type": "Lab Request",
                    "Date": (lab.get("ordered_at", "") or "")[:10],
                    "Time": "",
                    "Department": "",
                    "Doctor/Staff": lab.get("ordered_by_name", "") or "",
                    "Status": lab["status"],
                    "Details/Reason": f"{lab['test_type']} ({lab.get('test_category','')})",
                })
            if export_all:
                exdf = pd.DataFrame(export_all)
                csv_download(exdf, f"my_records_{dt.date.today()}.csv", "📥 Download Full Records CSV")

            demo_export = pd.DataFrame([{
                "Patient ID": prow["patient_id"],
                "First Name": prow["first_name"],
                "Last Name": prow["last_name"],
                "DOB": prow["dob"] or "",
                "Gender": prow["gender"] or "",
                "Phone": prow["phone"] or "",
                "Email": prow["email"] or "",
                "Registered At": prow.get("created_at", ""),
            }])
            st.markdown("---")
            csv_download(demo_export, f"my_demographics_{dt.date.today()}.csv", "📥 Download Demographics CSV", key="demo_csv")

except Exception as e:
    st.error(f"Page error: {e}")
