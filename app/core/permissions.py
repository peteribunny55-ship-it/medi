from __future__ import annotations

import sqlite3
from typing import Any, Optional, Union

from .auth import get_patient_user_link

RoleSet = Union[str, list[str], tuple[str, ...]]

_ADMIN = "Admin"
_DOCTOR = "Doctor"
_NURSE = "Nurse"
_PATIENT = "Patient"
_INVMGR = "InventoryManager"

ALL_ROLES = [_ADMIN, _DOCTOR, _NURSE, _PATIENT, _INVMGR]
STAFF_ROLES = [_ADMIN, _DOCTOR, _NURSE]
CLINICAL_ROLES = [_ADMIN, _DOCTOR, _NURSE]
MANAGEMENT_ROLES = [_ADMIN, _INVMGR]


class PermissionError_(Exception):
    pass


def _user_role(user: Optional[dict[str, Any]]) -> str:
    if not user:
        return ""
    return user.get("role", "") or ""


def _in_roles(user: Optional[dict[str, Any]], allowed: RoleSet) -> bool:
    role = _user_role(user)
    if isinstance(allowed, str):
        return role == allowed
    return role in set(allowed)


def require_role(user: Optional[dict[str, Any]], allowed: RoleSet) -> bool:
    """Raises PermissionError_ if user role is not in allowed set."""
    if not user:
        raise PermissionError_("Authentication required")
    if not _in_roles(user, allowed):
        raise PermissionError_(f"Role '{_user_role(user)}' not permitted for this action")
    return True


def can_manage_users(user: Optional[dict[str, Any]]) -> bool:
    return _in_roles(user, [_ADMIN])


def can_view_reports(user: Optional[dict[str, Any]]) -> bool:
    return _in_roles(user, [_ADMIN, _INVMGR, _DOCTOR, _NURSE])


def can_view_audit_log(user: Optional[dict[str, Any]]) -> bool:
    return _in_roles(user, [_ADMIN])


# ---------------- Patients ----------------
def can_view_patient(
    conn: sqlite3.Connection,
    user: Optional[dict[str, Any]],
    patient_id: Optional[int] = None,
) -> bool:
    """Return True if user may read this patient's data. Patient role → only their own link."""
    if not user:
        return False
    role = _user_role(user)
    if role in (_ADMIN, _DOCTOR, _NURSE):
        return True
    if role == _INVMGR:
        return False  # inventory should not see PHI
    if role == _PATIENT:
        if patient_id is None:
            return False
        linked = get_patient_user_link(conn, int(user["id"]))
        return linked is not None and int(linked) == int(patient_id)
    return False


def can_modify_patient(user: Optional[dict[str, Any]]) -> bool:
    return _in_roles(user, [_ADMIN, _DOCTOR, _NURSE])


def can_register_patient(user: Optional[dict[str, Any]]) -> bool:
    return _in_roles(user, [_ADMIN, _NURSE]) or (user and _user_role(user) == _PATIENT)  # self-register limited


# ---------------- Appointments ----------------
def can_book_appointment(user: Optional[dict[str, Any]]) -> bool:
    return _in_roles(user, [_ADMIN, _DOCTOR, _NURSE, _PATIENT])


def can_cancel_any_appointment(user: Optional[dict[str, Any]]) -> bool:
    return _in_roles(user, [_ADMIN, _DOCTOR, _NURSE])


def can_view_appointment(
    conn: sqlite3.Connection, user: Optional[dict[str, Any]], patient_id: Optional[int], doctor_user_id: Optional[int]
) -> bool:
    if not user:
        return False
    role = _user_role(user)
    if role in (_ADMIN, _NURSE):
        return True
    if role == _DOCTOR:
        return doctor_user_id is not None and int(doctor_user_id) == int(user["id"])
    if role == _PATIENT:
        if patient_id is None:
            return False
        linked = get_patient_user_link(conn, int(user["id"]))
        return linked is not None and int(linked) == int(patient_id)
    return False


# ---------------- Queue ----------------
def can_manage_queue(user: Optional[dict[str, Any]]) -> bool:
    return _in_roles(user, [_ADMIN, _NURSE, _DOCTOR])


def can_call_next_patient(user: Optional[dict[str, Any]]) -> bool:
    return _in_roles(user, [_ADMIN, _NURSE])


# ---------------- Beds / Admissions ----------------
def can_manage_beds(user: Optional[dict[str, Any]]) -> bool:
    return _in_roles(user, [_ADMIN, _NURSE, _DOCTOR])


def can_allocate_bed(user: Optional[dict[str, Any]]) -> bool:
    return _in_roles(user, [_ADMIN, _NURSE])


# ---------------- Staff / Scheduling ----------------
def can_manage_staff(user: Optional[dict[str, Any]]) -> bool:
    return _in_roles(user, [_ADMIN])


def can_approve_schedule(user: Optional[dict[str, Any]]) -> bool:
    return _in_roles(user, [_ADMIN])


# ---------------- OR ----------------
def can_manage_or(user: Optional[dict[str, Any]]) -> bool:
    return _in_roles(user, [_ADMIN, _DOCTOR])


# ---------------- Emergency ----------------
def can_manage_emergency(user: Optional[dict[str, Any]]) -> bool:
    return _in_roles(user, [_ADMIN, _DOCTOR, _NURSE])


def can_assign_triage(user: Optional[dict[str, Any]]) -> bool:
    return _in_roles(user, [_ADMIN, _DOCTOR])  # human-assigned only


# ---------------- Inventory ----------------
def can_manage_inventory(user: Optional[dict[str, Any]]) -> bool:
    return _in_roles(user, [_ADMIN, _INVMGR])


def can_view_inventory(user: Optional[dict[str, Any]]) -> bool:
    return _in_roles(user, [_ADMIN, _INVMGR, _NURSE, _DOCTOR])


# ---------------- Lab ----------------
def can_request_lab(user: Optional[dict[str, Any]]) -> bool:
    return _in_roles(user, [_ADMIN, _DOCTOR, _NURSE])


def can_view_lab_result(
    conn: sqlite3.Connection, user: Optional[dict[str, Any]], patient_id: int, requesting_user_id: Optional[int]
) -> bool:
    if not user:
        return False
    role = _user_role(user)
    if role in (_ADMIN, _NURSE, _DOCTOR):
        return True
    if role == _PATIENT:
        linked = get_patient_user_link(conn, int(user["id"]))
        return linked is not None and int(linked) == int(patient_id)
    return False


def can_update_lab(user: Optional[dict[str, Any]]) -> bool:
    return _in_roles(user, [_ADMIN, _NURSE, _DOCTOR])


# ---------------- Handovers / Tasks ----------------
def can_view_handover(user: Optional[dict[str, Any]], dept_id: Optional[int]) -> bool:
    if not user:
        return False
    role = _user_role(user)
    if role == _ADMIN:
        return True
    if role in (_DOCTOR, _NURSE):
        return dept_id is None or int(user.get("department_id") or 0) == int(dept_id)
    return False


def can_create_handover(user: Optional[dict[str, Any]]) -> bool:
    return _in_roles(user, [_ADMIN, _NURSE, _DOCTOR])


def can_view_tasks(user: Optional[dict[str, Any]], assignee_id: Optional[int], dept_id: Optional[int]) -> bool:
    if not user:
        return False
    role = _user_role(user)
    if role == _ADMIN:
        return True
    if assignee_id is not None and int(assignee_id) == int(user["id"]):
        return True
    if role in (_NURSE, _DOCTOR) and dept_id is not None and int(user.get("department_id") or 0) == int(dept_id):
        return True
    return False


def can_assign_task(user: Optional[dict[str, Any]]) -> bool:
    return _in_roles(user, [_ADMIN, _NURSE])


# ---------------- Feedback ----------------
def can_submit_feedback(user: Optional[dict[str, Any]]) -> bool:
    return user is not None  # any authenticated user (or allow anonymous via page UI)


def can_resolve_feedback(user: Optional[dict[str, Any]]) -> bool:
    return _in_roles(user, [_ADMIN])


# ---------------- Infection Control ----------------
def can_complete_ic_checklist(user: Optional[dict[str, Any]]) -> bool:
    return _in_roles(user, [_ADMIN, _NURSE, _DOCTOR])


# ---------------- Notifications ----------------
def can_send_notifications(user: Optional[dict[str, Any]]) -> bool:
    return _in_roles(user, [_ADMIN])


# ---------------- Blood Bank & Ambulances ----------------
def can_manage_blood_bank(user: Optional[dict[str, Any]]) -> bool:
    return _in_roles(user, [_ADMIN, _DOCTOR, _NURSE, _INVMGR])


def can_manage_ambulances(user: Optional[dict[str, Any]]) -> bool:
    return _in_roles(user, [_ADMIN, _DOCTOR, _NURSE])

