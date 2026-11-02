"""The manifest declares that a module has settings; the method implements them.

``BaseModule.get_settings_schema`` is where a module's settings actually live,
but it is a Python method, so the *fact* that a module has any was only
readable by importing the module — or, as the frontend was doing, by matching
a regex against ``module.py``. That scan is wrong in both directions: it reads
another language's source as text, and it cannot run in the frontend container,
which mounts ``./frontend`` and nothing else.

So the fact moves into ``manifest.json``, where declarations belong, and this
test is what keeps the declaration true. `approvals` is the case that shows why
the regex was never safe: it attaches its schema with an assignment rather than
a ``def``, so a scan looking for a definition would miss it and a scan looking
for the name would match a comment.
"""

import json
from pathlib import Path

import pytest

from app.core.module_manifest_schema import ModuleManifest
from app.core.module_registry import module_registry

MODULES_DIR = Path(__file__).resolve().parents[2] / 'app' / 'modules'


def _discovered_instances() -> dict[str, object]:
    if not module_registry.get_all():
        module_registry.discover_modules()
    return {m.metadata.name: m for m in module_registry.get_all()}


def _manifests() -> list[ModuleManifest]:
    return [
        ModuleManifest(**json.loads(path.read_text()))
        for path in sorted(MODULES_DIR.glob('*/manifest.json'))
    ]


def _settings_fields(schema: dict, prefix: str = ''):
    """Every leaf field of a settings schema, with its dotted path.

    `recipes` groups a field under an object (`jina.api_key`), so the walk has
    to descend rather than read the top level only.
    """
    for name, field in (schema.get('properties') or {}).items():
        path = f'{prefix}.{name}' if prefix else name
        if isinstance(field, dict) and field.get('properties'):
            yield from _settings_fields(field, path)
        elif isinstance(field, dict):
            yield path, field


@pytest.mark.unit
class TestManifestSettingsSchema:
    def test_the_declaration_matches_the_method(self):
        instances = _discovered_instances()
        mismatches = []

        for manifest in _manifests():
            instance = instances.get(manifest.name)
            # A module the registry rejected is another test's problem; here it
            # would only produce a second, misleading failure.
            if instance is None:
                continue

            implemented = instance.get_settings_schema() is not None
            if implemented != manifest.has_settings_schema:
                mismatches.append(
                    f'{manifest.name}: manifest says '
                    f'has_settings_schema={manifest.has_settings_schema}, '
                    f'get_settings_schema() says {implemented}'
                )

        assert not mismatches, (
            'manifest.json disagrees with the module about its settings:\n  '
            + '\n  '.join(mismatches)
        )

    def test_the_declaration_is_not_vacuous(self):
        # Without this, a run where nothing declares settings would pass by
        # describing an empty world — which is exactly how the frontend scan
        # this replaces managed to be green while reading no files at all.
        declared = {m.name for m in _manifests() if m.has_settings_schema}

        assert 'recipes' in declared
        assert len(declared) >= 2

    def test_every_settings_field_names_an_i18n_key(self):
        """A field's label reaches the screen as written unless a key names it.

        The generic settings screen renders the schema the backend sends, and
        a Python string in a manifest has no translation. `approvals` shipped
        one: the whole screen spoke the reader's language except the single
        setting on it, in English.
        """
        untranslated = []

        for name, instance in sorted(_discovered_instances().items()):
            schema = instance.get_settings_schema()
            if not schema:
                continue
            for path, field in _settings_fields(schema):
                for text, key in (
                    ('title', 'title_key'),
                    ('description', 'description_key'),
                ):
                    if field.get(text) and not field.get(key):
                        untranslated.append(f'{name}.{path}: {text} without {key}')

        assert not untranslated, (
            'settings fields whose text reaches the screen untranslated:\n  '
            + '\n  '.join(untranslated)
        )

    def test_a_module_without_settings_says_so_by_default(self):
        # The flag is opt-in: a manifest that omits it declares "no settings",
        # so adding the field did not silently change what existing modules say.
        assert (
            ModuleManifest(
                name='maker', version='1.0.0', module_type='community'
            ).has_settings_schema
            is False
        )
