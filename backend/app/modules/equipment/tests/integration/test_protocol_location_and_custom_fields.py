"""Protocols for assets that stand somewhere, and for fields a category adds.

A checkout to a location is not a handover to a person: the press bolted
to a production line has no receiving party to sign, and the document
describing the placement has to say where the asset stands — the one fact
the placement establishes. The protocol template decides with the location
placeholder: where it is empty, two signatures; where it carries a name,
one signature and the location in the row a receiver would take. This is
a condition inside the CHECKOUT template rather than a third document
type: the template editor already offers exactly two types, and a third
would demand its own built-in, its own settings key and its own screen
support before the first placement could print — while every organization
with a saved checkout copy would additionally have to author the new
type's layout. The person-versus-location fact is one conditional, stated
exactly where the signature block is drawn.

The category a machine belongs to can carry its own fields — an hour
counter, an inspection day — stored on the asset's equipment meta. A
protocol is exactly the document where those numbers get confirmed by
signature, so the template reaches them through one generic accessor
instead of a per-field whitelist every industry would have to extend.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from jinja2.exceptions import SecurityError as JinjaSecurityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.public_api import core_api
from app.core.testing import ModuleTestHelper
from app.models.category import Category
from app.models.item import Item
from app.models.organization import Organization
from app.models.storage_location import StorageLocation
from app.models.user import User
from app.modules.equipment.models import EquipmentAssignment
from app.modules.equipment.protocol_service import render_protocol_html


def _placeholders(
    client: TestClient, headers: dict[str, str], path: str
) -> dict[str, str]:
    resp = client.get(path, headers=headers)
    assert resp.status_code == 200
    return {entry['key']: entry['description'] for entry in resp.json()}


@pytest.mark.integration
class TestALocationCheckout:
    """The document says where the asset stands, and asks only real people to sign."""

    def test_the_document_names_the_location(
        self,
        client: TestClient,
        eq_auth_headers: dict[str, str],
        eq_item: Item,
        eq_storage_location: StorageLocation,
    ) -> None:
        created = client.post(
            '/api/v1/equipment/assignments',
            headers=eq_auth_headers,
            json={
                'item_id': str(eq_item.id),
                'assigned_to_name': '',
                'checkout_location_id': str(eq_storage_location.id),
            },
        )
        assert created.status_code == 201, created.text
        assignment_id = created.json()['id']

        resp = client.get(
            f'/api/v1/equipment/assignments/{assignment_id}/protocol/html',
            headers=eq_auth_headers,
        )
        assert resp.status_code == 200
        # The one fact a placement establishes is the only thing the row
        # has to say: where the asset now stands.
        assert 'Server Room A' in resp.text

    def test_a_location_does_not_sign_but_a_person_does(
        self,
        client: TestClient,
        eq_auth_headers: dict[str, str],
        eq_item: Item,
        eq_storage_location: StorageLocation,
    ) -> None:
        placed = client.post(
            '/api/v1/equipment/assignments',
            headers=eq_auth_headers,
            json={
                'item_id': str(eq_item.id),
                'assigned_to_name': '',
                'checkout_location_id': str(eq_storage_location.id),
            },
        )
        assert placed.status_code == 201, placed.text
        placed_html = client.get(
            f'/api/v1/equipment/assignments/{placed.json()["id"]}/protocol/html',
            headers=eq_auth_headers,
        ).text
        # The same asset cannot carry two live assignments, so this one
        # closes before a person receives it.
        checked_in = client.post(
            f'/api/v1/equipment/assignments/{placed.json()["id"]}/checkin',
            headers=eq_auth_headers,
            json={'checkin_notes': 'Back on the shelf', 'checkin_condition': 'GOOD'},
        )
        assert checked_in.status_code == 200, checked_in.text
        returned_html = client.get(
            f'/api/v1/equipment/assignments/{placed.json()["id"]}/protocol/html',
            headers=eq_auth_headers,
        ).text
        assert 'Server Room A' in returned_html
        assert 'Returning Party' not in returned_html
        handed = client.post(
            '/api/v1/equipment/assignments',
            headers=eq_auth_headers,
            json={
                'item_id': str(eq_item.id),
                'assigned_to_name': 'Jan Kowalski',
            },
        )
        assert handed.status_code == 201, handed.text
        handed_html = client.get(
            f'/api/v1/equipment/assignments/{handed.json()["id"]}/protocol/html',
            headers=eq_auth_headers,
        ).text

        # A person takes responsibility and signs; the issuing party
        # countersigns. A rack does not.
        assert 'Issuing Party' in placed_html
        assert 'Receiving Party' not in placed_html
        assert 'Issuing Party' in handed_html
        assert 'Receiving Party' in handed_html

    def test_a_bare_partner_names_the_receiver(
        self,
        client: TestClient,
        eq_auth_headers: dict[str, str],
        eq_item: Item,
        eq_org: Organization,
        eq_user: User,
        h: ModuleTestHelper,
    ) -> None:
        # The batch issue already names the partner itself when the payload
        # carries only its id; the single checkout has to print the same
        # person, not an empty row and an anonymous signature line.
        partner = h.create_partner(eq_org, eq_user, name='Ewa Nowak')
        handed = client.post(
            '/api/v1/equipment/assignments',
            headers=eq_auth_headers,
            json={'item_id': str(eq_item.id), 'assignee_partner_id': str(partner.id)},
        )
        assert handed.status_code == 201, handed.text
        assert handed.json()['assigned_to_name'] == 'Ewa Nowak'
        handed_html = client.get(
            f'/api/v1/equipment/assignments/{handed.json()["id"]}/protocol/html',
            headers=eq_auth_headers,
        ).text
        assert 'Receiving Party (Ewa Nowak)' in handed_html

    def test_the_location_placeholder_is_documented(
        self, client: TestClient, eq_auth_headers: dict[str, str]
    ) -> None:
        keys = _placeholders(
            client, eq_auth_headers, '/api/v1/equipment/protocol/placeholders'
        )
        assert '{{checkout_location_name}}' in keys


@pytest.mark.integration
class TestCategoryCustomFields:
    """One generic accessor over the asset's equipment meta."""

    @pytest.fixture
    def machine_category(self, db_session: Any, eq_org: Organization) -> Category:
        cat = Category(
            name=f'Milling machine {uuid4().hex[:4]}',
            code=f'CNC_{uuid4().hex[:4]}',
            context_tag='equipment',
            organization_id=eq_org.id,
            field_definitions=[
                {
                    'key': 'operating_hours',
                    'type': 'number',
                    'label': 'Operating hours',
                },
                {
                    'key': 'udt_review_due',
                    'type': 'date',
                    'label': 'UDT review due',
                },
            ],
        )
        db_session.add(cat)
        db_session.commit()
        db_session.refresh(cat)
        return cat

    @pytest.fixture
    def machine(
        self,
        db_session: Any,
        eq_org: Organization,
        eq_storage_location: StorageLocation,
        machine_category: Category,
    ) -> Item:
        item = Item(
            name='Frezarka CNC',
            organization_id=eq_org.id,
            storage_location_id=eq_storage_location.id,
            category_id=machine_category.id,
            quantity=1,
            meta_data={
                'equipment': {
                    'serial_number': 'SN-CNC-9',
                    'operating_hours': '12 450',
                    'udt_review_due': '2026-11-30',
                }
            },
        )
        db_session.add(item)
        db_session.commit()
        db_session.refresh(item)
        return item

    def test_the_template_prints_a_field_the_whitelist_never_heard_of(
        self,
        client: TestClient,
        eq_auth_headers: dict[str, str],
        machine: Item,
    ) -> None:
        created = client.post(
            '/api/v1/equipment/assignments',
            headers=eq_auth_headers,
            json={
                'item_id': str(machine.id),
                'assigned_to_name': 'Jan Kowalski',
            },
        )
        assert created.status_code == 201
        tpl = client.post(
            '/api/v1/equipment/templates',
            headers=eq_auth_headers,
            json={
                'name': 'Machine handover',
                'document_type': 'CHECKOUT',
                'module': 'equipment',
                'body_html': (
                    '<html><body>'
                    '<p>Hours: {{custom.operating_hours}}</p>'
                    '<p>UDT: {{custom.udt_review_due}}</p>'
                    '</body></html>'
                ),
            },
        )
        assert tpl.status_code == 201, tpl.text

        html = client.get(
            f'/api/v1/equipment/assignments/{created.json()["id"]}/protocol/html',
            headers=eq_auth_headers,
            params={'template_id': tpl.json()['id']},
        )
        assert html.status_code == 200
        assert 'Hours: 12 450' in html.text
        assert 'UDT: 2026-11-30' in html.text

    def test_the_placeholder_lists_say_what_the_category_defines(
        self,
        client: TestClient,
        eq_auth_headers: dict[str, str],
        machine_category: Category,
    ) -> None:
        for path in (
            '/api/v1/equipment/protocol/placeholders',
            '/api/v1/equipment/templates/placeholders',
        ):
            keys = _placeholders(client, eq_auth_headers, path)
            assert '{{custom.operating_hours}}' in keys, path
            assert 'Operating hours' in keys['{{custom.operating_hours}}'], path
            assert '{{custom.udt_review_due}}' in keys, path

    def test_a_custom_field_entry_carries_its_label_and_categories_apart(
        self,
        client: TestClient,
        eq_auth_headers: dict[str, str],
        machine_category: Category,
    ) -> None:
        """The description is one English sentence; a Polish editor cannot
        translate the connective inside it, so the parts travel separately."""
        for path in (
            '/api/v1/equipment/protocol/placeholders',
            '/api/v1/equipment/templates/placeholders',
        ):
            resp = client.get(path, headers=eq_auth_headers)
            entry = next(
                e for e in resp.json() if e['key'] == '{{custom.operating_hours}}'
            )
            assert entry['custom_field_label'] == 'Operating hours', path
            assert entry['custom_field_categories'] == [machine_category.name], path
            builtin = next(e for e in resp.json() if e['key'] == '{{item_name}}')
            assert builtin['custom_field_label'] is None, path

    def test_food_category_fields_are_not_offered(
        self,
        client: TestClient,
        eq_auth_headers: dict[str, str],
        eq_org: Organization,
        db_session: Any,
        machine_category: Category,
    ) -> None:
        db_session.add(
            Category(
                name='Food',
                code=f'FOOD_{uuid4().hex[:4]}',
                context_tag='food',
                organization_id=eq_org.id,
                field_definitions=[
                    {'key': 'food_only', 'type': 'text', 'label': 'Food only'}
                ],
            )
        )
        db_session.commit()
        keys = _placeholders(
            client, eq_auth_headers, '/api/v1/equipment/protocol/placeholders'
        )
        assert '{{custom.operating_hours}}' in keys
        assert '{{custom.food_only}}' not in keys


@pytest.mark.integration
class TestTheAccessorReachesNoObjects:
    """The generic accessor is a plain dict, and the sandbox keeps it that way."""

    async def test_object_introspection_prints_nothing_and_refuses_to_run(
        self,
        real_async_db_session: AsyncSession,
        eq_org: Organization,
        eq_item: Item,
        eq_user: User,
    ) -> None:
        db = real_async_db_session
        assignment = EquipmentAssignment(
            organization_id=eq_org.id,
            item_id=eq_item.id,
            assigned_to_name='Jan Kowalski',
            checked_out_by=eq_user.id,
        )
        db.add(assignment)
        await db.commit()
        await db.refresh(assignment)

        async def _render(body: str) -> str:
            probe = await core_api.templates.create_async(
                db=db,
                organization_id=eq_org.id,
                module='equipment',
                user_id=eq_user.id,
                name=f'Introspection probe {uuid4().hex[:4]}',
                body_html=body,
                document_type='CHECKOUT',
            )
            return await render_protocol_html(
                db, eq_org.id, assignment.id, template_id=probe.id, lang='en'
            )

        # Reading the object behind the dict prints nothing at all — not
        # its class, not a repr, not an error text.
        quiet = await _render(
            '<html><body>[{{ custom.__class__ }}|'
            "{{ custom|attr('__init__') }}]</body></html>"
        )
        assert 'dict' not in quiet and 'class' not in quiet and 'object' not in quiet

        # Escaping through the dunder is refused the moment it would run.
        with pytest.raises(JinjaSecurityError):
            await _render('<html><body>{{ custom.__class__() }}</body></html>')

        # The probe templates above were never committed — CoreAPI writes
        # flush and the caller owns the commit. End the unit of work here,
        # before the sync-session fixture teardown (set up before this one)
        # waits on their locks.
        await db.rollback()

    def test_a_key_nobody_wrote_prints_nothing(
        self,
        client: TestClient,
        eq_auth_headers: dict[str, str],
        eq_item: Item,
    ) -> None:
        created = client.post(
            '/api/v1/equipment/assignments',
            headers=eq_auth_headers,
            json={
                'item_id': str(eq_item.id),
                'assigned_to_name': 'Jan Kowalski',
            },
        )
        assert created.status_code == 201
        tpl = client.post(
            '/api/v1/equipment/templates',
            headers=eq_auth_headers,
            json={
                'name': 'Blank probe',
                'document_type': 'CHECKOUT',
                'module': 'equipment',
                'body_html': (
                    '<html><body>[{{custom.nobody_wrote_this}}]</body></html>'
                ),
            },
        )
        assert tpl.status_code == 201

        html = client.get(
            f'/api/v1/equipment/assignments/{created.json()["id"]}/protocol/html',
            headers=eq_auth_headers,
            params={'template_id': tpl.json()['id']},
        )
        assert html.status_code == 200
        # An absent key is empty, not an object, not an error.
        assert '[]' in html.text
