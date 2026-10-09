from __future__ import annotations

import sqlite3
from typing import Any, Optional

from .audit import log_action
from .permissions import (
    PermissionError_,
    can_modify_patient,
    can_register_patient,
    can_view_patient,
    require_role,
)


def _now() -> str:
    import datetime as _dt
    return _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _generate_patient_id(conn: sqlite3.Connection) -> str:
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM patients")
    count = cur.fetchone()[0]
    return f"P-{count + 1:04d}"


def create_patient(
    conn: sqlite3.Connection,
    user: dict[str, Any],
    first_name: str,
    last_name: str,
    dob: Optional[str] = None,
    gender: Optional[str] = None,
    phone: Optional[str] = None,
    email: Optional[str] = None,
    address: Optional[str] = None,
    emergency_contact: Optional[str] = None,
) -> dict[str, Any]:
    """Create a new patient record with auto-generated P-XXXX ID.

    Args:
        conn: Active SQLite connection.
        user: Authenticated user dict with id and role keys.
        first_name: Patient first name (required).
        last_name: Patient last name (required).
        dob: Date of birth as YYYY-MM-DD string.
        gender: Patient gender.
        phone: Unique phone number.
        email: Unique email address.
        address: Physical address.
        emergency_contact: Emergency contact details.

    Returns:
        Dict containing the inserted patient row with patient_id, id, etc.

    Raises:
        PermissionError: If user lacks can_register_patient permission.
        ValueError: If required fields missing or phone/email already exists.
        RuntimeError: On unexpected database failure.
    """
    if not can_register_patient(user):
        raise PermissionError("Not permitted to register patients")
    if not first_name or not last_name:
        raise ValueError("first_name and last_name are required")

    conn.execute("BEGIN IMMEDIATE")
    try:
        if phone:
            dup = conn.execute("SELECT id FROM patients WHERE phone = ?", (phone,)).fetchone()
            if dup:
                raise ValueError(f"Phone number '{phone}' is already registered")
        if email:
            dup = conn.execute("SELECT id FROM patients WHERE email = ?", (email,)).fetchone()
            if dup:
                raise ValueError(f"Email '{email}' is already registered")

        patient_id = _generate_patient_id(conn)
        user_id_for_link = int(user["id"]) if user.get("role") == "Patient" else None

        cur = conn.cursor()
        cur.execute(
            """INSERT INTO patients(patient_id,first_name,last_name,dob,gender,phone,email,address,emergency_contact,user_id,created_at)
               VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
            (patient_id, first_name, last_name, dob, gender, phone, email, address, emergency_contact, user_id_for_link, _now()),
        )
        new_id = cur.lastrowid
        row = conn.execute("SELECT * FROM patients WHERE id = ?", (new_id,)).fetchone()
        log_action(
            conn, user.get("id"), user.get("role"),
            "CREATE", "patient", str(new_id),
            {"patient_id": patient_id, "first_name": first_name, "last_name": last_name, "phone": phone, "email": email},
        )
        conn.execute("COMMIT")
        return dict(row)
    except (ValueError, PermissionError, PermissionError_):
        conn.execute("ROLLBACK")
        raise
    except sqlite3.Error as e:
        conn.execute("ROLLBACK")
        raise RuntimeError(f"Database error creating patient: {e}") from e


def search_patients(
    conn: sqlite3.Connection,
    user: dict[str, Any],
    query: str = "",
    dept_id: Optional[int] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    limit: int = 200,
) -> list[dict[str, Any]]:
    """Search patients by name/ID/phone/email with optional filters.

    Args:
        conn: Active SQLite connection.
        user: Authenticated user dict.
        query: Free-text search string matched against first_name, last_name, patient_id, phone, email.
        dept_id: Optional department filter (matches via latest appointment).
        date_from: Optional created_at lower bound.
        date_to: Optional created_at upper bound.
        limit: Maximum rows to return (default 200).

    Returns:
        List of patient dicts that user is permitted to view.

    Raises:
        PermissionError: If user is not authenticated.
    """
    if not user:
        raise PermissionError("Authentication required")

    params: list[Any] = []
    q = "SELECT DISTINCT p.* FROM patients p"
    joins: list[str] = []
    where: list[str] = ["1=1"]

    if dept_id is not None:
        joins.append("LEFT JOIN appointments a ON a.patient_id = p.id")
        where.append("a.department_id = ?")
        params.append(int(dept_id))

    if query:
        like = f"%{query}%"
        where.append("(p.first_name LIKE ? OR p.last_name LIKE ? OR p.patient_id LIKE ? OR p.phone LIKE ? OR p.email LIKE ?)")
        params.extend([like, like, like, like, like])

    if date_from:
        where.append("date(p.created_at) >= date(?)")
        params.append(date_from)
    if date_to:
        where.append("date(p.created_at) <= date(?)")
        params.append(date_to)

    sql = q + (" " + " ".join(joins) if joins else "") + " WHERE " + " AND ".join(where) + " ORDER BY p.id DESC LIMIT ?"
    params.append(int(limit))

    rows = conn.execute(sql, params).fetchall()
    results: list[dict[str, Any]] = []
    for r in rows:
        d = dict(r)
        if can_view_patient(conn, user, d["id"]):
            results.append(d)
    return results


def get_patient_by_id(
    conn: sqlite3.Connection,
    user: dict[str, Any],
    patient_id: Any,
) -> dict[str, Any]:
    """Fetch a single patient by integer row id or patient_id string (P-XXXX).

    Args:
        conn: Active SQLite connection.
        user: Authenticated user dict.
        patient_id: Either the int row id or the P-XXXX string patient identifier.

    Returns:
        Patient dict.

    Raises:
        PermissionError: If user cannot view this patient.
        ValueError: If patient does not exist.
    """
    if not user:
        raise PermissionError("Authentication required")

    if isinstance(patient_id, str) and patient_id.upper().startswith("P-"):
        row = conn.execute("SELECT * FROM patients WHERE patient_id = ?", (patient_id,)).fetchone()
    else:
        row = conn.execute("SELECT * FROM patients WHERE id = ?", (int(patient_id),)).fetchone()

    if not row:
        raise ValueError(f"Patient {patient_id} not found")

    d = dict(row)
    if not can_view_patient(conn, user, d["id"]):
        raise PermissionError("Not permitted to view this patient")
    return d


def update_patient(
    conn: sqlite3.Connection,
    user: dict[str, Any],
    patient_id: Any,
    **fields: Any,
) -> dict[str, Any]:
    """Update mutable patient fields. Only allowed roles may modify.

    Args:
        conn: Active SQLite connection.
        user: Authenticated user dict.
        patient_id: Integer id or P-XXXX string identifier.
        **fields: Allowed keys: first_name, last_name, dob, gender, phone, email, address, emergency_contact.

    Returns:
        Updated patient dict.

    Raises:
        PermissionError: If user lacks modification rights.
        ValueError: If patient missing, unknown fields, or duplicate phone/email.
        RuntimeError: On unexpected database error.
    """
    if not can_modify_patient(user):
        raise PermissionError("Not permitted to modify patients")

    ALLOWED = {"first_name", "last_name", "dob", "gender", "phone", "email", "address", "emergency_contact"}
    unknown = set(fields.keys()) - ALLOWED
    if unknown:
        raise ValueError(f"Unknown patient fields: {sorted(unknown)}")

    conn.execute("BEGIN IMMEDIATE")
    try:
        if isinstance(patient_id, str) and patient_id.upper().startswith("P-"):
            existing = conn.execute("SELECT * FROM patients WHERE patient_id = ?", (patient_id,)).fetchone()
        else:
            existing = conn.execute("SELECT * FROM patients WHERE id = ?", (int(patient_id),)).fetchone()
        if not existing:
            raise ValueError(f"Patient {patient_id} not found")
        pid = int(existing["id"])

        if not can_view_patient(conn, user, pid):
            raise PermissionError("Not permitted to view/modify this patient")

        if "phone" in fields and fields["phone"]:
            dup = conn.execute("SELECT id FROM patients WHERE phone = ? AND id != ?", (fields["phone"], pid)).fetchone()
            if dup:
                raise ValueError(f"Phone '{fields['phone']}' is already registered")
        if "email" in fields and fields["email"]:
            dup = conn.execute("SELECT id FROM patients WHERE email = ? AND id != ?", (fields["email"], pid)).fetchone()
            if dup:
                raise ValueError(f"Email '{fields['email']}' is already registered")

        if fields:
            sets = ", ".join(f"{k} = ?" for k in fields.keys())
            params: list[Any] = list(fields.values()) + [pid]
            conn.execute(f"UPDATE patients SET {sets} WHERE id = ?", params)
            log_action(
                conn, user.get("id"), user.get("role"),
                "UPDATE", "patient", str(pid),
                {"changed_fields": sorted(list(fields.keys()))},
            )

        updated = conn.execute("SELECT * FROM patients WHERE id = ?", (pid,)).fetchone()
        conn.execute("COMMIT")
        return dict(updated)
    except (ValueError, PermissionError, PermissionError_):
        conn.execute("ROLLBACK")
        raise
    except sqlite3.Error as e:
        conn.execute("ROLLBACK")
        raise RuntimeError(f"Database error updating patient: {e}") from e


def list_patients(
    conn: sqlite3.Connection,
    user: dict[str, Any],
    limit: int = 500,
) -> list[dict[str, Any]]:
    """List patients subject to permission filtering.

    Args:
        conn: Active SQLite connection.
        user: Authenticated user dict.
        limit: Maximum number of rows (default 500).

    Returns:
        List of patient dicts visible to user.

    Raises:
        PermissionError: If user is not authenticated.
    """
    if not user:
        raise PermissionError("Authentication required")

    rows = conn.execute(
        "SELECT * FROM patients ORDER BY id DESC LIMIT ?",
        (int(limit),),
    ).fetchall()
    results: list[dict[str, Any]] = []
    for r in rows:
        d = dict(r)
        if can_view_patient(conn, user, d["id"]):
            results.append(d)
    return results


def get_patient_visit_history(
    conn: sqlite3.Connection,
    user: dict[str, Any],
    patient_id: Any,
) -> dict[str, list[dict[str, Any]]]:
    """Return consolidated patient history: appointments, admissions, lab_requests.

    Args:
        conn: Active SQLite connection.
        user: Authenticated user dict.
        patient_id: Integer id or P-XXXX string identifier.

    Returns:
        Dict with keys 'appointments', 'admissions', 'lab_requests', each a list of
        dicts sorted by relevant date descending.

    Raises:
        PermissionError: If user cannot view this patient.
        ValueError: If patient does not exist.
    """
    if not user:
        raise PermissionError("Authentication required")

    if isinstance(patient_id, str) and patient_id.upper().startswith("P-"):
        prow = conn.execute("SELECT id FROM patients WHERE patient_id = ?", (patient_id,)).fetchone()
    else:
        prow = conn.execute("SELECT id FROM patients WHERE id = ?", (int(patient_id),)).fetchone()
    if not prow:
        raise ValueError(f"Patient {patient_id} not found")
    pid = int(prow["id"])

    if not can_view_patient(conn, user, pid):
        raise PermissionError("Not permitted to view this patient")

    appt_rows = conn.execute(
        """SELECT a.*, d.name AS dept_name, u.full_name AS doctor_name
           FROM appointments a
           LEFT JOIN departments d ON d.id = a.department_id
           LEFT JOIN doctors doc ON doc.id = a.doctor_id
           LEFT JOIN users u ON u.id = doc.user_id
           WHERE a.patient_id = ?
           ORDER BY date(a.appointment_date) DESC, time(a.appointment_time) DESC""",
        (pid,),
    ).fetchall()

    adm_rows = conn.execute(
        """SELECT adm.*, b.bed_no, b.ward, d.name AS dept_name
           FROM admissions adm
           LEFT JOIN beds b ON b.id = adm.bed_id
           LEFT JOIN departments d ON d.id = b.department_id
           WHERE adm.patient_id = ?
           ORDER BY date(adm.admitted_at) DESC""",
        (pid,),
    ).fetchall()

    lab_rows = conn.execute(
        """SELECT lr.*, u.full_name AS ordered_by_name
           FROM lab_requests lr
           LEFT JOIN users u ON u.id = lr.requested_by
           WHERE lr.patient_id = ?
           ORDER BY date(lr.ordered_at) DESC""",
        (pid,),
    ).fetchall()

    return {
        "appointments": [dict(r) for r in appt_rows],
        "admissions": [dict(r) for r in adm_rows],
        "lab_requests": [dict(r) for r in lab_rows],
    }
