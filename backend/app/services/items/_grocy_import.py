"""Moving in from Grocy: its database file through the doors the form uses.

Grocy writes no export of its own; :mod:`app.core.grocy_file` reads its
SQLite file, and this module files what the file holds into the
organization:

- every active location, product group and store becomes a location, a
  category and a supplier, reusing one of the same name;
- every batch of stock becomes a record through ``create_item_async`` — the
  door the form and the sheet import use — with its amount in the product's
  stock unit, its best-before date, price, purchase date, shelf, store and
  the opened mark;
- a product without stock becomes a product of the catalogue only.

Each product and each record keeps where it came from in
``meta_data['import']`` (``{'source': 'grocy', 'id': <Grocy's id>}``): a
second run of the same file adds nothing twice, and a module reading the
same file — the shopping lists — finds the products by Grocy's id
(:func:`imported_product_ids_async`).

What the file holds that has no place here is counted, never dropped in
silence (:func:`left_behind`). Prices are read in the organization's
currency: Grocy keeps its own in its configuration, not in the file.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any, cast
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import UserContextDTO
from app.core.exceptions import ServiceRejectionError
from app.core.grocy_file import GrocyFile, GrocyProduct, GrocyStockEntry
from app.core.import_sheet import explain
from app.core.logging import get_logger
from app.core.move_contributors import (
    MoveMatches,
    MoveOutcome,
    bring_async,
    contributors_for,
)
from app.core.open_package import OPENED_KEY
from app.models.category import Category
from app.models.item import Item
from app.models.organization import Organization
from app.models.partner import Partner
from app.models.product_template import ProductTemplate
from app.models.storage_location import StorageLocation
from app.models.storage_type import StorageType
from app.schemas.item import ItemCreate

from ._create import _default_piece_uom_id_async, create_item_async
from ._import_locations import default_storage_type_id
from ._template import find_template_async

logger = get_logger(__name__)

SOURCE = 'grocy'

#: The ``meta_data`` key that says where a product or a record came from.
IMPORT_KEY = 'import'

#: Products and batches imported between two progress reports.
_BATCH = 50

#: The kinds of record a summary lists, in the order it lists them.
_LEFT_BEHIND_ORDER = (
    'inactive_products',
    'inactive_locations',
    'inactive_product_groups',
    'inactive_stores',
    'extra_barcodes',
    'unit_conversions',
    'units_as_pieces',
    'prices_below_a_cent',
    'default_best_before_days',
    'pictures',
    'parent_products',
    'own_field_values',
    'shopping_list_entries',
    'recipes',
    'meal_plan',
    'chores',
    'batteries',
    'tasks',
    'equipment',
)


def import_stamp(grocy_id: object) -> dict[str, Any]:
    """The ``meta_data`` a product or record brought from Grocy carries."""
    return {IMPORT_KEY: {'source': SOURCE, 'id': str(grocy_id)}}


async def imported_product_ids_async(db: AsyncSession, org_id: UUID) -> dict[str, UUID]:
    """Grocy's product id → the product it became, for every earlier Grocy move."""
    stamp = ProductTemplate.meta_data[IMPORT_KEY]
    rows = await db.execute(
        select(stamp['id'].astext, ProductTemplate.id).where(
            ProductTemplate.organization_id == org_id,
            stamp['source'].astext == SOURCE,
        )
    )
    return {str(grocy_id): template_id for grocy_id, template_id in rows.all()}


async def _imported_stock_ids_async(db: AsyncSession, org_id: UUID) -> set[str]:
    stamp = Item.meta_data[IMPORT_KEY]
    rows = await db.execute(
        select(stamp['id'].astext).where(
            Item.organization_id == org_id,
            stamp['source'].astext == SOURCE,
        )
    )
    return {grocy_id for (grocy_id,) in rows.all()}


def _active_products(grocy: GrocyFile) -> list[GrocyProduct]:
    return [p for p in grocy.products.values() if p.active]


def _stock_of(grocy: GrocyFile) -> dict[int, list[GrocyStockEntry]]:
    by_product: dict[int, list[GrocyStockEntry]] = {}
    for entry in grocy.stock:
        if entry.amount > 0:
            by_product.setdefault(entry.product_id, []).append(entry)
    return by_product


def left_behind(
    grocy: GrocyFile,
    units_as_pieces: list[str],
    taken: set[str] | frozenset[str] = frozenset(),
    failed: set[str] | frozenset[str] = frozenset(),
) -> list[dict[str, Any]]:
    """What the file holds that a move does not bring, by kind and count.

    ``units_as_pieces`` names the units no unit here matched, which the
    imported stock is counted in as pieces. ``taken`` names the kinds a
    switched-on module brings (:mod:`app.core.move_contributors`);
    ``failed`` the kinds whose module's part failed, listed as staying and
    marked so.
    """
    products = _active_products(grocy)
    counts: dict[str, int] = {
        'inactive_products': sum(1 for p in grocy.products.values() if not p.active),
        'inactive_locations': sum(1 for x in grocy.locations.values() if not x.active),
        'inactive_product_groups': sum(
            1 for g in grocy.groups.values() if not g.active
        ),
        'inactive_stores': sum(1 for s in grocy.stores.values() if not s.active),
        'extra_barcodes': sum(max(0, len(p.barcodes) - 1) for p in products),
        'default_best_before_days': sum(1 for p in products if p.has_default_days),
        'pictures': sum(1 for p in products if p.has_picture),
        'parent_products': sum(1 for p in products if p.has_parent),
        'units_as_pieces': len(units_as_pieces),
        'prices_below_a_cent': sum(
            1
            for p in products
            for e in _stock_of(grocy).get(p.id, [])
            if _price_held(e.price) is None and e.price is not None and e.price > 0
        ),
        'shopping_list_entries': len(grocy.shopping_list),
        **grocy.left_behind,
    }
    return [
        {
            'what': kind,
            'count': counts[kind],
            'names': units_as_pieces if kind == 'units_as_pieces' else [],
            'failed': kind in failed,
        }
        for kind in _LEFT_BEHIND_ORDER
        if counts.get(kind, 0) > 0 and (kind not in taken or kind in failed)
    ]


#: The smallest price a record holds: its price is kept to the cent.
_CENT = Decimal('0.01')


def _price_held(price: Decimal | None) -> Decimal | None:
    """A batch's price as a record keeps it, or ``None`` when it cannot.

    A record keeps its unit price to the cent, and Grocy prices a product
    counted in grams per gram: 0.0035 would be kept as 0.00, a price of
    nothing. Such a price is left behind and counted, not written as zero.
    """
    if price is None or price <= 0:
        return None
    held = price.quantize(_CENT)
    return held if held > 0 else None


def _min_quantity(product: GrocyProduct) -> float | None:
    """Grocy's minimum stock as the product's stock alert; 0 means none."""
    return float(product.min_stock) if product.min_stock > 0 else None


def _name_key(name: str) -> str:
    return name.strip().lower()


@dataclass
class GrocyPlan:
    """What a run of the file would found, and the units it cannot match.

    Read before anything is written: the route weighs the founding against
    the caller's permissions, and the step before the import shows it.
    """

    new_locations: list[str]
    new_categories: list[str]
    new_suppliers: list[str]
    #: Grocy unit id → the unit here; a unit no unit matched maps to pieces.
    unit_ids: dict[int, UUID]
    units_as_pieces: list[str]
    #: The units here that hold whole numbers only (a piece, a pack).
    whole_units: set[UUID] = field(default_factory=set)
    #: A Grocy group's name (lower case) → the category here it is, when the
    #: reader's screen matched it by the name it shows (see
    #: :func:`plan_grocy_import_async`).
    category_matches: dict[str, UUID] = field(default_factory=dict)
    #: The modules switched on for the organization; those that registered
    #: for Grocy bring their part, and the kinds they take stop staying behind.
    enabled_modules: list[str] = field(default_factory=list)

    @property
    def taken(self) -> set[str]:
        return {c.takes for c in contributors_for(SOURCE, self.enabled_modules)}


async def plan_grocy_import_async(
    db: AsyncSession,
    user: UserContextDTO,
    grocy: GrocyFile,
    category_matches: dict[str, UUID] | None = None,
) -> GrocyPlan:
    """What the move would found, read before anything is written.

    A category the platform seeded is stored under its English name and
    shown under its code's translation, so "Nabiał" in a Polish Grocy is
    the seeded "Dairy" only by the name the screen shows. The screen knows
    those names; ``category_matches`` is what it matched (a Grocy group's
    name → a category id), and an id that is not this organization's is
    ignored.
    """
    org_id = _org_of(user)
    locations = {
        _name_key(n)
        for (n,) in (
            await db.execute(
                select(StorageLocation.name).where(
                    StorageLocation.organization_id == org_id
                )
            )
        ).all()
    }
    category_rows = (
        await db.execute(
            select(Category.id, Category.name).where(Category.organization_id == org_id)
        )
    ).all()
    matches = {
        _name_key(name): category_id
        for name, category_id in (category_matches or {}).items()
        if category_id in {row_id for row_id, _ in category_rows}
    }
    categories = {_name_key(n) for _, n in category_rows} | set(matches)
    suppliers = {
        _name_key(n)
        for (n,) in (
            await db.execute(
                select(Partner.name).where(Partner.organization_id == org_id)
            )
        ).all()
    }
    unit_ids, unknown, whole_units = await _match_units_async(db, org_id, grocy)
    used_units = {p.unit_id for p in _active_products(grocy)}
    return GrocyPlan(
        new_locations=_missing(grocy.locations.values(), locations),
        new_categories=_missing(grocy.groups.values(), categories),
        new_suppliers=_missing(grocy.stores.values(), suppliers),
        unit_ids=unit_ids,
        units_as_pieces=[grocy.units[u].name for u in unknown if u in used_units],
        whole_units=whole_units,
        category_matches=matches,
        enabled_modules=list(
            await db.scalar(
                select(Organization.enabled_modules).where(Organization.id == org_id)
            )
            or []
        ),
    )


def _missing(named: Any, existing: set[str]) -> list[str]:
    seen: set[str] = set()
    missing: list[str] = []
    for row in named:
        key = _name_key(row.name)
        if row.active and key not in existing and key not in seen:
            seen.add(key)
            missing.append(row.name)
    return missing


async def _match_units_async(
    db: AsyncSession, org_id: UUID, grocy: GrocyFile
) -> tuple[dict[int, UUID], list[int], set[UUID]]:
    """Each Grocy unit's unit here, by its name or plural in any language.

    Answers the matches, the Grocy units nothing matched, and the units here
    that hold whole numbers only.

    Grocy units are free words ("Piece", "Packung", "Tin"); a word the shared
    resolver matches to no unit counts the stock in pieces, and is named in
    the summary.
    """
    from app.core.uom_resolver import UomResolverAsync
    from app.services.uom_service import list_uoms_for_org_async

    resolver = UomResolverAsync(db, org_id)
    uoms = await list_uoms_for_org_async(db, org_id)
    pieces = await _default_piece_uom_id_async(db, org_id)
    matched: dict[int, UUID] = {}
    unknown: list[int] = []
    for unit in grocy.units.values():
        found: UUID | None = None
        for word in (unit.name, unit.plural):
            if word and found is None:
                found = await resolver.resolve(word)
        if found is None:
            unknown.append(unit.id)
        matched[unit.id] = found or pieces
    whole = {u.id for u in uoms if u.rounding is not None and u.rounding >= 1}
    return matched, unknown, whole


def _org_of(user: UserContextDTO) -> UUID:
    if user.organization_id is None:
        raise ServiceRejectionError('user_has_no_organization')
    return user.organization_id


async def analyze_grocy_file_async(
    db: AsyncSession, user: UserContextDTO, grocy: GrocyFile
) -> dict[str, Any]:
    """What the file holds, what a run would found, and what stays behind."""
    org_id = _org_of(user)
    plan = await plan_grocy_import_async(db, user, grocy)
    stock = _stock_of(grocy)
    products = _active_products(grocy)
    entries = [e for p in products for e in stock.get(p.id, [])]
    already = await _imported_stock_ids_async(db, org_id)
    currency = await db.scalar(
        select(Organization.currency).where(Organization.id == org_id)
    )
    return {
        'products': len(products),
        'stock_entries': len(entries),
        'already_imported': sum(1 for e in entries if e.stock_id in already),
        'locations': sum(1 for loc in grocy.locations.values() if loc.active),
        'product_groups': sum(1 for g in grocy.groups.values() if g.active),
        'stores': sum(1 for s in grocy.stores.values() if s.active),
        'shopping_list_entries': len(grocy.shopping_list),
        'new_locations': plan.new_locations,
        'new_categories': plan.new_categories,
        'new_suppliers': plan.new_suppliers,
        'currency': currency,
        'steps': grocy_import_steps(grocy),
        'left_behind': left_behind(grocy, plan.units_as_pieces, plan.taken),
    }


def grocy_import_steps(grocy: GrocyFile) -> int:
    """Products without stock and batches: what the progress counts."""
    stock = _stock_of(grocy)
    return sum(len(stock.get(p.id, [])) or 1 for p in _active_products(grocy))


@dataclass
class _Run:
    db: AsyncSession
    user: UserContextDTO
    org_id: UUID
    grocy: GrocyFile
    plan: GrocyPlan
    today: date
    locations: dict[int, UUID] = field(default_factory=dict)
    categories: dict[int, UUID] = field(default_factory=dict)
    suppliers: dict[int, UUID] = field(default_factory=dict)
    templates: dict[str, UUID] = field(default_factory=dict)
    imported_stock: set[str] = field(default_factory=set)
    default_location: UUID | None = None
    imported: int = 0
    joined_existing: int = 0
    skipped: int = 0
    failed: int = 0
    errors: list[dict[str, Any]] = field(default_factory=list)
    created_locations: list[str] = field(default_factory=list)
    created_categories: list[str] = field(default_factory=list)
    created_suppliers: list[str] = field(default_factory=list)

    async def found_named_rows_async(self) -> None:
        """Every active location, group and store, found or founded."""
        await self._locations_async()
        await self._categories_async()
        await self._suppliers_async()

    async def _locations_async(self) -> None:
        rows = await self.db.execute(
            select(StorageLocation.id, StorageLocation.name)
            .where(StorageLocation.organization_id == self.org_id)
            .order_by(StorageLocation.created_at, StorageLocation.name)
        )
        by_name: dict[str, UUID] = {}
        for loc_id, name in rows.all():
            by_name.setdefault(_name_key(name), loc_id)
        default_type = await default_storage_type_id(self.db, self.org_id)
        freezer_type = await self._freezer_type_async() or default_type
        for loc in self.grocy.locations.values():
            if not loc.active:
                continue
            key = _name_key(loc.name)
            if key not in by_name:
                location = StorageLocation(
                    name=loc.name,
                    description=loc.description,
                    organization_id=self.org_id,
                    storage_type_id=freezer_type if loc.is_freezer else default_type,
                    created_by=self.user.id,
                    parent_id=None,
                )
                self.db.add(location)
                await self.db.flush()
                by_name[key] = location.id
                self.created_locations.append(loc.name)
            self.locations[loc.id] = by_name[key]
        self.default_location = next(iter(by_name.values()), None)

    async def _freezer_type_async(self) -> UUID | None:
        """A type of place that freezes what it holds, the organization's first."""
        found: UUID | None = await self.db.scalar(
            select(StorageType.id)
            .where(
                (StorageType.organization_id == self.org_id)
                | StorageType.organization_id.is_(None),
                StorageType.behavior_mode == 'FREEZING',
            )
            .order_by(StorageType.organization_id.desc().nullslast())
            .limit(1)
        )
        return found

    async def _categories_async(self) -> None:
        rows = await self.db.execute(
            select(Category.id, Category.name).where(
                Category.organization_id == self.org_id
            )
        )
        by_name = {_name_key(name): cat_id for cat_id, name in rows.all()}
        for key, category_id in self.plan.category_matches.items():
            by_name.setdefault(key, category_id)
        for group in self.grocy.groups.values():
            if not group.active:
                continue
            key = _name_key(group.name)
            if key not in by_name:
                category = Category(name=group.name, organization_id=self.org_id)
                self.db.add(category)
                await self.db.flush()
                by_name[key] = category.id
                self.created_categories.append(group.name)
            self.categories[group.id] = by_name[key]

    async def _suppliers_async(self) -> None:
        from app.schemas.partner import PartnerCreate
        from app.services import partner_service

        rows = await self.db.execute(
            select(Partner.id, Partner.name).where(
                Partner.organization_id == self.org_id
            )
        )
        by_name: dict[str, UUID] = {}
        for partner_id, name in rows.all():
            by_name.setdefault(_name_key(name), partner_id)
        for store in self.grocy.stores.values():
            if not store.active:
                continue
            key = _name_key(store.name)
            if key not in by_name:
                partner = await partner_service.create_async(
                    self.db,
                    self.org_id,
                    PartnerCreate(
                        name=store.name, type='SUPPLIER', notes=store.description
                    ),
                    self.user.id,
                )
                by_name[key] = partner.id
                self.created_suppliers.append(store.name)
            self.suppliers[store.id] = by_name[key]

    def _location_of(
        self, product: GrocyProduct, entry: GrocyStockEntry | None
    ) -> UUID:
        for grocy_id in (entry.location_id if entry else None, product.location_id):
            if grocy_id is not None and grocy_id in self.locations:
                return self.locations[grocy_id]
        if self.default_location is None:
            raise ServiceRejectionError('import_location_unresolved')
        return self.default_location

    async def _template_of_async(
        self, product: GrocyProduct
    ) -> tuple[UUID | None, bool]:
        """The product this Grocy product already is, and whether it existed.

        One an earlier run stamped wins; else the one the form would match
        — by the first barcode, then by name — which is stamped now. ``None``
        when there is none, and the first batch mints it.
        """
        known = self.templates.get(str(product.id))
        if known is not None:
            return known, True
        template = await find_template_async(
            self.db,
            self.org_id,
            name=product.name,
            barcode=product.barcodes[0] if product.barcodes else None,
        )
        if template is None or template.organization_id != self.org_id:
            return None, False
        self._stamp(template, product)
        self.templates[str(product.id)] = template.id
        return template.id, True

    def _stamp(self, template: ProductTemplate, product: GrocyProduct) -> None:
        template.meta_data = {**(template.meta_data or {}), **import_stamp(product.id)}

    async def catalogue_only_async(self, product: GrocyProduct, step: int) -> None:
        """A product with no stock: a product of the catalogue, nothing on a shelf.

        One that is here already — stamped by an earlier run, or the product
        the form would match — is left as it is, and counted as skipped.
        """
        if str(product.id) in self.templates:
            self.skipped += 1
            return

        async def work() -> bool:
            from app.services._product_template_writes import (
                create_product_template_async,
            )

            _, existed = await self._template_of_async(product)
            if existed:
                return False
            created = cast(
                ProductTemplate,
                await create_product_template_async(
                    self.db,
                    self.org_id,
                    product.name,
                    barcode=product.barcodes[0] if product.barcodes else None,
                    description=product.description,
                    meta_data=import_stamp(product.id),
                    uom_id=self._unit_of(product),
                    min_quantity=_min_quantity(product),
                    user_id=self.user.id,
                ),
            )
            self.templates[str(product.id)] = created.id
            return True

        made = await self._attempt_async(step, product, work)
        if made is True:
            self.imported += 1
        elif made is False:
            self.skipped += 1

    def _unit_of(self, product: GrocyProduct) -> UUID | None:
        return self.plan.unit_ids.get(product.unit_id) if product.unit_id else None

    async def batch_async(
        self, product: GrocyProduct, entry: GrocyStockEntry, step: int
    ) -> None:
        """One Grocy batch as one record, through the form's door."""
        if entry.stock_id in self.imported_stock:
            self.skipped += 1
            return

        async def work() -> bool:
            template_id, existed = await self._template_of_async(product)
            whole, part = self._whole_and_part(product, entry.amount)
            if whole > 0:
                await self._record_async(
                    product, entry, template_id, whole, mark_opened=part == 0
                )
                template_id = self.templates.get(str(product.id), template_id)
            if part > 0:
                await self._opened_remainder_async(product, entry, template_id, part)
            return existed

        joined = await self._attempt_async(step, product, work)
        if joined is None:
            return
        self.imported_stock.add(entry.stock_id)
        self.imported += 1
        if joined:
            self.joined_existing += 1

    async def _attempt_async(
        self, step: int, product: GrocyProduct, work: Callable[[], Awaitable[bool]]
    ) -> bool | None:
        """Run one step in a savepoint; a refused step is reported, not fatal.

        ``None`` when the step was refused: its writes are rolled back, and
        a product it minted is forgotten, so the next batch of the same
        product mints it again rather than naming a row that is gone.
        """
        known = dict(self.templates)
        try:
            async with self.db.begin_nested():
                return await work()
        except Exception as exc:  # noqa: BLE001 — a refused step is reported (explain() logs the unforeseen) and the move goes on
            self.templates = known
            self.failed += 1
            self.errors.append(
                {'row': step, 'error': f'{product.name}: {explain(exc, {})}'}
            )
            return None

    def _whole_and_part(
        self, product: GrocyProduct, amount: Decimal
    ) -> tuple[Decimal, Decimal]:
        """The whole units of a batch, and the fraction an opened one has left.

        A unit that holds whole numbers only (a piece) cannot hold 2.5; Grocy
        writes that for two sealed pieces and half of an opened one, so the
        half comes across the way an opened package is kept here.
        """
        if self._unit_of(product) not in self.plan.whole_units:
            return amount, Decimal(0)
        whole = Decimal(int(amount))
        return whole, amount - whole

    async def _record_async(
        self,
        product: GrocyProduct,
        entry: GrocyStockEntry,
        template_id: UUID | None,
        quantity: Decimal,
        *,
        mark_opened: bool,
    ) -> Item:
        item = await create_item_async(
            self.db,
            self._item_in(
                product, entry, template_id, quantity, mark_opened=mark_opened
            ),
            self.user,
            unit_confirmed_over_template=True,
        )
        if template_id is None and item.template_id is not None:
            await self._adopt_async(item.template_id, product)
        if entry.store_id in self.suppliers:
            item.partner_id = self.suppliers[entry.store_id]
            await self.db.flush()
        return item

    async def _opened_remainder_async(
        self,
        product: GrocyProduct,
        entry: GrocyStockEntry,
        template_id: UUID | None,
        part: Decimal,
    ) -> None:
        """What is left of an opened piece: one piece, opened, used down to *part*.

        The same door the "opened" action uses, so the fraction is held the
        way any opened package is — and the part already used is a use, as
        it was in Grocy. The opening keeps Grocy's date.
        """
        from ._open_package import use_partially_async

        piece = await self._record_async(
            product, entry, template_id, Decimal(1), mark_opened=False
        )
        opened = await use_partially_async(self.db, piece, self.user, left=part)
        meta = dict(opened.meta_data or {})
        meta[OPENED_KEY] = {
            **meta.get(OPENED_KEY, {}),
            'at': self._opened_on(entry).isoformat(),
        }
        opened.meta_data = meta
        await self.db.flush()

    def _opened_on(self, entry: GrocyStockEntry) -> date:
        return entry.opened or entry.purchased or self.today

    def _item_in(
        self,
        product: GrocyProduct,
        entry: GrocyStockEntry,
        template_id: UUID | None,
        quantity: Decimal,
        *,
        mark_opened: bool,
    ) -> ItemCreate:
        metadata: dict[str, Any] = import_stamp(entry.stock_id)
        if entry.is_open and mark_opened:
            metadata[OPENED_KEY] = {'at': self._opened_on(entry).isoformat()}
        return ItemCreate(
            name=product.name,
            template_id=template_id,
            location_id=self._location_of(product, entry),
            category_id=self.categories.get(product.group_id)
            if product.group_id
            else None,
            quantity=quantity,
            uom_id=self._unit_of(product),
            # A product that is already here keeps its own code.
            barcode=product.barcodes[0]
            if product.barcodes and template_id is None
            else None,
            expiry_date=entry.best_before,
            purchase_price=_price_held(entry.price),
            added_date=entry.purchased,
            description=entry.note or product.description,
            min_quantity=_min_quantity(product),
            metadata=metadata,
        )

    async def _adopt_async(self, template_id: UUID, product: GrocyProduct) -> None:
        """The product the first batch minted takes Grocy's id and description."""
        template = await self.db.get(ProductTemplate, template_id)
        # A product of the shared catalogue the batch matched is not this
        # organization's to stamp.
        if template is None or template.organization_id != self.org_id:
            return
        self._stamp(template, product)
        if product.description and not template.description:
            template.description = product.description
        await self.db.flush()
        self.templates[str(product.id)] = template_id

    def result(self, total: int, moved: MoveOutcome) -> dict[str, Any]:
        return {
            'total': total,
            'imported': self.imported,
            'joined_existing': self.joined_existing,
            'updated': 0,
            'skipped': self.skipped,
            'failed': self.failed,
            'errors': self.errors[:10],
            'created_locations': self.created_locations,
            'created_categories': self.created_categories,
            'created_suppliers': self.created_suppliers,
            'left_behind': left_behind(
                self.grocy, self.plan.units_as_pieces, self.plan.taken, moved.failed
            ),
            'brought_by_modules': [
                {'module': b.module, 'sentence': b.sentence} for b in moved.brought
            ],
        }


async def import_grocy_file_async(
    db: AsyncSession,
    grocy: GrocyFile,
    user: UserContextDTO,
    on_batch: Callable[[int], Awaitable[None]] | None = None,
    category_matches: dict[str, UUID] | None = None,
) -> dict[str, Any]:
    """File the Grocy database into the organization; the summary of what it did.

    Nothing here commits: the request commits a short file with its answer,
    the background job each batch (``on_batch``, told how many steps are
    done — a product without stock or a batch of stock is one step).
    """
    from app.core.period_guard import check_period_not_closed
    from app.services.analytics._common import org_today_async

    org_id = _org_of(user)
    today = await org_today_async(db, org_id)
    # The move adds stock: a closed period refuses it before anything is
    # written, on the organization's day.
    await check_period_not_closed(db, org_id, today)

    run = _Run(
        db=db,
        user=user,
        org_id=org_id,
        grocy=grocy,
        plan=await plan_grocy_import_async(db, user, grocy, category_matches),
        today=today,
        templates=await imported_product_ids_async(db, org_id),
        imported_stock=await _imported_stock_ids_async(db, org_id),
    )
    await run.found_named_rows_async()

    stock = _stock_of(grocy)
    step = reported = 0
    for product in _active_products(grocy):
        entries = stock.get(product.id, [])
        if not entries:
            step += 1
            await run.catalogue_only_async(product, step)
        for entry in entries:
            step += 1
            await run.batch_async(product, entry, step)
        if on_batch is not None and step - reported >= _BATCH:
            await on_batch(step)
            reported = step
    moved = await bring_async(
        SOURCE,
        db,
        user,
        grocy,
        MoveMatches(products=dict(run.templates), units=dict(run.plan.unit_ids)),
        run.plan.enabled_modules,
    )
    return run.result(step, moved)
