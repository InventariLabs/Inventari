"""SKU generation and validation service, and the internal product code."""

from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.core.exceptions import ContractViolationError


class SkuService:
    @staticmethod
    def get_schema(db: Session, org_id: UUID) -> dict | None:
        """Get SKU naming schema for organization."""
        from app.models.organization import Organization

        org = db.scalar(select(Organization).where(Organization.id == org_id))
        if not org or not org.settings:
            return None
        return org.settings.get('sku_schema')

    @staticmethod
    def set_schema(db: Session, org_id: UUID, schema: dict) -> dict:
        """Set SKU naming schema for organization. Flushes but does not commit."""
        from app.models.organization import Organization

        org = db.scalar(select(Organization).where(Organization.id == org_id))
        if not org:
            raise ContractViolationError(f'Organization {org_id} not found')

        settings = dict(org.settings or {})
        settings['sku_schema'] = schema
        org.settings = settings
        db.flush()
        return schema

    @staticmethod
    async def generate_next_async(db: AsyncSession, org_id: UUID) -> str | None:
        """Async: generate next SKU based on org schema. Returns None if schema not configured."""
        from app.models.organization import Organization
        from app.models.product_template import ProductTemplate

        # Lock the Organization row so two concurrent SKU generations
        # cannot both read the same next_number and produce a duplicate SKU.
        # The lock is released at commit/rollback of the surrounding tx.
        org = await db.scalar(
            select(Organization).where(Organization.id == org_id).with_for_update()
        )
        if not org or not org.settings:
            return None
        schema = org.settings.get('sku_schema')
        if not schema or not schema.get('enabled'):
            return None

        prefix = schema.get('prefix', '')
        separator = schema.get('separator', '-')
        next_num = schema.get('next_number', 1)
        pad = schema.get('pad_length', 5)

        if prefix:
            sku = f'{prefix}{separator}{str(next_num).zfill(pad)}'
        else:
            sku = str(next_num).zfill(pad)

        while await db.scalar(
            select(ProductTemplate).where(
                ProductTemplate.organization_id == org_id,
                ProductTemplate.sku == sku,
            )
        ):
            next_num += 1
            if prefix:
                sku = f'{prefix}{separator}{str(next_num).zfill(pad)}'
            else:
                sku = str(next_num).zfill(pad)

        schema['next_number'] = next_num + 1
        settings = dict(org.settings or {})
        settings['sku_schema'] = schema
        org.settings = settings
        await db.flush()

        return sku

    @staticmethod
    async def generate_internal_barcode_async(db: AsyncSession, org_id: UUID) -> str:
        """The next internal EAN-13 for a product that carries no code.

        ``20`` + a ten-digit number the organization counts up + the check
        digit. EAN-13 rather than Code 128 of the SKU: it needs no SKU
        numbering switched on, any scanner reads it, and it fits the barcode
        field every scan door already looks a product up by.

        Every call takes a number, saved or not, so two forms open at once
        never get the same code; a number some product already answers to —
        a code typed in by hand, or one a scan would resolve — is skipped.
        Flushes but does not commit.
        """
        from app.core.barcode import INTERNAL_EAN_PREFIX, gtin_check_digit
        from app.models.item import Item
        from app.models.organization import Organization
        from app.services._product_template_reads import get_template_by_barcode_async

        org = await db.scalar(
            select(Organization).where(Organization.id == org_id).with_for_update()
        )
        if org is None:
            raise ContractViolationError(f'Organization {org_id} not found')
        settings = dict(org.settings or {})
        number = int(settings.get('internal_barcode_next', 1))
        while True:
            body = f'{INTERNAL_EAN_PREFIX}{number:010d}'
            code = body + gtin_check_digit(body)
            number += 1
            on_a_record = await db.scalar(
                select(Item.id)
                .where(Item.organization_id == org_id, Item.barcode == code)
                .limit(1)
            )
            if on_a_record is None and not await get_template_by_barcode_async(
                db, org_id, code
            ):
                break
        settings['internal_barcode_next'] = number
        org.settings = settings
        await db.flush()
        return code

    @staticmethod
    async def lookup_by_sku_async(
        db: AsyncSession, org_id: UUID, sku: str
    ) -> object | None:
        """Async: find ProductTemplate by SKU within organization."""
        from app.models.product_template import ProductTemplate

        result = await db.scalars(
            select(ProductTemplate)
            .where(
                or_(
                    ProductTemplate.organization_id == org_id,
                    ProductTemplate.organization_id.is_(None),
                ),
                ProductTemplate.sku == sku,
            )
            .order_by(ProductTemplate.organization_id.desc().nullslast())
        )
        return result.first()
