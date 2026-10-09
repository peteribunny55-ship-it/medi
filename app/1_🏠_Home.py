from __future__ import annotations

import os
import sys

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

import pandas as pd
import streamlit as st

st.set_page_config(
    page_title="Medi — Hospital Resource Optimization System",
    page_icon="🏥",
    layout="wide",
    initial_sidebar_state="expanded",
)

from app.utils.ui import (
    apply_custom_css,
    disclaimer_banner,
    role_header,
    metric_card,
    status_badge,
    logout_btn,
    notification_bell,
    get_session,
    live_vs_sim_badge,
)
from app.db.database import get_db, init_db
from app.db.seed import seed_all
from app.core.auth import authenticate
from app.config import DEMO_USERS

apply_custom_css()

with get_db() as _conn:
    init_db(_conn)
    try:
        seed_all(_conn, force=False)
    except Exception:
        pass


def _login_page() -> None:
    disclaimer_banner()
    st.markdown(
        """
        <div style="text-align:center;margin-top:30px;">
          <div style="font-size:3.2rem;">🏥</div>
          <h1 style="color:#0B2545;margin:8px 0 2px 0;">Hospital Resource Optimization System</h1>
          <p style="color:#6B7280;margin-bottom:28px;">AI-powered operations, scheduling, forecasting &amp; analytics</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    cols = st.columns([1.2, 1, 1.2])
    with cols[1]:
        with st.form("login_form", clear_on_submit=False):
            st.subheader("🔐 Sign In")
            username = st.text_input("Username", value="admin", placeholder="admin / doctor / nurse / patient / inventory")
            password = st.text_input("Password", type="password", value="admin123", placeholder="admin123 / doctor123 / etc.")
            submitted = st.form_submit_button("Sign In", type="primary", use_container_width=True)
            if submitted:
                with get_db() as conn:
                    user = authenticate(conn, username, password)
                if user:
                    st.session_state["user"] = user
                    st.success(f"✅ Welcome, {user['full_name']}! Redirecting…")
                    st.rerun()
                else:
                    st.error("❌ Invalid username or password. Try the demo accounts below.")

    st.markdown("---")
    st.subheader("🗝 Demo Accounts")
    demo_rows = []
    for u in DEMO_USERS:
        demo_rows.append({
            "Role": u["role"],
            "Username": u["username"],
            "Password": u["password"],
            "Full Name": u["full_name"],
        })
    st.table(pd.DataFrame(demo_rows))
    st.caption("Demo system account directory.")


def _admin_dashboard(user) -> None:
    role_header()
    disclaimer_banner()
    try:
        with get_db() as conn:
            beds_count = conn.execute("SELECT COUNT(*) FROM beds").fetchone()[0]
            occ_count = conn.execute("SELECT COUNT(*) FROM beds WHERE status='Occupied'").fetchone()[0]
            avail_count = beds_count - occ_count
            today = pd.Timestamp.now().strftime("%Y-%m-%d")
            today_appts = conn.execute(
                "SELECT COUNT(*) FROM appointments WHERE appointment_date = ?", (today,)
            ).fetchone()[0]
            waiting_tokens = conn.execute(
                "SELECT COUNT(*) FROM queue_tokens WHERE status='Waiting'"
            ).fetchone()[0]
            active_staff = conn.execute(
                "SELECT COUNT(DISTINCT u.id) FROM users u WHERE u.role IN ('Doctor','Nurse')"
            ).fetchone()[0]
            low_stock = conn.execute(
                "SELECT COUNT(*) FROM inventory_items WHERE quantity <= reorder_threshold"
            ).fetchone()[0]
            active_em = conn.execute(
                "SELECT COUNT(*) FROM admissions WHERE admission_type='Emergency' AND status != 'Discharged'"
            ).fetchone()[0]

            from app.core.beds import utilization_summary
            from app.core.queue import list_tokens
            from app.ai.forecast import build_demand_history, train_forecast_model
            from app.core.emergency import surge_alert

            k1, k2, k3, k4 = st.columns(4)
            with k1: metric_card("Total Beds", beds_count, icon="🛏️", variant="info")
            with k2: metric_card("Occupied", occ_count, icon="🔴", variant="alert")
            with k3: metric_card("Available", avail_count, icon="✅", variant="occup")
            with k4: metric_card("Today's Appointments", today_appts, icon="📅", variant="info")

            k5, k6, k7, k8 = st.columns(4)
            with k5: metric_card("Queue Waiting", waiting_tokens, icon="⏳", variant="warn")
            with k6: metric_card("Active Clinical Staff", active_staff, icon="👩‍⚕️", variant="info")
            with k7: metric_card("Low-Stock Items", low_stock, icon="⚠️", variant="alert")
            with k8: metric_card("Active Emergencies", active_em, icon="🚨", variant="alert")

            tab1, tab2, tab3, tab4 = st.tabs(["📊 Department KPIs", "🤖 AI Forecast", "🚨 Emergency & Alerts", "💡 AI Recommendations"])
            with tab1:
                try:
                    import plotly.express as px
                    rows = conn.execute(
                        """SELECT d.name AS dept,
                                  SUM(CASE WHEN b.status='Occupied' THEN 1 ELSE 0 END) AS occupied,
                                  SUM(CASE WHEN b.status='Available' THEN 1 ELSE 0 END) AS available
                           FROM departments d LEFT JOIN beds b ON b.department_id = d.id
                           GROUP BY d.id ORDER BY d.name"""
                    ).fetchall()
                    df = pd.DataFrame([dict(r) for r in rows])
                    if len(df):
                        fig = px.bar(df, x="dept", y=["occupied", "available"],
                                     title="Bed Utilization by Department",
                                     color_discrete_sequence=["#1B4079", "#14B8A6"],
                                     barmode="stack")
                        fig.update_layout(xaxis_title="", yaxis_title="Beds", legend_title="Status")
                        st.plotly_chart(fig, use_container_width=True)
                    appt_rows = conn.execute(
                        """SELECT d.name AS dept, COUNT(a.id) AS cnt
                           FROM departments d LEFT JOIN appointments a
                             ON a.department_id = d.id AND a.appointment_date >= date('now','-7 days')
                           GROUP BY d.id ORDER BY cnt DESC"""
                    ).fetchall()
                    df2 = pd.DataFrame([dict(r) for r in appt_rows])
                    if len(df2):
                        fig2 = px.bar(df2, x="dept", y="cnt", title="Appointments Last 7 Days (per department)",
                                      color_discrete_sequence=["#3D7EDB"])
                        st.plotly_chart(fig2, use_container_width=True)
                except Exception as e:
                    st.warning(f"Charts unavailable: {e}")

            with tab2:
                st.markdown(f"### 7-Day Demand Forecast {live_vs_sim_badge(True, 'FORECAST')}")
                st.caption("AI model: Scikit-learn ensemble on synthetic 90-day history. Values are estimates.")
                try:
                    import plotly.graph_objects as go
                    hist = build_demand_history(conn)
                    if hist is not None and len(hist) > 30:
                        best_model, metrics, future_df = train_forecast_model(hist, horizon=7)
                        st.write("**Model Performance (Holdout):**",
                                 f"MAE={metrics.get('MAE','?'):.2f}, ",
                                 f"RMSE={metrics.get('RMSE','?'):.2f}, ",
                                 f"R²={metrics.get('R²','?'):.3f} &nbsp; ",
                                 f"<span class=\"live-badge sim\">SIMULATED / PREDICTION</span>",
                                 unsafe_allow_html=True)
                        try:
                            hist_plot = hist.tail(21).copy()
                            fut_plot = future_df.copy()
                            fig = go.Figure()
                            fig.add_trace(go.Scatter(x=hist_plot["date"], y=hist_plot["total_demand"],
                                                     mode="lines+markers", name="Actual (last 21d)",
                                                     line=dict(color="#13315C")))
                            fig.add_trace(go.Scatter(x=fut_plot["date"], y=fut_plot["predicted"],
                                                     mode="lines+markers", name="Predicted (7d)",
                                                     line=dict(color="#F59E0B", dash="dash")))
                            fig.update_layout(title="Actual vs Predicted Hospital Demand",
                                              xaxis_title="Date", yaxis_title="Total demand")
                            st.plotly_chart(fig, use_container_width=True)
                        except Exception as e:
                            st.write(future_df)
                            st.info(f"Forecast data generated — plot rendering issue: {e}")
                    else:
                        st.info("Insufficient historical demand data — re-seed the database for full forecasting.")
                except Exception as e:
                    st.error(f"Forecast error: {e}")

            with tab3:
                em_surge = surge_alert(conn)
                colA, colB = st.columns(2)
                with colA:
                    if em_surge:
                        st.error("🚨 **EMERGENCY SURGE ALERT** — Forecasted + active cases exceed capacity threshold. Requires human review.")
                    else:
                        st.success("✅ Emergency capacity within expected thresholds.")
                with colB:
                    alerts = conn.execute(
                        """SELECT 'Low stock' AS type, name, sku, quantity AS current_qty, reorder_threshold AS threshold
                           FROM inventory_items WHERE quantity <= reorder_threshold
                           UNION ALL
                           SELECT 'Near expiry' AS type, name, sku,
                                  CAST(julianday(expiry_date)-julianday('now') AS INT) || ' days' AS current_qty,
                                  '30 days' AS threshold
                           FROM inventory_items
                           WHERE expiry_date IS NOT NULL AND julianday(expiry_date)-julianday('now') <= 30
                           LIMIT 10"""
                    ).fetchall()
                    adf = pd.DataFrame([dict(r) for r in alerts])
                    if len(adf):
                        st.markdown("**Top 10 Alerts:**")
                        st.dataframe(adf, use_container_width=True, hide_index=True)
                    else:
                        st.info("No inventory alerts at this time.")

            with tab4:
                st.markdown(f"### AI-Generated Recommendations {live_vs_sim_badge(True, 'AI SUGGESTION')}")
                recs = []
                if occ_count and beds_count and (occ_count / beds_count) > 0.85:
                    recs.append("⚠️ **Bed occupancy >85%** — Consider deferring elective admissions or activating surge beds.")
                if waiting_tokens > 30:
                    recs.append(f"⏳ **{waiting_tokens} patients waiting** — Reallocate triage nurses and open additional consultation slots.")
                if low_stock > 5:
                    recs.append(f"💊 **{low_stock} items below reorder threshold** — Initiate stock procurement immediately.")
                if em_surge:
                    recs.append("🚨 **Surge alert active** — Activate emergency response plan; notify on-call staff.")
                try:
                    from app.ai.bottleneck import detect_bottlenecks
                    bns = detect_bottlenecks(conn)
                    for bn in bns[:3]:
                        recs.append(f"🔁 **Bottleneck detected:** {bn.get('workflow_step','?')} "
                                    f"(median dwell {bn.get('median_dwell_minutes',0):.0f} min, level={bn.get('alert_level','?')})")
                except Exception:
                    pass
                if not recs:
                    recs.append("✅ System operating within normal parameters — no immediate actions suggested.")
                for i, r in enumerate(recs, 1):
                    st.markdown(f"{i}. {r}")
    except Exception as e:
        st.error(f"Dashboard error: {e}")


def _doctor_dashboard(user) -> None:
    role_header()
    disclaimer_banner()
    try:
        with get_db() as conn:
            doc_row = conn.execute("SELECT id FROM doctors WHERE user_id=?", (int(user["id"]),)).fetchone()
            doc_id = int(doc_row["id"]) if doc_row else None
            today = pd.Timestamp.now().strftime("%Y-%m-%d")
            my_appts = conn.execute(
                "SELECT COUNT(*) FROM appointments WHERE doctor_id=? AND appointment_date=?",
                (doc_id, today) if doc_id else (0, today)
            ).fetchone()[0] if doc_id else 0
            waiting = conn.execute(
                """SELECT COUNT(*) FROM queue_tokens q
                   JOIN appointments a ON a.id = q.appointment_id
                   WHERE q.status='Waiting' AND a.doctor_id=?""",
                (doc_id,)
            ).fetchone()[0] if doc_id else 0
            pending_lab = conn.execute(
                """SELECT COUNT(*) FROM lab_requests l
                   WHERE l.status IN ('Requested','InProgress') AND l.requested_by=?""",
                (int(user["id"]),)
            ).fetchone()[0]
            my_tasks = conn.execute(
                "SELECT COUNT(*) FROM tasks WHERE assignee_id=? AND status != 'Done'",
                (int(user["id"]),)
            ).fetchone()[0]

            k1, k2, k3, k4 = st.columns(4)
            with k1: metric_card("Today's Appointments", my_appts, icon="📅")
            with k2: metric_card("Patients in Queue", waiting, icon="⏳", variant="warn")
            with k3: metric_card("Pending Lab", pending_lab, icon="🧪", variant="info")
            with k4: metric_card("Open Tasks", my_tasks, icon="✅", variant="info")

            st.markdown("#### 📋 My Upcoming Appointments")
            if doc_id:
                appts = conn.execute(
                    """SELECT a.appointment_time, a.status, p.first_name || ' ' || p.last_name AS patient,
                              a.reason, p.patient_id
                       FROM appointments a JOIN patients p ON p.id = a.patient_id
                       WHERE a.doctor_id=? AND a.appointment_date=?
                       ORDER BY a.appointment_time LIMIT 15""",
                    (doc_id, today)
                ).fetchall()
                adf = pd.DataFrame([dict(r) for r in appts])
                if len(adf):
                    adf["status"] = adf["status"].apply(lambda s: status_badge(str(s)))
                    st.markdown(adf.to_html(escape=False, index=False), unsafe_allow_html=True)
                else:
                    st.info("No appointments scheduled for today.")
            else:
                st.info("Doctor profile not linked.")

            colA, colB = st.columns(2)
            with colA:
                st.markdown("#### 📝 Open Tasks")
                tr = conn.execute(
                    """SELECT t.title, t.priority, t.due_at FROM tasks t
                       WHERE t.assignee_id=? AND t.status != 'Done'
                       ORDER BY CASE t.priority WHEN 'High' THEN 1 WHEN 'Medium' THEN 2 ELSE 3 END, t.due_at
                       LIMIT 10""",
                    (int(user["id"]),)
                ).fetchall()
                tdf = pd.DataFrame([dict(r) for r in tr])
                if len(tdf):
                    tdf["priority"] = tdf["priority"].apply(lambda s: status_badge(str(s)))
                    st.markdown(tdf.to_html(escape=False, index=False), unsafe_allow_html=True)
                else:
                    st.success("No open tasks — clear!")
            with colB:
                st.markdown("#### 📩 Recent Lab Requests")
                lr = conn.execute(
                    """SELECT l.test_type, l.priority, l.status, l.ordered_at
                       FROM lab_requests l WHERE l.requested_by=?
                       ORDER BY l.id DESC LIMIT 10""",
                    (int(user["id"]),)
                ).fetchall()
                ldf = pd.DataFrame([dict(r) for r in lr])
                if len(ldf):
                    ldf["status"] = ldf["status"].apply(lambda s: status_badge(str(s)))
                    ldf["priority"] = ldf["priority"].apply(lambda s: status_badge(str(s)))
                    st.markdown(ldf.to_html(escape=False, index=False), unsafe_allow_html=True)
                else:
                    st.info("No recent lab requests.")
    except Exception as e:
        st.error(f"Dashboard error: {e}")


def _nurse_dashboard(user) -> None:
    role_header()
    disclaimer_banner()
    try:
        with get_db() as conn:
            total_beds = conn.execute("SELECT COUNT(*) FROM beds").fetchone()[0]
            occ = conn.execute("SELECT COUNT(*) FROM beds WHERE status='Occupied'").fetchone()[0]
            avail = total_beds - occ
            dept_id = int(user.get("department_id") or 0)
            waiting_dept = conn.execute(
                "SELECT COUNT(*) FROM queue_tokens WHERE status='Waiting' AND (?=0 OR department_id=?)",
                (dept_id, dept_id)
            ).fetchone()[0]
            my_tasks = conn.execute(
                "SELECT COUNT(*) FROM tasks WHERE assignee_id=? AND status != 'Done'",
                (int(user["id"]),)
            ).fetchone()[0]
            handover = conn.execute(
                "SELECT COUNT(*) FROM handover_notes WHERE to_staff_id=? AND is_read=0",
                (int(user["id"]),)
            ).fetchone()[0]

            k1, k2, k3, k4 = st.columns(4)
            with k1: metric_card("Available Beds", avail, icon="🛏️", variant="occup")
            with k2: metric_card("Occupied", occ, icon="🔴", variant="alert")
            with k3: metric_card("Queue Waiting (Dept)", waiting_dept, icon="⏳", variant="warn")
            with k4: metric_card("Unread Handovers", handover, icon="🤝", variant="info")

            colA, colB = st.columns(2)
            with colA:
                st.markdown("#### 🔢 Live Queue — Call Next")
                qrows = conn.execute(
                    """SELECT q.prefix || '-' || q.token_no AS token, d.name AS dept, q.status,
                              p.first_name || ' ' || p.last_name AS patient,
                              q.estimated_wait_minutes
                       FROM queue_tokens q JOIN patients p ON p.id=q.patient_id
                         JOIN departments d ON d.id=q.department_id
                       WHERE q.status IN ('Waiting','Called','InProgress')
                       ORDER BY q.department_id, q.token_no LIMIT 20"""
                ).fetchall()
                qdf = pd.DataFrame([dict(r) for r in qrows])
                if len(qdf):
                    qdf["status"] = qdf["status"].apply(lambda s: status_badge(str(s)))
                    st.markdown(qdf.to_html(escape=False, index=False), unsafe_allow_html=True)
                else:
                    st.info("No waiting patients.")
            with colB:
                st.markdown("#### 🛏️ Beds Status Snapshot")
                brows = conn.execute(
                    """SELECT d.name AS dept,
                              SUM(CASE WHEN b.status='Available' THEN 1 ELSE 0 END) AS available,
                              SUM(CASE WHEN b.status='Occupied' THEN 1 ELSE 0 END) AS occupied,
                              SUM(CASE WHEN b.status='Maintenance' THEN 1 ELSE 0 END) AS maintenance
                       FROM departments d LEFT JOIN beds b ON b.department_id=d.id
                       GROUP BY d.id ORDER BY available DESC"""
                ).fetchall()
                bdf = pd.DataFrame([dict(r) for r in brows])
                if len(bdf):
                    st.dataframe(bdf, use_container_width=True, hide_index=True)

            st.markdown("#### 📝 My Open Tasks")
            tr = conn.execute(
                """SELECT title, priority, due_at, status FROM tasks
                   WHERE assignee_id=? AND status != 'Done' LIMIT 10""",
                (int(user["id"]),)
            ).fetchall()
            tdf = pd.DataFrame([dict(r) for r in tr])
            if len(tdf):
                tdf["priority"] = tdf["priority"].apply(lambda s: status_badge(str(s)))
                tdf["status"] = tdf["status"].apply(lambda s: status_badge(str(s)))
                st.markdown(tdf.to_html(escape=False, index=False), unsafe_allow_html=True)
            else:
                st.success("All tasks done! 🎉")
    except Exception as e:
        st.error(f"Dashboard error: {e}")


def _patient_dashboard(user) -> None:
    role_header()
    disclaimer_banner()
    try:
        with get_db() as conn:
            from app.core.auth import get_patient_user_link
            pid = get_patient_user_link(conn, int(user["id"]))
            if not pid:
                st.info("Your account is not linked to a patient record.")
                return
            prow = conn.execute("SELECT * FROM patients WHERE id=?", (pid,)).fetchone()
            today = pd.Timestamp.now().strftime("%Y-%m-%d")
            upc = conn.execute(
                """SELECT COUNT(*) FROM appointments a
                   WHERE a.patient_id=? AND a.appointment_date >= ? AND a.status NOT IN ('Cancelled')""",
                (pid, today)
            ).fetchone()[0]
            my_q = conn.execute(
                """SELECT COUNT(*) FROM queue_tokens q
                   WHERE q.patient_id=? AND q.status IN ('Waiting','Called','InProgress')""",
                (pid,)
            ).fetchone()[0]
            my_adm = conn.execute(
                "SELECT COUNT(*) FROM admissions WHERE patient_id=? AND status != 'Discharged'",
                (pid,)
            ).fetchone()[0]
            my_notifs = conn.execute(
                "SELECT COUNT(*) FROM notifications WHERE user_id=? AND is_read=0",
                (int(user["id"]),)
            ).fetchone()[0]

            k1, k2, k3, k4 = st.columns(4)
            with k1: metric_card("Upcoming Appointments", upc, icon="📅", variant="info")
            with k2: metric_card("Active Queue Tokens", my_q, icon="⏳", variant="warn")
            with k3: metric_card("Active Admissions", my_adm, icon="🏥", variant="info")
            with k4: metric_card("Unread Notifications", my_notifs, icon="🔔", variant="info")

            st.markdown("#### 👤 Profile Summary")
            st.write(f"**Name:** {prow['first_name']} {prow['last_name']}  \n"
                     f"**Patient ID:** {prow['patient_id']}  \n"
                     f"**DOB:** {prow['dob']}  \n"
                     f"**Phone:** {prow['phone']}  \n"
                     f"**Email:** {prow['email']}")

            st.markdown("#### 📅 Upcoming Appointments")
            arows = conn.execute(
                """SELECT a.appointment_date, a.appointment_time, a.status, d.name AS dept,
                          u.full_name AS doctor, a.reason
                   FROM appointments a
                   JOIN departments d ON d.id = a.department_id
                   JOIN doctors doc ON doc.id = a.doctor_id
                   JOIN users u ON u.id = doc.user_id
                   WHERE a.patient_id=? AND a.appointment_date >= ? AND a.status != 'Cancelled'
                   ORDER BY a.appointment_date, a.appointment_time LIMIT 10""",
                (pid, today)
            ).fetchall()
            adf = pd.DataFrame([dict(r) for r in arows])
            if len(adf):
                adf["status"] = adf["status"].apply(lambda s: status_badge(str(s)))
                st.markdown(adf.to_html(escape=False, index=False), unsafe_allow_html=True)
            else:
                st.info("No upcoming appointments.")
    except Exception as e:
        st.error(f"Dashboard error: {e}")


def _inventory_dashboard(user) -> None:
    role_header()
    disclaimer_banner()
    try:
        with get_db() as conn:
            total_items = conn.execute("SELECT COUNT(*) FROM inventory_items").fetchone()[0]
            low = conn.execute(
                "SELECT COUNT(*) FROM inventory_items WHERE quantity <= reorder_threshold"
            ).fetchone()[0]
            near_exp = conn.execute(
                "SELECT COUNT(*) FROM inventory_items "
                "WHERE expiry_date IS NOT NULL AND julianday(expiry_date)-julianday('now') <= 30"
            ).fetchone()[0]
            movements_today = conn.execute(
                "SELECT COUNT(*) FROM stock_movements WHERE date(created_at)=date('now')"
            ).fetchone()[0]

            k1, k2, k3, k4 = st.columns(4)
            with k1: metric_card("SKUs", total_items, icon="📦")
            with k2: metric_card("Below Reorder", low, icon="⚠️", variant="alert")
            with k3: metric_card("Near-Expiry (30d)", near_exp, icon="⏰", variant="warn")
            with k4: metric_card("Stock Movements Today", movements_today, icon="↔️", variant="info")

            colA, colB = st.columns(2)
            with colA:
                st.markdown("#### 💊 Low Stock Items")
                rows = conn.execute(
                    """SELECT sku, name, category, quantity, reorder_threshold, unit
                       FROM inventory_items WHERE quantity <= reorder_threshold
                       ORDER BY quantity ASC LIMIT 15"""
                ).fetchall()
                df = pd.DataFrame([dict(r) for r in rows])
                if len(df):
                    st.dataframe(df, use_container_width=True, hide_index=True)
                else:
                    st.success("No items below reorder threshold.")
            with colB:
                st.markdown("#### ⏰ Near-Expiry Items")
                rows = conn.execute(
                    """SELECT sku, name, category, expiry_date,
                              CAST(julianday(expiry_date)-julianday('now') AS INT) AS days_left
                       FROM inventory_items
                       WHERE expiry_date IS NOT NULL AND julianday(expiry_date)-julianday('now') <= 30
                       ORDER BY days_left ASC LIMIT 15"""
                ).fetchall()
                df2 = pd.DataFrame([dict(r) for r in rows])
                if len(df2):
                    st.dataframe(df2, use_container_width=True, hide_index=True)
                else:
                    st.success("No items expiring within 30 days.")

            st.markdown("#### 📈 Stock Movements Last 7 Days")
            try:
                import plotly.express as px
                rows = conn.execute(
                    """SELECT date(created_at) AS dt,
                              SUM(CASE WHEN quantity_delta>0 THEN quantity_delta ELSE 0 END) AS stock_in,
                              SUM(CASE WHEN quantity_delta<0 THEN -quantity_delta ELSE 0 END) AS stock_out
                       FROM stock_movements
                       WHERE date(created_at) >= date('now','-7 days')
                       GROUP BY date(created_at) ORDER BY dt"""
                ).fetchall()
                dff = pd.DataFrame([dict(r) for r in rows])
                if len(dff):
                    fig = px.bar(dff, x="dt", y=["stock_in", "stock_out"], barmode="group",
                                 title="Stock In vs Out (last 7 days)",
                                 color_discrete_sequence=["#10B981", "#EF4444"])
                    st.plotly_chart(fig, use_container_width=True)
            except Exception as e:
                st.info(f"Movements chart unavailable: {e}")
    except Exception as e:
        st.error(f"Dashboard error: {e}")


def _sidebar() -> None:
    user = st.session_state.get("user")
    st.sidebar.markdown("---")
    if not user:
        return
    role = user.get("role")
    st.sidebar.markdown(f"### 🏥 Medi — Hospital Ops")
    st.sidebar.markdown(f"**User:** {user.get('full_name','')}  \n**Role:** {role}")
    notification_bell()
    st.sidebar.markdown("---")
    logout_btn()


def main() -> None:
    user = get_session(require_auth=False)
    if not user:
        _login_page()
        return
    role = user.get("role")
    _sidebar()
    if role == "Admin":
        _admin_dashboard(user)
    elif role == "Doctor":
        _doctor_dashboard(user)
    elif role == "Nurse":
        _nurse_dashboard(user)
    elif role == "Patient":
        _patient_dashboard(user)
    elif role == "InventoryManager":
        _inventory_dashboard(user)
    else:
        st.warning(f"Role {role} — generic dashboard placeholder.")


if __name__ == "__main__":
    main()
