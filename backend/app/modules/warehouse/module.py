import importlib.util
from typing import Any
from uuid import UUID

from app.core.context import ModuleContext
from app.core.define_module import define_module


def _register_period_guard() -> None:
    """Register the inventory period guard in the Core registry.

    Core stock-mutating paths call ``core_api.periods.check_not_closed_async``
    which delegates to the registered implementation — Core never imports
    this module. Runs at module import (the registry imports every module
    package at startup).
    """
    from app.core.period_guard import register_period_guard
    from app.modules.warehouse.inventory_period_service import (
        check_stock_change_period_open_async,
    )

    register_period_guard(check_stock_change_period_open_async)


_register_period_guard()


def _approvals_installed() -> bool:
    """Whether the approvals package ships with this installation.

    The warehouse declares approvals an optional companion: it loads, confirms
    and posts without it, and only describes its documents to the approvals
    queue when there is one to describe them to.
    """
    return importlib.util.find_spec('app.modules.approvals') is not None


def _register_approval_target_summaries() -> None:
    """Describe a document to the approvals queue.

    The engine used to import this module and ask for the summaries itself;
    now every consumer claims its own target type, and a type nobody claims
    degrades to the bare identifier. Registered at import, like the period
    guard above: the queue is enriched by whoever the installation ships, not
    by which organisation happens to have the module switched on.
    """
    from app.modules.approvals.approvals_api import approvals_api
    from app.modules.warehouse.warehouse_api import warehouse_api

    approvals_api.register_target_summary_provider(
        'document', warehouse_api.get_target_summaries_by_ids_async
    )


def _register_approval_scope_provider() -> None:
    """Tell the approvals screen what a document workflow would hold.

    The profile decides what waits; the workflow screen has to say it before
    an administrator switches a workflow on, and it can only hear it from us.
    """
    from app.modules.approvals.approvals_api import approvals_api
    from app.modules.warehouse._approval_scope import describe_document_approval_scope

    approvals_api.register_target_scope_provider(
        'document', describe_document_approval_scope
    )


# What a decision does to a document, and the gate itself, are the approvals
# module's: it registers a pre-post check here (``warehouse_api``) and follows
# its own decisions through the hold it put on the document.
if _approvals_installed():
    _register_approval_target_summaries()
    _register_approval_scope_provider()


def _get_router() -> Any:
    from app.modules.warehouse.router import router

    return router


def _register_event_payloads(context: ModuleContext) -> None:
    """Declare this module's event payload contracts.

    Ownership claims ahead of the planned move of these classes out of the
    core table — no-ops while the core table still lists them. The claims are
    made now so the catalogue and the runtime registry already agree on who
    owns the names.
    """
    from app.core.contracts.events import (
        DocumentCancelledPayload,
        DocumentCompletedPayload,
        DocumentConfirmedPayload,
        DocumentShippedPayload,
    )
    from app.core.public_api import core_api

    core_api.events.register_payload('document.confirmed', DocumentConfirmedPayload)
    core_api.events.register_payload('document.completed', DocumentCompletedPayload)
    core_api.events.register_payload('document.cancelled', DocumentCancelledPayload)
    core_api.events.register_payload('document.shipped', DocumentShippedPayload)


async def _seed_default_profile(context: ModuleContext) -> None:
    if context.organization_id:
        from app.modules.warehouse.document_profile_service import (
            create_default_profile,
        )

        await create_default_profile(context._db, UUID(str(context.organization_id)))


def _purge_blocker_interceptor() -> Any:
    """The warehouse module's purge veto.

    Registered via ``interceptors=`` so the shared ``_wire_interceptors``
    path attaches it to the item pipeline at startup — the module never
    touches Core's pipeline directly.
    """
    from app.modules.warehouse.interceptors import DocumentsPurgeBlocker

    return DocumentsPurgeBlocker()


def _register_scan_provider() -> None:
    """Resolve document numbers printed on PDFs when a printout is scanned.

    registered from the module (Core must not know about documents),
       priority 30 — after labels (20), before OFF (50) and the barcode
       fallback (100). The provider claims broadly; the (org, number) lookup
       decides, so a miss falls through to the next provider.
    """
    from app.core.scan_registry import scan_registry

    from ._document_scan_provider import DocumentScanProvider

    scan_registry.register(DocumentScanProvider(), priority=30)


#: The organization's settings of this module.
#:
#: How far past the expected figure a receipt may record without the
#: over-receipt permission, in percent. 0 — the ERPNext-style default —
#: means every surplus needs the permission; the setting softens the rule
#: before it is asked. Read by ``_over_receipt``.
#:
#: How far past the same basis nobody may receive at all, permission or
#: not, in percent; 0 sets no ceiling. Read by ``_over_receipt``.
#:
#: How long a picking or receiving session may stand untouched before it
#: is released — its scans kept, its document free to complete or continue
#: by anyone. Read by ``_wms_session_release``.
DOCUMENTS_SETTINGS_SCHEMA: dict[str, Any] = {
    'type': 'object',
    'properties': {
        'over_receipt_tolerance_percent': {
            'type': 'number',
            'default': 0,
            'minimum': 0,
            'maximum': 100,
            'title': 'Over-receipt tolerance (%)',
            'title_key': 'warehouse:settings.overReceiptTolerance',
            'description_key': 'warehouse:settings.overReceiptToleranceDescription',
            'description': (
                'How far past the expected quantity — or past what is left '
                'on an order line — a receipt may go without the permission '
                'to receive over tolerance. 0% allows no surplus beyond it.'
            ),
        },
        'over_receipt_ceiling_percent': {
            'type': 'number',
            'default': 0,
            'minimum': 0,
            'maximum': 1000,
            'title': 'Over-receipt ceiling (%)',
            'title_key': 'warehouse:settings.overReceiptCeiling',
            'description_key': 'warehouse:settings.overReceiptCeilingDescription',
            'description': (
                'How far past the expected quantity — or past what is left on '
                'an order line — nobody may receive, not even someone who may '
                'receive over tolerance. 0% sets no ceiling.'
            ),
        },
        'scan_session_idle_minutes': {
            'type': 'integer',
            'default': 30,
            'minimum': 1,
            'maximum': 1440,
            'title': 'Release an idle scanning session after (minutes)',
            'title_key': 'warehouse:settings.scanSessionIdleMinutes',
            'description_key': 'warehouse:settings.scanSessionIdleMinutesDescription',
            'description': (
                'A picking or receiving session nobody has scanned in for this '
                'long stops holding its document: what was scanned is kept, '
                'and anyone can continue it or complete the document.'
            ),
        },
    },
    'additionalProperties': False,
}


module = define_module(
    router_factory=_get_router,
    interceptors=[_purge_blocker_interceptor()],
    on_startup_hook=_register_event_payloads,
    on_install_async_hook=_seed_default_profile,
    register_contributions_hook=_register_scan_provider,
    consumes_stock_quant=True,
    settings_schema=DOCUMENTS_SETTINGS_SCHEMA,
    default_settings={
        'over_receipt_tolerance_percent': 0,
        'over_receipt_ceiling_percent': 0,
        'scan_session_idle_minutes': 30,
    },
)
