from __future__ import annotations

import os
import sys

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

import pandas as pd
import streamlit as st

try:
    import streamlit.components.v1 as components
except Exception:
    components = None


from app.utils.ui import page_requires_role, apply_custom_css, disclaimer_banner, metric_card, status_badge
from app.utils.exporters import csv_download
from app.db.database import get_db
from app.core.ambulance import (
    HOSPITAL_LAT,
    HOSPITAL_LNG,
    HOSPITAL_NAME,
    list_ambulances,
    create_ambulance,
    update_ambulance_location,
    generate_route_geometry,
    dispatch_ambulance,
    list_dispatches,
    update_dispatch_status,
)

user = page_requires_role(["Admin", "Doctor", "Nurse"])
apply_custom_css()

st.title("🚑 Ambulance Fleet & Faster Route Navigation Map")
disclaimer_banner()

try:
    with get_db() as conn:
        fleet = list_ambulances(conn)
        dispatches = list_dispatches(conn)

        avail_count = sum(1 for a in fleet if a["status"] in ("Available", "Base Station"))
        active_disp = [d for d in dispatches if d["status"] not in ("Completed", "Arrived at ED")]
        avg_eta = int(pd.Series([d["eta_minutes"] for d in active_disp]).mean()) if active_disp else 10

        m1, m2, m3, m4 = st.columns(4)
        with m1:
            metric_card("Active Dispatches", len(active_disp), icon="🚨", variant="alert" if active_disp else "info")
        with m2:
            metric_card("Available Fleet", f"{avail_count} / {len(fleet)}", icon="🚑", variant="occup" if avail_count > 0 else "alert")
        with m3:
            metric_card("Avg Emergency ETA", f"{avg_eta} min", icon="⚡", variant="warn" if avg_eta > 12 else "occup")
        with m4:
            metric_card("Total Fleet Ambulances", len(fleet), icon="🚐", variant="info")

        tab1, tab2, tab3, tab4 = st.tabs([
            "🗺️ Live Navigation Route Map",
            "🚨 Dispatch Ambulance",
            "📋 Dispatch Monitor",
            "🚐 Fleet Management"
        ])

        # ---------------- TAB 1: Live Route Map ----------------
        with tab1:
            st.markdown("### 🗺️ Live Navigation Route Map for Ambulance Emergency Response")
            st.caption("Real-time route calculation and interactive navigation map showing fastest route with priority corridor.")

            if dispatches:
                disp_options = {
                    d["id"]: f"Call #{d['id']} — {d['vehicle_number']} ({d['driver_name']}) → {d['pickup_address']} [{d['status']}]"
                    for d in dispatches
                }
                selected_disp_id = st.selectbox(
                    "Select Active Call / Dispatch to View Route",
                    list(disp_options.keys()),
                    format_func=lambda k: disp_options[k],
                    index=0,
                )

                selected_disp = next((d for d in dispatches if d["id"] == selected_disp_id), dispatches[0])

                # Get pickup and destination coordinates
                amb_lat = float(selected_disp.get("amb_lat") or 12.9820)
                amb_lng = float(selected_disp.get("amb_lng") or 77.6010)

                # Generate 3 comparative routes
                fastest_route = generate_route_geometry(amb_lat, amb_lng, HOSPITAL_LAT, HOSPITAL_LNG, route_type="fastest")
                shortest_route = generate_route_geometry(amb_lat, amb_lng, HOSPITAL_LAT, HOSPITAL_LNG, route_type="shortest")
                bypass_route = generate_route_geometry(amb_lat, amb_lng, HOSPITAL_LAT, HOSPITAL_LNG, route_type="bypass")

                col_map, col_details = st.columns([2.2, 1.2])

                with col_map:
                    # Render Leaflet.js OpenStreetMap interactive map with polylines and custom markers
                    map_html = f"""
                    <!DOCTYPE html>
                    <html>
                    <head>
                        <meta charset="utf-8" />
                        <title>Ambulance Navigation Map</title>
                        <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
                        <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
                        <style>
                            #map {{ height: 500px; width: 100%; border-radius: 12px; box-shadow: 0 4px 12px rgba(0,0,0,0.15); }}
                            .leaflet-popup-content-wrapper {{ font-family: system-ui, sans-serif; font-size: 13px; }}
                        </style>
                    </head>
                    <body style="margin:0; padding:0;">
                        <div id="map"></div>
                        <script>
                            var map = L.map('map').setView([{amb_lat}, {amb_lng}], 13);

                            L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png', {{
                                attribution: '© OpenStreetMap contributors',
                                maxZoom: 19
                            }}).addTo(map);

                            // Markers
                            var ambIcon = L.divIcon({{
                                html: '<div style="font-size:28px; filter: drop-shadow(0 2px 4px rgba(0,0,0,0.4));">🚑</div>',
                                className: 'custom-div-icon',
                                iconSize: [30, 30],
                                iconAnchor: [15, 15]
                            }});

                            var pickupIcon = L.divIcon({{
                                html: '<div style="font-size:28px; filter: drop-shadow(0 2px 4px rgba(0,0,0,0.4));">📍</div>',
                                className: 'custom-div-icon',
                                iconSize: [30, 30],
                                iconAnchor: [15, 30]
                            }});

                            var hospIcon = L.divIcon({{
                                html: '<div style="font-size:32px; filter: drop-shadow(0 2px 4px rgba(0,0,0,0.4));">🏥</div>',
                                className: 'custom-div-icon',
                                iconSize: [35, 35],
                                iconAnchor: [17, 35]
                            }});

                            L.marker([{amb_lat}, {amb_lng}], {{icon: ambIcon}})
                             .addTo(map)
                             .bindPopup("<b>Ambulance {selected_disp['vehicle_number']}</b><br>Driver: {selected_disp['driver_name']}<br>Status: {selected_disp['status']}");

                            L.marker([{HOSPITAL_LAT}, {HOSPITAL_LNG}], {{icon: hospIcon}})
                             .addTo(map)
                             .bindPopup("<b>{HOSPITAL_NAME}</b><br>Destination Emergency Ward");

                            // Polylines
                            var fastestCoords = {fastest_route['waypoints']};
                            var shortestCoords = {shortest_route['waypoints']};
                            var bypassCoords = {bypass_route['waypoints']};

                            // Alternative routes (dashed)
                            L.polyline(shortestCoords, {{color: '#94A3B8', weight: 4, dashArray: '6, 8'}}).addTo(map)
                             .bindPopup("Direct City Route: {shortest_route['distance_km']} km, {shortest_route['eta_minutes']} min");

                            L.polyline(bypassCoords, {{color: '#CBD5E1', weight: 4, dashArray: '6, 8'}}).addTo(map)
                             .bindPopup("Ring Road Bypass: {bypass_route['distance_km']} km, {bypass_route['eta_minutes']} min");

                            // FASTEST ROUTE (Bold Highlighted Green/Blue Line)
                            var fastestLine = L.polyline(fastestCoords, {{color: '#10B981', weight: 7, opacity: 0.95}}).addTo(map)
                             .bindPopup("<b>⚡ FASTEST ROUTE (Priority Corridor)</b><br>Distance: {fastest_route['distance_km']} km<br>ETA: {fastest_route['eta_minutes']} mins");

                            map.fitBounds(fastestLine.getBounds(), {{padding: [40, 40]}});
                        </script>
                    </body>
                    </html>
                    """
                    if components:
                        components.html(map_html, height=520)
                    else:
                        st.info("🗺️ Interactive Leaflet Map Route Active.")


                with col_details:
                    st.markdown("#### ⚡ Route & Navigation Summary")
                    st.markdown(
                        f"""
                        <div style="background-color:#ECFDF5; border: 2px solid #10B981; border-radius: 10px; padding: 15px; margin-bottom: 15px;">
                            <h4 style="margin:0; color:#065F46;">⚡ FASTEST ROUTE SELECTED</h4>
                            <div style="font-size:1.8rem; font-weight:bold; color:#047857; margin:6px 0;">{fastest_route['eta_minutes']} mins <span style="font-size:1rem; color:#065F46;">ETA</span></div>
                            <div style="font-size:0.95rem; color:#064E3B;"><b>Distance:</b> {fastest_route['distance_km']} km</div>
                            <div style="font-size:0.95rem; color:#064E3B;"><b>Avg Speed:</b> {fastest_route['speed_kmh']} km/h</div>
                            <div style="font-size:0.95rem; color:#064E3B; margin-top:4px;"><b>Traffic Corridor:</b> {fastest_route['traffic_condition']}</div>
                        </div>
                        """,
                        unsafe_allow_html=True,
                    )

                    st.markdown("##### 🛣️ Turn-by-Turn Guidance")
                    for step in fastest_route["navigation_steps"]:
                        st.markdown(
                            f"""
                            <div style="background-color:#F8FAFC; border-left: 4px solid #3B82F6; padding: 8px 12px; margin-bottom: 8px; border-radius: 4px; font-size: 0.88rem;">
                                <b>Step {step['step']}:</b> {step['instruction']} <span style="color:#64748B;">({step['distance_m']}m)</span>
                            </div>
                            """,
                            unsafe_allow_html=True,
                        )

                    st.markdown("---")
                    st.markdown("##### 📍 Driver Live Position Simulator")
                    with st.form("sim_pos_form"):
                        sim_lat = st.number_input("Lat", value=amb_lat, format="%.6f")
                        sim_lng = st.number_input("Lng", value=amb_lng, format="%.6f")
                        sub_sim = st.form_submit_button("Update Ambulance GPS Position")
                        if sub_sim:
                            update_ambulance_location(conn, user, selected_disp["ambulance_id"], sim_lat, sim_lng)
                            st.success("✅ GPS location updated!")
                            st.rerun()

            else:
                st.info("No active ambulance dispatches.")

        # ---------------- TAB 2: Dispatch Ambulance ----------------
        with tab2:
            st.markdown("### 🚨 Dispatch Emergency Ambulance")

            avail_ambulances = [a for a in fleet if a["status"] in ("Available", "Base Station")]

            if not avail_ambulances:
                st.warning("⚠️ No ambulances currently available in the fleet for dispatch.")
            else:
                amb_map = {a["id"]: f"{a['vehicle_number']} — Driver: {a['driver_name']} ({a['driver_phone']})" for a in avail_ambulances}

                prows = conn.execute("SELECT id, patient_id, first_name, last_name FROM patients ORDER BY id DESC LIMIT 300").fetchall()
                pat_map = {int(p["id"]): f"{p['patient_id']} — {p['first_name']} {p['last_name']}" for p in prows}

                dept_rows = conn.execute("SELECT id, name FROM departments ORDER BY name").fetchall()
                dept_map = {int(d["id"]): d["name"] for d in dept_rows}

                with st.form("dispatch_form", clear_on_submit=True):
                    d_c1, d_c2 = st.columns(2)

                    with d_c1:
                        sel_amb = st.selectbox("Select Available Ambulance *", list(amb_map.keys()), format_func=lambda k: amb_map[k])
                        sel_pat = st.selectbox("Patient (Optional)", [0] + list(pat_map.keys()), format_func=lambda k: "Emergency Walk-in / Caller" if k == 0 else pat_map[k])
                        pick_addr = st.text_input("Emergency Pickup Address *", value="104 Maple Street, Sector 4")

                    with d_c2:
                        sel_dept = st.selectbox("Destination Department", list(dept_map.keys()), index=5 if 6 in dept_map else 0, format_func=lambda k: dept_map[k])
                        p_lat = st.number_input("Pickup Latitude", value=12.9820, format="%.6f")
                        p_lng = st.number_input("Pickup Longitude", value=77.6010, format="%.6f")
                        route_pref = st.selectbox("Route Optimization Profile", ["fastest", "shortest", "bypass"], format_func=lambda x: "⚡ Emergency Priority Expressway (Fastest Route)" if x=="fastest" else ("📏 Direct City Center (Shortest)" if x=="shortest" else "🔄 Ring Road Bypass"))

                    sub_disp = st.form_submit_button("🚨 Dispatch Ambulance Now", type="primary")

                    if sub_disp:
                        if not pick_addr.strip():
                            st.error("Pickup address is required.")
                        else:
                            try:
                                res = dispatch_ambulance(
                                    conn,
                                    user,
                                    ambulance_id=int(sel_amb),
                                    pickup_address=pick_addr,
                                    patient_id=None if sel_pat == 0 else int(sel_pat),
                                    destination_dept_id=int(sel_dept),
                                    pickup_lat=float(p_lat),
                                    pickup_lng=float(p_lng),
                                    route_preference=route_pref,
                                )
                                st.success(f"✅ Ambulance dispatched successfully! Dispatch #{res['id']} | ETA: {res['eta_minutes']} mins")
                                st.rerun()
                            except Exception as e:
                                st.error(f"Dispatch failed: {e}")

        # ---------------- TAB 3: Dispatch Monitor ----------------
        with tab3:
            st.markdown("### 📋 Dispatch Monitor & Live Tracking")

            d_filter = st.selectbox("Filter Status", ["All", "Dispatched", "En Route to Scene", "On Scene", "Transporting", "Arrived at ED", "Completed"], index=0)

            disp_list = list_dispatches(conn, status=None if d_filter == "All" else d_filter)

            if disp_list:
                ddf = pd.DataFrame(disp_list)
                ddf["status_badge"] = ddf["status"].apply(lambda s: status_badge(str(s)))
                ddf["patient_name"] = ddf.apply(
                    lambda r: f"{r.get('patient_code','') or ''} {r.get('first_name','') or ''} {r.get('last_name','') or ''}".strip() or "Caller",
                    axis=1,
                )
                show_d = ["id", "vehicle_number", "driver_name", "patient_name", "pickup_address", "status_badge", "eta_minutes", "distance_km", "dispatched_at", "completed_at"]
                show_d = [c for c in show_d if c in ddf.columns]
                st.markdown(ddf[show_d].to_html(escape=False, index=False), unsafe_allow_html=True)
                csv_download(ddf, "ambulance_dispatches.csv", "📥 Download Dispatches CSV")
            else:
                st.info("No dispatches matching filter criteria.")

            st.markdown("---")
            st.subheader("🔄 Update Dispatch Status")
            active_calls = [d for d in dispatches if d["status"] not in ("Completed", "Arrived at ED")]

            if active_calls:
                call_map = {d["id"]: f"Call #{d['id']} — {d['vehicle_number']} → {d['pickup_address']} [{d['status']}]" for d in active_calls}
                with st.form("upd_disp_status_form", clear_on_submit=True):
                    sel_call_id = st.selectbox("Select Active Call", list(call_map.keys()), format_func=lambda k: call_map[k])
                    n_status = st.selectbox("New Status", ["En Route to Scene", "On Scene", "Transporting", "Arrived at ED", "Completed"])
                    sub_upd = st.form_submit_button("Update Status", type="primary")
                    if sub_upd:
                        try:
                            res = update_dispatch_status(conn, user, dispatch_id=int(sel_call_id), new_status=n_status)
                            st.success(f"✅ Call #{res['id']} status updated to '{res['status']}'.")
                            st.rerun()
                        except Exception as e:
                            st.error(f"Status update failed: {e}")
            else:
                st.success("🎉 No active ambulance calls requiring status updates.")

        # ---------------- TAB 4: Fleet Management ----------------
        with tab4:
            st.markdown("### 🚐 Ambulance Fleet Management")

            f_df = pd.DataFrame(fleet)
            if len(f_df):
                f_df["status_badge"] = f_df["status"].apply(lambda s: status_badge(str(s)))
                show_f = ["id", "vehicle_number", "driver_name", "driver_phone", "status_badge", "current_location", "lat", "lng"]
                show_f = [c for c in show_f if c in f_df.columns]
                st.markdown(f_df[show_f].to_html(escape=False, index=False), unsafe_allow_html=True)

            st.markdown("---")
            st.subheader("➕ Register New Ambulance")
            with st.form("reg_amb_form", clear_on_submit=True):
                a1, a2 = st.columns(2)
                with a1:
                    v_num = st.text_input("Vehicle Number *", value="AMB-106")
                    d_name = st.text_input("Driver Full Name *", value="John Vance")
                with a2:
                    d_phone = st.text_input("Driver Phone Number", value="+1 555-0199")
                    c_loc = st.text_input("Initial Location", value="Base Station")
                sub_reg_amb = st.form_submit_button("Register Ambulance", type="primary")
                if sub_reg_amb:
                    if not v_num.strip() or not d_name.strip():
                        st.error("Vehicle number and driver name are required.")
                    else:
                        try:
                            res = create_ambulance(conn, user, vehicle_number=v_num, driver_name=d_name, driver_phone=d_phone, current_location=c_loc)
                            st.success(f"✅ Ambulance {res['vehicle_number']} registered successfully!")
                            st.rerun()
                        except Exception as e:
                            st.error(f"Registration failed: {e}")

except Exception as e:
    st.error(f"Ambulance page error: {e}")
