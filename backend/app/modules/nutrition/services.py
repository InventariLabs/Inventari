import re
from typing import Any

import sqlalchemy.exc as sa_exc
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.barcode import is_restricted_circulation
from app.core.logging import get_logger

from .models import OFFProductLocal

logger = get_logger(__name__)


def strip_html(text: str | None) -> str | None:
    if not text:
        return text
    clean = re.compile('<.*?>')
    return re.sub(clean, '', text).strip()


class OpenFoodFactsService:
    def fetch_product(self, barcode: str, db: Session) -> dict[str, Any] | None:
        """Fetch a product from the OFF local DB by barcode.

        This method is sync because it operates on a sync Session
        obtained from ``app.core.db_facade.ProductsSessionLocal()``. Callers
        that need to call it from async context should use
        ``await asyncio.to_thread(off_service.fetch_product, barcode, db)``.

        Returns ``None`` when the product is not found, the OFF table is
        missing, any DB error occurs, or the code is a GS1 restricted-
        circulation number (GTIN-13 prefixes 02, 04 and 20–29; a GTIN-8
        beginning with 0 or 2), which is not globally unique and so is never
        looked up in a shared catalogue.
        """
        if is_restricted_circulation(barcode):
            # Each company mints these for its own shelves, so the same digits
            # name a different product at every shop that prints them. A
            # generated internal code that happens to match a number somebody
            # once typed into Open Food Facts must not propose their product.
            logger.info(
                f'[OFF-Local] {barcode} is a restricted-circulation code, '
                'not a shared product number; skipping the lookup'
            )
            return None

        try:
            local_product = db.scalars(
                select(OFFProductLocal).where(OFFProductLocal.barcode == barcode)
            ).first()
            if local_product:
                logger.info(f'[OFF-Local] Found product: {barcode}')

                return {
                    'name': local_product.name,
                    'brand': local_product.brand,
                    'image_url': local_product.image_url,
                    'nutriscore': local_product.data.get('nutriscore'),
                    'ingredients': strip_html(local_product.data.get('ingredients')),
                    'energy_kcal': local_product.data.get('energy_kcal'),
                    'proteins': local_product.data.get('proteins'),
                    'carbohydrates': local_product.data.get('carbohydrates'),
                    'fat': local_product.data.get('fat'),
                    'sugars': local_product.data.get('sugars'),
                    'salt': local_product.data.get('salt'),
                    'fiber': local_product.data.get('fiber'),
                    'saturated_fat': local_product.data.get('saturated_fat'),
                    'nova_group': local_product.data.get('nova_group'),
                    'nutrient_levels': local_product.data.get('nutrient_levels'),
                    'categories': strip_html(local_product.data.get('categories')),
                    'source': 'local_off_db',
                }
            else:
                logger.info(f'[OFF-Local] Product NOT found in local DB: {barcode}')
                return None
        except (
            sa_exc.OperationalError,
            sa_exc.ProgrammingError,
            AttributeError,
            KeyError,
            TypeError,
        ) as e:
            if 'relation "off_products_local" does not exist' in str(e):
                logger.warning(
                    '[OFF-Local] OFF table not available, skipping OFF lookup'
                )
            else:
                logger.error(f'[OFF-Local] Database error: {e}')
            return None


off_service = OpenFoodFactsService()
