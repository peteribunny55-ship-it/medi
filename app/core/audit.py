from __future__ import annotations

import json
import sqlite3
from typing import Any, Optional


def _sanitize_detail(detail: Optional[dict[str, Any]]) -> dict[str, Any]:
    """Remove sensitive keys (password, hashes, tokens, PHI large text) from audit detail."""
    if not detail:
        return {}
    SENSITIVE = {
        "password", "old_password", "new_password", "password_hash", "token", "secret",
        "ssn", "credit_card", "result_note", "diagnosis", "notes", "description",
    }
    out: dict[str, Any] = {}
    for k, v in detail.items():
        kl = str(k).lower()
        if any(s in kl for s in SENSITIVE):
            if isinstance(v, str):
                out[k] = f"<REDACTED len={len(v)}>"
            else:
                out[k] = "<REDACTED>"
        else:
            out[k] = v
    return out


def log_action(
    conn: sqlite3.Connection,
    actor_id: Optional[int],
    actor_role: Optional[str],
    action: str,
    entity_type: str,
    entity_id: Optional[Any],
    detail: Optional[dict[str, Any]] = None,
    ip_address: Optional[str] = None,
    user_agent: Optional[str] = None,
) -> int:
    """Append a row to audit_logs. Redacts sensitive keys from detail."""
    safe_detail = _sanitize_detail(detail)
    try:
        detail_json = json.dumps(safe_detail, default=str, ensure_ascii=False)
    except Exception:
        detail_json = json.dumps({"repr": str(safe_detail)[:500]}, ensure_ascii=False)
    if actor_role is None and actor_id is not None:
        try:
            r = conn.execute("SELECT role FROM users WHERE id=?", (int(actor_id),)).fetchone()
            if r:
                actor_role = r["role"]
        except Exception:
            actor_role = None
    cur = conn.cursor()
    cur.execute(
        """INSERT INTO audit_logs(actor_id,actor_role,action,entity_type,entity_id,detail_json,ip_address,user_agent)
           VALUES(?,?,?,?,?,?,?,?)""",
        (
            int(actor_id) if actor_id is not None else None,
            actor_role,
            str(action or "")[:64],
            str(entity_type or "")[:64],
            str(entity_id)[:64] if entity_id is not None else None,
            detail_json,
            (ip_address or "")[:64] or None,
            (user_agent or "")[:256] or None,
        ),
    )
    return int(cur.lastrowid or 0)


def list_audit_logs(
    conn: sqlite3.Connection,
    actor_id: Optional[int] = None,
    action: Optional[str] = None,
    entity_type: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    limit: int = 500,
) -> list[dict[str, Any]]:
    q = "SELECT * FROM audit_logs WHERE 1=1"
    params: list[Any] = []
    if actor_id:
        q += " AND actor_id = ?"; params.append(int(actor_id))
    if action:
        q += " AND action = ?"; params.append(action)
    if entity_type:
        q += " AND entity_type = ?"; params.append(entity_type)
    if date_from:
        q += " AND date(created_at) >= date(?)"; params.append(date_from)
    if date_to:
        q += " AND date(created_at) <= date(?)"; params.append(date_to)
    q += " ORDER BY id DESC LIMIT ?"; params.append(int(limit))
    rows = conn.execute(q, params).fetchall()
    return [dict(r) for r in rows]
