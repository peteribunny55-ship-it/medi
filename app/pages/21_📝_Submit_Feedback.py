from __future__ import annotations

import os
import sys

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

import pandas as pd
import streamlit as st

st.set_page_config(
    page_title="Submit Feedback — Medi",
    page_icon="📝",
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
from app.core.feedback import submit_feedback, list_feedback

apply_custom_css()

user = page_requires_role(["Patient"])
role_header()
disclaimer_banner()

FEEDBACK_CATEGORIES = [
    "Waiting Time",
    "Doctor Attitude",
    "Nurse Care",
    "Cleanliness",
    "Food Quality",
    "Billing",
    "Communication",
    "Facilities",
    "Pain Management",
    "Discharge Process",
]

try:
    with get_db() as conn:
        pid = get_patient_user_link(conn, int(user["id"]))
        if not pid:
            st.warning("Your account is not linked to a patient record. Please contact administration.")
            st.stop()

        st.markdown("### 📝 Submit Feedback")

        my_feedback = list_feedback(conn, user, limit=100)
        my_own = [f for f in my_feedback if (not f.get("is_anonymous") and f.get("patient_id") == pid) or f.get("patient_id") == pid]

        k1, k2, k3 = st.columns(3)
        with k1:
            metric_card("Total Submissions", len(my_own), icon="📨")
        with k2:
            open_count = len([f for f in my_own if f["status"] == "Open"])
            metric_card("Open / Pending", open_count, icon="⏳", variant="warn")
        with k3:
            resolved_count = len([f for f in my_own if f["status"] == "Resolved"])
            metric_card("Resolved", resolved_count, icon="✅", variant="occup")

        tab_submit, tab_history = st.tabs(["✍️ Submit New Feedback", "📜 My Submissions"])

        with tab_submit:
            st.info("💡 Your feedback helps us improve hospital services. All submissions are reviewed by the Quality Assurance team.")

            dept_rows = conn.execute("SELECT id, name FROM departments ORDER BY name").fetchall()
            dept_map = {d["name"]: int(d["id"]) for d in dept_rows}
            dept_names = sorted(dept_map.keys())

            with st.form("feedback_form", clear_on_submit=True):
                c1, c2 = st.columns(2)
                with c1:
                    category = st.selectbox("Category", FEEDBACK_CATEGORIES)
                with c2:
                    dept_choice = st.selectbox("Department (optional)", ["— Not specific —"] + dept_names)
                    dept_id = dept_map[dept_choice] if dept_choice != "— Not specific —" else None

                subject = st.text_input("Subject / Title", max_chars=200, placeholder="Brief summary of your feedback")
                description = st.text_area(
                    "Detailed Description",
                    height=180,
                    max_chars=5000,
                    placeholder="Please share your experience, specific incidents, suggestions for improvement, or any concerns. Include relevant dates, locations, or staff names when possible.",
                )
                is_anonymous = st.checkbox("Submit anonymously (your identity will not be stored with this feedback)", value=False)

                submitted = st.form_submit_button("📤 Submit Feedback", type="primary", use_container_width=True)

                if submitted:
                    if not subject.strip():
                        st.error("❌ Subject is required.")
                    elif len(description.strip()) < 10:
                        st.error("❌ Please provide a more detailed description (at least 10 characters).")
                    else:
                        try:
                            result = submit_feedback(
                                conn,
                                user=user,
                                patient_id=pid if not is_anonymous else None,
                                is_anonymous=bool(is_anonymous),
                                category=category,
                                dept_id=dept_id,
                                subject=subject.strip(),
                                description=description.strip(),
                            )
                            st.success(
                                f"✅ Feedback #{result['id']} submitted successfully! "
                                f"{'Thank you for your anonymous submission.' if is_anonymous else 'We will review and respond as appropriate.'}"
                            )
                            try:
                                from app.core.notifications import push_notification
                                admin_rows = conn.execute("SELECT id FROM users WHERE role='Admin'").fetchall()
                                for ar in admin_rows:
                                    push_notification(
                                        conn,
                                        user_id=int(ar["id"]),
                                        type="feedback",
                                        title="New Patient Feedback",
                                        message=f"Category: {category} | Subject: {subject[:80]}",
                                        data_dict={"feedback_id": int(result["id"])},
                                    )
                            except Exception:
                                pass
                        except Exception as fe:
                            st.error(f"❌ Failed to submit feedback: {fe}")

        with tab_history:
            if my_own:
                hdf = pd.DataFrame([{
                    "ID": f["id"],
                    "Submitted": (f.get("submitted_at", "") or "")[:16],
                    "Category": f.get("category", "") or "—",
                    "Subject": f.get("subject", ""),
                    "Status": status_badge(f["status"]),
                    "Resolved": (f.get("resolved_at", "") or "")[:16] if f.get("resolved_at") else "—",
                } for f in my_own])
                st.markdown(hdf.to_html(escape=False, index=False), unsafe_allow_html=True)

                if st.checkbox("Show submission details", value=False, key="fb_details_toggle"):
                    for f in my_own:
                        with st.expander(f"#{f['id']} — {f.get('subject','')} ({(f.get('submitted_at','') or '')[:10]})"):
                            sd1, sd2 = st.columns(2)
                            with sd1:
                                st.write(f"**Category:** {f.get('category','') or '—'}  \n"
                                         f"**Status:** {f['status']}  \n"
                                         f"**Anonymous:** {'Yes' if f.get('is_anonymous') else 'No'}")
                            with sd2:
                                st.write(f"**Submitted:** {f.get('submitted_at','') or '—'}  \n"
                                         f"**Resolved At:** {f.get('resolved_at','') or '—'}  \n"
                                         f"**Resolution:** {f.get('resolution_notes','') or '—'}")
                            st.markdown("**Description:**")
                            st.write(f.get("description", "") or "—")
            else:
                st.info("No feedback submissions yet from your account.")

except Exception as e:
    st.error(f"Page error: {e}")
