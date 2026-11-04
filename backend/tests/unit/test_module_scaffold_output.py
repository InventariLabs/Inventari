"""What `module new-community` generates must be installable as-is.

The scaffold is the first thing a community author runs, so anything wrong in it
is wrong in every module built from it. Before it emitted a `BaseModule`
subclass (superseded by `define_module`, which no in-tree module still uses), a
manifest declaring a capability that exists in no enum, and four empty i18n
catalogs whose only effect was to satisfy a check.
"""

import json

import pytest

from app.cli._module_scaffold import scaffold_community_module
from app.i18n import SUPPORTED_LANGUAGES


@pytest.fixture
def package(tmp_path):
    scaffold_community_module('demo_mod', output_dir=str(tmp_path))
    return tmp_path / 'demo_mod'


@pytest.mark.unit
class TestScaffoldBackend:
    def test_module_py_uses_define_module(self, package):
        source = (package / 'backend' / 'module.py').read_text()

        assert 'define_module(' in source
        assert 'BaseModule' not in source

    def test_package_init_exports_what_module_py_defines(self, package):
        """A stale __init__ export is an ImportError at install time."""
        init = (package / 'backend' / '__init__.py').read_text()

        assert 'from .module import module' in init
        assert 'Module' not in init.replace('module', '')

    def test_ships_a_test_that_uses_its_own_table(self, package):
        """The guide says the tests live where the scaffold writes them, so the
        scaffold writes one: it keeps a row in the module's table, which is
        what a first run of the community loop proves."""
        source = (package / 'backend' / 'tests' / 'test_records.py').read_text()

        compile(source, 'test_records.py', 'exec')
        assert 'from app.modules.demo_mod.models import Record' in source
        assert 'db_session' in source
        assert 'test_household' in source

    def test_manifest_declares_the_capability_its_code_uses(self, package):
        """The shipped model and migration import SQLAlchemy, so the generated
        module declares `database`: an undeclared capability is a refused
        install. `module:read` was never one — it is not in
        ManifestCapability."""
        manifest = json.loads((package / 'backend' / 'manifest.json').read_text())

        assert manifest['capabilities'] == ['database']
        assert manifest['module_type'] == 'community'

    def test_the_router_asks_for_the_permissions_the_manifest_declares(self, package):
        # MODULES_GUIDE: every module route has a permission dependency.
        manifest = json.loads((package / 'backend' / 'manifest.json').read_text())
        router = (package / 'backend' / 'router.py').read_text()

        assert [permission['key'] for permission in manifest['permissions']] == [
            'demo_mod:read',
            'demo_mod:write',
        ]
        assert 'require_read_write("demo_mod:read", "demo_mod:write")' in router

    def test_generates_only_the_english_catalog_by_default(self, package):
        catalogs = sorted(p.name for p in (package / 'backend' / 'i18n').iterdir())

        assert catalogs == ['en.json']

    def test_an_asked_for_language_gets_its_catalog_beside_english(self, tmp_path):
        scaffold_community_module(
            'demo_mod', output_dir=str(tmp_path), languages=('pl', 'de')
        )

        catalogs = sorted(
            p.name for p in (tmp_path / 'demo_mod' / 'backend' / 'i18n').iterdir()
        )
        assert catalogs == ['de.json', 'en.json', 'pl.json']

    def test_every_language_can_be_asked_for(self, tmp_path):
        scaffold_community_module(
            'demo_mod', output_dir=str(tmp_path), languages=SUPPORTED_LANGUAGES
        )

        for half in ('backend', 'frontend'):
            catalogs = sorted(
                p.name for p in (tmp_path / 'demo_mod' / half / 'i18n').iterdir()
            )
            assert catalogs == sorted(f'{lang}.json' for lang in SUPPORTED_LANGUAGES)

    def test_the_command_takes_the_languages_as_repeated_options(self, tmp_path):
        from typer.testing import CliRunner

        from manage import app

        result = CliRunner().invoke(
            app,
            ['module', 'new-community', 'demo_mod', '--output', str(tmp_path)]
            + ['-l', 'pl', '--language', 'fr'],
        )

        assert result.exit_code == 0, result.output
        catalogs = sorted(
            p.name for p in (tmp_path / 'demo_mod' / 'frontend' / 'i18n').iterdir()
        )
        assert catalogs == ['en.json', 'fr.json', 'pl.json']

    def test_a_language_the_core_does_not_know_is_refused(self, tmp_path):
        with pytest.raises(SystemExit):
            scaffold_community_module(
                'demo_mod', output_dir=str(tmp_path), languages=('xx',)
            )

        assert not (tmp_path / 'demo_mod').exists()

    def test_a_translated_error_is_read_back_in_every_language(self, tmp_path):
        """The router raises ITEM_NOT_FOUND through get_module_error_message, so
        the key must sit where that function reads it — at the top level of the
        file — and differ per language. Under an `errors` wrapper it came back
        as the bare key from the Core catalogue."""
        from app.i18n.service import (
            _MODULE_TRANSLATIONS,
            get_module_error_message,
            load_module_translations,
        )

        scaffold_community_module(
            'demo_mod', output_dir=str(tmp_path), languages=SUPPORTED_LANGUAGES
        )
        package = tmp_path / 'demo_mod'
        source = (package / 'backend' / 'router.py').read_text()
        assert 'get_module_error_message("demo_mod", "item_not_found")' in source
        try:
            load_module_translations('demo_mod', package / 'backend' / 'i18n')
            messages = {
                lang: get_module_error_message('demo_mod', 'item_not_found', lang)
                for lang in SUPPORTED_LANGUAGES
            }
        finally:
            _MODULE_TRANSLATIONS.pop('demo_mod', None)

        assert 'item_not_found' not in messages.values()
        assert len(set(messages.values())) == len(SUPPORTED_LANGUAGES)


@pytest.mark.unit
class TestScaffoldFrontend:
    def test_generates_only_the_english_catalog_by_default(self, package):
        catalogs = sorted(p.name for p in (package / 'frontend' / 'i18n').iterdir())

        assert catalogs == ['en.json']

    def test_every_catalog_has_the_keys_module_ts_reads(self, tmp_path):
        scaffold_community_module(
            'demo_mod', output_dir=str(tmp_path), languages=SUPPORTED_LANGUAGES
        )
        package = tmp_path / 'demo_mod'
        for lang in SUPPORTED_LANGUAGES:
            catalog = json.loads(
                (package / 'frontend' / 'i18n' / f'{lang}.json').read_text()
            )

            assert catalog['navigation']['title']
            assert catalog['launcher']['description']
            assert catalog['permissions']['read']
            assert catalog['permissions']['write']

    def test_module_ts_passes_registry_only_fields(self, package):
        """`translations` is not a field of FrontendModule, so `tsc --noEmit`
        failed on code the author never wrote; the i18n glob loads the catalogs."""
        source = (package / 'frontend' / 'module.ts').read_text()

        assert 'translations:' not in source
        assert "json';" not in source

    def test_frontend_imports_core_only_through_the_sdk(self, package):
        """The guides name `@/module-sdk` as the one door, and an author outside
        the repository cannot add to it: a generated import that reaches past
        it is a finding on the first `check:boundaries`."""
        for source in (package / 'frontend').rglob('*.ts*'):
            for line in source.read_text().splitlines():
                if line.startswith('import') and "'@/" in line:
                    assert "'@/module-sdk'" in line, f'{source.name}: {line}'

    def test_the_page_hands_its_title_to_the_shell(self, package):
        """FRONTEND_MODULE_GUIDE: a module page never draws its own heading, it
        passes the title to ModuleShell, which renders the page's h1. The page
        drew a CardTitle instead, so the installed screen opened on an h2."""
        source = (package / 'frontend' / 'pages' / 'IndexPage.tsx').read_text()

        assert 'useModulePageHeader' in source
        assert "setHeader({ title: t('title')" in source
        assert 'CardTitle' not in source

    def test_module_ts_has_a_launcher_tile(self, package):
        """Without `launcher` an enabled module has no tile on the home screen
        and the search palette cannot find it."""
        source = (package / 'frontend' / 'module.ts').read_text()

        assert "displayName: 'demo_mod:navigation.title'" in source
        assert "description: 'demo_mod:launcher.description'" in source


@pytest.mark.unit
class TestScaffoldSaysWhereThePackageIs:
    """`make new-community-module` generates through the backend container,
    where the working directory is /app. A package therefore never appeared
    where the docs said it would, and the success line printed a container path
    the host does not have. Worse, the Makefile checked for a name collision in
    the directory it was *not* generating into, so an existing package could be
    overwritten past an explicit guard."""

    @staticmethod
    def _unwrapped(capsys) -> str:
        """Console output with the wrapping taken out.

        rich breaks a long path across lines at whatever width the terminal
        claims, and under xdist that width is not the one a single run gets.
        The question here is which path was printed, not how it was folded.
        """
        return ''.join(capsys.readouterr().out.split())

    def test_the_success_line_carries_the_path_it_wrote(self, tmp_path, capsys):
        scaffold_community_module('demo_mod', output_dir=str(tmp_path))

        assert str(tmp_path / 'demo_mod') in self._unwrapped(capsys)

    def test_the_local_test_command_points_at_that_path(self, tmp_path, capsys):
        """'install ./demo_mod' is only true when the package landed in the
        working directory, and with --output it did not."""
        scaffold_community_module('demo_mod', output_dir=str(tmp_path))

        out = self._unwrapped(capsys)

        assert f'moduleinstall{tmp_path / "demo_mod"}' in out
        assert 'moduleinstall./demo_mod' not in out

    def test_the_signing_step_names_the_key_the_quickstart_writes(
        self, tmp_path, capsys
    ):
        """The command runs in the backend container, whose working directory
        is /app: a bare `my-ed25519.key` is a file there that does not exist.
        The quickstart writes the key to /modules-workspace."""
        scaffold_community_module('demo_mod', output_dir=str(tmp_path))

        out = self._unwrapped(capsys)

        assert '--key/modules-workspace/my-ed25519.key' in out

    def test_it_refuses_rather_than_overwrite(self, tmp_path):
        scaffold_community_module('demo_mod', output_dir=str(tmp_path))

        with pytest.raises(SystemExit) as exc:
            scaffold_community_module('demo_mod', output_dir=str(tmp_path))

        assert exc.value.code == 1


@pytest.mark.unit
class TestScaffoldedVersion:
    """docs/MODULE_VERSIONING.md heads a section with "no 1.0.0 while the
    platform is on 0.x" and then says it does not police the number. The
    scaffold handed every community author exactly the version the document
    argues against, in both files that carry one."""

    def test_module_yaml_starts_below_one(self, package):
        yaml = (package.parent / 'demo_mod' / 'module.yaml').read_text()

        assert 'version: "0.1.0"' in yaml
        assert '1.0.0' not in yaml.split('inventari_min_version')[0]

    def test_the_backend_manifest_agrees_with_it(self, package):
        manifest = json.loads((package / 'backend' / 'manifest.json').read_text())

        assert manifest['version'] == '0.1.0'


@pytest.mark.unit
class TestScaffoldLinksPointAtTheRealRepository:
    """The scaffold once wrote a wrong organisation name into generated
    READMEs while the remote, the deploy docs and twenty markdown files all
    said InventariLabs — and the false address was the one handed to authors.
    The address lives in one constant; these tests pin the output to it."""

    def test_generated_readme_uses_the_repo_url_constant(self, package):
        from app.cli._module_scaffold import GITHUB_REPO_URL

        readme = (package / 'README.md').read_text()

        assert f']({GITHUB_REPO_URL})' in readme
        assert f'{GITHUB_REPO_URL}/blob/main/MODULES_GUIDE.md' in readme

    def test_generated_readme_names_no_other_organisation(self, package):
        import re

        readme = (package / 'README.md').read_text()
        orgs = {
            match.split('/', 1)[0]
            for match in re.findall(r'github\.com/([A-Za-z0-9_.-]+)/', readme)
        }

        assert orgs <= {'InventariLabs', 'yourname'}
