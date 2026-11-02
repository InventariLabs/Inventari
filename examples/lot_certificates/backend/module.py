"""Lot certificates — the worked example of extending the warehouse.

Metadata (name, version, display name, icon) is read from ``manifest.json``.
Everything this package imports from the platform comes from
``app.core.module_sdk``, ``app.core.contracts``, ``app.core.public_api`` and
``app.modules.warehouse.warehouse_api``; the install-time safety scan refuses
any other ``app.`` path.
"""

from app.core.module_sdk import define_module

from .router import router
from .seams import register_seams

register_seams()

module = define_module(router=router)
