"""A shelf called "Shelf 1" is not an address until you say which rack.

Location names are unique among siblings and nowhere else, so the same word
sits under every rack in the building — and since the depth limit was lifted
(ADR-018), naming places that way is the ordinary thing to do rather than an
edge case. The import took the first row it found, so one spreadsheet could
file a whole delivery onto the wrong shelf and say nothing at all.

The interface writes a location's address with `›` between the steps, so
that is what the import reads. A partial path is enough as long as it picks
out one place; a word that picks out several is refused, with the candidates
spelled out beside the row it came from.
"""

from __future__ import annotations

import pandas as pd
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.file_import import resolve_storage_location_async
from app.i18n.service import set_current_lang
from app.models.storage_location import StorageLocation
from app.models.storage_type import StorageType
from app.models.user import User

pytestmark = pytest.mark.integration

MAPPING = {'location': 'where'}


async def _place(
    db: AsyncSession,
    user: User,
    storage_type: StorageType,
    name: str,
    parent: StorageLocation | None = None,
) -> StorageLocation:
    location = StorageLocation(
        organization_id=user.organization_id,
        created_by=user.id,
        storage_type_id=storage_type.id,
        name=name,
        parent_id=parent.id if parent else None,
    )
    db.add(location)
    await db.flush()
    await db.refresh(location)
    return location


async def _resolve(db: AsyncSession, user: User, text: str) -> str | None:
    return await resolve_storage_location_async(
        db,
        user.organization_id,
        pd.Series({'where': text}),
        MAPPING,
        None,
        {},
    )


@pytest.fixture
async def two_shelves_with_one_name(
    real_async_db_session: AsyncSession,
    async_test_user: User,
    async_test_storage_type: StorageType,
) -> tuple[StorageLocation, StorageLocation]:
    """`Garage › Rack A › Shelf 1` and `Garage › Rack B › Shelf 1`."""
    db, user, st = real_async_db_session, async_test_user, async_test_storage_type
    garage = await _place(db, user, st, 'Garage')
    rack_a = await _place(db, user, st, 'Rack A', garage)
    rack_b = await _place(db, user, st, 'Rack B', garage)
    return (
        await _place(db, user, st, 'Shelf 1', rack_a),
        await _place(db, user, st, 'Shelf 1', rack_b),
    )


class TestAPathNamesOnePlace:
    async def test_a_full_path_resolves(
        self,
        real_async_db_session: AsyncSession,
        async_test_user: User,
        two_shelves_with_one_name: tuple[StorageLocation, StorageLocation],
    ) -> None:
        under_a, _under_b = two_shelves_with_one_name

        resolved = await _resolve(
            real_async_db_session, async_test_user, 'Garage › Rack A › Shelf 1'
        )

        assert resolved == str(under_a.id)

    async def test_a_partial_path_is_enough_when_it_picks_out_one(
        self,
        real_async_db_session: AsyncSession,
        async_test_user: User,
        two_shelves_with_one_name: tuple[StorageLocation, StorageLocation],
    ) -> None:
        """Nobody should have to write the building to name a shelf."""
        _under_a, under_b = two_shelves_with_one_name

        resolved = await _resolve(
            real_async_db_session, async_test_user, 'Rack B › Shelf 1'
        )

        assert resolved == str(under_b.id)

    async def test_a_plain_angle_bracket_works_too(
        self,
        real_async_db_session: AsyncSession,
        async_test_user: User,
        two_shelves_with_one_name: tuple[StorageLocation, StorageLocation],
    ) -> None:
        """The typographic character does not survive every keyboard."""
        under_a, _under_b = two_shelves_with_one_name

        resolved = await _resolve(
            real_async_db_session, async_test_user, 'Rack A > Shelf 1'
        )

        assert resolved == str(under_a.id)


class TestAnAmbiguousWordIsRefused:
    async def test_the_row_is_refused_and_the_candidates_named(
        self,
        real_async_db_session: AsyncSession,
        async_test_user: User,
        two_shelves_with_one_name: tuple[StorageLocation, StorageLocation],
    ) -> None:
        with pytest.raises(ValueError) as refusal:
            await _resolve(real_async_db_session, async_test_user, 'Shelf 1')

        message = str(refusal.value)
        assert 'Garage › Rack A › Shelf 1' in message
        assert 'Garage › Rack B › Shelf 1' in message


class TestTheRefusalSpeaksTheReadersLanguage:
    async def test_a_polish_session_reads_the_candidates_in_polish(
        self,
        real_async_db_session: AsyncSession,
        async_test_user: User,
        two_shelves_with_one_name: tuple[StorageLocation, StorageLocation],
    ) -> None:
        set_current_lang('pl')
        try:
            with pytest.raises(ValueError) as refusal:
                await _resolve(real_async_db_session, async_test_user, 'Shelf 1')
        finally:
            set_current_lang('en')

        assert str(refusal.value).startswith('„Shelf 1” pasuje do 2 miejsc')
        assert 'Garage › Rack A › Shelf 1' in str(refusal.value)


class TestTheOrdinaryCaseStaysOrdinary:
    async def test_a_name_that_picks_out_one_place_still_works(
        self,
        real_async_db_session: AsyncSession,
        async_test_user: User,
        async_test_storage_type: StorageType,
    ) -> None:
        cellar = await _place(
            real_async_db_session, async_test_user, async_test_storage_type, 'Cellar'
        )

        resolved = await _resolve(real_async_db_session, async_test_user, 'cellar')

        assert resolved == str(cellar.id)

    async def test_a_name_nobody_has_resolves_to_nothing(
        self,
        real_async_db_session: AsyncSession,
        async_test_user: User,
        async_test_storage_location: StorageLocation,
    ) -> None:
        assert await _resolve(real_async_db_session, async_test_user, 'Nowhere') is None


class TestEveryPlaceIsLookedAt:
    async def test_a_location_past_the_first_page_is_still_found(
        self,
        real_async_db_session: AsyncSession,
        async_test_user: User,
        async_test_storage_type: StorageType,
    ) -> None:
        """The listing pages at 200 by default.

        Reading only the first page meant an organization with more places
        than that had its later ones answer "no such location" — a silent
        wrong answer of the same family as the one above.
        """
        db, user, st = real_async_db_session, async_test_user, async_test_storage_type
        for number in range(210):
            db.add(
                StorageLocation(
                    organization_id=user.organization_id,
                    created_by=user.id,
                    storage_type_id=st.id,
                    name=f'Bay {number:03d}',
                )
            )
        await db.flush()

        resolved = await _resolve(real_async_db_session, async_test_user, 'Bay 209')

        assert resolved is not None
