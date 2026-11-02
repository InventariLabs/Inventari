"""Putaway limits, putaway rules and tax rates reach the log.

Each of them decides what the warehouse does next — which shelf a delivery
lands on, whether a shelf takes a second product, what rate a line is
taxed at — and changing one left nothing in the organization log: "who
moved the limit on this shelf" had no answer. They go through the same
configuration funnel the document profiles use, so an entry names the
module, the fields that moved and both sides of the change.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Coroutine
from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest
from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import Session

from app.core.contracts import UserContextDTO
from app.core.exceptions import NotFoundException
from app.core.testing import ModuleTestHelper
from app.models.audit_log import AuditLog
from app.models.organization import Organization
from app.models.product_template import ProductTemplate
from app.models.storage_location import StorageLocation
from app.models.storage_type import StorageType
from app.models.user import User
from app.modules.warehouse._router_capacity import update_putaway_capacity
from app.modules.warehouse._router_putaway import (
    delete_putaway_rule,
    update_putaway_rule,
)
from app.modules.warehouse.models import TaxRate
from app.modules.warehouse.putaway_schemas import (
    PutawayCapacityUpdate,
    PutawayRuleUpdate,
)
from app.modules.warehouse.tax_rate_service import (
    create_tax_rate,
    delete_tax_rate,
    update_tax_rate,
)

from .test_receipt_line_target import _make_category
from .test_two_scans_of_one_line import _let_racers_finish, _wait_until_parked

pytestmark = pytest.mark.integration


def _changes(db_session: Session, org_id: UUID, subject: str) -> list[dict[str, Any]]:
    """The warehouse configuration entries about *subject*, oldest first."""
    db_session.expire_all()
    rows = db_session.scalars(
        select(AuditLog)
        .where(
            AuditLog.organization_id == org_id,
            AuditLog.target_type == 'module',
        )
        .order_by(AuditLog.created_at.asc())
    ).all()
    return [
        {**(row.snapshot or {}), 'user_id': row.user_id}
        for row in rows
        if (row.snapshot or {}).get('name') == 'warehouse'
        and str((row.snapshot or {}).get('subject', '')).startswith(subject)
    ]


_Write = Callable[[AsyncSession], Coroutine[Any, Any, Any]]


def _overlap(engine: AsyncEngine, write: _Write, then: _Write | None = None) -> None:
    """Run *write* in two transactions at once, the second reaching the row
    while the first holds it uncommitted; the first commits, then the second.
    *then*, when given, is what the second transaction does instead.

    Two administrators saving the same edit together: the second save finds
    the change already made, and a journal entry it wrote from what it read
    before the first committed would record a change that never happened.
    """
    maker = async_sessionmaker(bind=engine, expire_on_commit=False)

    async def _run() -> None:
        async with maker() as first, maker() as second:
            await write(first)
            racer = asyncio.create_task((then or write)(second))
            try:
                await _wait_until_parked(engine, 1)
            except BaseException:
                await first.rollback()
                await _let_racers_finish(racer)
                raise
            await first.commit()
            await racer
            await second.commit()

    asyncio.run(_run())


def _defaults(db_session: Session, org_id: UUID) -> list[str]:
    """The names of the organization's rates currently marked as the default."""
    db_session.expire_all()
    return sorted(
        db_session.scalars(
            select(TaxRate.name).where(
                TaxRate.organization_id == org_id, TaxRate.is_default.is_(True)
            )
        ).all()
    )


class TestPutawayCapacityReachesTheLog:
    def test_setting_changing_and_dropping_a_limit_each_write_an_entry(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_org: Organization,
        doc_user: User,
        doc_target_location: StorageLocation,
        doc_template: ProductTemplate,
        db_session: Session,
    ) -> None:
        created = client.post(
            '/api/v1/warehouse/putaway/capacity',
            headers=doc_auth_headers,
            json={
                'location_id': str(doc_target_location.id),
                'product_template_id': str(doc_template.id),
                'max_quantity': '20',
            },
        )
        assert created.status_code == status.HTTP_201_CREATED, created.text
        entry_id = created.json()['id']
        changed = client.put(
            f'/api/v1/warehouse/putaway/capacity/{entry_id}',
            headers=doc_auth_headers,
            json={'max_quantity': '35'},
        )
        assert changed.status_code == status.HTTP_200_OK, changed.text
        dropped = client.delete(
            f'/api/v1/warehouse/putaway/capacity/{entry_id}', headers=doc_auth_headers
        )
        assert dropped.status_code == status.HTTP_204_NO_CONTENT, dropped.text

        entries = _changes(db_session, doc_org.id, 'putaway-capacity')
        assert len(entries) == 3, entries
        set_, moved, gone = entries
        assert float(set_['after']['max_quantity']) == 20
        assert set_['user_id'] == doc_user.id
        assert float(moved['before']['max_quantity']) == 20
        assert float(moved['after']['max_quantity']) == 35
        assert float(gone['before']['max_quantity']) == 35
        assert set(gone['after'].values()) == {None}
        # Only the number moves, but every entry says whose limit it is —
        # an edit included — by id and by the names they had at the time.
        for entry in entries:
            assert entry['location_id'] == str(doc_target_location.id)
            assert entry['location_name'] == doc_target_location.name
            assert entry['product_template_id'] == str(doc_template.id)
            assert entry['product_template_name'] == doc_template.name

    def test_the_same_edit_saved_twice_at_once_writes_one_entry(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_org: Organization,
        doc_user: User,
        doc_target_location: StorageLocation,
        doc_template: ProductTemplate,
        db_session: Session,
        async_engine_fixture: AsyncEngine,
    ) -> None:
        created = client.post(
            '/api/v1/warehouse/putaway/capacity',
            headers=doc_auth_headers,
            json={
                'location_id': str(doc_target_location.id),
                'product_template_id': str(doc_template.id),
                'max_quantity': '35',
            },
        )
        assert created.status_code == status.HTTP_201_CREATED, created.text
        entry_id = UUID(created.json()['id'])
        user = UserContextDTO(id=doc_user.id, organization_id=doc_org.id, role='admin')
        org_id = doc_org.id
        db_session.commit()

        _overlap(
            async_engine_fixture,
            lambda db: update_putaway_capacity(
                entry_id,
                PutawayCapacityUpdate(max_quantity=Decimal('40')),
                current_user=user,
                db=db,
            ),
        )

        moved = [
            entry
            for entry in _changes(db_session, org_id, 'putaway-capacity')
            if entry['before'].get('max_quantity') is not None
        ]
        assert len(moved) == 1, moved
        assert float(moved[0]['before']['max_quantity']) == 35
        assert float(moved[0]['after']['max_quantity']) == 40

    def test_the_mix_flag_is_journalled_only_when_it_moves(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_org: Organization,
        doc_target_location: StorageLocation,
        db_session: Session,
    ) -> None:
        url = f'/api/v1/warehouse/putaway/capacity-settings/{doc_target_location.id}'
        # A shelf nobody restricted already reads mixed: saving mixed is no change.
        unchanged = client.put(
            url, headers=doc_auth_headers, json={'single_product': False}
        )
        assert unchanged.status_code == status.HTTP_200_OK, unchanged.text
        assert _changes(db_session, doc_org.id, 'putaway-location') == []

        restricted = client.put(
            url, headers=doc_auth_headers, json={'single_product': True}
        )
        assert restricted.status_code == status.HTTP_200_OK, restricted.text

        entries = _changes(db_session, doc_org.id, 'putaway-location')
        assert len(entries) == 1, entries
        assert entries[0]['subject'] == 'putaway-location'
        assert entries[0]['location_id'] == str(doc_target_location.id)
        assert entries[0]['location_name'] == doc_target_location.name
        assert entries[0]['before'] == {'single_product': False}
        assert entries[0]['after'] == {'single_product': True}


class TestPutawayRulesReachTheLog:
    def test_creating_editing_and_deleting_a_rule_each_write_an_entry(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_org: Organization,
        doc_target_location: StorageLocation,
        doc_source_location: StorageLocation,
        db_session: Session,
    ) -> None:
        category = _make_category(db_session, doc_org, 'Frozen')
        created = client.post(
            '/api/v1/warehouse/putaway-rules',
            headers=doc_auth_headers,
            json={
                'category_id': str(category.id),
                'location_ids': [str(doc_target_location.id)],
            },
        )
        assert created.status_code == status.HTTP_201_CREATED, created.text
        rule_id = created.json()['id']
        # Only the shelves move: that alone has to be enough for an entry.
        moved = client.put(
            f'/api/v1/warehouse/putaway-rules/{rule_id}',
            headers=doc_auth_headers,
            json={
                'location_ids': [
                    str(doc_target_location.id),
                    str(doc_source_location.id),
                ]
            },
        )
        assert moved.status_code == status.HTTP_200_OK, moved.text
        deleted = client.delete(
            f'/api/v1/warehouse/putaway-rules/{rule_id}', headers=doc_auth_headers
        )
        assert deleted.status_code == status.HTTP_204_NO_CONTENT, deleted.text

        entries = _changes(db_session, doc_org.id, 'putaway-rule')
        assert len(entries) == 3, entries
        made, edited, gone = entries
        assert {entry['subject'] for entry in entries} == {'putaway-rule'}
        assert made['after']['category_id'] == str(category.id)
        assert made['after']['category_name'] == 'Frozen'
        assert made['after']['locations'] == [doc_target_location.name]
        assert made['after']['location_ids'] == [str(doc_target_location.id)]
        # A rule has no name, and what it matches need not be unique: its id
        # is which rule it was, on every entry.
        assert made['id'] == edited['id'] == gone['id'] == rule_id
        assert set(edited['after']) == {'locations', 'location_ids'}
        assert edited['after']['locations'] == [
            doc_target_location.name,
            doc_source_location.name,
        ]
        # The edit moved only the shelves; which rule it was rides beside them.
        assert edited['category_id'] == str(category.id)
        assert edited['category_name'] == 'Frozen'
        assert gone['before']['category_id'] == str(category.id)
        assert set(gone['after'].values()) == {None}

    def test_a_rule_moved_to_a_different_shelf_of_the_same_name_is_journalled(
        self,
        client: TestClient,
        h: ModuleTestHelper,
        doc_auth_headers: dict[str, str],
        doc_org: Organization,
        doc_user: User,
        doc_storage_type: StorageType,
        doc_target_location: StorageLocation,
        db_session: Session,
    ) -> None:
        # Two shelves both called "Target Warehouse", in different buildings:
        # the journal has to tell them apart by what they are, not by label.
        building = h.create_storage_location(
            doc_org, doc_storage_type, doc_user, name='Other building'
        )
        twin = h.create_storage_location(
            doc_org, doc_storage_type, doc_user, name=doc_target_location.name
        )
        twin.parent_id = building.id
        db_session.commit()
        category = _make_category(db_session, doc_org, 'Chilled')
        created = client.post(
            '/api/v1/warehouse/putaway-rules',
            headers=doc_auth_headers,
            json={
                'category_id': str(category.id),
                'location_ids': [str(doc_target_location.id)],
            },
        )
        assert created.status_code == status.HTTP_201_CREATED, created.text
        moved = client.put(
            f'/api/v1/warehouse/putaway-rules/{created.json()["id"]}',
            headers=doc_auth_headers,
            json={'location_ids': [str(twin.id)]},
        )
        assert moved.status_code == status.HTTP_200_OK, moved.text

        entries = _changes(db_session, doc_org.id, 'putaway-rule')
        assert len(entries) == 2, entries
        assert entries[1]['before'] == {'location_ids': [str(doc_target_location.id)]}
        assert entries[1]['after'] == {'location_ids': [str(twin.id)]}
        # The labels did not move, so they are not in before/after — but the
        # shelf is still named, beside the change.
        assert entries[1]['locations'] == [doc_target_location.name]

    def test_two_rules_matching_the_same_goods_are_told_apart_in_their_entries(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_org: Organization,
        doc_target_location: StorageLocation,
        doc_source_location: StorageLocation,
        db_session: Session,
    ) -> None:
        category = _make_category(db_session, doc_org, 'Review')
        rule_ids = []
        for shelf, priority in ((doc_target_location, 100), (doc_source_location, 10)):
            created = client.post(
                '/api/v1/warehouse/putaway-rules',
                headers=doc_auth_headers,
                json={
                    'category_id': str(category.id),
                    'location_ids': [str(shelf.id)],
                    'priority': priority,
                },
            )
            assert created.status_code == status.HTTP_201_CREATED, created.text
            rule_ids.append(created.json()['id'])
        for rule_id in rule_ids:
            disabled = client.put(
                f'/api/v1/warehouse/putaway-rules/{rule_id}',
                headers=doc_auth_headers,
                json={'is_active': False},
            )
            assert disabled.status_code == status.HTTP_200_OK, disabled.text

        first, second = _changes(db_session, doc_org.id, 'putaway-rule')[2:]
        assert first['after'] == second['after'] == {'is_active': False}
        assert [first['id'], second['id']] == rule_ids
        assert first['locations'] == [doc_target_location.name]
        assert first['priority'] == 100
        assert second['locations'] == [doc_source_location.name]
        assert second['priority'] == 10

    def _rule(
        self,
        client: TestClient,
        headers: dict[str, str],
        db_session: Session,
        org: Organization,
        shelf: StorageLocation,
    ) -> UUID:
        category = _make_category(db_session, org, 'Overlap')
        created = client.post(
            '/api/v1/warehouse/putaway-rules',
            headers=headers,
            json={
                'category_id': str(category.id),
                'location_ids': [str(shelf.id)],
                'priority': 100,
            },
        )
        assert created.status_code == status.HTTP_201_CREATED, created.text
        db_session.commit()
        return UUID(created.json()['id'])

    def test_a_rule_removed_twice_at_once_is_removed_and_journalled_once(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_org: Organization,
        doc_user: User,
        doc_target_location: StorageLocation,
        db_session: Session,
        async_engine_fixture: AsyncEngine,
    ) -> None:
        """The second removal finds the rule gone and answers what a removal
        sent after it answers: not found, with nothing journalled."""
        rule_id = self._rule(
            client, doc_auth_headers, db_session, doc_org, doc_target_location
        )
        user = UserContextDTO(id=doc_user.id, organization_id=doc_org.id, role='admin')
        org_id = doc_org.id

        with pytest.raises(NotFoundException):
            _overlap(
                async_engine_fixture,
                lambda db: delete_putaway_rule(rule_id, current_user=user, db=db),
            )

        removals = _changes(db_session, org_id, 'putaway-rule')[1:]
        assert len(removals) == 1, removals
        assert set(removals[0]['after'].values()) == {None}

    def test_a_rule_removed_while_being_edited_is_journalled_as_it_was_removed(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_org: Organization,
        doc_user: User,
        doc_target_location: StorageLocation,
        db_session: Session,
        async_engine_fixture: AsyncEngine,
    ) -> None:
        rule_id = self._rule(
            client, doc_auth_headers, db_session, doc_org, doc_target_location
        )
        user = UserContextDTO(id=doc_user.id, organization_id=doc_org.id, role='admin')
        org_id = doc_org.id

        _overlap(
            async_engine_fixture,
            lambda db: update_putaway_rule(
                rule_id,
                PutawayRuleUpdate(priority=10, is_active=False),
                current_user=user,
                db=db,
            ),
            then=lambda db: delete_putaway_rule(rule_id, current_user=user, db=db),
        )

        made, edited, gone = _changes(db_session, org_id, 'putaway-rule')
        assert edited['after'] == {'priority': 10, 'is_active': False}
        # The removal took away the rule the edit left, not the one it read
        # before the edit committed.
        assert gone['before']['priority'] == 10
        assert gone['before']['is_active'] is False


class TestTaxRatesReachTheLog:
    def test_creating_changing_and_deleting_a_rate_each_write_an_entry(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_org: Organization,
        doc_user: User,
        db_session: Session,
    ) -> None:
        created = client.post(
            '/api/v1/warehouse/tax-rates',
            headers=doc_auth_headers,
            json={'name': 'Standard VAT', 'rate': '23.00'},
        )
        assert created.status_code == status.HTTP_201_CREATED, created.text
        rate_id = created.json()['id']
        changed = client.put(
            f'/api/v1/warehouse/tax-rates/{rate_id}',
            headers=doc_auth_headers,
            json={'rate': '8.00'},
        )
        assert changed.status_code == status.HTTP_200_OK, changed.text
        deleted = client.delete(
            f'/api/v1/warehouse/tax-rates/{rate_id}', headers=doc_auth_headers
        )
        assert deleted.status_code == status.HTTP_204_NO_CONTENT, deleted.text

        entries = _changes(db_session, doc_org.id, 'tax-rate')
        assert len(entries) == 3, entries
        made, edited, gone = entries
        assert made['after']['name'] == 'Standard VAT'
        assert float(made['after']['rate']) == 23
        assert made['user_id'] == doc_user.id
        assert edited['subject'] == 'tax-rate:Standard VAT'
        assert float(edited['before']['rate']) == 23
        assert float(edited['after']['rate']) == 8
        assert gone['before']['name'] == 'Standard VAT'
        assert set(gone['after'].values()) == {None}

    def test_the_same_edit_saved_twice_at_once_writes_one_entry(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_org: Organization,
        doc_user: User,
        db_session: Session,
        async_engine_fixture: AsyncEngine,
    ) -> None:
        created = client.post(
            '/api/v1/warehouse/tax-rates',
            headers=doc_auth_headers,
            json={'name': 'Rate E', 'rate': '8.00'},
        )
        assert created.status_code == status.HTTP_201_CREATED, created.text
        rate_id = UUID(created.json()['id'])
        org_id, user_id = doc_org.id, doc_user.id
        db_session.commit()

        _overlap(
            async_engine_fixture,
            lambda db: update_tax_rate(
                db, org_id, rate_id, user_id=user_id, rate=Decimal('9.5')
            ),
        )

        edits = _changes(db_session, org_id, 'tax-rate:Rate E')[1:]
        assert len(edits) == 1, edits
        assert float(edits[0]['before']['rate']) == 8
        assert float(edits[0]['after']['rate']) == 9.5

    def test_a_rate_removed_twice_at_once_is_removed_and_journalled_once(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_org: Organization,
        doc_user: User,
        db_session: Session,
        async_engine_fixture: AsyncEngine,
    ) -> None:
        """The second removal finds the rate gone: it answers not found
        instead of failing on a row deleted under it, and journals nothing."""
        created = client.post(
            '/api/v1/warehouse/tax-rates',
            headers=doc_auth_headers,
            json={'name': 'Rate R', 'rate': '8.00'},
        )
        assert created.status_code == status.HTTP_201_CREATED, created.text
        rate_id = UUID(created.json()['id'])
        org_id, user_id = doc_org.id, doc_user.id
        db_session.commit()

        _overlap(
            async_engine_fixture,
            lambda db: delete_tax_rate(db, org_id, rate_id, user_id=user_id),
        )

        removals = _changes(db_session, org_id, 'tax-rate:Rate R')[1:]
        assert len(removals) == 1, removals
        assert set(removals[0]['after'].values()) == {None}

    def test_saving_a_rate_unchanged_writes_nothing(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_org: Organization,
        db_session: Session,
    ) -> None:
        created = client.post(
            '/api/v1/warehouse/tax-rates',
            headers=doc_auth_headers,
            json={'name': 'Reduced VAT', 'rate': '8.00'},
        )
        assert created.status_code == status.HTTP_201_CREATED, created.text
        # The column holds 8.00; a form posting 8 names the same rate.
        for _ in range(2):
            resaved = client.put(
                f'/api/v1/warehouse/tax-rates/{created.json()["id"]}',
                headers=doc_auth_headers,
                json={'rate': '8'},
            )
            assert resaved.status_code == status.HTTP_200_OK, resaved.text

        assert len(_changes(db_session, doc_org.id, 'tax-rate')) == 1

    def test_a_new_default_journals_the_rate_it_took_the_default_from(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_org: Organization,
        doc_user: User,
        db_session: Session,
    ) -> None:
        # One rate is the default: a rate created as the default, and a rate
        # promoted to it, each take the flag off the one that held it.
        for name, rate in (('Rate A', '8.00'), ('Rate B', '9.00')):
            created = client.post(
                '/api/v1/warehouse/tax-rates',
                headers=doc_auth_headers,
                json={'name': name, 'rate': rate, 'is_default': True},
            )
            assert created.status_code == status.HTTP_201_CREATED, created.text
        third = client.post(
            '/api/v1/warehouse/tax-rates',
            headers=doc_auth_headers,
            json={'name': 'Rate C', 'rate': '5.00'},
        )
        assert third.status_code == status.HTTP_201_CREATED, third.text
        promoted = client.put(
            f'/api/v1/warehouse/tax-rates/{third.json()["id"]}',
            headers=doc_auth_headers,
            json={'is_default': True},
        )
        assert promoted.status_code == status.HTTP_200_OK, promoted.text

        cleared = [
            entry
            for entry in _changes(db_session, doc_org.id, 'tax-rate')
            if entry.get('before', {}).get('is_default') is True
        ]
        assert [entry['subject'] for entry in cleared] == [
            'tax-rate:Rate A',
            'tax-rate:Rate B',
        ], cleared
        assert all(entry['after'] == {'is_default': False} for entry in cleared)
        assert all(entry['user_id'] == doc_user.id for entry in cleared)

    def test_two_new_defaults_at_once_journal_the_old_one_cleared_once(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_org: Organization,
        doc_user: User,
        db_session: Session,
        async_engine_fixture: AsyncEngine,
    ) -> None:
        """Two requests making a new default overlap: the old default is
        cleared once, so it is journalled once.

        Each request read the rate holding the flag before the other had
        cleared it, and each journalled true -> false for it. The second
        request now parks on the old default's row until the first commits,
        and that re-read finds it no longer the default.
        """
        held = client.post(
            '/api/v1/warehouse/tax-rates',
            headers=doc_auth_headers,
            json={'name': 'Rate P', 'rate': '8.00', 'is_default': True},
        )
        assert held.status_code == status.HTTP_201_CREATED, held.text
        org_id, user_id = doc_org.id, doc_user.id
        db_session.commit()
        maker = async_sessionmaker(bind=async_engine_fixture, expire_on_commit=False)

        async def _two_new_defaults() -> None:
            async with maker() as first, maker() as second:
                # The first request has taken the flag off P, uncommitted.
                await create_tax_rate(
                    first,
                    org_id,
                    'Rate X',
                    Decimal('5'),
                    user_id=user_id,
                    is_default=True,
                )
                racer = asyncio.create_task(
                    create_tax_rate(
                        second,
                        org_id,
                        'Rate Y',
                        Decimal('6'),
                        user_id=user_id,
                        is_default=True,
                    )
                )
                try:
                    await _wait_until_parked(async_engine_fixture, 1)
                except BaseException:
                    await first.rollback()
                    await _let_racers_finish(racer)
                    raise
                await first.commit()
                await racer
                await second.commit()

        asyncio.run(_two_new_defaults())

        cleared = [
            entry
            for entry in _changes(db_session, org_id, 'tax-rate:Rate P')
            if entry.get('before', {}).get('is_default') is True
        ]
        assert len(cleared) == 1, cleared

    def test_two_new_defaults_at_once_leave_one_default(
        self,
        client: TestClient,
        doc_org: Organization,
        doc_user: User,
        db_session: Session,
        async_engine_fixture: AsyncEngine,
    ) -> None:
        """Two rates created as the default while none holds the flag.

        With no holder there was no row to wait on, so both requests cleared
        nothing and both committed their own rate as the default. The
        organization's default is now taken under one lock: the second
        request waits for the first and takes the flag off its rate.
        """
        org_id, user_id = doc_org.id, doc_user.id
        db_session.commit()
        maker = async_sessionmaker(bind=async_engine_fixture, expire_on_commit=False)

        async def _create(db: AsyncSession, name: str) -> None:
            await create_tax_rate(
                db, org_id, name, Decimal('5'), user_id=user_id, is_default=True
            )

        async def _two_new_defaults() -> None:
            async with maker() as first, maker() as second:
                await _create(first, 'Rate X')
                racer = asyncio.create_task(_create(second, 'Rate Y'))
                try:
                    await _wait_until_parked(async_engine_fixture, 1)
                except BaseException:
                    await first.rollback()
                    await _let_racers_finish(racer)
                    raise
                await first.commit()
                await racer
                await second.commit()

        asyncio.run(_two_new_defaults())

        assert _defaults(db_session, org_id) == ['Rate Y']
        cleared = [
            entry
            for entry in _changes(db_session, org_id, 'tax-rate:Rate X')
            if entry.get('before', {}).get('is_default') is True
        ]
        assert len(cleared) == 1, cleared

    def test_two_promotions_at_once_leave_one_default_and_keep_the_trail(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_org: Organization,
        doc_user: User,
        db_session: Session,
        async_engine_fixture: AsyncEngine,
    ) -> None:
        """Two different rates promoted to the default at once.

        Both requests read the old default before either cleared it; the
        second, once released from the old default's row, found it already
        cleared and left the first's new default standing beside its own.
        """
        ids: dict[str, UUID] = {}
        for name, is_default in (
            ('Rate P', True),
            ('Rate Q', False),
            ('Rate R', False),
        ):
            created = client.post(
                '/api/v1/warehouse/tax-rates',
                headers=doc_auth_headers,
                json={'name': name, 'rate': '8.00', 'is_default': is_default},
            )
            assert created.status_code == status.HTTP_201_CREATED, created.text
            ids[name] = UUID(created.json()['id'])
        org_id, user_id = doc_org.id, doc_user.id
        db_session.commit()
        maker = async_sessionmaker(bind=async_engine_fixture, expire_on_commit=False)

        async def _promote(db: AsyncSession, name: str) -> None:
            await update_tax_rate(
                db, org_id, ids[name], user_id=user_id, is_default=True
            )

        async def _two_promotions() -> None:
            async with maker() as first, maker() as second:
                await _promote(first, 'Rate Q')
                racer = asyncio.create_task(_promote(second, 'Rate R'))
                try:
                    await _wait_until_parked(async_engine_fixture, 1)
                except BaseException:
                    await first.rollback()
                    await _let_racers_finish(racer)
                    raise
                await first.commit()
                await racer
                await second.commit()

        asyncio.run(_two_promotions())

        assert _defaults(db_session, org_id) == ['Rate R']
        flags = [
            (entry['subject'], entry['after'].get('is_default'))
            for entry in _changes(db_session, org_id, 'tax-rate')
            if entry['before'].get('is_default') is not None
            and 'is_default' in entry['after']
            and entry['before']['is_default'] != entry['after']['is_default']
        ]
        assert flags == [
            ('tax-rate:Rate P', False),
            ('tax-rate:Rate Q', True),
            ('tax-rate:Rate Q', False),
            ('tax-rate:Rate R', True),
        ], flags
