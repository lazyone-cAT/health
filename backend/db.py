"""Database connection, schema, and deterministic seed data."""
import os
import random
import sqlite3

DB_PATH = os.path.join(os.path.dirname(__file__), "phc_inventory.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    full_name TEXT NOT NULL,
    role TEXT NOT NULL,
    phc_id INTEGER,
    is_active INTEGER DEFAULT 1,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS phc (
    phc_id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE NOT NULL,
    block TEXT NOT NULL,
    district TEXT NOT NULL,
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

PHCS = [
    ("Khariar PHC", "Khariar", 14, (21.78, 82.71)),
    ("Boden PHC", "Boden", 10, (21.62, 82.88)),
    ("Narla PHC", "Narla", 12, (21.72, 83.13)),
    ("Kesinga PHC", "Kesinga", 16, (21.66, 83.19)),
    ("Junagarh PHC", "Junagarh", 18, (21.54, 82.93)),
    ("Dharamgarh PHC", "Dharamgarh", 20, (21.52, 83.31)),
    ("Karlakote PHC", "Karlakote", 8, (21.83, 82.66)),
    ("Ghumusar PHC", "Ghumusar", 9, (21.47, 82.79)),
]

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

BLOCK_DISTRICT = "Kalahandi"


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_schema(conn):
    conn.executescript(SCHEMA)


def _seed_if_empty(conn):
    if conn.execute("SELECT COUNT(*) FROM phc").fetchone()[0]:
        return

    for name, block, beds, (lat, lon) in PHCS:
        conn.execute(
            "INSERT INTO phc (name, block, district, facility_type, beds, latitude, longitude) VALUES (?,?,?,?,?,?,?)",
            (name, block, BLOCK_DISTRICT, "PHC", beds, lat, lon),
        )
    for name, category, strength, unit in MEDICINES:
        conn.execute(
            "INSERT INTO medicine (name, category, strength, unit, essential) VALUES (?,?,?,? ,1)",
            (name, category, strength, unit),
        )

    rng = random.Random(42)
    phc_ids = [r[0] for r in conn.execute("SELECT phc_id FROM phc")]
    med_rows = conn.execute("SELECT medicine_id, name FROM medicine").fetchall()

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

    users = [
        ("admin", "admin123", "District Programme Admin", "admin", None),
        ("district1", "district123", "Dr. A. Mishra — District Officer", "district_officer", None),
        ("khariar1", "phc123", "S. Sahu — Khariar PHC In-charge", "phc_manager", 1),
        ("junagarh1", "phc123", "R. Patel — Junagarh PHC In-charge", "phc_manager", 5),
    ]
    for username, pwd, full_name, role, phc_id in users:
        conn.execute(
            "INSERT INTO users (username, password_hash, full_name, role, phc_id) VALUES (?,?,?,?,?)",
            (username, hash_password(pwd), full_name, role, phc_id),
        )
    conn.execute(
        "INSERT INTO audit_log (username, action, detail) VALUES ('system','seed','Initial PHC inventory seed created')"
    )


def bootstrap():
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
