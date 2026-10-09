from __future__ import annotations

import sqlite3
from typing import Any, Optional

from .audit import log_action
from .permissions import (
    PermissionError_,
    can_book_appointment,
    can_cancel_any_appointment,
    can_manage_queue,
    can_view_appointment,
    can_view_patient,
    require_role,
)

VALID_APPOINTMENT_STATUSES = {"Scheduled", "Confirmed", "Completed", "Missed", "Cancelled"}

VALID_TRANSITIONS: dict[str, set[str]] = {
    "Scheduled": {"Confirmed", "Cancelled", "Missed", "Completed"},
    "Confirmed": {"Completed", "Cancelled", "Missed"},
    "Completed": set(),
    "Missed": {"Scheduled"},
    "Cancelled": {"Scheduled"},
}


def _now() -> str:
    import datetime as _dt
    return _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def appointment_conflict_exists(
    conn: sqlite3.Connection,
    doctor_id: int,
    appt_date: str,
    appt_time: str,
    exclude_appt_id: Optional[int] = None,
) -> bool:
    """Check whether a conflicting active appointment exists for the doctor slot.

    Args:
        conn: Active SQLite connection.
        doctor_id: Doctor (doctors.id) to check.
        appt_date: Appointment date (YYYY-MM-DD).
        appt_time: Appointment time (HH:MM).
        exclude_appt_id: Optional appointment id to ignore (used during reschedule).

    Returns:
        True if a conflicting appointment exists, else False.
    """
    params: list[Any] = [int(doctor_id), str(appt_date), str(appt_time)]
    q = """SELECT 1 FROM appointments
           WHERE doctor_id = ? AND appointment_date = ? AND appointment_time = ?
             AND status NOT IN ('Cancelled','Missed')"""
    if exclude_appt_id is not None:
        q += " AND id != ?"
        params.append(int(exclude_appt_id))
    row = conn.execute(q, params).fetchone()
    return row is not None


def book_appointment(
    conn: sqlite3.Connection,
    user: dict[str, Any],
    patient_id: int,
    doctor_id: int,
    dept_id: int,
    appt_date: str,
    appt_time: str,
    reason: str = "",
) -> dict[str, Any]:
    """Book a new appointment, detecting conflicts and generating a queue token.

    Args:
        conn: Active SQLite connection.
        user: Authenticated user dict.
        patient_id: Patient row id.
        doctor_id: Doctor row id.
        dept_id: Department row id.
        appt_date: Date YYYY-MM-DD.
        appt_time: Time HH:MM.
        reason: Optional reason text.

    Returns:
        Inserted appointment dict.

    Raises:
        PermissionError: If user cannot book appointments or cannot view patient.
        ValueError: If patient/doctor missing or conflict detected.
        RuntimeError: On unexpected database failure.
    """
    if not can_book_appointment(user):
        raise PermissionError("Not permitted to book appointments")
    if not patient_id or not doctor_id or not dept_id:
        raise ValueError("patient_id, doctor_id, dept_id are required")
    if not appt_date or not appt_time:
        raise ValueError("appt_date and appt_time are required")

    pid = int(patient_id)
    did = int(doctor_id)
    depid = int(dept_id)

    if not can_view_patient(conn, user, pid):
        raise PermissionError("Not permitted to act on this patient")

    conn.execute("BEGIN IMMEDIATE")
    try:
        prow = conn.execute("SELECT id FROM patients WHERE id = ?", (pid,)).fetchone()
        if not prow:
            raise ValueError(f"Patient {pid} not found")
        drow = conn.execute("SELECT id FROM doctors WHERE id = ?", (did,)).fetchone()
        if not drow:
            raise ValueError(f"Doctor {did} not found")

        conflict_row = conn.execute(
            """SELECT 1 FROM appointments
               WHERE doctor_id = ? AND appointment_date = ? AND appointment_time = ?
                 AND status NOT IN ('Cancelled','Missed')""",
            (did, appt_date, appt_time),
        ).fetchone()
        if conflict_row:
            raise ValueError("Conflict")

        cur = conn.cursor()
        cur.execute(
            """INSERT INTO appointments(patient_id,doctor_id,department_id,appointment_date,appointment_time,status,reason,created_at)
               VALUES(?,?,?,?,?,?,?,?)""",
            (pid, did, depid, appt_date, appt_time, "Scheduled", reason, _now()),
        )
        appt_id = cur.lastrowid

        try:
            from .queue import generate_token
            generate_token(conn, appointment_id=appt_id, patient_id=pid, dept_id=depid)
        except Exception:
            pass

        log_action(
            conn, user.get("id"), user.get("role"),
            "CREATE", "appointment", str(appt_id),
            {"patient_id": pid, "doctor_id": did, "dept_id": depid, "date": appt_date, "time": appt_time},
        )

        try:
            from .notifications import push_notification
            urows = conn.execute(
                """SELECT u.id FROM users u
                   WHERE u.id = (SELECT user_id FROM doctors WHERE id = ?)
                      OR u.id = (SELECT user_id FROM patients WHERE id = ?)""",
                (did, pid),
            ).fetchall()
            for ur in urows:
                push_notification(
                    conn,
                    user_id=int(ur["id"]),
                    notif_type="appointment",
                    title="New Appointment",
                    message=f"Appointment scheduled for {appt_date} {appt_time}",
                    data={"appointment_id": appt_id},
                )
        except Exception:
            pass

        new_row = conn.execute("SELECT * FROM appointments WHERE id = ?", (appt_id,)).fetchone()
        conn.execute("COMMIT")
        return dict(new_row)
    except (ValueError, PermissionError, PermissionError_):
        conn.execute("ROLLBACK")
        raise
    except sqlite3.Error as e:
        conn.execute("ROLLBACK")
        raise RuntimeError(f"Database error booking appointment: {e}") from e


def list_appointments(
    conn: sqlite3.Connection,
    user: dict[str, Any],
    patient_id: Optional[int] = None,
    doctor_id: Optional[int] = None,
    dept_id: Optional[int] = None,
    status: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    limit: int = 500,
) -> list[dict[str, Any]]:
    """List appointments filtered by optional criteria, filtered by row permissions.

    Args:
        conn: Active SQLite connection.
        user: Authenticated user dict.
        patient_id: Filter by patient.
        doctor_id: Filter by doctor.
        dept_id: Filter by department.
        status: Filter by status.
        date_from: Lower bound on appointment_date.
        date_to: Upper bound on appointment_date.
        limit: Max rows (default 500).

    Returns:
        List of appointment dicts viewable by the user.

    Raises:
        PermissionError: If user not authenticated.
    """
    if not user:
        raise PermissionError("Authentication required")

    params: list[Any] = []
    where: list[str] = ["1=1"]
    if patient_id is not None:
        where.append("a.patient_id = ?"); params.append(int(patient_id))
    if doctor_id is not None:
        where.append("a.doctor_id = ?"); params.append(int(doctor_id))
    if dept_id is not None:
        where.append("a.department_id = ?"); params.append(int(dept_id))
    if status:
        where.append("a.status = ?"); params.append(status)
    if date_from:
        where.append("date(a.appointment_date) >= date(?)"); params.append(date_from)
    if date_to:
        where.append("date(a.appointment_date) <= date(?)"); params.append(date_to)

    sql = f"""SELECT a.*, d.name AS dept_name,
                     doc.user_id AS doctor_user_id,
                     u.full_name AS doctor_name,
                     p.first_name AS patient_first_name,
                     p.last_name AS patient_last_name,
                     p.patient_id AS patient_code
              FROM appointments a
              LEFT JOIN departments d ON d.id = a.department_id
              LEFT JOIN doctors doc ON doc.id = a.doctor_id
              LEFT JOIN users u ON u.id = doc.user_id
              LEFT JOIN patients p ON p.id = a.patient_id
              WHERE {" AND ".join(where)}
              ORDER BY date(a.appointment_date) DESC, time(a.appointment_time) DESC
              LIMIT ?"""
    params.append(int(limit))
    rows = conn.execute(sql, params).fetchall()

    results: list[dict[str, Any]] = []
    for r in rows:
        d = dict(r)
        if can_view_appointment(conn, user, d["patient_id"], d.get("doctor_user_id")):
            results.append(d)
    return results


def reschedule_appointment(
    conn: sqlite3.Connection,
    user: dict[str, Any],
    appt_id: int,
    new_date: str,
    new_time: str,
) -> dict[str, Any]:
    """Reschedule an existing appointment to a new date/time with conflict check.

    Args:
        conn: Active SQLite connection.
        user: Authenticated user dict.
        appt_id: Appointment id.
        new_date: New date YYYY-MM-DD.
        new_time: New time HH:MM.

    Returns:
        Updated appointment dict.

    Raises:
        PermissionError: If user lacks booking rights.
        ValueError: If appointment missing or conflict.
        RuntimeError: On unexpected database error.
    """
    if not can_book_appointment(user):
        raise PermissionError("Not permitted to reschedule appointments")
    if not new_date or not new_time:
        raise ValueError("new_date and new_time are required")

    aid = int(appt_id)
    conn.execute("BEGIN IMMEDIATE")
    try:
        ex = conn.execute("SELECT * FROM appointments WHERE id = ?", (aid,)).fetchone()
        if not ex:
            raise ValueError(f"Appointment {aid} not found")
        if ex["status"] in ("Cancelled", "Completed"):
            raise ValueError(f"Cannot reschedule appointment in status {ex['status']}")

        if not can_view_appointment(conn, user, ex["patient_id"], None) and not can_cancel_any_appointment(user):
            raise PermissionError("Not permitted to reschedule this appointment")

        if appointment_conflict_exists(conn, int(ex["doctor_id"]), new_date, new_time, exclude_appt_id=aid):
            raise ValueError("Conflict")

        old_date, old_time = ex["appointment_date"], ex["appointment_time"]
        conn.execute(
            "UPDATE appointments SET appointment_date = ?, appointment_time = ?, status = 'Scheduled' WHERE id = ?",
            (new_date, new_time, aid),
        )
        log_action(
            conn, user.get("id"), user.get("role"),
            "UPDATE", "appointment", str(aid),
            {"reschedule_from": f"{old_date} {old_time}", "reschedule_to": f"{new_date} {new_time}"},
        )

        try:
            from .notifications import push_notification
            urows = conn.execute(
                """SELECT u.id FROM users u
                   WHERE u.id = (SELECT user_id FROM doctors WHERE id = ?)
                      OR u.id = (SELECT user_id FROM patients WHERE id = ?)""",
                (ex["doctor_id"], ex["patient_id"]),
            ).fetchall()
            for ur in urows:
                push_notification(
                    conn,
                    user_id=int(ur["id"]),
                    notif_type="appointment",
                    title="Appointment Rescheduled",
                    message=f"Appointment moved to {new_date} {new_time}",
                    data={"appointment_id": aid},
                )
        except Exception:
            pass

        updated = conn.execute("SELECT * FROM appointments WHERE id = ?", (aid,)).fetchone()
        conn.execute("COMMIT")
        return dict(updated)
    except (ValueError, PermissionError, PermissionError_):
        conn.execute("ROLLBACK")
        raise
    except sqlite3.Error as e:
        conn.execute("ROLLBACK")
        raise RuntimeError(f"Database error rescheduling appointment: {e}") from e


def cancel_appointment(
    conn: sqlite3.Connection,
    user: dict[str, Any],
    appt_id: int,
    reason: str = "",
) -> dict[str, Any]:
    """Cancel appointment and cancel any linked queue tokens.

    Args:
        conn: Active SQLite connection.
        user: Authenticated user dict.
        appt_id: Appointment id to cancel.
        reason: Optional cancellation reason.

    Returns:
        Updated appointment dict (status Cancelled).

    Raises:
        PermissionError: If user lacks cancellation rights.
        ValueError: If appointment missing or already cancelled/completed.
        RuntimeError: On unexpected database error.
    """
    aid = int(appt_id)
    conn.execute("BEGIN IMMEDIATE")
    try:
        ex = conn.execute("SELECT * FROM appointments WHERE id = ?", (aid,)).fetchone()
        if not ex:
            raise ValueError(f"Appointment {aid} not found")
        if ex["status"] in ("Cancelled", "Completed"):
            raise ValueError(f"Appointment already {ex['status']}")

        is_patient_own = (
            user.get("role") == "Patient"
            and can_view_appointment(conn, user, ex["patient_id"], None)
        )
        if not (can_cancel_any_appointment(user) or is_patient_own):
            raise PermissionError("Not permitted to cancel this appointment")

        conn.execute(
            "UPDATE appointments SET status = 'Cancelled', cancelled_at = ? WHERE id = ?",
            (_now(), aid),
        )

        tokens = conn.execute(
            "SELECT id FROM queue_tokens WHERE appointment_id = ? AND status != 'Cancelled'",
            (aid,),
        ).fetchall()
        for t in tokens:
            conn.execute("UPDATE queue_tokens SET status = 'Cancelled' WHERE id = ?", (int(t["id"]),))

        log_action(
            conn, user.get("id"), user.get("role"),
            "CANCEL", "appointment", str(aid),
            {"reason": reason, "tokens_cancelled": len(tokens)},
        )

        try:
            from .notifications import push_notification
            urows = conn.execute(
                """SELECT u.id FROM users u
                   WHERE u.id = (SELECT user_id FROM doctors WHERE id = ?)
                      OR u.id = (SELECT user_id FROM patients WHERE id = ?)""",
                (ex["doctor_id"], ex["patient_id"]),
            ).fetchall()
            for ur in urows:
                push_notification(
                    conn,
                    user_id=int(ur["id"]),
                    notif_type="appointment",
                    title="Appointment Cancelled",
                    message=f"Appointment cancelled. Reason: {reason or 'Not provided'}",
                    data={"appointment_id": aid},
                )
        except Exception:
            pass

        updated = conn.execute("SELECT * FROM appointments WHERE id = ?", (aid,)).fetchone()
        conn.execute("COMMIT")
        return dict(updated)
    except (ValueError, PermissionError, PermissionError_):
        conn.execute("ROLLBACK")
        raise
    except sqlite3.Error as e:
        conn.execute("ROLLBACK")
        raise RuntimeError(f"Database error cancelling appointment: {e}") from e


def update_status(
    conn: sqlite3.Connection,
    user: dict[str, Any],
    appt_id: int,
    status: str,
) -> dict[str, Any]:
    """Transition appointment status with validation against allowed moves.

    Args:
        conn: Active SQLite connection.
        user: Authenticated user dict.
        appt_id: Appointment id.
        status: New status. Must be one of VALID_APPOINTMENT_STATUSES and allowed transition.

    Returns:
        Updated appointment dict.

    Raises:
        PermissionError: If user lacks staff role.
        ValueError: If status invalid, transition disallowed, or appointment missing.
        RuntimeError: On unexpected database error.
    """
    require_role(user, ["Admin", "Doctor", "Nurse"])
    if status not in VALID_APPOINTMENT_STATUSES:
        raise ValueError(f"Invalid status '{status}'. Allowed: {sorted(VALID_APPOINTMENT_STATUSES)}")

    aid = int(appt_id)
    conn.execute("BEGIN IMMEDIATE")
    try:
        ex = conn.execute("SELECT * FROM appointments WHERE id = ?", (aid,)).fetchone()
        if not ex:
            raise ValueError(f"Appointment {aid} not found")
        current = ex["status"]
        if current == status:
            conn.execute("COMMIT")
            return dict(ex)
        if status not in VALID_TRANSITIONS.get(current, set()):
            raise ValueError(f"Disallowed status transition {current} -> {status}")

        if status == "Cancelled":
            conn.execute("UPDATE appointments SET status = ?, cancelled_at = ? WHERE id = ?", (status, _now(), aid))
        else:
            conn.execute("UPDATE appointments SET status = ? WHERE id = ?", (status, aid))

        log_action(
            conn, user.get("id"), user.get("role"),
            "UPDATE", "appointment", str(aid),
            {"status_from": current, "status_to": status},
        )
        updated = conn.execute("SELECT * FROM appointments WHERE id = ?", (aid,)).fetchone()
        conn.execute("COMMIT")
        return dict(updated)
    except (ValueError, PermissionError, PermissionError_):
        conn.execute("ROLLBACK")
        raise
    except sqlite3.Error as e:
        conn.execute("ROLLBACK")
        raise RuntimeError(f"Database error updating appointment status: {e}") from e
