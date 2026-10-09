from __future__ import annotations

import sqlite3
from typing import Any, Optional

from .audit import log_action
from .permissions import (
    PermissionError_,
    can_call_next_patient,
    can_manage_queue,
    require_role,
)


def _now() -> str:
    import datetime as _dt
    return _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _today() -> str:
    import datetime as _dt
    return _dt.date.today().strftime("%Y-%m-%d")


def _diff_minutes(start: str, end: str) -> int:
    try:
        import datetime as _dt
        s = _dt.datetime.strptime(start, "%Y-%m-%d %H:%M:%S")
        e = _dt.datetime.strptime(end, "%Y-%m-%d %H:%M:%S")
        return max(0, int((e - s).total_seconds() // 60))
    except Exception:
        return 0


def compute_wait_estimate(
    conn: sqlite3.Connection,
    dept_id: int,
    patient_position_ahead: Optional[int] = None,
    include_self: bool = False,
) -> int:
    """Estimate wait time for a department based on recent service averages.

    Estimated wait minutes = patients_ahead × dept_avg_service_minutes.

    Args:
        conn: Active SQLite connection.
        dept_id: Department id.
        patient_position_ahead: If provided, skip counting ahead from queue
            and use this number of patients ahead directly.
        include_self: When counting from queue, include the self token in the
            patients_ahead tally. (Used when caller has already created a token.)

    Returns:
        Integer estimated wait time in minutes (minimum 0).

    Raises:
        ValueError: If dept_id is invalid.
    """
    if not dept_id:
        raise ValueError("dept_id is required")
    depid = int(dept_id)

    if patient_position_ahead is None:
        q = """SELECT COUNT(*) FROM queue_tokens
               WHERE department_id = ? AND status = 'Waiting'"""
        count_row = conn.execute(q, (depid,)).fetchone()
        patients_ahead = int(count_row[0]) if count_row else 0
        if include_self:
            patients_ahead = max(0, patients_ahead - 1)
    else:
        patients_ahead = max(0, int(patient_position_ahead))

    recent_row = conn.execute(
        """SELECT AVG(doc.avg_consult_minutes) AS avg_min
           FROM appointments a
           LEFT JOIN doctors doc ON doc.id = a.doctor_id
           WHERE a.department_id = ?
             AND a.status = 'Completed'
             AND date(a.appointment_date) >= date('now', '-7 days')""",
        (depid,),
    ).fetchone()
    avg_min = None
    if recent_row:
        v = recent_row[0]
        if v is not None:
            try:
                avg_min = float(v)
            except Exception:
                avg_min = None
    if avg_min is None or avg_min <= 0:
        avg_min = 15.0

    return max(0, int(round(patients_ahead * avg_min)))


def generate_token(
    conn: sqlite3.Connection,
    patient_id: int,
    dept_id: int,
    appointment_id: Optional[int] = None,
    prefix: str = "T",
) -> dict[str, Any]:
    """Generate a new queue token with auto-incrementing token_no per (prefix, date).

    Args:
        conn: Active SQLite connection.
        patient_id: Patient row id (required).
        dept_id: Department row id (required).
        appointment_id: Optional linked appointment id.
        prefix: Token prefix string. Default 'T'. Combined with token_no forms e.g. T003.

    Returns:
        Newly inserted queue_token dict with estimated_wait_minutes populated.

    Raises:
        ValueError: If patient/dept missing or DB constraint fails.
        RuntimeError: On unexpected DB error.
    """
    if not patient_id or not dept_id:
        raise ValueError("patient_id and dept_id are required")
    pid = int(patient_id)
    depid = int(dept_id)
    pfx = str(prefix or "T")

    conn.execute("BEGIN IMMEDIATE")
    try:
        prow = conn.execute("SELECT id FROM patients WHERE id = ?", (pid,)).fetchone()
        if not prow:
            raise ValueError(f"Patient {pid} not found")
        drow = conn.execute("SELECT id FROM departments WHERE id = ?", (depid,)).fetchone()
        if not drow:
            raise ValueError(f"Department {depid} not found")

        today = _today()
        tn_row = conn.execute(
            """SELECT COALESCE(MAX(token_no), 0) AS nxt
               FROM queue_tokens WHERE prefix = ? AND date(created_at) = date(?)""",
            (pfx, today),
        ).fetchone()
        next_token_no = int(tn_row["nxt"]) + 1 if tn_row else 1

        cur = conn.cursor()
        cur.execute(
            """INSERT INTO queue_tokens(token_no,prefix,appointment_id,patient_id,department_id,status,estimated_wait_minutes,created_at)
               VALUES(?,?,?,?,?,'Waiting',?,?)""",
            (next_token_no, pfx, appointment_id, pid, depid, 0, _now()),
        )
        token_id = int(cur.lastrowid or 0)

        wait = compute_wait_estimate(conn, depid, include_self=False)
        conn.execute(
            "UPDATE queue_tokens SET estimated_wait_minutes = ? WHERE id = ?",
            (wait, token_id),
        )

        new_row = conn.execute("SELECT * FROM queue_tokens WHERE id = ?", (token_id,)).fetchone()
        conn.execute("COMMIT")
        return dict(new_row)
    except (ValueError, PermissionError, PermissionError_):
        conn.execute("ROLLBACK")
        raise
    except sqlite3.Error as e:
        conn.execute("ROLLBACK")
        raise RuntimeError(f"Database error generating queue token: {e}") from e


def list_department_queue(
    conn: sqlite3.Connection,
    dept_id: int,
    include_statuses: Optional[list[str]] = None,
) -> list[dict[str, Any]]:
    """Return queue tokens for a department ordered by created_at ascending.

    Args:
        conn: Active SQLite connection.
        dept_id: Department id.
        include_statuses: Optional list of status strings to filter. Default
            includes Waiting, Called, InProgress.

    Returns:
        List of queue token dicts, augmented with patient name and position.
    """
    if not dept_id:
        raise ValueError("dept_id is required")
    if include_statuses is None:
        include_statuses = ["Waiting", "Called", "InProgress"]
    statuses = [str(s) for s in include_statuses]
    placeholders = ",".join("?" for _ in statuses)
    params: list[Any] = [int(dept_id)] + statuses
    rows = conn.execute(
        f"""SELECT qt.*, p.first_name, p.last_name, p.patient_id AS patient_code,
                   d.name AS dept_name
            FROM queue_tokens qt
            LEFT JOIN patients p ON p.id = qt.patient_id
            LEFT JOIN departments d ON d.id = qt.department_id
            WHERE qt.department_id = ? AND qt.status IN ({placeholders})
            ORDER BY qt.created_at ASC, qt.id ASC""",
        params,
    ).fetchall()
    return [dict(r) for r in rows]


def list_tokens(
    conn: sqlite3.Connection,
    dept_id: Optional[int] = None,
    status: Optional[str] = None,
) -> list[dict[str, Any]]:
    """List queue tokens optionally filtered by department or status.

    Args:
        conn: Active SQLite connection.
        dept_id: Optional department ID to filter.
        status: Optional status string to filter (e.g. 'Waiting').

    Returns:
        List of token dicts augmented with patient name and dept name.
    """
    params: list[Any] = []
    where: list[str] = ["1=1"]
    if dept_id is not None:
        where.append("qt.department_id = ?"); params.append(int(dept_id))
    if status:
        where.append("qt.status = ?"); params.append(status)

    sql = f"""SELECT qt.*, p.first_name, p.last_name, p.patient_id AS patient_code,
                     d.name AS dept_name
              FROM queue_tokens qt
              LEFT JOIN patients p ON p.id = qt.patient_id
              LEFT JOIN departments d ON d.id = qt.department_id
              WHERE {" AND ".join(where)}
              ORDER BY qt.created_at ASC, qt.id ASC"""
    rows = conn.execute(sql, params).fetchall()
    return [dict(r) for r in rows]



def call_next_patient(
    conn: sqlite3.Connection,
    user: dict[str, Any],
    dept_id: int,
) -> dict[str, Any]:
    """Advance the queue: mark the oldest Waiting token as Called and update waits.

    Args:
        conn: Active SQLite connection.
        user: Authenticated user dict.
        dept_id: Department id.

    Returns:
        The token dict that was just called.

    Raises:
        PermissionError: If user lacks can_call_next_patient.
        ValueError: If dept id missing or no waiting patients.
        RuntimeError: On unexpected DB error.
    """
    if not can_call_next_patient(user):
        raise PermissionError("Not permitted to call next patient")
    if not dept_id:
        raise ValueError("dept_id is required")
    depid = int(dept_id)

    conn.execute("BEGIN IMMEDIATE")
    try:
        next_row = conn.execute(
            """SELECT * FROM queue_tokens
               WHERE department_id = ? AND status = 'Waiting'
               ORDER BY created_at ASC, id ASC LIMIT 1""",
            (depid,),
        ).fetchone()
        if not next_row:
            raise ValueError("No waiting patients in queue")
        token_id = int(next_row["id"])
        patient_id = int(next_row["patient_id"])

        conn.execute(
            "UPDATE queue_tokens SET status = 'Called', called_at = ? WHERE id = ?",
            (_now(), token_id),
        )

        waiting_ids = conn.execute(
            """SELECT id FROM queue_tokens
               WHERE department_id = ? AND status = 'Waiting'
               ORDER BY created_at ASC, id ASC""",
            (depid,),
        ).fetchall()
        for pos, wr in enumerate(waiting_ids):
            est = compute_wait_estimate(conn, depid, patient_position_ahead=pos)
            conn.execute(
                "UPDATE queue_tokens SET estimated_wait_minutes = ? WHERE id = ?",
                (est, int(wr["id"])),
            )

        log_action(
            conn, user.get("id"), user.get("role"),
            "CALL_NEXT", "queue_token", str(token_id),
            {"dept_id": depid, "patient_id": patient_id},
        )

        try:
            from .notifications import push_notification
            pu = conn.execute("SELECT user_id FROM patients WHERE id = ?", (patient_id,)).fetchone()
            if pu and pu["user_id"]:
                push_notification(
                    conn,
                    user_id=int(pu["user_id"]),
                    notif_type="queue",
                    title="Your Turn Is Next",
                    message=f"Please proceed to the department. Token: {next_row['prefix']}{next_row['token_no']}",
                    data={"token_id": token_id, "dept_id": depid},
                )
            staff_rows = conn.execute(
                """SELECT id FROM users WHERE role IN ('Admin','Doctor','Nurse')
                   AND (department_id = ? OR department_id IS NULL)""",
                (depid,),
            ).fetchall()
            for sr in staff_rows:
                push_notification(
                    conn,
                    user_id=int(sr["id"]),
                    notif_type="queue_staff",
                    title="Patient Called",
                    message=f"Token {next_row['prefix']}{next_row['token_no']} called for department {depid}",
                    data={"token_id": token_id},
                )
        except Exception:
            pass

        called = conn.execute("SELECT * FROM queue_tokens WHERE id = ?", (token_id,)).fetchone()
        conn.execute("COMMIT")
        return dict(called)
    except (ValueError, PermissionError, PermissionError_):
        conn.execute("ROLLBACK")
        raise
    except sqlite3.Error as e:
        conn.execute("ROLLBACK")
        raise RuntimeError(f"Database error calling next patient: {e}") from e


def start_service(
    conn: sqlite3.Connection,
    user: dict[str, Any],
    token_id: int,
) -> dict[str, Any]:
    """Mark a Called token as InProgress and record service_started_at.

    Args:
        conn: Active SQLite connection.
        user: Authenticated user dict.
        token_id: Queue token id.

    Returns:
        Updated token dict.

    Raises:
        PermissionError: If user lacks queue management.
        ValueError: If token missing or wrong status.
        RuntimeError: On unexpected DB error.
    """
    if not can_manage_queue(user):
        raise PermissionError("Not permitted to start service")
    if not token_id:
        raise ValueError("token_id is required")
    tid = int(token_id)

    conn.execute("BEGIN IMMEDIATE")
    try:
        ex = conn.execute("SELECT * FROM queue_tokens WHERE id = ?", (tid,)).fetchone()
        if not ex:
            raise ValueError(f"Queue token {tid} not found")
        if ex["status"] != "Called":
            raise ValueError(f"Cannot start service on token in status {ex['status']}")
        conn.execute(
            "UPDATE queue_tokens SET status = 'InProgress', service_started_at = ? WHERE id = ?",
            (_now(), tid),
        )
        log_action(
            conn, user.get("id"), user.get("role"),
            "START_SERVICE", "queue_token", str(tid),
            {"patient_id": ex["patient_id"]},
        )
        updated = conn.execute("SELECT * FROM queue_tokens WHERE id = ?", (tid,)).fetchone()
        conn.execute("COMMIT")
        return dict(updated)
    except (ValueError, PermissionError, PermissionError_):
        conn.execute("ROLLBACK")
        raise
    except sqlite3.Error as e:
        conn.execute("ROLLBACK")
        raise RuntimeError(f"Database error starting service: {e}") from e


def complete_token(
    conn: sqlite3.Connection,
    user: dict[str, Any],
    token_id: int,
) -> dict[str, Any]:
    """Mark a token Completed, record completed_at, and compute actual service minutes.

    Args:
        conn: Active SQLite connection.
        user: Authenticated user dict.
        token_id: Queue token id.

    Returns:
        Completed token dict.

    Raises:
        PermissionError: If user lacks queue management.
        ValueError: If token missing or not InProgress.
        RuntimeError: On unexpected DB error.
    """
    if not can_manage_queue(user):
        raise PermissionError("Not permitted to complete tokens")
    if not token_id:
        raise ValueError("token_id is required")
    tid = int(token_id)

    conn.execute("BEGIN IMMEDIATE")
    try:
        ex = conn.execute("SELECT * FROM queue_tokens WHERE id = ?", (tid,)).fetchone()
        if not ex:
            raise ValueError(f"Queue token {tid} not found")
        if ex["status"] != "InProgress":
            raise ValueError(f"Cannot complete token in status {ex['status']}")
        end = _now()
        conn.execute(
            "UPDATE queue_tokens SET status = 'Completed', completed_at = ? WHERE id = ?",
            (end, tid),
        )
        log_action(
            conn, user.get("id"), user.get("role"),
            "COMPLETE", "queue_token", str(tid),
            {"patient_id": ex["patient_id"],
             "actual_service_minutes": _diff_minutes(ex["service_started_at"] or end, end)},
        )
        updated = conn.execute("SELECT * FROM queue_tokens WHERE id = ?", (tid,)).fetchone()
        conn.execute("COMMIT")
        return dict(updated)
    except (ValueError, PermissionError, PermissionError_):
        conn.execute("ROLLBACK")
        raise
    except sqlite3.Error as e:
        conn.execute("ROLLBACK")
        raise RuntimeError(f"Database error completing token: {e}") from e


def patient_queue_position(
    conn: sqlite3.Connection,
    patient_id: int,
) -> list[dict[str, Any]]:
    """Return all active queue positions for a patient across departments.

    Args:
        conn: Active SQLite connection.
        patient_id: Patient row id.

    Returns:
        List of dicts, each with keys 'token' (queue_token dict),
        'position' (int position in the department queue, 1-based),
        'dept' (department dict). Only includes non-Completed tokens.
    """
    if not patient_id:
        raise ValueError("patient_id is required")
    pid = int(patient_id)
    rows = conn.execute(
        """SELECT qt.*, d.id AS d_id, d.name AS d_name, d.description AS d_desc, d.floor AS d_floor
           FROM queue_tokens qt
           LEFT JOIN departments d ON d.id = qt.department_id
           WHERE qt.patient_id = ? AND qt.status IN ('Waiting','Called','InProgress')
           ORDER BY qt.created_at ASC""",
        (pid,),
    ).fetchall()
    results: list[dict[str, Any]] = []
    for r in rows:
        depid = int(r["department_id"])
        pos_row = conn.execute(
            """SELECT COUNT(*) AS c FROM queue_tokens
               WHERE department_id = ? AND status = 'Waiting'
                 AND (created_at < ? OR (created_at = ? AND id < ?))""",
            (depid, r["created_at"], r["created_at"], int(r["id"])),
        ).fetchone()
        position = int(pos_row["c"]) + 1 if pos_row else 1
        token_d = {}
        dept_d = {}
        for k in r.keys():
            if k.startswith("d_"):
                dept_d[k[2:]] = r[k]
            else:
                token_d[k] = r[k]
        results.append({
            "token": token_d,
            "position": position,
            "dept": dept_d,
        })
    return results
