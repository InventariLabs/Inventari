# Analytics & Insights Subsystem

- **Module**: `app.modules.stats` — `router.py` mounts the endpoints, `services.py` is a
  re-export hub over `_alerts_service.py`, `_purchase_service.py` and `query_service.py`
- **Core read-model helpers**: `app.services.analytics.*` — `overview.py`, `dashboard.py`,
  `cost.py`, `consumption.py`, `forecast.py`, `rotation.py`, `reconciliation.py`,
  `_outflow_value.py` for what the stock that left was worth, and `_common.py` for the
  organization's day, currency and stock value
- **Frontend**: `frontend/src/modules/stats/components/`

## Features

1. **Overview**: Aggregate counts (total items, locations, value, expired, expiring soon, low stock). The value
   comes from the valuation layers where the organization keeps them, and the response says
   which source it used (`value_source`) plus how many rows were left out for being in
   another currency.
2. **By-Storage / By-Category**: Breakdown of item counts and expiring-soon counts per
   storage location, and of item counts and value per category. The category value still
   reads `Item.purchase_price`: a valuation layer is kept per product template and carries
   neither a location nor a category, so there is nothing to group it by. That number
   therefore need not agree with the overview's, and closing that gap needs a decision about
   how a layer is attributed, not a query change.
3. **Expiry Forecast**: Items with an expiry date, counted into six windows — expired,
   today, tomorrow, this week (2–7 days), next 2 weeks (7–14), this month (14–30). Cut on
   the organization's own day, not the server's.
4. **Activity Feed**: Recent inventory events (created, consumed, moved, discarded).
5. **Consumption Stats**: Quantity and ledger value consumed and wasted over the last `days` days (default 30): the ten most consumed and ten most wasted products and the totals.
6. **Shopping Suggestions**: Products below their reorder threshold, then products used or discarded within the last week that now sit at or under their minimum, at most 20 rows, higher urgency first.
7. **Cost Analysis**: What came in (`total_spent`, receipts priced by the valuation layers) and what was thrown away (`total_wasted`) over a `period` (day, week, month or year; the monthly trend always covers six months), with the top five categories by spend and the top five wasted products. Waste appears twice under two distinct names: `waste_event_rate` (share of outflow *events* that were disposals, in `/stats/consumption`) and `waste_value_percentage` (share of spent *value* that went to waste, in `/stats/cost-analysis`).
8. **Rotation Analysis**: Stock age (average and median days the stock on hand has been sitting — not inventory turnover), slow movers (over 30 and up to 90 days), dead stock (over 90 days). Ages run from `Item.added_date`, and the accompanying values read `Item.purchase_price` — the same attribution gap as By-Storage / By-Category.
9. **Smart Alerts**: Automated warnings for records nobody has touched in 60 days
   (`FORGOTTEN_ITEM`), recurring products overdue for a purchase (`MISSING_STAPLE`) and stock
   expiring within 7 days (`EXPIRING_SOON`, critical at 2 days or fewer). Expired stock and
   stock below its reorder threshold raise no alert; the overview counts them.
10. **Expense Forecasting**: Predicts future spending based on 90-day history.
11. **Purchase Patterns**: Identifies recurring products, seasonal products and bulk buying opportunities over the last 180 days.
12. **Reconciliation**: Compares the shelf (the records summed) against the movement ledger and against the cost layers (see `docs/subsystems/STOCK.md`).

## API Endpoints

All endpoints are mounted under `/api/v1/stats`:

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/v1/stats/config` | The module's two toggles (`enable_analytics`, `show_inventory_value`), readable at the `stats:read` level |
| GET | `/api/v1/stats/overview` | Aggregate dashboard stats |
| GET | `/api/v1/stats/overview/stream` | Server-Sent Events stream of overview stats |
| GET | `/api/v1/stats/low-stock` | The products behind the overview's low-stock number, one row each |
| GET | `/api/v1/stats/by-location` | Stats grouped by storage location |
| GET | `/api/v1/stats/by-category` | Stats grouped by category |
| GET | `/api/v1/stats/expiry-forecast` | Items grouped by expiry window |
| GET | `/api/v1/stats/activity` | Recent inventory activity feed |
| GET | `/api/v1/stats/consumption` | Consumption statistics over a period |
| GET | `/api/v1/stats/shopping-suggestions` | Reorder suggestions for low stock |
| GET | `/api/v1/stats/cost-analysis` | Spend and waste breakdown (`?period=day\|week\|month\|year`) |
| GET | `/api/v1/stats/rotation-analysis` | Stock age, slow movers, dead stock |
| GET | `/api/v1/stats/smart-alerts` | Forgotten products, overdue staples and products expiring soon |
| GET | `/api/v1/stats/expense-forecast` | Predicted future spending (`?period=month`) |
| GET | `/api/v1/stats/purchase-patterns` | Recurring products and bulk-buying patterns |
| GET | `/api/v1/stats/reconciliation` | The shelf vs the movement ledger and vs the cost layers |

## Frontend

The `stats` module registers one page, `StatsPage`, in the inventory shell
(see `frontend/src/modules/stats/module.ts`), with three tabs: Overview
(`/inventory/stats`), Analytics (`/inventory/stats/analytics`, shown only while the
`enable_analytics` setting is on) and Reconciliation (`/inventory/stats/reconciliation`),
plus a settings section for the two toggles. It contributes nothing to the
`dashboard_widgets` slot.
