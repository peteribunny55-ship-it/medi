from __future__ import annotations

import sqlite3
from typing import Any, Optional

from .audit import log_action
from .permissions import (
    PermissionError_,
    can_allocate_bed,
    can_manage_beds,
    can_view_patient,
    require_role,
)


def _now() -> str:
    import datetime as _dt
    return _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def list_beds(
    conn: sqlite3.Connection,
    status: Optional[str] = None,
    dept_id: Optional[int] = None,
    bed_type: Optional[str] = None,
    ward: Optional[str] = None,
) -> list[dict[str, Any]]:
    """List beds optionally filtered by status, department, type, or ward.

    Args:
        conn: Active SQLite connection.
        status: Filter by bed status.
        dept_id: Filter by department id.
        bed_type: Filter by bed type.
        ward: Filter by ward name.

    Returns:
        List of bed dicts augmented with department name and patient name if occupied.
    """
    params: list[Any] = []
    where: list[str] = ["1=1"]
    if status:
        where.append("b.status = ?"); params.append(status)
    if dept_id is not None:
        where.append("b.department_id = ?"); params.append(int(dept_id))
    if bed_type:
        where.append("b.bed_type = ?"); params.append(bed_type)
    if ward:
        where.append("b.ward = ?"); params.append(ward)

    sql = f"""SELECT b.*, d.name AS dept_name,
                     p.first_name AS patient_first_name,
                     p.last_name AS patient_last_name,
                     p.patient_id AS patient_code
              FROM beds b
              LEFT JOIN departments d ON d.id = b.department_id
              LEFT JOIN patients p ON p.id = b.current_patient_id
              WHERE {" AND ".join(where)}
              ORDER BY b.department_id ASC, b.bed_no ASC"""
    rows = conn.execute(sql, params).fetchall()
    return [dict(r) for r in rows]


def get_bed(
    conn: sqlite3.Connection,
    bed_id: int,
) -> dict[str, Any]:
    """Fetch a single bed by its id.

    Args:
        conn: Active SQLite connection.
        bed_id: Bed row id.

    Returns:
        Bed dict augmented with dept name and patient name.

    Raises:
        ValueError: If bed not found.
    """
    if not bed_id:
        raise ValueError("bed_id is required")
    row = conn.execute(
        """SELECT b.*, d.name AS dept_name,
                  p.first_name AS patient_first_name,
                  p.last_name AS patient_last_name,
                  p.patient_id AS patient_code
           FROM beds b
           LEFT JOIN departments d ON d.id = b.department_id
           LEFT JOIN patients p ON p.id = b.current_patient_id
           WHERE b.id = ?""",
        (int(bed_id),),
    ).fetchone()
    if not row:
        raise ValueError(f"Bed {bed_id} not found")
    return dict(row)


def allocate_bed(
    conn: sqlite3.Connection,
    user: dict[str, Any],
    bed_id: int,
    patient_id: int,
    doctor_id: Optional[int] = None,
    diagnosis: str = "",
    admission_type: str = "Elective",
    triage_level: Optional[int] = None,
) -> dict[str, Any]:
    """Allocate an available bed to a patient, creating an admission record.

    Uses BEGIN IMMEDIATE with SELECT ... FOR UPDATE to serialize bed
    assignments atomically.

    Args:
        conn: Active SQLite connection.
        user: Authenticated user dict.
        bed_id: Bed id to allocate (must be Available).
        patient_id: Patient id being admitted.
        doctor_id: Optional attending doctor id.
        diagnosis: Optional admitting diagnosis string.
        admission_type: Admission type. Default 'Elective'.
        triage_level: Optional integer triage level 1..5.

    Returns:
        Newly inserted admission dict (with the bed already updated to Occupied).

    Raises:
        PermissionError: If user lacks bed allocation rights.
        ValueError: If bed missing, bed not free, patient missing, or constraint fails.
        RuntimeError: On unexpected database failure.
    """
    if not can_allocate_bed(user):
        raise PermissionError("Not permitted to allocate beds")
    if not bed_id or not patient_id:
        raise ValueError("bed_id and patient_id are required")
    bid = int(bed_id)
    pid = int(patient_id)

    if not can_view_patient(conn, user, pid):
        raise PermissionError("Not permitted to view this patient")

    conn.execute("BEGIN IMMEDIATE")
    try:
        bed_row = conn.execute(
            "SELECT status FROM beds WHERE id = ?",
            (bid,),
        ).fetchone()
        if not bed_row:
            raise ValueError(f"Bed {bid} not found")
        if bed_row["status"] != "Available":
            raise ValueError("Bed not free")

        prow = conn.execute("SELECT id FROM patients WHERE id = ?", (pid,)).fetchone()
        if not prow:
            raise ValueError(f"Patient {pid} not found")

        admitted_at = _now()
        cur = conn.cursor()
        cur.execute(
            """INSERT INTO admissions(patient_id,bed_id,doctor_id,admitted_at,discharged_at,status,diagnosis,admission_type,triage_level)
               VALUES(?,?,?,?,NULL,'Admitted',?,?,?)""",
            (pid, bid, doctor_id, admitted_at, diagnosis, admission_type, triage_level),
        )
        admission_id = int(cur.lastrowid or 0)

        conn.execute(
            "UPDATE beds SET status = 'Occupied', current_patient_id = ? WHERE id = ?",
            (pid, bid),
        )

        log_action(
            conn, user.get("id"), user.get("role"),
            "ALLOCATE", "bed", str(bid),
            {"patient_id": pid, "admission_id": admission_id, "admission_type": admission_type},
        )
        log_action(
            conn, user.get("id"), user.get("role"),
            "CREATE", "admission", str(admission_id),
            {"bed_id": bid, "patient_id": pid, "doctor_id": doctor_id},
        )

        try:
            from .notifications import push_notification
            urows: list[Any] = []
            pu = conn.execute("SELECT user_id FROM patients WHERE id = ?", (pid,)).fetchone()
            if pu and pu["user_id"]:
                urows.append({"id": pu["user_id"]})
            if doctor_id:
                du = conn.execute("SELECT user_id FROM doctors WHERE id = ?", (int(doctor_id),)).fetchone()
                if du and du["user_id"]:
                    urows.append({"id": du["user_id"]})
            for ur in urows:
                push_notification(
                    conn,
                    user_id=int(ur["id"]),
                    notif_type="admission",
                    title="Patient Admitted",
                    message=f"Admission created for bed id {bid}. Type: {admission_type}",
                    data={"admission_id": admission_id, "bed_id": bid, "patient_id": pid},
                )
        except Exception:
            pass

        adm_row = conn.execute("SELECT * FROM admissions WHERE id = ?", (admission_id,)).fetchone()
        conn.execute("COMMIT")
        return dict(adm_row)
    except (ValueError, PermissionError, PermissionError_):
        conn.execute("ROLLBACK")
        raise
    except sqlite3.Error as e:
        conn.execute("ROLLBACK")
        raise RuntimeError(f"Database error allocating bed: {e}") from e


def discharge_bed(
    conn: sqlite3.Connection,
    user: dict[str, Any],
    admission_id: int,
) -> dict[str, Any]:
    """Discharge an admission and free the associated bed.

    Args:
        conn: Active SQLite connection.
        user: Authenticated user dict.
        admission_id: Admission id to discharge.

    Returns:
        Updated admission dict (status Discharged).

    Raises:
        PermissionError: If user lacks bed management.
        ValueError: If admission missing or already discharged.
        RuntimeError: On unexpected DB error.
    """
    if not can_manage_beds(user):
        raise PermissionError("Not permitted to discharge beds")
    if not admission_id:
        raise ValueError("admission_id is required")
    aid = int(admission_id)

    conn.execute("BEGIN IMMEDIATE")
    try:
        ex = conn.execute("SELECT * FROM admissions WHERE id = ?", (aid,)).fetchone()
        if not ex:
            raise ValueError(f"Admission {aid} not found")
        if ex["status"] == "Discharged":
            raise ValueError("Admission already discharged")

        discharged_at = _now()
        conn.execute(
            "UPDATE admissions SET status = 'Discharged', discharged_at = ? WHERE id = ?",
            (discharged_at, aid),
        )

        bed_id = ex["bed_id"]
        if bed_id:
            conn.execute(
                "UPDATE beds SET status = 'Available', current_patient_id = NULL WHERE id = ?",
                (int(bed_id),),
            )

        log_action(
            conn, user.get("id"), user.get("role"),
            "DISCHARGE", "admission", str(aid),
            {"bed_id": bed_id, "patient_id": ex["patient_id"]},
        )
        if bed_id:
            log_action(
                conn, user.get("id"), user.get("role"),
                "FREE", "bed", str(bed_id),
                {"admission_id": aid, "patient_id": ex["patient_id"]},
            )

        updated = conn.execute("SELECT * FROM admissions WHERE id = ?", (aid,)).fetchone()
        conn.execute("COMMIT")
        return dict(updated)
    except (ValueError, PermissionError, PermissionError_):
        conn.execute("ROLLBACK")
        raise
    except sqlite3.Error as e:
        conn.execute("ROLLBACK")
        raise RuntimeError(f"Database error discharging bed: {e}") from e


def transfer_patient(
    conn: sqlite3.Connection,
    user: dict[str, Any],
    admission_id: int,
    to_bed_id: int,
    reason: str = "",
) -> dict[str, Any]:
    """Atomically transfer a patient from their current bed to a new available bed.

    Args:
        conn: Active SQLite connection.
        user: Authenticated user dict.
        admission_id: Admission id that is currently Admitted / occupying a bed.
        to_bed_id: Destination bed id (must be Available).
        reason: Optional transfer reason string.

    Returns:
        Updated admission dict (bed_id switched) with transfer recorded.

    Raises:
        PermissionError: If user lacks bed management.
        ValueError: If admission missing, no current bed, destination not Available,
            or destination is the same as source.
        RuntimeError: On unexpected DB error.
    """
    if not can_manage_beds(user):
        raise PermissionError("Not permitted to transfer patients")
    if not admission_id or not to_bed_id:
        raise ValueError("admission_id and to_bed_id are required")
    aid = int(admission_id)
    to_bid = int(to_bed_id)

    conn.execute("BEGIN IMMEDIATE")
    try:
        adm = conn.execute("SELECT * FROM admissions WHERE id = ?", (aid,)).fetchone()
        if not adm:
            raise ValueError(f"Admission {aid} not found")
        if adm["status"] != "Admitted":
            raise ValueError(f"Cannot transfer admission in status {adm['status']}")
        from_bid = adm["bed_id"]
        if not from_bid:
            raise ValueError("Admission has no bed assigned; cannot transfer")
        from_bid = int(from_bid)
        if from_bid == to_bid:
            raise ValueError("Destination bed is the same as current bed")

        to_bed_row = conn.execute(
            "SELECT * FROM beds WHERE id = ?",
            (to_bid,),
        ).fetchone()
        if not to_bed_row:
            raise ValueError(f"Bed {to_bid} not found")
        if to_bed_row["status"] != "Available":
            raise ValueError("Destination bed is not available")

        from_bed_row = conn.execute("SELECT * FROM beds WHERE id = ?", (from_bid,)).fetchone()
        from_dept = from_bed_row["department_id"] if from_bed_row else None
        to_dept = to_bed_row["department_id"]
        pid = int(adm["patient_id"])

        conn.execute(
            "UPDATE beds SET status = 'Available', current_patient_id = NULL WHERE id = ?",
            (from_bid,),
        )
        conn.execute(
            "UPDATE beds SET status = 'Occupied', current_patient_id = ? WHERE id = ?",
            (pid, to_bid),
        )
        conn.execute(
            "UPDATE admissions SET bed_id = ? WHERE id = ?",
            (to_bid, aid),
        )
        conn.execute(
            """INSERT INTO transfers(admission_id,from_bed_id,to_bed_id,from_dept,to_dept,transferred_at,reason)
               VALUES(?,?,?,?,?,?,?)""",
            (aid, from_bid, to_bid, from_dept, to_dept, _now(), reason),
        )

        log_action(
            conn, user.get("id"), user.get("role"),
            "TRANSFER", "admission", str(aid),
            {"from_bed_id": from_bid, "to_bed_id": to_bid, "reason": reason},
        )

        updated = conn.execute("SELECT * FROM admissions WHERE id = ?", (aid,)).fetchone()
        conn.execute("COMMIT")
        return dict(updated)
    except (ValueError, PermissionError, PermissionError_):
        conn.execute("ROLLBACK")
        raise
    except sqlite3.Error as e:
        conn.execute("ROLLBACK")
        raise RuntimeError(f"Database error transferring patient: {e}") from e


def bed_utilization(
    conn: sqlite3.Connection,
    dept_id: Optional[int] = None,
) -> list[dict[str, Any]]:
    """Compute bed utilization summary per department.

    Args:
        conn: Active SQLite connection.
        dept_id: Optional single department to filter results.

    Returns:
        List of dicts, one per department (or filtered department), with keys:
        dept (department name), total, occupied, available, maintenance, pct_used.
    """
    params: list[Any] = []
    where: list[str] = ["1=1"]
    if dept_id is not None:
        where.append("b.department_id = ?"); params.append(int(dept_id))

    sql = f"""SELECT d.id AS dept_id, d.name AS dept,
                     COUNT(*) AS total,
                     SUM(CASE WHEN b.status = 'Occupied' THEN 1 ELSE 0 END) AS occupied,
                     SUM(CASE WHEN b.status = 'Available' THEN 1 ELSE 0 END) AS available,
                     SUM(CASE WHEN b.status = 'Maintenance' THEN 1 ELSE 0 END) AS maintenance
              FROM beds b
              LEFT JOIN departments d ON d.id = b.department_id
              WHERE {" AND ".join(where)}
              GROUP BY b.department_id
              ORDER BY d.name ASC"""
    rows = conn.execute(sql, params).fetchall()
    results: list[dict[str, Any]] = []
    for r in rows:
        d = dict(r)
        total = int(d.get("total") or 0)
        occupied = int(d.get("occupied") or 0)
        pct = round((occupied / total) * 100, 2) if total > 0 else 0.0
        results.append({
            "dept": d.get("dept"),
            "total": total,
            "occupied": occupied,
            "available": int(d.get("available") or 0),
            "maintenance": int(d.get("maintenance") or 0),
            "pct_used": pct,
        })
    return results


def utilization_summary(
    conn: sqlite3.Connection,
) -> dict[str, Any]:
    """Compute hospital-wide bed utilization summary statistics.

    Args:
        conn: Active SQLite connection.

    Returns:
        Dict containing total_beds, total, occupied, available, maintenance,
        utilization_rate, and pct_used.
    """
    row = conn.execute(
        """SELECT
             COUNT(*) AS total_beds,
             SUM(CASE WHEN status = 'Occupied' THEN 1 ELSE 0 END) AS occupied,
             SUM(CASE WHEN status = 'Available' THEN 1 ELSE 0 END) AS available,
             SUM(CASE WHEN status = 'Maintenance' THEN 1 ELSE 0 END) AS maintenance
           FROM beds"""
    ).fetchone()

    if not row:
        return {
            "total_beds": 0,
            "total": 0,
            "occupied": 0,
            "available": 0,
            "maintenance": 0,
            "utilization_rate": 0.0,
            "pct_used": 0.0,
        }

    total = int(row["total_beds"] or 0)
    occupied = int(row["occupied"] or 0)
    available = int(row["available"] or 0)
    maintenance = int(row["maintenance"] or 0)
    rate = round((occupied / total) * 100, 2) if total > 0 else 0.0

    return {
        "total_beds": total,
        "total": total,
        "occupied": occupied,
        "available": available,
        "maintenance": maintenance,
        "utilization_rate": rate,
        "pct_used": rate,
    }


def recommend_beds(
    conn: sqlite3.Connection,
    patient_dept_id: Optional[int] = None,
    bed_type_pref: Optional[str] = None,
    n: int = 5,
) -> list[dict[str, Any]]:
    """Recommend available beds via a heuristic AI-style ranking.

    NOTE: This is a heuristic AI recommendation, not a learned model.
    Scoring logic (higher is better):
      +5 same department as patient
      +3 same bed_type as preference
      +1 ward not NULL (structured ward)

    Args:
        conn: Active SQLite connection.
        patient_dept_id: Optional patient's target department id.
        bed_type_pref: Optional preferred bed type string.
        n: Maximum number of recommendations to return (default 5).

    Returns:
        Sorted list of Available bed dicts with a 'score' key added.
    """
    available = list_beds(conn, status="Available")
    scored: list[dict[str, Any]] = []
    for b in available:
        score = 0
        if patient_dept_id is not None and b.get("department_id") is not None:
            if int(b["department_id"]) == int(patient_dept_id):
                score += 5
        if bed_type_pref and b.get("bed_type") == bed_type_pref:
            score += 3
        if b.get("ward"):
            score += 1
        b["score"] = score
        scored.append(b)
    scored.sort(key=lambda x: (x.get("score", 0), x.get("dept_name", "") or ""), reverse=True)
    return scored[: max(1, int(n))]
