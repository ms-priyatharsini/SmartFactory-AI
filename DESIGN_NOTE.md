# SmartFactory AI — Design Note

## Data model

`users` stores login identity and role. `customers` and `products` are sales masters. `materials` stores raw/packaging master data and the current weighted-average reference rate. `bom(product_id, material_id, qty, unit)` defines standard material consumption per batch. `orders` and `order_lines` represent the field sales request; `invoices` and `payments` represent posted billing and collections. `production_runs` stores output, batch, labour and utilities; `run_materials` snapshots planned/actual quantities and the valuation rate used at the time of the run. `material_receipts` stores purchase/opening valuation layers. `stock_ledger` is the source of truth for on-hand balances. `audit_log` records key business actions. `order_sync_keys` prevents duplicate creation when the PWA retries a queued order.

## Stock and BOM calculation

A stock balance is `SUM(IN movements) - SUM(OUT movements)` by item type and item ID. The application never treats a manually overwritten balance as authoritative. A production run validates all material balances before posting, issues actual BOM consumption and receives the actual good packet count. Damaged pouches are issued separately; cartons are issued at the entered actual quantity. A dispatch posts finished goods OUT. Each movement references its source purchase, production run or order. The benchmark one-batch result is flour 120 kg, oil 19.5 L, spice 3.8 kg, pouches 306, cartons 21 and finished goods 238 before dispatch / 88 after dispatch.

## Variance

For each BOM line, consumption variance is `(actual − planned) / planned × 100`. Yield variance is `(actual good packets − expected packets) / expected packets × 100`. Absolute variance greater than 3% is flagged. The benchmark yield is −6% and oil consumption is +5%.

## Costing and valuation

Material valuation uses a quantity-weighted average: total receipt quantity × receipt rate divided by total receipt quantity, rounded to the nearest paise per unit. The production run snapshots this rate per material in `run_materials`. Run manufacturing cost includes BOM materials consumed, damaged pouches, labour and gas/power entered for that run. Cost per packet is total run cost divided by actual good packets. Benchmark cost is approximately ₹31.14 per packet. GST is excluded from manufacturing cost.

## Security and offline behavior

All business APIs require a logged-in session. Role decorators restrict write operations and reporting access; salesman order queries are scoped to the active salesman. Passwords are salted hashes for new seed data. Offline order drafts are kept in browser local storage and retried on the `online` event; the client-generated idempotency key protects against duplicate posts after an interrupted response.
