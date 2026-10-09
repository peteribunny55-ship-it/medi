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

user = page_requires_role(["Admin", "Doctor", "Nurse", "InventoryManager"])
apply_custom_css()

st.title("📊 Reports Center")
disclaimer_banner()

try:
    with get_db() as conn:
        depts = conn.execute("SELECT id, name FROM departments ORDER BY name").fetchall()
        dept_map = {0: "All Departments"} | {int(r["id"]): r["name"] for r in depts}

        st.markdown("### Report Filters")
        f1, f2, f3 = st.columns(3)
        import datetime as _dt
        today = _dt.date.today()
        default_from = today - _dt.timedelta(days=30)
        with f1:
            df_r = st.date_input("Date From", value=default_from)
        with f2:
            dt_r = st.date_input("Date To", value=today)
        with f3:
            d_r = st.selectbox("Department", list(dept_map.keys()),
                               format_func=lambda k: dept_map[k], index=0)
        dept_id_r = None if d_r == 0 else int(d_r)
        date_from_s = str(df_r)
        date_to_s = str(dt_r)

        from app.core.reports import (
            build_patients_registrations_report,
            build_appointments_report,
            build_waiting_time_trends_report,
            build_bed_utilization_report,
            build_staff_workload_report,
            build_or_utilization_report,
            build_inventory_alerts_report,
            build_emergency_demand_report,
            build_feedback_report,
            build_lab_tat_report,
            build_audit_log_report,
        )

        report_list = [
            ("Patient Registrations", build_patients_registrations_report, "patients_registrations.csv", "👥"),
            ("Appointments", build_appointments_report, "appointments.csv", "📅"),
            ("Waiting Times Trends", build_waiting_time_trends_report, "waiting_times.csv", "⏳"),
            ("Bed Utilization", build_bed_utilization_report, "bed_utilization.csv", "🛏️"),
            ("Staff Workload", build_staff_workload_report, "staff_workload.csv", "👩‍⚕️"),
            ("OR Utilization", build_or_utilization_report, "or_utilization.csv", "🏥"),
            ("Inventory Alerts", build_inventory_alerts_report, "inventory_alerts.csv", "💊"),
            ("Emergency Demand", build_emergency_demand_report, "emergency_demand.csv", "🚨"),
            ("Feedback Summary", build_feedback_report, "feedback_report.csv", "💬"),
            ("Lab Turnaround Time", build_lab_tat_report, "lab_tat.csv", "🧪"),
            ("Audit Log Report", build_audit_log_report, "audit_log.csv", "📜"),
        ]

        tabs = st.tabs([f"{i} {n}" for n, _, _, i in report_list])

        for idx, (rname, builder, fname, _ic) in enumerate(report_list):
            with tabs[idx]:
                st.markdown(f"### {rname} Report")
                st.caption(f"Filters: {date_from_s} → {date_to_s} | {dept_map[d_r]}")
                try:
                    df = builder(conn, date_from_s, date_to_s, dept_id_r)
                    if len(df):
                        st.dataframe(df, use_container_width=True, hide_index=True)
                        csv_download(df, fname, f"📥 Download {rname} CSV", key=f"rep_{idx}")
                        st.markdown("**Summary:**")
                        sc1, sc2, sc3 = st.columns(3)
                        with sc1:
                            from app.utils.ui import metric_card
                            metric_card("Rows", len(df), icon="📏", variant="info")
                        with sc2:
                            num_cols = df.select_dtypes(include="number").columns
                            if len(num_cols):
                                metric_card(f"Sum: {num_cols[0]}",
                                            f"{df[num_cols[0]].sum():,.0f}", icon="➕", variant="occup")
                        with sc3:
                            if len(num_cols) > 1:
                                metric_card(f"Avg: {num_cols[1]}",
                                            f"{df[num_cols[1]].mean():,.1f}", icon="📈", variant="warn")
                    else:
                        st.info("No data for selected filters. Expand date range or try a different department.")
                        try:
                            df_empty = builder(conn, None, None, None)
                            if len(df_empty):
                                csv_download(df_empty, fname, f"📥 Full {rname} CSV (all-time)", key=f"rep_full_{idx}")
                        except Exception:
                            pass
                except Exception as ee:
                    st.error(f"Report generation error: {ee}")
except Exception as e:
    st.error(f"Reports page error: {e}")
