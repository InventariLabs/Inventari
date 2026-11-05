"""Unit tests for app.services.crypto_service."""

import sys
import types

import pytest

# ---------------------------------------------------------------------------
# Helpers — replicate the crypto logic without triggering app circular imports.
# We patch app.config.settings so the module loads cleanly.
# ---------------------------------------------------------------------------


def _make_service(
    secret_key: str = 'test-secret-key-32-bytes-minimum!',
    fernet_salt: str = 'test-fernet-salt-per-deployment-0123456789',
    encryption_key: str = '',
):
    """Return a fresh module object with the given key material.

    ``encryption_key`` empty is the pre-split configuration: secrets are
    encrypted with SECRET_KEY, which is what these cases were written for.
    """
    # Build a minimal settings stub
    stub_settings = types.SimpleNamespace(
        SECRET_KEY=secret_key,
        FERNET_SALT=fernet_salt,
        ENCRYPTION_KEY=encryption_key,
        PREVIOUS_ENCRYPTION_KEY='',
    )

    # Save originals so we can restore after the test
    orig_config = sys.modules.get('app.config')
    orig_crypto = sys.modules.get('app.services.crypto_service')

    # Replace the config module stub BEFORE importing crypto_service
    fake_config = types.ModuleType('app.config')
    fake_config.settings = stub_settings
    sys.modules['app.config'] = fake_config

    # Force re-import of crypto_service so it picks up the stub
    if 'app.services.crypto_service' in sys.modules:
        del sys.modules['app.services.crypto_service']

    import app.services.crypto_service as cs

    # Restore originals immediately so other tests are not affected
    if orig_config is not None:
        sys.modules['app.config'] = orig_config
    else:
        del sys.modules['app.config']

    # The import also bound the fresh copy as an attribute of its package,
    # where `from app.services import crypto_service` finds it: left there, a
    # later test raised this copy's UndecryptableSecretError at code that
    # catches the original's, and the except clause let it through.
    package = sys.modules['app.services']
    if orig_crypto is not None:
        sys.modules['app.services.crypto_service'] = orig_crypto
        package.crypto_service = orig_crypto
    else:
        del sys.modules['app.services.crypto_service']
        del package.crypto_service

    return cs


@pytest.fixture
def cs():
    return _make_service()


# ---------------------------------------------------------------------------
# encrypt_value / decrypt_value
# ---------------------------------------------------------------------------


class TestEncryptDecrypt:
    def test_roundtrip(self, cs):
        secret = 'sk-or-test-12345'
        enc = cs.encrypt_value(secret)
        assert enc.startswith('enc:')
        assert cs.decrypt_value(enc) == secret

    def test_encrypt_is_idempotent(self, cs):
        """Calling encrypt twice should not double-wrap."""
        enc = cs.encrypt_value('my-key')
        assert cs.encrypt_value(enc) == enc

    def test_decrypt_plain_text_passthrough(self, cs):
        """Old plain-text values must pass through unchanged (backward compat)."""
        assert cs.decrypt_value('old-plain-key') == 'old-plain-key'

    def test_decrypt_empty_string(self, cs):
        assert cs.decrypt_value('') == ''

    def test_encrypt_empty_string(self, cs):
        assert cs.encrypt_value('') == ''

    def test_different_keys_cannot_decrypt(self):
        """A ciphertext encrypted under one SECRET_KEY must not yield the
        secret under another key. decrypt_value raises (the hard break)
        — the one answer that can never be mistaken for a legally empty
        secret — while the lenient reader degrades to '' for displays."""
        import pytest

        cs_a = _make_service('key-A-32-bytes-minimum-padding!!')
        cs_b = _make_service('key-B-32-bytes-minimum-padding!!')
        enc = cs_a.encrypt_value('secret')
        with pytest.raises(cs_b.UndecryptableSecretError):
            cs_b.decrypt_value(enc)
        assert cs_b.decrypt_value_lenient(enc) == ''

    def test_different_salts_cannot_decrypt(self):
        """Different per-deployment FERNET_SALT values must yield keys that
        cannot decrypt each other's ciphertext (the security property):
        the strict reader refuses, the plaintext never leaks."""
        import pytest

        cs_a = _make_service(fernet_salt='salt-deployment-alpha-1234567890')
        cs_b = _make_service(fernet_salt='salt-deployment-beta-0987654321')
        enc = cs_a.encrypt_value('secret')
        with pytest.raises(cs_b.UndecryptableSecretError):
            cs_b.decrypt_value(enc)
        assert cs_b.decrypt_value_lenient(enc) == ''


# ---------------------------------------------------------------------------
# mask_settings
# ---------------------------------------------------------------------------


class TestMaskSettings:
    def test_masks_api_key(self, cs):
        enc = cs.encrypt_value('sk-or-12345')
        result = cs.mask_settings({'llm': {'api_key': enc, 'model_name': 'gemini'}})
        assert result['llm']['api_key'] == cs.MASKED_VALUE
        assert result['llm']['model_name'] == 'gemini'  # non-sensitive preserved

    def test_masks_smtp_password(self, cs):
        enc = cs.encrypt_value('smtp-pass')
        result = cs.mask_settings(
            {'smtp': {'host': 'smtp.example.com', 'password': enc}}
        )
        assert result['smtp']['password'] == cs.MASKED_VALUE
        assert result['smtp']['host'] == 'smtp.example.com'

    def test_no_mask_when_key_absent(self, cs):
        result = cs.mask_settings({'llm': {'model_name': 'gemini'}})
        assert 'api_key' not in result['llm']

    def test_no_mask_when_key_empty(self, cs):
        result = cs.mask_settings({'llm': {'api_key': '', 'model_name': 'x'}})
        assert result['llm']['api_key'] == ''

    def test_does_not_mutate_input(self, cs):
        original = {'llm': {'api_key': cs.encrypt_value('key')}}
        cs.mask_settings(original)
        assert original['llm']['api_key'] != cs.MASKED_VALUE


# ---------------------------------------------------------------------------
# merge_incoming_settings
# ---------------------------------------------------------------------------


class TestMergeIncomingSettings:
    def test_masked_value_keeps_existing_encrypted(self, cs):
        enc = cs.encrypt_value('original-key')
        incoming = {'llm': {'api_key': cs.MASKED_VALUE, 'model_name': 'gpt-4'}}
        existing = {'llm': {'api_key': enc}}
        merged = cs.merge_incoming_settings(incoming, existing)
        assert merged['llm']['api_key'] == enc  # preserved
        assert merged['llm']['model_name'] == 'gpt-4'

    def test_new_value_gets_encrypted(self, cs):
        incoming = {'llm': {'api_key': 'new-secret'}}
        merged = cs.merge_incoming_settings(incoming, {})
        assert merged['llm']['api_key'].startswith('enc:')
        assert cs.decrypt_value(merged['llm']['api_key']) == 'new-secret'

    def test_empty_value_clears_key(self, cs):
        enc = cs.encrypt_value('original')
        incoming = {'llm': {'api_key': ''}}
        existing = {'llm': {'api_key': enc}}
        merged = cs.merge_incoming_settings(incoming, existing)
        assert merged['llm']['api_key'] == ''

    def test_existing_none_treated_as_empty(self, cs):
        incoming = {'llm': {'api_key': cs.MASKED_VALUE}}
        merged = cs.merge_incoming_settings(incoming, None)
        assert merged['llm']['api_key'] == ''

    def test_non_sensitive_fields_pass_through(self, cs):
        incoming = {'llm': {'model_name': 'claude', 'api_key': cs.MASKED_VALUE}}
        existing = {'llm': {'model_name': 'gemini', 'api_key': cs.encrypt_value('k')}}
        merged = cs.merge_incoming_settings(incoming, existing)
        assert merged['llm']['model_name'] == 'claude'


class TestDecryptSettings:
    def test_decrypt_plain_text_passthrough(self, cs):
        """Old settings without encryption should decrypt without error."""
        plain = {'llm': {'api_key': 'old-plain-key', 'model_name': 'gpt-4'}}
        result = cs.decrypt_settings(plain)
        assert result['llm']['api_key'] == 'old-plain-key'

    def test_undecryptable_secret_does_not_raise(self):
        """Regression guard for the hard-break 500: when the FERNET_SALT or
        SECRET_KEY changes, existing ``enc:`` secrets become undecryptable.
        decrypt_settings must return them as empty rather than raising — so the
        settings page stays loadable and the operator can re-enter the secret.
        """
        cs_a = _make_service(fernet_salt='old-deployment-salt-00000000000000')
        cs_b = _make_service(fernet_salt='new-deployment-salt-11111111111111')
        enc_with_old_salt = cs_a.encrypt_value('sk-or-real-key')
        settings_with_stale_secret = {
            'llm': {'api_key': enc_with_old_salt, 'model_name': 'gemini'},
            'smtp': {'host': 'smtp.example.com', 'password': ''},
        }
        # Must not raise
        result = cs_b.decrypt_settings(settings_with_stale_secret)
        assert result['llm']['api_key'] == ''  # secret lost, not leaked
        assert result['llm']['model_name'] == 'gemini'  # sibling preserved
        assert result['smtp']['host'] == 'smtp.example.com'


# ---------------------------------------------------------------------------
# Jina regression + general SENSITIVE_PATHS arity
# Bug: settings.modules.recipes.jina.api_key was read decrypted but never
# registered, leaving plaintext keys at rest in the DB.
# ---------------------------------------------------------------------------


class TestSensitivePathsRegistration:
    def test_jina_api_key_path_registered(self, cs):
        """The security gap: jina.api_key must be in SENSITIVE_PATHS so it
        is auto-encrypted on save and masked on read."""
        assert ('modules', 'recipes', 'jina', 'api_key') in cs.SENSITIVE_PATHS

    def test_paths_support_variable_arity(self, cs):
        """SENSITIVE_PATHS must support 2-tuples (legacy) and 4-tuples
        (jina) without breaking type iteration."""
        for path in cs.SENSITIVE_PATHS:
            assert isinstance(path, tuple)
            assert len(path) >= 2
            assert all(isinstance(segment, str) for segment in path)

    def test_legacy_two_tuple_paths_still_present(self, cs):
        """2-tuple paths (llm, smtp) must remain so existing encryption
        behaviour is preserved."""
        paths = cs.SENSITIVE_PATHS
        assert ('llm', 'api_key') in paths
        assert ('smtp', 'password') in paths


class TestJinaApiKeyEncryption:
    def test_jina_api_key_encrypted_on_save(self, cs):
        """merge_incoming_settings must encrypt a new jina key."""
        incoming = {'modules': {'recipes': {'jina': {'api_key': 'jina-plain-12345'}}}}
        merged = cs.merge_incoming_settings(incoming, {})
        assert merged['modules']['recipes']['jina']['api_key'].startswith('enc:')
        assert (
            cs.decrypt_value(merged['modules']['recipes']['jina']['api_key'])
            == 'jina-plain-12345'
        )

    def test_jina_api_key_masked_in_mask_settings(self, cs):
        """mask_settings must mask jina api_key on read."""
        enc = cs.encrypt_value('jina-secret')
        settings = {'modules': {'recipes': {'jina': {'api_key': enc}}}}
        result = cs.mask_settings(settings)
        assert result['modules']['recipes']['jina']['api_key'] == cs.MASKED_VALUE

    def test_jina_masked_value_keeps_existing_on_merge(self, cs):
        """If frontend sends MASKED_VALUE, keep the stored encrypted key."""
        enc = cs.encrypt_value('original-jina-key')
        incoming = {
            'modules': {
                'recipes': {'jina': {'api_key': cs.MASKED_VALUE, 'rate_limit_rpm': 20}}
            }
        }
        existing = {'modules': {'recipes': {'jina': {'api_key': enc}}}}
        merged = cs.merge_incoming_settings(incoming, existing)
        assert merged['modules']['recipes']['jina']['api_key'] == enc
        assert merged['modules']['recipes']['jina']['rate_limit_rpm'] == 20

    def test_jina_does_not_mutate_sibling_module_fields(self, cs):
        """Only the jina/api_key leaf is touched — sibling leaf nodes in
        the same subtree are passed through unchanged."""
        incoming = {
            'modules': {
                'recipes': {
                    'llm': {'api_key': cs.encrypt_value('llm-key')},
                    'jina': {'api_key': 'jina-new', 'enabled': True},
                }
            }
        }
        existing = {
            'modules': {
                'recipes': {
                    'llm': {'api_key': cs.encrypt_value('llm-orig')},
                    'jina': {'api_key': cs.encrypt_value('jina-orig')},
                }
            }
        }
        merged = cs.merge_incoming_settings(incoming, existing)
        # jina rotated to 'enc:...'
        assert merged['modules']['recipes']['jina']['api_key'].startswith('enc:')
        assert merged['modules']['recipes']['jina']['enabled'] is True
        # llm untouched (MASKED_VALUE preserved OR no path apply because
        # 'llm' is the 2-tuple legacy path and lives at the settings root
        # not inside modules)
        assert 'llm' not in merged['modules']['recipes'] or merged['modules'][
            'recipes'
        ]['llm']['api_key'].startswith('enc:')
