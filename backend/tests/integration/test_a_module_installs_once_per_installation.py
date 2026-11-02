"""Four workers booting together installed a module four times.

The registry read ``module_installations``, and when it found nothing it
ran the module's install hook -- migrations and all -- and only then wrote
the row. The insert was guarded (a savepoint and an IntegrityError branch
whose own log message says "already registered by another worker"), but a
unique index protects the row, not the work done before it. Every worker
that reached the read before anybody wrote ran the hook.

So the order is the fix: claim the row first, and let the index decide who
does the work. The claim and the hook sit in one savepoint, so a hook that
fails still leaves no installation behind and the next boot tries again.
"""

from __future__ import annotations

import asyncio
import uuid

import pytest
from fastapi import APIRouter
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.config import settings
from app.core._base_module import BaseModule
from app.core._module_declarations import ModuleMetadata
from app.core.context import ModuleContext
from app.core.module_registry import module_registry
from app.models.module_installation import ModuleInstallation

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


def _async_test_url() -> str:
    return settings.DATABASE_URL.replace('postgresql://', 'postgresql+asyncpg://', 1)


class _CountingModule(BaseModule):
    """A module whose install hook says how many times it was run."""

    def __init__(self, name: str, version: str = '1.0.0') -> None:
        self._name = name
        self._version = version
        self.installs = 0
        self.upgrades: list[str] = []
        self.async_upgrades: list[str] = []

    @property
    def metadata(self) -> ModuleMetadata:
        return ModuleMetadata(
            name=self._name,
            version=self._version,
            display_name='Counting',
            description='Counts its own installations',
            icon='Box',
        )

    def register_routes(self) -> APIRouter:
        return APIRouter()

    async def on_install_async(self, context: ModuleContext) -> None:
        # Long enough that a second worker reaching the read would be inside
        # the hook at the same time, which is the whole point.
        self.installs += 1
        await asyncio.sleep(0.05)

    def on_upgrade(self, old_version: str, context: ModuleContext) -> None:
        # Sync, like the base class's: this runs inside the async boot, so
        # sleeping is not an option -- the row lock is what serialises it.
        self.upgrades.append(old_version)

    async def on_upgrade_async(self, old_version: str, context: ModuleContext) -> None:
        await asyncio.sleep(0)
        self.async_upgrades.append(old_version)


async def _boot(module: _CountingModule, workers: int) -> None:
    """Start the module in *workers* processes at once."""
    engine = create_async_engine(_async_test_url(), echo=False, poolclass=NullPool)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def worker() -> None:
        async with factory() as session:
            await module_registry.check_module_version_async(module, session)
            await session.commit()

    try:
        await asyncio.gather(*(worker() for _ in range(workers)))
    finally:
        await engine.dispose()


@pytest.fixture
def module() -> _CountingModule:
    return _CountingModule(f'counting_{uuid.uuid4().hex[:8]}')


class TestAParallelBoot:
    async def test_the_install_hook_runs_once(
        self, module: _CountingModule, real_async_db_session: AsyncSession
    ) -> None:
        await _boot(module, workers=4)
        assert module.installs == 1

    async def test_one_installation_is_recorded(
        self, module: _CountingModule, real_async_db_session: AsyncSession
    ) -> None:
        await _boot(module, workers=4)

        rows = await real_async_db_session.scalar(
            select(func.count())
            .select_from(ModuleInstallation)
            .where(ModuleInstallation.module_name == module.metadata.name)
        )
        assert rows == 1


class TestASecondBoot:
    async def test_an_installed_module_is_not_installed_again(
        self, module: _CountingModule, real_async_db_session: AsyncSession
    ) -> None:
        await _boot(module, workers=1)
        await _boot(module, workers=1)
        assert module.installs == 1


class TestAHookThatFails:
    async def test_it_leaves_no_installation_behind(
        self, module: _CountingModule, real_async_db_session: AsyncSession
    ) -> None:
        """Otherwise the next boot would call the module installed."""

        async def explode(context: ModuleContext) -> None:
            module.installs += 1
            raise RuntimeError('migration failed')

        module.on_install_async = explode  # type: ignore[method-assign]

        with pytest.raises(RuntimeError):
            await _boot(module, workers=1)

        rows = await real_async_db_session.scalar(
            select(func.count())
            .select_from(ModuleInstallation)
            .where(ModuleInstallation.module_name == module.metadata.name)
        )
        assert rows == 0


class TestAVersionBump:
    """The upgrade hook is a hook too, and it ran once per worker.

    ``on_upgrade`` was called by whichever workers read the row before any
    of them wrote the new version -- all four, on a normal boot. The hook
    exists for what a migration cannot express, which is usually rewriting
    stored data, and rewriting it four times is not the same as once.
    """

    async def test_the_upgrade_hook_runs_once(
        self, module: _CountingModule, real_async_db_session: AsyncSession
    ) -> None:
        await _boot(module, workers=1)

        bumped = _CountingModule(module.metadata.name, version='2.0.0')
        await _boot(bumped, workers=4)

        assert bumped.upgrades == ['1.0.0']

    async def test_the_async_upgrade_hook_is_awaited_once(
        self, module: _CountingModule, real_async_db_session: AsyncSession
    ) -> None:
        """The registry awaits it, and the row lock keeps it to one worker.

        A hook that returns a coroutine nobody awaits appends nothing, so
        this is also the test that notices a firing-and-forgetting registry.
        """
        await _boot(module, workers=1)

        bumped = _CountingModule(module.metadata.name, version='2.0.0')
        await _boot(bumped, workers=4)

        assert bumped.async_upgrades == ['1.0.0']

    async def test_the_recorded_version_follows(
        self, module: _CountingModule, real_async_db_session: AsyncSession
    ) -> None:
        await _boot(module, workers=1)
        await _boot(_CountingModule(module.metadata.name, version='2.0.0'), workers=1)

        record = await real_async_db_session.scalar(
            select(ModuleInstallation).where(
                ModuleInstallation.module_name == module.metadata.name
            )
        )
        assert record is not None
        await real_async_db_session.refresh(record)
        assert record.installed_version == '2.0.0'
