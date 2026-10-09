from __future__ import annotations

import sqlite3
from datetime import datetime
from typing import Any, Optional

from .audit import log_action
from .permissions import require_role, can_request_lab, can_update_lab


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _minutes_between(a_str: str, b_str: str) -> int:
    try:
        a = datetime.strptime(a_str[:19], "%Y-%m-%d %H:%M:%S")
        b = datetime.strptime(b_str[:19], "%Y-%m-%d %H:%M:%S")
    except Exception:
        return 0
    diff = (b - a).total_seconds() / 60.0
    return int(round(diff))


_ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    "Requested": {"InProgress", "Cancelled", "Collected"},
    "Collected": {"InProgress", "Cancelled"},
    "InProgress": {"Completed", "Cancelled"},
    "Cancelled": set(),
    "Completed": set(),
}


def create_request(
    conn: sqlite3.Connection,
    user: Optional[dict[str, Any]],
    patient_id: int,
    test_type: str,
    test_category: str = "",
    priority: str = "Routine",
) -> dict[str, Any]:
    """Create a new lab request with status='Requested'.

    Args:
        conn: SQLite connection.
        user: Actor user (Admin, Doctor, Nurse).
        patient_id: Patient id.
        test_type: Test type/name (e.g. 'CBC', 'X-Ray').
        test_category: Optional category (e.g. 'Hematology', 'Radiology').
        priority: 'Routine' or 'Stat'.

    Returns:
        Inserted lab request dict.

    Raises:
        PermissionError_: If user cannot request lab.
        ValueError: On missing required fields.
    """
    require_role(user, ["Admin", "Doctor", "Nurse"])
    if not patient_id or not test_type:
        raise ValueError("patient_id, test_type are required")
    ordered_at = _now()
    try:
        conn.execute("BEGIN IMMEDIATE")
        cur = conn.cursor()
        cur.execute(
            """INSERT INTO lab_requests(
                patient_id,test_type,test_category,requested_by,ordered_at,status,priority
            ) VALUES(?,?,?,?,?,?,?)""",
            (
                int(patient_id), str(test_type)[:200], str(test_category or "")[:100],
                int(user["id"]) if user else None,
                ordered_at, "Requested", str(priority or "Routine")[:32],
            ),
        )
        req_id = int(cur.lastrowid or 0)
        log_action(
            conn,
            int(user["id"]) if user else None,
            user.get("role") if user else None,
            "CREATE",
            "lab_request",
            str(req_id),
            {
                "patient_id": int(patient_id),
                "test_type": str(test_type),
                "test_category": str(test_category or ""),
                "priority": str(priority or "Routine"),
            },
        )
        conn.execute("COMMIT")
    except Exception as exc:
        conn.execute("ROLLBACK")
        raise exc
    row = conn.execute("SELECT * FROM lab_requests WHERE id=?", (req_id,)).fetchone()
    return dict(row)


def update_status(
    conn: sqlite3.Connection,
    user: Optional[dict[str, Any]],
    request_id: int,
    new_status: str,
    result_note: Optional[str] = None,
) -> dict[str, Any]:
    """Transition a lab request status. On Completed, store resulted_at and turnaround_minutes.

    Args:
        conn: SQLite connection.
        user: Actor user (Admin, Nurse, Doctor).
        request_id: Lab request id.
        new_status: One of Requested -> Collected -> InProgress -> Completed/Cancelled.
        result_note: Optional result notes, applied if status is Completed.

    Returns:
        Updated lab request dict.

    Raises:
        PermissionError_: If user cannot update lab.
        ValueError: If request not found or invalid transition.
    """
    require_role(user, ["Admin", "Doctor", "Nurse"])
    row = conn.execute("SELECT * FROM lab_requests WHERE id=?", (int(request_id),)).fetchone()
    if not row:
        raise ValueError(f"lab request id {request_id} not found")
    current = str(row["status"] or "")
    if new_status not in _ALLOWED_TRANSITIONS.get(current, set()) and new_status != current:
        raise ValueError(f"Invalid transition from {current} to {new_status}")
    try:
        conn.execute("BEGIN IMMEDIATE")
        updates = ["status=?"]
        vals: list[Any] = [new_status]
        if new_status == "Completed":
            now = _now()
            updates.append("resulted_at=?")
            vals.append(now)
            updates.append("turnaround_minutes=?")
            vals.append(_minutes_between(str(row["ordered_at"]), now))
            if result_note is not None:
                updates.append("result_note=?")
                vals.append(str(result_note))
        if new_status == "Collected" and not row["picked_up_at"]:
            updates.append("picked_up_at=?")
            vals.append(_now())
        vals.append(int(request_id))
        conn.execute(f"UPDATE lab_requests SET {', '.join(updates)} WHERE id=?", vals)
        log_action(
            conn,
            int(user["id"]) if user else None,
            user.get("role") if user else None,
            "UPDATE",
            "lab_request",
            str(request_id),
            {"old_status": current, "new_status": new_status},
        )
        conn.execute("COMMIT")
    except Exception as exc:
        conn.execute("ROLLBACK")
        raise exc
    updated = conn.execute("SELECT * FROM lab_requests WHERE id=?", (int(request_id),)).fetchone()
    return dict(updated)


def list_requests(
    conn: sqlite3.Connection,
    patient_id: Optional[int] = None,
    status: Optional[str] = None,
    dept_id: Optional[int] = None,
    delayed_only: bool = False,
    threshold_min: int = 1440,
    limit: int = 500,
) -> list[dict[str, Any]]:
    """List lab requests with filters and optional delayed flag.

    A request is flagged delayed if status in (Requested, InProgress) and
    now() - ordered_at > threshold_min minutes.

    Args:
        conn: SQLite connection.
        patient_id: Optional patient filter.
        status: Optional status filter.
        dept_id: Optional department filter (via requesting user.department_id).
        delayed_only: If True, only return rows flagged delayed.
        threshold_min: Minutes before flagging delayed, default 1440 (24h).
        limit: Max rows.

    Returns:
        List of lab request dicts with a 'delayed' boolean key appended.
    """
    q = """
        SELECT lr.*, u.department_id AS requester_dept_id
        FROM lab_requests lr
        LEFT JOIN users u ON u.id = lr.requested_by
        WHERE 1=1
    """
    params: list[Any] = []
    if patient_id is not None:
        q += " AND lr.patient_id = ?"
        params.append(int(patient_id))
    if status:
        q += " AND lr.status = ?"
        params.append(str(status))
    if dept_id is not None:
        q += " AND u.department_id = ?"
        params.append(int(dept_id))
    q += " ORDER BY lr.id DESC LIMIT ?"
    params.append(int(limit))
    rows = conn.execute(q, params).fetchall()
    now_str = _now()
    out: list[dict[str, Any]] = []
    for r in rows:
        d = dict(r)
        ordered_at = str(d.get("ordered_at") or "")
        late = (
            d.get("status") in ("Requested", "InProgress")
            and ordered_at
            and _minutes_between(ordered_at, now_str) > int(threshold_min)
        )
        d["delayed"] = late
        if delayed_only and not late:
            continue
        out.append(d)
    return out


def TAT_stats(
    conn: sqlite3.Connection,
    dept_id: Optional[int] = None,
    days: int = 30,
) -> dict[str, Any]:
    """Compute Turnaround Time statistics for completed lab requests.

    Args:
        conn: SQLite connection.
        dept_id: Optional filter by requesting user's department.
        days: Lookback days, default 30.

    Returns:
        Dict: count, mean_tat_min, median_tat_min, p90_tat_min, per_category breakdown.
    """
    q = """
        SELECT lr.*, u.department_id AS requester_dept_id
        FROM lab_requests lr
        LEFT JOIN users u ON u.id = lr.requested_by
        WHERE lr.status='Completed'
          AND lr.turnaround_minutes IS NOT NULL
          AND date(lr.resulted_at) >= date('now','-? days')
    """
    params: list[Any] = [int(days)]
    if dept_id is not None:
        q += " AND u.department_id = ?"
        params.append(int(dept_id))
    rows = conn.execute(q, params).fetchall()
    tats = [int(r["turnaround_minutes"]) for r in rows if r["turnaround_minutes"] is not None]
    tats.sort()
    count = len(tats)
    mean = 0.0
    median = 0.0
    p90 = 0.0
    if count > 0:
        mean = sum(tats) / count
        median = float(tats[count // 2])
        idx_p90 = min(count - 1, max(0, int(round(count * 0.9)) - 1))
        p90 = float(tats[idx_p90])
    per_cat: dict[str, dict[str, float]] = {}
    by_cat: dict[str, list[int]] = {}
    for r in rows:
        cat = str(r["test_category"] or "Uncategorized")
        if r["turnaround_minutes"] is None:
            continue
        by_cat.setdefault(cat, []).append(int(r["turnaround_minutes"]))
    for cat, vals in by_cat.items():
        vals.sort()
        n = len(vals)
        if n == 0:
            continue
        per_cat[cat] = {
            "count": n,
            "mean_min": sum(vals) / n,
            "median_min": float(vals[n // 2]),
        }
    return {
        "count": count,
        "mean_tat_min": round(mean, 2),
        "median_tat_min": median,
        "p90_tat_min": p90,
        "per_category": per_cat,
    }
