"""Analytics — re-export hub.

The business logic lives in the sub-service modules beside this file; this
one re-exports what the router and the module's public API import, so a
caller does not have to know which sub-module a function ended up in.

The example this docstring used to give named a class that has never existed
in this repository.
"""

from ._alerts_service import get_smart_alerts_async
from ._purchase_service import get_purchase_patterns_async
from .query_service import get_expense_forecast

__all__ = [
    'get_expense_forecast',
    'get_smart_alerts_async',
    'get_purchase_patterns_async',
]
