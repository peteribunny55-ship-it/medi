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

user = page_requires_role(["Admin", "Nurse", "Doctor"])
apply_custom_css()

st.title("🔢 Queue Management")
disclaimer_banner()

try:
    with get_db() as conn:
        depts = conn.execute("SELECT id, name FROM departments ORDER BY name").fetchall()
        dept_map = {0: "All Departments"} | {int(r["id"]): r["name"] for r in depts}

        k1, k2, k3 = st.columns(3)
        total_wait = conn.execute("SELECT COUNT(*) FROM queue_tokens WHERE status='Waiting'").fetchone()[0]
        total_called = conn.execute("SELECT COUNT(*) FROM queue_tokens WHERE status IN ('Called','InProgress')").fetchone()[0]
        total_done = conn.execute("SELECT COUNT(*) FROM queue_tokens WHERE date(created_at)=date('now') AND status='Completed'").fetchone()[0]
        from app.utils.ui import metric_card
        with k1: metric_card("Waiting", total_wait, icon="⏳", variant="warn")
        with k2: metric_card("Called / In Progress", total_called, icon="📞", variant="info")
        with k3: metric_card("Served Today", total_done, icon="✅", variant="occup")

        st.markdown("---")
        tab1, tab2 = st.tabs(["📊 Live Queue", "📞 Call Next Patient"])

        with tab1:
            c1, c2 = st.columns(2)
            with c1:
                q_dept = st.selectbox("Department Filter", list(dept_map.keys()),
                                      format_func=lambda k: dept_map[k], index=0)
            with c2:
                q_status = st.multiselect("Status Filter",
                                          ["Waiting", "Called", "InProgress", "Completed", "Cancelled"],
                                          default=["Waiting", "Called", "InProgress"])

            where = ["1=1"]
            params = []
            if q_dept != 0:
                where.append("qt.department_id = ?")
                params.append(int(q_dept))
            if q_status:
                placeholders = ",".join("?" for _ in q_status)
                where.append(f"qt.status IN ({placeholders})")
                params.extend(q_status)

            rows = conn.execute(
                f"""SELECT qt.*, p.first_name, p.last_name, p.patient_id AS patient_code,
                           d.name AS dept_name
                    FROM queue_tokens qt
                    LEFT JOIN patients p ON p.id = qt.patient_id
                    LEFT JOIN departments d ON d.id = qt.department_id
                    WHERE {" AND ".join(where)}
                    ORDER BY qt.department_id, qt.created_at LIMIT 300""",
                params,
            ).fetchall()
            qdf = pd.DataFrame([dict(r) for r in rows])
            if len(qdf):
                qdf["token"] = qdf["prefix"] + "-" + qdf["token_no"].astype(str)
                qdf["patient"] = qdf["first_name"].fillna("") + " " + qdf["last_name"].fillna("")
                from app.core.queue import compute_wait_estimate
                qdf["_dept_id"] = qdf["department_id"].fillna(0).astype(int)
                eta_vals = []
                for i, r in qdf.iterrows():
                    if r["status"] == "Waiting":
                        try:
                            eta = compute_wait_estimate(conn, int(r["_dept_id"]), include_self=False)
                        except Exception:
                            eta = 0
                    else:
                        eta = r.get("estimated_wait_minutes", 0) or 0
                    eta_vals.append(eta)
                qdf["ETA_min"] = eta_vals
                qdf["Estimate"] = qdf["ETA_min"].apply(
                    lambda m: f'<span class="live-badge {"sim" if m else "live"}">~{int(m)} min</span>' if m else '<span class="live-badge live">Now</span>')

                show = ["token", "dept_name", "patient_code", "patient", "status", "Estimate", "estimated_wait_minutes", "created_at"]
                show = [c for c in show if c in qdf.columns]
                dfs = qdf[show].copy()
                dfs["status"] = dfs["status"].apply(lambda s: status_badge(str(s)))
                st.markdown(dfs.to_html(escape=False, index=False), unsafe_allow_html=True)
                csv_download(qdf, "queue.csv", "📥 Download Queue CSV")
            else:
                st.info("No queue entries.")

        with tab2:
            st.markdown("### Call Next Patient")
            call_dept = st.selectbox("Select Department to Call Next",
                                     [k for k in dept_map.keys() if k != 0],
                                     format_func=lambda k: dept_map[k], index=0)
            if st.button("📞 Call Next in Queue", type="primary", use_container_width=True):
                try:
                    from app.core.queue import call_next_patient
                    called = call_next_patient(conn, user, int(call_dept))
                    st.success(f"✅ Called: {called['prefix']}-{called['token_no']} (patient id {called['patient_id']})")
                except Exception as e:
                    st.error(f"Call next failed: {e}")

            st.markdown("#### Department ETA Overview")
            eta_rows = []
            for d in depts:
                did = int(d["id"])
                waiting_count = conn.execute(
                    "SELECT COUNT(*) FROM queue_tokens WHERE department_id=? AND status='Waiting'", (did,)).fetchone()[0]
                try:
                    from app.core.queue import compute_wait_estimate
                    eta = compute_wait_estimate(conn, did)
                except Exception:
                    eta = 0
                eta_rows.append({"Department": d["name"], "Waiting": waiting_count, "ETA_min": eta})
            edf = pd.DataFrame(eta_rows)
            edf["ETA Estimate"] = edf["ETA_min"].apply(lambda m: f'<span class="live-badge sim">~{int(m)} min</span>' if m else '<span class="live-badge live">—</span>')
            st.markdown(edf[["Department", "Waiting", "ETA Estimate"]].to_html(escape=False, index=False), unsafe_allow_html=True)
except Exception as e:
    st.error(f"Queue page error: {e}")
