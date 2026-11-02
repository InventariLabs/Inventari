import json
import logging
import math
import os
import sys
from typing import Any

import pyarrow.parquet as pq
import sqlalchemy.exc as sa_exc
from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core.barcode import normalize_barcode
from app.core.db_facade import ProductsSessionLocal, products_engine
from app.core.logging import get_logger
from app.core.utils import strip_html

from .models import OFFBase, OFFProductLocal

logging.basicConfig(
    level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = get_logger(__name__)


def clean_string(val: object) -> str | None:
    if val is None:
        return None
    s = str(val).replace('\x00', '').strip()
    return s if s != '' else None


def catalogue_barcode(val: object) -> str | None:
    """The key a catalogue row is filed under, or None if it has none.

    Normalization goes through ``core.barcode`` rather than padding UPC-A
    here: what a scan, an import sheet and this catalogue produce has to
    collide, or the one product they all mean is three products. The 199
    characters are the column's width.
    """
    barcode = clean_string(val)
    if not barcode:
        return None
    return normalize_barcode(barcode[:199])


IMAGE_BASE_URL = 'https://images.openfoodfacts.org/images/products'
IMAGE_PREFERRED_LANGS = ('pl', 'en')


def front_image_url(code: object, images: object) -> str | None:
    """The address of a product's front picture, from the ``images`` column.

    The 2026 file has no ``image_url``: ``images`` lists every picture of the
    product, and the front ones are the entries keyed ``front_<lang>`` that
    carry an image id and a revision. Open Food Facts keeps a picture under
    the barcode split into 3-3-3-rest (padded to 13 digits; a code of 8
    digits or fewer is its own folder) as ``<key>.<revision>.400.jpg``.
    """
    digits = clean_string(code)
    if not digits or not digits.isdigit() or not isinstance(images, list):
        return None
    fronts = {
        str(img['key']): img
        for img in images
        if isinstance(img, dict)
        and str(img.get('key')).startswith('front_')
        and img.get('imgid') is not None
        and img.get('rev') is not None
    }
    if not fronts:
        return None
    key = next(
        (
            f'front_{lang}'
            for lang in IMAGE_PREFERRED_LANGS
            if f'front_{lang}' in fronts
        ),
        sorted(fronts)[0],
    )
    if len(digits) > 8:
        digits = digits.zfill(13)
        digits = f'{digits[:3]}/{digits[3:6]}/{digits[6:9]}/{digits[9:]}'
    return f'{IMAGE_BASE_URL}/{digits}/{key}.{fronts[key]["rev"]}.400.jpg'


def extract_nested_text(
    val: object, preferred_langs: list[str] | None = None
) -> str | None:
    if preferred_langs is None:
        preferred_langs = ['pl', 'en', 'main']
    if not val:
        return None
    if isinstance(val, str) and val.startswith('[') and val.endswith(']'):
        try:
            val = json.loads(val.replace("'", '"'))
        except (json.JSONDecodeError, ValueError):
            pass
    if isinstance(val, list) and len(val) > 0:
        if isinstance(val[0], dict):
            for lang in preferred_langs:
                for item in val:
                    if item.get('lang') == lang and item.get('text'):
                        return clean_string(item.get('text'))
            return clean_string(val[0].get('text'))
        return clean_string(', '.join([str(i) for i in val if i]))
    return clean_string(val)


def extract_nutriments(nutriments_list: object) -> dict[str, float]:
    res: dict[str, float] = {}
    if not nutriments_list:
        return res
    if isinstance(nutriments_list, str) and nutriments_list.startswith('['):
        try:
            nutriments_list = json.loads(nutriments_list.replace("'", '"'))
        except (json.JSONDecodeError, ValueError):
            pass
    if not isinstance(nutriments_list, list):
        return res
    mapping = {
        'energy-kcal': 'energy_kcal',
        'proteins': 'proteins',
        'carbohydrates': 'carbohydrates',
        'fat': 'fat',
        'saturated-fat': 'saturated_fat',
        'sugars': 'sugars',
        'salt': 'salt',
        'fiber': 'fiber',
        'alcohol': 'alcohol',
    }
    for n in nutriments_list:
        if not isinstance(n, dict):
            continue
        name = n.get('name')
        val = n.get('100g')
        if name in mapping and val is not None:
            try:
                number = float(val)
            except (ValueError, TypeError):
                continue
            # JSON has no NaN or infinity, and Postgres refuses the row.
            if math.isfinite(number):
                res[mapping[name]] = number
    return res


def extract_nutrient_levels(levels_tags: object) -> dict[str, str]:
    """Converts ['en:sugars-in-high-quantity', ...] to {'sugars': 'high', ...}"""
    res: dict[str, str] = {}
    if not isinstance(levels_tags, list):
        return res
    for tag in levels_tags:
        tag = str(tag).replace('en:', '')
        parts = tag.split('-in-')
        if len(parts) == 2:
            nutrient = parts[0].replace('-', '_')
            level = parts[1].replace('-quantity', '')
            res[nutrient] = level
    return res


def single_insert(db: Session, data: dict[str, Any]) -> bool:
    """Write one product on its own, for a batch the database refused.

    In a savepoint, so a row that fails takes back only itself; the import
    commits what the rest of the batch wrote.
    """
    try:
        stmt = insert(OFFProductLocal).values(data)
        stmt = stmt.on_conflict_do_update(
            index_elements=['barcode'],
            set_={
                'name': stmt.excluded.name,
                'brand': stmt.excluded.brand,
                'image_url': stmt.excluded.image_url,
                'data': stmt.excluded.data,
                'updated_at': func.now(),
            },
        )
        with db.begin_nested():
            db.execute(stmt)
        return True
    except sa_exc.SQLAlchemyError as e:
        logger.warning(
            f'Failed to import product {data.get("barcode")}: {str(e)[:100]}'
        )
        return False


# The columns the loop below reads; the file has 145. A snapshot that drops
# one leaves its field empty; the 2026 ones have no ``image_url`` and carry the
# pictures in ``images`` instead.
COLUMNS_READ = (
    'code',
    'product_name',
    'generic_name',
    'brands',
    'image_url',
    'images',
    'nutriments',
    'nutrient_levels_tags',
    'nova_group',
    'nutriscore_grade',
    'ingredients_text',
    'quantity',
    'categories',
)


def catalogue_record(row: dict[str, Any]) -> dict[str, Any] | None:
    """One file row as the catalogue stores it, or None for a row without a code."""
    barcode = catalogue_barcode(row.get('code', ''))
    if not barcode:
        return None

    name = extract_nested_text(row.get('product_name')) or extract_nested_text(
        row.get('generic_name')
    )
    nova = row.get('nova_group')
    metadata = {
        'nutriscore': clean_string(row.get('nutriscore_grade')),
        'nova_group': int(nova)
        if isinstance(nova, (int, float)) and math.isfinite(nova)
        else None,
        'ingredients': strip_html(extract_nested_text(row.get('ingredients_text'))),
        'nutrient_levels': extract_nutrient_levels(row.get('nutrient_levels_tags')),
        'quantity': clean_string(row.get('quantity')),
        'categories': strip_html(extract_nested_text(row.get('categories'))),
        **extract_nutriments(row.get('nutriments')),
    }
    return {
        'barcode': barcode,
        'name': name or 'Unknown Product',
        'brand': extract_nested_text(row.get('brands')),
        'image_url': clean_string(row.get('image_url'))
        or front_image_url(row.get('code'), row.get('images')),
        'data': {k: v for k, v in metadata.items() if v is not None},
    }


def import_off_parquet(file_path: str, batch_size: int = 2000) -> bool:
    """Import the file; False when the import could not run or stopped early."""
    if not os.path.exists(file_path):
        logger.error(f'File not found: {file_path}')
        return False

    if products_engine is None or ProductsSessionLocal is None:
        logger.error('Products database is not configured')
        return False

    OFFBase.metadata.create_all(bind=products_engine)
    logger.info(f'Starting RESILIENT EXTENDED import from: {file_path}')

    db: Session | None = None
    try:
        # Pre-buffering keeps every column chunk it has read until the file
        # is closed, and iter_batches reads all of them: on the 7.9 GB Open
        # Food Facts file that is the whole file in memory by the end. Read
        # unbuffered, each row group is released once its batches are out.
        parquet_file = pq.ParquetFile(file_path, pre_buffer=False)
        total_rows = parquet_file.metadata.num_rows
        columns = [c for c in COLUMNS_READ if c in parquet_file.schema_arrow.names]
        db = ProductsSessionLocal()
        count = 0
        failed_count = 0

        # Decoding threads hold some 300 MB of their own on that file.
        for batch in parquet_file.iter_batches(
            batch_size=batch_size, columns=columns, use_threads=False
        ):
            data = batch.to_pylist()
            batch_data_map = {}

            for row in data:
                record = catalogue_record(row)
                if record:
                    batch_data_map[record['barcode']] = record

            if batch_data_map:
                insert_list = list(batch_data_map.values())
                try:
                    stmt = insert(OFFProductLocal).values(insert_list)
                    stmt = stmt.on_conflict_do_update(
                        index_elements=['barcode'],
                        set_={
                            'name': stmt.excluded.name,
                            'brand': stmt.excluded.brand,
                            'image_url': stmt.excluded.image_url,
                            'data': stmt.excluded.data,
                            'updated_at': func.now(),
                        },
                    )
                    db.execute(stmt)
                    db.commit()
                    count += len(insert_list)
                except (sa_exc.SQLAlchemyError, ValueError, TypeError):
                    db.rollback()
                    for item_data in insert_list:
                        if single_insert(db, item_data):
                            count += 1
                        else:
                            failed_count += 1
                    db.commit()

            if count % 10000 < batch_size:
                logger.info(
                    f'Progress: {count}/{total_rows} (Failed: {failed_count})...'
                )

        logger.info(f'FINISHED! Total: {count}, Failed: {failed_count}')
        return True

    except (OSError, sa_exc.SQLAlchemyError, ValueError) as e:
        logger.error(f'Global import error: {e}')
        return False
    finally:
        if db is not None:
            db.close()


def main() -> None:
    """Command line entry: a non-zero exit when the import did not complete,
    which is what ``make off-import`` reads before it reports success."""
    ok = import_off_parquet(
        sys.argv[1], int(sys.argv[2]) if len(sys.argv) > 2 else 2000
    )
    if not ok:
        sys.exit(1)


if __name__ == '__main__':
    main()
