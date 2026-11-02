"""The demo seeder refuses to seed on top of an organization that already
carries items — before it writes anything, with the way out named.

A second run used to die halfway through the quant uniqueness constraint:
the organization left half populated, nothing in the final state saying so,
every later measurement on it unreproducible.
"""

from __future__ import annotations

import collections
import uuid
from collections.abc import Generator
from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

import seed_demo_data
from app.database import Base
from app.models.category import Category
from app.models.item import Item
from app.models.organization import Organization
from app.models.product_template import ProductTemplate
from app.models.storage_location import StorageLocation
from app.models.uom import Uom, UomCategory
from app.models.user import User
from app.services.token_service import get_password_hash
from tests.integration._shelf import anchor_pending_records

pytestmark = pytest.mark.integration


@pytest.fixture
def equip_org(db_session: Session) -> Generator[dict]:
    """The smallest organization the equipment seeder accepts: two
    templates, one leaf location, one category."""
    org = Organization(id=uuid.uuid4(), name='Seed Refusal Org')
    db_session.add(org)
    db_session.commit()
    user = User(
        id=uuid.uuid4(),
        organization_id=org.id,
        email=f'seed-refusal+{uuid.uuid4().hex[:8]}@example.com',
        full_name='Seed',
        hashed_password=get_password_hash('seed-test-password'),
    )
    uom_category = UomCategory(id=uuid.uuid4(), name='units')
    uom = Uom(
        id=uuid.uuid4(),
        organization_id=None,
        category_id=uom_category.id,
        name='Piece',
        symbol=seed_demo_data.UOM_PIECE,
        factor=Decimal('1'),
    )
    db_session.add_all([user, uom_category, uom])
    db_session.commit()

    cat = Category(
        id=uuid.uuid4(),
        organization_id=org.id,
        name='Laptop',
        code='laptop',
    )
    db_session.add(cat)
    db_session.commit()

    root = StorageLocation(
        id=uuid.uuid4(),
        organization_id=org.id,
        name='HQ',
        context_tag=None,
        created_by=user.id,
    )
    db_session.add(root)
    db_session.commit()
    wing = StorageLocation(
        id=uuid.uuid4(),
        organization_id=org.id,
        name='Wing',
        parent_id=root.id,
        context_tag='equipment',
        created_by=user.id,
    )
    db_session.add(wing)
    db_session.commit()
    leaf = StorageLocation(
        id=uuid.uuid4(),
        organization_id=org.id,
        name='Room',
        parent_id=wing.id,
        context_tag='equipment',
        created_by=user.id,
    )
    db_session.add(leaf)
    db_session.commit()

    template = ProductTemplate(
        id=uuid.uuid4(),
        organization_id=org.id,
        name='Demo Laptop',
        brand='DemoBrand',
        barcode=f'DEMO-{uuid.uuid4().hex[:10]}',
        uom_id=uom.id,
    )
    db_session.add(template)
    db_session.commit()

    yield {
        'org_id': org.id,
        'user_id': user.id,
        'template': template,
        'leaf': leaf,
        'uom_ids': {seed_demo_data.UOM_PIECE: uom.id},
        'cat_ids': {'laptop': cat.id},
    }

    for table in reversed(Base.metadata.sorted_tables):
        column = table.c.get('organization_id')
        if column is None or table.name in ('organizations', 'audit_log'):
            continue
        db_session.execute(table.delete().where(column == org.id))
    db_session.query(Organization).filter(Organization.id == org.id).delete(
        synchronize_session=False
    )
    db_session.commit()


class TestRefusesToSeedOnTopOfItems:
    def test_refuses_when_the_organization_already_holds_items(
        self, db_session: Session, equip_org: dict, capsys
    ):
        org_id = equip_org['org_id']
        db_session.add(
            Item(
                id=uuid.uuid4(),
                organization_id=org_id,
                storage_location_id=equip_org['leaf'].id,
                category_id=equip_org['cat_ids']['laptop'],
                template_id=equip_org['template'].id,
                name=equip_org['template'].name,
                uom_id=next(iter(equip_org['uom_ids'].values())),
                quantity=Decimal('1'),
                is_deleted=False,
            )
        )
        anchor_pending_records(db_session)
        db_session.commit()

        with pytest.raises(SystemExit) as excinfo:
            seed_demo_data._ensure_seedable(db_session, org_id, clean=False)

        assert excinfo.value.code == 1
        out = capsys.readouterr().out
        assert 'already holds' in out
        assert '--clean' in out

    def test_an_empty_organization_is_seedable(
        self, db_session: Session, equip_org: dict
    ):
        seed_demo_data._ensure_seedable(db_session, equip_org['org_id'], clean=False)

    def test_clean_clears_the_refusal(self, db_session: Session, equip_org: dict):
        seed_demo_data._ensure_seedable(db_session, equip_org['org_id'], clean=True)


def _deleted_item(db_session: Session, equip_org: dict) -> None:
    """A record in the bin: gone from every screen, still a row, still
    pointing at its template."""
    db_session.add(
        Item(
            id=uuid.uuid4(),
            organization_id=equip_org['org_id'],
            storage_location_id=equip_org['leaf'].id,
            category_id=equip_org['cat_ids']['laptop'],
            template_id=equip_org['template'].id,
            name=equip_org['template'].name,
            uom_id=next(iter(equip_org['uom_ids'].values())),
            quantity=Decimal('1'),
            is_deleted=True,
        )
    )
    anchor_pending_records(db_session)
    db_session.commit()


class TestAnOrganizationWhoseItemsAreAllDeleted:
    """The guard counted every row, --clean removed only the live ones: the
    refusal pointed at a way out that died on the template's foreign key."""

    def test_the_refusal_says_the_items_it_counts_are_archived(
        self, db_session: Session, equip_org: dict, capsys
    ):
        _deleted_item(db_session, equip_org)

        with pytest.raises(SystemExit):
            seed_demo_data._ensure_seedable(
                db_session, equip_org['org_id'], clean=False
            )

        out = capsys.readouterr().out
        # A number the list does not show has to say where it lives.
        assert '1 item(s)' in out
        assert '1 of them archived (Products → Archived)' in out
        assert '--clean' in out

    def test_clean_removes_them_and_the_seed_can_run(
        self, db_session: Session, equip_org: dict
    ):
        _deleted_item(db_session, equip_org)

        seed_demo_data.clean_seed_data(db_session, equip_org['org_id'])

        remaining = (
            db_session.query(Item)
            .filter(Item.organization_id == equip_org['org_id'])
            .count()
        )
        assert remaining == 0
        seed_demo_data._ensure_seedable(db_session, equip_org['org_id'], clean=False)


class _SessionThatSurvivesClose:
    """``main`` opens its own session and closes it; the test's session is
    the one holding the fixture's rows, so ``close`` must not end it."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def close(self) -> None:
        pass

    def __getattr__(self, name: str):
        return getattr(self._session, name)


@pytest.fixture
def seeder_calls(monkeypatch, db_session: Session, equip_org: dict) -> list[str]:
    """Run ``main`` against the fixture organization, recording each step it
    takes in order. The writing steps are replaced by recorders, so a run
    that gets past the guard shows up as a name in the list, not as rows."""
    user = db_session.get(User, equip_org['user_id'])
    monkeypatch.setattr(seed_demo_data, 'ADMIN_EMAIL', user.email)
    monkeypatch.setattr(
        seed_demo_data, 'SessionLocal', lambda: _SessionThatSurvivesClose(db_session)
    )
    calls: list[str] = []
    real_guard = seed_demo_data._ensure_seedable

    def guard(*args, **kwargs):
        calls.append('guard')
        return real_guard(*args, **kwargs)

    def wipe(*_args, **_kwargs):
        calls.append('wipe')

    def seed(*_args, **_kwargs):
        calls.append('seed')
        return collections.defaultdict(int)

    monkeypatch.setattr(seed_demo_data, '_ensure_seedable', guard)
    monkeypatch.setattr(seed_demo_data, 'clean_seed_data', wipe)
    monkeypatch.setattr(seed_demo_data, 'seed_organization', seed)
    return calls


def _run_main(monkeypatch, *flags: str) -> None:
    monkeypatch.setattr('sys.argv', ['seed_demo_data.py', '--items', '1', *flags])
    seed_demo_data.main()


class TestTheGuardIsCalledFromMainBeforeAnyWrite:
    """The promise is where the guard is called and that it comes first;
    a predicate nobody calls passes every test of the predicate."""

    def test_a_populated_organization_is_refused_before_any_write(
        self, monkeypatch, db_session: Session, equip_org: dict, seeder_calls
    ):
        db_session.add(
            Item(
                id=uuid.uuid4(),
                organization_id=equip_org['org_id'],
                storage_location_id=equip_org['leaf'].id,
                category_id=equip_org['cat_ids']['laptop'],
                template_id=equip_org['template'].id,
                name=equip_org['template'].name,
                uom_id=next(iter(equip_org['uom_ids'].values())),
                quantity=Decimal('1'),
                is_deleted=False,
            )
        )
        anchor_pending_records(db_session)
        db_session.commit()

        with pytest.raises(SystemExit) as excinfo:
            _run_main(monkeypatch)

        assert excinfo.value.code == 1
        # Guard ran, and nothing that writes ran after it — or before it.
        assert seeder_calls == ['guard']

    def test_the_guard_comes_before_the_wipe_and_the_seed(
        self, monkeypatch, seeder_calls
    ):
        _run_main(monkeypatch, '--clean')

        assert seeder_calls == ['guard', 'wipe', 'seed']

    def test_an_empty_organization_is_guarded_then_seeded(
        self, monkeypatch, seeder_calls
    ):
        _run_main(monkeypatch)

        assert seeder_calls == ['guard', 'seed']
