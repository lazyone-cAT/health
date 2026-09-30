"""Federation: hardcoded demo payload + live per-state nodes with FedAvg.

The demo payload below is the original mock (kept for /api/federated/demo).
The live implementation at the bottom of this file is what the UI uses now:

Option A architecture
---------------------
* The national DB (phc_inventory.db) drives the dashboard and the coordinator
  — the only place where full rows live together.
* Every state also gets its own node DB (backend/nodes/state_<code>.db) with
  *only* that state's rows, as if the state ran its own instance.
* A federation round is: sync nodes -> train a local Ridge model on each
  node's own consumption history -> average coefficients (FedAvg, weighted
  by each node's training rows).
* Only aggregates and model coefficients leave a node; raw inventory and
  consumption rows never do.
"""
import os
import sqlite3
import time
from datetime import date

import db as database
from forecast import HOLDOUT, _row

FEDERATED_DEMO = {
    "query": "district_federated_stockout_risk_v1",
    "coordinator": "District Node — Kalahandi",
    "federation_id": "FED-KAL-2026-09",
    "rounds": 3,
    "privacy": {
        "raw_rows_shared": False,
        "mechanism": "Local aggregate computation + secure sum aggregation",
        "min_node_rows": 5,
        "noise": "None (demo mode — deterministic mock values)",
    },
    "nodes": [
        {
            "node_id": "NODE-KHARIAR",
            "phc": "Khariar PHC",
            "status": "online",
            "latency_ms": 41,
            "rounds_joined": 3,
            "local_aggregates": {
                "lines_reported": 20,
                "stock_out": 2,
                "critical": 3,
                "low": 4,
                "avg_days_cover": 16.4,
            },
        },
        {
            "node_id": "NODE-JUNAGARH",
            "phc": "Junagarh PHC",
            "status": "online",
            "latency_ms": 58,
            "rounds_joined": 3,
            "local_aggregates": {
                "lines_reported": 20,
                "stock_out": 1,
                "critical": 2,
                "low": 5,
                "avg_days_cover": 18.1,
            },
        },
        {
            "node_id": "NODE-DHARAMGARH",
            "phc": "Dharamgarh PHC",
            "status": "online",
            "latency_ms": 73,
            "rounds_joined": 3,
            "local_aggregates": {
                "lines_reported": 20,
                "stock_out": 0,
                "critical": 4,
                "low": 2,
                "avg_days_cover": 21.7,
            },
        },
        {
            "node_id": "NODE-BODEN",
            "phc": "Boden PHC",
            "status": "degraded",
            "latency_ms": 312,
            "rounds_joined": 2,
            "local_aggregates": {
                "lines_reported": 20,
                "stock_out": 3,
                "critical": 2,
                "low": 3,
                "avg_days_cover": 12.9,
            },
        },
        {
            "node_id": "NODE-NARLA",
            "phc": "Narla PHC",
            "status": "offline",
            "latency_ms": None,
            "rounds_joined": 0,
            "local_aggregates": None,
            "last_seen": "2026-09-28T18:42:00",
        },
    ],
    "aggregated_result": {
        "nodes_reporting": 4,
        "nodes_total": 5,
        "stock_out": 6,
        "critical": 11,
        "low": 14,
        "weighted_avg_days_cover": 17.3,
        "agreement_rate": 0.96,
    },
    "round_log": [
        {"round": 1, "phase": "query_dispatch", "participants": 4, "result": "ack 4/5"},
        {"round": 2, "phase": "local_aggregate", "participants": 4, "result": "4 aggregate vectors returned"},
        {"round": 3, "phase": "secure_sum", "participants": 4, "result": "district totals converged"},
    ],
    "demo_note": (
        "Hardcoded demonstration data. In a live deployment each PHC would run a "
        "local agent that computes these aggregates on-premise and only the "
        "aggregated vectors leave the node."
    ),
}


# =========================================================================
# Live federation — per-state node DBs + FedAvg of the demand model (P5)
# =========================================================================

NODES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "nodes")
MIN_NODE_ROWS = 5          # small-cell suppression threshold
ALPHA = 0.1                # matches forecast.Ridge settings
FEATURE_NAMES = ["dow_mon", "dow_tue", "dow_wed", "dow_thu", "dow_fri", "dow_sat",
                 "dow_sun", "trend", "lag7", "lag30"]

NODE_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS state (
    state_id INTEGER PRIMARY KEY, name TEXT, code TEXT);
CREATE TABLE IF NOT EXISTS district (
    district_id INTEGER PRIMARY KEY, state_id INTEGER, name TEXT);
CREATE TABLE IF NOT EXISTS phc (
    phc_id INTEGER PRIMARY KEY, name TEXT, block TEXT, state_id INTEGER,
    district_id INTEGER, facility_type TEXT, beds INTEGER);
CREATE TABLE IF NOT EXISTS medicine (
    medicine_id INTEGER PRIMARY KEY, name TEXT, category TEXT, strength TEXT,
    unit TEXT, essential INTEGER);
CREATE TABLE IF NOT EXISTS inventory (
    id INTEGER PRIMARY KEY, phc_id INTEGER, medicine_id INTEGER,
    stock_qty REAL, avg_daily_consumption REAL, updated_at TEXT);
CREATE TABLE IF NOT EXISTS consumption_history (
    id INTEGER PRIMARY KEY, phc_id INTEGER, medicine_id INTEGER,
    use_date TEXT, quantity REAL);
"""

# columns copied from the national DB per table (national ids are preserved)
_COPY = {
    "state": "state_id, name, code",
    "district": "district_id, state_id, name",
    "phc": "phc_id, name, block, state_id, district_id, facility_type, beds",
    "medicine": "medicine_id, name, category, strength, unit, essential",
    "inventory": "id, phc_id, medicine_id, stock_qty, avg_daily_consumption, updated_at",
    "consumption_history": "id, phc_id, medicine_id, use_date, quantity",
}


def node_path(code):
    return os.path.join(NODES_DIR, f"state_{code}.db")


def _fingerprint(conn):
    inv = conn.execute(
        "SELECT COUNT(*), COALESCE(MAX(updated_at), '') FROM inventory"
    ).fetchone()
    hist = conn.execute("SELECT COUNT(*) FROM consumption_history").fetchone()[0]
    adc = conn.execute(
        "SELECT COALESCE(SUM(avg_daily_consumption), 0) FROM inventory"
    ).fetchone()[0]
    return f"{inv[0]}|{inv[1]}|{hist}|{round(float(adc), 3)}"


def _state_where(table, state_id):
    if table in ("state", "district", "phc"):
        return " WHERE state_id = ?", (state_id,)
    if table in ("inventory", "consumption_history"):
        return " WHERE phc_id IN (SELECT phc_id FROM phc WHERE state_id = ?)", (state_id,)
    return "", ()  # medicine catalogue is national


def sync_node(conn, state_row, resync=False):
    """(Re)build one state's node DB from the national DB.

    Rebuilt only when the national fingerprint changed, so repeated rounds
    are cheap while nothing has moved.
    """
    code, name, state_id = state_row["code"], state_row["name"], state_row["state_id"]
    path = node_path(code)
    os.makedirs(NODES_DIR, exist_ok=True)
    fp = _fingerprint(conn)
    rebuilt = False
    node = sqlite3.connect(path)
    try:
        node.executescript(NODE_SCHEMA)
        stored = node.execute("SELECT value FROM meta WHERE key='fingerprint'").fetchone()
        if resync or not stored or stored[0] != fp:
            node.execute("ATTACH DATABASE ? AS nat", (database.DB_PATH,))
            try:
                node.execute("BEGIN")
                for table, cols in _COPY.items():
                    where, params = _state_where(table, state_id)
                    node.execute(f"DELETE FROM {table}")
                    node.execute(
                        f"INSERT INTO {table} ({cols}) SELECT {cols} FROM nat.{table}{where}",
                        params,
                    )
                node.execute(
                    "INSERT OR REPLACE INTO meta (key, value) VALUES ('fingerprint', ?)",
                    (fp,),
                )
                node.execute("COMMIT")
            finally:
                node.execute("DETACH DATABASE nat")
            rebuilt = True
    finally:
        node.close()
    return {"code": code, "name": name, "path": path, "rebuilt": rebuilt}


# ------------------------------------------------------------ on-node model
def _series_by_line(node):
    """(phc_id, medicine_id) -> (dates, demand ratios) from this node's own history.

    Lags must stay within one inventory line: several PHCs share a medicine
    and their rows interleave when sorted by date.
    """
    rows = node.execute(
        """
        SELECT h.phc_id, h.medicine_id, h.use_date, h.quantity, i.avg_daily_consumption
        FROM consumption_history h
        JOIN inventory i ON i.phc_id = h.phc_id AND i.medicine_id = h.medicine_id
        WHERE i.avg_daily_consumption > 0
        ORDER BY h.phc_id, h.medicine_id, h.use_date
        """
    ).fetchall()
    series = {}
    for phc_id, med_id, use_date, qty, adc in rows:
        d, vals = series.setdefault((phc_id, med_id), ([], []))
        d.append(date.fromisoformat(use_date))
        vals.append(float(qty) / float(adc))
    return series


def _design(series):
    """Feature rows for every medicine series + per-medicine holdout mask.

    Target = quantity ÷ avg_daily_consumption, so lines of any scale pool
    into one model and coefficients are scale-free.
    """
    X, y, train_idx, test_idx = [], [], [], []
    for med_id in sorted(series):
        dates, vals = series[med_id]
        start = len(y)
        for i, (d, q) in enumerate(zip(dates, vals)):
            w7 = vals[max(0, i - 7):i]
            w30 = vals[max(0, i - 30):i]
            lag7 = sum(w7) / len(w7) if w7 else q
            lag30 = sum(w30) / len(w30) if w30 else q
            X.append(_row(d, i / 365.0, lag7, lag30))
            y.append(q)
        split = start + max(0, len(dates) - HOLDOUT)
        train_idx.extend(range(start, split))
        test_idx.extend(range(split, len(y)))
    return X, y, train_idx, test_idx


def _aggregates(conn):
    row = conn.execute(
        """
        SELECT COUNT(*) AS lines,
               COUNT(DISTINCT phc_id) AS phcs,
               SUM(CASE WHEN stock_qty <= 0 THEN 1 ELSE 0 END) AS stock_out,
               SUM(CASE WHEN stock_qty > 0 AND avg_daily_consumption > 0
                         AND stock_qty / avg_daily_consumption < 7 THEN 1 ELSE 0 END) AS critical,
               SUM(CASE WHEN stock_qty > 0 AND avg_daily_consumption > 0
                         AND stock_qty / avg_daily_consumption >= 7
                         AND stock_qty / avg_daily_consumption < 14 THEN 1 ELSE 0 END) AS low,
               AVG(CASE WHEN avg_daily_consumption > 0
                        THEN stock_qty / avg_daily_consumption END) AS avg_days
        FROM inventory
        """
    ).fetchone()
    hist = conn.execute("SELECT COUNT(*) FROM consumption_history").fetchone()[0]
    return {
        "lines_reported": row["lines"] or 0,
        "phcs": row["phcs"] or 0,
        "stock_out": row["stock_out"] or 0,
        "critical": row["critical"] or 0,
        "low": row["low"] or 0,
        "avg_days_cover": round(row["avg_days"] or 0, 1),
        "history_rows": hist,
    }


def local_fit(path):
    """Train Ridge on a node's own data — nothing leaves the node but weights."""
    from sklearn.linear_model import Ridge
    from sklearn.metrics import r2_score

    node = sqlite3.connect(path)
    node.row_factory = sqlite3.Row
    try:
        hist_rows = node.execute("SELECT COUNT(*) FROM consumption_history").fetchone()[0]
        if hist_rows < MIN_NODE_ROWS:
            return {"suppressed": True, "history_rows": hist_rows,
                    "aggregates": _aggregates(node) if hist_rows else None}
        series = _series_by_line(node)
        X, y, train_idx, test_idx = _design(series)
        if len(train_idx) < 30:
            return {"suppressed": True, "history_rows": hist_rows,
                    "aggregates": _aggregates(node)}
        model = Ridge(alpha=ALPHA)
        model.fit([X[i] for i in train_idx], [y[i] for i in train_idx])
        r2 = None
        if test_idx:
            preds = model.predict([X[i] for i in test_idx])
            try:
                r2 = float(r2_score([y[i] for i in test_idx], preds))
            except Exception:
                r2 = None
        return {
            "suppressed": False,
            "history_rows": hist_rows,
            "aggregates": _aggregates(node),
            "coef": [round(float(c), 6) for c in model.coef_],
            "intercept": round(float(model.intercept_), 6),
            "n_train": len(train_idx),
            "holdout_r2": round(r2, 3) if r2 is not None else None,
        }
    finally:
        node.close()


def _fedavg(fits):
    """Weighted average of node coefficients (FedAvg)."""
    usable = [f for f in fits if not f.get("suppressed") and f.get("coef")]
    total = sum(f["n_train"] for f in usable)
    if not usable or total == 0:
        return None
    dim = len(usable[0]["coef"])
    coef = [0.0] * dim
    intercept = 0.0
    for f in usable:
        w = f["n_train"] / total
        for i in range(dim):
            coef[i] += f["coef"][i] * w
        intercept += f["intercept"] * w
    return {
        "coef": [round(c, 6) for c in coef],
        "intercept": round(intercept, 6),
        "train_rows": total,
        "nodes": len(usable),
        "weighted_local_r2": round(
            sum((f["holdout_r2"] or 0) * f["n_train"] for f in usable) / total, 3
        ),
    }


def _national_design(conn):
    """National holdout design for scoring the averaged model."""
    key = _fingerprint(conn)
    cached = getattr(_national_design, "cache", None)
    if cached and cached[0] == key:
        return cached[1]
    out = _design(_series_by_line(conn))
    _national_design.cache = (key, out)
    return out


def evaluate_fedavg(conn, fed):
    """Score the averaged coefficients on the national holdout."""
    if not fed:
        return None, None
    X, y, _, test_idx = _national_design(conn)
    if not test_idx:
        return None, None
    from sklearn.metrics import r2_score

    preds = [sum(c * v for c, v in zip(fed["coef"], X[i])) + fed["intercept"]
             for i in test_idx]
    actual = [y[i] for i in test_idx]
    try:
        r2 = round(float(r2_score(actual, preds)), 3)
    except Exception:
        r2 = None
    agree = sum(1 for p, a in zip(preds, actual) if abs(p - a) <= 0.2 * abs(a) + 1e-9)
    return r2, round(agree / len(actual), 3)


def run_federation(conn, state_ids=None, resync=False):
    """One full federation round -> payload for /api/federated/live."""
    started = time.time()
    q = "SELECT state_id, name, code FROM state"
    params = ()
    if state_ids:
        q += f" WHERE state_id IN ({','.join('?' * len(state_ids))})"
        params = tuple(state_ids)
    states = conn.execute(q + " ORDER BY state_id", params).fetchall()
    round_log = []

    # round 1: node sync
    t0 = time.time()
    syncs = [sync_node(conn, s, resync=resync) for s in states]
    rebuilt = sum(1 for s in syncs if s["rebuilt"])
    round_log.append({
        "round": 1, "phase": "node_sync", "participants": len(syncs),
        "result": f"{rebuilt} node DB(s) rebuilt, {len(syncs) - rebuilt} already fresh",
        "ms": int((time.time() - t0) * 1000),
    })

    # round 2: local training on each node
    t0 = time.time()
    fits, nodes = [], []
    for s in syncs:
        t_node = time.time()
        try:
            fit = local_fit(s["path"])
        except Exception as exc:  # a broken node must not sink the round
            fit = {"suppressed": True, "error": str(exc)}
        latency = int((time.time() - t_node) * 1000)
        agg = fit.get("aggregates")
        suppressed = fit.get("suppressed") or not agg or agg["history_rows"] < MIN_NODE_ROWS
        nodes.append({
            "node_id": f"NODE-{s['code']}",
            "state": s["name"],
            "status": "suppressed" if suppressed else "online",
            "latency_ms": latency,
            "rounds_joined": 0 if suppressed else 1,
            "local_aggregates": None if suppressed else agg,
            "local_model": None if suppressed else {
                "train_rows": fit.get("n_train"),
                "holdout_r2": fit.get("holdout_r2"),
                "coef_dim": len(fit.get("coef") or []) or None,
            },
            "error": fit.get("error"),
        })
        fits.append(fit)
    trained = sum(1 for n in nodes if n["status"] == "online")
    round_log.append({
        "round": 2, "phase": "local_fit", "participants": trained,
        "result": f"{trained} local Ridge model(s) trained on-node",
        "ms": int((time.time() - t0) * 1000),
    })

    # round 3: FedAvg + national holdout scoring
    t0 = time.time()
    fed = _fedavg(fits)
    fed_r2, agreement = evaluate_fedavg(conn, fed)
    round_log.append({
        "round": 3, "phase": "fedavg", "participants": fed["nodes"] if fed else 0,
        "result": (f"coefficients averaged over {fed['nodes']} node(s), "
                   f"holdout R² {fed_r2}" if fed else "no node produced a model"),
        "ms": int((time.time() - t0) * 1000),
    })

    reporting = [n for n in nodes if n["local_aggregates"]]
    lines = sum(n["local_aggregates"]["lines_reported"] for n in reporting)
    weighted_days = (
        sum(n["local_aggregates"]["avg_days_cover"] * n["local_aggregates"]["lines_reported"]
            for n in reporting) / lines if lines else 0
    )
    return {
        "query": "national_fedavg_demand_risk_v1",
        "coordinator": "National Command Center",
        "federation_id": f"FED-IN-{date.today():%Y%m%d}",
        "mode": "live",
        "rounds": len(round_log),
        "privacy": {
            "raw_rows_shared": False,
            "mechanism": "On-node Ridge training + weighted FedAvg coefficient averaging",
            "min_node_rows": MIN_NODE_ROWS,
            "noise": "None — only aggregates and model coefficients leave a node",
        },
        "nodes": nodes,
        "aggregated_result": {
            "nodes_reporting": len(reporting),
            "nodes_total": len(nodes),
            "lines": lines,
            "stock_out": sum(n["local_aggregates"]["stock_out"] for n in reporting),
            "critical": sum(n["local_aggregates"]["critical"] for n in reporting),
            "low": sum(n["local_aggregates"]["low"] for n in reporting),
            "weighted_avg_days_cover": round(weighted_days, 1),
            "fedavg_r2": fed_r2,
            "agreement_rate": agreement,
            "fedavg_train_rows": fed["train_rows"] if fed else 0,
        },
        "model_card": {
            "target": "quantity ÷ avg_daily_consumption (14-day holdout)",
            "features": FEATURE_NAMES,
            "algorithm": f"Ridge(alpha={ALPHA}), averaged across nodes",
            "alpha": ALPHA,
            "holdout_days": HOLDOUT,
            "coef": fed["coef"] if fed else None,
            "intercept": fed["intercept"] if fed else None,
            "train_rows": fed["train_rows"] if fed else 0,
            "weighted_local_r2": fed["weighted_local_r2"] if fed else None,
        },
        "round_log": round_log,
        "live_note": (
            "Live round: each state node DB is synced from its slice of the "
            "national data, trained on-node, and only aggregates plus model "
            "coefficients are sent to the coordinator. Raw rows never leave a node."
        ),
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "total_ms": int((time.time() - started) * 1000),
    }
