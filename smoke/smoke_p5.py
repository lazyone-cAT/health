import glob
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "backend")))

import app as appmod  # noqa: E402
import db as database  # noqa: E402
import federated  # noqa: E402

client = appmod.app.test_client()


def login(u, p):
    r = client.post("/api/login", json={"username": u, "password": p})
    assert r.status_code == 200, (u, r.status_code, r.get_json())
    return r.get_json()["user"]


def get(path, expect=200):
    r = client.get(path)
    body = r.get_json()
    assert r.status_code == expect, (path, r.status_code, str(body)[:500])
    return body


conn = database.get_db()

# ---------- unit: node DBs are built and hold exactly their state's rows ----
national = {r["code"]: r for r in conn.execute(
    """SELECT s.code,
              (SELECT COUNT(*) FROM phc p WHERE p.state_id = s.state_id) AS phcs,
              (SELECT COUNT(*) FROM inventory i
                 JOIN phc p ON p.phc_id = i.phc_id WHERE p.state_id = s.state_id) AS lines,
              (SELECT COUNT(*) FROM consumption_history h
                 JOIN phc p ON p.phc_id = h.phc_id WHERE p.state_id = s.state_id) AS hist
       FROM state s""")}
assert set(national) == {"OD", "CG", "TS"}, national.keys()
assert sum(v["phcs"] for v in national.values()) == 30

# first round (fresh or cached)
p1 = federated.run_federation(conn)
files = sorted(os.path.basename(f) for f in glob.glob(os.path.join(federated.NODES_DIR, "*.db")))
assert files == ["state_CG.db", "state_OD.db", "state_TS.db"], files
print("node files:", files)

assert p1["mode"] == "live" and p1["coordinator"] == "National Command Center"
assert p1["privacy"]["raw_rows_shared"] is False
assert "on-node" in p1["privacy"]["mechanism"].lower()
assert [r["phase"] for r in p1["round_log"]] == ["node_sync", "local_fit", "fedavg"]
assert len(p1["nodes"]) == 3

by_state = {n["state"]: n for n in p1["nodes"]}
names = {"Odisha": "OD", "Chhattisgarh": "CG", "Telangana": "TS"}
for sname, code in names.items():
    node = by_state[sname]
    assert node["node_id"] == f"NODE-{code}", node
    assert node["status"] == "online", node
    agg = node["local_aggregates"]
    assert agg["phcs"] == national[code]["phcs"], (sname, agg, national[code])
    assert agg["lines_reported"] == national[code]["lines"], (sname, agg, national[code])
    assert agg["history_rows"] == national[code]["hist"], (sname, agg, national[code])
    assert node["local_model"]["coef_dim"] == 10, node
    assert node["local_model"]["train_rows"] > 0
    assert node["latency_ms"] >= 0
    assert node["rounds_joined"] == 1

# aggregates in the payload match fresh national SQL (no cross-state bleed)
nat_agg = conn.execute(
    """SELECT COUNT(*) AS lines,
              SUM(CASE WHEN stock_qty <= 0 THEN 1 ELSE 0 END) AS so,
              SUM(CASE WHEN stock_qty > 0 AND avg_daily_consumption > 0
                       AND stock_qty/avg_daily_consumption < 7 THEN 1 ELSE 0 END) AS cr
       FROM inventory""").fetchone()
agg = p1["aggregated_result"]
assert agg["lines"] == nat_agg["lines"], (agg, nat_agg)
assert agg["stock_out"] == nat_agg["so"], (agg, nat_agg)
assert agg["critical"] == nat_agg["cr"], (agg, nat_agg)
assert agg["nodes_reporting"] == 3 and agg["nodes_total"] == 3
assert agg["fedavg_r2"] is not None and 0.5 <= agg["fedavg_r2"] <= 1, agg
assert agg["agreement_rate"] is not None and 0 <= agg["agreement_rate"] <= 1
assert agg["fedavg_train_rows"] > 0

card = p1["model_card"]
assert len(card["coef"]) == 10 and isinstance(card["intercept"], float)
assert card["holdout_days"] == 14 and card["alpha"] == 0.1
assert card["features"][0] == "dow_mon" and card["features"][-1] == "lag30"

# FedAvg really is the row-weighted mean of the local coefficients
weights = {n["state"]: n["local_model"]["train_rows"] for n in p1["nodes"]}
tot = sum(weights.values())
local = {n["state"]: n for n in p1["nodes"]}
# recompute local fits to get full coefficients
refit = [federated.local_fit(federated.node_path(c)) for c in ("OD", "CG", "TS")]
usable = [f for f in refit if not f.get("suppressed") and f.get("coef")]
w_total = sum(f["n_train"] for f in usable)
expect_coef = [sum(f["coef"][i] * f["n_train"] / w_total for f in usable) for i in range(10)]
for i in range(10):
    assert abs(expect_coef[i] - card["coef"][i]) < 1e-4, (i, expect_coef[i], card["coef"][i])
print("fedavg coef matches weighted local mean OK")

# ---------- idempotent: second round rebuilds nothing ----------------------
p2 = federated.run_federation(conn)
assert p2["round_log"][0]["result"].startswith("0 node DB(s) rebuilt"), p2["round_log"][0]
p3 = federated.run_federation(conn, resync=True)
assert p3["round_log"][0]["result"].startswith("3 node DB(s) rebuilt"), p3["round_log"][0]
print("fingerprint skip / resync OK")

# ---------- HTTP: admin sees all three nodes -------------------------------
login("admin", "admin123")
live = get("/api/federated/live")
assert live["mode"] == "live" and len(live["nodes"]) == 3
assert live["aggregated_result"]["fedavg_r2"] is not None
assert live["privacy"]["raw_rows_shared"] is False
demo = get("/api/federated/demo")
assert demo["demo_note"], "demo endpoint still available"

# second call is served from fresh nodes (fast path)
live2 = get("/api/federated/live")
assert live2["round_log"][0]["result"].startswith("0 node DB(s) rebuilt")
print("admin /api/federated/live OK")

# ---------- state officer: only own state ----------------------------------
login("odisha1", "state123")
od = get("/api/federated/live")
assert len(od["nodes"]) == 1 and od["nodes"][0]["state"] == "Odisha", od["nodes"]
assert od["aggregated_result"]["nodes_total"] == 1
assert od["aggregated_result"]["lines"] == national["OD"]["lines"]
print("state officer scoped OK")

# ---------- district officer: own state only -------------------------------
login("district1", "district123")
di = get("/api/federated/live")
assert len(di["nodes"]) == 1 and di["nodes"][0]["node_id"] == "NODE-OD", di["nodes"]
assert di["aggregated_result"]["fedavg_r2"] is not None
print("district officer scoped OK")

# ---------- phc_manager: 403 ----------------------------------------------
login("khariar1", "phc123")
r = client.get("/api/federated/live")
assert r.status_code == 403, r.status_code
print("phc_manager 403 OK")

# ---------- audit trail ----------------------------------------------------
login("admin", "admin123")
row = conn.execute(
    "SELECT COUNT(*) FROM audit_log WHERE action='federation_round'").fetchone()[0]
assert row >= 4, row
print(f"audit rows: {row}")

conn.close()
print("SMOKE P5 OK")
