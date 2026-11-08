import re
from collections.abc import Awaitable, Callable, Iterable
from datetime import date
from typing import cast
from uuid import UUID, uuid4

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.public_api import core_api

from . import document_types as dt
from .document_profile_service import get_profile
from .models import Document, DocumentNumberSequence
from .models.profile import DEFAULT_NUMBER_PADDING, DEFAULT_NUMBERING_FORMAT


def _get_type_label(doc_type: str, type_labels: dict[str, str] | None) -> str:
    """The organization's own label for *doc_type*, else its short code.

    ``{TYPE_LABEL}`` promises what the profile's label table shows. The
    table may name some types and skip others, and the skipped one used to
    print its stored value — a number reading ``INTERNAL_OUT`` beside a
    screen reading ``II``. The fallback is the same short code ``{TYPE}``
    writes, so no path out of here can put an enum name on paper.
    """
    if type_labels and doc_type in type_labels:
        return cast(str, type_labels[doc_type])
    return dt.short_code(doc_type)


def _parse_seq_format(format_str: str) -> tuple[str, int]:
    match = re.search(r'\{SEQ:(\d+)d\}', format_str)
    if match:
        placeholder = match.group(0)
        digits = int(match.group(1))
        return placeholder, digits
    return '{SEQ:03d}', 3


def _with_seq_width(format_str: str, width: int) -> str:
    """*format_str* with its sequence placeholder stated at *width* digits.

    A type that has been printing at a width of its own says so here rather
    than carrying a format of its own: the organization's shape stays the
    organization's, and the digits that are already on paper stay on paper.
    """
    placeholder, _ = _parse_seq_format(format_str)
    return format_str.replace(placeholder, f'{{SEQ:{width}d}}')


def _extract_seq(number: str, prefix: str) -> int | None:
    """Return the integer sequence in ``number`` after ``prefix``, or None.

    only fully-numeric suffixes count (mirrors the PO numbering
    regex ``^[0-9]+$``). A legacy/imported/manual number with a non-numeric
    suffix (e.g. 'IN/2026/042-A') yields None and is skipped, preventing an
    int() crash and keeping the next sequence anchored to the highest numeric
    suffix actually in use.

    The number must actually start with the prefix. It used to be cut by the
    prefix's *length*, so 'PZ/2026/999' read as sequence 999 under the prefix
    'PO/2026/'. Both callers filter by `LIKE 'prefix%'` in SQL first, which
    is why nothing has gone wrong — but this function is part of the
    warehouse module's public API now, and its contract binds callers nobody
    here can see.
    """
    if not number.startswith(prefix):
        return None
    suffix = number[len(prefix) :]
    if re.fullmatch(r'\d+', suffix):
        return int(suffix)
    return None


async def _build_prefix(
    db: AsyncSession,
    org_id: UUID,
    doc_type: str,
    profile_format: str,
    document_date: date | None = None,
) -> str:
    """The literal text every number of this type and period starts with.

    ``{TYPE}`` writes the type's short code (``II/2026/001``), never the
    value the register stores (``INTERNAL_OUT/2026/001``): a number is read
    on screen and on paper, where an enum name is not a word anybody uses,
    and two numbers that contain one another cannot be told apart by a
    search. ``{TYPE_LABEL}`` writes what the profile calls the type instead.

    ``{YEAR}`` and ``{MONTH}`` are the document's own, not the clock's. A
    delivery entered on 2 January and dated to the December it belongs to was
    being filed under January, while the register — which groups by the same
    date the period guard reads — filed it under December. One document,
    two periods, depending on which of the two you asked.

    A document with no date of its own — and a production run, which never
    has one — is numbered on the organization's today, the day its period
    guard and its monthly figures read. The server's UTC date filed a run
    made after midnight on the local first of January under the year that
    had just ended.
    """
    on = document_date or await core_api.organizations.today_async(db, org_id)
    year = on.year
    month = on.month
    type_label = dt.short_code(doc_type)

    if '{TYPE_LABEL}' in profile_format:
        profile = await get_profile(db, org_id)
        if profile and profile.type_labels:
            type_label = _get_type_label(doc_type, profile.type_labels)

    prefix = profile_format
    prefix = prefix.replace('{TYPE}', dt.short_code(doc_type))
    prefix = prefix.replace('{TYPE_LABEL}', type_label)
    prefix = prefix.replace('{YEAR}', str(year))
    prefix = prefix.replace('{MONTH}', f'{month:02d}')
    prefix = re.sub(r'\{ORG_PREFIX\}', '', prefix)
    placeholder, _ = _parse_seq_format(prefix)
    prefix = prefix.replace(placeholder, '')

    return prefix


#: How a type whose records are not documents reports the largest sequence
#: it has already printed under a prefix. The engine counts what is in
#: ``documents``; purchase orders live in a table of their own and would
#: otherwise be handed number one again on a register a year deep.
HighestInUse = Callable[[str], Awaitable[int]]


def highest_sequence(numbers: Iterable[str], prefix: str) -> int:
    """The largest fully-numeric sequence among *numbers* under *prefix*."""
    highest = 0
    for number in numbers:
        seq = _extract_seq(number, prefix)
        if seq is not None and seq > highest:
            highest = seq
    return highest


async def _highest_in_use_async(db: AsyncSession, org_id: UUID, prefix: str) -> int:
    """The largest sequence already printed on a document under *prefix*.

    Only fully-numeric suffixes count. A non-numeric one (legacy, manual,
    imported) is skipped rather than crashing ``int()``; it also sorts past
    numeric ones lexicographically, so taking the last row would miss the
    true maximum.

    Read once, when a prefix is first counted, so an organization that has
    been running keeps counting from where it was rather than starting again
    at one.
    """
    numbers = await db.scalars(
        select(Document.number).where(
            Document.organization_id == org_id,
            Document.number.like(f'{prefix}%'),
        )
    )
    return highest_sequence(numbers.all(), prefix)


async def _next_in_sequence_async(
    db: AsyncSession,
    org_id: UUID,
    prefix: str,
    highest_in_use: HighestInUse | None = None,
) -> int:
    """Take the next number under *prefix* and leave the counter one higher.

    The counter is the record of what has been handed out, which is not the
    same question as what is currently on file: a deleted draft leaves the
    register but must not give its number back.

    The number is claimed by one atomic statement in the caller's own
    transaction — no advisory lock, no read of the row first — so the counter
    row is held from this statement to the caller's commit and nothing else.
    Callers therefore claim the number as late as they can; a session of its
    own would hold a second pooled connection while the first is still held,
    and a burst of documents would wait on each other for it.
    """
    table = DocumentNumberSequence.__table__
    claimed = await db.scalar(
        update(DocumentNumberSequence)
        .where(
            DocumentNumberSequence.organization_id == org_id,
            DocumentNumberSequence.prefix == prefix,
        )
        .values(next_value=DocumentNumberSequence.next_value + 1)
        .returning(DocumentNumberSequence.next_value - 1)
    )
    if claimed is not None:
        return claimed
    floor = (
        await highest_in_use(prefix)
        if highest_in_use is not None
        else await _highest_in_use_async(db, org_id, prefix)
    )
    # A worker that lost the race to create the counter lands on the conflict
    # branch and takes the next number of the winner's counter instead.
    return cast(
        int,
        await db.scalar(
            insert(DocumentNumberSequence)
            .values(organization_id=org_id, prefix=prefix, next_value=floor + 2)
            .on_conflict_do_update(
                index_elements=['organization_id', 'prefix'],
                set_={'next_value': table.c.next_value + 1},
            )
            .returning(DocumentNumberSequence.next_value - 1)
        ),
    )


async def _format_in_force(
    db: AsyncSession,
    org_id: UUID,
    sequence_format: str | None,
    sequence_width: int | None = None,
) -> tuple[str, int]:
    """``(format, digits)``: the per-type override, else the profile's, else the default.

    *sequence_width* narrows the answer's digits without touching its shape —
    a type keeps the width already printed on its paper.
    """
    if sequence_format:
        _, digits = _parse_seq_format(sequence_format)
        if sequence_width is not None:
            return _with_seq_width(sequence_format, sequence_width), sequence_width
        return sequence_format, digits
    profile = await get_profile(db, org_id)
    if profile:
        if sequence_width is not None:
            return (
                _with_seq_width(profile.numbering_format, sequence_width),
                sequence_width,
            )
        return profile.numbering_format, int(profile.number_padding)
    # The same constant the preset and the column use: an organization
    # whose profile does not exist yet must not be numbered by a second
    # opinion about what "default" means.
    if sequence_width is not None:
        return _with_seq_width(DEFAULT_NUMBERING_FORMAT, sequence_width), sequence_width
    return DEFAULT_NUMBERING_FORMAT, DEFAULT_NUMBER_PADDING


async def number_for_date_async(
    db: AsyncSession,
    org_id: UUID,
    doc_type: str,
    number: str,
    sequence_format: str | None,
    document_date: date | None,
    highest_in_use: HighestInUse | None = None,
) -> str:
    """*number* if it is still filed where *document_date* says, else a new one.

    A draft's date can be changed, and the number carries the period the
    document was dated to when it was numbered. Left alone, a draft moved
    from December to January kept its December number while the register
    and the period guard filed it under January — one document, two periods
    again, the disagreement the date-based prefix exists to remove. The old
    number is not given back: the counter records what was handed out.
    """
    format_str, _ = await _format_in_force(db, org_id, sequence_format)
    prefix = await _build_prefix(db, org_id, doc_type, format_str, document_date)
    if number.startswith(prefix) and _extract_seq(number, prefix) is not None:
        return number
    return await generate_number(
        db, org_id, doc_type, sequence_format, document_date, highest_in_use
    )


#: The letters an identifier may end on — never a digit. A format may
#: print any text it likes in front of the sequence, but ``generate_number``
#: writes the sequence digits last, so a number of the register always
#: ends on one. Ending the identifier on a letter is what keeps the two
#: shapes apart with no reference to the configured format at all.
_IDENTIFIER_TAIL = 'ABCDEF'


def temporary_number() -> str:
    """What a draft carries until confirmation gives it its number.

    A draft is a plan, and plans are written and thrown away all day:
    numbering them at creation spent a sequence number on every one of
    them, so the register held gaps between the numbers of documents that
    never existed. The identifier is drawn from nowhere and recorded by
    nobody — it names one draft for as long as the draft stands, and the
    number the register knows is drawn when the draft is confirmed (see
    ``confirm_document``).

    Eleven hex characters of a UUID keep two drafts apart by a margin no
    organization reaches, and ``DRAFT-`` reads on screen and in a search
    as exactly what it is. The last character is a hex *letter*, and that
    is what ``is_temporary_number`` reads beside the shape: every number
    the register issues ends on its sequence's digits (``generate_number``
    appends them last), so no format, however it is configured, can print
    an identifier — while an identifier never ends where a number does.
    """
    token = uuid4().hex
    return f'DRAFT-{token[:11].upper()}{_IDENTIFIER_TAIL[int(token[11], 16) % 6]}'


#: The shape ``temporary_number`` writes — a prefix, eleven hex
#: characters and a hex letter. Matching the whole string is what keeps
#: an issued number out of the identifier's company: ``DRAFT-IN/2026/0003``
#: (a format whose literal text begins with ``DRAFT-``) and
#: ``DRAFT-000000000001`` (a format that prints only hex, and every one
#: of those ends on a digit) are numbers of the register, and only the
#: shape above is an identifier.
_TEMPORARY_NUMBER = re.compile(r'DRAFT-[0-9A-F]{11}[A-F]')


def is_temporary_number(number: str) -> bool:
    """Is *number* a draft's identifier rather than a number of the register?

    The shape decides, not the prefix — and half the shape is one no
    number of the register can have. ``DRAFT-{TYPE}/{YEAR}/{SEQ:03d}``
    and ``DRAFT-000000000{SEQ:03d}`` are legal profile formats, so
    ``DRAFT-IN/2026/0003`` and ``DRAFT-000000000001`` are issued numbers
    of the register — the first began with the identifier's prefix and
    was called temporary (confirmation drew a *second* number over it,
    and a date change skipped the re-file), the second matched its whole
    shape for the same reason. What separates them is where each ends:
    ``generate_number`` writes the sequence digits last, so every number
    the register issues ends on a digit, while ``temporary_number``
    ends on a hex letter. Detection therefore does not depend on the
    configured format at all.

    The only drafts carrying a number of the register are the ones
    numbered before this rule existed, or written straight into the table
    by a fixture: confirmation draws a number only for a document that
    does not have one, so a document keeps the number it was given.
    """
    return _TEMPORARY_NUMBER.fullmatch(number) is not None


async def generate_number(
    db: AsyncSession,
    org_id: UUID,
    doc_type: str,
    sequence_format: str | None = None,
    document_date: date | None = None,
    highest_in_use: HighestInUse | None = None,
    sequence_width: int | None = None,
) -> str:
    """Next free number for ``doc_type`` in this organization.

       ``sequence_format`` is the per-type override from ``DocumentTypeConfig``,
    passed by the caller that already loaded it. It was stored and
       never read: a warehouse that gave its receipts their own numbering saw the
       organization-wide format on every document regardless.

    ``document_date`` is the date the document is *for* — its scheduled date,
    the one the period guard and the register both read. It decides the year
    and month in the prefix, so a backdated document is filed where it
    belongs. Absent, the number is dated on the organization's today.

    The sequence digits are written last, so every number issued here ends
    on a digit. ``is_temporary_number`` rests on that: it tells a draft's
    temporary identifier (which ends on a hex letter) from a number of the
    register without asking what the format is, so nothing may be appended
    after the sequence.
    """
    format_str, digits = await _format_in_force(
        db, org_id, sequence_format, sequence_width
    )
    prefix = await _build_prefix(db, org_id, doc_type, format_str, document_date)

    seq = await _next_in_sequence_async(db, org_id, prefix, highest_in_use)
    return f'{prefix}{seq:0{digits}d}'
