from __future__ import annotations

import os
from typing import Any, Optional

import streamlit as st

_APP_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_ASSETS = os.path.join(os.path.dirname(_APP_ROOT), "assets")
_CSS_PATH = os.path.join(_ASSETS, "custom.css")


def apply_custom_css() -> None:
    if os.path.exists(_CSS_PATH):
        with open(_CSS_PATH, "r", encoding="utf-8") as fh:
            css = fh.read()
        st.markdown(f"<style>{css}</style>", unsafe_allow_html=True)
    else:
        _embedded_css_fallback()


def _embedded_css_fallback() -> None:
    st.markdown(
        """
<style>
:root{--navy-900:#0B2545;--navy-800:#13315C;--navy-700:#1B4079;--blue-500:#3D7EDB;--accent-teal:#14B8A6;--warn:#F59E0B;--danger:#EF4444;--success:#10B981;--bg:#F6F9FC;--card:#FFFFFF;--text:#1F2937;--muted:#6B7280;--border:#E5E7EB}
html,body,[class*="css"]{font-family:'Segoe UI',Roboto,system-ui;background:var(--bg);color:var(--text)}
section[data-testid="stSidebar"]{background:linear-gradient(180deg,var(--navy-900),var(--navy-700));color:#fff}
section[data-testid="stSidebar"] *{color:#fff}
.metric-card{background:var(--card);border:1px solid var(--border);border-left:5px solid var(--blue-500);border-radius:10px;padding:16px 18px;margin-bottom:12px}
.metric-card .m-title{color:var(--muted);font-size:.85rem}
.metric-card .m-value{font-size:1.8rem;font-weight:700;color:var(--navy-800);margin-top:4px}
.status-badge{display:inline-block;padding:3px 10px;border-radius:12px;font-size:.78rem;font-weight:600}
.status-available,.status-completed,.status-done,.status-confirmed,.status-resolved,.status-discharged{background:#D1FAE5;color:#065F46}
.status-occupied,.status-inprogress,.status-admitted,.status-scheduled,.status-open{background:#DBEAFE;color:#1E40AF}
.status-waiting,.status-pending,.status-maintenance,.status-dischargepending,.status-requested{background:#FEF3C7;color:#92400E}
.status-called,.status-intransfer{background:#E0E7FF;color:#3730A3}
.status-missed,.status-cancelled{background:#FEE2E2;color:#991B1B}
.live-badge{display:inline-block;padding:2px 8px;border-radius:10px;font-size:.75rem;font-weight:700;margin-left:6px}
.live-badge.live{background:#D1FAE5;color:#065F46}.live-badge.sim{background:#FFEDD5;color:#9A3412}
.prototype-disclaimer{background:#FFFBEB;border-left:5px solid var(--warn);border-radius:8px;padding:12px 16px;font-size:.9rem;color:#78350F;margin-bottom:18px}
.role-header{background:linear-gradient(90deg,var(--navy-800),var(--navy-600));color:#fff;padding:14px 20px;border-radius:10px;margin-bottom:14px;display:flex;justify-content:space-between;align-items:center}
.role-header h1{margin:0;font-size:1.35rem;color:#fff}.role-header .sub{opacity:.85;font-size:.85rem}
</style>
""",
        unsafe_allow_html=True,
    )


def disclaimer_banner() -> None:
    pass



_ROLE_ICONS = {
    "Admin": "🏥",
    "Doctor": "👨‍⚕️",
    "Nurse": "👩‍⚕️",
    "Patient": "🧑‍🦽",
    "InventoryManager": "💊",
}


def role_header() -> None:
    user = st.session_state.get("user")
    if not user:
        return
    role = user.get("role", "")
    icon = _ROLE_ICONS.get(role, "💼")
    name = user.get("full_name", "")
    st.markdown(
        f"""
<div class="role-header">
  <div>
    <h1>{icon}  {role} Dashboard</h1>
    <div class="sub">Logged in as <strong>{name}</strong> ({user.get('username','')})</div>
  </div>
  <div class="sub">{_today_str()}</div>
</div>
""",
        unsafe_allow_html=True,
    )


def _today_str() -> str:
    import datetime as _dt
    return _dt.datetime.now().strftime("%A, %d %b %Y %H:%M")


def get_session(require_auth: bool = True) -> Optional[dict[str, Any]]:
    user = st.session_state.get("user")
    if not user and require_auth:
        st.warning("🔒 You must be logged in to access this page.")
        if st.button("← Go to Login", use_container_width=True):
            st.switch_page("1_🏠_Home.py")
        st.stop()
    return user


def logout_btn() -> None:
    user = st.session_state.get("user")
    if st.sidebar.button("🚪 Logout", use_container_width=True):
        try:
            from app.db.database import get_db
            from app.core.auth import logout as _logout
            with get_db() as conn:
                _logout(conn, user)
        except Exception:
            pass
        for k in list(st.session_state.keys()):
            del st.session_state[k]
        st.success("Logged out. Returning to home…")
        st.rerun()


def notification_bell() -> None:
    user = st.session_state.get("user")
    if not user:
        return
    try:
        from app.db.database import get_db
        from app.core.notifications import unread_count
        with get_db() as conn:
            n = unread_count(conn, int(user["id"]))
    except Exception:
        n = 0
    st.sidebar.markdown(f"🔔 **Notifications**: {n} unread")


def metric_card(title: str, value: Any, delta: Any = None, icon: str = "", badge: str = "", variant: str = "info") -> None:
    badge_html = ""
    if badge:
        badge_cls = "sim" if badge.lower() in ("sim", "simulated", "forecast", "estimate", "prediction") else "live"
        badge_html = f'<span class="live-badge {badge_cls}">{badge}</span>'
    delta_html = ""
    if delta is not None:
        delta_html = f'<div class="m-delta">{delta}</div>'
    st.markdown(
        f"""
<div class="metric-card {variant}">
  <div class="m-title">{icon} {title}{badge_html}</div>
  <div class="m-value">{value}</div>
  {delta_html}
</div>
""",
        unsafe_allow_html=True,
    )


def status_badge(status: str) -> str:
    if not status:
        return '<span class="status-badge status-pending">—</span>'
    cls = "status-" + str(status).lower().replace(" ", "").replace("_", "")
    return f'<span class="status-badge {cls}">{status}</span>'


def live_vs_sim_badge(is_sim: bool = False, label: Optional[str] = None) -> str:
    if label:
        text = label
    else:
        text = "SIMULATED" if is_sim else "LIVE DB"
    cls = "sim" if is_sim else "live"
    return f'<span class="live-badge {cls}">{text}</span>'


def page_requires_role(allowed_roles: list[str]) -> dict[str, Any]:
    user = get_session(require_auth=True)
    role = user.get("role") if user else None
    if role not in set(allowed_roles):
        st.error(f"⛔ Permission denied — role **{role}** cannot access this page.")
        st.stop()
    return user


def render_df_with_status(df, status_col: Optional[str] = None) -> None:
    if status_col and status_col in df.columns and len(df) > 0:
        df = df.copy()
        df[status_col] = df[status_col].apply(lambda s: status_badge(str(s)) if s else "")
        safe_render_table(df)
    else:
        st.dataframe(df, use_container_width=True, hide_index=True)


def safe_render_table(data: Any, hide_index: bool = True) -> None:
    """Render a table safely using pandas to_html without requiring pyarrow."""
    import pandas as pd
    if isinstance(data, pd.DataFrame):
        df = data
    elif isinstance(data, (list, tuple, dict)):
        df = pd.DataFrame(data)
    else:
        df = pd.DataFrame([data])

    html = df.to_html(index=not hide_index, escape=False)
    styled_html = (
        '<div style="overflow-x:auto; margin-bottom:12px;">'
        '<style>'
        'table.custom-df { width:100%; border-collapse:collapse; background:#fff; border-radius:8px; overflow:hidden; font-size:0.88rem; } '
        'table.custom-df th { background:#13315C; color:#fff; padding:8px 12px; text-align:left; } '
        'table.custom-df td { padding:8px 12px; border-bottom:1px solid #E5E7EB; } '
        'table.custom-df tr:nth-child(even) { background:#F9FAFB; }'
        '</style>'
        + html.replace('class="dataframe"', 'class="custom-df"')
        + '</div>'
    )
    st.markdown(styled_html, unsafe_allow_html=True)


def patch_streamlit_table_fallbacks() -> None:
    """Monkey-patch st.dataframe and st.table to fallback safely if pyarrow is blocked by Windows Application Control."""
    if getattr(st, "_table_patched", False):
        return
    orig_dataframe = getattr(st, "dataframe")
    orig_table = getattr(st, "table")

    def safe_dataframe(data=None, *args, **kwargs):
        try:
            return orig_dataframe(data, *args, **kwargs)
        except Exception:
            safe_render_table(data)

    def safe_table(data=None, *args, **kwargs):
        try:
            return orig_table(data, *args, **kwargs)
        except Exception:
            safe_render_table(data)

    st.dataframe = safe_dataframe
    st.table = safe_table
    st._table_patched = True


# Auto-apply table patch on import
patch_streamlit_table_fallbacks()

