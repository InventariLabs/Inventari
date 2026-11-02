"""The Open Food Facts importer, run end to end against a generated parquet.

The catalogue table lives in its own database in production; here the
importer is pointed at the test database and the table is dropped afterwards,
so nothing it creates outlives the test.
"""

import base64
import os
from collections.abc import Generator
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import Insert
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.modules.nutrition import import_parquet
from app.modules.nutrition.models import OFFBase, OFFProductLocal


@pytest.fixture
def importer_on_test_db(
    setup_test_db: Engine, monkeypatch: pytest.MonkeyPatch
) -> Generator[sessionmaker[Session]]:
    engine = setup_test_db
    session_factory = sessionmaker(bind=engine)
    monkeypatch.setattr(import_parquet, 'products_engine', engine)
    monkeypatch.setattr(import_parquet, 'ProductsSessionLocal', session_factory)
    yield session_factory
    OFFBase.metadata.drop_all(bind=engine)


def _arrow_mib() -> float:
    """What the Arrow memory pool holds right now, in MiB.

    The importer's growth, when it has any, is Arrow's: a pre-buffered reader
    keeps every column chunk it has read until the file is closed, and those
    chunks are allocated from this pool. The process's resident size cannot
    answer the question — the test process already carries a few hundred MiB
    of imports, so the allocator reuses freed pages and a reading moves by
    tens of MiB with nothing kept at all, which is how this test failed on a
    host running other suites.
    """
    return float(pa.total_allocated_bytes()) / (1024 * 1024)


def test_a_product_lands_with_the_fields_the_scan_reads(
    importer_on_test_db: sessionmaker[Session], tmp_path: Path
) -> None:
    path = tmp_path / 'food.parquet'
    pq.write_table(
        pa.table(
            {
                'code': ['5901234123457', '96385074', ''],
                'product_name': [
                    [
                        {'lang': 'en', 'text': 'Oat drink'},
                        {'lang': 'pl', 'text': 'Napój owsiany'},
                    ],
                    [{'lang': 'en', 'text': 'Crackers'}],
                    [{'lang': 'en', 'text': 'Has no code'}],
                ],
                'brands': ['Oatly', None, None],
                'nutriscore_grade': ['b', None, None],
                'nutriments': [
                    [{'name': 'energy-kcal', '100g': 46.0}],
                    [],
                    [],
                ],
            }
        ),
        path,
    )

    import_parquet.import_off_parquet(str(path))

    with importer_on_test_db() as db:
        rows = {row.barcode: row for row in db.scalars(select(OFFProductLocal))}
    assert set(rows) == {'5901234123457', '0000096385074'}
    oat = rows['5901234123457']
    assert oat.name == 'Napój owsiany'
    assert oat.brand == 'Oatly'
    assert oat.data['nutriscore'] == 'b'
    assert oat.data['energy_kcal'] == 46.0


def _front(lang: str, imgid: int | None, rev: int | None) -> dict[str, object]:
    return {'key': f'front_{lang}', 'imgid': imgid, 'rev': rev}


def test_a_picture_is_built_from_the_images_column_of_the_current_file(
    importer_on_test_db: sessionmaker[Session], tmp_path: Path
) -> None:
    """The 2026 file has no ``image_url`` column: the front picture is a
    ``front_<lang>`` entry of ``images`` and its address is built from the
    barcode, the key and the revision."""
    path = tmp_path / 'food.parquet'
    image = pa.struct(
        [('key', pa.string()), ('imgid', pa.int32()), ('rev', pa.int32())]
    )
    pq.write_table(
        pa.table(
            {
                'code': ['5901234123457', '96385074', '4009900415934'],
                'product_name': ['With pictures', 'Short code', 'No front picture'],
                'images': pa.array(
                    [
                        [
                            {'key': '1', 'imgid': None, 'rev': None},
                            _front('fr', 1, 4),
                            _front('pl', 2, 7),
                        ],
                        [_front('en', 3, 2)],
                        [{'key': 'ingredients_fr', 'imgid': 2, 'rev': 10}],
                    ],
                    type=pa.list_(image),
                ),
            }
        ),
        path,
    )

    assert import_parquet.import_off_parquet(str(path)) is True

    with importer_on_test_db() as db:
        urls = {
            row.barcode: row.image_url for row in db.scalars(select(OFFProductLocal))
        }
    base = 'https://images.openfoodfacts.org/images/products'
    assert urls == {
        '5901234123457': f'{base}/590/123/412/3457/front_pl.7.400.jpg',
        '0000096385074': f'{base}/96385074/front_en.2.400.jpg',
        '4009900415934': None,
    }


def test_a_value_json_cannot_carry_becomes_null_instead_of_losing_the_product(
    importer_on_test_db: sessionmaker[Session], tmp_path: Path
) -> None:
    """Postgres refuses NaN in a JSON column, and the batch and the row-by-row
    fallback both failed on it, so the product never reached the catalogue."""
    nan = float('nan')
    path = tmp_path / 'food.parquet'
    pq.write_table(
        pa.table(
            {
                'code': ['4009900415934'],
                'product_name': ['Has a NaN'],
                'nova_group': [nan],
                'nutriments': [
                    [
                        {'name': 'proteins', '100g': nan},
                        {'name': 'fat', '100g': 3.0},
                    ]
                ],
            }
        ),
        path,
    )

    assert import_parquet.import_off_parquet(str(path)) is True

    with importer_on_test_db() as db:
        row = db.scalars(select(OFFProductLocal)).one()
    assert row.data['fat'] == 3.0
    assert 'proteins' not in row.data
    assert 'nova_group' not in row.data


def test_the_import_reports_failure_when_it_could_not_start(
    importer_on_test_db: sessionmaker[Session],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``make off-import`` prints its success line when the importer exits 0,
    so a missing file or a missing products database has to say no."""
    assert import_parquet.import_off_parquet(str(tmp_path / 'absent.parquet')) is False

    path = tmp_path / 'food.parquet'
    pq.write_table(pa.table({'code': ['5901234123457']}), path)
    monkeypatch.setattr(import_parquet, 'products_engine', None)
    assert import_parquet.import_off_parquet(str(path)) is False


def test_memory_stays_flat_as_the_file_is_read(
    importer_on_test_db: sessionmaker[Session],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The real file is 7.9 GB in row groups of 1 024 rows, and an importer
    whose memory grows with the bytes it has read is killed long before the
    end of it. The bulk sits in a column the importer reads, so leaving
    columns out cannot hide the growth: random text the file cannot
    compress, about 60 MB of it.
    """
    rows = 40_000
    path = tmp_path / 'food.parquet'
    pq.write_table(
        pa.table(
            {
                'code': [str(5_900_000_000_000 + i) for i in range(rows)],
                'product_name': [f'Product {i}' for i in range(rows)],
                'ingredients_text': [
                    base64.b64encode(os.urandom(1_125)).decode() for _ in range(rows)
                ],
            }
        ),
        path,
        row_group_size=1_024,
    )

    arrow_per_batch: list[float] = []
    build_insert = import_parquet.insert

    def insert_and_measure(table: type[OFFProductLocal]) -> Insert:
        arrow_per_batch.append(_arrow_mib())
        return build_insert(table)

    monkeypatch.setattr(import_parquet, 'insert', insert_and_measure)

    import_parquet.import_off_parquet(str(path), batch_size=1_000)

    with importer_on_test_db() as db:
        assert db.scalar(select(func.count()).select_from(OFFProductLocal)) == rows
    assert len(arrow_per_batch) == 40
    # Keeping what has been read leaves about 27 MB in the pool by the last
    # batch. A batch's own buffers, live while its rows are written and freed
    # after, are what the readings show when nothing is kept — and nothing the
    # host does moves them.
    growth = max(arrow_per_batch[-10:]) - min(arrow_per_batch[:10])
    assert growth < 5, f'the Arrow pool grew {growth:.1f} MiB while the file was read'
