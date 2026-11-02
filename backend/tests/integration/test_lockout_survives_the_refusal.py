"""The failed-login counter has to outlive the 401 that reports the failure.

``_record_failed_attempt_async`` writes the counter into the request session
and stops at a flush. The login route then raises a 401, and an exception
unwinds ``get_async_db`` before its post-yield commit — so the write the
lockout depends on was rolled back on every single wrong password. The
account lockout was, in effect, switched off for anyone coming through the
API; only the per-IP rate limit remained, and that one is answered by
rotating the source address.

The service-level tests could not see this: their fixture commits on its own.
These go through ``POST /auth/login`` and then read the row back, which is the
only place the difference shows.
"""

import pytest
from fastapi import status
from sqlalchemy.orm import Session

from app.models.user import User
from app.services.auth_service import MAX_FAILED_ATTEMPTS

WRONG = 'not-the-password'
RIGHT = 'testpassword123'


def _login(client, email: str, password: str):
    return client.post(
        '/api/v1/auth/login',
        data={'username': email, 'password': password},
    )


def _reread(db_session: Session, user_id) -> User:
    """Read the user back from the database, past any cached state."""
    db_session.expire_all()
    return db_session.get(User, user_id)


@pytest.mark.integration
class TestLockoutAccountingSurvivesThe401:
    def test_one_refusal_leaves_one_counted_attempt(
        self, client, db_session, test_user
    ):
        response = _login(client, test_user.email, WRONG)

        assert response.status_code == status.HTTP_401_UNAUTHORIZED
        assert _reread(db_session, test_user.id).failed_login_count == 1

    def test_every_refusal_advances_the_counter(self, client, db_session, test_user):
        for expected in range(1, 4):
            _login(client, test_user.email, WRONG)
            assert _reread(db_session, test_user.id).failed_login_count == expected

    def test_the_threshold_locks_the_account_and_the_right_password_stops_working(
        self, client, db_session, test_user
    ):
        for _ in range(MAX_FAILED_ATTEMPTS):
            assert (
                _login(client, test_user.email, WRONG).status_code
                == status.HTTP_401_UNAUTHORIZED
            )

        locked = _reread(db_session, test_user.id)
        assert locked.failed_login_count == MAX_FAILED_ATTEMPTS
        assert locked.locked_until is not None

        # The lock is what the counter was for: the correct password is now
        # refused too, and with the same 401 as a wrong one (no oracle).
        response = _login(client, test_user.email, RIGHT)
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_a_successful_login_still_clears_the_counter(
        self, client, db_session, test_user
    ):
        for _ in range(3):
            _login(client, test_user.email, WRONG)
        assert _reread(db_session, test_user.id).failed_login_count == 3

        assert _login(client, test_user.email, RIGHT).status_code == status.HTTP_200_OK

        cleared = _reread(db_session, test_user.id)
        assert cleared.failed_login_count == 0
        assert cleared.locked_until is None
