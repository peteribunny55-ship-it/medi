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

st.title("🚨 Emergency Department")
disclaimer_banner()

try:
    with get_db() as conn:
        from app.core.emergency import live_capacity, surge_alert
        lc = live_capacity(conn)
        is_surge = surge_alert(conn)

        k1, k2, k3, k4 = st.columns(4)
        from app.utils.ui import metric_card
        with k1: metric_card("ED Beds Available", lc["emergency_beds_available"], icon="🛏️", variant="occup")
        with k2: metric_card("On-Duty Staff", lc["on_duty_staff_count"], icon="👩‍⚕️", variant="info")
        with k3: metric_card("Active Emergencies", lc["active_emergencies"], icon="🚑", variant="alert")
        with k4:
            if is_surge:
                st.markdown('<div class="metric-card alert"><div class="m-title">🚨 Surge Status</div><div class="m-value" style="color:#991B1B;">ACTIVE</div><div><span class="live-badge sim">SURGE ALERT</span></div></div>', unsafe_allow_html=True)
            else:
                st.markdown('<div class="metric-card occup"><div class="m-title">✅ Surge Status</div><div class="m-value" style="color:#065F46;">Normal</div><div><span class="live-badge live">IN THRESHOLD</span></div></div>', unsafe_allow_html=True)

        if is_surge:
            st.error("🚨 **EMERGENCY SURGE ALERT ACTIVE** — Active + forecast demand exceeds capacity. Activate surge plan and on-call staff.")
        else:
            st.success("✅ Emergency capacity within thresholds.")

        tab1, tab2, tab3, tab4 = st.tabs(["📋 Case Log", "➕ Register Emergency Case", "🔄 Update Case Status", "🚑 Ambulance Route Navigation"])

        with tab1:
            st.markdown("### Emergency Case Log")
            cs = st.selectbox("Filter by Status", ["", "Triage", "Admitted", "InTreatment", "DischargePending", "Discharged"], index=0)
            from app.core.emergency import list_cases
            cases = list_cases(conn, status=(cs or None), limit=300)
            cdf = pd.DataFrame(cases)
            if len(cdf):
                cdf["triage_badge"] = cdf["triage_level"].apply(lambda t: f'<span class="live-badge {"live" if int(t or 0)<=2 else "sim"}>T{t}</span>' if t else "")
                bed_map = {}
                brows = conn.execute("SELECT id, bed_no FROM beds").fetchall()
                for b in brows:
                    bed_map[int(b["id"])] = b["bed_no"]
                cdf["bed_no"] = cdf["bed_id"].map(bed_map).fillna("—")
                prows = conn.execute("SELECT id, patient_id, first_name, last_name FROM patients").fetchall()
                pmap = {int(r["id"]): f"{r['patient_id']} {r['first_name']} {r['last_name']}" for r in prows}
                cdf["patient"] = cdf["patient_id"].map(pmap).fillna("?")
                show = ["id", "patient", "bed_no", "triage_badge", "diagnosis", "status", "admitted_at", "discharged_at"]
                show = [c for c in show if c in cdf.columns]
                dfs = cdf[show].copy()
                dfs["status"] = dfs["status"].apply(lambda s: status_badge(str(s)))
                st.markdown(dfs.to_html(escape=False, index=False), unsafe_allow_html=True)
                csv_download(cdf, "emergency_cases.csv", "📥 Download Case Log CSV")
            else:
                st.info("No emergency cases matching criteria.")

        with tab2:
            st.markdown("### Register Emergency Case")
            patients = conn.execute("SELECT id, patient_id, first_name, last_name FROM patients ORDER BY id DESC LIMIT 500").fetchall()
            pat_map = {int(r["id"]): f"{r['patient_id']} — {r['first_name']} {r['last_name']}" for r in patients}
            from app.core.beds import list_beds
            ed_beds = list_beds(conn)
            bed_map = {int(b["id"]): f"{b['bed_no']} ({b.get('dept_name','?')}, {b.get('bed_type','?')}) [{b.get('status','')}]" for b in ed_beds}
            with st.form("em_case_form", clear_on_submit=True):
                e1, e2 = st.columns(2)
                with e1:
                    ep = st.selectbox("Patient", list(pat_map.keys()), format_func=lambda k: pat_map[k], index=0)
                    et = st.selectbox("Triage Level (1=Resuscitation, 5=Less Urgent)", [1, 2, 3, 4, 5], index=2)
                    ec = st.text_area("Chief Complaint *", height=90)
                with e2:
                    import datetime as _dt
                    ea = st.date_input("Arrival Date", value=_dt.date.today())
                    eat = st.time_input("Arrival Time", value=_dt.datetime.now().time())
                    e_stat = st.selectbox("Initial Status", ["Triage", "Admitted", "InTreatment"], index=0)
                    eb = st.selectbox("Bed (optional)", [0] + list(bed_map.keys()),
                                      format_func=lambda k: "None / Waiting" if k == 0 else bed_map[k], index=0)
                sub = st.form_submit_button("Register Case", type="primary")
                if sub:
                    if not ec:
                        st.error("Chief complaint is required.")
                    else:
                        try:
                            from app.core.emergency import create_case
                            arrival_iso = pd.Timestamp(str(ea)) + pd.Timedelta(hours=eat.hour, minutes=eat.minute)
                            result = create_case(
                                conn, user,
                                patient_id=int(ep),
                                arrival_iso=arrival_iso.strftime("%Y-%m-%d %H:%M:%S"),
                                triage_level=int(et),
                                complaint=ec,
                                status=e_stat,
                                bed_id=(None if eb == 0 else int(eb)),
                            )
                            st.success(f"✅ Emergency case #{result['id']} created — T{et}.")
                        except Exception as e:
                            st.error(f"Case registration failed: {e}")

        with tab3:
            st.markdown("### Update Case Status")
            open_cases = conn.execute(
                """SELECT a.*, p.patient_id, p.first_name, p.last_name
                   FROM admissions a LEFT JOIN patients p ON p.id=a.patient_id
                   WHERE a.admission_type='Emergency' AND a.status!='Discharged' ORDER BY a.id DESC"""
            ).fetchall()
            ocdf = pd.DataFrame([dict(r) for r in open_cases])
            if not len(ocdf):
                st.info("No active emergency cases.")
            else:
                ocdf["label"] = "#" + ocdf["id"].astype(str) + " — " + ocdf["patient_id"] + " " + ocdf["first_name"] + " " + ocdf["last_name"] + f" [{ocdf['status']}]"
                sel_case = st.selectbox("Select Case", list(ocdf["id"].values),
                                        format_func=lambda i: ocdf.loc[ocdf["id"] == i, "label"].iloc[0], index=0)
                nstat = st.selectbox("New Status", ["Triage", "Admitted", "InTreatment", "DischargePending", "Discharged"], index=0)
                nnotes = st.text_area("Notes (audit only)")
                if st.button("Update Case Status", type="primary"):
                    try:
                        from app.core.emergency import set_case_status
                        r = set_case_status(conn, user, int(sel_case), nstat, nnotes or None)
                        st.success(f"✅ Case #{r['id']} status updated to {r['status']}.")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Status update failed: {e}")

        with tab4:
            st.markdown("### 🚑 Emergency Ambulance Faster Route Navigation")
            from app.core.ambulance import list_dispatches, list_ambulances
            dispatches = list_dispatches(conn)
            active_disp = [d for d in dispatches if d["status"] not in ("Completed", "Arrived at ED")]

            if active_disp:
                st.markdown(f"**{len(active_disp)} Active Ambulance Call(s) En Route:**")
                adf = pd.DataFrame(active_disp)
                adf["status_badge"] = adf["status"].apply(lambda s: status_badge(str(s)))
                show_a = ["id", "vehicle_number", "driver_name", "pickup_address", "status_badge", "eta_minutes", "distance_km", "route_summary"]
                show_a = [c for c in show_a if c in adf.columns]
                st.markdown(adf[show_a].to_html(escape=False, index=False), unsafe_allow_html=True)
            else:
                st.info("No active emergency ambulance calls currently in transit.")

            st.markdown("---")
            st.markdown("👉 For full interactive Leaflet map route navigation, alternative route overlays, turn-by-turn guidance, and live GPS simulation, visit **[Page 24: 🚑 Ambulance Navigation]** in the sidebar menu.")

except Exception as e:
    st.error(f"Emergency page error: {e}")
