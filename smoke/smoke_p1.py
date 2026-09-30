import json
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "backend")))

import app as appmod  # noqa: E402
import db as database  # noqa: E402

conn = database.get_db()
counts = {
    "states": conn.execute("SELECT COUNT(*) FROM state").fetchone()[0],
    "districts": conn.execute("SELECT COUNT(*) FROM district").fetchone()[0],
    "phcs": conn.execute("SELECT COUNT(*) FROM phc").fetchone()[0],
    "lines": conn.execute("SELECT COUNT(*) FROM inventory").fetchone()[0],
    "users": conn.execute("SELECT COUNT(*) FROM users").fetchone()[0],
    "alerts": conn.execute("SELECT COUNT(*) FROM alerts").fetchone()[0],
}
conn.close()
print("SEED:", counts)
assert counts["states"] == 3, counts
assert counts["districts"] == 9, counts
assert counts["phcs"] == 30, counts
assert counts["lines"] == 600, counts

client = appmod.app.test_client()

def login(u, p):
    r = client.post("/api/login", json={"username": u, "password": p})
    assert r.status_code == 200, (u, r.status_code, r.get_json())
    return r.get_json()["user"]

def get(path, expect=200):
    r = client.get(path)
    body = r.get_json()
    assert r.status_code == expect, (path, r.status_code, body)
    return body

def post(path, body=None, expect=200):
    r = client.post(path, json=body or {})
    assert r.status_code == expect, (path, r.status_code, r.get_json())
    return r.get_json()

# ---- admin: national ----
u = login("admin", "admin123")
print("admin role:", u["role"], u["state_name"], u["district_name"])
ov = get("/api/overview")
assert ov["level"] == "country" and len(ov["children"]) == 3, ov["level"]
assert ov["stats"]["phcs"] == 30 and ov["stats"]["lines"] == 600, ov["stats"]
geo = get("/api/geography")
assert len(geo["states"]) == 3
inv = get("/api/inventory")
assert inv["count"] == 600, inv["count"]
al = get("/api/alerts")
print("alerts:", al["counts"])
ov2 = get("/api/overview?state_id=%d" % geo["states"][0]["state_id"])
assert ov2["level"] == "state" and len(ov2["children"]) == 3, ov2["children"]
ov3 = get("/api/overview?state_id=%d&district_id=%d" % (
    geo["states"][0]["state_id"], geo["states"][0]["districts"][0]["district_id"]))
assert ov3["level"] == "district" and len(ov3["children"]) in (3, 4), ov3["children"]
ov4 = get("/api/overview?phc_id=1")
assert ov4["level"] == "phc", ov4["level"]
print("breadcrumb:", [c["label"] for c in ov4["breadcrumb"]])
phcs = get("/api/phcs")
assert len(phcs["phcs"]) == 30
meds = get("/api/medicines")
assert len(meds["medicines"]) == 20
aud = get("/api/audit")
assert len(aud["audit"]) > 0
sug = get("/api/redistribution/suggestions")
print("admin suggestions:", len(sug["suggestions"]))

# ---- state officer: Odisha ----
login("odisha1", "state123")
ov = get("/api/overview")
assert ov["level"] == "state" and len(ov["children"]) == 3, (ov["level"], len(ov["children"]))
assert ov["stats"]["states"] == 1 and ov["stats"]["phcs"] == 11, ov["stats"]
inv = get("/api/inventory")
assert inv["count"] == 220, inv["count"]
geo = get("/api/geography")
assert len(geo["states"]) == 1 and sum(len(s["districts"]) for s in geo["states"]) == 3
get("/api/overview?state_id=%d" % geo["states"][0]["state_id"], 200)
# cross-state probe -> 403
other = [s for s in get("/api/geography")["states"]]
cg_id = None
conn = database.get_db()
cg_id = conn.execute("SELECT state_id FROM state WHERE code='CG'").fetchone()[0]
kh_id = conn.execute("SELECT phc_id FROM phc WHERE name='Khariar PHC'").fetchone()[0]
other_phc = conn.execute("SELECT phc_id FROM phc WHERE name='Durg PHC'").fetchone()[0]
other_dist = conn.execute("SELECT d.district_id FROM district d JOIN state s ON s.state_id=d.state_id WHERE s.code='CG'").fetchone()[0]
conn.close()
get("/api/overview?state_id=%d" % cg_id, 403)
get("/api/inventory?district_id=%d" % other_dist, 403)
get("/api/inventory?phc_id=%d" % other_phc, 403)
get("/api/overview?phc_id=%d" % kh_id, 200)
post("/api/inventory/1/stock", {"stock_qty": 10}, 403) if False else None
# stock edit outside state
conn = database.get_db()
line = conn.execute(
    "SELECT i.id FROM inventory i JOIN phc p ON p.phc_id=i.phc_id WHERE p.name='Durg PHC' LIMIT 1"
).fetchone()[0]
conn.close()
post("/api/inventory/%d/stock" % line, {"stock_qty": 5}, 403)
get("/api/audit", 200)
post("/api/upload", {}, 400)  # officer allowed; no file -> 400

# ---- district officer: Kalahandi ----
u = login("district1", "district123")
print("district1:", u["state_name"], u["district_name"])
ov = get("/api/overview")
assert ov["level"] == "district" and len(ov["children"]) == 4, (ov["level"], len(ov["children"]))
assert ov["stats"]["districts"] == 1 and ov["stats"]["phcs"] == 4, ov["stats"]
inv = get("/api/inventory")
assert inv["count"] == 80, inv["count"]
names = {p["name"] for p in get("/api/phcs")["phcs"]}
assert names == {"Junagarh PHC", "Dharamgarh PHC", "Kesinga PHC", "Narla PHC"}, names
get("/api/overview?district_id=%d" % other_dist, 403)
get("/api/overview?phc_id=%d" % kh_id, 403)  # Khariar is Nuapada
# seed phc ids: district Kalahandi = first inserted (Junagarh=1)
ov = get("/api/overview?phc_id=1")
assert ov["level"] == "phc"
post("/api/inventory/%d/stock" % line, {"stock_qty": 5}, 403)  # Durg, other state
get("/api/audit", 200)

# ---- phc manager: Khariar ----
u = login("khariar1", "phc123")
print("khariar1:", u["phc_name"], u["district_name"])
ov = get("/api/overview")
assert ov["level"] == "phc", ov["level"]
assert ov["stats"]["phcs"] == 1 and ov["stats"]["lines"] == 20, ov["stats"]
inv = get("/api/inventory")
assert inv["count"] == 20, inv["count"]
assert all(r["phc_name"] == "Khariar PHC" for r in inv["inventory"])
get("/api/inventory?phc_id=1", 403)
get("/api/overview?state_id=%d" % cg_id, 403)
get("/api/audit", 403)
get("/api/upload/history", 403)
sug = get("/api/redistribution/suggestions", 403)
al = get("/api/alerts")
assert all(a["phc_name"] == "Khariar PHC" for a in al["alerts"])
# edit own line
conn = database.get_db()
my_line = conn.execute(
    "SELECT id FROM inventory WHERE phc_id = (SELECT phc_id FROM phc WHERE name='Khariar PHC') LIMIT 1"
).fetchone()[0]
conn.close()
post("/api/inventory/%d/stock" % my_line, {"stock_qty": 50, "avg_daily_consumption": 5}, 200)

print("ALL P1 SMOKE CHECKS PASSED")
