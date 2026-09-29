"""PHC Medicine Inventory — District Officer Command Center (Flask JSON API)."""
import os
import sqlite3

from flask import Flask, jsonify, redirect, request, send_from_directory, session

import db as database
import stock
import upload as uploader
from auth import hash_password, login_required, log_audit, role_required
from federated import FEDERATED_DEMO

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DIST_DIR = os.path.join(BASE_DIR, "..", "frontend", "dist")

app = Flask(__name__, static_folder=None)
app.secret_key = os.environ.get("SECRET_KEY", "phc-inventory-secret-2026")
app.config.update(SESSION_COOKIE_SAMESITE="Lax", SESSION_COOKIE_HTTPONLY=True)

PHC_MANAGER_ROLES = ("district_officer", "phc_manager")


def get_db():
    return database.get_db()


def current_scope():
    """phc_manager -> own PHC only. Everyone else -> district-wide (None)."""
    if session.get("role") == "phc_manager":
        return session.get("phc_id")
    return None


def scoped_phc_clause(alias="i"):
    phc_id = current_scope()
    if phc_id is None:
        return "", ()
    return f" AND {alias}.phc_id = ?", (phc_id,)


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
    return {
        "id": user["id"],
        "username": user["username"],
        "full_name": user["full_name"],
        "role": user["role"],
        "phc_id": user["phc_id"],
        "phc_name": _phc_name(user["phc_id"]),
    }


def _phc_name(phc_id):
    if not phc_id:
        return None
    conn = get_db()
    row = conn.execute("SELECT name FROM phc WHERE phc_id = ?", (phc_id,)).fetchone()
    conn.close()
    return row["name"] if row else None


# ============================== Overview ==============================

@app.get("/api/overview")
@login_required
def api_overview():
    conn = get_db()
    scope = current_scope()
    stats = stock.summary_stats(conn)
    phcs = _phc_rollup(conn, scope)

    q = """
        SELECT a.id, a.alert_type, a.severity, a.days_of_stock, a.message, a.status,
               a.created_at, p.name AS phc_name, m.name AS medicine, m.unit
        FROM alerts a
        JOIN phc p ON p.phc_id = a.phc_id
        JOIN medicine m ON m.medicine_id = a.medicine_id
        WHERE a.status IN ('open','acknowledged')
    """
    params = []
    if scope:
        q += " AND a.phc_id = ?"
        params.append(scope)
    order = "CASE a.severity WHEN 'stock_out' THEN 0 WHEN 'critical' THEN 1 ELSE 2 END, a.days_of_stock ASC"
    alerts = [dict(r) for r in conn.execute(q + f" ORDER BY {order} LIMIT 8", params)]

    by_severity = _alert_counts(conn, scope)
    conn.close()

    if scope:
        stats = {k: v for k, v in stats.items() if k in ("lines", "stock_out", "critical", "low", "open_alerts", "avg_days_cover", "medicines")}
        stats["phcs"] = 1
    return jsonify({"stats": stats, "phcs": phcs, "top_alerts": alerts, "alerts_by_severity": by_severity})


def _phc_rollup(conn, scope):
    q = """
        SELECT p.phc_id, p.name, p.block, p.beds,
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
        LEFT JOIN inventory i ON i.phc_id = p.phc_id
    """
    params = [stock.CRITICAL_DAYS, stock.CRITICAL_DAYS, stock.LOW_DAYS]
    if scope:
        q += " WHERE p.phc_id = ?"
        params.append(scope)
    q += " GROUP BY p.phc_id ORDER BY p.name"
    return [dict(r) for r in conn.execute(q, params)]


def _alert_counts(conn, scope):
    q = "SELECT severity, COUNT(*) AS n FROM alerts WHERE status IN ('open','acknowledged')"
    params = []
    if scope:
        q += " AND phc_id = ?"
        params.append(scope)
    q += " GROUP BY severity"
    out = {"stock_out": 0, "critical": 0, "low": 0}
    for r in conn.execute(q, params):
        out[r["severity"]] = r["n"]
    return out


# ============================== PHCs ==============================

@app.get("/api/phcs")
@login_required
def api_phcs():
    conn = get_db()
    scope = current_scope()
    rows = _phc_rollup(conn, scope)
    conn.close()
    return jsonify({"phcs": rows})


@app.get("/api/phcs/<int:phc_id>")
@login_required
def api_phc_detail(phc_id):
    if current_scope() not in (None, phc_id):
        return jsonify({"error": "Forbidden"}), 403
    conn = get_db()
    phc = conn.execute("SELECT * FROM phc WHERE phc_id = ?", (phc_id,)).fetchone()
    if not phc:
        conn.close()
        return jsonify({"error": "PHC not found"}), 404
    lines = _inventory_rows(conn, {"phc_id": phc_id})
    conn.close()
    return jsonify({"phc": dict(phc), "inventory": lines})


# ============================== Inventory ==============================

def _inventory_rows(conn, filters):
    q = """
        SELECT i.id, i.phc_id, p.name AS phc_name, p.block,
               i.medicine_id, m.name AS medicine, m.category, m.unit, m.essential,
               i.stock_qty, i.avg_daily_consumption, i.updated_at
        FROM inventory i
        JOIN phc p ON p.phc_id = i.phc_id
        JOIN medicine m ON m.medicine_id = i.medicine_id
        WHERE 1=1
    """
    params = []
    if filters.get("phc_id"):
        q += " AND i.phc_id = ?"
        params.append(filters["phc_id"])
    if filters.get("medicine_id"):
        q += " AND i.medicine_id = ?"
        params.append(filters["medicine_id"])
    if filters.get("q"):
        q += " AND (m.name LIKE ? OR p.name LIKE ?)"
        like = f'%{filters["q"]}%'
        params += [like, like]
    q += " ORDER BY p.name, m.name"

    rows = []
    for r in conn.execute(q, params):
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
    filters = {
        "phc_id": request.args.get("phc_id", type=int),
        "medicine_id": request.args.get("medicine_id", type=int),
        "q": (request.args.get("q") or "").strip(),
        "status": request.args.get("status", "all"),
    }
    if current_scope():
        filters["phc_id"] = current_scope()
    rows = _inventory_rows(conn, filters)
    conn.close()
    return jsonify({"inventory": rows, "count": len(rows)})


@app.post("/api/inventory/<int:item_id>/stock")
@login_required
@role_required(*PHC_MANAGER_ROLES)
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
    if current_scope() not in (None, item["phc_id"]):
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
    rows = conn.execute(
        """
        SELECT m.medicine_id, m.name, m.category, m.strength, m.unit, m.essential,
               COUNT(i.id) AS stocked_phcs,
               COALESCE(SUM(i.stock_qty), 0) AS district_stock,
               SUM(CASE WHEN i.stock_qty <= 0 THEN 1 ELSE 0 END) AS stock_out_phcs,
               AVG(CASE WHEN i.avg_daily_consumption > 0
                        THEN i.stock_qty / i.avg_daily_consumption END) AS avg_days
        FROM medicine m
        LEFT JOIN inventory i ON i.medicine_id = m.medicine_id
        GROUP BY m.medicine_id
        ORDER BY m.category, m.name
        """
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
@role_required("admin", "district_officer")
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
    q = """
        SELECT a.*, p.name AS phc_name, p.block, m.name AS medicine, m.unit
        FROM alerts a
        JOIN phc p ON p.phc_id = a.phc_id
        JOIN medicine m ON m.medicine_id = a.medicine_id
        WHERE 1=1
    """
    params = []
    if status_filter in ("open", "acknowledged", "resolved"):
        if status_filter == "open":
            q += " AND a.status IN ('open','acknowledged')"
        else:
            q += " AND a.status = ?"
            params.append(status_filter)
    else:
        q += " AND a.status IN ('open','acknowledged')"
    if current_scope():
        q += " AND a.phc_id = ?"
        params.append(current_scope())
    q += " ORDER BY CASE a.severity WHEN 'stock_out' THEN 0 WHEN 'critical' THEN 1 ELSE 2 END, a.days_of_stock ASC"
    rows = [dict(r) for r in conn.execute(q, params)]
    counts = _alert_counts(conn, current_scope())
    conn.close()
    return jsonify({"alerts": rows, "counts": counts})


@app.post("/api/alerts/<int:alert_id>/action")
@login_required
@role_required(*PHC_MANAGER_ROLES)
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
    if current_scope() not in (None, alert["phc_id"]):
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


# ============================== Redistribution ==============================

@app.get("/api/redistribution")
@login_required
def api_redistribution_list():
    conn = get_db()
    status_filter = request.args.get("status")
    q = """
        SELECT r.*, fp.name AS from_phc_name, tp.name AS to_phc_name,
               m.name AS medicine, m.unit
        FROM redistribution r
        LEFT JOIN phc fp ON fp.phc_id = r.from_phc_id
        JOIN phc tp ON tp.phc_id = r.to_phc_id
        JOIN medicine m ON m.medicine_id = r.medicine_id
        WHERE 1=1
    """
    params = []
    if status_filter and status_filter != "all":
        q += " AND r.status = ?"
        params.append(status_filter)
    if current_scope():
        q += " AND (r.to_phc_id = ? OR r.from_phc_id = ?)"
        params += [current_scope(), current_scope()]
    q += " ORDER BY r.created_at DESC"
    rows = [dict(r) for r in conn.execute(q, params)]
    conn.close()
    return jsonify({"redistributions": rows})


@app.get("/api/redistribution/suggestions")
@login_required
@role_required("admin", "district_officer")
def api_redistribution_suggestions():
    conn = get_db()
    suggestions = stock.redistribution_suggestions(conn)
    conn.close()
    return jsonify({"suggestions": suggestions, "target_days": stock.TARGET_DAYS})


@app.post("/api/redistribution")
@login_required
@role_required("admin", "district_officer")
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
              f"Proposed {qty} units of medicine {med_id} -> PHC {to_phc} from {from_phc or 'district pool'}")
    conn.commit()
    conn.close()
    return jsonify({"status": "ok"})


@app.post("/api/redistribution/<int:transfer_id>/status")
@login_required
@role_required(*PHC_MANAGER_ROLES)
def api_redistribution_status(transfer_id):
    data = request.get_json(silent=True) or {}
    new_status = data.get("status")
    allowed = ("accepted", "dispatched", "delivered", "cancelled")
    if new_status not in allowed:
        return jsonify({"error": f"status must be one of {', '.join(allowed)}"}), 400

    conn = get_db()
    row = conn.execute("SELECT * FROM redistribution WHERE id = ?", (transfer_id,)).fetchone()
    if not row:
        conn.close()
        return jsonify({"error": "Transfer not found"}), 404
    if current_scope() not in (None, row["to_phc_id"], row["from_phc_id"]):
        conn.close()
        return jsonify({"error": "Forbidden"}), 403

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
@role_required("admin", "district_officer")
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
@role_required("admin", "district_officer")
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
        result = uploader.confirm(conn, rec["temp_path"], session.get("username"))
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
@role_required("admin", "district_officer")
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
@role_required("admin", "district_officer")
def api_audit():
    conn = get_db()
    rows = [dict(r) for r in conn.execute(
        "SELECT * FROM audit_log ORDER BY id DESC LIMIT 100")]
    conn.close()
    return jsonify({"audit": rows})


# ============================== Federated demo ==============================

@app.get("/api/federated/demo")
@login_required
def api_federated_demo():
    return jsonify(FEDERATED_DEMO)


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
