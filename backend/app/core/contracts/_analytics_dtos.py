"""Analytics read-model DTOs for the CoreAPI queries layer.

These are domain-neutral aggregate read-models (counts, sums, GROUP BY
results) exposed via ``core_api.queries``. They pass the 3-Vertical Test
(food, equipment, warehouse) and contain no business opinions — just the
aggregated facts that modules build dashboards and reports on.

Field names are kept compatible with the existing stats API responses so
the migration from module-local escape hatches to ``core_api.queries``
does not change the public JSON contract.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import BaseModel


# --------------------------------------------------------------------------- #
# Low stock
# --------------------------------------------------------------------------- #
class LowStockProductDTO(BaseModel):
    """One short product, as a reader would say it: how much, against what."""

    template_id: UUID
    name: str
    #: What stands on the shelves, summed over every record of the product.
    on_hand: float
    minimum: float
    #: A record of the product the reader can open: one on the shelves when
    #: there is one, otherwise the last record it left behind, so a used-up
    #: product keeps its details. ``None`` only for a product with no record.
    item_id: UUID | None = None
    uom_symbol: str | None = None


# --------------------------------------------------------------------------- #
# Overview
# --------------------------------------------------------------------------- #
class OverviewDTO(BaseModel):
    """High-level inventory health snapshot for an organization."""

    total_items: int
    total_locations: int
    expiring_soon: int
    expired: int
    low_stock: int
    #: Stock value, summed over the items themselves rather than over
    #: per-category subtotals — an organization whose products carry no
    #: category still has stock, and still has a value for it.
    total_value: float = 0.0
    #: False when the value is read off the records and none of them carries
    #: a price: ``total_value`` is then the sum of no prices, and a screen
    #: shows the value as unknown, not as 0.00.
    value_known: bool = True
    #: Where ``total_value`` came from: the valuation layers, or the
    #: catalogue price on the records. A screen that cannot say which is a
    #: screen whose number cannot be checked.
    value_source: str = 'purchase_price'
    #: Rows left out of ``total_value`` because their currency is neither the
    #: organization's nor unstated. Two currencies do not add, and leaving
    #: them out silently turns "we cannot total this" into "0.00".
    excluded_other_currency_count: int = 0
    #: Whom ``total_value`` is about: ``organization`` when it comes from the
    #: cost ledger, which knows products and not shelves, or ``locations``
    #: when it was summed over the records in the locations the counts use.
    #: The ledger branch used to take the storage filter and ignore it, so
    #: the tile counted one population and valued another without a word.
    value_scope: str = 'locations'
    #: Receipts on the shelf that were posted at no cost (nobody priced
    #: them). They add nothing to ``total_value``, so a tile that shows the
    #: figure without this count presents a lower bound as a total.
    unvalued_stock_count: int = 0
    #: Records on the shelves with no price, when the value is read off the
    #: records (no cost ledger). They add nothing to ``total_value``, so the
    #: figure beside a non-zero count is a lower bound.
    unpriced_item_count: int = 0
    #: Whether any record in this organization carries an expiry date. The
    #: other half of the question is what the storage types declare; a screen
    #: that asks only one of the two contradicts the screen next to it.
    tracks_expiry: bool = False


# --------------------------------------------------------------------------- #
# Per-storage breakdown
# --------------------------------------------------------------------------- #
class StorageStatsDTO(BaseModel):
    """Item counts and expiry aggregates for a single storage location."""

    location_id: UUID
    location_name: str
    location_type: str
    items_count: int
    expiring_soon: int


# --------------------------------------------------------------------------- #
# Per-category breakdown
# --------------------------------------------------------------------------- #
class CategoryStatsDTO(BaseModel):
    """Item counts and stock value aggregated per category."""

    category_id: UUID | None
    category_name: str
    category_code: str | None
    category_icon: str | None
    items_count: int
    total_value: float
    #: A category lives on the record, not in the cost ledger — a layer
    #: carries a product template and nothing else — so a per-category value
    #: can only be read off the records' own prices. Said here rather than
    #: left to be guessed from the number.
    value_source: str = 'purchase_price'
    #: Records in this category that carry no price and so add nothing to
    #: ``total_value``. Zero of them means the figure is complete.
    unpriced_count: int = 0


# --------------------------------------------------------------------------- #
# Expiry forecast
# --------------------------------------------------------------------------- #
class ExpiryBucketDTO(BaseModel):
    """A single time-bucketed expiry count (e.g. ``Today``, ``This week``)."""

    period: str
    count: int


# --------------------------------------------------------------------------- #
# Recent activity
# --------------------------------------------------------------------------- #
class ActivityDTO(BaseModel):
    """A single recent ItemHistory entry surfaced on the activity feed."""

    id: UUID
    action: str
    item_name: str
    created_at: datetime
    user_name: str | None = None
    details: dict[str, Any] | None = None


# --------------------------------------------------------------------------- #
# Consumption (usage + disposal)
# --------------------------------------------------------------------------- #
class ConsumptionItemDTO(BaseModel):
    """A product ranked by consumed or disposed quantity/value."""

    name: str
    category: str
    #: See ``CategoryCostDTO.category_code``.
    category_code: str | None = None
    quantity: float
    value: float


class CategoryConsumptionDTO(BaseModel):
    """Consumption totals aggregated per category."""

    category: str
    #: See ``CategoryCostDTO.category_code``.
    category_code: str | None = None
    total_quantity: float
    total_value: float


class ConsumptionStatsDTO(BaseModel):
    """Usage and disposal aggregates over a time window.

    Field names mirror the existing stats API response so the migration
    to ``core_api.queries`` is transparent to the frontend.
    """

    most_consumed: list[ConsumptionItemDTO]
    most_wasted: list[ConsumptionItemDTO]
    #: Share of outflow events that were disposals — counted per event,
    #: not per money (that one is ``CostSummaryDTO.waste_value_percentage``).
    #: Counted from history, so this one is answerable whether or not the
    #: window has valuation behind it.
    waste_event_rate: float | None = None
    #: ``None`` where the ledger has no outgoing value for the window — see
    #: ``CostSummaryDTO.total_wasted``.
    total_consumed_value: float | None
    total_wasted_value: float | None
    consumption_by_category: list[CategoryConsumptionDTO]


# --------------------------------------------------------------------------- #
# Cost summary
# --------------------------------------------------------------------------- #
class MonthlyTrendDTO(BaseModel):
    """A single month's spent and wasted totals, read from the cost ledger."""

    month: str
    spent: float
    wasted: float


class CategoryCostDTO(BaseModel):
    """Cost breakdown for a single category."""

    category_name: str
    #: The category's seed code, ``None`` for a category someone named
    #: themselves — the reader's language names a seeded category through
    #: it, and the name beside it is the fallback. A name alone forced every
    #: screen to print the seed's English.
    category_code: str | None = None
    total_spent: float
    total_wasted: float
    items_count: int
    #: ``total_spent`` is summed off the records' prices — see
    #: ``CategoryStatsDTO.value_source`` for why the ledger cannot answer a
    #: per-category question. ``total_wasted`` does come from the ledger.
    value_source: str = 'purchase_price'
    #: Records in the category and window with no price to sum.
    unpriced_count: int = 0


class SavingsOpportunityDTO(BaseModel):
    """A product whose waste cost suggests a savings action."""

    product_name: str
    category_name: str
    #: See ``CategoryCostDTO.category_code``.
    category_code: str | None = None
    wasted_amount: float
    suggestion: str


class CostSummaryDTO(BaseModel):
    """Cost analysis: spent, wasted, trends, and savings opportunities."""

    total_spent: float
    #: What the disposals cost, or ``None`` when the ledger has nothing to
    #: say about this window.
    #:
    #: The two are different answers and used to read the same. An outflow is
    #: priced when it happens; before the ledger kept outgoing value there is
    #: no price to read, and there is no honest way to invent one afterwards —
    #: today's average was not the average then. So the screen says it does
    #: not know, rather than printing a confident 0.00 over a month of waste.
    total_wasted: float | None
    #: Share of spent VALUE that went to waste, in percent — the money-side
    #: twin of ``ConsumptionStatsDTO.waste_event_rate``, which counts events.
    #: ``None`` for the same reason: a percentage of an unknown is unknown.
    waste_value_percentage: float | None = None
    #: Priced records the sum could not include because their price is in a
    #: currency this organization does not keep its books in. Without it, a
    #: total of zero is indistinguishable from having bought nothing.
    excluded_other_currency_count: int = 0
    #: Where ``total_spent``, ``total_wasted`` and ``monthly_trend`` come
    #: from: the cost ledger. The per-category rows say their own source.
    value_source: str = 'valuation_layers'
    top_expensive_categories: list[CategoryCostDTO]
    monthly_trend: list[MonthlyTrendDTO]
    savings_opportunities: list[SavingsOpportunityDTO]


# --------------------------------------------------------------------------- #
# Rotation analysis
# --------------------------------------------------------------------------- #
class RotationItemDTO(BaseModel):
    """A single stock item with its days-in-storage and value."""

    item_id: str
    name: str
    brand: str | None
    days_in_storage: int
    category: str
    #: See ``CategoryCostDTO.category_code``.
    category_code: str | None = None
    value: float
    quantity: float
    location: str


class CategoryRotationDTO(BaseModel):
    """Average days-in-storage aggregated per category."""

    category_name: str
    #: See ``CategoryCostDTO.category_code``.
    category_code: str | None = None
    average_days: float | None
    item_count: int


class RotationAnalysisDTO(BaseModel):
    """Stock-age metrics: how long held stock has been sitting, slow movers,
    dead stock.

    The age figures say how old the stock on hand is — they are not
    inventory turnover (COGS / average stock, or DIO). Turnover is a
    different metric and would need the COGS the valuation layers carry;
    if it is ever built it arrives as a new field, not under these names.
    """

    #: Average age, in days, of the stock currently on hand.
    average_stock_age_days: float | None = None
    #: Median age, in days, of the stock currently on hand.
    median_stock_age_days: float | None = None
    average_days_to_consume: float
    median_days_to_consume: float
    active_items_count: int
    consumed_items_count: int
    slow_movers: list[RotationItemDTO]
    slow_movers_count: int
    slow_movers_value: float
    dead_stock: list[RotationItemDTO]
    dead_stock_count: int
    dead_stock_value: float
    rotation_by_category: list[CategoryRotationDTO]
    #: Age is a property of a record on a shelf, and the ledger does not
    #: know shelves, so the values here are price times quantity off the
    #: records — and say so.
    value_source: str = 'purchase_price'


# --------------------------------------------------------------------------- #
# Stock reconciliation (drift detection)
# --------------------------------------------------------------------------- #
class ReconciliationDTO(BaseModel):
    """The stock reconciliation: the shelf against its ledger and its cost.

    "The shelf" is the records summed per ``(template, location)``. Shelf vs
    movement ledger: a shelf whose first quant was once hydrated with its
    full quantity while the movement recorded only the delta carries that
    gap from its past (ADR-004, superseded by ADR-022) — this measures it
    instead of presuming it, so a gap that grows is visible. Layers vs
    shelf: stock that arrived without a priced receipt has no cost layer
    (the unpriced-receipt answer); the gap counts what the cost history
    does not cover.

    The report compared two more pairs while there was a quant table: the
    records against it, and it against the records' view. They ended with
    the table (ADR-022), and so did their fields. ``items_scanned`` counts
    the live records on a product card, the rows the shelf is summed from.
    """

    items_scanned: int
    #: ``(template, location)`` combos where the shelf and the movement
    #: ledger disagree. Populated since the ledger pair joined the report;
    #: ``None`` in reads made before it did.
    quant_move_drift_count: int | None = None
    #: Total absolute disagreement of that pair, in stock units.
    quant_move_drift_total: Decimal | None = None
    #: Templates where the cost layers and the shelf disagree.
    layer_quant_drift_count: int | None = None
    #: Total absolute disagreement of that pair, in stock units.
    layer_quant_drift_total: Decimal | None = None


class PreviousMeasurementDTO(BaseModel):
    """What the scheduled reconciliation pass before this one measured.

    The drift warning and the reconciliation screen read the same stored
    pass: the figures decide whether the warning fires again, the
    timestamp is when that measurement was taken. Four figures, the same
    names the report itself uses, so a reader can put a row beside its
    predecessor without translating between shapes.
    """

    measured_at: datetime
    quant_move_drift_count: int
    quant_move_drift_total: Decimal
    layer_quant_drift_count: int
    layer_quant_drift_total: Decimal


# --------------------------------------------------------------------------- #
# Expense forecast
# --------------------------------------------------------------------------- #
class ExpenseForecastDTO(BaseModel):
    """Predicted future spending derived from historical purchase trends.

    Trend-driven prediction of spend over a forecast period
    (week/month/quarter), plus top cost-driver categories and the waste
    reduction potential. Field names mirror the existing stats API
    response so the migration to ``core_api.queries`` is transparent to
    the frontend.
    """

    forecast_period: str
    predicted_spending: float
    historical_avg: float
    trend: str
    trend_percentage: float | None
    top_cost_drivers: list[CategoryCostDTO]
    waste_reduction_potential: float
    confidence: float
    # How much history the prediction stands on, and how much it needs. A
    # reader who is told "not enough data" deserves to know how much is
    # missing; a widget that simply vanishes reads as a fault.
    weeks_of_data: int = 0
    weeks_required: int = 0
    #: The weekly series behind ``predicted_spending`` and ``historical_avg``
    #: is read from the receipt layers — what arrived, at what it cost, on
    #: its business date. ``top_cost_drivers`` are per category and say
    #: their own, different, source.
    value_source: str = 'valuation_layers'
