"""Stock-out logic — plain division, no ML.

days_of_stock = stock_qty / avg_daily_consumption
"""
CRITICAL_DAYS = 7
LOW_DAYS = 14
SURPLUS_DAYS = 21
TARGET_DAYS = 14

SEVERITY_ORDER = {"stock_out": 0, "critical": 1, "forecast_risk": 2, "low": 3}


def days_of_stock(stock_qty, avg_daily_consumption):
    if avg_daily_consumption is None or avg_daily_consumption <= 0:
        return None
    return round(float(stock_qty) / float(avg_daily_consumption), 1)


def status_for(stock_qty, days):
    if stock_qty is not None and float(stock_qty) <= 0:
        return "stock_out"
    if days is None:
        return "ok"
    if days < CRITICAL_DAYS:
        return "critical"
    if days < LOW_DAYS:
        return "low"
    return "ok"


def severity_message(status, days, phc_name, med_name):
    if status == "stock_out":
        return f"{phc_name}: {med_name} is out of stock."
    if status == "critical":
        return f"{phc_name}: {med_name} runs out in {days} days."
    if status == "low":
        return f"{phc_name}: {med_name} covers only {days} days."
    return None


def evaluate_row(stock_qty, adc):
    days = days_of_stock(stock_qty, adc)
    return status_for(stock_qty, days), days


def refresh_alerts(conn):
    """Recompute alerts for every inventory line. Closes resolved, opens new."""
    rows = conn.execute(
        """
        SELECT i.id, i.phc_id, i.medicine_id, i.stock_qty, i.avg_daily_consumption,
               p.name AS phc_name, m.name AS med_name
        FROM inventory i
        JOIN phc p ON p.phc_id = i.phc_id
        JOIN medicine m ON m.medicine_id = i.medicine_id
        """
    ).fetchall()

    seen = []
    for r in rows:
        status, days = evaluate_row(r["stock_qty"], r["avg_daily_consumption"])
        if status == "ok":
            continue
        seen.append((r["phc_id"], r["medicine_id"], status))
        # Severity changed -> close the stale alert type first.
        # forecast_risk alerts are owned by forecast.py, never touched here.
        conn.execute(
            """
            UPDATE alerts SET status = 'resolved', updated_at = CURRENT_TIMESTAMP
            WHERE phc_id = ? AND medicine_id = ? AND alert_type NOT IN (?, 'forecast_risk')
              AND status IN ('open', 'acknowledged')
            """,
            (r["phc_id"], r["medicine_id"], status),
        )
        conn.execute(
            """
            INSERT INTO alerts (phc_id, medicine_id, alert_type, severity, days_of_stock, message, status)
            VALUES (?,?,?,?,?,?, 'open')
            ON CONFLICT (phc_id, medicine_id, alert_type) DO UPDATE SET
                days_of_stock = excluded.days_of_stock,
                message = excluded.message,
                status = CASE WHEN alerts.status = 'resolved' THEN 'open' ELSE alerts.status END,
                updated_at = CURRENT_TIMESTAMP
            """,
            (
                r["phc_id"],
                r["medicine_id"],
                status,
                status,
                days,
                severity_message(status, days, r["phc_name"], r["med_name"]),
            ),
        )

    # Close alerts whose inventory line recovered (keep acknowledged history).
    for r in rows:
        status, _ = evaluate_row(r["stock_qty"], r["avg_daily_consumption"])
        if status == "ok":
            conn.execute(
                """
                UPDATE alerts SET status = 'resolved', updated_at = CURRENT_TIMESTAMP
                WHERE phc_id = ? AND medicine_id = ? AND alert_type != 'forecast_risk'
                  AND status IN ('open', 'acknowledged')
                """,
                (r["phc_id"], r["medicine_id"]),
            )

    # Drop alerts that point at removed inventory lines.
    conn.execute(
        """
        DELETE FROM alerts WHERE NOT EXISTS (
            SELECT 1 FROM inventory i
            WHERE i.phc_id = alerts.phc_id AND i.medicine_id = alerts.medicine_id
        )
        """
    )

    # Ridge forecast_risk alerts (trained lazily, cached per line).
    from forecast import refresh_forecast_alerts

    refresh_forecast_alerts(conn)
    return len(seen)


def surplus_qty(stock_qty, adc, target_days=TARGET_DAYS):
    """Units above the district safety stock — eligible for redistribution."""
    if not adc or adc <= 0:
        return 0
    target = float(adc) * target_days
    return round(max(0.0, float(stock_qty) - target), 1)


def _donor_index(conn, clause="", params=()):
    """medicine_id -> surplus donors in this pool, richest stock first."""
    rows = conn.execute(
        f"""
        SELECT i.phc_id, i.medicine_id, i.stock_qty, i.avg_daily_consumption,
               p.name AS phc_name, d.name AS district_name, s.name AS state_name
        FROM inventory i
        JOIN phc p ON p.phc_id = i.phc_id
        JOIN district d ON d.district_id = p.district_id
        JOIN state s ON s.state_id = p.state_id
        WHERE 1=1 {clause}
        """,
        tuple(params),
    ).fetchall()
    index = {}
    for r in rows:
        surplus = surplus_qty(r["stock_qty"], r["avg_daily_consumption"])
        if surplus <= 0:
            continue
        index.setdefault(r["medicine_id"], []).append(
            {
                "phc_id": r["phc_id"],
                "phc_name": r["phc_name"],
                "district_name": r["district_name"],
                "state_name": r["state_name"],
                "surplus": surplus,
                "days": days_of_stock(r["stock_qty"], r["avg_daily_consumption"]),
            }
        )
    for med_id in index:
        index[med_id].sort(key=lambda d: d["days"] or 0, reverse=True)
    return index


def redistribution_suggestions(conn, clause="", params=(), limit=25, donor_pools=None):
    """For every non-OK line, find surplus PHCs that can cover the gap.

    `clause` scopes the PHCs that *need* stock. `donor_pools` is a list of
    (label, clause, params) searched narrowest-first: when a line cannot be
    covered inside its own district the search widens to the state (P4
    cross-district redistribution). Defaults to a single pool == `clause`.
    """
    if donor_pools is None:
        donor_pools = [(None, clause, params)]
    pools = [(label, _donor_index(conn, c, p)) for label, c, p in donor_pools]

    need_rows = conn.execute(
        f"""
        SELECT i.phc_id, i.medicine_id, i.stock_qty, i.avg_daily_consumption,
               p.name AS phc_name, d.name AS district_name, st.name AS state_name,
               m.name AS med_name, m.unit
        FROM inventory i
        JOIN phc p ON p.phc_id = i.phc_id
        JOIN district d ON d.district_id = p.district_id
        JOIN state st ON st.state_id = p.state_id
        JOIN medicine m ON m.medicine_id = i.medicine_id
        WHERE 1=1 {clause}
        """,
        tuple(params),
    ).fetchall()

    suggestions = []
    for r in need_rows:
        status, days = evaluate_row(r["stock_qty"], r["avg_daily_consumption"])
        if status == "ok":
            continue
        adc = r["avg_daily_consumption"]
        shortfall = round(max(0.0, TARGET_DAYS * adc - r["stock_qty"]), 1)
        if shortfall <= 0:
            shortfall = round(max(1.0, adc), 1)
        donors = []
        scopes_used = []
        remaining = shortfall
        # Merge pools narrowest-first; a donor only ever appears once so
        # surplus is never double-counted when the search widens.
        merged, seen = [], set()
        for label, index in pools:
            for d in index.get(r["medicine_id"], []):
                if d["phc_id"] == r["phc_id"] or d["phc_id"] in seen:
                    continue
                seen.add(d["phc_id"])
                merged.append({**d, "scope": label})
        for d in merged:
            if remaining <= 0:
                break
            take = round(min(d["surplus"], remaining), 1)
            if take <= 0:
                continue
            donors.append({**d, "offer": take})
            if d["scope"] not in scopes_used:
                scopes_used.append(d["scope"])
            remaining = round(remaining - take, 1)
        suggestions.append(
            {
                "phc_id": r["phc_id"],
                "phc_name": r["phc_name"],
                "district_name": r["district_name"],
                "state_name": r["state_name"],
                "medicine_id": r["medicine_id"],
                "medicine": r["med_name"],
                "unit": r["unit"],
                "status": status,
                "days_of_stock": days,
                "shortfall": shortfall,
                "donors": donors[:5],
                "donor_scopes": scopes_used,
                "can_cover": remaining <= 0,
            }
        )
        if len(suggestions) >= limit:
            break

    suggestions.sort(key=lambda s: SEVERITY_ORDER.get(s["status"], 9))
    return suggestions


def summary_stats(conn, clause="", params=()):
    """Aggregate stock position over the rows visible to the caller."""
    where = clause or ""
    args = tuple(params or ())
    total, stock_out, critical, low, covered = conn.execute(
        f"""
        SELECT COUNT(*),
               SUM(CASE WHEN i.stock_qty <= 0 THEN 1 ELSE 0 END),
               SUM(CASE WHEN i.stock_qty > 0 AND i.avg_daily_consumption > 0
                         AND i.stock_qty / i.avg_daily_consumption < ? THEN 1 ELSE 0 END),
               SUM(CASE WHEN i.stock_qty > 0 AND i.avg_daily_consumption > 0
                         AND i.stock_qty / i.avg_daily_consumption >= ? AND i.stock_qty / i.avg_daily_consumption < ?
                        THEN 1 ELSE 0 END),
               SUM(CASE WHEN i.avg_daily_consumption > 0 THEN i.stock_qty / i.avg_daily_consumption ELSE NULL END)
        FROM inventory i
        JOIN phc p ON p.phc_id = i.phc_id
        WHERE 1=1 {where}
        """,
        (CRITICAL_DAYS, CRITICAL_DAYS, LOW_DAYS) + args,
    ).fetchone()

    open_alerts = conn.execute(
        f"SELECT COUNT(*) FROM alerts a JOIN phc p ON p.phc_id = a.phc_id"
        f" WHERE a.status IN ('open','acknowledged') {where}",
        args,
    ).fetchone()[0]
    with_adc = conn.execute(
        f"SELECT COUNT(*) FROM inventory i JOIN phc p ON p.phc_id = i.phc_id"
        f" WHERE i.avg_daily_consumption > 0 {where}",
        args,
    ).fetchone()[0] or 0
    phcs, districts, states = conn.execute(
        f"""
        SELECT COUNT(*), COUNT(DISTINCT district_id), COUNT(DISTINCT state_id)
        FROM phc p WHERE 1=1 {where}
        """,
        args,
    ).fetchone()
    medicines = conn.execute("SELECT COUNT(*) FROM medicine").fetchone()[0]
    return {
        "states": states or 0,
        "districts": districts or 0,
        "phcs": phcs or 0,
        "medicines": medicines,
        "lines": total or 0,
        "stock_out": stock_out or 0,
        "critical": critical or 0,
        "low": low or 0,
        "open_alerts": open_alerts or 0,
        "avg_days_cover": round((covered or 0) / max(1, with_adc), 1),
    }
