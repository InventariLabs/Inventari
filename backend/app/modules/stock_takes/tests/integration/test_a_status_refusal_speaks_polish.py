"""A status refusal reaches a Polish reader in Polish.

The transition refusal used to be bare ``ValueError`` prose — English no
matter which language the interface was set to. It carries a catalog key
now (``ServiceRejectionError``), so the 400 envelope arrives translated and
stamped with the language it actually speaks.

The refusal is a reachable screen, not a dead path: the counting page
renders Cancel while the take is in_progress, and a second operator can
cancel the take first — the click then lands here on a stale client state.
That race is the reader's path, which is why the sentence has to be in the
reader's language.
"""

import pytest
from fastapi import status
from sqlalchemy.orm import Session
from starlette.testclient import TestClient

from app.models.item import Item
from app.models.storage_location import StorageLocation
from app.models.user import User
from app.modules.stock_takes.models import StockTake, StockTakeStatus


@pytest.mark.integration
class TestAStatusRefusalSpeaksTheReadersLanguage:
    def test_an_invalid_transition_refuses_in_polish(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
        test_storage_location: StorageLocation,
        test_item: Item,
        test_user: User,
    ) -> None:
        stock_take = StockTake(
            user_id=test_user.id,
            organization_id=test_storage_location.organization_id,
            storage_location_id=test_storage_location.id,
            name='Polish reader',
            status=StockTakeStatus.IN_PROGRESS,
        )
        db_session.add(stock_take)
        db_session.commit()

        resp = client.patch(
            f'/api/v1/stock-takes/{stock_take.id}/status',
            headers={**auth_headers, 'Accept-Language': 'pl'},
            json={'status': 'in_progress'},
        )

        assert resp.status_code == status.HTTP_400_BAD_REQUEST, resp.text
        detail = resp.json()['detail']
        assert detail['lang'] == 'pl'
        assert (
            detail['message']
            == 'Nie można zmienić statusu z in_progress na in_progress.'
        ), resp.text

        # The English reader keeps the English sentence.
        resp = client.patch(
            f'/api/v1/stock-takes/{stock_take.id}/status',
            headers={**auth_headers, 'Accept-Language': 'en'},
            json={'status': 'in_progress'},
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST, resp.text
        assert resp.json()['detail']['lang'] == 'en'
        assert resp.json()['detail']['message'] == (
            'Cannot change status from in_progress to in_progress.'
        )
