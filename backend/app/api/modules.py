from typing import Any

from fastapi import APIRouter, Body, Depends, Query

from app.api.dependencies import get_current_admin_user
from app.core.contracts import AuditAction, AuditTargetType, UserContextDTO
from app.core.db_utils import after_commit
from app.core.deps import get_async_db, get_current_user_context, require_org
from app.core.exceptions import (
    AppException,
    ForbiddenException,
    NotFoundException,
    ServiceRejectionError,
)
from app.core.logging import get_logger
from app.core.module_registry import (
    ALWAYS_ON_MODULES,
    is_always_on,
    module_registry,
)
from app.core.module_safety import (
    REPO_SHIPPED_MODULES,
    VIRTUAL_TOGGLEABLE_MODULES,
)
from app.core.public_api import core_api
from app.i18n.service import get_current_lang, get_error_message
from app.schemas._common import (
    ModuleEnablePreview,
    ModuleSettingsResponse,
    ModuleSettingsUpdateResponse,
    ModuleToggleResponse,
)
from app.schemas.module import (
    FocusModeDiff,
    FocusModeRequest,
    FocusModeResponse,
    ModuleInfo,
    ModuleToggle,
)
from app.schemas.pagination import PaginatedResponse
from app.services.focus_mode_service import (
    FocusModeApplyError,
    FocusModeError,
    enter_focus_mode,
    exit_focus_mode,
    load_org_for_focus_async,
    preview_focus_mode,
)
from app.services.module_service import ModuleService
from app.services.profile_switch_planner import ProfileSwitchError, ProfileSwitchPlan

logger = get_logger(__name__)

router = APIRouter()

# Frontend-only built-in modules (no backend registration, not in TRUSTED_CORE_MODULES)
_ALWAYS_ON_FRONTEND_ONLY = [
    'inventory',
    'spaces',
    'dashboard',
    'admin',
    'settings',
]


def _frontend_state_of(name: str, tracked: dict) -> str:
    """Say whether this installation has screens for *name*.

    Every module in the tree does, by construction — the check that guarantees
    it is that no backend module ships without a frontend sibling. Only a
    community module can be missing one, and the tracking file is where the
    installer already writes both what the package declared and what landed.
    """
    entry = tracked.get(name)
    if entry is None:
        return 'present'
    if entry.get('has_frontend', True):
        return 'present'
    # Entries written before the installer recorded the declaration cannot tell
    # the two apart; call them headless rather than accuse an old install.
    return 'incomplete' if entry.get('declares_frontend', False) else 'headless'


def _signature_of(name: str, tracked: dict) -> dict:
    """What the install verified about this package, for the store card.

    The author and the licence the card shows come off the package's own
    ``module.yaml``. The digest covers that file, so a verified signature
    turns those fields from a claim into something a key stands behind —
    and the card has to be able to tell the two apart. A module that was
    never installed as a package (everything in the tree) reports nothing:
    its code is in the repository, and a signature line would be theatre.
    """
    entry = tracked.get(name)
    if entry is None:
        return {}
    status = entry.get('signature_status')
    if status not in ('verified', 'unsigned'):
        # An entry from before signatures existed (or written with signing
        # off) verified nothing — and the one thing worse than showing an
        # unsigned package is showing it as if nobody needed to check.
        status = 'unsigned'
    return {
        'signature_status': status,
        'signed_by': entry.get('signature_key_id') or None
        if status == 'verified'
        else None,
    }


def _effective_always_on() -> list[str]:
    """The always-on names that still carry their grant.

    ``ALWAYS_ON_MODULES`` is the policy; ``is_always_on`` is what takes a
    name away from a dropped directory that borrowed it. Every place that
    grants implicit enablement reads this, not the raw policy set.
    """
    return [name for name in ALWAYS_ON_MODULES if is_always_on(name)]


def get_available_modules_list():
    # Imported inside the function on purpose: the tracking file is read at
    # call time, and the tests that describe what the store shows replace
    # this function at its source.
    from app.core.module_tracking import load_module_tracking

    tracked = load_module_tracking()
    modules = []

    virtual_modules = [
        ModuleInfo(
            name='partners',
            display_name='Partners',
            description='Manage suppliers, customers, and service providers for B2B workflows.',
            icon='building-2',
            requires=[],
            version='0.5.0',
            author='Core Team',
            module_type='official',
            category='business',
            # Partners have no BaseModule of their own: their data lives in
            # the core partner tables, and an empty list next to cards that
            # state what they touch reads as "touches nothing".
            capabilities=['database'],
            is_trusted=True,
        ),
    ]
    modules.extend(virtual_modules)

    for m in module_registry.get_all():
        if any(existing.name == m.metadata.name for existing in modules):
            continue

        # A worked example is documentation, not a product. It stays
        # registered so the scaffold and the tests can read it.
        if m.metadata.is_reference:
            continue

        # Who stands behind a module is decided by where its CODE comes
        # from, never by the manifest carrying its own claim: an installed
        # package reads as community, and so does a directory discovered
        # on disk that the repository did not ship (the registry walks the
        # filesystem, so such a directory is a full runtime citizen with
        # no tracking entry — the one shape where "tracked" and "in the
        # repository" disagree). Only REPO_SHIPPED_MODULES keeps its type.
        module_type = m.metadata.module_type
        if m.metadata.name in tracked or m.metadata.name not in REPO_SHIPPED_MODULES:
            module_type = 'community'

        modules.append(
            ModuleInfo(
                name=m.metadata.name,
                display_name=m.metadata.display_name,
                description=m.metadata.description,
                icon=m.metadata.icon,
                module_type=module_type,
                category=m.metadata.category,
                capabilities=m.metadata.capabilities,
                requires=m.metadata.requires,
                optional_requires=m.metadata.optional_requires,
                version=m.metadata.version,
                author=m.metadata.author,
                license=m.metadata.license,
                homepage=m.metadata.homepage,
                is_trusted=m.metadata.is_trusted,
                # One rule for the store card and the enablement API
                # alike: a discovered module wears always-on only when
                # the repository ships a directory with that name — a
                # dropped directory named like the feature is a drop,
                # not the feature, so the card may not offer what the
                # API would refuse (or refuse what it offers).
                is_always_on=is_always_on(m.metadata.name),
                safety_warnings=module_registry.get_safety_warnings(m.metadata.name),
                requires_api_key=m.metadata.requires_api_key,
                degraded=module_registry.is_degraded(m.metadata.name),
                frontend_state=_frontend_state_of(m.metadata.name, tracked),
                **_signature_of(m.metadata.name, tracked),
            )
        )

    return modules


@router.get('/available', response_model=PaginatedResponse[ModuleInfo])
async def get_available_modules(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    current_user: UserContextDTO = Depends(get_current_user_context),
    db=Depends(get_async_db, scope='function'),
):
    """List modules available for the current organization based on entitlements.

    Transaction note: this is the one API function that rolls back by hand.
    The ``allowed_modules`` read is best-effort — a failure is logged and
    swallowed so the list still renders — but the failed statement may have
    poisoned the transaction, and the request goes on to use the same session.
    Unlike every other rollback, it is not followed by a raise, so the
    request-scoped session cannot undo it for us; the rollback is the recovery
    that keeps the rest of the request usable.
    """
    allowed_list: list[str] = []
    if current_user.organization_id:
        try:
            organization = await core_api.organizations.get_async(
                db, current_user.organization_id
            )
            if organization and organization.allowed_modules:
                allowed_list = organization.allowed_modules
        except Exception:  # best-effort allowed_modules read; never blocks the list
            logger.exception(
                'Failed to read allowed_modules for org %s',
                current_user.organization_id,
            )
            # The failed read may have poisoned the transaction, and the
            # request goes on to use the session: the one rollback that is
            # not followed by a raise, so the request-scoped session cannot
            # do it for us.
            await db.rollback()
            allowed_list = []

    modules = get_available_modules_list()

    # Filter premium modules that are not unlocked for this org
    if allowed_list is not None:
        modules = [m for m in modules if not m.is_premium or m.name in allowed_list]

    return PaginatedResponse.from_full_list(modules, offset=offset, limit=limit)


@router.get(
    '/my',
    # list-envelope-exception: the names of the modules switched on, read whole
    response_model=list[str],
)
async def get_my_modules(
    current_user: UserContextDTO = Depends(get_current_user_context),
    db=Depends(get_async_db, scope='function'),
):
    """Get list of modules enabled for current organization."""
    from app.core.cache import cache_delete, cache_get_or_set

    org_id = current_user.organization_id
    if not org_id:
        always_on = _effective_always_on() + _ALWAYS_ON_FRONTEND_ONLY
        return always_on + [
            m.metadata.name
            for m in module_registry.get_all()
            if not m.metadata.is_premium and not m.metadata.is_reference
        ]

    key = f'org:{org_id}:modules'
    installed = _installed_modules_fingerprint()

    async def _compute() -> dict[str, Any]:
        return {
            'installed': installed,
            'modules': await _resolve_modules(current_user, db),
        }

    cached = await cache_get_or_set(key, ttl=300, factory=_compute)
    if not isinstance(cached, dict) or cached['installed'] != installed:
        # Written by a process that registered a different set of modules --
        # before an install, upgrade or uninstall and its restart (or by a
        # build that cached the bare list). The list
        # depends on what is registered, so the old answer is not ours to serve.
        await cache_delete(key)
        cached = await cache_get_or_set(key, ttl=300, factory=_compute)
    return cached['modules']


def _installed_modules_fingerprint() -> str:
    """The registered modules and their versions, as one comparable string."""
    return ','.join(
        sorted(
            f'{m.metadata.name}@{m.metadata.version}' for m in module_registry.get_all()
        )
    )


async def _resolve_modules(current_user: UserContextDTO, db: Any) -> list[str]:
    """Resolve enabled modules for an organization (uncached)."""
    always_on = _effective_always_on() + _ALWAYS_ON_FRONTEND_ONLY
    organization = current_user.organization
    if not organization or not organization.enabled_modules:
        return always_on + [
            m.metadata.name
            for m in module_registry.get_all()
            if not m.metadata.is_premium and not m.metadata.is_reference
        ]

    legacy_map = {'statistics': 'stats'}
    registered_names = {m.metadata.name for m in module_registry.get_all()}

    sanitized = []
    for m in organization.enabled_modules:
        name = legacy_map.get(m, m)
        if (
            is_always_on(name)
            or name in _ALWAYS_ON_FRONTEND_ONLY
            or name in registered_names
            or name in VIRTUAL_TOGGLEABLE_MODULES
        ) and name not in sanitized:
            sanitized.append(name)

    for name in always_on:
        if name not in sanitized:
            sanitized.append(name)

    return sanitized


class _MissingDependencyError(ValueError):
    """A module this one needs is not enabled — carries the name, not a sentence.

    The endpoint knows the request language; a literal raised down here would
    reach a Polish interface in English (and did).
    """

    def __init__(self, module_name: str) -> None:
        super().__init__(module_name)
        self.module_name = module_name


def _display_name(module_name: str) -> str:
    """The name the store card shows for *module_name*, for a refusal to use.

    A refusal that names the slug ("Module 'warehouse' must be enabled
    first.") asks the administrator to find a card the store titles
    "Warehouse".
    """
    module = module_registry.get(module_name)
    return (module.metadata.display_name if module else None) or module_name


def _check_module_dependencies(
    module_name: str,
    enabled_modules: list[str],
    _visited: set[str] | None = None,
) -> None:
    """Raise if required modules are not enabled or the requirements loop.

    Skips modules in ALWAYS_ON_MODULES (implicitly enabled). ``_visited`` holds
    the modules on the path being walked — the ancestors — so a prerequisite
    shared by two branches is not mistaken for a loop; only a module that
    requires itself, through any chain, is.
    """
    if _visited is None:
        _visited = set()
    if module_name in _visited:
        raise ServiceRejectionError('module_dependency_cycle', module=module_name)

    module = module_registry.get(module_name)
    if not module:
        return  # not registered — will fail elsewhere
    _visited.add(module_name)
    try:
        for req in module.metadata.requires:
            if is_always_on(req):
                continue
            if req not in enabled_modules:
                raise _MissingDependencyError(req)
            # Recurse to verify transitive dependencies
            _check_module_dependencies(req, enabled_modules, _visited)
    finally:
        _visited.discard(module_name)


@router.get('/{module_name}/enable-preview', response_model=ModuleEnablePreview)
async def get_enable_preview(
    module_name: str,
    current_user: UserContextDTO = Depends(get_current_admin_user),
    db=Depends(get_async_db, scope='function'),
):
    """What switching *module_name* on would resume — the question before the click.

    Admin only, like the switch itself. The module answers; a module that holds
    nothing it could resume answers zero, and so does one the registry does not
    know by an instance (a virtual or always-on name).
    """
    if not current_user.organization_id:
        raise ForbiddenException(
            message=get_error_message('module_org_required', get_current_lang()),
        )
    if (
        module_registry.get(module_name) is None
        and module_name not in _effective_always_on() + _ALWAYS_ON_FRONTEND_ONLY
        and module_name not in VIRTUAL_TOGGLEABLE_MODULES
    ):
        raise NotFoundException('module')
    module_instance = module_registry.get(module_name)
    resumes = (
        await module_instance.enable_preview(current_user.organization_id, db)
        if module_instance is not None
        else None
    )
    return ModuleEnablePreview(resumes=resumes or 0)


@router.post('/toggle', response_model=ModuleToggleResponse)
async def toggle_module(
    module_toggle: ModuleToggle,
    current_user: UserContextDTO = Depends(get_current_admin_user),
    db=Depends(get_async_db, scope='function'),
):
    """Enable or disable a module for the organization. Admin only."""
    lang = get_current_lang()

    if not current_user.organization_id:
        raise ForbiddenException(
            message=get_error_message('module_org_required', lang),
        )

    organization = await core_api.organizations.get_async(
        db, current_user.organization_id
    )
    if not organization:
        raise NotFoundException('organization', lang)

    module_instance = module_registry.get(module_toggle.module_name)
    allowed_list = organization.allowed_modules or []

    always_on = _effective_always_on() + _ALWAYS_ON_FRONTEND_ONLY
    if (
        module_instance is None
        and module_toggle.module_name not in always_on
        and module_toggle.module_name not in VIRTUAL_TOGGLEABLE_MODULES
    ):
        raise NotFoundException('module')

    if (
        module_instance is not None
        and module_instance.metadata.is_premium
        and module_toggle.module_name not in allowed_list
    ):
        raise ForbiddenException(
            message=get_error_message('module_premium_locked', lang).format(
                module=module_toggle.module_name
            ),
        )

    # The refusal and the store card read the same rule: what the card
    # offers as Deactivate, the API accepts, and what the API refuses,
    # the card does not offer. (Before this read the same rule in both
    # places, a dropped directory named like an always-on feature wore
    # the refusal from its name alone while the card, told the module
    # was not always-on, showed a button that could only answer 403.)
    if is_always_on(module_toggle.module_name):
        raise ForbiddenException(
            message=get_error_message('module_always_on', lang).format(
                module=module_toggle.module_name
            ),
        )

    # Dependency check when enabling
    if module_toggle.enabled:
        current_enabled = _effective_always_on() + _ALWAYS_ON_FRONTEND_ONLY
        if organization.enabled_modules:
            current_enabled.extend(organization.enabled_modules)
        try:
            _check_module_dependencies(module_toggle.module_name, current_enabled)
        except _MissingDependencyError as exc:
            raise ForbiddenException(
                message=get_error_message('module_requires_other', lang).format(
                    required=_display_name(exc.module_name)
                ),
            ) from exc

    # Reverse dependency check when disabling
    if not module_toggle.enabled:
        active_modules = organization.enabled_modules or []
        for active_mod in active_modules:
            if active_mod == module_toggle.module_name:
                continue
            dep_module = module_registry.get(active_mod)
            if dep_module and module_toggle.module_name in dep_module.metadata.requires:
                raise ForbiddenException(
                    message=get_error_message('module_blocks_dependent', lang).format(
                        dependent=_display_name(active_mod),
                        module=_display_name(module_toggle.module_name),
                    ),
                )

    # The journal entry for a real switch is written by the service that
    # owns the write, so it rides the same commit.
    enabled_modules = await core_api.organizations.toggle_module_async(
        db, organization, module_toggle.module_name, module_toggle.enabled, current_user
    )

    # Once the request has committed; cleared earlier, a concurrent read
    # would re-cache the old set for the full TTL.
    from app.core._require_module import invalidate_org_module_caches

    org_id = current_user.organization_id
    after_commit(db, lambda: invalidate_org_module_caches(org_id))

    return {'success': True, 'enabled_modules': enabled_modules}


def _focus_diff(focus_module: str, plan: ProfileSwitchPlan) -> FocusModeDiff:
    return FocusModeDiff(
        focus_module=focus_module,
        enable=plan.enable,
        disable=plan.disable,
        cascade_disable=plan.cascade_disable,
        disable_all=plan.disable_all,
        unchanged=plan.unchanged,
        manual_kept=plan.manual_kept,
        final_enabled_modules=plan.final_enabled_modules,
        warnings=plan.warnings,
    )


async def _load_org_for_focus(db: Any, current_user: UserContextDTO) -> Any:
    lang = get_current_lang()
    if not current_user.organization_id:
        raise ForbiddenException(message=get_error_message('module_org_required', lang))
    # The ORM row, not the DTO — focus mode rewrites enabled_modules and the
    # focus columns on it, and a DTO cannot be persisted. The model read lives
    # in the service layer, not here.
    organization = await load_org_for_focus_async(db, current_user.organization_id)
    if not organization:
        raise NotFoundException('organization', lang)
    return organization


@router.get('/focus', response_model=FocusModeResponse)
async def get_focus_mode_endpoint(
    current_user: UserContextDTO = Depends(get_current_user_context),
    db=Depends(get_async_db, scope='function'),
):
    """The current single-module focus state, or that there is none.

    Any member may read it — the shell needs it to draw navigation, and it
    carries no more than which modules are on, which every member already sees.
    """
    organization = await _load_org_for_focus(db, current_user)
    return FocusModeResponse(
        applied=organization.focus_module is not None,
        focus_module=organization.focus_module,
        enabled_modules=list(organization.enabled_modules or []),
        diff=None,
    )


@router.post('/focus/preview', response_model=FocusModeResponse)
async def preview_focus_mode_endpoint(
    body: FocusModeRequest,
    current_user: UserContextDTO = Depends(get_current_admin_user),
    db=Depends(get_async_db, scope='function'),
):
    """Dry-run single-module focus mode: the diff without any writes. Admin only."""
    organization = await _load_org_for_focus(db, current_user)
    try:
        plan = preview_focus_mode(
            organization=organization, focus_module=body.module_name
        )
    except FocusModeError as exc:
        raise AppException(status_code=409, code=exc.code, message=str(exc)) from exc
    except ProfileSwitchError as exc:
        raise AppException(status_code=409, code=exc.code, message=str(exc)) from exc
    return FocusModeResponse(
        applied=False,
        focus_module=body.module_name,
        enabled_modules=list(organization.enabled_modules or []),
        diff=_focus_diff(body.module_name, plan),
    )


@router.post('/focus', response_model=FocusModeResponse)
async def enter_focus_mode_endpoint(
    body: FocusModeRequest,
    current_user: UserContextDTO = Depends(get_current_admin_user),
    db=Depends(get_async_db, scope='function'),
):
    """Enter single-module focus mode on the given module. Admin only."""
    organization = await _load_org_for_focus(db, current_user)
    try:
        plan = await enter_focus_mode(
            db=db,
            organization=organization,
            focus_module=body.module_name,
            user=current_user,
        )
    except FocusModeError as exc:
        raise AppException(status_code=409, code=exc.code, message=str(exc)) from exc
    except ProfileSwitchError as exc:
        raise AppException(status_code=409, code=exc.code, message=str(exc)) from exc
    except FocusModeApplyError:
        logger.exception('Entering focus mode failed')
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
            'name': body.module_name,
            'before': {'focus_module': None},
            'after': {'focus_module': body.module_name},
        },
    )

    return FocusModeResponse(
        applied=True,
        focus_module=body.module_name,
        enabled_modules=list(plan.final_enabled_modules),
        diff=_focus_diff(body.module_name, plan),
    )


@router.delete('/focus', response_model=FocusModeResponse)
async def exit_focus_mode_endpoint(
    current_user: UserContextDTO = Depends(get_current_admin_user),
    db=Depends(get_async_db, scope='function'),
):
    """Leave single-module focus mode, restoring the state before it. Admin only."""
    organization = await _load_org_for_focus(db, current_user)
    previous_focus = organization.focus_module
    try:
        restored = await exit_focus_mode(
            db=db, organization=organization, user=current_user
        )
    except FocusModeError as exc:
        raise AppException(status_code=409, code=exc.code, message=str(exc)) from exc
    except FocusModeApplyError:
        logger.exception('Leaving focus mode failed')
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
            'name': previous_focus,
            'before': {'focus_module': previous_focus},
            'after': {'focus_module': None},
        },
    )

    return FocusModeResponse(
        applied=True, focus_module=None, enabled_modules=restored, diff=None
    )


@router.get('/{module_name}/settings', response_model=ModuleSettingsResponse)
async def get_module_settings(
    module_name: str,
    current_user: UserContextDTO = Depends(get_current_admin_user),
    db=Depends(get_async_db, scope='function'),
):
    """Get module settings and its schema for the current organization. Admin only."""

    require_org(current_user)

    module_instance = module_registry.get(module_name)
    if not module_instance:
        # A name this installation knows without a BaseModule behind it — an
        # always-on feature (items, locations, categories), a frontend-only
        # shell name, the virtual partners card — has no settings to read,
        # but it is not unknown. The 404 this branch used to produce is what
        # let the settings screen tell an admin the products module "does
        # not exist" while it sat enabled in their own organization.
        if module_name in (
            set(_effective_always_on())
            | set(_ALWAYS_ON_FRONTEND_ONLY)
            | set(VIRTUAL_TOGGLEABLE_MODULES)
        ):
            return {'settings': {}, 'settings_schema': None}
        raise NotFoundException('module')

    org_id = require_org(current_user)
    settings = (await core_api.settings.get_async(db, org_id, module_name)) or {}
    schema = module_instance.get_settings_schema()

    return {'settings': settings, 'settings_schema': schema}


@router.put('/{module_name}/settings', response_model=ModuleSettingsUpdateResponse)
async def update_module_settings(
    module_name: str,
    body: dict = Body(...),
    current_user: UserContextDTO = Depends(get_current_admin_user),
    db=Depends(get_async_db, scope='function'),
):
    """Update module settings for the current organization. Admin only.

    Partial update: the body merges over the saved settings at the top
    level — a key absent from the body keeps its saved value, and only a
    key that was never written takes the schema default. Sending the whole
    object still works unchanged.
    """
    org_id = require_org(current_user)

    if not module_registry.get(module_name):
        raise NotFoundException('module')

    change = await ModuleService.update_module_settings_async(
        db, org_id, module_name, body
    )
    if change is not None:
        # A module's settings decide what the module may do — up to whether
        # an approval step can be closed by its own author — and the write
        # used to leave no trace. Same shape as the module toggle: the
        # module's name is the identity worth keeping, the organization id
        # fills the target column, and the snapshot names the keys that
        # moved with secret leaves masked.
        await core_api.audit_log.log_action_async(
            db,
            organization_id=org_id,
            user_id=current_user.id,
            action=AuditAction.UPDATE,
            target_type=AuditTargetType.MODULE,
            target_id=org_id,
            snapshot={'name': module_name, **change},
        )
    return {'status': 'ok'}
