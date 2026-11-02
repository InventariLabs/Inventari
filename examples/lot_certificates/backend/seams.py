"""What this module plugs into the warehouse, and nothing else.

Four seams, each registered through ``warehouse_api`` (the manifest's
``"requires": ["warehouse"]`` is what lets a module from outside import it):

- a **required field**: a receipt line with a lot is not confirmed without the
  number of its certificate, kept on the line under this module's name;
- a **receiving rule**: a lot is not booked while that certificate is not on
  file in this module's own register;
- a **pick order**: zone by zone, the heaviest lines of each zone first;
- a **filter** of the documents list: the documents with a lot whose
  certificate is on file.

The module keeps no copy of a document and overrides no warehouse code: the
line's field is the warehouse's ``meta_data``, the refusal is a pre-post check
inside the warehouse's own posting, the walk is a strategy the organization
picks in the warehouse settings.
"""

from collections.abc import Sequence
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import (
    DocumentFilterDTO,
    DocumentToPostDTO,
    PickOrderLineDTO,
    PickOrderLocationDTO,
)
from app.core.module_sdk import InterceptorError, get_module_error_message
from app.core.public_api import core_api
from app.modules.warehouse.warehouse_api import warehouse_api

from .certificates import all_numbers_on_file_async, numbers_on_file_async
from .models import NUMBER_MAX_LENGTH

MODULE = 'lot_certificates'

#: The name the organization picks in the warehouse settings, offered there
#: under ``lot_certificates:pickOrderStrategies.by_zone_then_weight``.
PICK_ORDER = 'by_zone_then_weight'

#: The documents-list filter, sent by the list as ``lot_certificates:certified``.
FILTER = 'certified'


def certificate_number(meta_data: dict[str, Any]) -> str | None:
    """The number this module wrote on a line, or None when it wrote none.

    The module reads its own key and only its own key. A blank number is
    none; any other is read as written, the same way by the rule, the
    register and the filter, so none of them calls a lot certified that
    another does not.
    """
    number = meta_data.get(MODULE, {}).get('number')
    if isinstance(number, str) and number.strip():
        return number
    return None


async def require_certificates(
    db: AsyncSession, org_id: UUID, document: DocumentToPostDTO
) -> None:
    """Refuse a receipt whose lots are not certified.

    At ``confirm``: every line with a lot names its certificate, in a number
    the register can file. At ``post``:
    every certificate named is on file. The one-step post asks both, inside
    one transaction, so a refusal at either leaves nothing written.
    """
    if document.type != 'IN':
        return None
    lots = [line for line in document.lines if line.batch_number]
    for line in lots:
        number = certificate_number(line.meta_data)
        if number is None:
            raise InterceptorError(
                get_module_error_message(
                    MODULE, 'number_missing', lot=line.batch_number
                ),
                error_code='CERTIFICATE_NUMBER_MISSING',
            )
        if len(number) > NUMBER_MAX_LENGTH:
            raise InterceptorError(
                get_module_error_message(
                    MODULE,
                    'number_too_long',
                    lot=line.batch_number,
                    limit=NUMBER_MAX_LENGTH,
                ),
                error_code='CERTIFICATE_NUMBER_TOO_LONG',
            )
    if document.stage != 'post':
        return None
    named = {certificate_number(line.meta_data) or '' for line in lots}
    absent = sorted(named - await numbers_on_file_async(db, org_id, named))
    if absent:
        raise InterceptorError(
            get_module_error_message(
                MODULE, 'certificate_not_on_file', number=absent[0]
            ),
            error_code='CERTIFICATE_NOT_ON_FILE',
        )
    return None


def _zone(line: PickOrderLineDTO) -> PickOrderLocationDTO | None:
    """The place the line's shelf stands in — the shelf itself at the top."""
    path = line.location_path
    if len(path) >= 2:
        return path[-2]
    return path[0] if path else None


async def by_zone_then_weight(
    db: AsyncSession, org_id: UUID, lines: list[PickOrderLineDTO]
) -> Sequence[PickOrderLineDTO]:
    """Walk zone by zone; inside a zone take the heaviest line first.

    Zones follow the numbers the warehouse gave them, then their code and
    name. A line's weight is its product's weight times its quantity, in the
    reference unit of the product's weight unit; a product nobody weighed
    weighs nothing and comes last in its zone. Lines with no shelf come last.
    """
    template_ids = sorted(
        {line.product_template_id for line in lines if line.product_template_id}
    )
    templates = await core_api.product_templates.get_many_async(
        db, org_id, template_ids
    )

    def weight(line: PickOrderLineDTO) -> Decimal:
        template = (
            templates.get(line.product_template_id)
            if line.product_template_id
            else None
        )
        if template is None or template.weight_value is None:
            return Decimal(0)
        factor = template.weight_uom.factor if template.weight_uom else Decimal(1)
        return Decimal(str(template.weight_value)) * factor * line.quantity

    def key(line: PickOrderLineDTO) -> tuple[Any, ...]:
        zone = _zone(line)
        if zone is None:
            return (True, True, 0, '', '', Decimal(0))
        return (
            False,
            zone.sequence is None,
            zone.sequence or 0,
            zone.short_code or '',
            zone.name or '',
            -weight(line),
        )

    return sorted(lines, key=key)


async def certified(db: AsyncSession, org_id: UUID) -> DocumentFilterDTO:
    """The documents with a line whose certificate is on file.

    What the receiving rule asks at posting: a blank number, or one nobody
    filed, does not make a lot certified. Every number on file is one
    fragment; a register of thousands would want a narrower question.
    """
    numbers = await all_numbers_on_file_async(db, org_id)
    return DocumentFilterDTO(line_meta_data=[{'number': n} for n in numbers])


def register_seams() -> None:
    """Plug the module into the warehouse.

    Called once at import. Registering again replaces the same entries, so a
    reload — or a test that put something else under this name — is undone
    by calling it again.
    """
    warehouse_api.register_pre_post_check(MODULE, require_certificates)
    warehouse_api.register_pick_order_strategy(MODULE, PICK_ORDER, by_zone_then_weight)
    warehouse_api.register_document_filter(MODULE, FILTER, certified)
