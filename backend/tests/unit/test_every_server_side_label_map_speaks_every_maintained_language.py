"""A word the server writes into a document, a label or a notification is in
the reader's language for every maintained language.

These maps are their own dictionaries, outside the interface catalogs; a
language missing from one falls back to English in a stored notification, on a
printed jar label or in a location name seeded for a new organization.
"""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest

from app.core.datetimes import format_date_for
from app.core.product_profiles import MAIN_STORAGE_LOCATION, PRODUCT_PROFILES
from app.i18n import MAINTAINED_LANGUAGES
from app.modules.approvals import _services_notify as approvals_notify
from app.modules.equipment import _notification_labels as equipment_labels
from app.modules.equipment._module_declarations import build_equipment_metadata
from app.modules.maker import labelling
from app.modules.printing.services import print_queue_service
from app.modules.purchase_orders import _notification_labels as po_labels
from app.modules.recipes import _shopping_from_recipes as shopping

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
