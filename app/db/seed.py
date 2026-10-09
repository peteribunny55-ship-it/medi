from __future__ import annotations

import json
import os
import random
import sqlite3
import sys
from datetime import date, datetime, timedelta
from typing import Any

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from app.config import (
    SEED,
    ROLES,
    DEPARTMENTS,
    BED_TYPES,
    BED_STATUSES,
    SHIFT_TYPES,
    APPOINTMENT_STATUSES,
    QUEUE_STATUSES,
    ADMISSION_STATUSES,
    TASK_PRIORITIES,
    TASK_STATUSES,
    INVENTORY_CATEGORIES,
    LAB_STATUSES,
    DEMO_USERS,
    NEAR_EXPIRY_DAYS,
)
from app.core.auth import ensure_roles, ensure_demo_users, create_user

FIRST_NAMES = [
    "James", "Mary", "John", "Patricia", "Robert", "Jennifer", "Michael", "Linda",
    "William", "Elizabeth", "David", "Barbara", "Richard", "Susan", "Joseph", "Jessica",
    "Thomas", "Sarah", "Charles", "Karen", "Christopher", "Lisa", "Daniel", "Nancy",
    "Matthew", "Betty", "Anthony", "Helen", "Mark", "Sandra", "Donald", "Donna",
    "Steven", "Carol", "Paul", "Ruth", "Andrew", "Sharon", "Joshua", "Michelle",
    "Kenneth", "Laura", "Kevin", "Sarah", "Brian", "Kimberly", "George", "Deborah",
    "Edward", "Dorothy", "Ronald", "Maureen", "Timothy", "Sylvia", "Jason", "Virginia",
    "Jeffrey", "Katherine", "Ryan", "Christine", "Jacob", "Janet", "Gary", "Catherine",
    "Nicholas", "Frances", "Eric", "Ann", "Jonathan", "Joyce", "Stephen", "Diane",
    "Larry", "Julie", "Justin", "Kelly", "Scott", "Victoria", "Brandon", "Cynthia",
    "Benjamin", "Amy", "Samuel", "Kathleen", "Gregory", "Angela", "Alexander", "Shirley",
    "Patrick", "Anna", "Frank", "Brenda", "Raymond", "Emma", "Jack", "Samantha",
    "Dennis", "Rebecca", "Jerry", "Josephine", "Tyler", "Judy", "Aaron", "Megan",
    "Jose", "Cheryl", "Henry", "Andrea", "Adam", "Marie", "Douglas", "Janice",
    "Nathan", "Ann", "Peter", "Alice", "Zachary", "Judith", "Walter", "Hannah",
    "Kyle", "Martha", "Harold", "Gloria", "Carl", "Teresa", "Arthur", "Ann Marie",
    "Gerald", "Sara", "Roger", "Madison", "Keith", "Doris", "Jeremy", "Rita",
    "Terry", "Eleanor", "Lawrence", "Mildred", "Sean", "Tracy", "Austin", "Glenda",
    "Christian", "Lois", "Jesse", "Juanita", "Joe", "Peggy", "Ethan", "Crystal",
    "Noah", "Katie", "Billy", "Myrtle", "Bruce", "Lorraine", "Bryan", "Lydia",
    "Ralph", "Lula", "Roy", "Etta", "Eugene", "Ethel", "Wayne", "Mabel",
    "Louis", "Bertha", "Jordan", "Cora", "Russell", "Ida", "Phillip", "Vera",
    "Gabriel", "Fannie", "Alan", "Louise", "Johnny", "Ava", "Bradley", "Willie",
]

LAST_NAMES = [
    "Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller", "Davis",
    "Rodriguez", "Martinez", "Hernandez", "Lopez", "Gonzalez", "Wilson", "Anderson",
    "Thomas", "Taylor", "Moore", "Jackson", "Martin", "Lee", "Perez", "Thompson",
    "White", "Harris", "Sanchez", "Clark", "Ramirez", "Lewis", "Robinson", "Walker",
    "Young", "Allen", "King", "Wright", "Scott", "Torres", "Nguyen", "Hill",
    "Flores", "Green", "Adams", "Nelson", "Baker", "Hall", "Rivera", "Campbell",
    "Mitchell", "Carter", "Roberts", "Gomez", "Phillips", "Evans", "Turner", "Diaz",
    "Parker", "Cruz", "Edwards", "Collins", "Reyes", "Stewart", "Morris", "Morales",
    "Murphy", "Cook", "Rogers", "Gutierrez", "Ortiz", "Morgan", "Cooper", "Peterson",
    "Bailey", "Reed", "Kelly", "Howard", "Ramos", "Kim", "Cox", "Ward",
    "Richardson", "Watson", "Brooks", "Chavez", "Wood", "James", "Bennett", "Gray",
    "Mendoza", "Ruiz", "Hughes", "Price", "Alvarez", "Castillo", "Sanders", "Patel",
    "Myers", "Long", "Ross", "Foster", "Jimenez",
]

DEPT_PREFIXES = {
    "Cardiology": "CARD", "Neurology": "NEUR", "Orthopedics": "ORTH", "Pediatrics": "PED",
    "General Medicine": "GME", "Emergency": "EMER", "ICU": "ICU", "Radiology": "RAD",
    "Laboratory": "LAB", "Pharmacy": "PHARM",
}

BED_TYPE_SHORT = {
    "General": "G", "ICU": "U", "HDU": "H", "Emergency": "E", "Pediatric": "P", "Isolation": "S",
}

APPT_REASONS = {
    "Cardiology": ["Chest pain evaluation", "Hypertension follow-up", "Arrhythmia review", "Post-MI checkup", "Echocardiogram review"],
    "Neurology": ["Headache consultation", "Migraine review", "Epilepsy follow-up", "Memory evaluation", "Nerve pain assessment"],
    "Orthopedics": ["Joint pain review", "Post-fracture follow-up", "Arthritis consultation", "Back pain assessment", "Pre-surgery consult"],
    "Pediatrics": ["Well-child checkup", "Vaccination visit", "Fever evaluation", "Growth assessment", "Allergies review"],
    "General Medicine": ["Routine checkup", "Cold and flu", "Diabetes follow-up", "Blood pressure review", "Referral consultation"],
    "Emergency": ["Trauma evaluation", "Acute pain", "Breathing difficulty", "Infection review", "Minor laceration"],
    "ICU": ["Post-operative review", "Critical care follow-up", "Ventilation weaning", "Sepsis recovery", "Hemodynamic monitoring"],
    "Radiology": ["X-ray review", "CT scan consultation", "MRI follow-up", "Ultrasound review", "Imaging interpretation"],
    "Laboratory": ["Blood test follow-up", "Lab results review", "Pathology consultation", "Genetic screening", "Biochemistry review"],
    "Pharmacy": ["Medication review", "Prescription refill", "Drug interaction check", "Dosage adjustment", "Therapy compliance"],
}

DOCTOR_SPECIALIZATIONS = {
    1: ["Cardiologist", "Interventional Cardiologist", "Electrophysiologist"],
    2: ["Neurologist", "Neurosurgeon", "Pediatric Neurologist"],
    3: ["Orthopedic Surgeon", "Sports Medicine", "Joint Replacement"],
    4: ["Pediatrician", "Neonatologist", "Pediatric Emergency"],
    5: ["General Practitioner", "Internal Medicine", "Family Physician"],
    6: ["Emergency Physician", "Trauma Surgeon", "Critical Care"],
    7: ["Intensivist", "Critical Care Specialist", "Anesthesiologist"],
    8: ["Radiologist", "Interventional Radiologist", "Nuclear Medicine"],
    9: ["Pathologist", "Clinical Microbiologist", "Chemical Pathologist"],
    10: ["Clinical Pharmacist", "Pharmacy Director", "Oncology Pharmacist"],
}

INVENTORY_DATA = {
    "Medicine": [
        ("Amoxicillin 500mg", "tablet"), ("Paracetamol 500mg", "tablet"), ("Ibuprofen 400mg", "tablet"),
        ("Omeprazole 20mg", "capsule"), ("Metformin 500mg", "tablet"), ("Atorvastatin 10mg", "tablet"),
        ("Amlodipine 5mg", "tablet"), ("Losartan 50mg", "tablet"), ("Salbutamol Inhaler", "unit"),
        ("Ceftriaxone 1g", "vial"), ("Insulin Glargine", "vial"), ("Morphine 10mg/ml", "vial"),
        ("Ondansetron 4mg", "tablet"), ("Furosemide 40mg", "tablet"), ("Heparin 5000IU", "vial"),
    ],
    "Equipment": [
        ("Surgical Scalpel #10", "unit"), ("Sterile Syringe 5ml", "unit"), ("Blood Pressure Cuff", "unit"),
        ("Stethoscope Basic", "unit"), ("Infusion Pump", "unit"), ("ECG Electrodes Pack", "pack"),
        ("OT Light Bulb", "unit"), ("Defibrillator Pads", "pair"), ("Endotracheal Tube 7mm", "unit"),
        ("Laryngoscope Blade", "unit"),
    ],
    "Supplies": [
        ("Sterile Gauze Roll", "roll"), ("Medical Gloves M", "box"), ("N95 Face Mask", "box"),
        ("Alcohol Swab Pads", "box"), ("IV Cannula 20G", "unit"), ("IV Fluid 500ml NS", "bag"),
        ("Bandage Wrap 4in", "roll"), ("Disinfectant Wipes", "pack"), ("Sharps Container 5L", "unit"),
        ("Bed Sheet Sterile", "unit"), ("Hand Sanitizer 500ml", "bottle"), ("Suture Kit", "kit"),
        ("Urine Collection Bag", "unit"), ("Wound Dressing 10x10", "pad"), ("Tape Surgical 1in", "roll"),
    ],
}

DIAGNOSES = [
    "Acute upper respiratory tract infection", "Essential hypertension", "Type 2 diabetes mellitus",
    "Osteoarthritis of knee", "Lumbar back pain", "Generalized anxiety disorder",
    "Migraine without aura", "Gastro-esophageal reflux disease", "Iron deficiency anemia",
    "Hyperlipidemia", "Asthma, uncomplicated", "Hypothyroidism",
    "Acute sinusitis", "Urinary tract infection", "Cellulitis of lower limb",
    "Pneumonia, unspecified organism", "Congestive heart failure", "Chronic obstructive pulmonary disease",
]

ADMISSION_TYPES = ["Elective", "Emergency", "Transfer", "Direct"]

PROCEDURES = [
    "Coronary Angioplasty", "Hip Replacement", "Knee Arthroscopy", "Laparoscopic Cholecystectomy",
    "CT-guided Biopsy", "MRI Lumbar Spine", "TKR Right Knee", "Open Reduction Internal Fixation",
    "CABG x3", "Pacemaker Implantation", "Lumbar Laminectomy", "Carpal Tunnel Release",
    "Inguinal Hernia Repair", "Appendectomy", "Mastectomy Partial",
]

LAB_TESTS = [
    ("Complete Blood Count", "Hematology"),
    ("Basic Metabolic Panel", "Chemistry"),
    ("Comprehensive Metabolic Panel", "Chemistry"),
    ("Lipid Profile", "Chemistry"),
    ("Liver Function Test", "Chemistry"),
    ("Troponin I", "Cardiology"),
    ("D-Dimer", "Coagulation"),
    ("CRP", "Chemistry"),
    ("Urinalysis", "Urinalysis"),
    ("Prothrombin Time / INR", "Coagulation"),
    ("HbA1c", "Chemistry"),
    ("Thyroid Profile", "Endocrine"),
    ("Blood Culture", "Microbiology"),
    ("Urine Culture", "Microbiology"),
    ("Chest X-Ray", "Radiology"),
    ("ECG 12-Lead", "Cardiology"),
    ("ABG Analysis", "Blood Gas"),
]

IC_TEMPLATES = {
    "Hand Hygiene": [
        {"id": "HH-1", "text": "Washed hands with soap before patient contact"},
        {"id": "HH-2", "text": "Used alcohol rub after glove removal"},
        {"id": "HH-3", "text": "Washed hands after body fluid exposure risk"},
        {"id": "HH-4", "text": "Washed hands after touching patient surroundings"},
        {"id": "HH-5", "text": "Hands were visibly clean before leaving"},
    ],
    "PPE": [
        {"id": "PPE-1", "text": "Gown correctly tied and covering torso"},
        {"id": "PPE-2", "text": "Medical mask properly fitted, no gaps"},
        {"id": "PPE-3", "text": "Eye protection worn if splash risk"},
        {"id": "PPE-4", "text": "Gloves intact and changed between tasks"},
        {"id": "PPE-5", "text": "PPE removed in correct order without contamination"},
        {"id": "PPE-6", "text": "Hand hygiene performed after PPE removal"},
    ],
    "Isolation": [
        {"id": "ISO-1", "text": "Correct isolation signage posted outside room"},
        {"id": "ISO-2", "text": "Isolation PPE cart stocked outside door"},
        {"id": "ISO-3", "text": "Patient aware of isolation precautions"},
        {"id": "ISO-4", "text": "Equipment dedicated to room only (or decontaminated)"},
        {"id": "ISO-5", "text": "Waste bagged per protocol before removal"},
        {"id": "ISO-6", "text": "Room terminal cleaning checklist on hand"},
        {"id": "ISO-7", "text": "Hand hygiene station visible and full"},
        {"id": "ISO-8", "text": "Patient monitoring schedule posted and up-to-date"},
    ],
}

TASK_TITLES = [
    "Review lab results for bed #12", "Discharge summary for patient #88", "Medication reconciliation for new admission",
    "Verify consent form for OR tomorrow", "Schedule follow-up appointment", "Restock crash cart in ER",
    "Call radiology for STAT CT", "Update care plan for ward C", "Family meeting with patient #31",
    "Order blood products for surgery", "Check on patient in room 204", "Enter notes for morning rounds",
    "Arrange physiotherapy referral", "Contact pharmacy re: drug interaction", "Review ECG in #ICU-7",
    "Audit infection control logs", "Orient new nurse to ward", "Fill supply cart for afternoon shift",
    "Confirm fasting for morning procedures", "Complete incident report for fall",
]

FEEDBACK_CATEGORIES = [
    "Waiting Time", "Doctor Attitude", "Nurse Care", "Cleanliness", "Food Quality",
    "Billing & Payments", "Communication", "Facilities", "Pain Management", "Discharge Process",
]

FEEDBACK_SUBJECTS = {
    "Waiting Time": ["Long delay in OPD", "Emergency wait was too long", "Lab results took 3 days"],
    "Doctor Attitude": ["Doctor was impatient", "Excellent bedside manner", "Rushed consultation"],
    "Nurse Care": ["Night shift nurses very attentive", "Response to call bell slow", "IV line changed promptly"],
    "Cleanliness": ["Restroom was unclean", "Ward spotless", "Trash not emptied on time"],
    "Food Quality": ["Food cold when delivered", "Special diet not followed", "Good vegetarian options"],
    "Billing & Payments": ["Unclear charges on final bill", "Insurance process smooth", "Co-pay surprise"],
    "Communication": ["No update on scan results", "Doctor explained everything well", "Discharge instructions unclear"],
    "Facilities": ["Old bed very uncomfortable", "Lift broken for 2 days", "Good wheelchair availability"],
    "Pain Management": ["Post-op pain meds delayed", "Good pain protocol", "Not enough PRN offered"],
    "Discharge Process": ["Took 5 hours to discharge", "Discharge papers ready on time", "No follow-up info given"],
}

FEEDBACK_DESCRIPTIONS = {
    "Waiting Time": "Waited for over two hours beyond appointment time before being seen. Better schedule management required.",
    "Doctor Attitude": "The attending clinician was thorough, listened carefully, and explained the plan in plain language.",
    "Nurse Care": "Nursing staff responded quickly and ensured patient comfort throughout the shift.",
    "Cleanliness": "The room had not been mopped for two days; overflowing bin in the bathroom.",
    "Food Quality": "Breakfast tray arrived cold and dietary restrictions were ignored.",
    "Billing & Payments": "There is an unexplained charge on the final bill. Need itemized breakdown and clarification.",
    "Communication": "Nobody communicated the scan result or next steps clearly; family had to follow up repeatedly.",
    "Facilities": "Main elevator in the building was non-functional making floor transfers difficult.",
    "Pain Management": "Post-operative analgesia was given on schedule and the patient was comfortable.",
    "Discharge Process": "Discharge counselling and medications were ready quickly; very smooth process.",
}


def _rnd_phone() -> str:
    return f"+1-{random.randint(201, 999)}-{random.randint(200, 999)}-{random.randint(1000, 9999)}"


def _rnd_email(first: str, last: str) -> str:
    dom = random.choice(["mail.com", "example.org", "hospital.patient.net", "outlook.com", "gmail.com"])
    sep = random.choice([".", "_", ""])
    num = random.choice(["", str(random.randint(1, 99))])
    return f"{first.lower()}{sep}{last.lower()}{num}@{dom}"


def _fmt_date(d: date) -> str:
    return d.strftime("%Y-%m-%d")


def _fmt_datetime(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def _slots_15m() -> list[str]:
    slots = []
    for hour in range(8, 18):
        for m in (0, 15, 30, 45):
            slots.append(f"{hour:02d}:{m:02d}")
    return slots


def _wipes_table(conn: sqlite3.Connection) -> None:
    tables = [
        "audit_logs", "notifications", "ic_checklist_records", "ic_checklist_templates",
        "feedback", "tasks", "handover_notes", "lab_requests", "stock_movements", "inventory_items",
        "or_schedules", "operating_rooms", "schedules", "staff_availability", "shifts", "transfers",
        "admissions", "beds", "queue_tokens", "appointments", "appointment_daily_demand",
        "bottleneck_records", "forecast_history", "doctors", "staff", "patients", "users",
        "departments", "roles",
    ]
    cur = conn.cursor()
    cur.execute("PRAGMA foreign_keys = OFF")
    for t in tables:
        cur.execute(f"DELETE FROM {t}")
    for t in ("users", "departments", "roles", "inventory_items", "admissions", "staff"):
        try:
            cur.execute(f"DELETE FROM sqlite_sequence WHERE name='{t}'")
        except sqlite3.OperationalError:
            pass
    cur.execute("PRAGMA foreign_keys = ON")


def seed_all(conn: sqlite3.Connection, force: bool = False) -> dict[str, int]:
    """Deterministic seeded seeder: populates all clinical tables synthetically.

    Idempotent when ``force`` is False (returns early if departments exist).
    When ``force`` is True, wipes the existing data before re-seeding.

    Returns a summary dict with table_name -> rows_inserted counts.
    """
    random.seed(SEED)
    summary: dict[str, int] = {}
    cur = conn.cursor()

    pre_count = cur.execute("SELECT COUNT(*) FROM departments").fetchone()[0]
    if pre_count > 0 and not force:
        return {"_skipped": pre_count}
    if force:
        _wipes_table(conn)

    today = date.today()
    date_90_back = today - timedelta(days=90)
    date_30_fwd = today + timedelta(days=30)
    slots = _slots_15m()

    with conn:
        ensure_roles(conn, ROLES)
        summary["roles"] = len(ROLES)

        dept_rows = []
        for idx, (name, desc, floor) in enumerate(DEPARTMENTS, start=1):
            cur.execute(
                "INSERT INTO departments(id,name,description,floor) VALUES(?,?,?,?)",
                (idx, name, desc, floor),
            )
            dept_rows.append((idx, name))
        summary["departments"] = len(dept_rows)

        ensure_demo_users(conn, DEMO_USERS)

        user_ids: dict[str, int] = {}
        for u in DEMO_USERS:
            row = cur.execute("SELECT id FROM users WHERE username=?", (u["username"],)).fetchone()
            if row:
                user_ids[u["username"]] = int(row["id"])
        summary["demo_users"] = len(DEMO_USERS)

        doctor_user_ids: list[int] = []
        for i in range(1, 9):
            uname = f"doctor_{i:02d}"
            existing = cur.execute("SELECT id FROM users WHERE username=?", (uname,)).fetchone()
            if existing:
                uid = int(existing["id"])
            else:
                dept_id = ((i - 1) % 5) + 1
                specs = DOCTOR_SPECIALIZATIONS.get(dept_id, ["General Physician"])
                full = f"Dr. {random.choice(FIRST_NAMES)} {random.choice(LAST_NAMES)}"
                uid = create_user(
                    conn, uname, f"doctor{i:02d}pass", "Doctor", full,
                    email=f"{uname}@hospital.edu", department_id=dept_id, actor_id=None,
                )
            doctor_user_ids.append(uid)
            user_ids[uname] = uid
        doctor_user_ids.insert(0, user_ids["doctor"])
        summary["doctor_users"] = len(doctor_user_ids)

        nurse_user_ids: list[int] = []
        for i in range(1, 13):
            uname = f"nurse_{i:02d}"
            existing = cur.execute("SELECT id FROM users WHERE username=?", (uname,)).fetchone()
            if existing:
                uid = int(existing["id"])
            else:
                dept_id = ((i - 1) % 10) + 1
                full = f"Nurse {random.choice(FIRST_NAMES)} {random.choice(LAST_NAMES)}"
                uid = create_user(
                    conn, uname, f"nurse{i:02d}pass", "Nurse", full,
                    email=f"{uname}@hospital.edu", department_id=dept_id, actor_id=None,
                )
            nurse_user_ids.append(uid)
            user_ids[uname] = uid
        summary["nurse_users"] = len(nurse_user_ids)

        patient_pk_ids: list[int] = []
        phones_used: set[str] = set()
        emails_used: set[str] = set()
        patient_user_id = user_ids.get("patient")
        for p_idx in range(1, 501):
            pid_str = f"P-{p_idx:04d}"
            first = random.choice(FIRST_NAMES)
            last = random.choice(LAST_NAMES)
            yob = random.randint(1940, 2020)
            mob = random.randint(1, 12)
            try:
                dob_d = date(yob, mob, random.randint(1, 28))
            except ValueError:
                dob_d = date(yob, mob, 28)
            gender = random.choice(["Male", "Female", "Other"])
            phone = _rnd_phone()
            while phone in phones_used:
                phone = _rnd_phone()
            phones_used.add(phone)
            email = _rnd_email(first, last)
            while email in emails_used:
                email = _rnd_email(first, last)
            emails_used.add(email)
            addr = f"{random.randint(10,9999)} {random.choice(['Maple','Oak','Pine','Elm','Cedar','Main','Park'])}, {random.choice(['Springfield','Rivertown','Lakeview','Georgetown','Millwood'])}"
            ec = random.choice(FIRST_NAMES) + " " + random.choice(LAST_NAMES) + " " + _rnd_phone()
            u_id = patient_user_id if p_idx == 1 else None
            cur.execute(
                """INSERT INTO patients(patient_id,first_name,last_name,dob,gender,phone,email,address,emergency_contact,user_id)
                   VALUES(?,?,?,?,?,?,?,?,?,?)""",
                (pid_str, first, last, _fmt_date(dob_d), gender, phone, email, addr, ec, u_id),
            )
            patient_pk_ids.append(int(cur.lastrowid))
        summary["patients"] = len(patient_pk_ids)

        doctors_rows = []
        for d_ord, uid in enumerate(doctor_user_ids):
            dept_id = (d_ord % 10) + 1
            spec_list = DOCTOR_SPECIALIZATIONS.get(dept_id, ["General Physician"])
            spec = random.choice(spec_list)
            license_no = f"LIC-{random.randint(100000,999999):06d}-{chr(ord('A')+d_ord)}"
            while True:
                found = cur.execute("SELECT 1 FROM doctors WHERE license_no=?", (license_no,)).fetchone()
                if not found:
                    break
                license_no = f"LIC-{random.randint(100000,999999):06d}-{chr(ord('A')+d_ord)}"
            fee = round(random.uniform(50, 250), 2)
            avg_m = random.randint(15, 30)
            cur.execute(
                """INSERT INTO doctors(user_id,department_id,specialization,license_no,consultation_fee,avg_consult_minutes)
                   VALUES(?,?,?,?,?,?)""",
                (uid, dept_id, spec, license_no, fee, avg_m),
            )
            doctors_rows.append(int(cur.lastrowid))
        summary["doctors"] = len(doctors_rows)

        staff_rows = []
        all_staff_user_ids = list(nurse_user_ids)
        all_staff_user_ids.append(user_ids["nurse"])
        all_staff_user_ids.append(user_ids["inventory"])
        all_staff_user_ids.append(user_ids["admin"])

        for idx, uid in enumerate(all_staff_user_ids):
            if uid == user_ids["nurse"]:
                role, dept_id, wh = "Nurse", 5, random.randint(36, 44)
            elif uid == user_ids["inventory"]:
                role, dept_id, wh = "InventoryManager", 10, random.randint(36, 44)
            elif uid == user_ids["admin"]:
                role, dept_id, wh = "Admin", 5, random.randint(36, 44)
            else:
                role = "Nurse"
                dept_id = (idx % 10) + 1
                wh = random.randint(36, 44)
            cur.execute(
                "INSERT INTO staff(user_id,role,department_id,weekly_hours_limit) VALUES(?,?,?,?)",
                (uid, role, dept_id, wh),
            )
            staff_rows.append(int(cur.lastrowid))
        summary["staff"] = len(staff_rows)

        shift_ids: dict[str, int] = {}
        for sname, start_t, end_t in SHIFT_TYPES:
            cur.execute(
                "INSERT INTO shifts(shift_name,start_time,end_time) VALUES(?,?,?)",
                (sname, start_t, end_t),
            )
            shift_ids[sname] = int(cur.lastrowid)
        summary["shifts"] = len(shift_ids)

        bed_type_weights = [0.70, 0.10, 0.08, 0.08, 0.03, 0.01]
        beds_per_dept = [12, 10, 14, 10, 14, 12, 12, 10, 8, 18]
        all_beds: list[tuple[int, int, str]] = []
        bed_counter_per_dept: dict[tuple[int, str], int] = {}
        bed_ids: list[int] = []
        for d_i, (dept_id, dept_name) in enumerate(dept_rows):
            n = beds_per_dept[d_i]
            prefix = DEPT_PREFIXES[dept_name]
            dept_prefix_counter: dict[str, int] = {b: 0 for b in BED_TYPES}
            for _ in range(n):
                bt = random.choices(BED_TYPES, weights=bed_type_weights, k=1)[0]
                dept_prefix_counter[bt] += 1
                bt_short = BED_TYPE_SHORT[bt]
                bed_no = f"{prefix}-{bt_short}-{dept_prefix_counter[bt]:02d}"
                all_beds.append((dept_id, bed_no, bt))

        total_beds = len(all_beds)
        statuses: list[str] = []
        maint_count = 3
        occ_target = int((total_beds - maint_count) * 0.75)
        avail_target = total_beds - maint_count - occ_target
        statuses.extend(["Occupied"] * occ_target)
        statuses.extend(["Available"] * avail_target)
        statuses.extend(["Maintenance"] * maint_count)
        random.shuffle(statuses)

        shuffled_patients = list(patient_pk_ids)
        random.shuffle(shuffled_patients)
        occ_patients_iter = iter(shuffled_patients)
        bed_to_status: dict[int, str] = {}
        occupied_bed_ids: list[int] = []
        for i, (dept_id, bed_no, bt) in enumerate(all_beds):
            st = statuses[i]
            ward = f"{DEPARTMENTS[dept_id-1][0]}-Ward"
            cpid = None
            if st == "Occupied":
                cpid = next(occ_patients_iter, None)
            cur.execute(
                """INSERT INTO beds(bed_no,department_id,ward,bed_type,status,current_patient_id,last_maintenance_at)
                   VALUES(?,?,?,?,?,?,?)""",
                (
                    bed_no, dept_id, ward, bt, st, cpid,
                    _fmt_datetime(datetime.combine(today - timedelta(days=random.randint(0, 180)), datetime.min.time()) + timedelta(hours=8))
                    if st == "Maintenance" else None,
                ),
            )
            bid = int(cur.lastrowid)
            bed_ids.append(bid)
            bed_to_status[bid] = st
            if st == "Occupied":
                occupied_bed_ids.append(bid)
        summary["beds"] = total_beds

        doctor_id_list = list(doctors_rows)
        used_appt_keys: set[tuple[int, str, str]] = set()
        appt_date_range_past = [date_90_back + timedelta(days=i) for i in range((today - date_90_back).days)]
        appt_date_range_future = [today + timedelta(days=i) for i in range(1, (date_30_fwd - today).days + 1)]
        total_appts_target = 2000
        n_past = int(total_appts_target * (len(appt_date_range_past) / (len(appt_date_range_past) + len(appt_date_range_future))))
        n_future = total_appts_target - n_past
        appts_to_insert: list[tuple] = []

        def _pick_status(d: date) -> str:
            if d < today:
                r = random.random()
                if r < 0.60:
                    return "Completed"
                elif r < 0.70:
                    return "Missed"
                elif r < 0.75:
                    return "Cancelled"
                else:
                    return "Completed"
            else:
                r = random.random()
                if r < 0.25:
                    return "Scheduled"
                else:
                    return "Confirmed"

        def _try_add(d: date) -> bool:
            for _ in range(6):
                did = random.choice(doctor_id_list)
                dept_idx = (did - 1) % 10
                dept_id = dept_idx + 1
                time_s = random.choice(slots)
                key = (did, _fmt_date(d), time_s)
                if key in used_appt_keys:
                    continue
                used_appt_keys.add(key)
                pid = random.choice(patient_pk_ids)
                dept_name = DEPARTMENTS[dept_id - 1][0]
                reason = random.choice(APPT_REASONS[dept_name])
                status = _pick_status(d)
                cancelled_at = None
                if status == "Cancelled":
                    cancelled_at = _fmt_datetime(datetime.combine(d - timedelta(days=random.randint(0, 5)), datetime.min.time()) + timedelta(hours=random.randint(8, 20), minutes=random.randint(0, 59)))
                notes = "" if random.random() < 0.7 else f"Patient requested early slot. Reports {random.choice(['fatigue','mild nausea','headache','sleep difficulty'])} last 2 days."
                appts_to_insert.append((
                    pid, did, dept_id, _fmt_date(d), time_s, status, reason, notes, cancelled_at,
                ))
                return True
            return False

        total_planned = n_past + n_future
        i_att = 0
        while len(appts_to_insert) < total_planned and i_att < total_planned * 8:
            i_att += 1
            r = random.random()
            if r < (len(appt_date_range_past) / (len(appt_date_range_past) + len(appt_date_range_future))):
                d = random.choice(appt_date_range_past)
            else:
                d = random.choice(appt_date_range_future)
            _try_add(d)

        appt_ids: list[int] = []
        for t in appts_to_insert:
            cur.execute(
                """INSERT INTO appointments(patient_id,doctor_id,department_id,appointment_date,appointment_time,status,reason,notes,cancelled_at)
                   VALUES(?,?,?,?,?,?,?,?,?)""",
                t,
            )
            appt_ids.append(int(cur.lastrowid))
        summary["appointments"] = len(appt_ids)

        demand_rows: dict[tuple[str, int], dict[str, int]] = {}
        for a in appts_to_insert:
            d_date = a[3]
            d_dept = a[2]
            k = (d_date, d_dept)
            if k not in demand_rows:
                demand_rows[k] = {"n_appointments": 0, "n_admissions": 0, "n_emergency": 0, "total_demand": 0}
            demand_rows[k]["n_appointments"] += 1

        for dept_id in range(1, 11):
            d_cur = date_90_back
            while d_cur <= date_30_fwd:
                k = (_fmt_date(d_cur), dept_id)
                if k not in demand_rows:
                    demand_rows[k] = {"n_appointments": 0, "n_admissions": 0, "n_emergency": 0, "total_demand": 0}
                wd = d_cur.weekday()
                weekday_factor = [1.0, 1.1, 1.15, 1.1, 1.2, 0.6, 0.3][wd]
                month_factor = 0.9 + 0.2 * abs(6 - (d_cur.month - 1)) / 6
                base_appt = demand_rows[k]["n_appointments"]
                noise = random.gauss(0, 1.2)
                n_adm = max(0, int(round(
                    (1 + 0.15 * dept_id) * weekday_factor * month_factor * (1.2 + noise * 0.1)
                )))
                n_em = max(0, int(round((0.3 + 0.05 * dept_id) * weekday_factor * (0.8 + noise * 0.15))))
                demand_rows[k]["n_admissions"] = n_adm
                demand_rows[k]["n_emergency"] = n_em
                demand_rows[k]["total_demand"] = base_appt + n_adm + n_em
                d_cur += timedelta(days=1)

        for (dd, did), v in demand_rows.items():
            cur.execute(
                """INSERT INTO appointment_daily_demand(demand_date,department_id,n_admissions,n_appointments,n_emergency,total_demand)
                   VALUES(?,?,?,?,?,?)""",
                (dd, did, v["n_admissions"], v["n_appointments"], v["n_emergency"], v["total_demand"]),
            )
        summary["appointment_daily_demand"] = len(demand_rows)

        admission_ids: list[int] = []
        bed_to_adm: dict[int, int] = {}
        occupied_shuffled = list(occupied_bed_ids)
        random.shuffle(occupied_shuffled)
        active_count = min(120, len(occupied_shuffled))
        active_patients_pool = list(patient_pk_ids)
        random.shuffle(active_patients_pool)
        active_patients = set()
        for i in range(active_count):
            bid = occupied_shuffled[i]
            while True:
                pid = active_patients_pool.pop()
                if pid not in active_patients:
                    active_patients.add(pid)
                    break
            did = random.choice(doctor_id_list)
            admit_dt = datetime.combine(today - timedelta(days=random.randint(0, 29)), datetime.min.time()) + \
                       timedelta(hours=random.randint(6, 22), minutes=random.randint(0, 59))
            diag = random.choice(DIAGNOSES)
            at = random.choice(ADMISSION_TYPES)
            triage = random.choice([1, 2, 2, 3, 3, 3, 4, 4, 5])
            cur.execute(
                """INSERT INTO admissions(patient_id,bed_id,doctor_id,admitted_at,discharged_at,status,diagnosis,admission_type,triage_level)
                   VALUES(?,?,?,?,?,?,?,?,?)""",
                (pid, bid, did, _fmt_datetime(admit_dt), None, "Admitted", diag, at, triage),
            )
            aid = int(cur.lastrowid)
            admission_ids.append(aid)
            bed_to_adm[bid] = aid

        discharge_ids: list[int] = []
        for _ in range(300):
            pid = random.choice(patient_pk_ids)
            did = random.choice(doctor_id_list)
            days_back = random.randint(1, 89)
            stay_len = random.randint(1, 14)
            admit_d = today - timedelta(days=days_back + stay_len)
            discharge_d = today - timedelta(days=days_back)
            admit_dt = datetime.combine(admit_d, datetime.min.time()) + timedelta(hours=random.randint(6, 22), minutes=random.randint(0, 59))
            discharge_dt = datetime.combine(discharge_d, datetime.min.time()) + timedelta(hours=random.randint(8, 20), minutes=random.randint(0, 59))
            diag = random.choice(DIAGNOSES)
            at = random.choice(ADMISSION_TYPES)
            triage = random.choice([2, 2, 3, 3, 3, 4, 4, 5])
            cur.execute(
                """INSERT INTO admissions(patient_id,bed_id,doctor_id,admitted_at,discharged_at,status,diagnosis,admission_type,triage_level)
                   VALUES(?,?,?,?,?,?,?,?,?)""",
                (pid, None, did, _fmt_datetime(admit_dt), _fmt_datetime(discharge_dt), "Discharged", diag, at, triage),
            )
            discharge_ids.append(int(cur.lastrowid))
        admission_ids.extend(discharge_ids)
        summary["admissions"] = len(admission_ids)

        transfer_ids: list[int] = []
        for _ in range(25):
            from_dept = random.randint(1, 10)
            to_dept = random.randint(1, 10)
            while to_dept == from_dept:
                to_dept = random.randint(1, 10)
            from_bid = None
            to_bid = None
            aid = random.choice(discharge_ids if random.random() < 0.4 else admission_ids[:active_count])
            t_date = today - timedelta(days=random.randint(1, 60))
            t_dt = datetime.combine(t_date, datetime.min.time()) + timedelta(hours=random.randint(7, 21), minutes=random.randint(0, 59))
            reason = random.choice([
                "Level of care change", "Bed availability in specialty ward", "Isolation requirement",
                "Post-operative recovery", "Diagnostic imaging unit transfer",
            ])
            cur.execute(
                """INSERT INTO transfers(admission_id,from_bed_id,to_bed_id,from_dept,to_dept,transferred_at,reason)
                   VALUES(?,?,?,?,?,?,?)""",
                (aid, from_bid, to_bid, from_dept, to_dept, _fmt_datetime(t_dt), reason),
            )
            transfer_ids.append(int(cur.lastrowid))
        summary["transfers"] = len(transfer_ids)

        staff_ids = list(range(1, len(staff_rows) + 1))
        sa_count = 0
        for s_id in staff_ids:
            for d_offset in range(7):
                sd = today + timedelta(days=d_offset)
                for sh_id in shift_ids.values():
                    is_avail = 1 if random.random() < 0.70 else 0
                    try:
                        cur.execute(
                            """INSERT INTO staff_availability(staff_id,shift_date,shift_id,is_available)
                               VALUES(?,?,?,?)""",
                            (s_id, _fmt_date(sd), sh_id, is_avail),
                        )
                        sa_count += 1
                    except sqlite3.IntegrityError:
                        pass
        summary["staff_availability"] = sa_count

        schedule_count = 0
        for d_offset in range(3):
            sd = today + timedelta(days=d_offset)
            for sh_id in shift_ids.values():
                chosen = random.sample(staff_ids, k=min(6, len(staff_ids)))
                for s_id in chosen:
                    row = cur.execute("SELECT department_id FROM staff WHERE id=?", (s_id,)).fetchone()
                    dept = int(row["department_id"]) if row else 5
                    try:
                        cur.execute(
                            """INSERT INTO schedules(schedule_date,shift_id,staff_id,department_id,status,approved_by,approved_at)
                               VALUES(?,?,?,?,?,?,?)""",
                            (_fmt_date(sd), sh_id, s_id, dept, "Recommended", None, None),
                        )
                        schedule_count += 1
                    except sqlite3.IntegrityError:
                        pass
        summary["schedules"] = schedule_count

        or_depts = [1, 3, 5, 3, 1, 5, 7, 6]
        or_ids: list[int] = []
        for i in range(1, 9):
            room_no = f"OR-{i:02d}"
            cur.execute(
                "INSERT INTO operating_rooms(room_no,department_id,status,last_cleaned_at) VALUES(?,?,?,?)",
                (
                    room_no, or_depts[i - 1],
                    random.choice(["Available", "Available", "Available", "Maintenance"]),
                    _fmt_datetime(datetime.combine(today - timedelta(days=random.randint(0, 3)), datetime.min.time()) + timedelta(hours=random.randint(6, 20), minutes=random.randint(0, 59))),
                ),
            )
            or_ids.append(int(cur.lastrowid))
        summary["operating_rooms"] = len(or_ids)

        or_sched_ids: list[int] = []
        for _ in range(30):
            or_id = random.choice(or_ids)
            pid = random.choice(patient_pk_ids)
            proc = random.choice(PROCEDURES)
            pt = random.choice(["Elective", "Emergency", "Urgent"])
            plan_day = today + timedelta(days=random.randint(0, 1))
            start_h = random.randint(7, 16)
            dur = random.randint(45, 240)
            start_dt = datetime.combine(plan_day, datetime.min.time()) + timedelta(hours=start_h, minutes=random.choice([0, 15, 30, 45]))
            end_dt = start_dt + timedelta(minutes=dur)
            doc_id = random.choice(doctor_id_list)
            cur.execute(
                """INSERT INTO or_schedules(or_id,patient_id,procedure_name,procedure_type,planned_start,planned_end,estimated_duration_min,assigned_doctor_id,status,requires_approval,approved_by,approved_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                (or_id, pid, proc, pt, _fmt_datetime(start_dt), _fmt_datetime(end_dt), dur, doc_id,
                 "Draft", 1, None, None),
            )
            or_sched_ids.append(int(cur.lastrowid))
        summary["or_schedules"] = len(or_sched_ids)

        inventory_ids: list[int] = []
        item_idx = 1
        inv_items_list: list[tuple] = []
        for cat, items in INVENTORY_DATA.items():
            for (iname, iunit) in items:
                sku = f"{cat[:3].upper()}-{item_idx:04d}"
                qty = random.randint(2, 200)
                reorder = random.choice([10, 15, 20, 25, 30, 40])
                exp_date = None
                maint_date = None
                if cat == "Medicine":
                    if random.random() < 0.7:
                        exp_d = today + timedelta(days=random.randint(31, 540))
                        exp_date = _fmt_date(exp_d)
                elif cat == "Equipment":
                    maint_d = today + timedelta(days=random.randint(10, 180))
                    maint_date = _fmt_date(maint_d)
                    if random.random() < 0.2:
                        exp_d = today + timedelta(days=random.randint(365, 1095))
                        exp_date = _fmt_date(exp_d)
                else:
                    if random.random() < 0.2:
                        exp_d = today + timedelta(days=random.randint(90, 720))
                        exp_date = _fmt_date(exp_d)
                supplier = random.choice([
                    "PharmaSupplier Co.", "MedEquip Inc.", "Global Health Supplies",
                    "Clinical Solutions Ltd.", "BioMed Distributors",
                ])
                min_oq = random.choice([5, 10, 15, 20, 25, 50])
                loc = f"Shelf-{random.choice('ABCDEFGH')}{random.randint(1,12):02d}"
                inv_items_list.append((sku, iname, cat, iunit, qty, reorder, exp_date, maint_date, supplier, min_oq, loc))
                item_idx += 1

        while len(inv_items_list) < 50:
            cat = random.choice(INVENTORY_CATEGORIES)
            base = random.choice(list(INVENTORY_DATA[cat]))
            suffix = random.choice([" XL", " Mini", " Plus", " Advanced", " Pediatric", " Sterile"])
            inv_items_list.append((
                f"{cat[:3].upper()}-{item_idx:04d}",
                base[0] + suffix,
                cat,
                base[1],
                random.randint(2, 200),
                random.choice([10, 15, 20, 25, 30]),
                _fmt_date(today + timedelta(days=random.randint(31, 540))) if cat == "Medicine" and random.random() < 0.7 else None,
                _fmt_date(today + timedelta(days=random.randint(10, 180))) if cat == "Equipment" else None,
                random.choice(["PharmaSupplier Co.", "MedEquip Inc.", "Global Health Supplies"]),
                random.choice([5, 10, 15, 20, 25]),
                f"Shelf-{random.choice('ABCDEFGH')}{random.randint(1,12):02d}",
            ))
            item_idx += 1

        low_stock_target = 8
        for i in range(min(low_stock_target, len(inv_items_list))):
            sku, iname, cat, iunit, qty, reorder, exp_date, maint_date, supplier, min_oq, loc = inv_items_list[i]
            reorder = max(10, reorder)
            qty = random.randint(0, max(0, reorder - 1))
            inv_items_list[i] = (sku, iname, cat, iunit, qty, reorder, exp_date, maint_date, supplier, min_oq, loc)

        near_expiry_target = 5
        placed = 0
        for i in range(len(inv_items_list)):
            if placed >= near_expiry_target:
                break
            item = list(inv_items_list[i])
            if item[2] in ("Medicine", "Supplies") or (item[2] == "Equipment" and random.random() < 0.5):
                near_days = random.randint(1, NEAR_EXPIRY_DAYS)
                item[6] = _fmt_date(today + timedelta(days=near_days))
                inv_items_list[i] = tuple(item)
                placed += 1
        if placed < near_expiry_target:
            for i in range(placed, near_expiry_target):
                idx = len(inv_items_list) - 1 - i
                if idx >= 0:
                    item = list(inv_items_list[idx])
                    item[6] = _fmt_date(today + timedelta(days=random.randint(1, NEAR_EXPIRY_DAYS)))
                    inv_items_list[idx] = tuple(item)

        for t in inv_items_list:
            cur.execute(
                """INSERT INTO inventory_items(sku,name,category,unit,quantity,reorder_threshold,expiry_date,maintenance_date,supplier,min_order_qty,location)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                t,
            )
            inventory_ids.append(int(cur.lastrowid))
        summary["inventory_items"] = len(inventory_ids)

        sm_ids: list[int] = []
        admin_uid = user_ids.get("admin")
        inv_uid = user_ids.get("inventory")
        actor_pool = [inv_uid, inv_uid, inv_uid, admin_uid]
        for _ in range(200):
            i_id = random.choice(inventory_ids)
            mt = random.choice(["IN", "OUT"])
            qty = random.randint(1, 50)
            if mt == "OUT":
                qty = -qty
            reason = random.choice([
                "Purchase received", "Patient issue", "Ward transfer", "Stock adjustment",
                "Expired disposal", "Return to vendor", "Emergency use", "Consumption",
            ])
            uid = random.choice(actor_pool)
            ref = f"REF-{random.randint(100000,999999):06d}"
            sm_date = today - timedelta(days=random.randint(0, 60))
            sm_dt = datetime.combine(sm_date, datetime.min.time()) + timedelta(hours=random.randint(7, 21), minutes=random.randint(0, 59))
            cur.execute(
                """INSERT INTO stock_movements(item_id,quantity_delta,movement_type,reason,user_id,reference_no,created_at)
                   VALUES(?,?,?,?,?,?,?)""",
                (i_id, qty, mt, reason, uid, ref, _fmt_datetime(sm_dt)),
            )
            sm_ids.append(int(cur.lastrowid))
        summary["stock_movements"] = len(sm_ids)

        lab_ids: list[int] = []
        delay_target = 5
        delay_count = 0
        for i in range(80):
            pid = random.choice(patient_pk_ids)
            tt, tcat = random.choice(LAB_TESTS)
            ordered_by = random.choice(doctor_user_ids)
            days_back = random.randint(0, 29)
            od = today - timedelta(days=days_back)
            ordered_dt = datetime.combine(od, datetime.min.time()) + timedelta(hours=random.randint(7, 18), minutes=random.randint(0, 59))
            picked_up_dt = None
            resulted_dt = None
            priority = random.choices(["Routine", "Urgent", "STAT"], weights=[0.7, 0.22, 0.08], k=1)[0]
            base_turnaround = random.randint(60, 60 * 6)
            if priority == "STAT":
                base_turnaround = random.randint(30, 240)
            if priority == "Urgent":
                base_turnaround = random.randint(60, 360)
            make_delay = (delay_count < delay_target and i < 40)
            if make_delay:
                status = random.choice(["Requested", "InProgress"])
                turnaround = base_turnaround + 60 * 25 + random.randint(0, 60 * 12)
                delay_count += 1
            else:
                r = random.random()
                if r < 0.75:
                    status = "Completed"
                    picked_up_dt = ordered_dt + timedelta(minutes=random.randint(10, 180))
                    resulted_dt = ordered_dt + timedelta(minutes=base_turnaround)
                    turnaround = base_turnaround
                elif r < 0.82:
                    status = "Cancelled"
                    turnaround = random.randint(5, 120)
                elif r < 0.90:
                    status = "InProgress"
                    picked_up_dt = ordered_dt + timedelta(minutes=random.randint(10, 180))
                    turnaround = None
                else:
                    status = "Requested"
                    turnaround = None
            result_note = ""
            if status == "Completed":
                result_note = f"{tt}: within normal limits" if random.random() < 0.6 else f"{tt}: flag raised - review with clinician"
            cur.execute(
                """INSERT INTO lab_requests(patient_id,test_type,test_category,requested_by,ordered_at,picked_up_at,resulted_at,status,turnaround_minutes,result_note,priority)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    pid, tt, tcat, ordered_by,
                    _fmt_datetime(ordered_dt),
                    _fmt_datetime(picked_up_dt) if picked_up_dt else None,
                    _fmt_datetime(resulted_dt) if resulted_dt else None,
                    status,
                    turnaround,
                    result_note,
                    priority,
                ),
            )
            lab_ids.append(int(cur.lastrowid))
        summary["lab_requests"] = len(lab_ids)

        qt_ids: list[int] = []
        today_str = _fmt_date(today)
        todays_appts_per_dept: dict[int, list[int]] = {d: [] for d in range(1, 11)}
        for t, aid in zip(appts_to_insert, appt_ids):
            if t[3] == today_str:
                todays_appts_per_dept[t[2]].append(aid)
        for dept_id in range(1, 11):
            prefix = DEPT_PREFIXES[DEPARTMENTS[dept_id - 1][0]]
            n_q = random.randint(15, 25)
            waiting_ahead = 0
            for tn in range(1, n_q + 1):
                appt_id = None
                if todays_appts_per_dept[dept_id]:
                    if random.random() < 0.5:
                        appt_id = todays_appts_per_dept[dept_id].pop()
                        if not todays_appts_per_dept[dept_id]:
                            todays_appts_per_dept[dept_id] = []
                pid = random.choice(patient_pk_ids)
                r = random.random()
                if r < 0.55:
                    st = "Waiting"
                    estimated = waiting_ahead * 15
                    waiting_ahead += 1
                elif r < 0.72:
                    st = "Called"
                    estimated = max(0, (waiting_ahead - tn % 3) * 15)
                elif r < 0.90:
                    st = "InProgress"
                    estimated = random.randint(0, 15)
                else:
                    st = random.choice(["Completed", "Cancelled"])
                    estimated = 0
                called_at = None
                completed_at = None
                svc_start = None
                if st in ("Called", "InProgress", "Completed"):
                    called_at = _fmt_datetime(datetime.combine(today, datetime.min.time()) + timedelta(hours=random.randint(8, 17), minutes=random.randint(0, 59)))
                if st in ("InProgress", "Completed"):
                    svc_start = called_at
                if st == "Completed":
                    completed_at = _fmt_datetime(datetime.fromisoformat(called_at) + timedelta(minutes=random.randint(10, 40)))
                cur.execute(
                    """INSERT INTO queue_tokens(token_no,prefix,appointment_id,patient_id,department_id,status,called_at,completed_at,estimated_wait_minutes,service_started_at)
                       VALUES(?,?,?,?,?,?,?,?,?,?)""",
                    (tn, prefix, appt_id, pid, dept_id, st, called_at, completed_at, estimated, svc_start),
                )
                qt_ids.append(int(cur.lastrowid))
        summary["queue_tokens"] = len(qt_ids)

        hn_ids: list[int] = []
        for _ in range(10):
            from_uid = random.choice(nurse_user_ids + [user_ids["nurse"], user_ids["inventory"]])
            to_uid = random.choice(nurse_user_ids + [user_ids["nurse"]])
            sh_id = random.choice(list(shift_ids.values()))
            dept_id = random.randint(1, 10)
            txt = random.choice([
                "Patient in Rm 205 c/o dizziness overnight; vitals stable but orthostatic BP noted.",
                "New admission in bed #14 from ER: antibiotics started, ID consult pending.",
                "Bed #7 drain output was 600ml last shift; monitor closely and report if >100ml/hr.",
                "Family requested a care conference before discharge; please arrange with doc.",
                "Medication cart locked and counts verified. Insulin pen stored per protocol.",
                "Ward supply trolley restocked; ran out of 20G IV cannulas — reordered.",
                "Patient #38 pulled out central line; pressure dressing applied, MD notified.",
                "Bed #9 nil-by-mouth for 08:00 procedure; consent on file.",
                "Received transfer report from ICU for bed #4; on room air, ambulates with assistance.",
                "Isolation precaution signage posted outside Rm 310 (contact precautions).",
            ])
            is_read = 1 if random.random() < 0.6 else 0
            hn_date = today - timedelta(days=random.randint(0, 3))
            hn_dt = datetime.combine(hn_date, datetime.min.time()) + timedelta(hours=random.randint(6, 23), minutes=random.randint(0, 59))
            cur.execute(
                """INSERT INTO handover_notes(from_staff_id,to_staff_id,shift_id,department_id,note_text,is_read,created_at)
                   VALUES(?,?,?,?,?,?,?)""",
                (from_uid, to_uid if random.random() < 0.75 else None, sh_id, dept_id, txt, is_read, _fmt_datetime(hn_dt)),
            )
            hn_ids.append(int(cur.lastrowid))
        summary["handover_notes"] = len(hn_ids)

        task_ids: list[int] = []
        for i in range(15):
            title = TASK_TITLES[i]
            desc = f"Please complete: {title.lower()}. Priority per standard protocol and follow up if further action required."
            creator_id = random.choice(doctor_user_ids + nurse_user_ids + [user_ids["nurse"], user_ids["admin"]])
            assignee_id = random.choice(nurse_user_ids + [user_ids["nurse"]])
            if i < 3:
                priority = "High"
                status = random.choice(["Pending", "InProgress"])
            else:
                priority = random.choice(TASK_PRIORITIES)
                if priority == "High":
                    status = random.choice(["Pending", "InProgress", "Done"])
                else:
                    status = random.choice(TASK_STATUSES)
            dept_id = random.randint(1, 10)
            due = today + timedelta(days=random.randint(0, 7))
            due_dt = datetime.combine(due, datetime.min.time()) + timedelta(hours=random.randint(8, 20), minutes=random.randint(0, 59))
            completed_at = None
            if status == "Done":
                completed_at = _fmt_datetime(datetime.combine(today - timedelta(days=random.randint(0, 3)), datetime.min.time()) + timedelta(hours=random.randint(9, 20), minutes=random.randint(0, 59)))
            cur.execute(
                """INSERT INTO tasks(title,description,assignee_id,creator_id,priority,status,due_at,department_id,completed_at)
                   VALUES(?,?,?,?,?,?,?,?,?)""",
                (title, desc, assignee_id, creator_id, priority, status, _fmt_datetime(due_dt), dept_id, completed_at),
            )
            task_ids.append(int(cur.lastrowid))
        summary["tasks"] = len(task_ids)

        fb_ids: list[int] = []
        for i in range(15):
            cat = random.choice(FEEDBACK_CATEGORIES)
            subj = random.choice(FEEDBACK_SUBJECTS[cat])
            desc = FEEDBACK_DESCRIPTIONS[cat]
            is_anon = 1 if (i < 4 or random.random() < 0.3) else 0
            pid = None if is_anon else random.choice(patient_pk_ids)
            dept_id = random.randint(1, 10)
            if i < 5:
                status = "Open"
                resolved_at = None
                res_notes = None
                assignee_id = user_ids.get("admin")
            else:
                status = "Resolved"
                assignee_id = random.choice([user_ids.get("admin"), user_ids.get("nurse"), random.choice(doctor_user_ids)])
                res_notes = random.choice([
                    "Apology issued and action plan shared with department head.",
                    "Staff coached on communication; patient called directly.",
                    "Infrastructure team notified; maintenance scheduled.",
                    "Catering reviewed menu options and implemented rotation.",
                    "Billing department clarified charges over phone.",
                ])
                resolved_dt = datetime.combine(today - timedelta(days=random.randint(0, 10)), datetime.min.time()) + timedelta(hours=random.randint(9, 18), minutes=random.randint(0, 59))
                resolved_at = _fmt_datetime(resolved_dt)
            sub_dt = today - timedelta(days=random.randint(0, 45))
            sub_tm = datetime.combine(sub_dt, datetime.min.time()) + timedelta(hours=random.randint(9, 19), minutes=random.randint(0, 59))
            cur.execute(
                """INSERT INTO feedback(patient_id,is_anonymous,category,department_id,subject,description,status,assignee_id,resolution_notes,submitted_at,resolved_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                (pid, is_anon, cat, dept_id, subj, desc, status, assignee_id, res_notes, _fmt_datetime(sub_tm), resolved_at),
            )
            fb_ids.append(int(cur.lastrowid))
        summary["feedback"] = len(fb_ids)

        ict_ids: dict[str, int] = {}
        for name, items in IC_TEMPLATES.items():
            items_json = json.dumps(items, ensure_ascii=False)
            dept = random.choice([None, 7, 10, 6])
            cur.execute(
                "INSERT INTO ic_checklist_templates(name,department_id,items_json) VALUES(?,?,?)",
                (name, dept, items_json),
            )
            ict_ids[name] = int(cur.lastrowid)
        summary["ic_checklist_templates"] = len(ict_ids)

        icr_ids: list[int] = []
        template_names = list(IC_TEMPLATES.keys())
        for _ in range(12):
            tname = random.choice(template_names)
            tid = ict_ids[tname]
            items = IC_TEMPLATES[tname]
            ward = random.choice([f"{DEPARTMENTS[d-1][0]} Ward" for d in range(1, 11)])
            dept_id = random.randint(1, 10)
            done_by = random.choice(nurse_user_ids + [user_ids["nurse"]])
            done_at = datetime.combine(today - timedelta(days=random.randint(0, 7)), datetime.min.time()) + timedelta(hours=random.randint(6, 22), minutes=random.randint(0, 59))
            results = []
            for item in items:
                r = random.random()
                if r < 0.72:
                    result_val = "Pass"
                elif r < 0.92:
                    result_val = "Fail"
                else:
                    result_val = "N/A"
                results.append({"id": item["id"], "text": item["text"], "result": result_val})
            results_json = json.dumps(results, ensure_ascii=False)
            notes = ""
            fails = sum(1 for r in results if r["result"] == "Fail")
            if fails > 0:
                notes = f"{fails} item(s) flagged; escalation logged with ward manager."
            cur.execute(
                """INSERT INTO ic_checklist_records(template_id,ward,department_id,completed_by,completed_at,results_json,notes)
                   VALUES(?,?,?,?,?,?,?)""",
                (tid, ward, dept_id, done_by, _fmt_datetime(done_at), results_json, notes or None),
            )
            icr_ids.append(int(cur.lastrowid))
        summary["ic_checklist_records"] = len(icr_ids)

        notif_ids: list[int] = []
        low_stock_items = cur.execute(
            "SELECT id,name,quantity,reorder_threshold FROM inventory_items WHERE quantity <= reorder_threshold LIMIT 8"
        ).fetchall()
        near_exp_items = cur.execute(
            "SELECT id,name,expiry_date FROM inventory_items WHERE expiry_date IS NOT NULL AND date(expiry_date) <= date('now',?) AND date(expiry_date) >= date('now') LIMIT 5",
            (f"+{NEAR_EXPIRY_DAYS} days",),
        ).fetchall()
        for item in low_stock_items:
            data = {"item_id": int(item["id"]), "name": item["name"], "qty": int(item["quantity"]), "threshold": int(item["reorder_threshold"])}
            cur.execute(
                """INSERT INTO notifications(user_id,type,title,message,is_read,data_json)
                   VALUES(?,?,?,?,?,?)""",
                (
                    user_ids["inventory"], "LOW_STOCK",
                    f"Low stock alert: {item['name']}",
                    f"{item['name']} has {item['quantity']} remaining (reorder at {item['reorder_threshold']}). Initiate purchase order.",
                    0, json.dumps(data, ensure_ascii=False),
                ),
            )
            notif_ids.append(int(cur.lastrowid))
        for item in near_exp_items:
            data = {"item_id": int(item["id"]), "name": item["name"], "expiry_date": item["expiry_date"]}
            cur.execute(
                """INSERT INTO notifications(user_id,type,title,message,is_read,data_json)
                   VALUES(?,?,?,?,?,?)""",
                (
                    user_ids["inventory"], "EXPIRY",
                    f"Near-expiry: {item['name']}",
                    f"{item['name']} expires on {item['expiry_date']}. Review stock rotation and FIFO.",
                    0, json.dumps(data, ensure_ascii=False),
                ),
            )
            notif_ids.append(int(cur.lastrowid))

        occ_count_q = cur.execute("SELECT COUNT(*) FROM beds WHERE status='Occupied'").fetchone()[0]
        if occ_count_q >= total_beds * 0.95:
            cur.execute(
                """INSERT INTO notifications(user_id,type,title,message,is_read)
                   VALUES(?,?,?,?,?)""",
                (user_ids["admin"], "BED_SHORTAGE", "Bed shortage alert", "Occupancy exceeds 95%. Activate diversion and discharge planning protocols.", 0),
            )
            notif_ids.append(int(cur.lastrowid))
        else:
            cur.execute(
                """INSERT INTO notifications(user_id,type,title,message,is_read)
                   VALUES(?,?,?,?,?)""",
                (user_ids["admin"], "BED_SHORTAGE", "Bed usage update", f"Current occupancy: {occ_count_q}/{total_beds} beds occupied. Monitor ED inflow.", 0),
            )
            notif_ids.append(int(cur.lastrowid))

        future_appts = cur.execute(
            """SELECT a.id, p.patient_id, a.appointment_date, a.appointment_time FROM appointments a
               JOIN patients p ON p.id=a.patient_id
               WHERE a.status IN ('Scheduled','Confirmed') AND a.appointment_date=? LIMIT 4""",
            (_fmt_date(today + timedelta(days=1)),),
        ).fetchall()
        for fa in future_appts:
            cur.execute(
                """INSERT INTO notifications(user_id,type,title,message,is_read)
                   VALUES(?,?,?,?,?)""",
                (
                    random.choice(doctor_user_ids) if random.random() < 0.5 else user_ids["admin"],
                    "APPOINTMENT_REMINDER",
                    f"Appointment reminder for {fa['appointment_date']} {fa['appointment_time']}",
                    f"Patient {fa['patient_id']} has appointment tomorrow at {fa['appointment_time']}. Please confirm prep instructions.",
                    0,
                ),
            )
            notif_ids.append(int(cur.lastrowid))

        for dept_id in range(1, 11):
            waiting_q = cur.execute(
                "SELECT COUNT(*) FROM queue_tokens WHERE department_id=? AND status='Waiting'",
                (dept_id,),
            ).fetchone()[0]
            if waiting_q >= 10:
                cur.execute(
                    """INSERT INTO notifications(user_id,type,title,message,is_read)
                       VALUES(?,?,?,?,?)""",
                    (
                        user_ids["admin"], "QUEUE_UPDATE",
                        f"Queue alert in {DEPARTMENTS[dept_id-1][0]}",
                        f"{DEPARTMENTS[dept_id-1][0]} currently has {waiting_q} patients waiting. Consider redirecting staffing.",
                        0,
                    ),
                )
                notif_ids.append(int(cur.lastrowid))

        er_waiting_q = cur.execute(
            "SELECT COUNT(*) FROM queue_tokens WHERE department_id=6 AND status='Waiting'",
        ).fetchone()[0]
        if er_waiting_q > 0:
            cur.execute(
                """INSERT INTO notifications(user_id,type,title,message,is_read)
                   VALUES(?,?,?,?,?)""",
                (
                    user_ids["admin"], "EMERGENCY",
                    "Emergency queue active",
                    f"Emergency department currently has {er_waiting_q} patients waiting. Monitor triage for Level 1/2.",
                    0,
                ),
            )
            notif_ids.append(int(cur.lastrowid))

        while len(notif_ids) < 30:
            cur.execute(
                """INSERT INTO notifications(user_id,type,title,message,is_read)
                   VALUES(?,?,?,?,?)""",
                (
                    random.choice([user_ids["admin"], user_ids["inventory"], user_ids["nurse"]]),
                    random.choice(["INFO", "STAFF", "REPORT"]),
                    "System notification",
                    "Daily patient census and operational summary ready for review in the dashboard.",
                    1 if random.random() < 0.5 else 0,
                ),
            )
            notif_ids.append(int(cur.lastrowid))
        summary["notifications"] = len(notif_ids)

        # ---------------- Blood Bank Seeding ----------------
        blood_types = ["A+", "A-", "B+", "B-", "AB+", "AB-", "O+", "O-"]
        for bt in blood_types:
            avail_units = random.randint(3, 25)
            cur.execute(
                """INSERT INTO blood_inventory(blood_type, units_available, min_threshold_units, updated_at)
                   VALUES(?,?,?,?)""",
                (bt, avail_units, 10, _fmt_datetime(datetime.now())),
            )
        summary["blood_inventory"] = len(blood_types)

        donor_ids = []
        for i in range(1, 16):
            d_code = f"BD-DONOR-{i:03d}"
            fn = f"{random.choice(FIRST_NAMES)} {random.choice(LAST_NAMES)}"
            bt = random.choice(blood_types)
            phone = _rnd_phone()
            email = f"donor_{i}@example.com"
            days_ago = random.randint(10, 180)
            ld_date = _fmt_date(today - timedelta(days=days_ago))
            elig = "Eligible" if days_ago >= 56 else "Ineligible (Recent Donation)"
            donations = random.randint(1, 8)
            cur.execute(
                """INSERT INTO blood_donors(donor_code, full_name, blood_type, phone, email, last_donated_date, eligibility_status, total_donations, created_at)
                   VALUES(?,?,?,?,?,?,?,?,?)""",
                (d_code, fn, bt, phone, email, ld_date, elig, donations, _fmt_datetime(datetime.now())),
            )
            donor_ids.append(int(cur.lastrowid))
        summary["blood_donors"] = len(donor_ids)

        breq_ids = []
        for _ in range(8):
            pid = random.choice(patient_pk_ids)
            bt = random.choice(blood_types)
            urg = random.choice(["Routine", "Urgent", "Critical"])
            units = random.randint(1, 4)
            st = random.choice(["Requested", "Fulfilled", "Requested"])
            dept = random.choice([1, 2, 3, 5, 6])
            req_by = random.choice(doctor_user_ids)
            cur.execute(
                """INSERT INTO blood_requests(patient_id, requested_by, department_id, blood_type, units_requested, urgency, status, created_at)
                   VALUES(?,?,?,?,?,?,?,?)""",
                (pid, req_by, dept, bt, units, urg, st, _fmt_datetime(datetime.now() - timedelta(hours=random.randint(1, 48)))),
            )
            breq_ids.append(int(cur.lastrowid))
        summary["blood_requests"] = len(breq_ids)

        # ---------------- Ambulances & Dispatches Seeding ----------------
        amb_data = [
            ("AMB-101", "Robert Vance", "+1 555-0191", "Available", "Base Station", 12.9716, 77.5946),
            ("AMB-102", "Sarah Connor", "+1 555-0192", "Dispatched", "En Route to Scene", 12.9820, 77.6010),
            ("AMB-103", "David Miller", "+1 555-0193", "On Call", "Transporting Patient", 12.9650, 77.5880),
            ("AMB-104", "Jennifer Lopez", "+1 555-0194", "Available", "Base Station", 12.9716, 77.5946),
            ("AMB-105", "Michael Scott", "+1 555-0195", "Available", "Base Station", 12.9716, 77.5946),
        ]
        amb_ids = []
        for vehicle, driver, phone, status, loc, lat, lng in amb_data:
            cur.execute(
                """INSERT INTO ambulances(vehicle_number, driver_name, driver_phone, status, current_location, lat, lng)
                   VALUES(?,?,?,?,?,?,?)""",
                (vehicle, driver, phone, status, loc, lat, lng),
            )
            amb_ids.append(int(cur.lastrowid))
        summary["ambulances"] = len(amb_ids)

        disp_data = [
            (amb_ids[1], patient_pk_ids[0], "104 Maple Street, Sector 4", 6, "Dispatched", 12, 4.2, "Route: Emergency Priority Expressway | Distance: 4.2 km | ETA: 12 min"),
            (amb_ids[2], patient_pk_ids[1], "78 Lakeview Ave, Block B", 6, "Transporting", 8, 3.1, "Route: Direct City Center Route | Distance: 3.1 km | ETA: 8 min"),
            (amb_ids[0], patient_pk_ids[2], "22 North Avenue", 6, "Completed", 15, 5.5, "Route: Outer Ring Road Bypass | Distance: 5.5 km | ETA: 15 min"),
        ]
        disp_ids = []
        for a_id, p_id, addr, dept, st, eta, dist, route_sum in disp_data:
            cur.execute(
                """INSERT INTO ambulance_dispatches(ambulance_id, patient_id, pickup_address, destination_dept_id, status, eta_minutes, distance_km, route_summary, dispatched_at)
                   VALUES(?,?,?,?,?,?,?,?,?)""",
                (a_id, p_id, addr, dept, st, eta, dist, route_sum, _fmt_datetime(datetime.now() - timedelta(minutes=random.randint(10, 60)))),
            )
            disp_ids.append(int(cur.lastrowid))
        summary["ambulance_dispatches"] = len(disp_ids)

    return summary

