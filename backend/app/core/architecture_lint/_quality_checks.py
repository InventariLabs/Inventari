"""Quality-check entry points for the architecture linter.

This module is split into focused submodules by check category:

- ``_quality_checks_size`` — frontend file size + sync/async pair checks
- ``_quality_checks_modules`` — cross-module imports + ``get_db`` in async def
- ``_quality_checks_api`` — CoreAPI return-type leak (Guardrail 2)
- ``_quality_checks_twins`` — sync/async function twins (Guardrail 1)
- ``_quality_checks_toctou`` — TOCTOU risk + pattern helpers (Guardrail 3)
- ``_quality_checks_migrations`` — module-migrations check + table extraction
- ``_quality_checks_services`` — escape-hatch marker forbidden in Core services

The original ``_quality_checks.py`` is kept as a thin re-export shim so
existing callers (and tests) can still import from a single namespace.
"""

from __future__ import annotations

# Re-export the public symbols used by ``_main.py`` and the unit tests.
from ._quality_checks_api import (  # noqa: F401
    _check_coreapi_async_naming,
    _check_public_api_return_types,
)
from ._quality_checks_coreapi_legality import (  # noqa: F401
    _check_coreapi_signature_legality,
)
from ._quality_checks_migrations import (  # noqa: F401
    _check_module_migrations_exist,
    _collect_module_tablenames,
    _extract_tablenames,
    _list_version_files,
)
from ._quality_checks_modules import (  # noqa: F401
    _check_cross_module_imports,
    _check_get_db_in_async_def,
    _check_module_import_surface,
    _is_cross_module_import_whitelisted,
    collect_module_surface_imports,
)
from ._quality_checks_services import (  # noqa: F401
    _check_services_escape_hatch_marker,
)
from ._quality_checks_size import (  # noqa: F401
    _check_sync_async_file_pairs,
    _check_sync_async_function_pairs,
)
from ._quality_checks_toctou import (  # noqa: F401
    _check_toctou_risk,
    collect_toctou_risks,
)
from ._quality_checks_twins import (  # noqa: F401
    _check_sync_async_function_twins,
)
