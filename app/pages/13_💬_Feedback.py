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

st.title("💬 Feedback")
disclaimer_banner()

try:
    with get_db() as conn:
        depts = conn.execute("SELECT id, name FROM departments ORDER BY name").fetchall()
        dept_map = {int(r["id"]): r["name"] for r in depts}
        users = conn.execute("SELECT id, full_name FROM users WHERE role IN ('Admin','Doctor','Nurse') ORDER BY full_name").fetchall()
        user_map = {int(r["id"]): r["full_name"] for r in users}

        from app.core.feedback import list_feedback, summary_stats
        all_fb = list_feedback(conn, user, limit=500)
        stats = summary_stats(conn)
        k1, k2, k3 = st.columns(3)
        from app.utils.ui import metric_card
        with k1: metric_card("Total Feedback", stats.get("total", 0), icon="💬", variant="info")
        with k2: metric_card("Open", stats.get("by_status", {}).get("Open", 0), icon="⏳", variant="warn")
        with k3: metric_card("Resolved", stats.get("by_status", {}).get("Resolved", 0), icon="✅", variant="occup")

        is_patient = user.get("role") == "Patient"
        show_submit = is_patient or (user.get("role") in ("Admin", "Doctor", "Nurse"))
        tabs_list = ["📋 Feedback List"]
        if show_submit:
            tabs_list.append("➕ Submit Feedback")
        if user.get("role") == "Admin":
            tabs_list.append("✅ Resolve Feedback")
        tabs = st.tabs(tabs_list)

        with tabs[0]:
            st.markdown("### Feedback List")
            c1, c2, c3 = st.columns(3)
            with c1:
                fcat = st.selectbox("Category", [
                    "", "Wait times", "Staff behavior", "Cleanliness", "Care Quality",
                    "Billing", "Facilities", "Communication", "Other"
                ], index=0)
            with c2:
                fs = st.selectbox("Status", ["", "Open", "InProgress", "Resolved", "Closed"], index=0)
            with c3:
                fd = st.selectbox("Department", [0] + list(dept_map.keys()),
                                  format_func=lambda k: "All" if k == 0 else dept_map[k], index=0)
            ff = list_feedback(conn, user,
                               category=(fcat or None), status=(fs or None),
                               dept_id=(None if fd == 0 else int(fd)), limit=500)
            fdf = pd.DataFrame(ff)
            if len(fdf):
                fdf["dept"] = fdf["department_id"].map(dept_map).fillna("—")
                fdf["assignee"] = fdf["assignee_id"].map(user_map).fillna("—")
                fdf["anon_badge"] = fdf["is_anonymous"].apply(lambda a: "Yes" if int(a or 0) else "No")
                show = ["id", "category", "dept", "subject", "description", "status", "assignee", "anon_badge", "submitted_at"]
                show = [c for c in show if c in fdf.columns]
                dfs = fdf[show].copy()
                dfs["status"] = dfs["status"].apply(lambda s: status_badge(str(s)))
                st.markdown(dfs.to_html(escape=False, index=False), unsafe_allow_html=True)
                csv_download(fdf, "feedback.csv", "📥 Download Feedback CSV")
            else:
                st.info("No feedback matching criteria.")

        if len(tabs) > 1 and "➕ Submit Feedback" in tabs_list:
            with tabs[tabs_list.index("➕ Submit Feedback")]:
                st.markdown("### Submit Feedback")
                is_anon = False
                pat_id = None
                if is_patient:
                    from app.core.auth import get_patient_user_link
                    pat_id = get_patient_user_link(conn, int(user["id"]))
                with st.form("fb_submit", clear_on_submit=True):
                    f1, f2 = st.columns(2)
                    with f1:
                        if not is_patient:
                            is_anon = st.checkbox("Submit Anonymously", value=False)
                        cat = st.selectbox("Category", [
                            "Wait times", "Staff behavior", "Cleanliness", "Care Quality",
                            "Billing", "Facilities", "Communication", "Other"
                        ], index=0)
                        dept_fb = st.selectbox("Department (optional)", [0] + list(dept_map.keys()),
                                               format_func=lambda k: "None" if k == 0 else dept_map[k], index=0)
                    with f2:
                        subj = st.text_input("Subject *")
                    desc = st.text_area("Description * (detailed feedback)", height=120)
                    sbm = st.form_submit_button("Submit Feedback", type="primary")
                    if sbm:
                        if not subj or not desc:
                            st.error("Subject and description are required.")
                        else:
                            try:
                                from app.core.feedback import submit_feedback
                                r = submit_feedback(
                                    conn, user,
                                    patient_id=pat_id,
                                    is_anonymous=(is_anon or False),
                                    category=cat,
                                    dept_id=(None if dept_fb == 0 else int(dept_fb)),
                                    subject=subj,
                                    description=desc,
                                )
                                st.success(f"✅ Feedback #{r['id']} submitted. Thank you!")
                            except Exception as e:
                                st.error(f"Failed to submit feedback: {e}")

        if user.get("role") == "Admin":
            with tabs[tabs_list.index("✅ Resolve Feedback")]:
                st.markdown("### Resolve Feedback (Admin Only)")
                open_fb = [f for f in all_fb if str(f.get("status", "")) != "Resolved"]
                if not open_fb:
                    st.info("No open feedback to resolve.")
                else:
                    odf = pd.DataFrame(open_fb)
                    odf["label"] = "#" + odf["id"].astype(str) + " [" + odf["status"].fillna("Open") + "] " + odf["subject"]
                    sel_f = st.selectbox("Select Feedback", list(odf["id"].values),
                                         format_func=lambda i: odf.loc[odf["id"] == i, "label"].iloc[0], index=0)
                    assignee = st.selectbox("Assign To (optional)", [0] + list(user_map.keys()),
                                            format_func=lambda k: "None" if k == 0 else user_map[k], index=0)
                    res_note = st.text_area("Resolution Notes", height=100)
                    if st.button("Mark as Resolved", type="primary"):
                        try:
                            from app.core.feedback import resolve_feedback
                            resolve_feedback(conn, user, int(sel_f), res_note or "",
                                             assignee_id=(None if assignee == 0 else int(assignee)))
                            st.success(f"✅ Feedback #{sel_f} resolved.")
                            st.rerun()
                        except Exception as e:
                            st.error(f"Resolve failed: {e}")
                    st.markdown("#### Current Open Feedback")
                    if "subject" in odf.columns:
                        dfs2 = odf[["id", "category", "subject", "status", "submitted_at"]].copy()
                        dfs2["status"] = dfs2["status"].apply(lambda s: status_badge(str(s)))
                        st.markdown(dfs2.to_html(escape=False, index=False), unsafe_allow_html=True)
except Exception as e:
    st.error(f"Feedback page error: {e}")
