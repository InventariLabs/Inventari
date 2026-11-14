"""The two guarded write tools: create a record, correct a quantity.

Both follow the Core's own doors rather than writing a table: a record is
created through ``core_api.items.create_async``, which posts its opening
movement, and a quantity is corrected through the stock posting rules of
``backend/AGENTS.md`` — the group's anchor locked first, one
``update_quantity_async`` that writes the record, the movement and the cost
layer together, and the register's copy through the Warehouse module's public
API. The register copy is absent, not refused, when Warehouse is off: the
stock still moves and the correction says so.

Every call leaves two kinds of trace. The item history carries the reason
(``mcp_create`` / ``mcp_correction`` plus the caller's own words and the call
id), and the organization journal gets one row naming the tool, the call and
the parameters that are safe to keep. The API key itself is never written;
the journal's actor is the key's prefix, set by the authentication path.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Annotated, Any
from uuid import UUID, uuid4

from mcp.server.mcpserver import MCPServer
from mcp_types import ToolAnnotations
from pydantic import Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import (
    AuditAction,
    AuditTargetType,
    CountDifferenceDTO,
    ItemCreateDTO,
)
from app.core.public_api import core_api
from app.modules.warehouse.warehouse_api import warehouse_api

from .._db import request_session
from .._identity import McpIdentity, current_identity, refusal
from ..schemas import CorrectStockResult, ItemView

_CREATE = ToolAnnotations(destructiveHint=False, idempotentHint=False)
_CORRECT = ToolAnnotations(destructiveHint=True, idempotentHint=False)


async def _journal_the_call_async(
    db: AsyncSession,
    identity: McpIdentity,
    *,
    tool: str,
    call_id: UUID,
    target_id: UUID,
    action: AuditAction,
    reason: str,
    snapshot: dict[str, Any],
    parameters: dict[str, Any],
) -> None:
    """One journal row per tool call, beside the change the Core already logs.

    The Core's own posting writes the quantity change; this row says which
    tool asked for it and under which call id, so an operator reading the
    organization log can tell an agent's correction from one typed at the
    screen. The key travels as the journal's actor (``meta_data['actor']``),
    set where the request authenticated, never as a parameter here.
    """
    await core_api.audit_log.log_action_async(
        db,
        organization_id=identity.organization_id,
        user_id=identity.user_id,
        action=action,
        target_type=AuditTargetType.ITEM,
        target_id=target_id,
        snapshot=snapshot,
        reason=reason,
        meta_data={
            'tool': tool,
            'mcp_request_id': str(call_id),
            'parameters': parameters,
        },
    )


def register_write_tools(server: MCPServer) -> None:
    @server.tool(
        name='create_item',
        title='Create a stock record',
        description=(
            'Create one stock record and put its quantity on a shelf: a new '
            'product, a new batch of one, or a unit of something. The record '
            'gets its opening movement and its history row, so it counts as '
            'stock from this call on. Name the product with name, or point at '
            'an existing product card with template_id to avoid a duplicate. '
            'Use correct_stock to change a quantity that already exists; use '
            'search_items first when the product may already be on a shelf. '
            'Example: create_item(name="Olive oil", quantity=6, '
            'location_id="<a shelf id>").'
        ),
        annotations=_CREATE,
    )
    async def create_item(
        name: Annotated[
            str, Field(description='What the record is; a product or a unit name.')
        ],
        location_id: Annotated[
            UUID, Field(description='The shelf the stock stands on.')
        ],
        quantity: Annotated[
            Decimal, Field(description='How much arrives (0 or more).')
        ] = Decimal('1'),
        brand: Annotated[str | None, Field(description='The product brand.')] = None,
        barcode: Annotated[
            str | None, Field(description='The package barcode, when there is one.')
        ] = None,
        serial_number: Annotated[
            str | None,
            Field(description='A serial number, for a record tracked by one.'),
        ] = None,
        category_id: Annotated[
            UUID | None, Field(description='The category to file the product under.')
        ] = None,
        template_id: Annotated[
            UUID | None,
            Field(
                description=(
                    'The product card to attach the record to; omit to match '
                    'one by name or barcode, or to create one.'
                )
            ),
        ] = None,
        expiry_date: Annotated[
            date | None, Field(description='The batch expiry date, when it has one.')
        ] = None,
        metadata: Annotated[
            dict[str, Any] | None,
            Field(description='Namespaced metadata; a module reads its own key.'),
        ] = None,
    ) -> ItemView:
        """Create one stock record, with its opening movement and history."""
        identity = current_identity()
        identity.require('items:write')
        call_id = uuid4()
        data = ItemCreateDTO(
            name=name,
            quantity=quantity,
            location_id=location_id,
            brand=brand,
            barcode=barcode,
            serial_number=serial_number,
            category_id=category_id,
            template_id=template_id,
            expiry_date=expiry_date,
            metadata=metadata,
        )
        async with request_session() as db:
            item = await core_api.items.create_async(
                db,
                identity.organization_id,
                data,
                identity.user,
                history_changes={
                    'reason': 'mcp_create',
                    'mcp_request_id': str(call_id),
                },
            )
            await _journal_the_call_async(
                db,
                identity,
                tool='create_item',
                call_id=call_id,
                target_id=item.id,
                action=AuditAction.CREATE,
                reason='mcp_create',
                snapshot={
                    'name': item.name,
                    'quantity': item.quantity,
                    'location_id': str(item.location_id),
                    'template_id': str(item.template_id)
                    if item.template_id is not None
                    else None,
                },
                parameters={
                    'name': name,
                    'quantity': str(quantity),
                    'location_id': str(location_id),
                    'template_id': str(template_id)
                    if template_id is not None
                    else None,
                },
            )
        return ItemView.from_dto(item)

    @server.tool(
        name='correct_stock',
        title='Correct a stock quantity',
        description=(
            'Set one stock record to the quantity that is actually on the '
            'shelf, with a reason the journal can show. This writes the '
            'movement and cost layer and, when the Warehouse module is on, '
            'one adjustment document in the register; the record history and '
            'the organization log carry the reason. It is destructive: the '
            'quantity replaces what the record held. Use it after a count, '
            'never to receive or issue goods — a receipt or issue is a '
            'document, not a correction. A reason is required. Example: '
            'correct_stock(item_id="<id>", quantity=4, reason="Two bottles '
            'broke in the cold room").'
        ),
        annotations=_CORRECT,
    )
    async def correct_stock(
        item_id: Annotated[UUID, Field(description='The record id from search_items.')],
        quantity: Annotated[
            Decimal, Field(description='The quantity the shelf actually holds.')
        ],
        reason: Annotated[
            str,
            Field(
                description=(
                    'Why the quantity changes; kept in the record history and '
                    'the organization journal.'
                )
            ),
        ],
    ) -> CorrectStockResult:
        """Set one record's quantity through a locked, posted correction."""
        identity = current_identity()
        identity.require('items:write')
        reason = (reason or '').strip()
        if not reason:
            raise refusal('REASON_REQUIRED', 'reason_required')
        if quantity < 0:
            raise refusal('QUANTITY_INVALID', 'quantity_not_negative')
        call_id = uuid4()
        async with request_session() as db:
            item = await core_api.items.get_async(db, identity.organization_id, item_id)
            if item is None:
                raise refusal('ITEM_NOT_FOUND', 'item_not_found', item_id=str(item_id))

            # Every group this call writes is locked first, in one order, so
            # two corrections of the same product and shelf wait for each
            # other instead of deadlocking (backend/AGENTS.md, Stock Posting
            # Rules). A record with no product card joins no group.
            keys = (
                [(item.template_id, item.location_id)]
                if item.template_id is not None
                else []
            )
            await core_api.stock.lock_async(db, identity.organization_id, keys=keys)

            updated = await core_api.items.update_quantity_async(
                db,
                identity.organization_id,
                item_id,
                quantity,
                user_id=identity.user_id,
                history_changes={
                    'reason': 'mcp_correction',
                    'reason_text': reason,
                    'mcp_request_id': str(call_id),
                },
                move_reference_type='adjustment',
                move_reference_id=call_id,
            )
            if updated is None:
                raise refusal('ITEM_NOT_FOUND', 'item_not_found', item_id=str(item_id))

            previous = item.quantity if item.quantity is not None else Decimal('0')
            delta = quantity - previous
            # The register's copy is written in the same transaction as the
            # stock; a module that is off answers None and the stock still
            # moves. A correction that changes nothing leaves no document.
            recorded = None
            if delta != 0:
                batch_number = None
                if item.lot_id is not None:
                    lot = await core_api.stock.get_lot_detail_async(
                        db, identity.organization_id, item.lot_id
                    )
                    batch_number = lot.name if lot is not None else None
                recorded = await warehouse_api.record_count_differences_async(
                    db,
                    identity.organization_id,
                    identity.user_id,
                    location_id=item.location_id,
                    differences=[
                        CountDifferenceDTO(
                            item_id=item.id,
                            location_id=item.location_id,
                            product_template_id=item.template_id,
                            name=item.name,
                            quantity_delta=delta,
                            uom_id=item.uom_id,
                            batch_number=batch_number,
                            notes=reason,
                        )
                    ],
                    reference=f'mcp:{call_id}',
                    notes=reason,
                )

            await _journal_the_call_async(
                db,
                identity,
                tool='correct_stock',
                call_id=call_id,
                target_id=item.id,
                action=AuditAction.QUANTITY_CHANGE,
                reason='mcp_correction',
                snapshot={
                    'name': item.name,
                    'before': {'quantity': str(previous)},
                    'after': {'quantity': str(quantity)},
                    'reason_text': reason,
                },
                parameters={
                    'item_id': str(item.id),
                    'quantity': str(quantity),
                    'reason': reason,
                },
            )
        return CorrectStockResult(
            item=ItemView.from_dto(updated),
            previous_quantity=previous,
            # The stored value, not the argument: the record holds three
            # decimals and the answer should read like the record.
            quantity=updated.quantity if updated.quantity is not None else quantity,
            reference=call_id,
            register_document_id=recorded[0] if recorded is not None else None,
            register_document_number=recorded[1] if recorded is not None else None,
        )
