"""The refusal tells the truth about when the shortage appeared.

An order for 1000 candles against stock for 30 used to be refused with
"These ingredients ran out since the draft was created" — history nobody
lived through. The order records, at birth, whether its planned consumption
already exceeded stock; the refusal's ``short_at_create`` lets the sentence
distinguish "never enough" from "ran out since".
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.organization import Organization
from app.models.storage_location import StorageLocation
from app.modules.maker.models import ProductionOrder
from tests.integration._far_clock import zone_where_today_differs

from .test_production_audit import _seed_run

pytestmark = pytest.mark.integration


def _get_flag(db: Session, order_id: str) -> bool:
    order = db.execute(
        select(ProductionOrder).where(ProductionOrder.id == order_id)
    ).scalar_one()
    return order.short_at_create


class TestClosingFacts:
    def test_completed_run_gets_a_production_date(
        self,
        client: TestClient,
        mk_org: Organization,
        mk_auth_headers: dict[str, str],
        mk_input_loc: StorageLocation,
        mk_output_loc: StorageLocation,
        db_session: Session,
    ) -> None:
        """The date is optional at planning and known to the day at closing.

        A finished run used to show "PRODUCTION DATE —" next to its CREATED
        stamp.
        """
        run = _seed_run(
            db_session, client, mk_org, mk_auth_headers, mk_input_loc, mk_output_loc
        )
        resp = client.post(
            f'/api/v1/maker/production/orders/{run["order_id"]}/complete',
            headers=mk_auth_headers,
        )
        assert resp.status_code == 200, resp.text
        order = db_session.execute(
            select(ProductionOrder).where(ProductionOrder.id == run['order_id'])
        ).scalar_one()
        assert order.production_date is not None
        assert order.completed_at is not None
        assert order.production_date == order.completed_at.date()

    def test_a_run_is_filed_under_the_organizations_day(
        self,
        client: TestClient,
        mk_org: Organization,
        mk_auth_headers: dict[str, str],
        mk_input_loc: StorageLocation,
        mk_output_loc: StorageLocation,
        db_session: Session,
    ) -> None:
        """The day a run closes is the organization's, not the server's.

        A run with no production date took the UTC date of its completion
        stamp, and the period guard in front of it asked about the server's
        ``date.today()`` — so a workshop a day ahead of the server filed
        today's run under yesterday, in a month it might already have
        closed. The zone is one whose today differs from the server's right
        now, so the reverted code fails at any hour.
        """
        zone, org_today = zone_where_today_differs()
        mk_org.timezone = zone
        db_session.commit()
        run = _seed_run(
            db_session, client, mk_org, mk_auth_headers, mk_input_loc, mk_output_loc
        )

        resp = client.post(
            f'/api/v1/maker/production/orders/{run["order_id"]}/complete',
            headers=mk_auth_headers,
        )

        assert resp.status_code == 200, resp.text
        order = db_session.execute(
            select(ProductionOrder).where(ProductionOrder.id == run['order_id'])
        ).scalar_one()
        assert order.production_date == org_today

    def test_stock_moves_carry_the_unit(
        self,
        client: TestClient,
        mk_org: Organization,
        mk_auth_headers: dict[str, str],
        mk_input_loc: StorageLocation,
        mk_output_loc: StorageLocation,
        db_session: Session,
    ) -> None:
        """The moves table says "4 kg", like the consumption table beside it."""
        run = _seed_run(
            db_session, client, mk_org, mk_auth_headers, mk_input_loc, mk_output_loc
        )
        # The ingredient carries its measure — the move can only name a unit
        # the template declares.
        from app.models.product_template import ProductTemplate
        from app.models.uom import Uom

        kg = db_session.execute(
            select(Uom).where(Uom.symbol == 'kg', Uom.organization_id.is_(None))
        ).scalar_one()
        ingredient = db_session.execute(
            select(ProductTemplate).where(
                ProductTemplate.id == run['ingredient_template_id']
            )
        ).scalar_one()
        ingredient.uom_id = kg.id
        db_session.commit()

        complete_resp = client.post(
            f'/api/v1/maker/production/orders/{run["order_id"]}/complete',
            headers=mk_auth_headers,
        )
        assert complete_resp.status_code == 200, complete_resp.text

        moves = client.get(
            f'/api/v1/maker/production/orders/{run["order_id"]}/stock-moves',
            headers=mk_auth_headers,
        )
        assert moves.status_code == 200, moves.text
        entries = moves.json()['items']
        assert entries, 'completed run has no stock moves'
        symbols = {e['uom_symbol'] for e in entries}
        assert 'kg' in symbols, entries


class TestShortAtCreate:
    def test_order_born_over_stock_records_it(
        self,
        client: TestClient,
        mk_org: Organization,
        mk_auth_headers: dict[str, str],
        mk_input_loc: StorageLocation,
        mk_output_loc: StorageLocation,
        db_session: Session,
    ) -> None:
        """1000 candles from stock for 30: the order says it was born short."""
        run = _seed_run(
            db_session, client, mk_org, mk_auth_headers, mk_input_loc, mk_output_loc
        )
        # A much larger order, same stock: 1000 batches need 200 kg, the
        # seeded ingredient holds 10 kg.
        resp = client.post(
            '/api/v1/maker/production/orders',
            headers=mk_auth_headers,
            json={
                'output_template_id': run['output_template_id'],
                'planned_qty': '1000',
                'output_location_id': str(mk_output_loc.id),
                # The test is about the recorded fact, not about the warning.
                'confirm_shortage': True,
            },
        )
        assert resp.status_code == 201, resp.text
        big_order_id = resp.json()['id']

        assert _get_flag(db_session, big_order_id) is True

        # The refusal says which kind of shortage this is.
        complete_resp = client.post(
            f'/api/v1/maker/production/orders/{big_order_id}/complete',
            headers=mk_auth_headers,
        )
        assert complete_resp.status_code == 422
        detail = complete_resp.json()['detail']
        assert detail['error'] == 'insufficient_stock'
        assert detail['short_at_create'] is True

    def test_order_born_under_stock_gets_a_truthful_refusal(
        self,
        client: TestClient,
        mk_org: Organization,
        mk_auth_headers: dict[str, str],
        mk_input_loc: StorageLocation,
        mk_output_loc: StorageLocation,
        db_session: Session,
    ) -> None:
        """Born satisfiable, stock moved since: 'ran out' is now the truth."""
        run = _seed_run(
            db_session, client, mk_org, mk_auth_headers, mk_input_loc, mk_output_loc
        )
        order_id = run['order_id']
        assert _get_flag(db_session, order_id) is False

        # The stock drains after the draft was created: someone uses it all
        # off the shelf.
        drained = client.patch(
            f'/api/v1/items/{run["ingredient_item_id"]}/consume',
            headers=mk_auth_headers,
            json={'quantity': '10'},
        )
        assert drained.status_code == 200, drained.text

        complete_resp = client.post(
            f'/api/v1/maker/production/orders/{order_id}/complete',
            headers=mk_auth_headers,
        )
        assert complete_resp.status_code == 422
        detail = complete_resp.json()['detail']
        assert detail['error'] == 'insufficient_stock'
        # The run WAS satisfiable at creation — the dialog may say it ran
        # out since, and may not say "never enough".
        assert detail['short_at_create'] is False

    def test_new_organization_defaults_to_warn(
        self,
        client: TestClient,
        h: Any,
        mk_storage_type: Any,
        mk_user: Any,
    ) -> None:
        """The most silent of the three strategies is not the default.

        A new organization gets WARN: an order over stock still gets created,
        but with a warning instead of silence. BLOCK would refuse, ALLOW was
        the old default, the one that let the order through in silence.
        """
        org = h.create_org(
            'Fresh Maker Org',
            ['core', 'items', 'locations', 'categories', 'stats', 'maker'],
        )
        resp = client.get(
            '/api/v1/maker/settings',
            headers=h.get_auth_headers(h.create_user(org, email='fresh@example.com')),
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()['create_on_shortage_strategy'] == 'WARN'

    def test_changing_planned_qty_recomputes_the_flag(
        self,
        client: TestClient,
        mk_org: Organization,
        mk_auth_headers: dict[str, str],
        mk_input_loc: StorageLocation,
        mk_output_loc: StorageLocation,
        db_session: Session,
    ) -> None:
        """The flag answers about the current planned quantity, not the old one."""
        run = _seed_run(
            db_session, client, mk_org, mk_auth_headers, mk_input_loc, mk_output_loc
        )
        order_id = run['order_id']
        assert _get_flag(db_session, order_id) is False

        resp = client.patch(
            f'/api/v1/maker/production/orders/{order_id}',
            headers=mk_auth_headers,
            json={'planned_qty': '1000'},
        )
        assert resp.status_code == 200, resp.text
        assert _get_flag(db_session, order_id) is True

        resp = client.patch(
            f'/api/v1/maker/production/orders/{order_id}',
            headers=mk_auth_headers,
            json={'planned_qty': '1'},
        )
        assert resp.status_code == 200, resp.text
        assert _get_flag(db_session, order_id) is False
