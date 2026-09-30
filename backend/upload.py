"""Inventory file upload: detect columns, normalize names, preview, confirm.

Adapted from med_ops framework/file_processor.py — same 3-step flow
(upload -> preview -> confirm) but scoped to PHC inventory rows only.
"""
import difflib
import os
import re
import uuid

import pandas as pd

UPLOAD_DIR = os.path.join(os.path.dirname(__file__), "uploads")

COLUMN_PATTERNS = {
    "phc_name": {
        "headers": ["phc", "phc_name", "phc name", "facility", "facility_name",
                    "health centre", "centre", "center", "site", "location", "unit"],
        "patterns": [r"^phc", r"facility", r"health.{0,3}centre", r"health.{0,3}center", r"^site$", r"^location$"],
        "db_field": "phc_name",
    },
    "medicine_name": {
        "headers": ["medicine", "medicine_name", "medicine name", "drug", "drug_name",
                    "item", "item_name", "product", "sku"],
        "patterns": [r"^medicine", r"^drug", r"^item", r"^product", r"pharma"],
        "db_field": "medicine_name",
    },
    "stock_qty": {
        "headers": ["stock_qty", "stock", "stock quantity", "qty", "quantity",
                    "closing_stock", "closing stock", "on_hand", "available"],
        "patterns": [r"stock", r"^qty", r"quantity", r"closing", r"on.?hand"],
        "db_field": "stock_qty",
    },
    "avg_daily_consumption": {
        "headers": ["avg_daily_consumption", "avg daily consumption", "adc", "consumption",
                    "daily_usage", "daily usage", "usage", "avg_consumption", "avg daily usage"],
        "patterns": [r"consumpt", r"^adc$", r"daily.{0,3}usage", r"^usage$", r"avg.{0,5}daily"],
        "db_field": "avg_daily_consumption",
    },
}


def _norm(s):
    return re.sub(r"[^a-z0-9]+", " ", str(s).lower()).strip()


def read_file(path):
    ext = os.path.splitext(path)[1].lower()
    if ext == ".csv":
        for enc in ("utf-8-sig", "utf-8", "latin-1"):
            try:
                return pd.read_csv(path, encoding=enc)
            except UnicodeDecodeError:
                continue
        return pd.read_csv(path, encoding="utf-8", errors="replace")
    if ext in (".xlsx", ".xls"):
        return pd.read_excel(path)
    raise ValueError("Unsupported file type")


def detect_columns(df):
    """Map each file header to a db field using exact headers then fuzzy patterns."""
    mappings, unmapped = {}, []
    taken = set()
    for col in df.columns:
        raw = str(col).strip()
        key = _norm(raw)
        matched = None
        for field, spec in COLUMN_PATTERNS.items():
            if field in taken:
                continue
            if key in [_norm(h) for h in spec["headers"]]:
                matched = field
                break
        if matched is None:
            for field, spec in COLUMN_PATTERNS.items():
                if field in taken:
                    continue
                if any(re.search(p, key) for p in spec["patterns"]):
                    matched = field
                    break
        if matched:
            mappings[raw] = {"db_field": matched, "confidence": 1.0}
            taken.add(matched)
        else:
            unmapped.append(raw)
    return {"mappings": mappings, "unmapped_columns": unmapped, "detected_type": "inventory_stock"}


def _best_match(value, candidates, cutoff=0.6):
    if not value:
        return None, None
    v = _norm(value)
    if v in candidates:
        return candidates[v][0], 1.0
    close = difflib.get_close_matches(v, list(candidates.keys()), n=1, cutoff=cutoff)
    if close:
        score = difflib.SequenceMatcher(None, v, close[0]).ratio()
        return candidates[close[0]][0], round(score, 2)
    return None, 0.0


def build_lookup(conn):
    phcs = {_norm(r["name"]): (r["name"], r["phc_id"]) for r in conn.execute("SELECT name, phc_id FROM phc")}
    meds = {_norm(r["name"]): (r["name"], r["medicine_id"]) for r in conn.execute("SELECT name, medicine_id FROM medicine")}
    return phcs, meds


def to_number(v):
    if v is None or (isinstance(v, float) and pd.isna(v)) or str(v).strip() == "":
        return None
    try:
        return float(str(v).replace(",", "").strip())
    except ValueError:
        return None


def preview(conn, df, mappings):
    """Normalize every row, resolve names, flag errors and in-file duplicates."""
    phcs, meds = build_lookup(conn)
    field_cols = {info["db_field"]: col for col, info in mappings.items() if info.get("db_field")}
    if "phc_name" not in field_cols or "medicine_name" not in field_cols:
        raise ValueError("File must contain a PHC/facility column and a medicine/drug column")
    if "stock_qty" not in field_cols:
        raise ValueError("File must contain a stock quantity column")

    rows, seen = [], {}
    for idx, (_, src) in enumerate(df.iterrows()):
        phc_raw = src[field_cols["phc_name"]]
        med_raw = src[field_cols["medicine_name"]]
        phc_name, phc_score = _best_match(phc_raw, phcs)
        med_name, med_score = _best_match(med_raw, meds)
        stock = to_number(src[field_cols["stock_qty"]])
        adc = to_number(src[field_cols["avg_daily_consumption"]]) if "avg_daily_consumption" in field_cols else None

        errors = []
        if phc_name is None:
            errors.append(f"Unknown PHC '{phc_raw}'")
        if med_name is None:
            errors.append(f"Unknown medicine '{med_raw}'")
        if stock is None:
            errors.append("Stock quantity is not a number")
        if adc is not None and adc < 0:
            errors.append("Consumption cannot be negative")

        key = (phc_name, med_name)
        duplicate_of = None
        if not errors and key in seen:
            duplicate_of = seen[key]
        elif not errors:
            seen[key] = idx

        rows.append(
            {
                "row_index": idx,
                "phc_name": phc_name or str(phc_raw),
                "phc_match": phc_score,
                "medicine_name": med_name or str(med_raw),
                "medicine_match": med_score,
                "stock_qty": stock,
                "avg_daily_consumption": adc,
                "errors": errors,
                "duplicate_of": duplicate_of,
            }
        )

    valid = [r for r in rows if not r["errors"]]
    return {
        "total_rows": len(rows),
        "valid_rows": len(valid),
        "error_rows": len(rows) - len(valid),
        "duplicate_rows": sum(1 for r in rows if r["duplicate_of"] is not None),
        "column_mapping": mappings,
        "preview_rows": rows[:25],
        "all_rows": rows,
    }


def save_temp(file_storage):
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    ext = os.path.splitext(file_storage.filename or "")[1].lower()
    if ext not in (".csv", ".xlsx", ".xls"):
        raise ValueError("Use CSV or Excel (.xlsx/.xls)")
    upload_id = uuid.uuid4().hex[:12]
    path = os.path.join(UPLOAD_DIR, f"{upload_id}{ext}")
    file_storage.save(path)
    return upload_id, path, ext.lstrip(".")


def confirm(conn, temp_path, username, in_scope=None):
    """Apply previewed rows: upsert inventory, then refresh alerts.

    `in_scope(conn, phc_id)` (optional) drops rows whose facility falls outside
    the uploader's state/district/PHC scope.
    """
    from stock import refresh_alerts

    df = read_file(temp_path)
    detection = detect_columns(df)
    result = preview(conn, df, detection["mappings"])

    inserted = updated = rejected = out_of_scope = 0
    for row in result["all_rows"]:
        if row["errors"]:
            rejected += 1
            continue
        phc_id = conn.execute("SELECT phc_id FROM phc WHERE name = ?", (row["phc_name"],)).fetchone()[0]
        if in_scope is not None and not in_scope(conn, phc_id):
            out_of_scope += 1
            rejected += 1
            continue
        med_id = conn.execute("SELECT medicine_id FROM medicine WHERE name = ?", (row["medicine_name"],)).fetchone()[0]
        adc = row["avg_daily_consumption"]
        existing = conn.execute(
            "SELECT id FROM inventory WHERE phc_id = ? AND medicine_id = ?", (phc_id, med_id)
        ).fetchone()
        if existing:
            sets = ["stock_qty = ?", "updated_at = CURRENT_TIMESTAMP"]
            params = [row["stock_qty"]]
            if adc is not None:
                sets.append("avg_daily_consumption = ?")
                params.append(adc)
            conn.execute(
                f"UPDATE inventory SET {', '.join(sets)} WHERE id = ?", (*params, existing["id"])
            )
            updated += 1
        else:
            conn.execute(
                "INSERT INTO inventory (phc_id, medicine_id, stock_qty, avg_daily_consumption) VALUES (?,?,?,?)",
                (phc_id, med_id, row["stock_qty"], adc if adc is not None else 0),
            )
            inserted += 1

    refresh_alerts(conn)
    _ = username
    return {"rows_inserted": inserted, "rows_updated": updated, "rows_rejected": rejected,
            "rows_out_of_scope": out_of_scope, "alerts_refreshed": True}
