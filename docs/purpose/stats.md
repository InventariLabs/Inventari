# Statistics

## Job
"See how things are actually going — what gets used, what gets thrown away, what is about to."

## Whose job
Anyone may look, including a viewer. Nobody comes here to do work; they come here to decide whether
some work is needed.

## Inside the boundary
Analysis over records that already exist: consumption over time, waste, rotation, what is close to
expiring, cost and spend, the spend forecast, purchase patterns, smart alerts, the low-stock list, and
the widgets other screens embed to show a slice of it. The reconciliation report (the shelf against
the movement ledger and the cost layers) has a tab of its own, shown whatever the analytics setting
says. The analytics tab can be hidden per organization (`enable_analytics`), and the stock value on
the overview (`show_inventory_value`).

## Outside the boundary
- The records themselves → **Core — Inventory**, **warehouse**, and every owning module
- Acting on what the numbers say → **shopping_lists**, **purchase_orders**, **warehouse**

## Own concepts / Borrowed
**Own:** the analyses and the dashboard widgets.
**Borrowed:** everything it reads. Statistics introduces no noun of its own into the domain.

## Deliberately not done
- **No writing, ever.** Every route reads and its only permission is `stats:read`, deliberately:
  a screen that reports and also changes cannot be trusted to do either. The scheduled
  reconciliation pass the reconciliation tab compares against is not this module's: it is a Core
  job, which stores what it measured under a Core setting and warns the organization's
  administrators when a drift appears or stands. The tab only reads what it stored.
- **No report builder.** No custom dimensions, no saved queries, no pivot designer.
- **No scheduled reports by mail.** Reaching a person is the notification subsystem's job.
- **No prediction sold as fact.** A forecast is labelled as one or it is not shown.

## Switched off
Cannot be: statistics is one of the always-on modules. A screen that embeds one of its widgets must
still do without it when a widget has nothing to show or fails — a tile that renders an error, or a
dashboard that half-loads, is a defect in the embedding screen.
