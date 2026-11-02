"""A record's unit is its product's, unless somebody deliberately says otherwise.

The matched product template's unit is the reference every other reader works
from: the documents executor converts a delivery into it, the BoM guard
refuses a line that cannot be read as it, and the stock screen shows it. One
door disagreed with all of them — ``POST /items`` took a unit of its own and
wrote it down without a word, so a record could contradict its own catalogue
row and nothing anywhere said who decided that or why.

The rule now: a unit that differs from the matched template's is a
*deliberate* choice. It travels with an explicit confirmation
(``unit_confirmed_over_template``), it is refused by name — both units, in the
reader's language — when the confirmation is missing, and when it is given
the choice lands in the record's history with both units beside it. The stock
guard (a unit is never swapped under stock) keeps its own answer unchanged.

A confirmed choice is how the quantity was typed, not the unit the record is
kept in: the record keeps its card's unit and the quantity is restated in it
(``test_a_record_is_kept_in_its_cards_unit``). The confirmed cases here name
grams on a card kept in kilograms, a unit that converts.
"""

from __future__ import annotations

import pytest
from fastapi import status
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.testclient import TestClient

from app.i18n.service import get_default_language, get_error_message
from app.models.item import Item
from app.models.item_history import ItemHistory
from app.models.label_pool import LabelPool
from app.models.product_template import ProductTemplate
from app.models.storage_location import StorageLocation
from app.models.uom import Uom
from tests.integration._shelf import anchor_pending_records

pytestmark = pytest.mark.integration

ITEMS_URL = '/api/v1/items'
TEMPLATES_URL = '/api/v1/items/product-templates'

#: The refusal read from the catalogue rather than copied, so this pins the
#: key the guard raises and not the wording a translator may revise.
REFUSAL = get_error_message(
    'item_unit_differs_from_template_confirmation_required',
    get_default_language(),
    product='Rye flour',
    template_unit='kg',
    chosen_unit='pcs',
)

#: The same refusal for the confirmed cases' unit, grams.
REFUSAL_IN_GRAMS = get_error_message(
    'item_unit_differs_from_template_confirmation_required',
    get_default_language(),
    product='Rye flour',
    template_unit='kg',
    chosen_unit='g',
)

#: The reason a confirmed choice is written down with.
REASON = 'unit_chosen_over_template'


def _uom(db: Session, symbol: str) -> Uom:
    uom = db.scalars(select(Uom).where(Uom.symbol == symbol)).first()
    assert uom is not None, f"'{symbol}' is not in the seeded catalogue"
    return uom


def _template(client: TestClient, headers: dict[str, str], name: str, uom_id) -> dict:
    response = client.post(
        TEMPLATES_URL, headers=headers, json={'name': name, 'uom_id': str(uom_id)}
    )
    assert response.status_code == status.HTTP_201_CREATED, response.text
    return response.json()


def _history(db: Session, item_id) -> list[dict]:
    db.expire_all()
    return [
        row.changes or {}
        for row in db.scalars(
            select(ItemHistory).where(ItemHistory.item_id == item_id)
        ).all()
    ]


def _unit_choice_rows(db: Session, item_id) -> list[dict]:
    return [row for row in _history(db, item_id) if row.get('reason') == REASON]


class TestTheCreateDoorRefusesADifferenceNobodyConfirmed:
    def test_a_unit_that_contradicts_the_template_is_refused_by_name(
        self,
        client: TestClient,
        db_session: Session,
        auth_headers: dict[str, str],
        test_storage_location: StorageLocation,
    ) -> None:
        """The silent case, on the door that used to accept it.

        ``Rye flour`` is kept in kilograms. Asking for pieces used to answer
        201 and write the record — no warning, no history, no trace of the
        decision anywhere but the row itself.
        """
        kg = _uom(db_session, 'kg')
        pcs = _uom(db_session, 'pcs')
        _template(client, auth_headers, 'Rye flour', kg.id)

        response = client.post(
            ITEMS_URL,
            headers=auth_headers,
            json={
                'name': 'Rye flour',
                'location_id': str(test_storage_location.id),
                'quantity': 1,
                'uom_id': str(pcs.id),
            },
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.text
        assert response.json()['detail']['message'] == REFUSAL
        db_session.expire_all()
        assert (
            db_session.scalars(select(Item).where(Item.name == 'Rye flour')).first()
            is None
        ), 'the refused record must not land'

    def test_the_same_unit_the_template_keeps_needs_no_confirmation(
        self,
        client: TestClient,
        db_session: Session,
        auth_headers: dict[str, str],
        test_storage_location: StorageLocation,
    ) -> None:
        """The control: agreement is not a choice and asks for nothing."""
        kg = _uom(db_session, 'kg')
        _template(client, auth_headers, 'Rye flour', kg.id)

        response = client.post(
            ITEMS_URL,
            headers=auth_headers,
            json={
                'name': 'Rye flour',
                'location_id': str(test_storage_location.id),
                'quantity': 1,
                'uom_id': str(kg.id),
            },
        )

        assert response.status_code == status.HTTP_201_CREATED, response.text
        assert response.json()['uom']['symbol'] == 'kg'

    def test_a_product_the_catalogue_does_not_know_is_not_asked_about(
        self,
        client: TestClient,
        db_session: Session,
        auth_headers: dict[str, str],
        test_storage_location: StorageLocation,
    ) -> None:
        """No matched template means no reference to differ from."""
        grams = _uom(db_session, 'g')

        response = client.post(
            ITEMS_URL,
            headers=auth_headers,
            json={
                'name': 'Uncatalogued thing',
                'location_id': str(test_storage_location.id),
                'quantity': 1,
                'uom_id': str(grams.id),
            },
        )

        assert response.status_code == status.HTTP_201_CREATED, response.text
        assert response.json()['uom']['symbol'] == 'g'


class TestTheLookupNamesTheUnitTheRecordWillLandWith:
    def test_a_name_lookup_answers_the_template_unit(
        self,
        client: TestClient,
        db_session: Session,
        auth_headers: dict[str, str],
        test_storage_location: StorageLocation,
    ) -> None:
        """The form's hint, from the same matching the create path does.

        A second matching rule here is how the unit a form showed and the
        unit the record landed with came to be two different answers.
        """
        kg = _uom(db_session, 'kg')
        _template(client, auth_headers, 'Rye flour', kg.id)

        response = client.get(
            f'{ITEMS_URL}/product-templates/lookup',
            headers=auth_headers,
            params={'name': 'Rye flour'},
        )

        assert response.status_code == status.HTTP_200_OK, response.text
        body = response.json()
        assert body['uom_id'] == str(kg.id)
        assert body['uom_symbol'] == 'kg'
        assert body['uom_name'] == 'Kilogram'

    @pytest.mark.parametrize(
        'params',
        [
            {'name': 'Nothing like this exists'},
            {'barcode': '2000000000008'},
            {'sku': 'NO-SUCH-SKU'},
        ],
    )
    def test_a_product_the_catalogue_does_not_know_is_no_template(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        params: dict[str, str],
    ) -> None:
        """No template means no hint — the form shows nothing, not a guess.

        A new product is the normal case, asked on every name a form types:
        answered as a 404 it was an error in the browser's console each time.
        """
        response = client.get(
            f'{ITEMS_URL}/product-templates/lookup',
            headers=auth_headers,
            params=params,
        )

        assert response.status_code == status.HTTP_200_OK, response.text
        assert response.json() is None


class TestAConfirmedChoiceIsWrittenDown:
    def test_the_confirmed_create_lands_and_records_both_units(
        self,
        client: TestClient,
        db_session: Session,
        auth_headers: dict[str, str],
        test_storage_location: StorageLocation,
    ) -> None:
        """The trace: which unit the product is kept in, and which one was chosen."""
        kg = _uom(db_session, 'kg')
        grams = _uom(db_session, 'g')
        _template(client, auth_headers, 'Rye flour', kg.id)

        response = client.post(
            ITEMS_URL,
            headers=auth_headers,
            json={
                'name': 'Rye flour',
                'location_id': str(test_storage_location.id),
                'quantity': 500,
                'uom_id': str(grams.id),
                'unit_confirmed_over_template': True,
            },
        )

        assert response.status_code == status.HTTP_201_CREATED, response.text
        assert response.json()['uom']['symbol'] == 'kg'

        item_id = response.json()['id']
        rows = _unit_choice_rows(db_session, item_id)
        assert len(rows) == 1, f'expected one recorded choice, got {rows}'
        assert rows[0] == {
            'reason': REASON,
            'template_uom': 'kg',
            'template_uom_name': 'Kilogram',
            'chosen_uom': 'g',
            'chosen_uom_name': 'Gram',
            'entered_quantity': '500.000',
            'kept_quantity': '0.500',
        }

    def test_an_unconfirmed_create_writes_no_such_row(
        self,
        client: TestClient,
        db_session: Session,
        auth_headers: dict[str, str],
        test_storage_location: StorageLocation,
    ) -> None:
        """The control: the record is not what gets a choice written on it.

        Nothing was chosen here — the request named the template's own unit —
        so a row saying "chosen over the template" would be a false record.
        """
        kg = _uom(db_session, 'kg')
        _template(client, auth_headers, 'Rye flour', kg.id)

        response = client.post(
            ITEMS_URL,
            headers=auth_headers,
            json={
                'name': 'Rye flour',
                'location_id': str(test_storage_location.id),
                'quantity': 1,
                'uom_id': str(kg.id),
            },
        )

        assert response.status_code == status.HTTP_201_CREATED, response.text
        assert _unit_choice_rows(db_session, response.json()['id']) == []

    def test_a_confirmation_over_the_template_own_unit_writes_no_row(
        self,
        client: TestClient,
        db_session: Session,
        auth_headers: dict[str, str],
        test_storage_location: StorageLocation,
    ) -> None:
        """A confirmation with no difference behind it is not a choice.

        The importer spends the flag on every row it writes — it cannot know
        which rows will match a template — so the flag alone cannot be what
        puts the entry in the history. ``kg`` confirmed over a template that
        keeps ``kg`` is a non-choice, and a row claiming otherwise is a lie
        the reader meets on the product's history tab.
        """
        kg = _uom(db_session, 'kg')
        _template(client, auth_headers, 'Rye flour', kg.id)

        response = client.post(
            ITEMS_URL,
            headers=auth_headers,
            json={
                'name': 'Rye flour',
                'location_id': str(test_storage_location.id),
                'quantity': 1,
                'uom_id': str(kg.id),
                'unit_confirmed_over_template': True,
            },
        )

        assert response.status_code == status.HTTP_201_CREATED, response.text
        assert _unit_choice_rows(db_session, response.json()['id']) == []


class TestTheUpdateDoorAnswersTheSameWay:
    def _empty_item(self, db: Session, org_id, storage_id, uom_id) -> Item:
        """A record with nothing on the shelf: the swap guard lets it move."""
        from decimal import Decimal

        item = Item(
            name='Rye flour',
            organization_id=org_id,
            storage_location_id=storage_id,
            quantity=Decimal('0'),
            uom_id=uom_id,
        )
        db.add(item)
        db.commit()
        db.refresh(item)
        return item

    def _with_template(self, db: Session, item: Item, kg_id) -> None:
        template = ProductTemplate(
            organization_id=item.organization_id,
            name=item.name,
            uom_id=kg_id,
        )
        db.add(template)
        db.commit()
        item.template_id = template.id
        db.add(item)
        anchor_pending_records(db)
        db.commit()

    def test_moving_the_unit_off_the_template_is_refused_until_confirmed(
        self,
        client: TestClient,
        db_session: Session,
        auth_headers: dict[str, str],
        test_household,
        test_storage_location: StorageLocation,
    ) -> None:
        kg = _uom(db_session, 'kg')
        grams = _uom(db_session, 'g')
        item = self._empty_item(
            db_session, test_household.id, test_storage_location.id, kg.id
        )
        self._with_template(db_session, item, kg.id)

        refused = client.put(
            f'{ITEMS_URL}/{item.id}',
            headers=auth_headers,
            json={'uom_id': str(grams.id)},
        )

        assert refused.status_code == status.HTTP_400_BAD_REQUEST, refused.text
        assert refused.json()['detail']['message'] == REFUSAL_IN_GRAMS

        confirmed = client.put(
            f'{ITEMS_URL}/{item.id}',
            headers=auth_headers,
            json={'uom_id': str(grams.id), 'unit_confirmed_over_template': True},
        )

        assert confirmed.status_code == status.HTTP_200_OK, confirmed.text
        # Read from the row, not from the response: this is a test about what
        # the record is kept in — its card's unit, whatever the edit named.
        db_session.expire_all()
        stored = db_session.get(Item, item.id)
        assert stored is not None and stored.uom_id == kg.id
        rows = _unit_choice_rows(db_session, item.id)
        assert [row['template_uom'] for row in rows] == ['kg']
        assert [row['chosen_uom'] for row in rows] == ['g']


SCAN_ASSIGN_URL = '/api/v1/labels/scan/{short_code}/assign'


class TestTheScanDoorAnswersTheSameWay:
    """The third door, and the one that used to keep its own opinion.

    The form refused a difference nobody confirmed; the scan built the row
    straight from the request and let any unit land beside the template's.
    The product form after a scan is the same form, so it asks the same
    question — and the answer used to fall on the floor, because the scan's
    own request model had no field to carry it.
    """

    def _label(self, db: Session, org_id, user_id, short_code: str) -> LabelPool:
        label = LabelPool(
            short_code=short_code,
            organization_id=org_id,
            created_by=user_id,
            is_assigned=False,
        )
        db.add(label)
        db.commit()
        return label

    def _scan(
        self,
        client: TestClient,
        headers: dict[str, str],
        short_code: str,
        storage_id,
        *,
        uom_id,
        name: str = 'Rye flour',
        **extra,
    ):
        return client.post(
            SCAN_ASSIGN_URL.format(short_code=short_code),
            headers=headers,
            json={
                'name': name,
                'location_id': str(storage_id),
                'quantity': 1,
                'uom_id': str(uom_id),
                **extra,
            },
        )

    def test_a_scan_naming_a_unit_the_template_does_not_keep_is_refused_by_name(
        self,
        client: TestClient,
        db_session: Session,
        auth_headers: dict[str, str],
        test_household,
        test_user,
        test_storage_location: StorageLocation,
    ) -> None:
        """The silent case, on the door that used to accept it.

        ``Rye flour`` is kept in kilograms. A scan naming pieces answered 200
        and wrote the record — no warning, no history, no trace of the
        decision anywhere but the row itself.
        """
        kg = _uom(db_session, 'kg')
        pcs = _uom(db_session, 'pcs')
        _template(client, auth_headers, 'Rye flour', kg.id)
        self._label(db_session, test_household.id, test_user.id, 'STM-SCN1')

        response = self._scan(
            client,
            auth_headers,
            'STM-SCN1',
            test_storage_location.id,
            uom_id=pcs.id,
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.text
        assert response.json()['detail']['message'] == REFUSAL
        db_session.expire_all()
        assert (
            db_session.scalars(select(Item).where(Item.name == 'Rye flour')).first()
            is None
        ), 'the refused record must not land'
        left_over = db_session.scalars(
            select(LabelPool).where(LabelPool.short_code == 'STM-SCN1')
        ).first()
        assert left_over is not None
        assert not left_over.is_assigned, 'a refused scan leaves the label free'

    def test_a_confirmed_scan_lands_and_records_both_units(
        self,
        client: TestClient,
        db_session: Session,
        auth_headers: dict[str, str],
        test_household,
        test_user,
        test_storage_location: StorageLocation,
    ) -> None:
        """The reader who meant it: the record lands and the choice is written."""
        kg = _uom(db_session, 'kg')
        grams = _uom(db_session, 'g')
        _template(client, auth_headers, 'Rye flour', kg.id)
        self._label(db_session, test_household.id, test_user.id, 'STM-SCN2')

        response = self._scan(
            client,
            auth_headers,
            'STM-SCN2',
            test_storage_location.id,
            uom_id=grams.id,
            unit_confirmed_over_template=True,
        )

        assert response.status_code == status.HTTP_200_OK, response.text
        assert response.json()['uom']['symbol'] == 'kg'
        assert response.json()['quantity'] == '0.001'

        rows = _unit_choice_rows(db_session, response.json()['id'])
        assert len(rows) == 1, f'expected one recorded choice, got {rows}'
        assert rows[0] == {
            'reason': REASON,
            'template_uom': 'kg',
            'template_uom_name': 'Kilogram',
            'chosen_uom': 'g',
            'chosen_uom_name': 'Gram',
            'entered_quantity': '1.000',
            'kept_quantity': '0.001',
        }

    def test_a_scan_naming_the_template_own_unit_needs_no_confirmation(
        self,
        client: TestClient,
        db_session: Session,
        auth_headers: dict[str, str],
        test_household,
        test_user,
        test_storage_location: StorageLocation,
    ) -> None:
        """The control: agreement is not a choice and asks for nothing."""
        kg = _uom(db_session, 'kg')
        _template(client, auth_headers, 'Rye flour', kg.id)
        self._label(db_session, test_household.id, test_user.id, 'STM-SCN3')

        response = self._scan(
            client,
            auth_headers,
            'STM-SCN3',
            test_storage_location.id,
            uom_id=kg.id,
        )

        assert response.status_code == status.HTTP_200_OK, response.text
        assert response.json()['uom']['symbol'] == 'kg'
        assert _unit_choice_rows(db_session, response.json()['id']) == []
