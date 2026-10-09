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

user = page_requires_role(["Admin"])
apply_custom_css()

st.title("📜 Audit Log Viewer")
disclaimer_banner()

try:
    with get_db() as conn:
        users_rows = conn.execute("SELECT id, username, full_name, role FROM users ORDER BY username").fetchall()
        user_map = {int(r["id"]): f"{r['username']} — {r['full_name']} ({r['role']})" for r in users_rows}

        actions = conn.execute("SELECT DISTINCT action FROM audit_logs ORDER BY action LIMIT 50").fetchall()
        entities = conn.execute("SELECT DISTINCT entity_type FROM audit_logs ORDER BY entity_type LIMIT 50").fetchall()
        action_list = [""] + [r["action"] for r in actions if r["action"]]
        entity_list = [""] + [r["entity_type"] for r in entities if r["entity_type"]]

        st.markdown("### Filters")
        c1, c2, c3, c4 = st.columns(4)
        with c1:
            actor_ids = [0] + list(user_map.keys())
            fa = st.selectbox("Actor (User)", actor_ids,
                              format_func=lambda k: "All" if k == 0 else user_map[k], index=0)
        with c2:
            faction = st.selectbox("Action", action_list, index=0)
        with c3:
            fentity = st.selectbox("Entity Type", entity_list, index=0)
        with c4:
            today = pd.Timestamp.now().to_pydatetime()
            dff = st.date_input("Date From", value=(today - pd.Timedelta(days=30)))
        c5, c6 = st.columns(2)
        with c5:
            dtt = st.date_input("Date To", value=today)
        with c6:
            lim = st.selectbox("Max Rows", [100, 500, 1000, 5000], index=1)

        from app.core.audit import list_audit_logs
        logs = list_audit_logs(
            conn,
            actor_id=(None if fa == 0 else int(fa)),
            action=(faction or None),
            entity_type=(fentity or None),
            date_from=str(dff),
            date_to=str(dtt),
            limit=int(lim),
        )
        ldf = pd.DataFrame(logs)
        if len(ldf):
            ldf["actor"] = ldf["actor_id"].map(user_map).fillna(
                "System (" + ldf["actor_role"].fillna("?").astype(str) + ")")
            ldf["detail_preview"] = ldf["detail_json"].apply(
                lambda j: (str(j)[:200] if j else "")
            )
            show = ["id", "created_at", "actor", "actor_role", "action", "entity_type", "entity_id", "detail_preview"]
            show = [c for c in show if c in ldf.columns]
            st.dataframe(ldf[show], use_container_width=True, hide_index=True)
            csv_download(ldf, "audit_log.csv", "📥 Download Audit Log CSV")
            k1, k2, k3, k4 = st.columns(4)
            from app.utils.ui import metric_card
            with k1: metric_card("Total Entries", len(ldf), icon="📜", variant="info")
            with k2:
                top_act = ldf["action"].value_counts().head(1)
                metric_card("Top Action", f"{top_act.index[0]} ({top_act.values[0]})" if len(top_act) else "—", icon="🎯", variant="occup")
            with k3:
                top_ent = ldf["entity_type"].value_counts().head(1)
                metric_card("Top Entity", f"{top_ent.index[0]} ({top_ent.values[0]})" if len(top_ent) else "—", icon="🏷️", variant="warn")
            with k4:
                unique_actors = ldf["actor_id"].nunique()
                metric_card("Unique Actors", unique_actors, icon="👤", variant="info")
        else:
            st.info("No audit log entries match the selected filters.")
except Exception as e:
    st.error(f"Audit log page error: {e}")
