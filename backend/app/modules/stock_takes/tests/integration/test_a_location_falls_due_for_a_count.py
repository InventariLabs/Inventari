"""With "count every N days" on, a location that holds stock comes up in To do.

Each location knows when it was last counted — the latest closed count that
counted everything it held there, whether opened on it or on its rack or its
warehouse, or whose counter closed it as done, or that was opened on it and
left nothing uncounted — and with the setting on, it
falls due that many days later — whole days elapsed since that count, the
same days the count screen shows, so the reader's calendar, east or west of
UTC, never moves a count into the past or the future. Closing a count is not that proof by itself:
a partial count, a sampled schedule and a shelf added later leave the shelf
uncounted. A location never counted is due today.
While a count covering it is open the task is under way and opens that count.
The setting is off by default, and then no location is a task.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any, cast
from uuid import UUID

import pytest
from fastapi import status
from sqlalchemy.orm import Session
from starlette.testclient import TestClient

from app.core.testing import ModuleTestHelper
from app.models.storage_location import StorageLocation
from app.modules.stock_takes.models import (
    CycleCountSchedule,
    StockTake,
    StockTakeClosedLocation,
    StockTakeItem,
    StockTakeStatus,
)
from tests.integration._shelf import post_on_shelf

_TODAY = date.today()


class _Shop:
    def __init__(self, db_session: Session, client: TestClient) -> None:
        h = ModuleTestHelper(db_session)
        self.db = db_session
        self.org = h.create_org(
            'Counting Shop',
            ['core', 'items', 'locations', 'categories', 'warehouse', 'stock_takes'],
        )
        self.user = h.create_user(self.org, email='shop-counter@example.com')
        self.headers = h.get_auth_headers(self.user)
        storage_type = h.create_storage_type(
            'Shelf', 'SHELF', organization_id=self.org.id
        )
        self.pantry = h.create_storage_location(
            self.org, storage_type, self.user, name='Pantry'
        )
        self.shelf_a = self._below(h, storage_type, 'Shelf A')
        self.shelf_b = self._below(h, storage_type, 'Shelf B')
        self.bare = self._below(h, storage_type, 'Bare shelf')
        self.held: dict[UUID, list[UUID]] = {}
        for shelf, name in ((self.shelf_a, 'Rice'), (self.shelf_b, 'Oil')):
            self.stock(client, shelf, name)

    def stock(self, client: TestClient, shelf: StorageLocation, name: str) -> None:
        record = post_on_shelf(
            client,
            self.headers,
            ModuleTestHelper(self.db).create_template(self.org, name=name),
            shelf.id,
            3,
        )
        self.held.setdefault(shelf.id, []).append(UUID(record['id']))

    def _below(
        self, h: ModuleTestHelper, storage_type: Any, name: str
    ) -> StorageLocation:
        shelf = h.create_storage_location(self.org, storage_type, self.user, name=name)
        shelf.parent_id = self.pantry.id
        self.db.commit()
        return shelf

    def every(self, days: int) -> None:
        ModuleTestHelper(self.db).set_module_settings(
            self.org, 'stock_takes', {'count_every_days': days}
        )

    def counted(
        self,
        location: StorageLocation,
        days_ago: int,
        *,
        open_: bool = False,
        shelves: list[StorageLocation] | None = None,
        uncounted: list[StorageLocation] | None = None,
        schedule_id: UUID | None = None,
    ) -> StockTake:
        """A count of ``location`` with a row for every record it covers.

        The rows on ``shelves`` (``location`` itself and the shelves below it
        when not given) are counted; those on ``uncounted`` are left waiting.
        """
        at = datetime.now(UTC) - timedelta(days=days_ago)
        take = StockTake(
            organization_id=self.org.id,
            user_id=self.user.id,
            storage_location_id=location.id,
            name=f'Count of {location.name}',
            status=StockTakeStatus.IN_PROGRESS if open_ else StockTakeStatus.COMPLETED,
            started_at=at,
            completed_at=None if open_ else at,
            schedule_id=schedule_id,
        )
        self.db.add(take)
        self.db.flush()
        if shelves is None:
            below = [self.shelf_a, self.shelf_b, self.bare]
            shelves = below if location.id == self.pantry.id else [location]
        for shelf, counted in [(s, True) for s in shelves] + [
            (s, False) for s in uncounted or []
        ]:
            for item_id in self.held.get(shelf.id, []):
                self.db.add(
                    StockTakeItem(
                        stock_take_id=take.id,
                        item_id=item_id,
                        item_name='Counted',
                        system_quantity=Decimal(3),
                        counted_quantity=Decimal(3) if counted else None,
                        storage_location_id=shelf.id,
                    )
                )
        self.db.commit()
        return take

    def tasks(self, client: TestClient, **params: Any) -> dict[str, dict[str, Any]]:
        response = client.get(
            '/api/v1/warehouse/todo',
            headers=self.headers,
            params={'date_to': _TODAY.isoformat(), 'limit': 50, **params},
        )
        assert response.status_code == status.HTTP_200_OK, response.text
        items = cast(list[dict[str, Any]], response.json()['work_items']['items'])
        return {
            item['subject']: item for item in items if item['source_kind'] == 'location'
        }


@pytest.fixture
def shop(db_session: Session, client: TestClient) -> _Shop:
    return _Shop(db_session, client)


@pytest.mark.integration
class TestALocationFallsDueForACount:
    def test_no_location_is_a_task_while_the_setting_is_off(
        self, client: TestClient, shop: _Shop
    ) -> None:
        assert shop.tasks(client) == {}

    def test_a_location_is_due_its_days_after_the_count_that_covered_it(
        self, client: TestClient, shop: _Shop
    ) -> None:
        shop.every(30)
        # Shelf A's own count is older than the pantry's, which counted it
        # too: the pantry's is its last count. Shelf B was counted lately.
        shop.counted(shop.shelf_a, 90)
        shop.counted(shop.pantry, 40)
        shop.counted(shop.shelf_b, 5)

        tasks = shop.tasks(client)

        assert set(tasks) == {'Pantry › Shelf A'}
        assert Decimal(tasks['Pantry › Shelf A']['count']) == 40

    def test_an_old_count_makes_a_due_task_with_the_days_since(
        self, client: TestClient, shop: _Shop
    ) -> None:
        shop.every(30)
        shop.counted(shop.shelf_a, 62)
        shop.counted(shop.shelf_b, 3)

        tasks = shop.tasks(client)

        assert set(tasks) == {'Pantry › Shelf A'}
        task = tasks['Pantry › Shelf A']
        assert task['kind'] == 'count'
        assert task['state'] == 'todo'
        assert task['next_action'] == 'count'
        assert Decimal(task['count']) == 62
        assert task['due_date'] == (_TODAY - timedelta(days=32)).isoformat()
        assert task['action_href'] == (
            f'/inventory/stock-takes/count?location={shop.shelf_a.id}'
        )

    @pytest.mark.parametrize('reader_offset', [-1, 1])
    def test_a_count_made_minutes_ago_is_not_due_on_any_readers_calendar(
        self, client: TestClient, shop: _Shop, reader_offset: int
    ) -> None:
        # A reader east of UTC is already on tomorrow's date, one west of it
        # still on yesterday's: a count made a minute ago is today's for both.
        shop.every(1)
        shop.counted(shop.shelf_a, 0)
        shop.counted(shop.shelf_b, 0)
        their_today = datetime.now(UTC).date() + timedelta(days=reader_offset)

        assert shop.tasks(client, date_to=their_today.isoformat()) == {}
        done = shop.tasks(client, date_to=their_today.isoformat(), include_done=True)
        assert {subject: Decimal(task['count']) for subject, task in done.items()} == {
            'Pantry › Shelf A': 0,
            'Pantry › Shelf B': 0,
        }
        # A finished count falls due on no day: the next period's day would
        # read as a task a day ahead.
        assert done['Pantry › Shelf A']['due_date'] is None

    @pytest.mark.parametrize('reader_offset', [-1, 1])
    def test_a_count_a_day_old_is_due_on_any_readers_calendar(
        self, client: TestClient, shop: _Shop, reader_offset: int
    ) -> None:
        shop.every(1)
        take = shop.counted(shop.shelf_a, 1)
        take.completed_at = datetime.now(UTC) - timedelta(days=1, minutes=1)
        shop.db.commit()
        shop.counted(shop.shelf_b, 0)
        their_today = datetime.now(UTC).date() + timedelta(days=reader_offset)

        tasks = shop.tasks(client, date_to=their_today.isoformat())

        assert set(tasks) == {'Pantry › Shelf A'}
        assert Decimal(tasks['Pantry › Shelf A']['count']) == 1
        assert tasks['Pantry › Shelf A']['due_date'] == their_today.isoformat()

    def test_a_location_never_counted_is_due_today(
        self, client: TestClient, shop: _Shop
    ) -> None:
        shop.every(14)

        tasks = shop.tasks(client)

        # The bare shelf and the pantry itself hold nothing of their own.
        assert set(tasks) == {'Pantry › Shelf A', 'Pantry › Shelf B'}
        assert tasks['Pantry › Shelf B']['count'] is None
        assert tasks['Pantry › Shelf B']['due_date'] == _TODAY.isoformat()

    def test_a_module_owned_location_waits_for_the_organizations_say_so(
        self, client: TestClient, shop: _Shop
    ) -> None:
        shop.every(14)
        shop.shelf_b.context_tag = 'equipment'
        shop.db.commit()

        # The general screens leave a module's places out by default, and so
        # does To do: the count screen would not offer the rack.
        assert set(shop.tasks(client)) == {'Pantry › Shelf A'}

        shop.org.settings = {**(shop.org.settings or {}), 'show_module_data': True}
        shop.db.commit()
        assert set(shop.tasks(client)) == {'Pantry › Shelf A', 'Pantry › Shelf B'}

    def test_an_open_count_puts_the_task_under_way_and_a_closed_one_done(
        self, client: TestClient, shop: _Shop
    ) -> None:
        shop.every(30)
        shop.counted(shop.shelf_b, 3)
        take = shop.counted(shop.pantry, 0, open_=True)

        under_way = shop.tasks(client)['Pantry › Shelf A']
        assert under_way['state'] == 'in_progress'
        assert under_way['action_href'] == (
            f'/inventory/stock-takes/{take.id}/counting'
        )

        take.status = StockTakeStatus.COMPLETED
        take.completed_at = datetime.now(UTC)
        shop.db.commit()

        assert shop.tasks(client) == {}
        done = shop.tasks(client, include_done=True)
        assert {subject: task['state'] for subject, task in done.items()} == {
            'Pantry › Shelf A': 'done',
            'Pantry › Shelf B': 'done',
        }

    def test_the_locations_say_when_they_were_last_counted(
        self, client: TestClient, shop: _Shop
    ) -> None:
        shop.counted(shop.pantry, 10)
        recent = shop.counted(shop.shelf_a, 2)
        cancelled = shop.counted(shop.shelf_b, 1)
        cancelled.status = StockTakeStatus.CANCELLED
        shop.db.commit()

        response = client.get('/api/v1/stock-takes/locations', headers=shop.headers)

        assert response.status_code == status.HTTP_200_OK, response.text
        by_location = {
            row['location_id']: row['last_counted_at'][:10]
            for row in response.json()['items']
        }
        assert recent.completed_at is not None
        assert (
            by_location[str(shop.shelf_a.id)] == recent.completed_at.date().isoformat()
        )
        tenth = (datetime.now(UTC) - timedelta(days=10)).date().isoformat()
        assert by_location[str(shop.shelf_b.id)] == tenth
        # Nothing was counted on the bare shelf, and nobody closed it.
        assert str(shop.bare.id) not in by_location

    def test_a_count_that_counted_everything_dates_the_location_it_was_opened_on(
        self, client: TestClient, shop: _Shop
    ) -> None:
        # The pantry holds nothing of its own; a count of it that counted
        # every row it covered is still a count of the pantry.
        take = shop.counted(shop.pantry, 2)
        partial = shop.counted(shop.bare, 1, shelves=[], uncounted=[shop.shelf_a])

        response = client.get('/api/v1/stock-takes/locations', headers=shop.headers)

        by_location = {
            row['location_id']: row['last_counted_at']
            for row in response.json()['items']
        }
        assert take.completed_at is not None
        assert by_location[str(shop.pantry.id)][:10] == (
            take.completed_at.date().isoformat()
        )
        # A count that left a row waiting is no proof for its own location.
        assert partial.completed_at is not None
        assert str(shop.bare.id) not in by_location

    def test_a_closed_count_that_counted_nothing_on_a_shelf_dates_nothing(
        self, client: TestClient, shop: _Shop
    ) -> None:
        shop.every(30)
        shop.counted(shop.shelf_b, 3)
        # A partial count of the pantry closed with shelf A's rows waiting.
        shop.counted(shop.pantry, 0, shelves=[shop.shelf_b], uncounted=[shop.shelf_a])

        assert set(shop.tasks(client)) == {'Pantry › Shelf A'}
        response = client.get('/api/v1/stock-takes/locations', headers=shop.headers)
        assert str(shop.shelf_a.id) not in {
            row['location_id'] for row in response.json()['items']
        }

    def test_a_shelf_partly_counted_is_not_counted(
        self, client: TestClient, shop: _Shop
    ) -> None:
        shop.every(30)
        shop.counted(shop.shelf_b, 3)
        shop.stock(client, shop.shelf_a, 'Flour')
        take = shop.counted(shop.shelf_a, 0)
        # One of shelf A's two records was never counted.
        row = shop.db.query(StockTakeItem).filter_by(stock_take_id=take.id).first()
        assert row is not None
        row.counted_quantity = None
        shop.db.commit()

        assert set(shop.tasks(client)) == {'Pantry › Shelf A'}

    def test_a_count_from_a_schedule_dates_nothing(
        self, client: TestClient, shop: _Shop
    ) -> None:
        # A schedule may sample a few records or one category, so what it
        # counted says nothing about everything else on the shelf.
        shop.every(30)
        schedule = CycleCountSchedule(
            organization_id=shop.org.id, name='Pantry sample', created_by=shop.user.id
        )
        shop.db.add(schedule)
        shop.db.commit()
        shop.counted(shop.pantry, 0, schedule_id=schedule.id)

        assert set(shop.tasks(client)) == {'Pantry › Shelf A', 'Pantry › Shelf B'}

    def test_a_shelf_added_after_the_count_is_due(
        self, client: TestClient, shop: _Shop
    ) -> None:
        shop.every(30)
        shop.counted(shop.pantry, 5)
        h = ModuleTestHelper(shop.db)
        storage_type = h.create_storage_type('Bin', 'BIN', organization_id=shop.org.id)
        later = shop._below(h, storage_type, 'Shelf C')
        shop.stock(client, later, 'Sugar')

        tasks = shop.tasks(client)

        assert set(tasks) == {'Pantry › Shelf C'}
        assert tasks['Pantry › Shelf C']['count'] is None

    def test_a_shelf_the_counter_closed_is_counted_even_when_empty(
        self, client: TestClient, shop: _Shop
    ) -> None:
        take = shop.counted(shop.bare, 4)
        shop.db.add(
            StockTakeClosedLocation(
                stock_take_id=take.id,
                storage_location_id=shop.bare.id,
                path='Pantry › Bare shelf',
                empty=True,
            )
        )
        shop.db.commit()

        response = client.get('/api/v1/stock-takes/locations', headers=shop.headers)

        by_location = {
            row['location_id']: row['last_counted_at']
            for row in response.json()['items']
        }
        assert set(by_location) == {str(shop.bare.id)}
