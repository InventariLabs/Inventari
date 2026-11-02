"""The country supplies a document's numbers; the preset supplies its shape.

A preset is a way of working (numbering, type labels, visible line fields,
print template). The rate a document applies and the question whether a
partner must carry a tax id are questions of law, and the law is where the
organization sits — the organization's ``country``. The division follows
the currency rule: the profile's own entry is an override, the
organization — through its country — is the source of truth. A country with
no row in ``COUNTRY_RULES`` degrades to the profile as it stands, never to
an exception.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.item import Item
from app.models.organization import Organization
from app.models.partner import Partner
from app.models.product_template import ProductTemplate
from app.models.storage_location import StorageLocation


def _set_country(db_session: Session, org: Organization, country: str | None) -> None:
    org.country = country
    db_session.commit()


def _apply_preset(client: TestClient, headers: dict[str, str], name: str) -> None:
    response = client.post(
        f'/api/v1/warehouse/profile/apply-preset/{name}',
        headers=headers,
    )
    assert response.status_code == status.HTTP_200_OK, response.text


def _create_in(
    client: TestClient,
    headers: dict[str, str],
    partner: Partner,
    location: StorageLocation,
    template: ProductTemplate,
) -> dict[str, Any]:
    response = client.post(
        '/api/v1/warehouse/documents',
        headers=headers,
        json={
            'type': 'IN',
            'partner_id': str(partner.id),
            'target_location_id': str(location.id),
            'lines': [
                {
                    'product_template_id': str(template.id),
                    'expected_quantity': 5,
                    'unit_price': '10.00',
                }
            ],
        },
    )
    assert response.status_code == status.HTTP_201_CREATED, response.text
    payload: dict[str, Any] = response.json()
    return payload


@pytest.mark.integration
class TestTheCountrySuppliesTheRate:
    """``default_tax_rate``: the profile entry is an override, the country answers."""

    def test_a_polish_org_on_the_wms_profile_applies_the_polish_rate(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_org: Organization,
        doc_partner: Partner,
        doc_target_location: StorageLocation,
        doc_template: ProductTemplate,
        db_session: Session,
    ) -> None:
        """The promise behind the whole split: a Polish organization on the
        warehouse profile (``equipment_wms`` applies ``Full Value`` at
        onboarding) gets 23% without a visit to Settings. Fails without the fix with
        ``None`` — the country was never read."""
        _set_country(db_session, doc_org, 'PL')
        _apply_preset(client, doc_auth_headers, 'Full Value')

        profile = client.get(
            '/api/v1/warehouse/profile', headers=doc_auth_headers
        ).json()
        # The row itself states no rate — the country is the source, so a
        # country change later is followed, not frozen into the profile.
        assert profile['default_tax_rate'] is None

        data = _create_in(
            client, doc_auth_headers, doc_partner, doc_target_location, doc_template
        )
        assert data['lines'][0]['tax_rate'] == '23.00'
        assert data['total_net'] == '50.00'
        assert data['total_tax'] == '11.50'
        assert data['total_gross'] == '61.50'

    @pytest.mark.parametrize(
        ('country', 'rate', 'tax', 'gross'),
        [('FR', '20.00', '10.00', '60.00'), ('ES', '21.00', '10.50', '60.50')],
    )
    def test_a_french_and_a_spanish_org_apply_their_standard_rate(
        self,
        country: str,
        rate: str,
        tax: str,
        gross: str,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_org: Organization,
        doc_partner: Partner,
        doc_target_location: StorageLocation,
        doc_template: ProductTemplate,
        db_session: Session,
    ) -> None:
        """Fails without the country row with ``None`` — no rate was known."""
        _set_country(db_session, doc_org, country)
        _apply_preset(client, doc_auth_headers, 'Full Value')

        data = _create_in(
            client, doc_auth_headers, doc_partner, doc_target_location, doc_template
        )
        assert data['lines'][0]['tax_rate'] == rate
        assert data['total_tax'] == tax
        assert data['total_gross'] == gross

    def test_a_profile_entry_beats_the_country(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_org: Organization,
        doc_partner: Partner,
        doc_target_location: StorageLocation,
        doc_template: ProductTemplate,
        db_session: Session,
    ) -> None:
        """The override half of the contract, same as ``default_currency``
        against the organization currency. Passes without the fix too — it documents
        behaviour the split must not lose."""
        _set_country(db_session, doc_org, 'PL')
        _apply_preset(client, doc_auth_headers, 'Full Value')
        response = client.put(
            '/api/v1/warehouse/profile',
            headers=doc_auth_headers,
            json={'default_tax_rate': '5.00'},
        )
        assert response.status_code == status.HTTP_200_OK, response.text

        data = _create_in(
            client, doc_auth_headers, doc_partner, doc_target_location, doc_template
        )
        assert data['lines'][0]['tax_rate'] == '5.00'

    def test_a_country_outside_the_rules_leaves_the_rate_empty(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_org: Organization,
        doc_partner: Partner,
        doc_target_location: StorageLocation,
        doc_template: ProductTemplate,
        db_session: Session,
    ) -> None:
        """A country with no row degrades to the profile as it stands —
        no rate, no exception, no empty screen. Passes without the fix
        too; it pins the degradation, not the fix."""
        _set_country(db_session, doc_org, 'US')
        _apply_preset(client, doc_auth_headers, 'Full Value')

        data = _create_in(
            client, doc_auth_headers, doc_partner, doc_target_location, doc_template
        )
        assert data['lines'][0]['tax_rate'] is None
        assert data['total_net'] == '50.00'
        assert data['total_gross'] == '50.00'

    def test_the_price_hint_offers_the_country_rate(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_org: Organization,
        doc_template: ProductTemplate,
        db_session: Session,
    ) -> None:
        """The form's price hint reads the same source the document does —
        otherwise a Polish org would be offered a line with no rate after
        the country had already answered. Fails without the fix with ``None``."""
        _set_country(db_session, doc_org, 'PL')
        _apply_preset(client, doc_auth_headers, 'Full Value')

        hint = client.get(
            '/api/v1/warehouse/price-hint',
            headers=doc_auth_headers,
            params={'template_id': str(doc_template.id)},
        )
        assert hint.status_code == status.HTTP_200_OK
        assert hint.json()['tax_rate'] == '23.00'


@pytest.mark.integration
class TestTheCountrySuppliesTheTaxIdRequirement:
    """``require_partner_tax_id``: None in the profile means the country answers."""

    def test_a_polish_org_refuses_a_partner_without_a_tax_id_until_one_is_given(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_org: Organization,
        doc_partner: Partner,
        doc_target_location: StorageLocation,
        doc_template: ProductTemplate,
        db_session: Session,
    ) -> None:
        """``Full Value`` used to pin this requirement to False, so a Polish
        company confirmed documents with partners it could not invoice.
        Fails without the fix at the first confirm: 200 where 400 is the law."""
        _set_country(db_session, doc_org, 'PL')
        _apply_preset(client, doc_auth_headers, 'Full Value')
        doc = _create_in(
            client, doc_auth_headers, doc_partner, doc_target_location, doc_template
        )

        refused = client.patch(
            f'/api/v1/warehouse/documents/{doc["id"]}/confirm', headers=doc_auth_headers
        )
        assert refused.status_code == status.HTTP_400_BAD_REQUEST, refused.text
        assert 'Acme Supplies' in refused.json()['detail']['message']

        doc_partner.tax_id = 'PL1234567890'
        db_session.commit()
        accepted = client.patch(
            f'/api/v1/warehouse/documents/{doc["id"]}/confirm', headers=doc_auth_headers
        )
        assert accepted.status_code == status.HTTP_200_OK, accepted.text

    @pytest.mark.parametrize('country', ['FR', 'ES'])
    def test_a_french_and_a_spanish_org_refuse_a_partner_without_a_tax_id(
        self,
        country: str,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_org: Organization,
        doc_partner: Partner,
        doc_target_location: StorageLocation,
        doc_template: ProductTemplate,
        db_session: Session,
    ) -> None:
        """Fails without the country row: the confirm answers 200 where the
        country's invoicing rules want the partner's number."""
        _set_country(db_session, doc_org, country)
        _apply_preset(client, doc_auth_headers, 'Full Value')
        doc = _create_in(
            client, doc_auth_headers, doc_partner, doc_target_location, doc_template
        )

        refused = client.patch(
            f'/api/v1/warehouse/documents/{doc["id"]}/confirm', headers=doc_auth_headers
        )
        assert refused.status_code == status.HTTP_400_BAD_REQUEST, refused.text

        doc_partner.tax_id = 'FR12345678901' if country == 'FR' else 'ESB12345678'
        db_session.commit()
        accepted = client.patch(
            f'/api/v1/warehouse/documents/{doc["id"]}/confirm', headers=doc_auth_headers
        )
        assert accepted.status_code == status.HTTP_200_OK, accepted.text

    def test_a_country_without_the_requirement_confirms(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_org: Organization,
        doc_partner: Partner,
        doc_target_location: StorageLocation,
        doc_template: ProductTemplate,
        db_session: Session,
    ) -> None:
        """The other side of the same law: the country that requires nothing
        demands nothing. Passes without the fix too; it pins the degradation."""
        _set_country(db_session, doc_org, 'US')
        _apply_preset(client, doc_auth_headers, 'Full Value')
        doc = _create_in(
            client, doc_auth_headers, doc_partner, doc_target_location, doc_template
        )

        response = client.patch(
            f'/api/v1/warehouse/documents/{doc["id"]}/confirm', headers=doc_auth_headers
        )
        assert response.status_code == status.HTTP_200_OK, response.text

    def test_a_profile_entry_beats_the_country_on_the_requirement(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_org: Organization,
        doc_partner: Partner,
        doc_target_location: StorageLocation,
        doc_template: ProductTemplate,
        db_session: Session,
    ) -> None:
        """An explicit False in the profile waives the country's demand, the
        way ``default_currency`` overrides the organization currency.
        Passes without the fix too — it documents the override the split preserves."""
        _set_country(db_session, doc_org, 'PL')
        _apply_preset(client, doc_auth_headers, 'Full Value')
        response = client.put(
            '/api/v1/warehouse/profile',
            headers=doc_auth_headers,
            json={'require_partner_tax_id': False},
        )
        assert response.status_code == status.HTTP_200_OK, response.text
        doc = _create_in(
            client, doc_auth_headers, doc_partner, doc_target_location, doc_template
        )

        confirmed = client.patch(
            f'/api/v1/warehouse/documents/{doc["id"]}/confirm', headers=doc_auth_headers
        )
        assert confirmed.status_code == status.HTTP_200_OK, confirmed.text


@pytest.mark.integration
class TestGermanLawAsksNoPartnerTaxId:
    """§14(4) UStG names the supplier's own number as an invoice field, not
    the recipient's; a delivery note has no statutory tax-id field at all. A
    German shop receiving from a farmer or dispatching to a trade customer
    who gives no number must not be refused for it."""

    @pytest.mark.parametrize('preset', ['Full Value', 'DE Lager'])
    def test_a_german_receipt_confirms_without_a_partner_tax_id(
        self,
        preset: str,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_org: Organization,
        doc_partner: Partner,
        doc_target_location: StorageLocation,
        doc_template: ProductTemplate,
        db_session: Session,
    ) -> None:
        """Fails without the fix: 400 ``document_partner_tax_id_required``.
        ``DE Lager`` is the preset a German organization is offered, so it is
        the one that must not bring the requirement back."""
        assert not doc_partner.tax_id
        _set_country(db_session, doc_org, 'DE')
        _apply_preset(client, doc_auth_headers, preset)
        doc = _create_in(
            client, doc_auth_headers, doc_partner, doc_target_location, doc_template
        )

        confirmed = client.patch(
            f'/api/v1/warehouse/documents/{doc["id"]}/confirm', headers=doc_auth_headers
        )
        assert confirmed.status_code == status.HTTP_200_OK, confirmed.text

    def test_a_german_dispatch_to_a_business_confirms_without_a_tax_id(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_org: Organization,
        doc_stock_item: Item,
        doc_template: ProductTemplate,
        doc_source_location: StorageLocation,
        db_session: Session,
    ) -> None:
        """Fails without the fix: 400 for a business customer with no number."""
        _set_country(db_session, doc_org, 'DE')
        partner_id = _create_customer(
            client, doc_auth_headers, 'Handels GmbH', is_consumer=False
        )
        doc = _create_out_to(
            client,
            doc_auth_headers,
            partner_id,
            doc_stock_item,
            doc_template,
            doc_source_location,
        )

        confirmed = client.patch(
            f'/api/v1/warehouse/documents/{doc["id"]}/confirm', headers=doc_auth_headers
        )
        assert confirmed.status_code == status.HTTP_200_OK, confirmed.text

    def test_a_german_profile_that_turns_the_check_on_still_enforces_it(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_org: Organization,
        doc_partner: Partner,
        doc_target_location: StorageLocation,
        doc_template: ProductTemplate,
        db_session: Session,
    ) -> None:
        """The profile entry wins over the country in both directions.
        Passes without the fix too; it pins the opt-in the task promises."""
        _set_country(db_session, doc_org, 'DE')
        _apply_preset(client, doc_auth_headers, 'Full Value')
        response = client.put(
            '/api/v1/warehouse/profile',
            headers=doc_auth_headers,
            json={'require_partner_tax_id': True},
        )
        assert response.status_code == status.HTTP_200_OK, response.text
        doc = _create_in(
            client, doc_auth_headers, doc_partner, doc_target_location, doc_template
        )

        refused = client.patch(
            f'/api/v1/warehouse/documents/{doc["id"]}/confirm', headers=doc_auth_headers
        )
        assert refused.status_code == status.HTTP_400_BAD_REQUEST, refused.text


def _create_out_to(
    client: TestClient,
    headers: dict[str, str],
    partner_id: str,
    record: Item,
    template: ProductTemplate,
    location: StorageLocation,
) -> dict[str, Any]:
    response = client.post(
        '/api/v1/warehouse/documents',
        headers=headers,
        json={
            'type': 'OUT',
            'partner_id': partner_id,
            'source_location_id': str(location.id),
            'lines': [
                {
                    'item_id': str(record.id),
                    'product_template_id': str(template.id),
                    'expected_quantity': 2,
                }
            ],
        },
    )
    assert response.status_code == status.HTTP_201_CREATED, response.text
    payload: dict[str, Any] = response.json()
    return payload


def _create_customer(
    client: TestClient, headers: dict[str, str], name: str, *, is_consumer: bool
) -> str:
    response = client.post(
        '/api/v1/partners',
        headers=headers,
        json={'name': name, 'type': 'CUSTOMER', 'is_consumer': is_consumer},
    )
    assert response.status_code == status.HTTP_201_CREATED, response.text
    assert response.json()['is_consumer'] is is_consumer
    partner_id: str = response.json()['id']
    return partner_id


@pytest.mark.integration
class TestAPrivatePersonNeedsNoTaxId:
    """A consumer has no tax id to give; the law that asks for one asks it of
    businesses. A dispatch to a private person confirms under PL, DE, FR and ES."""

    @pytest.mark.parametrize('country', ['PL', 'DE', 'FR', 'ES'])
    def test_a_dispatch_to_a_consumer_confirms_without_a_tax_id(
        self,
        country: str,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_org: Organization,
        doc_stock_item: Item,
        doc_template: ProductTemplate,
        doc_source_location: StorageLocation,
        db_session: Session,
    ) -> None:
        """Fails without the fix: the partner API drops ``is_consumer`` and
        the confirm is refused for the missing tax id."""
        _set_country(db_session, doc_org, country)
        partner_id = _create_customer(
            client, doc_auth_headers, 'Jan Kowalski', is_consumer=True
        )
        doc = _create_out_to(
            client,
            doc_auth_headers,
            partner_id,
            doc_stock_item,
            doc_template,
            doc_source_location,
        )

        confirmed = client.patch(
            f'/api/v1/warehouse/documents/{doc["id"]}/confirm', headers=doc_auth_headers
        )
        assert confirmed.status_code == status.HTTP_200_OK, confirmed.text

    def test_the_refusal_names_the_partner_and_the_ways_out_in_the_readers_language(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_org: Organization,
        doc_stock_item: Item,
        doc_template: ProductTemplate,
        doc_source_location: StorageLocation,
        db_session: Session,
    ) -> None:
        """A business customer without a tax id is still refused, and the
        message says what to do about it. Fails without the fix: the old text
        named the partner but no way out."""
        _set_country(db_session, doc_org, 'PL')
        partner_id = _create_customer(
            client, doc_auth_headers, 'Hurtownia Nowak', is_consumer=False
        )
        doc = _create_out_to(
            client,
            doc_auth_headers,
            partner_id,
            doc_stock_item,
            doc_template,
            doc_source_location,
        )

        refused = client.patch(
            f'/api/v1/warehouse/documents/{doc["id"]}/confirm',
            headers={**doc_auth_headers, 'Accept-Language': 'pl'},
        )
        assert refused.status_code == status.HTTP_400_BAD_REQUEST, refused.text
        message = refused.json()['detail']['message']
        assert 'Hurtownia Nowak' in message
        assert 'Osoba prywatna (konsument)' in message
        assert 'Ustawienia' in message


@pytest.mark.integration
class TestAFrenchAndASpanishPresetApply:
    @pytest.mark.parametrize(
        ('preset', 'receipt_code', 'delivery_code'),
        [('FR Entrepôt', 'BR', 'BL'), ('ES Almacén', 'AE', 'AS')],
    )
    def test_applying_the_preset_names_and_numbers_the_documents_locally(
        self,
        preset: str,
        receipt_code: str,
        delivery_code: str,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_partner: Partner,
        doc_target_location: StorageLocation,
        doc_template: ProductTemplate,
        db_session: Session,
    ) -> None:
        """Fails without the preset: the apply answers 400 for an unknown name."""
        _apply_preset(client, doc_auth_headers, preset)

        profile = client.get(
            '/api/v1/warehouse/profile', headers=doc_auth_headers
        ).json()
        assert profile['name'] == preset
        assert profile['type_labels']['IN'] == receipt_code
        assert profile['type_labels']['OUT'] == delivery_code

        # A draft carries a placeholder number; the real one is written when
        # the document is confirmed.
        doc_partner.tax_id = 'FR12345678901'
        db_session.commit()
        doc = _create_in(
            client, doc_auth_headers, doc_partner, doc_target_location, doc_template
        )
        confirmed = client.patch(
            f'/api/v1/warehouse/documents/{doc["id"]}/confirm', headers=doc_auth_headers
        )
        assert confirmed.status_code == status.HTTP_200_OK, confirmed.text
        assert confirmed.json()['number'].startswith(f'{receipt_code}/')
