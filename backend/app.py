"""PHC Medicine Inventory — Federated Health Supply-Chain Command Center (Flask JSON API).

Scoping model (scope_clause / geo_scope):
    admin          -> no restriction (India-wide)
    state_officer  -> own state
    district_officer -> own district
    phc_manager    -> own PHC only
Query params (state_id, district_id, phc_id) drill down further but can never
widen a caller's scope — anything outside it is a 403.
"""
import os
from datetime import date, timedelta

from flask import Flask, abort, jsonify, request, send_from_directory, session

import db as database
import forecast
import stock
import upload as uploader
from auth import OFFICER_ROLES, hash_password, log_audit, login_required, role_required
import federated as federation
from federated import FEDERATED_DEMO

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DIST_DIR = os.path.join(BASE_DIR, "..", "frontend", "dist")

app = Flask(__name__, static_folder=None)
app.secret_key = os.environ.get("SECRET_KEY", "phc-inventory-secret-2026")
app.config.update(SESSION_COOKIE_SAMESITE="Lax", SESSION_COOKIE_HTTPONLY=True)

EDITOR_ROLES = ("district_officer", "state_officer", "phc_manager")

# Seed the database at import time so gunicorn (which imports this module
# instead of running it as __main__) also gets schema + seed data.
# bootstrap() is idempotent: CREATE IF NOT EXISTS + seed only when empty.
database.bootstrap()


def get_db():
    return database.get_db()


@app.errorhandler(403)
def _forbidden(e):
    return jsonify({"error": getattr(e, "description", "Forbidden")}), 403


# ============================== Scoping ==============================

def session_scope():
    """Restriction implied by the caller's role alone (no query params).

    A 0 sentinel means "matches nothing" — used when an account is missing its
    state/district/PHC assignment rather than accidentally falling open.
    """
    role = session.get("role")
    if role == "state_officer":
        return {"state_id": session.get("state_id") or 0}
    if role == "district_officer":
        return {"district_id": session.get("district_id") or 0}
    if role == "phc_manager":
        return {"phc_id": session.get("phc_id") or 0}
    return {}


def geo_scope(conn):
    """Merge the role scope with drill-down query params, validating that the
    requested geography is inside the caller's scope."""
    own = session_scope()
    wanted = {}
    for key in ("state_id", "district_id", "phc_id"):
        val = request.args.get(key, type=int)
        if val:
            wanted[key] = val

    for key, val in wanted.items():
        if key in own and own[key] != val:
            abort(403, description=f"{key}={val} is outside your scope")

    if "phc_id" in wanted and "phc_id" not in own:
        row = conn.execute(
            "SELECT state_id, district_id FROM phc WHERE phc_id = ?", (wanted["phc_id"],)
        ).fetchone()
        if not row:
            abort(403, description=f"phc_id={wanted['phc_id']} does not exist")
        if own.get("state_id") and row["state_id"] != own["state_id"]:
            abort(403, description="PHC is outside your state")
        if own.get("district_id") and row["district_id"] != own["district_id"]:
            abort(403, description="PHC is outside your district")

    if "district_id" in wanted and "district_id" not in own:
        row = conn.execute(
            "SELECT state_id FROM district WHERE district_id = ?", (wanted["district_id"],)
        ).fetchone()
        if not row:
            abort(403, description=f"district_id={wanted['district_id']} does not exist")
        if own.get("state_id") and row["state_id"] != own["state_id"]:
            abort(403, description="District is outside your state")
        if own.get("phc_id"):
            abort(403, description="PHC in-charges cannot select a district")

    if "state_id" in wanted and "state_id" not in own:
        if own.get("district_id"):
            row = conn.execute(
                "SELECT state_id FROM district WHERE district_id = ?", (own["district_id"],)
            ).fetchone()
            if not row or row["state_id"] != wanted["state_id"]:
                abort(403, description="State is outside your scope")
        elif own.get("phc_id"):
            row = conn.execute(
                "SELECT state_id FROM phc WHERE phc_id = ?", (own["phc_id"],)
            ).fetchone()
            if not row or row["state_id"] != wanted["state_id"]:
                abort(403, description="State is outside your scope")

    return {**own, **wanted}


def scope_clause(filters, alias="p"):
    """SQL fragment restricting a query joined to the `phc` table (alias)."""
    sql, params = "", []
    if filters.get("state_id") is not None:
        sql += f" AND {alias}.state_id = ?"
        params.append(filters["state_id"])
    if filters.get("district_id") is not None:
        sql += f" AND {alias}.district_id = ?"
        params.append(filters["district_id"])
    if filters.get("phc_id") is not None:
        sql += f" AND {alias}.phc_id = ?"
        params.append(filters["phc_id"])
    return sql, tuple(params)


def scope_level(filters):
    if filters.get("phc_id") is not None:
        return "phc"
    if filters.get("district_id") is not None:
        return "district"
    if filters.get("state_id") is not None:
        return "state"
    return "country"


def _in_scope(conn, phc_id):
    """True when the PHC row is visible to the caller."""
    row = conn.execute("SELECT state_id, district_id FROM phc WHERE phc_id = ?", (phc_id,)).fetchone()
    if not row:
        return False
    own = session_scope()
    if not own:
        return True
    if "phc_id" in own:
        return own["phc_id"] == phc_id
    if "district_id" in own:
        return own["district_id"] == row["district_id"]
    return own.get("state_id") == row["state_id"]


# ============================== Auth ==============================

@app.post("/api/login")
def api_login():
    data = request.get_json(silent=True) or {}
    username = (data.get("username") or "").strip()
    password = (data.get("password") or "").strip()
    if not username or not password:
        return jsonify({"error": "Username and password required"}), 400

    conn = get_db()
    user = conn.execute(
        "SELECT * FROM users WHERE username = ? AND is_active = 1", (username,)
    ).fetchone()
    if not user or user["password_hash"] != hash_password(password):
        conn.close()
        return jsonify({"error": "Invalid username or password"}), 401

    session.clear()
    session["user_id"] = user["id"]
    session["username"] = user["username"]
    session["full_name"] = user["full_name"]
    session["role"] = user["role"]
    session["phc_id"] = user["phc_id"]
    session["state_id"] = user["state_id"]
    session["district_id"] = user["district_id"]
    log_audit(conn, "login", f'{user["role"]} logged in', user["id"], user["username"])
    conn.commit()
    conn.close()
    return jsonify({"status": "ok", "user": _user_payload(user)})


@app.post("/api/logout")
def api_logout():
    conn = get_db()
    if "user_id" in session:
        log_audit(conn, "logout", "User logged out", session.get("user_id"))
        conn.commit()
    conn.close()
    session.clear()
    return jsonify({"status": "ok"})


@app.get("/api/me")
def api_me():
    if "user_id" not in session:
        return jsonify({"user": None}), 401
    conn = get_db()
    user = conn.execute("SELECT * FROM users WHERE id = ?", (session["user_id"],)).fetchone()
    conn.close()
    if not user:
        session.clear()
        return jsonify({"user": None}), 401
    return jsonify({"user": _user_payload(user)})


def _user_payload(user):
    conn = get_db()
    state_name = district_name = None
    if user["state_id"]:
        row = conn.execute("SELECT name FROM state WHERE state_id = ?", (user["state_id"],)).fetchone()
        state_name = row["name"] if row else None
    if user["district_id"]:
        row = conn.execute("SELECT name FROM district WHERE district_id = ?", (user["district_id"],)).fetchone()
        district_name = row["name"] if row else None
    phc_name = None
    if user["phc_id"]:
        row = conn.execute("SELECT name FROM phc WHERE phc_id = ?", (user["phc_id"],)).fetchone()
        phc_name = row["name"] if row else None
    conn.close()
    return {
        "id": user["id"],
        "username": user["username"],
        "full_name": user["full_name"],
        "role": user["role"],
        "phc_id": user["phc_id"],
        "phc_name": phc_name,
        "state_id": user["state_id"],
        "state_name": state_name,
        "district_id": user["district_id"],
        "district_name": district_name,
    }


# ============================== Geography ==============================

@app.get("/api/geography")
@login_required
def api_geography():
    conn = get_db()
    own = session_scope()
    state_f = own.get("state_id")
    district_f = own.get("district_id")
    phc_f = own.get("phc_id")
    if phc_f:
        row = conn.execute(
            "SELECT state_id, district_id FROM phc WHERE phc_id = ?", (phc_f,)
        ).fetchone()
        if row:
            state_f, district_f = row["state_id"], row["district_id"]
    elif district_f and state_f is None:
        row = conn.execute(
            "SELECT state_id FROM district WHERE district_id = ?", (district_f,)
        ).fetchone()
        if row:
            state_f = row["state_id"]

    states = conn.execute(
        """
        SELECT s.state_id, s.name, s.code,
               (SELECT COUNT(*) FROM district d WHERE d.state_id = s.state_id) AS districts,
               (SELECT COUNT(*) FROM phc p WHERE p.state_id = s.state_id) AS phcs
        FROM state s
        WHERE ? IS NULL OR s.state_id = ?
        ORDER BY s.name
        """,
        (state_f, state_f),
    ).fetchall()

    out = []
    for s in states:
        districts = conn.execute(
            """
            SELECT d.district_id, d.name,
                   (SELECT COUNT(*) FROM phc p WHERE p.district_id = d.district_id) AS phcs
            FROM district d
            WHERE d.state_id = ? AND (? IS NULL OR d.district_id = ?)
            ORDER BY d.name
            """,
            (s["state_id"], district_f, district_f),
        ).fetchall()
        ds = []
        for d in districts:
            phcs = conn.execute(
                "SELECT phc_id, name FROM phc WHERE district_id = ?"
                " AND (? IS NULL OR phc_id = ?) ORDER BY name",
                (d["district_id"], phc_f, phc_f),
            ).fetchall()
            ds.append(
                {
                    "district_id": d["district_id"],
                    "name": d["name"],
                    "phcs": d["phcs"],
                    "facilities": [dict(p) for p in phcs],
                }
            )
        out.append(
            {
                "state_id": s["state_id"],
                "name": s["name"],
                "code": s["code"],
                "districts": ds,
            }
        )
    conn.close()
    return jsonify(
        {
            "states": out,
            "level": scope_level(own),
            "scope": {"state_id": state_f, "district_id": district_f, "phc_id": phc_f},
        }
    )


# ============================== Overview ==============================

@app.get("/api/overview")
@login_required
def api_overview():
    conn = get_db()
    filters = geo_scope(conn)
    clause, params = scope_clause(filters)
    level = scope_level(filters)

    stats = stock.summary_stats(conn, clause, params)
    stats.update(_capacity_stats(conn, clause, params))
    children = _rollup(conn, level, clause, params)
    crumbs, geo_names = _breadcrumb(conn, filters)

    q = f"""
        SELECT a.id, a.alert_type, a.severity, a.days_of_stock, a.message, a.status,
               a.created_at, p.name AS phc_name, m.name AS medicine, m.unit
        FROM alerts a
        JOIN phc p ON p.phc_id = a.phc_id
        JOIN medicine m ON m.medicine_id = a.medicine_id
        WHERE a.status IN ('open','acknowledged') {clause}
    """
    order = ("CASE a.severity WHEN 'stock_out' THEN 0 WHEN 'critical' THEN 1"
             " WHEN 'forecast_risk' THEN 2 ELSE 3 END, a.days_of_stock ASC")
    alerts = [dict(r) for r in conn.execute(q + f" ORDER BY {order} LIMIT 8", params)]

    by_severity = _alert_counts(conn, clause, params)
    settings = forecast.get_settings(conn)
    top_risks = [
        {k: r[k] for k in ("phc_name", "medicine", "days_to_stockout", "stockout_date", "r2", "stock_qty")}
        for r in forecast.compute_forecasts(conn, clause, params, limit=8)
    ]
    generated_at = conn.execute("SELECT CURRENT_TIMESTAMP AS ts").fetchone()["ts"]
    conn.close()

    return jsonify(
        {
            "level": level,
            "geo": filters,
            "geo_names": geo_names,
            "breadcrumb": crumbs,
            "stats": stats,
            "children": children,
            "top_alerts": alerts,
            "alerts_by_severity": by_severity,
            "forecast": {
                "top_risks": top_risks,
                "models": forecast.models_trained(),
                "settings": settings,
            },
            "generated_at": generated_at,
        }
    )


def _rollup(conn, level, clause, params):
    """Aggregate inventory to the level *below* the current one."""
    if level == "country":
        idc, nc, join, extra = "p.state_id", "s.name", " JOIN state s ON s.state_id = p.state_id", ", s.code AS code"
    elif level == "state":
        idc, nc, join, extra = "p.district_id", "d.name", " JOIN district d ON d.district_id = p.district_id", ""
    else:
        idc, nc, join, extra = (
            "p.phc_id", "p.name", "",
            ", p.block AS block, p.beds AS beds, p.state_id, p.district_id",
        )
    q = f"""
        SELECT {idc} AS id, {nc} AS name{extra},
               COUNT(DISTINCT p.phc_id) AS phcs,
               COUNT(i.id) AS lines,
               SUM(CASE WHEN i.stock_qty <= 0 THEN 1 ELSE 0 END) AS stock_out,
               SUM(CASE WHEN i.stock_qty > 0 AND i.avg_daily_consumption > 0
                         AND i.stock_qty / i.avg_daily_consumption < ? THEN 1 ELSE 0 END) AS critical,
               SUM(CASE WHEN i.stock_qty > 0 AND i.avg_daily_consumption > 0
                         AND i.stock_qty / i.avg_daily_consumption >= ?
                         AND i.stock_qty / i.avg_daily_consumption < ? THEN 1 ELSE 0 END) AS low,
               AVG(CASE WHEN i.avg_daily_consumption > 0
                        THEN i.stock_qty / i.avg_daily_consumption END) AS avg_days
        FROM inventory i
        JOIN phc p ON p.phc_id = i.phc_id{join}
        WHERE 1=1 {clause}
        GROUP BY {idc}
        ORDER BY {nc}
    """
    args = (stock.CRITICAL_DAYS, stock.CRITICAL_DAYS, stock.LOW_DAYS) + tuple(params)
    rows = []
    for r in conn.execute(q, args):
        item = dict(r)
        item["avg_days"] = round(item["avg_days"], 1) if item["avg_days"] is not None else None
        rows.append(item)
    return rows


def _breadcrumb(conn, filters):
    """Full path from India down to the current node, whatever level was requested."""
    state_id = filters.get("state_id")
    district_id = filters.get("district_id")
    phc_id = filters.get("phc_id")
    names = {"state": None, "district": None, "phc": None}

    if phc_id:
        row = conn.execute(
            "SELECT name, district_id, state_id FROM phc WHERE phc_id = ?", (phc_id,)
        ).fetchone()
        if row:
            names["phc"] = row["name"]
            state_id = state_id or row["state_id"]
            district_id = district_id or row["district_id"]
    if district_id:
        row = conn.execute(
            "SELECT name, state_id FROM district WHERE district_id = ?", (district_id,)
        ).fetchone()
        if row:
            names["district"] = row["name"]
            state_id = state_id or row["state_id"]
    if state_id:
        row = conn.execute("SELECT name FROM state WHERE state_id = ?", (state_id,)).fetchone()
        names["state"] = row["name"] if row else None

    crumbs = [{"level": "country", "label": "India", "params": {}}]
    if state_id:
        crumbs.append({"level": "state", "label": names["state"] or "State",
                       "params": {"state_id": state_id}})
    if district_id:
        crumbs.append({"level": "district", "label": names["district"] or "District",
                       "params": {"state_id": state_id, "district_id": district_id}})
    if phc_id:
        crumbs.append({"level": "phc", "label": names["phc"] or "PHC",
                       "params": {"phc_id": phc_id}})
    return crumbs, names


def _alert_counts(conn, clause, params):
    q = f"SELECT severity, COUNT(*) AS n FROM alerts a JOIN phc p ON p.phc_id = a.phc_id" \
        f" WHERE a.status IN ('open','acknowledged') {clause} GROUP BY severity"
    out = {"stock_out": 0, "critical": 0, "low": 0, "forecast_risk": 0}
    for r in conn.execute(q, params):
        out[r["severity"]] = r["n"]
    return out


def _pct(part, whole):
    return round(100.0 * part / whole, 1) if whole else 0.0


def _capacity_stats(conn, clause, params):
    """Bed + staffing KPIs for the current scope (aggregate rows only)."""
    today = date.today().isoformat()
    beds = conn.execute(
        f"""
        SELECT COALESCE(SUM(b.total), 0) AS total, COALESCE(SUM(b.occupied), 0) AS occupied
        FROM bed_capacity b
        JOIN phc p ON p.phc_id = b.phc_id
        WHERE 1=1 {clause}
        """,
        params,
    ).fetchone()
    staff = conn.execute(
        f"""
        SELECT COALESCE(SUM(s.staff), 0) AS staff, COALESCE(SUM(s.present), 0) AS present,
               COALESCE(SUM(s.on_leave), 0) AS on_leave
        FROM staff_attendance s
        JOIN phc p ON p.phc_id = s.phc_id
        WHERE s.duty_date = ? {clause}
        """,
        (today, *params),
    ).fetchone()
    return {
        "beds_total": beds["total"],
        "beds_occupied": beds["occupied"],
        "beds_available": beds["total"] - beds["occupied"],
        "beds_occupancy_pct": _pct(beds["occupied"], beds["total"]),
        "staff_total": staff["staff"],
        "staff_present": staff["present"],
        "staff_on_leave": staff["on_leave"],
        "staff_present_pct": _pct(staff["present"], staff["staff"]),
    }


# ============================== Beds & Staff ==============================

@app.get("/api/beds")
@login_required
def api_beds():
    conn = get_db()
    clause, params = scope_clause(geo_scope(conn))
    rows = conn.execute(
        f"""
        SELECT b.id, b.phc_id, b.bed_type, b.total, b.occupied, b.updated_at,
               p.name AS phc_name, p.block, p.state_id, p.district_id,
               s.name AS state_name, d.name AS district_name
        FROM bed_capacity b
        JOIN phc p ON p.phc_id = b.phc_id
        JOIN state s ON s.state_id = p.state_id
        JOIN district d ON d.district_id = p.district_id
        WHERE 1=1 {clause}
        ORDER BY p.name, b.bed_type
        """,
        params,
    ).fetchall()
    generated_at = conn.execute("SELECT CURRENT_TIMESTAMP AS ts").fetchone()["ts"]
    conn.close()

    by_phc, order = {}, []
    for r in rows:
        item = dict(r)
        entry = by_phc.get(item["phc_id"])
        if entry is None:
            entry = {
                "phc_id": item["phc_id"],
                "phc_name": item["phc_name"],
                "block": item["block"],
                "state_name": item["state_name"],
                "district_name": item["district_name"],
                "total": 0,
                "occupied": 0,
                "types": [],
            }
            by_phc[item["phc_id"]] = entry
            order.append(entry)
        entry["types"].append(
            {"id": item["id"], "bed_type": item["bed_type"],
             "total": item["total"], "occupied": item["occupied"]}
        )
        entry["total"] += item["total"]
        entry["occupied"] += item["occupied"]

    for e in order:
        e["available"] = e["total"] - e["occupied"]
        e["occupancy_pct"] = _pct(e["occupied"], e["total"])
    total = sum(e["total"] for e in order)
    occupied = sum(e["occupied"] for e in order)
    return jsonify(
        {
            "beds": order,
            "summary": {
                "phcs": len(order),
                "total": total,
                "occupied": occupied,
                "available": total - occupied,
                "occupancy_pct": _pct(occupied, total),
            },
            "generated_at": generated_at,
        }
    )


@app.post("/api/beds/<int:phc_id>")
@login_required
@role_required(*EDITOR_ROLES)
def api_update_beds(phc_id):
    """Update occupied counts for one bed type — aggregate capacity, no patient data."""
    data = request.get_json(silent=True) or {}
    bed_type = (data.get("bed_type") or "").strip()
    if not bed_type:
        return jsonify({"error": "bed_type required"}), 400
    try:
        occupied = int(data.get("occupied"))
    except (TypeError, ValueError):
        return jsonify({"error": "occupied must be an integer"}), 400

    conn = get_db()
    if not _in_scope(conn, phc_id):
        conn.close()
        return jsonify({"error": "Forbidden"}), 403
    row = conn.execute(
        "SELECT id, total, occupied FROM bed_capacity WHERE phc_id = ? AND bed_type = ?",
        (phc_id, bed_type),
    ).fetchone()
    if not row:
        conn.close()
        return jsonify({"error": "Bed type not found for this PHC"}), 404
    if occupied < 0 or occupied > row["total"]:
        conn.close()
        return jsonify({"error": f"occupied must be between 0 and {row['total']}"}), 400

    conn.execute(
        "UPDATE bed_capacity SET occupied = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
        (occupied, row["id"]),
    )
    log_audit(conn, "bed_update",
              f"Bed capacity at PHC {phc_id}: {bed_type} {row['occupied']} -> {occupied} of {row['total']}")
    conn.commit()
    conn.close()
    return jsonify({"status": "ok", "occupancy_pct": _pct(occupied, row["total"])})


@app.get("/api/staff")
@login_required
def api_staff():
    conn = get_db()
    clause, params = scope_clause(geo_scope(conn))
    days = [(date.today() - timedelta(days=i)).isoformat() for i in range(6, -1, -1)]
    start, end = days[0], days[-1]
    rows = conn.execute(
        f"""
        SELECT s.id, s.phc_id, s.staff_role, s.duty_date, s.staff, s.present, s.on_leave,
               p.name AS phc_name, p.block, st.name AS state_name, dd.name AS district_name
        FROM staff_attendance s
        JOIN phc p ON p.phc_id = s.phc_id
        JOIN state st ON st.state_id = p.state_id
        JOIN district dd ON dd.district_id = p.district_id
        WHERE s.duty_date BETWEEN ? AND ? {clause}
        """,
        (start, end, *params),
    ).fetchall()
    generated_at = conn.execute("SELECT CURRENT_TIMESTAMP AS ts").fetchone()["ts"]
    conn.close()

    trend_map = {d: {"duty_date": d, "staff": 0, "present": 0, "on_leave": 0} for d in days}
    phc_map, phc_order = {}, []
    for r in rows:
        item = dict(r)
        t = trend_map[item["duty_date"]]
        t["staff"] += item["staff"]
        t["present"] += item["present"]
        t["on_leave"] += item["on_leave"]
        if item["duty_date"] != end:
            continue
        entry = phc_map.get(item["phc_id"])
        if entry is None:
            entry = {
                "phc_id": item["phc_id"],
                "phc_name": item["phc_name"],
                "block": item["block"],
                "state_name": item["state_name"],
                "district_name": item["district_name"],
                "staff": 0, "present": 0, "on_leave": 0, "roles": [],
            }
            phc_map[item["phc_id"]] = entry
            phc_order.append(entry)
        entry["staff"] += item["staff"]
        entry["present"] += item["present"]
        entry["on_leave"] += item["on_leave"]
        entry["roles"].append(
            {"id": item["id"], "staff_role": item["staff_role"],
             "staff": item["staff"], "present": item["present"], "on_leave": item["on_leave"]}
        )

    for e in phc_order:
        e["absent"] = e["staff"] - e["present"] - e["on_leave"]
        e["present_pct"] = _pct(e["present"], e["staff"])
    for t in trend_map.values():
        t["present_pct"] = _pct(t["present"], t["staff"])

    staff_total = sum(e["staff"] for e in phc_order)
    staff_present = sum(e["present"] for e in phc_order)
    staff_leave = sum(e["on_leave"] for e in phc_order)
    return jsonify(
        {
            "today": phc_order,
            "trend": list(trend_map.values()),
            "days": days,
            "summary": {
                "phcs": len(phc_order),
                "staff": staff_total,
                "present": staff_present,
                "on_leave": staff_leave,
                "absent": staff_total - staff_present - staff_leave,
                "present_pct": _pct(staff_present, staff_total),
            },
            "generated_at": generated_at,
        }
    )


@app.post("/api/staff")
@login_required
@role_required(*EDITOR_ROLES)
def api_update_staff():
    """Mark today's attendance for one role at one PHC."""
    data = request.get_json(silent=True) or {}
    phc_id = data.get("phc_id")
    role = (data.get("staff_role") or "").strip()
    if not phc_id or not role:
        return jsonify({"error": "phc_id and staff_role required"}), 400
    try:
        present = int(data.get("present"))
        on_leave = int(data.get("on_leave", 0))
    except (TypeError, ValueError):
        return jsonify({"error": "present and on_leave must be integers"}), 400

    conn = get_db()
    if not _in_scope(conn, int(phc_id)):
        conn.close()
        return jsonify({"error": "Forbidden"}), 403
    row = conn.execute(
        "SELECT id, staff, present FROM staff_attendance WHERE phc_id = ? AND staff_role = ? AND duty_date = ?",
        (int(phc_id), role, date.today().isoformat()),
    ).fetchone()
    if not row:
        conn.close()
        return jsonify({"error": "No attendance row for today"}), 404
    if present < 0 or on_leave < 0 or present + on_leave > row["staff"]:
        conn.close()
        return jsonify({"error": f"present + on_leave must be between 0 and {row['staff']}"}), 400

    conn.execute(
        "UPDATE staff_attendance SET present = ?, on_leave = ? WHERE id = ?",
        (present, on_leave, row["id"]),
    )
    log_audit(conn, "attendance_update",
              f"Attendance at PHC {phc_id} / {role}: present {row['present']} -> {present}")
    conn.commit()
    conn.close()
    return jsonify({"status": "ok"})


# ============================== PHCs ==============================

def _phc_rollup(conn, clause, params):
    q = f"""
        SELECT p.phc_id, p.name, p.block, p.beds, p.state_id, p.district_id,
               s.name AS state_name, d.name AS district_name,
               COUNT(i.id) AS lines,
               SUM(CASE WHEN i.stock_qty <= 0 THEN 1 ELSE 0 END) AS stock_out,
               SUM(CASE WHEN i.stock_qty > 0 AND i.avg_daily_consumption > 0
                         AND i.stock_qty / i.avg_daily_consumption < ? THEN 1 ELSE 0 END) AS critical,
               SUM(CASE WHEN i.stock_qty > 0 AND i.avg_daily_consumption > 0
                         AND i.stock_qty / i.avg_daily_consumption >= ?
                         AND i.stock_qty / i.avg_daily_consumption < ? THEN 1 ELSE 0 END) AS low,
               AVG(CASE WHEN i.avg_daily_consumption > 0
                        THEN i.stock_qty / i.avg_daily_consumption END) AS avg_days
        FROM phc p
        JOIN state s ON s.state_id = p.state_id
        JOIN district d ON d.district_id = p.district_id
        LEFT JOIN inventory i ON i.phc_id = p.phc_id
        WHERE 1=1 {clause}
        GROUP BY p.phc_id ORDER BY p.name
    """
    args = (stock.CRITICAL_DAYS, stock.CRITICAL_DAYS, stock.LOW_DAYS) + tuple(params)
    rows = []
    for r in conn.execute(q, args):
        item = dict(r)
        item["avg_days"] = round(item["avg_days"], 1) if item["avg_days"] is not None else None
        rows.append(item)
    return rows


@app.get("/api/phcs")
@login_required
def api_phcs():
    conn = get_db()
    clause, params = scope_clause(geo_scope(conn))
    rows = _phc_rollup(conn, clause, params)
    conn.close()
    return jsonify({"phcs": rows})


@app.get("/api/phcs/<int:phc_id>")
@login_required
def api_phc_detail(phc_id):
    conn = get_db()
    if not _in_scope(conn, phc_id):
        conn.close()
        return jsonify({"error": "Forbidden"}), 403
    phc = conn.execute("SELECT * FROM phc WHERE phc_id = ?", (phc_id,)).fetchone()
    if not phc:
        conn.close()
        return jsonify({"error": "PHC not found"}), 404
    lines = _inventory_rows(conn, " AND i.phc_id = ?", (phc_id,), {})
    conn.close()
    return jsonify({"phc": dict(phc), "inventory": lines})


# ============================== Inventory ==============================

def _inventory_rows(conn, clause, params, filters):
    q = f"""
        SELECT i.id, i.phc_id, p.name AS phc_name, p.block, p.state_id, p.district_id,
               s.name AS state_name, d.name AS district_name,
               i.medicine_id, m.name AS medicine, m.category, m.unit, m.essential,
               i.stock_qty, i.avg_daily_consumption, i.updated_at
        FROM inventory i
        JOIN phc p ON p.phc_id = i.phc_id
        JOIN state s ON s.state_id = p.state_id
        JOIN district d ON d.district_id = p.district_id
        JOIN medicine m ON m.medicine_id = i.medicine_id
        WHERE 1=1 {clause}
    """
    args = list(params)
    if filters.get("medicine_id"):
        q += " AND i.medicine_id = ?"
        args.append(filters["medicine_id"])
    if filters.get("q"):
        q += " AND (m.name LIKE ? OR p.name LIKE ?)"
        like = f'%{filters["q"]}%'
        args += [like, like]
    q += " ORDER BY p.name, m.name"

    rows = []
    for r in conn.execute(q, args):
        item = dict(r)
        status, days = stock.evaluate_row(item["stock_qty"], item["avg_daily_consumption"])
        item["days_of_stock"] = days
        item["status"] = status
        item["surplus"] = stock.surplus_qty(item["stock_qty"], item["avg_daily_consumption"])
        rows.append(item)

    if filters.get("status") and filters["status"] != "all":
        rows = [r for r in rows if r["status"] == filters["status"]]
    return rows


@app.get("/api/inventory")
@login_required
def api_inventory():
    conn = get_db()
    clause, params = scope_clause(geo_scope(conn))
    filters = {
        "medicine_id": request.args.get("medicine_id", type=int),
        "q": (request.args.get("q") or "").strip(),
        "status": request.args.get("status", "all"),
    }
    rows = _inventory_rows(conn, clause, params, filters)
    generated_at = conn.execute("SELECT CURRENT_TIMESTAMP AS ts").fetchone()["ts"]
    conn.close()
    return jsonify({"inventory": rows, "count": len(rows), "generated_at": generated_at})


@app.post("/api/inventory/<int:item_id>/stock")
@login_required
@role_required(*EDITOR_ROLES)
def api_update_stock(item_id):
    data = request.get_json(silent=True) or {}
    if "stock_qty" not in data:
        return jsonify({"error": "stock_qty required"}), 400
    try:
        new_stock = float(data["stock_qty"])
        new_adc = float(data["avg_daily_consumption"]) if data.get("avg_daily_consumption") not in (None, "") else None
    except (TypeError, ValueError):
        return jsonify({"error": "stock_qty and avg_daily_consumption must be numbers"}), 400
    if new_stock < 0:
        return jsonify({"error": "stock_qty cannot be negative"}), 400

    conn = get_db()
    item = conn.execute("SELECT * FROM inventory WHERE id = ?", (item_id,)).fetchone()
    if not item:
        conn.close()
        return jsonify({"error": "Inventory line not found"}), 404
    if not _in_scope(conn, item["phc_id"]):
        conn.close()
        return jsonify({"error": "Forbidden"}), 403

    sets = ["stock_qty = ?", "updated_at = CURRENT_TIMESTAMP"]
    params = [new_stock]
    if new_adc is not None:
        if new_adc < 0:
            conn.close()
            return jsonify({"error": "avg_daily_consumption cannot be negative"}), 400
        sets.append("avg_daily_consumption = ?")
        params.append(new_adc)
    conn.execute(f"UPDATE inventory SET {', '.join(sets)} WHERE id = ?", (*params, item_id))

    status, days = stock.evaluate_row(
        new_stock, new_adc if new_adc is not None else item["avg_daily_consumption"]
    )
    forecast.invalidate(item["phc_id"], item["medicine_id"])
    stock.refresh_alerts(conn)
    log_audit(
        conn, "stock_update",
        f'Updated stock for line {item_id}: {item["stock_qty"]} -> {new_stock} (status {status})',
    )
    conn.commit()
    conn.close()
    return jsonify({"status": "ok", "new_status": status, "days_of_stock": days})


# ============================== Medicines ==============================

@app.get("/api/medicines")
@login_required
def api_medicines():
    conn = get_db()
    clause, params = scope_clause(geo_scope(conn))
    rows = conn.execute(
        f"""
        SELECT m.medicine_id, m.name, m.category, m.strength, m.unit, m.essential,
               COUNT(i.id) AS stocked_phcs,
               COALESCE(SUM(i.stock_qty), 0) AS district_stock,
               SUM(CASE WHEN i.stock_qty <= 0 THEN 1 ELSE 0 END) AS stock_out_phcs,
               AVG(CASE WHEN i.avg_daily_consumption > 0
                        THEN i.stock_qty / i.avg_daily_consumption END) AS avg_days
        FROM medicine m
        LEFT JOIN inventory i ON i.medicine_id = m.medicine_id
        LEFT JOIN phc p ON p.phc_id = i.phc_id
        WHERE 1=1 {clause} OR i.id IS NULL
        GROUP BY m.medicine_id
        ORDER BY m.category, m.name
        """,
        params,
    ).fetchall()
    conn.close()
    out = []
    for r in rows:
        item = dict(r)
        item["avg_days"] = round(item["avg_days"], 1) if item["avg_days"] is not None else None
        out.append(item)
    return jsonify({"medicines": out})


@app.post("/api/medicines")
@login_required
@role_required("admin", "district_officer", "state_officer")
def api_add_medicine():
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"error": "name required"}), 400
    conn = get_db()
    if conn.execute("SELECT 1 FROM medicine WHERE name = ?", (name,)).fetchone():
        conn.close()
        return jsonify({"error": "Medicine already exists"}), 409
    conn.execute(
        "INSERT INTO medicine (name, category, strength, unit, essential) VALUES (?,?,?,?,?)",
        (name, (data.get("category") or "Other").strip(), (data.get("strength") or "").strip() or None,
         (data.get("unit") or "unit").strip(), 1 if data.get("essential", True) else 0),
    )
    log_audit(conn, "medicine_add", f"Added medicine {name}")
    conn.commit()
    conn.close()
    return jsonify({"status": "ok"})


# ============================== Alerts ==============================

@app.get("/api/alerts")
@login_required
def api_alerts():
    conn = get_db()
    status_filter = request.args.get("status", "open")
    clause, params = scope_clause(geo_scope(conn))
    q = f"""
        SELECT a.*, p.name AS phc_name, p.block, s.name AS state_name, d.name AS district_name,
               m.name AS medicine, m.unit
        FROM alerts a
        JOIN phc p ON p.phc_id = a.phc_id
        JOIN state s ON s.state_id = p.state_id
        JOIN district d ON d.district_id = p.district_id
        JOIN medicine m ON m.medicine_id = a.medicine_id
        WHERE 1=1 {clause}
    """
    args = list(params)
    if status_filter in ("open", "acknowledged", "resolved"):
        if status_filter == "open":
            q += " AND a.status IN ('open','acknowledged')"
        else:
            q += " AND a.status = ?"
            args.append(status_filter)
    else:
        q += " AND a.status IN ('open','acknowledged')"
    q += (" ORDER BY CASE a.severity WHEN 'stock_out' THEN 0 WHEN 'critical' THEN 1"
          " WHEN 'forecast_risk' THEN 2 ELSE 3 END, a.days_of_stock ASC")
    rows = [dict(r) for r in conn.execute(q, args)]
    counts = _alert_counts(conn, clause, params)
    generated_at = conn.execute("SELECT CURRENT_TIMESTAMP AS ts").fetchone()["ts"]
    conn.close()
    return jsonify({"alerts": rows, "counts": counts, "generated_at": generated_at})


@app.post("/api/alerts/<int:alert_id>/action")
@login_required
@role_required(*EDITOR_ROLES)
def api_alert_action(alert_id):
    data = request.get_json(silent=True) or {}
    action = data.get("action")
    if action not in ("acknowledge", "resolve"):
        return jsonify({"error": "action must be acknowledge or resolve"}), 400
    conn = get_db()
    alert = conn.execute("SELECT * FROM alerts WHERE id = ?", (alert_id,)).fetchone()
    if not alert:
        conn.close()
        return jsonify({"error": "Alert not found"}), 404
    if not _in_scope(conn, alert["phc_id"]):
        conn.close()
        return jsonify({"error": "Forbidden"}), 403

    new_status = "acknowledged" if action == "acknowledge" else "resolved"
    conn.execute(
        "UPDATE alerts SET status = ?, ack_by = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
        (new_status, session.get("username"), alert_id),
    )
    log_audit(conn, f"alert_{action}", f"Alert {alert_id} {action}d: {alert['message']}")
    conn.commit()
    conn.close()
    return jsonify({"status": "ok", "new_status": new_status})


# ============================== Forecast ==============================

@app.get("/api/forecast")
@login_required
def api_forecast():
    """Projected stock-out per visible inventory line (Ridge, 14-day horizon)."""
    conn = get_db()
    clause, params = scope_clause(geo_scope(conn))
    limit = request.args.get("limit", type=int) or 60
    rows = forecast.compute_forecasts(conn, clause, params, limit=limit)
    status = forecast.models_trained()
    settings = forecast.get_settings(conn)
    generated_at = conn.execute("SELECT CURRENT_TIMESTAMP AS ts").fetchone()["ts"]
    conn.close()
    return jsonify({"forecast": rows, "models": status, "settings": settings,
                    "horizon": forecast.HORIZON, "risk_days": forecast.RISK_DAYS,
                    "generated_at": generated_at})


@app.get("/api/forecast/status")
@login_required
def api_forecast_status():
    conn = get_db()
    history_rows = conn.execute("SELECT COUNT(*) AS n FROM consumption_history").fetchone()["n"]
    generated_at = conn.execute("SELECT CURRENT_TIMESTAMP AS ts").fetchone()["ts"]
    conn.close()
    return jsonify({
        "horizon": forecast.HORIZON,
        "risk_days": forecast.RISK_DAYS,
        "holdout_days": forecast.HOLDOUT,
        "history_rows": history_rows,
        "generated_at": generated_at,
        **forecast.models_trained(),
    })


# ============================== Settings ==============================

@app.get("/api/settings")
@login_required
def api_settings():
    conn = get_db()
    settings = forecast.get_settings(conn)
    conn.close()
    return jsonify(settings)


@app.post("/api/settings")
@login_required
@role_required(*OFFICER_ROLES)
def api_update_settings():
    data = request.get_json(silent=True) or {}
    conn = get_db()
    applied = {}
    if "emergency_mode" in data:
        mode = 1 if data.get("emergency_mode") else 0
        conn.execute(
            "INSERT INTO settings (key, value, updated_at) VALUES ('emergency_mode', ?, CURRENT_TIMESTAMP)"
            " ON CONFLICT (key) DO UPDATE SET value = excluded.value, updated_at = CURRENT_TIMESTAMP",
            (str(mode),),
        )
        applied["emergency_mode"] = bool(mode)
    if "emergency_multiplier" in data:
        try:
            mult = float(data.get("emergency_multiplier"))
        except (TypeError, ValueError):
            conn.close()
            return jsonify({"error": "emergency_multiplier must be a number"}), 400
        if not 1.0 <= mult <= 5.0:
            conn.close()
            return jsonify({"error": "emergency_multiplier must be between 1.0 and 5.0"}), 400
        conn.execute(
            "INSERT INTO settings (key, value, updated_at) VALUES ('emergency_multiplier', ?, CURRENT_TIMESTAMP)"
            " ON CONFLICT (key) DO UPDATE SET value = excluded.value, updated_at = CURRENT_TIMESTAMP",
            (str(mult),),
        )
        applied["emergency_multiplier"] = mult
    if not applied:
        conn.close()
        return jsonify({"error": "emergency_mode or emergency_multiplier required"}), 400

    log_audit(conn, "settings_update", f"Settings updated: {applied}")
    forecast.invalidate()  # multiplier feeds every projection
    stock.refresh_alerts(conn)  # re-evaluates forecast_risk alerts
    settings = forecast.get_settings(conn)
    conn.commit()
    conn.close()
    return jsonify({"status": "ok", "settings": settings})


# ============================== Redistribution ==============================

@app.get("/api/redistribution")
@login_required
def api_redistribution_list():
    conn = get_db()
    status_filter = request.args.get("status")
    drill = geo_scope(conn)
    own = session_scope()
    q = """
        SELECT r.*, fp.name AS from_phc_name, tp.name AS to_phc_name,
               fd.name AS from_district_name, td.name AS to_district_name,
               m.name AS medicine, m.unit
        FROM redistribution r
        LEFT JOIN phc fp ON fp.phc_id = r.from_phc_id
        LEFT JOIN phc f ON f.phc_id = r.from_phc_id
        LEFT JOIN district fd ON fd.district_id = fp.district_id
        LEFT JOIN phc tp ON tp.phc_id = r.to_phc_id
        LEFT JOIN phc p ON p.phc_id = r.to_phc_id
        LEFT JOIN district td ON td.district_id = tp.district_id
        JOIN medicine m ON m.medicine_id = r.medicine_id
        WHERE 1=1
    """
    args = []
    if drill:
        to_sql, to_params = scope_clause(drill, "p")
        from_sql, from_params = scope_clause(drill, "f")
        q += f" AND (({to_sql[5:]}) OR ({from_sql[5:]}))"
        args += list(to_params) + list(from_params)
    if own.get("phc_id") is not None:
        q += " AND (r.to_phc_id = ? OR r.from_phc_id = ?)"
        args += [own["phc_id"], own["phc_id"]]
    elif own.get("district_id") is not None:
        q += " AND (tp.district_id = ? OR fp.district_id = ?)"
        args += [own["district_id"], own["district_id"]]
    elif own.get("state_id") is not None:
        q += " AND (tp.state_id = ? OR fp.state_id = ?)"
        args += [own["state_id"], own["state_id"]]
    if status_filter and status_filter != "all":
        q += " AND r.status = ?"
        args.append(status_filter)
    q += " ORDER BY r.created_at DESC"
    rows = [dict(r) for r in conn.execute(q, args)]
    conn.close()
    return jsonify({"redistributions": rows})


def _donor_pools():
    """Donor search pools for suggestions — narrowest first.

    Cross-district redistribution (P4): a district officer can pull stock
    from anywhere in their state when the home district has no surplus; a
    state officer widens to the national pool; admins search nationally.
    """
    own = session_scope()
    if own.get("district_id"):
        return [
            ("district", "AND p.district_id = ?", (own["district_id"],)),
            ("state", "AND p.state_id = (SELECT state_id FROM district WHERE district_id = ?)",
             (own["district_id"],)),
        ]
    if own.get("state_id"):
        return [
            ("state", "AND p.state_id = ?", (own["state_id"],)),
            ("national", "", ()),
        ]
    return [("national", "", ())]


@app.get("/api/redistribution/suggestions")
@login_required
@role_required(*OFFICER_ROLES)
def api_redistribution_suggestions():
    conn = get_db()
    clause, params = scope_clause(geo_scope(conn))
    suggestions = stock.redistribution_suggestions(
        conn, clause, params, donor_pools=_donor_pools()
    )
    conn.close()
    return jsonify({"suggestions": suggestions, "target_days": stock.TARGET_DAYS})


@app.post("/api/redistribution/auto-propose")
@login_required
@role_required(*OFFICER_ROLES)
def api_auto_propose():
    """Create `proposed` transfers from every covered suggestion (P4).

    Skips any (donor, receiver, medicine) that already has an open transfer,
    so running it twice is idempotent.
    """
    data = request.get_json(silent=True) or {}
    try:
        limit = int(data.get("limit") or 25)
    except (TypeError, ValueError):
        return jsonify({"error": "limit must be an integer"}), 400
    conn = get_db()
    clause, params = scope_clause(geo_scope(conn))
    suggestions = stock.redistribution_suggestions(
        conn, clause, params, limit=max(limit, 25), donor_pools=_donor_pools()
    )
    created, skipped = [], 0
    for s in suggestions:
        for d in s["donors"]:
            if d["offer"] <= 0:
                continue
            if len(created) >= limit:
                break
            existing = conn.execute(
                """SELECT id FROM redistribution
                   WHERE from_phc_id = ? AND to_phc_id = ? AND medicine_id = ?
                     AND status IN ('proposed','accepted','dispatched')""",
                (d["phc_id"], s["phc_id"], s["medicine_id"]),
            ).fetchone()
            if existing:
                skipped += 1
                continue
            cross = f" (cross-district: {d['district_name']})" if d["district_name"] != s["district_name"] else ""
            reason = (
                f"Auto-proposed: {s['shortfall']} {s['unit']} of {s['medicine']} to cover "
                f"{s['status']} at {s['phc_name']} from {d['phc_name']}{cross}"
            )
            cur = conn.execute(
                """INSERT INTO redistribution
                   (from_phc_id, to_phc_id, medicine_id, quantity, reason, created_by, status)
                   VALUES (?,?,?,?,?,?, 'proposed')""",
                (d["phc_id"], s["phc_id"], s["medicine_id"], d["offer"], reason,
                 session.get("username")),
            )
            created.append({"id": cur.lastrowid, "from_phc": d["phc_name"], "to_phc": s["phc_name"],
                            "medicine": s["medicine"], "quantity": d["offer"],
                            "scope": d.get("scope")})
    log_audit(
        conn, "redistribution_auto_propose",
        f"Auto-proposed {len(created)} transfer(s) from {len(suggestions)} suggestion(s), {skipped} skipped as duplicates",
    )
    conn.commit()
    conn.close()
    return jsonify({"created": len(created), "skipped": skipped, "transfers": created})


@app.post("/api/redistribution")
@login_required
@role_required(*OFFICER_ROLES)
def api_redistribution_create():
    data = request.get_json(silent=True) or {}
    to_phc = data.get("to_phc_id")
    med_id = data.get("medicine_id")
    qty = data.get("quantity")
    from_phc = data.get("from_phc_id")
    if not to_phc or not med_id or qty is None:
        return jsonify({"error": "to_phc_id, medicine_id and quantity required"}), 400
    try:
        qty = float(qty)
    except (TypeError, ValueError):
        return jsonify({"error": "quantity must be a number"}), 400
    if qty <= 0:
        return jsonify({"error": "quantity must be positive"}), 400

    conn = get_db()
    if not _in_scope(conn, to_phc):
        conn.close()
        return jsonify({"error": "Forbidden"}), 403
    if from_phc:
        donor = conn.execute(
            "SELECT stock_qty FROM inventory WHERE phc_id = ? AND medicine_id = ?", (from_phc, med_id)
        ).fetchone()
        if not donor:
            conn.close()
            return jsonify({"error": "Donor PHC does not stock this medicine"}), 400
        if donor["stock_qty"] < qty:
            conn.close()
            return jsonify({"error": "Donor does not have enough surplus stock"}), 400
    conn.execute(
        """INSERT INTO redistribution (from_phc_id, to_phc_id, medicine_id, quantity, reason, created_by, status)
           VALUES (?,?,?,?,?,?, 'proposed')""",
        (from_phc, to_phc, med_id, qty, (data.get("reason") or "").strip(), session.get("username")),
    )
    log_audit(conn, "redistribution_propose",
              f"Proposed {qty} units of medicine {med_id} -> PHC {to_phc} from {from_phc or 'central pool'}")
    conn.commit()
    conn.close()
    return jsonify({"status": "ok"})


# proposed -> accepted (approve) / rejected (reject) / cancelled
# accepted -> dispatched -> delivered  (delivered moves the stock)
STATUS_FLOW = {
    "proposed": {"accepted", "rejected", "cancelled"},
    "accepted": {"dispatched", "cancelled"},
    "dispatched": {"delivered"},
    "delivered": set(),
    "rejected": set(),
    "cancelled": set(),
}


@app.post("/api/redistribution/<int:transfer_id>/status")
@login_required
@role_required(*EDITOR_ROLES)
def api_redistribution_status(transfer_id):
    data = request.get_json(silent=True) or {}
    new_status = data.get("status")
    allowed = tuple(sorted({s for moves in STATUS_FLOW.values() for s in moves}))
    if new_status not in allowed:
        return jsonify({"error": f"status must be one of {', '.join(allowed)}"}), 400

    conn = get_db()
    row = conn.execute("SELECT * FROM redistribution WHERE id = ?", (transfer_id,)).fetchone()
    if not row:
        conn.close()
        return jsonify({"error": "Transfer not found"}), 404
    if not (_in_scope(conn, row["to_phc_id"]) or _in_scope(conn, row["from_phc_id"] or -1)):
        conn.close()
        return jsonify({"error": "Forbidden"}), 403
    if new_status not in STATUS_FLOW.get(row["status"], set()):
        conn.close()
        return jsonify({"error": f"Cannot move a {row['status']} transfer to {new_status}"}), 400

    conn.execute(
        "UPDATE redistribution SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
        (new_status, transfer_id),
    )
    if new_status == "delivered" and row["from_phc_id"]:
        donor = conn.execute(
            "SELECT id FROM inventory WHERE phc_id = ? AND medicine_id = ?",
            (row["from_phc_id"], row["medicine_id"]),
        ).fetchone()
        if donor:
            conn.execute(
                "UPDATE inventory SET stock_qty = MAX(0, stock_qty - ?), updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (row["quantity"], donor["id"]),
            )
        conn.execute(
            """
            INSERT INTO inventory (phc_id, medicine_id, stock_qty, avg_daily_consumption)
            VALUES (?,?,?, COALESCE((SELECT avg_daily_consumption FROM inventory
                                     WHERE phc_id = ? AND medicine_id = ?), 0))
            ON CONFLICT (phc_id, medicine_id) DO UPDATE SET
                stock_qty = stock_qty + excluded.stock_qty,
                updated_at = CURRENT_TIMESTAMP
            """,
            (row["to_phc_id"], row["medicine_id"], row["quantity"], row["to_phc_id"], row["medicine_id"]),
        )
        stock.refresh_alerts(conn)
    log_audit(conn, "redistribution_status", f"Transfer {transfer_id} -> {new_status}")
    conn.commit()
    conn.close()
    return jsonify({"status": "ok"})


# ============================== Upload ==============================

@app.post("/api/upload")
@login_required
@role_required(*OFFICER_ROLES)
def api_upload():
    if "file" not in request.files:
        return jsonify({"error": "No file provided"}), 400
    file = request.files["file"]
    if not file.filename:
        return jsonify({"error": "No file selected"}), 400
    try:
        upload_id, temp_path, fmt = uploader.save_temp(file)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

    try:
        df = uploader.read_file(temp_path)
        conn = get_db()
        detection = uploader.detect_columns(df)
        result = uploader.preview(conn, df, detection["mappings"])
        cur = conn.execute(
            """INSERT INTO upload_history (filename, uploaded_by, total_rows, status, temp_path)
               VALUES (?,?,?,?,?)""",
            (file.filename, session.get("username"), result["total_rows"], "preview", temp_path),
        )
        record_id = cur.lastrowid
        log_audit(conn, "upload_preview",
                  f"Uploaded {file.filename}: {result['valid_rows']}/{result['total_rows']} valid rows ({fmt})")
        conn.commit()
        conn.close()
    except Exception as e:
        try:
            os.unlink(temp_path)
        except OSError:
            pass
        return jsonify({"error": f"Failed to process file: {e}"}), 400

    return jsonify({
        "upload_id": record_id,
        "temp_id": upload_id,
        "filename": file.filename,
        "detected_type": detection["detected_type"],
        "unmapped_columns": detection["unmapped_columns"],
        **{k: v for k, v in result.items() if k != "all_rows"},
    })


@app.post("/api/upload/confirm")
@login_required
@role_required(*OFFICER_ROLES)
def api_upload_confirm():
    data = request.get_json(silent=True) or {}
    upload_id = data.get("upload_id")
    if not upload_id:
        return jsonify({"error": "upload_id required"}), 400
    conn = get_db()
    rec = conn.execute(
        "SELECT * FROM upload_history WHERE id = ? AND status = 'preview'", (upload_id,)
    ).fetchone()
    if not rec or not rec["temp_path"] or not os.path.exists(rec["temp_path"]):
        conn.close()
        return jsonify({"error": "Upload session expired. Re-upload the file."}), 400

    try:
        forecast.invalidate()  # bulk stock change -> drop every cached projection
        result = uploader.confirm(conn, rec["temp_path"], session.get("username"), _in_scope)
    except Exception as e:
        conn.close()
        return jsonify({"error": f"Insert failed: {e}"}), 500

    conn.execute(
        """UPDATE upload_history SET status = 'confirmed', rows_inserted = ?, rows_updated = ?,
           rows_rejected = ?, confirmed_at = CURRENT_TIMESTAMP WHERE id = ?""",
        (result["rows_inserted"], result["rows_updated"], result["rows_rejected"], upload_id),
    )
    log_audit(conn, "upload_confirm",
              f"Applied {rec['filename']}: +{result['rows_inserted']} inserted, "
              f"{result['rows_updated']} updated, {result['rows_rejected']} rejected")
    conn.commit()
    conn.close()
    try:
        os.unlink(rec["temp_path"])
    except OSError:
        pass
    return jsonify({"status": "ok", **result})


@app.get("/api/upload/history")
@login_required
@role_required(*OFFICER_ROLES)
def api_upload_history():
    conn = get_db()
    rows = [dict(r) for r in conn.execute(
        "SELECT id, filename, uploaded_by, total_rows, rows_inserted, rows_updated, rows_rejected, status, created_at, confirmed_at "
        "FROM upload_history ORDER BY id DESC LIMIT 20")]
    conn.close()
    return jsonify({"history": rows})


# ============================== Audit ==============================

@app.get("/api/audit")
@login_required
@role_required("admin", "district_officer", "state_officer")
def api_audit():
    conn = get_db()
    own = session_scope()
    q, params = " WHERE 1=1", []
    if own.get("state_id"):
        q += " AND state_id = ?"
        params.append(own["state_id"])
    elif own.get("district_id"):
        q += " AND district_id = ?"
        params.append(own["district_id"])
    rows = [dict(r) for r in conn.execute(
        f"SELECT * FROM audit_log{q} ORDER BY id DESC LIMIT 100", params)]
    conn.close()
    return jsonify({"audit": rows})


# ============================== Federated demo ==============================

@app.get("/api/federated/demo")
@login_required
def api_federated_demo():
    return jsonify(FEDERATED_DEMO)


@app.get("/api/federated/live")
@login_required
@role_required(*OFFICER_ROLES)
def api_federated_live():
    """Live federation round: sync per-state nodes, train on-node, FedAvg."""
    conn = get_db()
    own_state = session.get("state_id")
    state_ids = [own_state] if own_state else None
    resync = request.args.get("resync") in ("1", "true")
    payload = federation.run_federation(conn, state_ids=state_ids, resync=resync)
    agg = payload["aggregated_result"]
    log_audit(
        conn,
        "federation_round",
        f"{payload['federation_id']}: {agg['nodes_reporting']}/{agg['nodes_total']} "
        f"nodes, fedavg_r2={agg['fedavg_r2']}, {payload['total_ms']}ms"
        + (" (resync)" if resync else ""),
    )
    conn.commit()
    conn.close()
    return jsonify(payload)


# ============================== Static frontend ==============================

@app.route("/", defaults={"path": ""})
@app.route("/<path:path>")
def spa(path):
    if path.startswith("api/"):
        return jsonify({"error": "Not found"}), 404
    if path and os.path.exists(os.path.join(DIST_DIR, path)):
        return send_from_directory(DIST_DIR, path)
    index = os.path.join(DIST_DIR, "index.html")
    if os.path.exists(index):
        return send_from_directory(DIST_DIR, "index.html")
    return jsonify({"error": "Frontend not built. Run `npm run dev` in frontend/ or `npm run build`."}), 404


if __name__ == "__main__":
    database.bootstrap()
    app.run(debug=True, port=5000)
