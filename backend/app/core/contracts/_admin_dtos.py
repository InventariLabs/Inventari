"""Admin analytics DTOs exposed via ``core_api.admin`` and ``core_api.ai_usage``.

These are read-only aggregate read-models used by super-admin dashboards
(SaaS control plane). They live in Core so that an extracted ``cloud``
module can consume them via ``core_api`` without importing ``app.models``,
which the module import lint keeps out.

Naming follows the existing analytics DTO convention (``*DTO`` suffix).
Field names mirror the previous module-local Pydantic schemas so the
public JSON contract of the admin endpoints does not change.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel


# --------------------------------------------------------------------------- #
# Org admin metrics (per-org breakdown for superadmin)
# --------------------------------------------------------------------------- #
class AdminOrgMemberDTO(BaseModel):
    id: UUID
    email: str
    full_name: str | None
    role: str
    actions_30d: int
    is_active: bool
    is_blocked: bool


class AdminOrgMetricsDTO(BaseModel):
    """Per-organization admin metrics (SaaS owner view)."""

    id: UUID
    short_id: str | None
    name: str
    created_at: datetime
    member_count: int
    item_count: int
    location_count: int
    total_value: float
    currency: str
    activity_30d: int
    waste_count: int
    members: list[AdminOrgMemberDTO]
    allowed_modules: list[str] = []


class GlobalAdminStatsDTO(BaseModel):
    total_organizations: int
    total_users: int
    active_items: int
    dau: int
    wau: int
    total_llm_cost_usd: float
    total_scans_30d: int


# --------------------------------------------------------------------------- #
# AI usage analytics
# --------------------------------------------------------------------------- #
class AIUsageTopOrgDTO(BaseModel):
    id: UUID
    name: str
    requests: int
    tokens: int
    cost_usd: float


class AIUsageModelStatDTO(BaseModel):
    model: str
    requests: int
    tokens: int
    cost_usd: float


class AIUsageProviderStatDTO(BaseModel):
    """One provider's share of AI usage and cost.

    ``provider`` is the value the ledger stored, reported verbatim.
    ``None`` is a bucket of its own — rows the ledger never stamped.
    ``'unknown'`` is what the LLM ledger writes when the caller named no
    client. Rows written before the ledger recorded the real provider all
    carry ``'openrouter'``, local model or not: the true provider was never
    stored, no backfill can recover it, and the bucket means "recorded as
    OpenRouter", not "verified".
    """

    provider: str | None
    requests: int
    tokens: int
    cost_usd: float


class AIUsageDailyStatDTO(BaseModel):
    date: str
    requests: int
    cost_usd: float


class GlobalAIUsageStatsDTO(BaseModel):
    period_days: int
    total_requests: int
    total_tokens: int
    total_cost_usd: float
    estimated_cost_ratio: float
    top_orgs: list[AIUsageTopOrgDTO]
    by_model: list[AIUsageModelStatDTO]
    by_provider: list[AIUsageProviderStatDTO]
    daily: list[AIUsageDailyStatDTO]


class OrgAIUsageMonthUsageDTO(BaseModel):
    ai_requests_monthly: int
    ai_scans_monthly: int


class OrgAIUsageUserStatDTO(BaseModel):
    """One user's share of AI usage — plus the unassigned bucket.

    A row with ``id`` and ``email`` null is *unassigned*: calls with no user
    (connection tests, background jobs) and calls whose user was deleted.
    ``sum(requests)`` over the list equals the report's ``total_requests``,
    so the breakdown adds up without a silent omission.
    """

    id: UUID | None
    email: str | None
    display_name: str | None
    requests: int
    tokens: int
    cost_usd: float


class OrgAIUsageActionStatDTO(BaseModel):
    action: str
    requests: int
    cost_usd: float


class OrgAIUsageStatsDTO(BaseModel):
    period_days: int
    total_requests: int
    total_cost_usd: float
    month_usage: OrgAIUsageMonthUsageDTO
    limits: dict[str, Any]
    by_user: list[OrgAIUsageUserStatDTO]
    by_provider: list[AIUsageProviderStatDTO]
    by_action: list[OrgAIUsageActionStatDTO]
    daily: list[AIUsageDailyStatDTO]
