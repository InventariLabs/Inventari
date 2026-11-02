"""Location codes that read like the shelf: a template per warehouse.

A warehouse is a top-level location, and the code template it carries says
how the codes of the places inside it are made. A template with placeholders
follows the tree: ``{zone}-{rack:02}-{level:02}`` gives the first level under
the warehouse a letter (``A``), the next a two-digit number after its
parent's code (``A-02``), and the one after that another (``A-02-01``). A
person reads the place off the sticker without scanning it. A template with
no placeholder is a prefix, and codes under it are drawn at random
(``LOC-7KQ2``) — the household style, where a code is only a code.

The template is kept in the warehouse's ``settings['code_template']``. A
warehouse that names none follows its organization's profile
(``ProductProfile.location_codes``), so a household that becomes a business
gets shelf codes for what it adds next without anything being rewritten.

Three rules hold everywhere below.

* A code is the physical sticker, not the name. Renaming a zone leaves every
  code under it as it was; nothing here reads a name.
* A code never moves to another shelf. When numbering changes a location's
  code, the old one stays behind as a pool label aimed at the same location
  (``LabelPool.target_storage_location_id``, which the scan chain resolves),
  and the location is marked as having a sticker to reprint. A new code is
  never one that an old sticker somewhere still carries.
* A number is the next one after the highest among the siblings, not the
  first gap: a gap is usually a rack that was taken down, and its old sticker
  may still be lying around.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.core.db_utils import acquire_advisory_lock
from app.core.exceptions import ValidationException, catalogue_refusal
from app.core.label_codes import LABEL_PREFIX_MAX_LENGTH
from app.core.product_profiles import DEFAULT_PROFILE_ID, get_profile
from app.models.label_pool import LabelPool
from app.models.organization import Organization
from app.models.storage_location import LocationUsage, StorageLocation

#: The business default: zone letter, rack and level two digits each.
TREE_TEMPLATE = '{zone}-{rack:02}-{level:02}'

#: The household default: random codes after this prefix.
RANDOM_PREFIX = 'LOC'

#: The key in a warehouse's ``settings`` that holds its template.
TEMPLATE_KEY = 'code_template'

#: The key in a location's ``settings`` that holds the code its old sticker
#: carries, while the sticker waits to be replaced.
REPRINT_KEY = 'label_reprint'

#: How many levels a template may number, and how wide a number may be.
_MAX_SEGMENTS = 6
_MAX_WIDTH = 6

_PLACEHOLDER = re.compile(r'\{([A-Za-z_][A-Za-z0-9_]*)(?::0?([1-9]))?\}')
_LITERAL = re.compile(r'^[A-Z0-9._/-]*$')
_PREFIX = re.compile(rf'^[A-Z0-9]{{1,{LABEL_PREFIX_MAX_LENGTH}}}$')


@dataclass(frozen=True)
class _Segment:
    #: The text between the previous level's code and this level's value.
    literal: str
    #: Digits padded to this width, or letters when None.
    width: int | None
    name: str


@dataclass(frozen=True)
class CodeTemplate:
    """A parsed template: either a random prefix or one segment per level."""

    raw: str
    prefix: str | None
    segments: tuple[_Segment, ...]

    @property
    def is_tree(self) -> bool:
        return self.prefix is None

    def base(self, depth: int, parent_code: str | None) -> str:
        """What a code at *depth* starts with, before its own value."""
        literal = self.segments[depth - 1].literal
        return literal if depth == 1 else f'{parent_code or ""}{literal}'

    def format(self, depth: int, base: str, number: int) -> str:
        width = self.segments[depth - 1].width
        value = _letters(number) if width is None else str(number).zfill(width)
        return f'{base}{value}'

    def value(self, depth: int, base: str, code: str | None) -> int | None:
        """The number *code* carries at *depth* after *base*, or None if it is
        not a code of this template there."""
        if not code or not code.startswith(base):
            return None
        rest = code[len(base) :]
        width = self.segments[depth - 1].width
        if width is None:
            return _from_letters(rest) if re.fullmatch(r'[A-Z]+', rest) else None
        if not re.fullmatch(r'\d+', rest) or len(rest) < width:
            return None
        # One code, one spelling: ``A-002`` is not the rack ``A-02``.
        number = int(rest)
        return number if str(number).zfill(width) == rest and number > 0 else None


def _letters(number: int) -> str:
    """1 → A, 26 → Z, 27 → AA: the column letters of a spreadsheet."""
    out = ''
    while number > 0:
        number, rest = divmod(number - 1, 26)
        out = chr(ord('A') + rest) + out
    return out


def _from_letters(text: str) -> int:
    number = 0
    for char in text:
        number = number * 26 + (ord(char) - ord('A') + 1)
    return number


def _refuse(key: str, **params: Any) -> ValidationException:
    return catalogue_refusal(key, **params, field='code_template')


def parse_template(raw: str) -> CodeTemplate:
    """Read a template as a person typed it, or refuse it in their words.

    Placeholders are ``{name}`` (letters) and ``{name:02}`` (digits padded to
    two); the text between two of them is the separator and may not be empty,
    or ``A1`` and ``A11`` could not be told apart. A template without any
    placeholder is a prefix for random codes, ``LOC`` or ``LOC-`` alike.
    """
    text = raw.strip()
    found = list(_PLACEHOLDER.finditer(text))
    if not found:
        prefix = text.rstrip('-').upper()
        if not _PREFIX.fullmatch(prefix):
            raise _refuse('storage_code_template_invalid', template=raw)
        return CodeTemplate(raw=prefix, prefix=prefix, segments=())
    segments: list[_Segment] = []
    cursor = 0
    for index, match in enumerate(found):
        literal = text[cursor : match.start()].upper()
        if not _LITERAL.fullmatch(literal) or (index > 0 and not literal):
            raise _refuse('storage_code_template_invalid', template=raw)
        width = int(match.group(2)) if match.group(2) else None
        segments.append(_Segment(literal, width, match.group(1)))
        cursor = match.end()
    if text[cursor:] or len(segments) > _MAX_SEGMENTS:
        raise _refuse('storage_code_template_invalid', template=raw)
    canonical = ''.join(
        f'{s.literal}{{{s.name}{f":0{s.width}" if s.width else ""}}}' for s in segments
    )
    return CodeTemplate(raw=canonical, prefix=None, segments=tuple(segments))


def default_template_for(profile_id: str | None) -> str:
    """The template a profile gives a warehouse naming none.

    Sync on purpose: the demo's seed numbers a freshly seeded sandbox from a
    session it already holds, and there the organization's row is in hand
    instead of one query away.
    """
    profile = get_profile(profile_id or DEFAULT_PROFILE_ID)
    if profile is not None and profile.location_codes == 'random':
        return RANDOM_PREFIX
    return TREE_TEMPLATE


async def default_template_async(db: AsyncSession, organization_id: UUID) -> str:
    """The template the organization's profile gives a warehouse naming none."""
    profile_id = await db.scalar(
        select(Organization.active_profile_id).where(Organization.id == organization_id)
    )
    return default_template_for(profile_id)


def stored_template(warehouse: StorageLocation) -> str | None:
    value = (warehouse.settings or {}).get(TEMPLATE_KEY)
    return value if isinstance(value, str) and value else None


async def template_of_async(
    db: AsyncSession, warehouse: StorageLocation
) -> CodeTemplate:
    raw = stored_template(warehouse) or await default_template_async(
        db, warehouse.organization_id
    )
    try:
        return parse_template(raw)
    except ValidationException:
        # A template written by hand into settings that no longer parses:
        # the profile's answer rather than no code at all.
        return parse_template(
            await default_template_async(db, warehouse.organization_id)
        )


# ── the tree, read once ─────────────────────────────────────────────


class _Tree:
    """Every internal location of an organization, by id and by parent."""

    def __init__(self, rows: Iterable[StorageLocation]) -> None:
        self.by_id = {row.id: row for row in rows}
        self.children: dict[UUID | None, list[StorageLocation]] = {}
        for row in self.by_id.values():
            self.children.setdefault(row.parent_id, []).append(row)
        for siblings in self.children.values():
            siblings.sort(key=_walk_order)

    def chain(self, location_id: UUID) -> list[StorageLocation]:
        """The location and its ancestors, the warehouse first."""
        out: list[StorageLocation] = []
        current = self.by_id.get(location_id)
        while current is not None and len(out) <= len(self.by_id):
            out.append(current)
            current = self.by_id.get(current.parent_id) if current.parent_id else None
        return list(reversed(out))

    def subtree(self, location_id: UUID) -> list[StorageLocation]:
        out: list[StorageLocation] = []
        stack = [self.by_id[location_id]]
        while stack:
            node = stack.pop()
            out.append(node)
            stack.extend(self.children.get(node.id, []))
        return out


def _walk_order(row: StorageLocation) -> tuple[Any, ...]:
    """The order a person reads siblings in: their walk number, then name."""
    return (row.sequence is None, row.sequence or 0, row.name.casefold(), str(row.id))


async def _tree_async(db: AsyncSession, organization_id: UUID) -> _Tree:
    """The places that take part in numbering. An archived one takes no
    number, and its code stays out of reach like any sticker's."""
    from app.services.storage._queries import not_archived_condition

    rows = await db.scalars(
        select(StorageLocation).where(
            StorageLocation.organization_id == organization_id,
            StorageLocation.usage == LocationUsage.INTERNAL.value,
            not_archived_condition(),
        )
    )
    return _Tree(rows.all())


async def _codes_in_use_async(db: AsyncSession, organization_id: UUID) -> set[str]:
    """Every code a sticker of this organization may carry today."""
    locations = await db.scalars(
        select(StorageLocation.short_code).where(
            StorageLocation.organization_id == organization_id,
            StorageLocation.short_code.is_not(None),
        )
    )
    labels = await db.scalars(
        select(LabelPool.short_code).where(LabelPool.organization_id == organization_id)
    )
    return {code for code in [*locations.all(), *labels.all()] if code}


def _numbered(template: CodeTemplate, chain: list[StorageLocation]) -> bool:
    """Whether every level below the warehouse carries its template code."""
    if len(chain) - 1 > len(template.segments):
        return False
    for depth in range(1, len(chain)):
        base = template.base(depth, chain[depth - 1].short_code)
        if template.value(depth, base, chain[depth].short_code) is None:
            return False
    return True


def _next_number(
    template: CodeTemplate,
    depth: int,
    base: str,
    siblings: Iterable[str | None],
    after: int,
    free: Any,
) -> tuple[int, str]:
    """The number after *after* and after every sibling's, whose code is free."""
    values = [template.value(depth, base, code) for code in siblings]
    number = max([after, *[v for v in values if v is not None]]) + 1
    while not free(template.format(depth, base, number)):
        number += 1
    return number, template.format(depth, base, number)


# ── a new location ──────────────────────────────────────────────────


async def new_location_code_async(
    db: AsyncSession, organization_id: UUID, parent_id: UUID | None
) -> str | None:
    """The tree code a new location under *parent_id* gets, if it gets one.

    None when the warehouse draws random codes, when the parent does not
    carry its own template code (a rack still numbered ``LOC-…``), or when
    the new place is deeper than the template numbers: the caller then draws
    a random code, as every location got before templates.
    """
    if parent_id is None:
        return None
    tree = await _tree_async(db, organization_id)
    chain = tree.chain(parent_id)
    if not chain:
        return None
    template = await template_of_async(db, chain[0])
    depth = len(chain)
    if not template.is_tree or not _numbered(template, chain):
        return None
    if depth > len(template.segments):
        return None
    taken = await _codes_in_use_async(db, organization_id)
    base = template.base(depth, chain[-1].short_code)
    siblings = [row.short_code for row in tree.children.get(parent_id, [])]
    return _next_number(
        template, depth, base, siblings, 0, lambda code: code not in taken
    )[1]


async def code_for_new_location_async(
    db: AsyncSession,
    organization_id: UUID,
    parent_id: UUID | None,
    asked_prefix: str | None = None,
) -> str:
    """The code a new location gets when nobody typed one.

    A caller that names a prefix of its own gets a random code after it, as
    every location did before templates. Otherwise the warehouse decides:
    the next shelf code under a numbered parent, or a random code after the
    warehouse's prefix.
    """
    from app.services.label_service import generate_short_code_async

    # The next code is read from the siblings that exist, so two requests that
    # read before either committed would draw the same letter and the second
    # insert would end on the unique constraint. The lock lives until the
    # caller's transaction ends, i.e. until the new place is visible to the
    # request that waits behind it.
    await acquire_advisory_lock(db, f'storage_codes:{organization_id}')
    if asked_prefix and asked_prefix.upper() != RANDOM_PREFIX:
        return await generate_short_code_async(
            db, prefix=asked_prefix, organization_id=organization_id
        )
    code = await new_location_code_async(db, organization_id, parent_id)
    if code is not None:
        return code
    return await generate_short_code_async(
        db,
        prefix=await random_prefix_async(db, organization_id, parent_id),
        organization_id=organization_id,
    )


async def random_prefix_async(
    db: AsyncSession, organization_id: UUID, parent_id: UUID | None
) -> str:
    """The prefix of a random code under *parent_id*'s warehouse."""
    if parent_id is not None:
        chain = (await _tree_async(db, organization_id)).chain(parent_id)
        if chain:
            template = await template_of_async(db, chain[0])
            if template.prefix:
                return template.prefix
    return RANDOM_PREFIX


# ── numbering a branch ──────────────────────────────────────────────


@dataclass(frozen=True)
class CodeChange:
    location: StorageLocation
    old_code: str | None
    new_code: str


class _Numbering:
    """One pass of numbering over a branch, the codes it gives kept in memory.

    A code may go to a location in the branch unless a sticker outside the
    branch carries it, another location in the branch carries it today, or
    this pass already gave it away.
    """

    def __init__(
        self, tree: _Tree, template: CodeTemplate, branch: set[UUID], in_use: set[str]
    ) -> None:
        self.tree = tree
        self.template = template
        self.held = {
            tree.by_id[i].short_code: i for i in branch if tree.by_id[i].short_code
        }
        self.outside = in_use - set(self.held)
        self.given: dict[UUID, str] = {}
        self.assigned: set[str] = set()

    def give(self, row: StorageLocation, code: str) -> None:
        self.given[row.id] = code
        self.assigned.add(code)

    def free_for(self, row: StorageLocation):
        def free(code: str) -> bool:
            owner = self.held.get(code)
            return (
                code not in self.outside
                and code not in self.assigned
                and (owner is None or owner == row.id)
            )

        return free

    def code_of(self, row: StorageLocation) -> str | None:
        return self.given.get(row.id, row.short_code)

    def place(
        self, target: StorageLocation, depth: int, parent_code: str | None
    ) -> None:
        """The branch's own head: kept when it is its template code already."""
        base = self.template.base(depth, parent_code)
        if self.template.value(depth, base, target.short_code) is not None:
            self.give(target, target.short_code or '')
            return
        siblings = [
            row.short_code
            for row in self.tree.children.get(target.parent_id, [])
            if row.id != target.id
        ]
        self.give(
            target,
            _next_number(
                self.template, depth, base, siblings, 0, self.free_for(target)
            )[1],
        )

    def family(self, parent: StorageLocation, level: int, keep: bool) -> None:
        """Number *parent*'s children, then theirs, down to the template's end."""
        if level > len(self.template.segments):
            return
        children = self.tree.children.get(parent.id, [])
        base = self.template.base(level, self.code_of(parent) if level > 1 else None)
        # A code that already is the template's code of this place is right
        # whichever way the branch is numbered; renumbering only takes the
        # places that have none, in walk order, from the lowest free number.
        for row in children:
            if self.template.value(level, base, row.short_code) is not None:
                self.give(row, row.short_code or '')
        last = 0
        for row in children:
            if row.id in self.given:
                continue
            kept = [self.given.get(c.id) for c in children] if keep else []
            last, code = _next_number(
                self.template, level, base, kept, last, self.free_for(row)
            )
            self.give(row, code)
        for row in children:
            self.family(row, level + 1, keep)


def plan_branch_codes(
    rows: Iterable[StorageLocation],
    template: CodeTemplate,
    location_id: UUID,
    in_use: set[str],
    *,
    renumber: bool,
) -> dict[UUID, str]:
    """The code each location of a branch takes, decided without writing one.

    The whole pass is pure: no query, no row touched. ``number_branch_async``
    loads the rows and writes what comes back, and the demo's seed numbers a
    sandbox's shelves straight from the session it seeded them with — a
    second walker would be a second answer the first has never seen, and two
    sandboxes only hand out the same code because they take this same path.

    Refuses exactly what ``number_branch_async`` refuses, in the same order:
    a location that is not here, a template that does not number, a parent
    that does not carry its own code yet.
    """
    tree = _Tree(rows)
    if location_id not in tree.by_id:
        raise _refuse('storage_code_number_not_here')
    chain = tree.chain(location_id)
    if not template.is_tree:
        raise _refuse('storage_code_template_not_tree')
    depth = len(chain) - 1
    if depth > len(template.segments) or not _numbered(template, chain[:-1]):
        raise _refuse('storage_code_parent_not_numbered')

    numbering = _Numbering(
        tree,
        template,
        {row.id for row in tree.subtree(location_id)},
        in_use,
    )
    if depth >= 1:
        numbering.place(chain[-1], depth, chain[-2].short_code if depth > 1 else None)
    numbering.family(chain[-1], depth + 1, keep=not renumber)
    return dict(numbering.given)


async def number_branch_async(
    db: AsyncSession,
    organization_id: UUID,
    user_id: UUID,
    location_id: UUID,
    *,
    renumber: bool,
) -> list[CodeChange]:
    """Give a branch its template codes; returns the codes that changed.

    *location_id* is a warehouse or a place inside one. Its own code is kept
    when it already is its template code, and given the next one among its
    siblings otherwise; a warehouse keeps its code either way.

    Both keep every code in the branch that already is its template code.
    ``renumber=False`` ("Number this rack") numbers the rest after the highest
    of them. ``renumber=True`` ("Renumber by template") numbers the rest in
    walk order from the lowest free number, skipping a code an old sticker
    still carries.

    Either way an old code that changes stays behind as a pool label aimed at
    its location, and the location is marked with a sticker to reprint.
    Flushes; the caller commits.
    """
    # The lock a new location takes before it draws its code
    # (``code_for_new_location_async``), taken before the branch and the
    # codes in use are read. Without it a location created meanwhile drew
    # the code this renumber was about to give, and one of the two ended on
    # the unique constraint; two renumbers of overlapping branches likewise.
    await acquire_advisory_lock(db, f'storage_codes:{organization_id}')
    tree = await _tree_async(db, organization_id)
    if location_id not in tree.by_id:
        raise _refuse('storage_code_number_not_here')
    template = await template_of_async(db, tree.chain(location_id)[0])
    given = plan_branch_codes(
        tree.by_id.values(),
        template,
        location_id,
        await _codes_in_use_async(db, organization_id),
        renumber=renumber,
    )

    changes = [
        CodeChange(tree.by_id[i], tree.by_id[i].short_code, code)
        for i, code in given.items()
        if code != tree.by_id[i].short_code
    ]
    await _write_changes_async(db, organization_id, user_id, changes)
    return changes


async def _write_changes_async(
    db: AsyncSession,
    organization_id: UUID,
    user_id: UUID,
    changes: list[CodeChange],
) -> None:
    from app.models.audit_log import AuditAction, AuditTargetType
    from app.services.audit_service import log_action_async

    if not changes:
        return
    # Cleared first: two locations of the branch may trade codes, and the
    # unique constraint is checked row by row.
    for change in changes:
        change.location.short_code = None
    await db.flush()
    new_codes = {change.new_code for change in changes}
    # A code a location took back from its own alias is a pool label already,
    # aimed at that location (a location may take only its own alias): it is
    # kept as it is rather than written twice.
    aliased = set(
        (
            await db.scalars(
                select(LabelPool.short_code).where(
                    LabelPool.organization_id == organization_id,
                    LabelPool.short_code.in_(
                        [c.old_code for c in changes if c.old_code]
                    ),
                )
            )
        ).all()
    )
    for change in changes:
        location = change.location
        location.short_code = change.new_code
        if change.old_code and change.old_code not in new_codes:
            if change.old_code not in aliased:
                db.add(
                    LabelPool(
                        short_code=change.old_code,
                        label_type='STORAGE',
                        target_storage_location_id=location.id,
                        organization_id=organization_id,
                        created_by=user_id,
                    )
                )
            location.settings = {
                **(location.settings or {}),
                REPRINT_KEY: change.old_code,
            }
            flag_modified(location, 'settings')
        await log_action_async(
            db,
            organization_id=organization_id,
            user_id=user_id,
            action=AuditAction.UPDATE,
            target_type=AuditTargetType.STORAGE,
            target_id=location.id,
            snapshot={
                'name': location.name,
                'before': {'short_code': change.old_code},
                'after': {'short_code': change.new_code},
            },
        )
    await db.flush()


# ── the warehouse's codes, as the screen reads them ─────────────────


async def warehouse_codes_async(
    db: AsyncSession, organization_id: UUID, location_id: UUID
) -> dict[str, Any] | None:
    """The template of *location_id*'s warehouse and its stickers to reprint."""
    tree = await _tree_async(db, organization_id)
    if location_id not in tree.by_id:
        return None
    warehouse = tree.chain(location_id)[0]
    template = await template_of_async(db, warehouse)
    paths: dict[UUID, str] = {}

    def path_of(row: StorageLocation) -> str:
        if row.id not in paths:
            parent = tree.by_id.get(row.parent_id) if row.parent_id else None
            paths[row.id] = f'{path_of(parent)} → {row.name}' if parent else row.name
        return paths[row.id]

    reprint = [
        {
            'id': row.id,
            'name': row.name,
            'path': path_of(row),
            'short_code': row.short_code,
            'old_code': (row.settings or {}).get(REPRINT_KEY),
        }
        for row in sorted(tree.subtree(warehouse.id), key=path_of)
        if (row.settings or {}).get(REPRINT_KEY)
    ]
    return {
        'warehouse_id': warehouse.id,
        'template': template.raw,
        'is_tree': template.is_tree,
        'stored': stored_template(warehouse) is not None,
        'default_template': await default_template_async(db, organization_id),
        'reprint': reprint,
    }


async def set_template_async(
    db: AsyncSession,
    organization_id: UUID,
    user_id: UUID,
    warehouse: StorageLocation,
    raw: str | None,
) -> None:
    """Keep *raw* as the warehouse's template, or None to follow the profile.

    Changes no code: the screen offers renumbering after, because rewriting
    every sticker in a warehouse is a decision of its own. Flushes.
    """
    from app.models.audit_log import AuditAction, AuditTargetType
    from app.services.audit_service import log_action_async

    if warehouse.parent_id is not None:
        raise _refuse('storage_code_template_not_warehouse')
    before = stored_template(warehouse)
    settings = dict(warehouse.settings or {})
    if raw is None or not raw.strip():
        settings.pop(TEMPLATE_KEY, None)
    else:
        settings[TEMPLATE_KEY] = parse_template(raw).raw
    if settings.get(TEMPLATE_KEY) == before:
        return
    warehouse.settings = settings
    flag_modified(warehouse, 'settings')
    await log_action_async(
        db,
        organization_id=organization_id,
        user_id=user_id,
        action=AuditAction.UPDATE,
        target_type=AuditTargetType.STORAGE,
        target_id=warehouse.id,
        snapshot={
            'name': warehouse.name,
            'before': {TEMPLATE_KEY: before},
            'after': {TEMPLATE_KEY: settings.get(TEMPLATE_KEY)},
        },
    )
    await db.flush()


async def mark_reprinted_async(
    db: AsyncSession, organization_id: UUID, user_id: UUID, location_ids: list[UUID]
) -> int:
    """Forget the stickers to reprint on these locations; returns how many.

    The old code keeps scanning: its pool label stays. Flushes.
    """
    from app.models.audit_log import AuditAction, AuditTargetType
    from app.services.audit_service import log_action_async

    rows = await db.scalars(
        select(StorageLocation).where(
            StorageLocation.organization_id == organization_id,
            StorageLocation.id.in_(location_ids),
        )
    )
    done = 0
    for row in rows.all():
        old_code = (row.settings or {}).get(REPRINT_KEY)
        if not old_code:
            continue
        row.settings = {
            k: v for k, v in (row.settings or {}).items() if k != REPRINT_KEY
        }
        flag_modified(row, 'settings')
        done += 1
        await log_action_async(
            db,
            organization_id=organization_id,
            user_id=user_id,
            action=AuditAction.UPDATE,
            target_type=AuditTargetType.STORAGE,
            target_id=row.id,
            snapshot={
                'name': row.name,
                'before': {REPRINT_KEY: old_code},
                'after': {REPRINT_KEY: None},
            },
        )
    await db.flush()
    return done
