"""A reader key that cannot be read refuses the import, and says why.

``resolve_jina_api_key_async`` answers from the connection bound to
``recipes.url_fetch``. A row whose ciphertext does not open — the state a
key or salt rotation leaves behind — is refused with a ``PermissionError``,
and that refusal travels through ``@map_service_errors`` to a 403 on both
import doors. The behaviour is deliberate: importing without the key would
quietly fall back to the free Jina tier off a *different* account, and the
operator would never learn their key is unreadable.
"""

import pytest
from fastapi import status
from sqlalchemy.orm import Session
from starlette.testclient import TestClient

from app.core.llm.secrets import encrypt_connection_secret
from app.models.ai_connection import AiConnection
from app.models.organization import Organization

_IMPORT_DOORS = (
    '/api/v1/recipes/import/preview',
    '/api/v1/recipes/import',
)


@pytest.mark.integration
class TestAnUnreadableJinaKey:
    @pytest.mark.parametrize('door', _IMPORT_DOORS)
    def test_the_import_refuses_with_the_reason(
        self,
        door: str,
        db_session: Session,
        test_household: Organization,
        client: TestClient,
        auth_headers: dict[str, str],
    ) -> None:
        sealed = encrypt_connection_secret('jina-test-key')
        # Keep the 'enc:' marker, corrupt the body: the value claims to be
        # a sealed secret but does not open — the shape a key or salt
        # rotation leaves behind. Losing the marker entirely would read as
        # legacy plaintext and pass through, which is a different (legal)
        # state, not the refusal under test.
        tampered = sealed[:8] + ('A' if sealed[8] != 'A' else 'B') + sealed[9:]
        conn = AiConnection(
            organization_id=test_household.id,
            name='Jina Reader',
            provider='jina',
            capabilities=['url_fetch'],
            api_key_enc=tampered,
        )
        db_session.add(conn)
        db_session.flush()
        test_household.settings = {
            'ai': {'defaults': {'recipes.url_fetch': str(conn.id)}}
        }
        db_session.commit()

        refused = client.post(
            door,
            # A public IP literal on purpose: the guard passes it without a
            # DNS lookup, and the refusal being tested arrives before any
            # fetch would.
            json={'format': 'url', 'url': 'http://93.184.216.34/recipe'},
            headers=auth_headers,
        )

        assert refused.status_code == status.HTTP_403_FORBIDDEN, refused.text
        detail = refused.json()['detail']
        assert detail['code'] == 'FORBIDDEN', (
            'the 403 answers in the canonical envelope every other 4xx uses, '
            'not as a bare string'
        )
        assert 'cannot be decrypted' in detail['message'], (
            'the 403 has to name the unreadable stored key, not blame the '
            'recipe or the URL'
        )
