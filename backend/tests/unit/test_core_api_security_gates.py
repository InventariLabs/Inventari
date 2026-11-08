"""Unit tests for the security gates (legality audit 2026-08-03).

What we assert:

- ``CoreSecretsAPI.encrypt_for_module`` / ``decrypt_for_module`` — the
  module tag is enforced: a module cannot decrypt another module's
  secret (``PermissionError``). Legacy untagged ciphertexts (from the
  deprecated ``encrypt``) stay decryptable for backward compatibility.
- ``CoreFileStorageAPI.*_for_org`` — the ``<org>/<module>/`` prefix is
  always enforced, regardless of caller-supplied path tricks.
- ``CoreAdminAPI`` — all three methods require ``is_superuser=True``
  (``PermissionError`` otherwise); a superuser caller passes the gate.
- ``CoreAIUsageAPI.get_global_stats_async`` — same superuser gate.

Note: the isolation is cooperative — the caller declares its own
``module_name``, so the gate stops accidental cross-module access, not
a malicious in-process module. Documented in MODULES_GUIDE.md.
"""

from __future__ import annotations

import uuid
from io import BytesIO
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.contracts import UserContextDTO


def _user(*, is_superuser: bool) -> UserContextDTO:
    return UserContextDTO(id=uuid.uuid4(), is_superuser=is_superuser)


async def test_admin_gates_speak_the_request_language() -> None:
    from app.core.public_api.admin import CoreAdminAPI
    from app.core.public_api.ai_usage import CoreAIUsageAPI
    from app.i18n.service import get_current_lang, set_current_lang

    previous = get_current_lang()
    set_current_lang('pl')
    try:
        for call in (
            CoreAdminAPI().get_global_stats_async,
            CoreAIUsageAPI().get_global_stats_async,
        ):
            with pytest.raises(
                PermissionError, match='Ta czynność wymaga uprawnień superużytkownika'
            ):
                await call(AsyncMock(), user=_user(is_superuser=False))
    finally:
        set_current_lang(previous)


# --------------------------- secrets namespace -------------------------------


class TestSecretsNamespace:
    def test_round_trip_same_module(self):
        from app.core.public_api.secrets import CoreSecretsAPI

        api = CoreSecretsAPI()
        encrypted = api.encrypt_for_module('mod_a', 'super-secret')
        assert encrypted.startswith('enc:mod1:')
        assert api.decrypt_for_module('mod_a', encrypted) == 'super-secret'

    def test_cross_module_decrypt_raises_permission_error(self):
        from app.core.public_api.secrets import CoreSecretsAPI

        api = CoreSecretsAPI()
        encrypted = api.encrypt_for_module('mod_a', 'super-secret')
        with pytest.raises(PermissionError, match='mod_b'):
            api.decrypt_for_module('mod_b', encrypted)

    def test_the_owner_is_bound_inside_the_cipher_not_beside_it(self):
        """Rewriting the owner in the stored text must be a refusal, not
        another module's read. The owner used to be a text suffix the
        cipher never saw, so a reader answered whoever claimed the tail
        of the string — ``cipher`` + ``':mod_b'`` read module A's
        secret as module B's."""
        from app.core.public_api.secrets import CoreSecretsAPI

        api = CoreSecretsAPI()
        encrypted = api.encrypt_for_module('mod_a', 'super-secret')
        forged = f'{encrypted}:mod_b'
        with pytest.raises(PermissionError, match='mod_b'):
            api.decrypt_for_module('mod_b', forged)

    def test_a_tampered_body_is_refused_not_silently_emptied(self):
        """Editing the stored ciphertext is a decryption failure. The old
        graceful-empty path would have answered an edited value with an
        empty string, indistinguishable from a cleared secret."""
        from app.core.public_api.secrets import CoreSecretsAPI

        api = CoreSecretsAPI()
        encrypted = api.encrypt_for_module('mod_a', 'super-secret')
        _, _mark, body = encrypted.split(':', 2)
        flipped = ('A' if body[0] != 'A' else 'B') + body[1:]
        with pytest.raises(PermissionError):
            api.decrypt_for_module('mod_a', f'enc:mod1:{flipped}')

    def test_swapped_values_refuse_across_owners(self):
        from app.core.public_api.secrets import CoreSecretsAPI

        api = CoreSecretsAPI()
        for_a = api.encrypt_for_module('mod_a', 'a-secret')
        for_b = api.encrypt_for_module('mod_b', 'b-secret')
        assert api.decrypt_for_module('mod_a', for_a) == 'a-secret'
        assert api.decrypt_for_module('mod_b', for_b) == 'b-secret'
        with pytest.raises(PermissionError):
            api.decrypt_for_module('mod_a', for_b)
        with pytest.raises(PermissionError):
            api.decrypt_for_module('mod_b', for_a)

    def test_legacy_tagged_values_are_read_without_verification(self):
        """Values written by the retired suffix format decrypt for ANY
        module: the suffix was cosmetic, so binding it was never real.
        The shape stays readable for data already on disk — the docstring
        says so, and re-saving through ``encrypt_for_module`` binds it."""
        from app.core.public_api.secrets import CoreSecretsAPI
        from app.services.crypto_service import _get_fernet

        api = CoreSecretsAPI()
        cipher = _get_fernet().encrypt(b'legacy-bound').decode()
        legacy = f'enc:{cipher}:mod_a'
        assert api.decrypt_for_module('mod_a', legacy) == 'legacy-bound'
        assert api.decrypt_for_module('mod_b', legacy) == 'legacy-bound'

    def test_a_stored_cleartext_passes_through(self):
        """Plaintext values predate encryption entirely; app-wide by
        design, they read back as-is."""
        from app.core.public_api.secrets import CoreSecretsAPI

        api = CoreSecretsAPI()
        assert api.decrypt_for_module('mod_a', 'in-cleartext') == 'in-cleartext'

    def test_a_module_name_cannot_carry_a_colon(self):
        """A colon would make the owner ambiguous in the legacy formats
        the reader must keep understanding."""
        from app.core.exceptions import ContractViolationError
        from app.core.public_api.secrets import CoreSecretsAPI

        api = CoreSecretsAPI()
        # A caller bug, not a refusal a reader is shown: it is not a ValueError,
        # which the 400 handler would put on screen.
        with pytest.raises(ContractViolationError, match='colon'):
            api.encrypt_for_module('mod:a', 'secret')

    def test_legacy_ciphertext_without_tag_still_decryptable(self):
        """Backward compatibility: secrets encrypted with the unbound
        ``encrypt`` (no module tag) predate namespace isolation and must
        remain readable — they were app-wide by design.

        The method that wrote them was removed without a window; the
        ciphertext it wrote was not, so this test builds the value the
        way that method did — through the crypto service directly —
        rather than through a facade that no longer offers it. The
        guarantee is about what is in the database, not about a method.
        """
        from app.core.public_api.secrets import CoreSecretsAPI
        from app.services.crypto_service import encrypt_value

        api = CoreSecretsAPI()
        legacy = encrypt_value('legacy-secret')
        assert api.decrypt_for_module('mod_a', legacy) == 'legacy-secret'


# --------------------------- file storage org scoping ------------------------


class TestFileStorageOrgScoping:
    def test_scoped_path_strips_leading_slash(self):
        from app.core.public_api.file_storage import CoreFileStorageAPI

        org = uuid.uuid4()
        assert (
            CoreFileStorageAPI._scoped_path(org, 'mod_a', '/labels/x.png')
            == f'{org}/mod_a/labels/x.png'
        )

    async def test_save_for_org_enforces_prefix(self):
        from app.core.public_api import file_storage as fs_mod

        org = uuid.uuid4()
        service = MagicMock()
        service.save = AsyncMock()
        with patch.object(fs_mod, 'FileStorageService', return_value=service):
            api = fs_mod.CoreFileStorageAPI()
            path = await api.save_for_org_async(org, 'mod_a', 'labels/x.png', b'data')

        assert path == f'{org}/mod_a/labels/x.png'
        assert service.save.call_args.args[0] == path

    async def test_get_for_org_reads_scoped_path(self):
        from app.core.public_api import file_storage as fs_mod

        org = uuid.uuid4()
        service = MagicMock()
        service.get = AsyncMock(return_value=BytesIO(b'data'))
        with patch.object(fs_mod, 'FileStorageService', return_value=service):
            api = fs_mod.CoreFileStorageAPI()
            content = await api.get_for_org_async(org, 'mod_a', 'labels/x.png')

        assert content == b'data'
        assert service.get.call_args.args[0] == f'{org}/mod_a/labels/x.png'

    @pytest.mark.parametrize(
        'relative',
        ['../mod_b/x.png', 'labels/../../mod_b/x.png', 'a/../../../other/x', '..'],
    )
    async def test_a_parent_segment_cannot_leave_the_namespace(self, relative):
        """``..`` would resolve outside ``<org>/<module>/`` on the local disk.

        The local provider only keeps a path inside its base directory, and
        every organization's files share that base, so the prefix alone is no
        boundary once the remainder may climb out of it. The path is refused
        before any storage call.
        """
        from app.core.file_storage.errors import StorageError
        from app.core.public_api import file_storage as fs_mod

        org = uuid.uuid4()
        service = MagicMock()
        service.save = AsyncMock()
        with patch.object(fs_mod, 'FileStorageService', return_value=service):
            with pytest.raises(StorageError):
                await fs_mod.CoreFileStorageAPI().save_for_org_async(
                    org, 'mod_a', relative, b'data'
                )
        service.save.assert_not_called()

    def test_a_dot_in_a_name_is_not_a_parent_segment(self):
        from app.core.public_api.file_storage import CoreFileStorageAPI

        org = uuid.uuid4()
        assert (
            CoreFileStorageAPI._scoped_path(org, 'mod_a', 'a/cover..v2.png')
            == f'{org}/mod_a/a/cover..v2.png'
        )

    def test_module_namespaces_are_disjoint(self):
        """Two modules saving the same relative path for the same org
        land on different storage keys."""
        from app.core.public_api.file_storage import CoreFileStorageAPI

        org = uuid.uuid4()
        path_a = CoreFileStorageAPI._scoped_path(org, 'mod_a', 'x.png')
        path_b = CoreFileStorageAPI._scoped_path(org, 'mod_b', 'x.png')
        assert path_a != path_b
        assert path_a.startswith(f'{org}/mod_a/')
        assert path_b.startswith(f'{org}/mod_b/')


# --------------------------- admin superuser gate ----------------------------


class TestAdminSuperuserGate:
    async def test_list_org_metrics_rejects_non_superuser(self):
        from app.core.public_api.admin import CoreAdminAPI

        with pytest.raises(PermissionError, match='Superuser'):
            await CoreAdminAPI().list_org_metrics_async(
                AsyncMock(), user=_user(is_superuser=False)
            )

    async def test_get_global_stats_rejects_non_superuser(self):
        from app.core.public_api.admin import CoreAdminAPI

        with pytest.raises(PermissionError, match='Superuser'):
            await CoreAdminAPI().get_global_stats_async(
                AsyncMock(), user=_user(is_superuser=False)
            )

    async def test_list_org_metrics_allows_superuser(self):
        from app.core.public_api.admin import CoreAdminAPI

        with patch(
            'app.services.admin_metrics_service.list_org_metrics_async',
            AsyncMock(return_value=[]),
        ):
            result = await CoreAdminAPI().list_org_metrics_async(
                AsyncMock(), user=_user(is_superuser=True)
            )
        assert result == []

    async def test_get_global_stats_allows_superuser(self):
        from app.core.public_api.admin import CoreAdminAPI

        sentinel = MagicMock()
        with patch(
            'app.services.admin_metrics_service.get_global_admin_stats_async',
            AsyncMock(return_value=sentinel),
        ):
            result = await CoreAdminAPI().get_global_stats_async(
                AsyncMock(), user=_user(is_superuser=True)
            )
        assert result is sentinel


# --------------------------- ai_usage global stats gate ----------------------


class TestAiUsageGlobalStatsGate:
    async def test_rejects_non_superuser(self):
        from app.core.public_api.ai_usage import CoreAIUsageAPI

        with pytest.raises(PermissionError, match='Superuser'):
            await CoreAIUsageAPI().get_global_stats_async(
                AsyncMock(), user=_user(is_superuser=False)
            )

    async def test_allows_superuser(self):
        from app.core.public_api.ai_usage import CoreAIUsageAPI

        sentinel = MagicMock()
        with patch(
            'app.services.ai_usage_stats_service.get_global_ai_stats_async',
            AsyncMock(return_value=sentinel),
        ):
            result = await CoreAIUsageAPI().get_global_stats_async(
                AsyncMock(), user=_user(is_superuser=True)
            )
        assert result is sentinel
