"""Auth helpers: password hashing, RBAC decorators, audit logging."""
import hashlib
from functools import wraps

from flask import jsonify, session

STAFF_ROLES = ("admin", "district_officer", "state_officer")
OFFICER_ROLES = ("admin", "district_officer", "state_officer")


def hash_password(p: str) -> str:
    return hashlib.sha256(p.encode()).hexdigest()


def log_audit(conn, action, detail, user_id=None, username=None):
    conn.execute(
        "INSERT INTO audit_log (user_id, username, action, detail, state_id, district_id)"
        " VALUES (?,?,?,?,?,?)",
        (
            user_id,
            username or session.get("username"),
            action,
            detail,
            session.get("state_id"),
            session.get("district_id"),
        ),
    )


def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user_id" not in session:
            return jsonify({"error": "Not authenticated"}), 401
        return f(*args, **kwargs)

    return decorated


def role_required(*roles):
    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            role = (session.get("role") or "").lower()
            if not role:
                return jsonify({"error": "Unauthorized"}), 403
            wanted = [r.lower() for r in roles]
            if role == "admin":
                return f(*args, **kwargs)
            if role not in wanted:
                return jsonify({"error": "Forbidden for role: " + role}), 403
            return f(*args, **kwargs)

        return decorated

    return decorator


def staff_only(f):
    return role_required(*STAFF_ROLES)(f)
