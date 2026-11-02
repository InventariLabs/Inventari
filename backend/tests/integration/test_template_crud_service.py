"""Integration tests for template_crud service (DocumentTemplate CRUD)."""

import uuid

import pytest
from sqlalchemy import func, select

from app.core.exceptions import NotFoundException
from app.core.template_models import DocumentTemplate
from app.services.template_crud import (
    create_template_async,
    delete_template_async,
    get_template_async,
    list_templates_async,
    seed_default_templates_async,
    update_template_async,
)
from app.services.template_engine import TemplateEngine


@pytest.mark.integration
class TestCreateTemplate:
    """Tests for create_template_async()."""

    async def test_create_basic_template(
        self, real_async_db_session, async_test_user, async_test_household
    ):
        result = await create_template_async(
            db=real_async_db_session,
            org_id=async_test_household.id,
            module='warehouse',
            user_id=async_test_user.id,
            name='Invoice Template',
            body_html='<h1>Invoice</h1>',
        )

        assert result.id is not None
        assert result.name == 'Invoice Template'
        assert result.organization_id == async_test_household.id
        assert result.module == 'warehouse'
        assert result.document_type == 'DEFAULT'
        assert result.is_default is False
        assert result.created_by == async_test_user.id

    async def test_create_template_with_custom_type(
        self, real_async_db_session, async_test_user, async_test_household
    ):
        result = await create_template_async(
            db=real_async_db_session,
            org_id=async_test_household.id,
            module='equipment',
            user_id=async_test_user.id,
            name='Checkout Slip',
            body_html='<p>Checkout</p>',
            document_type='CHECKOUT',
        )

        assert result.document_type == 'CHECKOUT'

    async def test_create_template_as_default_clears_previous(
        self, real_async_db_session, async_test_user, async_test_household
    ):
        await create_template_async(
            db=real_async_db_session,
            org_id=async_test_household.id,
            module='warehouse',
            user_id=async_test_user.id,
            name='First Default',
            body_html='<p>First</p>',
            is_default=True,
        )

        second = await create_template_async(
            db=real_async_db_session,
            org_id=async_test_household.id,
            module='warehouse',
            user_id=async_test_user.id,
            name='Second Default',
            body_html='<p>Second</p>',
            is_default=True,
        )

        assert second.is_default is True

        result = await real_async_db_session.scalars(
            select(DocumentTemplate).where(
                DocumentTemplate.organization_id == async_test_household.id,
                DocumentTemplate.module == 'warehouse',
                DocumentTemplate.is_default.is_(True),
            )
        )
        defaults = result.all()
        assert len(defaults) == 1
        assert defaults[0].id == second.id

    async def test_create_template_stores_verbatim_render_sanitizes(
        self, real_async_db_session, async_test_user, async_test_household
    ):
        """a template is stored verbatim — a source-level nh3 pass
        reorders HTML around Jinja spans — and the sanitizer runs on the
        rendered output instead (TemplateEngine.render)."""
        result = await create_template_async(
            db=real_async_db_session,
            org_id=async_test_household.id,
            module='warehouse',
            user_id=async_test_user.id,
            name='Sanitize Test',
            body_html='<script>alert("xss")</script><p>Safe</p>',
        )

        assert result.body_html == '<script>alert("xss")</script><p>Safe</p>'

        rendered = TemplateEngine().render(result.body_html, {})
        assert '<script>' not in rendered
        assert '<p>Safe</p>' in rendered


@pytest.mark.integration
class TestListTemplates:
    """Tests for list_templates_async()."""

    async def test_returns_empty_for_new_org(
        self, real_async_db_session, async_test_household
    ):
        result = await list_templates_async(
            real_async_db_session, async_test_household.id, 'warehouse'
        )

        assert result == []

    async def test_returns_templates_for_module(
        self, real_async_db_session, async_test_user, async_test_household
    ):
        await create_template_async(
            db=real_async_db_session,
            org_id=async_test_household.id,
            module='warehouse',
            user_id=async_test_user.id,
            name='T1',
            body_html='<p>T1</p>',
        )
        await create_template_async(
            db=real_async_db_session,
            org_id=async_test_household.id,
            module='equipment',
            user_id=async_test_user.id,
            name='T2',
            body_html='<p>T2</p>',
        )

        result = await list_templates_async(
            real_async_db_session, async_test_household.id, 'warehouse'
        )

        assert len(result) == 1
        assert result[0].name == 'T1'

    async def test_does_not_return_other_org_templates(
        self, real_async_db_session, async_test_user, async_test_household
    ):
        from app.models.organization import Organization

        other_org = Organization(name='Other Org for Template Test')
        real_async_db_session.add(other_org)
        await real_async_db_session.flush()

        await create_template_async(
            db=real_async_db_session,
            org_id=async_test_household.id,
            module='warehouse',
            user_id=async_test_user.id,
            name='My Template',
            body_html='<p>Mine</p>',
        )
        await create_template_async(
            db=real_async_db_session,
            org_id=other_org.id,
            module='warehouse',
            user_id=async_test_user.id,
            name='Other Template',
            body_html='<p>Other</p>',
        )

        result = await list_templates_async(
            real_async_db_session, async_test_household.id, 'warehouse'
        )

        assert len(result) == 1
        assert result[0].name == 'My Template'

    async def test_ordered_by_created_at_desc(
        self, real_async_db_session, async_test_user, async_test_household
    ):
        await create_template_async(
            db=real_async_db_session,
            org_id=async_test_household.id,
            module='warehouse',
            user_id=async_test_user.id,
            name='First',
            body_html='<p>1</p>',
        )
        await create_template_async(
            db=real_async_db_session,
            org_id=async_test_household.id,
            module='warehouse',
            user_id=async_test_user.id,
            name='Second',
            body_html='<p>2</p>',
        )

        result = await list_templates_async(
            real_async_db_session, async_test_household.id, 'warehouse'
        )

        assert result[0].name == 'Second'
        assert result[1].name == 'First'


@pytest.mark.integration
class TestGetTemplate:
    """Tests for get_template_async()."""

    async def test_returns_existing_template(
        self, real_async_db_session, async_test_user, async_test_household
    ):
        created = await create_template_async(
            db=real_async_db_session,
            org_id=async_test_household.id,
            module='warehouse',
            user_id=async_test_user.id,
            name='Fetchable',
            body_html='<p>Fetch</p>',
        )

        result = await get_template_async(
            real_async_db_session, async_test_household.id, created.id, 'warehouse'
        )

        assert result is not None
        assert result.name == 'Fetchable'

    async def test_returns_none_for_nonexistent_id(
        self, real_async_db_session, async_test_household
    ):
        result = await get_template_async(
            real_async_db_session, async_test_household.id, uuid.uuid4(), 'warehouse'
        )

        assert result is None

    async def test_returns_none_for_wrong_module(
        self, real_async_db_session, async_test_user, async_test_household
    ):
        created = await create_template_async(
            db=real_async_db_session,
            org_id=async_test_household.id,
            module='warehouse',
            user_id=async_test_user.id,
            name='Wrong Module',
            body_html='<p>Wrong</p>',
        )

        result = await get_template_async(
            real_async_db_session, async_test_household.id, created.id, 'equipment'
        )

        assert result is None

    async def test_returns_none_for_wrong_org(
        self, real_async_db_session, async_test_user, async_test_household
    ):
        created = await create_template_async(
            db=real_async_db_session,
            org_id=async_test_household.id,
            module='warehouse',
            user_id=async_test_user.id,
            name='Wrong Org',
            body_html='<p>Wrong</p>',
        )

        result = await get_template_async(
            real_async_db_session, uuid.uuid4(), created.id, 'warehouse'
        )

        assert result is None


@pytest.mark.integration
class TestUpdateTemplate:
    """Tests for update_template_async()."""

    async def test_update_name(
        self, real_async_db_session, async_test_user, async_test_household
    ):
        created = await create_template_async(
            db=real_async_db_session,
            org_id=async_test_household.id,
            module='warehouse',
            user_id=async_test_user.id,
            name='Old Name',
            body_html='<p>Content</p>',
        )

        result = await update_template_async(
            db=real_async_db_session,
            org_id=async_test_household.id,
            template_id=created.id,
            module='warehouse',
            name='New Name',
        )

        assert result.name == 'New Name'

    async def test_update_body_html(
        self, real_async_db_session, async_test_user, async_test_household
    ):
        created = await create_template_async(
            db=real_async_db_session,
            org_id=async_test_household.id,
            module='warehouse',
            user_id=async_test_user.id,
            name='Body Update',
            body_html='<p>Old</p>',
        )

        result = await update_template_async(
            db=real_async_db_session,
            org_id=async_test_household.id,
            template_id=created.id,
            module='warehouse',
            body_html='<p>New</p>',
        )

        assert result.body_html == '<p>New</p>'

    async def test_update_set_as_default(
        self, real_async_db_session, async_test_user, async_test_household
    ):
        first = await create_template_async(
            db=real_async_db_session,
            org_id=async_test_household.id,
            module='warehouse',
            user_id=async_test_user.id,
            name='First',
            body_html='<p>1</p>',
            is_default=True,
        )
        second = await create_template_async(
            db=real_async_db_session,
            org_id=async_test_household.id,
            module='warehouse',
            user_id=async_test_user.id,
            name='Second',
            body_html='<p>2</p>',
        )

        result = await update_template_async(
            db=real_async_db_session,
            org_id=async_test_household.id,
            template_id=second.id,
            module='warehouse',
            is_default=True,
        )

        assert result.is_default is True
        await real_async_db_session.refresh(first)
        assert first.is_default is False

    async def test_update_not_found_raises(
        self, real_async_db_session, async_test_household
    ):
        with pytest.raises(NotFoundException):
            await update_template_async(
                db=real_async_db_session,
                org_id=async_test_household.id,
                template_id=uuid.uuid4(),
                module='warehouse',
                name='Ghost',
            )

    async def test_partial_update_preserves_unset_fields(
        self, real_async_db_session, async_test_user, async_test_household
    ):
        created = await create_template_async(
            db=real_async_db_session,
            org_id=async_test_household.id,
            module='warehouse',
            user_id=async_test_user.id,
            name='Partial',
            body_html='<p>Keep me</p>',
            document_type='INVOICE',
        )

        result = await update_template_async(
            db=real_async_db_session,
            org_id=async_test_household.id,
            template_id=created.id,
            module='warehouse',
            name='Updated',
        )

        assert result.name == 'Updated'
        assert result.body_html == '<p>Keep me</p>'
        assert result.document_type == 'INVOICE'


@pytest.mark.integration
class TestDeleteTemplate:
    """Tests for delete_template_async()."""

    async def test_delete_existing_template(
        self, real_async_db_session, async_test_user, async_test_household
    ):
        created = await create_template_async(
            db=real_async_db_session,
            org_id=async_test_household.id,
            module='warehouse',
            user_id=async_test_user.id,
            name='Deletable',
            body_html='<p>Delete me</p>',
        )

        await delete_template_async(
            real_async_db_session, async_test_household.id, created.id, 'warehouse'
        )

        result = await get_template_async(
            real_async_db_session, async_test_household.id, created.id, 'warehouse'
        )
        assert result is None

    async def test_delete_not_found_raises(
        self, real_async_db_session, async_test_household
    ):
        with pytest.raises(NotFoundException):
            await delete_template_async(
                real_async_db_session,
                async_test_household.id,
                uuid.uuid4(),
                'warehouse',
            )


@pytest.mark.integration
class TestSeedDefaultTemplates:
    """Tests for seed_default_templates_async()."""

    async def test_seed_creates_templates(
        self, real_async_db_session, async_test_user, async_test_household
    ):
        built_ins = [
            ('Invoice', 'INVOICE', '<h1>Invoice</h1>'),
            ('Receipt', 'RECEIPT', '<h1>Receipt</h1>'),
        ]

        created = await seed_default_templates_async(
            db=real_async_db_session,
            org_id=async_test_household.id,
            module='warehouse',
            user_id=async_test_user.id,
            built_ins=built_ins,
        )

        assert len(created) == 2
        names = {t.name for t in created}
        assert 'Invoice' in names
        assert 'Receipt' in names

    async def test_seed_marks_first_template_default_when_none_exists(
        self, real_async_db_session, async_test_user, async_test_household
    ):
        built_ins = [('Invoice', 'INVOICE', '<h1>Invoice</h1>')]

        created = await seed_default_templates_async(
            db=real_async_db_session,
            org_id=async_test_household.id,
            module='warehouse',
            user_id=async_test_user.id,
            built_ins=built_ins,
        )

        assert len(created) == 1
        assert created[0].is_default is True

    async def test_seed_keeps_existing_default(
        self, real_async_db_session, async_test_user, async_test_household
    ):
        existing_default = await create_template_async(
            db=real_async_db_session,
            org_id=async_test_household.id,
            module='warehouse',
            user_id=async_test_user.id,
            name='Existing Default',
            body_html='<h1>Default</h1>',
            document_type='INVOICE',
            is_default=True,
        )

        created = await seed_default_templates_async(
            db=real_async_db_session,
            org_id=async_test_household.id,
            module='warehouse',
            user_id=async_test_user.id,
            built_ins=[('Invoice Copy', 'INVOICE', '<h1>Copy</h1>')],
        )

        assert len(created) == 1
        assert created[0].is_default is False

        default_ids = {
            t.id
            for t in await real_async_db_session.scalars(
                select(DocumentTemplate).where(
                    DocumentTemplate.organization_id == async_test_household.id,
                    DocumentTemplate.module == 'warehouse',
                    DocumentTemplate.document_type == 'INVOICE',
                    DocumentTemplate.is_default.is_(True),
                )
            )
        }
        assert default_ids == {existing_default.id}

    async def test_seed_idempotent_skips_existing(
        self, real_async_db_session, async_test_user, async_test_household
    ):
        built_ins = [
            ('Invoice', 'INVOICE', '<h1>Invoice</h1>'),
            ('Receipt', 'RECEIPT', '<h1>Receipt</h1>'),
        ]

        await seed_default_templates_async(
            db=real_async_db_session,
            org_id=async_test_household.id,
            module='warehouse',
            user_id=async_test_user.id,
            built_ins=built_ins,
        )

        created = await seed_default_templates_async(
            db=real_async_db_session,
            org_id=async_test_household.id,
            module='warehouse',
            user_id=async_test_user.id,
            built_ins=built_ins,
        )

        assert len(created) == 0

        total = await real_async_db_session.scalar(
            select(func.count(DocumentTemplate.id)).where(
                DocumentTemplate.organization_id == async_test_household.id,
                DocumentTemplate.module == 'warehouse',
            )
        )
        assert total == 2

    async def test_seed_returns_empty_for_empty_list(
        self, real_async_db_session, async_test_user, async_test_household
    ):
        created = await seed_default_templates_async(
            db=real_async_db_session,
            org_id=async_test_household.id,
            module='warehouse',
            user_id=async_test_user.id,
            built_ins=[],
        )

        assert created == []

    async def test_seed_partial_skip(
        self, real_async_db_session, async_test_user, async_test_household
    ):
        built_ins = [
            ('Invoice', 'INVOICE', '<h1>Invoice</h1>'),
            ('Receipt', 'RECEIPT', '<h1>Receipt</h1>'),
        ]
        await seed_default_templates_async(
            db=real_async_db_session,
            org_id=async_test_household.id,
            module='warehouse',
            user_id=async_test_user.id,
            built_ins=built_ins[:1],
        )

        created = await seed_default_templates_async(
            db=real_async_db_session,
            org_id=async_test_household.id,
            module='warehouse',
            user_id=async_test_user.id,
            built_ins=built_ins,
        )

        assert len(created) == 1
        assert created[0].name == 'Receipt'

    async def test_seed_different_modules_independent(
        self, real_async_db_session, async_test_user, async_test_household
    ):
        built_ins = [('Template A', 'DEFAULT', '<p>A</p>')]

        await seed_default_templates_async(
            db=real_async_db_session,
            org_id=async_test_household.id,
            module='warehouse',
            user_id=async_test_user.id,
            built_ins=built_ins,
        )
        await seed_default_templates_async(
            db=real_async_db_session,
            org_id=async_test_household.id,
            module='equipment',
            user_id=async_test_user.id,
            built_ins=built_ins,
        )

        docs = await list_templates_async(
            real_async_db_session, async_test_household.id, 'warehouse'
        )
        equipment = await list_templates_async(
            real_async_db_session, async_test_household.id, 'equipment'
        )

        assert len(docs) == 1
        assert len(equipment) == 1
