from __future__ import annotations

import datetime as _dt
import math
import sqlite3
from typing import Any, Optional

from .audit import log_action
from .permissions import require_role

# Default Hospital Base Coordinates (Central Hospital Emergency Entrance)
HOSPITAL_LAT = 12.9716
HOSPITAL_LNG = 77.5946
HOSPITAL_NAME = "Medi Central Emergency Center"


def _now_iso() -> str:
    return _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def haversine_distance(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Calculate the Great Circle / Haversine distance in kilometers between two points."""
    R = 6371.0  # Earth radius in kilometers
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = (
        math.sin(dlat / 2.0) ** 2
        + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlng / 2.0) ** 2
    )
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
    return round(R * c, 2)


def generate_route_geometry(
    origin_lat: float, origin_lng: float, dest_lat: float, dest_lng: float, route_type: str = "fastest"
) -> dict[str, Any]:
    """
    Generate interactive route map geometry, waypoints, distance, ETA, and turn-by-turn navigation cues.

    Routes:
      - 'fastest': Emergency corridor via expressway (Speed ~55 km/h, clear traffic, priority signal override)
      - 'shortest': Direct city arterial route (Speed ~35 km/h, distance slightly less)
      - 'bypass': Ring road bypass route (Speed ~48 km/h, avoids downtown congestion)
    """
    dist_direct = haversine_distance(origin_lat, origin_lng, dest_lat, dest_lng)
    # Ensure a non-zero distance for local testing
    if dist_direct < 0.1:
        dist_direct = 2.5

    if route_type == "fastest":
        multiplier = 1.25  # Road network tortuosity
        speed_kmh = 55.0  # Priority speed for emergency vehicle
        traffic_condition = "Green / Priority Signals Active"
        route_name = "⚡ Emergency Priority Expressway (Fastest Route)"
        offset_lat, offset_lng = 0.002, -0.003
    elif route_type == "shortest":
        multiplier = 1.12
        speed_kmh = 35.0
        traffic_condition = "Yellow / Moderate Downtown Traffic"
        route_name = "📏 Direct City Center Route"
        offset_lat, offset_lng = -0.001, 0.002
    else:  # bypass
        multiplier = 1.45
        speed_kmh = 48.0
        traffic_condition = "Green / Outer Ring Road Clear"
        route_name = "🔄 Outer Ring Road Bypass"
        offset_lat, offset_lng = 0.004, 0.005

    road_distance = round(dist_direct * multiplier, 2)
    eta_minutes = int(math.ceil((road_distance / speed_kmh) * 60))
    if eta_minutes < 2:
        eta_minutes = 2

    # Generate 6 key navigation waypoints along the route curve
    waypoints = []
    num_steps = 6
    for i in range(num_steps + 1):
        t = i / float(num_steps)
        # Add slight arc offset for realistic curve
        arc = math.sin(t * math.pi)
        w_lat = round(origin_lat + t * (dest_lat - origin_lat) + arc * offset_lat, 6)
        w_lng = round(origin_lng + t * (dest_lng - origin_lng) + arc * offset_lng, 6)
        waypoints.append([w_lat, w_lng])

    # Turn-by-turn navigation guidance steps
    navigation_steps = [
        {"step": 1, "instruction": "Depart pickup location and enter Emergency Vehicle Corridor", "distance_m": 300},
        {"step": 2, "instruction": f"Turn onto {route_name.split('(')[0].strip()} and activate siren override", "distance_m": int(road_distance * 300)},
        {"step": 3, "instruction": f"Proceed straight past signal intersection with green wave priority ({traffic_condition})", "distance_m": int(road_distance * 400)},
        {"step": 4, "instruction": "Take dedicated hospital exit ramp towards Emergency Gate 1", "distance_m": int(road_distance * 200)},
        {"step": 5, "instruction": f"Arrive at {HOSPITAL_NAME} Emergency Triage Bay", "distance_m": 100},
    ]

    return {
        "route_type": route_type,
        "route_name": route_name,
        "distance_km": road_distance,
        "eta_minutes": eta_minutes,
        "speed_kmh": speed_kmh,
        "traffic_condition": traffic_condition,
        "waypoints": waypoints,  # list of [lat, lng]
        "navigation_steps": navigation_steps,
        "origin": [origin_lat, origin_lng],
        "destination": [dest_lat, dest_lng],
    }


def list_ambulances(
    conn: sqlite3.Connection, status: Optional[str] = None
) -> list[dict[str, Any]]:
    """List ambulance fleet members."""
    q = "SELECT * FROM ambulances"
    params: list[Any] = []
    if status:
        q += " WHERE status = ?"
        params.append(status)
    q += " ORDER BY id ASC"
    rows = conn.execute(q, params).fetchall()
    return [dict(r) for r in rows]


def create_ambulance(
    conn: sqlite3.Connection,
    user: Optional[dict[str, Any]],
    vehicle_number: str,
    driver_name: str,
    driver_phone: str = "",
    current_location: str = "Central Emergency Station",
    lat: float = HOSPITAL_LAT,
    lng: float = HOSPITAL_LNG,
) -> dict[str, Any]:
    """Register new ambulance in the fleet."""
    require_role(user, ["Admin", "Doctor", "Nurse"])
    if not vehicle_number or not vehicle_number.strip():
        raise ValueError("Vehicle number is required")
    if not driver_name or not driver_name.strip():
        raise ValueError("Driver name is required")

    try:
        conn.execute("BEGIN IMMEDIATE")
        cur = conn.cursor()
        cur.execute(
            """INSERT INTO ambulances (vehicle_number, driver_name, driver_phone, status, current_location, lat, lng)
               VALUES (?, ?, ?, 'Available', ?, ?, ?)""",
            (vehicle_number.strip(), driver_name.strip(), driver_phone.strip(), current_location, lat, lng),
        )
        amb_id = int(cur.lastrowid or 0)
        log_action(
            conn,
            int(user["id"]) if user else None,
            user.get("role") if user else None,
            "CREATE",
            "ambulance",
            str(amb_id),
            {"vehicle": vehicle_number, "driver": driver_name},
        )
        conn.execute("COMMIT")
    except Exception as exc:
        conn.execute("ROLLBACK")
        raise exc

    row = conn.execute("SELECT * FROM ambulances WHERE id=?", (amb_id,)).fetchone()
    return dict(row)


def update_ambulance_location(
    conn: sqlite3.Connection,
    user: Optional[dict[str, Any]],
    ambulance_id: int,
    lat: float,
    lng: float,
    current_location: Optional[str] = None,
    status: Optional[str] = None,
) -> dict[str, Any]:
    """Update current GPS position and status of an ambulance."""
    require_role(user, ["Admin", "Doctor", "Nurse"])
    amb = conn.execute("SELECT * FROM ambulances WHERE id=?", (int(ambulance_id),)).fetchone()
    if not amb:
        raise ValueError(f"Ambulance ID {ambulance_id} not found")

    q = "UPDATE ambulances SET lat=?, lng=?"
    params: list[Any] = [float(lat), float(lng)]

    if current_location:
        q += ", current_location=?"
        params.append(current_location)
    if status:
        q += ", status=?"
        params.append(status)

    q += " WHERE id=?"
    params.append(int(ambulance_id))

    conn.execute(q, params)
    updated = conn.execute("SELECT * FROM ambulances WHERE id=?", (int(ambulance_id),)).fetchone()
    return dict(updated)


# ---------------- Dispatches & Route Optimization ----------------
def dispatch_ambulance(
    conn: sqlite3.Connection,
    user: Optional[dict[str, Any]],
    ambulance_id: int,
    pickup_address: str,
    patient_id: Optional[int] = None,
    emergency_case_id: Optional[int] = None,
    destination_dept_id: Optional[int] = 6,
    pickup_lat: float = 12.9800,
    pickup_lng: float = 77.6000,
    route_preference: str = "fastest",
) -> dict[str, Any]:
    """
    Dispatch an ambulance to an emergency scene with calculated route and ETA.
    """
    require_role(user, ["Admin", "Doctor", "Nurse"])
    amb = conn.execute("SELECT * FROM ambulances WHERE id=?", (int(ambulance_id),)).fetchone()
    if not amb:
        raise ValueError(f"Ambulance ID {ambulance_id} not found")
    if str(amb["status"]) not in ("Available", "Base Station"):
        raise ValueError(f"Ambulance {amb['vehicle_number']} is currently {amb['status']}")

    # Get route calculation from pickup location to Hospital Destination
    route_info = generate_route_geometry(
        pickup_lat, pickup_lng, HOSPITAL_LAT, HOSPITAL_LNG, route_type=route_preference
    )

    summary_text = (
        f"Route: {route_info['route_name']} | Distance: {route_info['distance_km']} km | "
        f"ETA: {route_info['eta_minutes']} min | Condition: {route_info['traffic_condition']}"
    )

    try:
        conn.execute("BEGIN IMMEDIATE")
        cur = conn.cursor()
        cur.execute(
            """INSERT INTO ambulance_dispatches
               (ambulance_id, patient_id, emergency_case_id, pickup_address, destination_dept_id,
                status, eta_minutes, distance_km, route_summary, dispatched_at)
               VALUES (?, ?, ?, ?, ?, 'Dispatched', ?, ?, ?, ?)""",
            (
                int(ambulance_id),
                int(patient_id) if patient_id else None,
                int(emergency_case_id) if emergency_case_id else None,
                pickup_address.strip(),
                int(destination_dept_id) if destination_dept_id else 6,
                route_info["eta_minutes"],
                route_info["distance_km"],
                summary_text,
                _now_iso(),
            ),
        )
        dispatch_id = int(cur.lastrowid or 0)

        # Update ambulance status to Dispatched
        conn.execute(
            "UPDATE ambulances SET status='Dispatched', current_location=? WHERE id=?",
            (f"En Route to {pickup_address[:30]}", int(ambulance_id)),
        )

        log_action(
            conn,
            int(user["id"]) if user else None,
            user.get("role") if user else None,
            "DISPATCH",
            "ambulance_dispatch",
            str(dispatch_id),
            {
                "ambulance_id": ambulance_id,
                "vehicle": amb["vehicle_number"],
                "pickup": pickup_address,
                "eta_min": route_info["eta_minutes"],
                "distance_km": route_info["distance_km"],
            },
        )
        conn.execute("COMMIT")
    except Exception as exc:
        conn.execute("ROLLBACK")
        raise exc

    row = conn.execute("SELECT * FROM ambulance_dispatches WHERE id=?", (dispatch_id,)).fetchone()
    res = dict(row)
    res["route_info"] = route_info
    return res


def list_dispatches(
    conn: sqlite3.Connection,
    status: Optional[str] = None,
    ambulance_id: Optional[int] = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """List ambulance dispatches with joined details."""
    q = """SELECT d.*, a.vehicle_number, a.driver_name, a.driver_phone, a.lat AS amb_lat, a.lng AS amb_lng,
                  p.patient_id AS patient_code, p.first_name, p.last_name, dept.name AS dept_name
           FROM ambulance_dispatches d
           JOIN ambulances a ON a.id = d.ambulance_id
           LEFT JOIN patients p ON p.id = d.patient_id
           LEFT JOIN departments dept ON dept.id = d.destination_dept_id
           WHERE 1=1"""
    params: list[Any] = []

    if status:
        q += " AND d.status = ?"
        params.append(status)
    if ambulance_id:
        q += " AND d.ambulance_id = ?"
        params.append(int(ambulance_id))

    q += " ORDER BY d.id DESC LIMIT ?"
    params.append(limit)

    rows = conn.execute(q, params).fetchall()
    return [dict(r) for r in rows]


def update_dispatch_status(
    conn: sqlite3.Connection,
    user: Optional[dict[str, Any]],
    dispatch_id: int,
    new_status: str,
    current_lat: Optional[float] = None,
    current_lng: Optional[float] = None,
) -> dict[str, Any]:
    """
    Update status of an active ambulance dispatch.
    Statuses: Dispatched -> En Route to Scene -> On Scene -> Transporting -> Arrived at ED -> Completed
    """
    require_role(user, ["Admin", "Doctor", "Nurse"])
    disp = conn.execute("SELECT * FROM ambulance_dispatches WHERE id=?", (int(dispatch_id),)).fetchone()
    if not disp:
        raise ValueError(f"Dispatch ID {dispatch_id} not found")

    amb_id = int(disp["ambulance_id"])

    try:
        conn.execute("BEGIN IMMEDIATE")
        completed_at = _now_iso() if new_status in ("Completed", "Arrived at ED") else None

        conn.execute(
            "UPDATE ambulance_dispatches SET status=?, completed_at=COALESCE(?, completed_at) WHERE id=?",
            (new_status, completed_at, int(dispatch_id)),
        )

        # Update associated ambulance status
        if new_status in ("Completed", "Arrived at ED"):
            conn.execute(
                "UPDATE ambulances SET status='Available', current_location='Base Station', lat=?, lng=? WHERE id=?",
                (current_lat or HOSPITAL_LAT, current_lng or HOSPITAL_LNG, amb_id),
            )
        else:
            amb_stat = "On Call" if new_status != "Dispatched" else "Dispatched"
            if current_lat is not None and current_lng is not None:
                conn.execute(
                    "UPDATE ambulances SET status=?, lat=?, lng=? WHERE id=?",
                    (amb_stat, float(current_lat), float(current_lng), amb_id),
                )
            else:
                conn.execute("UPDATE ambulances SET status=? WHERE id=?", (amb_stat, amb_id))

        log_action(
            conn,
            int(user["id"]) if user else None,
            user.get("role") if user else None,
            "UPDATE_STATUS",
            "ambulance_dispatch",
            str(dispatch_id),
            {"old_status": disp["status"], "new_status": new_status},
        )
        conn.execute("COMMIT")
    except Exception as exc:
        conn.execute("ROLLBACK")
        raise exc

    updated = conn.execute("SELECT * FROM ambulance_dispatches WHERE id=?", (int(dispatch_id),)).fetchone()
    return dict(updated)
