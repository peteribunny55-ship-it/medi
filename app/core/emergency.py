from __future__ import annotations

import sqlite3
from typing import Any, Optional

from .audit import log_action
from .permissions import require_role, can_manage_emergency, can_assign_triage


def _now_iso() -> str:
    import datetime as _dt
    return _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def create_case(
    conn: sqlite3.Connection,
    user: Optional[dict[str, Any]],
    patient_id: int,
    arrival_iso: str,
    triage_level: int,
    complaint: str,
    status: str = "Triage",
    bed_id: Optional[int] = None,
    on_duty_staff_ids: Optional[list[int]] = None,
) -> dict[str, Any]:
    """Create an emergency case as an admissions row with admission_type='Emergency'.

    Args:
        conn: SQLite connection.
        user: Actor user (Admin, Doctor, Nurse).
        patient_id: Patient id.
        arrival_iso: Arrival ISO timestamp.
        triage_level: 1-5 triage level (1 most severe).
        complaint: Chief complaint.
        status: Initial admission status, default 'Triage'.
        bed_id: Optional bed id.
        on_duty_staff_ids: Optional list of on-duty staff user ids (audited, not stored).

    Returns:
        Inserted admissions dict.

    Raises:
        PermissionError_: If user cannot manage emergency.
        ValueError: On missing required fields.
    """
    require_role(user, ["Admin", "Doctor", "Nurse"])
    if not patient_id or not arrival_iso or not triage_level:
        raise ValueError("patient_id, arrival_iso, triage_level are required")
    try:
        tl = int(triage_level)
        if tl < 1 or tl > 5:
            raise ValueError
    except Exception:
        raise ValueError("triage_level must be integer 1..5")
    try:
        conn.execute("BEGIN IMMEDIATE")
        if bed_id is not None:
            bed_row = conn.execute(
                "SELECT id, status FROM beds WHERE id=?",
                (int(bed_id),),
            ).fetchone()
            if not bed_row:
                raise ValueError(f"bed_id {bed_id} not found")
            if str(bed_row["status"]) != "Available":
                raise ValueError(f"bed_id {bed_id} is not Available")
            conn.execute(
                "UPDATE beds SET status='Occupied', current_patient_id=? WHERE id=?",
                (int(patient_id), int(bed_id)),
            )
        cur = conn.cursor()
        cur.execute(
            """INSERT INTO admissions(patient_id,bed_id,admitted_at,status,admission_type,triage_level,diagnosis)
               VALUES(?,?,?,?,?,?,?)""",
            (
                int(patient_id), int(bed_id) if bed_id else None,
                arrival_iso, str(status)[:32], "Emergency", tl, str(complaint or "")[:2000],
            ),
        )
        adm_id = int(cur.lastrowid or 0)
        log_action(
            conn,
            int(user["id"]) if user else None,
            user.get("role") if user else None,
            "CREATE",
            "emergency_case",
            str(adm_id),
            {
                "patient_id": int(patient_id),
                "triage_level": tl,
                "bed_id": bed_id,
                "arrival": arrival_iso,
                "complaint": complaint,
                "on_duty_staff_ids": list(on_duty_staff_ids or []),
            },
        )
        conn.execute("COMMIT")
    except Exception as exc:
        conn.execute("ROLLBACK")
        raise exc
    row = conn.execute("SELECT * FROM admissions WHERE id=?", (adm_id,)).fetchone()
    return dict(row)


def live_capacity(
    conn: sqlite3.Connection,
) -> dict[str, Any]:
    """Compute emergency department live capacity snapshot.

    Args:
        conn: SQLite connection.

    Returns:
        Dict with keys:
            emergency_beds_available: count of Available beds in dept_id 6 / Emergency ward
            on_duty_staff_count: count of staff records linked to users currently active
                (heuristic: count of all staff in departments 1/6 by default)
            active_emergencies: admissions of type Emergency not Discharged
    """
    beds_row = conn.execute(
        """
        SELECT COUNT(*) AS c FROM beds b
        LEFT JOIN departments d ON d.id = b.department_id
        WHERE b.status='Available'
          AND (b.ward = 'Emergency' OR d.name LIKE '%Emergency%' OR b.department_id=6)
        """,
    ).fetchone()
    staff_row = conn.execute(
        "SELECT COUNT(*) AS c FROM staff s WHERE s.department_id IN (1,6)",
    ).fetchone()
    active_row = conn.execute(
        "SELECT COUNT(*) AS c FROM admissions WHERE admission_type='Emergency' AND status != 'Discharged'",
    ).fetchone()
    return {
        "emergency_beds_available": int(beds_row["c"] if beds_row else 0),
        "on_duty_staff_count": int(staff_row["c"] if staff_row else 0),
        "active_emergencies": int(active_row["c"] if active_row else 0),
    }


def _forecast_next_24h(conn: sqlite3.Connection) -> int:
    """Heuristic forecast: average emergencies per day last 7 days, rounded."""
    row = conn.execute(
        """
        SELECT COALESCE(AVG(daily),0) AS avg FROM (
            SELECT date(admitted_at) AS dy, COUNT(*) AS daily
            FROM admissions
            WHERE admission_type='Emergency'
              AND date(admitted_at) >= date('now','-7 days')
            GROUP BY date(admitted_at)
        )
        """,
    ).fetchone()
    import math
    return int(math.ceil(float(row["avg"]) if row else 0.0))


def surge_alert(
    conn: sqlite3.Connection,
    dept_id: int = 6,
) -> bool:
    """Return True if active + 24h forecast exceeds capacity threshold.

    Threshold is computed as: available emergency beds + on-duty staff * 3.

    Args:
        conn: SQLite connection.
        dept_id: Department id (default 6 for Emergency).

    Returns:
        True if surge condition triggered, else False.
    """
    lc = live_capacity(conn)
    threshold = int(lc["emergency_beds_available"]) + int(lc["on_duty_staff_count"]) * 3
    if threshold <= 0:
        return False
    forecast = _forecast_next_24h(conn)
    total = int(lc["active_emergencies"]) + forecast
    _ = dept_id
    return total > threshold


def list_cases(
    conn: sqlite3.Connection,
    status: Optional[str] = None,
    limit: int = 200,
) -> list[dict[str, Any]]:
    """List emergency admissions (admission_type='Emergency').

    Args:
        conn: SQLite connection.
        status: Optional status filter.
        limit: Maximum rows.

    Returns:
        List of admissions dicts.
    """
    q = "SELECT * FROM admissions WHERE admission_type='Emergency'"
    params: list[Any] = []
    if status:
        q += " AND status = ?"
        params.append(str(status))
    q += " ORDER BY id DESC LIMIT ?"
    params.append(int(limit))
    rows = conn.execute(q, params).fetchall()
    return [dict(r) for r in rows]


def set_case_status(
    conn: sqlite3.Connection,
    user: Optional[dict[str, Any]],
    admission_id: int,
    status: str,
    notes: Optional[str] = None,
) -> dict[str, Any]:
    """Update emergency case admission status. On Discharged, free the bed.

    Args:
        conn: SQLite connection.
        user: Actor user (Admin, Doctor, Nurse).
        admission_id: Admission id.
        status: New status (Triage, Admitted, InTreatment, DischargePending, Discharged, ...).
        notes: Optional notes stored to diagnosis column tail (audit only; row unchanged).

    Returns:
        Updated admissions dict.

    Raises:
        PermissionError_: If user cannot manage emergency.
        ValueError: If admission not found.
    """
    require_role(user, ["Admin", "Doctor", "Nurse"])
    row = conn.execute(
        "SELECT * FROM admissions WHERE id=? AND admission_type='Emergency'",
        (int(admission_id),),
    ).fetchone()
    if not row:
        raise ValueError(f"Emergency admission id {admission_id} not found")
    old_status = str(row["status"] or "")
    new_status = str(status)
    try:
        conn.execute("BEGIN IMMEDIATE")
        if new_status == "Discharged":
            discharged_at = _now_iso()
            conn.execute(
                "UPDATE admissions SET status=?, discharged_at=? WHERE id=?",
                (new_status, discharged_at, int(admission_id)),
            )
            if int(row["bed_id"] or 0):
                conn.execute(
                    "UPDATE beds SET status='Available', current_patient_id=NULL WHERE id=?",
                    (int(row["bed_id"]),),
                )
        else:
            conn.execute(
                "UPDATE admissions SET status=? WHERE id=?",
                (new_status, int(admission_id)),
            )
        log_action(
            conn,
            int(user["id"]) if user else None,
            user.get("role") if user else None,
            "UPDATE",
            "emergency_case",
            str(admission_id),
            {"old_status": old_status, "new_status": new_status, "notes": notes},
        )
        conn.execute("COMMIT")
    except Exception as exc:
        conn.execute("ROLLBACK")
        raise exc
    updated = conn.execute("SELECT * FROM admissions WHERE id=?", (int(admission_id),)).fetchone()
    return dict(updated)
