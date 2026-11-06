"""The order list carries the shortage the detail page calls a blocker.

A draft whose planned consumption exceeds stock gets refused on completion,
and the detail page says so — but the card on the list said nothing, so a
planner with a pile of drafts opened them one by one to find out which runs
would be refused. The listing answers with the signal completion refuses
with: the same shortage function, at the order's own output location,
unmeasurable ingredients included — computed once for the page, so the
query count does not grow with it.
"""

from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.models.item import Item
from app.models.organization import Organization
from app.models.product_template import ProductTemplate
from app.models.storage_location import StorageLocation
from app.models.uom import Uom, UomCategory
from app.modules.maker import availability_service, bom_service
from app.modules.maker.models import BoMLine, MakerModuleSettings, MakerRecipe
from app.modules.maker.tests.integration.test_a_run_opens_the_card_at_its_cost import (
    _recipe,
    _template,
)
from tests.integration._shelf import post_on_shelf

pytestmark = pytest.mark.integration


def _catalog_orders(
    client: TestClient, headers: dict[str, str]
) -> dict[str, dict[str, Any]]:
    listed = client.get('/api/v1/maker/production/orders', headers=headers)
    assert listed.status_code == 200, listed.text
    return {row['output_template_name']: row for row in listed.json()['items']}


def _set_scope(db: Session, org: Organization, scope: str) -> None:
    row = db.execute(
        select(MakerModuleSettings).where(MakerModuleSettings.organization_id == org.id)
    ).scalar_one_or_none()
    if row is None:
        db.add(
            MakerModuleSettings(organization_id=org.id, availability_check_scope=scope)
        )
    else:
        row.availability_check_scope = scope
    db.commit()


def _recipe_with_yield(
    db: Session,
    org: Organization,
    *,
    output_id: Any,
    child_id: Any,
    yield_qty: str,
    qty_per_batch: str,
) -> MakerRecipe:
    """A recipe whose yield and line quantity are not both 1.

    With yield 1 and one piece per batch, an estimate that read the planned
    output as batches would still print the right number. The pair
    (yield 2, 4 per batch) makes the two readings differ by the factor the
    division is responsible for.
    """
    recipe = MakerRecipe(
        organization_id=org.id,
        output_template_id=output_id,
        name='One line',
        batch_yield_qty=Decimal(yield_qty),
        is_default=True,
    )
    db.add(recipe)
    db.commit()
    db.refresh(recipe)
    db.add(
        BoMLine(
            organization_id=org.id,
            recipe_id=recipe.id,
            parent_template_id=output_id,
            child_template_id=child_id,
            qty_per_batch=Decimal(qty_per_batch),
            unit='pcs',
        )
    )
    db.commit()
    return recipe


def _draft(
    client: TestClient,
    headers: dict[str, str],
    mk_org: Organization,
    mk_input_loc: StorageLocation,
    mk_output_loc: StorageLocation,
    name: str,
    planned: str,
    *,
    stock: str | None,
    db_session: Session,
    yield_qty: str = '1',
    qty_per_batch: str = '1',
) -> tuple[dict[str, Any], ProductTemplate]:
    ingredient = _template(db_session, mk_org, f'Flour for {name}')
    output = _template(db_session, mk_org, name)
    _recipe_with_yield(
        db_session,
        mk_org,
        output_id=output.id,
        child_id=ingredient.id,
        yield_qty=yield_qty,
        qty_per_batch=qty_per_batch,
    )
    db_session.commit()
    if stock is not None:
        post_on_shelf(
            client,
            headers,
            ingredient,
            mk_input_loc.id,
            stock,
            purchase_price='2.50',
        )
    created = client.post(
        '/api/v1/maker/production/orders',
        headers=headers,
        json={
            'output_template_id': str(output.id),
            'planned_qty': planned,
            'input_storage_location_id': str(mk_input_loc.id),
            'output_location_id': str(mk_output_loc.id),
            'confirm_shortage': True,
        },
    )
    assert created.status_code == 201, created.text
    return created.json(), ingredient


class TestTheListNamesTheBlocker:
    def test_a_short_draft_says_how_many_ingredients_are_short(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        mk_org: Organization,
        mk_input_loc: StorageLocation,
        mk_output_loc: StorageLocation,
        db_session: Session,
    ) -> None:
        _draft(
            client,
            mk_auth_headers,
            mk_org,
            mk_input_loc,
            mk_output_loc,
            'Output hungry',
            '50',
            stock='10',
            db_session=db_session,
        )

        rows = _catalog_orders(client, mk_auth_headers)
        row = rows['Output hungry']

        assert row['shortage_count'] == 1

    def test_a_draft_within_stock_reads_zero(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        mk_org: Organization,
        mk_input_loc: StorageLocation,
        mk_output_loc: StorageLocation,
        db_session: Session,
    ) -> None:
        _draft(
            client,
            mk_auth_headers,
            mk_org,
            mk_input_loc,
            mk_output_loc,
            'Output comfortable',
            '5',
            stock='10',
            db_session=db_session,
        )

        rows = _catalog_orders(client, mk_auth_headers)
        assert rows['Output comfortable']['shortage_count'] == 0

    def test_the_yield_divides_the_plan_before_it_is_measured(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        mk_org: Organization,
        mk_input_loc: StorageLocation,
        mk_output_loc: StorageLocation,
        db_session: Session,
    ) -> None:
        """Five outputs at two per batch take 2.5 batches of four pieces —
        ten pieces, and ten are on the shelf. A listing that read the planned
        output as batches would demand twenty and cry shortage where
        completion sees none."""
        _draft(
            client,
            mk_auth_headers,
            mk_org,
            mk_input_loc,
            mk_output_loc,
            'Output with yield',
            '5',
            stock='10',
            db_session=db_session,
            yield_qty='2',
            qty_per_batch='4',
        )

        rows = _catalog_orders(client, mk_auth_headers)
        assert rows['Output with yield']['shortage_count'] == 0

    def test_an_order_past_the_draft_carries_no_forecast(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        mk_org: Organization,
        mk_input_loc: StorageLocation,
        mk_output_loc: StorageLocation,
        db_session: Session,
    ) -> None:
        ingredient = _template(db_session, mk_org, 'Flour for the run')
        output = _template(db_session, mk_org, 'Output completed')
        _recipe(db_session, mk_org, output_id=output.id, child_id=ingredient.id)
        post_on_shelf(
            client,
            mk_auth_headers,
            ingredient,
            mk_input_loc.id,
            50,
            purchase_price='2.50',
        )
        created = client.post(
            '/api/v1/maker/production/orders',
            headers=mk_auth_headers,
            json={
                'output_template_id': str(output.id),
                'planned_qty': '2',
                'input_storage_location_id': str(mk_input_loc.id),
                'output_location_id': str(mk_output_loc.id),
            },
        )
        assert created.status_code == 201, created.text
        completed = client.post(
            f'/api/v1/maker/production/orders/{created.json()["id"]}/complete',
            headers=mk_auth_headers,
        )
        assert completed.status_code == 200, completed.text

        rows = _catalog_orders(client, mk_auth_headers)
        assert rows['Output completed']['shortage_count'] is None

        detail = client.get(
            f'/api/v1/maker/production/orders/{created.json()["id"]}',
            headers=mk_auth_headers,
        )
        assert detail.status_code == 200, detail.text
        assert detail.json()['shortage_count'] is None
        assert detail.json()['shortage_items'] is None

    def test_the_list_the_detail_and_the_refusal_agree(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        mk_org: Organization,
        mk_input_loc: StorageLocation,
        mk_output_loc: StorageLocation,
        db_session: Session,
    ) -> None:
        """One signal, three readers: the card on the list, the detail page,
        and the refusal completion answers with. A listing that counted one
        way and a check that refused by another left the planner reading two
        different truths about the same draft."""
        order, _ingredient = _draft(
            client,
            mk_auth_headers,
            mk_org,
            mk_input_loc,
            mk_output_loc,
            'Output agreed on',
            '50',
            stock='10',
            db_session=db_session,
        )

        rows = _catalog_orders(client, mk_auth_headers)
        listed = rows['Output agreed on']['shortage_count']

        detail = client.get(
            f'/api/v1/maker/production/orders/{order["id"]}',
            headers=mk_auth_headers,
        )
        assert detail.status_code == 200, detail.text
        detail_count = detail.json()['shortage_count']
        detail_items = detail.json()['shortage_items']

        completed = client.post(
            f'/api/v1/maker/production/orders/{order["id"]}/complete',
            headers=mk_auth_headers,
        )

        assert listed == 1
        assert detail_count == listed
        assert detail_items is not None
        assert len(detail_items) == listed
        assert detail_items[0]['child_template_name'] == 'Flour for Output agreed on'
        assert Decimal(str(detail_items[0]['shortage'])) == Decimal('40')
        assert completed.status_code == 422, completed.text

    def test_a_page_of_different_recipes_costs_one_recipe_round(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        mk_org: Organization,
        mk_input_loc: StorageLocation,
        mk_output_loc: StorageLocation,
        db_session: Session,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Six drafts on six different recipes are the shape the page used
        to choke on: exploding every order's recipe per row asked the same
        questions once per draft. The page asks once for the set's recipes
        and once for their children's default recipes — measured at the one
        seam every explosion passes through, not with a stopwatch."""
        for n in range(6):
            _draft(
                client,
                mk_auth_headers,
                mk_org,
                mk_input_loc,
                mk_output_loc,
                f'Output page {n}',
                '1',
                stock='5',
                db_session=db_session,
            )

        calls: list[list[UUID]] = []
        original = bom_service._find_default_recipes_batch

        async def counting(db: Any, organization_id: Any, template_ids: Any) -> Any:
            calls.append(list(template_ids))
            return await original(db, organization_id, template_ids)

        monkeypatch.setattr(bom_service, '_find_default_recipes_batch', counting)
        listed = client.get('/api/v1/maker/production/orders', headers=mk_auth_headers)
        assert listed.status_code == 200, listed.text

        # One resolution for the whole page. An explosion per row asks once
        # per recipe — six here — and that per-row cost is what this pins.
        assert len(calls) == 1, [len(batch) for batch in calls]

    def test_the_listing_does_not_take_the_settings_write_lock(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        mk_org: Organization,
        mk_input_loc: StorageLocation,
        mk_output_loc: StorageLocation,
        db_session: Session,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Reading the availability scope with the settings write lock would
        queue the whole page behind every maker write in the organisation —
        a GET that can serialize a create or a completion. The listing reads
        the scope unlocked, and this pins the flag the read passes."""
        _draft(
            client,
            mk_auth_headers,
            mk_org,
            mk_input_loc,
            mk_output_loc,
            'Output unlocked',
            '1',
            stock='5',
            db_session=db_session,
        )

        calls: list[dict[str, Any]] = []
        original = availability_service.recipe_service.get_settings

        async def spy(db: Any, organization_id: Any, **kwargs: Any) -> Any:
            calls.append(dict(kwargs))
            return await original(db, organization_id, **kwargs)

        monkeypatch.setattr(availability_service.recipe_service, 'get_settings', spy)
        listed = client.get('/api/v1/maker/production/orders', headers=mk_auth_headers)
        assert listed.status_code == 200, listed.text

        assert calls, 'the listing never asked for the scope setting'
        assert all(kw.get('for_update') is False for kw in calls), calls

    def test_a_per_location_scope_judges_the_orders_own_shelf(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        mk_org: Organization,
        mk_user: Any,
        mk_input_loc: StorageLocation,
        mk_output_loc: StorageLocation,
        db_session: Session,
    ) -> None:
        """With a per-location check, completion judges the order's output
        shelf — a listing that summed the whole organisation read a silent
        card over a run completion refuses."""
        _set_scope(db_session, mk_org, 'PER_LOCATION')
        other_loc = StorageLocation(
            organization_id=mk_org.id,
            name=f'Elsewhere {uuid4().hex[:6]}',
            storage_type_id=mk_input_loc.storage_type_id,
            created_by=mk_user.id,
        )
        db_session.add(other_loc)
        db_session.flush()
        order, ingredient = _draft(
            client,
            mk_auth_headers,
            mk_org,
            mk_input_loc,
            mk_output_loc,
            'Output elsewhere',
            '5',
            stock='10',
            db_session=db_session,
        )
        # Ten pieces cover an order of five when the whole organisation is
        # the shelf; they cover nothing when the check is the order's own
        # output shelf and the goods stand elsewhere. Move them.
        record = db_session.execute(
            select(Item).where(Item.template_id == ingredient.id)
        ).scalar_one()
        moved = client.patch(
            f'/api/v1/items/{record.id}/move',
            json={'to_location_id': str(other_loc.id)},
            headers=mk_auth_headers,
        )
        assert moved.status_code == 200, moved.text

        rows = _catalog_orders(client, mk_auth_headers)
        assert rows['Output elsewhere']['shortage_count'] == 1
        assert order['output_location_id'] == str(mk_output_loc.id)

    def test_an_ingredient_nobody_can_measure_still_counts(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        mk_org: Organization,
        mk_input_loc: StorageLocation,
        mk_output_loc: StorageLocation,
        db_session: Session,
    ) -> None:
        """A line written in kilograms against stock kept in pieces has no
        bridge between the two. Completion cannot name a shortage quantity,
        but it still refuses the run on the ingredient — and the card counts
        it exactly the same way. A count that skipped the unmeasurable would
        read zero here while completion refuses."""
        mass = UomCategory(name=f'Mass {uuid4().hex[:6]}')
        db_session.add(mass)
        db_session.flush()
        kg = Uom(category_id=mass.id, name='Kilogram', symbol='kg')
        db_session.add(kg)
        units = UomCategory(name=f'Units {uuid4().hex[:6]}')
        db_session.add(units)
        db_session.flush()
        pcs = Uom(category_id=units.id, name='Pieces', symbol='pcs')
        db_session.add(pcs)
        db_session.flush()

        ingredient = _template(db_session, mk_org, 'Flour in pieces')
        ingredient.uom_id = pcs.id
        output = _template(db_session, mk_org, 'Output unmeasurable')
        recipe = MakerRecipe(
            organization_id=mk_org.id,
            output_template_id=output.id,
            name='One line',
            batch_yield_qty=Decimal('1'),
            is_default=True,
        )
        db_session.add(recipe)
        db_session.commit()
        db_session.refresh(recipe)
        db_session.add(
            BoMLine(
                organization_id=mk_org.id,
                recipe_id=recipe.id,
                parent_template_id=output.id,
                child_template_id=ingredient.id,
                qty_per_batch=Decimal('1'),
                unit='kg',
                uom_id=kg.id,
            )
        )
        db_session.commit()
        # Stock exists, so the verdict is not "the shelf is empty" but
        # "nothing says how pieces meet kilograms".
        post_on_shelf(
            client,
            mk_auth_headers,
            ingredient,
            mk_input_loc.id,
            5,
            purchase_price='2.50',
        )

        created = client.post(
            '/api/v1/maker/production/orders',
            headers=mk_auth_headers,
            json={
                'output_template_id': str(output.id),
                'planned_qty': '1',
                'input_storage_location_id': str(mk_input_loc.id),
                'output_location_id': str(mk_output_loc.id),
                'confirm_shortage': True,
            },
        )
        assert created.status_code == 201, created.text

        rows = _catalog_orders(client, mk_auth_headers)
        assert rows['Output unmeasurable']['shortage_count'] == 1

        completed = client.post(
            f'/api/v1/maker/production/orders/{created.json()["id"]}/complete',
            headers=mk_auth_headers,
        )
        assert completed.status_code == 422, completed.text
        refusal = completed.json()['detail']['shortages']
        assert refusal[0]['convertible'] is False

        detail = client.get(
            f'/api/v1/maker/production/orders/{created.json()["id"]}',
            headers=mk_auth_headers,
        )
        assert detail.status_code == 200, detail.text
        items = detail.json()['shortage_items']
        assert items is not None and len(items) == 1
        assert items[0]['convertible'] is False
        assert items[0]['shortage'] is None
        assert items[0]['available_uom_symbol'] == 'pcs'

    def test_every_door_that_returns_a_draft_names_the_same_shortage(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        mk_org: Organization,
        mk_input_loc: StorageLocation,
        mk_output_loc: StorageLocation,
        db_session: Session,
    ) -> None:
        """Create, update and duplicate answered with the order and no
        forecast at all, while a read of the same draft counted two short
        ingredients: the client got a different truth depending on which door
        it came through. All of them go through one constructor now."""
        created, _ = _draft(
            client,
            mk_auth_headers,
            mk_org,
            mk_input_loc,
            mk_output_loc,
            'Output every door',
            '50',
            stock='10',
            db_session=db_session,
        )
        base = '/api/v1/maker/production/orders'

        def read(order_id: str) -> dict[str, Any]:
            got = client.get(f'{base}/{order_id}', headers=mk_auth_headers)
            assert got.status_code == 200, got.text
            body: dict[str, Any] = got.json()
            return body

        updated = client.patch(
            f'{base}/{created["id"]}', headers=mk_auth_headers, json={'notes': 'x'}
        )
        assert updated.status_code == 200, updated.text
        duplicated = client.post(
            f'{base}/{created["id"]}/duplicate', headers=mk_auth_headers
        )
        assert duplicated.status_code == 201, duplicated.text

        for answer in (created, updated.json(), duplicated.json()):
            read_back = read(answer['id'])
            assert read_back['shortage_count'] == 1
            assert answer['shortage_count'] == read_back['shortage_count']
            assert answer['shortage_items'] == read_back['shortage_items']

    def test_a_page_costs_the_same_statements_at_any_number_of_recipes(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        mk_org: Organization,
        mk_input_loc: StorageLocation,
        mk_output_loc: StorageLocation,
        db_session: Session,
    ) -> None:
        """Counted in statements, not milliseconds: the forecast for a page
        of drafts on three different recipes and on twelve asks the database
        the same number of questions, so its cost cannot grow with the
        recipes on the page."""

        def page_statements() -> int:
            seen: list[str] = []

            def count(conn: Any, cursor: Any, statement: str, *args: Any) -> None:
                seen.append(statement)

            event.listen(Engine, 'before_cursor_execute', count)
            try:
                listed = client.get(
                    '/api/v1/maker/production/orders', headers=mk_auth_headers
                )
            finally:
                event.remove(Engine, 'before_cursor_execute', count)
            assert listed.status_code == 200, listed.text
            return len(seen)

        def add_drafts(first: int, last: int) -> None:
            for n in range(first, last):
                _draft(
                    client,
                    mk_auth_headers,
                    mk_org,
                    mk_input_loc,
                    mk_output_loc,
                    f'Output many {n}',
                    '1',
                    stock='5',
                    db_session=db_session,
                )

        add_drafts(0, 3)
        few = page_statements()
        add_drafts(3, 12)
        many = page_statements()

        assert few > 0, 'the counter saw no statements'
        assert many == few, (few, many)
