"""Integration test for ``seed_demo_data._create_maker_demo``.

The seeder runs against a fresh org so it does not pollute the
E2E Test Org. Idempotency, template count and BOM contents are
verified, then the org + its user + everything seeded is torn down.
"""

from __future__ import annotations

import uuid
from collections.abc import Generator
from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

from app.models.organization import Organization
from app.models.product_template import ProductTemplate
from app.models.uom import Uom
from app.models.user import User
from app.modules.maker.models import BoMLine
from app.services.token_service import get_password_hash
from seed_demo_data import MAKER_BOM, MAKER_TEMPLATES, _create_maker_demo

#: The seeder is the source of these names, so the test reads them rather than
#: keeping a second copy. It kept one until 2026-09-21 and the copy was Polish,
#: so translating the seed turned three green tests red for no defect at all.
OUTPUT_NAME = MAKER_TEMPLATES[0][0]
INGREDIENT_NAMES = [name for name, *_rest in MAKER_TEMPLATES[1:]]
FIRST_INGREDIENT = MAKER_BOM[0][0]

pytestmark = pytest.mark.integration


@pytest.fixture
def smoke_org(db_session: Session) -> Generator[uuid.UUID]:
    org = Organization(id=uuid.uuid4(), name='Smoke Test Maker Seed')
    user = User(
        id=uuid.uuid4(),
        organization_id=org.id,
        email=f'smoke+{uuid.uuid4().hex[:8]}@example.com',
        full_name='Smoke',
        hashed_password=get_password_hash('smoke-test-password'),
    )
    db_session.add(org)
    db_session.commit()
    db_session.add(user)
    db_session.commit()
    yield org.id
    db_session.query(BoMLine).filter(BoMLine.organization_id == org.id).delete(
        synchronize_session=False
    )
    db_session.query(ProductTemplate).filter(
        ProductTemplate.organization_id == org.id
    ).delete(synchronize_session=False)
    db_session.query(User).filter(User.organization_id == org.id).delete(
        synchronize_session=False
    )
    db_session.query(Organization).filter(Organization.id == org.id).delete(
        synchronize_session=False
    )
    db_session.commit()


class TestMakerSeedDemo:
    def test_creates_four_templates_and_three_bom_lines(
        self, db_session: Session, smoke_org: uuid.UUID
    ) -> None:
        _create_maker_demo(db_session, smoke_org)
        db_session.commit()

        templates = (
            db_session.query(ProductTemplate)
            .filter(
                ProductTemplate.organization_id == smoke_org,
                ProductTemplate.meta_data.contains({'maker_demo': True}),
            )
            .all()
        )
        names = sorted(t.name for t in templates)
        assert names == sorted(name for name, *_rest in MAKER_TEMPLATES)

    def test_bom_recipe_targets_the_output_product_with_expected_ingredients(
        self, db_session: Session, smoke_org: uuid.UUID
    ) -> None:
        _create_maker_demo(db_session, smoke_org)
        db_session.commit()

        parent = (
            db_session.query(ProductTemplate)
            .filter(
                ProductTemplate.organization_id == smoke_org,
                ProductTemplate.name == OUTPUT_NAME,
            )
            .one()
        )
        lines = (
            db_session.query(BoMLine)
            .filter(
                BoMLine.organization_id == smoke_org,
                BoMLine.parent_template_id == parent.id,
            )
            .all()
        )

        def _child_name(line: BoMLine) -> str:
            tpl = db_session.get(ProductTemplate, line.child_template_id)
            assert tpl is not None
            return tpl.name

        ingredients = sorted(_child_name(line) for line in lines)
        assert ingredients == sorted(INGREDIENT_NAMES)

    def test_plum_line_has_qty_yield_and_unit(
        self, db_session: Session, smoke_org: uuid.UUID
    ) -> None:
        _create_maker_demo(db_session, smoke_org)
        db_session.commit()

        plum = (
            db_session.query(ProductTemplate)
            .filter(
                ProductTemplate.organization_id == smoke_org,
                ProductTemplate.name == FIRST_INGREDIENT,
            )
            .one()
        )
        parent = (
            db_session.query(ProductTemplate)
            .filter(
                ProductTemplate.organization_id == smoke_org,
                ProductTemplate.name == OUTPUT_NAME,
            )
            .one()
        )
        line = (
            db_session.query(BoMLine)
            .filter(
                BoMLine.organization_id == smoke_org,
                BoMLine.parent_template_id == parent.id,
                BoMLine.child_template_id == plum.id,
            )
            .one()
        )
        assert line.qty_per_batch == Decimal('2.0')
        assert line.unit == 'kg'
        assert line.yield_loss_pct == Decimal('10')

    def test_is_idempotent_when_run_twice(
        self, db_session: Session, smoke_org: uuid.UUID
    ) -> None:
        """Second invocation must reuse, not clone: same template ids, same 3 lines.

        Asserts on the seeder's own return value (template name -> id) plus the
        lines that belong to ``smoke_org``. This is immune to the function-scoped
        ``db_session`` fixture's global TRUNCATE, which a parallel test on the
        same xdist worker could fire between setup and the count assertion —
        unlike a global ``BoMLine.count()`` that would race the truncate.
        """
        ids_after_first = _create_maker_demo(db_session, smoke_org)
        db_session.commit()

        ids_after_second = _create_maker_demo(db_session, smoke_org)
        db_session.commit()

        # Idempotent: second run returns the SAME template ids (no clones).
        assert ids_after_first == ids_after_second

        # And exactly 3 lines for this org (no duplicates added on re-run).
        lines = (
            db_session.query(BoMLine)
            .filter(BoMLine.organization_id == smoke_org)
            .count()
        )
        assert lines == 3

    def test_every_seeded_line_names_its_unit(
        self, db_session: Session, smoke_org: uuid.UUID
    ) -> None:
        """A line with no unit is counted in its ingredient's; the seed says it."""
        _create_maker_demo(db_session, smoke_org)
        db_session.commit()

        lines = (
            db_session.query(BoMLine).filter(BoMLine.organization_id == smoke_org).all()
        )
        assert len(lines) == 3
        assert all(line.uom_id is not None for line in lines)
        for line in lines:
            uom = db_session.get(Uom, line.uom_id)
            assert uom is not None and uom.symbol == line.unit

    def test_an_ingredient_kept_in_pieces_gets_its_line_in_pieces(
        self, db_session: Session, smoke_org: uuid.UUID
    ) -> None:
        """An organization already keeps the cinnamon as 20 g jars.

        The seed reuses a template it finds by name, and the food catalogue's
        jar used to share the cinnamon's. The recipe's kilograms cannot be
        written as a kilogram line against a product counted in pieces —
        nothing converts one into the other — so the seed states it in the
        product's own unit, through the jar's weight: 5 g of 20 g jars is a
        quarter of a jar.
        """
        pcs = db_session.query(Uom).filter(Uom.symbol == 'pcs').one()
        gram = db_session.query(Uom).filter(Uom.symbol == 'g').one()
        cinnamon_name = MAKER_BOM[2][0]
        db_session.add(
            ProductTemplate(
                organization_id=smoke_org,
                name=cinnamon_name,
                sku=f'SKU-{uuid.uuid4().hex[:8]}',
                uom_id=pcs.id,
                weight_value=20.0,
                weight_uom_id=gram.id,
            )
        )
        db_session.commit()

        ids = _create_maker_demo(db_session, smoke_org)
        db_session.commit()

        line = (
            db_session.query(BoMLine)
            .filter(
                BoMLine.organization_id == smoke_org,
                BoMLine.child_template_id == ids[cinnamon_name],
            )
            .one()
        )
        assert line.uom_id == pcs.id
        assert line.unit == 'pcs'
        assert line.qty_per_batch == MAKER_BOM[2][1] / Decimal('0.020')
