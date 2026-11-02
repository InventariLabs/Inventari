"""Module-safe access to ProductTemplates (read and write)."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import ProductTemplateCandidateDTO, ProductTemplateDTO
from app.core.logging import get_logger

logger = get_logger(__name__)


class CoreProductTemplatesAPI:
    """Read and write access to ProductTemplate records for use by modules."""

    async def list_for_org_async(
        self,
        db: AsyncSession,
        org_id: UUID,
        limit: int = 200,
    ) -> list[ProductTemplateDTO]:
        from app.services._product_template_reads import list_templates_for_org_async

        templates = await list_templates_for_org_async(db, org_id, limit=limit)
        return [ProductTemplateDTO.model_validate(t) for t in templates]

    async def count_for_org_async(self, db: AsyncSession, org_id: UUID) -> int:
        """Count templates the org can pick from (org-scoped + global).

               Lets callers answer "is the catalog empty" before a form opens
        without a search query.
        """
        from app.services._product_template_reads import count_templates_for_org_async

        return await count_templates_for_org_async(db, org_id)

    async def get_async(
        self, db: AsyncSession, org_id: UUID, template_id: UUID
    ) -> ProductTemplateDTO | None:
        from app.services._product_template_reads import get_template_for_org_async

        template = await get_template_for_org_async(db, org_id, template_id)
        if template is None:
            return None
        return ProductTemplateDTO.model_validate(template)

    async def get_many_async(
        self, db: AsyncSession, org_id: UUID, template_ids: list[UUID]
    ) -> dict[UUID, ProductTemplateDTO]:
        """Batch twin of ``get_async``: id -> template, missing ids absent.

        Tier 2 extension for readers that resolve many templates in one
        request — recipe availability needs each matched template's pack
        size to compare a countable stock against a measured requirement,
        and asking one at a time makes that a query per ingredient.
        """
        from app.services._product_template_reads import list_templates_by_ids_async

        templates = await list_templates_by_ids_async(db, org_id, template_ids)
        return {t.id: ProductTemplateDTO.model_validate(t) for t in templates}

    async def names_and_units_async(
        self, db: AsyncSession, org_id: UUID, template_ids: Iterable[UUID]
    ) -> dict[UUID, tuple[str, str | None]]:
        """id -> (name, unit symbol) for many templates, missing ids absent.

        The narrow twin of ``get_many_async`` for a reader that prints a
        product's name beside a figure: one row of two columns per product,
        however many the report names.
        """
        from app.services._product_template_reads import names_and_units_by_ids_async

        return await names_and_units_by_ids_async(db, org_id, template_ids)

    async def exists_for_org_async(
        self, db: AsyncSession, org_id: UUID, template_id: UUID
    ) -> bool:
        from app.services._product_template_reads import template_exists_for_org_async

        return await template_exists_for_org_async(db, org_id, template_id)

    async def lookup_by_barcode_async(
        self, db: AsyncSession, org_id: UUID, barcode: str
    ) -> ProductTemplateDTO | None:
        from app.services._product_template_reads import get_template_by_barcode_async

        template = await get_template_by_barcode_async(db, org_id, barcode)
        if template is None:
            return None
        return ProductTemplateDTO.model_validate(template)

    async def lookup_by_sku_async(
        self, db: AsyncSession, org_id: UUID, sku: str
    ) -> ProductTemplateDTO | None:
        """Async: find a template by SKU, scoped to org + global templates."""
        from app.services.sku_service import SkuService

        template = await SkuService.lookup_by_sku_async(db, org_id, sku)
        if template is None:
            return None
        return ProductTemplateDTO.model_validate(template)

    async def lookup_by_identity_async(
        self,
        db: AsyncSession,
        org_id: UUID,
        *,
        name: str,
        brand: str | None = None,
        barcode: str | None = None,
    ) -> ProductTemplateDTO | None:
        """The card a record of this name, brand and code belongs to, if one does.

        The matching :meth:`resolve_default_async` adopts a record under —
        code first, then name and brand, the organization's own card ahead of
        a shared one — asked without giving anyone a card. A reader that
        plans ahead of the booking (a receipt's preview) has to know which
        card the booking will adopt; ``None`` is the case where it would
        mint one, and a fresh card has no rules to apply.
        """
        from app.services.items._template import find_template_async

        template = await find_template_async(
            db, org_id, name=name, barcode=barcode, brand=brand
        )
        if template is None:
            return None
        return ProductTemplateDTO.model_validate(template)

    async def resolve_default_async(
        self,
        db: AsyncSession,
        org_id: UUID,
        *,
        name: str,
        brand: str | None = None,
        barcode: str | None = None,
        uom_id: UUID | None = None,
    ) -> ProductTemplateDTO:
        """The card this product belongs to, minting one when none matches.

        The same rule a new record follows — barcode first, then name and
        brand, preferring the organization's own card — so a path that
        adopted a record before any card existed for it lands in the same
        per-product ledger a fresh record does, and two receipts of the
        same hand-named product share one card instead of minting twins.
        A minted card inherits *uom_id* — the organization's piece unit when
        the caller names none, the same answer a new record gets rather than
        a card that cannot say what its quantities are counted in; a matched
        card keeps its own unit.
        """
        from app.services.items._create import _default_piece_uom_id_async
        from app.services.items._template import resolve_template_default_async

        if uom_id is None:
            uom_id = await _default_piece_uom_id_async(db, org_id)
        template, _created = await resolve_template_default_async(
            db,
            {'name': name, 'brand': brand, 'barcode': barcode, 'uom_id': uom_id},
            org_id,
        )
        return ProductTemplateDTO.model_validate(template)

    async def create_stub_async(
        self,
        db: AsyncSession,
        org_id: UUID,
        name: str,
        barcode: str | None = None,
        user_id: UUID | None = None,
    ) -> ProductTemplateDTO:
        from app.services._product_template_writes import create_stub_template_async

        tpl = await create_stub_template_async(db, org_id, name, barcode, user_id)
        return ProductTemplateDTO.model_validate(tpl)

    async def create_async(
        self,
        db: AsyncSession,
        org_id: UUID,
        name: str,
        brand: str | None = None,
        barcode: str | None = None,
        sku: str | None = None,
        description: str | None = None,
        image_url: str | None = None,
        meta_data: dict[str, Any] | None = None,
        user_id: UUID | None = None,
    ) -> ProductTemplateDTO:
        from app.services._product_template_writes import create_product_template_async

        tpl = await create_product_template_async(
            db,
            org_id,
            name,
            brand=brand,
            barcode=barcode,
            sku=sku,
            description=description,
            image_url=image_url,
            meta_data=meta_data,
            user_id=user_id,
        )
        return ProductTemplateDTO.model_validate(tpl)

    async def update_async(
        self,
        db: AsyncSession,
        template_id: UUID,
        org_id: UUID,
        name: str | None = None,
        brand: str | None = None,
        barcode: str | None = None,
        description: str | None = None,
        image_url: str | None = None,
        meta_data: dict[str, Any] | None = None,
        user_id: UUID | None = None,
    ) -> ProductTemplateDTO:
        from app.services._product_template_writes import update_product_template_async

        tpl = await update_product_template_async(
            db,
            template_id,
            org_id,
            name=name,
            brand=brand,
            barcode=barcode,
            description=description,
            image_url=image_url,
            meta_data=meta_data,
            user_id=user_id,
        )
        return ProductTemplateDTO.model_validate(tpl)

    async def delete_async(
        self,
        db: AsyncSession,
        template_id: UUID,
        org_id: UUID,
        user_id: UUID | None = None,
    ) -> None:
        from app.services._product_template_writes import delete_product_template_async

        await delete_product_template_async(db, template_id, org_id, user_id)

    async def search_ranked_async(
        self,
        db: AsyncSession,
        org_id: UUID,
        query: str,
        limit: int = 10,
    ) -> list[ProductTemplateDTO]:
        """Search templates with priority ranking: exact barcode > exact SKU > ILIKE name.

        Returns results ordered by relevance rather than creation date.
        """
        from app.services._product_template_search import search_ranked_async

        templates = await search_ranked_async(db, org_id, query, limit=limit)
        return [ProductTemplateDTO.model_validate(t) for t in templates]

    async def search_fuzzy_async(
        self,
        db: AsyncSession,
        org_id: UUID,
        query: str,
        limit: int = 10,
    ) -> list[ProductTemplateDTO]:
        """ILIKE search across org + global templates, name-only.

        Tier 2 extension for ingredient-to-template matching in recipes
        import. Distinct from ``search_ranked_async`` (which scores
        barcode/SKU/name priority) — fuzzy search treats the name match
        as the sole criterion and includes global (org_id IS NULL)
        templates visible to *org_id*.

        Use ``search_ranked_async`` for barcode-scanner UX and
        ``search_fuzzy_async`` for LLM-prompt catalog dumps.
        """
        from app.services._product_template_search import search_fuzzy_async

        templates = await search_fuzzy_async(db, org_id, query, limit=limit)
        return [ProductTemplateDTO.model_validate(t) for t in templates]

    async def get_with_uom_async(
        self, db: AsyncSession, org_id: UUID, template_id: UUID
    ) -> ProductTemplateDTO | None:
        """Return a template with ``weight_uom`` eagerly loaded.

        Tier 2 extension used by recipes nutrition/cost reads that need
        the weight UOM symbol without a follow-up query.
        """
        from app.services._product_template_search import get_with_uom_async

        template = await get_with_uom_async(db, org_id, template_id)
        if template is None:
            return None
        return ProductTemplateDTO.model_validate(template)

    async def search_fuzzy_many_async(
        self,
        db: AsyncSession,
        org_id: UUID,
        queries: list[str],
    ) -> dict[str, list[ProductTemplateCandidateDTO]]:
        """Batch name-fragment search: fragment -> the templates containing it.

        Tier 2 extension used by recipes availability to look up many
        ingredients in one query. Includes org-scoped AND global templates.

        Candidates come back with their names because ranking them belongs
        to the caller: which template a name like "Ciecierzyca z puszki"
        really means is a domain question, and the Core stays neutral.
        """
        from app.services._product_template_search import search_fuzzy_many_async

        return await search_fuzzy_many_async(db, org_id, queries)

    async def list_for_org_with_recipe_usage_async(
        self,
        db: AsyncSession,
        org_id: UUID,
        limit: int = 200,
    ) -> list[ProductTemplateDTO]:
        """List templates with recipe-ingredient usage count, ordered by usage.

        Tier 2 CoreAPI extension for the recipes ``template_matcher``
        LLM-prompt catalog dump. Templates already referenced by this
        org's recipes surface first, then alphabetical.
        """
        from app.services._product_template_reads import (
            list_templates_for_org_with_recipe_usage_async,
        )

        templates = await list_templates_for_org_with_recipe_usage_async(
            db, org_id, limit=limit
        )
        return [ProductTemplateDTO.model_validate(t) for t in templates]
