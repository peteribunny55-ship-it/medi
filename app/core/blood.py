from __future__ import annotations

import datetime as _dt
import sqlite3
from typing import Any, Optional

from .audit import log_action
from .permissions import require_role

BLOOD_TYPES = ["A+", "A-", "B+", "B-", "AB+", "AB-", "O+", "O-"]


def _now_iso() -> str:
    return _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def ensure_blood_inventory_initialized(conn: sqlite3.Connection) -> None:
    """Ensure all 8 standard blood types exist in blood_inventory table."""
    with conn:
        for bt in BLOOD_TYPES:
            row = conn.execute("SELECT id FROM blood_inventory WHERE blood_type=?", (bt,)).fetchone()
            if not row:
                conn.execute(
                    """INSERT INTO blood_inventory (blood_type, units_available, min_threshold_units, updated_at)
                       VALUES (?, ?, ?, ?)""",
                    (bt, 15 if bt in ("O+", "A+", "B+") else 8, 10, _now_iso()),
                )


def get_blood_inventory(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """Retrieve inventory levels for all blood types with alert statuses."""
    ensure_blood_inventory_initialized(conn)
    rows = conn.execute("SELECT * FROM blood_inventory ORDER BY blood_type").fetchall()
    result = []
    for r in rows:
        d = dict(r)
        avail = int(d.get("units_available", 0))
        thresh = int(d.get("min_threshold_units", 10))
        if avail == 0:
            status = "Critical (Out of Stock)"
            badge = "alert"
        elif avail < thresh:
            status = "Low Stock"
            badge = "warn"
        else:
            status = "Adequate"
            badge = "occup"
        d["status_label"] = status
        d["status_badge"] = badge
        result.append(d)
    return result


def update_blood_stock(
    conn: sqlite3.Connection,
    user: Optional[dict[str, Any]],
    blood_type: str,
    delta_units: int,
    reason: str = "Manual Adjustment",
    in_transaction: bool = False,
) -> dict[str, Any]:
    """Adjust inventory stock units for a specific blood type."""
    require_role(user, ["Admin", "Doctor", "Nurse", "InventoryManager"])
    if blood_type not in BLOOD_TYPES:
        raise ValueError(f"Invalid blood type: {blood_type}")

    ensure_blood_inventory_initialized(conn)
    try:
        if not in_transaction and not conn.in_transaction:
            conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT units_available FROM blood_inventory WHERE blood_type=?",
            (blood_type,),
        ).fetchone()
        curr_qty = int(row["units_available"]) if row else 0
        new_qty = curr_qty + int(delta_units)
        if new_qty < 0:
            raise ValueError(f"Insufficient stock for {blood_type}. Available: {curr_qty}, requested delta: {delta_units}")

        conn.execute(
            "UPDATE blood_inventory SET units_available=?, updated_at=? WHERE blood_type=?",
            (new_qty, _now_iso(), blood_type),
        )
        log_action(
            conn,
            int(user["id"]) if user else None,
            user.get("role") if user else None,
            "UPDATE",
            "blood_inventory",
            blood_type,
            {"old_units": curr_qty, "delta": delta_units, "new_units": new_qty, "reason": reason},
        )
        if not in_transaction and conn.in_transaction:
            conn.execute("COMMIT")
    except Exception as exc:
        if not in_transaction and conn.in_transaction:
            conn.execute("ROLLBACK")
        raise exc

    updated = conn.execute("SELECT * FROM blood_inventory WHERE blood_type=?", (blood_type,)).fetchone()
    return dict(updated)


def set_blood_threshold(
    conn: sqlite3.Connection,
    user: Optional[dict[str, Any]],
    blood_type: str,
    min_threshold: int,
) -> None:
    """Set reorder/alert threshold for blood type."""
    require_role(user, ["Admin", "InventoryManager"])
    if blood_type not in BLOOD_TYPES:
        raise ValueError(f"Invalid blood type: {blood_type}")
    if min_threshold < 0:
        raise ValueError("Threshold cannot be negative")

    conn.execute(
        "UPDATE blood_inventory SET min_threshold_units=?, updated_at=? WHERE blood_type=?",
        (int(min_threshold), _now_iso(), blood_type),
    )


# ---------------- Donors ----------------
def list_donors(
    conn: sqlite3.Connection,
    search: Optional[str] = None,
    blood_type: Optional[str] = None,
    eligibility: Optional[str] = None,
    limit: int = 200,
) -> list[dict[str, Any]]:
    """Query registered blood donors with search and filters."""
    q = "SELECT * FROM blood_donors WHERE 1=1"
    params: list[Any] = []

    if search:
        q += " AND (full_name LIKE ? OR donor_code LIKE ? OR phone LIKE ?)"
        term = f"%{search.strip()}%"
        params.extend([term, term, term])
    if blood_type:
        q += " AND blood_type = ?"
        params.append(blood_type)
    if eligibility:
        q += " AND eligibility_status = ?"
        params.append(eligibility)

    q += " ORDER BY id DESC LIMIT ?"
    params.append(limit)

    rows = conn.execute(q, params).fetchall()
    return [dict(r) for r in rows]


def create_donor(
    conn: sqlite3.Connection,
    user: Optional[dict[str, Any]],
    full_name: str,
    blood_type: str,
    phone: str = "",
    email: str = "",
    last_donated_date: Optional[str] = None,
    eligibility_status: str = "Eligible",
) -> dict[str, Any]:
    """Register a new blood donor."""
    require_role(user, ["Admin", "Doctor", "Nurse", "InventoryManager"])
    if not full_name or not full_name.strip():
        raise ValueError("Full name is required")
    if blood_type not in BLOOD_TYPES:
        raise ValueError(f"Invalid blood type: {blood_type}")

    code = f"BD-{_dt.datetime.now().strftime('%Y%m%d%H%M%S')}-{int(conn.execute('SELECT COUNT(*) FROM blood_donors').fetchone()[0]) + 1}"

    try:
        if not conn.in_transaction:
            conn.execute("BEGIN IMMEDIATE")
        cur = conn.cursor()
        cur.execute(
            """INSERT INTO blood_donors
               (donor_code, full_name, blood_type, phone, email, last_donated_date, eligibility_status, total_donations, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                code,
                full_name.strip(),
                blood_type,
                phone.strip() if phone else None,
                email.strip() if email else None,
                last_donated_date or None,
                eligibility_status,
                1 if last_donated_date else 0,
                _now_iso(),
            ),
        )
        donor_id = int(cur.lastrowid or 0)
        log_action(
            conn,
            int(user["id"]) if user else None,
            user.get("role") if user else None,
            "CREATE",
            "blood_donor",
            str(donor_id),
            {"donor_code": code, "name": full_name, "blood_type": blood_type},
        )
        if conn.in_transaction:
            conn.execute("COMMIT")
    except Exception as exc:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise exc

    row = conn.execute("SELECT * FROM blood_donors WHERE id=?", (donor_id,)).fetchone()
    return dict(row)


def record_donation(
    conn: sqlite3.Connection,
    user: Optional[dict[str, Any]],
    donor_id: int,
    units_donated: int = 1,
    donation_date: Optional[str] = None,
) -> dict[str, Any]:
    """Record a successful donation from a donor and add units to blood bank inventory."""
    require_role(user, ["Admin", "Doctor", "Nurse", "InventoryManager"])
    donor = conn.execute("SELECT * FROM blood_donors WHERE id=?", (int(donor_id),)).fetchone()
    if not donor:
        raise ValueError(f"Donor ID {donor_id} not found")

    b_type = str(donor["blood_type"])
    don_date = donation_date or _dt.date.today().strftime("%Y-%m-%d")

    try:
        if not conn.in_transaction:
            conn.execute("BEGIN IMMEDIATE")
        # Update donor
        curr_donations = int(donor["total_donations"] or 0)
        conn.execute(
            """UPDATE blood_donors
               SET last_donated_date=?, total_donations=?, eligibility_status='Ineligible (Recent Donation)'
               WHERE id=?""",
            (don_date, curr_donations + units_donated, int(donor_id)),
        )

        # Update inventory
        update_blood_stock(
            conn,
            user,
            b_type,
            units_donated,
            reason=f"Donation from Donor {donor['donor_code']} ({donor['full_name']})",
            in_transaction=True,
        )

        log_action(
            conn,
            int(user["id"]) if user else None,
            user.get("role") if user else None,
            "RECORD_DONATION",
            "blood_donor",
            str(donor_id),
            {"donor_code": donor["donor_code"], "units": units_donated, "date": don_date},
        )
        if conn.in_transaction:
            conn.execute("COMMIT")
    except Exception as exc:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise exc

    updated = conn.execute("SELECT * FROM blood_donors WHERE id=?", (int(donor_id),)).fetchone()
    return dict(updated)


# ---------------- Blood Requests ----------------
def list_blood_requests(
    conn: sqlite3.Connection,
    status: Optional[str] = None,
    urgency: Optional[str] = None,
    blood_type: Optional[str] = None,
    limit: int = 200,
) -> list[dict[str, Any]]:
    """Query blood requests."""
    q = """SELECT br.*, p.patient_id AS patient_code, p.first_name, p.last_name, d.name AS dept_name, u.full_name AS requester_name
           FROM blood_requests br
           LEFT JOIN patients p ON p.id = br.patient_id
           LEFT JOIN departments d ON d.id = br.department_id
           LEFT JOIN users u ON u.id = br.requested_by
           WHERE 1=1"""
    params: list[Any] = []

    if status:
        q += " AND br.status = ?"
        params.append(status)
    if urgency:
        q += " AND br.urgency = ?"
        params.append(urgency)
    if blood_type:
        q += " AND br.blood_type = ?"
        params.append(blood_type)

    q += " ORDER BY CASE br.urgency WHEN 'Critical' THEN 1 WHEN 'Urgent' THEN 2 ELSE 3 END, br.id DESC LIMIT ?"
    params.append(limit)

    rows = conn.execute(q, params).fetchall()
    return [dict(r) for r in rows]


def create_blood_request(
    conn: sqlite3.Connection,
    user: Optional[dict[str, Any]],
    patient_id: Optional[int],
    department_id: Optional[int],
    blood_type: str,
    units_requested: int = 1,
    urgency: str = "Routine",
) -> dict[str, Any]:
    """Submit a blood product request for a patient/department."""
    require_role(user, ["Admin", "Doctor", "Nurse"])
    if blood_type not in BLOOD_TYPES:
        raise ValueError(f"Invalid blood type: {blood_type}")
    if units_requested <= 0:
        raise ValueError("Units requested must be greater than 0")

    try:
        if not conn.in_transaction:
            conn.execute("BEGIN IMMEDIATE")
        cur = conn.cursor()
        cur.execute(
            """INSERT INTO blood_requests
               (patient_id, requested_by, department_id, blood_type, units_requested, urgency, status, created_at)
               VALUES (?, ?, ?, ?, ?, ?, 'Requested', ?)""",
            (
                int(patient_id) if patient_id else None,
                int(user["id"]) if user else None,
                int(department_id) if department_id else None,
                blood_type,
                int(units_requested),
                urgency,
                _now_iso(),
            ),
        )
        req_id = int(cur.lastrowid or 0)
        log_action(
            conn,
            int(user["id"]) if user else None,
            user.get("role") if user else None,
            "CREATE",
            "blood_request",
            str(req_id),
            {"blood_type": blood_type, "units": units_requested, "urgency": urgency},
        )
        if conn.in_transaction:
            conn.execute("COMMIT")
    except Exception as exc:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise exc

    row = conn.execute("SELECT * FROM blood_requests WHERE id=?", (req_id,)).fetchone()
    return dict(row)


def fulfill_blood_request(
    conn: sqlite3.Connection,
    user: Optional[dict[str, Any]],
    request_id: int,
) -> dict[str, Any]:
    """Fulfill a blood request by deducting units from blood inventory and updating request status."""
    require_role(user, ["Admin", "Doctor", "Nurse", "InventoryManager"])
    req = conn.execute("SELECT * FROM blood_requests WHERE id=?", (int(request_id),)).fetchone()
    if not req:
        raise ValueError(f"Blood request ID {request_id} not found")
    if str(req["status"]) == "Fulfilled":
        raise ValueError(f"Blood request ID {request_id} is already fulfilled")

    b_type = str(req["blood_type"])
    units = int(req["units_requested"] or 1)

    try:
        if not conn.in_transaction:
            conn.execute("BEGIN IMMEDIATE")
        # Deduct from inventory
        update_blood_stock(
            conn,
            user,
            b_type,
            -units,
            reason=f"Fulfillment of Blood Request #{request_id}",
            in_transaction=True,
        )

        # Mark request as fulfilled
        ful_at = _now_iso()
        conn.execute(
            "UPDATE blood_requests SET status='Fulfilled', fulfilled_at=? WHERE id=?",
            (ful_at, int(request_id)),
        )

        log_action(
            conn,
            int(user["id"]) if user else None,
            user.get("role") if user else None,
            "FULFILL",
            "blood_request",
            str(request_id),
            {"blood_type": b_type, "units": units, "fulfilled_at": ful_at},
        )
        if conn.in_transaction:
            conn.execute("COMMIT")
    except Exception as exc:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise exc

    updated = conn.execute("SELECT * FROM blood_requests WHERE id=?", (int(request_id),)).fetchone()
    return dict(updated)



def get_blood_bank_summary(conn: sqlite3.Connection) -> dict[str, Any]:
    """Get overall KPI stats for the Blood Bank."""
    ensure_blood_inventory_initialized(conn)
    total_units = conn.execute("SELECT COALESCE(SUM(units_available), 0) FROM blood_inventory").fetchone()[0]
    low_types = conn.execute(
        "SELECT COUNT(*) FROM blood_inventory WHERE units_available < min_threshold_units"
    ).fetchone()[0]
    pending_reqs = conn.execute(
        "SELECT COUNT(*) FROM blood_requests WHERE status != 'Fulfilled'"
    ).fetchone()[0]
    total_donors = conn.execute("SELECT COUNT(*) FROM blood_donors").fetchone()[0]
    eligible_donors = conn.execute(
        "SELECT COUNT(*) FROM blood_donors WHERE eligibility_status = 'Eligible'"
    ).fetchone()[0]

    return {
        "total_units": int(total_units),
        "low_types_count": int(low_types),
        "pending_requests": int(pending_reqs),
        "total_donors": int(total_donors),
        "eligible_donors": int(eligible_donors),
    }
