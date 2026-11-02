"""Integration tests for the core_api.templates facade."""

import pytest

from app.core import template_models  # noqa: F401 — register table in metadata
from app.core.exceptions import NotFoundException
from app.core.public_api import core_api
from app.core.template_schemas import DocumentTemplateSchema


@pytest.mark.integration
class TestCoreTemplatesAPI:
    async def test_create_list_get_roundtrip(
        self, real_async_db_session, async_test_user, async_test_household
    ):
        created = await core_api.templates.create_async(
            db=real_async_db_session,
            organization_id=async_test_household.id,
            module='warehouse',
            user_id=async_test_user.id,
            name='Facade Template',
            body_html='<h1>Hello</h1>',
            document_type='STANDARD',
        )
        assert isinstance(created, DocumentTemplateSchema)
        assert created.name == 'Facade Template'

        listed = await core_api.templates.list_async(
            real_async_db_session, async_test_household.id, module='warehouse'
        )
        assert [t.id for t in listed] == [created.id]

        fetched = await core_api.templates.get_async(
            real_async_db_session, async_test_household.id, created.id, 'warehouse'
        )
        assert fetched is not None
        assert fetched.body_html == '<h1>Hello</h1>'

    async def test_get_scoped_by_module(
        self, real_async_db_session, async_test_user, async_test_household
    ):
        created = await core_api.templates.create_async(
            db=real_async_db_session,
            organization_id=async_test_household.id,
            module='warehouse',
            user_id=async_test_user.id,
            name='Scoped',
            body_html='<p>x</p>',
        )
        wrong_module = await core_api.templates.get_async(
            real_async_db_session,
            async_test_household.id,
            created.id,
            'purchase_orders',
        )
        assert wrong_module is None

    async def test_update_and_delete(
        self, real_async_db_session, async_test_user, async_test_household
    ):
        created = await core_api.templates.create_async(
            db=real_async_db_session,
            organization_id=async_test_household.id,
            module='warehouse',
            user_id=async_test_user.id,
            name='To Update',
            body_html='<p>old</p>',
        )
        updated = await core_api.templates.update_async(
            db=real_async_db_session,
            organization_id=async_test_household.id,
            template_id=created.id,
            module='warehouse',
            name='Updated',
        )
        assert updated.name == 'Updated'

        await core_api.templates.delete_async(
            real_async_db_session, async_test_household.id, created.id, 'warehouse'
        )
        assert (
            await core_api.templates.get_async(
                real_async_db_session, async_test_household.id, created.id, 'warehouse'
            )
            is None
        )

    async def test_update_missing_raises_not_found(
        self, real_async_db_session, async_test_household
    ):
        import uuid

        with pytest.raises(NotFoundException):
            await core_api.templates.update_async(
                db=real_async_db_session,
                organization_id=async_test_household.id,
                template_id=uuid.uuid4(),
                module='warehouse',
                name='nope',
            )

    async def test_seed_defaults_idempotent(
        self, real_async_db_session, async_test_user, async_test_household
    ):
        built_ins = [('Standard Template', 'STANDARD', '<h1>std</h1>')]
        first = await core_api.templates.seed_defaults_async(
            db=real_async_db_session,
            organization_id=async_test_household.id,
            module='warehouse',
            user_id=async_test_user.id,
            built_ins=built_ins,
        )
        second = await core_api.templates.seed_defaults_async(
            db=real_async_db_session,
            organization_id=async_test_household.id,
            module='warehouse',
            user_id=async_test_user.id,
            built_ins=built_ins,
        )
        assert len(first) == 1
        assert second == []
