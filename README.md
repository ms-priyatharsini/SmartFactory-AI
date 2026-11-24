# SmartFactory AI — Order-to-Audit ERP Prototype

A responsive Flask + SQLite web app for the NIT Tiruchirappalli Winter Internship brief, **Order-to-Audit System for a Small Food Manufacturer**. It connects field orders, GST billing, production/BOM consumption, inventory movements, costing, collections and audit exports.

## Run locally

```bash
git clone https://github.com/ms-priyatharsini/SmartFactory-AI.git
cd SmartFactory-AI
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
python app.py
```

Open `http://127.0.0.1:5000`. On first run, the database is created and the benchmark master data is seeded. To reset the demo, stop the server, delete `smartfactory.db`, and restart (or run `python seed.py`).

Set a private `SECRET_KEY` environment variable before any shared deployment. The included demo credentials are intentionally public and must be changed before deployment. This is a learning prototype; do not enter real customer, GST or financial data.

## Demo logins

| Role | Username | Password |
|---|---|---|
| Factory admin | `admin` | `admin123` |
| Salesman A | `salesa` | `sales123` |
| Salesman B | `salesb` | `sales123` |
| Production supervisor | `production` | `prod123` |
| Auditor | `auditor` | `audit123` |
| Owner | `owner` | `owner123` |

Passwords for newly seeded users are stored as salted Werkzeug hashes. Legacy plaintext demo accounts are upgraded to a hash at successful login. API routes require a session and enforce role permissions; salesman order lists are scoped to the logged-in salesman, invoice approval/dispatch/payment are admin-only, production entry is production/admin, and audit/report views are read-only for auditor/owner. This is application-level prototype security, not a substitute for a production security review, HTTPS, secrets management, rate limiting and CSRF hardening.

## Features

### Sales and billing
- Mobile-friendly order capture; salesman can see only their own orders.
- Orders flow through submitted → verified/invoiced → dispatched.
- Idempotency key prevents duplicate orders when an offline order sync is retried.
- Stock availability is checked before approval; shortage is returned with requested, available and shortage quantities.
- 5% GST benchmark: Tamil Nadu customers receive CGST + SGST; other-state customers receive IGST.
- Invoice numbering includes the financial-year label.
- Downloadable PDF tax invoice endpoint and PDF link in the invoice register.
- Payments cannot exceed the outstanding invoice balance.

### Production and inventory
- BOM-driven production run with planned vs actual input quantities, good output, damaged pouches and cartons.
- Stock movements are recorded in a ledger with source document; balances are derived from that ledger.
- Material usage and yield variances above ±3% are flagged.
- Opening balances and purchase receipts carry valuation rates. Purchase rates update a quantity-weighted average valuation rate; each production run snapshots rates in `run_materials`.
- Separate raw/packaging and finished-goods balances.

### Costing
- Run cost includes consumed BOM materials, damaged pouches, labour and gas/power.
- Raw-material and packaging valuation uses weighted-average purchase cost (opening stock plus receipts).
- Labour and utilities are assigned directly to the run entered by the supervisor; they are divided by good packets produced.
- Cost-per-packet API: `/api/costing`. The benchmark run should be approximately **₹31.14 per good packet** (minor paise rounding can affect the last decimal).

### Reports and AI-style decision support
- CSV exports: `/api/export/sales`, `/api/export/stock`, `/api/export/production`, `/api/export/collections`.
- Production costing breakdown: `/api/costing`.
- Audit log and live stock ledger.
- Explainable rules flag reorder thresholds, production yield variance and material consumption variance. This is deterministic decision support, not a connected LLM and not statutory advice.

### Offline field orders
- The PWA shell caches core UI assets and the last successfully opened app page.
- If an order submission loses network connectivity, the browser stores it locally and attempts sync when connectivity returns.
- A stable client key makes retries idempotent. Offline order data stays in that browser until successfully synced; clear browser storage only after verifying pending orders have synced.

## Mandatory benchmark walkthrough and expected results

1. Record a flour purchase: 60 kg at ₹45/kg.
2. Run one Murukku 200 g batch: 40 kg flour, 10.5 L oil, 1.2 kg spice mix; 188 good packets, 6 damaged pouches, 9 cartons; labour ₹1,200 and gas/power ₹600.
3. Salesman A submits 150 packets to Retailer A (Tamil Nadu). Admin approves, downloads PDF invoice and dispatches.
4. Salesman B submits 120 packets to Distributor B (Karnataka). Approval must be blocked with a 32-packet shortage.
5. Record ₹4,000 against Retailer A's invoice.
6. Review stock, cost-per-packet and exports.

| Check | Expected |
|---|---:|
| Flour closing | 120 kg |
| Oil closing | 19.5 L |
| Spice mix closing | 3.8 kg |
| Pouch closing | 306 pieces |
| Carton closing | 21 pieces |
| Finished goods after run | 238 packets |
| Finished goods after dispatch | 88 packets |
| Yield variance | −6% (flagged) |
| Oil consumption variance | +5% (flagged) |
| Retailer A taxable value | ₹7,500.00 |
| CGST / SGST | ₹187.50 / ₹187.50 |
| Invoice total | ₹7,875.00 |
| Retailer A outstanding after payment | ₹3,875.00 |
| Distributor B shortage | 32 packets |
| Approx. cost per good packet | ₹31.14 |

### Cost calculation assumption

Weighted average flour rate = `(100 kg × ₹42 + 60 kg × ₹45) / 160 kg = ₹43.125/kg` (stored rounded to paise per unit). The run cost includes 40 kg flour, 10.5 L oil, 1.2 kg spice, 188 good pouches, 9 cartons, 6 damaged pouches, ₹1,200 labour and ₹600 utilities. Cost is divided by 188 good packets. No selling margin or tax is included in manufacturing cost.

## Database and traceability

- `users`, `customers`, `products`, `materials`, `bom`
- `orders`, `order_lines`, `invoices`, `payments`
- `production_runs`, `run_materials`, `material_receipts`
- `stock_ledger`, `audit_log`, `order_sync_keys`

Money is stored as integer paise. Material balances and finished-goods balances are calculated from signed stock ledger movements. Purchases, production and dispatches write source-labelled ledger rows. Production runs snapshot weighted-average material rates so later purchases do not rewrite historical run costs.

## Test the benchmark

After installing requirements:

```bash
python -m unittest test_benchmark.py
```

The test creates a temporary database and checks the mandatory production, invoice, dispatch, payment, shortage, stock and PDF invoice workflow.

## Stack choice

Flask keeps the server-side business rules readable and easy to explain; SQLite provides a relational transactional database with no separate database server for a local demo. HTML/CSS/JavaScript and a small service worker keep the salesman workflow lightweight and mobile-friendly.

## Remaining production-grade work

The prototype now covers the four previously listed pending features. It is not yet a statutory GST/e-invoice product: GST rates and place-of-supply logic are simplified to the internship scenario; company identity/GSTIN are sample values; credit-note cancellation, supplier master/purchase register, GSTR-1/3B filing exports, date-filtered ageing, batch/expiry/FEFO, Tally integration, live hosted deployment and external LLM integration are not implemented. Review all tax and accounting treatment with a qualified professional before real use.
