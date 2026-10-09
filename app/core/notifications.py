from __future__ import annotations

import json
import sqlite3
from typing import Any, Optional

from .audit import log_action
from .permissions import require_role, can_send_notifications


def push_notification(
    conn: sqlite3.Connection,
    user_id: int,
    type: str,
    title: str,
    message: str,
    data_dict: Optional[dict[str, Any]] = None,
) -> int:
    """Insert a notification for a user.

    Args:
        conn: SQLite connection.
        user_id: Target user id.
        type: Notification type (e.g. 'info', 'warning', 'alert', 'task').
        title: Short title.
        message: Body text.
        data_dict: Optional extra payload stored as JSON.

    Returns:
        New notification id.

    Raises:
        ValueError: On missing required fields.
    """
    if not user_id or not type or not title or not message:
        raise ValueError("user_id, type, title, message are required")
    data_json = json.dumps(data_dict, ensure_ascii=False) if data_dict else None
    cur = conn.cursor()
    cur.execute(
        """INSERT INTO notifications(user_id,type,title,message,data_json,is_read,created_at)
           VALUES(?,?,?,?,?,0,datetime('now'))""",
        (int(user_id), str(type)[:32], str(title)[:200], str(message)[:2000], data_json),
    )
    notif_id = int(cur.lastrowid or 0)
    log_action(
        conn, None, "System",
        "CREATE", "notification", str(notif_id),
        {"user_id": int(user_id), "type": type, "title": title},
    )
    return notif_id


def mark_read(
    conn: sqlite3.Connection,
    user_id: int,
    notif_id: int,
) -> bool:
    """Mark a notification as read for the given user.

    Args:
        conn: SQLite connection.
        user_id: Owner of the notification.
        notif_id: Notification id.

    Returns:
        True if a row was updated, False otherwise.
    """
    cur = conn.cursor()
    cur.execute(
        "UPDATE notifications SET is_read=1 WHERE id=? AND user_id=?",
        (int(notif_id), int(user_id)),
    )
    updated = cur.rowcount > 0
    if updated:
        log_action(
            conn, int(user_id), None,
            "UPDATE", "notification", str(notif_id),
            {"is_read": True},
        )
    return updated


def list_for_user(
    conn: sqlite3.Connection,
    user_id: int,
    unread_only: bool = False,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """List notifications for a user, newest first.

    Args:
        conn: SQLite connection.
        user_id: Target user id.
        unread_only: If True, only unread notifications are returned.
        limit: Maximum number of rows.

    Returns:
        List of notification dicts.
    """
    q = "SELECT * FROM notifications WHERE user_id=?"
    params: list[Any] = [int(user_id)]
    if unread_only:
        q += " AND is_read=0"
    q += " ORDER BY id DESC LIMIT ?"
    params.append(int(limit))
    rows = conn.execute(q, params).fetchall()
    return [dict(r) for r in rows]


def unread_count(
    conn: sqlite3.Connection,
    user_id: int,
) -> int:
    """Count unread notifications for a user.

    Args:
        conn: SQLite connection.
        user_id: Target user id.

    Returns:
        Count of unread notifications.
    """
    row = conn.execute(
        "SELECT COUNT(*) AS c FROM notifications WHERE user_id=? AND is_read=0",
        (int(user_id),),
    ).fetchone()
    return int(row["c"] if row else 0)


def _deduped_push_for_role(
    conn: sqlite3.Connection,
    role: str,
    type: str,
    title: str,
    message: str,
    data_dict: Optional[dict[str, Any]] = None,
) -> None:
    """Push a notification to all users of a role, deduped by (title, user, date)."""
    users = conn.execute(
        "SELECT id FROM users WHERE role=?",
        (role,),
    ).fetchall()
    today_q = "date('now')"
    for u in users:
        uid = int(u["id"])
        existing = conn.execute(
            "SELECT id FROM notifications WHERE user_id=? AND title=? AND date(created_at)=date('now') LIMIT 1",
            (uid, title),
        ).fetchone()
        if existing:
            continue
        push_notification(conn, uid, type, title, message, data_dict)
