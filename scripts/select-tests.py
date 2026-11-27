#!/usr/bin/env python3
"""Pick the tests a change can affect, for the rounds before the full suite.

    python3 scripts/select-tests.py                  # the plan for this branch
    python3 scripts/select-tests.py --run            # print the plan, then run it
    python3 scripts/select-tests.py --files A B      # the plan for these files
    python3 scripts/select-tests.py --base main      # compare with another ref

The changed files are the difference between the merge base of `--base`
(default `origin/dev`) with HEAD and the working tree, untracked files
included. `--run` runs the plan on the stack of this tree (`docker compose`,
under the wrapper that names the stack), with the worker count
`scripts/test-workers.py` gives (`PYTEST_WORKERS` overrides it).

A quick run is not the gate: the full suites, with their coverage floors, run
once before the branch leaves (AGENTS.md, the pre-push gate). A test this
picker misses is caught there.

Backend. A change this picker cannot place runs the whole suite, and the plan
says why: the core (everything under `backend/app/` outside `modules/`), a
migration, a `conftest.py` and what the shared ones import, shared fixtures,
the pytest, dependency and image configuration, the Makefile, a compose file,
a deleted test helper, a backend file no test names. Otherwise it picks:

- a change inside a module: the module's tests, the tests that import it
  (directly or through other files), the tests that name it (an import path, a
  route, its name as a string) and the tests of the modules that require it;
- a changed test file, and the tests that import a changed test helper;
- a changed file tests read by its name (documents, data, scripts);
- the tests that read the repository itself (walk a directory, parse the
  sources, list the routes or tables), because an import graph cannot see what
  they depend on.

Frontend. Vitest's own `related` picks the test files whose imports reach a
changed file; to it are added the tests that name a changed file and the tests
that read files from disk. The build and test configuration, and a deleted
source file, run the whole suite. The browser specs have their own picker,
`frontend/scripts/select-e2e-specs.mjs`.
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import re
import subprocess
import sys
from collections import Counter, deque
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

#: A change to one of these changes what every test of both sides runs on.
BOTH_SUITES = re.compile(r'^(Makefile|docker-compose[^/]*\.ya?ml)$')
BACKEND_CONFIG = {
    'backend/pyproject.toml': 'the pytest and dependency configuration',
    'backend/uv.lock': 'the dependency lock',
    'backend/pytest.ini': 'the pytest configuration',
    'backend/alembic.ini': 'the migration configuration',
    'backend/Dockerfile': 'the image the tests run in',
}
FRONTEND_CONFIG = re.compile(
    r'^frontend/(package(-lock)?\.json|tsconfig[^/]*\.json|'
    r'[^/]*\.config\.[cm]?[jt]s|Dockerfile[^/]*|src/test/setup\.ts|'
    r'src/test/consoleGate(Global)?\.ts|src/test/console-baseline\.json)$'
)
#: Playwright's own configuration is not Vitest's.
NOT_VITEST_CONFIG = {'frontend/playwright.config.ts'}

#: A backend test whose source matches reads the code base as data, so what it
#: depends on is not in its imports.
READS_THE_REPOSITORY = re.compile(
    r'\.r?glob\(|os\.walk\(|\.iterdir\(|ast\.parse\(|\.routes\b|\.openapi\(\)'
    r'|__subclasses__\(|inspect\.getsource|INVENTARI_REPO_ROOT'
    # A script loaded by its path runs over whatever the script reads.
    r'|spec_from_file_location\('
)
#: The same for a frontend test: Vitest's `related` follows imports only.
READS_FROM_DISK = re.compile(
    r'\b(readFileSync|readdirSync|readFile|readdir|globSync)\('
)

#: File names several directories have: a test names such a file by its
#: directory too.
COMMON_NAMES = 3


class Tree:
    """The files of one state of the repository."""

    def paths(self) -> list[str]:
        raise NotImplementedError

    def read(self, path: str) -> str:
        raise NotImplementedError


class DiskTree(Tree):
    """The working tree: what git tracks and what it would track."""

    def __init__(self, root: Path):
        self.root = root
        self._paths: list[str] | None = None

    def paths(self) -> list[str]:
        if self._paths is None:
            out = _git(
                self.root,
                'ls-files',
                '-z',
                '--cached',
                '--others',
                '--exclude-standard',
            )
            # A file deleted in the working tree is still in the index.
            self._paths = [
                p for p in out.split('\0') if p and (self.root / p).is_file()
            ]
        return self._paths

    def read(self, path: str) -> str:
        try:
            return (self.root / path).read_text(encoding='utf-8', errors='replace')
        except OSError:
            return ''


@dataclass
class Plan:
    #: Why the whole suite runs; empty when a selection does.
    backend_full: list[str] = field(default_factory=list)
    frontend_full: list[str] = field(default_factory=list)
    #: Test file (relative to the repository root) -> why it was picked.
    backend: dict[str, str] = field(default_factory=dict)
    #: Files handed to `vitest related` -> why: changed files and test files.
    frontend: dict[str, str] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)


def _is_backend_test(path: str) -> bool:
    name = PurePosixPath(path).name
    return (
        path.startswith(('backend/tests/', 'backend/app/'))
        and name.startswith('test_')
        and name.endswith('.py')
    )


def _is_frontend_test(path: str) -> bool:
    return path.startswith(('frontend/src/', 'frontend/scripts/')) and bool(
        re.search(r'\.(test|spec)\.[cm]?[jt]sx?$', path)
    )


def _in_tests_dir(path: str) -> bool:
    return path.startswith('backend/') and 'tests' in PurePosixPath(path).parts[1:-1]


def _module_of(path: str) -> str | None:
    """The module a backend file belongs to."""
    parts = PurePosixPath(path).parts
    if parts[:3] == ('backend', 'app', 'modules') and len(parts) > 4:
        return parts[3]
    return None


def _is_core(path: str) -> bool:
    """A file of the platform every module leans on."""
    return path.startswith('backend/app/') and not (
        _module_of(path) or _in_tests_dir(path)
    )


def imported_names(path: str, text: str) -> list[tuple[list[str], bool]]:
    """The dotted names a file imports, from its directory under `backend/`; the
    flag marks a name written as a string, whose last part may be an attribute."""
    package = list(PurePosixPath(path).parts[1:-1])
    found: list[tuple[list[str], bool]] = []
    for node in ast.walk(ast.parse(text)):
        if isinstance(node, ast.Import):
            found.extend((alias.name.split('.'), False) for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            base = package[: len(package) - node.level + 1] if node.level else []
            prefix = base + (node.module.split('.') if node.module else [])
            found.append((prefix, False))
            found.extend(([*prefix, alias.name], False) for alias in node.names)
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            # `patch('app.modules.x.y.name')`, `importlib.import_module(…)`.
            if re.fullmatch(r'(app|tests)(\.\w+)+', node.value):
                found.append((node.value.split('.'), True))
    return found


class ImportGraph:
    """Who imports whom among the Python files under `backend/`."""

    def __init__(self, tree: Tree, *, read: bool = True):
        self.files = {
            p
            for p in (tree.paths() if read else ())
            if p.startswith('backend/') and p.endswith('.py')
        }
        self.imports: dict[str, set[str]] = {}
        self.unparsed: set[str] = set()
        for path in self.files:
            try:
                self.imports[path] = self._edges(path, tree.read(path))
            except (SyntaxError, ValueError):
                self.unparsed.add(path)
        self.importers: dict[str, set[str]] = {}
        for source, targets in self.imports.items():
            for target in targets:
                self.importers.setdefault(target, set()).add(source)

    def _resolve(self, parts: list[str]) -> set[str]:
        """The files a dotted name stands for."""
        stem = 'backend/' + '/'.join(parts)
        return {p for p in (f'{stem}.py', f'{stem}/__init__.py') if p in self.files}

    def _edges(self, path: str, text: str) -> set[str]:
        found: set[str] = set()
        for parts, fallback in imported_names(path, text):
            found |= self._resolve(parts) or (
                self._resolve(parts[:-1]) if fallback else set()
            )
        found.discard(path)
        return found

    def reaching(self, roots: list[str]) -> dict[str, str]:
        """Every file that imports one of `roots`, at any depth -> that root.

        The walk does not continue past the core: a core file that imports a
        module wires it in (the application, a model's type), and every test
        imports the application or the models."""
        seen = {root: root for root in roots}
        queue = deque(roots)
        while queue:
            current = queue.popleft()
            if _is_core(current):
                continue
            for importer in sorted(self.importers.get(current, ())):
                if importer not in seen:
                    seen[importer] = seen[current]
                    queue.append(importer)
        return seen

    def imported_by_shared_conftests(self) -> set[str]:
        """What the conftests outside the modules import, helpers' imports too."""
        queue = deque(
            p
            for p in self.files
            if PurePosixPath(p).name == 'conftest.py' and not _module_of(p)
        )
        seen: set[str] = set()
        while queue:
            for target in self.imports.get(queue.popleft(), ()):
                if target not in seen:
                    seen.add(target)
                    # A helper's imports run with the conftest; the application's
                    # own imports are the core rule's business.
                    if _in_tests_dir(target):
                        queue.append(target)
        return seen


def _dependent_modules(tree: Tree, changed: set[str]) -> dict[str, str]:
    """Modules that require a changed one, at any depth -> the changed one."""
    required_by: dict[str, set[str]] = {}
    for path in tree.paths():
        parts = PurePosixPath(path).parts
        if parts[:3] != ('backend', 'app', 'modules') or parts[4:] != (
            'manifest.json',
        ):
            continue
        try:
            manifest = json.loads(tree.read(path))
        except ValueError:
            continue
        for key in ('requires', 'optional_requires'):
            for other in manifest.get(key) or ():
                required_by.setdefault(other, set()).add(parts[3])
    found: dict[str, str] = {}
    queue = deque((name, name) for name in sorted(changed))
    while queue:
        name, root = queue.popleft()
        for dependent in sorted(required_by.get(name, ())):
            if dependent not in changed and dependent not in found:
                found[dependent] = root
                queue.append((dependent, root))
    return found


def _names_module(module: str) -> re.Pattern[str]:
    route = module.replace('_', '-')
    return re.compile(
        rf'app\.modules\.{module}\b|modules/{module}\b'
        rf'|[\'"]{module}[\'":]|/({module}|{route})(?=[/\'"?])'
    )


def _name_pattern(path: str, names: Counter[str]) -> re.Pattern[str]:
    """How a test names a file: by its name, or with its directory when the name
    alone says nothing about which file is meant."""
    pure = PurePosixPath(path)
    if names[pure.name] >= COMMON_NAMES and pure.parent.name:
        text = (
            re.escape(pure.parent.name)
            + r'[\'"]?\s*[/,]\s*[\'"]?'
            + re.escape(pure.name)
        )
    else:
        text = re.escape(pure.name)
    return re.compile(rf'(?<![\w.-]){text}(?![\w-])')


class _Picker:
    """One selection: the changed files are sorted into the plan's refusals and
    into what the rules then follow."""

    def __init__(self, changed: list[str], tree: Tree):
        self.changed = changed
        self.tree = tree
        self.plan = Plan()
        paths = tree.paths()
        self.present = set(paths)
        # Reading every import takes seconds; only a Python change needs them.
        python = any(p.startswith('backend/') and p.endswith('.py') for p in changed)
        self.graph = ImportGraph(tree, read=python)
        self.shared = self.graph.imported_by_shared_conftests()
        self.backend_tests = {p: tree.read(p) for p in paths if _is_backend_test(p)}
        self.frontend_tests = {p: tree.read(p) for p in paths if _is_frontend_test(p)}
        self.names = Counter(PurePosixPath(p).name for p in paths)
        self.roots: list[str] = []  # Python files whose importers' tests run
        self.modules: set[str] = set()  # modules with a changed file
        self.named: list[str] = []  # changed files the tests may name
        # Backend files nothing places unless a test imports or names them.
        self.must_be_named: set[str] = set()
        self.frontend_changed = False

    def whole_backend(self, path: str, why: str) -> None:
        self.plan.backend_full.append(f'{path}: {why}')

    def whole_frontend(self, path: str, why: str) -> None:
        self.plan.frontend_full.append(f'{path}: {why}')

    def sort(self, path: str) -> None:
        if BOTH_SUITES.match(path):
            self.whole_backend(path, 'what every test runs on')
            self.whole_frontend(path, 'what every test runs on')
        elif path.startswith('backend/'):
            self.sort_backend(path)
        elif path.startswith('frontend/'):
            self.sort_frontend(path)
        else:
            self.named.append(path)

    def unplaceable(self, path: str) -> str | None:
        """Why a backend change runs the whole suite, when its place says so."""
        pure = PurePosixPath(path)
        if path in BACKEND_CONFIG:
            return BACKEND_CONFIG[path]
        if pure.name == 'conftest.py':
            return 'fixtures'
        if 'migrations' in pure.parts[1:-1]:
            return 'a migration changes the database the tests build'
        if path.startswith('backend/tests/fixtures/'):
            return 'a shared fixture'
        if path in self.shared:
            return 'a shared conftest imports it'
        if path in self.graph.unparsed:
            return 'it does not parse as Python'
        if _in_tests_dir(path):
            if path not in self.present and not _is_backend_test(path):
                return 'a deleted test helper: its users are not known'
        elif _is_core(path):
            return 'the core'
        return None

    def sort_backend(self, path: str) -> None:
        here = path in self.present
        if path.endswith('.md'):
            self.named.append(path)
            return
        # The frontend's tests read the application's files, manifests first.
        if path.startswith('backend/app/') and not _in_tests_dir(path):
            self.frontend_changed = True
            self.named.append(path)
        why = self.unplaceable(path)
        if why:
            self.whole_backend(path, why)
            return
        if _is_backend_test(path):
            if here:
                self.plan.backend[path] = 'changed test'
            return
        if here and path.endswith('.py'):
            self.roots.append(path)
        module = _module_of(path)
        if module and not _in_tests_dir(path):
            self.modules.add(module)
        else:
            self.must_be_named.add(path)

    def sort_frontend(self, path: str) -> None:
        self.named.append(path)
        if FRONTEND_CONFIG.match(path) and path not in NOT_VITEST_CONFIG:
            self.whole_frontend(path, 'the build and test configuration')
        elif path.startswith('frontend/tests/e2e/'):
            self.plan.notes.append(
                f'{path}: a browser spec file;'
                ' frontend/scripts/select-e2e-specs.mjs picks those'
            )
        else:
            self.frontend_changed = True
            if path.endswith('.md'):
                return
            if path in self.present:
                self.plan.frontend[path] = (
                    'changed test' if _is_frontend_test(path) else 'changed file'
                )
            elif path.startswith('frontend/src/') and not _is_frontend_test(path):
                self.whole_frontend(
                    path, 'a deleted source file: Vitest cannot follow it'
                )

    def follow_imports(self) -> None:
        for path, root in self.graph.reaching(self.roots).items():
            if path in self.backend_tests:
                why = f'imports {root.removeprefix("backend/")}'
                self.plan.backend.setdefault(path, why)

    def follow_modules(self) -> None:
        """A module's tests, the tests that name it, the tests of its dependents."""
        for module in sorted(self.modules):
            pattern = _names_module(module)
            for test, text in self.backend_tests.items():
                if _module_of(test) == module:
                    why = f'tests of the changed module {module}'
                    self.plan.backend.setdefault(test, why)
                elif pattern.search(text):
                    why = f'names the changed module {module}'
                    self.plan.backend.setdefault(test, why)
        for dependent, root in _dependent_modules(self.tree, self.modules).items():
            for test in self.backend_tests:
                if _module_of(test) == dependent:
                    why = f'tests of {dependent}, which requires {root}'
                    self.plan.backend.setdefault(test, why)

    def follow_names(self) -> None:
        for path in [*self.named, *sorted(self.must_be_named - set(self.named))]:
            name = PurePosixPath(path).name
            pattern = _name_pattern(path, self.names)
            found = False
            for tests, picked in (
                (self.backend_tests, self.plan.backend),
                (self.frontend_tests, self.plan.frontend),
            ):
                for test, text in tests.items():
                    # The substring check first: most tests say nothing of it.
                    if name in text and pattern.search(text):
                        picked.setdefault(test, f'names {name}')
                        found = found or picked is self.plan.backend
            if path in self.must_be_named and not found:
                reached = self.graph.reaching([path])
                if not any(t in self.backend_tests for t in reached):
                    self.whole_backend(path, 'no test imports or names it')

    def add_the_readers(self) -> None:
        """The tests that read the repository, which no import graph places."""
        outside_docs = [
            p
            for p in self.changed
            if not (p.startswith('backend/') and p.endswith('.md'))
        ]
        if outside_docs:
            backend = any(p.startswith('backend/') for p in outside_docs)
            # For a change outside the backend, only the readers of that part.
            areas = sorted({PurePosixPath(p).parts[0] for p in outside_docs})
            area = re.compile('|'.join(rf'[\'"/]{re.escape(a)}[\'"/]' for a in areas))
            for test, text in self.backend_tests.items():
                if READS_THE_REPOSITORY.search(text) and (backend or area.search(text)):
                    self.plan.backend.setdefault(test, 'reads the repository')
        if self.frontend_changed:
            for test, text in self.frontend_tests.items():
                if READS_FROM_DISK.search(text):
                    self.plan.frontend.setdefault(test, 'reads files from disk')


def select(changed: list[str], tree: Tree) -> Plan:
    """The tests the changed files (relative to the repository root) can affect."""
    picker = _Picker(changed, tree)
    for path in changed:
        picker.sort(path)
    picker.follow_imports()
    picker.follow_modules()
    picker.follow_names()
    picker.add_the_readers()
    plan = picker.plan
    if plan.backend_full:
        plan.backend = {}
    if plan.frontend_full:
        plan.frontend = {}
    return plan


def render(plan: Plan, tree: Tree) -> list[str]:
    """The plan as the lines the tool prints."""
    out = list(plan.notes)
    total = sum(1 for p in tree.paths() if _is_backend_test(p))
    if plan.backend_full:
        out.append('backend: the whole suite')
        out.extend(f'  because {why}' for why in plan.backend_full)
    elif plan.backend:
        out.append(f'backend: {len(plan.backend)} of {total} test files')
        out.extend(_grouped(plan.backend))
    else:
        out.append('backend: no test is affected')
    if plan.frontend_full:
        out.append('frontend: the whole suite')
        out.extend(f'  because {why}' for why in plan.frontend_full)
    elif plan.frontend:
        out.append(f'frontend: the tests Vitest relates to {len(plan.frontend)} files')
        out.extend(_grouped(plan.frontend))
    else:
        out.append('frontend: no test is affected')
    return out


def _grouped(picked: dict[str, str]) -> list[str]:
    groups: dict[str, list[str]] = {}
    for path, why in picked.items():
        groups.setdefault(why, []).append(path)
    out = []
    for why in sorted(groups):
        out.append(f'  {why} ({len(groups[why])}):')
        out.extend(f'    {path}' for path in sorted(groups[why]))
    return out


def commands(plan: Plan, workers: int) -> list[list[str]]:
    """The commands that run the plan on the stack `docker compose` names."""
    found = []
    pytest = ['docker', 'compose', 'exec', '-T', 'backend', 'uv', 'run', 'pytest', '-q']
    pytest += ['-n', str(workers)]
    if plan.backend_full:
        found.append(pytest)
    elif plan.backend:
        found.append(pytest + sorted(p.removeprefix('backend/') for p in plan.backend))
    vitest = ['docker', 'compose', 'exec', '-T', 'frontend', 'npx', 'vitest']
    if plan.frontend_full:
        found.append([*vitest, 'run'])
    elif plan.frontend:
        files = sorted(p.removeprefix('frontend/') for p in plan.frontend)
        found.append([*vitest, 'related', *files, '--run', '--passWithNoTests'])
    return found


def _git(root: Path, *args: str) -> str:
    return subprocess.run(
        ['git', *args], cwd=root, capture_output=True, text=True, check=True
    ).stdout


def changed_files(root: Path, base: str) -> list[str]:
    """What differs between the merge base of `base` with HEAD and the working tree."""
    since = _git(root, 'merge-base', base, 'HEAD').strip()
    diff = _git(root, 'diff', '--name-only', '--no-renames', '-z', since)
    new = _git(root, 'ls-files', '--others', '--exclude-standard', '-z')
    return sorted({p for p in (diff + new).split('\0') if p})


def _workers(root: Path) -> int:
    if os.environ.get('PYTEST_WORKERS'):
        return int(os.environ['PYTEST_WORKERS'])
    script = root / 'scripts' / 'test-workers.py'
    out = subprocess.run(
        [sys.executable, str(script), 'pytest'],
        capture_output=True,
        text=True,
        check=True,
    )
    return int(out.stdout.strip())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument('--run', action='store_true', help='run the plan')
    which = parser.add_mutually_exclusive_group()
    which.add_argument(
        '--files', nargs='+', help='changed files, from the repository root'
    )
    which.add_argument(
        '--base', default='origin/dev', help='the ref the branch started from'
    )
    args = parser.parse_args(argv)
    root = Path(__file__).resolve().parents[1]
    if args.files:
        files = args.files
    else:
        try:
            files = changed_files(root, args.base)
        except subprocess.CalledProcessError as error:
            print(
                f'cannot compare with {args.base}: {error.stderr.strip()}',
                file=sys.stderr,
            )
            return 2
    tree = DiskTree(root)
    plan = select(files, tree)
    print(f'{len(files)} changed files')
    print('\n'.join(render(plan, tree)), flush=True)
    if not args.run:
        return 0
    status = 0
    for command in commands(plan, _workers(root)):
        print(
            f'$ {" ".join(command[:10])}{" …" if len(command) > 10 else ""}', flush=True
        )
        # Every suite runs, and the first failure's status is the answer.
        status = subprocess.run(command, cwd=root).returncode or status
    return status


if __name__ == '__main__':
    sys.exit(main())
