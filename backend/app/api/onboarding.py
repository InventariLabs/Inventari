"""
POST /onboarding/setup — applies a product profile to an organisation.

Triggered once during first-run onboarding. Sets active_profile_id and
onboarding_completed on the organisation, seeds default data, and enables
the modules defined in the profile.

POST /onboarding/switch-profile — admin-only endpoint that switches an
already-onboarded organisation to a different product profile.
"""

from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field, field_validator

from app.api.dependencies import get_current_admin_user
from app.core._require_module import invalidate_enabled_modules
from app.core.cache import cache_delete
from app.core.contracts import (
    AuditAction,
    AuditTargetType,
    OrganizationDTO,
    UserContextDTO,
)
from app.core.deps import get_async_db, require_org
from app.core.exceptions import AppException, NotFoundException
from app.core.logging import get_logger
from app.core.product_profiles import get_profile
from app.core.public_api import core_api
from app.i18n.service import get_current_lang, get_error_message
from app.schemas.organization import validated_country_code
from app.services._org_reads import get_by_id_async
from app.services.focus_mode_service import (
    FocusModeApplyError,
    FocusModeError,
    enter_focus_mode,
    load_org_for_focus_async,
    preview_focus_mode,
)
from app.services.onboarding_service import country_document_preset
from app.services.profile_switch_planner import ProfileSwitchError
from app.services.profile_switch_service import (
    ProfileSwitchApplyError,
    apply_profile_switch,
    preview_profile_switch,
)

logger = get_logger(__name__)

router = APIRouter()


class OnboardingSetupRequest(BaseModel):
    profile_id: str
    # Currency picked on the package-selection screen — stored on
    # the organization so fleet valuation sums in the tenant's currency.
    currency: str | None = Field(None, pattern=r'^[A-Z]{3}$')
    # What the reader ticked on the second step. ``None`` means they
    # skipped it, or the client predates it, and the profile's list stands.
    modules: list[str] | None = None
    # The fourth choice beside the profiles: one module that is the whole
    # application. ``profile_id`` then names the neutral base the mode sits on
    # and is what Settings -> My modules returns to when the mode is left.
    focus_module: str | None = Field(None, min_length=1, max_length=50)
    # The zone the setup screen's browser reported, sent beside the currency
    # so a fresh organization's day starts where its readers' does — expiry
    # dates, inventory periods and reports all hang off it. ``None`` means the
    # client predates the field, and the UTC column default stands.
    timezone: str | None = Field(None, max_length=64)
    # The name the founder gave the organization. ``None`` (or only spaces)
    # keeps the name registration made from their own: invitations, outgoing
    # mail and printed documents carry it, so it is asked for here rather than
    # left to be found in Settings.
    organization_name: str | None = Field(None, max_length=255)
    # Where the organization sits. The country decides the standard tax rate
    # and the partner tax-id rule its documents follow, so it is asked here
    # rather than left to be found in Settings. ``None`` keeps it unset.
    country: str | None = Field(None, max_length=2)
    # The founder accepted the country's document preset (see
    # ``GET /onboarding/country-preset``). It rides on top of the profile's
    # own preset and never changes whether value tracking is on.
    use_country_preset: bool = False

    @field_validator('country', mode='before')
    @classmethod
    def validate_country(cls, v: object) -> str | None:
        return validated_country_code(v)


def _setup_timezone(name: str | None) -> str | None:
    """The zone the setup screen's browser reported, if this server reads it.

    The name is a hint, not an instruction: it comes from a browser whose
    tzdb may be newer than the server's, and onboarding is the one step that
    must not stop with a refusal the reader has no answer for — a 422 here
    strands them on the wizard. An unreadable name is dropped and the
    organization keeps its UTC default, the degradation
    ``org_timezone_async`` would perform on every read anyway. The same
    answer ``stock_moves._client_timezone`` gives the export's zone hint.
    """
    if not name:
        return None
    try:
        ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        logger.warning(
            'Onboarding setup: the browser reported a time zone this server '
            'cannot read (%r) — keeping the organization default',
            name,
        )
        return None
    return name


class ProfileSwitchRequest(BaseModel):
    profile_id: str = Field(min_length=1, max_length=50)
    dry_run: bool = True


class ProfileSwitchDiffResponse(BaseModel):
    from_profile_id: str | None
    to_profile_id: str
    enable: list[str]
    disable: list[str]
    cascade_disable: list[str]
    disable_all: list[str]
    unchanged: list[str]
    manual_kept: list[str]
    final_enabled_modules: list[str]
    module_config_overwrite: list[str]
    warnings: list[str] = Field(default_factory=list)
    #: The new profile numbers locations like shelves (``A-02-01``) where the
    #: old one drew random codes. Nothing is renumbered by the switch: the
    #: screen offers it, and the warehouse's Locations tab does it.
    offer_location_renumbering: bool = False


class ProfileSwitchResponse(BaseModel):
    applied: bool
    diff: ProfileSwitchDiffResponse
    organization: OrganizationDTO | None = None


class CountryPresetResponse(BaseModel):
    #: The document preset onboarding offers for the country; ``None`` when it
    #: has none (the country still gets its rate and tax-id rule).
    preset: str | None


@router.get('/country-preset', response_model=CountryPresetResponse)
async def onboarding_country_preset(
    country: str | None = None,
    current_user: UserContextDTO = Depends(get_current_admin_user),
) -> CountryPresetResponse:
    """Name the document preset the setup screen offers for a country."""
    require_org(current_user)
    return CountryPresetResponse(
        preset=country_document_preset(validated_country_code(country))
    )


@router.post('/setup', response_model=OrganizationDTO)
async def onboarding_setup(
    body: OnboardingSetupRequest,
    current_user: UserContextDTO = Depends(get_current_admin_user),
    db=Depends(get_async_db, scope='function'),
) -> OrganizationDTO:
    """
    Apply a product profile to the current organisation.

    1. Validates the profile exists.
    2. Applies the seed bundle (storage types, default data).
    3. Enables the profile's default modules (running system_on_enable callbacks).
    4. Marks onboarding_completed = True and saves active_profile_id.

    First run only: an organisation that already completed onboarding changes
    profile through ``/switch-profile``, which plans the diff instead of
    re-seeding and re-enabling blind; the request is answered with 409
    ``ONBOARDING_ALREADY_COMPLETED``, with no exception. A one-module choice
    is applied in the same transaction as the profile: when the module is
    refused or its focus mode fails to start, the profile is rolled back with
    it, onboarding stays open and the request can simply be repeated.
    """
    require_org(current_user)

    if not get_profile(body.profile_id):
        raise NotFoundException('profile')

    if not current_user.organization_id:
        raise NotFoundException('organization')

    organization = await core_api.organizations.get_async(
        db, current_user.organization_id
    )
    if not organization:
        raise NotFoundException('organization')

    focus_module = body.focus_module
    focus_org = None
    if focus_module:
        focus_org = await load_org_for_focus_async(db, organization.id)
        if focus_org is None:
            raise NotFoundException('organization')

    if organization.onboarding_completed:
        raise AppException(
            status_code=409,
            code='ONBOARDING_ALREADY_COMPLETED',
            message=get_error_message(
                'onboarding_already_completed', get_current_lang()
            ),
        )

    before_modules = list(organization.enabled_modules or [])

    # A refused module must leave onboarding open, so the choice is checked
    # before the profile is applied rather than undone after it.
    if focus_org is not None and focus_module:
        try:
            preview_focus_mode(organization=focus_org, focus_module=focus_module)
        except (FocusModeError, ProfileSwitchError) as exc:
            raise exc.conflict() from exc

    try:
        applied = await core_api.organizations.apply_onboarding_profile_async(
            db,
            organization,
            body.profile_id,
            user=current_user,
            currency=body.currency,
            modules=body.modules,
            timezone=_setup_timezone(body.timezone),
            organization_name=(body.organization_name or '').strip() or None,
            country=body.country,
            use_country_preset=body.use_country_preset,
        )
    except ValueError as exc:
        raise NotFoundException('organization') from exc
    except RuntimeError:
        logger.exception('Onboarding setup failed')
        raise AppException(
            status_code=500,
            code='INTERNAL_ERROR',
            message=get_error_message('internal_error', get_current_lang()),
        ) from None

    # The wizard decides the module set the organization runs with, and it
    # used to leave no row at all — an audit of a fresh org showed a counter
    # that had not moved while the modules had. The switch route writes the
    # same shape for the same reason; here the "before" side is the set the
    # organization was created with, which onboarding replaces wholesale.
    await core_api.audit_log.log_action_async(
        db,
        organization_id=applied.id,
        user_id=current_user.id,
        action=AuditAction.UPDATE,
        target_type=AuditTargetType.PRODUCT_PROFILE,
        target_id=applied.id,
        snapshot={
            'name': body.profile_id,
            'before': {'enabled_modules': before_modules},
            'after': {
                'profile_id': body.profile_id,
                'enabled_modules': list(applied.enabled_modules or []),
            },
        },
    )
    if focus_org is not None and focus_module:
        # One change: the profile and the chosen module are committed together
        # once focus mode has written both, and a failure on the way rolls both
        # back. Committing
        # the profile first left the organization completed with no module
        # chosen, and the normal entry then skipped onboarding for good.
        return await _enter_chosen_module(db, focus_org, focus_module, current_user)

    # Commit before clearing the module caches: cleared earlier, a concurrent
    # read re-caches the old committed set for the full TTL.
    await db.commit()
    await cache_delete(f'org:{applied.id}:modules')
    await invalidate_enabled_modules(applied.id)
    return applied


async def _enter_chosen_module(
    db, organization, focus_module: str, current_user: UserContextDTO
) -> OrganizationDTO:
    """Enter focus mode on top of the profile applied in this transaction.

    The same service Settings -> My modules calls, so leaving the mode
    restores the snapshot taken here and ``active_profile_id`` is untouched.
    Nothing is committed before this runs: any refusal or failure rolls the
    profile back with it, so onboarding stays open for a retry.
    """
    try:
        await enter_focus_mode(
            db=db,
            organization=organization,
            focus_module=focus_module,
            user=current_user,
        )
    except (FocusModeError, ProfileSwitchError) as exc:
        await db.rollback()
        raise exc.conflict() from exc
    except FocusModeApplyError:
        await db.rollback()
        logger.exception('Entering focus mode during onboarding failed')
        raise AppException(
            status_code=500,
            code='INTERNAL_ERROR',
            message=get_error_message('internal_error', get_current_lang()),
        ) from None
    await core_api.audit_log.log_action_async(
        db,
        organization_id=organization.id,
        user_id=current_user.id,
        action=AuditAction.UPDATE,
        target_type=AuditTargetType.MODULE,
        target_id=organization.id,
        snapshot={
            'name': focus_module,
            'before': {'focus_module': None},
            'after': {'focus_module': focus_module},
        },
    )
    await db.commit()
    result = await core_api.organizations.get_async(db, organization.id)
    if result is None:
        raise NotFoundException('organization')
    return result


@router.post('/switch-profile', response_model=ProfileSwitchResponse)
async def switch_profile(
    body: ProfileSwitchRequest,
    current_user: UserContextDTO = Depends(get_current_admin_user),
    db=Depends(get_async_db, scope='function'),
) -> ProfileSwitchResponse:
    """Switch the current organisation to a new product profile.

    Admin-only. By default the call is a dry-run: it returns the diff
    without any DB writes, hooks, seed, or cache invalidation. Pass
    ``dry_run=false`` to apply the switch transactionally.

    Errors:
        * 401 — no auth.
        * 403 — not an admin, or no organisation.
        * 404 — unknown profile.
        * 409 — invalid target (cycle, premium not allowed, etc).
        * 500 — apply failed (transaction rolled back).
    """
    org_id = require_org(current_user)

    profile = get_profile(body.profile_id)
    if not profile:
        raise NotFoundException('profile')

    organization = await get_by_id_async(db, org_id)
    if not organization:
        raise NotFoundException('organization')

    try:
        if body.dry_run:
            plan = preview_profile_switch(organization=organization, profile=profile)
            return ProfileSwitchResponse(
                applied=False,
                diff=ProfileSwitchDiffResponse(**plan.model_dump()),
                organization=None,
            )

        previous_profile_id = organization.active_profile_id
        plan = await apply_profile_switch(
            db=db,
            organization=organization,
            profile=profile,
            user=current_user,
        )
        # A profile switch enables and disables modules across the whole
        # organization, and the log recorded none of it.
        await core_api.audit_log.log_action_async(
            db,
            organization_id=organization.id,
            user_id=current_user.id,
            action=AuditAction.UPDATE,
            target_type=AuditTargetType.PRODUCT_PROFILE,
            target_id=organization.id,
            snapshot={
                'name': profile.id,
                'before': {'profile_id': previous_profile_id},
                'after': {
                    'profile_id': profile.id,
                    'enabled': plan.enable,
                    'disabled': plan.disable + plan.cascade_disable,
                },
            },
        )
        # The apply mutates ``organization`` in place; the response DTO
        # reads the deferred columns, so they are loaded here — the list
        # lives on the model, next to the columns it names.
        await db.refresh(
            organization, list(core_api.organizations.deferred_dto_columns)
        )
        return ProfileSwitchResponse(
            applied=True,
            diff=ProfileSwitchDiffResponse(**plan.model_dump()),
            organization=OrganizationDTO.model_validate(organization),
        )
    except ProfileSwitchError as exc:
        raise exc.conflict() from exc
    except ProfileSwitchApplyError:
        logger.exception('Profile switch apply failed')
        raise AppException(
            status_code=500,
            code='INTERNAL_ERROR',
            message=get_error_message('internal_error', get_current_lang()),
        ) from None
