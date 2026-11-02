"""
SystemSettingsService — CRUD for global system settings.

Every read goes to the database (primary-key lookup): a per-process cache would
hide a write made by one gunicorn worker from the others for its whole TTL.

Keys stored in system_settings table:
  model_pricing        — per-model LLM cost table (input/output per 1k tokens)
  default_org_limits   — default AI/item/member limits for new organizations
"""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.core.utils import isoformat_or_none
from app.models.system_setting import SystemSetting

logger = get_logger(__name__)

# Default values seeded at migration time — these are fallback if DB is empty
DEFAULT_MODEL_PRICING: dict[str, dict] = {
    'google/gemini-2.0-flash-001': {'input_per_1k': 0.000075, 'output_per_1k': 0.0003},
    'google/gemini-2.0-flash-exp:free': {'input_per_1k': 0.0, 'output_per_1k': 0.0},
    'google/gemini-2.5-pro': {'input_per_1k': 0.00125, 'output_per_1k': 0.01},
    'openai/gpt-4o': {'input_per_1k': 0.0025, 'output_per_1k': 0.01},
    'openai/gpt-4o-mini': {'input_per_1k': 0.00015, 'output_per_1k': 0.0006},
    'qwen/qwen-vl-plus': {'input_per_1k': 0.0008, 'output_per_1k': 0.0008},
    'xiaomi/mimo-v2.5-pro': {
        'input_per_1k': 0.435,
        'input_per_1k_cache_hit': 0.0036,
        'output_per_1k': 0.87,
    },
    'xiaomi/mimo-v2.5': {
        'input_per_1k': 0.14,
        'input_per_1k_cache_hit': 0.0028,
        'output_per_1k': 0.28,
    },
}

DEFAULT_ORG_LIMITS: dict[str, Any] = {
    'ai_scans_monthly': None,
    'ai_requests_monthly': None,
    'max_products': None,
    'max_members': None,
}


async def get_setting_async(db: AsyncSession, key: str, default: Any = None) -> Any:
    """Async: returns the current stored value, or *default* when unset."""
    row = (
        await db.scalars(
            select(SystemSetting)
            .filter_by(key=key)
            .execution_options(populate_existing=True)
        )
    ).first()
    return default if row is None else row.value


async def get_default_org_limits_async(db: AsyncSession) -> dict[str, Any]:
    """Async: return default org limits from system settings."""
    return await get_setting_async(db, 'default_org_limits', DEFAULT_ORG_LIMITS)


async def get_model_pricing_async(db: AsyncSession) -> dict[str, dict]:
    """Async: return model pricing from system settings."""
    return await get_setting_async(db, 'model_pricing', DEFAULT_MODEL_PRICING)


async def estimate_cost_async(
    db: AsyncSession,
    model_name: str,
    prompt_tokens: int,
    completion_tokens: int,
    cache_read_tokens: int = 0,
) -> tuple[float, bool]:
    """Async: estimate cost from model pricing table.
    cache_read_tokens: number of input tokens served from cache (cached pricing applies).
    """
    pricing = await get_model_pricing_async(db)
    model_price = pricing.get(model_name)
    if not model_price:
        return 0.0, True

    cache_hit_price = model_price.get('input_per_1k_cache_hit')
    if cache_read_tokens > 0 and cache_hit_price is not None:
        non_cache_tokens = max(0, prompt_tokens - cache_read_tokens)
        input_cost = (
            cache_read_tokens / 1000.0 * cache_hit_price
            + non_cache_tokens / 1000.0 * model_price.get('input_per_1k', 0)
        )
    else:
        input_cost = prompt_tokens / 1000.0 * model_price.get('input_per_1k', 0)

    cost = input_cost + completion_tokens / 1000.0 * model_price.get('output_per_1k', 0)
    return cost, True


async def get_all_settings_async(db: AsyncSession) -> list[dict]:
    """Async: return all system settings."""
    rows = (await db.scalars(select(SystemSetting))).all()
    return [
        {
            'key': r.key,
            'value': r.value,
            'updated_at': isoformat_or_none(r.updated_at),
        }
        for r in rows
    ]


async def set_setting_async(
    db: AsyncSession, key: str, value: Any, updated_by: UUID | None = None
) -> SystemSetting:
    """Async: upserts a setting."""
    row = (await db.scalars(select(SystemSetting).filter_by(key=key))).first()
    if row:
        row.value = value
        row.updated_at = datetime.now(UTC)
        row.updated_by = updated_by
    else:
        row = SystemSetting(key=key, value=value, updated_by=updated_by)
        db.add(row)
    await db.flush()
    await db.refresh(row)
    return row
