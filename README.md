# PHC MedSupply — Federated Health Supply-Chain Prototype

A national-scale medicine inventory, forecasting and redistribution tool for Primary
Health Centres (PHCs), with a **privacy-preserving federation layer** across state nodes.

Built from scratch: **Flask JSON API + React 18 (Vite) + SQLite**, seeded deterministically
with 3 states → 9 districts → 30 PHCs × 20 medicines.

Replaces manual stock compilation with a single view: live stock positions, days-of-cover
computed by plain division, Ridge demand forecasting, automatic alerts, cross-district
redistribution, and a live FedAvg federation round across per-state node databases.

---

## Stack

| Layer | Tech |
|-------|------|
| Backend | Flask (JSON API, session auth, RBAC + geography scoping) |
| Frontend | React 18 + React Router, built with Vite |
| Database | SQLite (`backend/phc_inventory.db`, auto-seeded, rebuilt-not-migrated) |
| ML | scikit-learn — per-line Ridge forecasting + federation FedAvg |
| Upload | pandas — CSV/Excel, column auto-detect, fuzzy name matching |
| Deployment | Free tier: `render.yaml` (build + gunicorn), ephemeral disk → re-seeds on deploy |

## Stock-out logic (no black box)

```
days_of_stock   = stock_qty / avg_daily_consumption
status          = stock_out  when stock_qty <= 0
                  critical   when days < 7
                  low        when 7 <= days < 14
                  ok         when days >= 14
surplus         = stock_qty - (avg_daily_consumption * 14)
```

Alerts (`stock_out`, `critical`, `low`, `forecast_risk`) are recomputed after every stock
edit, upload, delivered transfer and forecast refresh. Emergency mode (settings) multiplies
*forecast* demand only — never the threshold arithmetic above.

## Demand forecasting

- 90 days × 600 lines of `consumption_history` (54,000 rows, deterministic seed).
- One Ridge model (`alpha=0.1`) per PHC × medicine line: features = day-of-week (7) +
  trend + 7/30-day lags; last 14 days held out for R² (seeded data averages ≈ 0.77).
- 14-day horizon; a projected stock-out inside 10 days raises a `forecast_risk` alert.
- Emergency multiplier lives in `settings` (`emergency_multiplier`, 1.0–5.0).
- Model/forecast caches are invalidated on stock edits, uploads and settings changes.

## Federation (Option A architecture)

```
national DB (backend/phc_inventory.db)          per-state node DBs (backend/nodes/)
  ├─ drives the dashboard & coordinator   →     ├─ state_OD.db  (Odisha rows only)
  └─ the only place full rows live together     ├─ state_CG.db  (Chhattisgarh only)
                                                └─ state_TS.db  (Telangana only)
```

A federation round (`GET /api/federated/live`, officers/admin only):

1. **node_sync** — each state's slice is copied into its own node DB (fingerprint-checked;
   unchanged nodes are not rebuilt).
2. **local_fit** — every node trains a Ridge model on *its own* consumption history
   (demand ÷ ADC, scale-free ratios; per-line lags stay inside the line).
3. **fedavg** — coefficients are averaged weighted by training rows; the averaged model is
   scored on the national 14-day holdout (seeded data: R² ≈ 0.76, ≈ 99.8% agreement).

Only aggregates (counts, days-of-cover) and model coefficients leave a node — **raw
inventory/consumption rows never do**; nodes with < 5 history rows are suppressed
(small-cell protection). Every round is written to the audit log. Officers see only their
own state's node; `/api/federated/demo` keeps the original hardcoded mock for comparison.

## Data freshness (auto-refresh)

Overview, Alerts and Beds poll every **30 s** (`frontend/src/usePoll.jsx`), pause/resume on
tab visibility, and render a freshness line (`generated_at` + last update). If polling
fails or falls > 90 s behind, a stale banner shows the last good refresh time and keeps
retrying.

---

## Run

### Backend

```bash
cd backend
pip install -r requirements.txt
python app.py            # http://localhost:5000  (seeds DB on first run)
```

### Frontend (dev)

```bash
cd frontend
npm install
npm run dev              # http://localhost:5173  (proxies /api to :5000)
```

### Production (single origin)

```bash
cd frontend && npm run build
cd ../backend && python app.py    # serves frontend/dist at http://localhost:5000
```

## Demo accounts

| Role | Username | Password | Sees |
|------|----------|----------|------|
| Admin (national) | `admin` | `admin123` | All 3 states · 9 districts · 30 PHCs |
| State Officer | `odisha1` | `state123` | Odisha — 11 PHCs, 3 districts |
| District Officer | `district1` | `district123` | Kalahandi — 4 PHCs |
| PHC In-charge | `khariar1` | `phc123` | Khariar PHC only (row-scoped) |
| PHC In-charge | `junagarh1` | `phc123` | Junagarh PHC only (row-scoped) |

## Screens

1. **Overview** — scoped KPIs, geography drill-down with breadcrumbs, urgent alerts,
   severity buckets, demand-forecast panel with emergency toggle, auto-refresh
2. **Inventory** — PHC × medicine lines, days-of-cover bars, forecast column + CSV export,
   stock update modal
3. **Medicines** — essential catalogue with network stock and stock-out counts
4. **Alerts** — stock-out / critical / forecast-risk / low, acknowledge & resolve
5. **Beds & Staff** — aggregate bed capacity + 7-day duty staffing (no patient-level data)
6. **Redistribution** — cross-district suggestions, auto-propose, Approve/Reject/Dispatch
   status flow
7. **Upload** — CSV/Excel preview → validate → apply (officers/admin)
8. **Federated** — live per-state nodes, FedAvg round log, model card, privacy panel
9. **Audit Log** — every login, edit, upload, alert, transfer and federation round

## RBAC & scoping

| Role | Scope | Special |
|------|-------|---------|
| `admin` | all states | bypasses role gates |
| `state_officer` | own state | upload, settings, federation, audit |
| `district_officer` | own district | upload, redistribution, federation, audit |
| `phc_manager` | **own PHC rows** | own inventory/attendance edits only; officer endpoints → 403 |

Enforced twice: `login_required` / `role_required` decorators, and `geo_scope()` +
`scope_clause()` merged into every query. Geography query params outside the caller's
scope return 403 (e.g. a district officer requesting another state).

---

## Database schema

| Table | Purpose |
|-------|---------|
| `state` / `district` / `phc` | National geography hierarchy (3 / 9 / 30 rows) |
| `medicine` | Essential medicine catalogue (20) |
| `inventory` | Stock line per PHC × medicine (600) |
| `consumption_history` | 90 days of usage for forecasting (54,000) |
| `alerts` | Computed alerts + status workflow (≈500 open at seed) |
| `redistribution` | Transfers (`proposed → accepted → dispatched → delivered`, or rejected/cancelled) |
| `bed_capacity` / `staff_attendance` | Aggregate capacity & duty staffing (no patients) |
| `settings` | Emergency mode + multiplier |
| `users` / `audit_log` / `upload_history` | Accounts, action trail, uploads |

Rebuild-not-migrate: `db._schema_is_current()` fingerprints required tables/columns and
re-seeds stale files. Node DBs under `backend/nodes/` are generated and git-ignored.

## API (summary)

```
POST /api/login · POST /api/logout · GET /api/me
GET  /api/geography · GET /api/overview
GET  /api/inventory · POST /api/inventory/<id>/stock
GET  /api/medicines · POST /api/medicines
GET  /api/alerts · POST /api/alerts/<id>/action
GET  /api/forecast · GET /api/forecast/status · GET/POST /api/settings
GET  /api/beds · POST /api/beds/<phc_id> · GET /api/staff · POST /api/staff
GET  /api/phcs · GET /api/phcs/<id>
GET  /api/redistribution · GET /api/redistribution/suggestions
POST /api/redistribution · POST /api/redistribution/auto-propose
POST /api/redistribution/<id>/status
POST /api/upload · POST /api/upload/confirm · GET /api/upload/history
GET  /api/audit · GET /api/federated/demo · GET /api/federated/live
```

## Sample upload file

`backend/samples/inventory_upload_sample.csv` — includes deliberate bad rows to
demonstrate validation:

```csv
PHC Name,Drug Name,Closing Stock,Avg Daily Usage
Khariar PHC,Paracetamol 500mg,400,10
```

---

## Verification

```bash
python -m py_compile backend/*.py          # backend compiles
cd frontend && npm run build               # frontend builds

# API / RBAC / logic smokes (no browser needed)
python smoke/scoping.py                    # role × endpoint × data-visibility matrix
python smoke/smoke_p1.py                   # geography + scoping
python smoke/smoke_p2.py                   # beds + staff
python smoke/smoke_p3.py                   # forecasting + alerts + settings
python smoke/smoke_p4.py                   # redistribution + auto-propose
python smoke/smoke_p5.py                   # federation nodes + FedAvg + gating

# Headless Chrome smokes (Chrome at the path in each script; requires a running
# `python app.py` on :5000)
python smoke/browser_smoke.py              # all 9 screens, 0 JS exceptions
python smoke/browser_smoke_p3.py           # forecast/redirect/alerts content
python smoke/browser_smoke_p5.py           # live Federated screen + phc_manager gating
python smoke/browser_smoke_p6.py           # 30s poll tick + stale banner appear/recover
```

## Project structure

```
backend/
├── app.py           # Flask routes, RBAC, geo scoping, SPA serving
├── auth.py          # password hash, login_required, role_required, audit helper
├── db.py            # schema + deterministic seed + fingerprint rebuild
├── stock.py         # stock-out logic, alerts, donor pools, suggestions
├── forecast.py      # per-line Ridge training/caching, forecast_risk alerts, settings
├── federated.py     # FEDERATED_DEMO mock + live node sync / local fit / FedAvg
├── upload.py        # CSV/Excel detect → preview → confirm
├── nodes/           # generated per-state node DBs (git-ignored)
├── samples/         # sample inventory CSV with bad rows
└── requirements.txt
frontend/
├── src/
│   ├── App.jsx              # routes
│   ├── auth.jsx             # session context + role helpers
│   ├── api.js               # fetch wrapper
│   ├── usePoll.jsx          # 30s auto-refresh hook + freshness/stale banner
│   ├── styles.css           # editorial UI
│   ├── components/          # Layout (nav), GeoFilters, KPI/Panel/Chip helpers
│   └── pages/               # Overview, Inventory, Medicines, Alerts, Beds,
│                            # Redistribution, Upload, Federated, Audit, Login
└── vite.config.js           # /api proxy → :5000
smoke/                       # API + headless-browser verification scripts
render.yaml                  # free-tier deploy (build + gunicorn)
```
