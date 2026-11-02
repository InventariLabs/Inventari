"""PANTRY (dry goods) + universal 'Other' category seed data.

Pure data — no DB access. The orchestrator
:mod:`app.seed_profiles._food_home_categories` imports
``PANTRY_CATEGORIES`` and persists the rows.
"""

from typing import Any

PANTRY_CATEGORIES: list[dict[str, Any]] = [
    {
        'name': 'Dry products',
        'code': 'dry_products',
        'group_label': 'PANTRY',
        'context_tag': 'dry_goods',
        'icon': 'Wheat',
        'sort_order': 1,
    },
    {
        'name': 'Pasta',
        'code': 'pasta',
        'group_label': 'PANTRY',
        'context_tag': 'dry_goods',
        'icon': 'Utensils',
        'sort_order': 2,
    },
    {
        'name': 'Rice and grains',
        'code': 'rice_grains',
        'group_label': 'PANTRY',
        'context_tag': 'dry_goods',
        'icon': 'Wheat',
        'sort_order': 3,
    },
    {
        'name': 'Canned goods',
        'code': 'canned_goods',
        'group_label': 'PANTRY',
        'context_tag': 'dry_goods',
        'icon': 'Container',
        'sort_order': 4,
    },
    {
        'name': 'Spices and herbs',
        'code': 'spices_herbs',
        'group_label': 'PANTRY',
        'context_tag': 'dry_goods',
        'icon': 'Leaf',
        'sort_order': 5,
    },
    {
        'name': 'Oils and vinegars',
        'code': 'oils_vinegars',
        'group_label': 'PANTRY',
        'context_tag': 'dry_goods',
        'icon': 'GlassWater',
        'sort_order': 6,
    },
    {
        'name': 'Flours and sugars',
        'code': 'flours_sugars',
        'group_label': 'PANTRY',
        'context_tag': 'dry_goods',
        'icon': 'Box',
        'sort_order': 7,
    },
    {
        'name': 'Snacks',
        'code': 'snacks',
        'group_label': 'PANTRY',
        'context_tag': 'dry_goods',
        'icon': 'Cookie',
        'sort_order': 8,
    },
    {
        'name': 'Sweets',
        'code': 'sweets',
        'group_label': 'PANTRY',
        'context_tag': 'dry_goods',
        'icon': 'Candy',
        'sort_order': 9,
    },
    {
        'name': 'Beverages (non-refrigerated)',
        'code': 'beverages',
        'group_label': 'PANTRY',
        'context_tag': 'dry_goods',
        'icon': 'GlassWater',
        'sort_order': 10,
    },
    {
        'name': 'Tea and coffee',
        'code': 'tea_coffee',
        'group_label': 'PANTRY',
        'context_tag': 'dry_goods',
        'icon': 'Coffee',
        'sort_order': 11,
    },
    {
        'name': 'Cans and jars',
        'code': 'cans_jars',
        'group_label': 'PANTRY',
        'context_tag': 'dry_goods',
        'icon': 'Container',
        'sort_order': 12,
    },
    {
        'name': 'Other',
        'code': 'other',
        'group_label': None,
        'context_tag': None,
        'icon': 'Archive',
        'sort_order': 100,
    },
]
