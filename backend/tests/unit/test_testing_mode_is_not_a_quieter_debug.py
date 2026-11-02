"""TESTING=true with DEBUG=false is refused at startup.

TESTING is not a quieter DEBUG. It turns on the password-reset dev-token
response (a valid reset token handed back for any address that exists), makes
the token blacklist fail open, and accepts a SECRET_KEY from the known-weak
list. With DEBUG off, the deployment looks production-shaped from every other
angle and nothing says those three are gone.
"""

from __future__ import annotations

import pytest

from app.config import check_testing_mode_is_deliberate

pytestmark = pytest.mark.unit


def _check(**kwargs: bool) -> None:
    check_testing_mode_is_deliberate(
        **{'debug': False, 'testing': False, 'ack_unsafe': False, **kwargs}
    )


class TestTheCombinationIsRefused:
    def test_testing_without_debug_refuses_to_start(self) -> None:
        with pytest.raises(ValueError, match='TESTING=true with DEBUG=false'):
            _check(testing=True)

    def test_the_message_names_the_way_out(self) -> None:
        with pytest.raises(ValueError, match='TESTING_ACK_UNSAFE'):
            _check(testing=True)


class TestEveryOtherCombinationStarts:
    def test_a_developer_machine_is_fine(self) -> None:
        _check(debug=True, testing=True)

    def test_a_plain_deployment_is_fine(self) -> None:
        _check()

    def test_an_acknowledged_test_stack_is_fine(self) -> None:
        _check(testing=True, ack_unsafe=True)
