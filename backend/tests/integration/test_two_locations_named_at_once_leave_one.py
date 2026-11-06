"""Two locations named at the same moment leave one, and the loser is told so.

``_check_name_unique`` reads the siblings and the insert follows it, with no
constraint behind the read: two requests that both read before either wrote
each found the name free, and each got a row of its own — two top-level
places with one name, which the application's own message says cannot exist.
The rule now lives in the database as well (a unique index per level), and the
violation answers the same ``409 STORAGE_CONFLICT`` the read does.

The race is forced rather than hoped for: the name check is held back until
both requests have passed it, so each one is certain to have seen a free
name. The requests travel through the endpoints — the rule is the route's.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from httpx import AsyncClient, Response
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.config import settings
from app.models.storage_location import StorageLocation
from app.models.user import User
from app.services.storage import _writes
from app.services.token_service import create_access_token

LOCATIONS = '/api/v1/locations'


def _auth(user: User) -> dict[str, str]:
    return {
        'Authorization': f'Bearer {create_access_token(data={"sub": str(user.id)})}'
    }


async def _rows_named(name: str, organization_id) -> int:
    engine = create_async_engine(
        settings.DATABASE_URL.replace('postgresql://', 'postgresql+asyncpg://', 1),
        echo=False,
        poolclass=NullPool,
    )
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as verify:
        count = await verify.scalar(
            select(func.count())
            .select_from(StorageLocation)
            .where(
                StorageLocation.organization_id == organization_id,
                StorageLocation.name == name,
            )
        )
    await engine.dispose()
    return count or 0


def _one_won(responses: list[Response], won: int) -> None:
    codes = sorted(r.status_code for r in responses)
    assert codes == sorted([won, 409]), [r.text for r in responses]
    loser = next(r for r in responses if r.status_code == 409)
    assert loser.json()['detail']['code'] == 'STORAGE_CONFLICT'


@pytest.mark.integration
@pytest.mark.asyncio
class TestSimultaneousNames:
    async def test_two_creates_of_one_name_leave_one_row(
        self,
        real_async_db_session: AsyncSession,
        real_async_client: AsyncClient,
        async_test_user: User,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        await real_async_db_session.commit()
        org_id = async_test_user.organization_id
        _hold_until_both_pass(monkeypatch)

        async def create() -> Response:
            return await real_async_client.post(
                LOCATIONS, json={'name': 'Cellar'}, headers=_auth(async_test_user)
            )

        responses = await asyncio.gather(create(), create())

        _one_won(list(responses), 201)
        assert await _rows_named('Cellar', org_id) == 1

    async def test_two_creates_under_one_parent_leave_one_row(
        self,
        real_async_db_session: AsyncSession,
        real_async_client: AsyncClient,
        async_test_user: User,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        await real_async_db_session.commit()
        org_id = async_test_user.organization_id
        parent = await _create(real_async_client, async_test_user, 'Warehouse')
        _hold_until_both_pass(monkeypatch)

        async def create() -> Response:
            return await real_async_client.post(
                LOCATIONS,
                json={'name': 'Shelf', 'parent_id': parent},
                headers=_auth(async_test_user),
            )

        responses = await asyncio.gather(create(), create())

        _one_won(list(responses), 201)
        assert await _rows_named('Shelf', org_id) == 1

    async def test_a_rename_racing_a_create_is_refused(
        self,
        real_async_db_session: AsyncSession,
        real_async_client: AsyncClient,
        async_test_user: User,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        await real_async_db_session.commit()
        org_id = async_test_user.organization_id
        other = await _create(real_async_client, async_test_user, 'Draft')
        _hold_until_both_pass(monkeypatch)

        async def create() -> Response:
            return await real_async_client.post(
                LOCATIONS, json={'name': 'Dock'}, headers=_auth(async_test_user)
            )

        async def rename() -> Response:
            return await real_async_client.put(
                f'{LOCATIONS}/{other}',
                json={'name': 'Dock'},
                headers=_auth(async_test_user),
            )

        created, renamed = await asyncio.gather(create(), rename())

        codes = {created.status_code, renamed.status_code}
        assert 409 in codes and codes & {200, 201}, (created.text, renamed.text)
        loser = created if created.status_code == 409 else renamed
        assert loser.json()['detail']['code'] == 'STORAGE_CONFLICT'
        assert await _rows_named('Dock', org_id) == 1

    async def test_two_renames_onto_one_name_leave_one_row(
        self,
        real_async_db_session: AsyncSession,
        real_async_client: AsyncClient,
        async_test_user: User,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        await real_async_db_session.commit()
        org_id = async_test_user.organization_id
        first = await _create(real_async_client, async_test_user, 'One')
        second = await _create(real_async_client, async_test_user, 'Two')
        _hold_until_both_pass(monkeypatch)

        async def rename(location_id: str) -> Response:
            return await real_async_client.put(
                f'{LOCATIONS}/{location_id}',
                json={'name': 'Gate'},
                headers=_auth(async_test_user),
            )

        responses = await asyncio.gather(rename(first), rename(second))

        _one_won(list(responses), 200)
        assert await _rows_named('Gate', org_id) == 1


def _hold_until_both_pass(monkeypatch: pytest.MonkeyPatch) -> None:
    """Hold each caller after its name check until the other has passed it."""
    original = _writes._check_name_unique
    barrier = asyncio.Barrier(2)

    async def held(*args: Any, **kwargs: Any) -> None:
        await original(*args, **kwargs)
        await barrier.wait()

    monkeypatch.setattr(_writes, '_check_name_unique', held)


async def _create(client: AsyncClient, user: User, name: str) -> str:
    """Create one location before the race starts and return its id."""
    response = await client.post(LOCATIONS, json={'name': name}, headers=_auth(user))
    assert response.status_code == 201, response.text
    return response.json()['id']
