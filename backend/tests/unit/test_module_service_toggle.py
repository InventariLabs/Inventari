"""Unit tests for ModuleService.toggle_module — async hook handling.

The disable-path must await ``on_disable``
when it returns a coroutine, mirroring the enable-path. These tests
verify the fix by registering a fake module with an async ``on_disable``
and asserting the hook actually runs.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest

from app.core._base_module import BaseModule
from app.core._module_declarations import ModuleMetadata
from app.core.contracts import UserContextDTO
from app.core.module_registry import module_registry
from app.services.module_service import ModuleService


class _AsyncDisableModule(BaseModule):
    """Fake module whose ``on_disable`` is async — sets a flag when run."""

    def __init__(self) -> None:
        self.disable_hook_ran = False

    @property
    def metadata(self) -> ModuleMetadata:
        return ModuleMetadata(
            name='__test_async_disable',
            display_name='Test Async Disable',
            description='Test module for S1',
            icon='box',
        )

    def register_routes(self):
        raise NotImplementedError

    async def system_on_enable(
        self, organization_id: str, db: Any, *, user: Any | None = None
    ) -> None:
        pass

    async def system_on_disable(self, organization_id: str, db: Any) -> None:
        pass

    def on_enable(self, organization_id: str, context: Any) -> None:
        pass

    async def on_disable(self, organization_id: str, context: Any) -> None:
        self.disable_hook_ran = True


class _AsyncEnableModule(BaseModule):
    """Fake module whose ``on_enable`` is async — sets a flag when run."""

    def __init__(self) -> None:
        self.enable_hook_ran = False

    @property
    def metadata(self) -> ModuleMetadata:
        return ModuleMetadata(
            name='__test_async_enable',
            display_name='Test Async Enable',
            description='Test module for S1',
            icon='box',
        )

    def register_routes(self):
        raise NotImplementedError

    async def system_on_enable(
        self, organization_id: str, db: Any, *, user: Any | None = None
    ) -> None:
        pass

    async def system_on_disable(self, organization_id: str, db: Any) -> None:
        pass

    async def on_enable(self, organization_id: str, context: Any) -> None:
        self.enable_hook_ran = True

    def on_disable(self, organization_id: str, context: Any) -> None:
        pass


class _FakeOrg:
    """Minimal stand-in for Organization with just what toggle_module needs.

    Onboarded, by default: these tests exercise hooks, not the pre-onboarding
    manual-toggle record the service writes while onboarding stands open.
    """

    def __init__(self) -> None:
        self.id = uuid4()
        self.enabled_modules: list[str] = []
        self.onboarding_completed = True
        self.pre_onboarding_manual_modules: list[str] | None = None


class _FakeDb:
    """Minimal async DB session mock — commit/rollback plus the locking read.

    ``toggle_module`` re-reads the organization ``FOR UPDATE`` before editing
    ``enabled_modules``, so it needs ``scalar``. The mock hands back the very
    object the test passed in: returning a copy would leave the assertions
    inspecting a row the service never touched, and returning ``None`` reads to
    the service as "organization gone" and raises.
    """

    def __init__(self, organization: object | None = None) -> None:
        self._organization = organization
        # The session's scratch dict: ``emit_transactional`` buffers the event
        # there until the commit.
        self.info: dict[str, Any] = {}

    def add(self, _entry: object) -> None:
        pass

    async def flush(self) -> None:
        pass

    async def commit(self) -> None:
        pass

    async def rollback(self) -> None:
        pass

    async def scalar(self, *_args: object, **_kwargs: object) -> object | None:
        return self._organization


@pytest.mark.unit
class TestToggleModuleAsyncHooks:
    """toggle_module must await coroutine hooks on both enable and disable paths."""

    async def test_async_on_disable_is_awaited(self):
        """The bug: disable-path ignored the coroutine returned by on_disable,
        so async hooks silently never ran."""
        module = _AsyncDisableModule()
        original = module_registry._modules.pop('__test_async_disable', None)
        module_registry._modules['__test_async_disable'] = module

        try:
            org = _FakeOrg()
            org.enabled_modules = ['__test_async_disable']
            user = UserContextDTO(
                id=uuid4(),
                organization_id=org.id,
                role='admin',
                email='admin@test.com',
            )

            await ModuleService.toggle_module(
                _FakeDb(org),
                org,
                '__test_async_disable',
                enabled=False,
                user=user,
            )

            assert module.disable_hook_ran, 'async on_disable hook was not awaited'
            assert '__test_async_disable' not in org.enabled_modules
        finally:
            if original is not None:
                module_registry._modules['__test_async_disable'] = original
            else:
                module_registry._modules.pop('__test_async_disable', None)

    async def test_async_on_enable_is_awaited(self):
        """Sanity check: the enable-path already handles async — this guards
        against regressions."""
        module = _AsyncEnableModule()
        original = module_registry._modules.pop('__test_async_enable', None)
        module_registry._modules['__test_async_enable'] = module

        try:
            org = _FakeOrg()
            org.enabled_modules = []
            user = UserContextDTO(
                id=uuid4(),
                organization_id=org.id,
                role='admin',
                email='admin@test.com',
            )

            await ModuleService.toggle_module(
                _FakeDb(org),
                org,
                '__test_async_enable',
                enabled=True,
                user=user,
            )

            assert module.enable_hook_ran, 'async on_enable hook was not awaited'
            assert '__test_async_enable' in org.enabled_modules
        finally:
            if original is not None:
                module_registry._modules['__test_async_enable'] = original
            else:
                module_registry._modules.pop('__test_async_enable', None)


class _FailingEnableModule(BaseModule):
    """Fake module whose system_on_enable raises."""

    @property
    def metadata(self) -> ModuleMetadata:
        return ModuleMetadata(
            name='__test_failing_enable',
            display_name='Test Failing Enable',
            description='Test module for S7',
            icon='box',
        )

    def register_routes(self):
        raise NotImplementedError

    async def system_on_enable(
        self, organization_id: str, db: Any, *, user: Any | None = None
    ) -> None:
        raise RuntimeError('seed failed')

    async def system_on_disable(self, organization_id: str, db: Any) -> None:
        pass

    def on_enable(self, organization_id: str, context: Any) -> None:
        pass

    def on_disable(self, organization_id: str, context: Any) -> None:
        pass


class _NoopModule(BaseModule):
    """Fake module whose hooks do nothing — the recording tests toggle it."""

    @property
    def metadata(self) -> ModuleMetadata:
        return ModuleMetadata(
            name='__test_noop',
            display_name='Test Noop',
            description='Test module for the manual-toggle record',
            icon='box',
        )

    def register_routes(self):
        raise NotImplementedError

    async def system_on_enable(
        self, organization_id: str, db: Any, *, user: Any | None = None
    ) -> None:
        pass

    async def system_on_disable(self, organization_id: str, db: Any) -> None:
        pass

    def on_enable(self, organization_id: str, context: Any) -> None:
        pass

    def on_disable(self, organization_id: str, context: Any) -> None:
        pass


@pytest.mark.unit
class TestTheManualToggleRecord:
    """A toggle while onboarding stands open is an explicit answer.

    Onboarding completes by overwriting ``enabled_modules`` with the chosen
    profile's set; without the record, a module the profile does not offer
    was dropped without its disable hook and without a word. The record is
    what onboarding reads to keep the choice.
    """

    def _open_org(self) -> _FakeOrg:
        org = _FakeOrg()
        org.onboarding_completed = False
        org.pre_onboarding_manual_modules = []
        return org

    @staticmethod
    def _user(org: _FakeOrg) -> UserContextDTO:
        return UserContextDTO(
            id=uuid4(),
            organization_id=org.id,
            role='admin',
            email='admin@test.com',
        )

    async def test_enabling_while_onboarding_is_open_records_the_module(self):
        module = _NoopModule()
        original = module_registry._modules.pop('__test_noop', None)
        module_registry._modules['__test_noop'] = module
        try:
            org = self._open_org()

            await ModuleService.toggle_module(
                _FakeDb(org), org, '__test_noop', enabled=True, user=self._user(org)
            )

            assert org.pre_onboarding_manual_modules == ['__test_noop']
        finally:
            if original is not None:
                module_registry._modules['__test_noop'] = original
            else:
                module_registry._modules.pop('__test_noop', None)

    async def test_toggling_back_off_takes_the_name_out_of_the_record(self):
        module = _NoopModule()
        original = module_registry._modules.pop('__test_noop', None)
        module_registry._modules['__test_noop'] = module
        try:
            org = self._open_org()
            org.enabled_modules = ['__test_noop']
            org.pre_onboarding_manual_modules = ['__test_noop']

            await ModuleService.toggle_module(
                _FakeDb(org), org, '__test_noop', enabled=False, user=self._user(org)
            )

            assert org.pre_onboarding_manual_modules == []
        finally:
            if original is not None:
                module_registry._modules['__test_noop'] = original
            else:
                module_registry._modules.pop('__test_noop', None)

    async def test_a_toggle_after_onboarding_touches_no_record(self):
        module = _NoopModule()
        original = module_registry._modules.pop('__test_noop', None)
        module_registry._modules['__test_noop'] = module
        try:
            org = _FakeOrg()  # onboarding_completed = True

            await ModuleService.toggle_module(
                _FakeDb(org), org, '__test_noop', enabled=True, user=self._user(org)
            )

            assert org.pre_onboarding_manual_modules is None
        finally:
            if original is not None:
                module_registry._modules['__test_noop'] = original
            else:
                module_registry._modules.pop('__test_noop', None)


@pytest.mark.unit
class TestToggleModuleUsesSharedExecutor:
    """toggle_module delegates to the lifecycle executor — hook errors
    surface as ModuleLifecycleError (one code path everywhere)."""

    async def test_hook_failure_raises_module_lifecycle_error(self):
        from app.services.module_lifecycle_service import ModuleLifecycleError

        module = _FailingEnableModule()
        original = module_registry._modules.pop('__test_failing_enable', None)
        module_registry._modules['__test_failing_enable'] = module

        try:
            org = _FakeOrg()
            user = UserContextDTO(
                id=uuid4(),
                organization_id=org.id,
                role='admin',
                email='admin@test.com',
            )

            with pytest.raises(ModuleLifecycleError) as exc_info:
                await ModuleService.toggle_module(
                    _FakeDb(org),
                    org,
                    '__test_failing_enable',
                    enabled=True,
                    user=user,
                )

            assert exc_info.value.module_name == '__test_failing_enable'
            assert exc_info.value.hook == 'system_on_enable'
        finally:
            if original is not None:
                module_registry._modules['__test_failing_enable'] = original
            else:
                module_registry._modules.pop('__test_failing_enable', None)
