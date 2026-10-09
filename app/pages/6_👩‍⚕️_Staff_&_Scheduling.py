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

user = page_requires_role(["Admin"])
apply_custom_css()

st.title("👩‍⚕️ Staff & Scheduling")
disclaimer_banner()

try:
    with get_db() as conn:
        depts = conn.execute("SELECT id, name FROM departments ORDER BY name").fetchall()
        dept_map = {int(r["id"]): r["name"] for r in depts}

        tab1, tab2 = st.tabs(["👥 Staff Roster", "📅 Weekly Schedule"])

        with tab1:
            from app.core.staff_scheduling import list_staff
            staff = list_staff(conn)
            sdf = pd.DataFrame(staff)
            if len(sdf):
                if "user_department_id" in sdf.columns:
                    sdf["department_name"] = sdf["user_department_id"].map(dept_map).fillna(sdf["department_id"].map(dept_map).fillna("—"))
                show_cols = ["id", "full_name", "username", "user_role", "email", "department_name", "weekly_hours_limit", "user_created_at"]
                show_cols = [c for c in show_cols if c in sdf.columns]
                st.dataframe(sdf[show_cols], use_container_width=True, hide_index=True)
                csv_download(sdf, "staff.csv", "📥 Download Staff CSV")
            else:
                st.info("No staff records.")

        with tab2:
            st.markdown("### Generate Weekly Schedule")
            import datetime as _dt
            today = _dt.date.today()
            monday = today - _dt.timedelta(days=today.weekday())
            ws = st.date_input("Week Starting (Monday)", value=monday)
            st.caption("Status badge: Recommended = AI-generated; requires human approval before publishing.")

            if st.button("✨ Generate Weekly Schedule", type="primary"):
                try:
                    from app.core.staff_scheduling import generate_weekly_schedule
                    inserted, method = generate_weekly_schedule(conn, user, str(ws))
                    st.success(f"✅ Generated {len(inserted)} assignments via {method}.  <span class='live-badge sim'>RECOMMENDED</span>", unsafe_allow_html=True)
                except Exception as e:
                    st.error(f"Schedule generation failed: {e}")

            st.markdown("#### View Existing Schedules")
            v1, v2 = st.columns(2)
            with v1:
                v_dept = st.selectbox("Filter Department", [0] + list(dept_map.keys()),
                                      format_func=lambda k: "All" if k == 0 else dept_map[k], index=0, key="vsd")
            with v2:
                v_status = st.selectbox("Filter Status", ["", "Recommended", "Approved", "Published"], index=0, key="vss")
            sql = """SELECT sc.id, sc.schedule_date, sc.status, sc.staff_id, sc.department_id,
                            u.full_name AS staff_name, d.name AS dept_name,
                            sh.shift_name, sh.start_time, sh.end_time
                     FROM schedules sc
                     LEFT JOIN staff st ON st.id = sc.staff_id
                     LEFT JOIN users u ON u.id = st.user_id
                     LEFT JOIN departments d ON d.id = sc.department_id
                     LEFT JOIN shifts sh ON sh.id = sc.shift_id
                     WHERE sc.schedule_date >= ? AND sc.schedule_date < date(?,'+7 days')"""
            params = [str(ws), str(ws)]
            if v_dept != 0:
                sql += " AND sc.department_id = ?"
                params.append(int(v_dept))
            if v_status:
                sql += " AND sc.status = ?"
                params.append(v_status)
            sql += " ORDER BY sc.schedule_date, sh.start_time, u.full_name LIMIT 1000"
            rows = conn.execute(sql, params).fetchall()
            schdf = pd.DataFrame([dict(r) for r in rows])
            if len(schdf):
                def _badge_row(s):
                    badge = status_badge(str(s))
                    if s == "Recommended":
                        badge += ' <span class="live-badge sim">Recommended</span>'
                    return badge
                schdf["status"] = schdf["status"].apply(_badge_row)
                show = ["id", "schedule_date", "shift_name", "start_time", "end_time", "staff_name", "dept_name", "status"]
                show = [c for c in show if c in schdf.columns]
                st.markdown(schdf[show].to_html(escape=False, index=False), unsafe_allow_html=True)
                csv_download(schdf, "schedules.csv", "📥 Download Schedule CSV")
            else:
                st.info("No schedule records for selected week. Generate one to begin.")
except Exception as e:
    st.error(f"Staff scheduling page error: {e}")
