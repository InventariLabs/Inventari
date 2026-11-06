"""The unit is settled before anything is asked of it.

Three doors that minted a unitless catalogue row. A fourth
stayed open: a record with no ``template_id`` whose low-stock threshold (or
unit weight) is written mints its template from ``_AUDITED_TEMPLATE_FIELDS`` alone —
no unit travels with those fields, so the row was born blank while the record
standing on it knew its unit. Measured on a live stack: the template minted
by ``PUT /items/{id} {"min_quantity": 5}`` carried ``uom_id = NULL`` beside a
record holding ``pcs``. This door now hands the template what the record
knows, and pieces for a record that predates the default.

The second half is what "no piece unit" means. ``_default_piece_uom_id_async``
answers with the catalogue's piece row — the organization's own, else the
system one — and used to return ``None`` when the installation has neither,
letting that ``None`` travel on as a blank unit: the same silent hole, three
doors wide. The installation that cannot answer "a quantity of what" now says
so, in the reader's language, instead of recording a number nobody can read.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import func, select, text

from app.i18n.service import get_default_language, get_error_message
from app.models.item import Item
from app.models.product_template import ProductTemplate
from app.models.uom import Uom

ITEM_URL = '/api/v1/items'
TEMPLATE_URL = '/api/v1/items/product-templates'
QUICK_URL = '/api/v1/warehouse/product-search/quick-create'

#: The sentence a reader gets when the catalogue has no piece unit — read
#: from the catalogue rather than copied, so the test pins the key the code
#: raises and not the wording a translator may revise.
REFUSAL = get_error_message('piece_unit_missing_from_catalogue', get_default_language())


def _uom_id(db, symbol: str) -> str:
    return str(db.scalars(select(Uom).where(Uom.symbol == symbol)).first().id)


def _template_uom_symbol(db, template_id: str) -> str | None:
    tpl = db.scalars(
        select(ProductTemplate).where(ProductTemplate.id == template_id)
    ).one()
    return (
        db.scalars(select(Uom).where(Uom.id == tpl.uom_id)).one().symbol
        if tpl.uom_id
        else None
    )


def _unitless_templates(db) -> int:
    return db.scalar(
        select(func.count())
        .select_from(ProductTemplate)
        .where(ProductTemplate.uom_id.is_(None))
    )


def _drop_every_piece_row(db) -> None:
    """Leave the installation with no piece unit anywhere.

    The neutral catalogue is seeded at boot, so an installation reaches this
    state only through a boot that never ran the seeder — the future this
    guard is for. Both halves go: an organization's own row and the system
    one.
    """
    db.execute(text("DELETE FROM uoms WHERE symbol = 'pcs'"))
    db.commit()


def _create_item(client, auth_headers, storage, **overrides) -> dict:
    payload = {
        'name': 'Unit probe',
        'quantity': 1,
        'location_id': str(storage.id),
    }
    payload.update(overrides)
    response = client.post(ITEM_URL, headers=auth_headers, json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def _record_that_predates_its_card(db, storage, *, unit: str | None) -> str:
    """A record as it stands before any card: no template, no stock posted.

    ``unit`` is the record's own unit symbol, the case the review measured;
    ``None`` is what a row written before the archived ``uompcs01`` looks like. Inserted
    rather than created and then unhooked from its card: the create path
    mints a card of the same name and puts the stock under it, and an update
    that adopts a card finds that one by name instead of minting its own.
    """
    item = Item(
        organization_id=storage.organization_id,
        storage_location_id=storage.id,
        name='Unit probe',
        quantity=Decimal('1'),
        uom_id=_uom_id(db, unit) if unit else None,
    )
    db.add(item)
    db.commit()
    return str(item.id)


@pytest.mark.integration
class TestTheFourthDoor:
    """An update that mints a template hands it the unit it knows."""

    def test_the_template_minted_by_an_update_carries_the_records_unit(
        self, client, auth_headers, db_session, test_storage_location
    ) -> None:
        item_id = _record_that_predates_its_card(
            db_session, test_storage_location, unit='kg'
        )

        response = client.put(
            f'{ITEM_URL}/{item_id}',
            headers=auth_headers,
            json={'min_quantity': 5},
        )

        assert response.status_code == 200, response.text
        template_id = response.json()['template_id']
        assert template_id is not None
        # The record's unit, not the fallback: a bare default would answer
        # 'pcs' here and the two rows would disagree about the same product.
        assert _template_uom_symbol(db_session, template_id) == 'kg'

    def test_a_record_older_than_the_default_still_answers_pieces(
        self, client, auth_headers, db_session, test_storage_location
    ) -> None:
        item_id = _record_that_predates_its_card(
            db_session, test_storage_location, unit=None
        )

        response = client.put(
            f'{ITEM_URL}/{item_id}',
            headers=auth_headers,
            json={'min_quantity': 5},
        )

        assert response.status_code == 200, response.text
        template_id = response.json()['template_id']
        assert template_id is not None
        assert _template_uom_symbol(db_session, template_id) == 'pcs'

    def test_the_unit_weight_written_on_a_recordless_item_is_no_fifth_door(
        self, client, auth_headers, db_session, test_storage_location
    ) -> None:
        """``weight_value`` travels the same branch as ``min_quantity``."""
        item_id = _record_that_predates_its_card(
            db_session, test_storage_location, unit=None
        )

        response = client.put(
            f'{ITEM_URL}/{item_id}',
            headers=auth_headers,
            json={'weight_value': 250},
        )

        assert response.status_code == 200, response.text
        template_id = response.json()['template_id']
        assert template_id is not None
        assert _template_uom_symbol(db_session, template_id) == 'pcs'


@pytest.mark.integration
class TestAnInstallationWithoutAPieceUnit:
    """No piece row means the catalogue cannot answer — so it says so."""

    def test_an_item_with_no_chosen_unit_is_refused(
        self, client, auth_headers, db_session, test_storage_location
    ) -> None:
        _drop_every_piece_row(db_session)

        response = client.post(
            ITEM_URL,
            headers=auth_headers,
            json={
                'name': 'No catalogue to answer with',
                'quantity': 1,
                'location_id': str(test_storage_location.id),
            },
        )

        assert response.status_code == 400, response.text
        message = response.json()['detail']['message']
        assert message == REFUSAL, message
        # And nothing was written on the way to the refusal: a row left
        # behind by a failed create is the unitless row under another name.
        assert _unitless_templates(db_session) == 0

    def test_a_template_posted_without_a_unit_is_refused(
        self, client, auth_headers, db_session
    ) -> None:
        _drop_every_piece_row(db_session)

        response = client.post(
            TEMPLATE_URL, headers=auth_headers, json={'name': 'Nothing to answer with'}
        )

        assert response.status_code == 400, response.text
        assert response.json()['detail']['message'] == REFUSAL
        assert _unitless_templates(db_session) == 0

    def test_the_quick_create_stub_is_refused(
        self, client, auth_headers, db_session
    ) -> None:
        _drop_every_piece_row(db_session)

        response = client.post(
            QUICK_URL,
            headers=auth_headers,
            json={'name': 'Nothing to answer with either'},
        )

        assert response.status_code == 409, response.text
        assert response.json()['detail']['message'] == REFUSAL
        assert _unitless_templates(db_session) == 0

    def test_a_chosen_unit_still_carries_the_record_through(
        self, client, auth_headers, db_session, test_storage_location
    ) -> None:
        """The refusal is narrow: it is about a question nobody answered.

        A caller who names a unit — or a catalogue row that already names
        one — asked the question and answered it; the empty default has
        nothing to add and nothing to refuse.
        """
        _drop_every_piece_row(db_session)

        item = _create_item(
            client,
            auth_headers,
            test_storage_location,
            uom_id=_uom_id(db_session, 'kg'),
        )

        assert item['uom_id'] == _uom_id(db_session, 'kg')
        assert _template_uom_symbol(db_session, item['template_id']) == 'kg'
