from __future__ import annotations

import re

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.core import db_facade
from app.core.contracts import UserContextDTO
from app.core.logging import get_logger
from app.core.public_api import core_api
from app.core.scan_registry import ScanProvider
from app.schemas.label_pool import LabelScanResponse

from .services import off_service

logger = get_logger(__name__)


class OFFScanProvider(ScanProvider):
    async def can_handle(self, code: str) -> bool:
        return bool(re.match(r'^\d{8,14}$', code))

    async def handle(
        self, code: str, user: UserContextDTO, db: Session | AsyncSession
    ) -> LabelScanResponse | None:
        logger.info(f'[OFFScanProvider] Handling code: {code}')
        if not user.organization_id:
            logger.warning('[OFFScanProvider] No organization_id for user')
            return None

        module_enabled = await core_api.organizations.is_module_enabled_async(
            db,  # type: ignore[arg-type]
            user.organization_id,
            'nutrition',
        )
        if not module_enabled:
            logger.warning(
                f'[OFFScanProvider] Organization {user.organization_id} not found or module nutrition disabled'
            )
            return None

        has_active = await core_api.items.has_active_barcode_async(
            db,  # type: ignore[arg-type]
            user.organization_id,
            code,
        )
        if has_active:
            logger.info(
                f'[OFFScanProvider] Active item found in local inventory for {code}, skipping OFF'
            )
            return None

        # The organization already has the product, so the scan is answered
        # from its own catalogue and stock — this provider exists to fill in
        # a product form for a code nobody has, and one offered in front of
        # stock already on the shelf invites a second product for it. The
        # code lives on the catalogue row (a record created through the
        # application stays bare whenever its card holds it), so the row is
        # where "does this organization already have the product" is asked;
        # the record check above is the other shape, a code worn by the
        # record itself. The provider order this skip sits in is documented
        # in ``docs/subsystems/SCAN.md``.
        known = await core_api.product_templates.lookup_by_barcode_async(
            db,  # type: ignore[arg-type]
            user.organization_id,
            code,
        )
        if known is not None:
            logger.info(
                f'[OFFScanProvider] Catalogue already names {code}, skipping OFF'
            )
            return None

        try:
            logger.info(f'[OFFScanProvider] Querying OFF database for {code}')
            if db_facade.ProductsSessionLocal is None:
                logger.info(
                    '[OFFScanProvider] Products database not configured, skipping OFF lookup'
                )
                return None

            products_db = db_facade.ProductsSessionLocal()
            try:
                import asyncio

                off_data = await asyncio.to_thread(
                    off_service.fetch_product, code, products_db
                )
            finally:
                products_db.close()

        except (
            ValueError,
            KeyError,
            TypeError,
            AttributeError,
            RuntimeError,
            OSError,
        ) as e:
            logger.error(f'[OFFScanProvider] Error querying products database: {e}')
            return None

        if not off_data:
            logger.info(f'[OFFScanProvider] Product {code} not found in OFF database')
            return None

        logger.info(
            f'[OFFScanProvider] Product {code} FOUND in OFF database: {off_data.get("name")}'
        )

        nutrition_data = {
            'energy_kcal': off_data.get('energy_kcal'),
            'proteins': off_data.get('proteins'),
            'carbohydrates': off_data.get('carbohydrates'),
            'fat': off_data.get('fat'),
            'sugars': off_data.get('sugars'),
            'salt': off_data.get('salt'),
            'fiber': off_data.get('fiber'),
            'saturated_fat': off_data.get('saturated_fat'),
            'nova_group': off_data.get('nova_group'),
            'nutrient_levels': off_data.get('nutrient_levels'),
        }

        template = {
            'name': off_data.get('name'),
            'brand': off_data.get('brand'),
            'image_url': off_data.get('image_url'),
            'metadata': {
                'off_enriched': True,
                'nutriscore': off_data.get('nutriscore'),
                'nutrition': {k: v for k, v in nutrition_data.items() if v is not None},
                'ingredients': off_data.get('ingredients'),
                'categories': off_data.get('categories'),
                'source': off_data.get('source'),
            },
        }

        return LabelScanResponse(
            status='unassigned',
            label_code=code,
            message_key='scan:result.product',
            message_params={'product': off_data.get('name') or code},
            action='show_quick_add',
            stock_summary={
                'template': template,
                'total_quantity': 0,
                'items': [],
            },
        )
