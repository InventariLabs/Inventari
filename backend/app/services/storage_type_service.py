from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import UserContextDTO
from app.core.exceptions import ServiceRejectionError
from app.core.logging import get_logger
from app.i18n import Language
from app.i18n.service import get_error_message
from app.models.storage_location import StorageLocation
from app.models.storage_type import STORAGE_TYPE_ORDER, StorageType
from app.schemas.storage_type import StorageTypeCreate, StorageTypeUpdate

logger = get_logger(__name__)


class StorageTypeService:
    @staticmethod
    async def list_for_org_async(
        db: AsyncSession, organization_id: UUID
    ) -> list[StorageType]:
        """Return the storage types owned by *organization_id*.

        Every type has an owner since — seeded by the organization's
               profile, by a module it enabled, or created by hand. Rows with no
               owner were readable by every tenant on the installation, which is why
               an organization on the food profile could see another one's server
               racks; the migration copies them per organization and removes them.

        The rows come back in a stable order (name, then name case-folded
        away, then id). Without an ORDER BY Postgres returns heap order, and
        heap order on a long-lived table follows the physical layout, not
        the data — the same organization could see its types shuffle
        between reads, and two rows sharing a type code would resolve
        their collision by accident.
        """
        result = await db.scalars(
            select(StorageType)
            .where(StorageType.organization_id == organization_id)
            .order_by(*STORAGE_TYPE_ORDER)
        )
        return list(result.all())

    @staticmethod
    async def get_by_id_async(
        db: AsyncSession, storage_type_id: UUID, organization_id: UUID | None = None
    ) -> StorageType | None:
        """Return a single storage type by ID, or ``None``.

        When *organization_id* is provided, only returns the type if it belongs
        to that org or is a system type (organization_id IS NULL).
        """
        from sqlalchemy import or_

        stmt = select(StorageType).where(StorageType.id == storage_type_id)
        if organization_id is not None:
            stmt = stmt.where(
                or_(
                    StorageType.organization_id == organization_id,
                    StorageType.organization_id.is_(None),
                )
            )
        result = await db.scalar(stmt)
        return result

    @staticmethod
    async def create_storage_type_async(
        db: AsyncSession,
        storage_type_in: StorageTypeCreate,
        user: UserContextDTO,
        lang: Language | None = None,
    ) -> StorageType:
        organization_id = user.organization_id

        filters = [StorageType.type_code == storage_type_in.type_code.upper()]
        if organization_id:
            filters.append(StorageType.organization_id == organization_id)
        else:
            filters.append(StorageType.organization_id.is_(None))

        if await db.scalar(select(StorageType).where(*filters)):
            raise ServiceRejectionError('storage_type_exists')

        storage_type = StorageType(
            name=storage_type_in.name,
            type_code=storage_type_in.type_code.upper(),
            icon=storage_type_in.icon,
            default_settings=storage_type_in.default_settings,
            organization_id=organization_id,
            created_by=user.id,
            is_system=False,
        )
        db.add(storage_type)
        await db.flush()
        await db.refresh(storage_type)
        return storage_type

    @staticmethod
    async def update_storage_type_async(
        db: AsyncSession,
        storage_type: StorageType,
        storage_type_in: StorageTypeUpdate,
        user: UserContextDTO,
        lang: Language | None = None,
    ) -> StorageType:
        """Update a storage type; a global one is forked for the organization first.

        A type the organization owns is edited in place even when a profile
        seeded it (``is_system``): the seeders never rewrite a changed name, so
        renaming is how the organization adapts it. Only deletion is refused.
        """
        if storage_type.organization_id is None:
            existing_fork = await db.scalar(
                select(StorageType).where(
                    StorageType.organization_id == user.organization_id,
                    StorageType.type_code == storage_type.type_code,
                )
            )

            if existing_fork:
                storage_type = existing_fork
            else:
                new_storage_type = StorageType(
                    name=storage_type.name,
                    type_code=storage_type.type_code,
                    behavior_mode=storage_type.behavior_mode,
                    context_schema=storage_type.context_schema,
                    field_definitions=storage_type.field_definitions,
                    icon=storage_type.icon,
                    is_system=False,
                    organization_id=user.organization_id,
                    created_by=user.id,
                    default_settings=storage_type.default_settings,
                )
                db.add(new_storage_type)
                await db.flush()

                await db.execute(
                    update(StorageLocation)
                    .where(
                        StorageLocation.organization_id == user.organization_id,
                        StorageLocation.storage_type_id == storage_type.id,
                    )
                    .values(storage_type_id=new_storage_type.id)
                )
                storage_type = new_storage_type

        if storage_type.organization_id != user.organization_id:
            raise PermissionError(get_error_message('storage_type_no_access', lang))

        update_data = storage_type_in.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            if hasattr(storage_type, field):
                setattr(storage_type, field, value)
        await db.flush()
        await db.refresh(storage_type)
        return storage_type

    @staticmethod
    async def delete_storage_type_async(
        db: AsyncSession,
        storage_type: StorageType,
        user: UserContextDTO,
        lang: Language | None = None,
    ) -> None:
        if storage_type.is_system or storage_type.organization_id is None:
            raise PermissionError(get_error_message('storage_type_system_delete', lang))

        if storage_type.organization_id != user.organization_id:
            raise PermissionError(get_error_message('storage_type_no_access', lang))

        usage_count = await db.scalar(
            select(func.count())
            .select_from(StorageLocation)
            .where(
                StorageLocation.storage_type_id == storage_type.id,
                StorageLocation.organization_id == user.organization_id,
            )
        )

        if (usage_count or 0) > 0:
            raise ServiceRejectionError('storage_type_in_use', count=usage_count)

        await db.delete(storage_type)
        await db.flush()
