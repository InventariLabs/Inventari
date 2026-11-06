"""Integration tests for the /api/v1/ai-connections router.

Per AGENTS.md §Backend.2 (canonical endpoint
pattern), the router wires thin endpoint handlers to
:mod:`app.core.public_api.core_api`. These tests boot the test
client, hit each endpoint, and assert on the response code and
serialised body shape — the same contract the frontend form will
consume.

What we pin:

- 201 on create + masked api_key (never plaintext) in the response.
- 409 when the create hits the unique constraint uq_ai_connections_org_name.
- 200 + masked api_key on a list call — no plaintext whatsoever.
- 200 on update with MASKED_VALUE ("do not change") — the cipher stays put.
- 200 on update with plaintext — the cipher rotates.
- 409 on delete when the row is still bound to any registered purpose.
- 404 when the row belongs to another org (tenant guard).
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch

import pytest

from app.models.ai_connection import AiConnection


@pytest.mark.integration
class TestAiConnectionsCrud:
    def test_create_connection_encrypts_api_key(
        self, db_session, test_household, client, auth_headers
    ):
        """Plaintext goes in, MASKED_VALUE comes out — never plaintext."""
        response = client.post(
            '/api/v1/ai-connections',
            json={
                'name': 'GPT-4o Vision',
                'provider': 'openrouter',
                'api_key': 'sk-or-plaintext-NEVER-RETURNED',
                'api_base_url': 'https://openrouter.ai/api/v1',
                'model_name': 'gemini-2.0-flash',
                'temperature': 0.5,
                'capabilities': ['vision', 'text'],
            },
            headers=auth_headers,
        )

        assert response.status_code == 200
        body = response.json()
        assert body['provider'] == 'openrouter'
        assert 'sk-or-plaintext' not in response.text
        assert body['api_key'] == '**********'

    def test_create_with_null_optionals_saves_as_the_default_draft(
        self, client, auth_headers
    ):
        """The form drafts a blank input as null; the strict `str` fields
        turned that draft into a raw 422 — "Input should be a valid string"
        with no field named — while the identical request with `''` passed.
        A null is "left empty", the same thing `''` says. Google is the
        draft provider here: reached through an SDK, its blank base URL is
        legitimate, which is exactly what this test keeps pinning."""
        response = client.post(
            '/api/v1/ai-connections',
            json={
                'name': 'Default draft',
                'provider': 'google',
                'api_key': 'sk-or-plaintext',
                'api_base_url': None,
                'model_name': None,
            },
            headers=auth_headers,
        )

        assert response.status_code == 200
        body = response.json()
        assert body['api_base_url'] == ''
        assert body['model_name'] == ''

    def test_an_openai_compatible_draft_without_a_base_url_is_refused(
        self, client, auth_headers
    ):
        """The OpenAI-compatible client glues its request URL out of the
        base URL: saved empty, the connection looks ready and the first
        call dies on a relative path with a transport error that never
        names the real cause. The save refuses instead (422, field named)."""
        response = client.post(
            '/api/v1/ai-connections',
            json={
                'name': 'Stranded draft',
                'provider': 'openrouter',
                'api_key': 'sk-or-plaintext',
                'api_base_url': '',
                'model_name': 'deepseek-v4',
            },
            headers=auth_headers,
        )

        assert response.status_code == 422
        error = response.json()['detail'][0]
        # The field is named by `loc`, not by a prefix inside the message
        # string: the form maps this entry onto the input it belongs under,
        # which only works when the location carries the field name.
        assert error['loc'] == ['body', 'api_base_url']
        assert not error['msg'].startswith('api_base_url')

    def test_the_base_url_refusal_answers_in_the_sessions_language(
        self, client, auth_headers
    ):
        """A refusal raised inside pydantic still goes home translated:
        the 422 handler resolves our own validator sentences through the
        error catalog, so a Polish session reads Polish, not the wire
        English the validator was written in."""
        response = client.post(
            '/api/v1/ai-connections',
            json={
                'name': 'Stranded draft',
                'provider': 'openrouter',
                'api_key': 'sk-or-plaintext',
                'api_base_url': '',
            },
            headers={**auth_headers, 'Accept-Language': 'pl'},
        )

        assert response.status_code == 422
        error = response.json()['detail'][0]
        assert error['loc'] == ['body', 'api_base_url']
        assert error['msg'] == (
            'Ten dostawca działa przez HTTP, więc adres bazowy jest wymagany '
            '— na przykład https://openrouter.ai/api/v1'
        )

    def test_an_sdk_provider_still_saves_without_a_base_url(self, client, auth_headers):
        """Anthropic goes through the SDK with a fixed endpoint; the
        create-side rule must not grow into 'never empty'."""
        response = client.post(
            '/api/v1/ai-connections',
            json={
                'name': 'SDK draft',
                'provider': 'anthropic',
                'api_key': 'sk-ant-plaintext',
                'api_base_url': '',
            },
            headers=auth_headers,
        )

        assert response.status_code == 200
        assert response.json()['api_base_url'] == ''

    def test_clearing_the_base_url_of_a_saved_openai_compatible_connection_is_refused(
        self, client, auth_headers
    ):
        """The stored provider decides on update (the payload has none):
        emptying the field of an OpenAI-compatible connection is the same
        stranding as saving one without it."""
        created = client.post(
            '/api/v1/ai-connections',
            json={
                'name': 'Groq',
                'provider': 'groq',
                'api_key': 'sk-groq',
                'api_base_url': 'https://api.groq.com/openai/v1',
            },
            headers=auth_headers,
        )
        assert created.status_code == 200
        conn_id = created.json()['id']

        response = client.put(
            f'/api/v1/ai-connections/{conn_id}',
            json={'api_base_url': ''},
            headers=auth_headers,
        )

        assert response.status_code == 400
        # The update refusal is keyed, not a raw sentence: the detail
        # carries the catalog's message and a truthful language claim.
        detail = response.json()['detail']
        assert detail['lang'] == 'en'
        assert detail['message'] == (
            'This provider is reached over HTTP, so the base URL is '
            'required — for example https://openrouter.ai/api/v1'
        )

    def test_a_named_null_clears_the_base_url_of_a_saved_sdk_connection(
        self, client, auth_headers
    ):
        """A cleared field clears (AGENTS.md §2b).

        The form maps an empty input to null, and the update read the named
        null as "do not touch": the dialog answered success over the address
        it had just been told to drop. The column is NOT NULL with the empty
        string as its cleared state, so a null arrives as that — and the
        openai-compatible rule still refuses it the same way `''` does.
        """
        created = client.post(
            '/api/v1/ai-connections',
            json={
                'name': 'Anthropic SDK',
                'provider': 'anthropic',
                'api_key': 'sk-ant-plaintext',
                'api_base_url': 'https://api.anthropic.com/v1',
                'model_name': 'claude-test',
            },
            headers=auth_headers,
        )
        assert created.status_code == 200
        conn_id = created.json()['id']

        response = client.put(
            f'/api/v1/ai-connections/{conn_id}',
            json={'api_base_url': None},
            headers=auth_headers,
        )

        assert response.status_code == 200, response.text
        assert response.json()['api_base_url'] == ''

    def test_a_key_the_payload_did_not_carry_leaves_the_base_url(
        self, client, auth_headers
    ):
        """The other half of the same contract: an absent key is not a
        decision. A writer fixed only towards clearing would drop the
        address on every save that never mentioned it."""
        created = client.post(
            '/api/v1/ai-connections',
            json={
                'name': 'Anthropic SDK two',
                'provider': 'anthropic',
                'api_key': 'sk-ant-plaintext',
                'api_base_url': 'https://api.anthropic.com/v1',
                'model_name': 'claude-test',
            },
            headers=auth_headers,
        )
        assert created.status_code == 200
        conn_id = created.json()['id']

        response = client.put(
            f'/api/v1/ai-connections/{conn_id}',
            json={'model_name': 'claude-other'},
            headers=auth_headers,
        )

        assert response.status_code == 200, response.text
        body = response.json()
        assert body['api_base_url'] == 'https://api.anthropic.com/v1'
        assert body['model_name'] == 'claude-other'

    def test_get_connections_masks_api_key(
        self, db_session, test_household, client, auth_headers
    ):
        conn = AiConnection(
            organization_id=test_household.id,
            name='Pre-existing',
            provider='openrouter',
            api_key_enc='enc:secret-cipher-text',
            capabilities=['vision', 'text'],
        )
        db_session.add(conn)
        db_session.commit()

        response = client.get('/api/v1/ai-connections', headers=auth_headers)
        assert response.status_code == 200
        body = response.json()['items']
        assert body[0]['api_key'] == '**********'
        assert 'secret-cipher-text' not in response.text

    def test_update_connection_keeps_masked_api_key(
        self, db_session, test_household, client, auth_headers
    ):
        conn = AiConnection(
            organization_id=test_household.id,
            name='Pre-existing',
            provider='openrouter',
            api_key_enc='enc:existing-cipher',
            capabilities=['vision', 'text'],
        )
        db_session.add(conn)
        db_session.commit()
        db_session.refresh(conn)

        response = client.put(
            f'/api/v1/ai-connections/{conn.id}',
            json={
                'name': 'renamed',
                'api_key': '**********',
            },
            headers=auth_headers,
        )

        assert response.status_code == 200
        db_session.expire_all()
        updated = db_session.get(AiConnection, conn.id)
        assert updated.name == 'renamed'
        assert updated.api_key_enc == 'enc:existing-cipher'

    def test_update_rejects_null_key_but_omitting_it_keeps_the_cipher(
        self, db_session, test_household, client, auth_headers
    ):
        conn = AiConnection(
            organization_id=test_household.id,
            name='Keep key',
            provider='openrouter',
            api_key_enc='enc:existing',
            capabilities=['text'],
        )
        db_session.add(conn)
        db_session.commit()
        conn_id = conn.id
        url = f'/api/v1/ai-connections/{conn_id}'

        response = client.put(url, json={'api_key': None}, headers=auth_headers)
        assert response.status_code == 400
        assert 'api_key' in response.json()['detail']['message']
        response = client.put(url, json={'name': 'Renamed'}, headers=auth_headers)
        assert response.status_code == 200
        db_session.expire_all()
        assert db_session.get(AiConnection, conn_id).api_key_enc == 'enc:existing'

    def test_update_connection_rotates_api_key(
        self, db_session, test_household, client, auth_headers
    ):
        conn = AiConnection(
            organization_id=test_household.id,
            name='Rotate me',
            provider='openrouter',
            api_key_enc='enc:old',
            capabilities=['vision', 'text'],
        )
        db_session.add(conn)
        db_session.commit()
        db_session.refresh(conn)

        response = client.put(
            f'/api/v1/ai-connections/{conn.id}',
            json={'api_key': 'sk-or-NEW'},
            headers=auth_headers,
        )

        assert response.status_code == 200
        db_session.expire_all()
        rotated = db_session.get(AiConnection, conn.id)
        assert rotated.api_key_enc != 'enc:old'
        assert rotated.api_key_enc.startswith('enc:')
        assert 'sk-or-NEW' not in rotated.api_key_enc

    def test_create_duplicate_name_in_same_org_returns_409(
        self, db_session, test_household, client, auth_headers
    ):
        existing = AiConnection(
            organization_id=test_household.id,
            name='Already taken',
            provider='openrouter',
            capabilities=['vision', 'text'],
        )
        db_session.add(existing)
        db_session.commit()

        response = client.post(
            '/api/v1/ai-connections',
            json={
                'name': 'Already taken',
                'provider': 'openrouter',
                'api_base_url': 'https://openrouter.ai/api/v1',
                'capabilities': ['vision', 'text'],
            },
            headers=auth_headers,
        )
        assert response.status_code == 409

    def test_update_duplicate_name_in_same_org_returns_409(
        self, db_session, test_household, client, auth_headers
    ):
        """Renaming a connection onto an existing sibling name must be
        a friendly 409, not a 500 IntegrityError traceback."""
        first = AiConnection(
            organization_id=test_household.id,
            name='First',
            provider='openrouter',
            capabilities=['vision', 'text'],
        )
        second = AiConnection(
            organization_id=test_household.id,
            name='Second',
            provider='openrouter',
            capabilities=['vision', 'text'],
        )
        db_session.add_all([first, second])
        db_session.commit()
        db_session.refresh(second)

        response = client.put(
            f'/api/v1/ai-connections/{second.id}',
            json={'name': 'First'},
            headers=auth_headers,
        )
        assert response.status_code == 409
        db_session.expire_all()
        unchanged = db_session.get(AiConnection, second.id)
        assert unchanged.name == 'Second'


@pytest.mark.integration
class TestAiConnectionsAccessControl:
    def test_get_returns_404_for_cross_org_connection(
        self, db_session, test_household, client, auth_headers
    ):
        """Tenant guard at the row level."""
        from app.models.organization import Organization

        other_org = Organization(name='Other Org')
        db_session.add(other_org)
        db_session.commit()
        db_session.refresh(other_org)

        foreign_conn = AiConnection(
            organization_id=other_org.id,
            name='foreign',
            provider='openrouter',
            capabilities=['vision'],
        )
        db_session.add(foreign_conn)
        db_session.commit()
        db_session.refresh(foreign_conn)

        response = client.get(
            f'/api/v1/ai-connections/{foreign_conn.id}',
            headers=auth_headers,
        )
        assert response.status_code == 404


@pytest.mark.integration
class TestAiConnectionsBindings:
    def test_set_binding_core_purpose_writes_under_settings_ai_defaults(
        self, db_session, test_household, client, auth_headers
    ):
        conn = AiConnection(
            organization_id=test_household.id,
            name='GPT-4o',
            provider='openrouter',
            capabilities=['vision', 'text'],
        )
        db_session.add(conn)
        db_session.commit()
        db_session.refresh(conn)

        response = client.put(
            '/api/v1/ai-connections/bindings',
            json={
                'purpose_key': 'vision.extract',
                'connection_id': str(conn.id),
            },
            headers=auth_headers,
        )

        assert response.status_code == 200

        db_session.expire_all()
        db_session.refresh(test_household)
        settings = test_household.settings or {}
        assert settings.get('ai', {}).get('defaults', {}).get('vision.extract') == str(
            conn.id
        )

    def test_purposes_lists_registered_with_binding_enriched(
        self, db_session, test_household, client, auth_headers
    ):
        conn = AiConnection(
            organization_id=test_household.id,
            name='GPT-4o',
            provider='openrouter',
            capabilities=['vision', 'text'],
        )
        db_session.add(conn)
        db_session.commit()
        db_session.refresh(conn)

        # Bind first.
        bind_resp = client.put(
            '/api/v1/ai-connections/bindings',
            json={
                'purpose_key': 'vision.extract',
                'connection_id': str(conn.id),
            },
            headers=auth_headers,
        )
        assert bind_resp.status_code == 200

        # Then list.
        response = client.get('/api/v1/ai-connections/purposes', headers=auth_headers)
        assert response.status_code == 200
        purposes = response.json()['items']
        # At minimum, vision.extract is registered.
        vision = next((p for p in purposes if p['key'] == 'vision.extract'), None)
        assert vision is not None
        assert vision['bound_connection_id'] == str(conn.id)
        # A capable connection with no failed test serves — the verdict the
        # promise sentences branch on.
        assert vision['usable'] is True

    def test_a_bound_connection_without_the_capability_reads_bound_but_unusable(
        self, db_session, test_household, client, auth_headers
    ):
        """Two questions, two fields: the choice and the verdict.

        A connection kept for text parsing can be bound to vision.extract —
        the binding endpoint does not check capability, and the state is
        reachable from plain UI. The list must still report the binding as
        the org's choice (``bound_connection_id`` names it, so the binding
        select renders it back and the deletion guard protects it), while
        ``usable`` carries the verdict the promise sentences branch on: the
        client builder refuses this connection with a 503.
        """
        text_only = AiConnection(
            organization_id=test_household.id,
            name='Recipe Parser',
            provider='openrouter',
            capabilities=['text'],
        )
        db_session.add(text_only)
        db_session.commit()
        db_session.refresh(text_only)

        bind_resp = client.put(
            '/api/v1/ai-connections/bindings',
            json={
                'purpose_key': 'vision.extract',
                'connection_id': str(text_only.id),
            },
            headers=auth_headers,
        )
        assert bind_resp.status_code == 200

        response = client.get('/api/v1/ai-connections/purposes', headers=auth_headers)
        assert response.status_code == 200
        vision = next(
            (p for p in response.json()['items'] if p['key'] == 'vision.extract'), None
        )
        assert vision is not None
        assert vision['bound_connection_id'] == str(text_only.id)
        assert vision['usable'] is False

    def test_a_failed_capability_check_reads_as_unbound_too(
        self, db_session, test_household, client, auth_headers
    ):
        """Only a recorded failure disqualifies — the connection stays the
        org's choice in ``bound_connection_id`` while ``usable`` carries the
        refusal."""
        failed_vision = AiConnection(
            organization_id=test_household.id,
            name='Failed Vision',
            provider='openrouter',
            capabilities=['vision', 'text'],
            capability_checks={'vision': {'ok': False, 'detail': '401'}},
        )
        db_session.add(failed_vision)
        db_session.commit()
        db_session.refresh(failed_vision)

        bind_resp = client.put(
            '/api/v1/ai-connections/bindings',
            json={
                'purpose_key': 'vision.extract',
                'connection_id': str(failed_vision.id),
            },
            headers=auth_headers,
        )
        assert bind_resp.status_code == 200

        response = client.get('/api/v1/ai-connections/purposes', headers=auth_headers)
        assert response.status_code == 200
        vision = next(
            (p for p in response.json()['items'] if p['key'] == 'vision.extract'), None
        )
        assert vision is not None
        assert vision['bound_connection_id'] == str(failed_vision.id)
        assert vision['usable'] is False

    def test_two_purposes_of_one_module_keep_separate_bindings(
        self, db_session, test_household, client, auth_headers
    ):
        """A module's second purpose must not take the first one's slot.

        The module-owned binding used to be one id per module
        (``settings.modules.<owner>.ai_default_connection_id``), which
        worked while every module had exactly one purpose. Recipes now has
        two — the page reader and the text parser — and a shared slot
        would let the last binding silently re-route the other purpose.
        Bindings are written per purpose key
        (``settings.ai.defaults[<key>]``); the module slot stays readable
        as the legacy home of choices made before the split.
        """
        reader = AiConnection(
            organization_id=test_household.id,
            name='Jina Reader',
            provider='jina',
            capabilities=['url_fetch'],
        )
        parser = AiConnection(
            organization_id=test_household.id,
            name='Recipe Parser',
            provider='openrouter',
            capabilities=['text'],
        )
        db_session.add_all([reader, parser])
        db_session.commit()
        db_session.refresh(reader)
        db_session.refresh(parser)

        first = client.put(
            '/api/v1/ai-connections/bindings',
            json={
                'purpose_key': 'recipes.text_parse',
                'connection_id': str(parser.id),
            },
            headers=auth_headers,
        )
        second = client.put(
            '/api/v1/ai-connections/bindings',
            json={
                'purpose_key': 'recipes.url_fetch',
                'connection_id': str(reader.id),
            },
            headers=auth_headers,
        )
        assert first.status_code == 200
        assert second.status_code == 200

        response = client.get('/api/v1/ai-connections/purposes', headers=auth_headers)
        assert response.status_code == 200
        by_key = {p['key']: p for p in response.json()['items']}
        assert by_key['recipes.text_parse']['bound_connection_id'] == str(parser.id)
        assert by_key['recipes.url_fetch']['bound_connection_id'] == str(reader.id)
        assert by_key['recipes.url_fetch']['usable'] is True

    def test_usable_without_a_binding_when_the_env_fallback_serves(
        self, monkeypatch, test_household, client, auth_headers
    ):
        """The env fallback is the one unbound state that still runs.

        With nothing named in settings, ``get_client_for_purpose`` hands
        out a transient client from ``LLM_API_KEY`` — so the list
        must say ``usable`` for exactly that org, or a screen would refuse
        to promise what the backend is about to serve. Nothing is chosen,
        so ``bound_connection_id`` stays empty: the two answers disagree
        on purpose here, and each field tells its own truth.
        """
        from app.config import settings as app_settings

        monkeypatch.setattr(app_settings, 'LLM_API_KEY', 'sk-or-test-fallback')

        response = client.get('/api/v1/ai-connections/purposes', headers=auth_headers)
        assert response.status_code == 200
        vision = next(
            (p for p in response.json()['items'] if p['key'] == 'vision.extract'), None
        )
        assert vision is not None
        assert vision['bound_connection_id'] is None
        assert vision['usable'] is True

    def test_rebind_existing_purpose_persists_new_connection(
        self, db_session, test_household, client, auth_headers
    ):
        """Rebinding a purpose that already has a default must persist.

        Regression: the first PUT wrote the binding, but a second PUT
        switching the same purpose to another connection returned 200 while
        the stored settings kept the old UUID — the UI dropdown snapped back.
        """
        conn_a = AiConnection(
            organization_id=test_household.id,
            name='Conn A',
            provider='openrouter',
            capabilities=['vision', 'text'],
        )
        conn_b = AiConnection(
            organization_id=test_household.id,
            name='Conn B',
            provider='deepseek',
            capabilities=['vision', 'text'],
        )
        db_session.add_all([conn_a, conn_b])
        db_session.commit()
        db_session.refresh(conn_a)
        db_session.refresh(conn_b)

        for conn in (conn_a, conn_b):
            response = client.put(
                '/api/v1/ai-connections/bindings',
                json={
                    'purpose_key': 'vision.extract',
                    'connection_id': str(conn.id),
                },
                headers=auth_headers,
            )
            assert response.status_code == 200

        db_session.expire_all()
        db_session.refresh(test_household)
        settings = test_household.settings or {}
        assert settings.get('ai', {}).get('defaults', {}).get('vision.extract') == str(
            conn_b.id
        )

        response = client.get('/api/v1/ai-connections/purposes', headers=auth_headers)
        assert response.status_code == 200
        vision = next(
            (p for p in response.json()['items'] if p['key'] == 'vision.extract'), None
        )
        assert vision is not None
        assert vision['bound_connection_id'] == str(conn_b.id)

    def test_clear_binding_with_null_connection_id(
        self, db_session, test_household, client, auth_headers
    ):
        """The UI's \"not configured\" option sends connection_id=null."""
        conn = AiConnection(
            organization_id=test_household.id,
            name='Conn A',
            provider='openrouter',
            capabilities=['vision', 'text'],
        )
        db_session.add(conn)
        db_session.commit()
        db_session.refresh(conn)

        response = client.put(
            '/api/v1/ai-connections/bindings',
            json={'purpose_key': 'vision.extract', 'connection_id': str(conn.id)},
            headers=auth_headers,
        )
        assert response.status_code == 200

        response = client.put(
            '/api/v1/ai-connections/bindings',
            json={'purpose_key': 'vision.extract', 'connection_id': None},
            headers=auth_headers,
        )
        assert response.status_code == 200

        response = client.get('/api/v1/ai-connections/purposes', headers=auth_headers)
        assert response.status_code == 200
        vision = next(
            (p for p in response.json()['items'] if p['key'] == 'vision.extract'), None
        )
        assert vision is not None
        assert vision['bound_connection_id'] is None

    def test_clear_binding_whose_home_is_the_legacy_module_slot_detaches(
        self, db_session, test_household, client, auth_headers
    ):
        """PUT connection_id:null must detach a purpose whose binding
        still lives in the module slot.

        Deployments that bound a purpose before per-purpose slots keep
        their choice in ``settings.modules.<owner>.ai_default_connection_id``
        — the old write path and archived migration aiconn02 both wrote there. The
        clear popped only ``ai.defaults[<key>]``, the read fallback
        answered with the slot, and \"not configured\" came back as the
        same connection: a 200 that changed nothing, on every deployment
        that ever bound a purpose. The write now carries the slot into
        ``ai.defaults`` for the module's purposes first, so the clear
        lands where the reader reads.
        """
        parser = AiConnection(
            organization_id=test_household.id,
            name='Recipe Parser',
            provider='openrouter',
            capabilities=['text'],
        )
        reader = AiConnection(
            organization_id=test_household.id,
            name='Jina Reader',
            provider='jina',
            capabilities=['url_fetch'],
        )
        db_session.add_all([parser, reader])
        db_session.commit()
        db_session.refresh(parser)

        # The slot predates per-purpose bindings — seed it the way the old
        # write path (and archived migration aiconn02) left it behind.
        test_household.settings = {
            'modules': {'recipes': {'ai_default_connection_id': str(parser.id)}}
        }
        db_session.commit()

        response = client.put(
            '/api/v1/ai-connections/bindings',
            json={'purpose_key': 'recipes.text_parse', 'connection_id': None},
            headers=auth_headers,
        )
        assert response.status_code == 200

        response = client.get('/api/v1/ai-connections/purposes', headers=auth_headers)
        assert response.status_code == 200
        by_key = {p['key']: p for p in response.json()['items']}
        # The detach the org asked for — this is the assertion the old
        # code failed: the slot answered for the purpose it was told to
        # release.
        assert by_key['recipes.text_parse']['bound_connection_id'] is None
        # The sibling read the slot as its fallback before this write; the
        # migration keeps that choice answering instead of silently
        # releasing a binding the org never touched.
        assert by_key['recipes.url_fetch']['bound_connection_id'] == str(parser.id)

        db_session.expire_all()
        db_session.refresh(test_household)
        settings = test_household.settings or {}
        assert 'ai_default_connection_id' not in (
            settings.get('modules', {}).get('recipes', {})
        )
        assert settings.get('ai', {}).get('defaults', {}).get(
            'recipes.url_fetch'
        ) == str(parser.id)

    def test_detaching_one_purpose_keeps_the_sibling_reading_the_slot(
        self, db_session, test_household, client, auth_headers
    ):
        """The slot is one id per module — releasing one purpose must not
        release its sibling.

        The slot predates the second recipes purpose, so it carries the
        module's original choice. Blindly clearing it on any detach would
        take that choice away from the purpose the org did not touch;
        carrying the slot into ``ai.defaults`` first keeps every sibling
        answering while the requested detach lands.
        """
        parser = AiConnection(
            organization_id=test_household.id,
            name='Recipe Parser',
            provider='openrouter',
            capabilities=['text'],
        )
        db_session.add(parser)
        db_session.commit()
        db_session.refresh(parser)

        test_household.settings = {
            'modules': {'recipes': {'ai_default_connection_id': str(parser.id)}}
        }
        db_session.commit()

        response = client.put(
            '/api/v1/ai-connections/bindings',
            json={'purpose_key': 'recipes.url_fetch', 'connection_id': None},
            headers=auth_headers,
        )
        assert response.status_code == 200

        response = client.get('/api/v1/ai-connections/purposes', headers=auth_headers)
        assert response.status_code == 200
        by_key = {p['key']: p for p in response.json()['items']}
        assert by_key['recipes.url_fetch']['bound_connection_id'] is None
        # text_parse's binding came from the slot; the migration — not the
        # detach — decides where it lives now, and it keeps answering.
        assert by_key['recipes.text_parse']['bound_connection_id'] == str(parser.id)


def _custom_admin_headers(db_session, organization, perms: list[str]) -> dict:
    """A member whose custom role carries *perms* and nothing else."""
    from app.models.role import Role, UserRole
    from app.models.user import User
    from app.services.token_service import create_access_token

    user = User(
        email=f'custom_{uuid.uuid4().hex[:8]}@example.com',
        hashed_password='x',
        organization_id=organization.id,
        role='user',
        is_active=True,
    )
    role = Role(
        name=f'custom_{uuid.uuid4().hex[:6]}',
        permissions=perms,
        is_system=False,
        organization_id=organization.id,
    )
    db_session.add_all([user, role])
    db_session.flush()
    db_session.add(UserRole(user_id=user.id, role_id=role.id))
    db_session.commit()
    return {
        'Authorization': f'Bearer {create_access_token(data={"sub": str(user.id)})}'
    }


@pytest.mark.integration
class TestTheOrganizationWriteIsNotADoorToTheBindings:
    """The bindings answer to one key, through one door.

    ``PUT /organizations`` takes the settings block whole and asks for
    ``admin:access``; the bindings door asks for ``org:settings:write``.
    Measured: an account with the narrower key rebinds a purpose and is
    refused the organization write — and the reverse held too, through the
    block, for an account holding only ``admin:access``.
    """

    def _bound(self, db_session, test_household) -> tuple[str, str]:
        first = AiConnection(
            organization_id=test_household.id,
            name='Bound',
            provider='openrouter',
            capabilities=['vision', 'text'],
        )
        other = AiConnection(
            organization_id=test_household.id,
            name='Other',
            provider='openrouter',
            capabilities=['vision', 'text'],
        )
        db_session.add_all([first, other])
        db_session.commit()
        return str(first.id), str(other.id)

    def test_the_organization_write_cannot_rebind_a_purpose(
        self, db_session, test_household, client, auth_headers
    ):
        bound, other = self._bound(db_session, test_household)
        client.put(
            '/api/v1/ai-connections/bindings',
            json={'purpose_key': 'vision.extract', 'connection_id': bound},
            headers=auth_headers,
        ).raise_for_status()
        administration_only = _custom_admin_headers(
            db_session, test_household, ['admin:access']
        )
        refused = client.put(
            '/api/v1/ai-connections/bindings',
            json={'purpose_key': 'vision.extract', 'connection_id': other},
            headers=administration_only,
        )
        assert refused.status_code == 403

        settings_now = client.get(
            '/api/v1/organizations/my', headers=auth_headers
        ).json()['settings']
        response = client.put(
            '/api/v1/organizations',
            json={
                'settings': {
                    **settings_now,
                    'ai': {'defaults': {'vision.extract': other}},
                    'modules': {'vision': {'ai_default_connection_id': other}},
                    'allow_permanent_delete': True,
                }
            },
            headers=administration_only,
        )

        assert response.status_code == 200, response.text
        db_session.expire_all()
        db_session.refresh(test_household)
        stored = test_household.settings or {}
        assert stored['ai']['defaults']['vision.extract'] == bound
        assert 'ai_default_connection_id' not in stored['modules']['vision']
        # The rest of the block is this door's, and it was written.
        assert stored['allow_permanent_delete'] is True

    def test_a_stale_block_does_not_undo_a_binding_made_since(
        self, db_session, test_household, client, auth_headers
    ):
        bound, _ = self._bound(db_session, test_household)
        read_earlier = client.get(
            '/api/v1/organizations/my', headers=auth_headers
        ).json()['settings']
        client.put(
            '/api/v1/ai-connections/bindings',
            json={'purpose_key': 'vision.extract', 'connection_id': bound},
            headers=auth_headers,
        ).raise_for_status()

        response = client.put(
            '/api/v1/organizations',
            json={'settings': {**read_earlier, 'allow_permanent_delete': True}},
            headers=auth_headers,
        )

        assert response.status_code == 200, response.text
        purposes = client.get(
            '/api/v1/ai-connections/purposes', headers=auth_headers
        ).json()['items']
        by_key = {p['key']: p for p in purposes}
        assert by_key['vision.extract']['bound_connection_id'] == bound

    def test_a_legacy_binding_survives_a_block_without_it(
        self, db_session, test_household, client, auth_headers
    ):
        bound, _ = self._bound(db_session, test_household)
        test_household.settings = {
            'modules': {'recipes': {'ai_default_connection_id': bound}}
        }
        db_session.commit()

        response = client.put(
            '/api/v1/organizations',
            json={'settings': {'modules': {'recipes': {'jina': {}}}}},
            headers=auth_headers,
        )

        assert response.status_code == 200, response.text
        db_session.expire_all()
        db_session.refresh(test_household)
        recipes = (test_household.settings or {})['modules']['recipes']
        assert recipes['ai_default_connection_id'] == bound
        assert recipes['jina'] == {}


@pytest.mark.integration
class TestAiConnectionsDelete:
    def test_delete_unbound_connection_succeeds(
        self, db_session, test_household, client, auth_headers
    ):
        conn = AiConnection(
            organization_id=test_household.id,
            name='To delete',
            provider='openrouter',
            capabilities=['vision'],
        )
        db_session.add(conn)
        db_session.commit()
        db_session.refresh(conn)

        response = client.delete(
            f'/api/v1/ai-connections/{conn.id}',
            headers=auth_headers,
        )
        assert response.status_code == 200

    def test_delete_bound_connection_returns_409(
        self, db_session, test_household, client, auth_headers
    ):
        conn = AiConnection(
            organization_id=test_household.id,
            name='Bound',
            provider='openrouter',
            capabilities=['vision', 'text'],
        )
        db_session.add(conn)
        db_session.commit()
        db_session.refresh(conn)

        # Seed the binding via the public PUT endpoint so the test
        # exercises the same code path the real client uses.
        bind_resp = client.put(
            '/api/v1/ai-connections/bindings',
            json={
                'purpose_key': 'vision.extract',
                'connection_id': str(conn.id),
            },
            headers=auth_headers,
        )
        assert bind_resp.status_code == 200, bind_resp.text

        response = client.delete(
            f'/api/v1/ai-connections/{conn.id}',
            headers=auth_headers,
        )
        assert response.status_code == 409

    def test_delete_bound_connection_refuses_in_the_readers_language(
        self, db_session, test_household, client, auth_headers
    ):
        """The 409 detail comes from the error catalog, not a raw f-string.

        The refusal used to carry the connection's UUID in an English
        sentence no matter the session language — a Polish reader saw
        "Connection 1f832c3a-… is still the default". The catalog entry
        says what to do next without naming a UUID at all."""
        conn = AiConnection(
            organization_id=test_household.id,
            name='Bound (catalog refusal)',
            provider='openrouter',
            capabilities=['vision'],
        )
        db_session.add(conn)
        db_session.commit()
        db_session.refresh(conn)

        bind_resp = client.put(
            '/api/v1/ai-connections/bindings',
            json={
                'purpose_key': 'vision.extract',
                'connection_id': str(conn.id),
            },
            headers=auth_headers,
        )
        assert bind_resp.status_code == 200, bind_resp.text

        response = client.delete(
            f'/api/v1/ai-connections/{conn.id}',
            headers={**auth_headers, 'Accept-Language': 'pl'},
        )
        assert response.status_code == 409
        detail = response.json()['detail']
        assert str(conn.id) not in response.text
        assert detail == {
            'code': 'CONNECTION_STILL_BOUND',
            'message': 'To połączenie jest przypisane do celu. Najpierw je odepnij.',
        }


@pytest.mark.integration
class TestTestConnection:
    """POST /api/v1/ai-connections/test — lightweight model discovery.

    The endpoint accepts an inline draft (provider + key + base_url) so the
    UI can test BEFORE saving. The list_models() call is patched to avoid
    real HTTP — the underlying client behaviour is covered by unit tests.
    """

    def test_test_connection_returns_models(
        self, db_session, test_household, client, auth_headers
    ):
        with patch(
            'app.core.llm.openai_client.OpenAiCompatibleClient.list_models',
            new=AsyncMock(
                return_value=['google/gemini-2.0-flash-001', 'openai/gpt-4o']
            ),
        ):
            response = client.post(
                '/api/v1/ai-connections/test',
                json={
                    'provider': 'openrouter',
                    'api_key': 'sk-or-fake',
                    'api_base_url': 'https://openrouter.ai/api/v1',
                    'model_name': 'm',
                },
                headers=auth_headers,
            )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body['ok'] is True
        assert 'google/gemini-2.0-flash-001' in body['models']

    def test_test_connection_400_on_failure(
        self, db_session, test_household, client, auth_headers
    ):
        """An unexpected failure answers 400 in catalogue words; the raw
        exception travels to the log — the reader cannot act on "401
        Unauthorized", and on a Polish screen it would be English."""
        with patch(
            'app.core.llm.openai_client.OpenAiCompatibleClient.list_models',
            new=AsyncMock(side_effect=RuntimeError('401 Unauthorized')),
        ):
            response = client.post(
                '/api/v1/ai-connections/test',
                json={
                    'provider': 'openrouter',
                    'api_key': 'sk-bad',
                    'api_base_url': 'https://openrouter.ai/api/v1',
                    'model_name': 'm',
                },
                headers=auth_headers,
            )
        assert response.status_code == 400
        assert 'could not be completed' in response.json()['detail']['message']
        assert response.json()['detail']['code'] == 'LLM_CONNECTION_TEST_FAILED'
        assert '401' not in response.text

    def test_test_connection_names_a_rejected_key(
        self, db_session, test_household, client, auth_headers
    ):
        """A key the provider rejects is the most common first-setup state —
        the test button says so instead of echoing the provider's body."""
        from app.core.llm.errors import LlmProviderRefusalError

        with patch(
            'app.core.llm.openai_client.OpenAiCompatibleClient.list_models',
            new=AsyncMock(
                side_effect=LlmProviderRefusalError(
                    'OpenAI-compatible list_models returned 401: '
                    '{"error": "invalid api key"}',
                    status_code=401,
                )
            ),
        ):
            response = client.post(
                '/api/v1/ai-connections/test',
                json={
                    'provider': 'openrouter',
                    'api_key': 'sk-bad',
                    'api_base_url': 'https://openrouter.ai/api/v1',
                    'model_name': 'm',
                },
                headers=auth_headers,
            )
        assert response.status_code == 400
        assert response.json()['detail']['code'] == 'LLM_PROVIDER_KEY_REJECTED'
        detail = response.json()['detail']['message']
        assert 'key' in detail.lower()
        assert 'invalid api key' not in detail
        assert 'OpenAI-compatible' not in detail

    def test_test_connection_requires_provider_or_id(
        self, db_session, test_household, client, auth_headers
    ):
        response = client.post(
            '/api/v1/ai-connections/test', json={}, headers=auth_headers
        )
        assert response.status_code == 400

    def test_test_connection_anthropic_uses_anthropic_client(
        self, db_session, test_household, client, auth_headers
    ):
        """Anthropic provider must route to AnthropicClient, not OpenAI."""
        with (
            patch(
                'app.core.llm.anthropic_client.AnthropicClient.list_models',
                new=AsyncMock(return_value=['claude-sonnet-4-5']),
            ) as mock_anthropic,
            patch(
                'app.core.llm.openai_client.OpenAiCompatibleClient.list_models',
                new=AsyncMock(return_value=['should-not-be-called']),
            ) as mock_openai,
        ):
            response = client.post(
                '/api/v1/ai-connections/test',
                json={
                    'provider': 'anthropic',
                    'api_key': 'sk-ant-fake',
                    'api_base_url': 'https://api.anthropic.com',
                    'model_name': 'claude-sonnet-4-5',
                },
                headers=auth_headers,
            )
        assert response.status_code == 200, response.text
        assert response.json()['models'] == ['claude-sonnet-4-5']
        mock_anthropic.assert_awaited_once()
        mock_openai.assert_not_awaited()


@pytest.mark.integration
class TestTestConnectionSsrfGuard:
    """The base URL is attacker-controlled, so it goes through the
    SSRF guard before any outbound request leaves the server.

    These tests deliberately do NOT patch ``list_models`` — the guard lives
    inside it, and patching it away would test nothing. The HTTP layer
    (``httpx.AsyncClient.get``) is patched instead, so a request that should
    have been blocked is observable as an awaited call.
    """

    def test_test_connection_rejects_link_local_address(
        self, db_session, test_household, client, auth_headers, monkeypatch
    ):
        """The cloud metadata endpoint must not be reachable."""
        from app.config import settings

        # The test examines the guard's rule, not the machine's
        # configuration: an operator running with the local-model flag on
        # must not watch these rejections evaporate.
        monkeypatch.setattr(settings, 'LLM_ALLOW_PRIVATE_NETWORKS', False)
        with patch('httpx.AsyncClient.get', new=AsyncMock()) as mock_get:
            response = client.post(
                '/api/v1/ai-connections/test',
                json={
                    'provider': 'custom',
                    'api_key': 'sk-fake',
                    'api_base_url': 'http://169.254.169.254/',
                    'model_name': 'm',
                },
                headers=auth_headers,
            )

        assert response.status_code == 400, response.text
        # The refusal names the reason and the LLM's own opt-out flag —
        # not the webhook validator it delegates to. Keyed refusal: the
        # envelope carries the translated sentence and the language.
        detail = response.json()['detail']
        assert 'private or internal address' in detail['message']
        assert 'LLM_ALLOW_PRIVATE_NETWORKS' in detail['message']
        mock_get.assert_not_awaited()

    def test_the_guard_refusal_speaks_the_readers_language(
        self, db_session, test_household, client, auth_headers, monkeypatch
    ):
        """The same refusal on a Polish request — key first, sentence
        second: the screen reads Polish and the envelope says so."""
        from app.config import settings

        monkeypatch.setattr(settings, 'LLM_ALLOW_PRIVATE_NETWORKS', False)
        with patch('httpx.AsyncClient.get', new=AsyncMock()) as mock_get:
            response = client.post(
                '/api/v1/ai-connections/test',
                json={
                    'provider': 'custom',
                    'api_key': 'sk-fake',
                    'api_base_url': 'http://10.0.0.5:11434/v1',
                    'model_name': 'm',
                },
                headers={**auth_headers, 'Accept-Language': 'pl'},
            )

        assert response.status_code == 400, response.text
        detail = response.json()['detail']
        assert detail['lang'] == 'pl'
        assert 'prywatny lub wewnętrzny' in detail['message']
        assert 'private or internal' not in detail['message']
        mock_get.assert_not_awaited()

    def test_test_connection_rejects_loopback_hostname(
        self, db_session, test_household, client, auth_headers, monkeypatch
    ):
        from app.config import settings

        # The test examines the guard's rule, not the machine's
        # configuration: an operator running with the local-model flag on
        # must not watch these rejections evaporate.
        monkeypatch.setattr(settings, 'LLM_ALLOW_PRIVATE_NETWORKS', False)
        with patch('httpx.AsyncClient.get', new=AsyncMock()) as mock_get:
            response = client.post(
                '/api/v1/ai-connections/test',
                json={
                    'provider': 'custom',
                    'api_key': 'sk-fake',
                    'api_base_url': 'http://localhost:8000/v1',
                    'model_name': 'm',
                },
                headers=auth_headers,
            )

        assert response.status_code == 400, response.text
        mock_get.assert_not_awaited()

    def test_create_rejects_private_base_url(
        self, db_session, test_household, client, auth_headers, monkeypatch
    ):
        """A malicious URL must not even reach the database — it would
        fire later from a background job, outside any user request."""
        from app.config import settings

        # The test examines the guard's rule, not the machine's
        # configuration: an operator running with the local-model flag on
        # must not watch these rejections evaporate.
        monkeypatch.setattr(settings, 'LLM_ALLOW_PRIVATE_NETWORKS', False)
        response = client.post(
            '/api/v1/ai-connections',
            json={
                'name': 'Metadata probe',
                'provider': 'custom',
                'api_key': 'sk-fake',
                'api_base_url': 'http://169.254.169.254/v1',
                'model_name': 'm',
                'capabilities': ['text'],
            },
            headers=auth_headers,
        )

        assert response.status_code == 400, response.text
        assert 'private or internal address' in response.text
        assert 'LLM_ALLOW_PRIVATE_NETWORKS' in response.text
        assert (
            db_session.query(AiConnection)
            .filter(AiConnection.name == 'Metadata probe')
            .count()
            == 0
        )

    def test_update_rejects_private_base_url(
        self, db_session, test_household, client, auth_headers, monkeypatch
    ):
        from app.config import settings

        # The test examines the guard's rule, not the machine's
        # configuration: an operator running with the local-model flag on
        # must not watch these rejections evaporate.
        monkeypatch.setattr(settings, 'LLM_ALLOW_PRIVATE_NETWORKS', False)
        conn = AiConnection(
            organization_id=test_household.id,
            name='Legit',
            provider='custom',
            api_key_enc='enc:cipher',
            api_base_url='https://openrouter.ai/api/v1',
            capabilities=['text'],
        )
        db_session.add(conn)
        db_session.commit()
        db_session.refresh(conn)

        response = client.put(
            f'/api/v1/ai-connections/{conn.id}',
            json={'api_base_url': 'http://10.0.0.5:8080/v1'},
            headers=auth_headers,
        )

        assert response.status_code == 400, response.text
        db_session.refresh(conn)
        assert conn.api_base_url == 'https://openrouter.ai/api/v1'

    def test_create_allows_private_base_url_when_operator_opts_in(
        self, db_session, test_household, client, auth_headers, monkeypatch
    ):
        from app.config import settings

        monkeypatch.setattr(settings, 'LLM_ALLOW_PRIVATE_NETWORKS', True)

        response = client.post(
            '/api/v1/ai-connections',
            json={
                'name': 'Local Ollama',
                'provider': 'custom',
                'api_key': '',
                'api_base_url': 'http://127.0.0.1:11434/v1',
                'model_name': 'llama3',
                'capabilities': ['text'],
            },
            headers=auth_headers,
        )

        assert response.status_code == 200, response.text

    def test_private_address_allowed_when_operator_opts_in(
        self, db_session, test_household, client, auth_headers, monkeypatch
    ):
        """Self-hosted Ollama on 127.0.0.1 stays usable behind the flag."""
        import httpx

        from app.config import settings

        monkeypatch.setattr(settings, 'LLM_ALLOW_PRIVATE_NETWORKS', True)

        with patch(
            'httpx.AsyncClient.get',
            new=AsyncMock(
                return_value=httpx.Response(200, json={'data': [{'id': 'llama3'}]})
            ),
        ) as mock_get:
            response = client.post(
                '/api/v1/ai-connections/test',
                json={
                    'provider': 'custom',
                    'api_key': '',
                    'api_base_url': 'http://127.0.0.1:11434/v1',
                    'model_name': 'llama3',
                },
                headers=auth_headers,
            )

        assert response.status_code == 200, response.text
        assert response.json()['models'] == ['llama3']
        mock_get.assert_awaited_once()
