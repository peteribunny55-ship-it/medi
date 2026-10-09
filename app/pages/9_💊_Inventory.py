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

user = page_requires_role(["Admin", "InventoryManager"])
apply_custom_css()

st.title("💊 Inventory Management")
disclaimer_banner()

try:
    with get_db() as conn:
        from app.core.inventory import list_items, scan_low_stock_and_expiry
        alerts = scan_low_stock_and_expiry(conn)
        low_count = len(alerts["low_stock"])
        expiry_count = len(alerts["near_expiry"])
        k1, k2, k3, k4 = st.columns(4)
        from app.utils.ui import metric_card
        all_items = list_items(conn)
        total_skus = len(all_items)
        total_qty = sum(int(i.get("quantity", 0) or 0) for i in all_items)
        with k1: metric_card("Total SKUs", total_skus, icon="📦", variant="info")
        with k2: metric_card("Stock on Hand", total_qty, icon="📊", variant="info")
        with k3: metric_card("Low Stock", low_count, icon="⚠️", variant="alert")
        with k4: metric_card("Near Expiry", expiry_count, icon="⏰", variant="warn")

        if low_count or expiry_count:
            st.warning(f"⚠ Inventory alerts: {low_count} low-stock items, {expiry_count} near-expiry items.")

        tab1, tab2, tab3 = st.tabs(["📦 Items List", "↔️ Stock Movement", "📊 Alerts & History"])

        with tab1:
            st.markdown("### Inventory Items")
            c1, c2, c3, c4 = st.columns(4)
            with c1:
                kw = st.text_input("Search (name/SKU/category/supplier)", "")
            with c2:
                cats = conn.execute("SELECT DISTINCT category FROM inventory_items WHERE category IS NOT NULL ORDER BY category").fetchall()
                cat_list = [""] + [r["category"] for r in cats if r["category"]]
                fcat = st.selectbox("Category", cat_list, index=0)
            with c3:
                flow = st.checkbox("Only Low Stock", value=False)
            with c4:
                fexp = st.checkbox("Only Near Expiry (14d)", value=False)

            items = list_items(
                conn,
                category=(fcat or None),
                low_stock=flow,
                near_expiry_days=(14 if fexp else None),
                keyword=kw or "",
            )
            idf = pd.DataFrame(items)
            if len(idf):
                idf["alert"] = idf.apply(
                    lambda r:
                        ("LowStock" if int(r.get("quantity", 0) or 0) <= int(r.get("reorder_threshold", 0) or 0) else "") +
                        (" + Expiry" if r.get("expiry_date") and pd.to_datetime(r["expiry_date"]) <= (pd.Timestamp.now() + pd.Timedelta(days=14)) else ""),
                    axis=1,
                )
                idf["status"] = idf["alert"].apply(
                    lambda a: status_badge("Low Stock") if "LowStock" in a else
                              (status_badge("Available") if not a else status_badge("Maintenance"))
                )
                idf["alert_badge"] = idf["alert"].apply(
                    lambda a: f'<span class="live-badge sim">ALERT: {a}</span>' if a else '<span class="live-badge live">OK</span>'
                )
                show = ["sku", "name", "category", "unit", "quantity", "reorder_threshold",
                        "expiry_date", "supplier", "alert_badge"]
                show = [c for c in show if c in idf.columns]
                st.dataframe(idf[show], use_container_width=True, hide_index=True)
                csv_download(idf, "inventory_items.csv", "📥 Download Inventory CSV")
            else:
                st.info("No items matching criteria.")

        with tab2:
            st.markdown("### Stock Movement (Add / Consume)")
            item_opts = {int(r["id"]): f"{r['sku']} — {r['name']} (Qty: {r.get('quantity',0)} {r.get('unit','unit')})" for r in all_items}
            with st.form("stock_move_form", clear_on_submit=True):
                m1, m2 = st.columns(2)
                with m1:
                    mi = st.selectbox("Item", list(item_opts.keys()), format_func=lambda k: item_opts[k], index=0 if item_opts else 0)
                    mtype = st.radio("Movement Type", ["Restock (+)", "Dispense (-)"], horizontal=True)
                    mqty = st.number_input("Quantity", min_value=1, step=1, value=1)
                with m2:
                    mreason = st.text_input("Reason")
                    mref = st.text_input("Reference No (PO / Order)")
                sm = st.form_submit_button("Record Movement", type="primary")
                if sm:
                    if not item_opts:
                        st.error("No items available.")
                    else:
                        try:
                            from app.core.inventory import add_stock, consume_stock
                            if mtype.startswith("Restock"):
                                add_stock(conn, user, int(mi), int(mqty), mreason or "Restock", mref or None)
                            else:
                                consume_stock(conn, user, int(mi), int(mqty), mreason or "Dispense", mref or None)
                            st.success("✅ Stock movement recorded.")
                            st.rerun()
                        except Exception as e:
                            st.error(f"Movement failed: {e}")
            st.markdown("#### Recent Movements")
            from app.core.inventory import list_movements
            moves = list_movements(conn, limit=100)
            mdf = pd.DataFrame(moves)
            if len(mdf):
                mdf["item_sku"] = mdf["item_id"].map({int(r["id"]): r["sku"] for r in all_items}).fillna("?")
                mdf["item_name"] = mdf["item_id"].map({int(r["id"]): r["name"] for r in all_items}).fillna("?")
                show = ["id", "item_sku", "item_name", "quantity_delta", "movement_type", "reason", "reference_no", "created_at"]
                show = [c for c in show if c in mdf.columns]
                st.dataframe(mdf[show], use_container_width=True, hide_index=True)
                csv_download(mdf, "stock_movements.csv", "📥 Download Movements CSV")
            else:
                st.info("No stock movements recorded.")

        with tab3:
            st.markdown("### Low Stock & Near-Expiry Alerts")
            a1, a2 = st.columns(2)
            with a1:
                st.markdown("#### Low Stock Items (Qty ≤ Threshold)")
                ld = pd.DataFrame(alerts["low_stock"])
                if len(ld):
                    st.dataframe(ld[["sku", "name", "category", "quantity", "reorder_threshold", "unit"]], use_container_width=True, hide_index=True)
                else:
                    st.success("✅ No low-stock items.")
            with a2:
                st.markdown("#### Near-Expiry Items (Within 14 days)")
                nd = pd.DataFrame(alerts["near_expiry"])
                if len(nd):
                    st.dataframe(nd[["sku", "name", "category", "expiry_date", "quantity"]], use_container_width=True, hide_index=True)
                else:
                    st.success("✅ No near-expiry items.")
except Exception as e:
    st.error(f"Inventory page error: {e}")
