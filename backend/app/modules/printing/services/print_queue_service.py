"""The print queue: labels clicked in the app, printed by an agent next to the printer.

The server cannot reach a printer in somebody's office — the agent there asks
for work instead (it works behind a home router with no port opened). A job
names its printer when it is queued, the agent claims it under a lease, fetches
the labels' image, fits it to its printer, prints and reports. Labels from the pool
count as printed only on that report: a jammed printer leaves them unprinted
and the job can be sent again.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import UTC, date, datetime, timedelta
from typing import TYPE_CHECKING, Any
from uuid import UUID

from sqlalchemy import and_, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.datetimes import format_date_for
from app.core.exceptions import (
    AppException,
    NotFoundException,
    catalogue_refusal,
)
from app.core.logging import get_logger
from app.core.module_sdk import paginate_async
from app.core.public_api import core_api
from app.core.utils import pick_by_lang
from app.i18n.service import get_current_lang, get_error_message
from app.modules.printing.models import PrintAgent, PrintJob
from app.modules.printing.schemas import PROTOCOL_MIN_VERSION, PROTOCOL_VERSION
from app.modules.printing.services.label_geometry import LABEL_DPI

if TYPE_CHECKING:
    from app.core.contracts import ItemDTO, StockLotDTO
    from app.modules.printing.services.product_label_service import ProductLabel

#: An agent asks every few seconds; one silent for this long is offline.
ONLINE_SECONDS = 30
#: How long a claimed job is the claimant's. Printing a strip takes seconds; a
#: lease that runs out means the agent died mid-job, and the job goes back in
#: line for the next claim.
LEASE_SECONDS = 120
#: The longest error text kept from an agent's report.
MAX_ERROR_LENGTH = 500

QUEUED = 'queued'
PRINTING = 'printing'
PRINTED = 'printed'
FAILED = 'failed'

logger = get_logger(__name__)


def _now() -> datetime:
    return datetime.now(UTC)


def _refuse(key: str, status_code: int = 400, **fmt: Any) -> AppException:
    return AppException(
        status_code=status_code,
        code=key.upper(),
        message=get_error_message(key, get_current_lang(), **fmt),
    )


def _visibly_shrunk(scale: float | None) -> bool:
    """Whether the panel would show a shrink: less than 100% once rounded.

    A 24 mm label on a head 170 dots tall prints at 99.95% — a hundredth of
    a millimetre short. Calling that a shrink would put "printed at 100% of
    its size" next to the job.
    """
    return scale is not None and round(scale * 100) < 100


def is_online(agent: PrintAgent, now: datetime | None = None) -> bool:
    seen = agent.last_seen_at
    if seen.tzinfo is None:
        seen = seen.replace(tzinfo=UTC)
    return (now or _now()) - seen <= timedelta(seconds=ONLINE_SECONDS)


# ── agents ──────────────────────────────────────────────────────────


async def register_agent_async(
    db: AsyncSession,
    organization_id: UUID,
    *,
    name: str,
    printer_type: str,
    agent_version: str | None = None,
    protocol_version: int | None = None,
) -> PrintAgent:
    """Announce a printer, or say an agent of that name is back.

    The handshake is where the server learns what stands next to the printer:
    which build it is and which printing protocol it speaks. A protocol the
    server does not speak — including the silence of an agent from before the
    handshake carried one — is refused here, in words the agent prints.
    """
    if protocol_version is None:
        raise _refuse('print_agent_protocol_missing')
    if not PROTOCOL_MIN_VERSION <= protocol_version <= PROTOCOL_VERSION:
        raise _refuse(
            'print_agent_protocol_unsupported',
            agent=protocol_version,
            server=PROTOCOL_VERSION,
        )
    agent = (
        await db.execute(
            select(PrintAgent)
            .where(
                PrintAgent.organization_id == organization_id,
                PrintAgent.name == name,
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if agent is None:
        agent = PrintAgent(organization_id=organization_id, name=name)
        db.add(agent)
    agent.printer_type = printer_type
    agent.agent_version = agent_version
    agent.protocol_version = protocol_version
    agent.last_seen_at = _now()
    await db.flush()
    await db.refresh(agent)
    logger.info(
        '[Print queue] agent %s registered: %s, agent version %s, protocol %s',
        name,
        printer_type,
        agent_version or 'not stated',
        protocol_version,
    )
    return agent


async def list_agents_async(
    db: AsyncSession, organization_id: UUID
) -> list[PrintAgent]:
    rows = await db.execute(
        select(PrintAgent)
        .where(PrintAgent.organization_id == organization_id)
        .order_by(PrintAgent.name)
    )
    return list(rows.scalars().all())


async def get_agent_async(
    db: AsyncSession, organization_id: UUID, agent_id: UUID
) -> PrintAgent:
    agent = await db.get(PrintAgent, agent_id)
    if agent is None or agent.organization_id != organization_id:
        raise NotFoundException('print_agent', get_current_lang())
    return agent


async def _target_agent_async(
    db: AsyncSession, organization_id: UUID, agent_id: UUID | None
) -> PrintAgent:
    if agent_id is not None:
        return await get_agent_async(db, organization_id, agent_id)
    agents = await list_agents_async(db, organization_id)
    if not agents:
        raise _refuse('print_no_agent')
    if len(agents) > 1:
        raise _refuse('print_choose_agent')
    return agents[0]


# ── jobs: the app's side ────────────────────────────────────────────


async def _pool_entries_async(
    db: AsyncSession,
    organization_id: UUID,
    label_ids: list[UUID],
    short_codes: list[str],
) -> list[dict[str, Any]]:
    if label_ids:
        found = await core_api.labels.list_in_ids_async(db, label_ids, organization_id)
        by_key = {lbl.id: lbl for lbl in found}
        ordered = [by_key[i] for i in label_ids if i in by_key]
    else:
        found = await core_api.labels.list_by_short_codes_async(
            db, short_codes, organization_id
        )
        by_code = {lbl.short_code: lbl for lbl in found}
        ordered = [by_code[c] for c in short_codes if c in by_code]
    return [
        {
            'label_id': str(lbl.id),
            'short_code': lbl.short_code,
            'caption': core_api.labels.caption(lbl),
            'qr_only': False,
        }
        for lbl in ordered
    ]


async def _storage_entries_async(
    db: AsyncSession, organization_id: UUID, storage_ids: list[UUID]
) -> list[dict[str, Any]]:
    entries = []
    for storage_id in storage_ids:
        storage = await core_api.locations.get_async(db, organization_id, storage_id)
        if storage is None or not storage.short_code:
            continue
        caption = core_api.locations.label_caption(storage)
        entries.append(
            {
                'label_id': None,
                'short_code': storage.short_code,
                'caption': caption,
                # The storage label endpoint prints the QR alone when the
                # location hides its description; a queued copy must match.
                'qr_only': caption is None,
            }
        )
    return entries


async def location_labels_async(
    db: AsyncSession, organization_id: UUID, storage_ids: list[UUID], *, qr: bool
) -> tuple[list[ProductLabel], int]:
    """Shelf labels with bars, in the order asked, and how many have no code.

    The code goes large where a product's name would, the bars under it
    carry it for a 1D scanner, and the location's own caption — its
    description or name, as its QR label prints it — closes the label. A QR
    beside the bars carries the scan address, or the bare code where this
    installation's address only resolves on this machine.
    """
    from app.core.scan_links import printable_scan_url
    from app.modules.printing.services.product_label_service import (
        ProductLabel,
        symbology,
    )

    labels: list[ProductLabel] = []
    without_code = 0
    for storage_id in storage_ids:
        storage = await core_api.locations.get_async(db, organization_id, storage_id)
        if storage is None:
            continue
        code = storage.short_code
        if not code or symbology(code) is None:
            without_code += 1
            continue
        labels.append(
            ProductLabel(
                name=code,
                code=code,
                details=core_api.locations.label_caption(storage) or storage.name,
                qr=(printable_scan_url(code) or code) if qr else None,
            )
        )
    return labels, without_code


async def _location_entries_async(
    db: AsyncSession,
    organization_id: UUID,
    storage_ids: list[UUID],
    *,
    qr: bool,
    copies: int,
) -> list[dict[str, Any]]:
    labels, _ = await location_labels_async(db, organization_id, storage_ids, qr=qr)
    return [
        {
            'kind': 'product',
            'label_id': None,
            'short_code': label.code,
            'name': label.name,
            'details': label.details,
            'qr': label.qr,
        }
        for label in labels
        for _ in range(copies)
    ]


#: The words before the lot and the expiry date on a product label.
_LOT_WORD = {'en': 'Lot', 'pl': 'Partia', 'de': 'Charge', 'fr': 'Lot', 'es': 'Lote'}
_EXPIRY_WORD = {
    'en': 'Exp.',
    'pl': 'Termin',
    'de': 'Verfällt',
    'fr': 'Exp.',
    'es': 'Cad.',
}


def _details_line(lot_name: str | None, expiry: date | None, lang: str) -> str | None:
    """The lot and expiry line in *lang*, or None when the record has neither."""
    parts = []
    if lot_name:
        parts.append(f'{pick_by_lang(lang, **_LOT_WORD)} {lot_name}')
    if expiry:
        parts.append(
            f'{pick_by_lang(lang, **_EXPIRY_WORD)} {format_date_for(lang, expiry)}'
        )
    return ' · '.join(parts) or None


async def product_labels_async(
    db: AsyncSession,
    organization_id: UUID,
    item_ids: list[UUID],
    *,
    details: bool = True,
) -> tuple[list[ProductLabel], int, int]:
    """The labels of these products, in the order asked, and two counts.

    The counts are how many have no code and how many carry a lot or an
    expiry date, whether or not ``details`` prints them: the screen offers
    the option only when some do.

    The code is the one a scan finds the product by: the record's own, else
    its product's barcode, else its SKU. A record with none of them, or with
    one no barcode can carry, is left out and counted, so the screen can say
    how many it did not print. The lot and expiry come from the record's
    batch when it has one — the batch keeps the authoritative date.
    """
    from app.modules.printing.services.product_label_service import (
        ProductLabel,
        symbology,
    )

    items = [
        item
        for item in [
            await core_api.items.get_async(db, organization_id, item_id)
            for item_id in item_ids
        ]
        if item is not None
    ]
    templates = await core_api.product_templates.get_many_async(
        db, organization_id, list({i.template_id for i in items if i.template_id})
    )
    lots: dict[UUID, StockLotDTO] = {}
    for template_id in {i.template_id for i in items if i.lot_id and i.template_id}:
        for lot in await core_api.stock.list_lots_async(
            db, organization_id, template_id
        ):
            lots[lot.id] = lot
    lang = get_current_lang()
    labels: list[ProductLabel] = []
    without_code = 0
    with_details = 0
    for item in items:
        template = templates.get(item.template_id) if item.template_id else None
        code = item.barcode or (template and (template.barcode or template.sku))
        if not code or symbology(code) is None:
            without_code += 1
            continue
        line = _record_details(item, lots, lang)
        with_details += line is not None
        labels.append(
            ProductLabel(name=item.name, code=code, details=line if details else None)
        )
    return labels, without_code, with_details


def _record_details(
    item: ItemDTO, lots: dict[UUID, StockLotDTO], lang: str
) -> str | None:
    lot = lots.get(item.lot_id) if item.lot_id else None
    if lot is None:
        return _details_line(None, item.expiry_date, lang)
    expiry = lot.expiry_date or lot.use_by_date or item.expiry_date
    return _details_line(lot.name, expiry, lang)


def _with_options(
    entries: list[dict[str, Any]],
    *,
    caption: str | None,
    qr_only: bool,
    show_code: bool,
    copies: int,
) -> list[dict[str, Any]]:
    """Apply the download's options: one caption for all, the code alone, copies."""
    shaped: list[dict[str, Any]] = []
    for entry in entries:
        entry = dict(entry, show_code=show_code)
        if qr_only:
            entry['caption'] = None
            entry['qr_only'] = True
        elif caption:
            entry['caption'] = caption
            entry['qr_only'] = False
        shaped.extend(dict(entry) for _ in range(copies))
    return shaped


async def _product_entries_async(
    db: AsyncSession,
    organization_id: UUID,
    item_ids: list[UUID],
    *,
    details: bool,
    copies: int,
) -> list[dict[str, Any]]:
    labels, _, _ = await product_labels_async(
        db, organization_id, item_ids, details=details
    )
    if not labels:
        raise catalogue_refusal('product_label_no_code')
    return [
        {
            'kind': 'product',
            'label_id': None,
            # The code under ``short_code``: the job list names a job by it.
            'short_code': label.code,
            'name': label.name,
            'details': label.details,
        }
        for label in labels
        for _ in range(copies)
    ]


async def queue_job_async(
    db: AsyncSession,
    organization_id: UUID,
    user_id: UUID | None,
    *,
    read_permissions: Sequence[str],
    agent_id: UUID | None = None,
    label_ids: list[UUID] | None = None,
    short_codes: list[str] | None = None,
    storage_ids: list[UUID] | None = None,
    item_ids: list[UUID] | None = None,
    caption: str | None = None,
    qr_only: bool = False,
    show_code: bool = False,
    details: bool = True,
    copies: int = 1,
    width_mm: float = 50.0,
    height_mm: float = 24.0,
    bars: bool = False,
    qr: bool = False,
) -> PrintJob:
    """Queue the chosen labels for one printer.

    Exactly one kind of target: pool labels (by id or short code), storage
    locations, or products (their barcode labels). Storage locations print
    their QR label, or with ``bars`` their code as Code 128 (``qr`` adds the
    square beside it). What each label says, and its size, is resolved now
    and kept on the job, so the printed strip shows what the person saw when
    they clicked; ``read_permissions`` are the reads those records answer
    to, one of which the queue asks of whoever lists or resends the job.
    """
    kinds = [bool(label_ids), bool(short_codes), bool(storage_ids), bool(item_ids)]
    if sum(kinds) != 1:
        raise catalogue_refusal('print_job_one_target')
    agent = await _target_agent_async(db, organization_id, agent_id)
    if item_ids or (storage_ids and bars):
        if item_ids:
            entries = await _product_entries_async(
                db, organization_id, item_ids, details=details, copies=copies
            )
        else:
            entries = await _location_entries_async(
                db, organization_id, storage_ids or [], qr=qr, copies=copies
            )
            if not entries:
                raise catalogue_refusal('print_job_nothing_to_print')
        from app.modules.printing.services.product_label_service import (
            require_fits,
        )

        # Drawn at the file's raster now, so a label that cannot hold its
        # code is refused here, not when the printer asks for the image.
        for label in {_bars_label(entry) for entry in entries}:
            require_fits(label, width_mm, height_mm)
    else:
        if storage_ids:
            entries = await _storage_entries_async(db, organization_id, storage_ids)
        else:
            entries = await _pool_entries_async(
                db, organization_id, label_ids or [], short_codes or []
            )
        if not entries:
            raise catalogue_refusal('print_job_nothing_to_print')
        entries = _with_options(
            entries,
            caption=caption,
            qr_only=qr_only,
            show_code=show_code,
            copies=copies,
        )
    job = PrintJob(
        organization_id=organization_id,
        agent_id=agent.id,
        status=QUEUED,
        labels=entries,
        read_permissions=list(read_permissions),
        width_mm=width_mm,
        height_mm=height_mm,
        created_by=user_id,
        attempts=0,
    )
    db.add(job)
    await db.flush()
    await db.refresh(job)
    return job


async def queue_drawn_label_async(
    db: AsyncSession,
    organization_id: UUID,
    user_id: UUID | None,
    *,
    short_code: str,
    caption: str | None,
    qr_url: str,
    read_permission: str,
    agent_id: UUID | None = None,
    width_mm: float = 50.0,
    height_mm: float = 24.0,
) -> PrintJob:
    """Queue one QR label whose words and address another module decided.

    The label a module draws for its own record — a package of a dispatch —
    with the code printed under the QR, the caption beside it and the QR
    pointing at ``qr_url`` rather than at a pool label's scan address. One
    label, so the agent's image of the job is that label as the download
    draws it. The module names the read its record answers to.
    """
    agent = await _target_agent_async(db, organization_id, agent_id)
    job = PrintJob(
        organization_id=organization_id,
        agent_id=agent.id,
        status=QUEUED,
        labels=[
            {
                'label_id': None,
                'short_code': short_code,
                'caption': caption,
                'qr_only': False,
                'show_code': True,
                'qr_url': qr_url,
            }
        ],
        read_permissions=[read_permission],
        width_mm=width_mm,
        height_mm=height_mm,
        created_by=user_id,
        attempts=0,
    )
    db.add(job)
    await db.flush()
    await db.refresh(job)
    return job


async def list_jobs_async(
    db: AsyncSession,
    organization_id: UUID,
    *,
    may_read: Callable[[str], bool],
    offset: int = 0,
    limit: int = 20,
) -> tuple[list[PrintJob], int]:
    """One page of the jobs the caller ``may_read``, newest first, and their count.

    A job is listed to a holder of one of its ``read_permissions`` only. The queue
    keeps every job it was handed, so it is paged here rather than read whole;
    the id breaks a tie on the creation time so a page boundary cannot repeat
    or drop a job.
    """
    in_queue = await db.scalars(
        select(PrintJob.read_permissions)
        .where(PrintJob.organization_id == organization_id)
        .distinct()
    )
    readable = [reads for reads in in_queue if any(map(may_read, reads))]
    return await paginate_async(
        db,
        select(PrintJob)
        .where(
            PrintJob.organization_id == organization_id,
            PrintJob.read_permissions.in_(readable),
        )
        .order_by(PrintJob.created_at.desc(), PrintJob.id),
        limit=limit,
        offset=offset,
    )


async def get_job_async(
    db: AsyncSession, organization_id: UUID, job_id: UUID
) -> PrintJob:
    job = await db.get(PrintJob, job_id)
    if job is None or job.organization_id != organization_id:
        raise NotFoundException('print_job', get_current_lang())
    return job


async def retry_job_async(
    db: AsyncSession, organization_id: UUID, job_id: UUID
) -> PrintJob:
    """Send a failed job to its printer again."""
    job = await get_job_async(db, organization_id, job_id)
    if job.status != FAILED:
        raise _refuse('print_job_not_retryable', status_code=409)
    job.status = QUEUED
    job.error = None
    job.scale = None
    job.lease_until = None
    job.finished_at = None
    await db.flush()
    await db.refresh(job)
    return job


# ── jobs: the agent's side ──────────────────────────────────────────


async def claim_next_async(
    db: AsyncSession, organization_id: UUID, agent_id: UUID
) -> PrintJob | None:
    """Hand the agent its oldest waiting job, under a lease; also its heartbeat.

    A job whose lease ran out (the agent died mid-print) is waiting again.
    ``SKIP LOCKED`` keeps two claims racing for the same row from both
    winning it; the row stays locked until the caller commits.
    """
    agent = await get_agent_async(db, organization_id, agent_id)
    now = _now()
    agent.last_seen_at = now
    claimable = or_(
        PrintJob.status == QUEUED,
        and_(PrintJob.status == PRINTING, PrintJob.lease_until < now),
    )
    job = (
        await db.execute(
            select(PrintJob)
            .where(
                PrintJob.organization_id == organization_id,
                PrintJob.agent_id == agent.id,
                claimable,
            )
            .order_by(PrintJob.created_at)
            .limit(1)
            .with_for_update(skip_locked=True)
        )
    ).scalar_one_or_none()
    if job is not None:
        job.status = PRINTING
        job.lease_until = now + timedelta(seconds=LEASE_SECONDS)
        job.attempts = (job.attempts or 0) + 1
    await db.flush()
    return job


class _Printable:
    """The shape the label renderer reads: a code and the text under it."""

    def __init__(self, entry: dict[str, Any]) -> None:
        self.short_code = entry['short_code']
        self.description = entry.get('caption')


async def job_image_async(
    db: AsyncSession,
    organization_id: UUID,
    job_id: UUID,
    base_url: str,
    *,
    dpi: float = LABEL_DPI,
    max_height_px: int | None = None,
    edge_to_edge: bool = False,
    index: int | None = None,
) -> bytes:
    """The job's labels as one PNG, at the size they were queued with.

    The same file the label download gives for the same labels and options;
    the printer it goes to plays no part in drawing it. Its agent may ask for
    its own raster (``dpi``, ``max_height_px``) and gets the same label drawn
    at it, scaled down whole when it is taller than the head prints.

    ``index`` asks for the one label at that place in the job (copies are
    places of their own), drawn as it is in the strip: a printer that cuts
    after every label prints a job one image at a time.
    """
    from app.core.label_rendering import render_label_batch_png, render_label_png

    job = await get_job_async(db, organization_id, job_id)
    entries = list(job.labels or [])
    if index is not None and not 0 <= index < len(entries):
        raise NotFoundException('print_job', get_current_lang())
    if entries and entries[0].get('kind') == 'product':
        return _product_job_image(job, entries, dpi, max_height_px, index)
    printables = [_Printable(entry) for entry in entries]
    options = {
        'width_mm': job.width_mm,
        'height_mm': job.height_mm,
        'base_url': base_url,
        'qr_only': bool(entries) and all(entry.get('qr_only') for entry in entries),
        'show_code': bool(entries) and all(entry.get('show_code') for entry in entries),
        'dpi': dpi,
        'max_height_px': max_height_px,
        'edge_to_edge': edge_to_edge,
    }
    if index is not None or len(printables) == 1:
        place = index or 0
        # A drawn label carries the address its QR points at; the others
        # point at their own code's scan address.
        return render_label_png(
            printables[place],
            qr_url_override=entries[place].get('qr_url'),
            **options,
        )
    return render_label_batch_png(printables, columns=100, **options)


def _bars_label(entry: dict[str, Any]) -> ProductLabel:
    """The label a queued entry with bars draws: a product's or a shelf's."""
    from app.modules.printing.services.product_label_service import ProductLabel

    return ProductLabel(
        entry['name'], entry['short_code'], entry.get('details'), entry.get('qr')
    )


def _product_job_image(
    job: PrintJob,
    entries: list[dict[str, Any]],
    dpi: float,
    max_height_px: int | None,
    index: int | None,
) -> bytes:
    from app.modules.printing.services.product_label_service import (
        generate_product_label_batch_png,
        generate_product_label_png,
    )

    labels = [_bars_label(entry) for entry in entries]
    if index is not None or len(labels) == 1:
        return generate_product_label_png(
            labels[index or 0],
            job.width_mm,
            job.height_mm,
            dpi=dpi,
            max_height_px=max_height_px,
        )
    return generate_product_label_batch_png(
        labels, job.width_mm, job.height_mm, dpi=dpi, max_height_px=max_height_px
    )


async def report_job_async(
    db: AsyncSession,
    organization_id: UUID,
    job_id: UUID,
    agent_id: UUID,
    *,
    attempt: int,
    printed: bool,
    error: str | None = None,
    scale: float | None = None,
) -> PrintJob:
    """The agent's word on a job it holds: printed, or failed and why.

    Only the current claim may answer. A claim whose lease ran out and was
    handed out again is refused by its attempt number, even when the same
    agent re-registered in between: otherwise its late "failed" would close
    the job under the claim that is printing it now.
    """
    job = (
        await db.execute(
            select(PrintJob)
            .where(
                PrintJob.id == job_id,
                PrintJob.organization_id == organization_id,
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if job is None:
        raise NotFoundException('print_job', get_current_lang())
    if job.agent_id != agent_id or job.status != PRINTING or job.attempts != attempt:
        raise _refuse('print_job_not_claimed', status_code=409)
    now = _now()
    job.finished_at = now
    job.lease_until = None
    await db.execute(
        update(PrintAgent).where(PrintAgent.id == agent_id).values(last_seen_at=now)
    )
    # How much the agent had to shrink the labels to fit its printer, if it
    # did: the person asked for a size and should learn they did not get it
    # from the panel, not from the label.
    job.scale = scale if printed and _visibly_shrunk(scale) else None
    if printed:
        job.status = PRINTED
        job.error = None
        label_ids = [
            UUID(entry['label_id']) for entry in job.labels if entry.get('label_id')
        ]
        if label_ids:
            await core_api.labels.mark_as_printed_by_ids_async(
                db, label_ids, organization_id
            )
    else:
        job.status = FAILED
        job.error = (error or '').strip()[:MAX_ERROR_LENGTH] or None
    await db.flush()
    await db.refresh(job)
    return job
