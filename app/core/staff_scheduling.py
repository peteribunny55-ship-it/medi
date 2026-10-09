from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta
from typing import Any, Optional

from .audit import log_action
from .permissions import require_role, can_manage_staff, can_approve_schedule


def list_staff(
    conn: sqlite3.Connection,
    dept_id: Optional[int] = None,
) -> list[dict[str, Any]]:
    """List staff records joined with user info.

    Args:
        conn: SQLite connection.
        dept_id: Optional department filter.

    Returns:
        List of staff+user dicts.
    """
    q = """
        SELECT s.*, u.username, u.full_name, u.email, u.role AS user_role,
               u.department_id AS user_department_id, u.created_at AS user_created_at
        FROM staff s
        JOIN users u ON u.id = s.user_id
        WHERE 1=1
    """
    params: list[Any] = []
    if dept_id is not None:
        q += " AND s.department_id = ?"
        params.append(int(dept_id))
    q += " ORDER BY s.id"
    rows = conn.execute(q, params).fetchall()
    return [dict(r) for r in rows]


def list_shifts(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """List all shift definitions.

    Args:
        conn: SQLite connection.

    Returns:
        List of shift dicts.
    """
    rows = conn.execute("SELECT * FROM shifts ORDER BY id").fetchall()
    return [dict(r) for r in rows]


def ensure_min_staffing_dict(
    conn: sqlite3.Connection,
) -> dict[int, dict[int, int]]:
    """Return {dept_id: {shift_id: min_staff}}.

    Uses a heuristic of 2 per shift per department if no explicit
    min_staffing table exists. Departments with >20 staff get 3.

    Args:
        conn: SQLite connection.

    Returns:
        Nested dict mapping dept_id -> shift_id -> min count.
    """
    out: dict[int, dict[int, int]] = {}
    depts = conn.execute("SELECT id FROM departments").fetchall()
    shifts = conn.execute("SELECT id FROM shifts").fetchall()
    for d in depts:
        dept_id = int(d["id"])
        out[dept_id] = {}
        staff_count_row = conn.execute(
            "SELECT COUNT(*) AS c FROM staff WHERE department_id=?",
            (dept_id,),
        ).fetchone()
        staff_count = int(staff_count_row["c"]) if staff_count_row else 0
        base = 3 if staff_count > 20 else 2
        for s in shifts:
            shift_id = int(s["id"])
            out[dept_id][shift_id] = base
    return out


def _date_range(week_start_str: str) -> list[str]:
    """Return list of 7 date strings (YYYY-MM-DD) starting on week_start_str (inclusive)."""
    d = datetime.strptime(week_start_str[:10], "%Y-%m-%d").date()
    return [(d + timedelta(days=i)).isoformat() for i in range(7)]


def _night_shift_ids(conn: sqlite3.Connection) -> set[int]:
    """Heuristic: shifts with start_time >= 20:00 or end_time <= 06:00 are night."""
    ids: set[int] = set()
    for sh in list_shifts(conn):
        st = str(sh.get("start_time", "")).replace(":", "")
        et = str(sh.get("end_time", "") or "").replace(":", "")
        try:
            if (st and int(st[:2]) >= 20) or (et and int(et[:2]) <= 6):
                ids.add(int(sh["id"]))
        except Exception:
            pass
    return ids


def _morning_shift_ids(conn: sqlite3.Connection) -> set[int]:
    """Heuristic: shifts with start_time between 05:00 and 09:00."""
    ids: set[int] = set()
    for sh in list_shifts(conn):
        st = str(sh.get("start_time", ""))
        try:
            hh = int(st[:2])
            if 5 <= hh <= 9:
                ids.add(int(sh["id"]))
        except Exception:
            pass
    return ids


def _greedy_schedule(
    conn: sqlite3.Connection,
    week_start_str: str,
    dates: list[str],
    staff_list: list[dict[str, Any]],
    shifts_list: list[dict[str, Any]],
    min_staffing: dict[int, dict[int, int]],
) -> list[dict[str, Any]]:
    """Greedy fallback: assign by availability until min staffing met."""
    rows: list[dict[str, Any]] = []
    shift_ids = [int(s["id"]) for s in shifts_list]
    night_ids = _night_shift_ids(conn)
    morning_ids = _morning_shift_ids(conn)
    staff_hours: dict[int, int] = {int(s["id"]): 0 for s in staff_list}
    staff_weekly_limit = {
        int(s["id"]): int(s.get("weekly_hours_limit") or 40) for s in staff_list
    }
    avail_lookup: dict[tuple[int, str, int], bool] = {}
    for av in conn.execute("SELECT staff_id, shift_date, shift_id, is_available FROM staff_availability").fetchall():
        avail_lookup[(int(av["staff_id"]), str(av["shift_date"])[:10], int(av["shift_id"]))] = bool(int(av["is_available"]))
    assigned_day: dict[tuple[int, str], int] = {}
    last_shift: dict[int, int] = {}
    for dept_id, shift_map in min_staffing.items():
        dept_staff = [s for s in staff_list if int(s.get("department_id") or 0) == dept_id]
        for date in dates:
            for shift_id in shift_ids:
                minimum = shift_map.get(shift_id, 0)
                assigned = 0
                for staff in sorted(dept_staff, key=lambda s: staff_hours[int(s["id"])]):
                    if assigned >= minimum:
                        break
                    sid = int(staff["id"])
                    if assigned_day.get((sid, date), 0) > 0:
                        continue
                    if staff_hours[sid] + 8 > staff_weekly_limit[sid]:
                        continue
                    avail = avail_lookup.get((sid, date, shift_id), True)
                    if not avail:
                        continue
                    if last_shift.get(sid) in night_ids and shift_id in morning_ids:
                        continue
                    rows.append({
                        "schedule_date": date,
                        "shift_id": shift_id,
                        "staff_id": sid,
                        "department_id": dept_id,
                        "status": "Recommended",
                    })
                    assigned_day[(sid, date)] = shift_id
                    staff_hours[sid] += 8
                    last_shift[sid] = shift_id
                    assigned += 1
    return rows


def _pulp_schedule(
    conn: sqlite3.Connection,
    week_start_str: str,
    dates: list[str],
    staff_list: list[dict[str, Any]],
    shifts_list: list[dict[str, Any]],
    min_staffing: dict[int, dict[int, int]],
) -> list[dict[str, Any]]:
    """PuLP ILP schedule. Returns rows or raises on failure."""
    import pulp  # type: ignore
    from pulp import LpProblem, LpVariable, LpMinimize, LpBinary, lpSum, solvers  # type: ignore

    shift_ids = [int(s["id"]) for s in shifts_list]
    night_ids = _night_shift_ids(conn)
    morning_ids = _morning_shift_ids(conn)
    avail_lookup: dict[tuple[int, str, int], bool] = {}
    for av in conn.execute("SELECT staff_id, shift_date, shift_id, is_available FROM staff_availability").fetchall():
        avail_lookup[(int(av["staff_id"]), str(av["shift_date"])[:10], int(av["shift_id"]))] = bool(int(av["is_available"]))
    staff_weekly_limit = {
        int(s["id"]): int(s.get("weekly_hours_limit") or 40) for s in staff_list
    }
    combos: list[tuple[int, int, str]] = []
    x: dict[tuple[int, int, str], Any] = {}
    for staff in staff_list:
        sid = int(staff["id"])
        dept_id = int(staff.get("department_id") or 0)
        for date in dates:
            for shift_id in shift_ids:
                if not avail_lookup.get((sid, date, shift_id), True):
                    continue
                key = (sid, shift_id, date)
                combos.append((sid, shift_id, date))
                x[key] = LpVariable(f"x_{sid}_{shift_id}_{date}", cat=LpBinary)
                _ = dept_id
    prob = LpProblem("StaffSchedule", LpMinimize)
    prob += lpSum(x.values())
    for staff in staff_list:
        sid = int(staff["id"])
        limit = staff_weekly_limit[sid]
        max_shifts = limit // 8
        vars_for_staff = [v for (s, _, _), v in x.items() if s == sid]
        if vars_for_staff:
            prob += lpSum(vars_for_staff) <= max_shifts
        for date in dates:
            vars_day = [v for (s, sh, d), v in x.items() if s == sid and d == date]
            if vars_day:
                prob += lpSum(vars_day) <= 1
        for i in range(len(dates) - 1):
            d_prev = dates[i]
            d_next = dates[i + 1]
            for nid in night_ids:
                for mid in morning_ids:
                    v_prev = x.get((sid, nid, d_prev))
                    v_next = x.get((sid, mid, d_next))
                    if v_prev is not None and v_next is not None:
                        prob += v_prev + v_next <= 1
    for dept_id, shift_map in min_staffing.items():
        dept_staff_ids = {int(s["id"]) for s in staff_list if int(s.get("department_id") or 0) == dept_id}
        for date in dates:
            for shift_id in shift_ids:
                minimum = shift_map.get(shift_id, 0)
                if minimum <= 0:
                    continue
                vars_cell = [
                    v for (s, sh, d), v in x.items()
                    if s in dept_staff_ids and sh == shift_id and d == date
                ]
                if vars_cell:
                    prob += lpSum(vars_cell) >= minimum
    solver = solvers.PULP_CBC_CMD(msg=0)
    status = prob.solve(solver)
    if pulp.LpStatus[status] != "Optimal":
        raise RuntimeError(f"PuLP solver returned status {pulp.LpStatus[status]}")
    rows: list[dict[str, Any]] = []
    for staff in staff_list:
        sid = int(staff["id"])
        dept_id = int(staff.get("department_id") or 0)
        for date in dates:
            for shift_id in shift_ids:
                key = (sid, shift_id, date)
                v = x.get(key)
                if v is not None and int(v.value() or 0) == 1:
                    rows.append({
                        "schedule_date": date,
                        "shift_id": shift_id,
                        "staff_id": sid,
                        "department_id": dept_id,
                        "status": "Recommended",
                    })
    return rows


def generate_weekly_schedule(
    conn: sqlite3.Connection,
    user: Optional[dict[str, Any]],
    week_start_date_str: str,
) -> tuple[list[dict[str, Any]], str]:
    """Generate a weekly schedule for the week starting week_start_date_str.

    Attempts a PuLP ILP solve first; falls back to a greedy heuristic if
    PuLP import/solve fails or returns infeasible. Inserts the resulting
    rows with status='Recommended'.

    Args:
        conn: SQLite connection.
        user: Actor user dict (must be Admin).
        week_start_date_str: Week start date (YYYY-MM-DD).

    Returns:
        (schedule_rows, method) where method is 'PuLP' or 'Greedy'.

    Raises:
        PermissionError_: If user is not Admin.
        ValueError: On invalid date string.
    """
    require_role(user, "Admin")
    dates = _date_range(week_start_date_str)
    staff_list = list_staff(conn)
    shifts_list = list_shifts(conn)
    min_staffing = ensure_min_staffing_dict(conn)
    method = "PuLP"
    rows: list[dict[str, Any]] = []
    try:
        rows = _pulp_schedule(conn, week_start_date_str, dates, staff_list, shifts_list, min_staffing)
    except Exception:
        method = "Greedy"
        rows = _greedy_schedule(conn, week_start_date_str, dates, staff_list, shifts_list, min_staffing)
    inserted: list[dict[str, Any]] = []
    try:
        conn.execute("BEGIN IMMEDIATE")
        cur = conn.cursor()
        for r in rows:
            try:
                cur.execute(
                    """INSERT OR IGNORE INTO schedules(schedule_date,shift_id,staff_id,department_id,status)
                       VALUES(?,?,?,?,?)""",
                    (r["schedule_date"], int(r["shift_id"]), int(r["staff_id"]), int(r["department_id"]), r["status"]),
                )
                if cur.rowcount > 0:
                    rid = cur.lastrowid
                    inserted.append({**r, "id": rid})
                    log_action(
                        conn,
                        int(user["id"]) if user else None,
                        user.get("role") if user else None,
                        "CREATE",
                        "schedule",
                        str(rid),
                        {
                            "schedule_date": r["schedule_date"],
                            "shift_id": r["shift_id"],
                            "staff_id": r["staff_id"],
                            "department_id": r["department_id"],
                            "method": method,
                        },
                    )
            except Exception:
                continue
        conn.execute("COMMIT")
    except Exception as exc:
        conn.execute("ROLLBACK")
        raise exc
    return inserted, method
