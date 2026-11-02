"""
OnboardingService — applies a product profile to an organisation.

Called from app/api/onboarding.py after request validation.  Service owns
all DB writes so the API layer stays read-only per architecture rules.
"""

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import UserContextDTO
from app.core.exceptions import ServiceRejectionError, catalogue_refusal
from app.core.logging import get_logger
from app.core.module_registry import module_registry
from app.core.module_safety import (
    ALWAYS_ON_MODULES,
    VIRTUAL_TOGGLEABLE_MODULES,
    is_always_on,
)
from app.core.product_profiles import (
    QUARANTINE_LOCATION_CODE,
    ProductProfile,
    apply_profile_seed,
    get_profile,
)
from app.models.organization import Organization
from app.models.storage_location import StorageLocation
from app.services.module_lifecycle_service import (
    ModuleLifecycleError,
    enable_modules_async,
)
from app.services.profile_module_config_service import (
    apply_profile_module_config_async,
)

logger = get_logger(__name__)


def country_document_preset(country: str | None) -> str | None:
    """The document preset onboarding offers for *country*, if it has one."""
    from app.modules.warehouse.country_tax_rules import get_country_rule

    rule = get_country_rule(country)
    return rule.document_preset if rule else None


async def apply_onboarding_profile_async(
    db: AsyncSession,
    org: Organization,
    profile_id: str,
    profile: ProductProfile | None = None,
    user: UserContextDTO | None = None,
    currency: str | None = None,
    modules: list[str] | None = None,
    timezone: str | None = None,
    organization_name: str | None = None,
    country: str | None = None,
    use_country_preset: bool = False,
) -> Organization:
    """Apply a product profile to an organization.

       1. Apply the seed bundle (storage types, default data, UoM) and
          create the starting locations the profile declares.
       2. Enable the profile's default modules via the shared lifecycle
          executor (``enable_modules_async``). ``run_custom_hook=False``
          preserves the historical onboarding behaviour, which only ran
          the framework ``system_on_enable`` hook. The class-level
          ``on_enable`` is intentionally NOT invoked here — the profile
          switch service owns that path so the executor can share both
          hooks without breaking first-run onboarding. Module start data
          (categories, default storage locations) is therefore seeded by
          ``system_on_enable`` from the module's metadata declarations, so
          it arrives identically on every enable path.
       3. Apply the profile's ``module_config`` overrides through the shared
          path, which journals every namespace it moves. Invalid
          config is logged and skipped — the module still gets enabled with
          defaults.
       4. Mark onboarding as complete.

       Args:
           db: Active ``AsyncSession``.
           org: Organization model instance.
           profile_id: Product profile ID.
           profile: Optional pre-fetched profile (bypasses registry lookup).
           user: Authenticated user context — used as the creator of any
    module-declared default storage locations.
           modules: What the reader ticked on the second onboarding step.
           ``None`` means they skipped it (or the client predates it),
           and the profile's own list stands. Anything outside what the
           profile enables or offers is refused: the offer is the
           contract, or a client could name any module it liked.
           timezone: The zone the setup screen's browser reported, already
           settled to a name this server reads — ``None`` (the client
           predates the field, or the name did not read) leaves the column
           on its UTC default.
           organization_name: The name the founder gave the organization on the setup
           screen; ``None`` keeps the one registration derived.
           country: The ISO code the founder gave for where the organization
           sits; ``None`` leaves the column as it was. Written before the
           document preset so the country's rate and tax-id rule answer
           from the first document.
           use_country_preset: The founder accepted the offer of the country's
           document preset (names, numbering, print layout). Applied after
           the profile's own preset with that preset's value-tracking choice
           kept; a country without a preset, or without the warehouse module,
           leaves it alone.

       Beyond the profile's answer, modules the admin switched on by hand
       through POST /modules/toggle before onboarding finished are kept
       (the org's ``pre_onboarding_manual_modules`` record, consumed here).

       Raises ValueError for unknown profiles.
       Raises RuntimeError if seed or module-init fails.
    """
    if profile is None:
        profile = get_profile(profile_id)
    if not profile:
        raise ServiceRejectionError('onboarding_profile_unknown', profile=profile_id)

    try:
        # The seed stays inside the caller's transaction: the profile switch
        # takes the same seed with the same instruction, and a failure after
        # it has to be able to take the seeded rows back with everything else.
        await db.run_sync(
            lambda s: apply_profile_seed(
                profile, s, organization_id=org.id, commit=False
            )
        )
    except SQLAlchemyError as exc:
        logger.exception('Seed failed for profile %s', profile_id)
        raise RuntimeError(f'Seed failed: {exc}') from exc

    current_modules = list(org.enabled_modules or [])
    kept = await _settle_the_module_set_async(db, org, profile_id, profile, modules)
    new_modules = []
    # Virtual toggleable modules (no ``BaseModule``) are enabled by appending
    # the literal name to ``enabled_modules`` — there are no hooks to run.
    virtual_to_enable = []
    for name in kept:
        if name in current_modules:
            continue
        module = module_registry.get(name)
        if module is not None:
            new_modules.append(module)
        elif name in VIRTUAL_TOGGLEABLE_MODULES:
            virtual_to_enable.append(name)
    if new_modules:
        try:
            await enable_modules_async(
                new_modules,
                org.id,
                db=db,
                user=user,
                run_custom_hook=False,
            )
        except ModuleLifecycleError as exc:
            logger.exception(
                'system_on_enable failed for one of %s',
                [m.metadata.name for m in new_modules],
            )
            raise RuntimeError(str(exc)) from exc

    await apply_profile_module_config_async(
        db,
        org,
        profile.module_config,
        default_modules=profile.default_modules,
        profile_id=profile_id,
        user_id=user.id if user is not None else None,
    )
    await _apply_document_preset_async(db, org, profile, kept)
    await _apply_country_preset_async(
        db, org, country or org.country, kept, use_country_preset
    )

    org.enabled_modules = kept
    org.pre_onboarding_manual_modules = None
    org.active_profile_id = profile_id
    org.onboarding_completed = True
    # Persist the currency picked on the onboarding screen — fleet
    # valuation sums in the tenant's currency, not the global USD default.
    if currency:
        org.currency = currency
    # And the zone the setup screen's browser reported: when a day starts
    # for expiry dates, inventory periods and reports is the organization's
    # clock, and a fresh one used to sit on UTC whatever its readers' did.
    # The name was settled to a readable one at the door, so storing it
    # here cannot put an unreadable zone on the row.
    if timezone:
        org.timezone = timezone
    if organization_name:
        org.name = organization_name
    if country:
        org.country = country
    db.add(org)

    # The starting locations the profile declares: a home
    # organization's "Fridge / Shelf A / Freezer" used to stay a
    # dead declaration, and the first product landed on a "create a
    # storage" wall. Run for every profile, declared locations or not: the
    # seeder also leaves one ordinary location where nothing else did. The
    # seeder reads active_profile_id, set above — the pending org write
    # autoflushes under its SELECT.
    if user is not None:
        from app.services.storage._defaults import (
            create_default_storage_locations_async,
        )

        await create_default_storage_locations_async(db, str(org.id), str(user.id))
    else:
        # A location is created by someone (NOT NULL); onboarding
        # without a user context exists only off the product paths,
        # but staying loud beats a silent empty storage list.
        logger.warning(
            'Onboarding profile %s: no user context reached onboarding — '
            'no starting locations seeded on '
            'organization %s.',
            profile_id,
            org.id,
        )
    # The shelf is only half an answer until the document profile names
    # it: a receipt that carries a damaged unit is refused at completion
    # otherwise — the last step of a receiving session, in front of
    # whoever on the floor may not open the document settings to clear
    # it.
    await _name_the_quarantine_shelf_the_profile_seeded_async(db, org, kept)

    await db.flush()
    # The caller commits, and only then clears the org's module caches: a
    # read in between would re-cache the old set for the full TTL.
    return org


async def _settle_the_module_set_async(
    db: AsyncSession,
    org: Organization,
    profile_id: str,
    profile: ProductProfile,
    modules: list[str] | None,
) -> list[str]:
    """The module set onboarding writes: the profile's answer plus what the
    admin toggled on by hand, naming anything that did not survive.

    The answer to "what kind of place is this?" is the profile's list, plus
    what nobody opts into. It used to be the union of the profile and
    whatever the organization already had, which on a fresh one meant an
    eight-module default written into the ORM — so a household choosing
    "Food & Home" received the document register its profile does not list.

    The manual record is the one exception, and an earned one: a
    module the admin switched on through POST /modules/toggle while
    onboarding stood open is an explicit decision the profile question never
    asked about — kept, not dropped, because overwriting it with the chosen
    set switched a module off without its disable hook and told nobody. The
    record is consumed here; onboarding runs once, so it never serves again.

    Anything the organization holds beyond profile-plus-manual is logged
    rather than silently dropped: onboarding runs once, on an organization
    that has answered nothing, so the remainder should be empty — and a
    module removed here would go without its disable hook.
    """
    chosen = _chosen_modules(profile, modules)
    manual = await _manual_toggle_record_async(db, org)
    kept = chosen + [name for name in manual if name not in chosen]
    org.pre_onboarding_manual_modules = None

    current_modules = list(org.enabled_modules or [])
    dropped = [name for name in current_modules if name not in kept]
    if dropped:
        logger.warning(
            'Onboarding profile %s does not cover already-enabled module(s) %s '
            'on organization %s; they are being switched off without their '
            'disable hook.',
            profile_id,
            dropped,
            org.id,
        )
    return kept


async def _manual_toggle_record_async(db: AsyncSession, org: Organization) -> list[str]:
    """The org's manual-toggle record, loaded for the read below.

    ``pre_onboarding_manual_modules`` is deferred on the model, and the
    instance arrives from the caller's query, which did not load it:
    reading it cold fires a lazy SELECT outside the greenlet. Refresh the
    one column when it is unloaded; an instance that already carries the
    value (a test, or a write earlier in this transaction) keeps it.
    """
    from sqlalchemy import inspect as sa_inspect

    if 'pre_onboarding_manual_modules' in sa_inspect(org).unloaded:
        await db.refresh(org, ['pre_onboarding_manual_modules'])
    return list(org.pre_onboarding_manual_modules or [])


def _chosen_modules(profile: ProductProfile, selection: list[str] | None) -> list[str]:
    """The modules a fresh organization ends up with.

    Without a selection the profile's own list stands, which is what
    onboarding did before the second step existed. With one, the reader
    decides — they may drop what their kind of place does not need and add
    from what the profile offers. The pinned modules are appended either
    way: unticking everything is a legitimate answer, shipping an
    organization with no inventory at all is not.
    """
    if selection is None:
        chosen = list(profile.default_modules)
    else:
        offered = set(profile.default_modules) | set(profile.suggested_modules)
        refused = sorted(set(selection) - offered)
        if refused:
            raise catalogue_refusal(
                'onboarding_modules_not_offered',
                profile=profile.id,
                modules=', '.join(refused),
            )
        chosen = list(dict.fromkeys(selection))
    chosen.extend(
        name
        for name in sorted(ALWAYS_ON_MODULES)
        if is_always_on(name) and name not in chosen
    )
    return chosen


async def _apply_document_preset_async(
    db: AsyncSession,
    org: Organization,
    profile: ProductProfile,
    enabled_modules: list[str],
) -> None:
    """Apply ``profile.document_preset`` to the org's DocumentProfile.

    ``value_tracking_enabled`` and its sibling fields live on the documents
    module's ``DocumentProfile`` table, not in ``module_config`` (the
    warehouse module declares no settings schema). When a profile declares a
    ``document_preset`` and the warehouse module is enabled, the named preset
    (see ``document_profile_service.PRESETS``) is applied so that fresh orgs
    get the promised value-tracking configuration without a manual visit to
    Settings → Document profile.
    """
    if not profile.document_preset:
        return
    if 'warehouse' not in enabled_modules:
        logger.warning(
            'Profile %s declares document_preset %r but documents is not '
            'enabled — skipping',
            profile.id,
            profile.document_preset,
        )
        return
    from app.modules.warehouse.document_profile_service import apply_preset

    try:
        await apply_preset(db, org.id, profile.document_preset)
    except ValueError as exc:
        logger.warning(
            'Profile %s document_preset %r is unknown (%s) — skipping',
            profile.id,
            profile.document_preset,
            exc,
        )


async def _apply_country_preset_async(
    db: AsyncSession,
    org: Organization,
    country: str | None,
    enabled_modules: list[str],
    accepted: bool,
) -> None:
    """Apply the country's document preset when the founder accepted it.

    Without the warehouse module there is no document profile to put it on.
    """
    if not accepted or 'warehouse' not in enabled_modules:
        return
    from app.modules.warehouse.document_profile_service import apply_country_preset

    await apply_country_preset(db, org.id, country)


async def _name_the_quarantine_shelf_the_profile_seeded_async(
    db: AsyncSession,
    org: Organization,
    enabled_modules: list[str],
) -> None:
    """Point the document profile at the quarantine shelf the profile seeds.

    The receipt executor books a line coded DAMAGE or QUALITY_HOLD that
    carries no batch of its own onto the quarantine location the document
    profile names, and with none named the receipt is refused at completion
    — after the whole receiving session has recorded its quantities, and in
    front of whoever on the floor may not open the document settings to put
    one there. A product profile that seeds a location under
    ``QUARANTINE_LOCATION_CODE`` means its organizations to have one; the
    name is written here, once, with the rest of what onboarding decides for
    a fresh organization. The document settings section stays the way to
    change the answer.
    """
    if 'warehouse' not in enabled_modules:
        return

    rows = (
        (
            await db.execute(
                select(StorageLocation).where(StorageLocation.organization_id == org.id)
            )
        )
        .scalars()
        .all()
    )
    shelf = next(
        (
            row
            for row in rows
            if ((row.settings or {}).get('seed') or {}).get('code')
            == QUARANTINE_LOCATION_CODE
        ),
        None,
    )
    if shelf is None:
        return

    from app.modules.warehouse.document_profile_service import name_quarantine_shelf

    await name_quarantine_shelf(db, org.id, shelf.id)
