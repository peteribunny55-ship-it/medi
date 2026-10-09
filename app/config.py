from __future__ import annotations

SEED = 42

ROLES = ["Admin", "Doctor", "Nurse", "Patient", "InventoryManager"]

DEPARTMENTS = [
    ("Cardiology", "Heart and cardiovascular care", 1),
    ("Neurology", "Brain and nervous system care", 2),
    ("Orthopedics", "Bones, joints, and musculoskeletal care", 2),
    ("Pediatrics", "Child and infant care", 1),
    ("General Medicine", "Primary and general internal medicine", 3),
    ("Emergency", "24/7 emergency department", 0),
    ("ICU", "Intensive Care Unit", 4),
    ("Radiology", "Imaging and diagnostic radiology", 1),
    ("Laboratory", "Clinical laboratory services", 1),
    ("Pharmacy", "Medication dispensing and management", 0),
]

BED_TYPES = ["General", "ICU", "HDU", "Emergency", "Pediatric", "Isolation"]

BED_STATUSES = ["Available", "Occupied", "Reserved", "Maintenance"]

SHIFT_TYPES = [
    ("Morning", "07:00", "15:00"),
    ("Afternoon", "15:00", "23:00"),
    ("Night", "23:00", "07:00"),
]

APPOINTMENT_STATUSES = [
    "Scheduled",
    "Confirmed",
    "Completed",
    "Missed",
    "Cancelled",
]

QUEUE_STATUSES = ["Waiting", "Called", "InProgress", "Completed", "Cancelled"]

ADMISSION_STATUSES = [
    "Admitted",
    "InTransfer",
    "DischargePending",
    "Discharged",
]

TASK_PRIORITIES = ["Low", "Medium", "High"]
TASK_STATUSES = ["Pending", "InProgress", "Done"]

INVENTORY_CATEGORIES = ["Medicine", "Equipment", "Supplies"]

LAB_STATUSES = ["Requested", "InProgress", "Completed", "Cancelled"]

HOLIDAYS = [
    "01-01", "01-26", "03-29", "04-07", "05-01", "08-15",
    "10-02", "10-24", "12-25", "12-26",
]

DEMO_USERS = [
    {"username": "admin",    "password": "admin123",     "role": "Admin",            "full_name": "Dr. Alice Admin",     "email": "admin@hospital.edu",     "department_id": None},
    {"username": "doctor",   "password": "doctor123",    "role": "Doctor",           "full_name": "Dr. Bob Cardiologist","email": "bob@hospital.edu",       "department_id": 1},
    {"username": "nurse",    "password": "nurse123",     "role": "Nurse",            "full_name": "Nancy Nurse",         "email": "nancy@hospital.edu",     "department_id": 5},
    {"username": "patient",  "password": "patient123",   "role": "Patient",          "full_name": "Peter Patient",       "email": "peter.patient@mail.com", "department_id": None},
    {"username": "inventory","password": "inventory123", "role": "InventoryManager", "full_name": "Ivy Stockman",        "email": "ivy@hospital.edu",       "department_id": 10},
]

LAB_DELAY_THRESHOLD_MINUTES = 24 * 60
NEAR_EXPIRY_DAYS = 30
MIN_STAFF_PER_SHIFT = {
    1: 1, 2: 1, 3: 1, 4: 1, 5: 2,
    6: 2, 7: 2, 8: 1, 9: 2, 10: 1,
}
