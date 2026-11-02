"""`qa fixture --reset` — wiping one QA organization without touching the others.

A manual QA run leaves sediment the application itself refuses to remove: a
completed stock take, an archived storage location, a row whose quantity a bad
import made unreadable. Until this command existed the only way back was SQL by
hand, which is the one thing a QA run is not allowed to need.

The two properties worth a test are the two that make the difference between a
tool and an accident: everything hanging off the organization goes, and nothing
belonging to any other organization does.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.category import Category
from app.models.item import Item
from app.models.organization import Organization
from app.models.storage_location import StorageLocation
from app.models.user import User


async def _make_org(db: AsyncSession, name: str) -> tuple[Organization, User]:
    """A second organization, built the short way — it only has to exist."""
    from app.services.auth_service import get_password_hash

    org = Organization(name=name)
    db.add(org)
    await db.flush()
    user = User(
        email=f'{uuid.uuid4().hex[:8]}@example.com',
        hashed_password=get_password_hash('testpassword123'),
        full_name=name,
        organization_id=org.id,
        role='admin',
        is_active=True,
    )
    db.add(user)
    await db.flush()
    return org, user


@pytest.mark.asyncio
class TestWipeOrganization:
    async def test_wipe_removes_the_organization_its_people_and_its_rows(
        self,
        real_async_db_session: AsyncSession,
        async_test_household: Organization,
        async_test_user: User,
        async_test_storage_location: StorageLocation,
        async_test_category: Category,
        async_test_item: Item,
    ) -> None:
        """The organization row, its members and its data are all gone."""
        from app.cli.commands_qa import wipe_organization_async

        db = real_async_db_session
        org_id = async_test_household.id
        await db.commit()

        removed = await wipe_organization_async(db, org_id)
        await db.commit()

        assert await db.get(Organization, org_id) is None
        for model in (User, Item, StorageLocation, Category):
            left = await db.scalar(
                select(func.count())
                .select_from(model)
                .where(model.organization_id == org_id)
            )
            assert left == 0, f'{model.__tablename__} still has rows'

        # The report is what the console prints; it has to name what it did.
        assert removed['items'] == 1
        assert removed['users'] == 1

    async def test_wipe_leaves_every_other_organization_untouched(
        self,
        real_async_db_session: AsyncSession,
        async_test_household: Organization,
        async_test_user: User,
        async_test_item: Item,
    ) -> None:
        """A reset aimed at one organization is not a reset of the database."""
        from app.cli.commands_qa import wipe_organization_async

        db = real_async_db_session
        neighbour, neighbour_admin = await _make_org(db, 'Untouched Org')
        neighbour_id = neighbour.id
        neighbour_admin_id = neighbour_admin.id
        await db.commit()

        await wipe_organization_async(db, async_test_household.id)
        await db.commit()

        assert await db.get(Organization, neighbour_id) is not None
        assert await db.get(User, neighbour_admin_id) is not None

    async def test_wipe_survives_rows_that_point_at_a_shelf(
        self,
        real_async_db_session: AsyncSession,
        async_test_household: Organization,
        async_test_user: User,
        async_test_storage_location: StorageLocation,
        async_test_item: Item,
    ) -> None:
        """A stock movement must not outlive — or block — the shelf it names.

        Deleting a storage location by hand fails here: the movement's foreign
        key is ON DELETE SET NULL and the table has a CHECK demanding at least
        one location, so the null violates it. That is the exact wall a manual
        cleanup hits, so the order this command deletes in is the thing under
        test.
        """
        from app.cli.commands_qa import wipe_organization_async
        from app.models.product_template import ProductTemplate
        from app.models.stock_move import StockMove

        db = real_async_db_session
        org_id = async_test_household.id
        template = ProductTemplate(organization_id=org_id, name='Moved thing')
        db.add(template)
        await db.flush()
        db.add(
            StockMove(
                organization_id=org_id,
                product_template_id=template.id,
                to_location_id=async_test_storage_location.id,
                quantity=2,
                state='done',
                reference_type='item',
                reference_id=async_test_item.id,
            )
        )
        await db.commit()

        await wipe_organization_async(db, org_id)
        await db.commit()

        left = await db.scalar(
            select(func.count())
            .select_from(StockMove)
            .where(StockMove.organization_id == org_id)
        )
        assert left == 0

    async def test_wipe_of_an_unknown_organization_is_not_an_error(
        self,
        real_async_db_session: AsyncSession,
    ) -> None:
        """Resetting a variant that was never provisioned is a no-op, not a crash."""
        from app.cli.commands_qa import wipe_organization_async

        removed = await wipe_organization_async(real_async_db_session, uuid.uuid4())

        assert removed == {}


@pytest.mark.asyncio
class TestResetVariant:
    async def test_reset_takes_the_variant_organization_and_all_three_accounts(
        self,
        real_async_db_session: AsyncSession,
    ) -> None:
        """`--reset many` clears QA Many and the three accounts that reach it."""
        from app.cli.commands_qa import _email, reset_variant_async
        from app.services.auth_service import get_password_hash

        db = real_async_db_session
        org = Organization(name='QA Many')
        db.add(org)
        await db.flush()
        for suffix, role in (('', 'admin'), ('-viewer', 'viewer'), ('-user', 'user')):
            db.add(
                User(
                    email=_email('many', suffix),
                    hashed_password=get_password_hash('testpassword123'),
                    full_name=f'QA Many {role}',
                    organization_id=org.id,
                    role=role,
                    is_active=True,
                )
            )
        await db.commit()

        await reset_variant_async(db, 'many')
        await db.commit()

        assert await db.get(Organization, org.id) is None
        for suffix in ('', '-viewer', '-user'):
            left = await db.scalar(
                select(func.count())
                .select_from(User)
                .where(User.email == _email('many', suffix))
            )
            assert left == 0, f'account {_email("many", suffix)} survived'

    async def test_reset_removes_an_account_left_without_its_organization(
        self,
        real_async_db_session: AsyncSession,
    ) -> None:
        """A half-deleted fixture is exactly what a reset is for.

        An account pointing at an organization that no longer exists makes the
        next provisioning run adopt the wreck instead of building a new one, so
        the reset has to clear the account too.
        """
        from app.cli.commands_qa import _email, reset_variant_async
        from app.services.auth_service import get_password_hash

        db = real_async_db_session
        orphan = User(
            email=_email('one'),
            hashed_password=get_password_hash('testpassword123'),
            full_name='QA One Admin',
            organization_id=None,
            role='admin',
            is_active=True,
        )
        db.add(orphan)
        await db.commit()

        await reset_variant_async(db, 'one')
        await db.commit()

        left = await db.scalar(
            select(func.count()).select_from(User).where(User.email == _email('one'))
        )
        assert left == 0

    async def test_reset_of_a_variant_that_was_never_provisioned_is_a_no_op(
        self,
        real_async_db_session: AsyncSession,
    ) -> None:
        from app.cli.commands_qa import reset_variant_async

        assert await reset_variant_async(real_async_db_session, 'empty') == {}

    async def test_reset_works_for_a_variant_the_provisioner_does_not_know(
        self,
        real_async_db_session: AsyncSession,
    ) -> None:
        """QA Food follows the naming convention but is not a provisionable variant.

        The organizations a pass dirties are not always the three the fixture
        builds — ``qa-food@example.com`` was made by hand and follows the same
        convention. A reset keyed to ``VARIANT_VOLUMES`` would refuse exactly
        the organization that needs it most, so it is keyed to the address.
        """
        from app.cli.commands_qa import VARIANT_VOLUMES, _email, reset_variant_async
        from app.services.auth_service import get_password_hash

        assert 'food' not in VARIANT_VOLUMES

        db = real_async_db_session
        org = Organization(name='QA Food')
        db.add(org)
        await db.flush()
        db.add(
            User(
                email=_email('food'),
                hashed_password=get_password_hash('testpassword123'),
                full_name='QA Food Admin',
                organization_id=org.id,
                role='admin',
                is_active=True,
            )
        )
        await db.commit()

        await reset_variant_async(db, 'food')
        await db.commit()

        assert await db.get(Organization, org.id) is None


class TestTheWipeSeesEveryModulesTables:
    """The walk deletes what is in ``Base.metadata``, and nothing else.

    A module's tables land there when the module is imported, and a CLI
    process has imported none of them. The wipe therefore left an
    organization's documents and orders standing, and the next statement — its
    accounts — walked into the foreign key an order holds on its author:
    ``update or delete on table "users" violates ... purchase_orders_created_by_fkey``.

    Asked in a fresh interpreter on purpose. This test process has imported
    half the tree already, so in here the answer is yes whatever the wipe does
    — the condition only exists where the command runs.
    """

    def test_a_fresh_interpreter_sees_the_module_tables(self) -> None:
        import subprocess
        import sys

        script = (
            'from app.database import Base\n'
            'from app.cli.commands_qa import _import_module_tables\n'
            'before = "purchase_orders" in Base.metadata.tables\n'
            '_import_module_tables()\n'
            'after = "purchase_orders" in Base.metadata.tables\n'
            'print(before, after)\n'
        )
        result = subprocess.run(
            [sys.executable, '-c', script],
            capture_output=True,
            text=True,
            check=True,
        )

        assert result.stdout.split() == ['False', 'True'], result.stdout
