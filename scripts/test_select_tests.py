#!/usr/bin/env python3
"""Check of scripts/select-tests.py: each rule of the picker must still pick.

    python3 scripts/test_select_tests.py

The picker reads a repository made of a dictionary here, so the check needs no
stack and no checkout of its own. Standard library only: it runs on the host,
where `make lint` lives.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

SPEC = importlib.util.spec_from_file_location(
    'select_tests', Path(__file__).with_name('select-tests.py')
)
assert SPEC and SPEC.loader
picker = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = picker
SPEC.loader.exec_module(picker)

BACKEND = 'backend/'
ALPHA = 'backend/app/modules/alpha/'
BETA = 'backend/app/modules/beta/'
GAMMA = 'backend/app/modules/gamma/'
TESTS = 'backend/tests/unit/'

FILES = {
    'backend/conftest.py': 'from tests._shared import build\n',
    'backend/tests/__init__.py': '',
    'backend/tests/_shared.py': 'from app.modules.gamma.models import Row\n',
    'backend/tests/_helper.py': 'VALUE = 1\n',
    'backend/tests/_wrapper.py': 'from ._helper import VALUE\n',
    TESTS + 'test_uses_the_wrapper.py': 'from tests._wrapper import VALUE\n',
    TESTS + 'test_patches_the_helper.py': "TARGET = 'tests._helper.VALUE'\n",
    'backend/app/__init__.py': '',
    'backend/app/core/engine.py': 'from app.modules.alpha.service import run\n',
    'backend/app/modules/__init__.py': '',
    ALPHA + '__init__.py': '',
    ALPHA + 'manifest.json': '{"name": "alpha"}',
    ALPHA + 'service.py': 'def run():\n    return 1\n',
    ALPHA + 'tests/test_alpha_own.py': 'def test_own():\n    pass\n',
    BETA + '__init__.py': '',
    BETA + 'manifest.json': '{"name": "beta", "requires": ["alpha", "items"]}',
    BETA + 'tests/test_beta_own.py': 'def test_own():\n    pass\n',
    GAMMA + '__init__.py': '',
    GAMMA + 'models.py': 'class Row:\n    pass\n',
    GAMMA + 'manifest.json': '{"name": "gamma", "optional_requires": ["beta"]}',
    GAMMA + 'tests/test_gamma_own.py': 'def test_own():\n    pass\n',
    TESTS + 'test_imports_service.py': 'from app.modules.alpha import service\n',
    TESTS + 'test_through_a_helper.py': 'from app.modules.alpha.tool import x\n',
    ALPHA + 'tool.py': 'from app.modules.alpha.service import run\nx = run\n',
    TESTS + 'test_patches_by_name.py': ("TARGET = 'app.modules.alpha.service.run'\n"),
    TESTS + 'test_calls_the_route.py': "URL = '/api/v1/alpha/things'\n",
    TESTS + 'test_uses_the_helper.py': 'from tests._helper import VALUE\n',
    TESTS + 'test_through_the_core.py': 'from app.core import engine\n',
    TESTS + 'test_walks_the_sources.py': "files = root.rglob('*.py')\n",
    TESTS + 'test_walks_the_frontend.py': "files = (root / 'frontend').rglob('*')\n",
    TESTS + 'test_loads_a_generator.py': 'spec_from_file_location(name, path)\n',
    TESTS + 'test_reads_the_guide.py': "text = read('docs/GUIDE.md')\n",
    TESTS + 'test_runs_the_script.py': "path = 'scripts/check_thing.py'\n",
    'backend/scripts/check_thing.py': 'print()\n',
    'backend/scripts/orphan.py': 'print()\n',
    TESTS + 'test_unrelated.py': 'def test_unrelated():\n    pass\n',
    'docs/GUIDE.md': '',
    'docs/OTHER.md': '',
    'frontend/src/lib/format.ts': 'export const f = 1;\n',
    'frontend/src/lib/format.test.ts': "import { f } from './format';\n",
    'frontend/src/lib/guard.test.ts': "readFileSync('x');\n",
    'frontend/src/lib/manifest.test.ts': "load('alpha/manifest.json');\n",
    'frontend/tests/e2e/login.spec.ts': '',
}


class Memory(picker.Tree):
    def __init__(self, files):
        self.files = files

    def paths(self):
        return sorted(self.files)

    def read(self, path):
        return self.files.get(path, '')


def plan(*changed, without=(), **files):
    tree = dict(FILES)
    for path in without:
        del tree[path]
    tree.update(files)
    return picker.select(list(changed), Memory(tree))


def names(picked):
    return {Path(path).name for path in picked}


class AModuleChange(unittest.TestCase):
    def setUp(self):
        self.plan = plan(ALPHA + 'service.py')
        self.picked = names(self.plan.backend)

    def test_runs_the_modules_own_tests(self):
        self.assertIn('test_alpha_own.py', self.picked)

    def test_runs_the_tests_that_import_it(self):
        self.assertIn('test_imports_service.py', self.picked)

    def test_runs_the_tests_that_import_it_through_another_file(self):
        self.assertIn('test_through_a_helper.py', self.picked)

    def test_runs_the_tests_that_name_it(self):
        self.assertIn('test_patches_by_name.py', self.picked)
        self.assertIn('test_calls_the_route.py', self.picked)

    def test_runs_the_tests_of_the_modules_that_require_it(self):
        self.assertIn('test_beta_own.py', self.picked)
        self.assertIn('test_gamma_own.py', self.picked)

    def test_does_not_walk_past_the_core(self):
        self.assertNotIn('test_through_the_core.py', self.picked)

    def test_leaves_an_unrelated_test_out(self):
        self.assertFalse(self.plan.backend_full)
        self.assertNotIn('test_unrelated.py', self.picked)

    def test_runs_the_tests_that_read_the_repository(self):
        self.assertIn('test_walks_the_sources.py', self.picked)

    def test_runs_the_tests_that_load_a_script(self):
        self.assertIn('test_loads_a_generator.py', self.picked)

    def test_says_why(self):
        self.assertEqual(
            self.plan.backend[ALPHA + 'tests/test_alpha_own.py'],
            'tests of the changed module alpha',
        )

    def test_of_its_manifest_runs_the_frontend_test_that_names_it(self):
        picked = names(plan(ALPHA + 'manifest.json').frontend)
        self.assertIn('manifest.test.ts', picked)


class TheWholeBackend(unittest.TestCase):
    def whole(self, *changed, why, **kwargs):
        got = plan(*changed, **kwargs)
        self.assertTrue(got.backend_full, changed)
        self.assertIn(why, ' '.join(got.backend_full))
        self.assertEqual(got.backend, {})

    def test_the_core(self):
        self.whole('backend/app/core/engine.py', why='the core')

    def test_a_core_model_that_no_longer_exists(self):
        self.whole('backend/app/models/gone.py', why='the core')

    def test_a_migration(self):
        self.whole(ALPHA + 'migrations/versions/a.py', why='a migration')

    def test_a_conftest(self):
        self.whole(ALPHA + 'tests/conftest.py', why='fixtures')

    def test_what_a_shared_conftest_imports(self):
        self.whole('backend/tests/_shared.py', why='conftest imports it')
        self.whole(GAMMA + 'models.py', why='conftest imports it')

    def test_a_shared_fixture(self):
        self.whole('backend/tests/fixtures/rows.sql', why='shared fixture')

    def test_the_configuration(self):
        for path in picker.BACKEND_CONFIG:
            self.whole(path, why=picker.BACKEND_CONFIG[path])

    def test_a_deleted_test_helper(self):
        self.whole(
            'backend/tests/_helper.py',
            why='deleted test helper',
            without=['backend/tests/_helper.py'],
        )

    def test_a_file_that_does_not_parse(self):
        self.whole(
            ALPHA + 'service.py',
            why='does not parse',
            **{ALPHA + 'service.py': 'def (:\n'},
        )

    def test_a_backend_file_no_test_names(self):
        self.whole('backend/scripts/orphan.py', why='no test imports or names it')

    def test_the_makefile_and_compose_files_are_both_suites(self):
        for path in ('Makefile', 'docker-compose.yml', 'docker-compose.prod.yml'):
            got = plan(path)
            self.assertTrue(got.backend_full and got.frontend_full, path)


class OtherChanges(unittest.TestCase):
    def test_a_changed_test_runs_itself(self):
        got = plan(TESTS + 'test_unrelated.py')
        self.assertEqual(got.backend[TESTS + 'test_unrelated.py'], 'changed test')

    def test_a_deleted_test_runs_nothing_of_it(self):
        path = TESTS + 'test_unrelated.py'
        got = plan(path, without=[path])
        self.assertNotIn(path, got.backend)
        self.assertFalse(got.backend_full)

    def test_a_test_helper_runs_its_users(self):
        got = plan('backend/tests/_helper.py')
        self.assertIn('test_uses_the_helper.py', names(got.backend))
        self.assertFalse(got.backend_full)

    def test_a_test_helper_runs_the_users_of_its_users(self):
        got = plan('backend/tests/_helper.py')
        self.assertIn('test_uses_the_wrapper.py', names(got.backend))

    def test_a_name_written_as_a_string_is_an_import(self):
        got = plan('backend/tests/_helper.py')
        self.assertIn('test_patches_the_helper.py', names(got.backend))

    def test_a_script_runs_the_tests_that_name_it(self):
        got = plan('backend/scripts/check_thing.py')
        self.assertIn('test_runs_the_script.py', names(got.backend))
        self.assertFalse(got.backend_full)

    def test_a_document_runs_its_readers_only(self):
        got = plan('docs/GUIDE.md')
        self.assertEqual(names(got.backend), {'test_reads_the_guide.py'})
        self.assertEqual(got.frontend, {})

    def test_a_change_outside_the_backend_runs_the_readers_of_that_part(self):
        got = plan('frontend/src/lib/format.ts')
        self.assertEqual(names(got.backend), {'test_walks_the_frontend.py'})

    def test_a_common_file_name_needs_its_directory(self):
        # Three manifests: `manifest.json` alone says nothing about which.
        got = plan(BETA + 'manifest.json')
        self.assertNotIn(
            'manifest.test.ts',
            {
                Path(path).name
                for path, why in got.frontend.items()
                if why.startswith('names')
            },
        )


class TheFrontend(unittest.TestCase):
    def test_hands_the_changed_file_to_vitest(self):
        got = plan('frontend/src/lib/format.ts')
        self.assertIn('frontend/src/lib/format.ts', got.frontend)

    def test_adds_the_tests_that_read_files_from_disk(self):
        got = plan('frontend/src/lib/format.ts')
        self.assertIn('frontend/src/lib/guard.test.ts', got.frontend)

    def test_configuration_runs_the_whole_suite(self):
        for path in (
            'frontend/package.json',
            'frontend/package-lock.json',
            'frontend/vite.config.ts',
            'frontend/tsconfig.node.json',
            'frontend/tailwind.config.js',
            'frontend/src/test/setup.ts',
        ):
            got = plan(path)
            self.assertTrue(got.frontend_full, path)
            self.assertEqual(got.frontend, {})

    def test_a_deleted_source_file_runs_the_whole_suite(self):
        path = 'frontend/src/lib/format.ts'
        self.assertTrue(plan(path, without=[path]).frontend_full)

    def test_a_browser_spec_is_not_vitests(self):
        got = plan('frontend/tests/e2e/login.spec.ts')
        self.assertEqual(got.frontend, {})
        self.assertIn('select-e2e-specs', ' '.join(got.notes))


class TheCommands(unittest.TestCase):
    def test_pytest_gets_the_workers_and_the_files_from_backend(self):
        got = picker.commands(plan(TESTS + 'test_unrelated.py'), 7)[0]
        self.assertEqual(
            got[:11], 'docker compose exec -T backend uv run pytest -q -n 7'.split()
        )
        self.assertIn('tests/unit/test_unrelated.py', got[11:])

    def test_vitest_related_gets_the_files_from_frontend(self):
        only = plan('frontend/src/lib/format.test.ts')
        only.backend = {}
        command = picker.commands(only, 1)[0]
        self.assertEqual(command[4:7], ['frontend', 'npx', 'vitest'])
        self.assertEqual(command[7], 'related')
        self.assertIn('src/lib/format.test.ts', command)
        self.assertIn('--run', command)

    def test_a_whole_suite_has_no_file_list(self):
        got = picker.commands(plan('Makefile'), 3)
        self.assertEqual(got[0][-2:], ['-n', '3'])
        self.assertEqual(got[1][-1], 'run')

    def test_the_worker_count_is_the_scripts_unless_overridden(self):
        root = Path('/repository')
        answer = subprocess.CompletedProcess([], 0, stdout='9\n')
        with mock.patch.object(picker.subprocess, 'run', return_value=answer) as run:
            with mock.patch.dict(picker.os.environ, {'PYTEST_WORKERS': ''}):
                self.assertEqual(picker._workers(root), 9)
            command = run.call_args.args[0]
            self.assertEqual(
                command[1:], [str(root / 'scripts/test-workers.py'), 'pytest']
            )
            with mock.patch.dict(picker.os.environ, {'PYTEST_WORKERS': '5'}):
                self.assertEqual(picker._workers(root), 5)

    def test_a_run_runs_every_suite_and_keeps_the_first_failure(self):
        ran = []

        def fake(command, **_):
            ran.append(command)
            return subprocess.CompletedProcess(command, 3 if len(ran) == 1 else 0)

        with (
            mock.patch.object(picker.subprocess, 'run', fake),
            mock.patch.object(picker, 'DiskTree', lambda _root: Memory(FILES)),
            mock.patch.object(picker, '_workers', lambda _root: 2),
            mock.patch('builtins.print'),
        ):
            status = picker.main(['--files', 'Makefile', '--run'])
        self.assertEqual((status, len(ran)), (3, 2))


class TheChangedFiles(unittest.TestCase):
    def test_are_the_branchs_and_the_working_trees(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)

            def git(*args):
                subprocess.run(
                    ['git', '-c', 'user.name=t', '-c', 'user.email=t@t', *args],
                    cwd=root,
                    check=True,
                    capture_output=True,
                )

            git('init', '-b', 'base')
            for name in ('kept', 'edited', 'removed'):
                (root / name).write_text(name)
            git('add', '.')
            git('commit', '-m', 'one')
            git('switch', '-c', 'work')
            (root / 'committed').write_text('c')
            git('add', 'committed')
            git('commit', '-m', 'two')
            (root / 'edited').write_text('changed')
            (root / 'removed').unlink()
            (root / 'untracked').write_text('u')
            self.assertEqual(
                picker.changed_files(root, 'base'),
                ['committed', 'edited', 'removed', 'untracked'],
            )
            # The working tree's list of files, without what was removed.
            self.assertEqual(
                sorted(picker.DiskTree(root).paths()),
                ['committed', 'edited', 'kept', 'untracked'],
            )


if __name__ == '__main__':
    unittest.main()
