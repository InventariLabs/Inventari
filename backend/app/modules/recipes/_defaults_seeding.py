"""Seeding and deduplication for ingredient nutrition defaults.

Extracted from defaults_service.py to keep it under the 400 LOC quality
gate. Handles idempotent system-default seeding from JSON files and
stale name_normalized deduplication.
"""

from __future__ import annotations

import json
import uuid
from collections import defaultdict
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger

from ._name_matching import normalize_name
from .defaults_service import _opt_decimal
from .models import IngredientNutritionDefault

log = get_logger(__name__)

_DATA_DIR = Path(__file__).parent / 'data'

_SEED_FILES: dict[str, Path] = {
    'pl': _DATA_DIR / 'defaults_pl.json',
    'en': _DATA_DIR / 'defaults_en.json',
}


async def seed_system_defaults(db: AsyncSession) -> int:
    """Idempotent seed of system defaults from JSON files.

    Inserts rows only if they don't already exist (based on lang + name_normalized).
    Returns the number of newly inserted rows.
    """
    new_objects: list[IngredientNutritionDefault] = []
    for lang, path in _SEED_FILES.items():
        if not path.exists():
            log.warning('seed_system_defaults: file not found %s', path)
            continue

        with path.open(encoding='utf-8') as fh:
            entries: list[dict[str, Any]] = json.load(fh)

        result = await db.execute(
            select(IngredientNutritionDefault.name_normalized).where(
                IngredientNutritionDefault.organization_id.is_(None),
                IngredientNutritionDefault.lang == lang,
            )
        )
        existing_names: set[str] = {row[0] for row in result.all()}

        for entry in entries:
            normalized = normalize_name(entry['name'])
            if normalized in existing_names:
                continue

            new_objects.append(
                IngredientNutritionDefault(
                    id=uuid.uuid4(),
                    organization_id=None,
                    lang=lang,
                    name=entry['name'],
                    name_normalized=normalized,
                    calories_kcal=Decimal(str(entry['calories_kcal'])),
                    protein_g=_opt_decimal(entry.get('protein_g')),
                    fat_g=_opt_decimal(entry.get('fat_g')),
                    carbs_g=_opt_decimal(entry.get('carbs_g')),
                    fiber_g=_opt_decimal(entry.get('fiber_g')),
                    sugar_g=_opt_decimal(entry.get('sugar_g')),
                    salt_g=_opt_decimal(entry.get('salt_g')),
                    source='system',
                    is_system=True,
                )
            )
            existing_names.add(normalized)

    if new_objects:
        db.add_all(new_objects)
    await db.flush()
    log.info('seed_system_defaults: inserted %d rows', len(new_objects))
    return len(new_objects)


async def deduplicate_defaults(db: AsyncSession) -> int:
    """Fix stale ``name_normalized`` values and remove duplicate rows.

    Historically the normalization function had an optional transliteration
    dependency; when it was absent the fallback preserved diacritics, producing
    rows like ``bakłażan`` alongside correct rows like ``baklazan``.  The
    dependency is hard now and the fallback is gone, but rows written before
    that are still out there, and this is also the repair path if the
    transliteration table ever shifts under a dependency upgrade.  This
    function:

    1. Re-normalises every row's ``name_normalized`` using the current
       (always diacritic-free) implementation.
    2. Deduplicates: within each ``(organization_id, lang, name_normalized)``
       group keeps the row that already had the correct normalisation (or the
       first one if all were wrong) and deletes the rest.

    Returns the number of deleted rows.
    """
    result = await db.execute(select(IngredientNutritionDefault))
    all_rows = list(result.scalars().all())

    groups: dict[tuple[str, str, str], list[IngredientNutritionDefault]] = defaultdict(
        list
    )
    for row in all_rows:
        correct = normalize_name(row.name)
        key = (str(row.organization_id), row.lang, correct)
        groups[key].append(row)

    deleted = 0
    for (_, _, correct_normalized), rows in groups.items():
        rows.sort(key=lambda r: r.name_normalized != correct_normalized)
        keeper = rows[0]

        if keeper.name_normalized != correct_normalized:
            keeper.name_normalized = correct_normalized

        for dup in rows[1:]:
            await db.delete(dup)
            deleted += 1

    await db.flush()
    if deleted:
        log.info('deduplicate_defaults: removed %d duplicate rows', deleted)
    return deleted
