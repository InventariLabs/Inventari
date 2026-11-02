"""Shared test helper for module integration tests.

Provides reusable fixtures that replace the duplicated org→user→auth→storage_type→location
chain found in every module conftest. Modules with unique needs can extend this with their
own fixtures (categories with field_definitions, items with meta_data, documents with lines, etc.).
"""

import re
import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import DeclarativeBase, Mapped, ORMExecuteState, Session

from app.i18n import Language
from app.i18n.service import get_error_message
from app.models.organization import Organization
from app.models.partner import Partner
from app.models.product_template import ProductTemplate
from app.models.stock_quants_from_records import stock_quants_from_records
from app.models.storage_location import StorageLocation
from app.models.storage_type import StorageType
from app.models.uom import Uom
from app.models.user import User
from app.services.auth_service import get_password_hash
from app.services.token_service import create_access_token


def seed_org_storage_types(db: Session, organization_id: Any) -> None:
    """Give *organization_id* the neutral and food storage types.

    Storage types have an owner since, so a test that builds an
       ``Organization`` by hand has to seed them the way org creation does in
       production. The suite was written against the food vertical, so both sets
       are seeded — the rows the session snapshot used to hold globally.
    """
    from app.seed_profiles._food_home_storage_types import seed_food_storage_types
    from app.seed_profiles.base import seed_neutral_storage_types

    seed_neutral_storage_types(db, organization_id=organization_id, commit=False)
    seed_food_storage_types(db, organization_id=organization_id, commit=False)
    db.flush()


class ModuleTestHelper:
    def __init__(self, db: Session):
        self.db = db

    def create_org(self, name: str, enabled_modules: list[str]) -> Organization:
        """Create an organization with the neutral storage types it owns.

        Storage types belong to a tenant since, so an organization
               without them has no SYSTEM type and cannot book consumption.
        """
        from app.seed_profiles.base import seed_neutral_storage_types

        org = Organization(name=name, enabled_modules=enabled_modules)
        self.db.add(org)
        self.db.flush()
        seed_neutral_storage_types(self.db, organization_id=org.id, commit=False)
        self.db.commit()
        self.db.refresh(org)
        return org

    def set_module_settings(
        self, org: Organization, module_name: str, values: dict[str, Any]
    ) -> None:
        """Write a module's organization settings (same namespace as CoreAPI).

        For tests that need a module configured differently from its default —
        e.g. a single-user organization allowing admins to approve their own
        requests.
        """
        settings = dict(org.settings or {})
        namespace = f'module:{module_name}'
        settings[namespace] = {**settings.get(namespace, {}), **values}
        org.settings = settings
        self.db.add(org)
        self.db.commit()
        self.db.refresh(org)

    def create_user(
        self, org: Organization, *, email: str, role: str = 'admin'
    ) -> User:
        user = User(
            email=email,
            hashed_password=get_password_hash('testpassword123'),
            full_name=email.split('@')[0].title(),
            organization_id=org.id,
            role=role,
            is_active=True,
        )
        self.db.add(user)
        self.db.commit()
        self.db.refresh(user)
        return user

    @staticmethod
    async def create_user_async(
        db: AsyncSession,
        org: Organization,
        *,
        email: str,
        role: str = 'admin',
    ) -> User:
        """Async variant of ``create_user`` — for tests using the async session.

        Uses the same password hashing as the sync variant (not a bare 'x'),
        so users created here authenticate like production users.
        """
        user = User(
            email=email,
            hashed_password=get_password_hash('testpassword123'),
            full_name=email.split('@')[0].title(),
            organization_id=org.id,
            role=role,
            is_active=True,
        )
        db.add(user)
        await db.flush()
        await db.refresh(user)
        return user

    def grant_permissions(self, user: User, permissions: list[str]) -> None:
        """Give *user* a role in their own organization carrying *permissions*.

               Module permissions (``approvals:approve`` and friends) are enforced
        since, and a legacy ``User.role`` string no longer implies them.
               Tests that exercise a guarded endpoint as a non-admin need an actual
               grant, which is also what the product does — ``default_roles`` in the
               manifest assigns these at module enable.
        """
        from app.models.role import Role, UserRole

        role = Role(
            name=f'test_grant_{user.email.split("@")[0]}',
            permissions=permissions,
            is_system=False,
            organization_id=user.organization_id,
        )
        self.db.add(role)
        self.db.flush()
        self.db.add(UserRole(user_id=user.id, role_id=role.id))
        self.db.commit()

    def get_auth_headers(self, user: User) -> dict[str, str]:
        access_token = create_access_token(data={'sub': str(user.id)})
        return {'Authorization': f'Bearer {access_token}'}

    def create_storage_type(
        self,
        name: str,
        type_code: str,
        behavior_mode: str = 'NONE',
        icon: str | None = None,
        organization_id: Any | None = None,
    ) -> StorageType:
        st = StorageType(
            name=name,
            type_code=type_code,
            behavior_mode=behavior_mode,
            icon=icon,
            organization_id=organization_id,
        )
        self.db.add(st)
        self.db.commit()
        self.db.refresh(st)
        return st

    def create_storage_location(
        self,
        org: Organization,
        storage_type: StorageType,
        user: User,
        *,
        name: str,
        description: str | None = None,
    ) -> StorageLocation:
        location = StorageLocation(
            name=name,
            organization_id=org.id,
            storage_type_id=storage_type.id,
            created_by=user.id,
            description=description,
        )
        self.db.add(location)
        self.db.commit()
        self.db.refresh(location)
        return location

    def create_partner(
        self,
        org: Organization,
        user: User,
        *,
        name: str,
        type: str = 'SUPPLIER',
        email: str | None = None,
    ) -> Partner:
        partner = Partner(
            name=name,
            type=type,
            organization_id=org.id,
            created_by=user.id,
            email=email,
        )
        self.db.add(partner)
        self.db.commit()
        self.db.refresh(partner)
        return partner

    def create_template(
        self,
        org: Organization,
        *,
        name: str,
        barcode: str | None = None,
        sku: str | None = None,
        uom_id: uuid.UUID | str | None = None,
    ) -> ProductTemplate:
        template = ProductTemplate(
            name=name,
            organization_id=org.id,
            barcode=barcode,
            sku=sku,
            uom_id=uom_id,
        )
        self.db.add(template)
        self.db.commit()
        self.db.refresh(template)
        return template

    def get_uom(self, symbol: str) -> Uom:
        return self.db.scalars(select(Uom).where(Uom.symbol == symbol)).one()


def error_message_pattern(key: str, *, lang: Language = 'en', **params: Any) -> str:
    """The catalogue sentence for *key*, escaped for ``pytest.raises(match=)``.

    Services raise translated messages, so a test that spells the sentence out
    breaks whenever a translator improves the wording — and passes while
    asserting nothing if the sentence changes meaning. Matching the catalogue
    keeps the assertion on *which rule fired*.

    ``params`` fills the message's placeholders before escaping, so a test can
    pin the interpolated values too.
    """
    return re.escape(get_error_message(key, lang, **params))


class _ShelfRowBase(DeclarativeBase):
    """A registry of its own: a view is not a table ``create_all`` may build."""


class ShelfRow(_ShelfRowBase):
    """A group of stock as the records hold it — what a test used to read off a quant.

    Mapped onto ``stock_quants_from_records``, restricted to the groups that
    stand on a shelf (the quant table never held any other), so it reads the
    way the quant it replaces did: the same columns, the group's reservation
    rows as ``reserved_quantity``, and ``available_quantity`` beside them.
    Nothing can be written through it; stock is put on a shelf through the
    records (``tests/integration/_shelf.py``).

    Every select of it is read fresh: the numbers are sums over other tables,
    and a row the session kept from an earlier read would still say what the
    records said then (:func:`_read_shelf_rows_fresh`).
    """

    __table__ = (
        select(stock_quants_from_records)
        .where(stock_quants_from_records.c.storage_location_id.is_not(None))
        .subquery('shelf_rows')
    )
    __mapper_args__ = {'primary_key': [__table__.c.id]}

    id: Mapped[uuid.UUID]
    organization_id: Mapped[uuid.UUID]
    product_template_id: Mapped[uuid.UUID]
    storage_location_id: Mapped[uuid.UUID]
    lot_id: Mapped[uuid.UUID | None]
    owner_id: Mapped[uuid.UUID | None]
    quantity: Mapped[Decimal]
    reserved_quantity: Mapped[Decimal]

    @property
    def available_quantity(self) -> Decimal:
        return self.quantity - self.reserved_quantity


@event.listens_for(Session, 'do_orm_execute')
def _read_shelf_rows_fresh(state: ORMExecuteState) -> None:
    """Overwrite a kept :class:`ShelfRow` with what the view says now."""
    if state.is_select and any(
        mapper.class_ is ShelfRow for mapper in state.all_mappers
    ):
        state.update_execution_options(populate_existing=True)
