from fastapi import APIRouter

from app.core.container import ServiceContainer
from app.core.context import ModuleContext
from app.core.define_module import define_module


def _init_products_db(context: ModuleContext) -> None:
    from app.core.db_facade import products_engine

    from .models import OFFBase

    if products_engine:
        OFFBase.metadata.create_all(bind=products_engine)


def _register_services(container: ServiceContainer) -> None:
    from .services import off_service

    container.register('off_service', off_service)


def _register_contributions() -> None:
    from app.core.scan_registry import scan_registry

    from .scan_provider import OFFScanProvider
    from .vision_fields import register_vision_fields

    scan_registry.register(OFFScanProvider(), priority=50)
    # A photographed package may carry a nutrition table; vision reads it in
    # the same call rather than in a second, separately billed one.
    register_vision_fields()


module = define_module(
    router=APIRouter(),
    on_startup_hook=_init_products_db,
    register_services_hook=_register_services,
    register_contributions_hook=_register_contributions,
)
