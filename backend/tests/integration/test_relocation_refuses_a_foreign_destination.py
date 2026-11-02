"""``relocate_stock_async`` decides where a quant ends up, so it checks itself.

Both callers — the single move and the bulk edit — validate the destination
before they get here, the bulk edit only since a fix that taught it to. That made the
guarantee a matter of caller discipline: the function itself created a quant
on whatever location id it was handed, so the next caller written would have
to remember. It no longer has to.
"""

from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.organization import Organization
from app.models.product_template import ProductTemplate
from app.models.storage_location import StorageLocation
from app.models.storage_type import StorageType
from app.models.user import User
from app.services.items._stock_relocation import relocate_stock_async


@pytest.fixture
async def foreign_location(
    real_async_db_session: AsyncSession,
    async_test_storage_type: StorageType,
    async_test_user: User,
) -> StorageLocation:
    """A shelf belonging to a different organization entirely."""
    other_org = Organization(name='Someone Else', enabled_modules=['core', 'items'])
    real_async_db_session.add(other_org)
    await real_async_db_session.flush()

    shelf = StorageLocation(
        organization_id=other_org.id,
        storage_type_id=async_test_storage_type.id,
        name='Their Shelf',
        created_by=async_test_user.id,
    )
    real_async_db_session.add(shelf)
    await real_async_db_session.flush()
    await real_async_db_session.refresh(shelf)
    return shelf


@pytest.fixture
async def template(
    real_async_db_session: AsyncSession, async_test_user: User
) -> ProductTemplate:
    tpl = ProductTemplate(name='Flour', organization_id=async_test_user.organization_id)
    real_async_db_session.add(tpl)
    await real_async_db_session.flush()
    await real_async_db_session.refresh(tpl)
    return tpl


@pytest.mark.integration
class TestRelocationChecksItsDestination:
    @pytest.mark.asyncio
    async def test_a_shelf_of_another_organization_is_refused(
        self,
        real_async_db_session: AsyncSession,
        async_test_user: User,
        async_test_storage_location: StorageLocation,
        foreign_location: StorageLocation,
        template: ProductTemplate,
    ):
        with pytest.raises(ValueError, match='destination'):
            await relocate_stock_async(
                real_async_db_session,
                org_id=async_test_user.organization_id,
                template_id=template.id,
                from_location_id=async_test_storage_location.id,
                to_location_id=foreign_location.id,
                quantity=Decimal('1'),
                item_id=uuid4(),
            )

    @pytest.mark.asyncio
    async def test_a_destination_that_does_not_exist_is_refused(
        self,
        real_async_db_session: AsyncSession,
        async_test_user: User,
        async_test_storage_location: StorageLocation,
        template: ProductTemplate,
    ):
        with pytest.raises(ValueError, match='destination'):
            await relocate_stock_async(
                real_async_db_session,
                org_id=async_test_user.organization_id,
                template_id=template.id,
                from_location_id=async_test_storage_location.id,
                to_location_id=uuid4(),
                quantity=Decimal('1'),
                item_id=uuid4(),
            )
