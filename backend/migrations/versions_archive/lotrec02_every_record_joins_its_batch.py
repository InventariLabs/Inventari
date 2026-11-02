"""every record joins its batch: the existing records assigned to batch and owner

Revision ID: lotrec02
Revises: lotrec01
Create Date: 2026-09-25

``lotrec01`` gave a record the two members of a quant's key it lacked, the
batch and the owner. This assigns the records that exist, by the rule the
grain census measured (every ambiguous shelf of its data assignable, none
left for a person to decide):

- A group is ``(organization, product, shelf)``. Only groups with a quant
  that names a batch or an owner are candidates, and of those only the ones
  whose records, summed per batch and owner, do not already equal their
  quants — so a second run finds nothing to do.
- The group's live records that hold stock are laid end to end by expiry
  date (undated last, then by id); its quants that hold stock likewise by
  their batch's expiry date (undated last, then by batch name, the
  batch-less stock after every named batch). Each unit of a record goes to
  the quant it lines up with.
- A record whose units straddle two quants is split. The record keeps its
  id, its label and its barcode on the first part — each names one
  physical thing, and a live barcode is unique in the organization — and
  every further part is a copy of the row without them. The date stays the
  record's own: stock moves between batches here, dates are not invented.
- A group whose records and quants do not hold the same total is left
  alone: no rule can assign stock that is not there. Nor is a group in
  which a record with a serial number would have to be split, since a
  serial number is one thing. Both are reported.

The report goes to the migration log and is returned to the caller: groups
looked at, assigned by date (the records' dates name the batches one to one
and there is no batch-less stock), assigned by rule, records split, and the
two kinds left alone.

One direction only: a split record cannot be told from any other afterwards,
so ``downgrade`` is a documented no-op (same contract as ``openbal01``); the
schema's own downgrade drops the columns, and every record keeps its quantity.
An upgrade after that assigns afresh: the parts of the first run line up in
a different order, and some are split again (measured on the grain census's
warehouse data: 12 splits on the first run, 6 more after a downgrade and an
upgrade). Quantities and the batch-by-batch agreement come out the same.
"""

import logging
import uuid
from collections import Counter
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

import sqlalchemy as sa
from alembic import op

revision = 'lotrec02'
down_revision = 'lotrec01'
branch_labels = None
depends_on = None

logger = logging.getLogger('alembic.runtime.migration')

_CANDIDATE_GROUPS = """
WITH sides AS (
    SELECT organization_id AS org, template_id AS tpl, storage_location_id AS loc,
           lot_id, owner_id, COALESCE(NULLIF(quantity, 'NaN'::numeric), 0) AS qty
    FROM items
    WHERE is_deleted IS FALSE AND template_id IS NOT NULL
    UNION ALL
    SELECT organization_id, product_template_id, storage_location_id,
           lot_id, owner_id, -quantity
    FROM stock_quants
), disagreeing AS (
    -- GROUP BY puts NULL batches and owners together, as the quant's key does.
    SELECT org, tpl, loc
    FROM sides
    GROUP BY org, tpl, loc, lot_id, owner_id
    HAVING SUM(qty) <> 0
)
SELECT DISTINCT d.org, d.tpl, d.loc
FROM disagreeing d
WHERE EXISTS (
    SELECT 1 FROM stock_quants x
    WHERE x.organization_id = d.org AND x.product_template_id = d.tpl
      AND x.storage_location_id = d.loc AND x.quantity > 0
      AND (x.lot_id IS NOT NULL OR x.owner_id IS NOT NULL)
)
ORDER BY 1, 2, 3
"""

_RECORDS = """
SELECT id, quantity, expiry_date, serial_number
FROM items
WHERE organization_id = :org AND template_id = :tpl AND storage_location_id = :loc
  AND is_deleted IS FALSE AND quantity > 0 AND quantity <> 'NaN'::numeric
ORDER BY expiry_date NULLS LAST, id
"""

_QUANTS = """
SELECT q.lot_id, q.owner_id, l.expiry_date, q.quantity
FROM stock_quants q
LEFT JOIN stock_lots l ON l.id = q.lot_id
WHERE q.organization_id = :org AND q.product_template_id = :tpl
  AND q.storage_location_id = :loc AND q.quantity > 0
ORDER BY l.expiry_date NULLS LAST, l.name NULLS LAST, q.owner_id NULLS FIRST
"""

_ASSIGN = """
UPDATE items SET quantity = :qty, lot_id = :lot, owner_id = :owner WHERE id = :id
"""

#: Columns a split part does not inherit: its own identity, the stock it holds,
#: and the two that name one physical thing.
_NOT_COPIED = ('id', 'quantity', 'lot_id', 'owner_id', 'label_code', 'barcode')


@dataclass
class _Report:
    groups: int = 0
    by_date: int = 0
    by_rule: int = 0
    split_records: int = 0
    unassigned_drift: int = 0
    unassigned_serial: int = 0
    unassigned: list[tuple] = field(default_factory=list)

    def as_dict(self) -> dict[str, int]:
        return {
            'groups': self.groups,
            'by_date': self.by_date,
            'by_rule': self.by_rule,
            'split_records': self.split_records,
            'unassigned_drift': self.unassigned_drift,
            'unassigned_serial': self.unassigned_serial,
        }


def _walk(records, quants) -> list[list[tuple[Decimal, object, object]]]:
    """Lay both sides end to end; each record's parts as (qty, lot, owner).

    The caller has checked that both sides hold the same total. Should they
    not, this stops where the quants run out rather than walk on for ever.
    """
    parts: list[list[tuple[Decimal, object, object]]] = []
    index, left = 0, quants[0].quantity
    for record in records:
        need, mine = record.quantity, []
        while need > 0:
            if left == 0:
                raise ValueError('the records hold more than the quants')
            take = min(need, left)
            mine.append((take, quants[index].lot_id, quants[index].owner_id))
            need, left = need - take, left - take
            if left == 0 and index + 1 < len(quants):
                index += 1
                left = quants[index].quantity
        parts.append(mine)
    return parts


def _dates_name_the_batches(records, quants) -> bool:
    """The census's "exact": per expiry date, the records hold what the batches hold."""
    if any(q.lot_id is None for q in quants):
        return False
    held: Counter[date | None] = Counter()
    for r in records:
        held[r.expiry_date] += r.quantity
    batches: Counter[date | None] = Counter()
    for q in quants:
        batches[q.expiry_date] += q.quantity
    return held == batches


def _copy_statement(bind) -> sa.TextClause:
    table = sa.Table('items', sa.MetaData(), autoload_with=bind)
    columns = ', '.join(
        f'"{c.name}"' for c in table.columns if c.name not in _NOT_COPIED
    )
    return sa.text(
        f'INSERT INTO items (id, quantity, lot_id, owner_id, {columns}) '
        f'SELECT :new_id, :qty, :lot, :owner, {columns} FROM items WHERE id = :src'
    )


def _assign_group(bind, group, copy, report: _Report) -> None:
    key = {'org': group.org, 'tpl': group.tpl, 'loc': group.loc}
    records = bind.execute(sa.text(_RECORDS), key).all()
    quants = bind.execute(sa.text(_QUANTS), key).all()
    report.groups += 1
    if sum(r.quantity for r in records) != sum(q.quantity for q in quants):
        report.unassigned_drift += 1
        report.unassigned.append((*group, 'drift'))
        return
    parts = _walk(records, quants)
    if any(r.serial_number and len(p) > 1 for r, p in zip(records, parts, strict=True)):
        report.unassigned_serial += 1
        report.unassigned.append((*group, 'serial'))
        return
    if _dates_name_the_batches(records, quants):
        report.by_date += 1
    else:
        report.by_rule += 1
    for record, (first, *rest) in zip(records, parts, strict=True):
        qty, lot, owner = first
        bind.execute(
            sa.text(_ASSIGN), {'id': record.id, 'qty': qty, 'lot': lot, 'owner': owner}
        )
        report.split_records += 1 if rest else 0
        for qty, lot, owner in rest:
            bind.execute(
                copy,
                {
                    'new_id': uuid.uuid4(),
                    'qty': qty,
                    'lot': lot,
                    'owner': owner,
                    'src': record.id,
                },
            )


def _run_backfill(bind) -> dict[str, int]:
    """Assign every candidate group's records; return the report."""
    report = _Report()
    copy = _copy_statement(bind)
    for group in bind.execute(sa.text(_CANDIDATE_GROUPS)).all():
        _assign_group(bind, group, copy, report)
    logger.info('lotrec02: records assigned to batches: %s', report.as_dict())
    for org, tpl, loc, why in report.unassigned:
        logger.warning(
            'lotrec02: left unassigned (%s): organization %s, product %s, shelf %s',
            why,
            org,
            tpl,
            loc,
        )
    return report.as_dict()


def upgrade() -> None:
    _run_backfill(op.get_bind())


def downgrade() -> None:
    """No-op: a split record cannot be told from any other afterwards."""
