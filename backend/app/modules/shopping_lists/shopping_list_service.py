"""Business logic for shopping list operations.

This module is a facade re-exporting the implementation from sub-modules.
Public API is preserved; existing import paths keep working.
"""

from ._helpers import (
    get_shopping_list_item_or_404,
    get_shopping_list_or_404,
)
from ._item_crud import (
    add_single_item,
    bulk_add_items,
    delete_shopping_list_item,
    get_list_items_filtered,
    update_shopping_list_item,
)
from ._item_state import (
    clear_purchased_from_list,
    set_item_purchased,
    set_item_unpurchased,
)
from ._list_crud import (
    create_shopping_list,
    delete_shopping_list_by_id,
    get_shopping_list_with_items,
    list_shopping_lists,
    update_shopping_list_fields,
)
from ._suggestions import (
    add_suggestions_to_list,
    get_suggestions_for_list,
    get_suggestions_for_organization,
)

__all__ = [
    'add_single_item',
    'add_suggestions_to_list',
    'bulk_add_items',
    'clear_purchased_from_list',
    'create_shopping_list',
    'delete_shopping_list_by_id',
    'delete_shopping_list_item',
    'get_list_items_filtered',
    'get_shopping_list_item_or_404',
    'get_shopping_list_or_404',
    'get_shopping_list_with_items',
    'get_suggestions_for_list',
    'get_suggestions_for_organization',
    'list_shopping_lists',
    'set_item_purchased',
    'set_item_unpurchased',
    'update_shopping_list_fields',
    'update_shopping_list_item',
]
