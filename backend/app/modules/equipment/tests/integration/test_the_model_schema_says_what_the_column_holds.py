"""The equipment contract names what the server accepts and sends.

A model's description and picture address live in ``String(500)`` columns of
the product template. The request schemas bounded the name and the brand but
not these two, so a 501st character reached the driver and answered 500
instead of a translated 422. The campaign responses, in turn, declared the
scope and the status as free text although only a handful of values are ever
written, which the generated types then carried to the screens as ``string``.
"""

from __future__ import annotations

from typing import Any, get_args

import pytest
from pydantic import BaseModel
from starlette.testclient import TestClient

from app.modules.equipment._schemas_attestation import (
    CampaignCreate,
    CampaignDetail,
    CampaignSchema,
)

MODELS_URL = '/api/v1/equipment/models'


def _literal_values(schema: type[BaseModel], field: str) -> set[str]:
    annotation = schema.model_fields[field].annotation
    return set(get_args(annotation))


@pytest.mark.integration
class TestAModelFieldLongerThanItsColumnIsRefused:
    @pytest.mark.parametrize('field', ['description', 'image_url'])
    def test_create_answers_422_not_500(
        self,
        client: TestClient,
        eq_auth_headers: dict[str, str],
        field: str,
    ) -> None:
        response = client.post(
            MODELS_URL,
            headers=eq_auth_headers,
            json={'name': 'Dell Latitude 5540', field: 'x' * 501},
        )
        assert response.status_code == 422, response.text

    @pytest.mark.parametrize('field', ['description', 'image_url'])
    def test_update_answers_422_not_500(
        self,
        client: TestClient,
        eq_auth_headers: dict[str, str],
        field: str,
    ) -> None:
        created = client.post(
            MODELS_URL, headers=eq_auth_headers, json={'name': 'Dell Latitude 5540'}
        )
        assert created.status_code == 201, created.text
        response = client.put(
            f'{MODELS_URL}/{created.json()["id"]}',
            headers=eq_auth_headers,
            json={field: 'x' * 501},
        )
        assert response.status_code == 422, response.text

    def test_five_hundred_characters_are_stored(
        self,
        client: TestClient,
        eq_auth_headers: dict[str, str],
    ) -> None:
        body: dict[str, Any] = {
            'name': 'Dell Latitude 5540',
            'description': 'd' * 500,
        }
        response = client.post(MODELS_URL, headers=eq_auth_headers, json=body)
        assert response.status_code == 201, response.text
        assert response.json()['description'] == 'd' * 500


class TestCampaignResponsesNameTheirValues:
    def test_scope_is_the_set_the_create_form_accepts(self) -> None:
        accepted = {'ALL', 'STORAGE', 'CATEGORY'}
        assert _literal_values(CampaignCreate, 'scope_type') == accepted
        assert _literal_values(CampaignSchema, 'scope_type') == accepted
        assert _literal_values(CampaignDetail, 'scope_type') == accepted

    def test_status_is_the_set_the_service_writes(self) -> None:
        written = {'DRAFT', 'ACTIVE', 'COMPLETED', 'CANCELLED'}
        assert _literal_values(CampaignSchema, 'status') == written
        assert _literal_values(CampaignDetail, 'status') == written
