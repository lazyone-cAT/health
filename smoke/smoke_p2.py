import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "backend")))

import app as appmod  # noqa: E402
import db as database  # noqa: E402

client = appmod.app.test_client()

def login(u, p):
    r = client.post("/api/login", json={"username": u, "password": p})
    assert r.status_code == 200, (u, r.status_code, r.get_json())
    return r.get_json()["user"]

def get(path, expect=200):
    r = client.get(path)
    body = r.get_json()
    assert r.status_code == expect, (path, r.status_code, str(body)[:300])
    return body

def post(path, body=None, expect=200):
    r = client.post(path, json=body or {})
    assert r.status_code == expect, (path, r.status_code, str(r.get_json())[:300])
    return r.get_json()

conn = database.get_db()
phc_beds = conn.execute("SELECT SUM(beds) FROM phc").fetchone()[0]
bed_rows = conn.execute("SELECT COUNT(*) FROM bed_capacity").fetchone()[0]
att_rows = conn.execute("SELECT COUNT(*) FROM staff_attendance").fetchone()[0]
khariar = conn.execute("SELECT phc_id, beds FROM phc WHERE name='Khariar PHC'").fetchone()
durg = conn.execute("SELECT phc_id, beds FROM phc WHERE name='Durg PHC'").fetchone()
junagarh = conn.execute("SELECT phc_id FROM phc WHERE name='Junagarh PHC'").fetchone()
conn.close()
print(f"bed_rows={bed_rows} att_rows={att_rows} total_beds={phc_beds}")
assert bed_rows == 120, bed_rows
assert att_rows == 30 * 5 * 7, att_rows

# ---- admin ----
login("admin", "admin123")
ov = get("/api/overview")
s = ov["stats"]
assert s["beds_total"] == phc_beds and s["beds_occupied"] > 0, s
assert s["staff_total"] > 0 and s["staff_present"] > 0, s
assert s["beds_available"] == s["beds_total"] - s["beds_occupied"]
beds = get("/api/beds")
assert beds["summary"]["phcs"] == 30 and len(beds["beds"]) == 30, beds["summary"]
assert sum(len(b["types"]) for b in beds["beds"]) == 120
for b in beds["beds"]:
    assert sum(t["total"] for t in b["types"]) == b["total"]
    assert all(0 <= t["occupied"] <= t["total"] for t in b["types"])
staff = get("/api/staff")
assert len(staff["today"]) == 30 and len(staff["trend"]) == 7, (len(staff["today"]), len(staff["trend"]))
assert staff["summary"]["present"] + staff["summary"]["on_leave"] <= staff["summary"]["staff"]
# update beds
post(f"/api/beds/{junagarh['phc_id']}", {"bed_type": "General Ward", "occupied": 3}, 200)
post(f"/api/beds/{junagarh['phc_id']}", {"bed_type": "General Ward", "occupied": 999}, 400)
post(f"/api/beds/{junagarh['phc_id']}", {"bed_type": "Nope", "occupied": 1}, 404)
post("/api/staff", {"phc_id": junagarh["phc_id"], "staff_role": "Nurse", "present": 99, "on_leave": 0}, 400)
post("/api/staff", {"phc_id": junagarh["phc_id"], "staff_role": "Nurse", "present": 2, "on_leave": 1}, 200)

# ---- district officer (Kalahandi) ----
login("district1", "district123")
beds = get("/api/beds")
assert beds["summary"]["phcs"] == 4, beds["summary"]
staff = get("/api/staff")
assert len(staff["today"]) == 4, len(staff["today"])
ov = get("/api/overview")
assert ov["stats"]["beds_total"] > 0 and ov["stats"]["staff_total"] > 0, ov["stats"]
post(f"/api/beds/{durg['phc_id']}", {"bed_type": "General Ward", "occupied": 1}, 403)
post("/api/staff", {"phc_id": durg["phc_id"], "staff_role": "Nurse", "present": 1, "on_leave": 0}, 403)
post(f"/api/beds/{junagarh['phc_id']}", {"bed_type": "General Ward", "occupied": 2}, 200)

# ---- state officer (Odisha) ----
login("odisha1", "state123")
beds = get("/api/beds")
assert beds["summary"]["phcs"] == 11, beds["summary"]
post(f"/api/beds/{durg['phc_id']}", {"bed_type": "General Ward", "occupied": 1}, 403)

# ---- phc manager (Khariar) ----
login("khariar1", "phc123")
beds = get("/api/beds")
assert beds["summary"]["phcs"] == 1, beds["summary"]
assert beds["beds"][0]["phc_id"] == khariar["phc_id"]
assert beds["summary"]["total"] == khariar["beds"]
staff = get("/api/staff")
assert len(staff["today"]) == 1 and staff["today"][0]["phc_id"] == khariar["phc_id"]
ov = get("/api/overview")
assert ov["stats"]["beds_total"] == khariar["beds"], ov["stats"]
post(f"/api/beds/{durg['phc_id']}", {"bed_type": "General Ward", "occupied": 1}, 403)
post(f"/api/beds/{khariar['phc_id']}", {"bed_type": "General Ward", "occupied": 5}, 200)
post("/api/staff", {"phc_id": durg["phc_id"], "staff_role": "Nurse", "present": 1, "on_leave": 0}, 403)
get("/api/beds?phc_id=1", 403)

print("ALL P2 SMOKE CHECKS PASSED")
