"""A partner sheet lands once per partner.

Partners were the second thing a small company keeps in Excel, and the only
one without a way in. The import takes the same shape as the product import:
a header row, a column mapping, and a per-row report of what was refused and
why. A row naming a partner the organization already has — the same name in
any letter case, or the same tax id — is refused, not doubled.
"""

import io
import json

import pandas as pd
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.partner import Partner


def _csv(rows: list[dict]) -> bytes:
    return pd.DataFrame(rows).to_csv(index=False).encode()


def _xlsx(rows: list[dict]) -> bytes:
    buffer = io.BytesIO()
    pd.DataFrame(rows).to_excel(buffer, index=False)
    return buffer.getvalue()


MAPPING = {
    'name': 'Nazwa',
    'type': 'Typ',
    'tax_id': 'NIP',
    'email': 'E-mail',
    'city': 'Miasto',
    'country': 'Kraj',
}


def _import(client: TestClient, headers: dict, content: bytes, **form):
    return client.post(
        '/api/v1/partners/import',
        files={'file': ('partnerzy.csv', content, 'text/csv')},
        data={'mapping_json': json.dumps(MAPPING), **form},
        headers=headers,
    )


@pytest.mark.integration
class TestAPartnerSheetLandsOncePerPartner:
    def test_three_good_rows_land_and_the_reader_learns_why_two_did_not(
        self, client: TestClient, auth_headers: dict, db_session: Session
    ):
        rows = [
            {
                'Nazwa': 'Hurtownia ABC',
                'Typ': 'supplier',
                'NIP': 'PL 111-222-33-44',
                'E-mail': 'abc@example.com',
                'Miasto': 'Warszawa',
                'Kraj': 'pl',
            },
            {
                'Nazwa': 'Firma Beta',
                'Typ': 'customer',
                'NIP': None,
                'E-mail': None,
                'Miasto': None,
                'Kraj': None,
            },
            {
                'Nazwa': 'Gamma sp. z o.o.',
                'Typ': None,
                'NIP': 'PL3333333333',
                'E-mail': None,
                'Miasto': None,
                'Kraj': None,
            },
            {
                'Nazwa': 'hurtownia abc',
                'Typ': 'customer',
                'NIP': None,
                'E-mail': None,
                'Miasto': None,
                'Kraj': None,
            },
            {
                'Nazwa': None,
                'Typ': 'supplier',
                'NIP': 'PL5555555555',
                'E-mail': None,
                'Miasto': None,
                'Kraj': None,
            },
        ]
        resp = _import(client, auth_headers, _csv(rows), default_type='SUPPLIER')
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert (body['total'], body['imported'], body['failed']) == (5, 3, 2)
        assert [e['row'] for e in body['errors']] == [5, 6]
        assert 'Hurtownia ABC' in body['errors'][0]['error']
        assert 'name' in body['errors'][1]['error'].lower()

        partners = db_session.scalars(
            select(Partner).where(Partner.name.ilike('hurtownia abc'))
        ).all()
        assert len(partners) == 1
        abc = partners[0]
        assert abc.type == 'SUPPLIER'
        assert abc.tax_id == 'PL 111-222-33-44'
        assert abc.address == {
            'street': None,
            'city': 'Warszawa',
            'postal_code': None,
            'country': 'PL',
        }
        gamma = db_session.scalar(
            select(Partner).where(Partner.name == 'Gamma sp. z o.o.')
        )
        assert gamma is not None and gamma.type == 'SUPPLIER'

    def test_a_tax_id_the_organization_already_has_is_refused(
        self, client: TestClient, auth_headers: dict
    ):
        first = client.post(
            '/api/v1/partners',
            json={
                'name': 'Stary dostawca',
                'type': 'SUPPLIER',
                'tax_id': 'PL1234567890',
            },
            headers=auth_headers,
        )
        assert first.status_code == 201, first.text

        rows = [
            {
                'Nazwa': 'Nowa nazwa tej samej firmy',
                'Typ': 'supplier',
                'NIP': 'pl 123 456 78 90',
                'E-mail': None,
                'Miasto': None,
                'Kraj': None,
            },
            {
                'Nazwa': 'Zła rola',
                'Typ': 'wholesaler',
                'NIP': None,
                'E-mail': None,
                'Miasto': None,
                'Kraj': None,
            },
        ]
        resp = _import(client, auth_headers, _csv(rows))
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert (body['imported'], body['failed']) == (0, 2)
        assert 'Stary dostawca' in body['errors'][0]['error']
        assert 'Typ' in body['errors'][1]['error']

    def test_analyze_returns_the_header_row_and_a_preview_of_a_workbook(
        self, client: TestClient, auth_headers: dict
    ):
        resp = client.post(
            '/api/v1/partners/import/analyze',
            files={
                'file': (
                    'partnerzy.xlsx',
                    _xlsx([{'Nazwa': 'X', 'NIP': '1'}]),
                    'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                )
            },
            headers=auth_headers,
        )
        assert resp.status_code == 200, resp.text
        # Headers and the first rows: the mapping step shows both, because a
        # mapping chosen against column names alone cannot be checked by the
        # person choosing it.
        body = resp.json()
        assert body['headers'] == ['Nazwa', 'NIP']
        assert body['total_rows'] == 1
        # The sheet typed '1' as text, so text is how the preview reads it:
        # the reader types every cell as the text it is, on the workbook
        # branch as on the CSV branch, and never re-infers a column.
        assert body['preview_rows'] == [{'Nazwa': 'X', 'NIP': '1'}]
