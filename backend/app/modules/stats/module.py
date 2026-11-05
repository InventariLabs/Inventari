from app.core.define_module import define_module

from .router import router

# Analytics (rotation, forecasts, purchase patterns) is a per-profile
# feature. It needs months of transaction history to say anything — a home
# pantry gets noise out of it, so `food_home` presets this to False and the
# business profile keeps it on. Mirrors the `recipes.enable_cost_calculation`
# toggle. `show_inventory_value` is the same gate on the always-visible
# overview: the total value is a business metric read off a cost ledger a
# home pantry does not keep, so `food_home` presets that off too.
_SETTINGS_SCHEMA = {
    'type': 'object',
    'properties': {
        'enable_analytics': {
            'type': 'boolean',
            'default': True,
            'title': 'Enable analytics',
            'title_key': 'stats:settings.enableAnalytics',
            'description_key': 'stats:settings.enableAnalyticsDescription',
            'description': (
                'Show the analytics tab (rotation, spend forecasts, purchase '
                'patterns). Disable for small home inventories where there is '
                'not enough history for these to be meaningful.'
            ),
        },
        'show_inventory_value': {
            'type': 'boolean',
            'default': True,
            'title': 'Show inventory value',
            'title_key': 'stats:settings.showInventoryValue',
            'description_key': 'stats:settings.showInventoryValueDescription',
            'description': (
                'Show stock values across the app: on the stats overview, the '
                'product screens, and in exports and printouts. It is a '
                'business metric — disable for home inventories that keep no '
                'purchase prices for it to add up.'
            ),
        },
    },
    'additionalProperties': False,
}

module = define_module(
    router=router,
    settings_schema=_SETTINGS_SCHEMA,
    default_settings={'enable_analytics': True, 'show_inventory_value': True},
)
