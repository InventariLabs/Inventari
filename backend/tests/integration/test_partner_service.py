import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.organization import Organization
from app.models.user import User
from app.schemas.partner import PartnerCreate, PartnerUpdate
from app.services import partner_service


def _make_create(
    name: str = 'Acme Corp',
    type_: str = 'SUPPLIER',
    code: str | None = None,
    **kwargs,
) -> PartnerCreate:
    return PartnerCreate(name=name, type=type_, code=code, **kwargs)


@pytest.mark.integration
class TestPartnerCreate:
    @pytest.mark.asyncio
    async def test_create_partner_returns_partner_with_correct_fields(
        self,
        real_async_db_session: AsyncSession,
        async_test_user: User,
        async_test_household: Organization,
    ):
        data = _make_create()
        partner = await partner_service.create_async(
            real_async_db_session, async_test_household.id, data, async_test_user.id
        )
        assert partner.id is not None
        assert partner.name == 'Acme Corp'
        assert partner.type == 'SUPPLIER'
        assert partner.organization_id == async_test_household.id
        assert partner.created_by == async_test_user.id
        assert partner.is_active is True

    @pytest.mark.asyncio
    async def test_create_partner_with_code(
        self,
        real_async_db_session: AsyncSession,
        async_test_user: User,
        async_test_household: Organization,
    ):
        data = _make_create(code='ACME-001')
        partner = await partner_service.create_async(
            real_async_db_session, async_test_household.id, data, async_test_user.id
        )
        assert partner.code == 'ACME-001'

    @pytest.mark.asyncio
    async def test_create_duplicate_name_type_raises_value_error(
        self,
        real_async_db_session: AsyncSession,
        async_test_user: User,
        async_test_household: Organization,
    ):
        data = _make_create()
        await partner_service.create_async(
            real_async_db_session, async_test_household.id, data, async_test_user.id
        )
        with pytest.raises(ValueError, match='Partner with name'):
            await partner_service.create_async(
                real_async_db_session,
                async_test_household.id,
                data,
                async_test_user.id,
            )

    @pytest.mark.asyncio
    async def test_create_duplicate_code_raises_value_error(
        self,
        real_async_db_session: AsyncSession,
        async_test_user: User,
        async_test_household: Organization,
    ):
        data1 = _make_create(name='First', code='SAME-CODE')
        await partner_service.create_async(
            real_async_db_session, async_test_household.id, data1, async_test_user.id
        )
        data2 = _make_create(name='Second', type_='CUSTOMER', code='SAME-CODE')
        with pytest.raises(ValueError, match='Partner with code'):
            await partner_service.create_async(
                real_async_db_session,
                async_test_household.id,
                data2,
                async_test_user.id,
            )


@pytest.mark.integration
class TestPartnerGet:
    @pytest.mark.asyncio
    async def test_get_respects_org_isolation(
        self,
        real_async_db_session: AsyncSession,
        async_test_user: User,
        async_test_household: Organization,
    ):
        data = _make_create()
        created = await partner_service.create_async(
            real_async_db_session, async_test_household.id, data, async_test_user.id
        )
        other_org_id = uuid.uuid4()
        result = await partner_service.get_async(
            real_async_db_session, other_org_id, created.id
        )
        assert result is None


async def _seed_partners_async(db: AsyncSession, org_id, user_id):
    """Helper to seed partners via async service for tests."""
    partners = []
    for name, type_, code in [
        ('Alpha Supplier', 'SUPPLIER', 'ALPHA'),
        ('Beta Customer', 'CUSTOMER', 'BETA'),
        ('Gamma Supplier', 'SUPPLIER', 'GAMMA'),
    ]:
        p = await partner_service.create_async(
            db,
            org_id,
            _make_create(name=name, type_=type_, code=code),
            user_id,
        )
        partners.append(p)
    return partners


@pytest.mark.integration
class TestPartnerList:
    @pytest.mark.asyncio
    async def test_list_search_by_code(
        self,
        real_async_db_session: AsyncSession,
        async_test_user: User,
        async_test_household: Organization,
    ):
        await _seed_partners_async(
            real_async_db_session, async_test_household.id, async_test_user.id
        )
        partners, total = await partner_service.list_partners_async(
            real_async_db_session,
            async_test_household.id,
            search='GAMMA',
            is_active=None,
        )
        assert total == 1
        assert partners[0].code == 'GAMMA'

    @pytest.mark.asyncio
    async def test_list_sort_order_desc(
        self,
        real_async_db_session: AsyncSession,
        async_test_user: User,
        async_test_household: Organization,
    ):
        await _seed_partners_async(
            real_async_db_session, async_test_household.id, async_test_user.id
        )
        partners, _ = await partner_service.list_partners_async(
            real_async_db_session,
            async_test_household.id,
            sort_by='name',
            sort_order='desc',
            is_active=None,
        )
        names = [p.name for p in partners]
        assert names == sorted(names, reverse=True)

    @pytest.mark.asyncio
    async def test_list_attaches_document_stats(
        self,
        real_async_db_session: AsyncSession,
        async_test_user: User,
        async_test_household: Organization,
    ):
        from datetime import UTC, datetime
        from decimal import Decimal

        from app.modules.warehouse.models.document import Document

        partner = await partner_service.create_async(
            real_async_db_session,
            async_test_household.id,
            _make_create(name='Docs Partner', type_='SUPPLIER', code='DOCS'),
            async_test_user.id,
        )
        await partner_service.create_async(
            real_async_db_session,
            async_test_household.id,
            _make_create(name='Empty Partner', type_='SUPPLIER', code='EMPTY'),
            async_test_user.id,
        )
        real_async_db_session.add_all(
            [
                Document(
                    organization_id=async_test_household.id,
                    type='IN',
                    number='IN/2026/001',
                    status='COMPLETED',
                    partner_id=partner.id,
                    total_gross=Decimal('120.50'),
                    currency='EUR',
                    created_by=async_test_user.id,
                    created_at=datetime(2026, 7, 1, tzinfo=UTC),
                ),
                Document(
                    organization_id=async_test_household.id,
                    type='OUT',
                    number='OUT/2026/002',
                    status='DRAFT',
                    partner_id=partner.id,
                    total_gross=Decimal('999.00'),
                    created_by=async_test_user.id,
                    created_at=datetime(2026, 7, 2, tzinfo=UTC),
                ),
            ]
        )
        await real_async_db_session.flush()

        partners, _ = await partner_service.list_partners_async(
            real_async_db_session,
            async_test_household.id,
            search='Partner',
            is_active=None,
        )
        by_name = {p.name: p for p in partners}
        stats = by_name['Docs Partner']
        empty = by_name['Empty Partner']
        # DRAFT is excluded from every stat: the COMPLETED document is the only
        # non-draft one, so it drives both the count and the last-activity date.
        assert stats.document_count == 1
        assert stats.total_amount == Decimal('120.50')
        assert stats.turnover_currency == 'EUR'
        assert stats.last_activity_at == datetime(2026, 7, 1, tzinfo=UTC)
        assert empty.document_count == 0
        assert empty.total_amount is None
        assert empty.turnover_currency is None
        assert empty.last_activity_at is None

    @pytest.mark.asyncio
    async def test_documents_without_value_are_no_turnover_not_mixed_currencies(
        self,
        real_async_db_session: AsyncSession,
        async_test_user: User,
        async_test_household: Organization,
    ):
        from datetime import UTC, datetime
        from decimal import Decimal

        from app.modules.warehouse.models.document import Document

        partner = await partner_service.create_async(
            real_async_db_session,
            async_test_household.id,
            _make_create(name='No Value', type_='CUSTOMER', code='NOVAL'),
            async_test_user.id,
        )
        real_async_db_session.add(
            Document(
                organization_id=async_test_household.id,
                type='OUT',
                number='OUT/2026/NV1',
                status='COMPLETED',
                partner_id=partner.id,
                total_gross=None,
                created_by=async_test_user.id,
                created_at=datetime(2026, 7, 1, tzinfo=UTC),
            )
        )
        await real_async_db_session.flush()

        partners, _ = await partner_service.list_partners_async(
            real_async_db_session,
            async_test_household.id,
            search='No Value',
            is_active=None,
        )
        stats = partners[0]
        assert stats.document_count == 1
        # A document without a value contributes nothing: the turnover is zero,
        # not "unknown" — None is reserved for a sum that mixes currencies.
        assert stats.total_amount == Decimal('0')
        assert stats.turnover_currency is None

    @pytest.mark.asyncio
    async def test_list_attaches_purchase_order_count(
        self,
        real_async_db_session: AsyncSession,
        async_test_user: User,
        async_test_household: Organization,
    ):
        from app.modules.purchase_orders.models import PurchaseOrder

        partner = await partner_service.create_async(
            real_async_db_session,
            async_test_household.id,
            _make_create(name='PO Partner', type_='SUPPLIER', code='POSRC'),
            async_test_user.id,
        )
        await partner_service.create_async(
            real_async_db_session,
            async_test_household.id,
            _make_create(name='No PO Partner', type_='SUPPLIER', code='POZERO'),
            async_test_user.id,
        )
        real_async_db_session.add_all(
            [
                PurchaseOrder(
                    organization_id=async_test_household.id,
                    number='PO/2026/001',
                    status='CONFIRMED',
                    partner_id=partner.id,
                    created_by=async_test_user.id,
                ),
                # DRAFT is included on purpose: the sheet link opens the
                # purchase-order list, whose status filter defaults to ALL —
                # unlike document_count, which excludes DRAFT by design.
                PurchaseOrder(
                    organization_id=async_test_household.id,
                    number='PO/2026/002',
                    status='DRAFT',
                    partner_id=partner.id,
                    created_by=async_test_user.id,
                ),
            ]
        )
        await real_async_db_session.flush()

        partners, _ = await partner_service.list_partners_async(
            real_async_db_session,
            async_test_household.id,
            search='PO Partner',
            is_active=None,
        )
        by_name = {p.name: p for p in partners}
        assert by_name['PO Partner'].purchase_order_count == 2
        assert by_name['No PO Partner'].purchase_order_count == 0

    @pytest.mark.asyncio
    async def test_list_turnover_never_mixes_currencies(
        self,
        real_async_db_session: AsyncSession,
        async_test_user: User,
        async_test_household: Organization,
    ):
        from datetime import UTC, datetime
        from decimal import Decimal

        from app.modules.warehouse.models.document import Document

        partner = await partner_service.create_async(
            real_async_db_session,
            async_test_household.id,
            _make_create(name='Multi Currency', type_='SUPPLIER', code='MULTI'),
            async_test_user.id,
        )
        real_async_db_session.add_all(
            [
                Document(
                    organization_id=async_test_household.id,
                    type='IN',
                    number='IN/2026/M1',
                    status='COMPLETED',
                    partner_id=partner.id,
                    total_gross=Decimal('100.00'),
                    currency='EUR',
                    created_by=async_test_user.id,
                    created_at=datetime(2026, 7, 1, tzinfo=UTC),
                ),
                Document(
                    organization_id=async_test_household.id,
                    type='IN',
                    number='IN/2026/M2',
                    status='COMPLETED',
                    partner_id=partner.id,
                    total_gross=Decimal('200.00'),
                    currency='USD',
                    created_by=async_test_user.id,
                    created_at=datetime(2026, 7, 2, tzinfo=UTC),
                ),
            ]
        )
        await real_async_db_session.flush()

        partners, _ = await partner_service.list_partners_async(
            real_async_db_session,
            async_test_household.id,
            search='Multi Currency',
            is_active=None,
        )
        assert len(partners) == 1
        stats = partners[0]
        assert stats.document_count == 2
        # Two currencies → no single number; never sum EUR + USD.
        assert stats.total_amount is None
        assert stats.turnover_currency is None
        assert stats.last_activity_at == datetime(2026, 7, 2, tzinfo=UTC)

    @pytest.mark.asyncio
    @pytest.mark.asyncio
    async def test_list_search_by_contact(
        self,
        real_async_db_session: AsyncSession,
        async_test_user: User,
        async_test_household: Organization,
    ):
        await partner_service.create_async(
            real_async_db_session,
            async_test_household.id,
            PartnerCreate(
                name='Contact Co', type='SUPPLIER', contact_person='John Doe'
            ),
            async_test_user.id,
        )
        partners, total = await partner_service.list_partners_async(
            real_async_db_session,
            async_test_household.id,
            search='John',
            is_active=None,
        )
        assert total == 1

    @pytest.mark.asyncio
    async def test_list_search_by_email(
        self,
        real_async_db_session: AsyncSession,
        async_test_user: User,
        async_test_household: Organization,
    ):
        await partner_service.create_async(
            real_async_db_session,
            async_test_household.id,
            PartnerCreate(name='Email Co', type='SUPPLIER', email='test@co.com'),
            async_test_user.id,
        )
        partners, total = await partner_service.list_partners_async(
            real_async_db_session,
            async_test_household.id,
            search='test@co',
            is_active=None,
        )
        assert total == 1

    @pytest.mark.asyncio
    async def test_list_sort_by_type(
        self,
        real_async_db_session: AsyncSession,
        async_test_user: User,
        async_test_household: Organization,
    ):
        await _seed_partners_async(
            real_async_db_session, async_test_household.id, async_test_user.id
        )
        partners, _ = await partner_service.list_partners_async(
            real_async_db_session,
            async_test_household.id,
            sort_by='type',
            sort_order='asc',
            is_active=None,
        )
        types = [p.type for p in partners]
        assert types == sorted(types)


@pytest.mark.integration
class TestPartnerUpdate:
    @pytest.mark.asyncio
    async def test_update_noop_returns_partner(
        self,
        real_async_db_session: AsyncSession,
        async_test_user: User,
        async_test_household: Organization,
    ):
        created = await partner_service.create_async(
            real_async_db_session,
            async_test_household.id,
            _make_create(),
            async_test_user.id,
        )
        updated = await partner_service.update_async(
            real_async_db_session,
            async_test_household.id,
            created.id,
            PartnerUpdate(),
        )
        assert updated is not None
        assert updated.id == created.id
        assert updated.name == created.name

    @pytest.mark.asyncio
    async def test_update_name_to_duplicate_raises_value_error(
        self,
        real_async_db_session: AsyncSession,
        async_test_user: User,
        async_test_household: Organization,
    ):
        await partner_service.create_async(
            real_async_db_session,
            async_test_household.id,
            _make_create(name='First'),
            async_test_user.id,
        )
        second = await partner_service.create_async(
            real_async_db_session,
            async_test_household.id,
            _make_create(name='Second'),
            async_test_user.id,
        )
        with pytest.raises(ValueError, match='Partner with name'):
            await partner_service.update_async(
                real_async_db_session,
                async_test_household.id,
                second.id,
                PartnerUpdate(name='First'),
            )

    @pytest.mark.asyncio
    async def test_update_code_to_duplicate_raises_value_error(
        self,
        real_async_db_session: AsyncSession,
        async_test_user: User,
        async_test_household: Organization,
    ):
        await partner_service.create_async(
            real_async_db_session,
            async_test_household.id,
            _make_create(name='First', code='CODE-A'),
            async_test_user.id,
        )
        second = await partner_service.create_async(
            real_async_db_session,
            async_test_household.id,
            _make_create(name='Second', code='CODE-B'),
            async_test_user.id,
        )
        with pytest.raises(ValueError, match='Partner with code'):
            await partner_service.update_async(
                real_async_db_session,
                async_test_household.id,
                second.id,
                PartnerUpdate(code='CODE-A'),
            )

    @pytest.mark.asyncio
    async def test_update_type_change_triggers_uniqueness_check(
        self,
        real_async_db_session: AsyncSession,
        async_test_user: User,
        async_test_household: Organization,
    ):
        await partner_service.create_async(
            real_async_db_session,
            async_test_household.id,
            _make_create(name='Same', type_='SUPPLIER'),
            async_test_user.id,
        )
        p2 = await partner_service.create_async(
            real_async_db_session,
            async_test_household.id,
            _make_create(name='Same', type_='CUSTOMER'),
            async_test_user.id,
        )
        with pytest.raises(ValueError, match='Partner with name'):
            await partner_service.update_async(
                real_async_db_session,
                async_test_household.id,
                p2.id,
                PartnerUpdate(type='SUPPLIER'),
            )

    @pytest.mark.asyncio
    async def test_update_code_no_change_does_not_trigger_check(
        self,
        real_async_db_session: AsyncSession,
        async_test_user: User,
        async_test_household: Organization,
    ):
        created = await partner_service.create_async(
            real_async_db_session,
            async_test_household.id,
            _make_create(code='KEEP-ME'),
            async_test_user.id,
        )
        updated = await partner_service.update_async(
            real_async_db_session,
            async_test_household.id,
            created.id,
            PartnerUpdate(notes='just notes'),
        )
        assert updated is not None
        assert updated.code == 'KEEP-ME'


@pytest.mark.integration
class TestPartnerActivate:
    @pytest.mark.asyncio
    async def test_activate_nonexistent_returns_none(
        self,
        real_async_db_session: AsyncSession,
        async_test_household: Organization,
    ):
        result = await partner_service.activate_async(
            real_async_db_session, async_test_household.id, uuid.uuid4()
        )
        assert result is None


@pytest.mark.integration
class TestPartnerDelete:
    @pytest.mark.asyncio
    async def test_delete_partner_nonexistent_returns_false(
        self,
        real_async_db_session: AsyncSession,
        async_test_household: Organization,
    ):
        result = await partner_service.delete_async(
            real_async_db_session, async_test_household.id, uuid.uuid4()
        )
        assert result is False

    @pytest.mark.asyncio
    async def test_delete_blocked_when_open_purchase_order_exists(
        self,
        real_async_db_session: AsyncSession,
        async_test_user: User,
        async_test_household: Organization,
    ):
        """PA-1: partner deletion must be blocked when open POs reference it."""
        from app.modules.purchase_orders.models import PurchaseOrder

        created = await partner_service.create_async(
            real_async_db_session,
            async_test_household.id,
            _make_create(),
            async_test_user.id,
        )
        po = PurchaseOrder(
            organization_id=async_test_household.id,
            number='PO/2026/9999',
            status='CONFIRMED',
            partner_id=created.id,
            currency='PLN',
            created_by=async_test_user.id,
        )
        real_async_db_session.add(po)
        await real_async_db_session.flush()

        with pytest.raises(ValueError, match='open purchase order'):
            await partner_service.delete_async(
                real_async_db_session, async_test_household.id, created.id
            )

    @pytest.mark.asyncio
    async def test_delete_allowed_when_po_completed_or_cancelled(
        self,
        real_async_db_session: AsyncSession,
        async_test_user: User,
        async_test_household: Organization,
    ):
        """PA-1: COMPLETED and CANCELLED POs do not block deletion."""
        from app.modules.purchase_orders.models import PurchaseOrder

        created = await partner_service.create_async(
            real_async_db_session,
            async_test_household.id,
            _make_create(),
            async_test_user.id,
        )
        for status, num in [
            ('COMPLETED', 'PO/2026/C001'),
            ('CANCELLED', 'PO/2026/C002'),
        ]:
            real_async_db_session.add(
                PurchaseOrder(
                    organization_id=async_test_household.id,
                    number=num,
                    status=status,
                    partner_id=created.id,
                    currency='PLN',
                    created_by=async_test_user.id,
                )
            )
        await real_async_db_session.flush()

        result = await partner_service.delete_async(
            real_async_db_session, async_test_household.id, created.id
        )
        assert result is True
