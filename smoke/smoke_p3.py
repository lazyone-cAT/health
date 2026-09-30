import os
import sys
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "backend")))

t0 = time.time()
import app as appmod  # noqa: E402
import db as database  # noqa: E402
print(f"import+bootstrap: {time.time()-t0:.1f}s")

client = appmod.app.test_client()

def login(u, p):
    r = client.post("/api/login", json={"username": u, "password": p})
    assert r.status_code == 200, (u, r.status_code, r.get_json())
    return r.get_json()["user"]

def get(path, expect=200):
    t = time.time()
    r = client.get(path)
    body = r.get_json()
    print(f"  GET {path} -> {r.status_code} ({time.time()-t:.2f}s)")
    assert r.status_code == expect, (path, r.status_code, str(body)[:400])
    return body

def post(path, body=None, expect=200):
    r = client.post(path, json=body or {})
    assert r.status_code == expect, (path, r.status_code, str(r.get_json())[:400])
    return r.get_json()

conn = database.get_db()
hist_rows = conn.execute("SELECT COUNT(*) FROM consumption_history").fetchone()[0]
settings_rows = conn.execute("SELECT COUNT(*) FROM settings").fetchone()[0]
fr_alerts = conn.execute("SELECT COUNT(*) FROM alerts WHERE alert_type='forecast_risk'").fetchone()[0]
all_alerts = conn.execute("SELECT COUNT(*) FROM alerts").fetchone()[0]
conn.close()
print(f"history={hist_rows} settings={settings_rows} forecast_risk={fr_alerts} all_alerts={all_alerts}")
assert hist_rows == 90 * 600, hist_rows
assert settings_rows == 2, settings_rows
assert fr_alerts > 0, fr_alerts

# ---- forecast status ----
login("admin", "admin123")
st = get("/api/forecast/status")
assert st["history_rows"] == 54000, st
assert st["trained"] > 0 and st["cached"] > 0, st
assert st["avg_r2"] is not None, st
assert st["avg_r2"] > 0.5, st
assert st["min_r2"] > 0, st
print("R²:", st["avg_r2"], "min", st["min_r2"], "max", st["max_r2"], "trained", st["trained"])

# ---- forecast listing (admin, national) ----
t = time.time()
fc = get("/api/forecast?limit=60")
print(f"  forecast compute: {time.time()-t:.2f}s")
rows = fc["forecast"]
assert rows, rows
days = [r["days_to_stockout"] for r in rows]
assert days == sorted(days, key=lambda d: (d is None, d or 0)), "not sorted soonest-first"
top = rows[0]
assert top["days_to_stockout"] is not None and top["days_to_stockout"] <= 10, top
assert top["r2"] is not None and top["stockout_date"], top
assert all(r["r2"] is not None for r in rows[:10])
# second call hits the projection cache
t = time.time()
get("/api/forecast?limit=60")
print(f"  forecast cached: {time.time()-t:.2f}s")

ov = get("/api/overview")
assert ov["forecast"]["top_risks"], ov["forecast"]
assert ov["forecast"]["models"]["trained"] > 0
assert ov["alerts_by_severity"]["forecast_risk"] > 0, ov["alerts_by_severity"]
print("alerts_by_severity:", ov["alerts_by_severity"])

al = get("/api/alerts")
fr = [a for a in al["alerts"] if a["severity"] == "forecast_risk"]
assert fr and al["counts"]["forecast_risk"] > 0, al["counts"]
assert fr[0]["status"] in ("open", "acknowledged")

# ---- settings ----
s = get("/api/settings")
assert s["emergency_mode"] is False and s["emergency_multiplier"] == 1.5, s
post("/api/settings", {"emergency_multiplier": 9.0}, 400)
post("/api/settings", {"emergency_multiplier": "abc"}, 400)
r = post("/api/settings", {"emergency_mode": True, "emergency_multiplier": 2.0})
assert r["settings"]["emergency_mode"] is True and r["settings"]["emergency_multiplier"] == 2.0, r
fc2 = get("/api/forecast?limit=5")
assert fc2["settings"]["emergency_mode"] is True
assert all(r["emergency_multiplier"] == 2.0 for r in fc2["forecast"]), fc2["forecast"][0]
post("/api/settings", {"emergency_mode": False, "emergency_multiplier": 1.5})

# ---- stock edit invalidation: deplete a healthy line -> forecast_risk opens ----
conn = database.get_db()
line = conn.execute(
    """SELECT i.id, i.phc_id, i.medicine_id, p.name AS phc_name, m.name AS med_name, i.stock_qty
       FROM inventory i JOIN phc p ON p.phc_id=i.phc_id JOIN medicine m ON m.medicine_id=i.medicine_id
       WHERE i.avg_daily_consumption > 0 AND i.stock_qty > 0
         AND NOT EXISTS (SELECT 1 FROM alerts a WHERE a.phc_id=i.phc_id AND a.medicine_id=i.medicine_id
                         AND a.alert_type='forecast_risk')
       ORDER BY i.stock_qty / i.avg_daily_consumption DESC LIMIT 1"""
).fetchone()
conn.close()
print("depleting:", line["phc_name"], line["med_name"], line["stock_qty"])
post(f"/api/inventory/{line['id']}/stock", {"stock_qty": 1})
conn = database.get_db()
a = conn.execute(
    "SELECT * FROM alerts WHERE phc_id=? AND medicine_id=? AND alert_type='forecast_risk'",
    (line["phc_id"], line["medicine_id"]),
).fetchone()
conn.close()
assert a and a["status"] == "open" and a["days_of_stock"] <= 10, a
print("opened:", a["message"])
# restock far beyond horizon -> resolved
post(f"/api/inventory/{line['id']}/stock", {"stock_qty": 5000})
conn = database.get_db()
a = conn.execute(
    "SELECT status FROM alerts WHERE phc_id=? AND medicine_id=? AND alert_type='forecast_risk'",
    (line["phc_id"], line["medicine_id"]),
).fetchone()
conn.close()
assert a["status"] == "resolved", a
post(f"/api/inventory/{line['id']}/stock", {"stock_qty": line["stock_qty"]})

# ---- scoping ----
login("district1", "district123")
fc = get("/api/forecast?limit=100")
assert fc["forecast"], fc
conn = database.get_db()
kalahandi = conn.execute("SELECT district_id FROM district WHERE name='Kalahandi'").fetchone()[0]
khariar_pid = conn.execute("SELECT phc_id FROM phc WHERE name='Khariar PHC'").fetchone()[0]
conn.close()
# forecast rows carry phc_id only -> verify via inventory join
inv = get("/api/inventory")
assert inv["inventory"] and all(r["district_name"] == "Kalahandi" for r in inv["inventory"]), "scope leak"
get("/api/forecast?phc_id=%d" % khariar_pid, 403)
get("/api/settings", 200)  # read allowed for any role
r = post("/api/settings", {"emergency_multiplier": 1.5})  # district officer is in OFFICER_ROLES
assert r["status"] == "ok", r

login("khariar1", "phc123")
fc = get("/api/forecast?limit=50")
assert fc["forecast"] and all(r["phc_id"] == khariar_pid for r in fc["forecast"]), fc["forecast"][:2]
get("/api/forecast?district_id=%d" % kalahandi, 403)
ov = get("/api/overview")
assert ov["forecast"]["top_risks"] and all(
    r["phc_name"] == "Khariar PHC" for r in ov["forecast"]["top_risks"]
), ov["forecast"]["top_risks"]
post("/api/settings", {"emergency_mode": True}, 403)  # phc_manager may not change settings

print("ALL P3 SMOKE CHECKS PASSED")
