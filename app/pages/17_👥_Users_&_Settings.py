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

st.title("👥 Users & Settings")
disclaimer_banner()

try:
    with get_db() as conn:
        depts = conn.execute("SELECT id, name FROM departments ORDER BY name").fetchall()
        dept_map = {int(r["id"]): r["name"] for r in depts}

        from app.core.auth import list_users
        users = list_users(conn)
        udf = pd.DataFrame(users)
        k1, k2, k3 = st.columns(3)
        from app.utils.ui import metric_card
        with k1: metric_card("Total Users", len(udf), icon="👥", variant="info")
        with k2:
            role_counts = udf["role"].value_counts() if "role" in udf.columns else pd.Series()
            metric_card("Admins", role_counts.get("Admin", 0), icon="🏥", variant="alert")
        with k3:
            metric_card("Clinical Roles",
                        role_counts.get("Doctor", 0) + role_counts.get("Nurse", 0),
                        icon="👩‍⚕️", variant="occup")

        tab1, tab2, tab3 = st.tabs(["📋 Users List", "➕ Create User", "🔐 Change Password"])

        with tab1:
            st.markdown("### Users")
            if len(udf):
                udf["department"] = udf["department_id"].map(dept_map).fillna("—")
                show = ["id", "username", "full_name", "role", "email", "department", "created_at"]
                show = [c for c in show if c in udf.columns]
                dfs = udf[show].copy()
                dfs["role"] = dfs["role"].apply(lambda s: status_badge(str(s)))
                st.markdown(dfs.to_html(escape=False, index=False), unsafe_allow_html=True)
                csv_download(udf, "users.csv", "📥 Download Users CSV")
            else:
                st.info("No users found.")

        with tab2:
            st.markdown("### Create New User")
            roles_list = ["Admin", "Doctor", "Nurse", "Patient", "InventoryManager"]
            with st.form("create_user_form", clear_on_submit=True):
                u1, u2 = st.columns(2)
                with u1:
                    uname = st.text_input("Username *")
                    fname = st.text_input("Full Name *")
                    email = st.text_input("Email")
                with u2:
                    pwd = st.text_input("Password * (min 6 chars)", type="password")
                    role = st.selectbox("Role *", roles_list, index=0)
                    dpt = st.selectbox("Department (optional)", [0] + list(dept_map.keys()),
                                       format_func=lambda k: "None" if k == 0 else dept_map[k], index=0)
                submit = st.form_submit_button("Create User", type="primary")
                if submit:
                    if not uname or not pwd or not fname:
                        st.error("Username, password, and full name are required.")
                    else:
                        try:
                            from app.core.auth import create_user
                            new_id = create_user(
                                conn,
                                username=uname.strip(),
                                password=pwd,
                                role=role,
                                full_name=fname.strip(),
                                email=email or None,
                                department_id=(None if dpt == 0 else int(dpt)),
                                actor_id=int(user["id"]),
                            )
                            st.success(f"✅ User #{new_id} created: {uname} ({role})")
                        except Exception as e:
                            st.error(f"User creation failed: {e}")

        with tab3:
            st.markdown("### Change User Password")
            cu1, cu2 = st.columns(2)
            with cu1:
                target_id = st.selectbox("Select User", list(udf["id"].values) if len(udf) else [0],
                                         format_func=lambda i: udf.loc[udf["id"] == i, "username"].iloc[0] +
                                                               f" ({udf.loc[udf['id'] == i, 'full_name'].iloc[0]})"
                                         if len(udf) and i in udf["id"].values else "No users",
                                         index=0)
                admin_check = st.checkbox("Admin override (skip old password)", value=True,
                                          help="Admin can change any user's password without the old one.")
            with cu2:
                old_pw = st.text_input("Current Password (required if not admin override)", type="password", disabled=admin_check)
                new_pw = st.text_input("New Password *", type="password")
                confirm_pw = st.text_input("Confirm New Password *", type="password")
            if st.button("Change Password", type="primary"):
                if not new_pw or len(new_pw) < 6:
                    st.error("New password must be at least 6 characters.")
                elif new_pw != confirm_pw:
                    st.error("New password and confirmation do not match.")
                else:
                    try:
                        if admin_check:
                            from app.core.auth import hash_password
                            conn.execute("UPDATE users SET password_hash=? WHERE id=?",
                                         (hash_password(new_pw), int(target_id)))
                            st.success("✅ Password updated via admin override.")
                        else:
                            from app.core.auth import change_password
                            ok = change_password(conn, int(target_id), old_pw, new_pw)
                            if ok:
                                st.success("✅ Password changed.")
                            else:
                                st.error("❌ Old password incorrect.")
                        conn.commit()
                    except Exception as e:
                        st.error(f"Password change failed: {e}")
except Exception as e:
    st.error(f"Users & settings page error: {e}")
