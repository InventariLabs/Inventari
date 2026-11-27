from app.core.module_sdk import define_module

from .router import router

module = define_module(router=router)
