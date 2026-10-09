from __future__ import annotations

import sqlite3
from typing import Any, Optional

from .audit import log_action
from .permissions import require_role, can_manage_or, can_approve_schedule


def list_operating_rooms(
    conn: sqlite3.Connection,
    dept_id: Optional[int] = None,
) -> list[dict[str, Any]]:
    """List operating rooms, optionally filtered by department.

    Args:
        conn: SQLite connection.
        dept_id: Optional department filter.

    Returns:
        List of OR dicts.
    """
    q = "SELECT * FROM operating_rooms WHERE 1=1"
    params: list[Any] = []
    if dept_id is not None:
        q += " AND department_id = ?"
        params.append(int(dept_id))
    q += " ORDER BY id"
    rows = conn.execute(q, params).fetchall()
    return [dict(r) for r in rows]


def _has_overlap(
    conn: sqlite3.Connection,
    or_id: int,
    planned_start: str,
    planned_end: str,
    exclude_sched_id: Optional[int] = None,
) -> bool:
    """Return True if another non-Cancelled OR booking overlaps this range."""
    q = """
        SELECT id FROM or_schedules
        WHERE or_id = ? AND status != 'Cancelled'
          AND planned_start < ? AND planned_end > ?
    """
    params: list[Any] = [int(or_id), planned_end, planned_start]
    if exclude_sched_id is not None:
        q += " AND id != ?"
        params.append(int(exclude_sched_id))
    row = conn.execute(q, params).fetchone()
    return row is not None


def book_or_procedure(
    conn: sqlite3.Connection,
    user: Optional[dict[str, Any]],
    or_id: int,
    patient_id: int,
    procedure_name: str,
    procedure_type: str,
    planned_start_iso: str,
    planned_end_iso: str,
    estimated_min: int,
    assigned_doctor_id: int,
) -> dict[str, Any]:
    """Book a procedure in an operating room with status='Draft' and requires_approval=1.

    Performs conflict check against overlapping non-Cancelled bookings.

    Args:
        conn: SQLite connection.
        user: Actor user (Admin or Doctor).
        or_id: Operating room id.
        patient_id: Patient id.
        procedure_name: Procedure name.
        procedure_type: Procedure type/category.
        planned_start_iso: Planned start ISO timestamp.
        planned_end_iso: Planned end ISO timestamp.
        estimated_min: Estimated duration in minutes.
        assigned_doctor_id: Assigned doctor (users.id) or doctor.id-compatible; stored as-is.

    Returns:
        Inserted or_schedule dict.

    Raises:
        PermissionError_: If user is not Admin or Doctor.
        ValueError: On missing fields, invalid range, or overlapping conflict.
    """
    require_role(user, ["Admin", "Doctor"])
    if not or_id or not patient_id or not procedure_name:
        raise ValueError("or_id, patient_id, procedure_name are required")
    if not planned_start_iso or not planned_end_iso:
        raise ValueError("planned_start_iso and planned_end_iso are required")
    if planned_end_iso <= planned_start_iso:
        raise ValueError("planned_end_iso must be after planned_start_iso")
    or_row = conn.execute("SELECT id FROM operating_rooms WHERE id=?", (int(or_id),)).fetchone()
    if not or_row:
        raise ValueError(f"OR id {or_id} not found")
    if _has_overlap(conn, int(or_id), planned_start_iso, planned_end_iso):
        raise ValueError(f"OR id {or_id} has an overlapping booking in the requested time range")
    try:
        conn.execute("BEGIN IMMEDIATE")
        cur = conn.cursor()
        cur.execute(
            """INSERT INTO or_schedules(
                or_id,patient_id,procedure_name,procedure_type,planned_start,planned_end,
                estimated_duration_min,assigned_doctor_id,status,requires_approval
            ) VALUES(?,?,?,?,?,?,?,?,?,?)""",
            (
                int(or_id), int(patient_id), str(procedure_name)[:200], str(procedure_type or "")[:100],
                planned_start_iso, planned_end_iso,
                int(estimated_min or 0), int(assigned_doctor_id) if assigned_doctor_id else None,
                "Draft", 1,
            ),
        )
        sched_id = int(cur.lastrowid or 0)
        log_action(
            conn,
            int(user["id"]) if user else None,
            user.get("role") if user else None,
            "CREATE",
            "or_schedule",
            str(sched_id),
            {
                "or_id": int(or_id),
                "patient_id": int(patient_id),
                "procedure_name": procedure_name,
                "planned_start": planned_start_iso,
                "planned_end": planned_end_iso,
                "estimated_min": int(estimated_min or 0),
            },
        )
        conn.execute("COMMIT")
    except Exception as exc:
        conn.execute("ROLLBACK")
        raise exc
    row = conn.execute("SELECT * FROM or_schedules WHERE id=?", (sched_id,)).fetchone()
    return dict(row)


def approve_or_schedule(
    conn: sqlite3.Connection,
    user: Optional[dict[str, Any]],
    or_sched_id: int,
) -> dict[str, Any]:
    """Approve an OR schedule. Status transitions Draft -> Approved -> Confirmed.

    Args:
        conn: SQLite connection.
        user: Actor user (Admin).
        or_sched_id: OR schedule id.

    Returns:
        Updated or_schedule dict.

    Raises:
        PermissionError_: If user is not Admin.
        ValueError: If the schedule does not exist.
    """
    require_role(user, "Admin")
    row = conn.execute("SELECT * FROM or_schedules WHERE id=?", (int(or_sched_id),)).fetchone()
    if not row:
        raise ValueError(f"OR schedule id {or_sched_id} not found")
    current = str(row["status"] or "Draft")
    if current == "Draft":
        new_status = "Approved"
    elif current == "Approved":
        new_status = "Confirmed"
    else:
        new_status = current
    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            """UPDATE or_schedules SET status=?, requires_approval=?, approved_by=?, approved_at=datetime('now')
               WHERE id=?""",
            (new_status, 0 if new_status != "Draft" else 1, int(user["id"]) if user else None, int(or_sched_id)),
        )
        log_action(
            conn,
            int(user["id"]) if user else None,
            user.get("role") if user else None,
            "UPDATE",
            "or_schedule",
            str(or_sched_id),
            {"old_status": current, "new_status": new_status},
        )
        conn.execute("COMMIT")
    except Exception as exc:
        conn.execute("ROLLBACK")
        raise exc
    updated = conn.execute("SELECT * FROM or_schedules WHERE id=?", (int(or_sched_id),)).fetchone()
    return dict(updated)


def list_or_schedule(
    conn: sqlite3.Connection,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
) -> list[dict[str, Any]]:
    """List OR schedules within an inclusive date range, ordered by start.

    Args:
        conn: SQLite connection.
        date_from: Optional start date (YYYY-MM-DD or ISO).
        date_to: Optional end date (YYYY-MM-DD or ISO).

    Returns:
        List of or_schedule dicts.
    """
    q = "SELECT * FROM or_schedules WHERE 1=1"
    params: list[Any] = []
    if date_from:
        q += " AND date(planned_start) >= date(?)"
        params.append(date_from)
    if date_to:
        q += " AND date(planned_start) <= date(?)"
        params.append(date_to)
    q += " ORDER BY planned_start ASC, id ASC"
    rows = conn.execute(q, params).fetchall()
    return [dict(r) for r in rows]
