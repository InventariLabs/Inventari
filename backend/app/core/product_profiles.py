"""
Product Profile registry — minimal version (no DB table, static definitions).

A ProductProfile defines a set of enabled modules and a seed bundle
that is applied during onboarding. This is the minimum needed to support
the onboarding flow (POST /onboarding/setup).

A later version may add route overrides, nav overrides and i18n
terminology.
"""

from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core._module_declarations import LocalizedText

# Launcher grouping for profile-aware navigation. Each module can be assigned
# to one of these categories; the Launcher UI groups cards accordingly.
LauncherCategory = Literal[
    'core',
    'business',
    'analytics',
    'integrations',
    'system',
]


#: Seed handle of the location a profile offers as the organization's
#: default quarantine shelf — the place a receipt line coded DAMAGE or
#: QUALITY_HOLD that carries no batch of its own is booked onto.
#:
#: The document profile's ``quarantine_location_id`` is what the receipt
#: executor reads, and with none named the receipt is refused at completion
#: — after the receiving session has recorded everything, in front of a
#: member who cannot open the document settings to clear it. A profile that
#: seeds a location under this code has it named on the document profile
#: during onboarding, so a fresh organization never reaches that refusal.
#: The settings section stays the way to change the answer.
QUARANTINE_LOCATION_CODE = 'QUARANTINE'


class ProfileStorageLocation(BaseModel):
    """A starting location a product profile seeds for a new organization.

       Modules declare theirs in ``StorageLocationDeclaration``; a profile
       declares them here. Core seeds whatever the organization's profile asks
    for and knows no location names of its own — before it hardcoded
       three on food storage types, so an organization on any other profile
       silently got none.
    """

    #: Storage type the location stands on. Must be a type the profile's seed
    #: bundle brings, or the seed logs and skips it (never silently).
    type_code: str
    #: English name written to the database.
    name: str
    #: English names this location used to carry. A row that has no seed
    #: handle yet and still bears one is the same location, so a rename
    #: here does not seed a second one beside it.
    former_names: list[str] = []
    #: Stable handle recorded in the row's ``settings['seed']`` — how a later
    #: pass tells a row nobody has touched from one the user renamed (the
    #: same mechanism module declarations seed with).
    code: str | None = None
    #: The name per language, keyed by language code. A location's name is
    #: data — editable, printed, exported — so it is written once, in the
    #: language the seed runs in, falling back to ``name``.
    translations: dict[str, LocalizedText] = {}


#: Where a first product goes when nothing else is there. ``clean_core``
#: declares it as its one starting location, and the seed adds it for any
#: organization left without an ordinary location — internal, owned by no
#: module, not the quarantine shelf — so adding the first product never
#: starts with setting up a warehouse. It is an ordinary row, renamed or
#: moved like any other. Stands on ``SHELF``, which the base seed brings to
#: every profile.
MAIN_STORAGE_LOCATION = ProfileStorageLocation(
    name='Main Storage',
    type_code='SHELF',
    code='MAIN_STORAGE',
    translations={
        'en': LocalizedText(name='Main Storage'),
        'pl': LocalizedText(name='Magazyn główny'),
        'de': LocalizedText(name='Hauptlager'),
        'fr': LocalizedText(name='Stockage principal'),
        'es': LocalizedText(name='Almacén principal'),
    },
)


class ProductProfile(BaseModel):
    """Minimal product profile definition.

    Extended fields (route_overrides, nav_overrides, terminology) are deferred
    until white-label / dominant-module requirements are clearer.
    """

    id: str  # stable identifier, e.g. 'food_home'
    name: str  # display name, e.g. 'Food & Home'
    description: str
    default_modules: list[str]  # modules enabled by default for new orgs
    seed_profile: str  # maps to app.seed_profiles.* function name
    theme_id: str | None = None  # optional theme override (future use)
    icon: str | None = None
    # Per-module settings overrides applied during onboarding.
    # Format: {module_name: {setting_key: value}}. The onboarding service
    # validates each entry against the module's get_settings_schema() and
    # skips entries that fail — the module still gets enabled with the
    # schema defaults instead.
    module_config: dict[str, dict[str, Any]] = Field(default_factory=dict)
    # Optional DocumentProfile preset name (see
    # ``app.modules.warehouse.document_profile_service.PRESETS``) applied
    # after the warehouse module is enabled. Used to flip
    # ``value_tracking_enabled`` and related value-tracking settings that
    # cannot be expressed through ``module_config`` (the warehouse module
    # declares no settings schema). ``None`` leaves the default 'Simple'
    # profile created by the documents on_install hook untouched.
    document_preset: str | None = None
    # Launcher profile-awareness: maps each enabled module to one of the
    # `LauncherCategory` literals. The Launcher UI uses this to group
    # navigation cards into sections (core, business, analytics,
    # integrations, system). This is an *override*: a module absent from the
    # map keeps its own declared `launcher.category`, falling back to
    # 'business' (frontend `resolveProfileCategory`). Leaving the map empty
    # therefore means "this profile has no opinion about grouping", not
    # "render a flat list" — the sections still appear, built from the
    # modules' own metadata.
    launcher_categories: dict[str, LauncherCategory] = Field(default_factory=dict)
    # Per-profile visual identity so a
    # profile switch looks like switching apps. `theme` maps CSS variable
    # names to RGB triplets (e.g. `--color-accent-500` -> "16 185 129"),
    # matching the convention used by module themes; profile themes are
    # applied AFTER module themes so the profile wins on key conflicts.
    # `branding` carries the i18n subtitle key rendered next to the
    # "Inventari" wordmark in the shell (e.g.
    # {"subtitle_key": "profiles.food_home.subtitle"}).
    theme: dict[str, str] | None = None
    branding: dict[str, str] | None = None
    # the starting locations a new organization on this profile gets.
    # Empty means "this profile seeds none" — either deliberately, or because
    # its modules seed their own through ``system_on_enable``.
    default_locations: list[ProfileStorageLocation] = Field(default_factory=list)
    # What the second onboarding step offers on top of `default_modules`,
    # so a maker's first move is not "go into Settings and turn it on
    # yourself". A shortlist, not an index: an installation may ship
    # hundreds of modules and most belong only in the store, which has the
    # search and categories this screen does not.
    #
    # Empty means the profile has no second step. That is the household
    # answer: a person who came to know what is in the fridge gets a working
    # application without being asked anything about modules. It is also why
    # no profile is obliged to offer anything — a preset that fits its reader
    # has nothing to ask.
    suggested_modules: list[str] = Field(default_factory=list)
    # How a new location's code is made when its warehouse names no template
    # of its own (``services/storage/_codes.py``). A business reads the shelf
    # off its sticker, so its codes follow the location tree (``A-02-01``);
    # a household pantry has no aisles and racks to number, and a code there
    # is only a code (``LOC-7KQ2``).
    # Kept off the profile list the API serves: the screens read the result
    # (a warehouse's template, a switch's offer to renumber), not the rule.
    location_codes: Literal['tree', 'random'] = Field('tree', exclude=True)


# The neutral baseline. An organization that has not picked a profile yet is
# read as this one — "no industry preset", not "the food one".
DEFAULT_PROFILE_ID = 'clean_core'


# -------------------------------------------------------------------------
# Registry ― built-in profiles shipped with Inventari
# -------------------------------------------------------------------------

PRODUCT_PROFILES: dict[str, ProductProfile] = {
    'food_home': ProductProfile(
        id='food_home',
        name='Food & Home',
        description='Track food inventory, cold storage, and shelves. Includes recipes and shopping lists.',
        default_modules=[
            'core',
            'items',
            'locations',
            'categories',
            'shopping_lists',
            'recipes',
            'stock_takes',
            'nutrition',
            'vision',
            'stats',
        ],
        seed_profile='food_home',
        icon='ShoppingBasket',
        location_codes='random',
        # Empty on purpose, and it is the whole point of this profile. Someone
        # who came here to know what is in the fridge and what they can cook
        # should get a working application without being asked a single
        # question about modules. An advanced self-hoster who wants API keys
        # or webhooks will find them in the module store; everybody else
        # never has to learn the word.
        #
        # Empty also means this profile has no second onboarding step at all —
        # the step exists to offer, and a profile with nothing to offer has
        # nothing to show.
        suggested_modules=[],
        # Home users benefit from the cost breakdown on each recipe so
        # they can plan a weekly budget — keep it enabled. Equipment
        # warning windows use the module defaults (30 / 7) since home
        # devices rarely need long procurement cycles.
        module_config={
            'recipes': {
                'enable_cost_calculation': True,
            },
            # Rotation, spend forecasts and purchase patterns need months of
            # transaction history; a forty-item pantry gets noise, not a
            # conclusion. The overview tab stays — it answers "what
            # expires soon", which a home user does ask. The value signal on
            # it does not: a home pantry keeps no cost ledger for that figure
            # to be read back from.
            'stats': {
                'enable_analytics': False,
                'show_inventory_value': False,
            },
        },
        launcher_categories={
            'core': 'system',
            'items': 'business',
            'locations': 'business',
            'categories': 'business',
            'shopping_lists': 'business',
            'recipes': 'business',
            'stock_takes': 'business',
            'nutrition': 'business',
            'vision': 'integrations',
            'stats': 'analytics',
        },
        # Explicit emerald palette (≈ the neutral default accent, declared
        # here so the profile owns its identity and can drift from the
        # default later). Home = inventory items.
        # The primary ramp mirrors accent:
        # `primary-*` is the dominant action colour across the app, so a
        # profile switch must repaint it too. Ramps are tuned for light
        # mode; dark mid-tones behave like the current accent scale, and
        # the `--primary`/`--ring` aliases in index.css inherit
        # automatically because they reference the same variables.
        theme={
            '--color-accent-50': '236 253 245',
            '--color-accent-100': '209 250 229',
            '--color-accent-200': '167 243 208',
            '--color-accent-300': '110 231 183',
            '--color-accent-400': '52 211 153',
            '--color-accent-500': '16 185 129',
            '--color-accent-600': '5 150 105',
            '--color-accent-700': '4 120 87',
            '--color-accent-800': '6 95 70',
            '--color-accent-900': '6 78 59',
            '--color-primary-50': '236 253 245',
            '--color-primary-100': '209 250 229',
            '--color-primary-200': '167 243 208',
            '--color-primary-300': '110 231 183',
            '--color-primary-400': '52 211 153',
            '--color-primary-500': '16 185 129',
            '--color-primary-600': '5 150 105',
            '--color-primary-700': '4 120 87',
            '--color-primary-800': '6 95 70',
            '--color-primary-900': '6 78 59',
            '--color-primary-950': '2 44 34',
        },
        branding={'subtitle_key': 'profiles.food_home.subtitle'},
        # The three Core used to create for everyone. They belong here: this
        # is the profile whose seed brings the types they stand on.
        default_locations=[
            ProfileStorageLocation(
                name='Fridge',
                former_names=['Cold Storage'],
                type_code='FRIDGE',
                code='COLD_STORAGE',
                translations={
                    'en': LocalizedText(name='Fridge'),
                    'pl': LocalizedText(name='Lodówka'),
                    'de': LocalizedText(name='Kühlschrank'),
                    'fr': LocalizedText(name='Réfrigérateur'),
                    'es': LocalizedText(name='Nevera'),
                },
            ),
            ProfileStorageLocation(
                name='Shelf A',
                type_code='PANTRY',
                code='SHELF_A',
                translations={
                    'en': LocalizedText(name='Shelf A'),
                    'pl': LocalizedText(name='Półka A'),
                    'de': LocalizedText(name='Regal A'),
                    'fr': LocalizedText(name='Étagère A'),
                    'es': LocalizedText(name='Estantería A'),
                },
            ),
            ProfileStorageLocation(
                name='Freezer',
                former_names=['Cold Room'],
                type_code='FREEZER',
                code='COLD_ROOM',
                translations={
                    'en': LocalizedText(name='Freezer'),
                    'pl': LocalizedText(name='Zamrażalnia'),
                    'de': LocalizedText(name='Tiefkühllager'),
                    'fr': LocalizedText(name='Chambre froide'),
                    'es': LocalizedText(name='Cámara fría'),
                },
            ),
        ],
    ),
    'equipment_wms': ProductProfile(
        id='equipment_wms',
        name='Equipment & Warehouse',
        description='Track IT assets and equipment with warehouse procurement — purchase orders, receiving, check-out/in, maintenance logs, and warranty alerts.',
        default_modules=[
            'core',
            'items',
            'locations',
            'categories',
            'stock_takes',
            'equipment',
            'warehouse',
            'partners',
            'purchase_orders',
            'approvals',
            'stats',
        ],
        seed_profile='equipment_wms',
        icon='Monitor',
        # Production is the gap this profile leaves widest: a warehouse
        # that assembles anything needs it, and no profile enables it.
        suggested_modules=['maker', 'vision', 'api_keys', 'webhooks'],
        document_preset='Full Value',
        # IT procurement cycles are slow — warn earlier than the module
        # defaults. Value tracking is turned on via ``document_preset`` so a
        # fresh WMS org sees amounts on documents/POs without a manual visit
        # to Settings → Document profile.
        module_config={
            'equipment': {
                'warranty_warning_days': 60,
                'maintenance_warning_days': 14,
            },
            # Named explicitly rather than inherited: a profile says
            # what it wants, and a warehouse with procurement history is
            # exactly who the analytics tab and the inventory value are for.
            'stats': {
                'enable_analytics': True,
                'show_inventory_value': True,
            },
        },
        launcher_categories={
            'core': 'system',
            'items': 'business',
            'locations': 'business',
            'categories': 'business',
            'stock_takes': 'business',
            'equipment': 'business',
            'warehouse': 'business',
            'partners': 'business',
            'purchase_orders': 'business',
            'approvals': 'business',
            'stats': 'analytics',
        },
        # Blue palette — moved 1:1 from the equipment module theme so
        # the profile is the single source of truth. Home = equipment
        # assets. The primary ramp mirrors accent
        # (see the food_home comment for the rationale and light-mode
        # tuning caveat).
        theme={
            '--color-accent-50': '239 246 255',
            '--color-accent-100': '219 234 254',
            '--color-accent-200': '191 219 254',
            '--color-accent-300': '147 197 253',
            '--color-accent-400': '96 165 250',
            '--color-accent-500': '59 130 246',
            '--color-accent-600': '37 99 235',
            '--color-accent-700': '29 78 216',
            '--color-accent-800': '30 64 175',
            '--color-accent-900': '30 58 138',
            '--color-primary-50': '239 246 255',
            '--color-primary-100': '219 234 254',
            '--color-primary-200': '191 219 254',
            '--color-primary-300': '147 197 253',
            '--color-primary-400': '96 165 250',
            '--color-primary-500': '59 130 246',
            '--color-primary-600': '37 99 235',
            '--color-primary-700': '29 78 216',
            '--color-primary-800': '30 64 175',
            '--color-primary-900': '30 58 138',
            '--color-primary-950': '23 37 84',
        },
        branding={'subtitle_key': 'profiles.equipment_wms.subtitle'},
        # One location, and it is the shelf this profile's own receipts need:
        # the rooms a warehouse holds goods in are the equipment module's to
        # seed (Server Room, IT Storage, Main Warehouse, through
        # ``system_on_enable``), while where a damaged unit waits is a
        # documents answer — a document profile with no quarantine location
        # names refuses to complete such a receipt, and the refusal lands on
        # the floor after the whole receiving session is done. Onboarding
        # names this one on the document profile (see
        # ``QUARANTINE_LOCATION_CODE``); the document settings section is
        # still the way to move it.
        default_locations=[
            ProfileStorageLocation(
                name='Quarantine',
                type_code='STORAGE_ROOM',
                code=QUARANTINE_LOCATION_CODE,
                translations={
                    'en': LocalizedText(name='Quarantine'),
                    'pl': LocalizedText(name='Kwarantanna'),
                    'de': LocalizedText(name='Quarantäne'),
                    'fr': LocalizedText(name='Quarantaine'),
                    'es': LocalizedText(name='Cuarentena'),
                },
            ),
        ],
    ),
    'clean_core': ProductProfile(
        id='clean_core',
        # 'Custom' / 'Własny' — the id stays `clean_core` (it is a database
        # value and a seeder name), but "Core" is our architecture word, not a
        # user concept. See docs/MODULE_NAMES.md § "Workspace mode names".
        # Both fields are a fallback only; the visible label lives under
        # `profiles.clean_core.*` in the frontend common namespace.
        name='Custom',
        # The old text promised "build your own configuration from scratch",
        # which switching never does: `profile_switch_planner` keeps every
        # manually enabled module (`manual_kept`) and touches no data at all.
        description='No industry preset — a neutral base you shape yourself.',
        default_modules=[
            'core',
            'items',
            'locations',
            'categories',
            'stock_takes',
        ],
        seed_profile='clean_core',
        icon='Box',
        # The capabilities no preset hands you. Someone who picked "no
        # industry preset" is going to the store anyway; this is a shortcut.
        suggested_modules=['warehouse', 'maker', 'api_keys', 'webhooks'],
        # clean_core deliberately leaves launcher_categories empty: it states
        # no opinion about grouping, so each module lands in the section it
        # declares for itself. Reviewed again while naming the mode and kept —
        # grouping is an opinion about a domain, and a mode called "Custom"
        # holds none. It also does not declare `module_config` overrides —
        # every module keeps its own defaults. This is the "neutral" baseline.
        launcher_categories={},
        # Amber palette. This profile used to declare no theme at all, which
        # meant it fell back to the default accent — the very emerald
        # `food_home` declares explicitly, so the two modes were visually
        # indistinguishable. Neutral about domains is not the same as having
        # no identity.
        # Steps are Tailwind's amber ramp unshifted: `primary-700` is what
        # the filled Button variants paint, and amber-700 measures 5.0:1
        # against white (the ramp step below it does not — see the note in
        # components/ui/Button.tsx). Recorded caveat: amber also carries a
        # warning meaning elsewhere in this app (cascade disables, warranty
        # alerts). Those use literal `amber-*` utilities, which a profile
        # theme does not repaint, so the two do not collide mechanically —
        # the overlap was accepted knowingly. See docs/MODULE_NAMES.md.
        theme={
            '--color-accent-50': '255 251 235',
            '--color-accent-100': '254 243 199',
            '--color-accent-200': '253 230 138',
            '--color-accent-300': '252 211 77',
            '--color-accent-400': '251 191 36',
            '--color-accent-500': '245 158 11',
            '--color-accent-600': '217 119 6',
            '--color-accent-700': '180 83 9',
            '--color-accent-800': '146 64 14',
            '--color-accent-900': '120 53 15',
            '--color-primary-50': '255 251 235',
            '--color-primary-100': '254 243 199',
            '--color-primary-200': '253 230 138',
            '--color-primary-300': '252 211 77',
            '--color-primary-400': '251 191 36',
            '--color-primary-500': '245 158 11',
            '--color-primary-600': '217 119 6',
            '--color-primary-700': '180 83 9',
            '--color-primary-800': '146 64 14',
            '--color-primary-900': '120 53 15',
            '--color-primary-950': '69 26 3',
        },
        # `branding` stays None on purpose. food_home renders "Inventari
        # for Home" and equipment_wms "Inventari for Business"; a mode defined
        # by having no domain has nothing to append, and inventing a subtitle
        # would claim an identity it does not have. This is a decision, not an
        # omission — do not "fix" it by adding a subtitle_key.
        # One location, on the neutral shelf type this profile seeds. Measured
        # before: a fresh organization here got zero, because Core tried
        # to create three on food types `clean_core` does not seed and skipped
        # each one silently — the storage list opened empty. Three dummy
        # locations in a mode that holds no domain opinion would be three
        # things to delete; one is somewhere to put the first item.
        default_locations=[MAIN_STORAGE_LOCATION],
    ),
}


def get_profile(profile_id: str) -> ProductProfile | None:
    """Return a profile by ID, or None if not found."""
    return PRODUCT_PROFILES.get(profile_id)


def get_all_profiles() -> list[ProductProfile]:
    """Return all available profiles in display order."""
    return list(PRODUCT_PROFILES.values())


def apply_profile_seed(
    profile_or_id: ProductProfile | str,
    db: Session,
    *,
    organization_id: UUID,
    insert_only: bool = False,
    commit: bool = True,
) -> None:
    """Apply the seed bundle associated with a profile.

    Accepts either a profile object or an ID. When given an ID, looks the
    profile up in the registry. Imports lazily to avoid circular imports
    at module load time.

    Args:
        profile_or_id: Profile instance or ID.
        db: Active SQLAlchemy session.
        organization_id: The organization that chose the profile. Required,
            not optional: a profile is picked by one tenant, so its domain
            seed belongs to that tenant (AGENTS.md §4). Seeding it without an
            owner writes ``organization_id IS NULL`` rows, and those are read
            by every organization on the installation.
        insert_only: When True, existing rows are left untouched (used
            by profile switching to preserve user customisations).
        commit: When True (default), commits at the end. Pass False to
            keep the seeder inside a larger transaction.
    """
    import importlib

    if isinstance(profile_or_id, ProductProfile):
        profile: ProductProfile = profile_or_id
    else:
        fetched = get_profile(profile_or_id)
        if fetched is None:
            raise RuntimeError(f"Unknown profile: '{profile_or_id}'")
        profile = fetched

    module = importlib.import_module(f'app.seed_profiles.{profile.seed_profile}')
    seed_fn_name = f'seed_{profile.seed_profile}'
    seed_fn = getattr(module, seed_fn_name)
    seed_fn(
        db,
        organization_id=organization_id,
        insert_only=insert_only,
        commit=commit,
    )
