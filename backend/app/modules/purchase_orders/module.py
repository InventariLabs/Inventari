"""Purchase Orders module registration."""

from typing import Any
from uuid import UUID

from fastapi import APIRouter

from app.core.context import ModuleContext
from app.core.logging import get_logger
from app.core.modules import BaseModule, ModuleMetadata

logger = get_logger(__name__)

__version__ = '0.8.0'


def _register_approval_target_summaries() -> None:
    """Describe a purchase order to the approvals queue.

    The queue rendered it as eight characters of a UUID — no supplier, no
    amount, no way through to the order — on the screen whose only job is
    deciding about the spend. Registered at import, like the warehouse module
    does, so enrichment does not depend on which organisation started first.
    """
    from app.modules.approvals.approvals_api import approvals_api

    from .purchase_orders_api import purchase_orders_api

    approvals_api.register_target_summary_provider(
        'purchase_order', purchase_orders_api.get_target_summaries_by_ids_async
    )


_register_approval_target_summaries()


def _register_work_item_provider() -> None:
    """Put the orders that expect goods into To do.

    Registered at import, like the other cross-module providers, so the list
    does not depend on which organisation started first; the warehouse module
    only calls it while this module is enabled for the organisation asking.
    """
    from app.modules.purchase_orders.purchase_orders_api import (
        purchase_orders_api,
    )
    from app.modules.warehouse.warehouse_api import warehouse_api

    warehouse_api.register_work_item_provider(
        'purchase_orders', purchase_orders_api.list_work_items_async
    )


_register_work_item_provider()


def _register_over_order_check() -> None:
    """Hold a receipt to what its order line still has left.

    The warehouse asks a pre-post check of every module enabled for the
    organization when it confirms and when it completes a document; ours
    refuses a document that overdraws an order line it names. Registered at
    import, like the other cross-module providers.
    """
    from app.modules.purchase_orders._over_order_check import (
        MODULE,
        refuse_receipt_past_order_async,
    )
    from app.modules.warehouse.warehouse_api import warehouse_api

    warehouse_api.register_pre_post_check(MODULE, refuse_receipt_past_order_async)


_register_over_order_check()


def _register_approval_decision_listener() -> None:
    """Follow requests the approvals engine releases about our orders.

    Without it a request released by switching its workflow off left the order
    parked in PENDING_APPROVAL for good.
    """
    from app.modules.approvals.approvals_api import approvals_api
    from app.modules.purchase_orders._approval_decisions import (
        apply_approval_decision,
    )

    approvals_api.register_target_decision_listener(
        'purchase_order', apply_approval_decision
    )


_register_approval_decision_listener()


def _register_approval_scope_provider() -> None:
    """Tell the approvals screen what a purchase-order workflow would hold.

    The order settings decide what waits; the workflow on its own holds
    nothing, and the screen has to say so before anyone switches it on.
    """
    # Absolute, like the warehouse module's registrations: a relative import
    # reached from the registry's own import of this package binds a second
    # copy of the models to the same metadata.
    from app.modules.approvals.approvals_api import approvals_api
    from app.modules.purchase_orders._approval_scope import (
        describe_po_approval_scope,
    )

    approvals_api.register_target_scope_provider(
        'purchase_order', describe_po_approval_scope
    )


_register_approval_scope_provider()


def _register_supplier_prices() -> None:
    """Provide estimates through the Core port without a Core module import."""
    from app.core.cost_estimates import register_supplier_price_provider
    from app.modules.purchase_orders._estimate_prices import supplier_rates_async

    register_supplier_price_provider(supplier_rates_async)


_register_supplier_prices()


class PurchaseOrdersModule(BaseModule):
    """Purchase Orders warehouse module."""

    def __init__(self) -> None:
        self._metadata = ModuleMetadata(
            name='purchase_orders',
            version=__version__,
            display_name='Purchase Orders',
            description='Purchase order management for warehouse operations',
            icon='truck',
            category='business',
            module_type='official',
            requires=['items', 'locations', 'warehouse'],
            consumes_stock_quant=True,
        )

    @property
    def metadata(self) -> ModuleMetadata:
        return self._metadata

    def register_routes(self) -> APIRouter:
        from app.modules.purchase_orders.router import router

        return router

    def on_startup(self, context: ModuleContext) -> None:
        super().on_startup(context)
        self._context = context

        from app.core.contracts.events import (
            PurchaseOrderCancelledPayload,
            PurchaseOrderCompletedPayload,
            PurchaseOrderConfirmedPayload,
            ReceiptCreatedFromPOPayload,
        )
        from app.core.public_api import core_api

        # These four names are this module's own: the core table no longer
        # lists them, so the registration below is what makes them known.
        core_api.events.register_payload(
            'purchase_order.confirmed', PurchaseOrderConfirmedPayload
        )
        core_api.events.register_payload(
            'purchase_order.completed', PurchaseOrderCompletedPayload
        )
        core_api.events.register_payload(
            'purchase_order.cancelled', PurchaseOrderCancelledPayload
        )
        core_api.events.register_payload(
            'receipt.created_from_po', ReceiptCreatedFromPOPayload
        )

        # By string, not by importing app.modules.warehouse.events: an event
        # name is a contract, another module's code is not (see the docstring
        # of DocumentEvent). These two used to read SystemEvent.DOCUMENT_*,
        # which was the warehouse module's surface parked in the core table.
        context.subscribe('document.cancelled', self._handle_document_cancelled)
        context.subscribe('document.completed', self._handle_document_completed)

    async def _recalc_po_from_event(self, payload: Any, event_label: str) -> None:
        """Shared recalculation logic for DOCUMENT_COMPLETED / DOCUMENT_CANCELLED."""
        from app.core.public_api import core_api

        from ._service_workflow import recalculate_po_quantities

        org_id_str = getattr(payload, 'organization_id', None)
        if not org_id_str:
            return

        lines_data = getattr(payload, 'lines', []) or []
        po_line_ids: list[UUID] = []
        for ld in lines_data:
            po_line_id_str = (
                ld.get('source_po_line_id') if isinstance(ld, dict) else None
            )
            if po_line_id_str:
                try:
                    po_line_ids.append(UUID(po_line_id_str))
                except (ValueError, TypeError):
                    pass

        if not po_line_ids:
            return

        try:
            async with self._context.tenant_session(org_id_str) as db:
                await recalculate_po_quantities(db, UUID(org_id_str), po_line_ids)
                await db.commit()
                await core_api.events.flush_pending_async(db.raw_session)
        except Exception:  # EventBus._safe_execute swallows handler errors by design
            logger.exception(
                '[purchase_orders] Failed to recalculate quantities '
                'after %s — quantity_received may be stale',
                event_label,
            )
            await self._notify_recalc_failure(org_id_str, po_line_ids)

    async def _handle_document_cancelled(self, payload: Any) -> None:
        """Recalculate PO quantities when a linked receipt is cancelled."""
        await self._recalc_po_from_event(payload, 'document cancellation')

    async def _handle_document_completed(self, payload: Any) -> None:
        """Recalculate PO quantities when a linked receipt is completed."""
        await self._recalc_po_from_event(payload, 'document completion')

    async def _notify_recalc_failure(
        self, org_id_str: str, po_line_ids: list[UUID]
    ) -> None:
        """Notify org admins that PO quantity recalculation failed."""
        from app.core.public_api import core_api

        from . import _notification_labels as _labels

        try:
            async with self._context.tenant_session(org_id_str) as db:
                admin_notifications = (
                    await core_api.notifications.notify_org_admins_async(
                        db.raw_session,
                        organization_id=UUID(org_id_str),
                        title=core_api.notifications.localize(
                            _labels.RECALC_FAILED_TITLE
                        ),
                        content=core_api.notifications.localize(
                            _labels.RECALC_FAILED_CONTENT, lines=len(po_line_ids)
                        ),
                        notification_type='warning',
                    )
                )
                await db.commit()
                await core_api.notifications.publish_async(
                    db.raw_session, admin_notifications
                )
        except Exception:  # noqa: BLE001 — the notice is best-effort
            logger.error(
                '[purchase_orders] Failed to notify admins about recalc failure'
            )
