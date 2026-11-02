"""Unit tests for platform version helpers + module version guards."""

from uuid import uuid4

import pytest

from app.core.version import check_min_version, get_platform_version, parse_version


@pytest.mark.unit
class TestParseVersion:
    def test_full_semver(self):
        assert parse_version('0.10.2') == (0, 10, 2)

    def test_short_forms_padded(self):
        assert parse_version('2') == (2, 0, 0)
        assert parse_version('1.5') == (1, 5, 0)

    def test_invalid_raises(self):
        with pytest.raises(ValueError, match='Invalid version'):
            parse_version('abc')
        with pytest.raises(ValueError, match='Invalid version'):
            parse_version('1.2.3.4')


@pytest.mark.unit
class TestCheckMinVersion:
    def test_empty_means_no_constraint(self):
        assert check_min_version('') is None
        assert check_min_version('  ') is None

    def test_satisfied(self):
        assert check_min_version('0.8.0', '0.9.0') is None
        assert check_min_version('0.8.0', '0.8.0') is None
        assert check_min_version('0.9', '0.10.0') is None

    def test_unmet_returns_message(self):
        error = check_min_version('0.10.0', '0.9.0')
        assert error is not None
        assert '0.10.0' in error
        assert '0.9.0' in error

    def test_invalid_min_version_is_unmet(self):
        assert check_min_version('not-a-version', '0.9.0') is not None

    def test_reads_platform_version_from_pyproject(self):
        # pyproject in this repo — must satisfy its own version
        assert check_min_version(get_platform_version()) is None


@pytest.mark.unit
class TestToggleModuleVersionGuard:
    """Enable path rejects tracked community modules requiring a newer platform."""

    async def test_enable_rejected_for_incompatible_community_module(self, monkeypatch):
        from app.core.contracts import UserContextDTO
        from app.core.exceptions import ValidationException
        from app.services.module_service import ModuleService
        from tests.unit.test_module_service_toggle import _FakeDb, _FakeOrg

        monkeypatch.setattr(
            'app.services.module_service.load_module_tracking',
            lambda: {'some_module': {'inventari_min_version': '999.0.0'}},
        )

        org = _FakeOrg()
        user = UserContextDTO(
            id=uuid4(), organization_id=org.id, role='admin', email='a@t.com'
        )

        with pytest.raises(ValidationException, match='999.0.0'):
            await ModuleService.toggle_module(
                _FakeDb(org), org, 'some_module', enabled=True, user=user
            )
        assert 'some_module' not in org.enabled_modules

    async def test_enable_allowed_when_constraint_met(self, monkeypatch):
        from app.core.contracts import UserContextDTO
        from app.services.module_service import ModuleService
        from tests.unit.test_module_service_toggle import _FakeDb, _FakeOrg

        monkeypatch.setattr(
            'app.services.module_service.load_module_tracking',
            lambda: {'some_module': {'inventari_min_version': '0.1.0'}},
        )

        org = _FakeOrg()
        user = UserContextDTO(
            id=uuid4(), organization_id=org.id, role='admin', email='a@t.com'
        )

        result = await ModuleService.toggle_module(
            _FakeDb(org), org, 'some_module', enabled=True, user=user
        )
        assert 'some_module' in result

    async def test_untracked_module_has_no_constraint(self, monkeypatch):
        from app.core.contracts import UserContextDTO
        from app.services.module_service import ModuleService
        from tests.unit.test_module_service_toggle import _FakeDb, _FakeOrg

        monkeypatch.setattr(
            'app.services.module_service.load_module_tracking', lambda: {}
        )

        org = _FakeOrg()
        user = UserContextDTO(
            id=uuid4(), organization_id=org.id, role='admin', email='a@t.com'
        )

        result = await ModuleService.toggle_module(
            _FakeDb(org), org, 'core_module', enabled=True, user=user
        )
        assert 'core_module' in result


@pytest.mark.unit
class TestScaffoldUsesCurrentPlatformVersion:
    def test_scaffolded_min_version_installable_on_current_platform(self, tmp_path):
        """Run the real scaffold: a fresh module must pass its own version gate."""
        import yaml

        from app.cli._module_scaffold import scaffold_community_module

        scaffold_community_module('scaffold_probe', output_dir=str(tmp_path))

        manifest = yaml.safe_load(
            (tmp_path / 'scaffold_probe' / 'module.yaml').read_text()
        )
        min_version = str(manifest['inventari_min_version'])
        assert min_version == get_platform_version()
        # the generated module must install on the platform that built it
        assert check_min_version(min_version) is None
