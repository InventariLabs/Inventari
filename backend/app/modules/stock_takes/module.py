from typing import Any

from app.core.define_module import define_module
from app.modules.stock_takes.router import router


def _purge_blocker_interceptor() -> Any:
    """The stock_takes purge veto.

    Registered via ``interceptors=`` so the shared ``_wire_interceptors``
    path attaches it to the item pipeline at startup — the module never
    touches Core's pipeline directly.
    """
    from app.modules.stock_takes.interceptors import StockTakesPurgeBlocker

    return StockTakesPurgeBlocker()


def _register_work_item_provider() -> None:
    """Put the counts that have fallen due into To do.

    Registered at import, like the other cross-module providers, so the list
    does not depend on which organisation started first; the warehouse module
    only calls it while this module is enabled for the organisation asking.
    """
    from app.modules.stock_takes.stock_takes_api import stock_takes_api
    from app.modules.warehouse.warehouse_api import warehouse_api

    warehouse_api.register_work_item_provider(
        'stock_takes', stock_takes_api.list_work_items_async
    )


_register_work_item_provider()


# Counting by age: with a number of days set, every location that holds
# stock comes up in To do that long after its last count. Off (0) by default:
# a home pantry has no use for it, and a business turns it on when it wants it.
_SETTINGS_SCHEMA = {
    'type': 'object',
    'properties': {
        'count_every_days': {
            'type': 'integer',
            'default': 0,
            'minimum': 0,
            'maximum': 365,
            'title': 'Count every location every (days)',
            'title_key': 'stock_takes:settings.countEveryDays',
            'description_key': 'stock_takes:settings.countEveryDaysDescription',
            'description': (
                'Each location that holds stock appears in To do this many '
                'days after it was last counted. 0 turns it off.'
            ),
        },
    },
    'additionalProperties': False,
}


module = define_module(
    router=router,
    interceptors=[_purge_blocker_interceptor()],
    consumes_stock_quant=True,
    settings_schema=_SETTINGS_SCHEMA,
    default_settings={'count_every_days': 0},
)
