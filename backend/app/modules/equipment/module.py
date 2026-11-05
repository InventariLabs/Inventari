from typing import Any

from app.core.logging import get_logger
from app.core.modules import BaseModule

from ._module_declarations import build_equipment_metadata


def _register_export_enricher() -> None:
    """Register the XLSX export enrichment (Assigned To) with Core's registry.

    Core must not import a feature module (architecture lint), so
    the equipment module registers itself here at import time — the same
    pattern as ``warehouse`` and ``app.core.period_guard``.
    """
    from app.core.export_enrichers import register_export_enricher

    from .export_enricher import get_active_assignments_map_async

    register_export_enricher('equipment', get_active_assignments_map_async)


_register_export_enricher()


def _register_record_placement() -> None:
    """Tell Core where a checked-out asset stands: the place it was checked
    out to, while it is there. Core's location counts and the module's own
    list, filter and sort then read one answer."""
    from app.core.module_ownership import register_record_placement

    from ._assets_service import open_placements

    register_record_placement('equipment', open_placements)


_register_record_placement()


def _register_approval_target_summaries() -> None:
    """Describe an equipment checkout to the approvals queue.

    The queue rendered a checkout as eight characters of a UUID — no asset
    name, no serial, no way through to the equipment page — on the screen
    whose only job is deciding whether to allow the checkout. Registered at
    import, like the warehouse and purchase_orders modules do, so enrichment
    does not depend on which organisation happened to start first.
    """
    from app.modules.approvals.approvals_api import approvals_api

    from ._approval_summaries import get_target_summaries_by_ids_async

    approvals_api.register_target_summary_provider(
        'equipment_checkout', get_target_summaries_by_ids_async
    )

    # The card names the asset, so the queue's search finds it by that name
    # (or its serial) — the asset list's own search, the same matches.
    from ._assets_service import list_matching_asset_ids_async

    async def _search(db: Any, org_id: Any, text: str) -> list[Any]:
        return await list_matching_asset_ids_async(db, org_id, search=text)

    approvals_api.register_target_search_provider('equipment_checkout', _search)


_register_approval_target_summaries()


def _register_approval_scope_provider() -> None:
    """Tell the approvals screen that a checkout workflow holds every checkout.

    Equipment has no settings that filter checkouts: the assignment gate asks
    approvals whenever a checkout workflow is active (``_assignment_service``,
    ``bulk_service``), so the switch-on dialog has to say "every checkout of
    every asset" — whatever the organization configured.
    """
    from app.modules.approvals.approvals_api import WorkflowScope, approvals_api

    approvals_api.register_target_scope_provider(
        'equipment_checkout',
        approvals_api.fixed_target_scope(WorkflowScope(holds='all')),
    )


_register_approval_scope_provider()


class EquipmentModule(BaseModule):
    def __init__(self) -> None:
        self._metadata = build_equipment_metadata()

    @property
    def metadata(self) -> Any:
        return self._metadata

    def get_settings_schema(self) -> dict[str, Any] | None:
        return {
            'type': 'object',
            'properties': {
                'warranty_warning_days': {
                    'type': 'integer',
                    'default': 30,
                    'minimum': 1,
                    'maximum': 365,
                    'title': 'Warranty warning window (days)',
                    'title_key': 'equipment:settings.warrantyWarningDays',
                    'description_key': 'equipment:settings.warrantyWarningDaysDescription',
                    'description': (
                        'How many days before warranty expiry an alert is raised.'
                    ),
                },
                'maintenance_warning_days': {
                    'type': 'integer',
                    'default': 7,
                    'minimum': 1,
                    'maximum': 90,
                    'title': 'Maintenance warning window (days)',
                    'title_key': 'equipment:settings.maintenanceWarningDays',
                    'description_key': 'equipment:settings.maintenanceWarningDaysDescription',
                    'description': (
                        'How many days before scheduled maintenance an alert is raised.'
                    ),
                },
                # Fallback depreciation period for
                # categories that declare no default of their own.
                'default_useful_life_years': {
                    'type': 'integer',
                    'default': 5,
                    'minimum': 1,
                    'maximum': 50,
                    'title': 'Default useful life (years)',
                    'title_key': 'equipment:settings.defaultUsefulLifeYears',
                    'description_key': 'equipment:settings.defaultUsefulLifeYearsDescription',
                    'description': (
                        'Depreciation period used for categories without '
                        'their own default.'
                    ),
                },
            },
            'additionalProperties': False,
        }

    def get_default_settings(self) -> dict[str, Any]:
        return {
            'warranty_warning_days': 30,
            'maintenance_warning_days': 7,
            'default_useful_life_years': 5,
        }

    def register_routes(self) -> Any:
        from .router import router

        return router

    def on_startup(self, context: Any) -> None:
        from datetime import timedelta

        from app.core.logging import get_logger

        log = get_logger(__name__)

        BaseModule.on_startup(self, context)

        from app.core.contracts.events import (
            EquipmentCheckinPayload,
            EquipmentCheckoutPayload,
        )
        from app.core.public_api import core_api

        # Ownership claims ahead of the planned move of these classes out of
        # the core table — no-ops while the core table still lists them.
        core_api.events.register_payload('equipment.checkout', EquipmentCheckoutPayload)
        core_api.events.register_payload('equipment.checkin', EquipmentCheckinPayload)

        try:
            core_api.scheduler.register_task(
                'attestation_reminder_check',
                timedelta(hours=6),
                self._attestation_reminder_worker,
                module_name='equipment',
            )
            core_api.scheduler.register_task(
                'equipment_notification_check',
                timedelta(hours=6),
                self._equipment_notification_worker,
                module_name='equipment',
            )
        except (ImportError, AttributeError):
            log.warning(
                '[equipment] TaskScheduler unavailable — attestation reminders disabled.'
            )

    def register_contributions(self) -> None:
        from typing import cast

        from app.core.contributions import BaseContribution, contribution_registry

        from .interceptors import EquipmentItemInterceptor
        from .resolvers import EquipmentAttachmentResolver

        contribution_registry.register(
            'item_interceptors', cast(BaseContribution, EquipmentItemInterceptor())
        )
        contribution_registry.register(
            'upload_path_resolvers',
            cast(BaseContribution, EquipmentAttachmentResolver()),
        )

    async def _attestation_reminder_worker(
        self, payload: dict[str, Any] | None = None
    ) -> None:
        from .attestation_service import run_attestation_reminder_self_contained

        log = get_logger(__name__)
        try:
            await run_attestation_reminder_self_contained()
        except Exception:  # worker loop must never crash
            log.exception('[equipment] Error in attestation reminder worker')

    async def _equipment_notification_worker(
        self, payload: dict[str, Any] | None = None
    ) -> None:
        from .notification_worker import run_notification_check_self_contained

        log = get_logger(__name__)
        try:
            await run_notification_check_self_contained()
        except Exception:  # worker loop must never crash
            log.exception('[equipment] Error in notification worker')
