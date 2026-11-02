"""Module-safe access to DocumentTemplate management.

Replaces direct ``app.services.template_crud`` imports in module routers
(previously baselined architecture-lint bypasses).

Transaction semantics: like the rest of CoreAPI, the write methods flush
and return — the caller owns the commit, so a template write composes with
whatever else the caller is writing.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.template_schemas import DocumentTemplateSchema


class CoreTemplatesAPI:
    """Public Core API for document template CRUD."""

    async def list_async(
        self,
        db: AsyncSession,
        organization_id: UUID,
        module: str,
        built_ins: list[tuple[str, str, str]] | None = None,
    ) -> list[DocumentTemplateSchema]:
        """The organization's own templates.

        Pass ``built_ins`` to have each copy told apart from the built-in it
        came from: the flag says the built-in has moved on since,
        which is the one thing the copy itself cannot know.
        """
        from app.services import template_crud

        templates = await template_crud.list_templates_async(
            db, organization_id, module
        )
        if built_ins is None:
            return [DocumentTemplateSchema.model_validate(t) for t in templates]
        return [
            DocumentTemplateSchema.model_validate(t).model_copy(
                update={
                    'source_outdated': template_crud.builtin_has_moved_on(t, built_ins)
                }
            )
            for t in templates
        ]

    async def copy_builtin_alongside_async(
        self,
        db: AsyncSession,
        organization_id: UUID,
        module: str,
        user_id: UUID,
        template_id: UUID,
        built_ins: list[tuple[str, str, str]],
    ) -> DocumentTemplateSchema:
        """Copy the current built-in next to the organization's own copy.

        Never over it — an organization's edits are not something an upgrade
        gets to discard, so the refreshed layout arrives as a second template
        and does not become the default.
        """
        from app.services import template_crud

        created = await template_crud.copy_builtin_alongside_async(
            db=db,
            org_id=organization_id,
            module=module,
            user_id=user_id,
            template_id=template_id,
            built_ins=built_ins,
        )
        return DocumentTemplateSchema.model_validate(created)

    async def get_async(
        self, db: AsyncSession, organization_id: UUID, template_id: UUID, module: str
    ) -> DocumentTemplateSchema | None:
        from app.services import template_crud

        template = await template_crud.get_template_async(
            db, organization_id, template_id, module
        )
        return DocumentTemplateSchema.model_validate(template) if template else None

    async def get_default_async(
        self, db: AsyncSession, organization_id: UUID, module: str, document_type: str
    ) -> DocumentTemplateSchema | None:
        """Get the default template for ``(module, document_type)``."""
        from app.services import template_crud

        template = await template_crud.get_default_template_async(
            db, organization_id, module, document_type
        )
        return DocumentTemplateSchema.model_validate(template) if template else None

    async def create_async(
        self,
        db: AsyncSession,
        organization_id: UUID,
        module: str,
        user_id: UUID,
        name: str,
        body_html: str,
        document_type: str = 'DEFAULT',
        is_default: bool = False,
        partials: dict[str, str] | None = None,
    ) -> DocumentTemplateSchema:
        from app.services import template_crud

        template = await template_crud.create_template_async(
            db=db,
            org_id=organization_id,
            module=module,
            user_id=user_id,
            name=name,
            body_html=body_html,
            document_type=document_type,
            is_default=is_default,
            partials=partials,
        )
        return DocumentTemplateSchema.model_validate(template)

    async def update_async(
        self,
        db: AsyncSession,
        organization_id: UUID,
        template_id: UUID,
        module: str,
        *,
        name: str | None = None,
        body_html: str | None = None,
        document_type: str | None = None,
        is_default: bool | None = None,
        partials: dict[str, str] | None = None,
        user_id: UUID | None = None,
    ) -> DocumentTemplateSchema:
        """Raises ``NotFoundException`` when the template does not exist.

        *user_id* names who made the change for the organization log. It is
        optional because a template can also be rewritten by a migration or
        a seeding pass, where there is nobody to name.
        """
        from app.services import template_crud

        template = await template_crud.update_template_async(
            db=db,
            org_id=organization_id,
            template_id=template_id,
            module=module,
            name=name,
            body_html=body_html,
            document_type=document_type,
            is_default=is_default,
            partials=partials,
            user_id=user_id,
        )
        return DocumentTemplateSchema.model_validate(template)

    async def delete_async(
        self,
        db: AsyncSession,
        organization_id: UUID,
        template_id: UUID,
        module: str,
        user_id: UUID | None = None,
    ) -> None:
        """Raises ``NotFoundException`` when the template does not exist."""
        from app.services import template_crud

        await template_crud.delete_template_async(
            db, organization_id, template_id, module, user_id=user_id
        )

    async def seed_defaults_async(
        self,
        db: AsyncSession,
        organization_id: UUID,
        module: str,
        user_id: UUID,
        built_ins: list[tuple[str, str, str]],
        partials: dict[str, str] | None = None,
    ) -> list[DocumentTemplateSchema]:
        """Seed built-in templates; existing names are skipped (idempotent)."""
        from app.services import template_crud

        created = await template_crud.seed_default_templates_async(
            db=db,
            org_id=organization_id,
            module=module,
            user_id=user_id,
            built_ins=built_ins,
            partials=partials,
        )
        return [DocumentTemplateSchema.model_validate(t) for t in created]
