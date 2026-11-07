"""The partner refusals speak the reader's language.

Three refusals of ``partner_service`` reached the reader through the 409 the
router wraps them in, and two more reach it through the row report of the
partner import — all five were English literals: a buyer whose sheet repeated
a supplier read `Duplicate partner: "Stary dostawca" already has this name or
tax id` under a report whose own column headers were already translated.

Each now raises through a catalogue key. The assertions are equalities
against the Polish text, not status codes: a service reverted to its literal
still answers 409 (or a 200 row report), and only the sentence tells the two
builds apart. The 409 envelope carries no language claim of its own — the
message is translated where it is raised, which is what is being pinned here.
"""

from __future__ import annotations

import json

import pandas as pd
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.organization import Organization
from app.models.user import User

pytestmark = pytest.mark.integration

PL_HEADERS = {'Accept-Language': 'pl'}

MAPPING = {
    'name': 'Nazwa',
    'type': 'Typ',
    'tax_id': 'NIP',
    'email': 'E-mail',
    'city': 'Miasto',
    'country': 'Kraj',
}


def _polish(headers: dict[str, str]) -> dict[str, str]:
    return {**headers, **PL_HEADERS}


def _message(response) -> str:
    detail = response.json()['detail']
    return detail['message']


def _csv(rows: list[dict]) -> bytes:
    return pd.DataFrame(rows).to_csv(index=False).encode()


def _import(client: TestClient, headers: dict, content: bytes) -> dict:
    resp = client.post(
        '/api/v1/partners/import',
        files={'file': ('partnerzy.csv', content, 'text/csv')},
        data={'mapping_json': json.dumps(MAPPING)},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


class TestPartnerServiceRefusalsSpeakPolish:
    """``app/services/partner_service.py`` — the three 409s."""

    def test_creating_a_partner_with_a_name_the_org_has_speaks_polish(
        self, client: TestClient, auth_headers: dict
    ) -> None:
        payload = {'name': 'Hurtownia Duplikat', 'type': 'SUPPLIER'}
        created = client.post('/api/v1/partners', json=payload, headers=auth_headers)
        assert created.status_code == 201, created.text

        resp = client.post(
            '/api/v1/partners',
            json={'name': 'Hurtownia Duplikat', 'type': 'SUPPLIER'},
            headers=_polish(auth_headers),
        )

        assert resp.status_code == 409, resp.text
        assert _message(resp) == (
            'Kontrahent o nazwie "Hurtownia Duplikat" i typie "Dostawca" już istnieje.'
        )
        assert resp.json()['detail']['code'] == 'PARTNER_NAME_EXISTS'

    def test_creating_a_partner_with_a_code_the_org_has_speaks_polish(
        self, client: TestClient, auth_headers: dict
    ) -> None:
        created = client.post(
            '/api/v1/partners',
            json={'name': 'Pierwszy', 'type': 'SUPPLIER', 'code': 'DUP-1'},
            headers=auth_headers,
        )
        assert created.status_code == 201, created.text

        resp = client.post(
            '/api/v1/partners',
            json={'name': 'Drugi', 'type': 'SUPPLIER', 'code': 'DUP-1'},
            headers=_polish(auth_headers),
        )

        assert resp.status_code == 409, resp.text
        assert _message(resp) == 'Kontrahent o kodzie "DUP-1" już istnieje.'
        assert resp.json()['detail']['code'] == 'PARTNER_CODE_EXISTS'

    def test_deleting_a_partner_an_open_order_names_speaks_polish(
        self,
        client: TestClient,
        auth_headers: dict,
        db_session: Session,
        test_user: User,
        test_household: Organization,
    ) -> None:
        from app.modules.purchase_orders.models import PurchaseOrder

        created = client.post(
            '/api/v1/partners',
            json={'name': 'Zamawiający', 'type': 'SUPPLIER'},
            headers=auth_headers,
        )
        assert created.status_code == 201, created.text
        partner_id = created.json()['id']

        db_session.add(
            PurchaseOrder(
                organization_id=test_household.id,
                number='PO/TEST/LANG/1',
                status='CONFIRMED',
                partner_id=partner_id,
                currency='PLN',
                created_by=test_user.id,
            )
        )
        db_session.commit()

        resp = client.delete(
            f'/api/v1/partners/{partner_id}', headers=_polish(auth_headers)
        )

        assert resp.status_code == 409, resp.text
        assert _message(resp) == (
            'Nie można usunąć kontrahenta: 1 otwartych zamówień zakupowych '
            'odwołuje się do tego kontrahenta'
        )


class TestPartnerImportRefusalsSpeakPolish:
    """``app/services/partner_import.py`` — the two rows of the report.

    A row refusal lands in a 200 report, not a 4xx: the sheet is imported
    as far as it goes and the report says what it dropped. The sentence the
    reader gets there is the one pinned below.
    """

    def test_a_row_without_a_name_says_so_in_polish(
        self, client: TestClient, auth_headers: dict
    ) -> None:
        rows = [
            {
                'Nazwa': None,
                'Typ': 'supplier',
                'NIP': None,
                'E-mail': None,
                'Miasto': None,
                'Kraj': None,
            }
        ]

        body = _import(client, _polish(auth_headers), _csv(rows))

        assert (body['imported'], body['failed']) == (0, 1)
        assert body['errors'] == [{'row': 2, 'error': 'Brak nazwy kontrahenta'}]

    def test_a_row_repeating_another_partner_says_so_in_polish(
        self, client: TestClient, auth_headers: dict
    ) -> None:
        rows = [
            {
                'Nazwa': 'Stary dostawca',
                'Typ': 'supplier',
                'NIP': None,
                'E-mail': None,
                'Miasto': None,
                'Kraj': None,
            },
            {
                'Nazwa': 'stary dostawca',
                'Typ': 'customer',
                'NIP': None,
                'E-mail': None,
                'Miasto': None,
                'Kraj': None,
            },
        ]

        body = _import(client, _polish(auth_headers), _csv(rows))

        assert (body['imported'], body['failed']) == (1, 1)
        assert body['errors'] == [
            {
                'row': 3,
                'error': (
                    'Duplikat kontrahenta: "Stary dostawca" ma już tę nazwę lub '
                    'ten numer identyfikacji podatkowej'
                ),
            }
        ]
