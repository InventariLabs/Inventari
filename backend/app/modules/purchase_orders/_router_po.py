from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts.dtos import UserContextDTO
from app.core.deps import (
    get_async_db,
    get_current_user_context,
    require_org,
    require_permission,
)
from app.core.exceptions import (
    AppException,
    ConflictException,
    NotFoundException,
    catalogue_refusal,
)
from app.core.logging import get_logger
from app.core.module_sdk import PaginatedResponse
from app.core.public_api import core_api
from app.i18n.service import get_current_lang, get_error_message

from ._journal import journal_order_act
from ._po_render_context import build_po_context
from ._service_crud import (
    create_purchase_order as _create_po,
)
from ._service_crud import (
    get_purchase_order as _get_po,
)
from ._service_crud import (
    list_purchase_orders as _list_pos,
)
from ._service_crud import (
    order_line_tallies_async,
)
from ._service_crud import (
    update_purchase_order as _update_po,
)
from ._update_canon import refuse_named_nulls
from .schemas import (
    CreateReceiptFromPO,
    LinkedReceiptSchema,
    OrderLineTally,
    PurchaseOrderCreate,
    PurchaseOrderListResponse,
    PurchaseOrderListRowSchema,
    PurchaseOrderSchema,
    PurchaseOrderUpdate,
    ReceiptFromPOSchema,
    ReplenishmentDraftPosCreate,
    ReplenishmentDraftPosResult,
)

logger = get_logger(__name__)


def register_po_routes(router: APIRouter) -> None:  # noqa: C901, PLR0915 - route registration, one block per endpoint
    @router.post(
        '', response_model=PurchaseOrderSchema, status_code=status.HTTP_201_CREATED
    )
    async def create_purchase_order(
        data: PurchaseOrderCreate,
        current_user: UserContextDTO = Depends(get_current_user_context),
        db: AsyncSession = Depends(get_async_db, scope='function'),
        org_id: UUID = Depends(require_org),
    ) -> PurchaseOrderSchema:
        po = await _create_po(db, org_id, data, current_user.id)
        return PurchaseOrderSchema.model_validate(po)

    # Static path — must outrank ``/{po_id}`` below: without an earlier
    # registration the segment would be parsed as a PO id and 422.
    @router.post(
        '/replenishment/draft-pos',
        response_model=ReplenishmentDraftPosResult,
        status_code=status.HTTP_201_CREATED,
    )
    async def create_replenishment_draft_pos(
        data: ReplenishmentDraftPosCreate,
        current_user: UserContextDTO = Depends(get_current_user_context),
        db: AsyncSession = Depends(get_async_db, scope='function'),
        org_id: UUID = Depends(require_org),
    ) -> ReplenishmentDraftPosResult:
        from .replenishment_service import create_draft_pos_from_alerts_async

        created, skipped = await create_draft_pos_from_alerts_async(
            db, org_id, data.reorder_rule_ids, current_user.id
        )
        return ReplenishmentDraftPosResult(
            created=[PurchaseOrderSchema.model_validate(po) for po in created],
            skipped=skipped,
        )

    @router.get('', response_model=PurchaseOrderListResponse)
    async def list_purchase_orders(
        search: str | None = Query(None, min_length=1),
        po_status: str | None = Query(
            None,
            alias='status',
            pattern='^(DRAFT|PENDING_APPROVAL|CONFIRMED|COMPLETED|CANCELLED)$',
        ),
        partner_id: UUID | None = Query(None),
        with_lines: bool = Query(
            False,
            description=(
                'Also carry every line of each order. The list counts and '
                'sums them on its own; the receive screen, choosing an open '
                "order's lines to receive, asks for them."
            ),
        ),
        limit: int = Query(50, ge=1, le=200),
        offset: int = Query(0, ge=0),
        current_user: UserContextDTO = Depends(get_current_user_context),
        db: AsyncSession = Depends(get_async_db, scope='function'),
        org_id: UUID = Depends(require_org),
    ) -> PurchaseOrderListResponse:
        pos, total = await _list_pos(
            db,
            org_id,
            search=search,
            status=po_status,
            partner_id=partner_id,
            with_lines=with_lines,
            limit=limit,
            offset=offset,
        )
        tallies = await order_line_tallies_async(db, org_id, [po.id for po in pos])
        return PurchaseOrderListResponse.from_slice(
            items=[
                PurchaseOrderListRowSchema.of(
                    PurchaseOrderSchema.model_validate(po),
                    tallies.get(po.id, OrderLineTally()),
                )
                for po in pos
            ],
            offset=offset,
            limit=limit,
            total=total,
        )

    @router.get('/{po_id}', response_model=PurchaseOrderSchema)
    async def get_purchase_order(
        po_id: UUID,
        current_user: UserContextDTO = Depends(get_current_user_context),
        db: AsyncSession = Depends(get_async_db, scope='function'),
        org_id: UUID = Depends(require_org),
    ) -> PurchaseOrderSchema:
        po = await _get_po(db, org_id, po_id)
        if not po:
            raise NotFoundException('purchase_order', get_current_lang())
        return PurchaseOrderSchema.model_validate(po)

    @router.patch('/{po_id}', response_model=PurchaseOrderSchema)
    async def update_purchase_order(
        po_id: UUID,
        data: PurchaseOrderUpdate,
        current_user: UserContextDTO = Depends(get_current_user_context),
        db: AsyncSession = Depends(get_async_db, scope='function'),
        org_id: UUID = Depends(require_org),
    ) -> PurchaseOrderSchema:
        # §2b exception, recorded in §2b: scheduled_date is nullable by
        # column, but the order number carries the date's period — dated by
        # it on create, renumbered when a value change moves it — and the
        # engine's answer for an absent date is "today". Clearing it would
        # strand the number in the old period or, on the next renumber,
        # re-file the order in the current one, so a named null is refused
        # instead of silently read as "leave alone". The clearable columns
        # (partner_id, currency, notes) are decided by presence in the
        # service.
        refuse_named_nulls(data, {'scheduled_date'})
        po = await _update_po(db, org_id, po_id, data, current_user.id)
        return PurchaseOrderSchema.model_validate(po)

    @router.post('/{po_id}/confirm', response_model=PurchaseOrderSchema)
    async def confirm_purchase_order(
        po_id: UUID,
        current_user: UserContextDTO = Depends(get_current_user_context),
        db: AsyncSession = Depends(get_async_db, scope='function'),
        org_id: UUID = Depends(require_org),
    ) -> PurchaseOrderSchema:
        from ._service_workflow import confirm_purchase_order as _confirm_po

        po = await _confirm_po(db, org_id, po_id, current_user.id)
        return PurchaseOrderSchema.model_validate(po)

    @router.post('/{po_id}/cancel', response_model=PurchaseOrderSchema)
    async def cancel_purchase_order(
        po_id: UUID,
        _: None = require_permission('purchase_orders:manage'),
        current_user: UserContextDTO = Depends(get_current_user_context),
        db: AsyncSession = Depends(get_async_db, scope='function'),
        org_id: UUID = Depends(require_org),
    ) -> PurchaseOrderSchema:
        try:
            from ._service_workflow import POHasOpenReceiptsError
            from ._service_workflow import cancel_purchase_order as _cancel_po

            po = await _cancel_po(db, org_id, po_id, current_user.id)
            return PurchaseOrderSchema.model_validate(po)
        except POHasOpenReceiptsError as exc:
            raise ConflictException(
                code='PO_HAS_OPEN_RECEIPTS', message=str(exc.args[0])
            ) from exc

    @router.post(
        '/{po_id}/create-receipt',
        response_model=ReceiptFromPOSchema,
        status_code=status.HTTP_201_CREATED,
    )
    async def create_receipt_from_po(
        po_id: UUID,
        data: CreateReceiptFromPO,
        current_user: UserContextDTO = Depends(get_current_user_context),
        db: AsyncSession = Depends(get_async_db, scope='function'),
        org_id: UUID = Depends(require_org),
    ) -> ReceiptFromPOSchema:
        lines_data = None
        if data.lines is not None:
            lines_data = [ld.model_dump() for ld in data.lines]
        from ._service_workflow import create_receipt_from_po as _create_receipt

        doc = await _create_receipt(
            db,
            org_id,
            po_id,
            current_user.id,
            data.target_location_id,
            lines_data,
        )
        return ReceiptFromPOSchema.model_validate(doc)

    @router.get(
        '/{po_id}/linked-receipts',
        response_model=PaginatedResponse[LinkedReceiptSchema],
    )
    async def list_linked_receipts(
        po_id: UUID,
        limit: int = Query(50, ge=1, le=200),
        offset: int = Query(0, ge=0),
        current_user: UserContextDTO = Depends(get_current_user_context),
        db: AsyncSession = Depends(get_async_db, scope='function'),
        org_id: UUID = Depends(require_org),
    ) -> PaginatedResponse[LinkedReceiptSchema]:
        po = await _get_po(db, org_id, po_id)
        if not po:
            raise NotFoundException('purchase_order', get_current_lang())
        from ._service_workflow import list_linked_receipts as _list_receipts

        receipts = await _list_receipts(db, po_id, org_id)
        return PaginatedResponse.from_full_list(receipts, offset=offset, limit=limit)

    @router.get('/{po_id}/pending-quantities')
    async def get_pending_quantities(
        po_id: UUID,
        current_user: UserContextDTO = Depends(get_current_user_context),
        db: AsyncSession = Depends(get_async_db, scope='function'),
        org_id: UUID = Depends(require_org),
    ) -> dict[str, str]:
        """Return ``{po_line_id: pending_qty}`` for quantities reserved on
        active (DRAFT/CONFIRMED) receipts of this PO.

        Used by the Create Receipt panel to surface an
        "in transit / open receipts" indicator so the operator does not
        over-receive before the first receipt completes. Quantities are
        returned as strings (Decimal-safe) keyed by str(po_line_id).
        """
        po = await _get_po(db, org_id, po_id)
        if not po:
            raise NotFoundException('purchase_order', get_current_lang())
        from app.modules.warehouse.warehouse_api import warehouse_api

        pending = await warehouse_api.get_pending_receipt_quantities_async(
            db, org_id, [line.id for line in po.lines]
        )

        def _qty_str(q: Decimal) -> str:
            """Render a Decimal as an int string when whole, else full."""
            if q == q.to_integral_value():
                return str(int(q))
            return str(q)

        return {str(line_id): _qty_str(qty) for line_id, qty in pending.items()}

    @router.get(
        '/{po_id}/pdf',
        response_class=Response,
    )
    async def download_po_pdf(
        po_id: UUID,
        lang: str = Query(default='en', pattern='^[a-z]{2}(-[A-Z]{2})?$'),
        current_user: UserContextDTO = Depends(get_current_user_context),
        db: AsyncSession = Depends(get_async_db, scope='function'),
        org_id: UUID = Depends(require_org),
    ) -> Response:
        po = await _get_po(db, org_id, po_id)
        if not po:
            raise NotFoundException('purchase_order', get_current_lang())
        if po.status not in {'CONFIRMED', 'COMPLETED'}:
            raise catalogue_refusal('po_pdf_invalid_status', status=po.status)
        try:
            from .po_pdf_service import generate_po_pdf

            pdf_bytes = await generate_po_pdf(po, lang=lang, db=db, org_id=org_id)
        except (
            ValueError,
            KeyError,
            TypeError,
            FileNotFoundError,
            OSError,
            RuntimeError,
        ) as exc:
            raise AppException(
                status_code=500,
                code='INTERNAL_ERROR',
                message=get_error_message(
                    'po_pdf_generation_failed', get_current_lang()
                ),
            ) from exc
        from app.core.utils import build_pdf_response, sanitize_filename

        return build_pdf_response(pdf_bytes, sanitize_filename(po.number, prefix='PO'))

    @router.post(
        '/{po_id}/send-email',
    )
    async def send_po_email(
        po_id: UUID,
        lang: str = Query(default='en', pattern='^[a-z]{2}(-[A-Z]{2})?$'),
        current_user: UserContextDTO = Depends(get_current_user_context),
        db: AsyncSession = Depends(get_async_db, scope='function'),
        org_id: UUID = Depends(require_org),
    ) -> dict[str, str]:
        from ._service_email import send_po_email as _send_po_email

        ok = await _send_po_email(db, po_id, org_id, lang=lang)
        if not ok:
            raise AppException(
                status_code=502,
                code='EMAIL_DELIVERY_FAILED',
                message=get_error_message('email_delivery_failed', get_current_lang()),
            )
        # The send reads the order and changes nothing on it, but who was
        # mailed the order, and when, is a fact about it.
        po = await _get_po(db, org_id, po_id)
        if po is not None and po.partner is not None:
            await journal_order_act(
                db,
                org_id,
                current_user.id,
                po,
                act={
                    'emailed_to': po.partner.email,
                    'partner_id': str(po.partner_id),
                    'partner_name': po.partner.name,
                },
            )
        return {'status': 'ok', 'message': 'Email sent successfully'}

    @router.get('/{po_id}/html')
    async def get_po_html(
        po_id: UUID,
        template_id: UUID | None = None,
        lang: str = Query(default='en', pattern='^[a-z]{2}(-[A-Z]{2})?$'),
        current_user: UserContextDTO = Depends(get_current_user_context),
        db: AsyncSession = Depends(get_async_db, scope='function'),
        org_id: UUID = Depends(require_org),
    ) -> Response:
        po = await _get_po(db, org_id, po_id)
        if not po:
            raise NotFoundException('purchase_order', get_current_lang())

        from pathlib import Path

        templates_dir = Path(__file__).parent / 'templates'

        template_html: str | None = None
        if template_id:
            tpl = await core_api.templates.get_async(
                db, org_id, template_id, module='purchase_orders'
            )
            if tpl:
                template_html = tpl.body_html
        if not template_html:
            logger.warning(
                'No template found for PO %s — using filesystem fallback', po_id
            )
            fs_path = templates_dir / 'po_standard.html'
            if fs_path.exists():
                template_html = fs_path.read_text(encoding='utf-8')

        context = build_po_context(po, lang)
        return Response(
            content=core_api.pdf.render_html(
                template_html, context, templates_dir=templates_dir
            ),
            media_type='text/html',
        )
