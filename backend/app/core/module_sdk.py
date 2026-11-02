"""The backend module SDK — the one door through which a module reaches Core.

A module shipped in this tree and a module installed from outside see the same
application, so they import from the same place. This module re-exports what a
module may use: the registration helpers, the lifecycle and context types, the
interceptor and contribution classes, the HTTP exception surface, the FastAPI
dependencies, a logger, the model bases, the system event names a subscription
needs, the migration helpers a revision uses, the field type a scanned code
arrives in, and the pagination envelopes with the helper that pages a query
into one. Anything under ``app.`` that is not
re-exported here is Core's own business: it may be renamed, split or deleted
between releases.

Two gates defend the door:

- the install-time safety scan (``module_safety_analysis``) allows a module
  outside this repository to import only ``app.core.contracts``,
  ``app.core.public_api`` and this module — the module's own package aside.
  A path that is not one of those three is refused before the code is
  imported;
- ``module_sdk_snapshot.json`` freezes the names exported here and the
  signatures of the hooks a module implements, the same additive-only way
  ``core_api_snapshot.json`` freezes the facade. A removed or renamed export,
  a parameter that moves or becomes required, or a new abstract method on a
  hook base fails the architecture lint and needs a deliberate, reviewed
  change.

The modules shipped before this door existed import Core directly; their
current reaches are frozen in ``module_import_surface_baseline.txt`` and only
ever shrink. New code in a module — in this tree or outside it — imports from
here.

Adding a name is not a breaking change: a module can ignore an export it does
not use. Removing or renaming one is, because a module importing it stops
working — the same rule ``core_api`` follows. Regenerate the snapshot after an
intentional, additive change:

    python manage.py arch lint --update-module-sdk-snapshot
"""

from __future__ import annotations

from app.core._base_module import BaseModule
from app.core._event_types import SystemEvent
from app.core._interceptor_base import (
    CategoryInterceptor,
    InterceptorError,
    ItemInterceptor,
    StorageInterceptor,
)
from app.core._module_declarations import ModuleMetadata
from app.core._require_module import require_module
from app.core.api_key_auth import register_api_key_scope
from app.core.context import ModuleContext
from app.core.contracts import ModuleModelBase
from app.core.contributions import (
    BaseContribution,
    ContributionRegistry,
    OwnedFileMeta,
    QuotaProvider,
    UploadPathResolver,
    contribution_registry,
)
from app.core.db_utils import paginate_async
from app.core.define_module import ModuleScheduledTask, define_module
from app.core.deps import (
    get_async_db,
    get_current_user_context,
    require_org,
    require_permission,
    require_read_write,
)
from app.core.exceptions import (
    AppException,
    ConflictException,
    EntityNotFoundError,
    ForbiddenException,
    NotFoundException,
    PeriodClosedError,
    QuotaExceededError,
    RoleInUseError,
    ServiceRejectionError,
    StockUnavailableError,
    ValidationException,
    map_service_errors,
)
from app.core.file_reference import cover_extension, served_url, stored_reference
from app.core.interceptors import InterceptorPipeline, interceptor_pipeline
from app.core.logging import get_logger
from app.core.migration_helpers import (
    convert_naive_timestamps_to_utc,
    create_index_if_absent,
    create_table_if_absent,
    relation_exists,
)
from app.core.module_ownership import general_rows, hidden_module_tags_async
from app.core.scan_registry import ScanProvider, scan_registry
from app.core.settings_diff import journal_config_change, record_settings
from app.database import Base as CoreModelBase
from app.i18n.service import get_current_lang, get_module_error_message
from app.schemas.pagination import (
    CursorPaginatedResponse,
    KeysetPaginatedResponse,
    PaginatedResponse,
)
from app.schemas.validators import ScannedCode

# Deliberately absent, so a module author does not read this file as "everything
# Core has": the sync ``get_db`` and ``get_current_user`` (the async session and
# the ``UserContextDTO`` are the supported pair), ``read_only_post`` (a Core
# route-shape declaration), the ORM models, ``app.config`` and the core helpers
# that carry Core's own policy (money, barcodes, file storage). A module asks
# ``core_api`` for data and reads settings through the module settings API.
#
# Two declarative bases, two owners. ``ModuleModelBase`` (from the contracts)
# is a base of the module's own: its metadata holds only the module's tables,
# so Core's autogenerate never proposes them, and it is the one the guide puts
# in front of a module installed from outside. ``CoreModelBase`` is the base
# Core itself models on, re-exported here for the modules this repository
# ships: their tables were declared on it before the SDK existed, their
# relationships reach Core's mapped classes, and their test schema is built
# from Core's metadata in one ``create_all``. A module from outside this
# repository uses ``ModuleModelBase``.

__all__ = [
    'AppException',
    'BaseContribution',
    'BaseModule',
    'CategoryInterceptor',
    'ConflictException',
    'ContributionRegistry',
    'CoreModelBase',
    'CursorPaginatedResponse',
    'EntityNotFoundError',
    'ForbiddenException',
    'InterceptorError',
    'InterceptorPipeline',
    'ItemInterceptor',
    'KeysetPaginatedResponse',
    'ModuleContext',
    'ModuleMetadata',
    'ModuleModelBase',
    'ModuleScheduledTask',
    'NotFoundException',
    'OwnedFileMeta',
    'PaginatedResponse',
    'PeriodClosedError',
    'QuotaExceededError',
    'QuotaProvider',
    'RoleInUseError',
    'ScanProvider',
    'ScannedCode',
    'ServiceRejectionError',
    'StockUnavailableError',
    'StorageInterceptor',
    'SystemEvent',
    'UploadPathResolver',
    'ValidationException',
    'contribution_registry',
    'convert_naive_timestamps_to_utc',
    'cover_extension',
    'create_index_if_absent',
    'create_table_if_absent',
    'define_module',
    'general_rows',
    'get_async_db',
    'get_current_lang',
    'get_current_user_context',
    'get_logger',
    'get_module_error_message',
    'hidden_module_tags_async',
    'interceptor_pipeline',
    'journal_config_change',
    'map_service_errors',
    'paginate_async',
    'record_settings',
    'register_api_key_scope',
    'relation_exists',
    'require_module',
    'require_org',
    'require_permission',
    'require_read_write',
    'scan_registry',
    'served_url',
    'stored_reference',
]
