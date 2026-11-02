"""A module may only call the core APIs in its own name.

``core_api.settings``, ``core_api.secrets`` and ``core_api.scheduler``
key their namespaces by a ``module_name`` argument; before the identity
carried by ``app.core.module_identity``, that argument was a claim anyone
could write. Module A calling with B's name read B's settings — including
``get_decrypted_async``, B's plaintext secret — and unhooked B's
scheduled jobs. The refusal is explicit: ``PermissionError`` naming both
modules. Core code (no identity bound) still speaks for everyone, which
is how the settings screen and ``module disable`` work.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from app.core._event_bus import EventBus
from app.core.contracts.events import EventPayload
from app.core.module_identity import module_scope
from app.core.public_api import core_api

ORG = '00000000-0000-0000-0000-000000000001'


@pytest.mark.unit
class TestSettings:
    async def test_a_module_cannot_read_anothers_plaintext_secret(self):
        with module_scope('shelf_notes'), pytest.raises(PermissionError) as exc:
            await core_api.settings.get_decrypted_async(
                object(), ORG, 'equipment', 'api_key'
            )
        assert 'shelf_notes' in str(exc.value)
        assert 'equipment' in str(exc.value)

    async def test_a_module_cannot_write_anothers_settings(self):
        with module_scope('shelf_notes'), pytest.raises(PermissionError):
            await core_api.settings.set_bulk_async(object(), ORG, 'equipment', {})

    async def test_a_module_cannot_encrypt_hidden_under_anothers_name(self):
        with module_scope('shelf_notes'), pytest.raises(PermissionError):
            core_api.settings.encrypt_secret('equipment', 'value')

    async def test_core_code_still_names_any_module(self, monkeypatch):
        """The core's own settings screen passes a module name with no
        identity around it; the call must reach the reader, not raise."""
        read: list[tuple] = []

        async def fake_get_by_id_async(db, org_id):
            read.append((db, org_id))
            return None

        monkeypatch.setattr(
            'app.services._org_reads.get_by_id_async', fake_get_by_id_async
        )

        db = object()
        assert await core_api.settings.get_async(db, ORG, 'equipment') is None
        assert read == [(db, ORG)]

    async def test_a_shipped_module_may_reach_a_companions_settings(self, monkeypatch):
        """Reviewed in-tree composition: documents' approval road reads
        approvals' settings through the approvals API. The request's
        identity is documents, and the refusal must not fire on code the
        repository ships (ADR-019)."""
        read: list[tuple] = []

        async def fake_get_by_id_async(db, org_id):
            read.append((db, org_id))
            return None

        monkeypatch.setattr(
            'app.services._org_reads.get_by_id_async', fake_get_by_id_async
        )

        db = object()
        with module_scope('warehouse'):
            assert await core_api.settings.get_async(db, ORG, 'approvals') is None
        assert read == [(db, ORG)]

    async def test_a_core_settings_namespace_is_not_a_modules(self, monkeypatch):
        """``core`` answers to no loaded module — a core service running
        inside a module's request reads its own namespace."""
        read: list[tuple] = []

        async def fake_get_by_id_async(db, org_id):
            read.append((db, org_id))
            return None

        monkeypatch.setattr(
            'app.services._org_reads.get_by_id_async', fake_get_by_id_async
        )

        db = object()
        with module_scope('shelf_notes'):
            assert await core_api.settings.get_async(db, ORG, 'core') is None
        assert read == [(db, ORG)]


@pytest.mark.unit
class TestSecrets:
    def test_a_module_cannot_encrypt_for_another(self):
        with module_scope('shelf_notes'), pytest.raises(PermissionError):
            core_api.secrets.encrypt_for_module('equipment', 'value')

    def test_a_module_cannot_decrypt_anothers(self):
        with module_scope('shelf_notes'), pytest.raises(PermissionError):
            core_api.secrets.decrypt_for_module('equipment', 'enc:mod1:xxx')

    def test_a_module_encrypts_for_itself(self):
        ciphertext = core_api.secrets.encrypt_for_module('webhooks', 'value')
        assert ciphertext != 'value'


@pytest.mark.unit
class TestScheduler:
    def test_a_module_cannot_register_under_anothers_name(self):
        with module_scope('shelf_notes'), pytest.raises(PermissionError):
            core_api.scheduler.register_task(
                'job',
                timedelta(minutes=5),
                lambda: None,
                module_name='equipment',
            )

    def test_a_module_cannot_unhook_anothers_job(self):
        with module_scope('shelf_notes'), pytest.raises(PermissionError):
            core_api.scheduler.unregister_task('job', module_name='equipment')

    def test_a_module_may_unregister_its_own(self):
        with module_scope('webhooks'):
            assert (
                core_api.scheduler.unregister_task(
                    'no_such_job', module_name='webhooks'
                )
                is False
            )


@pytest.mark.unit
class TestEvents:
    def test_a_module_cannot_claim_anothers_namespace(self):
        class _Thing(EventPayload):
            pass

        from app.core.contracts.events import register_payload

        with module_scope('webhooks'), pytest.raises(ValueError) as exc:
            register_payload('equipment.new_thing', _Thing)
        assert 'webhooks' in str(exc.value)

    async def test_a_module_cannot_emit_anothers_unregistered_event(self):
        bus = EventBus()
        with module_scope('webhooks'), pytest.raises(ValueError):
            await bus.emit('equipment.new_thing', EventPayload())

    async def test_a_module_can_emit_a_core_event(self):
        from app.core._event_types import TenantEventPayload

        bus = EventBus()
        with module_scope('webhooks'):
            await bus.emit(
                'module.enabled',
                TenantEventPayload(organization_id=ORG, module_name='webhooks'),
            )
