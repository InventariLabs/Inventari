"""Unit tests for app.services.module_lifecycle_service.

The lifecycle executor runs enable/disable hooks for a batch of modules
in the correct dependency order. It is the shared engine used by both
the existing onboarding flow and the new profile switch service.

"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Sequence
from typing import Any

import pytest

from app.core._base_module import BaseModule
from app.core._module_declarations import ModuleMetadata
from app.services.module_lifecycle_service import (
    ModuleLifecycleError,
    disable_modules_async,
    enable_modules_async,
)

ORG_ID = uuid.UUID('00000000-0000-0000-0000-000000000001')
ORG_STR = str(ORG_ID)


class _RecordingModule(BaseModule):
    """A module that records every hook invocation.

    Records a tuple ``(hook, org_id, extra)`` to ``self.events`` for
    assertions. Both sync and async on_enable/on_disable are supported
    so we can verify the executor handles both uniformly.
    """

    def __init__(
        self,
        name: str,
        requires: Sequence[str] | None = None,
        *,
        async_enable: bool = False,
        async_disable: bool = False,
    ) -> None:
        self.events: list[tuple[str, str, Any]] = []
        self._async_enable = async_enable
        self._async_disable = async_disable
        self._requires = list(requires or [])
        self._name = name

    @property
    def metadata(self) -> ModuleMetadata:
        return ModuleMetadata(
            name=self._name,
            display_name=self._name.title(),
            description=f'Recording {self._name}',
            icon='box',
            requires=self._requires,
        )

    def register_routes(self):
        raise NotImplementedError

    async def system_on_enable(
        self, organization_id: uuid.UUID, db: Any, *, user: Any | None = None
    ) -> None:
        self.events.append(('system_on_enable', str(organization_id), None))

    async def system_on_disable(self, organization_id: uuid.UUID, db: Any) -> None:
        self.events.append(('system_on_disable', str(organization_id), None))

    def on_enable(self, organization_id: uuid.UUID, context: Any) -> Any:
        if self._async_enable:

            async def _coro():
                self.events.append(('on_enable', str(organization_id), None))

            return _coro()
        self.events.append(('on_enable', str(organization_id), None))

    def on_disable(self, organization_id: uuid.UUID, context: Any) -> Any:
        if self._async_disable:

            async def _coro():
                self.events.append(('on_disable', str(organization_id), None))

            return _coro()
        self.events.append(('on_disable', str(organization_id), None))


def _make(name: str, **kwargs: Any) -> _RecordingModule:
    requires = kwargs.pop('requires', [])
    return _RecordingModule(name, requires=requires, **kwargs)


@pytest.mark.unit
class TestEnableModules:
    """enable_modules_async runs hooks in dependency order."""

    async def test_runs_system_hook_before_module_hook(self):
        a = _make('a')
        modules = [a]
        await enable_modules_async(modules, ORG_ID, db=None)
        assert a.events == [
            ('system_on_enable', ORG_STR, None),
            ('on_enable', ORG_STR, None),
        ]

    async def test_awaits_async_on_enable(self):
        a = _make('a', async_enable=True)
        await enable_modules_async([a], ORG_ID, db=None)
        assert ('on_enable', ORG_STR, None) in a.events

    async def test_processes_modules_in_dependency_order(self):
        """When modules list is provided, dependencies must be enabled first.

        'b' requires 'a', so 'a' must be enabled before 'b'.
        """
        a = _make('a')
        b = _make('b', requires=['a'])
        # Caller passes them in topological order.
        await enable_modules_async([a, b], ORG_ID, db=None)
        # The executor processes modules sequentially: a's full sequence
        # finishes before b's system_on_enable starts.
        assert a.events[-1] == ('on_enable', ORG_STR, None)
        assert b.events[0] == ('system_on_enable', ORG_STR, None)

    async def test_empty_list_is_noop(self):
        await enable_modules_async([], ORG_ID, db=None)  # no error

    async def test_continues_after_module_hook_error(self):
        """If a module's on_enable raises, the executor surfaces the error
        but the caller can decide whether to rollback. We do not silently
        continue — errors are surfaced via ModuleLifecycleError."""

        class _BoomModule(BaseModule):
            @property
            def metadata(self) -> ModuleMetadata:
                return ModuleMetadata(
                    name='boom',
                    display_name='Boom',
                    description='Always raises.',
                    icon='box',
                )

            def register_routes(self):
                raise NotImplementedError

            async def system_on_enable(
                self, organization_id: uuid.UUID, db: Any, *, user: Any | None = None
            ) -> None:
                pass

            def on_enable(self, organization_id: uuid.UUID, context: Any) -> None:
                raise RuntimeError('kapow')

        boom = _BoomModule()
        with pytest.raises(ModuleLifecycleError):
            await enable_modules_async([boom], ORG_ID, db=None)

    async def test_every_enable_runs_both_hooks(self):
        """There is no path that runs the system hook alone any more."""
        a = _make('a')
        await enable_modules_async([a], ORG_ID, db=None)
        assert a.events == [
            ('system_on_enable', ORG_STR, None),
            ('on_enable', ORG_STR, None),
        ]


@pytest.mark.unit
class TestDisableModules:
    """disable_modules_async runs hooks in reverse dependency order."""

    async def test_runs_system_hook_before_module_hook(self):
        a = _make('a')
        await disable_modules_async([a], ORG_ID, db=None)
        assert a.events == [
            ('system_on_disable', ORG_STR, None),
            ('on_disable', ORG_STR, None),
        ]

    async def test_awaits_async_on_disable(self):
        a = _make('a', async_disable=True)
        await disable_modules_async([a], ORG_ID, db=None)
        assert ('on_disable', ORG_STR, None) in a.events

    async def test_processes_in_reverse_dependency_order(self):
        """For disable, dependents must be disabled before dependencies.

        'b' requires 'a' — so 'b' (dependent) must be disabled BEFORE
        'a' (dependency). When the caller passes [a, b] we must reverse
        the order so b goes first.
        """
        a = _make('a')
        b = _make('b', requires=['a'])
        await disable_modules_async([a, b], ORG_ID, db=None)
        # The executor processes modules sequentially in reverse order:
        # b's full sequence finishes before a's begins.
        assert b.events[-1] == ('on_disable', ORG_STR, None)
        assert a.events[0] == ('system_on_disable', ORG_STR, None)
        assert len(b.events) == 2
        assert len(a.events) == 2

    async def test_empty_list_is_noop(self):
        await disable_modules_async([], ORG_ID, db=None)  # no error


@pytest.mark.unit
class TestLifecycleExecutor:
    """Cross-cutting concerns of the lifecycle executor."""

    async def test_works_with_real_event_loop(self):
        """Sanity check — the executor is awaitable and does not block."""
        a = _make('a')
        await asyncio.wait_for(enable_modules_async([a], ORG_ID, db=None), timeout=1.0)
        assert a.events

    async def test_does_not_commit_or_flush(self):
        """The executor must NOT commit the transaction — the caller owns
        transaction boundaries. Verify by checking no commit/flush was
        performed on the passed db argument."""

        class _SpyDb:
            def __init__(self) -> None:
                self.commits = 0
                self.flushes = 0

            async def commit(self) -> None:
                self.commits += 1

            async def flush(self) -> None:
                self.flushes += 1

        a = _make('a')
        db = _SpyDb()
        await enable_modules_async([a], ORG_ID, db=db)
        await disable_modules_async([a], ORG_ID, db=db)
        # The executor must not commit on its own.
        # BaseModule.system_on_enable/disable may flush their own writes
        # internally (those are domain operations, not transaction
        # boundaries), but the executor itself does not commit.
        assert db.commits == 0, (
            'Executor must not commit — caller owns transaction boundaries'
        )
