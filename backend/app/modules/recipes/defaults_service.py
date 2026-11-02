"""Service for ingredient nutrition defaults.

Handles system defaults (seeded from JSON, organization_id=NULL)
and per-organisation overrides (organization_id=UUID).

Lookup hierarchy:
  1. org override (org_id + lang + name_normalized)
  2. system default (org_id=NULL + lang + name_normalized)
"""

from __future__ import annotations

import csv
import io
import json
import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db_utils import acquire_advisory_lock, escape_ilike, paginate_async
from app.core.exceptions import AppException
from app.core.export_hygiene import defuse
from app.core.logging import get_logger
from app.i18n.service import get_current_lang, get_error_message

from ._name_matching import normalize_name
from .models import IngredientNutritionDefault

log = get_logger(__name__)


# ---------------------------------------------------------------------------
# Lookup
# ---------------------------------------------------------------------------


async def lookup_default(
    db: AsyncSession,
    name: str,
    lang: str = 'en',
    org_id: uuid.UUID | None = None,
) -> IngredientNutritionDefault | None:
    """Return the best matching default for *name*.

       Priority: org override > system default; within each group the current
    language wins and other languages act as a fallback — nutrition
       data must not depend on the UI language, only on the ingredient name.
       Returns None when no match is found.
    """
    normalized = normalize_name(name)

    result = await db.execute(
        select(IngredientNutritionDefault).where(
            IngredientNutritionDefault.name_normalized == normalized,
            or_(
                IngredientNutritionDefault.organization_id == org_id,
                IngredientNutritionDefault.organization_id.is_(None),
            ),
        )
    )
    rows = list(result.scalars().all())
    if not rows:
        return None

    # Org overrides first; within each group prefer the current language.
    # A single-language user is unaffected (their language still wins), the
    # lookup simply stops going dark after a UI language switch.
    rows.sort(key=lambda row: (row.organization_id != org_id, row.lang != lang))
    return rows[0]


# ---------------------------------------------------------------------------
# List / search
# ---------------------------------------------------------------------------


async def list_defaults(
    db: AsyncSession,
    org_id: uuid.UUID,
    lang: str = 'en',
    q: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[IngredientNutritionDefault], int]:
    """Return paginated defaults visible to *org_id* (system + org overrides)."""
    stmt = select(IngredientNutritionDefault).where(
        IngredientNutritionDefault.lang == lang,
        or_(
            IngredientNutritionDefault.organization_id == org_id,
            IngredientNutritionDefault.organization_id.is_(None),
        ),
    )
    if q:
        # normalize_name only lowercases, transliterates to ASCII and strips
        # the outer whitespace — `%` and `_` pass through untouched.
        pattern = f'%{escape_ilike(normalize_name(q))}%'
        stmt = stmt.where(IngredientNutritionDefault.name_normalized.like(pattern))

    return await paginate_async(
        db,
        stmt.order_by(IngredientNutritionDefault.name_normalized),
        limit=limit,
        offset=offset,
    )


# ---------------------------------------------------------------------------
# Upsert / delete
# ---------------------------------------------------------------------------


async def upsert_org_default(
    db: AsyncSession,
    org_id: uuid.UUID,
    data: dict[str, Any],
) -> IngredientNutritionDefault:
    """Create or update an org-level override for a given ingredient + lang."""
    lang = data.get('lang', 'en')
    normalized = normalize_name(data['name'])

    # TOCTOU guard: lock the (org, lang, name) slot so concurrent requests
    # don't both see "no existing" and double-insert.
    await acquire_advisory_lock(db, f'recipes.defaults:{org_id}:{lang}:{normalized}')

    result = await db.execute(
        select(IngredientNutritionDefault).where(
            IngredientNutritionDefault.organization_id == org_id,
            IngredientNutritionDefault.lang == lang,
            IngredientNutritionDefault.name_normalized == normalized,
        )
    )
    existing = result.scalars().first()

    if existing:
        for field in (
            'name',
            'calories_kcal',
            'protein_g',
            'fat_g',
            'carbs_g',
            'fiber_g',
            'sugar_g',
            'salt_g',
        ):
            if field in data:
                setattr(existing, field, data[field])
        existing.source = 'manual'
        await db.flush()
        await db.refresh(existing)
        return existing

    obj = IngredientNutritionDefault(
        id=uuid.uuid4(),
        organization_id=org_id,
        lang=lang,
        name=data['name'],
        name_normalized=normalized,
        calories_kcal=Decimal(str(data['calories_kcal'])),
        protein_g=_opt_decimal(data.get('protein_g')),
        fat_g=_opt_decimal(data.get('fat_g')),
        carbs_g=_opt_decimal(data.get('carbs_g')),
        fiber_g=_opt_decimal(data.get('fiber_g')),
        sugar_g=_opt_decimal(data.get('sugar_g')),
        salt_g=_opt_decimal(data.get('salt_g')),
        source='manual',
        is_system=False,
    )
    db.add(obj)
    await db.flush()
    await db.refresh(obj)
    return obj


async def delete_org_default(
    db: AsyncSession,
    org_id: uuid.UUID,
    default_id: uuid.UUID,
) -> None:
    """Delete an org override.

    Raises AppException(404) if not found, PermissionError if system-owned.
    """
    result = await db.execute(
        select(IngredientNutritionDefault).where(
            IngredientNutritionDefault.id == default_id,
            IngredientNutritionDefault.organization_id == org_id,
        )
    )
    row = result.scalars().first()
    if not row:
        raise AppException(
            status_code=404,
            code='NOT_FOUND',
            message=get_error_message('not_found', get_current_lang()),
        )
    if row.is_system or row.organization_id is None:
        raise PermissionError('cannot_delete_system_default')
    await db.delete(row)
    await db.flush()


# ---------------------------------------------------------------------------
# Import / export
# ---------------------------------------------------------------------------


_NUTRIENT_FIELDS = (
    'calories_kcal',
    'protein_g',
    'fat_g',
    'carbs_g',
    'fiber_g',
    'sugar_g',
    'salt_g',
)


def _says_system(item: dict[str, Any]) -> bool:
    flag = item.get('is_system')
    return flag is True or str(flag).strip().lower() in ('true', '1')


def _same_numbers(row: IngredientNutritionDefault, item: dict[str, Any]) -> bool:
    return all(
        _opt_decimal(item.get(field)) == getattr(row, field)
        for field in _NUTRIENT_FIELDS
    )


async def import_defaults(
    db: AsyncSession,
    org_id: uuid.UUID,
    lang: str,
    items: list[dict[str, Any]],
) -> dict[str, int]:
    """Read a sheet of ingredients back into the organization's overrides.

    The sheet is the organization's own export more often than not: system
    rows and overrides side by side. A row that says what already applies
    (the override if there is one, else the system row) changes nothing —
    writing an override for every system row doubled the dictionary. A row
    that differs updates its override, or founds one over the system row, or
    is a new ingredient when no row carries the name.

    Returns a summary: created / overridden / updated / unchanged / errors.
    """
    summary = {
        'created': 0,
        'overridden': 0,
        'updated': 0,
        'unchanged': 0,
        'errors': 0,
    }
    for item in items:
        try:
            item['lang'] = lang
            for field in _NUTRIENT_FIELDS:
                # A CSV cell left empty is "no value", not the number ''.
                if item.get(field) == '':
                    item[field] = None
            normalized = normalize_name(item['name'])
            result = await db.execute(
                select(IngredientNutritionDefault).where(
                    IngredientNutritionDefault.lang == lang,
                    IngredientNutritionDefault.name_normalized == normalized,
                    or_(
                        IngredientNutritionDefault.organization_id == org_id,
                        IngredientNutritionDefault.organization_id.is_(None),
                    ),
                )
            )
            rows = list(result.scalars().all())
            override = next((r for r in rows if r.organization_id == org_id), None)
            system = next((r for r in rows if r.organization_id is None), None)
            # The export flags the system's copy; measured against the system
            # row it is either untouched or an edit the reader made on it. A
            # row without the flag is measured against what applies.
            reference = system if _says_system(item) else (override or system)
            if reference is not None and _same_numbers(reference, item):
                summary['unchanged'] += 1
                continue
            await upsert_org_default(db, org_id, item)
            if override is not None:
                summary['updated'] += 1
            elif system is not None:
                summary['overridden'] += 1
            else:
                summary['created'] += 1
        except Exception as exc:  # noqa: BLE001 — one bad item must not abort the import
            log.warning('import_defaults: skipped item %s — %s', item, exc)
            summary['errors'] += 1
    return summary


async def export_defaults(
    db: AsyncSession,
    org_id: uuid.UUID,
    lang: str = 'en',
    fmt: str = 'json',
) -> str:
    """Export all defaults visible to *org_id* as JSON or CSV string."""
    items, _ = await list_defaults(db, org_id, lang=lang, limit=10_000)
    fields = [
        'name',
        'lang',
        'calories_kcal',
        'protein_g',
        'fat_g',
        'carbs_g',
        'fiber_g',
        'sugar_g',
        'salt_g',
        'source',
        'is_system',
    ]

    if fmt == 'csv':
        buf = io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=fields)
        writer.writeheader()
        for row in items:
            # Names and sources are user text; a leading '=' would execute on
            # open.
            writer.writerow({f: defuse(getattr(row, f, None)) for f in fields})
        return buf.getvalue()

    return json.dumps(
        [{f: _serialise(getattr(row, f, None)) for f in fields} for row in items],
        ensure_ascii=False,
        indent=2,
    )


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _opt_decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    return Decimal(str(value))


def _serialise(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    return value
