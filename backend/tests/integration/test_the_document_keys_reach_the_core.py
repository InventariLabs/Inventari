"""Four keys a core chain cannot build, and a module install must.

The models declare them: ``items.source_document_id`` and
``item_history.source_document_id`` point at ``documents``,
``stock_reservations.document_line_id`` and
``stock_valuation_layers.document_line_id`` at ``document_lines``. The core
chain leaves them out on purpose — it must not reach for a table a module
builds — and the warehouse module never picked them up, so a full
installation had none of them. The ``SET NULL`` the models promise was a
word with no constraint behind it: a deleted document left rows naming an
id that was gone.

An installation that lived through that gap holds exactly those rows, and
the upgrade that brings the keys cannot be built over them. It counts
them, sets them to NULL — the promise catching up with what the missing
key let happen — reports how many each key carried, and only then builds
the key; references that name a real row pass through untouched.
"""

from __future__ import annotations

import uuid

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, insert, inspect, select, text

from app.core.db_isolation import isolated_db_url
from app.core.module_migrations import run_module_migrations

pytestmark = pytest.mark.integration

_EXPECTED = {
    ('items', 'source_document_id', 'documents'),
    ('item_history', 'source_document_id', 'documents'),
    ('stock_reservations', 'document_line_id', 'document_lines'),
    ('stock_valuation_layers', 'document_line_id', 'document_lines'),
}


def _keys_present(engine) -> set[tuple[str, str, str]]:
    found: set[tuple[str, str, str]] = set()
    inspector = inspect(engine)
    for table, column, target in _EXPECTED:
        for fk in inspector.get_foreign_keys(table):
            if fk['constrained_columns'] == [column] and fk['referred_table'] == target:
                found.add((table, column, target))
    return found


def test_a_full_install_carries_the_keys_the_models_declare(monkeypatch):
    with isolated_db_url('dockeys') as url:
        monkeypatch.setenv('DATABASE_URL', url)
        command.upgrade(Config('alembic.ini'), 'head')
        run_module_migrations('warehouse', 'upgrade', db_url=url)

        engine = create_engine(url)
        try:
            assert _keys_present(engine) == _EXPECTED
        finally:
            engine.dispose()


def test_deleting_a_document_clears_the_records_that_named_it(monkeypatch):
    """The promise behind the key: SET NULL, not a dangling id."""
    from app.models.item import Item
    from app.models.organization import Organization
    from app.models.storage_location import StorageLocation
    from app.models.user import User

    org_id, user_id, location_id, item_id = (uuid.uuid4() for _ in range(4))
    document_id = uuid.uuid4()

    with isolated_db_url('dockeys2') as url:
        monkeypatch.setenv('DATABASE_URL', url)
        command.upgrade(Config('alembic.ini'), 'head')
        run_module_migrations('warehouse', 'upgrade', db_url=url)

        engine = create_engine(url)
        try:
            with engine.begin() as conn:
                conn.execute(insert(Organization).values(id=org_id, name='Keys'))
                conn.execute(
                    insert(User).values(
                        id=user_id,
                        organization_id=org_id,
                        email=f'{uuid.uuid4().hex[:8]}@example.com',
                        hashed_password='x',
                        full_name='Keys',
                    )
                )
                conn.execute(
                    insert(StorageLocation).values(
                        id=location_id,
                        organization_id=org_id,
                        name='Shelf',
                        created_by=user_id,
                    )
                )
                conn.execute(
                    text(
                        'INSERT INTO documents (id, organization_id, type, '
                        'number, status, created_by) VALUES '
                        "(:id, :org, 'RECEIPT', :number, 'DRAFT', :user)"
                    ),
                    {
                        'id': document_id,
                        'org': org_id,
                        'number': f'K/{uuid.uuid4().hex[:6]}',
                        'user': user_id,
                    },
                )
                conn.execute(
                    insert(Item).values(
                        id=item_id,
                        organization_id=org_id,
                        storage_location_id=location_id,
                        name='Kawa',
                        quantity=1,
                        source_document_id=document_id,
                    )
                )

            with engine.begin() as conn:
                conn.execute(
                    text('DELETE FROM documents WHERE id = :id'), {'id': document_id}
                )

            with engine.connect() as conn:
                left = conn.execute(
                    select(Item.source_document_id).where(Item.id == item_id)
                ).scalar()
            assert left is None, 'the record kept an id no document answers to'
        finally:
            engine.dispose()


def _seed_the_shape_the_keys_never_guarded(engine) -> dict[str, uuid.UUID]:
    """The rows an installation holds when no key ever anchored them.

    One reference names a real document — the upgrade must leave it alone —
    and the rest name ids nothing answers to: two items, a history row, a
    reservation and a valuation layer, so every one of the four keys has
    something of its own to count. Returns the ids the assertions read back.
    """
    from app.models.item import Item
    from app.models.item_history import ItemHistory
    from app.models.organization import Organization
    from app.models.product_template import ProductTemplate
    from app.models.stock_anchor import StockAnchor
    from app.models.stock_reservation import StockReservation
    from app.models.stock_valuation_layer import StockValuationLayer
    from app.models.storage_location import StorageLocation
    from app.models.user import User

    org, user, location, template, anchor = (uuid.uuid4() for _ in range(5))
    kept_item, first_item, second_item = (uuid.uuid4() for _ in range(3))
    history, reservation, layer = (uuid.uuid4() for _ in range(3))
    document = uuid.uuid4()
    dangling = {
        name: uuid.uuid4()
        for name in ('item_a', 'item_b', 'history', 'line_a', 'line_b')
    }

    with engine.begin() as conn:
        conn.execute(insert(Organization).values(id=org, name='Dirty'))
        conn.execute(
            insert(User).values(
                id=user,
                organization_id=org,
                email=f'{uuid.uuid4().hex[:8]}@example.com',
                hashed_password='x',
                full_name='Dirty',
            )
        )
        conn.execute(
            insert(StorageLocation).values(
                id=location,
                organization_id=org,
                name='Shelf',
                created_by=user,
            )
        )
        conn.execute(
            insert(ProductTemplate).values(
                id=template, organization_id=org, name='Kawa'
            )
        )
        conn.execute(
            insert(StockAnchor).values(
                id=anchor,
                organization_id=org,
                product_template_id=template,
                storage_location_id=location,
            )
        )
        conn.execute(
            text(
                'INSERT INTO documents (id, organization_id, type, '
                'number, status, created_by) VALUES '
                "(:id, :org, 'RECEIPT', :number, 'DRAFT', :user)"
            ),
            {
                'id': document,
                'org': org,
                'number': f'K/{uuid.uuid4().hex[:6]}',
                'user': user,
            },
        )
        conn.execute(
            insert(Item).values(
                id=kept_item,
                organization_id=org,
                # The piece the reservation below holds: a hold with no
                # record under it is refused at commit (archived ``holdguard01``).
                template_id=template,
                storage_location_id=location,
                name='Kept',
                quantity=1,
                source_document_id=document,
            )
        )
        for item_id, value in (
            (first_item, dangling['item_a']),
            (second_item, dangling['item_b']),
        ):
            conn.execute(
                insert(Item).values(
                    id=item_id,
                    organization_id=org,
                    storage_location_id=location,
                    name='Dangling',
                    quantity=1,
                    source_document_id=value,
                )
            )
        conn.execute(
            insert(ItemHistory).values(
                id=history,
                organization_id=org,
                item_id=first_item,
                action='CREATED',
                source_document_id=dangling['history'],
            )
        )
        conn.execute(
            insert(StockReservation).values(
                id=reservation,
                organization_id=org,
                document_id=uuid.uuid4(),
                document_line_id=dangling['line_a'],
                anchor_id=anchor,
                quantity=1,
            )
        )
        conn.execute(
            insert(StockValuationLayer).values(
                id=layer,
                organization_id=org,
                product_template_id=template,
                document_line_id=dangling['line_b'],
                quantity=1,
                remaining_qty=1,
                unit_cost=1,
                total_value=1,
                direction='IN',
            )
        )
    return {
        'kept_item': kept_item,
        'first_item': first_item,
        'second_item': second_item,
        'history': history,
        'reservation': reservation,
        'layer': layer,
        'document': document,
    }


def test_the_upgrade_clears_dangling_references_and_reports_them(monkeypatch, capsys):
    """An installation whose documents were deleted while no key stood behind.

    Measured before the repair: the upgrade died on the first such row with
    a raw foreign key violation, partway through the module's own chain.
    Now each key counts its dangling rows, sets them to NULL — the same
    thing the key's ``SET NULL`` does when its document is deleted — prints
    the count, and is built validated. A reference naming a real row is
    left alone.
    """
    from app.core.migration_doctor import unvalidated_constraints
    from app.models.item import Item
    from app.models.item_history import ItemHistory
    from app.models.stock_reservation import StockReservation
    from app.models.stock_valuation_layer import StockValuationLayer

    with isolated_db_url('dockeys3') as url:
        monkeypatch.setenv('DATABASE_URL', url)
        command.upgrade(Config('alembic.ini'), 'head')
        # The module as it stood before the four keys: tables there, keys not.
        run_module_migrations(
            'warehouse',
            'upgrade',
            db_url=url,
            revision='doc_line_unit_backfill01',
        )
        engine = create_engine(url)
        try:
            ids = _seed_the_shape_the_keys_never_guarded(engine)

            run_module_migrations('warehouse', 'upgrade', db_url=url)
            report = capsys.readouterr().out

            with engine.connect() as conn:
                kept = conn.execute(
                    select(Item.source_document_id).where(Item.id == ids['kept_item'])
                ).scalar()
                assert kept == ids['document'], (
                    'a reference to a document that exists was cleared too'
                )
                cleared = (
                    (Item, Item.source_document_id, ids['first_item']),
                    (Item, Item.source_document_id, ids['second_item']),
                    (ItemHistory, ItemHistory.source_document_id, ids['history']),
                    (
                        StockReservation,
                        StockReservation.document_line_id,
                        ids['reservation'],
                    ),
                    (
                        StockValuationLayer,
                        StockValuationLayer.document_line_id,
                        ids['layer'],
                    ),
                )
                for model, column, row_id in cleared:
                    left = conn.execute(
                        select(column).where(model.id == row_id)
                    ).scalar()
                    assert left is None, (
                        f'{model.__tablename__} kept an id no row answers to'
                    )

            assert _keys_present(engine) == _EXPECTED
            assert unvalidated_constraints(engine) == [], (
                'a key was left half-promised over the rows it counted'
            )
            for line in (
                'items.source_document_id -> documents: 2 row(s) set to NULL',
                'item_history.source_document_id -> documents: 1 row(s) set to NULL',
                'stock_reservations.document_line_id -> document_lines: '
                '1 row(s) set to NULL',
                'stock_valuation_layers.document_line_id -> document_lines: '
                '1 row(s) set to NULL',
            ):
                assert line in report, f'the report never named: {line}'
        finally:
            engine.dispose()
