"""The occupancy overview: the whole floor in one answer.

The screen shows every warehouse, zone and shelf at once, as a tree and as a
heat map. The server rolls the shelves up so the browser never adds up
thousands of rows, and answers in a number of queries that does not depend
on how many locations there are — asserted here on a seeded tree of two
thousand shelves, not assumed.
"""

from __future__ import annotations

import time
from decimal import Decimal
from typing import Any
from uuid import uuid4

import pytest
from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlalchemy.orm import Session

from app.models.item import Item
from app.models.organization import Organization
from app.models.stock_anchor import StockAnchor
from app.models.storage_location import StorageLocation
from app.models.user import User
from app.modules.warehouse.models import PutawayCapacity

from .test_putaway_rule_location_list import _put_capacity, _stock_shelf
from .test_receipt_line_target import _make_location

pytestmark = pytest.mark.integration

URL = '/api/v1/warehouse/putaway/occupancy'


def _by_name(body: dict[str, Any], prefix: str) -> dict[str, dict[str, Any]]:
    return {n['name']: n for n in body['nodes'] if n['name'].startswith(prefix)}


class TestOccupancyOverview:
    def test_rolls_the_shelves_up_to_zone_and_warehouse(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        db_session: Session,
        async_engine_fixture: AsyncEngine,
        doc_org: Organization,
        doc_user: User,
    ) -> None:
        """A zone counts its shelves, the ones with a limit, the full, the
        over-limit and the empty; its average is taken over the limited
        shelves only, an unlimited shelf adding nothing to it."""
        from app.core.testing import ModuleTestHelper

        tag = uuid4().hex[:6]
        h = ModuleTestHelper(db_session)
        rice = h.create_template(doc_org, name=f'OV rice {tag}')
        plums = h.create_template(doc_org, name=f'OV plums {tag}')

        def make(name: str, parent: StorageLocation, **kw: object) -> StorageLocation:
            return _make_location(
                db_session,
                doc_org,
                doc_target_location,
                doc_user,
                f'OV {tag} {name}',
                parent_id=parent.id,
                **kw,
            )

        zone = make('Zone', doc_target_location)
        half = make('Half', zone, sequence=10)  # 50%
        mixed = make('Mixed', zone, sequence=20)  # 50% + 50% = 100%
        over = make('Over', zone, sequence=30)  # 150%
        bare = make('Bare', zone, sequence=40)  # stock, no limit
        empty = make('Empty', zone, sequence=50)  # nothing at all

        _put_capacity(
            client,
            doc_auth_headers,
            location_id=half,
            template_id=rice.id,
            max_quantity='100',
        )
        _stock_shelf(
            db_session,
            async_engine_fixture,
            org=doc_org,
            location=half,
            template_id=rice.id,
            quantity='50',
        )
        _put_capacity(
            client,
            doc_auth_headers,
            location_id=mixed,
            template_id=rice.id,
            max_quantity='100',
        )
        _put_capacity(
            client,
            doc_auth_headers,
            location_id=mixed,
            template_id=plums.id,
            max_quantity='40',
        )
        _stock_shelf(
            db_session,
            async_engine_fixture,
            org=doc_org,
            location=mixed,
            template_id=rice.id,
            quantity='50',
        )
        _stock_shelf(
            db_session,
            async_engine_fixture,
            org=doc_org,
            location=mixed,
            template_id=plums.id,
            quantity='20',
        )
        _put_capacity(
            client,
            doc_auth_headers,
            location_id=over,
            template_id=rice.id,
            max_quantity='10',
        )
        _stock_shelf(
            db_session,
            async_engine_fixture,
            org=doc_org,
            location=over,
            template_id=rice.id,
            quantity='15',
        )
        _stock_shelf(
            db_session,
            async_engine_fixture,
            org=doc_org,
            location=bare,
            template_id=plums.id,
            quantity='7',
        )

        read = client.get(URL, headers=doc_auth_headers)
        assert read.status_code == status.HTTP_200_OK, read.text
        body = read.json()
        nodes = _by_name(body, f'OV {tag}')

        zone_node = nodes[f'OV {tag} Zone']
        assert zone_node['summary'] == {
            'shelves': 5,
            'with_limit': 3,
            'full': 2,
            'over': 1,
            'empty': 1,
            # (50 + 100 + 100) / 3: the over-limit shelf counts as 100.
            'average_fill': 83,
        }
        assert zone_node['cell'] is None

        cell = nodes[f'OV {tag} Mixed']['cell']
        assert cell['fill'] == 100
        assert cell['status'] == 'nearly_full'
        assert sorted(e['share'] for e in cell['entries']) == [50, 50]
        assert {e['product_template_name'] for e in cell['entries']} == {
            rice.name,
            plums.name,
        }

        bare_cell = nodes[f'OV {tag} Bare']['cell']
        assert bare_cell['fill'] is None
        assert bare_cell['status'] == 'no_limit'
        assert nodes[f'OV {tag} Empty']['cell']['status'] == 'empty'

        # Children follow their parent, in walk order, one level deeper.
        names = [n['name'] for n in body['nodes'] if n['name'].startswith(f'OV {tag}')]
        assert names == [
            f'OV {tag} {s}' for s in ('Zone', 'Half', 'Mixed', 'Over', 'Bare', 'Empty')
        ]
        assert zone_node['depth'] == nodes[f'OV {tag} Half']['depth'] - 1
        assert nodes[f'OV {tag} Half']['parent_id'] == str(zone.id)

        # The totals cover the warehouse these shelves hang under.
        assert body['totals']['shelves'] >= 5
        assert empty.id  # keep the fixture referenced

    def test_counts_the_products_it_does_not_list(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        db_session: Session,
        async_engine_fixture: AsyncEngine,
        doc_org: Organization,
        doc_user: User,
    ) -> None:
        """The floor's cells carry their fill, not their contents: a shelf
        lists the products its bar is made of and the one product it holds
        when it holds one, and counts the rest. The shelf's own read lists
        them all, for the reader who opens it."""
        from app.core.testing import ModuleTestHelper

        tag = uuid4().hex[:6]
        h = ModuleTestHelper(db_session)
        rice, plums, salt = (
            h.create_template(doc_org, name=f'OV {name} {tag}')
            for name in ('rice', 'plums', 'salt')
        )

        def make(name: str) -> StorageLocation:
            return _make_location(
                db_session,
                doc_org,
                doc_target_location,
                doc_user,
                f'OV {tag} {name}',
                parent_id=doc_target_location.id,
            )

        mixed, single = make('Mixed'), make('Single')
        _put_capacity(
            client,
            doc_auth_headers,
            location_id=mixed,
            template_id=rice.id,
            max_quantity='100',
        )
        for template, quantity in ((rice, '50'), (plums, '7'), (salt, '3')):
            _stock_shelf(
                db_session,
                async_engine_fixture,
                org=doc_org,
                location=mixed,
                template_id=template.id,
                quantity=quantity,
            )
        _stock_shelf(
            db_session,
            async_engine_fixture,
            org=doc_org,
            location=single,
            template_id=salt.id,
            quantity='4',
        )

        body = client.get(URL, headers=doc_auth_headers).json()
        nodes = _by_name(body, f'OV {tag}')

        cell = nodes[f'OV {tag} Mixed']['cell']
        assert cell['products'] == 3
        assert [e['product_template_name'] for e in cell['entries']] == [rice.name]
        assert cell['fill'] == 50
        assert cell['status'] == 'ok'
        # Plums and salt stand there with no limit of their own.
        assert cell['unmeasured'] is True

        lone = nodes[f'OV {tag} Single']['cell']
        assert lone['products'] == 1
        assert lone['status'] == 'no_limit'
        assert [
            (e['product_template_name'], e['quantity']) for e in lone['entries']
        ] == [(salt.name, '4.000')]

        opened = client.get(f'{URL}/{mixed.id}', headers=doc_auth_headers)
        assert opened.status_code == status.HTTP_200_OK, opened.text
        (shelf,) = opened.json()['locations']
        assert shelf['products'] == 3
        assert {e['product_template_name'] for e in shelf['entries']} == {
            rice.name,
            plums.name,
            salt.name,
        }

    def test_the_cost_does_not_grow_with_the_tree(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        db_session: Session,
        async_engine_fixture: AsyncEngine,
        doc_org: Organization,
        doc_user: User,
    ) -> None:
        """Two thousand shelves, a third of them limited and stocked: the
        answer takes the same handful of statements it takes for ten, and
        arrives fast enough that the screen can ask for all of it at once."""
        from app.core.testing import ModuleTestHelper

        tag = uuid4().hex[:6]
        h = ModuleTestHelper(db_session)
        template = h.create_template(doc_org, name=f'OV big {tag}')

        def statements() -> int:
            seen = {'n': 0}

            def count(*_: object) -> None:
                seen['n'] += 1

            event.listen(
                async_engine_fixture.sync_engine, 'before_cursor_execute', count
            )
            try:
                resp = client.get(URL, headers=doc_auth_headers)
            finally:
                event.remove(
                    async_engine_fixture.sync_engine, 'before_cursor_execute', count
                )
            assert resp.status_code == status.HTTP_200_OK, resp.text
            return seen['n']

        # One limited, stocked shelf first, so the small read takes the same
        # paths the large one does (a tree with no product skips the lookups).
        lone = _make_location(
            db_session,
            doc_org,
            doc_target_location,
            doc_user,
            f'OV {tag} lone',
            parent_id=doc_target_location.id,
        )
        _put_capacity(
            client,
            doc_auth_headers,
            location_id=lone,
            template_id=template.id,
            max_quantity='10',
        )
        _stock_shelf(
            db_session,
            async_engine_fixture,
            org=doc_org,
            location=lone,
            template_id=template.id,
            quantity='5',
        )
        small = statements()

        zones = []
        for z in range(20):
            zone = StorageLocation(
                organization_id=doc_org.id,
                storage_type_id=doc_target_location.storage_type_id,
                created_by=doc_user.id,
                name=f'OV {tag} Z{z:02d}',
                parent_id=doc_target_location.id,
            )
            db_session.add(zone)
            zones.append(zone)
        db_session.flush()
        shelves = []
        for zone in zones:
            for s in range(100):
                shelves.append(
                    StorageLocation(
                        organization_id=doc_org.id,
                        storage_type_id=doc_target_location.storage_type_id,
                        created_by=doc_user.id,
                        name=f'{zone.name} S{s:03d}',
                        parent_id=zone.id,
                        sequence=s,
                    )
                )
        db_session.add_all(shelves)
        db_session.flush()
        for index, shelf in enumerate(shelves):
            if index % 3:
                continue
            db_session.add(
                PutawayCapacity(
                    organization_id=doc_org.id,
                    location_id=shelf.id,
                    product_template_id=template.id,
                    max_quantity=Decimal('100'),
                )
            )
            db_session.add(
                StockAnchor(
                    organization_id=doc_org.id,
                    product_template_id=template.id,
                    storage_location_id=shelf.id,
                )
            )
            db_session.flush()
            db_session.add(
                Item(
                    name=f'OV big {index}',
                    organization_id=doc_org.id,
                    storage_location_id=shelf.id,
                    template_id=template.id,
                    quantity=Decimal(index % 120),
                )
            )
        db_session.commit()

        started = time.perf_counter()
        large = statements()
        elapsed = time.perf_counter() - started

        assert large == small, (small, large)
        assert elapsed < 5, elapsed
        body = client.get(URL, headers=doc_auth_headers).json()
        assert body['totals']['shelves'] >= 2000
