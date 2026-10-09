from __future__ import annotations

import os
import sys

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

import pandas as pd
import streamlit as st

from app.utils.ui import page_requires_role, apply_custom_css, disclaimer_banner, metric_card, status_badge
from app.utils.exporters import csv_download
from app.db.database import get_db
from app.core.blood import (
    BLOOD_TYPES,
    get_blood_bank_summary,
    get_blood_inventory,
    update_blood_stock,
    set_blood_threshold,
    list_donors,
    create_donor,
    record_donation,
    list_blood_requests,
    create_blood_request,
    fulfill_blood_request,
)

user = page_requires_role(["Admin", "Doctor", "Nurse", "InventoryManager"])
apply_custom_css()

st.title("🩸 Blood Bank & Donor Management System")
disclaimer_banner()

try:
    with get_db() as conn:
        summary = get_blood_bank_summary(conn)

        m1, m2, m3, m4 = st.columns(4)
        with m1:
            metric_card("Total Blood Units", summary["total_units"], icon="🩸", variant="occup")
        with m2:
            metric_card("Low / Critical Types", summary["low_types_count"], icon="⚠️", variant="alert" if summary["low_types_count"] > 0 else "info")
        with m3:
            metric_card("Pending Blood Requests", summary["pending_requests"], icon="📋", variant="warn" if summary["pending_requests"] > 0 else "info")
        with m4:
            metric_card("Eligible Donors", f"{summary['eligible_donors']} / {summary['total_donors']}", icon="👥", variant="info")

        tab1, tab2, tab3 = st.tabs(["🩸 Inventory Stock", "👥 Donors Directory", "📋 Blood Requests & Fulfillment"])

        # ---------------- TAB 1: Inventory Stock ----------------
        with tab1:
            st.markdown("### 🩸 Blood Bank Inventory Levels")
            inv_items = get_blood_inventory(conn)

            # Render visual grid of all 8 blood types
            cols = st.columns(4)
            for idx, item in enumerate(inv_items):
                col = cols[idx % 4]
                with col:
                    status_color = "#10B981" if item["status_badge"] == "occup" else ("#F59E0B" if item["status_badge"] == "warn" else "#EF4444")
                    st.markdown(
                        f"""
                        <div style="background-color: #F8FAFC; border: 2px solid {status_color}; border-radius: 10px; padding: 15px; margin-bottom: 15px; text-align: center;">
                            <h2 style="margin: 0; color: #1E293B;">{item['blood_type']}</h2>
                            <div style="font-size: 2rem; font-weight: bold; color: {status_color}; margin: 5px 0;">{item['units_available']} <span style="font-size: 1rem; color: #64748B;">units</span></div>
                            <div style="font-size: 0.85rem; color: #475569;">Reorder Threshold: {item['min_threshold_units']} units</div>
                            <div style="margin-top: 8px;"><span class="live-badge {item['status_badge']}">{item['status_label']}</span></div>
                        </div>
                        """,
                        unsafe_allow_html=True,
                    )

            st.markdown("---")
            c_adj, c_thresh = st.columns(2)

            with c_adj:
                st.subheader("⚡ Stock Adjustment")
                with st.form("adj_stock_form", clear_on_submit=True):
                    b_type = st.selectbox("Blood Group", BLOOD_TYPES)
                    adj_units = st.number_input("Units Delta (+ to Add, - to Deduct)", value=1, step=1)
                    adj_reason = st.text_input("Reason / Reference", value="Manual Stock Count Adjustment")
                    sub_adj = st.form_submit_button("Update Stock", type="primary")
                    if sub_adj:
                        try:
                            res = update_blood_stock(conn, user, b_type, int(adj_units), reason=adj_reason)
                            st.success(f"✅ Updated {b_type} stock. New total: {res['units_available']} units.")
                            st.rerun()
                        except Exception as e:
                            st.error(f"Failed to update stock: {e}")

            with c_thresh:
                st.subheader("⚙️ Reorder Threshold")
                with st.form("thresh_form", clear_on_submit=True):
                    t_type = st.selectbox("Blood Group ", BLOOD_TYPES, key="thresh_b_type")
                    t_val = st.number_input("Minimum Safe Threshold (units)", value=10, min_value=1, step=1)
                    sub_t = st.form_submit_button("Set Threshold")
                    if sub_t:
                        try:
                            set_blood_threshold(conn, user, t_type, int(t_val))
                            st.success(f"✅ Set threshold for {t_type} to {t_val} units.")
                            st.rerun()
                        except Exception as e:
                            st.error(f"Failed to set threshold: {e}")

        # ---------------- TAB 2: Donors Directory ----------------
        with tab2:
            st.markdown("### 👥 Blood Donors Directory")

            f1, f2, f3 = st.columns([2, 1, 1])
            with f1:
                search_term = st.text_input("Search Donors (Name / Code / Phone)", value="")
            with f2:
                filter_bt = st.selectbox("Filter Blood Group", ["All"] + BLOOD_TYPES, index=0)
            with f3:
                filter_elig = st.selectbox("Eligibility Status", ["All", "Eligible", "Ineligible (Recent Donation)"], index=0)

            donors = list_donors(
                conn,
                search=search_term or None,
                blood_type=None if filter_bt == "All" else filter_bt,
                eligibility=None if filter_elig == "All" else filter_elig,
            )

            if donors:
                ddf = pd.DataFrame(donors)
                show_cols = ["donor_code", "full_name", "blood_type", "phone", "email", "last_donated_date", "total_donations", "eligibility_status"]
                show_cols = [c for c in show_cols if c in ddf.columns]
                ddf_disp = ddf[show_cols].copy()
                ddf_disp["eligibility_status"] = ddf_disp["eligibility_status"].apply(
                    lambda s: f'<span class="live-badge {"live" if "Eligible" in str(s) and "Ineligible" not in str(s) else "sim"}">{s}</span>'
                )
                st.markdown(ddf_disp.to_html(escape=False, index=False), unsafe_allow_html=True)
                csv_download(ddf, "blood_donors.csv", "📥 Download Donors CSV")
            else:
                st.info("No blood donors matching filter criteria.")

            st.markdown("---")
            d_col1, d_col2 = st.columns(2)

            with d_col1:
                st.subheader("➕ Register New Donor")
                with st.form("reg_donor_form", clear_on_submit=True):
                    fn = st.text_input("Full Name *")
                    bt = st.selectbox("Blood Type *", BLOOD_TYPES)
                    ph = st.text_input("Phone Number")
                    em = st.text_input("Email")
                    ld = st.date_input("Last Donated Date (Optional)", value=None)
                    sub_reg = st.form_submit_button("Register Donor", type="primary")
                    if sub_reg:
                        if not fn.strip():
                            st.error("Full name is required.")
                        else:
                            try:
                                ld_str = ld.strftime("%Y-%m-%d") if ld else None
                                res = create_donor(
                                    conn, user, full_name=fn, blood_type=bt, phone=ph, email=em, last_donated_date=ld_str
                                )
                                st.success(f"✅ Donor registered successfully! Code: {res['donor_code']}")
                                st.rerun()
                            except Exception as e:
                                st.error(f"Registration failed: {e}")

            with d_col2:
                st.subheader("🩸 Record Donation Event")
                if donors:
                    donor_map = {d["id"]: f"{d['donor_code']} — {d['full_name']} ({d['blood_type']})" for d in donors}
                    with st.form("rec_don_form", clear_on_submit=True):
                        sel_d = st.selectbox("Select Donor", list(donor_map.keys()), format_func=lambda k: donor_map[k])
                        u_don = st.number_input("Units Donated", value=1, min_value=1, max_value=3, step=1)
                        d_date = st.date_input("Donation Date", value=pd.Timestamp.now().date())
                        sub_don = st.form_submit_button("Record Donation", type="primary")
                        if sub_don:
                            try:
                                res = record_donation(
                                    conn, user, donor_id=int(sel_d), units_donated=int(u_don), donation_date=d_date.strftime("%Y-%m-%d")
                                )
                                st.success(f"✅ Recorded {u_don} unit(s) donation for {res['full_name']}. Blood bank inventory updated!")
                                st.rerun()
                            except Exception as e:
                                st.error(f"Failed to record donation: {e}")
                else:
                    st.info("Register a donor first to record donations.")

        # ---------------- TAB 3: Blood Requests ----------------
        with tab3:
            st.markdown("### 📋 Blood Requests & Fulfillment")

            r_col1, r_col2 = st.columns([1, 1])
            with r_col1:
                req_status_filter = st.selectbox("Filter Request Status", ["All", "Requested", "Fulfilled"], index=0)
            with r_col2:
                req_urgency_filter = st.selectbox("Filter Urgency", ["All", "Routine", "Urgent", "Critical"], index=0)

            requests = list_blood_requests(
                conn,
                status=None if req_status_filter == "All" else req_status_filter,
                urgency=None if req_urgency_filter == "All" else req_urgency_filter,
            )

            if requests:
                rdf = pd.DataFrame(requests)
                rdf["urgency_badge"] = rdf["urgency"].apply(
                    lambda u: f'<span class="live-badge {"alert" if u=="Critical" else ("sim" if u=="Urgent" else "live")}">{u}</span>'
                )
                rdf["status_badge"] = rdf["status"].apply(lambda s: status_badge(str(s)))
                rdf["patient_name"] = rdf.apply(
                    lambda r: f"{r.get('patient_code','') or ''} {r.get('first_name','') or ''} {r.get('last_name','') or ''}".strip() or "General Department",
                    axis=1,
                )
                show_r = ["id", "patient_name", "dept_name", "blood_type", "units_requested", "urgency_badge", "status_badge", "created_at", "fulfilled_at"]
                show_r = [c for c in show_r if c in rdf.columns]
                st.markdown(rdf[show_r].to_html(escape=False, index=False), unsafe_allow_html=True)
            else:
                st.info("No blood requests found.")

            st.markdown("---")
            req_c1, req_c2 = st.columns(2)

            with req_c1:
                st.subheader("➕ Submit New Blood Request")
                prows = conn.execute("SELECT id, patient_id, first_name, last_name FROM patients ORDER BY id DESC LIMIT 300").fetchall()
                pat_dict = {int(p["id"]): f"{p['patient_id']} — {p['first_name']} {p['last_name']}" for p in prows}
                dept_rows = conn.execute("SELECT id, name FROM departments ORDER BY name").fetchall()
                dept_dict = {int(d["id"]): d["name"] for d in dept_rows}

                with st.form("new_blood_req_form", clear_on_submit=True):
                    sel_p = st.selectbox("Patient (Optional)", [0] + list(pat_dict.keys()), format_func=lambda k: "General Dept Request" if k == 0 else pat_dict[k])
                    sel_d = st.selectbox("Requesting Department", list(dept_dict.keys()), format_func=lambda k: dept_dict[k], index=0)
                    req_bt = st.selectbox("Blood Group Needed", BLOOD_TYPES)
                    req_u = st.number_input("Units Requested", value=1, min_value=1, max_value=10, step=1)
                    req_urg = st.selectbox("Urgency Level", ["Routine", "Urgent", "Critical"])
                    sub_req = st.form_submit_button("Submit Request", type="primary")
                    if sub_req:
                        try:
                            res = create_blood_request(
                                conn,
                                user,
                                patient_id=None if sel_p == 0 else int(sel_p),
                                department_id=int(sel_d),
                                blood_type=req_bt,
                                units_requested=int(req_u),
                                urgency=req_urg,
                            )
                            st.success(f"✅ Blood request #{res['id']} submitted with urgency '{req_urg}'.")
                            st.rerun()
                        except Exception as e:
                            st.error(f"Request failed: {e}")

            with req_c2:
                st.subheader("✅ Fulfill Pending Blood Request")
                open_reqs = [r for r in requests if r["status"] != "Fulfilled"]
                if open_reqs:
                    req_map = {
                        r["id"]: f"Req #{r['id']} — {r['blood_type']} ({r['units_requested']} units) [{r['urgency']}]"
                        for r in open_reqs
                    }
                    with st.form("ful_blood_req_form", clear_on_submit=True):
                        sel_f_id = st.selectbox("Select Pending Request", list(req_map.keys()), format_func=lambda k: req_map[k])
                        sub_ful = st.form_submit_button("Fulfill & Deduct Stock", type="primary")
                        if sub_ful:
                            try:
                                res = fulfill_blood_request(conn, user, request_id=int(sel_f_id))
                                st.success(f"✅ Request #{res['id']} fulfilled successfully! Inventory updated.")
                                st.rerun()
                            except Exception as e:
                                st.error(f"Fulfillment failed: {e}")
                else:
                    st.success("🎉 All blood requests are currently fulfilled!")

except Exception as e:
    st.error(f"Blood Bank page error: {e}")
