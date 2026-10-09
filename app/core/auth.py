from __future__ import annotations

import json
import sqlite3
from typing import Any, Optional

try:
    from passlib.context import CryptContext
    _PWD_CONTEXT = CryptContext(schemes=["bcrypt"], deprecated="auto", bcrypt__rounds=10)
    _HAS_BCRYPT = True
except Exception:  # pragma: no cover - fallback for environments without bcrypt
    _PWD_CONTEXT = None
    _HAS_BCRYPT = False
    import hashlib
    import os


def hash_password(password: str) -> str:
    """Hash a password using bcrypt (or PBKDF2 fallback) and return the stored hash."""
    if _HAS_BCRYPT and _PWD_CONTEXT is not None:
        return _PWD_CONTEXT.hash(password)
    salt = os.urandom(16).hex()
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 100_000).hex()
    return f"pbkdf2_sha256$100000${salt}${digest}"


def verify_password(password: str, stored_hash: str) -> bool:
    """Verify a password against a stored hash."""
    if not stored_hash or not password:
        return False
    if _HAS_BCRYPT and _PWD_CONTEXT is not None and stored_hash.startswith("$2"):
        try:
            return _PWD_CONTEXT.verify(password, stored_hash)
        except Exception:
            return False
    if stored_hash.startswith("pbkdf2_sha256$"):
        try:
            _, iterations, salt, digest = stored_hash.split("$", 3)
            import hashlib
            computed = hashlib.pbkdf2_hmac(
                "sha256", password.encode("utf-8"), salt.encode("utf-8"), int(iterations)
            ).hex()
            return computed == digest
        except Exception:
            return False
    return False


def _now() -> str:
    import datetime as _dt
    return _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def create_user(
    conn: sqlite3.Connection,
    username: str,
    password: str,
    role: str,
    full_name: str,
    email: Optional[str] = None,
    department_id: Optional[int] = None,
    actor_id: Optional[int] = None,
) -> int:
    """Create a user with a hashed password and audit the action. Returns new user id."""
    from .audit import log_action
    if not username or not password or not role or not full_name:
        raise ValueError("username, password, role, full_name are required")
    if len(password) < 6:
        raise ValueError("password must be at least 6 characters")
    role = role.strip()
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM roles WHERE role_name = ?", (role,))
    if not cur.fetchone():
        conn.execute("INSERT OR IGNORE INTO roles(role_name, description) VALUES(?,?)", (role, f"Role {role}"))
    existing = conn.execute("SELECT id FROM users WHERE username = ?", (username,)).fetchone()
    if existing:
        raise ValueError(f"Username '{username}' already exists")
    pw_hash = hash_password(password)
    cur.execute(
        """INSERT INTO users(username,password_hash,role,full_name,email,department_id,created_at)
           VALUES(?,?,?,?,?,?,?)""",
        (username, pw_hash, role, full_name, email, department_id, _now()),
    )
    new_id = cur.lastrowid
    log_action(
        conn, actor_id, role if actor_id is None else None,
        "CREATE", "user", str(new_id),
        {"username": username, "role": role, "full_name": full_name},
    )
    return new_id


def ensure_roles(conn: sqlite3.Connection, roles: list[str]) -> None:
    with conn:
        for r in roles:
            conn.execute("INSERT OR IGNORE INTO roles(role_name, description) VALUES(?,?)", (r, f"{r} role"))


def ensure_demo_users(conn: sqlite3.Connection, demo_users: list[dict[str, Any]]) -> None:
    """Idempotently create 5 demo users (only if they do not already exist)."""
    for u in demo_users:
        row = conn.execute("SELECT id FROM users WHERE username = ?", (u["username"],)).fetchone()
        if row:
            continue
        create_user(
            conn,
            username=u["username"],
            password=u["password"],
            role=u["role"],
            full_name=u["full_name"],
            email=u.get("email"),
            department_id=u.get("department_id"),
            actor_id=None,
        )


def authenticate(conn: sqlite3.Connection, username: str, password: str) -> Optional[dict[str, Any]]:
    """Verify credentials. Returns user dict on success, else None. Audits login attempts."""
    from .audit import log_action
    row = conn.execute(
        "SELECT id,username,password_hash,role,full_name,email,department_id FROM users WHERE username=?",
        (username,),
    ).fetchone()
    if not row:
        return None
    ok = verify_password(password, row["password_hash"])
    if not ok:
        log_action(conn, row["id"], row["role"], "LOGIN_FAILURE", "user", str(row["id"]), {"username": username})
        return None
    user = {k: row[k] for k in row.keys() if k != "password_hash"}
    log_action(conn, user["id"], user["role"], "LOGIN_SUCCESS", "user", str(user["id"]), {"username": username})
    return user


def get_user_by_id(conn: sqlite3.Connection, user_id: int) -> Optional[dict[str, Any]]:
    row = conn.execute(
        "SELECT id,username,role,full_name,email,department_id,created_at FROM users WHERE id=?",
        (user_id,),
    ).fetchone()
    return dict(row) if row else None


def get_patient_user_link(conn: sqlite3.Connection, user_id: int) -> Optional[int]:
    """Return patient.id for a user linked to a Patient role account, or None."""
    row = conn.execute("SELECT id FROM patients WHERE user_id = ?", (user_id,)).fetchone()
    return int(row["id"]) if row else None


def logout(conn: sqlite3.Connection, user: dict[str, Any]) -> None:
    from .audit import log_action
    log_action(conn, user["id"], user["role"], "LOGOUT", "user", str(user["id"]), {"username": user.get("username")})


def list_users(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT id,username,role,full_name,email,department_id,created_at FROM users ORDER BY id"
    ).fetchall()
    return [dict(r) for r in rows]


def change_password(conn: sqlite3.Connection, user_id: int, old_pw: str, new_pw: str) -> bool:
    row = conn.execute("SELECT password_hash FROM users WHERE id=?", (user_id,)).fetchone()
    if not row or not verify_password(old_pw, row["password_hash"]):
        return False
    conn.execute("UPDATE users SET password_hash=? WHERE id=?", (hash_password(new_pw), user_id))
    from .audit import log_action
    log_action(conn, user_id, None, "CHANGE_PASSWORD", "user", str(user_id), {"length": len(new_pw)})
    return True
