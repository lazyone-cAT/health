"""End-to-end RBAC/scoping matrix: role x endpoint x data visibility."""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "backend")))

import app as appmod  # noqa: E402
import db as database  # noqa: E402

client = appmod.app.test_client()

# ---------------- unauthenticated -------------------------------------------
for path in ("/api/overview", "/api/inventory", "/api/alerts", "/api/beds",
             "/api/federated/live", "/api/audit"):
    r = client.get(path)
    assert r.status_code == 401, (path, r.status_code)
print("unauthenticated -> 401 on all checked endpoints")

conn = database.get_db()
odisha = conn.execute("SELECT state_id FROM state WHERE name='Odisha'").fetchone()[0]
cg = conn.execute("SELECT state_id FROM state WHERE name='Chhattisgarh'").fetchone()[0]
kal = conn.execute("SELECT district_id FROM district WHERE name='Kalahandi'").fetchone()[0]
cg_district = conn.execute("SELECT district_id FROM district WHERE state_id=?", (cg,)).fetchone()[0]
khariar = conn.execute("SELECT phc_id FROM phc WHERE name='Khariar PHC'").fetchone()[0]
other_phc = conn.execute(
    "SELECT phc_id FROM phc WHERE phc_id != ? LIMIT 1", (khariar,)).fetchone()[0]


def expected(state_id=None, district_id=None, phc_id=None):
    where, params = "", []
    if phc_id:
        where, params = " WHERE p.phc_id = ?", [phc_id]
    elif district_id:
        where, params = " WHERE p.district_id = ?", [district_id]
    elif state_id:
        where, params = " WHERE p.state_id = ?", [state_id]
    row = conn.execute(
        f"SELECT COUNT(DISTINCT p.phc_id) phcs, COUNT(i.id) lines "
        f"FROM phc p LEFT JOIN inventory i ON i.phc_id = p.phc_id{where}", params
    ).fetchone()
    return row["phcs"], row["lines"]


ROLES = [
    ("admin", "admin123", "country", None, None, None),
    ("odisha1", "state123", "state", odisha, None, None),
    ("district1", "district123", "district", None, kal, None),
    ("khariar1", "phc123", "phc", None, None, khariar),
]

for username, password, level, state_id, district_id, phc_id in ROLES:
    r = client.post("/api/login", json={"username": username, "password": password})
    assert r.status_code == 200, (username, r.text)
    exp_phcs, exp_lines = expected(state_id, district_id, phc_id)

    ov = client.get("/api/overview").get_json()
    assert ov["level"] == level, (username, ov["level"], level)
    assert ov["stats"]["phcs"] == exp_phcs, (username, ov["stats"]["phcs"], exp_phcs)

    inv = client.get("/api/inventory").get_json()
    assert inv["count"] == exp_lines, (username, inv["count"], exp_lines)

    beds = client.get("/api/beds").get_json()
    assert beds["summary"]["phcs"] == exp_phcs, (username, beds["summary"]["phcs"])
    staff = client.get("/api/staff").get_json()
    assert staff["summary"]["phcs"] == exp_phcs, (username, staff["summary"]["phcs"])

    al = client.get("/api/alerts").get_json()
    assert al["generated_at"], username
    fc = client.get("/api/forecast").get_json()
    assert fc["generated_at"] and fc["horizon"] == 14, username
    geo = client.get("/api/geography")
    assert geo.status_code == 200, (username, geo.status_code)

    if phc_id:  # row-scoped role: every row must be their own PHC
        kh = conn.execute("SELECT name FROM phc WHERE phc_id=?", (khariar,)).fetchone()["name"]
        for a in al["alerts"]:
            assert a["phc_name"] == kh, (username, a["phc_name"])
        for row in inv["inventory"]:
            assert row["phc_name"] == kh, (username, row["phc_name"])
        for row in fc["forecast"]:
            assert row["phc_name"] == kh, (username, row["phc_name"])
    print(f"{username:11} level={level:8} phcs={exp_phcs:2} lines={exp_lines:3} ok")

# ---------------- endpoint gating matrix ------------------------------------
GATED = [
    ("GET", "/api/federated/live", {"admin": 200, "odisha1": 200, "district1": 200, "khariar1": 403}),
    ("GET", "/api/audit", {"admin": 200, "odisha1": 200, "district1": 200, "khariar1": 403}),
    ("GET", "/api/upload/history", {"admin": 200, "odisha1": 200, "district1": 200, "khariar1": 403}),
    ("GET", "/api/redistribution/suggestions", {"admin": 200, "odisha1": 200, "district1": 200, "khariar1": 403}),
    ("POST", "/api/settings", {"admin": 200, "odisha1": 200, "district1": 200, "khariar1": 403}),
    ("POST", "/api/upload", {"admin": 400, "odisha1": 400, "district1": 400, "khariar1": 403}),
]
CREDS = {u: p for u, p, *_ in ROLES}

for method, path, expect in GATED:
    for username, want in expect.items():
        client.post("/api/login", json={"username": username, "password": CREDS[username]})
        body = {"emergency_multiplier": 1.5} if path == "/api/settings" else {}
        r = client.post(path, json=body) if method == "POST" else client.get(path)
        assert r.status_code == want, (username, method, path, r.status_code, want)
    print(f"{method:4} {path:36} -> {expect}")

# ---------------- stock edit: officers + own-PHC manager only ---------------
client.post("/api/login", json={"username": "khariar1", "password": "phc123"})
own_line = conn.execute(
    "SELECT id, stock_qty, avg_daily_consumption FROM inventory WHERE phc_id=?",
    (khariar,)).fetchone()
r = client.post(f"/api/inventory/{own_line['id']}/stock",
                json={"stock_qty": own_line["stock_qty"],
                      "avg_daily_consumption": own_line["avg_daily_consumption"]})
assert r.status_code == 200, (r.status_code, r.get_json())
foreign_line = conn.execute(
    "SELECT id FROM inventory WHERE phc_id=? LIMIT 1", (other_phc,)).fetchone()
r = client.post(f"/api/inventory/{foreign_line['id']}/stock", json={"stock_qty": 999})
assert r.status_code in (403, 404), r.status_code
print("phc_manager: own line editable, foreign line blocked")

# ---------------- cross-scope geography params ------------------------------
CROSS = [
    ("district1", f"/api/overview?state_id={cg}", 403),          # other state
    ("odisha1", f"/api/overview?district_id={cg_district}", 403),  # other state's district
    ("khariar1", f"/api/overview?district_id={kal}", 403),         # PHC cannot pick district
    ("khariar1", f"/api/overview?phc_id={other_phc}", 403),        # other PHC
    ("district1", f"/api/overview?phc_id={khariar}", 403),         # Nuapada PHC, wrong district
    ("odisha1", f"/api/overview?state_id={odisha}", 200),          # own state
]
for username, path, want in CROSS:
    client.post("/api/login", json={"username": username, "password": CREDS[username]})
    r = client.get(path)
    assert r.status_code == want, (username, path, r.status_code, want)
print("cross-scope geography params -> 403 / own scope -> 200")

# ---------------- direct cross-state query as district officer --------------
client.post("/api/login", json={"username": "district1", "password": "district123"})
ov = client.get("/api/overview").get_json()
assert ov["stats"]["states"] == 1, ov["stats"]["states"]
client.post("/api/login", json={"username": "admin", "password": "admin123"})
ov = client.get("/api/overview").get_json()
assert ov["stats"]["states"] == 3, ov["stats"]["states"]
print("rollup: district sees 1 state, admin sees 3")

conn.close()
print("SCOPING MATRIX OK")
