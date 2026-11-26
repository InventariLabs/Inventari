from app.core.define_module import define_module
from app.modules.shopping_lists.router import router


def _register_grocy_move() -> None:
    """Bring Grocy's shopping lists when a household moves in from Grocy.

    The core never imports a module (architecture lint), so the module
    registers its part of the move here, when it is imported, through the
    module SDK.
    """
    from app.core.module_sdk import MoveContributor, register_move_contributor

    from ._grocy_move import bring_grocy_shopping_lists_async

    register_move_contributor(
        'grocy',
        MoveContributor(
            module='shopping_lists',
            takes='shopping_list_entries',
            bring=bring_grocy_shopping_lists_async,
        ),
    )


_register_grocy_move()

module = define_module(router=router)
