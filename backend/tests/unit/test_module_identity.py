"""The identity a unit of work runs under, and who may name whom.

``app.core.module_identity`` is the ContextVar the HTTP middleware, the
lifecycle hooks, the scheduler and the event bus set around a module's
code. Core code runs with no identity and may speak for anyone; a module
may speak only for itself. These tests pin the helper semantics and the
middleware's bind/reset; the seams (settings, secrets, scheduler, events)
are covered where they live.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import timedelta
from unittest.mock import AsyncMock

import pytest
from fastapi import APIRouter

from app.core.module_identity import (
    ModuleIdentityMiddleware,
    current_module,
    event_emission_refusal,
    event_registration_refusal,
    foreign_module_refusal,
    module_name_from_api_path,
    module_scope,
    refuse_foreign_module,
)
from app.core.modules import BaseModule, ModuleMetadata
from app.core.scheduler import TaskScheduler
from app.services.module_lifecycle_service import enable_modules_async

KNOWN = {'foo', 'bar'}


class TestTheScope:
    @pytest.mark.unit
    def test_a_scope_sets_and_restores_the_identity(self):
        assert current_module() is None
        with module_scope('foo'):
            assert current_module() == 'foo'
            with module_scope('bar'):
                assert current_module() == 'bar'
            assert current_module() == 'foo'
        assert current_module() is None

    @pytest.mark.unit
    def test_core_code_names_anyone(self):
        assert foreign_module_refusal('bar', api='x') is None

    @pytest.mark.unit
    def test_a_module_names_itself(self):
        with module_scope('foo'):
            assert foreign_module_refusal('foo', api='x') is None

    @pytest.mark.unit
    def test_a_module_naming_another_is_refused(self):
        # 'equipment' is a loaded module, 'shelf_notes' is a dropped one —
        # the refusal needs the named namespace to belong to a real module.
        with module_scope('shelf_notes'):
            refusal = foreign_module_refusal('equipment', api='core_api.settings.get')
            assert refusal is not None
            assert 'shelf_notes' in refusal
            assert 'equipment' in refusal
            with pytest.raises(PermissionError):
                refuse_foreign_module('equipment', api='core_api.settings.get')

    @pytest.mark.unit
    def test_a_name_no_loaded_module_answers_to_is_not_refused(self):
        # 'core' is the core's own settings namespace; a core service runs
        # inside a module's request too, so this must stay readable.
        with module_scope('shelf_notes'):
            assert foreign_module_refusal('core', api='x') is None


class TestTheEventNamespace:
    @pytest.mark.unit
    def test_core_registers_and_emits_anything(self):
        assert event_registration_refusal('bar.x', known_modules=KNOWN) is None
        assert (
            event_emission_refusal(
                'bar.x', core_owned=False, runtime_owner=None, known_modules=KNOWN
            )
            is None
        )

    @pytest.mark.unit
    def test_a_module_claims_its_own_namespace(self):
        with module_scope('foo'):
            assert event_registration_refusal('foo.x', known_modules=KNOWN) is None

    @pytest.mark.unit
    def test_a_module_cannot_claim_another_modules_namespace(self):
        with module_scope('foo'):
            refusal = event_registration_refusal('bar.x', known_modules=KNOWN)
            assert refusal is not None
            assert 'bar' in refusal

    @pytest.mark.unit
    def test_a_historical_prefix_no_module_answers_to_is_still_claimable(self):
        """``recipes`` owns ``recipe.created`` and ``purchase_orders`` owns
        ``receipt.created_from_po``: the namespace is a claim, not always
        the module's own spelling, and only a loaded module's name is
        protected."""
        with module_scope('foo'):
            assert event_registration_refusal('receipt.x', known_modules=KNOWN) is None

    @pytest.mark.unit
    def test_a_module_emits_core_events(self):
        with module_scope('foo'):
            assert (
                event_emission_refusal(
                    'item.created',
                    core_owned=True,
                    runtime_owner=None,
                    known_modules=KNOWN,
                )
                is None
            )

    @pytest.mark.unit
    def test_a_module_emits_an_event_it_registered(self):
        with module_scope('foo'):
            assert (
                event_emission_refusal(
                    'receipt.created',
                    core_owned=False,
                    runtime_owner='foo',
                    known_modules=KNOWN,
                )
                is None
            )

    @pytest.mark.unit
    def test_a_module_may_not_emit_an_event_registered_by_another(self):
        with module_scope('foo'):
            refusal = event_emission_refusal(
                'receipt.created',
                core_owned=False,
                runtime_owner='bar',
                known_modules=KNOWN,
            )
            assert refusal is not None
            assert 'bar' in refusal

    @pytest.mark.unit
    def test_a_module_may_not_announce_another_modules_unregistered_event(self):
        with module_scope('foo'):
            refusal = event_emission_refusal(
                'bar.thing',
                core_owned=False,
                runtime_owner=None,
                known_modules=KNOWN,
            )
            assert refusal is not None


class TestTheBoundaries:
    @pytest.mark.unit
    def test_a_modules_enable_hook_runs_under_its_identity(self):
        seen: list[str | None] = []

        class Hooked(BaseModule):
            @property
            def metadata(self) -> ModuleMetadata:
                return ModuleMetadata(
                    name='shelf_notes',
                    version='1.0.0',
                    display_name='Shelf notes',
                    description='',
                    icon='box',
                )

            def register_routes(self) -> APIRouter:
                return APIRouter()

            def on_enable(self, organization_id, context):  # type: ignore[no-untyped-def]
                seen.append(current_module())

        asyncio.run(
            enable_modules_async(
                [Hooked()],
                uuid.UUID('00000000-0000-0000-0000-000000000001'),
                db=AsyncMock(),
            )
        )

        assert seen == ['shelf_notes']
        assert current_module() is None

    @pytest.mark.unit
    def test_a_scheduled_task_runs_under_its_modules_identity(self):
        seen: list[str | None] = []

        async def handler() -> None:
            seen.append(current_module())

        scheduler = TaskScheduler()
        scheduler.register(
            name='job',
            interval=timedelta(minutes=5),
            handler=handler,
            module_name='webhooks',
        )

        asyncio.run(scheduler._execute_task(scheduler._tasks['webhooks.job']))

        assert seen == ['webhooks']
        assert current_module() is None


class TestTheMiddleware:
    @pytest.mark.unit
    def test_a_module_path_binds_the_identity_and_resets_it(self, monkeypatch):
        seen: list[str | None] = []

        async def inner(scope, receive, send):
            seen.append(current_module())

        monkeypatch.setattr(
            'app.core.module_identity._module_mounted_at',
            lambda name: name if name == 'purchase_orders' else None,
        )
        middleware = ModuleIdentityMiddleware(inner)

        asyncio.run(
            middleware(
                {'type': 'http', 'path': '/api/v1/purchase-orders/42'},
                None,
                None,
            )
        )

        assert seen == ['purchase_orders']
        assert current_module() is None

    @pytest.mark.unit
    def test_a_core_path_binds_nothing(self, monkeypatch):
        seen: list[str | None] = []

        async def inner(scope, receive, send):
            seen.append(current_module())

        monkeypatch.setattr(
            'app.core.module_identity._module_mounted_at', lambda name: None
        )
        middleware = ModuleIdentityMiddleware(inner)

        asyncio.run(middleware({'type': 'http', 'path': '/api/v1/labels'}, None, None))

        assert seen == [None]

    @pytest.mark.unit
    def test_the_path_segment_is_normalised_back_to_a_module_name(self):
        assert (
            module_name_from_api_path('/api/v1/purchase-orders/42') == 'purchase_orders'
        )
        assert module_name_from_api_path('/api/v1/items') == 'items'
        assert module_name_from_api_path('/health') is None
