"""FREEZER category seed data for the Food & Home profile.

Pure data — no DB access. The orchestrator
:mod:`app.seed_profiles._food_home_categories` imports
``FREEZER_CATEGORIES`` and persists the rows.
"""

from typing import Any

FREEZER_CATEGORIES: list[dict[str, Any]] = [
    {
        'name': 'Pork',
        'code': 'pork',
        'group_label': 'FREEZER',
        'context_tag': 'cold_storage',
        'icon': 'Drumstick',
        'sort_order': 1,
        'field_definitions': [
            {
                'key': 'cut_type',
                'is_system': True,
                'label': 'Cut type',
                'type': 'text',
                'visible': True,
                'required': False,
            },
            {
                'key': 'freeze_date',
                'is_system': True,
                'label': 'Freeze date',
                'type': 'date',
                'visible': True,
                'required': False,
            },
        ],
    },
    {
        'name': 'Beef',
        'code': 'beef',
        'group_label': 'FREEZER',
        'context_tag': 'cold_storage',
        'icon': 'Drumstick',
        'sort_order': 2,
        'field_definitions': [
            {
                'key': 'cut_type',
                'is_system': True,
                'label': 'Cut type',
                'type': 'text',
                'visible': True,
                'required': False,
            },
            {
                'key': 'freeze_date',
                'is_system': True,
                'label': 'Freeze date',
                'type': 'date',
                'visible': True,
                'required': False,
            },
        ],
    },
    {
        'name': 'Poultry',
        'code': 'poultry',
        'group_label': 'FREEZER',
        'context_tag': 'cold_storage',
        'icon': 'Drumstick',
        'sort_order': 3,
        'field_definitions': [
            {
                'key': 'freeze_date',
                'is_system': True,
                'label': 'Freeze date',
                'type': 'date',
                'visible': True,
                'required': False,
            }
        ],
    },
    {
        'name': 'Fish',
        'code': 'fish',
        'group_label': 'FREEZER',
        'context_tag': 'cold_storage',
        'icon': 'Fish',
        'sort_order': 4,
        'field_definitions': [
            {
                'key': 'freeze_date',
                'is_system': True,
                'label': 'Freeze date',
                'type': 'date',
                'visible': True,
                'required': False,
            }
        ],
    },
    {
        'name': 'Seafood',
        'code': 'seafood',
        'group_label': 'FREEZER',
        'context_tag': 'cold_storage',
        'icon': 'Shell',
        'sort_order': 5,
        'field_definitions': [
            {
                'key': 'freeze_date',
                'is_system': True,
                'label': 'Freeze date',
                'type': 'date',
                'visible': True,
                'required': False,
            }
        ],
    },
    {
        'name': 'Frozen meals',
        'code': 'frozen_meals',
        'group_label': 'FREEZER',
        'context_tag': 'cold_storage',
        'icon': 'Soup',
        'sort_order': 6,
    },
    {
        'name': 'Frozen vegetables',
        'code': 'frozen_vegetables',
        'group_label': 'FREEZER',
        'context_tag': 'cold_storage',
        'icon': 'LeafyGreen',
        'sort_order': 7,
    },
    {
        'name': 'Frozen fruits',
        'code': 'frozen_fruits',
        'group_label': 'FREEZER',
        'context_tag': 'cold_storage',
        'icon': 'Apple',
        'sort_order': 8,
    },
    {
        'name': 'Ice cream and desserts',
        'code': 'ice_cream',
        'group_label': 'FREEZER',
        'context_tag': 'cold_storage',
        'icon': 'IceCream',
        'sort_order': 9,
    },
    {
        'name': 'Frozen pizza',
        'code': 'frozen_pizza',
        'group_label': 'FREEZER',
        'context_tag': 'cold_storage',
        'icon': 'Pizza',
        'sort_order': 10,
    },
]
