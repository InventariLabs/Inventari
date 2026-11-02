"""PO settings REST endpoints (approval config).

Mounted at:
- GET /api/v1/purchase-orders/settings
- PUT /api/v1/purchase-orders/settings

Registered BEFORE ``register_po_routes``: ``/settings`` (single segment)
would otherwise be captured by ``GET /{po_id}`` and fail UUID validation.

Reading answers to the module router's ``purchase_orders:read``: anyone who
works with orders sees the threshold in the confirm dialog. Writing answers
to ``purchase_orders:manage`` on top of the router's ``:write`` — whether an
order needs approval is not a buyer's own call, or a member could lower the
control meant to stop their orders.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts.dtos import UserContextDTO
from app.core.deps import (
    get_async_db,
    get_current_user_context,
    require_org,
    require_permission,
)
from app.core.settings_diff import journal_config_change, record_settings

from ._service_settings import (
    UNSET,
    get_or_create_po_settings,
    upsert_po_settings,
)
from ._update_canon import refuse_named_nulls
from .schemas import POSettingsSchema, POSettingsUpdate


def register_settings_routes(router: APIRouter) -> None:
    @router.get('/settings', response_model=POSettingsSchema)
    async def get_settings(
        current_user: UserContextDTO = Depends(get_current_user_context),
        db: AsyncSession = Depends(get_async_db, scope='function'),
        org_id: UUID = Depends(require_org),
    ) -> POSettingsSchema:
        settings = await get_or_create_po_settings(db, org_id)
        return POSettingsSchema.model_validate(settings)

    @router.put(
        '/settings',
        response_model=POSettingsSchema,
        dependencies=[require_permission('purchase_orders:manage')],
    )
    async def update_settings(
        data: POSettingsUpdate,
        current_user: UserContextDTO = Depends(get_current_user_context),
        db: AsyncSession = Depends(get_async_db, scope='function'),
        org_id: UUID = Depends(require_org),
    ) -> POSettingsSchema:
        # The payload answers two ways about the threshold: naming the
        # field with null clears it, omitting the field leaves it alone —
        # and those are different instructions the service must tell
        # apart.
        # §2b: approval_required backs a NOT NULL column, so naming it
        # with null is refused by name. The threshold above stays
        # tri-state: absent = leave, null = clear, value = set.
        refuse_named_nulls(data, {'approval_required'})
        sent = data.model_fields_set
        # Copy the before-side before the write: the upsert mutates this
        # same row, and a live reference would read the after-values.
        before = {
            key: value
            for key, value in record_settings(
                await get_or_create_po_settings(db, org_id)
            ).items()
            if key in {'approval_required', 'approval_threshold'}
        }
        settings = await upsert_po_settings(
            db,
            org_id,
            approval_threshold=(
                data.approval_threshold if 'approval_threshold' in sent else UNSET
            ),
            approval_required=data.approval_required,
        )
        # Whether a purchase order needs anyone's approval is the sharpest
        # switch this module owns; turning it used to leave no trace.
        await journal_config_change(
            db,
            org_id,
            current_user.id,
            module='purchase_orders',
            subject='settings',
            keys={'approval_required', 'approval_threshold'},
            before=before,
            after=settings,
        )
        return POSettingsSchema.model_validate(settings)
