"""A location can hold a capacity per product.

Without a capacity the rule cannot know a shelf is full, and the company
overview has nothing to show occupancy from. The capacity lives in the
warehouse module, beside the PutawayRule whose decision it sharpens — the
same precedent as ReorderRule living in purchase_orders. A location with
no capacity entry behaves exactly as before: no limit, zero change for
homes and for organizations that never set one.

A reorder rule that wants more of a product than the shelf can hold is a
real, livable contradiction — so it is a warning, not a refusal, surfaced
in both directions: saving the capacity names the rule that oversubscribes
it, and saving the rule names the shelf it oversubscribes.
"""

from __future__ import annotations

from decimal import Decimal
from typing import cast
from uuid import uuid4

import httpx
import pytest
from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.organization import Organization
from app.models.storage_location import StorageLocation
from app.models.user import User

from .test_receipt_line_target import _make_location


def _put_capacity(
    client: TestClient,
    headers: dict[str, str],
    *,
    location_id: str,
    template_id: str,
    max_quantity: str,
) -> httpx.Response:
    return cast(
        httpx.Response,
        client.post(
            '/api/v1/warehouse/putaway/capacity',
            headers=headers,
            json={
                'location_id': location_id,
                'product_template_id': template_id,
                'max_quantity': max_quantity,
            },
        ),
    )


@pytest.mark.integration
class TestPutawayCapacity:
    def test_capacity_crud_round_trip(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        db_session: Session,
        doc_org: Organization,
    ) -> None:
        """An entry created for a shelf and a product reads back with the
        names a reader needs, updates, and deletes."""
        from app.core.testing import ModuleTestHelper

        h = ModuleTestHelper(db_session)
        template = h.create_template(doc_org, name=f'PAW4 {uuid4().hex[:6]}')

        created = _put_capacity(
            client,
            doc_auth_headers,
            location_id=str(doc_target_location.id),
            template_id=str(template.id),
            max_quantity='200',
        )
        assert created.status_code == status.HTTP_201_CREATED, created.text
        entry = created.json()
        assert Decimal(entry['max_quantity']) == Decimal('200')
        assert entry['location_name'] == doc_target_location.name
        assert entry['product_template_name'] == template.name

        listed = client.get(
            '/api/v1/warehouse/putaway/capacity',
            headers=doc_auth_headers,
            params={'location_id': str(doc_target_location.id)},
        )
        assert listed.status_code == status.HTTP_200_OK, listed.text
        assert len(listed.json()['items']) == 1

        changed = client.put(
            f'/api/v1/warehouse/putaway/capacity/{entry["id"]}',
            headers=doc_auth_headers,
            json={'max_quantity': '150'},
        )
        assert changed.status_code == status.HTTP_200_OK, changed.text
        assert Decimal(changed.json()['max_quantity']) == Decimal('150')

        removed = client.delete(
            f'/api/v1/warehouse/putaway/capacity/{entry["id"]}',
            headers=doc_auth_headers,
        )
        assert removed.status_code == status.HTTP_204_NO_CONTENT

    def test_capacity_refuses_foreign_references_as_missing(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        db_session: Session,
        doc_org: Organization,
        doc_user: User,
    ) -> None:
        """A shelf or a product from another organization is refused with
        the same answer a missing one gets.

        The product half needs a template that really belongs to another
        organization. It used to pass a random UUID, which only proves the
        endpoint checks existence: a lookup without an ``organization_id``
        filter would have stayed green while happily capping another
        tenant's product on our shelf. That is the cross-tenant lookup
        class.
        """
        from app.core.testing import ModuleTestHelper

        h = ModuleTestHelper(db_session)
        template = h.create_template(doc_org, name=f'PAW4 {uuid4().hex[:6]}')

        foreign_org = Organization(name=f'PAW4 org {uuid4().hex[:6]}')
        db_session.add(foreign_org)
        db_session.commit()
        foreign_loc = _make_location(
            db_session, foreign_org, doc_target_location, doc_user, 'PAW4 Foreign'
        )
        foreign_template = h.create_template(
            foreign_org, name=f'PAW4 foreign product {uuid4().hex[:6]}'
        )

        for location_id, template_id in (
            (str(foreign_loc.id), str(template.id)),
            (str(doc_target_location.id), str(foreign_template.id)),
            # A plainly missing id has to read the same as the foreign one:
            # existence elsewhere is not ours to confirm.
            (str(doc_target_location.id), str(uuid4())),
        ):
            resp = _put_capacity(
                client,
                doc_auth_headers,
                location_id=location_id,
                template_id=template_id,
                max_quantity='10',
            )
            assert resp.status_code == status.HTTP_400_BAD_REQUEST, resp.text

    def test_capacity_rejects_quantity_past_unit_precision(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        db_session: Session,
        doc_org: Organization,
    ) -> None:
        """Precision comes from the product's stock unit (uom.rounding) —
        the same rule quantities everywhere else obey."""
        from app.core.testing import ModuleTestHelper

        h = ModuleTestHelper(db_session)
        uom = h.get_uom('pcs')
        template = h.create_template(
            doc_org, name=f'PAW4 {uuid4().hex[:6]}', uom_id=str(uom.id)
        )

        resp = _put_capacity(
            client,
            doc_auth_headers,
            location_id=str(doc_target_location.id),
            template_id=str(template.id),
            max_quantity='10.0005',
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST, resp.text

    def test_capacity_save_warns_when_reorder_rule_oversubscribes(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        db_session: Session,
        doc_org: Organization,
    ) -> None:
        """Replenishment wants 500, the shelf holds 200: saving the capacity
        says so instead of letting the two numbers disagree in silence."""
        from app.core.testing import ModuleTestHelper

        h = ModuleTestHelper(db_session)
        template = h.create_template(doc_org, name=f'PAW4 {uuid4().hex[:6]}')

        # The replenishment side of the pair lives behind the
        # purchase-orders module guard; the org opts in here.
        doc_org.enabled_modules = [*doc_org.enabled_modules, 'purchase_orders']
        db_session.commit()

        rule = client.post(
            '/api/v1/purchase-orders/reorder-rules',
            headers=doc_auth_headers,
            json={
                'product_template_id': str(template.id),
                'location_id': str(doc_target_location.id),
                'min_quantity': '50',
                'max_quantity': '500',
            },
        )
        assert rule.status_code in (
            status.HTTP_200_OK,
            status.HTTP_201_CREATED,
        ), rule.text

        created = _put_capacity(
            client,
            doc_auth_headers,
            location_id=str(doc_target_location.id),
            template_id=str(template.id),
            max_quantity='200',
        )
        assert created.status_code == status.HTTP_201_CREATED, created.text
        assert Decimal(created.json()['reorder_max_quantity']) == Decimal('500')
        assert created.json()['reorder_over_capacity'] is True

    def test_reorder_save_warns_when_capacity_is_smaller(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        db_session: Session,
        doc_org: Organization,
    ) -> None:
        """The same contradiction, seen from the reorder form: saving a
        rule that wants more than the shelf holds names the capacity."""
        from app.core.testing import ModuleTestHelper

        h = ModuleTestHelper(db_session)
        template = h.create_template(doc_org, name=f'PAW4 {uuid4().hex[:6]}')

        created = _put_capacity(
            client,
            doc_auth_headers,
            location_id=str(doc_target_location.id),
            template_id=str(template.id),
            max_quantity='200',
        )
        assert created.status_code == status.HTTP_201_CREATED, created.text

        # The replenishment side of the pair lives behind the
        # purchase-orders module guard; the org opts in here.
        doc_org.enabled_modules = [*doc_org.enabled_modules, 'purchase_orders']
        db_session.commit()

        rule = client.post(
            '/api/v1/purchase-orders/reorder-rules',
            headers=doc_auth_headers,
            json={
                'product_template_id': str(template.id),
                'location_id': str(doc_target_location.id),
                'min_quantity': '50',
                'max_quantity': '500',
            },
        )
        assert rule.status_code in (
            status.HTTP_200_OK,
            status.HTTP_201_CREATED,
        ), rule.text
        body = rule.json()
        assert Decimal(body['capacity_max_quantity']) == Decimal('200')
        assert body['over_capacity'] is True

    def test_neither_side_warns_when_the_shelf_holds_what_is_wanted(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        db_session: Session,
        doc_org: Organization,
    ) -> None:
        """Replenishment wants 200, the shelf holds 200: no warning, from
        either side.

        Both flags were only ever asserted true. An implementation that
        answered ``True`` unconditionally — or compared with ``>=`` where
        ``>`` is meant, so a rule wanting exactly what fits reads as
        oversubscribed — passed the whole set. Equality is the boundary and
        it belongs on the quiet side: wanting exactly what fits is not a
        contradiction.
        """
        from app.core.testing import ModuleTestHelper

        h = ModuleTestHelper(db_session)
        template = h.create_template(doc_org, name=f'PAW12 {uuid4().hex[:6]}')

        created = _put_capacity(
            client,
            doc_auth_headers,
            location_id=str(doc_target_location.id),
            template_id=str(template.id),
            max_quantity='200',
        )
        assert created.status_code == status.HTTP_201_CREATED, created.text

        doc_org.enabled_modules = [*doc_org.enabled_modules, 'purchase_orders']
        db_session.commit()

        rule = client.post(
            '/api/v1/purchase-orders/reorder-rules',
            headers=doc_auth_headers,
            json={
                'product_template_id': str(template.id),
                'location_id': str(doc_target_location.id),
                'min_quantity': '50',
                'max_quantity': '200',
            },
        )
        assert rule.status_code in (
            status.HTTP_200_OK,
            status.HTTP_201_CREATED,
        ), rule.text
        # The reorder side sees the capacity and stays quiet about it.
        assert Decimal(rule.json()['capacity_max_quantity']) == Decimal('200')
        assert rule.json()['over_capacity'] is False

        # And the capacity side, re-read with the rule in place, likewise.
        listed = client.get(
            '/api/v1/warehouse/putaway/capacity',
            headers=doc_auth_headers,
            params={'product_template_id': str(template.id)},
        )
        assert listed.status_code == status.HTTP_200_OK, listed.text
        entry = listed.json()['items'][0]
        assert Decimal(entry['reorder_max_quantity']) == Decimal('200')
        assert entry['reorder_over_capacity'] is False

    def test_reorder_list_carries_the_capacity_side(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        db_session: Session,
        doc_org: Organization,
    ) -> None:
        """The warning a save answers rides on the list too — a rule that
        oversubscribes its shelf reads as oversubscribed everywhere, not
        only in the moment somebody re-saves it."""
        from app.core.testing import ModuleTestHelper

        h = ModuleTestHelper(db_session)
        template = h.create_template(doc_org, name=f'PAW4 {uuid4().hex[:6]}')

        created = _put_capacity(
            client,
            doc_auth_headers,
            location_id=str(doc_target_location.id),
            template_id=str(template.id),
            max_quantity='200',
        )
        assert created.status_code == status.HTTP_201_CREATED, created.text

        # The replenishment side of the pair lives behind the
        # purchase-orders module guard; the org opts in here.
        doc_org.enabled_modules = [*doc_org.enabled_modules, 'purchase_orders']
        db_session.commit()

        rule = client.post(
            '/api/v1/purchase-orders/reorder-rules',
            headers=doc_auth_headers,
            json={
                'product_template_id': str(template.id),
                'location_id': str(doc_target_location.id),
                'min_quantity': '50',
                'max_quantity': '500',
            },
        )
        assert rule.status_code in (
            status.HTTP_200_OK,
            status.HTTP_201_CREATED,
        ), rule.text

        listed = client.get(
            '/api/v1/purchase-orders/reorder-rules',
            headers=doc_auth_headers,
            params={'product_template_id': str(template.id)},
        )
        assert listed.status_code == status.HTTP_200_OK, listed.text
        rows = listed.json()['items']
        assert len(rows) == 1, rows
        assert Decimal(rows[0]['capacity_max_quantity']) == Decimal('200')
        assert rows[0]['over_capacity'] is True

    def test_location_settings_list_names_every_restricted_shelf(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
    ) -> None:
        """The settings screen reads the whole organization in one request.

        A shelf nobody restricted has no row at all — mixed is the default —
        so the list carries the restrictions that were chosen and nothing
        else. Reading one shelf at a time turned a table of twenty locations
        into twenty requests.
        """
        empty = client.get(
            '/api/v1/warehouse/putaway/capacity-settings',
            headers=doc_auth_headers,
        )
        assert empty.status_code == status.HTTP_200_OK, empty.text
        assert empty.json()['items'] == []

        put = client.put(
            f'/api/v1/warehouse/putaway/capacity-settings/{doc_target_location.id}',
            headers=doc_auth_headers,
            json={'single_product': True},
        )
        assert put.status_code == status.HTTP_200_OK, put.text

        listed = client.get(
            '/api/v1/warehouse/putaway/capacity-settings',
            headers=doc_auth_headers,
        )
        assert listed.status_code == status.HTTP_200_OK, listed.text
        rows = listed.json()['items']
        assert len(rows) == 1, rows
        assert rows[0]['location_id'] == str(doc_target_location.id)
        assert rows[0]['single_product'] is True

    def test_location_setting_reads_mixed_by_default(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
    ) -> None:
        """A location nobody configured mixes products — the default that
        keeps every existing organization unchanged."""
        read = client.get(
            f'/api/v1/warehouse/putaway/capacity-settings/{doc_target_location.id}',
            headers=doc_auth_headers,
        )
        assert read.status_code == status.HTTP_200_OK, read.text
        assert read.json()['single_product'] is False

        put = client.put(
            f'/api/v1/warehouse/putaway/capacity-settings/{doc_target_location.id}',
            headers=doc_auth_headers,
            json={'single_product': True},
        )
        assert put.status_code == status.HTTP_200_OK, put.text
        assert put.json()['single_product'] is True

    def test_location_setting_refuses_foreign_shelf(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        db_session: Session,
        doc_org: Organization,
        doc_user: User,
    ) -> None:
        foreign_org = Organization(name=f'PAW4 org2 {uuid4().hex[:6]}')
        db_session.add(foreign_org)
        db_session.commit()
        foreign_loc = _make_location(
            db_session, foreign_org, doc_target_location, doc_user, 'PAW4 F2'
        )
        put = client.put(
            f'/api/v1/warehouse/putaway/capacity-settings/{foreign_loc.id}',
            headers=doc_auth_headers,
            json={'single_product': True},
        )
        assert 400 <= put.status_code < 500, put.text
