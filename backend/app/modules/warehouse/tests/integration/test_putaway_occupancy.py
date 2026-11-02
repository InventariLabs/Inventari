"""Occupancy of capped locations, as a view and as signals.

The company overview wants to say "A-12 is 95% full" and "3 receipt lines
have nowhere to go". The occupancy read turns the capacity entries and the
stock ledger into those two sentences: per location, the stock of every
capped product against the caps; across the organization's open receipts,
the lines whose plan is over capacity.

The number in the cell is the sum of the product's stock at that location
— asserted here against seeded data, not against a screenshot. A location
with no capacity entry has no percentage at all: an unlimited shelf's
fill is not zero, it is undefined, and inventing one from a count of
things would be a lie with a colour on it.

A shelf limiting several products reports the sum of their shares — each
product's stock over its own limit — the same sum the putaway planner
decides by. The limits themselves are never added: they are declared per
product in that product's own stock unit, and adding them adds kilograms
to pieces.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

import pytest
from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlalchemy.orm import Session

from app.models.item import Item
from app.models.organization import Organization
from app.models.partner import Partner
from app.models.storage_location import StorageLocation
from app.models.user import User
from app.modules.warehouse.tests.integration._records import (
    sow as _sow,
)

from .test_putaway_rule_location_list import (
    _categorised_item,
    _confirmed_in,
    _put_capacity,
    _rule_with_locations,
    _stock_shelf,
)
from .test_receipt_line_target import _make_category, _make_location


@pytest.mark.integration
class TestPutawayOccupancy:
    def test_cells_carry_the_stock_sum_against_the_cap(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        db_session: Session,
        async_engine_fixture: AsyncEngine,
        doc_org: Organization,
        doc_user: User,
    ) -> None:
        """Three shelves: one 190/200, one capped and empty, one with seven
        records but no cap — the first two read numbers, the third refuses
        to invent a percentage."""
        from app.core.testing import ModuleTestHelper

        h = ModuleTestHelper(db_session)
        template = h.create_template(doc_org, name=f'PAW6 {uuid4().hex[:6]}')
        parent = {'parent_id': doc_target_location.id}
        full = _make_location(
            db_session, doc_org, doc_target_location, doc_user, 'PAW6 Full', **parent
        )
        empty = _make_location(
            db_session, doc_org, doc_target_location, doc_user, 'PAW6 Empty', **parent
        )
        uncapped = _make_location(
            db_session,
            doc_org,
            doc_target_location,
            doc_user,
            'PAW6 Uncapped',
            **parent,
        )
        _put_capacity(
            client,
            doc_auth_headers,
            location_id=full,
            template_id=template.id,
            max_quantity='200',
        )
        _put_capacity(
            client,
            doc_auth_headers,
            location_id=empty,
            template_id=template.id,
            max_quantity='50',
        )
        _stock_shelf(
            db_session,
            async_engine_fixture,
            org=doc_org,
            location=full,
            template_id=template.id,
            quantity='190',
        )
        # Seven records on the uncapped shelf — a count of things, not a fill.
        for _ in range(7):
            db_session.add(
                Item(
                    name=f'PAW6 loose {uuid4().hex[:6]}',
                    organization_id=doc_org.id,
                    storage_location_id=uncapped.id,
                    quantity=Decimal('1'),
                )
            )
        db_session.commit()

        read = client.get(
            f'/api/v1/warehouse/putaway/occupancy/{doc_target_location.id}',
            headers=doc_auth_headers,
        )
        assert read.status_code == status.HTTP_200_OK, read.text
        body = read.json()
        cells = {c['location_id']: c for c in body['locations']}
        assert Decimal(cells[str(full.id)]['capacity_used']) == Decimal('190')
        assert Decimal(cells[str(full.id)]['capacity_max']) == Decimal('200')
        assert Decimal(cells[str(empty.id)]['capacity_used']) == Decimal('0')
        assert cells[str(uncapped.id)]['capacity_max'] is None
        assert cells[str(uncapped.id)]['fill'] is None

    def test_a_limit_speaks_the_unit_of_its_product(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        db_session: Session,
        doc_org: Organization,
        doc_user: User,
    ) -> None:
        """The pair under a shelf's percentage is counted in the product's
        unit, so the read names it — and names none for a product that has
        none. The overview of the whole floor always did; the read of one
        location left every entry without a unit, and the location settings
        tab printed "0/10" two columns from a limit that says "10 kg"."""
        from app.core.testing import ModuleTestHelper

        h = ModuleTestHelper(db_session)
        flour = h.create_template(
            doc_org, name=f'PAW12 {uuid4().hex[:6]}', uom_id=h.get_uom('kg').id
        )
        bolts = h.create_template(doc_org, name=f'PAW12b {uuid4().hex[:6]}')
        shelf = _make_location(
            db_session,
            doc_org,
            doc_target_location,
            doc_user,
            'PAW12 Unit',
            parent_id=doc_target_location.id,
        )
        for template in (flour, bolts):
            _put_capacity(
                client,
                doc_auth_headers,
                location_id=shelf,
                template_id=template.id,
                max_quantity='10',
            )

        read = client.get(
            f'/api/v1/warehouse/putaway/occupancy/{doc_target_location.id}',
            headers=doc_auth_headers,
        )

        assert read.status_code == status.HTTP_200_OK, read.text
        cell = next(
            c for c in read.json()['locations'] if c['location_id'] == str(shelf.id)
        )
        units = {
            e['product_template_id']: e['product_unit_symbol'] for e in cell['entries']
        }
        assert units == {str(flour.id): 'kg', str(bolts.id): None}

    def test_quantities_arrive_as_text_like_every_other_read(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        db_session: Session,
        async_engine_fixture: AsyncEngine,
        doc_org: Organization,
        doc_user: User,
    ) -> None:
        """The numbers cross the wire as strings, the way every other
        decimal in this module does.

        This endpoint used to be declared without a ``response_model``, so
        it had no schema in OpenAPI at all: ``make check-api-types`` had
        nothing to compare, and the frontend carried a hand-written
        interface in place of a generated one. Adding the model closes that,
        and this pins the one thing a generated type would otherwise be
        trusted for blindly.

        What it fails on: a model that types these fields ``float``, or a
        response built to bypass the model. Measured: it is green both with
        and without the ``response_model`` — the wire type did not change,
        only who guarantees it. The assertion is on the JSON type rather
        than the value, because a value check reads the same either way.
        """
        from app.core.testing import ModuleTestHelper

        h = ModuleTestHelper(db_session)
        # A decimal unit: 12.5 has to pass the UOM gate the items service
        # enforces on the way in (pcs takes whole numbers only).
        template = h.create_template(
            doc_org, name=f'PAW11 {uuid4().hex[:6]}', uom_id=h.get_uom('kg').id
        )
        shelf = _make_location(
            db_session,
            doc_org,
            doc_target_location,
            doc_user,
            'PAW11 Typed',
            parent_id=doc_target_location.id,
        )
        _put_capacity(
            client,
            doc_auth_headers,
            location_id=shelf,
            template_id=template.id,
            max_quantity='100',
        )
        _stock_shelf(
            db_session,
            async_engine_fixture,
            org=doc_org,
            location=shelf,
            template_id=template.id,
            quantity='12.5',
        )

        read = client.get(
            f'/api/v1/warehouse/putaway/occupancy/{doc_target_location.id}',
            headers=doc_auth_headers,
        )
        assert read.status_code == status.HTTP_200_OK, read.text
        cell = {c['location_id']: c for c in read.json()['locations']}[str(shelf.id)]
        assert isinstance(cell['capacity_used'], str), cell['capacity_used']
        assert isinstance(cell['capacity_max'], str), cell['capacity_max']
        assert isinstance(cell['entries'][0]['quantity'], str)
        assert Decimal(cell['capacity_used']) == Decimal('12.5')

    def test_two_batches_of_one_product_are_added_together(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        db_session: Session,
        async_engine_fixture: AsyncEngine,
        doc_org: Organization,
        doc_user: User,
    ) -> None:
        """The cell says "sum", so two batches of one product on one shelf
        have to arrive as one number.

        A shelf holds one quant per (product, batch) — two deliveries of the
        same product are two rows, and that is the only way one shelf can
        hold the same product twice. Every earlier case seeded a single
        quant, so returning the first row instead of the total passed them
        all. 60 and 30 against a cap of 100 is 90; a first-row read answers
        60, and a shelf one delivery from full reads as comfortably empty.

        What it fails on: the accumulation that folds a shelf's quants into
        one number per (shelf, product). Replace that ``+=`` with an
        assignment and this reads 60/100 at 60% fill. It is green both
        before and after the change that made a mixed shelf report its
        fullest product — that line was never the one at fault, and this
        test pins it so it stays right.
        """
        from app.core.testing import ModuleTestHelper
        from app.models.stock_lot import StockLot

        h = ModuleTestHelper(db_session)
        template = h.create_template(doc_org, name=f'PAW9 {uuid4().hex[:6]}')
        shelf = _make_location(
            db_session,
            doc_org,
            doc_target_location,
            doc_user,
            'PAW9 Two batches',
            parent_id=doc_target_location.id,
        )
        _put_capacity(
            client,
            doc_auth_headers,
            location_id=shelf,
            template_id=template.id,
            max_quantity='100',
        )
        for amount in ('60', '30'):
            lot = StockLot(
                organization_id=doc_org.id,
                product_template_id=template.id,
                name=f'PAW9-{uuid4().hex[:6]}',
            )
            db_session.add(lot)
            db_session.flush()
            _sow(
                db_session,
                async_engine_fixture,
                doc_org,
                template,
                shelf.id,
                Decimal(amount),
                lot_id=lot.id,
            )
        db_session.commit()

        read = client.get(
            f'/api/v1/warehouse/putaway/occupancy/{doc_target_location.id}',
            headers=doc_auth_headers,
        )
        assert read.status_code == status.HTTP_200_OK, read.text
        cell = {c['location_id']: c for c in read.json()['locations']}[str(shelf.id)]
        assert Decimal(cell['capacity_used']) == Decimal('90')
        assert cell['fill'] == 90

    def test_a_mixed_shelf_reports_the_sum_of_the_products_shares(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        db_session: Session,
        async_engine_fixture: AsyncEngine,
        doc_org: Organization,
        doc_user: User,
    ) -> None:
        """Rice 20 of 40 and plums 25 of 50 on one shelf: each half full,
        the shelf full. A third product stands there with no limit: it adds
        no share, and the cell says part of the shelf is unmeasured.

        What it fails on: the cell used to speak for the fullest product
        alone and read 50 where the planner — and the shelf — say 100.
        """
        from app.core.testing import ModuleTestHelper

        h = ModuleTestHelper(db_session)
        rice = h.create_template(doc_org, name=f'PAW9 Rice {uuid4().hex[:6]}')
        plums = h.create_template(doc_org, name=f'PAW9 Plums {uuid4().hex[:6]}')
        loose = h.create_template(doc_org, name=f'PAW9 Loose {uuid4().hex[:6]}')
        shelf = _make_location(
            db_session,
            doc_org,
            doc_target_location,
            doc_user,
            'PAW9 Mixed',
            parent_id=doc_target_location.id,
        )
        for template_id, cap, stocked in (
            (rice.id, '40', '20'),
            (plums.id, '50', '25'),
            (loose.id, None, '7'),
        ):
            if cap is not None:
                _put_capacity(
                    client,
                    doc_auth_headers,
                    location_id=shelf,
                    template_id=template_id,
                    max_quantity=cap,
                )
            _stock_shelf(
                db_session,
                async_engine_fixture,
                org=doc_org,
                location=shelf,
                template_id=template_id,
                quantity=stocked,
            )

        read = client.get(
            f'/api/v1/warehouse/putaway/occupancy/{doc_target_location.id}',
            headers=doc_auth_headers,
        )
        assert read.status_code == status.HTTP_200_OK, read.text
        cell = {c['location_id']: c for c in read.json()['locations']}[str(shelf.id)]
        assert cell['fill'] == 100
        assert cell['status'] == 'nearly_full'
        assert cell['unmeasured'] is True
        assert cell['capped_products'] == 2
        shares = {e['product_template_id']: e for e in cell['entries']}
        assert shares[str(rice.id)]['share'] == 50
        assert shares[str(plums.id)]['share'] == 50
        assert shares[str(loose.id)]['share'] is None
        assert shares[str(loose.id)]['max_quantity'] is None
        assert Decimal(shares[str(loose.id)]['quantity']) == Decimal('7')
        # A full shelf is a sentence the overview quotes.
        over = [
            s
            for s in read.json()['signals']
            if s['code'] == 'location_over_capacity'
            and s['location_id'] == str(shelf.id)
        ]
        assert over and over[0]['fill'] == 100

    def test_full_location_raises_a_signal(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        db_session: Session,
        async_engine_fixture: AsyncEngine,
        doc_org: Organization,
        doc_user: User,
    ) -> None:
        """95% full is a sentence the overview can quote: which shelf, how
        full."""
        from app.core.testing import ModuleTestHelper

        h = ModuleTestHelper(db_session)
        template = h.create_template(doc_org, name=f'PAW6 s {uuid4().hex[:6]}')
        full = _make_location(
            db_session,
            doc_org,
            doc_target_location,
            doc_user,
            'PAW6 Sig',
            parent_id=doc_target_location.id,
        )
        _put_capacity(
            client,
            doc_auth_headers,
            location_id=full,
            template_id=template.id,
            max_quantity='200',
        )
        _stock_shelf(
            db_session,
            async_engine_fixture,
            org=doc_org,
            location=full,
            template_id=template.id,
            quantity='190',
        )

        read = client.get(
            f'/api/v1/warehouse/putaway/occupancy/{doc_target_location.id}',
            headers=doc_auth_headers,
        )
        signals = read.json()['signals']
        over = [s for s in signals if s['code'] == 'location_over_capacity']
        assert len(over) == 1
        assert over[0]['location_name'] == 'PAW6 Sig'
        assert over[0]['fill'] == 95

    def test_receipt_lines_without_space_are_counted(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        db_session: Session,
        async_engine_fixture: AsyncEngine,
        doc_org: Organization,
        doc_user: User,
    ) -> None:
        """An open receipt whose every rule shelf is full counts as a line
        with nowhere to go — the second sentence the overview quotes."""
        from app.core.testing import ModuleTestHelper

        h = ModuleTestHelper(db_session)
        category = _make_category(db_session, doc_org, f'PAW6 c {uuid4().hex[:6]}')
        template = h.create_template(doc_org, name=f'PAW6 c {uuid4().hex[:6]}')
        first = _make_location(
            db_session,
            doc_org,
            doc_target_location,
            doc_user,
            'PAW6 C1',
            parent_id=doc_target_location.id,
        )
        _rule_with_locations(
            client, doc_auth_headers, category_id=category, location_ids=[first]
        )
        _put_capacity(
            client,
            doc_auth_headers,
            location_id=first,
            template_id=template.id,
            max_quantity='20',
        )
        _stock_shelf(
            db_session,
            async_engine_fixture,
            org=doc_org,
            location=first,
            template_id=template.id,
            quantity='20',
        )
        item = _categorised_item(
            db_session, doc_org, doc_target_location, category, template.id
        )
        _confirmed_in(
            client,
            doc_auth_headers,
            partner=doc_partner,
            target_location=doc_target_location,
            item=item,
        )

        read = client.get(
            f'/api/v1/warehouse/putaway/occupancy/{doc_target_location.id}',
            headers=doc_auth_headers,
        )
        assert read.status_code == status.HTTP_200_OK, read.text
        signals = read.json()['signals']
        stuck = [s for s in signals if s['code'] == 'receipt_lines_without_space']
        assert len(stuck) == 1
        assert stuck[0]['count'] == 1
