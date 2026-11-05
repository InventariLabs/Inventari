"""Fixtures a screen-by-screen pass needs before it can reach half its states.

An empty list, a list with one row and a list long enough to paginate are three
different screens, and one database cannot hold all three at once — so the
fixture is three organizations, not three seed levels in one. Without them a
pass quietly shrinks to the happy path, which is the part that has already been
clicked.

Every account here has a known password, so the command refuses to run anywhere
that is not development or staging.

    python manage.py qa fixture              all three, equipment_wms profile
    python manage.py qa fixture --variant many --items 300
    python manage.py qa fixture --profile food_home

    python manage.py qa fixture --variant many --reset --yes

Running it twice leaves the same state: organizations are looked up by their
admin's address, and volume is topped up to the target rather than added to.

Topping up is not the same as starting over, and a pass that leaves state the
application refuses to remove — a completed stock take, an archived location,
a row a bad import made unreadable — has no way back through the product. That
is what ``--reset`` is for: it deletes the organization and its accounts first,
so ``fresh`` in a corpus header stays true.
"""

from __future__ import annotations

import asyncio
import sys
from typing import Any, cast

import typer
from rich.console import Console

from app.cli import guard_disposable_install

qa_app = typer.Typer(no_args_is_help=True)
console = Console()

#: Enough rows that every list which paginates has a second page.
DEFAULT_MANY = 150

#: Satisfies the same policy the API enforces — an account the CLI can create
#: but the login screen refuses is not a fixture, it is a bug report.
DEFAULT_PASSWORD = 'QaFixture123'  # noqa: S105 — a fixture account, refused outside dev

VARIANT_VOLUMES = {'empty': 0, 'one': 1, 'many': DEFAULT_MANY}


def _email(variant: str, suffix: str = '') -> str:
    return f'qa-{variant}{suffix}@example.com'


def _guard_environment() -> None:
    guard_disposable_install('creates accounts with known passwords')


# ---------------------------------------------------------------------------
# Organizations and their people
# ---------------------------------------------------------------------------


async def _ensure_org(db: Any, variant: str, password: str) -> tuple[Any, Any]:
    """The organization for *variant* and its admin, created if absent."""
    from sqlalchemy import select

    from app.models.organization import Organization
    from app.models.user import User
    from app.services.auth_service import get_password_hash

    email = _email(variant)
    user = (await db.scalars(select(User).where(User.email == email))).first()
    if user and user.organization_id:
        org = await db.get(Organization, user.organization_id)
        return org, user

    if not user:
        user = User(
            email=email,
            hashed_password=get_password_hash(password),
            full_name=f'QA {variant.title()} Admin',
            role='admin',
            is_active=True,
        )
        db.add(user)
        await db.flush()

    org = Organization(name=f'QA {variant.title()}', created_by=user.id)
    db.add(org)
    await db.flush()
    user.organization_id = org.id
    await db.flush()
    return org, user


async def _ensure_member(db: Any, org: Any, variant: str, role: str, password: str):
    """A member of *org* holding *role*, created if absent."""
    from sqlalchemy import select

    from app.models.user import User
    from app.services.auth_service import get_password_hash

    email = _email(variant, f'-{role}')
    user = (await db.scalars(select(User).where(User.email == email))).first()
    if user:
        user.organization_id = org.id
        user.role = role
        return user

    user = User(
        email=email,
        hashed_password=get_password_hash(password),
        full_name=f'QA {variant.title()} {role.title()}',
        role=role,
        is_active=True,
        organization_id=org.id,
    )
    db.add(user)
    await db.flush()
    return user


async def _apply_profile(db: Any, org: Any, user: Any, profile_id: str) -> None:
    """Seed the profile bundle and switch its modules on, once."""
    from sqlalchemy import select

    from app.core.contracts import UserContextDTO
    from app.models.organization import Organization
    from app.services.onboarding_service import apply_onboarding_profile_async

    # Read the column rather than the attribute: it is deferred, and touching
    # it on a loaded instance would be lazy IO in an async session.
    active = await db.scalar(
        select(Organization.active_profile_id).where(Organization.id == org.id)
    )
    if active == profile_id:
        return

    await apply_onboarding_profile_async(
        db,
        org,
        profile_id,
        user=UserContextDTO(
            id=user.id,
            email=user.email,
            role=user.role,
            organization_id=org.id,
            is_superuser=False,
        ),
    )


# ---------------------------------------------------------------------------
# Volume
# ---------------------------------------------------------------------------


async def _seed_one(db: Any, org: Any, user: Any) -> dict[str, int]:
    """Exactly one of each core record — the state between empty and many."""
    from sqlalchemy import func, select

    from app.core.contracts import UserContextDTO
    from app.models.category import Category
    from app.models.partner import Partner
    from app.models.product_template import ProductTemplate
    from app.models.storage_location import StorageLocation
    from app.schemas.item import ItemCreate
    from app.services.items._create import (
        _default_piece_uom_id_async,
        create_item_async,
    )

    created: dict[str, int] = {}

    async def _count(model) -> int:
        return await db.scalar(
            select(func.count())
            .select_from(model)
            .where(model.organization_id == org.id)
        )

    # Core rows only. An organization provisioned on a module profile
    # already has that module's categories and shelves, and a record filed
    # under one of them is the module's record: the core list hides it, and
    # the "one row" variant showed an empty list.
    location = (
        await db.scalars(
            select(StorageLocation).where(
                StorageLocation.organization_id == org.id,
                StorageLocation.context_tag.is_(None),
            )
        )
    ).first()
    if location is None:
        location = StorageLocation(
            organization_id=org.id, name='QA Location', created_by=user.id
        )
        db.add(location)
        await db.flush()
        created['storage_location'] = 1

    category = (
        await db.scalars(
            select(Category).where(
                Category.organization_id == org.id,
                Category.context_tag.is_(None),
            )
        )
    ).first()
    if category is None:
        category = Category(organization_id=org.id, name='QA Category', icon='box')
        db.add(category)
        await db.flush()
        created['category'] = 1

    if await _count(Partner) == 0:
        # One of each side of the trade: a supplier to receive from and a
        # customer to dispatch to. With suppliers alone the partner picker on
        # a delivery document is empty, and the outbound half of the app
        # cannot be reached from the fixture at all.
        db.add(
            Partner(
                organization_id=org.id,
                name='QA Supplier',
                type='SUPPLIER',
                created_by=user.id,
            )
        )
        db.add(
            Partner(
                organization_id=org.id,
                name='QA Customer',
                type='CUSTOMER',
                created_by=user.id,
            )
        )
        created['partner'] = 2

    template = (
        await db.scalars(
            select(ProductTemplate).where(ProductTemplate.organization_id == org.id)
        )
    ).first()
    if template is None:
        # The unit every other door gives a product nobody chose one for:
        # the organization's pieces, and a refusal when the catalogue has
        # none — never the first row of anyone's catalogue, or no unit.
        template = ProductTemplate(
            organization_id=org.id,
            name='QA Product',
            uom_id=await _default_piece_uom_id_async(db, org.id),
        )
        db.add(template)
        await db.flush()
        created['product_template'] = 1

    from app.models.item import Item

    if await _count(Item) == 0:
        await create_item_async(
            db,
            ItemCreate(
                # The template's name: the record is matched to its template
                # by name, and a different one minted a second template —
                # two catalogue rows in the variant that promises one.
                name=template.name,
                quantity=1,
                location_id=location.id,
                category_id=category.id,
                template_id=template.id,
            ),
            UserContextDTO(
                id=user.id,
                email=user.email,
                role=user.role,
                organization_id=org.id,
                is_superuser=False,
            ),
        )
        created['item'] = 1

    return created


def _seed_many(org_id: Any, created_by: Any, items: int) -> dict[str, int]:
    """Volume, through the demo seeder — the path that writes the ledger too.

    Synchronous, and deliberately so: the seeder is a sync script and rewriting
    it to be called from here would put a second copy of item creation in the
    tree, which is how a record and its ledger drift apart.

    What gets seeded follows the organization's own modules, so the fixture
    stops depending on which profile it was provisioned with: a warehouse
    organization gets its equipment, documents and orders, a food one gets
    neither the rows nor a crash over the categories it never declared.
    """
    import seed_demo_data as demo  # backend root, not a package
    from app.database import SessionLocal
    from app.models.organization import Organization

    db = SessionLocal()
    try:
        org = db.get(Organization, org_id)
        modules = list(org.enabled_modules or []) if org is not None else []
        return demo.seed_organization(
            db, org_id, created_by, items=items, modules=modules
        )
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Reset
# ---------------------------------------------------------------------------


#: Rows a wipe must not take with it. ``organizations`` goes last and by hand;
#: ``users`` carries the accounts, which are tenant rows here even though the
#: table is shared with other organizations.
_WIPE_SKIP_TABLES = frozenset({'organizations', 'alembic_version'})


def _import_module_tables() -> None:
    """Put every module's tables into ``Base.metadata``.

    A table joins the metadata when the module that declares it is imported,
    and a CLI process has imported none of them. The wipe below walks the
    metadata, so what it has not imported it does not delete: it used to leave
    an organization's documents and orders standing, and the next statement —
    the accounts — then walked into the foreign key an order holds on its
    author.

    Importing each module's ``models`` rather than its package: whether a
    package pulls its own models in is a per-module habit, and the one that
    did not was the one that broke this.
    """
    import importlib
    from pathlib import Path

    import app.modules as modules_pkg

    root = Path(modules_pkg.__file__).parent
    for module_dir in sorted(root.iterdir()):
        if not module_dir.is_dir() or module_dir.name.startswith('_'):
            continue
        name = f'app.modules.{module_dir.name}.models'
        try:
            importlib.import_module(name)
        except ModuleNotFoundError as exc:
            # A module with no tables of its own. Anything deeper failing to
            # import is a real problem and is left to raise.
            if exc.name != name:
                raise


async def wipe_organization_async(db: Any, organization_id: Any) -> dict[str, int]:
    """Delete one organization and everything that belongs to it.

    Deleting an organization is not an operation the application offers, and a
    hand-written ``DELETE`` walks straight into two walls: a foreign key with
    ``ON DELETE SET NULL`` into ``stock_moves``, whose CHECK then refuses the
    null, and half a dozen ``NO ACTION`` keys from line tables that have no
    ``organization_id`` of their own.

    Both walls come from deleting in the wrong order, so the order is the whole
    method: children before parents. ``metadata.sorted_tables`` lists a table
    after everything it references; walking it backwards means a row is always
    gone before the row it points at, and the line tables ride along on their
    parents' ``ON DELETE CASCADE``.

    There is a third wall, and it is one we put there on purpose: ``audit_log``
    carries a trigger that refuses every UPDATE and DELETE, so the log is
    append-only for the application and for anyone at a psql prompt. This
    command is the one place that is allowed past it — unmaking a QA
    organization is its entire job, it refuses to run outside development and
    staging, and it says out loud which table it lifted the guard for. The
    trigger is disabled for this transaction only; a rollback or a crash leaves
    it exactly as it was.

    Returns the row count removed per table — the caller prints it, and a
    silent reset is indistinguishable from one that missed.
    """
    from sqlalchemy import delete, func, select, text

    from app.database import Base
    from app.models.organization import Organization

    org = await db.get(Organization, organization_id)
    if org is None:
        return {}

    _import_module_tables()

    await db.execute(
        # `USER` rather than the trigger's name: naming it fails on a database
        # that does not have it, and the test databases are built with
        # `create_all`, which makes tables and no triggers.
        text('ALTER TABLE audit_log DISABLE TRIGGER USER')
    )

    removed: dict[str, int] = {}
    for table in reversed(Base.metadata.sorted_tables):
        if table.name in _WIPE_SKIP_TABLES:
            continue
        column = table.c.get('organization_id')
        if column is None:
            continue
        count = await db.scalar(
            select(func.count()).select_from(table).where(column == organization_id)
        )
        if not count:
            continue
        await db.execute(delete(table).where(column == organization_id))
        removed[table.name] = count

    await db.delete(org)
    await db.flush()
    await db.execute(text('ALTER TABLE audit_log ENABLE TRIGGER USER'))
    return removed


async def reset_variant_async(db: Any, variant: str) -> dict[str, int]:
    """Return one QA variant to the state it had before it was ever provisioned.

    Wipes the organization each of the variant's three accounts points at, then
    removes the accounts themselves. The second half is not tidiness: an account
    left pointing at a deleted organization makes the next provisioning run
    adopt the wreck (``_ensure_org`` looks the organization up *through* the
    admin) instead of building a clean one.
    """
    from sqlalchemy import delete, select

    from app.models.user import User

    emails = [_email(variant), _email(variant, '-viewer'), _email(variant, '-user')]
    users = (await db.scalars(select(User).where(User.email.in_(emails)))).all()

    removed: dict[str, int] = {}
    for org_id in {u.organization_id for u in users if u.organization_id}:
        for table, count in (await wipe_organization_async(db, org_id)).items():
            removed[table] = removed.get(table, 0) + count

    # Accounts of an organization that was already gone: no wipe reached them.
    leftovers = await db.execute(delete(User).where(User.email.in_(emails)))
    if leftovers.rowcount:
        removed['users'] = removed.get('users', 0) + leftovers.rowcount
    await db.flush()
    return removed


# ---------------------------------------------------------------------------
# The command
# ---------------------------------------------------------------------------


async def _reset(variant: str) -> dict[str, int]:
    """Open a session of its own and clear one variant. See ``fixture --reset``."""
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from app import database

    database.init_async_engine()
    factory = cast(
        'async_sessionmaker[AsyncSession]',
        database.AsyncSessionLocal,
    )
    async with factory() as db:
        removed = await reset_variant_async(db, variant)
        await db.commit()
        return removed


async def _provision(variant: str, password: str, profile_id: str) -> dict[str, Any]:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from app import database
    from app.core._require_module import invalidate_org_module_caches

    # The session factory is a module global the initialiser rebinds, so it has
    # to be read through the module and after the call — and it is declared as
    # None until then, which is why the cast is here rather than an assertion.
    database.init_async_engine()
    factory = cast(
        'async_sessionmaker[AsyncSession]',
        database.AsyncSessionLocal,
    )

    async with factory() as db:
        org, admin = await _ensure_org(db, variant, password)
        await _apply_profile(db, org, admin, profile_id)
        await _ensure_member(db, org, variant, 'viewer', password)
        await _ensure_member(db, org, variant, 'user', password)
        counts = await _seed_one(db, org, admin) if variant == 'one' else {}
        await db.commit()
        # A CLI has no app lifespan, so the cache client is unset here: clear
        # the running app's module caches through a connection of our own.
        await invalidate_org_module_caches(org.id, standalone=True)
        return {
            'organization': org.name,
            'organization_id': str(org.id),
            'admin': admin.email,
            'admin_id': admin.id,
            'seeded': counts,
        }


def _validate_password(password: str) -> None:
    from app.schemas.user import validate_password_policy

    try:
        validate_password_policy(password)
    except ValueError as exc:
        console.print(f'[red]✘ Password rejected: {exc}[/]')
        raise typer.Exit(code=1) from exc


def _wanted_variants(variant: str) -> list[str]:
    wanted = list(VARIANT_VOLUMES) if variant == 'all' else [variant]
    unknown = [v for v in wanted if v not in VARIANT_VOLUMES]
    if unknown:
        console.print(f'[red]✘ Unknown variant(s): {", ".join(unknown)}[/]')
        raise typer.Exit(code=1)
    return wanted


def _provision_variants(
    wanted: list[str], password: str, profile: str, items: int
) -> None:
    """Build every organization in *wanted* and print its accounts."""
    for name in wanted:
        try:
            result = asyncio.run(_provision(name, password, profile))
        except Exception as exc:  # noqa: BLE001 — a CLI reports, it does not raise at the user
            console.print(f'[red]✘ {name}: {exc}[/]')
            sys.exit(1)

        if name == 'many':
            result['seeded'] = _seed_many(
                result['organization_id'], result['admin_id'], items
            )

        console.print(
            f'[green]✔[/] {result["organization"]} — {result["admin"]} '
            f'(+ {_email(name, "-viewer")}, {_email(name, "-user")})'
        )
        for key, value in (result['seeded'] or {}).items():
            console.print(f'    {key}: {value}')

    console.print(f'\nPassword for every account above: [bold]{password}[/]')


@qa_app.command()
def fixture(
    variant: str = typer.Option(
        'all', help='empty | one | many | all — which organization to provision'
    ),
    profile: str = typer.Option(
        'equipment_wms',
        help='Product profile to apply. food_home brings recipes and shopping lists.',
    ),
    items: int = typer.Option(
        DEFAULT_MANY, help='Target item count for the "many" organization'
    ),
    password: str = typer.Option(DEFAULT_PASSWORD, help='Password for every account'),
    reset: bool = typer.Option(
        False,
        '--reset',
        help='Delete the organization and its accounts first, then provision '
        'from scratch. Use it when a pass left state the application itself '
        'cannot remove.',
    ),
    yes: bool = typer.Option(
        False, '--yes', '-y', help='Answer the --reset confirmation with yes.'
    ),
):
    """Provision the empty / one / many organizations a manual QA run needs."""
    _guard_environment()
    _validate_password(password)
    wanted = _wanted_variants(variant)

    if reset:
        targets = ', '.join(f'QA {n.title()}' for n in wanted)
        if not yes:
            typer.confirm(
                f'Delete {targets} — every row and every account — and rebuild?',
                abort=True,
            )
        for name in wanted:
            try:
                removed = asyncio.run(_reset(name))
            except Exception as exc:  # noqa: BLE001 — a CLI reports, it does not raise at the user
                console.print(f'[red]✘ reset {name}: {exc}[/]')
                sys.exit(1)
            total = sum(removed.values())
            if total:
                head = ', '.join(
                    f'{table} {count}'
                    for table, count in sorted(removed.items(), key=lambda kv: -kv[1])[
                        :4
                    ]
                )
                console.print(f'[yellow]↺[/] QA {name.title()} wiped — {head}')
            else:
                console.print(f'[dim]↺ QA {name.title()} — nothing to wipe[/]')

    _provision_variants(wanted, password, profile, items)


@qa_app.command()
def reset(
    variant: str = typer.Argument(
        ...,
        help='Which organization to clear: the part between "qa-" and "@" in '
        'its admin address (empty | one | many | food | ...).',
    ),
    yes: bool = typer.Option(
        False, '--yes', '-y', help='Answer the confirmation with yes.'
    ),
):
    """Clear one QA organization without rebuilding it.

    ``fixture --reset`` wipes and provisions in one go, which only works for the
    variants the fixture knows how to build. The organizations a pass dirties are
    not always those three — ``qa-food@example.com`` follows the same convention
    and is not one of them — so this command is keyed to the address rather than
    to the provisioner's list, and stops after the wipe.
    """
    _guard_environment()

    if not yes:
        typer.confirm(
            f'Delete QA {variant.title()} — every row and every account?',
            abort=True,
        )

    try:
        removed = asyncio.run(_reset(variant))
    except Exception as exc:  # a CLI reports, it does not raise at the user
        console.print(f'[red]✘ reset {variant}: {exc}[/]')
        raise typer.Exit(code=1) from exc

    if not removed:
        console.print(f'[dim]↺ nothing to wipe — no account {_email(variant)}[/]')
        return

    console.print(f'[yellow]↺[/] QA {variant.title()} wiped:')
    for table, count in sorted(removed.items(), key=lambda kv: -kv[1]):
        console.print(f'    {table}: {count}')
