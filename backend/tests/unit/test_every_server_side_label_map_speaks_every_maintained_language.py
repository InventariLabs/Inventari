"""A word the server writes into a document, a label or a notification is in
the reader's language for every maintained language.

These maps are their own dictionaries, outside the interface catalogs; a
language missing from one falls back to English in a stored notification, on a
printed jar label or in a location name seeded for a new organization.
"""

from __future__ import annotations

import importlib
import pkgutil
from datetime import date
from typing import Any

import pytest

import app as app_package
from app.core.datetimes import format_date_for
from app.core.product_profiles import MAIN_STORAGE_LOCATION, PRODUCT_PROFILES
from app.i18n import MAINTAINED_LANGUAGES
from app.modules.approvals import _services_notify as approvals_notify
from app.modules.equipment import _notification_labels as equipment_labels
from app.modules.equipment import _protocol_templates as protocol_templates
from app.modules.equipment._module_declarations import build_equipment_metadata
from app.modules.maker import labelling
from app.modules.printing.services import print_queue_service
from app.modules.purchase_orders import _notification_labels as po_labels
from app.modules.recipes import _shopping_from_recipes as shopping
from app.seed_profiles._storage_type_catalogue import seeded_storage_type_names

_FLAT_MAPS: list[tuple[str, dict[str, str]]] = [
    *(
        (f'po.{name}', value)
        for name, value in vars(po_labels).items()
        if name.isupper() and isinstance(value, dict)
    ),
    *(
        (f'equipment.{name}', value)
        for name, value in vars(equipment_labels).items()
        if name.isupper() and isinstance(value, dict)
    ),
    *(
        (f'approvals.{name}', getattr(approvals_notify, name))
        for name in (
            '_NOTIFY_TITLE',
            '_NOTIFY_CONTENT',
            '_NOTIFY_TITLE_NAMED',
            '_NOTIFY_CONTENT_NAMED',
            '_NET_AMOUNT',
            '_OPEN_QUEUE',
            '_DEAD_END_TITLE',
            '_DEAD_END_NAMED_CONTENT',
            '_DEAD_END_OPEN_CONTENT',
            '_REJECT_TITLE',
            '_REJECT_CONTENT',
            '_REJECT_NO_REASON',
            '_REJECT_OPEN_DOC',
            '_APPROVE_TITLE',
            '_APPROVE_CONTENT',
            '_APPROVE_NO_NOTES',
            '_CLOSED_TITLE',
            '_GOES_ON_CONTENT',
            '_STILL_REQUIRED_CONTENT',
        )
    ),
    *(
        (f'approvals.closure.{key}', value)
        for key, value in approvals_notify._CLOSURE_CONTENT.items()
    ),
    *(
        (f'labelling.{name}', getattr(labelling, name))
        for name in ('_INGREDIENTS_WORD', '_CONTAINS_WORD', '_MAY_CONTAIN_WORD')
    ),
    *(
        (f'labelling.allergen.{key}', value)
        for key, value in labelling._ALLERGEN_NAMES.items()
    ),
    *(
        (f'print_queue.{name}', getattr(print_queue_service, name))
        for name in ('_LOT_WORD', '_EXPIRY_WORD', '_MADE_WORD', '_BEST_BEFORE_WORD')
    ),
    *(
        (f'shopping.{name}', getattr(shopping, name))
        for name in ('_SHOPPING_NOTE_LABELS', '_DEFAULT_LIST_NAME_LABELS')
    ),
]
_FLAT_MAPS = [(label, value) for label, value in _FLAT_MAPS if value]


@pytest.mark.parametrize('lang', MAINTAINED_LANGUAGES)
@pytest.mark.parametrize(
    ('label', 'table'), _FLAT_MAPS, ids=[label for label, _ in _FLAT_MAPS]
)
def test_a_label_map_has_an_entry_for_the_language(
    label: str, table: dict[str, str], lang: str
) -> None:
    assert table.get(lang), f'{label} has no {lang} entry'


@pytest.mark.parametrize('lang', MAINTAINED_LANGUAGES)
def test_a_setting_name_exists_in_the_language(lang: str) -> None:
    names = approvals_notify._SETTING_NAMES
    assert names[lang].keys() == names['en'].keys()


def _declared_translations() -> list[tuple[str, dict[str, Any]]]:
    out: list[tuple[str, dict[str, Any]]] = [
        ('main_storage', MAIN_STORAGE_LOCATION.translations)
    ]
    for profile in PRODUCT_PROFILES.values():
        out.extend(
            (f'{profile.id}.{loc.code}', loc.translations)
            for loc in profile.default_locations
        )
    meta = build_equipment_metadata()
    out.extend(
        (f'equipment.{loc.code}', loc.translations)
        for loc in meta.default_storage_locations
    )
    out.extend(
        (f'equipment.type.{t.code}', t.translations)
        for t in meta.storage_types
        if t.translations
    )
    return out


@pytest.mark.parametrize('lang', [x for x in MAINTAINED_LANGUAGES if x != 'en'])
@pytest.mark.parametrize(
    ('label', 'translations'),
    _declared_translations(),
    ids=[label for label, _ in _declared_translations()],
)
def test_a_seeded_location_is_named_in_the_language(
    label: str, translations: dict[str, Any], lang: str
) -> None:
    assert translations.get(lang), f'{label} has no {lang} name'


def test_a_portuguese_document_writes_its_dates_day_first() -> None:
    assert format_date_for('pt', date(2026, 11, 4)) == '04/11/2026'
    assert format_date_for('pt-BR', date(2026, 11, 4)) == '04/11/2026'


def _is_label_map(value: object) -> bool:
    """A table keyed by language that already speaks a language beyond Polish.

    A table with English and Polish only is the owner-facing kind (a report in
    the owner's language) and is out of this rule; one that carries any of the
    other maintained languages has declared itself a reader-facing table.
    """
    if not isinstance(value, dict) or 'en' not in value:
        return False
    keys = set(value)
    return keys <= {*MAINTAINED_LANGUAGES, 'pt-BR'} and bool(
        keys & {'de', 'fr', 'es', 'pt'}
    )


def _discover_label_maps() -> list[tuple[str, dict[str, Any]]]:
    found: list[tuple[str, dict[str, Any]]] = []
    for info in pkgutil.walk_packages(app_package.__path__, 'app.'):
        # Tests mirror the maps they check, and a migration needs a live
        # Alembic context to import.
        if '.tests.' in info.name or '.migrations' in info.name:
            continue
        module = importlib.import_module(info.name)
        for name, value in vars(module).items():
            if _is_label_map(value):
                found.append((f'{info.name}.{name}', value))
    return found


_DISCOVERED = _discover_label_maps()


def test_the_discovery_finds_the_known_maps() -> None:
    names = {label for label, _ in _DISCOVERED}
    assert 'app.modules.webhooks._notification_labels.AUTO_DISABLED_TITLE' in names
    assert 'app.modules.recipes._meal_plan_shopping._NOTES_LABELS' in names
    assert 'app.modules.equipment._protocol_templates.LABELS' in names
    assert 'app.modules.purchase_orders._service_email._PO_EMAIL_CONTENT' in names


@pytest.mark.parametrize('lang', MAINTAINED_LANGUAGES)
@pytest.mark.parametrize(
    ('label', 'table'), _DISCOVERED, ids=[label for label, _ in _DISCOVERED]
)
def test_every_discovered_label_map_has_the_language(
    label: str, table: dict[str, Any], lang: str
) -> None:
    assert table.get(lang), f'{label} has no {lang} entry'


@pytest.mark.parametrize('lang', MAINTAINED_LANGUAGES)
def test_every_seeded_storage_type_is_named_in_the_language(lang: str) -> None:
    missing = [
        code for code, names in seeded_storage_type_names().items() if lang not in names
    ]
    assert not missing, f'no {lang} name for storage types {missing}'


@pytest.mark.parametrize('lang', MAINTAINED_LANGUAGES)
def test_a_protocol_names_every_heading_in_the_language(lang: str) -> None:
    labels = protocol_templates.LABELS
    assert labels[lang].keys() == labels['en'].keys()


def test_a_portuguese_protocol_is_not_headed_in_english() -> None:
    labels = protocol_templates.LABELS
    assert labels['pt']['checkout_title'] != labels['en']['checkout_title']
    assert labels['pt']['checkin_title'] != labels['en']['checkin_title']
