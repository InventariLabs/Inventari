"""Guards in the backend core that must not hang, sleep or crash on a host.

* ``sqlstate_of`` walks an exception chain that can point back at itself.
* The dev import guard reads the same environment switch the CLI guard reads.
* The real app answers a refused request with the coded handler.
* The upload directory default is writable on a host that has no ``/app``.
"""

from pathlib import Path

import pytest
from slowapi.errors import RateLimitExceeded

from app import config
from app.core import dev_guard
from app.core.db_retry import sqlstate_of
from app.core.limiter import rate_limit_exceeded_handler


class TestSqlstateOfOnACyclingChain:
    def test_a_cause_cycle_ends_the_walk(self):
        a, b = RuntimeError('a'), RuntimeError('b')
        a.__cause__ = b
        b.__cause__ = a

        assert sqlstate_of(a) is None

    def test_an_orig_cycle_ends_the_walk(self):
        a = RuntimeError('a')
        a.orig = a  # type: ignore[attr-defined]

        assert sqlstate_of(a) is None

    def test_a_code_found_before_the_cycle_still_wins(self):
        a, b = RuntimeError('a'), RuntimeError('b')
        b.sqlstate = '40001'  # type: ignore[attr-defined]
        a.__cause__ = b
        b.__cause__ = a

        assert sqlstate_of(a) == '40001'


class TestTheDevGuardRuns:
    @pytest.fixture
    def violating_router(self, monkeypatch):
        monkeypatch.setattr(
            dev_guard,
            'check_module_router_imports',
            lambda: ['modules/x/router.py:1: from app.models import'],
        )

    @pytest.mark.parametrize('name', ['INVENTARI_ENV', 'ENVIRONMENT'])
    def test_it_scans_when_the_environment_says_development(
        self, monkeypatch, violating_router, name
    ):
        monkeypatch.delenv('INVENTARI_ENV', raising=False)
        monkeypatch.delenv('ENVIRONMENT', raising=False)
        monkeypatch.setenv(name, 'development')

        with pytest.raises(RuntimeError, match='forbidden imports'):
            dev_guard.run_dev_guard()

    def test_the_name_wins_over_the_alias(self, monkeypatch, violating_router):
        monkeypatch.setenv('INVENTARI_ENV', 'production')
        monkeypatch.setenv('ENVIRONMENT', 'development')

        dev_guard.run_dev_guard()

    def test_it_stays_silent_when_nothing_is_declared(
        self, monkeypatch, violating_router
    ):
        monkeypatch.delenv('INVENTARI_ENV', raising=False)
        monkeypatch.delenv('ENVIRONMENT', raising=False)

        dev_guard.run_dev_guard()

    def test_the_module_routers_in_the_tree_pass_it(self):
        assert dev_guard.check_module_router_imports() == []


def test_the_real_app_refuses_with_the_coded_handler():
    from app.main import app

    assert app.exception_handlers[RateLimitExceeded] is rate_limit_exceeded_handler


class TestTheUploadsDefault:
    def test_the_container_path_is_kept_where_app_exists(self, monkeypatch):
        monkeypatch.setattr(Path, 'is_dir', lambda self: str(self) == '/app')

        assert config._uploads_path_for_this_host('/app/uploads') == '/app/uploads'

    def test_a_path_the_operator_chose_is_left_alone(self, monkeypatch):
        monkeypatch.setattr(Path, 'is_dir', lambda self: False)

        assert config._uploads_path_for_this_host('/srv/files') == '/srv/files'

    def test_the_setting_goes_through_it(self, monkeypatch):
        monkeypatch.setattr(Path, 'is_dir', lambda self: False)
        monkeypatch.delenv('FILE_STORAGE_LOCAL_PATH', raising=False)

        loaded = config.Settings(_env_file=None)

        beside_the_backend = Path(config.__file__).resolve().parent.parent / 'uploads'
        assert loaded.FILE_STORAGE_LOCAL_PATH == str(beside_the_backend)

    def test_a_host_without_app_gets_a_directory_beside_the_backend(self, monkeypatch):
        monkeypatch.setattr(Path, 'is_dir', lambda self: False)

        path = Path(config._uploads_path_for_this_host('/app/uploads'))

        assert path.name == 'uploads'
        assert path.parent == Path(config.__file__).resolve().parent.parent
