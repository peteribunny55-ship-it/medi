from __future__ import annotations

import os
import sys

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

import pandas as pd
import streamlit as st

st.set_page_config(
    page_title="My Queue — Medi",
    page_icon="⏳",
    layout="wide",
)

from app.utils.ui import (
    apply_custom_css,
    disclaimer_banner,
    role_header,
    status_badge,
    page_requires_role,
    live_vs_sim_badge,
    metric_card,
)
from app.db.database import get_db
from app.core.auth import get_patient_user_link
from app.core.queue import (
    patient_queue_position,
    compute_wait_estimate,
)

apply_custom_css()

user = page_requires_role(["Patient"])
role_header()
disclaimer_banner()

try:
    with get_db() as conn:
        pid = get_patient_user_link(conn, int(user["id"]))
        if not pid:
            st.warning("Your account is not linked to a patient record. Please contact administration.")
            st.stop()

        st.markdown("### ⏳ My Queue Status")

        positions = patient_queue_position(conn, pid)
        active_tokens = [p for p in positions if p["token"]["status"] in ("Waiting", "Called", "InProgress")]

        k1, k2 = st.columns(2)
        with k1:
            metric_card("Active Queue Tokens", len(active_tokens), icon="🎫")
        with k2:
            waiting_only = [p for p in active_tokens if p["token"]["status"] == "Waiting"]
            metric_card("Currently Waiting", len(waiting_only), icon="⏱️", variant="warn")

        if not active_tokens:
            st.info("You have no active queue tokens. Book an appointment to receive a queue token.")
        else:
            for pos_info in active_tokens:
                tok = pos_info["token"]
                dept = pos_info["dept"]
                pos = pos_info["position"]

                st.markdown("---")
                tc1, tc2, tc3 = st.columns([1.2, 1.5, 1.3])
                with tc1:
                    token_display = f"{tok['prefix']}-{tok['token_no']:03d}"
                    st.markdown(
                        f"""
                        <div style="background:linear-gradient(135deg,#0B2545,#1B4079);color:#fff;border-radius:14px;padding:22px;text-align:center;">
                          <div style="font-size:.85rem;opacity:.8;">TOKEN NUMBER</div>
                          <div style="font-size:2.6rem;font-weight:800;letter-spacing:2px;margin:6px 0;">{token_display}</div>
                          <div style="font-size:.9rem;opacity:.9;">{dept.get("name","") or '—'}</div>
                        </div>
                        """,
                        unsafe_allow_html=True,
                    )
                with tc2:
                    st.markdown(f"**Department:** {dept.get('name','')}  \n"
                                f"**Floor:** {dept.get('floor','N/A')}  \n"
                                f"**Status:** {status_badge(tok['status'])}  \n"
                                f"**Current Position:** **#{pos}** in queue")
                with tc3:
                    est_minutes = compute_wait_estimate(
                        conn,
                        int(tok["department_id"]),
                        patient_position_ahead=max(0, pos - 1),
                    )
                    st.markdown(
                        f"""
                        <div style="border:2px solid #F59E0B;border-radius:14px;padding:18px;background:#FFFBEB;">
                          <div style="font-size:.8rem;color:#92400E;font-weight:600;">ESTIMATED WAIT {live_vs_sim_badge(True,'ESTIMATE')}</div>
                          <div style="font-size:2.4rem;font-weight:800;color:#92400E;margin:8px 0;">{est_minutes} <span style="font-size:1.1rem;font-weight:500;">MINUTES</span></div>
                          <div style="font-size:.8rem;color:#78350F;">Approx. {max(0, pos - 1)} patient(s) ahead × dept avg service time</div>
                        </div>
                        """,
                        unsafe_allow_html=True,
                    )

            st.markdown("---")
            st.markdown("#### 📋 All Active Tokens Summary")
            summary_rows = []
            for pos_info in active_tokens:
                tok = pos_info["token"]
                dept = pos_info["dept"]
                pos = pos_info["position"]
                est = compute_wait_estimate(conn, int(tok["department_id"]), patient_position_ahead=max(0, pos - 1))
                summary_rows.append({
                    "Token": f"{tok['prefix']}-{tok['token_no']:03d}",
                    "Department": dept.get("name", ""),
                    "Status": status_badge(tok["status"]),
                    "Position": f"#{pos}",
                    "Est. Wait (min)": f"{est} min {live_vs_sim_badge(True,'EST')}",
                    "Created At": tok.get("created_at", ""),
                })
            if summary_rows:
                sdf = pd.DataFrame(summary_rows)
                st.markdown(sdf.to_html(escape=False, index=False), unsafe_allow_html=True)

            hist_tokens = conn.execute(
                """SELECT qt.*, d.name AS dept_name
                   FROM queue_tokens qt JOIN departments d ON d.id=qt.department_id
                   WHERE qt.patient_id=? AND qt.status NOT IN ('Waiting','Called','InProgress')
                   ORDER BY qt.id DESC LIMIT 20""",
                (pid,),
            ).fetchall()
            if hist_tokens:
                st.markdown("#### 📜 Queue History (last 20)")
                hrows = []
                for h in hist_tokens:
                    hrows.append({
                        "Token": f"{h['prefix']}-{h['token_no']:03d}",
                        "Department": h["dept_name"],
                        "Status": status_badge(h["status"]),
                        "Est. Wait (min)": h["estimated_wait_minutes"],
                        "Called At": h.get("called_at", "") or "—",
                        "Completed At": h.get("completed_at", "") or "—",
                    })
                hdf = pd.DataFrame(hrows)
                st.markdown(hdf.to_html(escape=False, index=False), unsafe_allow_html=True)

except Exception as e:
    st.error(f"Page error: {e}")
