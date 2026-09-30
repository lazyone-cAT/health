"""Demand forecasting — one scikit-learn Ridge model per (PHC, medicine).

Models train lazily on the 90-day consumption_history table, are cached in
memory, and are invalidated when a stock edit changes the projection inputs.
A 14-day recursive forecast gives a projected stock-out date; lines at risk
inside RISK_DAYS get a `forecast_risk` alert.
"""
import threading
from datetime import date, timedelta

from sklearn.linear_model import Ridge
from sklearn.metrics import r2_score

HORIZON = 14          # days forecast ahead
RISK_DAYS = 10        # forecast_risk alert threshold
HOLDOUT = 14          # last N days held out to report R²
ALPHA = 0.1
MIN_TRAIN_ROWS = 30

# day-of-week one-hot (7) + trend (day index / 365) + lag7 + lag30
_FEATURE_DIM = 7 + 1 + 2

_models = {}   # (phc, med) -> {"model", "r2", "n"}
_proj = {}     # (phc, med, stock, multiplier) -> projection dict
_history = None
_lock = threading.Lock()


# ---------------------------------------------------------------- features
def _row(date_, trend, lag7, lag30):
    dow = [0.0] * 7
    dow[date_.weekday()] = 1.0
    return dow + [trend, lag7, lag30]


def _matrix(dates, values):
    X, y = [], []
    for i, (d, q) in enumerate(zip(dates, values)):
        w7 = values[max(0, i - 7):i]
        w30 = values[max(0, i - 30):i]
        lag7 = sum(w7) / len(w7) if w7 else q
        lag30 = sum(w30) / len(w30) if w30 else q
        X.append(_row(d, i / 365.0, lag7, lag30))
        y.append(q)
    return X, y


# ---------------------------------------------------------------- history
def history_map(conn, refresh=False):
    """(phc_id, medicine_id) -> (dates, quantities), loaded once per process."""
    global _history
    with _lock:
        if _history is not None and not refresh:
            return _history
        dates, values = {}, {}
        for r in conn.execute(
            "SELECT phc_id, medicine_id, use_date, quantity FROM consumption_history"
            " ORDER BY phc_id, medicine_id, use_date"
        ):
            key = (r["phc_id"], r["medicine_id"])
            dates.setdefault(key, []).append(date.fromisoformat(r["use_date"]))
            values.setdefault(key, []).append(float(r["quantity"]))
        _history = {k: (dates[k], values[k]) for k in dates}
        return _history


# ---------------------------------------------------------------- training
def _train(dates, values):
    if len(dates) < MIN_TRAIN_ROWS:
        return None
    X, y = _matrix(dates, values)
    split = len(X) - HOLDOUT
    r2 = None
    if split > MIN_TRAIN_ROWS:
        model = Ridge(alpha=ALPHA)
        model.fit(X[:split], y[:split])
        try:
            r2 = float(r2_score(y[split:], model.predict(X[split:])))
        except Exception:
            r2 = None
    model = Ridge(alpha=ALPHA)
    model.fit(X, y)
    return {"model": model, "r2": r2, "n": len(X)}


def _bundle(key, hist):
    with _lock:
        if key in _models:
            return _models[key]
    dates, values = hist.get(key, ([], []))
    bundle = _train(dates, values) if dates else None
    with _lock:
        _models[key] = bundle
    return bundle


def invalidate(phc_id=None, medicine_id=None):
    """Drop cached models/projections after a stock edit or settings change."""
    with _lock:
        if phc_id is None:
            _models.clear()
            _proj.clear()
        else:
            for store in (_models, _proj):
                for k in list(store):
                    if k[0] == phc_id and (medicine_id is None or k[1] == medicine_id):
                        store.pop(k, None)


def models_trained():
    with _lock:
        trained = [b for b in _models.values() if b]
        rs = [b["r2"] for b in trained if b["r2"] is not None]
    return {
        "cached": len(_models),
        "trained": len(trained),
        "avg_r2": round(sum(rs) / len(rs), 3) if rs else None,
        "min_r2": round(min(rs), 3) if rs else None,
        "max_r2": round(max(rs), 3) if rs else None,
    }


# ---------------------------------------------------------------- predicting
def forecast_series(bundle, values, horizon=HORIZON):
    """Recursive `horizon`-day forecast; predicted lags feed back in."""
    hist = list(values)
    preds = []
    for i in range(1, horizon + 1):
        d = date.today() + timedelta(days=i)
        w7 = hist[-7:] or hist[-1:]
        w30 = hist[-30:] or hist[-1:]
        lag7 = sum(w7) / len(w7)
        lag30 = sum(w30) / len(w30)
        q = max(0.0, float(bundle["model"].predict([_row(d, len(hist) / 365.0, lag7, lag30)])[0]))
        preds.append(q)
        hist.append(q)
    return preds


def project_stockout(stock_qty, preds, multiplier=1.0):
    """Day index (1..len) at which stock hits zero, or None beyond horizon."""
    remaining = float(stock_qty or 0)
    if remaining <= 0:
        return 1
    for i, q in enumerate(preds, start=1):
        remaining -= q * multiplier
        if remaining <= 0:
            return i
    return None


def get_settings(conn):
    out = {"emergency_mode": False, "emergency_multiplier": 1.0}
    for r in conn.execute("SELECT key, value FROM settings"):
        if r["key"] == "emergency_mode":
            out["emergency_mode"] = r["value"] in ("1", "true", "True")
        elif r["key"] == "emergency_multiplier":
            try:
                out["emergency_multiplier"] = float(r["value"])
            except ValueError:
                pass
    return out


def multiplier_for(settings):
    return settings["emergency_multiplier"] if settings["emergency_mode"] else 1.0


def _projection(key, hist, stock_qty, multiplier, settings):
    proj_key = (key, round(float(stock_qty or 0), 3), round(multiplier, 3))
    with _lock:
        if proj_key in _proj:
            return _proj[proj_key]
    dates, values = hist.get(key, ([], []))
    bundle = _bundle(key, hist)
    if bundle is None:
        return None
    preds = forecast_series(bundle, values)
    days = project_stockout(stock_qty, preds, multiplier)
    result = {
        "phc_id": key[0],
        "medicine_id": key[1],
        "daily_avg": round(sum(preds) / len(preds), 2),
        "forecast": [round(p, 1) for p in preds],
        "days_to_stockout": days,
        "stockout_date": (date.today() + timedelta(days=days)).isoformat() if days else None,
        "r2": round(bundle["r2"], 3) if bundle["r2"] is not None else None,
        "trained_rows": bundle["n"],
        "emergency_mode": settings["emergency_mode"],
        "emergency_multiplier": multiplier,
    }
    with _lock:
        _proj[proj_key] = result
    return result


def line_forecast(conn, phc_id, medicine_id, stock_qty, hist=None, settings=None):
    """Forecast one inventory line -> dict, or None when history is missing."""
    hist = history_map(conn) if hist is None else hist
    settings = get_settings(conn) if settings is None else settings
    key = (phc_id, medicine_id)
    if key not in hist:
        return None
    return _projection(key, hist, stock_qty, multiplier_for(settings), settings)


def compute_forecasts(conn, clause="", params=(), limit=None):
    """Projected stock-out for every visible inventory line, soonest first."""
    hist = history_map(conn)
    settings = get_settings(conn)
    mult = multiplier_for(settings)
    rows = conn.execute(
        f"""
        SELECT i.phc_id, i.medicine_id, i.stock_qty, p.name AS phc_name,
               p.state_id, p.district_id, m.name AS medicine, m.unit
        FROM inventory i
        JOIN phc p ON p.phc_id = i.phc_id
        JOIN medicine m ON m.medicine_id = i.medicine_id
        WHERE 1=1 {clause}
        """,
        tuple(params),
    ).fetchall()
    out = []
    for r in rows:
        key = (r["phc_id"], r["medicine_id"])
        if key not in hist:
            continue
        proj = _projection(key, hist, r["stock_qty"], mult, settings)
        if proj is None:
            continue
        out.append(
            {
                **proj,
                "phc_name": r["phc_name"],
                "medicine": r["medicine"],
                "unit": r["unit"],
                "stock_qty": r["stock_qty"],
            }
        )
    out.sort(key=lambda x: (x["days_to_stockout"] is None, x["days_to_stockout"] or 0))
    return out[:limit] if limit else out


# ---------------------------------------------------------------- alerts
def refresh_forecast_alerts(conn):
    """Recompute `forecast_risk` alerts for every inventory line."""
    hist = history_map(conn)
    settings = get_settings(conn)
    mult = multiplier_for(settings)

    at_risk = set()
    for row in conn.execute(
        "SELECT i.phc_id, i.medicine_id, i.stock_qty, p.name AS phc_name, m.name AS med_name"
        " FROM inventory i JOIN phc p ON p.phc_id = i.phc_id"
        " JOIN medicine m ON m.medicine_id = i.medicine_id"
    ):
        key = (row["phc_id"], row["medicine_id"])
        if key not in hist:
            continue
        # Cheap prune: even at recent peak demand the line outlasts the window.
        values = hist[key][1]
        peak = (max(values[-30:]) if values else 0) * mult
        if peak > 0 and float(row["stock_qty"] or 0) / peak > RISK_DAYS:
            continue
        proj = _projection(key, hist, row["stock_qty"], mult, settings)
        if proj is None or proj["days_to_stockout"] is None or proj["days_to_stockout"] > RISK_DAYS:
            continue
        days = proj["days_to_stockout"]
        suffix = ", emergency x%.1f" % mult if settings["emergency_mode"] else ""
        message = (
            f"{row['phc_name']}: {row['med_name']} projected to run out on "
            f"{proj['stockout_date']} ({days}d, Ridge forecast{suffix})"
        )
        conn.execute(
            "INSERT INTO alerts (phc_id, medicine_id, alert_type, severity, days_of_stock, message)"
            " VALUES (?,?, 'forecast_risk', 'forecast_risk', ?, ?)"
            " ON CONFLICT (phc_id, medicine_id, alert_type) DO UPDATE SET"
            " days_of_stock = excluded.days_of_stock, message = excluded.message,"
            " status = CASE WHEN alerts.status = 'resolved' THEN 'open' ELSE alerts.status END,"
            " updated_at = CURRENT_TIMESTAMP",
            (row["phc_id"], row["medicine_id"], days, message),
        )
        at_risk.add(key)

    # Resolve forecast_risk alerts that are no longer at risk.
    if at_risk:
        pairs = [v for k in at_risk for v in k]
        placeholders = ",".join("(?,?)" for _ in at_risk)
        conn.execute(
            "UPDATE alerts SET status='resolved', updated_at=CURRENT_TIMESTAMP"
            " WHERE alert_type='forecast_risk' AND status='open'"
            f" AND (phc_id, medicine_id) NOT IN ({placeholders})",
            pairs,
        )
    else:
        conn.execute(
            "UPDATE alerts SET status='resolved', updated_at=CURRENT_TIMESTAMP"
            " WHERE alert_type='forecast_risk' AND status='open'"
        )
