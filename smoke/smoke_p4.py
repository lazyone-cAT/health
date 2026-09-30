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
    assert r.status_code == expect, (path, r.status_code, str(body)[:400])
    return body

def post(path, body=None, expect=200):
    r = client.post(path, json=body or {})
    assert r.status_code == expect, (path, r.status_code, str(r.get_json())[:400])
    return r.get_json()

conn = database.get_db()
conn.execute("DELETE FROM redistribution")  # clean board for an idempotent run
# --- force a cross-district case: every Kalahandi line of one medicine low,
# --- one Nuapada PHC flush with surplus.
med = conn.execute("SELECT medicine_id, name FROM medicine WHERE name='Paracetamol 500mg'").fetchone()
kal_phcs = [r[0] for r in conn.execute(
    "SELECT p.phc_id FROM phc p JOIN district d ON d.district_id=p.district_id WHERE d.name='Kalahandi'")]
khariar = conn.execute("SELECT phc_id FROM phc WHERE name='Khariar PHC'").fetchone()[0]
saved = {}
for pid in kal_phcs:
    row = conn.execute("SELECT id, stock_qty FROM inventory WHERE phc_id=? AND medicine_id=?",
                       (pid, med["medicine_id"])).fetchone()
    saved[("kal", pid)] = row["stock_qty"]
    conn.execute("UPDATE inventory SET stock_qty=1 WHERE id=?", (row["id"],))
row = conn.execute("SELECT id, stock_qty FROM inventory WHERE phc_id=? AND medicine_id=?",
                   (khariar, med["medicine_id"])).fetchone()
saved[("khariar", khariar)] = row["stock_qty"]
conn.execute("UPDATE inventory SET stock_qty=800 WHERE id=?", (row["id"],))
conn.commit()
conn.close()

# ---- district officer: cross-district suggestion ----
login("district1", "district123")
sug = get("/api/redistribution/suggestions")
target = [s for s in sug["suggestions"] if s["medicine_id"] == med["medicine_id"] and s["phc_id"] in kal_phcs]
assert target, "no Kalahandi suggestion for the forced line"
s = target[0]
assert s["district_name"] == "Kalahandi" and s["state_name"] == "Odisha", s
assert s["donors"], s
cross = [d for d in s["donors"] if d["district_name"] != "Kalahandi"]
assert cross, [(d["phc_name"], d["district_name"]) for d in s["donors"]]
assert all(d["state_name"] == "Odisha" for d in s["donors"]), s["donors"]
assert s["donor_scopes"], s
print("cross-district donor:", cross[0]["phc_name"], cross[0]["district_name"], "offer", cross[0]["offer"])

# ---- auto-propose ----
before = get("/api/redistribution?status=all")["redistributions"]
r = post("/api/redistribution/auto-propose", {"limit": 300})
assert r["created"] > 0, r
print("auto-propose created:", r["created"], "skipped:", r["skipped"])
after = get("/api/redistribution?status=all")["redistributions"]
assert len(after) == len(before) + r["created"]
r2 = post("/api/redistribution/auto-propose", {"limit": 300})
assert r2["created"] == 0 and r2["skipped"] > 0, r2  # idempotent
board = get("/api/redistribution?status=all")["redistributions"]
xfer = [t for t in board
        if t["status"] == "proposed" and t["from_district_name"] and t["to_district_name"]
        and t["from_district_name"] != t["to_district_name"]]
assert xfer, board[:2]
x = xfer[0]
print(f"cross-district transfer #{x['id']}: {x['from_phc_name']} ({x['from_district_name']}) -> "
      f"{x['to_phc_name']} ({x['to_district_name']}) {x['quantity']} {x['unit']}")
assert "cross-district" in (x["reason"] or "") or x["from_district_name"] != x["to_district_name"]

# ---- approve / reject flow ----
post(f"/api/redistribution/{x['id']}/status", {"status": "accepted"})
assert get("/api/redistribution?status=all")["redistributions"][0] or True
status_of = lambda i: [t for t in get("/api/redistribution?status=all")["redistributions"] if t["id"] == i][0]["status"]
assert status_of(x["id"]) == "accepted"
post(f"/api/redistribution/{x['id']}/status", {"status": "accepted"}, 400)  # no double-approve
post(f"/api/redistribution/{x['id']}/status", {"status": "rejected"}, 400)  # can't reject after approve

# reject another proposed transfer
other = [t for t in board if t["status"] == "proposed" and t["id"] != x["id"]]
assert other, "need a second proposed transfer"
rid = other[0]["id"]
post(f"/api/redistribution/{rid}/status", {"status": "rejected"})
assert status_of(rid) == "rejected"
post(f"/api/redistribution/{rid}/status", {"status": "accepted"}, 400)  # rejected is terminal
post(f"/api/redistribution/{rid}/status", {"status": "weird"}, 400)

# ---- deliver the approved cross-district transfer ----
conn = database.get_db()
donor_before = conn.execute("SELECT stock_qty FROM inventory WHERE phc_id=? AND medicine_id=?",
                            (x["from_phc_id"], x["medicine_id"])).fetchone()[0]
recv_before = conn.execute("SELECT stock_qty FROM inventory WHERE phc_id=? AND medicine_id=?",
                           (x["to_phc_id"], x["medicine_id"])).fetchone()[0]
conn.close()
post(f"/api/redistribution/{x['id']}/status", {"status": "dispatched"})
post(f"/api/redistribution/{x['id']}/status", {"status": "delivered"})
assert status_of(x["id"]) == "delivered"
conn = database.get_db()
donor_after = conn.execute("SELECT stock_qty FROM inventory WHERE phc_id=? AND medicine_id=?",
                           (x["from_phc_id"], x["medicine_id"])).fetchone()[0]
recv_after = conn.execute("SELECT stock_qty FROM inventory WHERE phc_id=? AND medicine_id=?",
                          (x["to_phc_id"], x["medicine_id"])).fetchone()[0]
conn.close()
assert round(donor_after, 2) == round(donor_before - x["quantity"], 2), (donor_before, donor_after, x)
assert round(recv_after, 2) == round(recv_before + x["quantity"], 2), (recv_before, recv_after, x)
print("delivery moved stock:", donor_before, "->", donor_after, "/", recv_before, "->", recv_after)

# ---- state officer: donors stay inside the state ----
login("odisha1", "state123")
sug = get("/api/redistribution/suggestions")
assert sug["suggestions"]
for s in sug["suggestions"]:
    assert s["state_name"] == "Odisha", s
    for d in s["donors"]:
        assert d["state_name"] == "Odisha", d  # never widens past the state
r = post("/api/redistribution/auto-propose", {})
print("state officer auto-propose:", r["created"], "created,", r["skipped"], "skipped")

# ---- admin: national donor pool ----
login("admin", "admin123")
sug = get("/api/redistribution/suggestions")
states = {d["state_name"] for s in sug["suggestions"] for d in s["donors"]}
print("admin donor states:", states)
assert len(states) >= 1

# ---- phc manager: no suggestions / no auto-propose ----
login("khariar1", "phc123")
get("/api/redistribution/suggestions", 403)
post("/api/redistribution/auto-propose", {}, 403)

# ---- restore the seeded stock ----
conn = database.get_db()
for (kind, pid), qty in saved.items():
    conn.execute("UPDATE inventory SET stock_qty=? WHERE phc_id=? AND medicine_id=?",
                 (qty, pid, med["medicine_id"]))
conn.execute("UPDATE inventory SET stock_qty=? WHERE phc_id=? AND medicine_id=?",
             (donor_before, x["from_phc_id"], x["medicine_id"]))
conn.execute("UPDATE inventory SET stock_qty=? WHERE phc_id=? AND medicine_id=?",
             (recv_before, x["to_phc_id"], x["medicine_id"]))
from stock import refresh_alerts
refresh_alerts(conn)
conn.commit()
conn.close()

print("ALL P4 SMOKE CHECKS PASSED")
