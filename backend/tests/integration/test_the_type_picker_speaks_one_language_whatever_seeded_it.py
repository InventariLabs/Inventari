"""The type picker speaks one language, whatever seeded its rows.

An organization collects storage-type rows from every profile and module it
has ever been on: the install-day seed, the equipment profile it tried for a
month, the equipment module's own declarations. Each row was written in the
language of the seeding that created it, and the picker showed the mixture —
six Polish rows beside six English ones in one dropdown, because the profile
switch only ever localized the types of the profile it was switching TO.

A row still bearing a literal this installation knows is not a customisation,
whichever profile's literal it is: a profile pick moves every such row into
the language of the reader picking, and keeps moving it — the first reader
does not lock the language, the next one moves the literals again. A name
that differs from every literal is the organization's, and no pick rewrites
it. See ``upsert_storage_types`` for the rule and its history.
"""

import pytest
from fastapi import status
from sqlalchemy import select

from app.models.storage_type import StorageType

#: The picker's visible seeded rows: install-day English literal → the Polish
#: name a Polish reader picks. Deliberately drawn from more than one profile
#: and from a module declaration — the mixture the picker used to show.
LITERAL_ROWS = {
    'SHELF': ('Shelf / Cabinet', 'Półka / szafa'),
    'STORAGE_ROOM': ('Storage Room', 'Pomieszczenie magazynowe'),
    'FREEZER': ('Freezer', 'Zamrażarka'),
    'FRIDGE': ('Fridge', 'Lodówka'),
    'PANTRY': ('Pantry', 'Spiżarnia'),
    'TOOL_ROOM': ('Tool Room', 'Narzędziownia'),
    'MAINTENANCE_BAY': ('Maintenance Bay', 'Stanowisko serwisowe'),
    'SERVER_ROOM': ('Server Room', 'Serwerownia'),
    'IT_STORAGE': ('IT Storage / Warehouse', 'Magazyn IT'),
}

RENAMED_FRIDGE = 'Lodówka babci'
OWN_CODE_NAME = 'Garaż'


def _names(db_session, organization_id) -> dict[str, str]:
    rows = (
        db_session.execute(
            select(StorageType).where(StorageType.organization_id == organization_id)
        )
        .scalars()
        .all()
    )
    return {row.type_code: row.name for row in rows}


def _install_day_rows(db_session, organization_id) -> None:
    """The organization as its installs left it: every profile's and module's
    rows in English, one row the organization renamed, one code no seeder
    knows."""
    for type_code, (english, _) in LITERAL_ROWS.items():
        row = db_session.scalars(
            select(StorageType).where(
                StorageType.type_code == type_code,
                StorageType.organization_id == organization_id,
            )
        ).first()
        if row is None:
            row = StorageType(
                type_code=type_code,
                is_system=True,
                organization_id=organization_id,
            )
            db_session.add(row)
        row.name = english
    db_session.add(
        StorageType(
            name=OWN_CODE_NAME,
            type_code='GARAGE',
            behavior_mode='STOCK',
            is_system=False,
            organization_id=organization_id,
        )
    )
    db_session.commit()


def _pick_profile(client, auth_headers, profile_id: str, lang: str):
    return client.post(
        '/api/v1/onboarding/switch-profile',
        json={'profile_id': profile_id, 'dry_run': False},
        headers={**auth_headers, 'Accept-Language': lang},
    )


@pytest.mark.integration
class TestAProfilePickSpeaksThePickersLanguage:
    async def test_rows_from_every_profile_join_the_readers_language(
        self, client, auth_headers, db_session, test_household
    ) -> None:
        test_household.active_profile_id = 'food_home'
        db_session.commit()
        _install_day_rows(db_session, test_household.id)
        # A name the organization typed itself, on a row the seed also knows.
        fridge = db_session.scalars(
            select(StorageType).where(
                StorageType.type_code == 'FRIDGE',
                StorageType.organization_id == test_household.id,
            )
        ).first()
        fridge.name = RENAMED_FRIDGE
        db_session.commit()

        # Re-picking the profile the organization is already on — the one
        # move that reaches rows the active profile's own seed never touches.
        response = _pick_profile(client, auth_headers, 'food_home', 'pl')

        assert response.status_code == status.HTTP_200_OK
        assert response.json()['applied'] is True

        db_session.expire_all()
        names = _names(db_session, test_household.id)
        for type_code, (_, polish) in LITERAL_ROWS.items():
            # FRIDGE is the one row the organization renamed — it asserts
            # below that the pick left its handwriting alone.
            if type_code == 'FRIDGE':
                continue
            assert names[type_code] == polish, (
                f'{type_code} still reads {names[type_code]!r} beside rows '
                f'the same picker already shows in Polish'
            )
        # The organization's own words and codes the seed does not know are
        # not literals, and no pick rewrites them.
        assert names['FRIDGE'] == RENAMED_FRIDGE
        assert names['GARAGE'] == OWN_CODE_NAME

    async def test_a_later_reader_moves_the_literals_again(
        self, client, auth_headers, db_session, test_household
    ) -> None:
        """The first reader does not freeze the language.

        A row still carrying a literal carries it in SOME reader's language,
        and the next pick moves it again — an organization that reads German
        after reading Polish is not sentenced to Polish names forever.
        """
        test_household.active_profile_id = 'food_home'
        db_session.commit()
        _install_day_rows(db_session, test_household.id)

        assert (
            _pick_profile(client, auth_headers, 'food_home', 'pl')
        ).status_code == status.HTTP_200_OK
        # The state the second reader finds: the literals stand in Polish,
        # so the English move below has something to move.
        db_session.expire_all()
        assert _names(db_session, test_household.id)['FREEZER'] == 'Zamrażarka'
        response = _pick_profile(client, auth_headers, 'food_home', 'en')

        assert response.status_code == status.HTTP_200_OK
        db_session.expire_all()
        names = _names(db_session, test_household.id)
        for type_code, (english, _) in LITERAL_ROWS.items():
            assert names[type_code] == english, (
                f'{type_code} stayed in the previous reader’s language'
            )
