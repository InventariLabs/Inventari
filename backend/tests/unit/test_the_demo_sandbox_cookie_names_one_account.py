"""The way back into a demo sandbox names its account, and nothing else passes.

The cookie is a signed token of its own type: an access or refresh token, a
forged string or a token naming something that is not an account must all
read as "no sandbox", which leads the visitor to a fresh one.
"""

import uuid
from datetime import UTC, datetime, timedelta

import jwt

from app.config import settings
from app.services.token_service import (
    create_access_token,
    create_demo_sandbox_token,
    read_demo_sandbox_subject,
)


def test_it_reads_back_the_account_it_was_made_for() -> None:
    account = uuid.uuid4()
    assert read_demo_sandbox_subject(create_demo_sandbox_token(account)) == account


def test_an_access_token_is_not_a_way_back() -> None:
    token = create_access_token(data={'sub': str(uuid.uuid4())})
    assert read_demo_sandbox_subject(token) is None


def test_a_string_that_is_no_token_is_not_a_way_back() -> None:
    assert read_demo_sandbox_subject('not-a-token') is None


def test_a_token_naming_no_account_is_not_a_way_back() -> None:
    token = jwt.encode(
        {
            'sub': 'not-an-id',
            'type': 'demo_sandbox',
            'exp': datetime.now(UTC) + timedelta(days=1),
        },
        settings.SECRET_KEY,
        algorithm=settings.ALGORITHM,
    )
    assert read_demo_sandbox_subject(token) is None
