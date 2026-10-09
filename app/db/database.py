from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from typing import Iterator

DB_PATH = os.environ.get("HOSPITAL_DB_PATH", os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "..", "data", "hospital.db"
))
DB_PATH = os.path.abspath(DB_PATH)


@contextmanager
def get_db() -> Iterator[sqlite3.Connection]:
    """Context-managed SQLite connection with WAL mode, FK enforcement, and Row factory."""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=30, isolation_level=None, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA foreign_keys=ON;")
        conn.execute("PRAGMA busy_timeout=30000;")
        yield conn
    finally:
        conn.close()


SCHEMA_STATEMENTS: list[str] = [
    """
    CREATE TABLE IF NOT EXISTS roles (
        role_name TEXT PRIMARY KEY,
        description TEXT
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS departments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT UNIQUE NOT NULL,
        description TEXT,
        floor INTEGER DEFAULT 0
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        role TEXT NOT NULL REFERENCES roles(role_name),
        full_name TEXT NOT NULL,
        email TEXT,
        department_id INTEGER REFERENCES departments(id),
        created_at TEXT NOT NULL DEFAULT (datetime('now'))
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS patients (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        patient_id TEXT UNIQUE NOT NULL,
        first_name TEXT NOT NULL,
        last_name TEXT NOT NULL,
        dob TEXT,
        gender TEXT,
        phone TEXT UNIQUE,
        email TEXT UNIQUE,
        address TEXT,
        emergency_contact TEXT,
        user_id INTEGER REFERENCES users(id),
        created_at TEXT NOT NULL DEFAULT (datetime('now'))
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS doctors (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER UNIQUE NOT NULL REFERENCES users(id),
        department_id INTEGER NOT NULL REFERENCES departments(id),
        specialization TEXT,
        license_no TEXT UNIQUE,
        consultation_fee REAL DEFAULT 0,
        avg_consult_minutes INTEGER DEFAULT 20
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS appointments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        patient_id INTEGER NOT NULL REFERENCES patients(id),
        doctor_id INTEGER NOT NULL REFERENCES doctors(id),
        department_id INTEGER NOT NULL REFERENCES departments(id),
        appointment_date TEXT NOT NULL,
        appointment_time TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'Scheduled',
        reason TEXT,
        notes TEXT,
        created_at TEXT NOT NULL DEFAULT (datetime('now')),
        cancelled_at TEXT,
        UNIQUE(doctor_id, appointment_date, appointment_time)
    );
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_appt_patient ON appointments(patient_id);
    CREATE INDEX IF NOT EXISTS idx_appt_doctor_date ON appointments(doctor_id, appointment_date);
    CREATE INDEX IF NOT EXISTS idx_appt_dept_date ON appointments(department_id, appointment_date);
    """,
    """
    CREATE TABLE IF NOT EXISTS queue_tokens (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        token_no INTEGER NOT NULL,
        prefix TEXT NOT NULL,
        appointment_id INTEGER REFERENCES appointments(id),
        patient_id INTEGER NOT NULL REFERENCES patients(id),
        department_id INTEGER NOT NULL REFERENCES departments(id),
        status TEXT NOT NULL DEFAULT 'Waiting',
        called_at TEXT,
        completed_at TEXT,
        estimated_wait_minutes INTEGER DEFAULT 0,
        service_started_at TEXT,
        created_at TEXT NOT NULL DEFAULT (datetime('now'))
    );
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_queue_dept_status ON queue_tokens(department_id, status, created_at);
    """,
    """
    CREATE TABLE IF NOT EXISTS beds (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        bed_no TEXT UNIQUE NOT NULL,
        department_id INTEGER NOT NULL REFERENCES departments(id),
        ward TEXT,
        bed_type TEXT NOT NULL DEFAULT 'General',
        status TEXT NOT NULL DEFAULT 'Available',
        current_patient_id INTEGER REFERENCES patients(id),
        last_maintenance_at TEXT
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS admissions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        patient_id INTEGER NOT NULL REFERENCES patients(id),
        bed_id INTEGER REFERENCES beds(id),
        doctor_id INTEGER REFERENCES doctors(id),
        admitted_at TEXT NOT NULL,
        discharged_at TEXT,
        status TEXT NOT NULL DEFAULT 'Admitted',
        diagnosis TEXT,
        admission_type TEXT DEFAULT 'Elective',
        triage_level INTEGER
    );
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_adm_patient ON admissions(patient_id);
    CREATE INDEX IF NOT EXISTS idx_adm_status ON admissions(status);
    """,
    """
    CREATE TABLE IF NOT EXISTS transfers (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        admission_id INTEGER NOT NULL REFERENCES admissions(id),
        from_bed_id INTEGER REFERENCES beds(id),
        to_bed_id INTEGER REFERENCES beds(id),
        from_dept INTEGER REFERENCES departments(id),
        to_dept INTEGER REFERENCES departments(id),
        transferred_at TEXT NOT NULL,
        reason TEXT
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS staff (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER UNIQUE NOT NULL REFERENCES users(id),
        role TEXT NOT NULL,
        department_id INTEGER NOT NULL REFERENCES departments(id),
        weekly_hours_limit INTEGER DEFAULT 40
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS shifts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        shift_name TEXT UNIQUE NOT NULL,
        start_time TEXT NOT NULL,
        end_time TEXT NOT NULL
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS staff_availability (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        staff_id INTEGER NOT NULL REFERENCES staff(id),
        shift_date TEXT NOT NULL,
        shift_id INTEGER NOT NULL REFERENCES shifts(id),
        is_available INTEGER NOT NULL DEFAULT 1,
        UNIQUE(staff_id, shift_date, shift_id)
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS schedules (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        schedule_date TEXT NOT NULL,
        shift_id INTEGER NOT NULL REFERENCES shifts(id),
        staff_id INTEGER NOT NULL REFERENCES staff(id),
        department_id INTEGER NOT NULL REFERENCES departments(id),
        status TEXT NOT NULL DEFAULT 'Recommended',
        approved_by INTEGER REFERENCES users(id),
        approved_at TEXT,
        UNIQUE(schedule_date, shift_id, staff_id)
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS operating_rooms (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        room_no TEXT UNIQUE NOT NULL,
        department_id INTEGER NOT NULL REFERENCES departments(id),
        status TEXT NOT NULL DEFAULT 'Available',
        last_cleaned_at TEXT
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS or_schedules (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        or_id INTEGER NOT NULL REFERENCES operating_rooms(id),
        patient_id INTEGER REFERENCES patients(id),
        procedure_name TEXT NOT NULL,
        procedure_type TEXT,
        planned_start TEXT NOT NULL,
        planned_end TEXT NOT NULL,
        estimated_duration_min INTEGER,
        assigned_doctor_id INTEGER REFERENCES doctors(id),
        status TEXT NOT NULL DEFAULT 'Draft',
        requires_approval INTEGER NOT NULL DEFAULT 1,
        approved_by INTEGER REFERENCES users(id),
        approved_at TEXT
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS inventory_items (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        sku TEXT UNIQUE NOT NULL,
        name TEXT NOT NULL,
        category TEXT NOT NULL,
        unit TEXT DEFAULT 'unit',
        quantity INTEGER NOT NULL DEFAULT 0,
        reorder_threshold INTEGER DEFAULT 10,
        expiry_date TEXT,
        maintenance_date TEXT,
        supplier TEXT,
        min_order_qty INTEGER DEFAULT 10,
        location TEXT,
        created_at TEXT NOT NULL DEFAULT (datetime('now'))
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS stock_movements (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        item_id INTEGER NOT NULL REFERENCES inventory_items(id),
        quantity_delta INTEGER NOT NULL,
        movement_type TEXT NOT NULL,
        reason TEXT,
        user_id INTEGER REFERENCES users(id),
        reference_no TEXT,
        created_at TEXT NOT NULL DEFAULT (datetime('now'))
    );
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_stockmove_item ON stock_movements(item_id, created_at);
    """,
    """
    CREATE TABLE IF NOT EXISTS lab_requests (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        patient_id INTEGER NOT NULL REFERENCES patients(id),
        test_type TEXT NOT NULL,
        test_category TEXT,
        requested_by INTEGER NOT NULL REFERENCES users(id),
        ordered_at TEXT NOT NULL,
        picked_up_at TEXT,
        resulted_at TEXT,
        status TEXT NOT NULL DEFAULT 'Requested',
        turnaround_minutes INTEGER,
        result_note TEXT,
        priority TEXT DEFAULT 'Routine'
    );
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_lab_status ON lab_requests(status);
    """,
    """
    CREATE TABLE IF NOT EXISTS handover_notes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        from_staff_id INTEGER NOT NULL REFERENCES users(id),
        to_staff_id INTEGER REFERENCES users(id),
        shift_id INTEGER REFERENCES shifts(id),
        department_id INTEGER REFERENCES departments(id),
        note_text TEXT NOT NULL,
        is_read INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL DEFAULT (datetime('now'))
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS tasks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL,
        description TEXT,
        assignee_id INTEGER NOT NULL REFERENCES users(id),
        creator_id INTEGER NOT NULL REFERENCES users(id),
        priority TEXT NOT NULL DEFAULT 'Medium',
        status TEXT NOT NULL DEFAULT 'Pending',
        due_at TEXT,
        department_id INTEGER REFERENCES departments(id),
        created_at TEXT NOT NULL DEFAULT (datetime('now')),
        completed_at TEXT
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS feedback (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        patient_id INTEGER REFERENCES patients(id),
        is_anonymous INTEGER NOT NULL DEFAULT 0,
        category TEXT NOT NULL,
        department_id INTEGER REFERENCES departments(id),
        subject TEXT NOT NULL,
        description TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'Open',
        assignee_id INTEGER REFERENCES users(id),
        resolution_notes TEXT,
        submitted_at TEXT NOT NULL DEFAULT (datetime('now')),
        resolved_at TEXT
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS ic_checklist_templates (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        department_id INTEGER REFERENCES departments(id),
        items_json TEXT NOT NULL
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS ic_checklist_records (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        template_id INTEGER NOT NULL REFERENCES ic_checklist_templates(id),
        ward TEXT,
        department_id INTEGER REFERENCES departments(id),
        completed_by INTEGER NOT NULL REFERENCES users(id),
        completed_at TEXT NOT NULL DEFAULT (datetime('now')),
        results_json TEXT NOT NULL,
        notes TEXT
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS notifications (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL REFERENCES users(id),
        type TEXT NOT NULL,
        title TEXT NOT NULL,
        message TEXT NOT NULL,
        is_read INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL DEFAULT (datetime('now')),
        data_json TEXT
    );
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_notifs_user ON notifications(user_id, is_read, created_at);
    """,
    """
    CREATE TABLE IF NOT EXISTS audit_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        actor_id INTEGER REFERENCES users(id),
        actor_role TEXT,
        action TEXT NOT NULL,
        entity_type TEXT NOT NULL,
        entity_id TEXT,
        detail_json TEXT,
        ip_address TEXT,
        user_agent TEXT,
        created_at TEXT NOT NULL DEFAULT (datetime('now'))
    );
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_audit_actor ON audit_logs(actor_id, created_at);
    CREATE INDEX IF NOT EXISTS idx_audit_entity ON audit_logs(entity_type, entity_id);
    """,
    """
    CREATE TABLE IF NOT EXISTS forecast_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        forecast_date TEXT NOT NULL,
        horizon_days INTEGER NOT NULL,
        model_name TEXT NOT NULL,
        metrics_json TEXT,
        predictions_json TEXT,
        department_id INTEGER REFERENCES departments(id),
        created_at TEXT NOT NULL DEFAULT (datetime('now'))
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS bottleneck_records (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        workflow_step TEXT NOT NULL,
        department_id INTEGER REFERENCES departments(id),
        observed_at TEXT NOT NULL DEFAULT (datetime('now')),
        median_dwell_minutes REAL,
        alert_level TEXT,
        sample_count INTEGER
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS appointment_daily_demand (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        demand_date TEXT NOT NULL,
        department_id INTEGER REFERENCES departments(id),
        n_admissions INTEGER DEFAULT 0,
        n_appointments INTEGER DEFAULT 0,
        n_emergency INTEGER DEFAULT 0,
        total_demand INTEGER DEFAULT 0,
        UNIQUE(demand_date, department_id)
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS ambulances (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        vehicle_number TEXT UNIQUE NOT NULL,
        driver_name TEXT NOT NULL,
        driver_phone TEXT,
        status TEXT NOT NULL DEFAULT 'Available',
        current_location TEXT,
        lat REAL,
        lng REAL
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS ambulance_dispatches (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ambulance_id INTEGER NOT NULL REFERENCES ambulances(id),
        patient_id INTEGER REFERENCES patients(id),
        emergency_case_id INTEGER REFERENCES admissions(id),
        pickup_address TEXT NOT NULL,
        destination_dept_id INTEGER REFERENCES departments(id),
        status TEXT NOT NULL DEFAULT 'Dispatched',
        eta_minutes INTEGER,
        distance_km REAL,
        route_summary TEXT,
        dispatched_at TEXT NOT NULL DEFAULT (datetime('now')),
        completed_at TEXT
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS blood_donors (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        donor_code TEXT UNIQUE NOT NULL,
        full_name TEXT NOT NULL,
        blood_type TEXT NOT NULL,
        phone TEXT,
        email TEXT,
        last_donated_date TEXT,
        eligibility_status TEXT DEFAULT 'Eligible',
        total_donations INTEGER DEFAULT 0,
        created_at TEXT NOT NULL DEFAULT (datetime('now'))
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS blood_inventory (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        blood_type TEXT UNIQUE NOT NULL,
        units_available INTEGER NOT NULL DEFAULT 0,
        min_threshold_units INTEGER DEFAULT 10,
        updated_at TEXT NOT NULL DEFAULT (datetime('now'))
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS blood_requests (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        patient_id INTEGER REFERENCES patients(id),
        requested_by INTEGER REFERENCES users(id),
        department_id INTEGER REFERENCES departments(id),
        blood_type TEXT NOT NULL,
        units_requested INTEGER NOT NULL DEFAULT 1,
        urgency TEXT DEFAULT 'Routine',
        status TEXT DEFAULT 'Requested',
        created_at TEXT NOT NULL DEFAULT (datetime('now')),
        fulfilled_at TEXT
    );
    """,
]


def init_db(conn: sqlite3.Connection) -> None:
    """Idempotently initialise schema. Safe to call on every app start."""
    with conn:
        cur = conn.cursor()
        # Check if admissions table has old UNIQUE(bed_id) constraint
        row = cur.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='admissions'").fetchone()
        if row and "UNIQUE(BED_ID)" in (row["sql"] or "").upper().replace(" ", ""):
            cur.execute("PRAGMA foreign_keys=OFF;")
            cur.execute("ALTER TABLE admissions RENAME TO _admissions_old;")
            cur.execute("""
                CREATE TABLE admissions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    patient_id INTEGER NOT NULL REFERENCES patients(id),
                    bed_id INTEGER REFERENCES beds(id),
                    doctor_id INTEGER REFERENCES doctors(id),
                    admitted_at TEXT NOT NULL,
                    discharged_at TEXT,
                    status TEXT NOT NULL DEFAULT 'Admitted',
                    diagnosis TEXT,
                    admission_type TEXT DEFAULT 'Elective',
                    triage_level INTEGER
                );
            """)
            cur.execute("INSERT INTO admissions SELECT * FROM _admissions_old;")
            cur.execute("DROP TABLE _admissions_old;")
            cur.execute("PRAGMA foreign_keys=ON;")

        for stmt in SCHEMA_STATEMENTS:
            s = stmt.strip()
            if not s:
                continue
            cur.executescript(s)

