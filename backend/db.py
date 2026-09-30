"""Database connection, schema, and deterministic seed data.

National hierarchy: state -> district -> PHC -> inventory line.
The seed is deterministic (random.Random(42)) so the national DB and the
per-state federation node DBs (P5) can be regenerated identically.
"""
import os
import random
import sqlite3

DB_PATH = os.path.join(os.path.dirname(__file__), "phc_inventory.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS state (
    state_id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE NOT NULL,
    code TEXT UNIQUE NOT NULL
);

CREATE TABLE IF NOT EXISTS district (
    district_id INTEGER PRIMARY KEY AUTOINCREMENT,
    state_id INTEGER NOT NULL REFERENCES state(state_id),
    name TEXT NOT NULL,
    UNIQUE (state_id, name)
);

CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    full_name TEXT NOT NULL,
    role TEXT NOT NULL,
    phc_id INTEGER,
    state_id INTEGER,
    district_id INTEGER,
    is_active INTEGER DEFAULT 1,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS phc (
    phc_id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE NOT NULL,
    block TEXT NOT NULL,
    state_id INTEGER NOT NULL REFERENCES state(state_id),
    district_id INTEGER NOT NULL REFERENCES district(district_id),
    facility_type TEXT DEFAULT 'PHC',
    beds INTEGER DEFAULT 0,
    latitude REAL,
    longitude REAL
);

CREATE TABLE IF NOT EXISTS medicine (
    medicine_id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE NOT NULL,
    category TEXT NOT NULL,
    strength TEXT,
    unit TEXT NOT NULL DEFAULT 'unit',
    essential INTEGER DEFAULT 1
);

CREATE TABLE IF NOT EXISTS inventory (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    phc_id INTEGER NOT NULL REFERENCES phc(phc_id),
    medicine_id INTEGER NOT NULL REFERENCES medicine(medicine_id),
    stock_qty REAL NOT NULL DEFAULT 0,
    avg_daily_consumption REAL NOT NULL DEFAULT 0,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (phc_id, medicine_id)
);

CREATE TABLE IF NOT EXISTS alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    phc_id INTEGER NOT NULL REFERENCES phc(phc_id),
    medicine_id INTEGER NOT NULL REFERENCES medicine(medicine_id),
    alert_type TEXT NOT NULL,
    severity TEXT NOT NULL,
    days_of_stock REAL,
    message TEXT NOT NULL,
    status TEXT DEFAULT 'open',
    ack_by TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (phc_id, medicine_id, alert_type)
);

CREATE TABLE IF NOT EXISTS redistribution (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    from_phc_id INTEGER REFERENCES phc(phc_id),
    to_phc_id INTEGER NOT NULL REFERENCES phc(phc_id),
    medicine_id INTEGER NOT NULL REFERENCES medicine(medicine_id),
    quantity REAL NOT NULL,
    reason TEXT,
    status TEXT DEFAULT 'proposed',
    created_by TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    username TEXT,
    action TEXT NOT NULL,
    detail TEXT,
    state_id INTEGER,
    district_id INTEGER,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS upload_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    filename TEXT,
    uploaded_by TEXT,
    total_rows INTEGER DEFAULT 0,
    rows_inserted INTEGER DEFAULT 0,
    rows_updated INTEGER DEFAULT 0,
    rows_rejected INTEGER DEFAULT 0,
    status TEXT DEFAULT 'preview',
    temp_path TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    confirmed_at TEXT
);
"""

MEDICINES = [
    ("Paracetamol 500mg", "Analgesic", "500mg", "tablet"),
    ("Ibuprofen 400mg", "Analgesic", "400mg", "tablet"),
    ("Amoxicillin 500mg", "Antibiotic", "500mg", "capsule"),
    ("Azithromycin 500mg", "Antibiotic", "500mg", "tablet"),
    ("Ceftriaxone 1g", "Antibiotic", "1g", "vial"),
    ("Metronidazole 400mg", "Antibiotic", "400mg", "tablet"),
    ("ORS Sachet", "Gastro", "20.5g", "sachet"),
    ("Pantoprazole 40mg", "Gastro", "40mg", "tablet"),
    ("Metformin 500mg", "NCD", "500mg", "tablet"),
    ("Amlodipine 5mg", "NCD", "5mg", "tablet"),
    ("Losartan 50mg", "NCD", "50mg", "tablet"),
    ("Salbutamol Inhaler", "Respiratory", "100mcg", "inhaler"),
    ("Albendazole 400mg", "Child Health", "400mg", "tablet"),
    ("Iron Folic Acid", "Maternal", "60mg", "tablet"),
    ("Ferrous Ascorbate", "Maternal", "100mg", "tablet"),
    ("Tetanus Toxoid", "Vaccine", "0.5ml", "vial"),
    ("Measles-Rubella Vaccine", "Vaccine", "0.5ml", "vial"),
    ("Vitamin D3 60K", "Supplement", "60K", "capsule"),
    ("Insulin Regular", "NCD", "100IU", "vial"),
    ("Levocetirizine 5mg", "Analgesic", "5mg", "tablet"),
]

# state -> [(district, [(phc_name, block, beds, (lat, lon)), ...]), ...]
GEOGRAPHY = [
    ("Odisha", "OD", [
        ("Kalahandi", [
            ("Junagarh PHC", "Junagarh", 18, (21.54, 82.93)),
            ("Dharamgarh PHC", "Dharamgarh", 20, (21.52, 83.31)),
            ("Kesinga PHC", "Kesinga", 16, (21.66, 83.19)),
            ("Narla PHC", "Narla", 12, (21.72, 83.13)),
        ]),
        ("Nuapada", [
            ("Khariar PHC", "Khariar", 14, (21.78, 82.71)),
            ("Boden PHC", "Boden", 10, (21.62, 82.88)),
            ("Karlakote PHC", "Karlakote", 8, (21.83, 82.66)),
            ("Sinapali PHC", "Sinapali", 11, (19.36, 83.90)),
        ]),
        ("Balangir", [
            ("Patnagarh PHC", "Patnagarh", 15, (20.45, 83.13)),
            ("Kantabanjhi PHC", "Kantabanjhi", 9, (20.47, 82.60)),
            ("Loisingha PHC", "Loisingha", 10, (20.88, 83.20)),
        ]),
    ]),
    ("Chhattisgarh", "CG", [
        ("Raipur", [
            ("Raipur Urban PHC", "Raipur Urban", 24, (21.25, 81.63)),
            ("Arang PHC", "Arang", 12, (21.53, 81.97)),
            ("Abhanpur PHC", "Abhanpur", 10, (21.47, 81.74)),
        ]),
        ("Durg", [
            ("Durg PHC", "Durg", 20, (21.19, 81.28)),
            ("Bhilai PHC", "Bhilai", 18, (21.21, 81.35)),
            ("Patan PHC", "Patan", 9, (20.99, 81.38)),
        ]),
        ("Bastar", [
            ("Jagdalpur PHC", "Jagdalpur", 16, (19.07, 82.00)),
            ("Kondagaon PHC", "Kondagaon", 10, (19.59, 81.66)),
            ("Narayanpur PHC", "Narayanpur", 8, (19.70, 81.08)),
        ]),
    ]),
    ("Telangana", "TS", [
        ("Warangal", [
            ("Warangal Rural PHC", "Warangal Rural", 22, (17.98, 79.59)),
            ("Narsampet PHC", "Narsampet", 12, (17.73, 79.75)),
            ("Elkathurthy PHC", "Elkathurthy", 9, (17.99, 79.53)),
            ("Geesugonda PHC", "Geesugonda", 11, (17.95, 79.68)),
        ]),
        ("Karimnagar", [
            ("Karimnagar PHC", "Karimnagar", 19, (18.44, 79.13)),
            ("Sircilla PHC", "Sircilla", 13, (18.39, 78.80)),
            ("Jammikunta PHC", "Jammikunta", 10, (18.28, 79.47)),
        ]),
        ("Nalgonda", [
            ("Nalgonda PHC", "Nalgonda", 17, (17.05, 79.27)),
            ("Miryalaguda PHC", "Miryalaguda", 12, (16.83, 79.56)),
            ("Devarakonda PHC", "Devarakonda", 9, (16.68, 78.93)),
        ]),
    ]),
]

USERS = [
    # username, password, full_name, role, phc_name, state, district
    ("admin", "admin123", "National Programme Admin", "admin", None, None, None),
    ("odisha1", "state123", "P. Das — Odisha State Officer", "state_officer", None, "Odisha", None),
    ("district1", "district123", "Dr. A. Mishra — District Officer", "district_officer", None, "Odisha", "Kalahandi"),
    ("khariar1", "phc123", "S. Sahu — Khariar PHC In-charge", "phc_manager", "Khariar PHC", "Odisha", "Nuapada"),
    ("junagarh1", "phc123", "R. Patel — Junagarh PHC In-charge", "phc_manager", "Junagarh PHC", "Odisha", "Kalahandi"),
]


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_schema(conn):
    conn.executescript(SCHEMA)


def _schema_is_current(conn):
    """Old (pre-national) schema files are rebuilt, not migrated — the DB is
    ephemeral on Render and re-seeds on every deploy anyway."""
    phc_cols = {r[1] for r in conn.execute("PRAGMA table_info(phc)")}
    if "state_id" not in phc_cols or "district_id" not in phc_cols:
        return False
    audit_cols = {r[1] for r in conn.execute("PRAGMA table_info(audit_log)")}
    return "state_id" in audit_cols


def _seed_if_empty(conn):
    if conn.execute("SELECT COUNT(*) FROM phc").fetchone()[0]:
        return

    state_ids, district_ids = {}, {}
    for state_name, code, districts in GEOGRAPHY:
        cur = conn.execute(
            "INSERT INTO state (name, code) VALUES (?,?)", (state_name, code)
        )
        state_ids[state_name] = cur.lastrowid
        for district_name, phcs in districts:
            cur = conn.execute(
                "INSERT INTO district (state_id, name) VALUES (?,?)",
                (state_ids[state_name], district_name),
            )
            district_ids[(state_name, district_name)] = cur.lastrowid
            for phc_name, block, beds, (lat, lon) in phcs:
                conn.execute(
                    "INSERT INTO phc (name, block, state_id, district_id, facility_type, beds, latitude, longitude)"
                    " VALUES (?,?,?,?, 'PHC', ?,?,?)",
                    (phc_name, block, state_ids[state_name],
                     district_ids[(state_name, district_name)], beds, lat, lon),
                )

    for name, category, strength, unit in MEDICINES:
        conn.execute(
            "INSERT INTO medicine (name, category, strength, unit, essential) VALUES (?,?,?,? ,1)",
            (name, category, strength, unit),
        )

    rng = random.Random(42)
    phc_ids = [r[0] for r in conn.execute("SELECT phc_id FROM phc ORDER BY phc_id")]
    med_rows = conn.execute("SELECT medicine_id FROM medicine ORDER BY medicine_id").fetchall()

    for phc_id in phc_ids:
        for med in med_rows:
            med_id = med["medicine_id"]
            adc = rng.choice([2, 4, 6, 8, 10, 14, 18, 24, 30, 40])
            roll = rng.random()
            if roll < 0.07:
                stock = 0
            elif roll < 0.20:
                stock = round(adc * rng.uniform(0.5, 6.5), 1)
            elif roll < 0.45:
                stock = round(adc * rng.uniform(7.0, 13.0), 1)
            elif roll < 0.75:
                stock = round(adc * rng.uniform(14.0, 22.0), 1)
            else:
                stock = round(adc * rng.uniform(23.0, 45.0), 1)
            conn.execute(
                "INSERT INTO inventory (phc_id, medicine_id, stock_qty, avg_daily_consumption) VALUES (?,?,?,?)",
                (phc_id, med_id, stock, adc),
            )

    from auth import hash_password

    phc_lookup = {r["name"]: r["phc_id"] for r in conn.execute("SELECT phc_id, name FROM phc")}
    for username, pwd, full_name, role, phc_name, state_name, district_name in USERS:
        state_id = state_ids.get(state_name)
        district_id = district_ids.get((state_name, district_name)) if district_name else None
        phc_id = phc_lookup.get(phc_name)
        if phc_id:
            row = conn.execute(
                "SELECT state_id, district_id FROM phc WHERE phc_id = ?", (phc_id,)
            ).fetchone()
            state_id, district_id = row["state_id"], row["district_id"]
        conn.execute(
            "INSERT INTO users (username, password_hash, full_name, role, phc_id, state_id, district_id)"
            " VALUES (?,?,?,?,?,?,?)",
            (username, hash_password(pwd), full_name, role, phc_id, state_id, district_id),
        )
    conn.execute(
        "INSERT INTO audit_log (username, action, detail) VALUES ('system','seed','Initial national PHC inventory seed created')"
    )


def bootstrap():
    if os.path.exists(DB_PATH):
        probe = sqlite3.connect(DB_PATH)
        try:
            has_phc = probe.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='phc'"
            ).fetchone()
            stale = bool(has_phc) and not _schema_is_current(probe)
        finally:
            probe.close()
        if stale:
            os.remove(DB_PATH)

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    init_schema(conn)
    _seed_if_empty(conn)
    conn.commit()
    conn.close()
    from stock import refresh_alerts

    conn = get_db()
    refresh_alerts(conn)
    conn.commit()
    conn.close()
