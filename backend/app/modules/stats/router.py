import asyncio
import uuid
from collections.abc import AsyncIterator
from typing import cast

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse
from starlette.background import BackgroundTask

from app.core import db_facade
from app.core.contracts import UserContextDTO
from app.core.deps import (
    get_async_db,
    get_current_user_context,
    require_org,
    require_permission,
)
from app.core.exceptions import AppException
from app.core.logging import get_logger
from app.core.module_sdk import (
    PaginatedResponse,
    get_current_lang,
    get_module_error_message,
)
from app.core.modules import require_module

from ._alerts_service import get_smart_alerts_async
from ._purchase_service import get_purchase_patterns_async
from .query_service import (
    get_consumption_stats,
    get_cost_analysis,
    get_expiry_forecast,
    get_low_stock_products,
    get_overview_stats,
    get_recent_activity,
    get_rotation_analysis_async,
    get_shopping_suggestions,
    get_stats_by_category,
    get_stats_by_storage,
)
from .query_service import (
    get_expense_forecast as _query_expense_forecast,
)
from .query_service import (
    get_reconciliation as _query_reconciliation,
)
from .schemas import (
    ActivityItem,
    CategoryStats,
    ConsumptionStats,
    CostAnalysis,
    ExpenseForecastResponse,
    ExpiryForecast,
    LowStockProduct,
    OverviewStats,
    PurchasePatternsResponse,
    ReconciliationResponse,
    RestockForecastRow,
    RotationAnalysisResponse,
    SmartAlertsResponse,
    StatsConfig,
    StorageStats,
)

logger = get_logger(__name__)

router = APIRouter(
    dependencies=[
        Depends(require_module('stats')),
        require_permission('stats:read'),
    ]
)


@router.get('/config', response_model=StatsConfig)
async def get_stats_config_endpoint(
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
) -> StatsConfig:
    """Module toggles the interface needs at the stats:read level.

    The generic module-settings endpoint is admin-only, but the analytics tab
    is visible to viewers too — so the module serves its own config here.
    """
    from app.core.public_api import core_api

    org_id = require_org(current_user)
    enabled = await core_api.settings.get_async(
        db, org_id, 'stats', 'enable_analytics', default=True
    )
    show_value = await core_api.settings.get_async(
        db, org_id, 'stats', 'show_inventory_value', default=True
    )
    return StatsConfig(
        enable_analytics=bool(enabled),
        show_inventory_value=bool(show_value),
    )


@router.get('/overview', response_model=OverviewStats)
async def get_overview_stats_endpoint(
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
) -> OverviewStats:
    return cast(OverviewStats, await get_overview_stats(db, require_org(current_user)))


@router.get('/low-stock', response_model=PaginatedResponse[LowStockProduct])
async def get_low_stock_products_endpoint(
    exclude_module_contexts: bool = Query(
        False,
        description='Hide records whose category belongs to a vertical module',
    ),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
) -> PaginatedResponse[LowStockProduct]:
    """The products the overview's ``low_stock`` number counts, one row each.

    ``exclude_module_contexts`` takes the same products out that it takes out
    of ``GET /items/attention-counts``, so a heading and its rows agree; the
    page's ``total`` is that number.
    """
    rows, total = await get_low_stock_products(
        db,
        require_org(current_user),
        exclude_module_contexts,
        offset=offset,
        limit=limit,
    )
    products = [
        LowStockProduct(
            template_id=r.template_id,
            name=r.name,
            on_hand=r.on_hand,
            minimum=r.minimum,
            item_id=r.item_id,
            uom_symbol=r.uom_symbol,
        )
        for r in rows
    ]
    return PaginatedResponse.from_slice(products, offset, limit, total)


# The two breakdowns are one row per location and per category, so they grow
# with the organization like any other list; each row is aggregated in one
# query over every row of the organization, so they are read whole and sliced.
@router.get('/by-location', response_model=PaginatedResponse[StorageStats])
async def get_stats_by_storage_endpoint(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
) -> PaginatedResponse[StorageStats]:
    rows = await get_stats_by_storage(db, require_org(current_user))
    return PaginatedResponse.from_full_list(rows, offset=offset, limit=limit)


@router.get('/by-category', response_model=PaginatedResponse[CategoryStats])
async def get_stats_by_category_endpoint(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
) -> PaginatedResponse[CategoryStats]:
    rows = await get_stats_by_category(db, require_org(current_user))
    return PaginatedResponse.from_full_list(rows, offset=offset, limit=limit)


@router.get(
    '/expiry-forecast',
    # list-envelope-exception: six fixed time buckets, one series, not rows to page
    response_model=list[ExpiryForecast],
)
async def get_expiry_forecast_endpoint(
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
) -> list[ExpiryForecast]:
    return cast(
        list[ExpiryForecast],
        await get_expiry_forecast(db, require_org(current_user)),
    )


@router.get(
    '/activity',
    # list-envelope-exception: the newest entries of the history, capped by limit
    response_model=list[ActivityItem],
)
async def get_recent_activity_endpoint(
    limit: int = Query(10, ge=1, le=200),
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
) -> list[ActivityItem]:
    org_id = require_org(current_user)
    return cast(
        list[ActivityItem],
        await get_recent_activity(db, org_id, limit),
    )


@router.get('/consumption', response_model=ConsumptionStats)
async def get_consumption_stats_endpoint(
    days: int = Query(30, description='Analysis period in days'),
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
) -> ConsumptionStats:
    return cast(
        ConsumptionStats,
        await get_consumption_stats(db, require_org(current_user), days),
    )


@router.get(
    '/shopping-suggestions', response_model=PaginatedResponse[RestockForecastRow]
)
async def get_shopping_suggestions_endpoint(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
) -> PaginatedResponse[RestockForecastRow]:
    # Built in memory from two reads and merged by product, so sliced here.
    suggestions = await get_shopping_suggestions(db, require_org(current_user))
    return PaginatedResponse.from_full_list(suggestions, offset=offset, limit=limit)


@router.get('/cost-analysis', response_model=CostAnalysis)
async def get_cost_analysis_endpoint(
    period: str = Query('month', description='Analysis period: day/week/month/year'),
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
) -> CostAnalysis:
    return cast(
        CostAnalysis,
        await get_cost_analysis(db, require_org(current_user), period),
    )


@router.get('/rotation-analysis', response_model=RotationAnalysisResponse)
async def get_rotation_analysis(
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
) -> RotationAnalysisResponse:
    return cast(
        RotationAnalysisResponse,
        await get_rotation_analysis_async(db, require_org(current_user)),
    )


@router.get('/smart-alerts', response_model=SmartAlertsResponse)
async def get_smart_alerts(
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
) -> SmartAlertsResponse:
    return SmartAlertsResponse.model_validate(
        await get_smart_alerts_async(db, require_org(current_user))
    )


@router.get('/expense-forecast', response_model=ExpenseForecastResponse)
async def get_expense_forecast(
    period: str = Query('month', pattern='^(week|month|quarter)$'),
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
) -> ExpenseForecastResponse:
    return cast(
        ExpenseForecastResponse,
        await _query_expense_forecast(db, require_org(current_user), period),
    )


@router.get('/purchase-patterns', response_model=PurchasePatternsResponse)
async def get_purchase_patterns(
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
) -> PurchasePatternsResponse:
    return PurchasePatternsResponse.model_validate(
        await get_purchase_patterns_async(db, require_org(current_user))
    )


@router.get('/reconciliation', response_model=ReconciliationResponse)
async def get_reconciliation(
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
) -> ReconciliationResponse:
    return cast(
        ReconciliationResponse,
        await _query_reconciliation(db, require_org(current_user)),
    )


# Per-worker-process ceiling on concurrent overview streams (the counter is
# module state, so each gunicorn worker has its own). Every stream ticks on the
# same 10 s rhythm, so N streams put N short sessions on the pool at once; the
# cap bounds that burst per process. The durable answer is one
# poller per node fanning out through Redis pub/sub — deferred because it
# needs a pub/sub channel the stats module does not own yet, and the cap makes
# the failure mode a clean 429 in the meantime instead of a starved pool.
MAX_CONCURRENT_OVERVIEW_STREAMS = 50
_open_overview_streams = 0

# A tick failure is logged with its traceback once per outage *per org*, then
# counted; that org's first successful tick reports the count. Keyed per org so
# a success elsewhere (e.g. an org still served from the overview cache during
# a database outage) cannot end another org's outage and re-arm its tracebacks.
# Log volume is therefore independent of client count and outage length.
_tick_outage_suppressed: dict[uuid.UUID, int] = {}


def _record_tick_failure(org_id: uuid.UUID) -> None:
    if org_id not in _tick_outage_suppressed:
        _tick_outage_suppressed[org_id] = 0
        logger.exception('stats overview tick failed')
    else:
        _tick_outage_suppressed[org_id] += 1


def _record_tick_success(org_id: uuid.UUID) -> None:
    suppressed = _tick_outage_suppressed.pop(org_id, None)
    if suppressed is not None:
        logger.info(
            'stats overview ticks recovered; %d failures suppressed',
            suppressed,
        )


@router.get('/overview/stream')
async def stream_overview(
    current_user: UserContextDTO = Depends(get_current_user_context),
) -> EventSourceResponse:
    """SSE stream: pushes updated overview stats every 10 seconds."""
    global _open_overview_streams
    org_id = require_org(current_user)

    # Refuse up front, like every other caller of the factory, instead of
    # letting `None()` raise inside the loop and repeat as an error event.
    if db_facade.AsyncSessionLocal is None:
        logger.error(
            'Cannot start statistics stream: database session factory is not initialised'
        )
        raise AppException(
            status_code=503,
            code='DATABASE_NOT_INITIALISED',
            message=get_module_error_message('stats', 'internal_error'),
        )
    if _open_overview_streams >= MAX_CONCURRENT_OVERVIEW_STREAMS:
        raise AppException(
            status_code=429,
            code='TOO_MANY_STREAMS',
            message=get_module_error_message('stats', 'overview_stream_limit'),
            extra={'lang': get_current_lang()},
        )
    _open_overview_streams += 1
    released = False

    def release() -> None:
        global _open_overview_streams
        nonlocal released
        if not released:
            released = True
            _open_overview_streams -= 1

    async def event_generator() -> AsyncIterator[dict[str, str]]:
        try:
            while True:
                try:
                    # A fresh short session per tick: the connection is
                    # checked out of the pool only for the query and returned
                    # before the stream sleeps. A session kept across ticks
                    # would pin a pooled connection and an open transaction
                    # per connected dashboard — enough tabs exhaust the pool
                    # and stall every other request, and the snapshot holds
                    # back VACUUM. The attribute access through db_facade is
                    # deliberate: it reads the live factory, which
                    # init_async_engine rebinds.
                    async with db_facade.AsyncSessionLocal() as db:
                        stats = await get_overview_stats(db, org_id)
                    _record_tick_success(org_id)
                    yield {
                        'event': 'overview',
                        'data': stats.model_dump_json(),
                    }
                except Exception:  # noqa: BLE001 — SSE stream must never crash on per-event failure
                    _record_tick_failure(org_id)
                    yield {
                        'event': 'error',
                        'data': '{"message": "Stats unavailable"}',
                    }
                await asyncio.sleep(10)
        finally:
            release()

    return EventSourceResponse(event_generator(), background=BackgroundTask(release))
