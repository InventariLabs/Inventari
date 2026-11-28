"""A partner sheet exported from another tool moves in as it is written.

A country may be named in words, and a contact person's row, which names the
company it belongs to, becomes part of that company rather than a partner of
its own.
"""

import json

import pandas as pd
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.partner import Partner

pytestmark = pytest.mark.integration

#: The mapping the dialog suggests for Odoo's contact export.
MAPPING = {
    'name': 'Name',
    'company': 'Related Company',
    'code': 'Reference',
    'tax_id': 'Tax ID',
    'street': 'Street',
    'city': 'City',
    'postal_code': 'Zip',
    'country': 'Country',
    'email': 'Email',
    'phone': 'Phone',
    'website': 'Website Link',
    'notes': 'Notes',
}


def _odoo(**cells) -> dict:
    row = {
        'Display Name': '',
        'Name': '',
        'Is a Company': 'True',
        'Related Company': '',
        'Reference': '',
        'Tax ID': '',
        'Street': '',
        'Street2': '',
        'City': '',
        'Zip': '',
        'State': '',
        'Country': '',
        'Email': '',
        'Phone': '',
        'Mobile': '',
        'Website Link': '',
        'Tags': '',
        'Notes': '',
    }
    return {**row, **cells}


def _import(client: TestClient, headers: dict, rows: list[dict]) -> dict:
    response = client.post(
        '/api/v1/partners/import',
        files={
            'file': (
                'partners.csv',
                pd.DataFrame(rows).to_csv(index=False).encode(),
                'text/csv',
            )
        },
        data={'mapping_json': json.dumps(MAPPING)},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    return response.json()


def _partners(db: Session) -> dict[str, Partner]:
    db.expire_all()
    return {p.name: p for p in db.scalars(select(Partner)).all()}


class TestACountryNamedInWords:
    @pytest.mark.parametrize(
        ('written', 'code'),
        [
            ('Poland', 'PL'),
            ('france', 'FR'),
            ('Polska', 'PL'),
            ('Deutschland', 'DE'),
            ('España', 'ES'),
            ('Polónia', 'PL'),
            ('Polônia', 'PL'),
            ('Allemagne', 'DE'),
            ('Czech Republic', 'CZ'),
            ('United States', 'US'),
            ('it', 'IT'),
        ],
    )
    def test_it_is_stored_as_its_code(
        self,
        client: TestClient,
        auth_headers: dict,
        db_session: Session,
        written: str,
        code: str,
    ):
        result = _import(
            client, auth_headers, [_odoo(Name='Named Land', Country=written)]
        )

        assert result['imported'] == 1, result
        assert _partners(db_session)['Named Land'].address['country'] == code

    def test_a_word_that_names_no_country_is_still_refused(
        self, client: TestClient, auth_headers: dict
    ):
        result = _import(
            client, auth_headers, [_odoo(Name='Nowhere', Country='Atlantis')]
        )

        assert (result['imported'], result['failed']) == (0, 1), result


class TestAContactPersonRow:
    def test_it_goes_onto_its_company_instead_of_becoming_a_supplier(
        self, client: TestClient, auth_headers: dict, db_session: Session
    ):
        rows = [
            # The contact may stand above its company.
            _odoo(
                **{
                    'Name': 'Anna Nowak',
                    'Is a Company': 'False',
                    'Related Company': 'Acme Foods',
                    'Email': 'anna@acme.example',
                    'Phone': '+48 600 000 001',
                }
            ),
            _odoo(Name='Acme Foods', Country='Poland', Notes='Pays in 14 days'),
            _odoo(
                **{
                    'Name': 'Jan Kowalski',
                    'Is a Company': 'False',
                    'Related Company': 'ACME  foods',
                }
            ),
        ]

        result = _import(client, auth_headers, rows)

        assert (result['imported'], result['contacts'], result['failed']) == (
            1,
            2,
            0,
        ), result
        partners = _partners(db_session)
        assert set(partners) >= {'Acme Foods'}
        assert not {'Anna Nowak', 'Jan Kowalski'} & set(partners)
        company = partners['Acme Foods']
        assert company.contact_person == 'Anna Nowak'
        assert company.notes.split('\n') == [
            'Pays in 14 days',
            'Anna Nowak, anna@acme.example, +48 600 000 001',
            'Jan Kowalski',
        ]

    def test_a_contact_whose_company_is_already_here_joins_it(
        self, client: TestClient, auth_headers: dict, db_session: Session
    ):
        _import(client, auth_headers, [_odoo(Name='Here Already')])

        result = _import(
            client,
            auth_headers,
            [
                _odoo(
                    **{
                        'Name': 'Eva',
                        'Related Company': 'Here Already',
                        'Email': 'eva@here.example',
                    }
                ),
            ],
        )

        assert (result['imported'], result['contacts'], result['failed']) == (
            0,
            1,
            0,
        ), result
        partners = _partners(db_session)
        assert 'Eva' not in partners
        company = partners['Here Already']
        assert company.contact_person == 'Eva'
        assert company.notes == 'Eva, eva@here.example'

    def test_a_contact_joins_the_notes_of_a_company_that_has_a_contact_person(
        self, client: TestClient, auth_headers: dict, db_session: Session
    ):
        _import(client, auth_headers, [_odoo(Name='Here Already')])
        company = _partners(db_session)['Here Already']
        company.contact_person = 'Maria'
        company.notes = 'Pays in 14 days'
        db_session.commit()

        result = _import(
            client,
            auth_headers,
            [_odoo(**{'Name': 'Eva', 'Related Company': 'Here Already'})],
        )

        assert (result['contacts'], result['failed']) == (1, 0), result

        # The same export uploaded again has nothing new to add.
        again = _import(
            client,
            auth_headers,
            [_odoo(**{'Name': 'Eva', 'Related Company': 'Here Already'})],
        )

        assert (again['contacts'], again['failed']) == (1, 0), again
        db_session.expire_all()
        company = _partners(db_session)['Here Already']
        assert company.contact_person == 'Maria'
        assert company.notes.split('\n') == ['Pays in 14 days', 'Eva']

    def test_a_contact_whose_company_is_found_nowhere_is_named(
        self, client: TestClient, auth_headers: dict, db_session: Session
    ):
        result = _import(
            client,
            auth_headers,
            [_odoo(**{'Name': 'Ola', 'Related Company': 'Unlisted'})],
        )

        assert (result['contacts'], result['failed']) == (0, 1), result
        assert result['errors'][0]['row'] == 1
        assert 'Unlisted' in result['errors'][0]['error']
        assert 'Ola' not in _partners(db_session)

    def test_a_company_naming_itself_is_a_partner(
        self, client: TestClient, auth_headers: dict, db_session: Session
    ):
        result = _import(
            client,
            auth_headers,
            [_odoo(**{'Name': 'Solo', 'Related Company': 'Solo'})],
        )

        assert (result['imported'], result['contacts']) == (1, 0), result
