"""
Recipe tag management service.

Provides:
  - list_tags(db, org_id, …)        — aggregate tags for the reader's current
                                      view + config (color, count)
  - upsert_tag_color(db, name, color, org_id) — set/update/clear a tag's color
  - merge_tags(db, old_tag, new_tag, org_id)  — rename tag across all recipes
  - delete_tag(db, tag_name, org_id)          — strip a tag from every recipe
"""

import re
import uuid
from typing import Any

from sqlalchemy import func, select, true
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db_utils import acquire_advisory_lock, escape_ilike
from app.core.exceptions import AppException, ServiceRejectionError
from app.i18n.service import get_current_lang, get_error_message

from .models import Recipe, RecipeCollectionMember, RecipeTagConfig

_HEX_RE = re.compile(r'^#[0-9a-fA-F]{3}([0-9a-fA-F]{3})?$')


def _validate_hex_color(color: str) -> None:
    if not _HEX_RE.match(color):
        raise ServiceRejectionError('hex_color_invalid', color=color)


# ---------------------------------------------------------------------------
# List tags
# ---------------------------------------------------------------------------


async def list_tags(
    db: AsyncSession,
    org_id: uuid.UUID,
    search: str | None = None,
    tags: list[str] | None = None,
    is_favorite: bool | None = None,
    collection_id: uuid.UUID | None = None,
) -> list[dict[str, Any]]:
    """Return aggregated tags for the view the reader is looking at.

    Each entry: { name, count, color | None }
    Sorted by usage count desc, then name asc.

    The filters mirror ``list_recipes``: a chip's count answers "how many
    recipes would this chip leave on the screen", not "how many this
    organization owns". A collection showing zero recipes used to keep
    counting the whole organization on its chips, so every click led to
    the same empty list.
    """
    # One row per tag per recipe, so counting the rows counts the recipes
    # carrying each tag — jsonb_array_elements_text as a lateral relation.
    tag = func.jsonb_array_elements_text(Recipe.tags).table_valued('value').alias('tag')

    conditions = [
        Recipe.organization_id == org_id,
        Recipe.tags.is_not(None),
        func.jsonb_typeof(Recipe.tags) == 'array',
    ]
    if search:
        conditions.append(Recipe.name.ilike(f'%{escape_ilike(search)}%'))
    if tags:
        conditions.extend(Recipe.tags.contains([name]) for name in tags)
    if is_favorite is not None:
        conditions.append(Recipe.is_favorite == is_favorite)
    if collection_id is not None:
        conditions.append(
            Recipe.id.in_(
                select(RecipeCollectionMember.recipe_id).where(
                    RecipeCollectionMember.collection_id == collection_id
                )
            )
        )

    tag_count = func.count().label('tag_count')
    rows = (
        await db.execute(
            select(tag.c.value.label('tag'), tag_count)
            .select_from(Recipe)
            .join(tag, true())
            .where(*conditions)
            .group_by(tag.c.value)
            .order_by(tag_count.desc(), tag.c.value.asc())
        )
    ).fetchall()

    if not rows:
        return []

    tag_counts: dict[str, int] = {row.tag: row.tag_count for row in rows}

    config_result = await db.execute(
        select(RecipeTagConfig).where(
            RecipeTagConfig.organization_id == org_id,
            RecipeTagConfig.name.in_(tag_counts.keys()),
        )
    )
    configs = list(config_result.scalars().all())
    color_map: dict[str, str | None] = {cfg.name: cfg.color for cfg in configs}

    return [
        {
            'name': name,
            'count': count,
            'color': color_map.get(name),
        }
        for name, count in tag_counts.items()
    ]


# ---------------------------------------------------------------------------
# Set / update tag color
# ---------------------------------------------------------------------------


async def upsert_tag_color(
    db: AsyncSession,
    tag_name: str,
    color: str | None,
    org_id: uuid.UUID,
) -> dict[str, Any]:
    """Set the display color for a tag, or clear it with ``None``.

    Clearing drops the config row rather than nulling its column: the row
    holds nothing else, so a colourless one is a tag claiming a setting it
    does not have. The table then means what it says — the tags that have a
    colour — and `list_tags` reports the rest as uncoloured either way.

    Returns { name, color }.
    Raises ValueError for invalid hex color.
    """
    # TOCTOU guard: lock the (org, tag_name) slot so concurrent requests
    # don't both see "no existing" and double-insert.
    await acquire_advisory_lock(db, f'recipes.tag_color:{org_id}:{tag_name}')

    result = await db.execute(
        select(RecipeTagConfig).where(
            RecipeTagConfig.organization_id == org_id,
            RecipeTagConfig.name == tag_name,
        )
    )
    cfg = result.scalars().first()

    if color is None:
        if cfg:
            await db.delete(cfg)
            await db.flush()
        return {'name': tag_name, 'color': None}

    _validate_hex_color(color)

    if cfg:
        cfg.color = color
    else:
        cfg = RecipeTagConfig(
            organization_id=org_id,
            name=tag_name,
            color=color,
        )
        db.add(cfg)
    await db.flush()
    return {'name': cfg.name, 'color': cfg.color}


# ---------------------------------------------------------------------------
# Merge tags
# ---------------------------------------------------------------------------


async def merge_tags(
    db: AsyncSession,
    old_tag: str,
    new_tag: str,
    org_id: uuid.UUID,
) -> dict[str, Any]:
    """Rename old_tag → new_tag across all recipes in the org.

    Returns { old_tag, new_tag, updated_recipes }.
    Raises ValueError if old_tag has no recipes.
    """
    result = await db.execute(
        select(Recipe)
        .where(
            Recipe.organization_id == org_id,
            Recipe.tags.isnot(None),
        )
        .with_for_update()
    )
    all_with_tags = list(result.scalars().all())
    recipes = [r for r in all_with_tags if old_tag in (r.tags or [])]

    if not recipes:
        raise AppException(
            status_code=404,
            code='TAG_NOT_FOUND',
            message=get_error_message('tag_not_found', get_current_lang(), tag=old_tag),
        )

    updated = 0
    for recipe in recipes:
        tags = list(recipe.tags or [])
        if old_tag not in tags:
            continue
        new_tags = []
        seen: set[str] = set()
        for t in tags:
            effective = new_tag if t == old_tag else t
            if effective not in seen:
                new_tags.append(effective)
                seen.add(effective)
        recipe.tags = new_tags
        updated += 1

    old_cfg_result = await db.execute(
        select(RecipeTagConfig).where(
            RecipeTagConfig.organization_id == org_id,
            RecipeTagConfig.name == old_tag,
        )
    )
    old_cfg = old_cfg_result.scalars().first()
    if old_cfg:
        new_cfg_result = await db.execute(
            select(RecipeTagConfig).where(
                RecipeTagConfig.organization_id == org_id,
                RecipeTagConfig.name == new_tag,
            )
        )
        new_cfg = new_cfg_result.scalars().first()
        if new_cfg:
            await db.delete(old_cfg)
        else:
            old_cfg.name = new_tag

    await db.flush()
    return {'old_tag': old_tag, 'new_tag': new_tag, 'updated_recipes': updated}


# ---------------------------------------------------------------------------
# Delete tag
# ---------------------------------------------------------------------------


async def delete_tag(
    db: AsyncSession,
    tag_name: str,
    org_id: uuid.UUID,
) -> dict[str, Any]:
    """Remove *tag_name* from every recipe in the org, and drop its colour.

    Tags are free text typed into a comma-separated field, so a typo used to
    be permanent: the panel could merge one tag into another and colour it,
    but never take one away.

    Returns { name, updated_recipes }.
    """
    result = await db.execute(
        select(Recipe)
        .where(
            Recipe.organization_id == org_id,
            Recipe.tags.isnot(None),
        )
        .with_for_update()
    )
    recipes = [r for r in result.scalars().all() if tag_name in (r.tags or [])]

    if not recipes:
        raise AppException(
            status_code=404,
            code='TAG_NOT_FOUND',
            message=get_error_message(
                'tag_not_found', get_current_lang(), tag=tag_name
            ),
        )

    for recipe in recipes:
        recipe.tags = [t for t in (recipe.tags or []) if t != tag_name]

    cfg_result = await db.execute(
        select(RecipeTagConfig).where(
            RecipeTagConfig.organization_id == org_id,
            RecipeTagConfig.name == tag_name,
        )
    )
    cfg = cfg_result.scalars().first()
    if cfg:
        await db.delete(cfg)

    await db.flush()
    return {'name': tag_name, 'updated_recipes': len(recipes)}
