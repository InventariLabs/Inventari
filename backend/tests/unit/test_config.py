import pytest


@pytest.fixture(autouse=True)
def _the_module_is_put_back():
    """Every test here reloads ``app.config`` and leaves a new ``settings`` in it.

    The reload rebuilds the module from the monkeypatched environment;
    ``monkeypatch`` restores the environment afterwards but not the module,
    so the process went on with a ``settings`` object nobody else held --
    one with the dev ``DATABASE_URL`` instead of the worker's test database,
    and without any value another test had patched on the original. Code
    that imports ``settings`` at load time kept the old object, code that
    reads ``app.config.settings`` on each call got the new one, and whether
    the two agreed depended on whether this file had run yet.
    """
    import app.config as mod

    before = dict(mod.__dict__)
    yield
    mod.__dict__.clear()
    mod.__dict__.update(before)


def test_weak_secret_key_rejected(monkeypatch):
    monkeypatch.setenv('SECRET_KEY', 'changeme')
    monkeypatch.setenv('DEBUG', 'false')
    monkeypatch.delenv('TESTING', raising=False)

    with pytest.raises(ValueError, match='known weak value'):
        import importlib

        import app.config as mod

        importlib.reload(mod)


def test_weak_secret_key_warning_shows_no_part_of_the_key(monkeypatch, caplog):
    """The dev-mode warning says the key is weak, not what any of it is."""
    import importlib
    import logging

    import app.config as mod

    monkeypatch.setenv('SECRET_KEY', 'changeme')
    monkeypatch.setenv('TESTING', 'true')

    with caplog.at_level(logging.WARNING, logger=mod.__name__):
        importlib.reload(mod)

    warning = next(r for r in caplog.records if 'known weak value' in r.getMessage())
    assert '***' not in warning.getMessage()
    assert warning.args in (None, ())


def test_strong_secret_key_accepted(monkeypatch):
    monkeypatch.setenv('SECRET_KEY', 'a-valid-random-key-that-is-long-enough-abc123xyz')
    monkeypatch.setenv('DEBUG', 'false')

    import importlib

    import app.config as mod

    mod.settings.SECRET_KEY = 'a-valid-random-key-that-is-long-enough-abc123xyz'
    importlib.reload(mod)

    assert mod.settings.SECRET_KEY not in mod._WEAK_SECRET_KEYS


def test_short_secret_key_rejected_in_production(monkeypatch):
    """Keys shorter than 32 bytes must be rejected in production."""
    monkeypatch.setenv('SECRET_KEY', 'tooshort')  # 8 bytes, not in blocklist
    monkeypatch.setenv('DEBUG', 'false')
    monkeypatch.delenv('TESTING', raising=False)

    with pytest.raises(ValueError, match='at least 32 bytes'):
        import importlib

        import app.config as mod

        importlib.reload(mod)


def test_short_secret_key_warned_in_testing(monkeypatch):
    """Keys shorter than 32 bytes are allowed (warned) in TESTING mode."""
    monkeypatch.setenv('SECRET_KEY', 'tooshort')  # 8 bytes, not in blocklist
    monkeypatch.setenv('TESTING', 'true')

    import importlib

    import app.config as mod

    importlib.reload(mod)  # must NOT raise
    assert mod.settings.SECRET_KEY == 'tooshort'


class TestFernetSaltGuard:
    """the dev salt is long enough to pass the length check, so a
    copied .env would satisfy production while sharing a published value."""

    def test_example_salt_rejected_in_production(self, monkeypatch):
        monkeypatch.setenv(
            'SECRET_KEY', 'a-valid-random-key-that-is-long-enough-abc123xyz'
        )
        monkeypatch.setenv(
            'FERNET_SALT', 'dev-fernet-salt-please-rotate-1234567890abcdef'
        )
        monkeypatch.setenv('DEBUG', 'false')
        monkeypatch.delenv('TESTING', raising=False)

        with pytest.raises(ValueError, match='known example value'):
            import importlib

            import app.config as mod

            importlib.reload(mod)

    def test_per_deployment_salt_accepted(self, monkeypatch):
        monkeypatch.setenv(
            'SECRET_KEY', 'a-valid-random-key-that-is-long-enough-abc123xyz'
        )
        monkeypatch.setenv('FERNET_SALT', 'Zm9vYmFyLXBlci1kZXBsb3ltZW50LXNhbHQ')
        monkeypatch.setenv('DEBUG', 'false')
        monkeypatch.delenv('TESTING', raising=False)

        import importlib

        import app.config as mod

        importlib.reload(mod)  # must NOT raise
        assert mod.settings.FERNET_SALT not in mod._WEAK_FERNET_SALTS


class TestLoadTestingGuard:
    """LOAD_TESTING disables the global rate limiter — it must never reach prod.

    ``core/limiter.py`` turns the limiter off whenever the flag is set, so a
    ``.env`` copied from a load-test run would strip brute-force protection from
    every endpoint silently. Startup fails instead.
    """

    @staticmethod
    def _reload(monkeypatch):
        monkeypatch.setenv(
            'SECRET_KEY', 'a-valid-random-key-that-is-long-enough-abc123xyz'
        )
        monkeypatch.setenv('FERNET_SALT', 'a-valid-random-salt-that-is-long-enough')
        import importlib

        import app.config as mod

        importlib.reload(mod)
        return mod

    def test_rejected_outside_debug_and_testing(self, monkeypatch):
        monkeypatch.setenv('LOAD_TESTING', 'true')
        monkeypatch.setenv('DEBUG', 'false')
        monkeypatch.delenv('TESTING', raising=False)
        monkeypatch.delenv('LOAD_TESTING_ACK_UNSAFE', raising=False)

        with pytest.raises(ValueError, match='no brute-force protection'):
            self._reload(monkeypatch)

    def test_allowed_in_debug(self, monkeypatch):
        monkeypatch.setenv('LOAD_TESTING', 'true')
        monkeypatch.setenv('DEBUG', 'true')

        mod = self._reload(monkeypatch)  # must NOT raise

        assert mod.settings.LOAD_TESTING is True

    def test_allowed_in_testing(self, monkeypatch):
        monkeypatch.setenv('LOAD_TESTING', 'true')
        monkeypatch.setenv('DEBUG', 'false')
        monkeypatch.setenv('TESTING', 'true')

        mod = self._reload(monkeypatch)  # must NOT raise

        assert mod.settings.LOAD_TESTING is True

    def test_allowed_when_acknowledged(self, monkeypatch):
        """The load-test stack runs prod-like on purpose and opts in explicitly."""
        monkeypatch.setenv('LOAD_TESTING', 'true')
        monkeypatch.setenv('DEBUG', 'false')
        monkeypatch.delenv('TESTING', raising=False)
        monkeypatch.setenv('LOAD_TESTING_ACK_UNSAFE', 'true')

        mod = self._reload(monkeypatch)  # must NOT raise

        assert mod.settings.LOAD_TESTING_ACK_UNSAFE is True


# ---------------------------------------------------------------------------
# FERNET_SALT — per-deployment salt for Fernet key derivation.
# Replaces the hardcoded b'inventari-fernet-salt' shared across deployments.
# ---------------------------------------------------------------------------


class TestFernetSaltConfig:
    def test_empty_salt_rejected_in_production(self, monkeypatch):
        """Empty FERNET_SALT must raise in production mode."""
        monkeypatch.setenv(
            'SECRET_KEY', 'a-valid-random-key-that-is-long-enough-abc123xyz'
        )
        monkeypatch.setenv('FERNET_SALT', '')
        monkeypatch.setenv('DEBUG', 'false')
        monkeypatch.delenv('TESTING', raising=False)

        with pytest.raises(ValueError, match='FERNET_SALT must be set'):
            import importlib

            import app.config as mod

            importlib.reload(mod)

    def test_short_salt_rejected_in_production(self, monkeypatch):
        """FERNET_SALT shorter than 16 bytes must raise in production."""
        monkeypatch.setenv(
            'SECRET_KEY', 'a-valid-random-key-that-is-long-enough-abc123xyz'
        )
        monkeypatch.setenv('FERNET_SALT', 'short')  # 5 bytes
        monkeypatch.setenv('DEBUG', 'false')
        monkeypatch.delenv('TESTING', raising=False)

        with pytest.raises(ValueError, match='FERNET_SALT must be set'):
            import importlib

            import app.config as mod

            importlib.reload(mod)

    def test_valid_salt_accepted_in_production(self, monkeypatch):
        """A per-deployment salt (>=16 bytes) is accepted in production."""
        monkeypatch.setenv(
            'SECRET_KEY', 'a-valid-random-key-that-is-long-enough-abc123xyz'
        )
        monkeypatch.setenv('FERNET_SALT', 'a-per-deployment-random-salt-1234567890')
        monkeypatch.setenv('DEBUG', 'false')
        monkeypatch.delenv('TESTING', raising=False)

        import importlib

        import app.config as mod

        importlib.reload(mod)  # must NOT raise
        assert mod.settings.FERNET_SALT == 'a-per-deployment-random-salt-1234567890'

    def test_empty_salt_generated_in_dev(self, monkeypatch):
        """Empty FERNET_SALT in dev/test generates a random one (no crash)."""
        monkeypatch.setenv(
            'SECRET_KEY', 'a-valid-random-key-that-is-long-enough-abc123xyz'
        )
        monkeypatch.setenv('FERNET_SALT', '')
        monkeypatch.setenv('TESTING', 'true')

        import importlib

        import app.config as mod

        importlib.reload(mod)  # must NOT raise
        assert len(mod.settings.FERNET_SALT) > 0


def test_a_compose_env_file_with_keys_settings_does_not_know_still_loads(
    tmp_path, monkeypatch
):
    """The root ``.env`` is Compose's file as much as the backend's.

    ``make dev-up`` writes DB_USER, DB_PASSWORD, PRODUCTS_DB_* and printer
    keys there for Compose to read. Run on the host, the backend reads the
    same file, and pydantic's default of rejecting a dotenv key no field names
    stopped it before it served a request.
    """
    from app.config import Settings

    env_file = tmp_path / '.env'
    env_file.write_text(
        'DB_USER=inventari_user\n'
        'DB_PASSWORD=change-me-strong-password\n'
        'PRODUCTS_DB_NAME=products_db\n'
        'MIGRATION_DATABASE_URL=postgresql://from-the-file/db\n',
        encoding='utf-8',
    )

    monkeypatch.delenv('MIGRATION_DATABASE_URL', raising=False)

    loaded = Settings(_env_file=env_file)

    assert loaded.MIGRATION_DATABASE_URL == 'postgresql://from-the-file/db'


def _reload_with_llm_keys(monkeypatch, *, new=None, old=None):
    import importlib

    import app.config as mod

    for name, value in (('LLM_API_KEY', new), ('OPENROUTER_API_KEY', old)):
        if value is None:
            monkeypatch.delenv(name, raising=False)
        else:
            monkeypatch.setenv(name, value)
    monkeypatch.setenv('TESTING', 'true')
    importlib.reload(mod)
    return mod


def test_llm_api_key_configures_the_environment_model(monkeypatch):
    mod = _reload_with_llm_keys(monkeypatch, new='sk-new')

    assert mod.settings.LLM_API_KEY == 'sk-new'


def test_old_openrouter_variable_still_sets_the_key(monkeypatch):
    """Existing .env files (the demo's included) keep working."""
    mod = _reload_with_llm_keys(monkeypatch, old='sk-old')

    assert mod.settings.LLM_API_KEY == 'sk-old'


def test_llm_api_key_wins_over_the_old_name_with_one_warning(monkeypatch, caplog):
    with caplog.at_level('WARNING', logger='app.config'):
        mod = _reload_with_llm_keys(monkeypatch, new='sk-new', old='sk-old')

    assert mod.settings.LLM_API_KEY == 'sk-new'
    warnings = [
        r.getMessage()
        for r in caplog.records
        if 'LLM_API_KEY' in r.getMessage() and 'OPENROUTER_API_KEY' in r.getMessage()
    ]
    assert len(warnings) == 1
    assert 'sk-new' not in warnings[0] and 'sk-old' not in warnings[0]


def test_both_names_with_the_same_value_do_not_warn(monkeypatch, caplog):
    with caplog.at_level('WARNING', logger='app.config'):
        mod = _reload_with_llm_keys(monkeypatch, new='sk-same', old='sk-same')

    assert mod.settings.LLM_API_KEY == 'sk-same'
    assert not [r for r in caplog.records if 'OPENROUTER_API_KEY' in r.getMessage()]


def test_empty_new_name_falls_back_to_the_old_one(monkeypatch):
    """Compose passes ``LLM_API_KEY=`` when only the old name is in .env."""
    mod = _reload_with_llm_keys(monkeypatch, new='', old='sk-old')

    assert mod.settings.LLM_API_KEY == 'sk-old'
