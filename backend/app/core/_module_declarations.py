from typing import Any, Literal

from pydantic import BaseModel

from app.core.logging import get_logger
from app.core.module_manifest_schema import ModuleCategory, PermissionDef

logger = get_logger(__name__)

CORE_MODULES: frozenset[str] = frozenset(
    {
        'core',
        'items',
        'locations',
        'categories',
        'shopping_lists',
        'stock_takes',
        'stats',
        'warehouse',
    }
)

ALWAYS_ENABLED_MODULES: frozenset[str] = frozenset(
    {
        'core',
        'items',
        'locations',
        'categories',
    }
)


class CategoryDeclaration(BaseModel):
    """Category declaration in module metadata."""

    code: str
    name: str
    icon: str | None = None
    context_tag: str | None = (
        None  # Neutral context label (e.g. 'cold_storage', 'equipment', 'media')
    )
    field_definitions: list[dict[str, Any]] = []


class LocalizedText(BaseModel):
    """A declared row's name and description in one language."""

    name: str
    description: str | None = None


class StorageTypeDeclaration(BaseModel):
    """Storage type declaration in module metadata."""

    code: str
    name: str
    #: The declared name per language, keyed by language code.
    #:
    #: A type's name is data, the same way a location's is: it stands in the
    #: storage picker, on the storage's card and in every exported row. Seeded
    #: in English and left there, it answered a Polish reader in a language
    #: the rest of the wizard did not speak — and no screen could repair it,
    #: because a name the organization owns is not something a later release
    #: may rewrite. The seeder writes the entry for the language it is
    #: enabling in, and falls back to ``name`` for a language that declares
    #: none (see ``translations`` on ``StorageLocationDeclaration``).
    translations: dict[str, LocalizedText] = {}
    context_schema: list[str]
    behavior_mode: str = 'STOCK'
    icon: str | None = None


class StorageLocationDeclaration(BaseModel):
    """Default storage location declared in module metadata.

    Seeded per organization by ``BaseModule.system_on_enable``, which runs
    on every enable path (onboarding, profile switch, App Store toggle)
    before the module's own ``on_enable``. Declared here, the start data is
    seeded the same way everywhere and needs no code of the module's.
    """

    name: str
    description: str | None = None
    behavior_mode: str = 'NONE'
    context_tag: str | None = None
    #: Stable handle for the row this declaration seeds, e.g. ``SERVER_ROOM``.
    #:
    #: Marks the row as seeded and records, under ``settings['seed']``, the
    #: name that was written — which is how a later pass tells a row nobody
    #: has touched from one the user has renamed.
    #:
    #: It used to serve a second purpose: a client translated the code at
    #: display time, because the name was written in English and then read by
    #: people working in five languages. That covered React screens and
    #: nothing else — the path under a picker, the search box, the label
    #: printed on the door and every exported document still carried the
    #: stored name, so the same room answered to two names depending on where
    #: you looked. A location's name is data: editable, printed, exported.
    #: Its language is chosen once, when it is written (see ``translations``).
    code: str | None = None
    #: The declared name and description per language, keyed by language code.
    #:
    #: The seeder writes the entry for the language the module is being
    #: enabled in, and falls back to ``name``/``description`` above for a
    #: language that declares none.
    translations: dict[str, LocalizedText] = {}


class ModuleMetadata(BaseModel):
    """Module metadata used for identification and UI display."""

    name: str
    version: str | None = None
    display_name: str
    description: str
    icon: str
    module_type: Literal['core', 'official', 'cloud', 'community'] = 'community'
    category: ModuleCategory = 'other'
    requires: list[str] = []
    #: Soft integration, not a dependency: never gates enabling — the store
    #: surfaces a disabled companion as a hint on the module's card instead.
    optional_requires: list[str] = []
    #: Declared resources the module touches (network, filesystem, process,
    #: database). This is not a security boundary — it is
    #: information for the operator, shown on the store card.
    capabilities: list[str] = []
    #: None means nobody signed the module. The default used to be 'Core Team',
    #: which made every anonymous community module present itself under the
    #: core team's name — the one place a user decides whether to trust
    #: installed code. Core modules are labelled by the registry, not by this
    #: default (see module_registry's is_core handling).
    author: str | None = None
    license: str | None = None
    homepage: str | None = None
    requires_api_key: bool = False
    is_trusted: bool = False
    is_premium: bool = False
    # Registered and usable, but never offered: see ModuleManifest.is_reference.
    is_reference: bool = False
    categories: list[CategoryDeclaration] = []
    storage_types: list[StorageTypeDeclaration] = []
    default_storage_locations: list[StorageLocationDeclaration] = []
    consumes_stock_quant: bool = False
    # Permissions the module owns, carried over from manifest.json. Core keys a
    # module merely depends on are filtered out upstream — this list is what the
    # RBAC catalog publishes under the module's own section.
    permissions: list[PermissionDef] = []
