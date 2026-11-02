"""A mixed shelf is full when its products' shares add up to 100%.

The planner used to ask one product at a time: rice limited to 40 and plums
to 50 kg on one shelf, 20 rice and 25 kg plums standing there, and each
product alone read half full — so the shelf kept receiving while it was
physically full. A shelf now has room for a quantity q of product P only
while the sum of the shares already there plus q / limit(P) stays within 1.
A line goes to one shelf whole: one that only partly fits sends the line on
to the next shelf in the rule.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlalchemy.orm import Session

from app.models.organization import Organization
from app.models.partner import Partner
from app.models.storage_location import StorageLocation
from app.models.user import User

from .test_putaway_rule_location_list import (
    _categorised_item,
    _confirmed_in,
    _put_capacity,
    _rule_with_locations,
    _stock_shelf,
)
from .test_receipt_line_target import _make_category, _make_location


class _Shelves:
    """Rice and plums in one category, a rule over two shelves, and the
    first shelf limiting both products."""

    def __init__(
        self,
        client: TestClient,
        headers: dict[str, str],
        db: Session,
        engine: AsyncEngine,
        org: Organization,
        user: User,
        target: StorageLocation,
        partner: Partner,
        *,
        plum_limit: str | None = '50',
    ) -> None:
        from app.core.testing import ModuleTestHelper

        self._client, self._headers = client, headers
        self._db, self._engine, self._org = db, engine, org
        self._target, self._partner = target, partner
        h = ModuleTestHelper(db)
        tag = uuid4().hex[:6]
        self.category = _make_category(db, org, f'MIX {tag}')
        self.rice = h.create_template(org, name=f'MIX Rice {tag}')
        self.plums = h.create_template(org, name=f'MIX Plums {tag}')
        self.first = _make_location(db, org, target, user, f'MIX First {tag}')
        self.second = _make_location(db, org, target, user, f'MIX Second {tag}')
        _rule_with_locations(
            client,
            headers,
            category_id=self.category,
            location_ids=[self.first, self.second],
        )
        _put_capacity(
            client,
            headers,
            location_id=self.first,
            template_id=self.rice.id,
            max_quantity='40',
        )
        if plum_limit is not None:
            _put_capacity(
                client,
                headers,
                location_id=self.first,
                template_id=self.plums.id,
                max_quantity=plum_limit,
            )
        self.rice_item = _categorised_item(db, org, target, self.category, self.rice.id)
        self.plum_item = _categorised_item(
            db, org, target, self.category, self.plums.id
        )

    def stock(self, template: Any, quantity: str) -> None:
        _stock_shelf(
            self._db,
            self._engine,
            org=self._org,
            location=self.first,
            template_id=template.id,
            quantity=quantity,
        )

    def plan(self, *lines: tuple[Any, int]) -> list[dict[str, Any]]:
        doc_id = _confirmed_in(
            self._client,
            self._headers,
            partner=self._partner,
            target_location=self._target,
            item=lines[0][0],
            lines=[
                {'item_id': str(item.id), 'expected_quantity': qty}
                for item, qty in lines
            ],
        )
        read = self._client.get(
            f'/api/v1/warehouse/documents/{doc_id}', headers=self._headers
        )
        return list(read.json()['lines'])


@pytest.fixture
def shelves(
    client: TestClient,
    doc_auth_headers: dict[str, str],
    db_session: Session,
    async_engine_fixture: AsyncEngine,
    doc_org: Organization,
    doc_user: User,
    doc_target_location: StorageLocation,
    doc_partner: Partner,
) -> Any:
    def build(**kwargs: Any) -> _Shelves:
        return _Shelves(
            client,
            doc_auth_headers,
            db_session,
            async_engine_fixture,
            doc_org,
            doc_user,
            doc_target_location,
            doc_partner,
            **kwargs,
        )

    return build


@pytest.mark.integration
class TestMixedShelfFill:
    def test_a_shelf_full_by_the_sum_sends_the_line_on(self, shelves: Any) -> None:
        """20/40 rice + 25/50 plums = 100%: one more kilo of plums goes to
        the second shelf, although plums alone are half their limit.

        What it fails on: asked per product, 25 + 1 <= 50 and the line
        planned onto the full first shelf."""
        s = shelves()
        s.stock(s.rice, '20')
        s.stock(s.plums, '25')
        [line] = s.plan((s.plum_item, 1))
        assert line['planned_location_id'] == str(s.second.id), line
        assert line['planned_over_capacity'] is None

    def test_a_partial_fit_moves_the_whole_line_to_the_next_shelf(
        self, shelves: Any
    ) -> None:
        """20/40 rice + 20/50 plums = 90%: room for 5 kg of plums. Five go
        on the first shelf; ten do not fit there and go on whole."""
        s = shelves()
        s.stock(s.rice, '20')
        s.stock(s.plums, '20')
        [fits] = s.plan((s.plum_item, 5))
        assert fits['planned_location_id'] == str(s.first.id), fits
        [spills] = s.plan((s.plum_item, 10))
        assert spills['planned_location_id'] == str(s.second.id), spills

    def test_two_products_of_one_delivery_count_together(self, shelves: Any) -> None:
        """An empty shelf, 20 rice (50%) then 30 kg plums (60%): the second
        line no longer fits beside what the first one already sent."""
        s = shelves()
        rice, plums = s.plan((s.rice_item, 20), (s.plum_item, 30))
        assert rice['planned_location_id'] == str(s.first.id), rice
        assert plums['planned_location_id'] == str(s.second.id), plums

    def test_a_product_without_a_limit_adds_no_share(self, shelves: Any) -> None:
        """Plums stand on the shelf with no limit of their own: rice still
        has its whole 40 there, and not one more."""
        s = shelves(plum_limit=None)
        s.stock(s.plums, '25')
        [whole] = s.plan((s.rice_item, 40))
        assert whole['planned_location_id'] == str(s.first.id), whole
        [over] = s.plan((s.rice_item, 41))
        assert over['planned_location_id'] == str(s.second.id), over

    def test_an_over_full_mixed_shelf_says_its_whole_fill(self, shelves: Any) -> None:
        """Both shelves too full: the plan falls back to the first with the
        over-capacity mark, and names the shelf's fill — the sum — because
        rice's own 20/40 cannot explain why it is full. The fill counts the
        incoming line: the sentence says how full the shelf will be.

        What it fails on: a fill read before the line, 110 for a shelf the
        two kilos take to 115."""
        s = shelves()
        s.stock(s.rice, '20')
        s.stock(s.plums, '30')
        # Fill the second shelf too, with a single-product promise.
        s._client.put(
            f'/api/v1/warehouse/putaway/capacity-settings/{s.second.id}',
            headers=s._headers,
            json={'single_product': True},
        )
        _stock_shelf(
            s._db,
            s._engine,
            org=s._org,
            location=s.second,
            template_id=s.plums.id,
            quantity='1',
        )
        [line] = s.plan((s.rice_item, 2))
        assert line['planned_location_id'] == str(s.first.id), line
        assert line['planned_over_capacity'] is True
        assert line['planned_shelf_fill'] == 115
        assert Decimal(line['planned_capacity_max']) == Decimal('40')
