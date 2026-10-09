from __future__ import annotations

import sqlite3
from typing import Any, Optional

from .audit import log_action
from .permissions import require_role, can_manage_inventory, can_view_inventory
from .notifications import _deduped_push_for_role


def create_item(
    conn: sqlite3.Connection,
    user: Optional[dict[str, Any]],
    sku: str,
    name: str,
    category: str,
    unit: str = "unit",
    quantity: int = 0,
    reorder_threshold: int = 10,
    expiry_date: Optional[str] = None,
    maintenance_date: Optional[str] = None,
    supplier: Optional[str] = None,
) -> dict[str, Any]:
    """Create a new inventory item.

    Args:
        conn: SQLite connection.
        user: Actor user (Admin or InventoryManager).
        sku: Unique stock-keeping unit code.
        name: Item display name.
        category: Category string.
        unit: Unit label, default 'unit'.
        quantity: Initial quantity on hand.
        reorder_threshold: Trigger low-stock alert at/below this qty.
        expiry_date: Optional expiry date.
        maintenance_date: Optional next maintenance date.
        supplier: Optional supplier name.

    Returns:
        Inserted item dict.

    Raises:
        PermissionError_: If user cannot manage inventory.
        ValueError: On missing fields or duplicate SKU.
    """
    require_role(user, ["Admin", "InventoryManager"])
    if not sku or not name or not category:
        raise ValueError("sku, name, category are required")
    existing = conn.execute("SELECT id FROM inventory_items WHERE sku=?", (str(sku),)).fetchone()
    if existing:
        raise ValueError(f"SKU '{sku}' already exists")
    try:
        conn.execute("BEGIN IMMEDIATE")
        cur = conn.cursor()
        cur.execute(
            """INSERT INTO inventory_items(
                sku,name,category,unit,quantity,reorder_threshold,expiry_date,maintenance_date,supplier
            ) VALUES(?,?,?,?,?,?,?,?,?)""",
            (
                str(sku)[:64], str(name)[:200], str(category)[:100],
                str(unit or "unit")[:32], int(quantity or 0),
                int(reorder_threshold or 0),
                str(expiry_date)[:10] if expiry_date else None,
                str(maintenance_date)[:10] if maintenance_date else None,
                str(supplier)[:200] if supplier else None,
            ),
        )
        item_id = int(cur.lastrowid or 0)
        log_action(
            conn,
            int(user["id"]) if user else None,
            user.get("role") if user else None,
            "CREATE",
            "inventory_item",
            str(item_id),
            {"sku": str(sku), "name": str(name), "category": str(category), "qty": int(quantity or 0)},
        )
        conn.execute("COMMIT")
    except Exception as exc:
        conn.execute("ROLLBACK")
        raise exc
    row = conn.execute("SELECT * FROM inventory_items WHERE id=?", (item_id,)).fetchone()
    return dict(row)


def update_item(
    conn: sqlite3.Connection,
    user: Optional[dict[str, Any]],
    item_id: int,
    **fields: Any,
) -> dict[str, Any]:
    """Update editable fields of an inventory item.

    Args:
        conn: SQLite connection.
        user: Actor user (Admin or InventoryManager).
        item_id: Item id.
        **fields: Keys to update: name, category, unit, reorder_threshold,
                  expiry_date, maintenance_date, supplier, location, min_order_qty.

    Returns:
        Updated item dict.

    Raises:
        PermissionError_: If user cannot manage inventory.
        ValueError: If item not found or sku (read-only) in fields.
    """
    require_role(user, ["Admin", "InventoryManager"])
    if "sku" in fields:
        raise ValueError("sku is read-only")
    if "quantity" in fields:
        raise ValueError("quantity must be changed via add_stock/consume_stock")
    allowed = {
        "name", "category", "unit", "reorder_threshold",
        "expiry_date", "maintenance_date", "supplier",
        "location", "min_order_qty",
    }
    changes = {k: v for k, v in fields.items() if k in allowed}
    if not changes:
        row = conn.execute("SELECT * FROM inventory_items WHERE id=?", (int(item_id),)).fetchone()
        if not row:
            raise ValueError(f"item id {item_id} not found")
        return dict(row)
    row = conn.execute("SELECT * FROM inventory_items WHERE id=?", (int(item_id),)).fetchone()
    if not row:
        raise ValueError(f"item id {item_id} not found")
    sets = ", ".join(f"{k}=?" for k in changes.keys())
    vals = list(changes.values()) + [int(item_id)]
    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(f"UPDATE inventory_items SET {sets} WHERE id=?", vals)
        log_action(
            conn,
            int(user["id"]) if user else None,
            user.get("role") if user else None,
            "UPDATE",
            "inventory_item",
            str(item_id),
            dict(changes),
        )
        conn.execute("COMMIT")
    except Exception as exc:
        conn.execute("ROLLBACK")
        raise exc
    updated = conn.execute("SELECT * FROM inventory_items WHERE id=?", (int(item_id),)).fetchone()
    return dict(updated)


def _movement(
    conn: sqlite3.Connection,
    user: Optional[dict[str, Any]],
    item_id: int,
    qty: int,
    movement_type: str,
    reason: str,
    ref: Optional[str],
) -> dict[str, Any]:
    row = conn.execute("SELECT * FROM inventory_items WHERE id=?", (int(item_id),)).fetchone()
    if not row:
        raise ValueError(f"item id {item_id} not found")
    cur_qty = int(row["quantity"] or 0)
    new_qty = cur_qty + int(qty)
    if movement_type == "Dispense" and new_qty < 0:
        raise ValueError(f"Cannot consume {qty}: only {cur_qty} available")
    cur = conn.cursor()
    cur.execute(
        """INSERT INTO stock_movements(item_id,quantity_delta,movement_type,reason,user_id,reference_no)
           VALUES(?,?,?,?,?,?)""",
        (
            int(item_id), int(qty), str(movement_type)[:32],
            str(reason or "")[:200],
            int(user["id"]) if user else None,
            str(ref)[:100] if ref else None,
        ),
    )
    mv_id = int(cur.lastrowid or 0)
    conn.execute(
        "UPDATE inventory_items SET quantity=? WHERE id=?",
        (new_qty, int(item_id)),
    )
    log_action(
        conn,
        int(user["id"]) if user else None,
        user.get("role") if user else None,
        "UPDATE",
        "inventory_item",
        str(item_id),
        {"quantity_delta": int(qty), "new_quantity": new_qty, "reason": reason, "movement_type": movement_type},
    )
    mv_row = conn.execute("SELECT * FROM stock_movements WHERE id=?", (mv_id,)).fetchone()
    return dict(mv_row)


def add_stock(
    conn: sqlite3.Connection,
    user: Optional[dict[str, Any]],
    item_id: int,
    qty: int,
    reason: str = "Restock",
    ref: Optional[str] = None,
) -> dict[str, Any]:
    """Add stock to an inventory item.

    Args:
        conn: SQLite connection.
        user: Actor user (Admin or InventoryManager).
        item_id: Item id.
        qty: Positive quantity to add.
        reason: Movement reason label, default 'Restock'.
        ref: Optional purchase order / reference number.

    Returns:
        Movement row dict.

    Raises:
        PermissionError_: If user cannot manage inventory.
        ValueError: If qty <= 0 or item not found.
    """
    require_role(user, ["Admin", "InventoryManager"])
    if int(qty) <= 0:
        raise ValueError("qty must be positive")
    try:
        conn.execute("BEGIN IMMEDIATE")
        mv = _movement(conn, user, item_id, int(qty), "Restock", reason, ref)
        conn.execute("COMMIT")
        return mv
    except Exception as exc:
        conn.execute("ROLLBACK")
        raise exc


def consume_stock(
    conn: sqlite3.Connection,
    user: Optional[dict[str, Any]],
    item_id: int,
    qty: int,
    reason: str = "Dispense",
    ref: Optional[str] = None,
) -> dict[str, Any]:
    """Consume stock from an inventory item (negative delta).

    Args:
        conn: SQLite connection.
        user: Actor user (Admin or InventoryManager).
        item_id: Item id.
        qty: Positive quantity to subtract.
        reason: Movement reason, default 'Dispense'.
        ref: Optional reference id.

    Returns:
        Movement row dict.

    Raises:
        PermissionError_: If user cannot manage inventory.
        ValueError: If qty <= 0, item not found, or would go negative.
    """
    require_role(user, ["Admin", "InventoryManager"])
    if int(qty) <= 0:
        raise ValueError("qty must be positive")
    try:
        conn.execute("BEGIN IMMEDIATE")
        mv = _movement(conn, user, item_id, -int(qty), "Dispense", reason, ref)
        conn.execute("COMMIT")
        return mv
    except Exception as exc:
        conn.execute("ROLLBACK")
        raise exc


def list_items(
    conn: sqlite3.Connection,
    category: Optional[str] = None,
    low_stock: bool = False,
    near_expiry_days: Optional[int] = None,
    keyword: str = "",
) -> list[dict[str, Any]]:
    """List inventory items with filters.

    Args:
        conn: SQLite connection.
        category: Optional exact category filter.
        low_stock: If True, only items with quantity <= reorder_threshold.
        near_expiry_days: If set, items with expiry_date within next N days (or past).
        keyword: Substring search in name/sku/category/supplier.

    Returns:
        List of item dicts.
    """
    q = "SELECT * FROM inventory_items WHERE 1=1"
    params: list[Any] = []
    if category:
        q += " AND category = ?"
        params.append(str(category))
    if low_stock:
        q += " AND quantity <= reorder_threshold"
    if near_expiry_days is not None:
        nd = int(near_expiry_days)
        q += (
            " AND expiry_date IS NOT NULL"
            " AND date(expiry_date) <= date('now', '+' || ? || ' days')"
        )
        params.append(nd)
    if keyword:
        kw = f"%{keyword}%"
        q += " AND (name LIKE ? OR sku LIKE ? OR category LIKE ? OR COALESCE(supplier,'') LIKE ?)"
        params += [kw, kw, kw, kw]
    q += " ORDER BY id DESC"
    rows = conn.execute(q, params).fetchall()
    return [dict(r) for r in rows]


def list_movements(
    conn: sqlite3.Connection,
    item_id: Optional[int] = None,
    limit: int = 200,
) -> list[dict[str, Any]]:
    """List stock movement records.

    Args:
        conn: SQLite connection.
        item_id: Optional item filter.
        limit: Max rows.

    Returns:
        List of movement dicts.
    """
    q = "SELECT * FROM stock_movements WHERE 1=1"
    params: list[Any] = []
    if item_id is not None:
        q += " AND item_id = ?"
        params.append(int(item_id))
    q += " ORDER BY id DESC LIMIT ?"
    params.append(int(limit))
    rows = conn.execute(q, params).fetchall()
    return [dict(r) for r in rows]


def scan_low_stock_and_expiry(
    conn: sqlite3.Connection,
) -> dict[str, list[dict[str, Any]]]:
    """Scan inventory for low-stock and near-expiry items, push deduped notifications to Admin/InventoryManager roles.

    Args:
        conn: SQLite connection.

    Returns:
        Dict with 'low_stock' and 'near_expiry' item lists.
    """
    low_items = list_items(conn, low_stock=True)
    near_items = list_items(conn, near_expiry_days=14)
    try:
        conn.execute("BEGIN IMMEDIATE")
        if low_items:
            title = f"Low stock alert: {len(low_items)} items below reorder threshold"
            msg = (
                f"{len(low_items)} inventory items have quantity <= reorder_threshold. "
                f"Please review stock levels and schedule restocks."
            )
            _deduped_push_for_role(conn, "Admin", "warning", title, msg, {"count": len(low_items)})
            _deduped_push_for_role(conn, "InventoryManager", "warning", title, msg, {"count": len(low_items)})
        if near_items:
            title2 = f"Near-expiry alert: {len(near_items)} items expiring within 14 days"
            msg2 = (
                f"{len(near_items)} items are expiring within 14 days. "
                f"Plan usage, return, or disposal to avoid losses."
            )
            _deduped_push_for_role(conn, "Admin", "warning", title2, msg2, {"count": len(near_items)})
            _deduped_push_for_role(conn, "InventoryManager", "warning", title2, msg2, {"count": len(near_items)})
        conn.execute("COMMIT")
    except Exception as exc:
        conn.execute("ROLLBACK")
        raise exc
    return {"low_stock": low_items, "near_expiry": near_items}
