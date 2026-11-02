"""Integration tests for the recipe model, batch math and invariants.

Test contract:
  - Partial unique index: two is_default=True per (org, template) → IntegrityError
  - "Min 1 default": delete default → oldest remaining becomes default
  - explode_for_order after migration = identical to v1 (yield=1)
  - Batch math: recipe yield=12, planned=24 → 2 batches
  - Multi-level: parent → sub-assembly → leaves
  - Cycles + _MAX_DEPTH on new model
  - Line-parent invariant: parent_template_id == recipe.output_template_id
  - Line-parent guard: mismatched (recipe, parent) pair → ValueError
  - move_line: recipe_id re-pointed to the new parent's default recipe
  - Unique lines: (recipe_id, child_template_id) — duplicate blocked
"""

from __future__ import annotations

import asyncio
from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.models.organization import Organization
from app.models.product_template import ProductTemplate
from app.modules.maker.bom_service import _MAX_DEPTH
from app.modules.maker.models import BoMLine, MakerRecipe

pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_template(db: Session, org: Organization, name: str = 'T') -> ProductTemplate:
    t = ProductTemplate(organization_id=org.id, name=name)
    db.add(t)
    db.commit()
    db.refresh(t)
    return t


def _make_recipe(
    db: Session,
    org: Organization,
    template: ProductTemplate,
    *,
    name: str = 'Recipe',
    is_default: bool = False,
    batch_yield_qty: Decimal = Decimal('1'),
) -> MakerRecipe:
    r = MakerRecipe(
        organization_id=org.id,
        output_template_id=template.id,
        name=name,
        batch_yield_qty=batch_yield_qty,
        is_default=is_default,
    )
    db.add(r)
    db.commit()
    db.refresh(r)
    return r


# ---------------------------------------------------------------------------
# Partial unique index — at most 1 default per (org, template)
# ---------------------------------------------------------------------------


class TestPartialUniqueIndex:
    """The partial unique index enforces "max 1 default recipe per template"."""

    def test_two_defaults_same_template_raises_integrity_error(
        self,
        db_session: Session,
        mk_org: Organization,
    ) -> None:
        template = _make_template(db_session, mk_org, 'Widget')
        _make_recipe(db_session, mk_org, template, name='A', is_default=True)

        with pytest.raises(IntegrityError):
            _make_recipe(db_session, mk_org, template, name='B', is_default=True)
        db_session.rollback()

    def test_two_defaults_different_templates_ok(
        self,
        db_session: Session,
        mk_org: Organization,
    ) -> None:
        t1 = _make_template(db_session, mk_org, 'Widget A')
        t2 = _make_template(db_session, mk_org, 'Widget B')
        _make_recipe(db_session, mk_org, t1, name='R1', is_default=True)
        _make_recipe(db_session, mk_org, t2, name='R2', is_default=True)

    def test_two_non_defaults_same_template_ok(
        self,
        db_session: Session,
        mk_org: Organization,
    ) -> None:
        template = _make_template(db_session, mk_org, 'Widget')
        _make_recipe(db_session, mk_org, template, name='A', is_default=False)
        _make_recipe(db_session, mk_org, template, name='B', is_default=False)


# ---------------------------------------------------------------------------
# Unique lines — (recipe_id, child_template_id)
# ---------------------------------------------------------------------------


class TestUniqueLines:
    """(recipe_id, child_template_id) must be unique."""

    def test_duplicate_line_same_recipe_raises(
        self,
        db_session: Session,
        mk_org: Organization,
    ) -> None:
        parent = _make_template(db_session, mk_org, 'Parent')
        child = _make_template(db_session, mk_org, 'Child')
        recipe = _make_recipe(db_session, mk_org, parent, is_default=True)

        line1 = BoMLine(
            organization_id=mk_org.id,
            recipe_id=recipe.id,
            parent_template_id=parent.id,
            child_template_id=child.id,
            qty_per_batch=Decimal('1'),
            unit='kg',
        )
        db_session.add(line1)
        db_session.commit()

        line2 = BoMLine(
            organization_id=mk_org.id,
            recipe_id=recipe.id,
            parent_template_id=parent.id,
            child_template_id=child.id,
            qty_per_batch=Decimal('2'),
            unit='kg',
        )
        db_session.add(line2)
        with pytest.raises(IntegrityError):
            db_session.commit()
        db_session.rollback()

    def test_same_child_different_recipes_ok(
        self,
        db_session: Session,
        mk_org: Organization,
    ) -> None:
        parent = _make_template(db_session, mk_org, 'Parent')
        child = _make_template(db_session, mk_org, 'Child')

        r1 = _make_recipe(db_session, mk_org, parent, name='R1', is_default=True)
        r2 = _make_recipe(db_session, mk_org, parent, name='R2', is_default=False)

        for recipe in (r1, r2):
            line = BoMLine(
                organization_id=mk_org.id,
                recipe_id=recipe.id,
                parent_template_id=parent.id,
                child_template_id=child.id,
                qty_per_batch=Decimal('1'),
                unit='kg',
            )
            db_session.add(line)
        db_session.commit()


# ---------------------------------------------------------------------------
# "Min 1 default" rule — reassignment on delete
# ---------------------------------------------------------------------------


class TestRecipeDefaultReassignment:
    """Deleting the default recipe promotes the oldest remaining to default."""

    def test_delete_default_promotes_oldest(
        self,
        db_session: Session,
        mk_org: Organization,
        async_engine_fixture: Any,
    ) -> None:
        from sqlalchemy.ext.asyncio import async_sessionmaker

        from app.modules.maker import recipe_service

        template = _make_template(db_session, mk_org, 'Product')
        r1 = _make_recipe(db_session, mk_org, template, name='First', is_default=True)
        r2 = _make_recipe(db_session, mk_org, template, name='Second', is_default=False)

        assert r1.is_default is True
        assert r2.is_default is False

        # Call async delete_recipe
        maker = async_sessionmaker(bind=async_engine_fixture, expire_on_commit=False)

        async def _delete() -> None:
            async with maker() as session:
                await recipe_service.delete_recipe(session, mk_org.id, r1.id)
                await session.commit()

        asyncio.run(_delete())

        # Refresh r2 from DB
        db_session.expire_all()
        r2_fresh = db_session.get(MakerRecipe, r2.id)
        assert r2_fresh is not None
        assert r2_fresh.is_default is True

    def test_first_recipe_created_is_default(
        self,
        client: Any,
        mk_auth_headers: dict[str, str],
        db_session: Session,
        mk_org: Organization,
    ) -> None:
        """The door production uses elects the default too: the first recipe
        a POST creates answers True.

        The service-level twins live in TestOneLockedDefaultImplementation —
        this one is the API door, so a route change cannot silently stop
        electing a default the service still would."""
        template = _make_template(db_session, mk_org, 'Product')

        created = client.post(
            '/api/v1/maker/recipes',
            headers=mk_auth_headers,
            json={
                'output_template_id': str(template.id),
                'name': 'First via POST',
            },
        )
        assert created.status_code == 201, created.text

        db_recipe = db_session.get(MakerRecipe, UUID(created.json()['id']))
        assert db_recipe is not None
        assert db_recipe.is_default is True


# ---------------------------------------------------------------------------
# Batch math — explode with yield > 1
#
# These cases drive the production entry points (``explode_with_uom`` behind
# ``explode``) against real default recipes in the database — the same path
# availability, consumption and the cost rollup read. They used to exercise a
# pure-function copy of the algorithm that no production code called; the copy
# ignored recipe identity and line UoM, so a drift there was invisible to this
# suite. A test that passes on a copy says nothing about the code that ships.
# ---------------------------------------------------------------------------


def _recipe_with_lines(
    db: Session,
    org: Organization,
    template: ProductTemplate,
    lines: list[
        tuple[ProductTemplate, Decimal, str, Decimal]
        | tuple[ProductTemplate, Decimal, str, Decimal, UUID | None]
    ],
    *,
    batch_yield_qty: Decimal = Decimal('1'),
) -> MakerRecipe:
    """A default recipe for *template* with (child, qty_per_batch, unit, loss)
    lines; a fifth element names the line's uom_id."""
    r = _make_recipe(
        db, org, template, is_default=True, batch_yield_qty=batch_yield_qty
    )
    for line in lines:
        child, qty, unit, loss, *rest = line
        uom_id = rest[0] if rest else None
        db.add(
            BoMLine(
                organization_id=org.id,
                recipe_id=r.id,
                parent_template_id=template.id,
                child_template_id=child.id,
                qty_per_batch=qty,
                unit=unit,
                uom_id=uom_id,
                yield_loss_pct=loss,
            )
        )
    db.commit()
    db.refresh(r)
    return r


def _explode(
    async_engine_fixture: Any,
    org: Organization,
    template: ProductTemplate,
    qty: Decimal,
    *,
    keep_uom: bool = False,
) -> list[tuple[UUID, Decimal, str]] | list[tuple[UUID, Decimal, str, UUID | None]]:
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app.modules.maker import bom_service

    maker = async_sessionmaker(bind=async_engine_fixture, expire_on_commit=False)

    async def _run() -> list[tuple[UUID, Decimal, str, UUID | None]]:
        async with maker() as session:
            return await bom_service.explode_with_uom(session, org.id, template.id, qty)

    flat = asyncio.run(_run())
    if keep_uom:
        return flat
    return [(child_id, child_qty, unit) for child_id, child_qty, unit, _uom in flat]


class TestExplodeBatchMath:
    """Batch math: batches = planned / batch_yield_qty, on the shipped path."""

    def test_no_recipe_explodes_to_nothing(
        self, async_engine_fixture: Any, mk_org: Organization, db_session: Session
    ) -> None:
        template = _make_template(db_session, mk_org, 'Orphan product')
        assert _explode(async_engine_fixture, mk_org, template, Decimal('3')) == []

    def test_yield_equals_one_matches_legacy(
        self, async_engine_fixture: Any, mk_org: Organization, db_session: Session
    ) -> None:
        """Migrated recipes (yield=1) give identical results to v1."""
        parent = _make_template(db_session, mk_org, 'Bread')
        child = _make_template(db_session, mk_org, 'Flour')
        _recipe_with_lines(
            db_session, mk_org, parent, [(child, Decimal('2'), 'kg', Decimal('0'))]
        )

        out = _explode(async_engine_fixture, mk_org, parent, Decimal('3'))

        assert out == [(child.id, Decimal('6'), 'kg')]

    def test_explode_carries_the_line_unit_id(
        self, async_engine_fixture: Any, mk_org: Organization, db_session: Session
    ) -> None:
        """The property the production path was chosen for: explode keeps the
        uom_id each line was written in — the fourth element the shared clean
        copy dropped, the thing that made unit-awareness the deciding
        argument."""
        from app.models.uom import Uom, UomCategory

        parent = _make_template(db_session, mk_org, 'Sauce')
        child = _make_template(db_session, mk_org, 'Salt')
        category = UomCategory(organization_id=mk_org.id, name='Mass')
        db_session.add(category)
        db_session.flush()
        gram = Uom(
            organization_id=mk_org.id,
            name='Gram',
            symbol='g',
            category_id=category.id,
            factor=Decimal('0.001'),
        )
        db_session.add(gram)
        db_session.flush()
        _recipe_with_lines(
            db_session,
            mk_org,
            parent,
            [(child, Decimal('500'), 'g', Decimal('0'), gram.id)],
        )

        out = _explode(
            async_engine_fixture, mk_org, parent, Decimal('3'), keep_uom=True
        )

        assert out == [(child.id, Decimal('1500'), 'g', gram.id)]

    def test_batch_yield_12_planned_24_two_batches(
        self, async_engine_fixture: Any, mk_org: Organization, db_session: Session
    ) -> None:
        """Recipe yields 12 per batch; order 24 → 2 batches → 2× consumption."""
        parent = _make_template(db_session, mk_org, 'Stew')
        child = _make_template(db_session, mk_org, 'Carrot')
        _recipe_with_lines(
            db_session,
            mk_org,
            parent,
            [(child, Decimal('5'), 'kg', Decimal('0'))],
            batch_yield_qty=Decimal('12'),
        )

        out = _explode(async_engine_fixture, mk_org, parent, Decimal('24'))

        # batches = 24 / 12 = 2; line_qty = 2 * 5 = 10
        assert out == [(child.id, Decimal('10'), 'kg')]

    def test_batch_yield_fractional_batches(
        self, async_engine_fixture: Any, mk_org: Organization, db_session: Session
    ) -> None:
        """Fractional batches are OK (e.g. 1.5 batches)."""
        parent = _make_template(db_session, mk_org, 'Dough')
        child = _make_template(db_session, mk_org, 'Water')
        _recipe_with_lines(
            db_session,
            mk_org,
            parent,
            [(child, Decimal('2'), 'kg', Decimal('0'))],
            batch_yield_qty=Decimal('10'),
        )

        out = _explode(async_engine_fixture, mk_org, parent, Decimal('15'))

        # batches = 15 / 10 = 1.5; line_qty = 1.5 * 2 = 3
        assert out == [(child.id, Decimal('3'), 'kg')]

    def test_batch_yield_with_yield_loss(
        self, async_engine_fixture: Any, mk_org: Organization, db_session: Session
    ) -> None:
        """Yield loss applies on top of batch math."""
        parent = _make_template(db_session, mk_org, 'Roast')
        child = _make_template(db_session, mk_org, 'Beef')
        _recipe_with_lines(
            db_session,
            mk_org,
            parent,
            [(child, Decimal('10'), 'kg', Decimal('20'))],
            batch_yield_qty=Decimal('5'),
        )

        out = _explode(async_engine_fixture, mk_org, parent, Decimal('10'))

        # batches = 10 / 5 = 2; line_qty = 2 * 10 * 1.20 = 24
        assert out == [(child.id, Decimal('24'), 'kg')]


class TestExplodeMultiLevel:
    """Multi-level explode: parent → sub-assembly → leaves, real recursion."""

    def test_sub_assembly_batch_math(
        self, async_engine_fixture: Any, mk_org: Organization, db_session: Session
    ) -> None:
        """Parent yield=4; parent→sub(2 per batch); sub yield=6; sub→leaf(3 per batch).

        Order 12: parent_batches = 12/4 = 3; sub_qty = 3*2 = 6;
        sub_batches = 6/6 = 1; leaf_qty = 1*3 = 3.
        """
        p = _make_template(db_session, mk_org, 'Cake')
        sub = _make_template(db_session, mk_org, 'Cream')
        leaf = _make_template(db_session, mk_org, 'Sugar')
        _recipe_with_lines(
            db_session,
            mk_org,
            p,
            [(sub, Decimal('2'), 'kg', Decimal('0'))],
            batch_yield_qty=Decimal('4'),
        )
        _recipe_with_lines(
            db_session,
            mk_org,
            sub,
            [(leaf, Decimal('3'), 'kg', Decimal('0'))],
            batch_yield_qty=Decimal('6'),
        )

        out = _explode(async_engine_fixture, mk_org, p, Decimal('12'))

        assert out == [(leaf.id, Decimal('3'), 'kg')]

    def test_multi_level_siblings(
        self, async_engine_fixture: Any, mk_org: Organization, db_session: Session
    ) -> None:
        """Parent has two children; both leaves."""
        p = _make_template(db_session, mk_org, 'Basket')
        c1 = _make_template(db_session, mk_org, 'Apple')
        c2 = _make_template(db_session, mk_org, 'Pear')
        _recipe_with_lines(
            db_session,
            mk_org,
            p,
            [
                (c1, Decimal('1'), 'kg', Decimal('0')),
                (c2, Decimal('0.5'), 'kg', Decimal('0')),
            ],
        )

        out = _explode(async_engine_fixture, mk_org, p, Decimal('4'))

        assert sorted(out) == sorted(
            [
                (c1.id, Decimal('4'), 'kg'),
                (c2.id, Decimal('2'), 'kg'),
            ]
        )

    def test_multi_level_siblings_under_child(
        self, async_engine_fixture: Any, mk_org: Organization, db_session: Session
    ) -> None:
        """A→B (2 per batch); B has children C and D — B dissolves into them."""
        a = _make_template(db_session, mk_org, 'Box')
        b = _make_template(db_session, mk_org, 'Pallet')
        c = _make_template(db_session, mk_org, 'Bolt')
        d = _make_template(db_session, mk_org, 'Nut')
        _recipe_with_lines(
            db_session, mk_org, a, [(b, Decimal('2'), 'kg', Decimal('0'))]
        )
        _recipe_with_lines(
            db_session,
            mk_org,
            b,
            [
                (c, Decimal('1'), 'kg', Decimal('0')),
                (d, Decimal('1'), 'kg', Decimal('0')),
            ],
        )

        out = _explode(async_engine_fixture, mk_org, a, Decimal('3'))

        assert sorted(out) == sorted(
            [
                (c.id, Decimal('6'), 'kg'),
                (d.id, Decimal('6'), 'kg'),
            ]
        )

    def test_sub_assembly_without_lines_is_a_leaf(
        self, async_engine_fixture: Any, mk_org: Organization, db_session: Session
    ) -> None:
        """A sub-assembly whose recipe lists no ingredients counts as a leaf."""
        a = _make_template(db_session, mk_org, 'Kit')
        b = _make_template(db_session, mk_org, 'Empty sub')
        _recipe_with_lines(
            db_session, mk_org, a, [(b, Decimal('2'), 'kg', Decimal('0'))]
        )
        _recipe_with_lines(db_session, mk_org, b, [])

        out = _explode(async_engine_fixture, mk_org, a, Decimal('3'))

        assert out == [(b.id, Decimal('6'), 'kg')]


class TestCycleDetection:
    """Cycles and depth limits raise on the shipped recursion."""

    def test_cycle_raises(
        self, async_engine_fixture: Any, mk_org: Organization, db_session: Session
    ) -> None:
        a = _make_template(db_session, mk_org, 'Pancake A')
        b = _make_template(db_session, mk_org, 'Pancake B')
        _recipe_with_lines(
            db_session, mk_org, a, [(b, Decimal('1'), 'kg', Decimal('0'))]
        )
        _recipe_with_lines(
            db_session, mk_org, b, [(a, Decimal('1'), 'kg', Decimal('0'))]
        )

        with pytest.raises(ValueError, match='cycle'):
            _explode(async_engine_fixture, mk_org, a, Decimal('1'))

    def test_depth_limit_raises(
        self, async_engine_fixture: Any, mk_org: Organization, db_session: Session
    ) -> None:
        """A chain deeper than _MAX_DEPTH recipes refuses to explode.

        The top recipe counts as depth 0 and the guard fires on
        ``depth > _MAX_DEPTH``, so the chain needs _MAX_DEPTH + 2 recipes.
        """
        nodes = [
            _make_template(db_session, mk_org, f'Level {i}')
            for i in range(_MAX_DEPTH + 3)
        ]
        for i in range(_MAX_DEPTH + 2):
            _recipe_with_lines(
                db_session,
                mk_org,
                nodes[i],
                [(nodes[i + 1], Decimal('1'), 'kg', Decimal('0'))],
            )

        with pytest.raises(ValueError, match=f'nested more than {_MAX_DEPTH} levels'):
            _explode(async_engine_fixture, mk_org, nodes[0], Decimal('1'))


# ---------------------------------------------------------------------------
# Line-parent invariant — parent_template_id == recipe.output_template_id
# ---------------------------------------------------------------------------


class TestDenormalizationInvariant:
    """parent_template_id must equal recipe.output_template_id."""

    def test_add_line_produces_consistent_parent(
        self,
        db_session: Session,
        mk_org: Organization,
        async_engine_fixture: Any,
    ) -> None:
        """A line added to a recipe has parent == recipe.output_template."""
        from sqlalchemy.ext.asyncio import async_sessionmaker

        from app.modules.maker import bom_service, recipe_service
        from app.modules.maker._schemas_recipes import BoMLineCreateForRecipe

        parent = _make_template(db_session, mk_org, 'Parent')
        child = _make_template(db_session, mk_org, 'Child')

        maker = async_sessionmaker(bind=async_engine_fixture, expire_on_commit=False)

        async def _add() -> tuple[UUID, UUID]:
            async with maker() as session:
                recipe = await bom_service.get_or_create_default_recipe(
                    session, mk_org.id, parent.id
                )
                await session.commit()
                line = await recipe_service.add_bom_line(
                    session,
                    mk_org.id,
                    recipe.id,
                    BoMLineCreateForRecipe(
                        child_template_id=child.id,
                        qty_per_batch=Decimal('1'),
                        unit='kg',
                    ),
                )
                await session.commit()
                return line.id, line.recipe_id

        line_id, recipe_id = asyncio.run(_add())

        db_line = db_session.get(BoMLine, line_id)
        db_recipe = db_session.get(MakerRecipe, recipe_id)
        assert db_line is not None
        assert db_recipe is not None
        assert db_line.parent_template_id == db_recipe.output_template_id

    def test_guard_rejects_mismatched_parent_template(
        self,
        db_session: Session,
        mk_org: Organization,
    ) -> None:
        """The app-level guard raises ValueError for a mismatched pair.

        ``add_line`` derives the recipe from the parent, so the mismatch is
        impossible through its public signature — the guard is the shared
        choke point and is exercised directly with mismatched ids.
        """
        from app.modules.maker import bom_service

        parent = _make_template(db_session, mk_org, 'Parent')
        other = _make_template(db_session, mk_org, 'Other')
        recipe = _make_recipe(db_session, mk_org, parent, is_default=True)

        with pytest.raises(ValueError, match='does not match'):
            bom_service._validate_line_parent(recipe, other.id)


# ---------------------------------------------------------------------------
# Line-parent invariant — move_line re-points recipe_id to the new parent's recipe
# ---------------------------------------------------------------------------


class TestMoveLineReparentsRecipe:
    """``move_line`` must re-point ``recipe_id`` together with ``parent_template_id``.

    Otherwise the moved line keeps exploding under the OLD recipe (silent
    line-parent invariant violation).
    """

    def test_move_repoints_recipe_and_explodes_under_new_parent(
        self,
        db_session: Session,
        mk_org: Organization,
        async_engine_fixture: Any,
    ) -> None:
        """Moving A→C to B: line joins B's default recipe; explode follows."""
        from sqlalchemy.ext.asyncio import async_sessionmaker

        from app.modules.maker import bom_service, bom_tree

        parent_a = _make_template(db_session, mk_org, 'Parent A')
        parent_b = _make_template(db_session, mk_org, 'Parent B')
        child = _make_template(db_session, mk_org, 'Child')

        recipe_a = _make_recipe(
            db_session, mk_org, parent_a, name='RA', is_default=True
        )
        recipe_b = _make_recipe(
            db_session, mk_org, parent_b, name='RB', is_default=True
        )

        line = BoMLine(
            organization_id=mk_org.id,
            recipe_id=recipe_a.id,
            parent_template_id=parent_a.id,
            child_template_id=child.id,
            qty_per_batch=Decimal('2'),
            unit='kg',
        )
        db_session.add(line)
        db_session.commit()
        db_session.refresh(line)

        maker = async_sessionmaker(bind=async_engine_fixture, expire_on_commit=False)

        async def _move() -> None:
            async with maker() as session:
                await bom_tree.move_line(session, mk_org.id, line.id, parent_b.id)
                await session.commit()

        asyncio.run(_move())

        db_session.expire_all()
        reloaded = db_session.get(BoMLine, line.id)
        assert reloaded is not None
        assert reloaded.recipe_id == recipe_b.id
        assert reloaded.parent_template_id == parent_b.id
        # The line-parent invariant holds after the move.
        new_recipe = db_session.get(MakerRecipe, recipe_b.id)
        assert new_recipe is not None
        assert reloaded.parent_template_id == new_recipe.output_template_id

        async def _explode() -> tuple[
            list[tuple[UUID, Decimal, str]], list[tuple[UUID, Decimal, str]]
        ]:
            async with maker() as session:
                out_b = await bom_service.explode(
                    session, mk_org.id, parent_b.id, Decimal('1')
                )
                out_a = await bom_service.explode(
                    session, mk_org.id, parent_a.id, Decimal('1')
                )
                return out_b, out_a

        out_b, out_a = asyncio.run(_explode())
        # New parent's recipe now includes the moved child (qty 1 batch × 2).
        assert out_b == [(child.id, Decimal('2'), 'kg')]
        # Old recipe has no lines left — explode is empty.
        assert out_a == []

    def test_move_auto_creates_default_recipe_for_new_parent(
        self,
        db_session: Session,
        mk_org: Organization,
        async_engine_fixture: Any,
    ) -> None:
        """Moving to a parent without any recipe auto-creates a yield=1 default."""
        from sqlalchemy.ext.asyncio import async_sessionmaker

        from app.modules.maker import bom_tree

        parent_a = _make_template(db_session, mk_org, 'Parent A')
        parent_b = _make_template(db_session, mk_org, 'Parent B')
        child = _make_template(db_session, mk_org, 'Child')

        recipe_a = _make_recipe(
            db_session, mk_org, parent_a, name='RA', is_default=True
        )
        line = BoMLine(
            organization_id=mk_org.id,
            recipe_id=recipe_a.id,
            parent_template_id=parent_a.id,
            child_template_id=child.id,
            qty_per_batch=Decimal('1'),
            unit='kg',
        )
        db_session.add(line)
        db_session.commit()
        db_session.refresh(line)

        maker = async_sessionmaker(bind=async_engine_fixture, expire_on_commit=False)

        async def _move() -> UUID:
            async with maker() as session:
                moved = await bom_tree.move_line(
                    session, mk_org.id, line.id, parent_b.id
                )
                await session.commit()
                return moved.recipe_id

        new_recipe_id = asyncio.run(_move())

        db_session.expire_all()
        new_recipe = db_session.get(MakerRecipe, new_recipe_id)
        assert new_recipe is not None
        assert new_recipe.output_template_id == parent_b.id
        assert new_recipe.is_default is True
        assert new_recipe.batch_yield_qty == Decimal('1')

        reloaded = db_session.get(BoMLine, line.id)
        assert reloaded is not None
        assert reloaded.recipe_id == new_recipe_id
        assert reloaded.parent_template_id == parent_b.id

    def test_move_to_parent_with_same_child_in_default_recipe_raises(
        self,
        db_session: Session,
        mk_org: Organization,
        async_engine_fixture: Any,
    ) -> None:
        """Moving A→C to B where B's default recipe already has C → ValueError."""
        from sqlalchemy.ext.asyncio import async_sessionmaker

        from app.modules.maker import bom_tree

        parent_a = _make_template(db_session, mk_org, 'Parent A')
        parent_b = _make_template(db_session, mk_org, 'Parent B')
        child = _make_template(db_session, mk_org, 'Child')

        recipe_a = _make_recipe(
            db_session, mk_org, parent_a, name='RA', is_default=True
        )
        recipe_b = _make_recipe(
            db_session, mk_org, parent_b, name='RB', is_default=True
        )

        def _line(recipe: MakerRecipe, parent: ProductTemplate) -> BoMLine:
            obj = BoMLine(
                organization_id=mk_org.id,
                recipe_id=recipe.id,
                parent_template_id=parent.id,
                child_template_id=child.id,
                qty_per_batch=Decimal('1'),
                unit='kg',
            )
            db_session.add(obj)
            db_session.commit()
            db_session.refresh(obj)
            return obj

        line_ac = _line(recipe_a, parent_a)
        _line(recipe_b, parent_b)

        maker = async_sessionmaker(bind=async_engine_fixture, expire_on_commit=False)

        async def _move() -> None:
            async with maker() as session:
                with pytest.raises(ValueError, match='already exists'):
                    await bom_tree.move_line(
                        session, mk_org.id, line_ac.id, parent_b.id
                    )

        asyncio.run(_move())

        # The line is untouched — still under the old parent/recipe.
        db_session.expire_all()
        reloaded = db_session.get(BoMLine, line_ac.id)
        assert reloaded is not None
        assert reloaded.recipe_id == recipe_a.id
        assert reloaded.parent_template_id == parent_a.id


class TestOneLockedDefaultImplementation:
    """Every "first recipe → default" path rides the same lock.

    The legacy adapter that carried its own unlocked count-then-insert is
    gone (its tests ride recipe_service.create_recipe now, the path POST
    /recipes uses), and get_or_create_default_recipe holds the same lock
    around its own guaranteed-default insert.

    Measured with the lock removed at both call sites: the two tests that
    run the decision in parallel go red (IntegrityError off
    ``uq_recipe_org_template_name`` and ``uq_recipe_default_per_template``
    respectively); the four sequential tests pass with and without the
    lock — they measure the sequence, not the race, and stay as the
    behaviour the race must land in.
    """

    def test_first_recipe_is_default(
        self,
        db_session: Session,
        mk_org: Organization,
        async_engine_fixture: Any,
    ) -> None:
        """The service door's baseline: one create answers True once.

        The API door has the same fact pinned in
        TestRecipeDefaultReassignment — this one starts the lock story the
        concurrency tests below carry on."""
        from sqlalchemy.ext.asyncio import async_sessionmaker

        from app.modules.maker import recipe_service
        from app.modules.maker._schemas_recipes import RecipeCreate

        template = _make_template(db_session, mk_org, 'First product')

        maker = async_sessionmaker(bind=async_engine_fixture, expire_on_commit=False)

        async def _create() -> UUID:
            async with maker() as session:
                r = await recipe_service.create_recipe(
                    session,
                    mk_org.id,
                    RecipeCreate(output_template_id=template.id, name='First create'),
                )
                await session.commit()
                return r.id

        recipe_id = asyncio.run(_create())
        db_recipe = db_session.get(MakerRecipe, recipe_id)
        assert db_recipe is not None
        assert db_recipe.is_default is True

    def test_second_recipe_is_not_default(
        self,
        db_session: Session,
        mk_org: Organization,
        async_engine_fixture: Any,
    ) -> None:
        """Second create for the same template does not steal the default:
        the count-then-insert behind create_recipe answers True once, and
        every later create claims False."""
        from sqlalchemy.ext.asyncio import async_sessionmaker

        from app.modules.maker import recipe_service
        from app.modules.maker._schemas_recipes import RecipeCreate

        template = _make_template(db_session, mk_org, 'Shared product')

        maker = async_sessionmaker(bind=async_engine_fixture, expire_on_commit=False)

        async def _create_both() -> tuple[UUID, UUID]:
            async with maker() as session:
                first = await recipe_service.create_recipe(
                    session,
                    mk_org.id,
                    RecipeCreate(output_template_id=template.id, name='First'),
                )
                second = await recipe_service.create_recipe(
                    session,
                    mk_org.id,
                    RecipeCreate(output_template_id=template.id, name='Second'),
                )
                await session.commit()
                return first.id, second.id

        first_id, second_id = asyncio.run(_create_both())

        first = db_session.get(MakerRecipe, first_id)
        second = db_session.get(MakerRecipe, second_id)
        assert first is not None and second is not None
        assert first.is_default is True
        assert second.is_default is False

    def test_get_or_create_returns_the_standing_default_without_inserting(
        self,
        db_session: Session,
        mk_org: Organization,
        async_engine_fixture: Any,
    ) -> None:
        from sqlalchemy import func, select
        from sqlalchemy.ext.asyncio import async_sessionmaker

        from app.modules.maker import bom_service

        template = _make_template(db_session, mk_org, 'Looked-up product')
        first = MakerRecipe(
            organization_id=mk_org.id,
            output_template_id=template.id,
            name='Standing default',
            batch_yield_qty=Decimal('1'),
            is_default=True,
        )
        db_session.add(first)
        db_session.commit()

        maker = async_sessionmaker(bind=async_engine_fixture, expire_on_commit=False)

        async def _get() -> UUID:
            async with maker() as session:
                recipe = await bom_service.get_or_create_default_recipe(
                    session, mk_org.id, template.id
                )
                await session.commit()
                return recipe.id

        found_id = asyncio.run(_get())

        assert found_id == first.id
        count = db_session.scalar(
            select(func.count(MakerRecipe.id)).where(
                MakerRecipe.output_template_id == template.id
            )
        )
        assert count == 1

    def test_get_or_create_fills_a_defaultless_template(
        self,
        db_session: Session,
        mk_org: Organization,
        async_engine_fixture: Any,
    ) -> None:
        """Recipes exist but none is default: the insert becomes the default
        the template is missing — the guarantee the function's name makes.
        (The partial unique index only covers is_default rows, so without a
        standing default this insert cannot collide on it.)"""
        from sqlalchemy.ext.asyncio import async_sessionmaker

        from app.modules.maker import bom_service

        template = _make_template(db_session, mk_org, 'Defaultless product')
        plain = MakerRecipe(
            organization_id=mk_org.id,
            output_template_id=template.id,
            name='Plain non-default',
            batch_yield_qty=Decimal('1'),
            is_default=False,
        )
        db_session.add(plain)
        db_session.commit()

        maker = async_sessionmaker(bind=async_engine_fixture, expire_on_commit=False)

        async def _get() -> UUID:
            async with maker() as session:
                recipe = await bom_service.get_or_create_default_recipe(
                    session, mk_org.id, template.id
                )
                await session.commit()
                return recipe.id

        created_id = asyncio.run(_get())

        created = db_session.get(MakerRecipe, created_id)
        assert created is not None
        assert created.id != plain.id
        assert created.is_default is True

    @pytest.mark.asyncio
    async def test_concurrent_get_or_create_inserts_one_default_row(
        self,
        real_async_db_session: AsyncSession,
    ) -> None:
        """Two parallel get_or_create calls on a recipe-less template race
        the find-then-insert: the lock serializes them, so both return the
        same id and exactly one row is written. Without the lock both
        inserts carry the template's name and one dies on
        ``uq_recipe_org_template_name``."""
        from sqlalchemy import func, select

        from app.modules.maker import bom_service

        org = Organization(name='Maker GetOrCreate Race Org', enabled_modules=['maker'])
        template = ProductTemplate(organization_id=org.id, name='Race product')
        real_async_db_session.add_all([org, template])
        await real_async_db_session.commit()
        org_id, template_id = org.id, template.id

        engine = real_async_db_session.bind  # the AsyncEngine the fixture uses
        session_a = AsyncSession(bind=engine)
        session_b = AsyncSession(bind=engine)
        try:

            async def _get_or_create(session: AsyncSession) -> UUID:
                recipe = await bom_service.get_or_create_default_recipe(
                    session, org_id, template_id
                )
                recipe_id = recipe.id  # read before commit expires the instance
                # The advisory lock is transaction-scoped: committing is what
                # releases it, exactly like a real request ending.
                await session.commit()
                return recipe_id

            id_a, id_b = await asyncio.gather(
                _get_or_create(session_a), _get_or_create(session_b)
            )
        finally:
            await session_a.close()
            await session_b.close()

        # Both callers ended up with the same single default row.
        assert id_a == id_b
        rows = (
            (
                await real_async_db_session.execute(
                    select(MakerRecipe).where(
                        MakerRecipe.output_template_id == template_id
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(rows) == 1
        assert rows[0].id == id_a
        assert rows[0].is_default is True
        total = await real_async_db_session.scalar(
            select(func.count(MakerRecipe.id)).where(
                MakerRecipe.organization_id == org_id
            )
        )
        assert total == 1

    @pytest.mark.asyncio
    async def test_concurrent_create_recipes_elect_exactly_one_default(
        self,
        real_async_db_session: AsyncSession,
    ) -> None:
        """Two parallel create_recipe calls with different names: under the
        shared lock the count-then-insert answers one True and one False
        with zero exceptions. Without the lock both count zero and both
        claim default, so one dies on ``uq_recipe_default_per_template``."""
        from sqlalchemy import select

        from app.modules.maker import recipe_service
        from app.modules.maker._schemas_recipes import RecipeCreate

        org = Organization(name='Maker Create Race Org', enabled_modules=['maker'])
        template = ProductTemplate(organization_id=org.id, name='Race product too')
        real_async_db_session.add_all([org, template])
        await real_async_db_session.commit()
        org_id, template_id = org.id, template.id

        engine = real_async_db_session.bind  # the AsyncEngine the fixture uses
        session_a = AsyncSession(bind=engine)
        session_b = AsyncSession(bind=engine)
        try:

            async def _create(session: AsyncSession, name: str) -> bool:
                recipe = await recipe_service.create_recipe(
                    session,
                    org_id,
                    RecipeCreate(output_template_id=template_id, name=name),
                )
                is_default = recipe.is_default  # read before commit expires it
                # The advisory lock is transaction-scoped: committing is what
                # releases it, exactly like a real request ending.
                await session.commit()
                return is_default

            default_a, default_b = await asyncio.gather(
                _create(session_a, 'First racer'),
                _create(session_b, 'Second racer'),
            )
        finally:
            await session_a.close()
            await session_b.close()

        # gather raising would already mean a constraint died uncaught;
        # exactly one of the two parallel firsts may claim default.
        assert sorted([default_a, default_b]) == [False, True]
        rows = (
            (
                await real_async_db_session.execute(
                    select(MakerRecipe).where(
                        MakerRecipe.output_template_id == template_id
                    )
                )
            )
            .scalars()
            .all()
        )
        assert {row.name for row in rows} == {'First racer', 'Second racer'}
        assert sum(1 for row in rows if row.is_default) == 1

    @pytest.mark.asyncio
    async def test_concurrent_default_changes_elect_exactly_one_default(
        self,
        real_async_db_session: AsyncSession,
    ) -> None:
        """Two parallel default flips on one template end with one default.

        The creating paths decide "first recipe becomes default" under the
        shared advisory lock; changing the default breaks the same invariant
        the index polices, so the change path owes the same lock. Two
        unlocked clear-then-set turns interleave into two defaults — the
        partial unique index refuses one with an uncaught IntegrityError —
        or, on the other timing, into none."""
        from sqlalchemy import select

        from app.modules.maker import recipe_service
        from app.modules.maker._schemas_recipes import RecipeCreate, RecipeUpdate

        org = Organization(name='Maker Flip Race Org', enabled_modules=['maker'])
        template = ProductTemplate(organization_id=org.id, name='Flip race product')
        real_async_db_session.add_all([org, template])
        await real_async_db_session.commit()
        org_id, template_id = org.id, template.id

        engine = real_async_db_session.bind  # the AsyncEngine the fixture uses
        setup = AsyncSession(bind=engine)
        try:
            incumbent = await recipe_service.create_recipe(
                setup,
                org_id,
                RecipeCreate(output_template_id=template_id, name='Incumbent'),
            )
            challenger_one = await recipe_service.create_recipe(
                setup,
                org_id,
                RecipeCreate(output_template_id=template_id, name='Challenger one'),
            )
            challenger_two = await recipe_service.create_recipe(
                setup,
                org_id,
                RecipeCreate(output_template_id=template_id, name='Challenger two'),
            )
            incumbent_default = incumbent.is_default  # read before commit expires it
            one_id, two_id = challenger_one.id, challenger_two.id
            await setup.commit()
        finally:
            await setup.close()
        assert incumbent_default is True  # the auto-default first

        session_a = AsyncSession(bind=engine)
        session_b = AsyncSession(bind=engine)
        try:

            async def _flip(session: AsyncSession, recipe_id: UUID) -> None:
                await recipe_service.update_recipe(
                    session,
                    org_id,
                    recipe_id,
                    RecipeUpdate(is_default=True),
                )
                # The advisory lock is transaction-scoped: committing is what
                # releases it, exactly like a real request ending.
                await session.commit()

            await asyncio.gather(_flip(session_a, one_id), _flip(session_b, two_id))
        finally:
            await session_a.close()
            await session_b.close()

        rows = (
            (
                await real_async_db_session.execute(
                    select(MakerRecipe).where(
                        MakerRecipe.output_template_id == template_id
                    )
                )
            )
            .scalars()
            .all()
        )
        # gather raising would already mean the index died uncaught; the
        # template must still name exactly one default.
        assert sum(1 for row in rows if row.is_default) == 1
