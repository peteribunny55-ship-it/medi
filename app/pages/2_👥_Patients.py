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

st.title("👥 Patients Management")
disclaimer_banner()

try:
    with get_db() as conn:
        depts = conn.execute("SELECT id, name FROM departments ORDER BY name").fetchall()
        dept_options = {0: "All Departments"} | {int(r["id"]): r["name"] for r in depts}

        tab1, tab2 = st.tabs(["🔍 Search Patients", "➕ Register New Patient"])

        with tab1:
            st.markdown("### Patient Search")
            col1, col2, col3, col4 = st.columns(4)
            with col1:
                search_query = st.text_input("Search (name/ID/phone/email)", "")
            with col2:
                filter_dept = st.selectbox("Department", list(dept_options.keys()),
                                           format_func=lambda k: dept_options[k], index=0)
            with col3:
                date_from = st.date_input("Registered From", value=None)
            with col4:
                date_to = st.date_input("Registered To", value=None)

            from app.core.patients import search_patients

            df_val = None
            with st.spinner("Searching patients…"):
                results = search_patients(
                    conn, user,
                    query=search_query or "",
                    dept_id=(None if filter_dept == 0 else int(filter_dept)),
                    date_from=str(date_from) if date_from else None,
                    date_to=str(date_to) if date_to else None,
                    limit=500,
                )
                df_val = pd.DataFrame(results)

            if len(df_val):
                show_cols = ["patient_id", "first_name", "last_name", "dob", "gender",
                             "phone", "email", "created_at"]
                show_cols = [c for c in show_cols if c in df_val.columns]
                st.dataframe(df_val[show_cols], use_container_width=True, hide_index=True)
                csv_download(df_val, "patients_search.csv", "📥 Download Patient List CSV")
            else:
                st.info("No patients found matching criteria.")

        with tab2:
            st.markdown("### Register New Patient")
            with st.form("register_patient_form", clear_on_submit=True):
                c1, c2 = st.columns(2)
                with c1:
                    first_name = st.text_input("First Name *")
                    last_name = st.text_input("Last Name *")
                    dob = st.date_input("Date of Birth", value=None)
                    gender = st.selectbox("Gender", ["", "Male", "Female", "Other"])
                    phone = st.text_input("Phone")
                with c2:
                    email = st.text_input("Email")
                    address = st.text_area("Address", height=80)
                    ec = st.text_input("Emergency Contact")
                submitted = st.form_submit_button("Register Patient", type="primary")
                if submitted:
                    if not first_name or not last_name:
                        st.error("First name and last name are required.")
                    else:
                        try:
                            from app.core.patients import create_patient
                            patient = create_patient(
                                conn, user,
                                first_name=first_name.strip(),
                                last_name=last_name.strip(),
                                dob=str(dob) if dob else None,
                                gender=gender or None,
                                phone=phone or None,
                                email=email or None,
                                address=address or None,
                                emergency_contact=ec or None,
                            )
                            st.success(f"✅ Patient registered: ID {patient['patient_id']} — {patient['first_name']} {patient['last_name']}")
                        except Exception as e:
                            st.error(f"Failed to register patient: {e}")
except Exception as e:
    st.error(f"Patients page error: {e}")
