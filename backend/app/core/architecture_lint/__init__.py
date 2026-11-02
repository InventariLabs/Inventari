"""Architecture lint for module boundaries.

Public surface re-exported from submodules for backward compatibility.
Entry point ``main`` is invoked by ``manage.py arch lint``.
"""

from __future__ import annotations

from ._main import main
from ._quality_checks import (
    _check_module_migrations_exist,
    _check_public_api_return_types,
    _check_sync_async_function_pairs,
    _check_sync_async_function_twins,
    _check_toctou_risk,
    _is_cross_module_import_whitelisted,
)
from ._violations import (
    find_api_layer_import_violations,
    find_module_boundary_violations,
)

__all__ = [
    '_check_module_migrations_exist',
    '_check_public_api_return_types',
    '_check_sync_async_function_pairs',
    '_check_sync_async_function_twins',
    '_check_toctou_risk',
    '_is_cross_module_import_whitelisted',
    'find_api_layer_import_violations',
    'find_module_boundary_violations',
    'main',
]
