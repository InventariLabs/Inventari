"""Who can say what a workflow for a target type would hold.

Whether something waits for an approval is the asking module's decision,
never the engine's (``docs/purpose/approvals.md``): a document is held by the
documents profile and its gate, a purchase order by its own settings. So the
engine cannot tell an administrator what a workflow will hold once switched
on — only the module that owns the gate can. Each registers a provider at
import time, like the summary providers and decision listeners, and the
workflow list asks whoever is registered. A target type nobody claimed has
no scope to show, and the list says nothing rather than guessing.
"""

from collections.abc import Awaitable, Callable
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from .exceptions import ApprovalScopeChangedError, ApprovalScopeRequiredError
from .schemas import WorkflowScope

TargetScopeProvider = Callable[[AsyncSession, UUID], Awaitable[WorkflowScope]]

_PROVIDERS: dict[str, TargetScopeProvider] = {}


def register_target_scope_provider(
    target_type: str, provider: TargetScopeProvider
) -> None:
    """Claim the scope question for one target type.

    Registering twice for the same type replaces the earlier provider, which
    keeps module reloads (and tests) from accumulating stale entries.
    """
    _PROVIDERS[target_type] = provider


def fixed_target_scope(scope: WorkflowScope) -> TargetScopeProvider:
    """A provider for a target type whose rule no setting changes.

    Equipment checkouts, for one: an active workflow holds every checkout,
    whatever the organization configured. The answer needs neither the
    session nor the organization, so the provider takes them and ignores
    them by design rather than pretending to read them.
    """

    async def _provider(*_: object) -> WorkflowScope:
        return scope

    return _provider


async def describe_scope_async(
    db: AsyncSession, org_id: UUID, target_type: str
) -> WorkflowScope | None:
    """What a workflow for ``target_type`` holds, or ``None`` when nobody says."""
    provider = _PROVIDERS.get(target_type)
    if provider is None:
        return None
    return await provider(db, org_id)


async def ensure_scope_unchanged_async(
    db: AsyncSession,
    org_id: UUID,
    target_type: str,
    expected: WorkflowScope | None,
) -> None:
    """Refuse when what a workflow would hold is not what the reader was shown.

    Compared as values: an amount sent back as ``"100.00"`` is the same limit
    as the ``Decimal('100')`` the provider answers. No ``expected`` is a
    refusal of its own wherever a provider says what the workflow would hold;
    a target type nobody claimed has nothing to show and nothing to compare.
    """
    current = await describe_scope_async(db, org_id, target_type)
    if current is None:
        return
    if expected is None:
        raise ApprovalScopeRequiredError.translated('approval_scope_required')
    if current != expected:
        raise ApprovalScopeChangedError.translated('approval_scope_changed')
