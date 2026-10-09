from __future__ import annotations

import sqlite3
from datetime import datetime
from typing import Any, Optional

from .audit import log_action
from .permissions import (
    require_role,
    can_create_handover,
    can_view_handover,
    can_view_tasks,
    can_assign_task,
)


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def create_note(
    conn: sqlite3.Connection,
    user: Optional[dict[str, Any]],
    to_staff_id: int,
    shift_id: int,
    dept_id: int,
    note_text: str,
) -> dict[str, Any]:
    """Create a handover note from one staff member to another for a shift/dept.

    Args:
        conn: SQLite connection.
        user: Actor user (Admin, Nurse, Doctor) - sender.
        to_staff_id: Recipient user id.
        shift_id: Shift id.
        dept_id: Department id.
        note_text: Handover content text.

    Returns:
        Inserted handover note dict.

    Raises:
        PermissionError_: If user cannot create handover.
        ValueError: On missing required fields.
    """
    require_role(user, ["Admin", "Nurse", "Doctor"])
    if not to_staff_id or not shift_id or not dept_id or not note_text:
        raise ValueError("to_staff_id, shift_id, dept_id, note_text are required")
    try:
        conn.execute("BEGIN IMMEDIATE")
        cur = conn.cursor()
        cur.execute(
            """INSERT INTO handover_notes(
                from_staff_id,to_staff_id,shift_id,department_id,note_text,is_read,created_at
            ) VALUES(?,?,?,?,?,0,datetime('now'))""",
            (
                int(user["id"]) if user else None,
                int(to_staff_id), int(shift_id), int(dept_id), str(note_text),
            ),
        )
        note_id = int(cur.lastrowid or 0)
        log_action(
            conn,
            int(user["id"]) if user else None,
            user.get("role") if user else None,
            "CREATE",
            "handover_note",
            str(note_id),
            {
                "to_staff_id": int(to_staff_id),
                "shift_id": int(shift_id),
                "department_id": int(dept_id),
                "note_len": len(str(note_text)),
            },
        )
        conn.execute("COMMIT")
    except Exception as exc:
        conn.execute("ROLLBACK")
        raise exc
    row = conn.execute("SELECT * FROM handover_notes WHERE id=?", (note_id,)).fetchone()
    return dict(row)


def list_notes(
    conn: sqlite3.Connection,
    user: Optional[dict[str, Any]],
    dept_id: Optional[int] = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """List handover notes visible to the current user.

    Admin sees all. Doctors/Nurses see only their dept. Also notes addressed
    to the current user are always included regardless of dept.

    Args:
        conn: SQLite connection.
        user: Current user.
        dept_id: Optional department filter.
        limit: Max rows.

    Returns:
        List of handover note dicts.

    Raises:
        PermissionError_: If no user.
    """
    require_role(user, ["Admin", "Nurse", "Doctor"])
    role = user.get("role", "") if user else ""
    uid = int(user["id"]) if user else 0
    user_dept = int(user.get("department_id") or 0) if user else 0
    q = "SELECT * FROM handover_notes WHERE 1=1"
    params: list[Any] = []
    if role != "Admin":
        if dept_id:
            q += " AND department_id = ?"
            params.append(int(dept_id))
        else:
            q += " AND (department_id = ? OR to_staff_id = ? OR from_staff_id = ?)"
            params += [user_dept, uid, uid]
    elif dept_id:
        q += " AND department_id = ?"
        params.append(int(dept_id))
    q += " ORDER BY id DESC LIMIT ?"
    params.append(int(limit))
    rows = conn.execute(q, params).fetchall()
    return [dict(r) for r in rows]


def mark_note_read(
    conn: sqlite3.Connection,
    user: Optional[dict[str, Any]],
    note_id: int,
) -> bool:
    """Mark a handover note as read. Only Admin or the note recipient/to_staff_id.

    Args:
        conn: SQLite connection.
        user: Current user.
        note_id: Note id.

    Returns:
        True if updated, else False.

    Raises:
        PermissionError_: If user not authenticated or not allowed.
    """
    require_role(user, ["Admin", "Nurse", "Doctor"])
    row = conn.execute("SELECT * FROM handover_notes WHERE id=?", (int(note_id),)).fetchone()
    if not row:
        return False
    role = user.get("role", "") if user else ""
    uid = int(user["id"]) if user else 0
    if role != "Admin" and int(row["to_staff_id"] or 0) != uid and int(row["from_staff_id"] or 0) != uid:
        return False
    cur = conn.cursor()
    cur.execute("UPDATE handover_notes SET is_read=1 WHERE id=?", (int(note_id),))
    updated = cur.rowcount > 0
    if updated:
        log_action(
            conn, uid,
            user.get("role") if user else None,
            "UPDATE",
            "handover_note",
            str(note_id),
            {"is_read": True},
        )
    return updated


def create_task(
    conn: sqlite3.Connection,
    user: Optional[dict[str, Any]],
    title: str,
    assignee_id: int,
    priority: str = "Medium",
    description: str = "",
    due_at: Optional[str] = None,
    dept_id: Optional[int] = None,
) -> dict[str, Any]:
    """Create a task assigned to a staff member.

    Args:
        conn: SQLite connection.
        user: Creator (Admin, Nurse for assignment; clinical can create assigned to self).
        title: Task title.
        assignee_id: Assignee user id.
        priority: Low/Medium/High.
        description: Optional description.
        due_at: Optional due ISO timestamp.
        dept_id: Optional department id.

    Returns:
        Inserted task dict.

    Raises:
        PermissionError_: If user cannot assign task and not self-assign by clinical.
    """
    if not user:
        require_role(user, "Admin")
    role = user.get("role", "")
    uid = int(user["id"]) if user else 0
    is_self_assign = int(assignee_id) == uid
    if not (role == "Admin" or role == "Nurse" or (is_self_assign and role in ("Doctor",))):
        require_role(user, ["Admin", "Nurse"])
    if not title or not assignee_id:
        raise ValueError("title and assignee_id are required")
    try:
        conn.execute("BEGIN IMMEDIATE")
        cur = conn.cursor()
        cur.execute(
            """INSERT INTO tasks(
                title,description,assignee_id,creator_id,priority,status,due_at,department_id,created_at
            ) VALUES(?,?,?,?,?,'Pending',?,?,datetime('now'))""",
            (
                str(title)[:200], str(description or "")[:2000], int(assignee_id),
                uid, str(priority or "Medium")[:32],
                str(due_at) if due_at else None,
                int(dept_id) if dept_id else None,
            ),
        )
        task_id = int(cur.lastrowid or 0)
        log_action(
            conn, uid,
            user.get("role") if user else None,
            "CREATE",
            "task",
            str(task_id),
            {
                "title": str(title),
                "assignee_id": int(assignee_id),
                "priority": str(priority or "Medium"),
                "due_at": due_at,
            },
        )
        conn.execute("COMMIT")
    except Exception as exc:
        conn.execute("ROLLBACK")
        raise exc
    row = conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
    return dict(row)


def list_tasks(
    conn: sqlite3.Connection,
    user: Optional[dict[str, Any]],
    assignee_id: Optional[int] = None,
    status: Optional[str] = None,
    priority: Optional[str] = None,
    limit: int = 200,
) -> list[dict[str, Any]]:
    """List tasks visible to the current user.

    Admin sees all. Others see tasks assigned to them or created by them
    within their dept (per can_view_tasks rule).

    Args:
        conn: SQLite connection.
        user: Current user.
        assignee_id: Optional assignee filter.
        status: Optional status filter.
        priority: Optional priority filter.
        limit: Max rows.

    Returns:
        List of task dicts.

    Raises:
        PermissionError_: If no user.
    """
    require_role(user, ["Admin", "Nurse", "Doctor"])
    role = user.get("role", "") if user else ""
    uid = int(user["id"]) if user else 0
    user_dept = int(user.get("department_id") or 0) if user else 0
    q = "SELECT * FROM tasks WHERE 1=1"
    params: list[Any] = []
    if role != "Admin":
        eff_assignee = assignee_id if assignee_id is not None else uid
        eff_dept = user_dept
        q += " AND (assignee_id = ? OR creator_id = ? OR department_id = ?)"
        params += [eff_assignee, uid, eff_dept]
    if assignee_id is not None:
        q += " AND assignee_id = ?"
        params.append(int(assignee_id))
    if status:
        q += " AND status = ?"
        params.append(str(status))
    if priority:
        q += " AND priority = ?"
        params.append(str(priority))
    q += " ORDER BY CASE priority WHEN 'High' THEN 1 WHEN 'Medium' THEN 2 ELSE 3 END, id DESC LIMIT ?"
    params.append(int(limit))
    rows = conn.execute(q, params).fetchall()
    return [dict(r) for r in rows]


def update_task_status(
    conn: sqlite3.Connection,
    user: Optional[dict[str, Any]],
    task_id: int,
    new_status: str,
) -> dict[str, Any]:
    """Update task status. When Done, sets completed_at=now.

    Args:
        conn: SQLite connection.
        user: Current user.
        task_id: Task id.
        new_status: Pending, InProgress, Blocked, Done, Cancelled.

    Returns:
        Updated task dict.

    Raises:
        PermissionError_: If user not Admin/assignee/creator.
        ValueError: If task not found.
    """
    require_role(user, ["Admin", "Nurse", "Doctor"])
    row = conn.execute("SELECT * FROM tasks WHERE id=?", (int(task_id),)).fetchone()
    if not row:
        raise ValueError(f"task id {task_id} not found")
    uid = int(user["id"]) if user else 0
    role = user.get("role", "") if user else ""
    if role != "Admin" and int(row["assignee_id"] or 0) != uid and int(row["creator_id"] or 0) != uid:
        raise ValueError("Only Admin, assignee, or creator can update this task")
    old_status = str(row["status"] or "")
    try:
        conn.execute("BEGIN IMMEDIATE")
        if str(new_status) == "Done":
            conn.execute(
                "UPDATE tasks SET status=?, completed_at=datetime('now') WHERE id=?",
                (str(new_status), int(task_id)),
            )
        else:
            conn.execute(
                "UPDATE tasks SET status=? WHERE id=?",
                (str(new_status), int(task_id)),
            )
        log_action(
            conn, uid,
            user.get("role") if user else None,
            "UPDATE",
            "task",
            str(task_id),
            {"old_status": old_status, "new_status": str(new_status)},
        )
        conn.execute("COMMIT")
    except Exception as exc:
        conn.execute("ROLLBACK")
        raise exc
    updated = conn.execute("SELECT * FROM tasks WHERE id=?", (int(task_id),)).fetchone()
    return dict(updated)
