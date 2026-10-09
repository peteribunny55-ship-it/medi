from __future__ import annotations

import sqlite3
from typing import Any, Optional

import pandas as pd

from .permissions import require_role, can_view_reports


def _apply_common_filters(
    base_sql: str,
    params: list[Any],
    date_from: Optional[str],
    date_to: Optional[str],
    dept_id: Optional[int],
    date_col: str,
    dept_col: Optional[str] = None,
) -> tuple[str, list[Any]]:
    sql = base_sql
    if date_from:
        sql += f" AND date({date_col}) >= date(?)"
        params.append(date_from)
    if date_to:
        sql += f" AND date({date_col}) <= date(?)"
        params.append(date_to)
    if dept_id is not None and dept_col:
        sql += f" AND {dept_col} = ?"
        params.append(int(dept_id))
    return sql, params


def build_patients_registrations_report(
    conn: sqlite3.Connection,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    dept_id: Optional[int] = None,
) -> pd.DataFrame:
    """Patients registration report.

    Args:
        conn: SQLite connection.
        date_from: Inclusive start date filter on patients.created_at.
        date_to: Inclusive end date filter.
        dept_id: Unused for patients report (accepted for API consistency).

    Returns:
        DataFrame with patient id, patient_id code, name, contact info, created_at.
    """
    sql = "SELECT id, patient_id, first_name, last_name, dob, gender, phone, email, created_at FROM patients WHERE 1=1"
    params: list[Any] = []
    sql, params = _apply_common_filters(sql, params, date_from, date_to, None, "created_at")
    sql += " ORDER BY id"
    rows = conn.execute(sql, params).fetchall()
    return pd.DataFrame([dict(r) for r in rows])


def build_appointments_report(
    conn: sqlite3.Connection,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    dept_id: Optional[int] = None,
) -> pd.DataFrame:
    """Appointments report joined with patient, doctor, department names.

    Args:
        conn: SQLite connection.
        date_from: Appointments on/after date.
        date_to: Appointments on/before date.
        dept_id: Department filter.

    Returns:
        DataFrame columns: appointment_id, appointment_date, appointment_time, status, reason,
        department_name, patient_id, patient_full_name, doctor_id, doctor_name.
    """
    sql = """
        SELECT a.id AS appointment_id, a.appointment_date, a.appointment_time, a.status, a.reason,
               d.name AS department_name,
               p.id AS patient_id, p.first_name || ' ' || p.last_name AS patient_full_name,
               u.id AS doctor_user_id, u.full_name AS doctor_name
        FROM appointments a
        LEFT JOIN departments d ON d.id = a.department_id
        LEFT JOIN patients p ON p.id = a.patient_id
        LEFT JOIN doctors dc ON dc.id = a.doctor_id
        LEFT JOIN users u ON u.id = dc.user_id
        WHERE 1=1
    """
    params: list[Any] = []
    sql, params = _apply_common_filters(sql, params, date_from, date_to, dept_id, "a.appointment_date", "a.department_id")
    sql += " ORDER BY a.appointment_date, a.appointment_time, a.id"
    rows = conn.execute(sql, params).fetchall()
    return pd.DataFrame([dict(r) for r in rows])


def build_waiting_time_trends_report(
    conn: sqlite3.Connection,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    dept_id: Optional[int] = None,
) -> pd.DataFrame:
    """Queue waiting time trends per department per day.

    Args:
        conn: SQLite connection.
        date_from: Created on/after.
        date_to: Created on/before.
        dept_id: Department filter.

    Returns:
        DataFrame columns: day, department_id, department_name, queue_count,
        avg_wait_minutes, avg_service_minutes, p95_estimated_wait.
    """
    sql = """
        SELECT date(qt.created_at) AS day,
               qt.department_id,
               d.name AS department_name,
               COUNT(*) AS queue_count,
               AVG(qt.estimated_wait_minutes) AS avg_wait_minutes,
               AVG(
                   CASE WHEN qt.service_started_at IS NOT NULL AND qt.called_at IS NOT NULL
                        THEN (strftime('%s', qt.service_started_at) - strftime('%s', qt.called_at)) / 60.0
                        ELSE NULL END
               ) AS avg_service_minutes,
               MAX(qt.estimated_wait_minutes) AS p95_estimated_wait
        FROM queue_tokens qt
        LEFT JOIN departments d ON d.id = qt.department_id
        WHERE 1=1
    """
    params: list[Any] = []
    sql, params = _apply_common_filters(sql, params, date_from, date_to, dept_id, "qt.created_at", "qt.department_id")
    sql += " GROUP BY day, qt.department_id ORDER BY day DESC, qt.department_id"
    rows = conn.execute(sql, params).fetchall()
    return pd.DataFrame([dict(r) for r in rows])


def build_bed_utilization_report(
    conn: sqlite3.Connection,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    dept_id: Optional[int] = None,
) -> pd.DataFrame:
    """Bed capacity and utilization by department.

    Args:
        conn: SQLite connection.
        date_from: Unused for static snapshot (accepted for API consistency).
        date_to: Unused for static snapshot.
        dept_id: Department filter.

    Returns:
        DataFrame columns: department_id, department_name, total_beds, occupied_beds,
        available_beds, occupancy_pct, ward_distribution.
    """
    sql = """
        SELECT b.department_id,
               d.name AS department_name,
               COUNT(*) AS total_beds,
               SUM(CASE WHEN b.status='Occupied' THEN 1 ELSE 0 END) AS occupied_beds,
               SUM(CASE WHEN b.status='Available' THEN 1 ELSE 0 END) AS available_beds,
               ROUND(100.0 * SUM(CASE WHEN b.status='Occupied' THEN 1 ELSE 0 END) / NULLIF(COUNT(*),0), 2) AS occupancy_pct
        FROM beds b
        LEFT JOIN departments d ON d.id = b.department_id
        WHERE 1=1
    """
    params: list[Any] = []
    if dept_id is not None:
        sql += " AND b.department_id = ?"
        params.append(int(dept_id))
    sql += " GROUP BY b.department_id ORDER BY occupancy_pct DESC"
    rows = conn.execute(sql, params).fetchall()
    return pd.DataFrame([dict(r) for r in rows])


def build_staff_workload_report(
    conn: sqlite3.Connection,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    dept_id: Optional[int] = None,
) -> pd.DataFrame:
    """Staff workload measured by scheduled shifts per period.

    Args:
        conn: SQLite connection.
        date_from: Schedule on/after.
        date_to: Schedule on/before.
        dept_id: Department filter.

    Returns:
        DataFrame columns: staff_id, user_id, full_name, role, department_id,
        department_name, shifts_scheduled, estimated_hours, scheduled_days.
    """
    sql = """
        SELECT s.id AS staff_id, u.id AS user_id, u.full_name, s.role,
               s.department_id, d.name AS department_name,
               COUNT(sc.id) AS shifts_scheduled,
               COUNT(sc.id) * 8 AS estimated_hours,
               COUNT(DISTINCT sc.schedule_date) AS scheduled_days
        FROM staff s
        JOIN users u ON u.id = s.user_id
        LEFT JOIN departments d ON d.id = s.department_id
        LEFT JOIN schedules sc ON sc.staff_id = s.id
        WHERE 1=1
    """
    params: list[Any] = []
    if dept_id is not None:
        sql += " AND s.department_id = ?"
        params.append(int(dept_id))
    if date_from:
        sql += " AND (sc.id IS NULL OR date(sc.schedule_date) >= date(?))"
        params.append(date_from)
    if date_to:
        sql += " AND (sc.id IS NULL OR date(sc.schedule_date) <= date(?))"
        params.append(date_to)
    sql += " GROUP BY s.id ORDER BY shifts_scheduled DESC"
    rows = conn.execute(sql, params).fetchall()
    return pd.DataFrame([dict(r) for r in rows])


def build_or_utilization_report(
    conn: sqlite3.Connection,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    dept_id: Optional[int] = None,
) -> pd.DataFrame:
    """Operating room utilization report.

    Args:
        conn: SQLite connection.
        date_from: Planned start on/after.
        date_to: Planned start on/before.
        dept_id: Department filter.

    Returns:
        DataFrame columns: or_id, room_no, department_id, department_name,
        total_bookings, approved_bookings, total_planned_minutes, avg_duration_min, status.
    """
    sql = """
        SELECT or_.id AS or_id, or_.room_no, or_.department_id, d.name AS department_name,
               COUNT(os.id) AS total_bookings,
               SUM(CASE WHEN os.status IN ('Approved','Confirmed') THEN 1 ELSE 0 END) AS approved_bookings,
               SUM(
                   CASE WHEN os.planned_start IS NOT NULL AND os.planned_end IS NOT NULL
                        THEN (strftime('%s', os.planned_end) - strftime('%s', os.planned_start)) / 60.0
                        ELSE COALESCE(os.estimated_duration_min,0) END
               ) AS total_planned_minutes,
               ROUND(AVG(COALESCE(os.estimated_duration_min,0)),2) AS avg_duration_min,
               or_.status
        FROM operating_rooms or_
        LEFT JOIN departments d ON d.id = or_.department_id
        LEFT JOIN or_schedules os ON os.or_id = or_.id
        WHERE 1=1
    """
    params: list[Any] = []
    if dept_id is not None:
        sql += " AND or_.department_id = ?"
        params.append(int(dept_id))
    if date_from:
        sql += " AND (os.id IS NULL OR date(os.planned_start) >= date(?))"
        params.append(date_from)
    if date_to:
        sql += " AND (os.id IS NULL OR date(os.planned_start) <= date(?))"
        params.append(date_to)
    sql += " GROUP BY or_.id ORDER BY total_planned_minutes DESC"
    rows = conn.execute(sql, params).fetchall()
    return pd.DataFrame([dict(r) for r in rows])


def build_inventory_alerts_report(
    conn: sqlite3.Connection,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    dept_id: Optional[int] = None,
) -> pd.DataFrame:
    """Inventory alerts: low-stock and near-expiry items.

    Args:
        conn: SQLite connection.
        date_from: Unused (accepted for API consistency).
        date_to: Unused.
        dept_id: Unused (inventory is global).

    Returns:
        DataFrame columns: item_id, sku, name, category, unit, quantity,
        reorder_threshold, expiry_date, supplier, alert_type.
    """
    sql = """
        SELECT id AS item_id, sku, name, category, unit, quantity, reorder_threshold,
               expiry_date, supplier,
               CASE
                   WHEN quantity <= reorder_threshold AND expiry_date IS NOT NULL AND date(expiry_date) <= date('now','+14 days') THEN 'Low Stock + Near Expiry'
                   WHEN quantity <= reorder_threshold THEN 'Low Stock'
                   WHEN expiry_date IS NOT NULL AND date(expiry_date) <= date('now','+14 days') THEN 'Near Expiry'
                   ELSE 'OK'
               END AS alert_type
        FROM inventory_items
        WHERE quantity <= reorder_threshold OR (expiry_date IS NOT NULL AND date(expiry_date) <= date('now','+14 days'))
        ORDER BY category, name
    """
    rows = conn.execute(sql, []).fetchall()
    return pd.DataFrame([dict(r) for r in rows])


def build_emergency_demand_report(
    conn: sqlite3.Connection,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    dept_id: Optional[int] = None,
) -> pd.DataFrame:
    """Emergency department admissions demand by day and triage level.

    Args:
        conn: SQLite connection.
        date_from: Admitted on/after.
        date_to: Admitted on/before.
        dept_id: Unused (Emergency admissions are typed; accepted for consistency).

    Returns:
        DataFrame columns: day, total_emergencies, avg_triage, triage1, triage2, triage3, triage4, triage5,
        discharged_count, still_admitted_count.
    """
    sql = """
        SELECT date(admitted_at) AS day,
               COUNT(*) AS total_emergencies,
               ROUND(AVG(COALESCE(triage_level,0)),2) AS avg_triage,
               SUM(CASE WHEN triage_level=1 THEN 1 ELSE 0 END) AS triage1,
               SUM(CASE WHEN triage_level=2 THEN 1 ELSE 0 END) AS triage2,
               SUM(CASE WHEN triage_level=3 THEN 1 ELSE 0 END) AS triage3,
               SUM(CASE WHEN triage_level=4 THEN 1 ELSE 0 END) AS triage4,
               SUM(CASE WHEN triage_level=5 THEN 1 ELSE 0 END) AS triage5,
               SUM(CASE WHEN status='Discharged' THEN 1 ELSE 0 END) AS discharged_count,
               SUM(CASE WHEN status!='Discharged' THEN 1 ELSE 0 END) AS still_admitted_count
        FROM admissions
        WHERE admission_type='Emergency'
    """
    params: list[Any] = []
    sql, params = _apply_common_filters(sql, params, date_from, date_to, None, "admitted_at")
    sql += " GROUP BY day ORDER BY day DESC"
    rows = conn.execute(sql, params).fetchall()
    return pd.DataFrame([dict(r) for r in rows])


def build_feedback_report(
    conn: sqlite3.Connection,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    dept_id: Optional[int] = None,
) -> pd.DataFrame:
    """Feedback submissions report with status/category breakdown columns.

    Args:
        conn: SQLite connection.
        date_from: Submitted on/after.
        date_to: Submitted on/before.
        dept_id: Department filter.

    Returns:
        DataFrame columns: feedback_id, category, department_id, department_name,
        subject, status, is_anonymous, submitted_at, resolved_at, resolution_notes_trimmed.
    """
    sql = """
        SELECT f.id AS feedback_id, f.category, f.department_id, d.name AS department_name,
               f.subject, f.status, f.is_anonymous, f.submitted_at, f.resolved_at,
               SUBSTR(COALESCE(f.resolution_notes,''),1,80) AS resolution_notes_trimmed
        FROM feedback f
        LEFT JOIN departments d ON d.id = f.department_id
        WHERE 1=1
    """
    params: list[Any] = []
    sql, params = _apply_common_filters(sql, params, date_from, date_to, dept_id, "f.submitted_at", "f.department_id")
    sql += " ORDER BY f.id DESC"
    rows = conn.execute(sql, params).fetchall()
    return pd.DataFrame([dict(r) for r in rows])


def build_audit_log_report(
    conn: sqlite3.Connection,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    dept_id: Optional[int] = None,
) -> pd.DataFrame:
    """Audit log report with summary columns.

    Args:
        conn: SQLite connection.
        date_from: Created on/after.
        date_to: Created on/before.
        dept_id: Unused (audit logs are global; accepted for API consistency).

    Returns:
        DataFrame columns: id, actor_id, actor_role, action, entity_type, entity_id,
        detail_preview, created_at.
    """
    sql = """
        SELECT id, actor_id, actor_role, action, entity_type, entity_id,
               SUBSTR(COALESCE(detail_json,''),1,200) AS detail_preview, created_at
        FROM audit_logs
        WHERE 1=1
    """
    params: list[Any] = []
    sql, params = _apply_common_filters(sql, params, date_from, date_to, None, "created_at")
    sql += " ORDER BY id DESC LIMIT 5000"
    rows = conn.execute(sql, params).fetchall()
    return pd.DataFrame([dict(r) for r in rows])


def build_lab_tat_report(
    conn: sqlite3.Connection,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    dept_id: Optional[int] = None,
) -> pd.DataFrame:
    """Lab turnaround time report.

    Args:
        conn: SQLite connection.
        date_from: Resulted on/after (falls back to ordered_at when not Completed).
        date_to: Resulted on/before.
        dept_id: Department filter via requesting user.

    Returns:
        DataFrame columns: request_id, patient_id, test_type, test_category, priority,
        status, ordered_at, resulted_at, turnaround_minutes, requester_dept_id,
        requester_name, tat_bucket.
    """
    sql = """
        SELECT lr.id AS request_id, lr.patient_id, lr.test_type, lr.test_category,
               lr.priority, lr.status, lr.ordered_at, lr.resulted_at, lr.turnaround_minutes,
               u.department_id AS requester_dept_id, u.full_name AS requester_name,
               CASE
                   WHEN lr.turnaround_minutes IS NULL THEN 'Pending'
                   WHEN lr.turnaround_minutes <= 60 THEN '<= 1h'
                   WHEN lr.turnaround_minutes <= 360 THEN '1-6h'
                   WHEN lr.turnaround_minutes <= 1440 THEN '6-24h'
                   ELSE '> 24h'
               END AS tat_bucket
        FROM lab_requests lr
        LEFT JOIN users u ON u.id = lr.requested_by
        WHERE 1=1
    """
    params: list[Any] = []
    if date_from or date_to:
        sql += " AND (CASE WHEN lr.resulted_at IS NOT NULL THEN date(lr.resulted_at) ELSE date(lr.ordered_at) END) "
        params2: list[Any] = []
        if date_from:
            sql += " >= " + (",>=?" if params2 else "?")
            params.append(date_from)
        if date_from and date_to:
            sql = sql.rsplit(">=", 1)[0] + f"BETWEEN ? AND ?"
            params.pop()
            params += [date_from, date_to]
        elif date_to:
            sql += " <= date(?)"
            params.append(date_to)
    if dept_id is not None:
        sql += " AND u.department_id = ?"
        params.append(int(dept_id))
    sql += " ORDER BY lr.id DESC LIMIT 10000"
    rows = conn.execute(sql, params).fetchall()
    return pd.DataFrame([dict(r) for r in rows])
