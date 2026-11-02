"""Every short code this app can create is one its scanner recognises.

The two constraints were written apart and disagreed on one character
class: the creation schema invited digits in the prefix (its own field
description gave ``B12`` as the example) while the recognition pattern
took letters only. A label generated as ``B12-6UPR`` therefore sat in
``label_pool``, printed and stuck to a shelf, and the scanner answered
``SCAN_UNRECOGNIZED`` — "no product, label, place or document matches" —
about a row of that organization's own.

The relation between the two is deliberate and is the thing under test
here: recognition is a **superset** of creation. It has to be, because a
row in ``label_pool`` can predate any cap the schema carries today, and a
sticker already on a shelf must keep scanning.
"""

import re
from uuid import uuid4

import pytest
from fastapi import status
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.label_codes import (
    LABEL_CODE_PATTERN,
    LABEL_PREFIX_MAX_LENGTH,
)
from app.models.organization import Organization
from app.models.user import User
from app.schemas.label_pool import LabelPoolCreate
from app.services.auth_service import get_password_hash
from app.services.token_service import create_access_token


def _auth(user: User) -> dict:
    return {
        'Authorization': f'Bearer {create_access_token(data={"sub": str(user.id)})}'
    }


@pytest.fixture
async def code_org(real_async_db_session: AsyncSession) -> Organization:
    org = Organization(
        name='Label Codes Org',
        enabled_modules=['core', 'items', 'locations', 'categories', 'printing'],
    )
    real_async_db_session.add(org)
    await real_async_db_session.commit()
    await real_async_db_session.refresh(org)
    return org


@pytest.fixture
async def code_user(
    real_async_db_session: AsyncSession, code_org: Organization
) -> User:
    user = User(
        email=f'codes_{uuid4().hex[:8]}@test.com',
        hashed_password=get_password_hash('Password123'),
        full_name='Label Codes User',
        organization_id=code_org.id,
        role='admin',
        is_active=True,
    )
    real_async_db_session.add(user)
    await real_async_db_session.commit()
    await real_async_db_session.refresh(user)
    return user


@pytest.mark.unit
@pytest.mark.integration
class TestRecognitionCoversCreation:
    """The invariant, checked directly rather than through one example."""

    @pytest.mark.parametrize(
        'prefix',
        ['STM', 'B12', 'A', '123', 'Q1', 'ABCDE', '12345', 'a1b2c'],
    )
    def test_a_prefix_the_schema_accepts_yields_a_code_the_scanner_reads(
        self, prefix: str
    ) -> None:
        # The generator uppercases the prefix and appends four uppercase
        # alphanumerics, so this is the shape every generated code takes.
        accepted = LabelPoolCreate(count=1, prefix=prefix)
        code = f'{accepted.prefix.upper()}-6UPR'

        assert LABEL_CODE_PATTERN.match(code), (
            f'{code} is creatable but would not be recognised'
        )

    def test_the_longest_creatable_prefix_is_still_recognised(self) -> None:
        prefix = '9' * LABEL_PREFIX_MAX_LENGTH
        LabelPoolCreate(count=1, prefix=prefix)

        assert LABEL_CODE_PATTERN.match(f'{prefix}-ABCD')

    def test_recognition_reaches_beyond_what_creation_offers(self) -> None:
        # Deliberate, and the reason the two numbers may differ: a row can
        # predate the cap the schema carries today, and a sticker already
        # on a shelf has to keep scanning.
        long_prefix = 'LEGACY123456'
        with pytest.raises(ValidationError):
            LabelPoolCreate(count=1, prefix=long_prefix)

        assert LABEL_CODE_PATTERN.match(f'{long_prefix}-ABCD')

    def test_a_barcode_is_still_not_a_label(self) -> None:
        # The hyphen is what keeps the two apart; widening the prefix to
        # digits must not make a plain EAN look like a label code.
        assert not LABEL_CODE_PATTERN.match('5901234123457')
        assert not re.match(r'^\d{8,14}$', 'B12-6UPR')


@pytest.mark.integration
class TestADigitInThePrefixScans:
    async def test_generated_then_scanned(
        self, real_async_client, code_user, code_org
    ) -> None:
        generated = await real_async_client.post(
            '/api/v1/labels/pool/generate',
            json={'count': 2, 'prefix': 'B12'},
            headers=_auth(code_user),
        )
        assert generated.status_code == status.HTTP_201_CREATED
        codes = [row['short_code'] for row in generated.json()]
        assert codes and all(code.startswith('B12-') for code in codes)

        scanned = await real_async_client.get(
            f'/api/v1/labels/scan/{codes[0]}', headers=_auth(code_user)
        )

        assert scanned.status_code == status.HTTP_200_OK, scanned.text
        body = scanned.json()
        assert body['status'] == 'unassigned'
        assert body['action'] == 'show_quick_add'
        assert body['label_code'] == codes[0]

    async def test_the_letters_only_control_still_scans(
        self, real_async_client, code_user, code_org
    ) -> None:
        generated = await real_async_client.post(
            '/api/v1/labels/pool/generate',
            json={'count': 1, 'prefix': 'STM'},
            headers=_auth(code_user),
        )
        assert generated.status_code == status.HTTP_201_CREATED
        code = generated.json()[0]['short_code']

        scanned = await real_async_client.get(
            f'/api/v1/labels/scan/{code}', headers=_auth(code_user)
        )

        assert scanned.status_code == status.HTTP_200_OK
        assert scanned.json()['action'] == 'show_quick_add'
