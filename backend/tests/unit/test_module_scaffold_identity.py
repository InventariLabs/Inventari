"""A scaffolded module must be about itself, not about the module it was copied from.

`make new-module` copies the reference module and substitutes names. It
substituted two: `name` and `display_name`. Everything else in the manifest
survived — the description ("Manage simple widgets with name, color, and
quantity"), which the App Store prints verbatim as the first thing anyone reads
about the new module; the reference's icon; its `system` category; and the
template's own version number. Five translation catalogs came along describing
widgets, and because only the English strings carrying "Example Widgets" were
substituted, the Polish page title stayed "Widgety".
"""

from __future__ import annotations

import ast
import json
import shutil
from pathlib import Path

import pytest

from app.cli import module_generator

REFERENCE = Path(module_generator.__file__).resolve().parents[1] / 'modules'


@pytest.fixture
def scaffold(tmp_path, monkeypatch):
    """Generate a module into a throwaway tree holding a copy of the reference."""
    modules_dir = tmp_path / 'modules'
    modules_dir.mkdir()
    shutil.copytree(
        REFERENCE / module_generator.REFERENCE_MODULE,
        modules_dir / module_generator.REFERENCE_MODULE,
        ignore=shutil.ignore_patterns('__pycache__', '*.pyc'),
    )
    monkeypatch.setattr(module_generator, 'MODULES_DIR', modules_dir)

    module_generator.create_module('warranty_tracker')
    return modules_dir / 'warranty_tracker'


@pytest.mark.unit
class TestScaffoldedManifest:
    def test_the_description_is_not_about_widgets(self, scaffold):
        manifest = json.loads((scaffold / 'manifest.json').read_text())

        assert 'widget' not in manifest['description'].lower()
        assert 'reference module' not in manifest['description'].lower()

    def test_it_starts_at_its_own_first_version(self, scaffold):
        manifest = json.loads((scaffold / 'manifest.json').read_text())

        assert manifest['version'] == '0.1.0'

    def test_it_does_not_inherit_the_reference_icon_or_category(self, scaffold):
        manifest = json.loads((scaffold / 'manifest.json').read_text())
        reference = json.loads(
            (
                REFERENCE / module_generator.REFERENCE_MODULE / 'manifest.json'
            ).read_text()
        )

        assert manifest['icon'] != reference['icon']
        assert manifest['category'] != reference['category']

    def test_the_reference_flag_does_not_travel(self, scaffold):
        """A module carrying it would be registered, working and unfindable."""
        manifest = json.loads((scaffold / 'manifest.json').read_text())

        assert 'is_reference' not in manifest

    def test_the_display_name_capitalises_every_word(self, scaffold):
        """The store's neighbours are Purchase Orders and Stock Takes, not
        Purchase orders — `str.capitalize()` made every scaffolded module the
        odd one out."""
        manifest = json.loads((scaffold / 'manifest.json').read_text())

        assert manifest['display_name'] == 'Warranty Tracker'


@pytest.mark.unit
class TestScaffoldedCatalogs:
    def test_no_language_still_talks_about_widgets(self, scaffold):
        for catalog in (scaffold / 'i18n').glob('*.json'):
            text = catalog.read_text().lower()
            assert 'widget' not in text, f'{catalog.name} still describes widgets'

    def test_every_required_language_is_still_present(self, scaffold):
        """Emptying the catalogs must not drop the files: module validation
        requires one per language."""
        written = sorted(p.name for p in (scaffold / 'i18n').glob('*.json'))

        assert written == ['de.json', 'en.json', 'es.json', 'fr.json', 'pl.json']

    def test_the_catalogs_are_valid_and_empty(self, scaffold):
        for catalog in (scaffold / 'i18n').glob('*.json'):
            assert json.loads(catalog.read_text()) == {}


@pytest.fixture
def shipped_tree(tmp_path, monkeypatch):
    """A throwaway tree with the reference module and a copy of the shipped list."""
    modules_dir = tmp_path / 'app' / 'modules'
    modules_dir.mkdir(parents=True)
    shutil.copytree(
        REFERENCE / module_generator.REFERENCE_MODULE,
        modules_dir / module_generator.REFERENCE_MODULE,
        ignore=shutil.ignore_patterns('__pycache__', '*.pyc'),
    )
    (tmp_path / 'app' / 'core').mkdir()
    shutil.copy(
        REFERENCE.parent / 'core' / 'module_safety.py',
        tmp_path / 'app' / 'core' / 'module_safety.py',
    )
    monkeypatch.setattr(module_generator, 'MODULES_DIR', modules_dir)
    return tmp_path / 'app' / 'core' / 'module_safety.py'


def _shipped(source: str) -> list[str]:
    """The names REPO_SHIPPED_MODULES lists, in file order."""
    for node in ast.parse(source).body:
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == 'REPO_SHIPPED_MODULES'
            for t in node.targets
        ):
            assert isinstance(node.value, ast.Set)
            return [ast.literal_eval(e) for e in node.value.elts]
    raise AssertionError('REPO_SHIPPED_MODULES not found')


@pytest.mark.unit
class TestTheScaffoldIsShipped:
    """An in-tree module the list does not name is refused at startup.

    The registry lets a manifest claim ``official`` only for a directory on
    REPO_SHIPPED_MODULES, and the scaffold's manifest claims it — so a module
    made by ``make new-module`` was rejected at the next backend start, with
    nothing in the generator or the quick start saying why.
    """

    def test_the_new_module_is_put_on_the_list_in_order(self, shipped_tree):
        before = _shipped(shipped_tree.read_text())

        module_generator.create_module('warranty_tracker')

        after = _shipped(shipped_tree.read_text())
        at = after.index('warranty_tracker')
        assert after[at + 1] > 'warranty_tracker' > after[at - 1]
        # No other entry moves: the list is not sorted ('warehouse' sits near
        # the top), and re-sorting it put every unrelated line in the diff.
        assert [name for name in after if name != 'warranty_tracker'] == before

    def test_nothing_else_in_the_file_changes(self, shipped_tree):
        before = shipped_tree.read_text().splitlines()

        module_generator.create_module('warranty_tracker')

        after = shipped_tree.read_text().splitlines()
        assert [line for line in after if line not in before] == [
            "    'warranty_tracker',"
        ]
        assert len(after) == len(before) + 1
