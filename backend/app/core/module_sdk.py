"""The backend module SDK — the one door through which a module reaches Core.

A module shipped in this tree and a module installed from outside see the same
application, so they import from the same place. This module re-exports what a
module may use: the API key scope registration, the lifecycle and context types, the
interceptor and contribution classes, the HTTP exception surface, the FastAPI
dependencies, a logger, the model bases, the system event names a subscription
needs, the migration helpers a revision uses, the field type a scanned code
arrives in, the lot-trace source a module names its movements through, the
pagination envelopes with the helper that pages a query into one, the helper
that writes a location's path, the resolver that reads a free-text unit
against the catalogue, and the effective-expiry rule an opened
package is judged by. Anything under ``app.`` that is not
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

Six registrations stay Core's own for now and are deliberately not re-exported:
export enrichers (``app.core.export_enrichers``), record placement
(``app.core.module_ownership``), template ranking (``app.core.template_ranking``),
supplier prices (``app.core.cost_estimates``), the period guard
(``app.core.period_guard``) and the label renderers (``app.core.label_rendering``).
The modules this repository ships register through them by importing Core
directly; a module installed from outside has no door to them, and a name added
here would be a promise kept for every release after. CONTRACTS_STABILITY.md
lists them as in-tree only.

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
from app.core.audit_actor import audit_actor_scope, current_actor
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
from app.core.csv_export import rows_to_csv
from app.core.datetimes import utc_now
from app.core.db_utils import hit_constraint, paginate_async
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
from app.core.file_reference import (
    cover_extension,
    cover_leaf,
    cover_leaf_of,
    served_url,
    stored_reference,
)
from app.core.held_back_locations import register_held_back_locations
from app.core.import_sheet import cell_text, read_sheet
from app.core.interceptors import InterceptorPipeline, interceptor_pipeline
from app.core.location_path import join_location_path
from app.core.logging import get_logger
from app.core.lot_trace import LotTraceSource, register_lot_trace_source
from app.core.migration_helpers import (
    convert_naive_timestamps_to_utc,
    create_index_if_absent,
    create_table_if_absent,
    relation_exists,
)
from app.core.module_ownership import general_rows, hidden_module_tags_async
from app.core.module_scope import get_context_tags_of
from app.core.open_package import effective_expiry
from app.core.scan_registry import ScanProvider, scan_registry
from app.core.settings_diff import journal_config_change, record_settings
from app.core.uom_resolver import UomResolverAsync
from app.core.upload_validation import (
    ATTACHMENT_CONTENT_TYPES,
    FileSignatureMismatchError,
    FileTooLargeError,
    FileTypeNotAllowedError,
    UploadMessages,
    UploadPolicy,
)
from app.core.utils import pick_by_lang
from app.core.work_in_progress import register_work_in_progress_provider
from app.database import Base as CoreModelBase
from app.i18n.service import get_current_lang, get_module_error_message
from app.schemas.pagination import (
    CursorPaginatedResponse,
    KeysetPaginatedResponse,
    PaginatedResponse,
)
from app.schemas.validators import ScannedCode
from app.services.identity_service import get_current_user

# Deliberately absent, so a module author does not read this file as "everything
# Core has": the sync ``get_db`` (the async session and the ``UserContextDTO``
# are the supported pair, and ``get_current_user`` is exported for a module
# that authenticates its own ASGI transport rather than a FastAPI route),
# ``read_only_post`` (a Core route-shape declaration), the ORM models,
# ``app.config`` and the core helpers that carry Core's own policy (money,
# barcodes, file storage). A module asks ``core_api`` for data and reads
# settings through the module settings API.
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
    'ATTACHMENT_CONTENT_TYPES',
    'AppException',
    'BaseContribution',
    'BaseModule',
    'CategoryInterceptor',
    'ConflictException',
    'ContributionRegistry',
    'CoreModelBase',
    'CursorPaginatedResponse',
    'EntityNotFoundError',
    'FileSignatureMismatchError',
    'FileTooLargeError',
    'FileTypeNotAllowedError',
    'ForbiddenException',
    'InterceptorError',
    'InterceptorPipeline',
    'ItemInterceptor',
    'KeysetPaginatedResponse',
    'LotTraceSource',
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
    'UploadMessages',
    'UploadPathResolver',
    'UploadPolicy',
    'UomResolverAsync',
    'ValidationException',
    'audit_actor_scope',
    'cell_text',
    'current_actor',
    'contribution_registry',
    'convert_naive_timestamps_to_utc',
    'cover_extension',
    'cover_leaf',
    'cover_leaf_of',
    'create_index_if_absent',
    'create_table_if_absent',
    'define_module',
    'effective_expiry',
    'general_rows',
    'get_async_db',
    'get_context_tags_of',
    'get_current_lang',
    'get_current_user',
    'get_current_user_context',
    'get_logger',
    'get_module_error_message',
    'hidden_module_tags_async',
    'hit_constraint',
    'interceptor_pipeline',
    'join_location_path',
    'journal_config_change',
    'map_service_errors',
    'paginate_async',
    'pick_by_lang',
    'record_settings',
    'register_api_key_scope',
    'register_held_back_locations',
    'register_lot_trace_source',
    'read_sheet',
    'register_work_in_progress_provider',
    'relation_exists',
    'require_module',
    'require_org',
    'require_permission',
    'require_read_write',
    'rows_to_csv',
    'scan_registry',
    'served_url',
    'stored_reference',
    'utc_now',
]
