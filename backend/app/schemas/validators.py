"""Shared Pydantic validators and serializers for Decimal/str coercion.

These helpers are used across schemas (items, stock takes, templates, etc.)
to avoid copy-pasting the same field_validator / field_serializer bodies.
"""

import re
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Annotated, Any, Literal

from pydantic import AfterValidator

from app.core.scan_links import scanned_code

_SKU_RE = re.compile(r'^[A-Z0-9][A-Z0-9\-_/]{0,49}$')


def decimal_from_int_float(v: Any) -> Any:
    """Convert int/float to Decimal; pass None, str and a bool through unchanged.

    A bool is an ``int`` to Python but not a number in a JSON body: it is
    handed back so the field's own type check refuses it.

    Suitable as a Pydantic ``BeforeValidator`` or inline in a
    ``@field_validator``.
    """
    if v is None:
        return v
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return Decimal(str(v))
    return v


#: The quantity columns' shape — numeric(QUANTITY_MAX_DIGITS, QUANTITY_SCALE)
#: everywhere a quantity lands in the store. The column, the schemas and the
#: forms derive their bounds from these constants: the step is what Postgres
#: would otherwise round to silently and banker's-style, and the ceiling is
#: the largest value the column can hold — a schema bound (``le=``) on it
#: answers a twelve-digit quantity with a 422 sentence instead of the driver's
#: overflow 500.
QUANTITY_MAX_DIGITS = 12
QUANTITY_SCALE = 3
QUANTITY_STEP = Decimal(1).scaleb(-QUANTITY_SCALE)
QUANTITY_MAX = Decimal(
    f'{"9" * (QUANTITY_MAX_DIGITS - QUANTITY_SCALE)}.{"9" * QUANTITY_SCALE}'
)

#: The orders stock can leave a shelf in — the values
#: ``app.services.stock_strategy.SUPPORTED_STRATEGIES`` resolves. A product
#: carries one, a category names the one its new products start with.
RemovalStrategy = Literal['FIFO', 'FEFO']


def quantize_quantity(v: Any) -> Any:
    """Quantize an incoming quantity to the store's precision (3 dp, HALF_UP).

    Pydantic passes 1.0005 through and Postgres rounds it silently; an
    explicit quantize at entry makes the stored number the one the client
    was told about. Use as a Pydantic ``AfterValidator`` on quantity fields.

    A value too wide for the decimal context to quantize is past every
    column: it is returned as it came, for the ceiling of whoever writes it
    to refuse, rather than raising ``InvalidOperation`` out of validation.
    """
    if v is None:
        return v
    number = Decimal(v)
    try:
        return number.quantize(QUANTITY_STEP, rounding=ROUND_HALF_UP)
    except InvalidOperation:
        return number


def empty_string_to_none(v: Any) -> Any:
    """Convert ``''`` to ``None``, pass everything else through."""
    if v == '':
        return None
    return v


def normalize_barcode(v: Any) -> Any:
    """Normalize barcode value using the core barcode utility.

    A value that is not a string goes back as it came: the field's own type
    check refuses it, where ``.strip()`` on it would be a 500.
    """
    from app.core.barcode import normalize_barcode as _normalize

    return _normalize(v) if isinstance(v, str) else v


def normalize_sku(v: Any) -> Any:
    """A SKU as the catalogue keeps it: trimmed, upper-case, blank as ``None``.

    Raises the translated ``sku_format_invalid`` refusal for a value outside
    the shape the ``sku`` column and the product-template door accept.
    """
    if not isinstance(v, str):
        return v
    from app.core.exceptions import ServiceRejectionError

    v = v.strip().upper() or None
    if v and not _SKU_RE.match(v):
        raise ServiceRejectionError('sku_format_invalid')
    return v


#: A request field a scan fills: the code, whatever shape the sticker wrapped
#: it in (``app.core.scan_links``).
ScannedCode = Annotated[str, AfterValidator(scanned_code)]
