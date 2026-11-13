"""A run that already happened is recorded in one step.

"I made 20 kg of plum butter" used to be a draft first and a completion
second, and the completion refused the run when the records held fewer plums
than the recipe asked for — goods that had already been made could not be
recorded. Saving a run as made now opens and closes the order in one
transaction, in the product's own unit. An ingredient the records lack is
consumed as far as they go; the rest is recorded on the order's line and the
place it is kept is put up for a count in To do. Before saving, the preview
says what each ingredient needs against what the records hold, and a planned
run's shortfall can go straight onto the shopping list.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any, cast

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.testing import ModuleTestHelper
from app.models.item import Item
from app.models.organization import Organization
from app.models.product_template import ProductTemplate
from app.models.storage_location import StorageLocation
from app.models.uom import Uom
from app.models.user import User
from app.modules.maker.models import (
    BoMLine,
    MakerModuleSettings,
    ProductionOrderLine,
)
from app.modules.shopping_lists.models import ShoppingListItem
from app.modules.stock_takes.models import StockTake, StockTakeStatus
from tests.integration._shelf import post_on_shelf

from .test_role_guards import _template

pytestmark = pytest.mark.integration


@pytest.fixture
def org(h: ModuleTestHelper) -> Organization:
    return h.create_org(
        'Plum Kitchen',
        [
            'core',
            'items',
            'locations',
            'categories',
            'warehouse',
            'maker',
            'stock_takes',
            'shopping_lists',
        ],
    )


@pytest.fixture
def user(h: ModuleTestHelper, org: Organization) -> User:
    return h.create_user(org, email='cook@example.com')


@pytest.fixture
def headers(h: ModuleTestHelper, user: User) -> dict[str, str]:
    return h.get_auth_headers(user)


@pytest.fixture
def pantry(h: ModuleTestHelper, org: Organization, user: User) -> StorageLocation:
    return h.create_storage_location(
        org, h.create_storage_type('Pantry', 'PANTRY'), user, name='Pantry'
    )


def _plum_butter(
    db: Session,
    client: TestClient,
    org: Organization,
    headers: dict[str, str],
    pantry: StorageLocation,
    *,
    plums_on_shelf: str | None,
) -> dict[str, Any]:
    """Plum butter: 1.1 kg of plums per kilogram made, a recipe for 1 kg."""
    plums = _template(db, org, name='Damson Plums')
    butter = _template(db, org, name='Plum Butter')
    recipe = client.post(
        '/api/v1/maker/recipes',
        headers=headers,
        json={
            'output_template_id': str(butter.id),
            'name': 'Plum butter',
            'batch_yield_qty': '1',
            'is_default': True,
            'reference_price': '18.00',
        },
    )
    assert recipe.status_code == 201, recipe.text
    line = client.post(
        f'/api/v1/maker/recipes/{recipe.json()["id"]}/bom-lines',
        headers=headers,
        json={
            'child_template_id': str(plums.id),
            'qty_per_batch': '1.1',
            'unit': 'kg',
        },
    )
    assert line.status_code == 201, line.text
    if plums_on_shelf is not None:
        post_on_shelf(client, headers, plums, pantry.id, plums_on_shelf)
    return {'plums': plums, 'butter': butter, 'recipe_id': recipe.json()['id']}


def _run(butter: ProductTemplate, pantry: StorageLocation, qty: str) -> dict[str, str]:
    return {
        'output_template_id': str(butter.id),
        'planned_qty': qty,
        'output_location_id': str(pantry.id),
    }


def _on_hand(db: Session, template: ProductTemplate) -> Decimal:
    db.expire_all()
    return sum(
        (
            item.quantity
            for item in db.scalars(
                select(Item).where(
                    Item.template_id == template.id, Item.deleted_at.is_(None)
                )
            )
        ),
        Decimal('0'),
    )


def _todo(client: TestClient, headers: dict[str, str], **params: Any) -> list[Any]:
    response = client.get(
        '/api/v1/warehouse/todo',
        headers=headers,
        params={'date_to': date.today().isoformat(), 'limit': 50, **params},
    )
    assert response.status_code == 200, response.text
    return cast(list[Any], response.json()['work_items']['items'])


class TestAlreadyMade:
    def test_made_records_and_completes_the_run_in_one_step(
        self,
        client: TestClient,
        org: Organization,
        headers: dict[str, str],
        pantry: StorageLocation,
        db_session: Session,
    ) -> None:
        """20 kg made from 22 kg of the 30 on the shelf: one call, all posted."""
        seed = _plum_butter(
            db_session, client, org, headers, pantry, plums_on_shelf='30'
        )

        response = client.post(
            '/api/v1/maker/production/orders/made',
            headers=headers,
            json=_run(seed['butter'], pantry, '20'),
        )

        assert response.status_code == 201, response.text
        body = response.json()
        assert body['status'] == 'COMPLETED'
        assert Decimal(body['actual_qty']) == Decimal('20')
        assert Decimal(body['lines'][0]['consumed_qty']) == Decimal('22')
        assert body['lines'][0]['shortfall_qty'] is None
        assert _on_hand(db_session, seed['plums']) == Decimal('8')
        assert _on_hand(db_session, seed['butter']) == Decimal('20')

    def test_made_over_stock_consumes_what_is_recorded_and_keeps_the_rest(
        self,
        client: TestClient,
        org: Organization,
        headers: dict[str, str],
        pantry: StorageLocation,
        db_session: Session,
    ) -> None:
        """22 kg used, 18 kg in the records: the run is not refused.

        It used to answer "cannot complete — out of stock" for goods already
        made. The records give up their 18 kg, the line names the 4 kg they
        lacked, and the butter is on the shelf.
        """
        seed = _plum_butter(
            db_session, client, org, headers, pantry, plums_on_shelf='18'
        )

        response = client.post(
            '/api/v1/maker/production/orders/made',
            headers=headers,
            json=_run(seed['butter'], pantry, '20'),
        )

        assert response.status_code == 201, response.text
        line = response.json()['lines'][0]
        assert Decimal(line['consumed_qty']) == Decimal('22')
        assert Decimal(line['shortfall_qty']) == Decimal('4')
        assert _on_hand(db_session, seed['plums']) == Decimal('0')
        assert _on_hand(db_session, seed['butter']) == Decimal('20')

    def test_made_is_not_stopped_by_the_planning_shortage_strategy(
        self,
        client: TestClient,
        org: Organization,
        headers: dict[str, str],
        pantry: StorageLocation,
        db_session: Session,
    ) -> None:
        """BLOCK decides whether to plan over stock; a run made is not a plan."""
        seed = _plum_butter(
            db_session, client, org, headers, pantry, plums_on_shelf=None
        )
        db_session.merge(
            MakerModuleSettings(
                organization_id=org.id, create_on_shortage_strategy='BLOCK'
            )
        )
        db_session.commit()

        planned = client.post(
            '/api/v1/maker/production/orders',
            headers=headers,
            json=_run(seed['butter'], pantry, '5'),
        )
        made = client.post(
            '/api/v1/maker/production/orders/made',
            headers=headers,
            json=_run(seed['butter'], pantry, '5'),
        )

        assert planned.status_code == 422, planned.text
        assert made.status_code == 201, made.text
        assert Decimal(made.json()['lines'][0]['shortfall_qty']) == Decimal('5.5')

    def test_the_shortfall_puts_the_ingredient_up_for_a_count_until_it_is_counted(
        self,
        client: TestClient,
        org: Organization,
        user: User,
        headers: dict[str, str],
        pantry: StorageLocation,
        db_session: Session,
    ) -> None:
        """The goods existed, so the records are wrong: count where they are kept."""
        seed = _plum_butter(
            db_session, client, org, headers, pantry, plums_on_shelf='18'
        )
        kg = db_session.scalars(select(Uom).where(Uom.symbol == 'kg')).first()
        assert kg is not None
        seed['butter'].uom_id = kg.id
        db_session.commit()
        made = client.post(
            '/api/v1/maker/production/orders/made',
            headers=headers,
            json=_run(seed['butter'], pantry, '20'),
        )
        assert made.status_code == 201, made.text
        line_id = made.json()['lines'][0]['id']
        key = f'production_shortfall:{line_id}'

        task = next(item for item in _todo(client, headers) if item['key'] == key)
        assert task['kind'] == 'count'
        assert task['subject'] == 'Damson Plums'
        assert task['place'] == 'Pantry'
        assert task['number'] == made.json()['number']
        assert task['action_href'] == (
            f'/inventory/stock-takes/count?location={pantry.id}'
        )

        db_session.add(
            StockTake(
                organization_id=org.id,
                user_id=user.id,
                storage_location_id=pantry.id,
                name='Pantry count',
                status=StockTakeStatus.COMPLETED,
                completed_at=datetime.now(UTC),
            )
        )
        db_session.commit()

        assert all(item['key'] != key for item in _todo(client, headers))
        done = next(
            item
            for item in _todo(client, headers, include_done=True)
            if item['key'] == key
        )
        assert done['state'] == 'done'

        # The run itself is a finished card too, and says when it was made.
        run = next(
            item
            for item in _todo(client, headers, include_done=True)
            if item['key'] == f'production_order:{made.json()["id"]}'
        )
        assert run['state'] == 'done'
        assert run['done_at'] is not None
        # ...and the quantity it made is a quantity of something.
        assert run['unit'] == 'kg'

    def test_a_line_that_cannot_be_measured_is_still_refused(
        self,
        client: TestClient,
        org: Organization,
        headers: dict[str, str],
        pantry: StorageLocation,
        db_session: Session,
    ) -> None:
        """Kilograms in the recipe, pieces on the shelf: nobody knows what to take.

        The refusal carries completion's own shape, so the same dialog reads it.
        """
        seed = _plum_butter(
            db_session, client, org, headers, pantry, plums_on_shelf=None
        )
        kg = db_session.scalars(select(Uom).where(Uom.symbol == 'kg')).first()
        pcs = db_session.scalars(select(Uom).where(Uom.symbol == 'pcs')).first()
        assert kg is not None and pcs is not None
        line = db_session.scalars(select(BoMLine)).one()
        line.uom_id = kg.id
        seed['plums'].uom_id = pcs.id
        db_session.commit()

        response = client.post(
            '/api/v1/maker/production/orders/made',
            headers=headers,
            json=_run(seed['butter'], pantry, '2'),
        )

        assert response.status_code == 422, response.text
        detail = response.json()['detail']
        assert detail['error'] == 'insufficient_stock'
        assert detail['shortages'][0]['shortage'] is None
        assert _on_hand(db_session, seed['butter']) == Decimal('0')


class TestBeforeSaving:
    def test_preview_shows_need_have_and_short_with_the_cost_per_unit(
        self,
        client: TestClient,
        org: Organization,
        headers: dict[str, str],
        pantry: StorageLocation,
        db_session: Session,
    ) -> None:
        """The shortage is on the first screen, not at "create draft"."""
        seed = _plum_butter(
            db_session, client, org, headers, pantry, plums_on_shelf='18'
        )

        response = client.post(
            '/api/v1/maker/production/orders/preview',
            headers=headers,
            json=_run(seed['butter'], pantry, '20'),
        )

        assert response.status_code == 200, response.text
        body = response.json()
        assert body['has_shortage'] is True
        assert Decimal(body['batch_yield_qty']) == Decimal('1')
        assert Decimal(body['reference_price']) == Decimal('18.00')
        [plums] = body['ingredients']
        assert plums['child_template_name'] == 'Damson Plums'
        assert Decimal(plums['needed']) == Decimal('22')
        assert Decimal(plums['available']) == Decimal('18')
        assert Decimal(plums['shortage']) == Decimal('4')

    def test_a_planned_runs_shortfall_goes_onto_the_shopping_list_once(
        self,
        client: TestClient,
        org: Organization,
        headers: dict[str, str],
        pantry: StorageLocation,
        db_session: Session,
    ) -> None:
        """ "Add 4 kg to the shopping list" adds 4 kg, and a second press nothing."""
        seed = _plum_butter(
            db_session, client, org, headers, pantry, plums_on_shelf='18'
        )
        run = _run(seed['butter'], pantry, '20')

        first = client.post(
            '/api/v1/maker/production/orders/shortages/shopping-list',
            headers=headers,
            json=run,
        )
        again = client.post(
            '/api/v1/maker/production/orders/shortages/shopping-list',
            headers=headers,
            json=run,
        )

        assert first.status_code == 200, first.text
        assert first.json()['added_count'] == 1
        assert again.json()['added_count'] == 0
        assert again.json()['shopping_list_id'] == first.json()['shopping_list_id']
        rows = db_session.scalars(
            select(ShoppingListItem).where(
                ShoppingListItem.template_id == seed['plums'].id
            )
        ).all()
        assert [(row.name, row.quantity) for row in rows] == [
            ('Damson Plums', Decimal('4.000'))
        ]

    def test_a_shortfall_of_part_of_a_piece_is_listed_as_a_whole_piece(
        self,
        client: TestClient,
        org: Organization,
        headers: dict[str, str],
        pantry: StorageLocation,
        db_session: Session,
    ) -> None:
        """The list is shopped in the ingredient's unit: 1.5 pieces is 2 pieces.

        The shortfall was rounded to the store's three places whatever the
        ingredient was counted in, so a run half a piece short asked the
        shopper to buy 1,5 szt. — part of a piece, which no shelf holds. The
        preview says the same quantity, so the button that puts the shortfall
        on the list states what the list will receive.
        """
        plums = _template(db_session, org, name='Damson Plums')
        pieces = db_session.scalars(select(Uom).where(Uom.symbol == 'pcs')).one()
        plums.uom_id = pieces.id
        butter = _template(db_session, org, name='Plum Butter')
        recipe = client.post(
            '/api/v1/maker/recipes',
            headers=headers,
            json={
                'output_template_id': str(butter.id),
                'name': 'Plum butter',
                'batch_yield_qty': '1',
                'is_default': True,
            },
        )
        assert recipe.status_code == 201, recipe.text
        line = client.post(
            f'/api/v1/maker/recipes/{recipe.json()["id"]}/bom-lines',
            headers=headers,
            json={
                'child_template_id': str(plums.id),
                'qty_per_batch': '1.5',
                'unit': 'pcs',
            },
        )
        assert line.status_code == 201, line.text

        run = _run(butter, pantry, '1')
        preview = client.post(
            '/api/v1/maker/production/orders/preview',
            headers=headers,
            json=run,
        )
        assert preview.status_code == 200, preview.text
        [plums_short] = preview.json()['ingredients']
        assert Decimal(plums_short['shortage']) == Decimal('1.5')
        assert Decimal(plums_short['to_buy']) == Decimal('2')
        assert plums_short['to_buy_uom_symbol'] == 'pcs'

        response = client.post(
            '/api/v1/maker/production/orders/shortages/shopping-list',
            headers=headers,
            json=run,
        )

        assert response.status_code == 200, response.text
        rows = db_session.scalars(
            select(ShoppingListItem).where(ShoppingListItem.template_id == plums.id)
        ).all()
        assert [(row.name, row.quantity) for row in rows] == [
            ('Damson Plums', Decimal('2.000'))
        ]

    def test_a_whole_piece_reached_through_the_batch_yield_stays_one_piece(
        self,
        client: TestClient,
        org: Organization,
        headers: dict[str, str],
        pantry: StorageLocation,
        db_session: Session,
    ) -> None:
        """A plan of five against a recipe yielding three is 5/3 batches.

        Three pieces per batch times 5/3 is five pieces, but the quotient
        keeps 28 significant digits and the product sits a few units in the
        last place above five. The requirement rounds up, so the panel's row
        read five pieces beside a button offering six, and the list received
        six — a piece the run never needed.
        """
        pieces = db_session.scalars(select(Uom).where(Uom.symbol == 'pcs')).one()
        eggs = _template(db_session, org, name='Eggs')
        eggs.uom_id = pieces.id
        db_session.commit()
        cake = _template(db_session, org, name='Cake')
        recipe = client.post(
            '/api/v1/maker/recipes',
            headers=headers,
            json={
                'output_template_id': str(cake.id),
                'name': 'Cake',
                'batch_yield_qty': '3',
                'is_default': True,
            },
        )
        assert recipe.status_code == 201, recipe.text
        line = client.post(
            f'/api/v1/maker/recipes/{recipe.json()["id"]}/bom-lines',
            headers=headers,
            json={
                'child_template_id': str(eggs.id),
                'qty_per_batch': '3',
                'unit': 'pcs',
                'uom_id': str(pieces.id),
            },
        )
        assert line.status_code == 201, line.text
        run = _run(cake, pantry, '5')

        preview = client.post(
            '/api/v1/maker/production/orders/preview',
            headers=headers,
            json=run,
        )

        assert preview.status_code == 200, preview.text
        [egg] = preview.json()['ingredients']
        # The row the panel shows at its own precision still reads five, and
        # the button offers the five the list is about to hold.
        assert abs(Decimal(egg['shortage']) - Decimal('5')) < Decimal('0.000001')
        assert Decimal(egg['to_buy']) == Decimal('5')

        response = client.post(
            '/api/v1/maker/production/orders/shortages/shopping-list',
            headers=headers,
            json=run,
        )

        assert response.status_code == 200, response.text
        rows = db_session.scalars(
            select(ShoppingListItem).where(ShoppingListItem.template_id == eggs.id)
        ).all()
        assert [(row.name, row.quantity) for row in rows] == [
            ('Eggs', Decimal('5.000'))
        ]

    def test_the_preview_and_the_line_agree_when_the_units_differ(
        self,
        client: TestClient,
        org: Organization,
        headers: dict[str, str],
        pantry: StorageLocation,
        db_session: Session,
    ) -> None:
        """An ounce line against a gram shelf: 2 oz less 2.8 g is 53.899 g.

        The preview converts the shortfall back from the recipe's unit, the
        line writes the difference in the stock unit. The two routes agree
        exactly, but a hair of division noise on the preview's side used to
        round one step above the write — the button promised 53.900 g and the
        list held 53.899 g.
        """
        grams = db_session.scalars(select(Uom).where(Uom.symbol == 'g')).one()
        ounces = db_session.scalars(select(Uom).where(Uom.symbol == 'oz')).one()
        chocolate = _template(db_session, org, name='Chocolate')
        chocolate.uom_id = grams.id
        db_session.commit()
        post_on_shelf(client, headers, chocolate, pantry.id, '2.8')
        cake = _template(db_session, org, name='Cake')
        recipe = client.post(
            '/api/v1/maker/recipes',
            headers=headers,
            json={
                'output_template_id': str(cake.id),
                'name': 'Cake',
                'batch_yield_qty': '1',
                'is_default': True,
            },
        )
        assert recipe.status_code == 201, recipe.text
        line = client.post(
            f'/api/v1/maker/recipes/{recipe.json()["id"]}/bom-lines',
            headers=headers,
            json={
                'child_template_id': str(chocolate.id),
                'qty_per_batch': '2',
                'unit': 'oz',
                'uom_id': str(ounces.id),
            },
        )
        assert line.status_code == 201, line.text
        run = _run(cake, pantry, '1')

        preview = client.post(
            '/api/v1/maker/production/orders/preview',
            headers=headers,
            json=run,
        )

        assert preview.status_code == 200, preview.text
        [short] = preview.json()['ingredients']
        assert short['to_buy_uom_symbol'] == 'g'
        assert Decimal(short['to_buy']) == Decimal('53.899')

        response = client.post(
            '/api/v1/maker/production/orders/shortages/shopping-list',
            headers=headers,
            json=run,
        )

        assert response.status_code == 200, response.text
        rows = db_session.scalars(
            select(ShoppingListItem).where(ShoppingListItem.template_id == chocolate.id)
        ).all()
        assert [(row.quantity, row.uom_id) for row in rows] == [
            (Decimal('53.899'), grams.id)
        ]

    def test_a_run_that_now_needs_more_raises_the_listed_line(
        self,
        client: TestClient,
        org: Organization,
        headers: dict[str, str],
        pantry: StorageLocation,
        db_session: Session,
    ) -> None:
        """A line already listed is not "covered" whatever the run now needs.

        The shortfall used to skip any product already on the list, so a run
        that grew from 20 to 30 left the 4 kg the smaller run asked for.
        """
        seed = _plum_butter(
            db_session, client, org, headers, pantry, plums_on_shelf='18'
        )
        url = '/api/v1/maker/production/orders/shortages/shopping-list'
        first = client.post(
            url, headers=headers, json=_run(seed['butter'], pantry, '20')
        )
        bigger = client.post(
            url, headers=headers, json=_run(seed['butter'], pantry, '30')
        )
        smaller = client.post(
            url, headers=headers, json=_run(seed['butter'], pantry, '20')
        )

        assert first.json()['added_count'] == 1
        assert bigger.json()['added_count'] == 0
        assert bigger.json()['raised_count'] == 1
        # A run that needs no more than the list already asks for changes nothing.
        assert smaller.json()['raised_count'] == 0
        rows = db_session.scalars(
            select(ShoppingListItem).where(
                ShoppingListItem.template_id == seed['plums'].id
            )
        ).all()
        assert [(row.name, row.quantity) for row in rows] == [
            ('Damson Plums', Decimal('15.000'))
        ]

    def test_a_line_listed_in_grams_covers_only_its_weight(
        self,
        client: TestClient,
        org: Organization,
        headers: dict[str, str],
        pantry: StorageLocation,
        db_session: Session,
    ) -> None:
        """500 g of plums already listed leaves 3.5 kg of a 4 kg shortfall to buy.

        The list's lines were summed whatever their unit, so the 500 g line
        read as 500 kg of cover and the run's shortfall added nothing.
        """
        seed = _plum_butter(
            db_session, client, org, headers, pantry, plums_on_shelf='18'
        )
        kg = db_session.scalars(select(Uom).where(Uom.symbol == 'kg')).first()
        g = db_session.scalars(select(Uom).where(Uom.symbol == 'g')).first()
        assert kg is not None and g is not None
        seed['plums'].uom_id = kg.id
        db_session.commit()
        listed = client.post(
            '/api/v1/shopping-lists', headers=headers, json={'name': 'This week'}
        )
        assert listed.status_code == 201, listed.text
        line = client.post(
            f'/api/v1/shopping-lists/{listed.json()["id"]}/items',
            headers=headers,
            json={
                'name': 'Damson Plums',
                'quantity': '500',
                'uom_id': str(g.id),
                'template_id': str(seed['plums'].id),
            },
        )
        assert line.status_code == 201, line.text
        url = '/api/v1/maker/production/orders/shortages/shopping-list'
        run = _run(seed['butter'], pantry, '20')

        first = client.post(url, headers=headers, json=run)
        again = client.post(url, headers=headers, json=run)

        assert first.status_code == 200, first.text
        assert first.json()['shopping_list_id'] == listed.json()['id']
        # What the screen reads: something went onto the list, then nothing.
        assert first.json()['added_count'] + first.json()['raised_count'] == 1
        assert again.json()['added_count'] + again.json()['raised_count'] == 0
        rows = db_session.scalars(
            select(ShoppingListItem).where(
                ShoppingListItem.template_id == seed['plums'].id
            )
        ).all()
        assert sorted((row.quantity, row.uom_id, row.source) for row in rows) == [
            (Decimal('3.500'), kg.id, 'production'),
            (Decimal('500.000'), g.id, 'manual'),
        ]

    def test_nothing_short_touches_no_list(
        self,
        client: TestClient,
        org: Organization,
        headers: dict[str, str],
        pantry: StorageLocation,
        db_session: Session,
    ) -> None:
        seed = _plum_butter(
            db_session, client, org, headers, pantry, plums_on_shelf='30'
        )

        response = client.post(
            '/api/v1/maker/production/orders/shortages/shopping-list',
            headers=headers,
            json=_run(seed['butter'], pantry, '20'),
        )

        assert response.status_code == 200, response.text
        assert response.json() == {
            'shopping_list_id': None,
            'list_name': None,
            'added_count': 0,
            'raised_count': 0,
        }

    def test_a_line_on_a_run_drawn_in_full_records_no_shortfall(
        self,
        client: TestClient,
        org: Organization,
        headers: dict[str, str],
        pantry: StorageLocation,
        db_session: Session,
    ) -> None:
        """The ordinary completion leaves the new column empty."""
        seed = _plum_butter(
            db_session, client, org, headers, pantry, plums_on_shelf='30'
        )
        draft = client.post(
            '/api/v1/maker/production/orders',
            headers=headers,
            json=_run(seed['butter'], pantry, '10'),
        )
        assert draft.status_code == 201, draft.text
        done = client.post(
            f'/api/v1/maker/production/orders/{draft.json()["id"]}/complete',
            headers=headers,
        )
        assert done.status_code == 200, done.text
        line = db_session.scalars(
            select(ProductionOrderLine).where(
                ProductionOrderLine.production_order_id == draft.json()['id']
            )
        ).one()
        assert line.shortfall_qty is None
