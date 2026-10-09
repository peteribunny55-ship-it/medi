from __future__ import annotations

import json
import sqlite3
from typing import Any, Optional

from .audit import log_action
from .permissions import require_role, can_complete_ic_checklist


_DEFAULT_TEMPLATES: list[dict[str, Any]] = [
    {
        "name": "Hand Hygiene",
        "items_json": [
            {"item": "Wash hands with soap before patient contact", "guideline": "20-second scrub"},
            {"item": "Use alcohol-based hand rub after contact", "guideline": "Minimum 60% alcohol"},
            {"item": "Clean hands after removing gloves", "guideline": "Immediately after glove removal"},
            {"item": "No artificial nails or extenders for clinical staff", "guideline": "Per policy"},
        ],
    },
    {
        "name": "PPE",
        "items_json": [
            {"item": "Gloves worn when contact with bodily fluids", "guideline": "Nitrile preferred"},
            {"item": "Gown used for anticipated splash procedures", "guideline": "Fluid-resistant"},
            {"item": "Mask with eye protection for aerosol-generating", "guideline": "Surgical or N95"},
            {"item": "PPE doffing performed in correct order", "guideline": "Gloves first, then gown, mask last"},
        ],
    },
    {
        "name": "Isolation",
        "items_json": [
            {"item": "Contact isolation sign posted on door", "guideline": "Visible from hallway"},
            {"item": "Patient placed in private room or cohort", "guideline": "Per pathogen"},
            {"item": "Dedicated equipment (stethoscope, BP cuff)", "guideline": "Labeled"},
            {"item": "Room terminal cleaning documented after discharge", "guideline": "Checklist signed"},
        ],
    },
]


def ensure_default_templates(conn: sqlite3.Connection) -> int:
    """Create default Hand Hygiene, PPE, and Isolation checklist templates if missing.

    Args:
        conn: SQLite connection.

    Returns:
        Count of newly inserted templates.
    """
    inserted = 0
    try:
        conn.execute("BEGIN IMMEDIATE")
        cur = conn.cursor()
        for tpl in _DEFAULT_TEMPLATES:
            existing = conn.execute(
                "SELECT id FROM ic_checklist_templates WHERE name=? AND department_id IS NULL",
                (str(tpl["name"]),),
            ).fetchone()
            if existing:
                continue
            cur.execute(
                "INSERT INTO ic_checklist_templates(name,department_id,items_json) VALUES(?,NULL,?)",
                (str(tpl["name"]), json.dumps(tpl["items_json"], ensure_ascii=False)),
            )
            inserted += 1
            log_action(
                conn, None, "System",
                "CREATE", "ic_template",
                str(cur.lastrowid or 0),
                {"name": str(tpl["name"])},
            )
        conn.execute("COMMIT")
    except Exception as exc:
        conn.execute("ROLLBACK")
        raise exc
    return inserted


def list_templates(
    conn: sqlite3.Connection,
    dept_id: Optional[int] = None,
) -> list[dict[str, Any]]:
    """List infection control checklist templates, optionally filtered by department.

    Always includes global templates (department_id is NULL).

    Args:
        conn: SQLite connection.
        dept_id: Optional department filter.

    Returns:
        List of template dicts with items_json parsed into Python list.
    """
    q = "SELECT * FROM ic_checklist_templates WHERE 1=1"
    params: list[Any] = []
    if dept_id is not None:
        q += " AND (department_id = ? OR department_id IS NULL)"
        params.append(int(dept_id))
    q += " ORDER BY id"
    rows = conn.execute(q, params).fetchall()
    out: list[dict[str, Any]] = []
    for r in rows:
        d = dict(r)
        try:
            d["items"] = json.loads(str(d.get("items_json") or "[]"))
        except Exception:
            d["items"] = []
        out.append(d)
    return out


def flag_incomplete(
    records_list: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Attach 'incomplete' boolean flag to each record.

    Incomplete if any checklist item has passed=False AND na=False.

    Args:
        records_list: List of record dicts each with a parsed 'results' key
                      (list of {item, passed:bool, na:bool}).

    Returns:
        Same list with each dict enriched by key 'incomplete': bool.
    """
    out: list[dict[str, Any]] = []
    for rec in records_list:
        d = dict(rec)
        results = d.get("results") or []
        incomplete = False
        for it in results:
            if not it.get("na", False) and not it.get("passed", False):
                incomplete = True
                break
        d["incomplete"] = incomplete
        out.append(d)
    return out


def submit_record(
    conn: sqlite3.Connection,
    user: Optional[dict[str, Any]],
    template_id: int,
    ward: str,
    dept_id: int,
    results_list_of_dicts: list[dict[str, Any]],
    notes: str = "",
) -> dict[str, Any]:
    """Submit an infection control checklist completion record.

    Args:
        conn: SQLite connection.
        user: Actor user (Admin, Nurse, Doctor).
        template_id: Template id.
        ward: Ward name string.
        dept_id: Department id.
        results_list_of_dicts: List of {item, passed:bool, na:bool}.
        notes: Optional free text notes.

    Returns:
        Inserted record dict with parsed results list and incomplete flag.

    Raises:
        PermissionError_: If user cannot complete checklist.
        ValueError: On missing template, dept, or invalid results.
    """
    require_role(user, ["Admin", "Nurse", "Doctor"])
    if not template_id or not dept_id:
        raise ValueError("template_id and dept_id are required")
    tpl = conn.execute(
            "SELECT id FROM ic_checklist_templates WHERE id=?",
            (int(template_id),)
        ).fetchone()
    if not tpl:
        raise ValueError(f"template id {template_id} not found")
    if not isinstance(results_list_of_dicts, list) or not results_list_of_dicts:
        pass
    if not isinstance(results_list_of_dicts, list) or len(results_list_of_dicts) == 0:
        raise ValueError("results_list_of_dicts must be a non-empty list")
    normalized: list[dict[str, Any]] = []
    for it in results_list_of_dicts:
        if not isinstance(it, dict):
            raise ValueError("each result must be a dict")
        normalized.append({
            "item": str(it.get("item", ""))[:200],
            "passed": bool(it.get("passed", False)),
            "na": bool(it.get("na", False)),
        })
    results_json = json.dumps(normalized, ensure_ascii=False)
    try:
        conn.execute("BEGIN IMMEDIATE")
        cur = conn.cursor()
        cur.execute(
            """INSERT INTO ic_checklist_records(
                template_id,ward,department_id,completed_by,completed_at,results_json,notes
            ) VALUES(?,?,?,?,datetime('now'),?,?)""",
            (
                int(template_id), str(ward)[:100], int(dept_id),
                int(user["id"]) if user else None,
                results_json, str(notes or "")[:2000],
            ),
        )
        rec_id = int(cur.lastrowid or 0)
        log_action(
            conn,
            int(user["id"]) if user else None,
            user.get("role") if user else None,
            "CREATE",
            "ic_record",
            str(rec_id),
            {
                "template_id": int(template_id),
                "ward": str(ward),
                "dept_id": int(dept_id),
                "items_count": len(normalized),
            },
        )
        conn.execute("COMMIT")
    except Exception as exc:
        conn.execute("ROLLBACK")
        raise exc
    row = conn.execute("SELECT * FROM ic_checklist_records WHERE id=?", (rec_id,)).fetchone()
    d = dict(row)
    try:
        d["results"] = json.loads(str(d.get("results_json") or "[]"))
    except Exception:
        d["results"] = normalized
    flagged = flag_incomplete([d])
    return flagged[0]


def list_records(
    conn: sqlite3.Connection,
    dept_id: Optional[int] = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """List infection control records with parsed results and incomplete flags.

    Args:
        conn: SQLite connection.
        dept_id: Optional department filter.
        limit: Max rows.

    Returns:
        List of record dicts, each with 'results' list and 'incomplete' flag.
    """
    q = "SELECT * FROM ic_checklist_records WHERE 1=1"
    params: list[Any] = []
    if dept_id is not None:
        q += " AND department_id = ?"
        params.append(int(dept_id))
    q += " ORDER BY id DESC LIMIT ?"
    params.append(int(limit))
    rows = conn.execute(q, params).fetchall()
    parsed: list[dict[str, Any]] = []
    for r in rows:
        d = dict(r)
        try:
            d["results"] = json.loads(str(d.get("results_json") or "[]"))
        except Exception:
            d["results"] = []
        parsed.append(d)
    return flag_incomplete(parsed)
