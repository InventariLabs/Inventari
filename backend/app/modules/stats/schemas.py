from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import BaseModel


class OverviewStats(BaseModel):
    total_items: int
    total_locations: int
    expiring_soon: int
    expired: int
    low_stock: int
    #: Stock value over the items themselves — see OverviewDTO.
    total_value: float = 0.0
    #: False when no record carries a price — see OverviewDTO.
    value_known: bool = True
    #: Where ``total_value`` came from — see OverviewDTO. The domain layer
    #: has always returned this; the response model used to drop it, so the
    #: screen showed a figure with no way to check where it was from.
    value_source: str = 'purchase_price'
    #: Records left out of ``total_value`` for their currency — see
    #: OverviewDTO. Cut off here, the tile could only say "0.00" where the
    #: honest answer was "we cannot add these up, and there are N of them".
    excluded_other_currency_count: int = 0
    #: Whom ``total_value`` is about — see OverviewDTO. The ledger knows
    #: products, not shelves, so a ledger figure is the organization's.
    value_scope: str = 'locations'
    #: Receipts on the shelf posted at no cost — see OverviewDTO.
    unvalued_stock_count: int = 0
    #: Records with no price, when valued off the records — see OverviewDTO.
    unpriced_item_count: int = 0
    #: Whether any record carries an expiry date — see OverviewDTO.
    tracks_expiry: bool = False


class LowStockProduct(BaseModel):
    """One product the tile's low-stock number counts — see ``low_stock``."""

    template_id: UUID
    name: str
    #: On the shelves, summed over the product's records; 0 when used up.
    on_hand: float
    minimum: float
    #: A shelf record of the product to open from the list; ``None`` when used up.
    item_id: UUID | None = None
    uom_symbol: str | None = None


class StorageStats(BaseModel):
    location_id: UUID
    location_name: str
    location_type: str
    items_count: int
    expiring_soon: int


class CategoryStats(BaseModel):
    category_id: UUID | None
    category_name: str
    category_code: str | None
    category_icon: str | None
    items_count: int
    total_value: float
    #: Off the records' prices — see CategoryStatsDTO.
    value_source: str = 'purchase_price'
    unpriced_count: int = 0


class ExpiryForecast(BaseModel):
    period: str
    count: int


class ActivityItem(BaseModel):
    id: UUID
    action: str
    item_name: str
    created_at: datetime
    user_name: str | None
    details: dict[str, Any] | None


class MostConsumedItem(BaseModel):
    name: str
    category: str
    #: See CategoryCostItem.category_code.
    category_code: str | None = None
    quantity: float
    value: float


class CategoryConsumption(BaseModel):
    category: str
    #: See CategoryCostItem.category_code.
    category_code: str | None = None
    total_quantity: float
    total_value: float


class ConsumptionStats(BaseModel):
    most_consumed: list[MostConsumedItem]
    most_wasted: list[MostConsumedItem]
    #: Share of outflow events that were waste. Served for API consumers
    #: only: the cost analysis screen shows the share of *value* wasted
    #: (``CostAnalysis.waste_value_percentage``), which is the figure a
    #: reader can act on; an event count says nothing about money lost.
    waste_event_rate: float
    #: ``None`` where the ledger has no outgoing value for the window — see
    #: ``CostAnalysis.total_wasted``.
    total_consumed_value: float | None
    total_wasted_value: float | None
    consumption_by_category: list[CategoryConsumption]


class RestockForecastRow(BaseModel):
    product_name: str
    category_name: str
    #: See CategoryCostItem.category_code.
    category_code: str | None = None
    avg_consumption_rate: float
    days_since_last_purchase: int
    urgency: str
    estimated_days_until_needed: int


class MonthlyTrendItem(BaseModel):
    month: str
    spent: float
    wasted: float


class CategoryCostItem(BaseModel):
    category_name: str
    #: The seed code — the reader's language names the category through it.
    category_code: str | None = None
    total_spent: float
    total_wasted: float
    items_count: int
    #: ``total_spent`` is off the records' prices — see CategoryCostDTO.
    value_source: str = 'purchase_price'
    unpriced_count: int = 0


class SavingsOpportunity(BaseModel):
    product_name: str
    category_name: str
    #: See CategoryCostItem.category_code.
    category_code: str | None = None
    wasted_amount: float
    suggestion: str


class CostAnalysis(BaseModel):
    total_spent: float
    #: ``None`` when the ledger has no outgoing value for this window — see
    #: ``CostSummaryDTO.total_wasted``. Zero and "no idea" are different
    #: answers and this field used to give the first for both.
    total_wasted: float | None
    #: ``None`` for the same reason: a percentage of an unknown is unknown.
    waste_value_percentage: float | None
    top_expensive_categories: list[CategoryCostItem]
    monthly_trend: list[MonthlyTrendItem]
    savings_opportunities: list[SavingsOpportunity]
    #: Priced records left out of the sum — see CostSummaryDTO.
    excluded_other_currency_count: int = 0
    #: Where the totals and the monthly trend come from — see CostSummaryDTO.
    value_source: str = 'valuation_layers'


class RotationItem(BaseModel):
    item_id: str
    name: str
    brand: str | None
    days_in_storage: int
    category: str
    #: See CategoryCostItem.category_code.
    category_code: str | None = None
    value: float
    quantity: float
    location: str


class CategoryRotation(BaseModel):
    category_name: str
    #: See CategoryCostItem.category_code.
    category_code: str | None = None
    average_days: float | None
    item_count: int


class RotationAnalysisResponse(BaseModel):
    #: None when nothing measurable stands on any shelf — the age of no
    #: stock is not a figure, and 0.0 would read as the best possible age.
    average_stock_age_days: float | None
    median_stock_age_days: float | None
    #: How many records the rotation figures were measured over. Zero of them
    #: makes "0.0 days" the best possible result rather than no result at all.
    consumed_items_count: int = 0
    slow_movers: list[RotationItem]
    slow_movers_count: int
    slow_movers_value: float
    dead_stock: list[RotationItem]
    dead_stock_count: int
    dead_stock_value: float
    rotation_by_category: list[CategoryRotation]
    #: Values are price times quantity off the records — see RotationAnalysisDTO.
    value_source: str = 'purchase_price'


class AlertItem(BaseModel):
    type: str
    severity: str
    message_key: str
    message_params: dict[str, Any] | None = None
    action: str | None = None
    action_param: str | None = None
    item_id: str | None = None
    item_name: str | None = None
    days_untouched: int | None = None
    product_name: str | None = None
    last_purchase_days_ago: int | None = None
    usual_frequency_days: int | None = None
    expiry_date: str | None = None
    days_until_expiry: int | None = None


class SmartAlertsResponse(BaseModel):
    alerts: list[AlertItem]
    total_alerts: int


class WasteReductionPotential(BaseModel):
    current_monthly_waste: float
    if_reduced_50_percent: float
    annual_savings: float


class ExpenseForecastResponse(BaseModel):
    forecast_period: str
    predicted_spending: float
    historical_avg: float
    trend: str
    trend_percentage: float | None
    top_cost_drivers: list[CategoryCostItem]
    waste_reduction_potential: float
    confidence: float
    weeks_of_data: int = 0
    weeks_required: int = 0
    #: The weekly series is read from the receipt layers — see ExpenseForecastDTO.
    value_source: str = 'valuation_layers'


class RecurringProduct(BaseModel):
    name: str
    brand: str | None
    category: str
    #: See CategoryCostItem.category_code.
    category_code: str | None = None
    purchase_frequency_days: float
    total_purchases_last_6_months: int
    avg_price: float
    avg_quantity: float
    total_spent: float
    price_volatility: str


class SeasonalProduct(BaseModel):
    name: str
    peak_month: str | None = None
    peak_quantity: float | None = None
    average_quantity: float | None = None
    seasonality_score: float | None = None
    peak_months: list[str] = []
    avg_monthly_spend_peak: float = 0.0
    avg_monthly_spend_off_season: float = 0.0


class BulkOpportunity(BaseModel):
    product: str
    brand: str | None = None
    current_avg_purchase_kg: float
    current_price_per_kg: float
    unit_price_current: float = 0.0
    bulk_option_kg: float
    bulk_price_per_kg: float
    potential_annual_savings: float


class PurchasePatternsResponse(BaseModel):
    top_recurring_products: list[RecurringProduct]
    seasonal_products: list[SeasonalProduct]
    bulk_opportunities: list[BulkOpportunity]
    #: Grouped by name, brand and category — properties of the record the
    #: cost ledger does not carry — so the amounts are price times quantity
    #: off the records, and the report says so.
    value_source: str = 'purchase_price'


class PreviousMeasurement(BaseModel):
    """What the previous scheduled reconciliation pass measured.

    The screen puts a row beside its predecessor with this — same figure
    names as the report itself, plus when that pass ran. ``None`` on the
    wire until the scheduled job has measured this organization once.
    """

    measured_at: datetime
    quant_move_drift_count: int
    quant_move_drift_total: Decimal
    layer_quant_drift_count: int
    layer_quant_drift_total: Decimal


class ReconciliationResponse(BaseModel):
    """What the pair comparisons found, as the reader gets to see it.

    Every figure the DTO carries is on the wire, including how much was
    scanned to reach it — a drift of nought over nothing is not the same
    statement as a drift of nought over eleven thousand records. The two
    pairs that compared the records and their view with the quant table
    ended with the table (ADR-022), and their fields with them.
    """

    #: How many live records on a product card the shelf was summed from.
    items_scanned: int
    #: The shelf against the movement ledger. A shelf once hydrated with its
    #: full quantity while the movement carried only the delta keeps that
    #: gap from its past (ADR-004, superseded by ADR-022), so the figure is
    #: measured rather than presumed; the one to watch is a figure that grows.
    quant_move_drift_count: int | None = None
    quant_move_drift_total: Decimal | None = None
    #: The cost layers against the shelf — how much of the shelf the cost
    #: history does not cover.
    layer_quant_drift_count: int | None = None
    layer_quant_drift_total: Decimal | None = None
    #: The previous scheduled pass — the pair a reader watches against its
    #: predecessor, so a standing figure and a growing one stop looking
    #: alike. ``None`` before the job's first pass.
    previous: PreviousMeasurement | None = None


class StatsConfig(BaseModel):
    """Module-level toggles every stats:read user may see.

    Served from the module's own router because the generic settings endpoint
    is admin-only, while the tab this drives is visible to viewers.
    """

    enable_analytics: bool
    show_inventory_value: bool
