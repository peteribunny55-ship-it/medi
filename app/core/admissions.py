from __future__ import annotations

import sqlite3
from datetime import datetime
from statistics import median
from typing import Any, Optional

from .audit import log_action
from .permissions import require_role, can_allocate_bed, can_manage_beds


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _minutes_between(a_str: str, b_str: str) -> float:
    try:
        a = datetime.strptime(a_str[:19], "%Y-%m-%d %H:%M:%S")
        b = datetime.strptime(b_str[:19], "%Y-%m-%d %H:%M:%S")
    except Exception:
        return 0.0
    return (b - a).total_seconds() / 60.0


def allocate_bed(
    conn: sqlite3.Connection,
    user: Optional[dict[str, Any]],
    patient_id: int,
    bed_id: int,
    doctor_id: Optional[int] = None,
    admission_type: str = "Elective",
    diagnosis: Optional[str] = None,
) -> dict[str, Any]:
    """Allocate a bed to a patient (create or update admission).

    Args:
        conn: SQLite connection.
        user: Actor user (Admin, Nurse).
        patient_id: Patient id.
        bed_id: Available bed id.
        doctor_id: Optional doctor id.
        admission_type: 'Elective' or 'Emergency'.
        diagnosis: Optional diagnosis text.

    Returns:
        Admissions dict.

    Raises:
        PermissionError_: If user cannot allocate a bed.
        ValueError: If bed not available or patient already admitted.
    """
    require_role(user, ["Admin", "Nurse"])
    if not patient_id or not bed_id:
        raise ValueError("patient_id and bed_id are required")
    bed_row = conn.execute("SELECT * FROM beds WHERE id=?", (int(bed_id),)).fetchone()
    if not bed_row:
        raise ValueError(f"bed id {bed_id} not found")
    if str(bed_row["status"]) != "Available":
        raise ValueError(f"bed id {bed_id} is not Available")
    existing = conn.execute(
        "SELECT id FROM admissions WHERE patient_id=? AND status IN ('Admitted','Triage','InTreatment','DischargePending')",
        (int(patient_id),),
    ).fetchone()
    if existing:
        raise ValueError(f"patient id {patient_id} already has an active admission")
    admitted_at = _now()
    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            "UPDATE beds SET status='Occupied', current_patient_id=? WHERE id=?",
            (int(patient_id), int(bed_id)),
        )
        cur = conn.cursor()
        cur.execute(
            """INSERT INTO admissions(patient_id,bed_id,doctor_id,admitted_at,status,admission_type,diagnosis)
               VALUES(?,?,?,?,?,?,?)""",
            (
                int(patient_id), int(bed_id),
                int(doctor_id) if doctor_id else None,
                admitted_at, "Admitted", str(admission_type)[:32],
                str(diagnosis)[:2000] if diagnosis else None,
            ),
        )
        adm_id = int(cur.lastrowid or 0)
        log_action(
            conn,
            int(user["id"]) if user else None,
            user.get("role") if user else None,
            "CREATE",
            "admission",
            str(adm_id),
            {
                "patient_id": int(patient_id),
                "bed_id": int(bed_id),
                "doctor_id": doctor_id,
                "admission_type": str(admission_type),
            },
        )
        conn.execute("COMMIT")
    except Exception as exc:
        conn.execute("ROLLBACK")
        raise exc
    row = conn.execute("SELECT * FROM admissions WHERE id=?", (adm_id,)).fetchone()
    return dict(row)


def discharge(
    conn: sqlite3.Connection,
    user: Optional[dict[str, Any]],
    admission_id: int,
) -> dict[str, Any]:
    """Discharge an admission and free the associated bed.

    Args:
        conn: SQLite connection.
        user: Actor user (Admin, Nurse, Doctor).
        admission_id: Admission id.

    Returns:
        Updated admissions dict.

    Raises:
        PermissionError_: If user cannot manage beds.
        ValueError: If admission not found or already discharged.
    """
    require_role(user, ["Admin", "Nurse", "Doctor"])
    row = conn.execute("SELECT * FROM admissions WHERE id=?", (int(admission_id),)).fetchone()
    if not row:
        raise ValueError(f"admission id {admission_id} not found")
    if str(row["status"]) == "Discharged":
        raise ValueError(f"admission id {admission_id} already discharged")
    discharged_at = _now()
    bed_id = int(row["bed_id"]) if row["bed_id"] else None
    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            "UPDATE admissions SET status='Discharged', discharged_at=? WHERE id=?",
            (discharged_at, int(admission_id)),
        )
        if bed_id:
            conn.execute(
                "UPDATE beds SET status='Available', current_patient_id=NULL WHERE id=?",
                (bed_id,),
            )
        log_action(
            conn,
            int(user["id"]) if user else None,
            user.get("role") if user else None,
            "UPDATE",
            "admission",
            str(admission_id),
            {"new_status": "Discharged", "discharged_at": discharged_at},
        )
        conn.execute("COMMIT")
    except Exception as exc:
        conn.execute("ROLLBACK")
        raise exc
    updated = conn.execute("SELECT * FROM admissions WHERE id=?", (int(admission_id),)).fetchone()
    return dict(updated)


def flow_timeline(
    conn: sqlite3.Connection,
    patient_id: Optional[int] = None,
    admission_id: Optional[int] = None,
) -> list[dict[str, Any]]:
    """Build a timeline of workflow events for a patient or admission.

    Combines admissions, queue tokens, and lab requests into a single
    chronological list of step events.

    Args:
        conn: SQLite connection.
        patient_id: Optional patient filter.
        admission_id: Optional admission filter.

    Returns:
        List of timeline event dicts: {step, ts, meta}.
    """
    events: list[dict[str, Any]] = []
    if admission_id:
        adm = conn.execute("SELECT * FROM admissions WHERE id=?", (int(admission_id),)).fetchone()
        if adm:
            if adm["admitted_at"]:
                events.append({"step": "Admission", "ts": str(adm["admitted_at"]), "meta": {"admission_id": int(adm["id"]), "status": str(adm["status"])}})
            if adm["discharged_at"]:
                events.append({"step": "Discharge", "ts": str(adm["discharged_at"]), "meta": {"admission_id": int(adm["id"])}})
            pt_id = int(adm["patient_id"])
        else:
            pt_id = patient_id if patient_id else 0
    else:
        pt_id = patient_id if patient_id else 0
    if pt_id:
        for adm in conn.execute(
            "SELECT * FROM admissions WHERE patient_id=? ORDER BY id",
            (int(pt_id),),
        ).fetchall():
            if admission_id and int(adm["id"]) != int(admission_id):
                continue
            if adm["admitted_at"]:
                events.append({"step": "Admission", "ts": str(adm["admitted_at"]), "meta": {"admission_id": int(adm["id"]), "status": str(adm["status"])}})
            if adm["discharged_at"]:
                events.append({"step": "Discharge", "ts": str(adm["discharged_at"]), "meta": {"admission_id": int(adm["id"])}})
        for q in conn.execute(
            "SELECT * FROM queue_tokens WHERE patient_id=? ORDER BY id",
            (int(pt_id),),
        ).fetchall():
            if q["created_at"]:
                events.append({"step": "Queue Created", "ts": str(q["created_at"]), "meta": {"queue_id": int(q["id"]), "token": str(q["prefix"]) + str(q["token_no"])}})
            if q["called_at"]:
                events.append({"step": "Queue Called", "ts": str(q["called_at"]), "meta": {"queue_id": int(q["id"])}})
            if q["service_started_at"]:
                events.append({"step": "Service Start", "ts": str(q["service_started_at"]), "meta": {"queue_id": int(q["id"])}})
            if q["completed_at"]:
                events.append({"step": "Service Complete", "ts": str(q["completed_at"]), "meta": {"queue_id": int(q["id"])}})
        for lr in conn.execute(
            "SELECT * FROM lab_requests WHERE patient_id=? ORDER BY id",
            (int(pt_id),),
        ).fetchall():
            if lr["ordered_at"]:
                events.append({"step": "Lab Ordered", "ts": str(lr["ordered_at"]), "meta": {"lab_id": int(lr["id"]), "test": str(lr["test_type"])}})
            if lr["picked_up_at"]:
                events.append({"step": "Lab Pickup", "ts": str(lr["picked_up_at"]), "meta": {"lab_id": int(lr["id"])}})
            if lr["resulted_at"]:
                events.append({"step": "Lab Result", "ts": str(lr["resulted_at"]), "meta": {"lab_id": int(lr["id"])}})
    events.sort(key=lambda e: str(e.get("ts", "")))
    return events


def _alert_level(minutes: float) -> str:
    if minutes <= 30:
        return "Normal"
    if minutes <= 120:
        return "Warning"
    return "Critical"


def bottleneck_detection(
    conn: sqlite3.Connection,
    lookback_days: int = 30,
) -> list[dict[str, Any]]:
    """Detect workflow bottlenecks across Order->Lab Pickup, Admission->DischargePending, Queue->Service Start steps.

    Inserts summary rows into bottleneck_records and returns the latest per step/dept.

    Args:
        conn: SQLite connection.
        lookback_days: Days of history to analyze, default 30.

    Returns:
        List of {workflow_step, dept_id, median_dwell_minutes, alert_level, sample_count}.
    """
    records: list[dict[str, Any]] = []
    lab_rows = conn.execute(
        """
        SELECT lr.*, u.department_id AS dept_id
        FROM lab_requests lr
        LEFT JOIN users u ON u.id = lr.requested_by
        WHERE lr.ordered_at IS NOT NULL AND lr.picked_up_at IS NOT NULL
          AND date(lr.ordered_at) >= date('now', '-' || ? || ' days')
        """,
        (int(lookback_days),),
    ).fetchall()
    by_dept_lab: dict[Any, list[float]] = {}
    for r in lab_rows:
        dept = r["dept_id"]
        dwell = _minutes_between(str(r["ordered_at"]), str(r["picked_up_at"]))
        if dwell > 0:
            by_dept_lab.setdefault(dept, []).append(dwell)
    for dept, vals in by_dept_lab.items():
        if not vals:
            continue
        med = float(median(vals))
        records.append({
            "workflow_step": "Order->Lab Pickup",
            "department_id": int(dept) if dept else None,
            "median_dwell_minutes": round(med, 2),
            "alert_level": _alert_level(med),
            "sample_count": len(vals),
        })
    adm_rows = conn.execute(
        """
        SELECT a.*, b.department_id AS dept_id
        FROM admissions a
        LEFT JOIN beds b ON b.id = a.bed_id
        WHERE a.admitted_at IS NOT NULL AND a.discharged_at IS NOT NULL
          AND date(a.admitted_at) >= date('now', '-' || ? || ' days')
        """,
        (int(lookback_days),),
    ).fetchall()
    by_dept_adm: dict[Any, list[float]] = {}
    for r in adm_rows:
        dept = r["dept_id"]
        dwell = _minutes_between(str(r["admitted_at"]), str(r["discharged_at"]))
        if dwell > 0:
            by_dept_adm.setdefault(dept, []).append(dwell)
    for dept, vals in by_dept_adm.items():
        if not vals:
            continue
        med = float(median(vals))
        records.append({
            "workflow_step": "Admission->DischargePending",
            "department_id": int(dept) if dept else None,
            "median_dwell_minutes": round(med, 2),
            "alert_level": _alert_level(med),
            "sample_count": len(vals),
        })
    queue_rows = conn.execute(
        """
        SELECT qt.*, qt.department_id AS dept_id
        FROM queue_tokens qt
        WHERE qt.created_at IS NOT NULL AND qt.service_started_at IS NOT NULL
          AND date(qt.created_at) >= date('now', '-' || ? || ' days')
        """,
        (int(lookback_days),),
    ).fetchall()
    by_dept_q: dict[Any, list[float]] = {}
    for r in queue_rows:
        dept = r["dept_id"]
        dwell = _minutes_between(str(r["created_at"]), str(r["service_started_at"]))
        if dwell > 0:
            by_dept_q.setdefault(dept, []).append(dwell)
    for dept, vals in by_dept_q.items():
        if not vals:
            continue
        med = float(median(vals))
        records.append({
            "workflow_step": "Queue->Service Start",
            "department_id": int(dept) if dept else None,
            "median_dwell_minutes": round(med, 2),
            "alert_level": _alert_level(med),
            "sample_count": len(vals),
        })
    try:
        conn.execute("BEGIN IMMEDIATE")
        cur = conn.cursor()
        for rec in records:
            cur.execute(
                """INSERT INTO bottleneck_records(workflow_step,department_id,observed_at,median_dwell_minutes,alert_level,sample_count)
                   VALUES(?,?,datetime('now'),?,?,?)""",
                (
                    rec["workflow_step"],
                    rec["department_id"],
                    rec["median_dwell_minutes"],
                    rec["alert_level"],
                    int(rec["sample_count"]),
                ),
            )
        conn.execute("COMMIT")
    except Exception as exc:
        conn.execute("ROLLBACK")
        raise exc
    return records
