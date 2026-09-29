# PHC Medicine Inventory — District Command Center

A district-level medicine inventory and redistribution tool for Primary Health Centres (PHCs).
Built from scratch: **Flask JSON API + React (Vite) frontend**.

Replaces manual stock compilation across PHCs with a single view: live stock positions,
days-of-cover computed by plain division, automatic stock-out alerts, and a redistribution
board for moving surplus stock between facilities.

---

## Stack

| Layer | Tech |
|-------|------|
| Backend | Flask (JSON API, session auth, RBAC decorators) |
| Frontend | React 18 + React Router, built with Vite |
| Database | SQLite (`backend/phc_inventory.db`, auto-seeded) |
| Upload | pandas — CSV/Excel, column auto-detect, fuzzy name matching |
| ML | None — stock-out logic is `stock ÷ avg_daily_consumption` |

## Stock-out logic (no black box)

```
days_of_stock   = stock_qty / avg_daily_consumption
status          = stock_out  when stock_qty <= 0
                  critical   when days < 7
                  low        when 7 <= days < 14
                  ok         when days >= 14
surplus         = stock_qty - (avg_daily_consumption * 14)
```

Alerts are recomputed after every stock edit, upload, and delivered transfer.

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

---

## Demo accounts

| Role | Username | Password | Sees |
|------|----------|----------|------|
| District Officer | `district1` | `district123` | All 8 PHCs, suggestions, upload, audit |
| Admin | `admin` | `admin123` | Everything + audit |
| PHC In-charge | `khariar1` | `phc123` | Khariar PHC only (row-scoped) |
| PHC In-charge | `junagarh1` | `phc123` | Junagarh PHC only |

---

## Screens

1. **Overview** — district KPIs, per-PHC rollup, most urgent alerts, severity buckets
2. **Inventory** — every PHC × medicine line, days-of-cover bars, filters, stock update modal, CSV export
3. **Medicines** — essential medicine catalogue with district stock and stock-out counts
4. **Alerts** — stock-out / critical / low lists, acknowledge & resolve, severity filter
5. **Redistribution** — auto suggestions (who can cover whom) + transfer board with status flow
6. **Upload** — CSV/Excel inventory upload with preview → validate → apply (staff only)
7. **Federated Demo** — hardcoded mock of a privacy-preserving cross-PHC query
8. **Audit Log** — every login, edit, upload, alert and transfer (staff only)

## RBAC

- `admin` — everything
- `district_officer` — district-wide read/write, upload, suggestions, audit
- `phc_manager` — **row-scoped to their own PHC** (inventory, alerts, transfers); upload/suggestions/audit return 403

Enforced by Flask decorators (`login_required`, `role_required`) plus a `current_scope()`
clause added to every query for PHC in-charges.

---

## Database schema

| Table | Purpose |
|-------|---------|
| `phc` | Facilities (name, block, district, beds, lat/lon) |
| `medicine` | Essential medicine catalogue |
| `inventory` | Stock line per PHC × medicine (`stock_qty`, `avg_daily_consumption`) |
| `alerts` | Computed stock-out/critical/low alerts with status workflow |
| `redistribution` | Transfers between PHCs (`proposed → accepted → dispatched → delivered`) |
| `users` | Accounts with role + optional PHC scope |
| `audit_log` | Action trail |
| `upload_history` | File upload records |

Seed: 8 PHCs, 20 medicines, 160 inventory lines, ~70 alerts, 4 users.

## API (summary)

```
POST /api/login · POST /api/logout · GET /api/me
GET  /api/overview · GET /api/phcs · GET /api/phcs/<id>
GET  /api/inventory · POST /api/inventory/<id>/stock
GET  /api/medicines · POST /api/medicines
GET  /api/alerts · POST /api/alerts/<id>/action
GET  /api/redistribution · GET /api/redistribution/suggestions
POST /api/redistribution · POST /api/redistribution/<id>/status
POST /api/upload · POST /api/upload/confirm · GET /api/upload/history
GET  /api/audit · GET /api/federated/demo
```

## Sample upload file

`backend/samples/inventory_upload_sample.csv` — includes deliberate bad rows to demonstrate validation:

```csv
PHC Name,Drug Name,Closing Stock,Avg Daily Usage
Khariar PHC,Paracetamol 500mg,400,10
```

---

## Project structure

```
backend/
├── app.py           # Flask routes + RBAC + SPA serving
├── auth.py          # password hash, login_required, role_required, audit helper
├── db.py            # schema + deterministic seed
├── stock.py         # stock-out logic, alerts, redistribution suggestions
├── upload.py        # CSV/Excel detect → preview → confirm
├── federated.py     # hardcoded federated demo payload
├── samples/         # sample inventory CSV with bad rows
└── requirements.txt
frontend/
├── src/
│   ├── App.jsx              # routes
│   ├── auth.jsx             # session context + role helpers
│   ├── api.js               # fetch wrapper
│   ├── styles.css           # editorial UI (adapted from med_ops CSS)
│   ├── components/          # Layout (sidebar), KPI/Panel/Chip/Modal helpers
│   └── pages/               # Overview, Inventory, Medicines, Alerts,
│                            # Redistribution, Upload, Federated, Audit, Login
└── vite.config.js           # /api proxy → :5000
samples/inventory_upload_sample.csv
```
