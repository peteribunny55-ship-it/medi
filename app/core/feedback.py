from __future__ import annotations

import sqlite3
from typing import Any, Optional

from .audit import log_action
from .permissions import require_role, can_submit_feedback, can_resolve_feedback


def submit_feedback(
    conn: sqlite3.Connection,
    user: Optional[dict[str, Any]] = None,
    patient_id: Optional[int] = None,
    is_anonymous: bool = False,
    category: str = "",
    dept_id: Optional[int] = None,
    subject: str = "",
    description: str = "",
) -> dict[str, Any]:
    """Submit feedback, optionally anonymously or linked to a patient.

    Args:
        conn: SQLite connection.
        user: Actor user (may be None if anonymous form via UI).
        patient_id: Optional linked patient id.
        is_anonymous: If True, user_id is not exposed and user is optional.
        category: Category string (e.g. 'Wait times', 'Staff behavior', 'Cleanliness').
        dept_id: Optional department id.
        subject: Subject line.
        description: Free-form description.

    Returns:
        Inserted feedback dict.

    Raises:
        ValueError: On missing subject/description or non-anonymous with no user and no patient.
    """
    if not subject or not description:
        raise ValueError("subject and description are required")
    if not is_anonymous and user is None and patient_id is None:
        raise ValueError("Non-anonymous feedback requires a user or patient_id")
    actor_id = int(user["id"]) if user else None
    actor_role = user.get("role") if user else None
    try:
        conn.execute("BEGIN IMMEDIATE")
        cur = conn.cursor()
        cur.execute(
            """INSERT INTO feedback(
                patient_id,is_anonymous,category,department_id,subject,description,status,assignee_id,resolution_notes,submitted_at,resolved_at
            ) VALUES(?,?,?,?,?,?,'Open',NULL,NULL,datetime('now'),NULL)""",
            (
                int(patient_id) if patient_id else None,
                1 if is_anonymous else 0,
                str(category or "")[:100],
                int(dept_id) if dept_id else None,
                str(subject)[:200],
                str(description),
            ),
        )
        fb_id = int(cur.lastrowid or 0)
        log_action(
            conn,
            actor_id,
            actor_role,
            "CREATE",
            "feedback",
            str(fb_id),
            {
                "patient_id": patient_id,
                "is_anonymous": bool(is_anonymous),
                "category": str(category or ""),
                "dept_id": dept_id,
                "subject": str(subject),
            },
        )
        conn.execute("COMMIT")
    except Exception as exc:
        conn.execute("ROLLBACK")
        raise exc
    row = conn.execute("SELECT * FROM feedback WHERE id=?", (fb_id,)).fetchone()
    return dict(row)


def list_feedback(
    conn: sqlite3.Connection,
    user: Optional[dict[str, Any]],
    category: Optional[str] = None,
    status: Optional[str] = None,
    dept_id: Optional[int] = None,
    limit: int = 200,
) -> list[dict[str, Any]]:
    """List feedback visible to user. Admin sees all. Others see limited scope.

    Args:
        conn: SQLite connection.
        user: Current user.
        category: Optional category filter.
        status: Optional status filter.
        dept_id: Optional dept filter.
        limit: Max rows.

    Returns:
        List of feedback dicts.

    Raises:
        PermissionError_: If user is None.
    """
    if user is None:
        require_role(user, "Admin")
    role = user.get("role", "")
    q = "SELECT * FROM feedback WHERE 1=1"
    params: list[Any] = []
    if role != "Admin":
        user_dept = int(user.get("department_id") or 0)
        uid = int(user["id"])
        q += " AND (department_id = ? OR assignee_id = ?)"
        params += [user_dept, uid]
    if category:
        q += " AND category = ?"
        params.append(str(category))
    if status:
        q += " AND status = ?"
        params.append(str(status))
    if dept_id is not None:
        q += " AND department_id = ?"
        params.append(int(dept_id))
    q += " ORDER BY id DESC LIMIT ?"
    params.append(int(limit))
    rows = conn.execute(q, params).fetchall()
    return [dict(r) for r in rows]


def resolve_feedback(
    conn: sqlite3.Connection,
    user: Optional[dict[str, Any]],
    feedback_id: int,
    resolution_notes: str = "",
    assignee_id: Optional[int] = None,
) -> dict[str, Any]:
    """Resolve feedback. Sets status='Resolved', resolved_at=now, optional assignee + notes.

    Args:
        conn: SQLite connection.
        user: Actor user (Admin).
        feedback_id: Feedback id.
        resolution_notes: Resolution description text.
        assignee_id: Optional staff member assigned to the resolution.

    Returns:
        Updated feedback dict.

    Raises:
        PermissionError_: If user is not Admin.
        ValueError: If feedback not found.
    """
    require_role(user, "Admin")
    row = conn.execute("SELECT * FROM feedback WHERE id=?", (int(feedback_id),)).fetchone()
    if not row:
        raise ValueError(f"feedback id {feedback_id} not found")
    old_status = str(row["status"] or "")
    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            """UPDATE feedback SET status='Resolved', assignee_id=?, resolution_notes=?, resolved_at=datetime('now')
               WHERE id=?""",
            (
                int(assignee_id) if assignee_id else None,
                str(resolution_notes or ""),
                int(feedback_id),
            ),
        )
        log_action(
            conn,
            int(user["id"]) if user else None,
            user.get("role") if user else None,
            "UPDATE",
            "feedback",
            str(feedback_id),
            {
                "old_status": old_status,
                "new_status": "Resolved",
                "assignee_id": assignee_id,
                "resolution_len": len(str(resolution_notes or "")),
            },
        )
        conn.execute("COMMIT")
    except Exception as exc:
        conn.execute("ROLLBACK")
        raise exc
    updated = conn.execute("SELECT * FROM feedback WHERE id=?", (int(feedback_id),)).fetchone()
    return dict(updated)


def summary_stats(
    conn: sqlite3.Connection,
) -> dict[str, Any]:
    """Aggregate feedback summary by status, department, and category.

    Args:
        conn: SQLite connection.

    Returns:
        Dict with 'total', 'by_status', 'by_dept' (dept_id->counts), and 'by_category' (cat->counts).
    """
    total_row = conn.execute("SELECT COUNT(*) AS c FROM feedback").fetchone()
    total = int(total_row["c"] if total_row else 0)
    by_status: dict[str, int] = {}
    for r in conn.execute("SELECT status, COUNT(*) AS c FROM feedback GROUP BY status").fetchall():
        by_status[str(r["status"] or "Unknown")] = int(r["c"])
    by_dept: dict[str, int] = {}
    for r in conn.execute(
        "SELECT COALESCE(department_id,0) AS dept, COUNT(*) AS c FROM feedback GROUP BY COALESCE(department_id,0)"
    ).fetchall():
        by_dept[str(r["dept"])] = int(r["c"])
    by_category: dict[str, int] = {}
    for r in conn.execute(
        "SELECT COALESCE(category,'') AS cat, COUNT(*) AS c FROM feedback GROUP BY COALESCE(category,'')"
    ).fetchall():
        by_category[str(r["cat"])] = int(r["c"])
    return {
        "total": total,
        "by_status": by_status,
        "by_dept": by_dept,
        "by_category": by_category,
    }
