import asyncio
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, cast
from uuid import UUID

import typer
from redis.exceptions import RedisError
from rich.console import Console
from rich.markup import escape
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError

if TYPE_CHECKING:
    from app.core.token_blacklist import TokenBlacklist

user_app = typer.Typer(no_args_is_help=True)
console = Console()

# Known-weak bootstrap passwords — the Makefile's DEV_ADMIN_PASSWORD default
# ('Admin123') heads the list. Harmless on a throwaway dev stack, a standing
# credential on anything else, so a production-shaped environment refuses them.
# Exact-match membership, same as the SECRET_KEY blocklist in app.config.
_WEAK_ADMIN_PASSWORDS = frozenset(
    {'Admin123', 'admin', 'password', 'Password123', 'admin123', 'changeme'}
)


def _refuse_known_weak_password(password: str, allow_weak: bool) -> None:
    """Refuse the seed passwords on a production-shaped install.

    Runs ahead of the complexity policy: on a deployed install the operator
    should hear "this is the known-weak seed password", not "add an uppercase
    letter". The dev signal is the one the SECRET_KEY gate uses (app.config)
    — DEBUG or TESTING on means the stack is not serving people. Tests patch
    the attributes, so read them here and not os.environ, which conftest pins.
    """
    from app.config import settings

    if (settings.DEBUG or settings.TESTING) or allow_weak:
        return
    if password not in _WEAK_ADMIN_PASSWORDS:
        return
    console.print(
        '[red]✘ Password refused: it is on the known-weak bootstrap list '
        '(the development seed default heads it), and this environment is '
        'production-shaped — DEBUG and TESTING are both off.[/]'
    )
    console.print(
        '[yellow]Choose a strong password, or re-run with '
        '--allow-weak-password if this really is a throwaway stack.[/]'
    )
    sys.exit(1)


def _refuse_unusable_input(password: str, lang: str | None, allow_weak: bool) -> None:
    """Exit 1 with a readable message when the password or language cannot be used."""
    from app.i18n import SUPPORTED_LANGUAGES
    from app.schemas.user import validate_password_policy

    _refuse_known_weak_password(password, allow_weak)

    if lang is not None and lang not in SUPPORTED_LANGUAGES:
        console.print(
            f'[red]✘ Unknown language {lang!r}. '
            f'Choose one of: {", ".join(SUPPORTED_LANGUAGES)}[/]'
        )
        sys.exit(1)

    # The CLI hashed whatever it was given, so it could create an account with
    # a password the API itself would refuse — and `make dev-up` then printed
    # that password as the login. Same policy in both places.
    try:
        validate_password_policy(password)
    except ValueError as exc:
        console.print(f'[red]✘ Password rejected: {exc}[/]')
        sys.exit(1)


@asynccontextmanager
async def _own_token_blacklist() -> AsyncIterator['TokenBlacklist']:
    """A token blacklist on a Redis connection this command opens and closes.

    The HTTP paths get theirs for free — the app lifespan hands the blacklist
    a Redis connection at startup. The CLI has no lifespan, so it opens its
    own connection, mirroring the instance choice made there: the dedicated
    noeviction instance when one is configured, otherwise the main one.
    Getting that wrong would write the marker where nobody reads it, which
    looks exactly like success. The ping comes first, so an unreachable Redis
    is reported before the command has changed anything.

    Its own :class:`TokenBlacklist` rather than the module singleton: the key
    layout is class-level, so what it writes lands in the same place, and the
    connection closed here cannot be left behind on an object the rest of the
    process shares.
    """
    import redis.asyncio as aioredis

    from app.config import settings
    from app.core.token_blacklist import TokenBlacklist

    url = settings.REDIS_CRITICAL_URL or settings.REDIS_URL
    client = aioredis.from_url(url, decode_responses=True)
    try:
        await client.ping()
        blacklist = TokenBlacklist()
        blacklist.set_redis(client)
        yield blacklist
    finally:
        await client.aclose()


async def _mark_credentials_changed(user_id: str) -> None:
    """Invalidate every session issued before this password reset."""
    async with _own_token_blacklist() as blacklist:
        await blacklist.mark_credentials_changed(user_id)


class _ErasureStoppedError(Exception):
    """The erasure stopped before its commit; the message says why."""


async def _erase_account(user_id: UUID, *, ask: bool) -> bool:
    """Erase the account in one transaction; False when the operator declines.

    The async engine is built inside the API's lifespan, which a CLI never
    enters, so it is bound to this loop here. The token revocation goes
    through a blacklist of the command's own, connected before anything is
    read — production refuses to drop a revocation, and the shared blacklist
    of a process with no lifespan has no Redis to write it to.
    """
    from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

    from app import database
    from app.models.user import User
    from app.services.gdpr_service import anonymize_user_async

    async with _own_token_blacklist() as blacklist:
        database.init_async_engine()
        engine = cast('AsyncEngine', database.async_engine)
        factory = cast('async_sessionmaker[AsyncSession]', database.AsyncSessionLocal)
        try:
            async with factory() as db:
                user = await db.get(User, user_id)
                if user is None:
                    raise _ErasureStoppedError(f'no account has the id {user_id}.')
                whose = user.email + (f' ({user.full_name})' if user.full_name else '')
                if ask and not typer.confirm(
                    f'Erase the account of {whose}? This cannot be undone.'
                ):
                    return False
                # Leaving the block without a commit rolls the session back,
                # so a revocation that fails takes the rewrite with it.
                await anonymize_user_async(db, user_id, blacklist=blacklist)
                await db.commit()
                return True
        finally:
            await engine.dispose()


@user_app.command('erase')
def erase(
    user_id: UUID = typer.Argument(..., help='Id of the account (users.id)'),
    yes: bool = typer.Option(
        False, '--yes', '-y', help='Erase without asking for confirmation'
    ),
):
    """Erase one person's account on a GDPR erasure request. Irreversible.

    Replaces the account's email address, name and password, closes it and
    revokes its sessions, in one transaction: when a step fails, nothing is
    erased. The records erasure does not reach are listed in
    docs/GDPR_MANUAL_PROCEDURE.md.
    """
    from app.cli import bootstrap_db

    # Every module's models, so the mappers the account touches resolve.
    bootstrap_db()
    try:
        erased = asyncio.run(_erase_account(user_id, ask=not yes))
    except typer.Abort as exc:
        # No terminal behind the question (`exec -T`), or Ctrl+C at it.
        console.print(
            'Nothing was erased: the question went unanswered. Pass --yes to '
            'erase without it.'
        )
        raise typer.Exit(code=1) from exc
    except (
        _ErasureStoppedError,
        RedisError,
        SQLAlchemyError,
        OSError,
        RuntimeError,
    ) as exc:
        console.print(f'[red]✘ Nothing was erased: {escape(str(exc))}[/]')
        raise typer.Exit(code=1) from exc
    if not erased:
        console.print('Nothing was erased.')
        raise typer.Exit(code=1)
    console.print(
        f'[green]✔ Erased account {user_id}: its email address, name and '
        f'password are replaced, it is closed and its sessions are revoked.[/]'
    )
    console.print(
        'Records outside the account can still name the person: see "Records '
        'that keep the address" in docs/GDPR_MANUAL_PROCEDURE.md.'
    )


@user_app.command('create-admin')
def create_admin(
    email: str = typer.Option(..., help='Admin email address'),
    password: str = typer.Option(..., help='Admin password'),
    name: str = typer.Option('Administrator', help='Full name'),
    lang: str | None = typer.Option(
        None,
        '--lang',
        help=(
            'Interface language of the account (en, pl, de, fr, es, pt); '
            'omitted: the instance default for a new account, unchanged for an existing one'
        ),
    ),
    allow_weak_password: bool = typer.Option(
        False,
        '--allow-weak-password',
        help='Override the production refusal of known-weak bootstrap passwords',
    ),
    instance_superuser: bool = typer.Option(
        True,
        '--instance-superuser/--no-instance-superuser',
        help='Make the first account on the instance its superuser (default)',
    ),
):
    """Create an admin user or reset existing admin password."""
    provision_admin(
        email=email,
        password=password,
        name=name,
        lang=lang,
        allow_weak_password=allow_weak_password,
        instance_superuser=instance_superuser,
    )


def provision_admin(
    email: str,
    password: str,
    name: str = 'Administrator',
    lang: str | None = None,
    allow_weak_password: bool = False,
    instance_superuser: bool = True,
) -> None:
    """Create an admin user or reset an existing admin's password.

    The body of ``create-admin`` with plain Python defaults. A typer command
    called as a function receives ``typer.Option`` objects for the parameters
    it was not given, so code that creates an admin calls this instead.
    """
    import app.modules.stock_takes.models  # resolve StockTakeItem/StockTake mapper
    import app.modules.warehouse.models  # noqa: F401 - resolve Document mapper
    from app.database import SessionLocal
    from app.models.organization import Organization
    from app.models.user import User
    from app.services.auth_service import get_password_hash

    _refuse_unusable_input(password, lang, allow_weak_password)

    db = SessionLocal()
    try:
        user = db.scalars(select(User).where(User.email == email)).first()
        if user:
            console.print(
                f'User {email} already exists. Updating password and granting admin role...'
            )
            user.hashed_password = get_password_hash(password)
            user.role = 'admin'
            user.is_active = True
            if lang is not None:
                user.preferred_language = lang
            db.commit()
            user_id = str(user.id)
            console.print('[green]✔ Updated successfully.[/]')
            # A reset from the CLI is an incident-response move as much as
            # the HTTP one; leaving the old sessions alive would defeat it.
            try:
                asyncio.run(_mark_credentials_changed(user_id))
            except Exception as exc:  # noqa: BLE001 — reported, not swallowed
                console.print(
                    f'[red]✘ Password changed, but existing sessions could NOT be '
                    f'invalidated: {exc}[/]\n'
                    f'[yellow]Tokens issued before this reset stay valid until they '
                    f'expire. Fix the Redis connection and run this command again.[/]'
                )
                sys.exit(1)
            console.print('[green]✔ Earlier sessions invalidated.[/]')
            return

        # The first account on the instance is its superuser, by the rule the
        # sign-up applies to the first person who registers. The requests for
        # access are decided by a superuser, and an instance set up from the
        # command line had none until the backend's next start promoted one.
        first_account = (
            instance_superuser and db.scalar(select(func.count(User.id))) == 0
        )
        user = User(
            email=email,
            hashed_password=get_password_hash(password),
            full_name=name,
            role='admin',
            is_superuser=first_account,
            is_active=True,
        )
        if lang is not None:
            user.preferred_language = lang
        db.add(user)
        db.flush()

        organization = Organization(name='My Organization', created_by=user.id)
        db.add(organization)
        db.flush()

        # Storage types belong to a tenant; without SYSTEM the
        # organization cannot book consumption, loss or production.
        from app.seed_profiles.base import seed_neutral_storage_types

        seed_neutral_storage_types(db, organization_id=organization.id, commit=False)

        user.organization_id = organization.id
        db.commit()
        console.print(f'[green]✔ Successfully created admin user: {email}[/]')

    except Exception as e:  # noqa: BLE001 — CLI tool must handle unexpected errors gracefully with user feedback
        db.rollback()
        console.print(f'[red]Error: {e}[/]')
        sys.exit(1)
    finally:
        db.close()
