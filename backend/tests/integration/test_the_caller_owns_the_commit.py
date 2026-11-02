"""The commit — and the rollback — belong to whoever owns the transaction.

One convention covers every layer below the router: flush, and let the
caller commit. The request-scoped session commits once, on success, before
the response is written. A service that commits slices the caller's unit of
work in two; one that rolls back erases everything the caller wrote before
asking. Conversions that came with the rule, each pinned here:

- ``delete_storage`` used to commit mid-flight (and to roll the caller back
  when the delete itself was refused);
- ``create_storage_hierarchy`` committed mid-chain while its docstring says
  "atomically";
- the CoreAPI write methods that promised flush-only and did not:
  ``_category_writes``, ``onboarding_service.apply_onboarding_profile_async``
  and ``template_crud`` each committed at the end of their own write, so a
  module composing a CoreAPI call with its own write got a transaction cut
  in two underneath it;
- ``import_lines_from_dataframe`` committed when it finished, which made the
  opening-stock import two transactions: the draft survived an error raised
  in the step after the lines (see
  ``test_opening_stock_lands_as_one_draft_receipt``).

A third, ``decrement_quant_by_strategy_async`` flushing partial draws before
it refused, went with the quant table: the draw that replaced it plans from
the records and writes nothing unless the whole of it can be taken.

The label-scan provider's core commit is pinned by its absence from the
architecture-lint baseline rather than here.
"""

from uuid import uuid4

import pandas as pd
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import UserContextDTO
from app.models.category import Category
from app.models.storage_location import StorageLocation
from app.modules.warehouse.document_import_service import import_lines_from_dataframe
from app.schemas.category import CategoryCreate, CategoryUpdate
from app.schemas.storage_location import StorageHierarchyCreate, StorageHierarchyStep
from app.services import template_crud
from app.services._category_writes import (
    create_category,
    delete_category,
    update_category,
)
from app.services.onboarding_service import apply_onboarding_profile_async
from app.services.storage._writes import delete_storage
from app.services.storage_hierarchy_service import create_storage_hierarchy

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


def _user(user) -> UserContextDTO:
    """The DTO the router would hand over — the user must really exist,
    because the audit trail the write leaves points at their row."""
    return UserContextDTO(
        id=user.id,
        organization_id=user.organization_id,
        role='admin',
        email=user.email,
    )


async def _spy_on(db: AsyncSession, method: str, calls: list[str]) -> None:
    """Shadow a session method just enough to notice it was used.

    The shadow only arms the trap while the service runs: the fixture
    teardown commits for real, so the spy comes back off afterwards.
    """
    original = getattr(db, method)

    async def recorder(*args, **kwargs):
        calls.append(method)
        raise AssertionError(
            f'the service called {method}() — the caller owns the transaction'
        )

    setattr(db, method, recorder)

    async def restore():
        db.__dict__.pop(method, None)
        setattr(db, method, original)

    db.__dict__[f'_restore_{method}'] = restore


async def _witness_rename(db: AsyncSession, org_id, user_id) -> StorageLocation:
    """A caller mid-unit-of-work: a rename that is not committed yet."""
    witness = await _empty_storage(db, org_id, user_id, f'Witness {uuid4().hex[:6]}')
    witness.name = f'Witness Renamed {uuid4().hex[:6]}'
    await db.flush()
    return witness


async def _empty_storage(
    db: AsyncSession, org_id, user_id, name: str
) -> StorageLocation:
    storage = StorageLocation(
        organization_id=org_id,
        created_by=user_id,
        name=name,
        behavior_mode='STOCK',
    )
    db.add(storage)
    await db.flush()
    return storage


async def test_delete_neither_commits_nor_rolls_the_caller_back(
    real_async_db_session: AsyncSession,
    async_test_household,
    async_test_user,
    async_test_storage_location,
) -> None:
    db = real_async_db_session
    witness = await _witness_rename(db, async_test_household.id, async_test_user.id)
    renamed_to = witness.name
    victim = await _empty_storage(
        db, async_test_household.id, async_test_user.id, 'Victim Shelf'
    )

    commits: list[str] = []
    rollbacks: list[str] = []
    await _spy_on(db, 'commit', commits)
    await _spy_on(db, 'rollback', rollbacks)

    await delete_storage(db, victim, _user(async_test_user))

    # The delete rode the caller's unit of work: no commit of its own, no
    # rollback of anything the caller had standing, and the row is gone.
    assert commits == []
    assert rollbacks == []
    await db.__dict__['_restore_commit']()
    await db.__dict__['_restore_rollback']()
    assert witness.name == renamed_to
    assert (
        await db.scalar(select(StorageLocation).where(StorageLocation.id == victim.id))
        is None
    )


async def test_the_hierarchy_builds_without_committing_midway(
    real_async_db_session: AsyncSession,
    async_test_household,
    async_test_user,
    async_test_storage_location,
) -> None:
    db = real_async_session_guard(real_async_db_session)
    commits: list[str] = []
    await _spy_on(db, 'commit', commits)

    node = await create_storage_hierarchy(
        db,
        StorageHierarchyCreate(
            parent_id=async_test_storage_location.id,
            steps=[
                StorageHierarchyStep(name='Aisle'),
                StorageHierarchyStep(name='Rack'),
            ],
        ),
        _user(async_test_user),
    )

    # The docstring says "atomically" — one unit of work, ended by the
    # caller's commit, not two commits stitched around a second one.
    assert commits == []
    await db.__dict__['_restore_commit']()
    rack = await db.scalar(select(StorageLocation).where(StorageLocation.id == node.id))
    assert rack is not None
    parent = await db.scalar(
        select(StorageLocation).where(StorageLocation.id == rack.parent_id)
    )
    assert parent is not None and parent.name == 'Aisle'


async def test_category_writes_never_commit(
    real_async_db_session: AsyncSession,
    async_test_user,
) -> None:
    """create/update/delete ride the caller's unit of work.

    The three committed at the end of their own write, so a module that
    composed a category write with one of its own got the transaction cut
    under it — the module's rollback could not take the category back, and
    the journal entry had already left.
    """
    db = real_async_db_session
    user = _user(async_test_user)
    commits: list[str] = []
    await _spy_on(db, 'commit', commits)

    name = f'Category {uuid4().hex[:6]}'
    created = await create_category(db, CategoryCreate(name=name), user)
    await update_category(db, created, CategoryUpdate(name=f'{name} v2'), user)
    await delete_category(db, created, user)

    assert commits == []
    await db.__dict__['_restore_commit']()
    await db.flush()
    assert await db.scalar(select(Category).where(Category.id == created.id)) is None


async def test_template_writes_never_commit(
    real_async_db_session: AsyncSession,
    async_test_household,
    async_test_user,
) -> None:
    """create, seed, copy, update and delete all flush and return."""
    db = real_async_db_session
    org_id = async_test_household.id
    user_id = async_test_user.id
    commits: list[str] = []
    await _spy_on(db, 'commit', commits)

    created = await template_crud.create_template_async(
        db,
        org_id,
        'warehouse',
        user_id,
        name=f'Template {uuid4().hex[:6]}',
        body_html='<p>hello</p>',
    )
    seeded = await template_crud.seed_default_templates_async(
        db,
        org_id,
        'warehouse',
        user_id,
        [(f'Built-in {uuid4().hex[:6]}', 'DEFAULT', '<p>built</p>')],
    )
    await template_crud.copy_builtin_alongside_async(
        db,
        org_id,
        'warehouse',
        user_id,
        seeded[0].id,
        [(seeded[0].source_builtin, 'DEFAULT', '<p>moved on</p>')],
    )
    await template_crud.update_template_async(
        db,
        org_id,
        created.id,
        'warehouse',
        name='Renamed',
        user_id=user_id,
    )
    await template_crud.delete_template_async(
        db, org_id, created.id, 'warehouse', user_id=user_id
    )

    assert commits == []
    await db.__dict__['_restore_commit']()


async def test_document_line_import_never_commits(
    real_async_db_session: AsyncSession,
    async_test_household,
    async_test_user,
) -> None:
    """The import flushes what it built; the caller ends the transaction.

    The response carries the created lines' ids, and those come from the
    flush — not from a commit the importer performed behind the caller.
    """
    from app.modules.warehouse.models import Document

    db = real_async_db_session
    doc = Document(
        organization_id=async_test_household.id,
        type='IN',
        number=f'IMP-{uuid4().hex[:6]}',
        status='DRAFT',
        created_by=async_test_user.id,
    )
    db.add(doc)
    await db.flush()

    commits: list[str] = []
    await _spy_on(db, 'commit', commits)
    result = await import_lines_from_dataframe(
        db,
        doc.id,
        pd.DataFrame([{'name': 'Widget A', 'quantity': 2}]),
        {'name': 'name', 'quantity': 'quantity'},
        async_test_household.id,
    )

    assert result['imported'] == 1
    assert result['lines'][0]['id'] is not None
    assert commits == []
    await db.__dict__['_restore_commit']()


async def test_onboarding_stays_inside_the_callers_transaction(
    real_async_db_session: AsyncSession,
) -> None:
    """The profile seed and the module switch flush; the caller commits.

    ``apply_onboarding_profile_async`` used to commit at its end — after
    the router had handed it the request session, before the router could
    write anything of its own. The seed it runs is asked to stay inside the
    transaction for the same reason (``commit=False``).
    """
    from app.models.organization import Organization
    from app.models.user import User

    db = real_async_db_session
    org = Organization(name=f'Onboarding {uuid4().hex[:8]}', enabled_modules=['core'])
    db.add(org)
    await db.flush()
    onboarder = User(
        email=f'onboarder_{uuid4().hex[:8]}@example.com',
        hashed_password='x',
        full_name='Onboarder',
        organization_id=org.id,
        role='admin',
        is_active=True,
    )
    db.add(onboarder)
    await db.flush()
    user = UserContextDTO(
        id=onboarder.id, organization_id=org.id, role='admin', email=onboarder.email
    )

    commits: list[str] = []
    await _spy_on(db, 'commit', commits)

    applied = await apply_onboarding_profile_async(db, org, 'food_home', user=user)

    assert applied.onboarding_completed is True
    assert commits == []
    await db.__dict__['_restore_commit']()


def real_async_session_guard(db: AsyncSession) -> AsyncSession:
    """A no-op marker: the hierarchy test below wants the real session."""
    return db
