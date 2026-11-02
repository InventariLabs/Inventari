from app.core.define_module import define_module
from app.modules.shopping_lists.router import router

module = define_module(router=router)
