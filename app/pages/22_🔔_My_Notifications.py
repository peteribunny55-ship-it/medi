from __future__ import annotations

import os
import sys

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

import json
import pandas as pd
import streamlit as st

from app.utils.ui import page_requires_role, apply_custom_css, disclaimer_banner, status_badge
from app.utils.exporters import csv_download
from app.db.database import get_db

user = page_requires_role(["Admin", "Doctor", "Nurse", "Patient", "InventoryManager"])
apply_custom_css()

st.title("🔔 My Notifications")
disclaimer_banner()

try:
    with get_db() as conn:
        uid = int(user["id"])

        from app.core.notifications import list_for_user, unread_count, mark_read
        unread = unread_count(conn, uid)
        total_notifs = len(list_for_user(conn, uid, limit=1000))
        k1, k2 = st.columns(2)
        from app.utils.ui import metric_card
        with k1: metric_card("Unread", unread, icon="🔔", variant="warn")
        with k2: metric_card("Total (last 1000)", total_notifs, icon="📬", variant="info")

        tab1, tab2 = st.tabs(["📬 All Notifications", "⭐ Unread Only"])

        def _render(notif_rows, tab_key):
            if not len(notif_rows):
                st.info("No notifications in this view.")
                return
            ndf = pd.DataFrame(notif_rows)
            ndf["type_badge"] = ndf["type"].apply(lambda t: status_badge(str(t).title()))
            ndf["read_badge"] = ndf["is_read"].apply(
                lambda r: status_badge("Completed") if int(r or 0) else status_badge("Pending"))
            show_cols = ["id", "type_badge", "title", "message", "read_badge", "created_at"]
            show_cols = [c for c in show_cols if c in ndf.columns]
            dfs = ndf[show_cols].copy()
            st.dataframe(dfs, use_container_width=True, hide_index=True)

            st.markdown("#### Batch Actions")
            b1, b2 = st.columns(2)
            with b1:
                unread_now = [n for n in notif_rows if not int(n.get("is_read") or 0)]
                if st.button("📖 Mark All Shown As Read", key=f"mr_all_{tab_key}") and len(unread_now):
                    for n in unread_now:
                        try:
                            mark_read(conn, uid, int(n["id"]))
                        except Exception:
                            pass
                    st.success("✅ Marked all notifications in view as read.")
                    st.rerun()
            with b2:
                csv_download(ndf, "notifications.csv", "📥 Download Notifications CSV", key=f"csv_{tab_key}")

            st.markdown("#### Individual Actions")
            sel_id = st.selectbox("Select a notification to view details / mark read",
                                  list(ndf["id"].values),
                                  format_func=lambda i: f"#{i} — {ndf.loc[ndf['id'] == i, 'title'].iloc[0]}",
                                  index=0,
                                  key=f"sel_{tab_key}")
            sel_row = next(n for n in notif_rows if int(n["id"]) == int(sel_id))
            with st.expander(f"Notification Details #{sel_id}", expanded=True):
                st.write(f"**Type:** {sel_row.get('type', '')}")
                st.write(f"**Title:** {sel_row.get('title', '')}")
                st.write(f"**Message:** {sel_row.get('message', '')}")
                st.write(f"**Received:** {sel_row.get('created_at', '')}")
                try:
                    data = json.loads(sel_row.get("data_json") or "{}")
                    if data:
                        st.write("**Payload:**")
                        st.json(data)
                except Exception:
                    pass
                if not int(sel_row.get("is_read") or 0):
                    if st.button("Mark This Read", key=f"m1_{tab_key}_{sel_id}", type="primary"):
                        mark_read(conn, uid, int(sel_id))
                        st.success("✅ Marked as read.")
                        st.rerun()

        with tab1:
            all_n = list_for_user(conn, uid, unread_only=False, limit=500)
            _render(all_n, "all")

        with tab2:
            un_n = list_for_user(conn, uid, unread_only=True, limit=500)
            _render(un_n, "unread")
except Exception as e:
    st.error(f"Notifications page error: {e}")
