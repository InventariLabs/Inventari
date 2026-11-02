"""FRIDGE category seed data for the Food & Home profile.

Pure data — no DB access. The orchestrator
:mod:`app.seed_profiles._food_home_categories` imports
``FRIDGE_CATEGORIES`` and persists the rows.
"""

from typing import Any

FRIDGE_CATEGORIES: list[dict[str, Any]] = [
    {
        'name': 'Dairy',
        'code': 'dairy',
        'group_label': 'FRIDGE',
        'context_tag': 'cold_storage',
        'icon': 'Milk',
        'sort_order': 1,
        'field_definitions': [
            {
                'key': 'lactose_free',
                'is_system': True,
                'label': 'Lactose free',
                'type': 'select',
                'options': ['No', 'Yes'],
                # A seeded field's words are the platform's copy, so they are
                # catalogued like its label (see items:fields.<key>) rather
                # than stored in whatever language the seeding ran in.
                'options_i18n': {
                    'No': 'items:fieldOptions.lactose_free.No',
                    'Yes': 'items:fieldOptions.lactose_free.Yes',
                },
                'visible': True,
                'required': False,
            }
        ],
    },
    {
        'name': 'Cheese',
        'code': 'cheese',
        'group_label': 'FRIDGE',
        'context_tag': 'cold_storage',
        'icon': 'Cheese',
        'sort_order': 2,
        'field_definitions': [
            {
                'key': 'lactose_free',
                'is_system': True,
                'label': 'Lactose free',
                'type': 'select',
                'options': ['No', 'Yes'],
                # A seeded field's words are the platform's copy, so they are
                # catalogued like its label (see items:fields.<key>) rather
                # than stored in whatever language the seeding ran in.
                'options_i18n': {
                    'No': 'items:fieldOptions.lactose_free.No',
                    'Yes': 'items:fieldOptions.lactose_free.Yes',
                },
                'visible': True,
                'required': False,
            }
        ],
    },
    {
        'name': 'Deli',
        'code': 'deli',
        'group_label': 'FRIDGE',
        'context_tag': 'cold_storage',
        'icon': 'Beef',
        'sort_order': 3,
    },
    {
        'name': 'Eggs',
        'code': 'eggs',
        'group_label': 'FRIDGE',
        'context_tag': 'cold_storage',
        'icon': 'Egg',
        'sort_order': 4,
    },
    {
        'name': 'Fresh vegetables',
        'code': 'fresh_vegetables',
        'group_label': 'FRIDGE',
        'context_tag': 'cold_storage',
        'icon': 'LeafyGreen',
        'sort_order': 5,
    },
    {
        'name': 'Fresh fruits',
        'code': 'fresh_fruits',
        'group_label': 'FRIDGE',
        'context_tag': 'cold_storage',
        'icon': 'Apple',
        'sort_order': 6,
    },
    {
        'name': 'Drinks',
        'code': 'drinks',
        'group_label': 'FRIDGE',
        'context_tag': 'cold_storage',
        'icon': 'GlassWater',
        'sort_order': 7,
        'field_definitions': [
            {
                'key': 'abv',
                'is_system': True,
                'label': 'Alcohol content (ABV %)',
                'type': 'number',
                'visible': True,
                'required': False,
            }
        ],
    },
    {
        'name': 'Sauces and dips',
        'code': 'sauces',
        'group_label': 'FRIDGE',
        'context_tag': 'cold_storage',
        'icon': 'Pint',
        'sort_order': 8,
    },
    {
        'name': 'Fresh meat',
        'code': 'fresh_meat',
        'group_label': 'FRIDGE',
        'context_tag': 'cold_storage',
        'icon': 'Drumstick',
        'sort_order': 9,
        'field_definitions': [
            {
                'key': 'cut_type',
                'is_system': True,
                'label': 'Cut type',
                'type': 'text',
                'visible': True,
                'required': False,
            }
        ],
    },
    {
        'name': 'Fresh meals',
        'code': 'fresh_meals',
        'group_label': 'FRIDGE',
        'context_tag': 'cold_storage',
        'icon': 'CookingPot',
        'sort_order': 10,
    },
]
