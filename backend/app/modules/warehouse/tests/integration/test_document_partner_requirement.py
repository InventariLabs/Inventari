"""Partner requirement for IN/OUT documents depends on the partners module.

With the partners module disabled the UI hides the partner field, so
the backend must accept IN/OUT documents without a partner — otherwise the
receipt flow is deadlocked. With the module enabled the requirement stays.
"""

import pytest
from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.testing import ModuleTestHelper
from app.models.organization import Organization
from app.models.partner import Partner
from app.models.product_template import ProductTemplate
from app.models.storage_location import StorageLocation
from app.models.user import User


@pytest.mark.integration
class TestPartnerRequirementByModule:
    def test_in_without_partner_allowed_when_partners_module_disabled(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_template: ProductTemplate,
    ) -> None:
        # doc_org fixture has no 'partners' in enabled_modules
        response = client.post(
            '/api/v1/warehouse/documents',
            headers=doc_auth_headers,
            json={
                'type': 'IN',
                'target_location_id': str(doc_target_location.id),
                'lines': [
                    {
                        'product_template_id': str(doc_template.id),
                        'expected_quantity': 5,
                        'unit': 'pcs',
                    }
                ],
            },
        )

        assert response.status_code == status.HTTP_201_CREATED
        assert response.json()['partner_id'] is None

    def test_in_without_partner_rejected_when_partners_module_enabled(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_template: ProductTemplate,
        doc_org: Organization,
        db_session: Session,
    ) -> None:
        doc_org.enabled_modules = (doc_org.enabled_modules or []) + ['partners']
        db_session.commit()

        response = client.post(
            '/api/v1/warehouse/documents',
            headers=doc_auth_headers,
            json={
                'type': 'IN',
                'target_location_id': str(doc_target_location.id),
                'lines': [
                    {
                        'product_template_id': str(doc_template.id),
                        'expected_quantity': 5,
                        'unit': 'pcs',
                    }
                ],
            },
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        detail = response.json()['detail']
        message = detail['message'] if isinstance(detail, dict) else detail
        assert 'requires a partner' in message


@pytest.mark.integration
class TestPartnerRoleValidation:
    """A receipt must come from a supplier — or back from a customer, whose
    returned goods are received on a receipt — and a delivery must go to a
    customer. Enforced server-side, not only by the dropdown filter."""

    def test_in_with_supplier_partner_accepted(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_template: ProductTemplate,
        doc_partner: Partner,
    ) -> None:
        response = client.post(
            '/api/v1/warehouse/documents',
            headers=doc_auth_headers,
            json={
                'type': 'IN',
                'target_location_id': str(doc_target_location.id),
                'partner_id': str(doc_partner.id),
                'lines': [
                    {
                        'product_template_id': str(doc_template.id),
                        'expected_quantity': 5,
                        'unit': 'pcs',
                    }
                ],
            },
        )

        assert response.status_code == status.HTTP_201_CREATED
        assert response.json()['partner_id'] == str(doc_partner.id)

    def test_in_with_customer_partner_accepted(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_template: ProductTemplate,
        h: ModuleTestHelper,
        doc_org: Organization,
        doc_user: User,
    ) -> None:
        """A customer's return is received on a receipt naming the customer."""
        customer = h.create_partner(
            doc_org, doc_user, name='Retail Customer', type='CUSTOMER'
        )

        response = client.post(
            '/api/v1/warehouse/documents',
            headers=doc_auth_headers,
            json={
                'type': 'IN',
                'target_location_id': str(doc_target_location.id),
                'partner_id': str(customer.id),
                'lines': [
                    {
                        'product_template_id': str(doc_template.id),
                        'expected_quantity': 5,
                        'unit': 'pcs',
                    }
                ],
            },
        )

        assert response.status_code == status.HTTP_201_CREATED
        assert response.json()['partner_id'] == str(customer.id)

    def test_in_with_employee_partner_rejected(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_template: ProductTemplate,
        h: ModuleTestHelper,
        doc_org: Organization,
        doc_user: User,
    ) -> None:
        """Widening the receipt's roles to customers keeps the rule: an
        employee is neither a supplier nor a customer."""
        employee = h.create_partner(
            doc_org, doc_user, name='Adam Jakis', type='EMPLOYEE'
        )

        response = client.post(
            '/api/v1/warehouse/documents',
            headers=doc_auth_headers,
            json={
                'type': 'IN',
                'target_location_id': str(doc_target_location.id),
                'partner_id': str(employee.id),
                'lines': [
                    {
                        'product_template_id': str(doc_template.id),
                        'expected_quantity': 5,
                        'unit': 'pcs',
                    }
                ],
            },
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        detail = response.json()['detail']
        message = detail['message'] if isinstance(detail, dict) else detail
        assert 'a supplier, a manufacturer or a customer' in message

    def test_in_with_manufacturer_partner_accepted(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_template: ProductTemplate,
        h: ModuleTestHelper,
        doc_org: Organization,
        doc_user: User,
    ) -> None:
        """a MANUFACTURER also delivers goods — the supplier role set
        is {SUPPLIER, BOTH, MANUFACTURER}."""
        manufacturer = h.create_partner(
            doc_org, doc_user, name='Component Maker', type='MANUFACTURER'
        )

        response = client.post(
            '/api/v1/warehouse/documents',
            headers=doc_auth_headers,
            json={
                'type': 'IN',
                'target_location_id': str(doc_target_location.id),
                'partner_id': str(manufacturer.id),
                'lines': [
                    {
                        'product_template_id': str(doc_template.id),
                        'expected_quantity': 5,
                        'unit': 'pcs',
                    }
                ],
            },
        )

        assert response.status_code == status.HTTP_201_CREATED
        assert response.json()['partner_id'] == str(manufacturer.id)

    def test_in_with_both_partner_accepted(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_template: ProductTemplate,
        h: ModuleTestHelper,
        doc_org: Organization,
        doc_user: User,
    ) -> None:
        """BOTH (buy from and sell to the same entity) is a supplier."""
        both = h.create_partner(doc_org, doc_user, name='Dual Role Co', type='BOTH')

        response = client.post(
            '/api/v1/warehouse/documents',
            headers=doc_auth_headers,
            json={
                'type': 'IN',
                'target_location_id': str(doc_target_location.id),
                'partner_id': str(both.id),
                'lines': [
                    {
                        'product_template_id': str(doc_template.id),
                        'expected_quantity': 5,
                        'unit': 'pcs',
                    }
                ],
            },
        )

        assert response.status_code == status.HTTP_201_CREATED
        assert response.json()['partner_id'] == str(both.id)

    def test_out_with_employee_partner_rejected(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_source_location: StorageLocation,
        doc_template: ProductTemplate,
        h: ModuleTestHelper,
        doc_org: Organization,
        doc_user: User,
    ) -> None:
        employee = h.create_partner(
            doc_org, doc_user, name='Adam Jakis', type='EMPLOYEE'
        )

        response = client.post(
            '/api/v1/warehouse/documents',
            headers=doc_auth_headers,
            json={
                'type': 'OUT',
                'source_location_id': str(doc_source_location.id),
                'partner_id': str(employee.id),
                'lines': [
                    {
                        'product_template_id': str(doc_template.id),
                        'expected_quantity': 5,
                        'unit': 'pcs',
                    }
                ],
            },
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        detail = response.json()['detail']
        message = detail['message'] if isinstance(detail, dict) else detail
        assert 'a customer or a supplier' in message
