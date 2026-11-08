"""Centralised module safety constants.

Single source of truth for AST safety validation rules shared between
``module_validator`` (CLI) and ``module_registry`` (runtime loader).
"""

from collections.abc import Collection
from typing import Any

TRUSTED_CORE_MODULES = {
    'core',
    'items',
    'locations',
    'categories',
    'shopping_lists',
    'stock_takes',
    'announcements',
    'printing',
    'webhooks',
    'api_keys',
    'recipes',
    'warehouse',
    'purchase_orders',
    'stats',
}

#: Every module directory this repository ships — a name is here only
#: while a ``manifest.json`` for it actually lies under ``app/modules/``.
#: The module store keeps a manifest's ``module_type`` only for names on
#: this list, and a forgotten name reads as community — visible on the
#: store screen, honest by default, one line to fix. A name here WITHOUT
#: a directory behind it is the opposite failure and a dangerous one: the
#: repository answers to it with no code of its own, so a directory
#: somebody drops under ``app/modules/`` taking that name reads as the
#: repository's own work — which is how five product features that live
#: outside the module tree (core, items, locations, categories,
#: announcements) sat in this set, and a dropped directory named
#: ``announcements`` presented itself as Official. The list is pinned to
#: the tree in both directions by ``tests/unit/test_module_shipped_lists.py``.
REPO_SHIPPED_MODULES = {
    'api_keys',
    'approvals',
    'warehouse',
    'equipment',
    'example_widgets',
    'maker',
    'nutrition',
    'printing',
    'purchase_orders',
    'recipes',
    'shopping_lists',
    'stats',
    'stock_takes',
    'vision',
    'webhooks',
}

#: The names the registry grants its first-party trust to when it meets
#: them as discovered modules — shipped directories only — and the set the
#: AST gate reads where it decides about a discovered directory.
#: TRUSTED_CORE_MODULES keeps the feature names without directories (they
#: stay reserved for module creation), but a directory under ``app/modules/``
#: with such a name is somebody's drop, not the feature, and must not
#: arrive signed as the core team's work — nor reach the core seams: a
#: trust decision a directory can claim by naming itself is no decision at
#: all, so the gate reads this set and not the wider one.
TRUSTED_SHIPPED_MODULES = frozenset(TRUSTED_CORE_MODULES & REPO_SHIPPED_MODULES)

ALWAYS_ON_MODULES = {
    'core',
    'items',
    'locations',
    'categories',
    'stats',
    # Labelling is part of the box, not a capability an organisation opts into.
    # Printed stickers reference ``/labels/scan/:code``, a route the frontend
    # registers only for enabled modules, so leaving this out of a product
    # profile ships physical labels that resolve to a 404. Single-module focus
    # mode hides the inventory navigation, but the label pool stays reachable:
    # the focus module adopts it (equipment does), and ``/labels/scan/:code``
    # is a flat printing route that stays mounted regardless.
    'printing',
    # The notification bell and the announcement banner are shell furniture:
    # every organisation gets them, none opts in. The name has no backend
    # module to register, so the sanitiser in ``api/modules.py`` could never
    # return it — the frontend gated both components on a name that never
    # arrived, and notifications piled up with no way out of the product.
    # Decision: ``announcements`` stays a module (it owns slots and its own
    # translations) and is always on; it is deliberately absent from the store,
    # which lists registered backend modules only.
    'announcements',
}

#: The always-on names a DISCOVERED module can wear. A feature without a
#: module directory (the banner, the bell) keeps its grant by being virtual;
#: a module the registry actually loaded needs the repository to ship the
#: directory its name claims — see ``is_always_on``.
ALWAYS_ON_SHIPPED_MODULES = frozenset(ALWAYS_ON_MODULES & REPO_SHIPPED_MODULES)


def is_always_on(module_name: str) -> bool:
    """Whether *module_name* is effectively always-on.

    One rule for both shapes the name can take. A name with no module
    directory behind it — the inventory core, the banner, the bell — is a
    virtual feature and keeps ``ALWAYS_ON_MODULES`` as it was. A name the
    registry loaded from a directory is a discovered module, and it wears
    always-on only when the repository ships a directory with that name:
    a directory somebody drops under ``app/modules/`` must not arrive
    switched on and impossible to turn off on the strength of its name
    alone. (A shipped name cannot be impersonated by a drop — the
    repository's own directory already stands on that path.)
    """
    if module_name not in ALWAYS_ON_MODULES:
        return False
    if module_name in ALWAYS_ON_SHIPPED_MODULES:
        return True
    from app.core.module_registry import module_registry

    return module_registry.get(module_name) is None


# Virtual toggleable modules: core features exposed in Settings → Modules and
# in product profiles, but not ``BaseModule`` subclasses (no manifest, no
# registration). Their data lives in core tables; enabling them only appends
# the literal name to ``Organization.enabled_modules``. Centralised here so
# the onboarding service, profile-switch planner and modules API share one
# source of truth.
VIRTUAL_TOGGLEABLE_MODULES = frozenset({'partners'})

#: The namespaces the core's own translations answer under — the file names
#: under ``frontend/src/i18n/locales/<language>/``. A module's namespace is
#: its own name (``frontend/src/i18n/config.ts`` reads
#: ``modules/<name>/i18n/<language>.json`` under it), so a module called
#: ``common`` answers the core's ``t("common:...")`` calls from its own file
#: and the core's own translations are the ones overwritten.
#: Pinned to the locale tree by
#: ``tests/unit/test_a_module_may_not_take_a_name_the_frontend_owns.py``.
CORE_I18N_NAMESPACES = frozenset(
    {
        'auth',
        'categories',
        'common',
        'items',
        'labels',
        'locations',
        'modules',
        'onboarding',
        'permissions',
        'scan',
    }
)

#: The directories the core keeps in the frontend source tree a module's own
#: frontend lands in — ``module install`` copies it to
#: ``frontend/src/modules/<name>/`` — from two places:
#:
#: * every directory directly under ``frontend/src``, the tree the module
#:   directory is part of and whose top-level names are the core's own
#:   source layout;
#: * every directory under ``frontend/src/modules`` the core keeps for
#:   itself (``settings``, ``shared``, ``spaces``, ``inventory``,
#:   ``launcher``, …). A module of such a name gets no directory of its
#:   own: it writes into one the core already reads from, and the core's
#:   settings screens are replaced by somebody else's.
#:
#: Shipped modules and modules installed on this machine are absent by
#: construction — their names come from ``REPO_SHIPPED_MODULES`` and from a
#: tracking entry, never from here. Pinned to the tree by
#: ``tests/unit/test_a_module_may_not_take_a_name_the_frontend_owns.py``.
CORE_FRONTEND_DIRECTORIES = frozenset(
    {
        # Every top-level directory under frontend/src.
        '__mocks__',
        'components',
        'config',
        'contexts',
        'hooks',
        'i18n',
        'lib',
        'modules',
        'pages',
        'store',
        'test',
        'types',
        'utils',
        # The directories under frontend/src/modules the core keeps.
        'announcements',
        'inventory',
        'launcher',
        'onboarding',
        'partners',
        'settings',
        'shared',
        'spaces',
    }
)


def _path_segments(path: Any) -> list[str]:
    return [segment for segment in str(path or '').split('/') if segment]


def _collect_url_names(
    routes: Any, own_prefix: list[str], names: set[str], inherited: list[str]
) -> None:
    """Walk a router tree, collecting the first path segment of every route.

    FastAPI keeps an included router as a lazy wrapper (``include_context``
    carries the prefix it was mounted under); plain routers carry finished
    ``path`` strings. Both shapes are walked, so the extraction survives
    whichever the installed FastAPI builds — a wrapper's absent attributes
    read as "nothing here", never as a crash.
    """
    for route in routes:
        context = getattr(route, 'include_context', None)
        if context is not None:
            prefix = _path_segments(getattr(context, 'prefix', ''))
            child = getattr(context, 'included_router', None)
            _collect_url_names(
                getattr(child, 'routes', ()), own_prefix, names, inherited + prefix
            )
            continue
        combined = inherited + _path_segments(getattr(route, 'path', ''))
        if own_prefix and combined[: len(own_prefix)] == own_prefix:
            combined = combined[len(own_prefix) :]
        elif own_prefix and inherited:
            # A nested route whose accumulated prefix does not sit under this
            # router's own: not part of its v1 surface.
            continue
        if combined and '{' not in combined[0]:
            names.add(combined[0].replace('-', '_'))


def core_api_url_names(router: Any) -> frozenset[str]:
    """Module names the core's own v1 routes already occupy.

    Derived from the built router, never maintained by hand: whenever core
    mounts a new route under ``/api/v1``, its first path segment becomes
    reserved the same moment. A module mounts at
    ``/api/v1/<name with underscores as dashes>``, so the segment is
    normalised back to a module-name shape (``/location-types`` →
    ``location_types``); a path parameter is not a name at all.
    """
    names: set[str] = set()
    own_prefix = _path_segments(getattr(router, 'prefix', ''))
    _collect_url_names(getattr(router, 'routes', ()), own_prefix, names, [])
    return frozenset(names)


def reserved_module_names(
    extra_reserved_names: Collection[str] = (),
) -> frozenset[str]:
    """Names a dropped module directory may not take.

    The union of every name the repository already answers to with code or
    with files — the core's feature names (``TRUSTED_CORE_MODULES``), the
    virtual modules (``VIRTUAL_TOGGLEABLE_MODULES``), the module
    directories it ships (``REPO_SHIPPED_MODULES``), the namespaces its own
    translations answer under (``CORE_I18N_NAMESPACES``) and the
    directories its frontend keeps (``CORE_FRONTEND_DIRECTORIES``) — plus
    whatever the caller derived from the running surface
    (``core_api_url_names`` for the mounted routes). Nothing here is a
    second hand-kept list: each source is the code or the tree that answers
    to the name, and a test reads the frontend ones back out of the trees
    they describe.
    """
    return frozenset(
        TRUSTED_CORE_MODULES
        | VIRTUAL_TOGGLEABLE_MODULES
        | REPO_SHIPPED_MODULES
        | CORE_I18N_NAMESPACES
        | CORE_FRONTEND_DIRECTORIES
        | set(extra_reserved_names)
    )


def reserved_name_reason(name: str) -> str | None:
    """Why *name* is taken, or ``None`` when no list here holds it.

    Which source of ``reserved_module_names`` the name came from is the
    answer a reader wants from a refusal: "is a reserved core module name"
    tells an author nothing about why ``common`` or ``settings`` is theirs
    to lose. A name reserved only by the caller's extras — a core API route
    prefix, which only the running router knows — answers ``None``: the
    caller added it and knows why.
    """
    if name in TRUSTED_CORE_MODULES or name in VIRTUAL_TOGGLEABLE_MODULES:
        return 'the core answers to it with a feature of its own'
    if name in REPO_SHIPPED_MODULES:
        return 'this repository ships a module of that name'
    if name in CORE_I18N_NAMESPACES:
        return 'the core keeps its own translations under that namespace'
    if name in CORE_FRONTEND_DIRECTORIES:
        return 'the core keeps a directory by that name under frontend/src'
    return None


#: The declared import surface of a module: the only ``app.`` paths a module
#: outside this repository may reach, its own package aside. Two of them are
#: the stability promises that already existed (``contracts_snapshot.json``
#: and ``core_api_snapshot.json``); ``module_sdk`` is the door that covers
#: everything else a module needs to *be* a module — registration, lifecycle
#: hooks, interceptors, contributions, exceptions, dependencies, logging, the
#: model base and the pagination envelopes.
#:
#: The scan is an allow-list rather than a denylist because the denylist made
#: every helper the shipped modules used a de-facto contract: it loaded, so an
#: author copied it, and nobody had promised its shape. A path not listed here
#: is refused to an untrusted module with a message naming this file.
#:
#: The modules this repository ships predate the door; what each still reaches
#: is frozen in ``module_import_surface_baseline.txt`` and cannot grow.
MODULE_IMPORT_SURFACE = (
    'app.core.contracts',
    'app.core.public_api',
    'app.core.module_sdk',
)

FORBIDDEN_IMPORT_PREFIXES = (
    'app.models',
    'app.database',
    'app.core.events.event_bus',
    # The module events.py re-exports the bus from; naming it directly is the
    # same bypass of the CoreAPI facade.
    'app.core._event_bus',
    'subprocess',
    'builtins.eval',
    'builtins.exec',
    'socket',
    'urllib.request',
)

#: Objects an untrusted module may not hold, however it reaches them. A path
#: in FORBIDDEN_IMPORT_PREFIXES closes one road to an object; every app module
#: that imports the object for its own use is another, because its namespace
#: hands the object out — the public events facade itself holds the raw bus.
#: So the scan resolves each ``app.`` name a module reaches and compares it
#: with these by identity (``module_safety_analysis``), wherever it was bound.
FORBIDDEN_OBJECTS = (
    # The raw bus; ``core_api.events`` is the module-safe way to it.
    'app.core._event_bus.event_bus',
    # The class: a fresh instance is a second bus without the facade's checks.
    'app.core._event_bus.EventBus',
)

#: Objects only a module this repository ships may hold, compared the same
#: way. The module SDK re-exports Core's declarative base as
#: ``CoreModelBase`` for the shipped modules whose tables were Core's before
#: the SDK existed; ``app.core.module_sdk`` is on the import surface, so the
#: path alone let a module from outside declare its tables in Core's
#: metadata, where Core's autogenerate proposes them as a core migration.
#: A module from outside declares on ``ModuleModelBase``.
SHIPPED_ONLY_OBJECTS = ('app.database.Base',)

CORE_EXEMPTIONS: dict[str, list[str]] = {
    # Each entry grants an import the scan would refuse without it — no
    # standing allowance for one a module might make later
    # (tests/unit/test_the_scan_names_what_it_bans.py).
    'equipment': ['app.models.item'],
    'approvals': ['app.models.user'],
    # Maker: batched read of the records' view for the recipe catalog (escape
    # hatch in stock_consumption.py — CoreAPI stock.list_quants_async is
    # per-template only).
    'maker': [
        'app.models.stock_quants_from_records',
        # Type-only import in models.py, under `if TYPE_CHECKING:` — the
        # recipe-to-template relationship annotation. Never executes; the
        # scanner reads every statement, so the name itself is the exemption.
        # Owner: maker module maintainers.
        'app.models.product_template',
    ],
}

FORBIDDEN_CALLS = (
    'eval',
    'exec',
    '__import__',
    'import_module',
)

CAPABILITY_MAP: dict[str, list[str]] = {
    'network': ['requests', 'httpx', 'urllib', 'socket'],
    'filesystem': ['os', 'shutil', 'builtins.open', 'open'],
    'process': ['subprocess', 'sys'],
    'database': ['sqlalchemy', 'sqlmodel'],
}
