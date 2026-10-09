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

st.title("🤝 Handover & Tasks")
disclaimer_banner()

try:
    with get_db() as conn:
        depts = conn.execute("SELECT id, name FROM departments ORDER BY name").fetchall()
        dept_map = {int(r["id"]): r["name"] for r in depts}
        users = conn.execute("SELECT id, full_name, role, department_id FROM users WHERE role IN ('Admin','Doctor','Nurse') ORDER BY full_name").fetchall()
        user_map = {int(r["id"]): f"{r['full_name']} ({r['role']})" for r in users}
        shifts = conn.execute("SELECT id, shift_name, start_time, end_time FROM shifts ORDER BY id").fetchall()
        shift_map = {int(r["id"]): f"{r['shift_name']} ({r['start_time']}-{r['end_time']})" for r in shifts}

        from app.core.handover import list_notes, list_tasks
        notes = list_notes(conn, user, limit=200)
        tasks = list_tasks(conn, user, limit=300)
        unread_h = sum(1 for n in notes if not n.get("is_read"))
        open_t = sum(1 for t in tasks if t.get("status") != "Done")
        from app.utils.ui import metric_card
        k1, k2, k3 = st.columns(3)
        with k1: metric_card("Unread Handovers", unread_h, icon="📝", variant="warn")
        with k2: metric_card("Open Tasks", open_t, icon="✅", variant="info")
        with k3: metric_card("Total Handovers", len(notes), icon="🤝", variant="info")

        tab1, tab2, tab3, tab4 = st.tabs(["📝 Handovers List", "➕ Create Handover Note", "📋 Tasks List", "➕ Create Task"])

        with tab1:
            st.markdown("### Handover Notes")
            c1, c2 = st.columns(2)
            with c1:
                fd = st.selectbox("Department", [0] + list(dept_map.keys()),
                                  format_func=lambda k: "All" if k == 0 else dept_map[k], index=0, key="hd1")
            with c2:
                only_un = st.checkbox("Only Unread", value=False)
            f_notes = notes
            if fd != 0:
                f_notes = [n for n in f_notes if int(n.get("department_id") or 0) == int(fd)]
            if only_un:
                f_notes = [n for n in f_notes if not n.get("is_read")]
            ndf = pd.DataFrame(f_notes)
            if len(ndf):
                ndf["from_staff"] = ndf["from_staff_id"].map(user_map).fillna("?")
                ndf["to_staff"] = ndf["to_staff_id"].map(user_map).fillna("?")
                ndf["dept"] = ndf["department_id"].map(dept_map).fillna("?")
                ndf["shift"] = ndf["shift_id"].map(shift_map).fillna("?")
                ndf["read_badge"] = ndf["is_read"].apply(
                    lambda r: status_badge("Completed") if r else status_badge("Pending"))
                show = ["id", "from_staff", "to_staff", "dept", "shift", "note_text", "read_badge", "created_at"]
                show = [c for c in show if c in ndf.columns]
                st.dataframe(ndf[show], use_container_width=True, hide_index=True)
                if st.button("📖 Mark All as Read"):
                    from app.core.handover import mark_note_read
                    for n in f_notes:
                        try:
                            mark_note_read(conn, user, int(n["id"]))
                        except Exception:
                            pass
                    st.success("✅ All notes marked as read.")
                    st.rerun()
            else:
                st.info("No handover notes.")

        with tab2:
            st.markdown("### Create Handover Note")
            with st.form("handover_form", clear_on_submit=True):
                h1, h2 = st.columns(2)
                with h1:
                    hto = st.selectbox("To Staff Member", list(user_map.keys()), format_func=lambda k: user_map[k], index=0)
                    hsh = st.selectbox("Shift", list(shift_map.keys()), format_func=lambda k: shift_map[k], index=0 if shift_map else 0)
                    hd = st.selectbox("Department", list(dept_map.keys()), format_func=lambda k: dept_map[k], index=0)
                with h2:
                    hnote = st.text_area("Handover Note *", height=160)
                hsub = st.form_submit_button("Send Handover", type="primary")
                if hsub:
                    if not hnote or not shift_map:
                        st.error("Handover note and shift are required.")
                    else:
                        try:
                            from app.core.handover import create_note
                            r = create_note(conn, user, int(hto), int(hsh), int(hd), hnote)
                            st.success(f"✅ Handover note #{r['id']} sent.")
                            st.rerun()
                        except Exception as e:
                            st.error(f"Failed to create handover: {e}")

        with tab3:
            st.markdown("### Tasks List")
            t1, t2, t3 = st.columns(3)
            with t1:
                ts = st.selectbox("Status", ["", "Pending", "InProgress", "Blocked", "Done", "Cancelled"], index=0)
            with t2:
                tp = st.selectbox("Priority", ["", "High", "Medium", "Low"], index=0)
            with t3:
                tass = st.selectbox("Assignee", [0] + list(user_map.keys()),
                                    format_func=lambda k: "All" if k == 0 else user_map[k], index=0, key="tass")
            ft = tasks
            if ts:
                ft = [t for t in ft if str(t.get("status", "")) == ts]
            if tp:
                ft = [t for t in ft if str(t.get("priority", "")) == tp]
            if tass != 0:
                ft = [t for t in ft if int(t.get("assignee_id") or 0) == int(tass)]
            tdf = pd.DataFrame(ft)
            if len(tdf):
                tdf["assignee"] = tdf["assignee_id"].map(user_map).fillna("?")
                tdf["creator"] = tdf["creator_id"].map(user_map).fillna("?")
                tdf["dept"] = tdf["department_id"].map(dept_map).fillna("—")
                show = ["id", "title", "description", "priority", "status", "assignee", "creator", "dept", "due_at"]
                show = [c for c in show if c in tdf.columns]
                dtf = tdf[show].copy()
                dtf["priority"] = dtf["priority"].apply(lambda s: status_badge(str(s)))
                dtf["status"] = dtf["status"].apply(lambda s: status_badge(str(s)))
                st.markdown(dtf.to_html(escape=False, index=False), unsafe_allow_html=True)
                csv_download(tdf, "tasks.csv", "📥 Download Tasks CSV")
            else:
                st.info("No tasks matching criteria.")

        with tab4:
            st.markdown("### Create Task")
            with st.form("task_form", clear_on_submit=True):
                tk1, tk2 = st.columns(2)
                with tk1:
                    ttitle = st.text_input("Task Title *")
                    tass2 = st.selectbox("Assignee *", list(user_map.keys()), format_func=lambda k: user_map[k], index=0)
                    tpri = st.selectbox("Priority", ["High", "Medium", "Low"], index=1)
                    tdept = st.selectbox("Department (optional)", [0] + list(dept_map.keys()),
                                         format_func=lambda k: "None" if k == 0 else dept_map[k], index=0)
                with tk2:
                    tdesc = st.text_area("Description", height=110)
                    import datetime as _dt
                    tdue_d = st.date_input("Due Date (optional)", value=None)
                    tdue_t = st.time_input("Due Time (optional)", value=None)
                tsub = st.form_submit_button("Create Task", type="primary")
                if tsub:
                    if not ttitle:
                        st.error("Task title is required.")
                    else:
                        try:
                            due_iso = None
                            if tdue_d:
                                dt = pd.Timestamp(str(tdue_d))
                                if tdue_t:
                                    dt = dt + pd.Timedelta(hours=tdue_t.hour, minutes=tdue_t.minute)
                                due_iso = dt.strftime("%Y-%m-%d %H:%M:%S")
                            from app.core.handover import create_task
                            r = create_task(conn, user, ttitle, int(tass2),
                                            priority=tpri, description=tdesc or "",
                                            due_at=due_iso,
                                            dept_id=(None if tdept == 0 else int(tdept)))
                            st.success(f"✅ Task #{r['id']} created: {r['title']}")
                            st.rerun()
                        except Exception as e:
                            st.error(f"Failed to create task: {e}")
except Exception as e:
    st.error(f"Handover & Tasks page error: {e}")
