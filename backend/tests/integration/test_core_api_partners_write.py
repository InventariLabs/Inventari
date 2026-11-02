"""Integration tests for CorePartnersAPI write methods."""

from __future__ import annotations

from uuid import uuid4

import pytest

from app.core.contracts import PartnerCreateDTO, PartnerUpdateDTO
from app.core.public_api import core_api

from ._core_api_helpers import make_other_org, make_user_context, run_async


@pytest.mark.integration
class TestCoreAPIPartnersCreate:
    """`create` returns PartnerDTO; enforces uniqueness and validation."""

    def test_create_partner_success(
        self, db_session, test_household, test_user, async_engine_fixture
    ):
        from app.database import async_sessionmaker

        ctx = make_user_context(test_household.id, test_user.id)

        async def _create():
            maker = async_sessionmaker(
                bind=async_engine_fixture, expire_on_commit=False
            )
            async with maker() as session:
                return await core_api.partners.create_async(
                    session,
                    test_household.id,
                    PartnerCreateDTO(
                        name='ACME Corp', type='CUSTOMER', email='info@acme.com'
                    ),
                    ctx,
                )

        result = run_async(_create())
        assert result.name == 'ACME Corp'
        assert result.type == 'CUSTOMER'
        assert result.is_active is True
        assert result.id is not None

    def test_create_partner_normalizes_website(
        self, db_session, test_household, test_user, async_engine_fixture
    ):
        """Website without scheme gets https:// prepended (parity with REST API)."""
        from app.database import async_sessionmaker

        ctx = make_user_context(test_household.id, test_user.id)

        async def _create():
            maker = async_sessionmaker(
                bind=async_engine_fixture, expire_on_commit=False
            )
            async with maker() as session:
                return await core_api.partners.create_async(
                    session,
                    test_household.id,
                    PartnerCreateDTO(
                        name='Web Corp', type='CUSTOMER', website='example.com'
                    ),
                    ctx,
                )

        result = run_async(_create())
        assert result.website == 'https://example.com'

    def test_create_partner_duplicate_name_type_raises(
        self, db_session, test_household, test_user, async_engine_fixture
    ):
        from app.database import async_sessionmaker

        ctx = make_user_context(test_household.id, test_user.id)
        data = PartnerCreateDTO(name='Dup Corp', type='SUPPLIER')

        async def _create():
            maker = async_sessionmaker(
                bind=async_engine_fixture, expire_on_commit=False
            )
            async with maker() as session:
                await core_api.partners.create_async(
                    session, test_household.id, data, ctx
                )
                await session.commit()

        run_async(_create())

        async def _create_again():
            maker = async_sessionmaker(
                bind=async_engine_fixture, expire_on_commit=False
            )
            async with maker() as session:
                await core_api.partners.create_async(
                    session, test_household.id, data, ctx
                )

        with pytest.raises(ValueError, match='already exists'):
            run_async(_create_again())

    def test_create_partner_duplicate_code_raises(
        self, db_session, test_household, test_user, async_engine_fixture
    ):
        """Duplicate code within same org raises ValueError."""
        from app.database import async_sessionmaker

        ctx = make_user_context(test_household.id, test_user.id)

        async def _create_first():
            maker = async_sessionmaker(
                bind=async_engine_fixture, expire_on_commit=False
            )
            async with maker() as session:
                await core_api.partners.create_async(
                    session,
                    test_household.id,
                    PartnerCreateDTO(name='Alpha', type='CUSTOMER', code='C-001'),
                    ctx,
                )
                await session.commit()

        run_async(_create_first())

        async def _create_second():
            maker = async_sessionmaker(
                bind=async_engine_fixture, expire_on_commit=False
            )
            async with maker() as session:
                await core_api.partners.create_async(
                    session,
                    test_household.id,
                    PartnerCreateDTO(name='Beta', type='SUPPLIER', code='C-001'),
                    ctx,
                )

        with pytest.raises(ValueError, match='code'):
            run_async(_create_second())

    def test_create_partner_org_isolation(
        self, db_session, test_household, test_user, async_engine_fixture
    ):
        """Partner created in org A is not visible in org B."""
        from app.database import async_sessionmaker

        other_org = make_other_org(db_session)
        ctx = make_user_context(test_household.id, test_user.id)

        async def _create_and_check():
            maker = async_sessionmaker(
                bind=async_engine_fixture, expire_on_commit=False
            )
            async with maker() as session:
                created = await core_api.partners.create_async(
                    session,
                    test_household.id,
                    PartnerCreateDTO(name='Isolated Corp', type='CUSTOMER'),
                    ctx,
                )
                await session.commit()
                # Should not be findable in org B
                result = await core_api.partners.get_async(
                    session, other_org.id, created.id
                )
                return result

        result = run_async(_create_and_check())
        assert result is None

    def test_create_partner_validates_type(self):
        """Invalid type is rejected at DTO level."""
        with pytest.raises(ValueError, match='partner type is not recognized'):
            PartnerCreateDTO(name='X', type='INVALID')


@pytest.mark.integration
class TestCoreAPIPartnersUpdate:
    """`update` returns PartnerDTO or None; partial updates supported."""

    def test_update_partner_success(
        self, db_session, test_household, test_user, async_engine_fixture
    ):
        from app.database import async_sessionmaker

        ctx = make_user_context(test_household.id, test_user.id)

        async def _create_and_update():
            maker = async_sessionmaker(
                bind=async_engine_fixture, expire_on_commit=False
            )
            async with maker() as session:
                partner = await core_api.partners.create_async(
                    session,
                    test_household.id,
                    PartnerCreateDTO(name='Update Corp', type='CUSTOMER'),
                    ctx,
                )
                await session.commit()
                updated = await core_api.partners.update_async(
                    session,
                    test_household.id,
                    partner.id,
                    PartnerUpdateDTO(email='new@acme.com'),
                )
                return partner, updated

        original, result = run_async(_create_and_update())
        assert result.email == 'new@acme.com'
        assert result.name == original.name  # unchanged

    def test_update_partner_not_found_returns_none(
        self, db_session, test_household, async_engine_fixture
    ):
        from app.database import async_sessionmaker

        async def _update():
            maker = async_sessionmaker(
                bind=async_engine_fixture, expire_on_commit=False
            )
            async with maker() as session:
                return await core_api.partners.update_async(
                    session,
                    test_household.id,
                    uuid4(),
                    PartnerUpdateDTO(name='Ghost'),
                )

        result = run_async(_update())
        assert result is None

    def test_update_partner_code_conflict_raises(
        self, db_session, test_household, test_user, async_engine_fixture
    ):
        """Updating code to one already used by another partner raises ValueError."""
        from app.database import async_sessionmaker

        ctx = make_user_context(test_household.id, test_user.id)

        async def _setup_and_conflict():
            maker = async_sessionmaker(
                bind=async_engine_fixture, expire_on_commit=False
            )
            async with maker() as session:
                await core_api.partners.create_async(
                    session,
                    test_household.id,
                    PartnerCreateDTO(name='First', type='CUSTOMER', code='CODE-A'),
                    ctx,
                )
                p2 = await core_api.partners.create_async(
                    session,
                    test_household.id,
                    PartnerCreateDTO(name='Second', type='CUSTOMER', code='CODE-B'),
                    ctx,
                )
                await session.commit()
                # Try to update p2's code to p1's code
                await core_api.partners.update_async(
                    session,
                    test_household.id,
                    p2.id,
                    PartnerUpdateDTO(code='CODE-A'),
                )

        with pytest.raises(ValueError, match='code'):
            run_async(_setup_and_conflict())


@pytest.mark.integration
class TestCoreAPIPartnersLifecycle:
    """`deactivate` and `activate` round-trip."""

    def test_deactivate_partner_success(
        self, db_session, test_household, test_user, async_engine_fixture
    ):
        from app.database import async_sessionmaker

        ctx = make_user_context(test_household.id, test_user.id)

        async def _create_and_deactivate():
            maker = async_sessionmaker(
                bind=async_engine_fixture, expire_on_commit=False
            )
            async with maker() as session:
                partner = await core_api.partners.create_async(
                    session,
                    test_household.id,
                    PartnerCreateDTO(name='Deactivate Corp', type='SUPPLIER'),
                    ctx,
                )
                await session.commit()
                return await core_api.partners.deactivate_async(
                    session, test_household.id, partner.id
                )

        result = run_async(_create_and_deactivate())
        assert result.is_active is False

    def test_activate_partner_success(
        self, db_session, test_household, test_user, async_engine_fixture
    ):
        from app.database import async_sessionmaker

        ctx = make_user_context(test_household.id, test_user.id)

        async def _create_deactivate_activate():
            maker = async_sessionmaker(
                bind=async_engine_fixture, expire_on_commit=False
            )
            async with maker() as session:
                partner = await core_api.partners.create_async(
                    session,
                    test_household.id,
                    PartnerCreateDTO(name='Reactivate Corp', type='BOTH'),
                    ctx,
                )
                await session.commit()
                await core_api.partners.deactivate_async(
                    session, test_household.id, partner.id
                )
                return await core_api.partners.activate_async(
                    session, test_household.id, partner.id
                )

        result = run_async(_create_deactivate_activate())
        assert result.is_active is True
