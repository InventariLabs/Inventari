"""Production orders carry a number from the organization's document register.

Two runs on the same product on the same day were told apart by eight
characters of a UUID, and the earlier decision to give them something a
person can say out loud answered with a second numbering engine of
its own beside the register: its own advisory lock, its own prefix scan, and
the shape "PR/{YEAR}/{SEQ:04d}" hardcoded in the maker. That second engine
and its hardcoded shape are withdrawn here, in favour of the register every
other numbered record uses. What that decision asked for stands: the number is still
one a person can say out loud.

The width stays at four digits, so numbers already printed keep their shape —
the register's own default is three, and "PR/2026/0007" beside "PR/2026/008"
is the kind of history a register should not carry. The type states that
through the register's per-type override, the same door a warehouse uses when
its receipts have their own numbering.

Legacy orders keep NULL — a number the row never had is not invented
afterwards.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.organization import Organization
from app.models.product_template import ProductTemplate
from app.models.storage_location import StorageLocation
from app.modules.maker.models import BoMLine, MakerRecipe
from app.modules.maker.models import ProductionOrder as OrderModel

pytestmark = pytest.mark.integration


def _default_recipe_with_line(
    db: Session,
    org: Organization,
    *,
    output_id: str,
) -> None:
    ingredient = ProductTemplate(
        organization_id=org.id, name='Berries', sku=f'SKU-ING-{uuid4().hex[:6]}'
    )
    db.add(ingredient)
    db.flush()
    recipe = MakerRecipe(
        organization_id=org.id,
        output_template_id=output_id,
        name='Numbered Run',
        batch_yield_qty=1,
        is_default=True,
    )
    db.add(recipe)
    db.flush()
    db.add(
        BoMLine(
            organization_id=org.id,
            recipe_id=recipe.id,
            parent_template_id=output_id,
            child_template_id=ingredient.id,
            qty_per_batch=1,
            unit='pcs',
        )
    )
    db.commit()


def _create_order(
    client: TestClient,
    headers: dict[str, str],
    output_id: str,
    loc_id: str,
) -> dict[str, Any]:
    resp = client.post(
        '/api/v1/maker/production/orders',
        headers=headers,
        json={
            'output_template_id': output_id,
            'planned_qty': '1',
            'output_location_id': loc_id,
            # Numbering is the subject here; the strategy default (WARN)
            # must not turn a short run into a 422 before it is numbered.
            'confirm_shortage': True,
        },
    )
    assert resp.status_code == 201, resp.text
    payload: dict[str, Any] = resp.json()
    return payload


def _seq(order: dict[str, Any]) -> int:
    number = order['number']
    assert number is not None
    return int(number.rsplit('/', 1)[1])


class TestOrderNumbering:
    def test_new_order_gets_a_year_sequence_number(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        db_session: Session,
        mk_org: Organization,
        mk_output_loc: StorageLocation,
    ) -> None:
        output = ProductTemplate(organization_id=mk_org.id, name='Jar', sku='SKU-NUM-1')
        db_session.add(output)
        db_session.commit()
        _default_recipe_with_line(db_session, mk_org, output_id=str(output.id))

        order = _create_order(
            client, mk_auth_headers, str(output.id), str(mk_output_loc.id)
        )

        assert order['number'] is not None
        # The register's shape under the maker's type, at the width already
        # printed: four digits, not the register's own three.
        assert re.fullmatch(r'PR/\d{4}/0001', order['number'])

    def test_the_register_holds_the_sequence(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        db_session: Session,
        mk_org: Organization,
        mk_output_loc: StorageLocation,
    ) -> None:
        """The counter is the register's row, not one the maker keeps beside it."""
        from app.modules.warehouse.models import DocumentNumberSequence

        output = ProductTemplate(organization_id=mk_org.id, name='Jar', sku='SKU-NUM-R')
        db_session.add(output)
        db_session.commit()
        _default_recipe_with_line(db_session, mk_org, output_id=str(output.id))

        order = _create_order(
            client, mk_auth_headers, str(output.id), str(mk_output_loc.id)
        )
        prefix = order['number'].rsplit('/', 1)[0] + '/'

        counter = (
            db_session.query(DocumentNumberSequence)
            .filter_by(organization_id=mk_org.id, prefix=prefix)
            .one()
        )
        assert counter.next_value == 2

    def test_a_number_already_printed_holds_the_floor(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        db_session: Session,
        mk_org: Organization,
        mk_output_loc: StorageLocation,
    ) -> None:
        """A run printed before this engine keeps its number out of circulation."""
        output = ProductTemplate(organization_id=mk_org.id, name='Jar', sku='SKU-NUM-F')
        db_session.add(output)
        db_session.commit()
        _default_recipe_with_line(db_session, mk_org, output_id=str(output.id))

        # On file before the register has ever counted this type — the counter
        # row does not exist yet, so the floor is what is on file rather than
        # one. This is the organization a year into its numbers.
        prefix = f'PR/{datetime.now(UTC).year}/'
        taken = OrderModel(
            organization_id=mk_org.id,
            output_template_id=output.id,
            output_storage_location_id=mk_output_loc.id,
            planned_qty=1,
            number=f'{prefix}0007',
        )
        db_session.add(taken)
        db_session.commit()

        order = _create_order(
            client, mk_auth_headers, str(output.id), str(mk_output_loc.id)
        )
        assert order['number'] == f'{prefix}0008'

    def test_the_organizations_document_format_reaches_its_runs(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        db_session: Session,
        mk_org: Organization,
        mk_output_loc: StorageLocation,
    ) -> None:
        """One format, one place to change it — at the width already printed.

        The sibling test in the purchase orders is this one. Production runs
        differ in exactly one thing: the width stays at four, so numbers
        already printed keep their shape. The rest of the shape is the
        organization's, and an organization that changes it changes its runs
        with it.
        """
        if 'warehouse' not in (mk_org.enabled_modules or []):
            mk_org.enabled_modules = [*(mk_org.enabled_modules or []), 'warehouse']
            db_session.commit()
        profile = client.put(
            '/api/v1/warehouse/profile',
            headers=mk_auth_headers,
            json={'numbering_format': '{TYPE}-{YEAR}-{SEQ:05d}', 'number_padding': 5},
        )
        assert profile.status_code == 200, profile.text

        output = ProductTemplate(organization_id=mk_org.id, name='Jar', sku='SKU-NUM-G')
        db_session.add(output)
        db_session.commit()
        _default_recipe_with_line(db_session, mk_org, output_id=str(output.id))

        order = _create_order(
            client, mk_auth_headers, str(output.id), str(mk_output_loc.id)
        )
        assert order['number'] == f'PR-{datetime.now(UTC).year}-0001'

    def test_numbers_increase_within_an_organization(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        db_session: Session,
        mk_org: Organization,
        mk_output_loc: StorageLocation,
    ) -> None:
        output = ProductTemplate(organization_id=mk_org.id, name='Jar', sku='SKU-NUM-2')
        db_session.add(output)
        db_session.commit()
        _default_recipe_with_line(db_session, mk_org, output_id=str(output.id))

        first = _create_order(
            client, mk_auth_headers, str(output.id), str(mk_output_loc.id)
        )
        second = _create_order(
            client, mk_auth_headers, str(output.id), str(mk_output_loc.id)
        )

        assert _seq(second) == _seq(first) + 1

    def test_detail_and_list_return_the_number(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        db_session: Session,
        mk_org: Organization,
        mk_output_loc: StorageLocation,
    ) -> None:
        output = ProductTemplate(organization_id=mk_org.id, name='Jar', sku='SKU-NUM-3')
        db_session.add(output)
        db_session.commit()
        _default_recipe_with_line(db_session, mk_org, output_id=str(output.id))

        order = _create_order(
            client, mk_auth_headers, str(output.id), str(mk_output_loc.id)
        )
        number = order['number']

        detail = client.get(
            f'/api/v1/maker/production/orders/{order["id"]}',
            headers=mk_auth_headers,
        )
        assert detail.status_code == 200
        assert detail.json()['number'] == number

        listing = client.get('/api/v1/maker/production/orders', headers=mk_auth_headers)
        assert listing.status_code == 200
        numbers = [o.get('number') for o in listing.json()['items']]
        assert number in numbers

    def test_numbers_are_unique_per_organization(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        db_session: Session,
        mk_org: Organization,
        mk_output_loc: StorageLocation,
    ) -> None:
        output = ProductTemplate(organization_id=mk_org.id, name='Jar', sku='SKU-NUM-4')
        db_session.add(output)
        db_session.commit()
        _default_recipe_with_line(db_session, mk_org, output_id=str(output.id))

        numbers = [
            _create_order(
                client, mk_auth_headers, str(output.id), str(mk_output_loc.id)
            )['number']
            for _ in range(3)
        ]

        assert len(set(numbers)) == 3

    def test_two_organizations_number_independently(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        db_session: Session,
        mk_org: Organization,
        mk_output_loc: StorageLocation,
        h: Any,
        mk_storage_type: Any,
        mk_user: Any,
    ) -> None:
        """The other org's sequence is its own — no cross-tenant leakage."""
        from app.models import ProductTemplate as CoreTemplate

        other_org = h.create_org('Other Numbering Org', ['core', 'maker'])
        other_user = h.create_user(other_org, email='other-numbering@example.com')
        other_headers = h.get_auth_headers(other_user)
        other_loc = h.create_storage_location(
            other_org, mk_storage_type, other_user, name='Other Output Shelf'
        )

        own = ProductTemplate(organization_id=mk_org.id, name='Jar', sku='SKU-NUM-5')
        db_session.add(own)
        db_session.commit()
        _default_recipe_with_line(db_session, mk_org, output_id=str(own.id))

        other = CoreTemplate(
            organization_id=other_org.id, name='Other Jar', sku='SKU-NUM-6'
        )
        db_session.add(other)
        other_ingredient = ProductTemplate(
            organization_id=other_org.id,
            name='Other Berries',
            sku=f'SKU-ING-{uuid4().hex[:6]}',
        )
        db_session.add(other_ingredient)
        db_session.flush()
        other_recipe = MakerRecipe(
            organization_id=other_org.id,
            output_template_id=other.id,
            name='Other Numbered Run',
            batch_yield_qty=1,
            is_default=True,
        )
        db_session.add(other_recipe)
        db_session.flush()
        db_session.add(
            BoMLine(
                organization_id=other_org.id,
                recipe_id=other_recipe.id,
                parent_template_id=other.id,
                child_template_id=other_ingredient.id,
                qty_per_batch=1,
                unit='pcs',
            )
        )
        db_session.commit()

        first = _create_order(
            client, mk_auth_headers, str(own.id), str(mk_output_loc.id)
        )
        second = _create_order(client, other_headers, str(other.id), str(other_loc.id))

        assert first['number'].endswith('0001')
        assert second['number'].endswith('0001')

    def test_legacy_order_without_number_reads_as_none(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        db_session: Session,
        mk_org: Organization,
        mk_output_loc: StorageLocation,
    ) -> None:
        output = ProductTemplate(organization_id=mk_org.id, name='Jar', sku='SKU-NUM-7')
        db_session.add(output)
        db_session.commit()
        _default_recipe_with_line(db_session, mk_org, output_id=str(output.id))

        order = _create_order(
            client, mk_auth_headers, str(output.id), str(mk_output_loc.id)
        )
        row = db_session.get(OrderModel, UUID(str(order['id'])))
        assert row is not None
        row.number = None
        db_session.commit()

        detail = client.get(
            f'/api/v1/maker/production/orders/{order["id"]}',
            headers=mk_auth_headers,
        )
        assert detail.status_code == 200
        assert detail.json()['number'] is None
