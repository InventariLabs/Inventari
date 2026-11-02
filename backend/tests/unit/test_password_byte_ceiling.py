"""Unit tests for the password byte ceiling.

bcrypt 5 refuses passwords longer than 72 bytes instead of truncating them,
so every door that hashes or verifies a password must answer for that limit
itself: the shared policy refuses the value up front, verification treats it
like a wrong password, and hashing raises our own sentence instead of the
library's.
"""

import pytest

from app.schemas.user import validate_password_policy
from app.services.token_service import get_password_hash, verify_password

#: 73 bytes in UTF-8: 35 two-byte letters plus 'Aa1'. It passes every
#: character rule (8..128 chars, upper, lower, digit) and breaks only the
#: byte ceiling, which is the only thing these tests claim about it.
PAST_THE_CEILING = 'Ą' * 35 + 'Aa1'

#: Exactly 72 bytes — the ceiling itself must still be accepted.
AT_THE_CEILING = 'Ą' * 34 + 'Aa1x'


class TestPolicyByteCeiling:
    def test_the_policy_refuses_a_password_past_the_ceiling(self):
        with pytest.raises(ValueError, match='72 bytes'):
            validate_password_policy(PAST_THE_CEILING)

    def test_the_policy_refuses_it_with_a_sentence_of_ours(self):
        with pytest.raises(ValueError) as exc:
            validate_password_policy(PAST_THE_CEILING)
        message = str(exc.value)
        assert 'bcrypt' not in message.lower()
        assert 'truncate' not in message.lower()

    def test_the_ceiling_itself_is_accepted(self):
        assert validate_password_policy(AT_THE_CEILING) == AT_THE_CEILING


class TestVerifyPastTheCeiling:
    def test_verification_answers_false_instead_of_raising(self):
        hashed = get_password_hash('Password123')
        assert verify_password(PAST_THE_CEILING, hashed) is False

    def test_verification_still_pays_a_bcrypt_round(self, monkeypatch):
        """A past-the-ceiling password cannot match any stored hash, but the
        bcrypt round still happens: answering it faster than a wrong password
        would re-open the timing oracle the uniform 401 closed."""
        import bcrypt

        checked: list[tuple[bytes, bytes]] = []
        real_checkpw = bcrypt.checkpw

        def _counting_checkpw(password: bytes, hashed: bytes) -> bool:
            checked.append((password, hashed))
            return real_checkpw(password, hashed)

        monkeypatch.setattr(bcrypt, 'checkpw', _counting_checkpw)

        hashed = get_password_hash('Password123')
        assert verify_password(PAST_THE_CEILING, hashed) is False
        assert len(checked) == 1


class TestHashPastTheCeiling:
    def test_hashing_refuses_past_the_ceiling_with_our_sentence(self):
        with pytest.raises(ValueError) as exc:
            get_password_hash(PAST_THE_CEILING)
        message = str(exc.value)
        assert '72 bytes' in message
        assert 'bcrypt' not in message.lower()
        assert 'truncate' not in message.lower()

    def test_hashing_accepts_the_ceiling_itself(self):
        assert get_password_hash(AT_THE_CEILING).startswith('$2')
