"""Where an import row's product goes: the sheet's location cells, read as a path.

The app writes a location as "Pantry › Dry Goods › Shelf A". A file from
another tool writes "WH/Stock/Shelf 1" or splits the path over two columns.
Either way a row lands in one location, found or founded level by level.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, cast
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import UserContextDTO
from app.core.exceptions import ServiceRejectionError
from app.core.location_path import join_location_path
from app.models.storage_location import LocationUsage, StorageLocation
from app.models.storage_type import StorageType

#: A keyboard writes the app's arrow as "->" or ">", and a file written before
#: the arrow gave way to it still says "→". All of them read as one path.
_PATH_SEPARATORS = ('›', '→', '->', '>')

#: How a "/" in a location cell reads: as a step of a path, or as a letter of
#: the name. The reader chooses in the mapping step.
LocationSlash = Literal['path', 'name']


class _StorageIndex:
    """The organization's locations, by name and by place in the tree.

    A bare name matches any location carrying it (the first one seen), a
    path matches segment by segment from the root — so "Shelf A" and
    "Pantry › Dry Goods › Shelf A" both find the shelf, and a path whose
    tail is missing knows which parent to grow it under.
    """

    def __init__(self) -> None:
        self._children: dict[tuple[UUID | None, str], UUID] = {}
        self._by_name: dict[str, UUID] = {}
        self._name: dict[UUID, str] = {}
        self._parent: dict[UUID, UUID | None] = {}
        self._fields: dict[UUID, list[dict[str, Any]]] = {}

    @staticmethod
    def _key(name: str) -> str:
        return name.strip().lower()

    def add(
        self,
        loc_id: UUID,
        name: str,
        parent_id: UUID | None,
        fields: list[dict[str, Any]] | None = None,
    ) -> None:
        self._children[(parent_id, self._key(name))] = loc_id
        self._by_name.setdefault(self._key(name), loc_id)
        self._name[loc_id] = name
        self._parent[loc_id] = parent_id
        self._fields[loc_id] = fields or []

    def remove(self, loc_id: UUID) -> None:
        """Forget a location whose INSERT was rolled back."""
        name = self._name.pop(loc_id, None)
        parent_id = self._parent.pop(loc_id, None)
        self._fields.pop(loc_id, None)
        if name is None:
            return
        self._children.pop((parent_id, self._key(name)), None)
        if self._by_name.get(self._key(name)) == loc_id:
            del self._by_name[self._key(name)]

    def child(self, parent_id: UUID | None, name: str) -> UUID | None:
        return self._children.get((parent_id, self._key(name)))

    def by_name(self, name: str) -> UUID | None:
        return self._by_name.get(self._key(name))

    def path_of(self, loc_id: UUID) -> str:
        names: list[str] = []
        seen: set[UUID] = set()
        current: UUID | None = loc_id
        while current is not None and current not in seen:
            seen.add(current)
            names.append(self._name.get(current, ''))
            current = self._parent.get(current)
        return join_location_path(reversed(names))

    def fields_of(self, loc_id: UUID) -> dict[str, dict[str, Any]]:
        """The product fields a location asks for: its own and every level's above.

        The rule the storages listing and the form follow: the nearest level
        that defines a key gives it, so the location's own definition wins
        over its rack's and the rack's over the warehouse's. A location this
        import founds sets nothing itself and still inherits.
        """
        fields: dict[str, dict[str, Any]] = {}
        seen: set[UUID] = set()
        current: UUID | None = loc_id
        while current is not None and current not in seen:
            seen.add(current)
            for definition in self._fields.get(current, []):
                key = definition.get('key') if isinstance(definition, dict) else None
                if key:
                    fields.setdefault(key, definition)
            current = self._parent.get(current)
        return fields


async def _preload_storage_index(
    db: AsyncSession, org_id: UUID | None
) -> _StorageIndex:
    index = _StorageIndex()
    if org_id is None:
        return index
    result = await db.execute(
        select(StorageLocation)
        .where(StorageLocation.organization_id == org_id)
        .order_by(StorageLocation.created_at, StorageLocation.name)
    )
    for s in result.scalars().all():
        index.add(s.id, s.name, s.parent_id, s.field_definitions)
    return index


async def default_storage_type_id(db: AsyncSession, org_id: UUID | None) -> UUID | None:
    """The StorageType a freshly-founded location gets.

    Prefers the org's own types; falls back to a global (org_id IS NULL) type;
    None when no type exists at all.
    """
    if org_id is None:
        return None
    own = await db.scalar(
        select(StorageType.id).where(StorageType.organization_id == org_id).limit(1)
    )
    if own:
        return own
    return cast(
        UUID | None,
        await db.scalar(
            select(StorageType.id).where(StorageType.organization_id.is_(None)).limit(1)
        ),
    )


@dataclass
class SheetLocations:
    """The locations one import reads, and the ones it founds on the way."""

    db: AsyncSession
    user: UserContextDTO
    index: _StorageIndex
    storage_type_id: UUID | None
    create_missing: bool
    slash: LocationSlash
    default_id: UUID | None = None
    #: The paths of the locations founded, for the result screen.
    created: list[str] = field(default_factory=list)
    #: What the row in progress founded. The savepoint rolls back its
    #: INSERTs, not the index — a stale id would FK-fail every later row.
    row_founded: list[UUID] = field(default_factory=list)

    @classmethod
    async def load(
        cls,
        db: AsyncSession,
        user: UserContextDTO,
        *,
        create_missing: bool,
        slash: LocationSlash,
    ) -> SheetLocations:
        return cls(
            db=db,
            user=user,
            index=await _preload_storage_index(db, user.organization_id),
            storage_type_id=await default_storage_type_id(db, user.organization_id),
            create_missing=create_missing,
            slash=slash,
        )

    def discard_row(self) -> None:
        for loc_id in self.row_founded:
            self.index.remove(loc_id)
        if self.row_founded:
            del self.created[-len(self.row_founded) :]
        self.row_founded.clear()

    def _steps(self, text: str) -> list[str]:
        """A cell as the steps of a path, outermost first.

        A "/" divides steps only when the reader chose that reading, the cell
        is not already written the app's way (where it belongs to a name), and
        no location carries the whole text as its name.
        """
        marked = text
        for separator in _PATH_SEPARATORS:
            marked = marked.replace(separator, '\x00')
        if (
            self.slash == 'path'
            and '\x00' not in marked
            and self.index.by_name(text) is None
        ):
            marked = marked.replace('/', '\x00')
        return [part.strip() for part in marked.split('\x00') if part.strip()]

    async def resolve(self, cells: list[tuple[str, str]]) -> UUID:
        """The location *cells* name — (column, text) pairs, read as one path.

        No cell names the organization's first location. A path that misses is
        founded when allowed, and refused otherwise.
        """
        steps = [step for _, text in cells for step in self._steps(text)]
        if not steps:
            return await self._default()
        found = await self._walk(steps, create=False)
        if found is None and self.create_missing:
            found = await self._walk(steps, create=True)
        if found is None:
            raise ServiceRejectionError(
                'import_column_location_not_found',
                column=cells[0][0],
                value=join_location_path(text for _, text in cells),
            )
        return found

    async def _default(self) -> UUID:
        """The organization's first real shelf, for a row that names none.

        The virtual places — consumed, loss, production — are seeded before
        any shelf and sort first by creation, so taking the oldest location
        outright files the import's stock as already gone: the products list
        shows only what sits on a real shelf, and the reader's new product
        would never appear. An organization with no shelf at all has nowhere
        for stock to go, and the refusal says so.
        """
        if self.default_id is None:
            self.default_id = await self.db.scalar(
                select(StorageLocation.id)
                .where(
                    StorageLocation.organization_id == self.user.organization_id,
                    StorageLocation.usage == LocationUsage.INTERNAL,
                )
                .order_by(StorageLocation.created_at)
            )
        if self.default_id is None:
            raise ServiceRejectionError('import_location_unresolved')
        return self.default_id

    async def _walk(self, steps: list[str], *, create: bool) -> UUID | None:
        """Follow a path down the tree, founding what is missing when allowed.

        The first step may sit anywhere in the tree (a reader may start the
        path below the root); every later one must be a child of the one before.
        """
        parent_id: UUID | None = None
        for position, name in enumerate(steps):
            found = self.index.child(parent_id, name)
            if found is None and position == 0:
                found = self.index.by_name(name)
            if found is None:
                if not create:
                    return None
                found = await self._found(name, parent_id)
            parent_id = found
        return parent_id

    async def _found(self, name: str, parent_id: UUID | None) -> UUID:
        location = StorageLocation(
            name=name,
            organization_id=self.user.organization_id,
            storage_type_id=self.storage_type_id,
            created_by=self.user.id,
            parent_id=parent_id,
        )
        self.db.add(location)
        await self.db.flush()
        self.index.add(location.id, name, parent_id)
        self.row_founded.append(location.id)
        self.created.append(self.index.path_of(location.id))
        return location.id
