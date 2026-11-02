"""Single source of truth for document type groupings and predicates.

All document-type classification logic lives here. Other files MUST import
from this module instead of defining ad-hoc sets.

Canonical types: IN, OUT, INT, INTERNAL_IN, INTERNAL_OUT, CORRECTION,
                 ADJUSTMENT, SCRAP
Legacy codes:    PZ (→IN), WZ (→OUT), MM (→INT),
                 PW (→INTERNAL_IN), RW (→INTERNAL_OUT)

``INTERNAL_IN`` and ``INTERNAL_OUT`` were spelled ``PW`` and ``RW`` — the
Polish abbreviations for *przyjęcie wewnętrzne* and *rozchód wewnętrzny* —
which put two country-specific codes in an otherwise neutral vocabulary. The
Polish spellings stay where they belong: in the ``PL Magazyn`` type labels and
in the ``PL PZ`` print layout.
"""

from __future__ import annotations

from app.core.exceptions import ServiceRejectionError

# ---------------------------------------------------------------------------
# Canonical type constants
# ---------------------------------------------------------------------------

IN = 'IN'
OUT = 'OUT'
INT = 'INT'
INTERNAL_IN = 'INTERNAL_IN'
INTERNAL_OUT = 'INTERNAL_OUT'
CORRECTION = 'CORRECTION'
ADJUSTMENT = 'ADJUSTMENT'
SCRAP = 'SCRAP'

ALL_TYPES: set[str] = {
    IN,
    OUT,
    INT,
    INTERNAL_IN,
    INTERNAL_OUT,
    CORRECTION,
    ADJUSTMENT,
    SCRAP,
}

# ---------------------------------------------------------------------------
# Legacy code mapping (Polish warehouse codes → international)
# ---------------------------------------------------------------------------

LEGACY_MAP: dict[str, str] = {
    'PZ': IN,
    'WZ': OUT,
    'MM': INT,
    'PW': INTERNAL_IN,
    'RW': INTERNAL_OUT,
}


def normalize(doc_type: str) -> str:
    """Translate legacy codes to canonical. Uppercases input."""
    return LEGACY_MAP.get(doc_type.upper(), doc_type.upper())


# ---------------------------------------------------------------------------
# Short codes — what a document number writes for its type
# ---------------------------------------------------------------------------

#: The short, country-neutral code each canonical type wears in a number.
#:
#: ``{TYPE}`` used to write the stored value: a fresh organization's number
#: read ``INTERNAL_OUT/2026/001`` while every label on the screen said ``RW``,
#: and a search for ``OUT/2026/001`` found that document because the one
#: number contained the other. These codes are the module's own, not a
#: country's, so they read the same in every language: the Polish paperwork
#: codes stay where they belong — the ``PL Magazyn`` type labels, which
#: ``{TYPE_LABEL}`` writes into the number.
SHORT_CODES: dict[str, str] = {
    IN: 'IN',
    OUT: 'OUT',
    INT: 'INT',
    INTERNAL_IN: 'IR',
    INTERNAL_OUT: 'II',
    CORRECTION: 'COR',
    ADJUSTMENT: 'ADJ',
    SCRAP: 'SCR',
}


def short_code(doc_type: str) -> str:
    """The short code for *doc_type*.

    Legacy spellings (PZ, WZ, MM, PW, RW) answer with their canonical
    type's code. A value the module does not know keeps the spelling it
    arrived with: purchase orders (``PO``) and production runs (``PR``)
    number through the same engine, and they already carry short codes of
    their own that must not be renamed.
    """
    return SHORT_CODES.get(normalize(doc_type), doc_type)


# ---------------------------------------------------------------------------
# Classification predicates — prefer these over raw set membership
# ---------------------------------------------------------------------------


def is_receipt(t: str) -> bool:
    """Goods coming in: IN, INTERNAL_IN (and legacy PZ, PW)."""
    return t in _RECEIPT


def is_dispatch(t: str) -> bool:
    """Goods going out: OUT, INTERNAL_OUT (and legacy WZ, RW)."""
    return t in _DISPATCH


def is_transfer(t: str) -> bool:
    """Internal transfer between locations: INT (and legacy MM)."""
    return t in _TRANSFER


def is_correction(t: str) -> bool:
    """Post-completion correction document."""
    return t == CORRECTION


def is_adjustment(t: str) -> bool:
    """Stock-take / physical inventory adjustment."""
    return t == ADJUSTMENT


def is_scrap(t: str) -> bool:
    """Scrapped / destroyed items."""
    return t == SCRAP


def is_external_in(t: str) -> bool:
    """Receipt from an external partner. Excludes INTERNAL_IN."""
    return t in {IN, 'PZ'}


def is_internal_in(t: str) -> bool:
    """Internal production receipt (no external partner)."""
    return t == INTERNAL_IN


def is_external_out(t: str) -> bool:
    """Dispatch to an external partner. Excludes INTERNAL_OUT."""
    return t in {OUT, 'WZ'}


def is_internal_out(t: str) -> bool:
    """Internal consumption / issue (no external partner)."""
    return t == INTERNAL_OUT


# ---------------------------------------------------------------------------
# Grouping predicates — used by validators and business rules
# ---------------------------------------------------------------------------


def carries_value(t: str) -> bool:
    """Documents whose lines carry price and VAT: goods coming in or going
    out, from a partner or between the organization's own shelves.

    A transfer moves the same goods to another shelf without changing what
    they are worth; a correction records a difference and a scrap writes
    goods off. None of the three asks for a price, so neither the form nor
    the printout offers one — the screens read the same rule through
    ``showsDocumentValue`` in the frontend.

    What a document *stores* is a different question: a value already
    written is kept, and the register lists it as before.
    """
    return is_receipt(t) or is_dispatch(t)


def requires_target(t: str) -> bool:
    """Documents that must have a target (receiving) location."""
    return t in _REQUIRES_TARGET


def requires_source(t: str) -> bool:
    """Documents that must have a source (dispatch) location."""
    return t in _REQUIRES_SOURCE


def requires_partner(t: str) -> bool:
    """Documents that require an external partner (supplier/customer)."""
    return t in {IN, OUT}


def requires_stock_row(t: str) -> bool:
    """Documents whose lines must name a stock record, not just a product.

    These take goods off a named shelf, and the executors move stock by
    record: a line carrying only a catalogue entry has nothing to take.
    Dispatch and transfer said so and refused. Scrap did not — it treated the
    record as optional, found no location either, skipped the whole stock
    block and let the document close as COMPLETED. The register then held a
    write-off of goods still on the shelf, which is worse than a refusal.
    """
    return t in _REQUIRES_STOCK_ROW


def allows_negative_quantity(t: str) -> bool:
    """Types whose lines may carry a quantity of zero or less.

    Only a correction may: its lines *are* deltas, and a delta of -2 is the
    whole point of the document. Everywhere else a line is an amount, and the
    totals every screen reads — "Plan", "received X of Y", the picking and
    receiving counters — are plain sums over them, so one negative row makes
    an incomplete receipt report a complete one. The rule lives here, beside
    the type, rather than in whichever writer happens to check: line import
    wrote straight to the table and so asked nobody, which is how a receipt
    of 5 + 2 + (-5) came to declare a plan of 2.
    """
    return is_correction(t)


def is_backorder_eligible(t: str) -> bool:
    """Types that can spawn a backorder document on shortage."""
    return t in {IN, OUT, INT, INTERNAL_IN}


def is_return_eligible(t: str) -> bool:
    """Types that support return-document creation."""
    return t in {IN, OUT, INT}


def return_type(t: str) -> str:
    """Map original document type to its return document type."""
    return _RETURN_TYPE_MAP[t]


def needs_quant_reservation(t: str) -> bool:
    """Types that reserve stock on confirmation."""
    return t in _NEEDS_QUANT_RESERVATION


# Correction sign: determines direction of stock delta when correcting
# a document of this type. +1 = receipt-like (delta applied as-is),
# -1 = dispatch-like (delta inverted).


def correction_sign(original_type: str) -> int:
    """Return +1 for receipt-like originals, -1 for dispatch-like.

    Raises ValueError for unknown types.
    """
    if original_type in _RECEIPT_LIKE:
        return 1
    if original_type in _DISPATCH_LIKE:
        return -1
    raise ServiceRejectionError('document_correction_type_not_correctable')


# ---------------------------------------------------------------------------
# Internal sets (private) — use predicates above instead
# ---------------------------------------------------------------------------

_RECEIPT = {IN, INTERNAL_IN, 'PZ', 'PW'}
_DISPATCH = {OUT, INTERNAL_OUT, 'WZ', 'RW'}
_TRANSFER = {INT, 'MM'}

# For correction sign logic (includes transfers as receipt-like). A scrap
# takes goods off the shelf like a dispatch, so less scrapped puts them back.
# An adjustment is in neither: its lines are already differences, and a
# mistake in one is a new adjustment, not a correction of it.
_RECEIPT_LIKE = {IN, 'PZ', INTERNAL_IN, 'PW', INT, 'MM'}
_DISPATCH_LIKE = {OUT, 'WZ', INTERNAL_OUT, 'RW', SCRAP}

# Location requirements (includes legacy codes)
_REQUIRES_TARGET = {IN, INT, INTERNAL_IN, 'PZ', 'MM', 'PW'}
# Scrap is absent on purpose: its line names a stock record (see
# requires_stock_row) and the record already says which shelf it stands on,
# so asking for the shelf twice only creates a second answer to disagree with.
_REQUIRES_SOURCE = {OUT, INT, INTERNAL_OUT, 'WZ', 'MM', 'RW'}

# Lines that must name a stock record (see requires_stock_row).
_REQUIRES_STOCK_ROW = {OUT, INTERNAL_OUT, INT, SCRAP, 'WZ', 'MM', 'RW'}

# Stock reservation on confirmation
_NEEDS_QUANT_RESERVATION = {OUT, 'WZ', INTERNAL_OUT, SCRAP, INT, 'MM', 'RW'}

# Return document type mapping
_RETURN_TYPE_MAP: dict[str, str] = {
    IN: OUT,
    OUT: IN,
    INT: INT,
}
