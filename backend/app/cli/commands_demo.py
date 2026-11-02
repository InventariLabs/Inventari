"""The demo instance and the one command that rebuilds it.

A public demo is a database strangers write to. Left alone it fills with
whatever they tried — half-finished documents, test partners, an item called
"asdf" — and within a week it stops showing the product and starts showing its
own wear. The answer is not moderation but a short life: the instance is
rebuilt from the seed on a schedule, and nothing in it is expected to survive.

``demo reset`` is that rebuild, and it is deliberately the destructive command
with the loudest guard in this CLI. ``db reset`` refuses in production and asks
the operator to type the database name; this one refuses in production *and*
refuses anywhere that has not declared itself a demo, because it is meant to be
run by a timer with nobody watching, and a timer cannot be asked to confirm.
"""

from __future__ import annotations

import asyncio
import os
import shutil
from datetime import UTC, datetime
from pathlib import Path

import httpx
import typer

from app.cli import (
    DISPOSABLE_ENVIRONMENTS,
    NotDisposableError,
    bootstrap_db,
    check_disposable_install,
    console,
)
from app.cli._migration_lock import hold_migration_lock
from app.cli._reset_sweep import (
    TERMINATE_OTHER_SESSIONS_PARAMS,
    TERMINATE_OTHER_SESSIONS_SQL,
)

demo_app = typer.Typer(no_args_is_help=True)

#: The environment variable an instance sets to say what it is. Nothing infers
#: it: a database named ``inventari_demo`` on somebody's laptop is still their
#: laptop, and guessing from the name is how a reset finds the wrong machine.
DEMO_MARKER_ENV = 'INVENTARI_DEMO'

#: Where the demo stack's Mailpit answers its HTTP API. Set by
#: ``docker-compose.demo.yml`` on the reset service; unset everywhere else,
#: because a development machine has no inbox beside the database.
DEMO_INBOX_API_URL_ENV = 'DEMO_INBOX_API_URL'

#: How long the mail catcher beside the demo may take before the reset stops
#: waiting. Deliberately short: the rebuild must not be held hostage by it.
DEMO_INBOX_TIMEOUT_SECONDS = 10

#: Written to the organization after every rebuild, so the instance can say how
#: old it is without anyone reading the container logs.
LAST_RESET_KEY = 'demo_last_reset_at'

#: The seed fills a warehouse — food and equipment, documents and orders — so
#: this is the profile whose modules match what the visitor will find.
DEMO_PROFILE_ID = 'equipment_wms'

#: The warehouse profile leaves the kitchen half switched off, which on a demo
#: means Production and Recipes greet the visitor with "Module Not Enabled"
#: over rows the seed had already written. The demo shows everything it seeds,
#: so the profile's list is widened by the four the seeder also fills.
DEMO_EXTRA_MODULES = ['maker', 'recipes', 'shopping_lists', 'nutrition']

#: Modules that seed no rows but that the demo switches on because the server
#: can serve them: module name -> the AI purpose it depends on. The photo tab
#: in Quick Add belongs to ``vision``, and the demo's own model (``.env``)
#: serves it, so a visitor should not have to find Settings > Modules first.
#: A module is enabled only when ``env_fallback_serves`` says that purpose has a
#: model behind it — a demo run without a vision-capable key would otherwise
#: show a tab whose button is disabled.
DEMO_AI_MODULES = {'vision': 'vision.extract'}


#: What the demo-reset service sets ``INVENTARI_ENV`` to. It runs on the
#: production compose with ``DEBUG`` off, so it needs a name of its own; only
#: this command accepts it, ``db reset`` and the ``qa`` fixtures do not.
DEMO_ENVIRONMENT = 'demo'


class DemoGuardError(RuntimeError):
    """The instance did not identify itself as a demo."""


def guard_demo_instance() -> None:
    """Refuse unless this instance has declared itself a demo and its data disposable.

    Separate from the command so the test suite can call the decision rather
    than the side effect — a guard whose only caller is the thing it guards can
    only be tested by letting it through.
    """
    try:
        check_disposable_install(
            'drops the schema and every uploaded file',
            allowed=(*DISPOSABLE_ENVIRONMENTS, DEMO_ENVIRONMENT),
        )
    except NotDisposableError as exc:
        raise DemoGuardError(str(exc)) from exc

    marker = os.getenv(DEMO_MARKER_ENV, '').strip().lower()
    if marker not in ('1', 'true', 'yes'):
        raise DemoGuardError(
            f'demo reset refuses to run: {DEMO_MARKER_ENV} is not set. This '
            f'command drops every row in the database, so it runs only where '
            f'somebody has said in the environment that losing them is the '
            f'point. Set {DEMO_MARKER_ENV}=true on the demo instance, and '
            f'nowhere else.'
        )


def _seed_everything(items: int, admin_email: str, admin_password: str) -> dict:
    """Migrations, system data, the admin account and the demo rows."""
    import seed_demo_data
    from app.seed_data import seed_all

    bootstrap_db()

    console.print('  Applying migrations...')
    from alembic import command
    from alembic.config import Config

    from app.cli.commands_db import _upgrade_all_modules

    command.upgrade(Config('alembic.ini'), 'head')
    _upgrade_all_modules()

    console.print('  Seeding installation-wide data...')
    seed_all(profile='clean_core', organization_id=None)

    console.print(f'  Creating {admin_email}...')
    from app.cli.commands_user import create_admin

    # Everyone signs in to a public demo with this one account, so it is an
    # organization admin only: the instance-wide powers of a superuser (block
    # accounts, announce to all users, decide registrations) stay out of reach.
    create_admin(
        email=admin_email,
        password=admin_password,
        name='Demo Administrator',
        instance_superuser=False,
    )

    console.print('  Completing onboarding...')
    asyncio.run(_complete_onboarding(admin_email))

    console.print('  Seeding demo rows...')
    report = seed_demo_data.seed_from_cli(
        items=items, admin_email=admin_email, report=console.print
    )

    # The shared seed is the one every stack runs and ``--clean`` takes apart
    # again by its markers; what only a public instance needs — no marker on
    # screen, no module on its empty state — is a step of its own.
    console.print('  Dressing the demo for visitors...')
    import seed_demo_showcase

    showcase = seed_demo_showcase.dress_from_cli(
        admin_email=admin_email, report=console.print
    )
    return {**report, **showcase}


async def _complete_onboarding(admin_email: str) -> None:
    """Answer the setup wizard, because a visitor must not be asked to.

    A reset that stops before this reports success and leaves an instance that
    opens on "Choose your workflow". Two things are wrong with that on a public
    demo: the visitor is asked a question about somebody else's organization,
    and the first one to answer it changes what everybody after them sees until
    the next rebuild. The seeded rows are food, equipment, documents and
    purchase orders, so the profile that matches them is the warehouse one.
    """
    from app import database

    # The async engine is built inside the API's lifespan, which a CLI never
    # enters — bind it to this loop before asking for a session. The factory
    # starts life as None, so read it into a name the type checker can narrow
    # rather than calling the module attribute.
    database.init_async_engine()
    session_factory = database.AsyncSessionLocal
    if session_factory is None:
        raise RuntimeError('async session factory was not initialised')

    async with session_factory() as db:
        await apply_demo_onboarding(db, admin_email)


async def apply_demo_onboarding(db, admin_email: str) -> None:
    """The onboarding itself, against a session somebody else owns.

    Split from the caller above so it can be tested. The wrapper builds its own
    engine from ``settings.DATABASE_URL``, and inside the test suite that names
    a database which does not exist — the workers each run against their own.
    Code that opens its own connection is code the suite cannot reach, which is
    how the other function in this repo doing the same thing came to be red on
    ``dev`` with nobody able to run it.
    """
    from sqlalchemy import select

    from app.core.contracts import UserContextDTO
    from app.models.organization import Organization
    from app.models.user import User
    from app.services.onboarding_service import apply_onboarding_profile_async

    user = (await db.scalars(select(User).where(User.email == admin_email))).first()
    if user is None or not user.organization_id:
        return
    org = await db.get(Organization, user.organization_id)
    if org is None:
        return

    already = await db.scalar(
        select(Organization.active_profile_id).where(Organization.id == org.id)
    )
    if already == DEMO_PROFILE_ID:
        return

    context = UserContextDTO(
        id=user.id,
        email=user.email,
        role=user.role,
        organization_id=org.id,
        is_superuser=False,
    )
    await apply_onboarding_profile_async(db, org, DEMO_PROFILE_ID, user=context)
    await _enable_extra_modules(db, org, context)
    await db.commit()
    # The CLI never ran the app lifespan, so only a standalone delete reaches
    # the cache the running app reads from.
    from app.core._require_module import invalidate_org_module_caches

    await invalidate_org_module_caches(org.id, standalone=True)


async def _enable_extra_modules(db, org, user) -> None:
    """Switch on the modules the warehouse profile does not offer.

    The wizard refuses a selection outside the profile's own list, and rightly
    so — it is answering "what kind of place is this?" rather than "what is
    installed?". A demo is the case where the honest answer is *all of it*: the
    seeder writes production runs and recipes whatever the profile says, and a
    module left off shows "Module Not Enabled" over rows that already exist.
    So the extras are enabled afterwards, through the same lifecycle executor
    onboarding itself uses.

    The AI modules (``DEMO_AI_MODULES``) join them only when the server's own
    model serves what they need.
    """
    from app.core.llm import registry
    from app.core.module_registry import module_registry
    from app.services.module_lifecycle_service import enable_modules_async

    enabled = set(org.enabled_modules or [])
    served = [
        name
        for name, purpose in DEMO_AI_MODULES.items()
        if registry.env_fallback_serves(purpose)
    ]
    wanted = [name for name in [*DEMO_EXTRA_MODULES, *served] if name not in enabled]
    modules = [m for m in (module_registry.get(name) for name in wanted) if m]
    if not modules:
        return

    await enable_modules_async(modules, org.id, db=db, user=user, run_custom_hook=False)
    org.enabled_modules = list(enabled | {m.metadata.name for m in modules})


def empty_demo_inbox(api_url: str) -> None:
    """Delete every message the demo's Mailpit holds.

    The demo sends no real email: every message a visitor triggers — a purchase
    order, an invitation — is caught by Mailpit and shown in a public inbox.
    Emptying it belongs to the rebuild, because an address a stranger typed
    yesterday must not still be on display today. Mailpit's API deletes all of
    them on ``DELETE /api/v1/messages``.
    """
    response = httpx.delete(
        f'{api_url.rstrip("/")}/api/v1/messages',
        timeout=DEMO_INBOX_TIMEOUT_SECONDS,
    )
    response.raise_for_status()


def _clear_the_demo_inbox() -> None:
    """Empty the public inbox, and never let it stop the rebuild.

    Mailpit is one small container beside the instance; it can be restarting,
    renamed or simply not there, and a reset that aborts before the drop
    because the inbox refused leaves yesterday's data in place — the failure
    becomes the visitor's, which is the worse trade. So any failure here is a
    warning and the rebuild continues; the next run tries again.
    """
    api_url = os.getenv(DEMO_INBOX_API_URL_ENV, '').strip()
    if not api_url:
        return
    try:
        empty_demo_inbox(api_url)
        console.print('  Emptied the demo inbox...')
    except Exception as exc:  # noqa: BLE001 — the demo inbox is a side service; the rebuild goes on
        console.print(
            f'[yellow]![/] Could not empty the demo inbox ({exc}); '
            f'the database rebuild continues.'
        )


def _drop_schema() -> None:
    from sqlalchemy import create_engine, text

    database_url = os.getenv('DATABASE_URL')
    if not database_url:
        raise DemoGuardError('DATABASE_URL is not set.')

    engine = create_engine(database_url)
    with engine.connect() as conn:
        conn.execute(
            text(TERMINATE_OTHER_SESSIONS_SQL), TERMINATE_OTHER_SESSIONS_PARAMS
        )
        conn.execute(text('DROP SCHEMA public CASCADE'))
        conn.execute(text('CREATE SCHEMA public'))
        conn.execute(text('GRANT ALL ON SCHEMA public TO public'))
        conn.commit()


def empty_uploads_directory(root: Path) -> int:
    """Delete everything under ``root`` and keep ``root`` itself; return how many entries went.

    The directory stays because on the demo stack it is a mounted volume, and a
    mount point cannot be removed from inside the container. Symbolic links are
    unlinked, never followed: a link a visitor somehow planted must not carry
    the deletion out of the uploads directory.

    Refuses a root that is not an absolute directory, that leads to the
    filesystem root, or that holds this very module: the path comes from a
    setting, and an empty or mistyped one — ``/`` or ``/app``, which on a dev
    stack is the host's source tree — must stop here rather than reach
    ``rmtree``. The spelling does not matter — ``/var/..`` and a link to ``/``
    are the root as much as ``/`` is — so the path is resolved before it is
    compared.
    """
    if (
        not root.is_absolute()
        or (resolved := root.resolve()) == Path(resolved.anchor)
        or Path(__file__).resolve().is_relative_to(resolved)
    ):
        raise DemoGuardError(
            f'refusing to empty {str(root)!r}: not an uploads directory.'
        )
    if not root.is_dir():
        return 0
    removed = 0
    for entry in root.iterdir():
        if entry.is_dir() and not entry.is_symlink():
            shutil.rmtree(entry)
        else:
            entry.unlink()
        removed += 1
    return removed


async def empty_object_storage() -> int:
    """Delete every object object storage holds; how many went.

    The same reason as the directory's half: the rows that pointed at the
    objects went with the schema, so from here on they are objects nothing
    can reach, adding up every day. Opened through the storage service from
    the application's own configuration rather than a copy of the settings —
    the way the showcase step opens it — and, like the directory, after the
    drop and before the seed, which writes objects of its own that must
    survive.
    """
    from app.core.file_storage.service import FileStorageService

    service = FileStorageService.initialize_from_settings()
    return await service.empty()


def _clear_the_uploads() -> None:
    """Remove the files visitors uploaded, and never let it stop the rebuild.

    The rows that pointed at them went with the schema, so from here on they
    are files nothing can reach, adding up every day. Run before the seed,
    which writes files of its own that must survive. Whichever backend holds
    them goes: the local directory, or — with object storage — every object
    in the configured bucket. A failure is a warning for the reason the
    inbox's is: the rebuild is the part the demo cannot run without, and the
    next reset tries again.
    """
    from app.config import settings

    try:
        if settings.FILE_STORAGE_BACKEND == 'local':
            removed = empty_uploads_directory(Path(settings.FILE_STORAGE_LOCAL_PATH))
        else:
            removed = asyncio.run(empty_object_storage())
        console.print(f'  Emptied the uploaded files ({removed} entries)...')
    except Exception as exc:  # noqa: BLE001 — a storage failure is reported; the rebuild goes on
        console.print(
            f'[yellow]![/] Could not empty the uploaded files ({exc}); '
            f'the database rebuild continues.'
        )


def _record_reset_time() -> None:
    """Leave the rebuild time where a reader of the instance can find it."""
    from sqlalchemy.orm.attributes import flag_modified

    from app.database import SessionLocal
    from app.models.organization import Organization

    with SessionLocal() as db:
        org = db.query(Organization).first()
        if org is None:
            return
        settings = dict(org.settings or {})
        settings[LAST_RESET_KEY] = datetime.now(UTC).isoformat()
        org.settings = settings
        flag_modified(org, 'settings')
        db.commit()


async def cap_demo_ai_requests_async(db, monthly: int) -> None:
    """Write the demo's monthly AI ceiling into the instance-wide default limits.

    The demo answers AI from one key in the server's environment, which no
    organization can see or bound, and ``ai_requests_monthly`` defaults to no
    limit. The default limits are what every organization without limits of
    its own answers to — the operator's and each visitor's — and a visitor
    cannot write them. Set by every rebuild, because the rebuild drops the
    schema a limit set by hand would live in.
    """
    from app.services.system_settings_service import (
        get_default_org_limits_async,
        set_setting_async,
    )

    limits = dict(await get_default_org_limits_async(db))
    limits['ai_requests_monthly'] = monthly
    await set_setting_async(db, 'default_org_limits', limits)


def _cap_the_ai_requests() -> int:
    from app.config import settings

    monthly = settings.DEMO_AI_REQUESTS_MONTHLY
    asyncio.run(_on_async_db(lambda db: cap_demo_ai_requests_async(db, monthly)))
    return monthly


@demo_app.command()
def reset(
    items: int = typer.Option(500, '--items', help='How many food rows to seed.'),
    admin_email: str = typer.Option(
        'admin@example.com',
        '--email',
        help="The operator's own account; visitors get sandboxes instead.",
    ),
    admin_password: str = typer.Option(
        'DemoPass123', '--password', help='Its password, kept by the operator.'
    ),
):
    """Rebuild the demo instance from scratch. DESTRUCTIVE, and meant to be.

    Drops the schema, empties the uploaded files, re-applies every migration,
    seeds the system data, the administrator and the demo rows. Safe to run on a fresh database and on one
    that is already seeded — both end at the same place, which is what lets a
    timer call it without knowing which it found.

    Runs under the migration advisory lock (``app.cli._migration_lock``): a
    backend starting beside the rebuild — the demo's first rebuild happens at
    the same moment as the stack's first start — waits for it instead of
    migrating into a schema that is being dropped, and the sweep that empties
    the database spares the session holding it.
    """
    try:
        guard_demo_instance()
    except DemoGuardError as exc:
        console.print(f'[bold red]ERROR:[/] {exc}')
        raise typer.Exit(code=1) from exc

    started = datetime.now(UTC)
    console.print('[yellow]↺[/] Rebuilding the demo instance...')
    _clear_the_demo_inbox()
    with hold_migration_lock():
        _drop_schema()
        _clear_the_uploads()
        report = _seed_everything(items, admin_email, admin_password)
        report['ai_requests_monthly'] = _cap_the_ai_requests()
        _record_reset_time()

    seconds = (datetime.now(UTC) - started).total_seconds()
    console.print(f'[green]✔[/] Demo rebuilt in {seconds:.0f}s:')
    for key, value in sorted(report.items()):
        console.print(f'    {key}: {value}')
    console.print(f'\nSign in as [bold]{admin_email}[/] / [bold]{admin_password}[/]')


#: The visitors' sandbox administrators. ``example.com`` is the domain kept for
#: documentation, so no message to one of them can reach a real inbox.
SANDBOX_EMAIL_DOMAIN = 'sandbox.example.com'


def open_sandbox_account(db) -> tuple:
    """A new organization and its administrator, for one visitor of the demo.

    The account is an organization admin, never a superuser, and it is created
    inactive: it waits in the pool with a password nobody knows, and handing it
    to a visitor is what activates it (``demo_sandbox_service``). Takes the
    caller's session so the test suite can open one on its own database.
    Returns ``(organization_id, user_id, email)``.
    """
    import secrets

    from app.models.organization import Organization
    from app.models.user import User
    from app.seed_profiles.base import seed_neutral_storage_types
    from app.services.auth_service import get_password_hash

    email = f'visitor-{secrets.token_hex(6)}@{SANDBOX_EMAIL_DOMAIN}'
    user = User(
        email=email,
        hashed_password=get_password_hash(secrets.token_urlsafe(32)),
        full_name='Demo Visitor',
        role='admin',
        is_superuser=False,
        is_active=False,
    )
    db.add(user)
    db.flush()
    organization = Organization(name='My Organization', created_by=user.id)
    db.add(organization)
    db.flush()
    seed_neutral_storage_types(db, organization_id=organization.id, commit=False)
    user.organization_id = organization.id
    db.commit()
    return organization.id, user.id, email


def sandboxes_to_seed(state, *, target: int, cap: int) -> int:
    """How many sandboxes to seed now: up to ``target`` waiting, none past the cap.

    A sandbox seeded beyond what the cap still lets visitors claim before the
    reset would never be handed out.
    """
    claimable = cap - state.claimed
    return max(0, min(target, claimable) - state.ready)


async def _on_async_db(work):
    """Run ``work(db)`` and commit, on the async engine a CLI process lacks."""
    from app import database

    database.init_async_engine()
    session_factory = database.AsyncSessionLocal
    if session_factory is None:
        raise RuntimeError('async session factory was not initialised')
    async with session_factory() as db:
        result = await work(db)
        await db.commit()
        return result


def _seed_one_sandbox(items: int) -> None:
    """Open, onboard, seed and dress one sandbox, then offer it to the pool."""
    import seed_demo_data
    import seed_demo_showcase
    from app.database import SessionLocal
    from app.services.demo_sandbox_service import add_to_pool_async

    def quiet(_message: str) -> None:
        return None

    with SessionLocal() as db:
        organization_id, user_id, email = open_sandbox_account(db)
    asyncio.run(_complete_onboarding(email))
    seed_demo_data.seed_from_cli(items=items, admin_email=email, report=quiet)
    seed_demo_showcase.dress_from_cli(admin_email=email, report=quiet)
    asyncio.run(
        _on_async_db(lambda db: add_to_pool_async(db, organization_id, user_id))
    )


@demo_app.command('fill-pool')
def fill_pool(
    items: int = typer.Option(
        500, '--items', help='How many food rows each sandbox is seeded with.'
    ),
    size: int | None = typer.Option(
        None,
        '--size',
        help='How many sandboxes to keep ready (default: DEMO_SANDBOX_POOL_SIZE).',
    ),
):
    """Seed visitors' sandboxes until the pool holds enough. Run by the demo-reset loop.

    One sandbox takes several seconds to seed, too long for a visitor to wait
    on a click, so they are seeded here in advance. Seeds none past the daily
    cap: a sandbox nobody may claim before the reset is wasted work.
    """
    try:
        guard_demo_instance()
    except DemoGuardError as exc:
        console.print(f'[bold red]ERROR:[/] {exc}')
        raise typer.Exit(code=1) from exc

    from app.config import settings
    from app.services.demo_sandbox_service import pool_state_async

    bootstrap_db()
    target = settings.DEMO_SANDBOX_POOL_SIZE if size is None else size
    state = asyncio.run(_on_async_db(pool_state_async))
    missing = sandboxes_to_seed(
        state, target=target, cap=settings.DEMO_SANDBOX_DAILY_CAP
    )
    for number in range(1, missing + 1):
        started = datetime.now(UTC)
        _seed_one_sandbox(items)
        seconds = (datetime.now(UTC) - started).total_seconds()
        console.print(
            f'  Sandbox {number}/{missing} seeded in {seconds:.1f}s '
            f'({state.ready + number} ready)'
        )
