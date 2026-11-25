"""A Grocy household moves in from Grocy's own database file.

Grocy writes no export, so the move reads ``data/grocy.db``. Every active
location, product group and store becomes a location, a category and a
supplier; every batch of stock becomes a record through the door the form
uses, with its amount, best-before date, price, purchase date, shelf, store
and the opened mark; a product without stock becomes a product of the
catalogue only. A second run of the same file adds nothing twice, and what
the file holds that has no place here is counted in the summary.
"""

from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import UserContextDTO
from app.core.grocy_file import read_grocy_file
from app.core.open_package import opened_at
from app.models.category import Category
from app.models.item import Item
from app.models.partner import Partner
from app.models.product_template import ProductTemplate
from app.models.storage_location import StorageLocation
from app.services.items import _import_job as import_jobs
from app.services.items._grocy_import import (
    analyze_grocy_file_async,
    import_grocy_file_async,
    imported_product_ids_async,
)
from tests.integration._grocy import GrocyDb

pytestmark = pytest.mark.integration


def _ctx(user) -> UserContextDTO:
    return UserContextDTO(
        id=user.id, organization_id=user.organization_id, role='admin'
    )


def _household() -> tuple[GrocyDb, dict[str, int]]:
    g = GrocyDb()
    ids = {
        'pantry': g.location('Grocy pantry'),
        'freezer': g.location('Grocy chest freezer', is_freezer=True),
        'sweets': g.group('Grocy sweets'),
        'baking': g.group('Grocy baking'),
        'shop': g.store('Grocy corner shop'),
        'piece': g.unit('Piece', 'Pieces'),
        'gram': g.unit('Gram', 'Grams'),
        'tin': g.unit('Tin', 'Tins'),
        'pack': g.unit('Pack', 'Packs'),
    }
    ids['cookies'] = g.product(
        'Grocy cookies',
        location=ids['pantry'],
        unit=ids['piece'],
        group=ids['sweets'],
        store=ids['shop'],
        description='Chocolate chip',
        min_stock=4,
    )
    g.barcode(ids['cookies'], '5901234123457')
    g.barcode(ids['cookies'], '5901234123464')
    g.conversion(ids['cookies'], ids['pack'], ids['piece'], 6)
    g.stock(
        ids['cookies'],
        3,
        best_before='2027-03-05',
        purchased='2026-11-02',
        price=1.25,
        location=ids['pantry'],
        store=ids['shop'],
    )
    g.stock(
        ids['cookies'],
        2,
        location=ids['freezer'],
        opened='2026-11-20 08:15:00',
    )
    ids['flour'] = g.product(
        'Grocy flour', location=ids['pantry'], unit=ids['gram'], group=ids['baking']
    )
    g.stock(ids['flour'], 750, best_before='2027-06-01', location=ids['pantry'])
    ids['beans'] = g.product('Grocy beans', location=ids['pantry'], unit=ids['tin'])
    g.stock(ids['beans'], 4, location=ids['pantry'])
    ids['saffron'] = g.product(
        'Grocy saffron', location=ids['pantry'], unit=ids['gram'], min_stock=1
    )
    g.product(
        'Grocy retired jam', location=ids['pantry'], unit=ids['piece'], active=False
    )
    g.recipe('Cheesecake')
    g.chore('Vacuum')
    return g, ids


async def _records(db: AsyncSession, name: str) -> list[Item]:
    rows = await db.execute(
        select(Item)
        .where(Item.name == name, Item.is_deleted.is_(False))
        .order_by(Item.quantity.desc())
    )
    return list(rows.scalars().all())


class TestAHouseholdMovesIn:
    async def test_every_batch_becomes_a_record_with_its_own_date_price_and_shelf(
        self, real_async_db_session, async_test_user, async_test_storage_location
    ) -> None:
        db = real_async_db_session
        g, _ = _household()

        result = await import_grocy_file_async(
            db, read_grocy_file(g.content()), _ctx(async_test_user)
        )

        assert result['failed'] == 0, result['errors']
        # Four batches and one product without stock; the inactive one stays.
        assert result['total'] == 5
        assert result['imported'] == 5
        # The second batch of the cookies joins the product the first made.
        assert result['joined_existing'] == 1
        sealed, opened = await _records(db, 'Grocy cookies')
        assert sealed.quantity == Decimal('3')
        assert sealed.expiry_date == date(2027, 3, 5)
        assert sealed.added_date == date(2026, 11, 2)
        assert sealed.purchase_price == Decimal('1.25')
        assert sealed.description == 'Chocolate chip'
        assert opened.expiry_date is None
        assert opened_at(opened.meta_data) == '2026-11-20'
        assert opened_at(sealed.meta_data) is None
        assert sealed.template_id == opened.template_id
        await db.refresh(
            sealed, ['storage_location', 'category', 'partner', 'template']
        )
        await db.refresh(opened, ['storage_location'])
        assert sealed.storage_location.name == 'Grocy pantry'
        assert opened.storage_location.name == 'Grocy chest freezer'
        assert sealed.category is not None and sealed.category.name == 'Grocy sweets'
        assert sealed.partner is not None and sealed.partner.name == 'Grocy corner shop'
        assert sealed.template.min_quantity == 4
        # The first barcode is the product's; a product keeps one.
        assert sealed.template.barcode == '5901234123457'

    async def test_a_unit_is_matched_by_its_word_and_an_unknown_one_counts_pieces(
        self, real_async_db_session, async_test_user, async_test_storage_location
    ) -> None:
        db = real_async_db_session
        g, _ = _household()

        result = await import_grocy_file_async(
            db, read_grocy_file(g.content()), _ctx(async_test_user)
        )

        (flour,) = await _records(db, 'Grocy flour')
        (beans,) = await _records(db, 'Grocy beans')
        await db.refresh(flour, ['uom'])
        await db.refresh(beans, ['uom'])
        assert (flour.quantity, flour.uom.symbol) == (Decimal('750'), 'g')
        assert (beans.quantity, beans.uom.symbol) == (Decimal('4'), 'pcs')
        assert {
            'what': 'units_as_pieces',
            'count': 1,
            'names': ['Tin'],
        } in result['left_behind']

    async def test_a_product_without_stock_is_a_product_of_the_catalogue_only(
        self, real_async_db_session, async_test_user, async_test_storage_location
    ) -> None:
        db = real_async_db_session
        g, ids = _household()

        await import_grocy_file_async(
            db, read_grocy_file(g.content()), _ctx(async_test_user)
        )

        assert await _records(db, 'Grocy saffron') == []
        saffron = (
            await db.execute(
                select(ProductTemplate).where(ProductTemplate.name == 'Grocy saffron')
            )
        ).scalar_one()
        assert saffron.min_quantity == 1
        stamped = await imported_product_ids_async(db, async_test_user.organization_id)
        assert stamped[str(ids['saffron'])] == saffron.id
        assert str(ids['cookies']) in stamped

    async def test_the_summary_names_what_was_founded_and_what_stayed_behind(
        self, real_async_db_session, async_test_user, async_test_storage_location
    ) -> None:
        db = real_async_db_session
        g, _ = _household()

        result = await import_grocy_file_async(
            db, read_grocy_file(g.content()), _ctx(async_test_user)
        )

        assert result['created_locations'] == ['Grocy pantry', 'Grocy chest freezer']
        assert result['created_categories'] == ['Grocy sweets', 'Grocy baking']
        assert result['created_suppliers'] == ['Grocy corner shop']
        left = {entry['what']: entry['count'] for entry in result['left_behind']}
        assert left == {
            'inactive_products': 1,
            'extra_barcodes': 1,
            'unit_conversions': 1,
            'units_as_pieces': 1,
            'recipes': 1,
            'chores': 1,
        }
        supplier = (
            await db.execute(select(Partner).where(Partner.name == 'Grocy corner shop'))
        ).scalar_one()
        assert supplier.type == 'SUPPLIER'

    async def test_a_place_group_or_store_already_here_is_reused(
        self, real_async_db_session, async_test_user, async_test_storage_location
    ) -> None:
        db = real_async_db_session
        g = GrocyDb()
        here = g.location(async_test_storage_location.name.upper())
        piece = g.unit('Piece')
        tea = g.product('Grocy tea', location=here, unit=piece)
        g.stock(tea, 2, location=here)

        result = await import_grocy_file_async(
            db, read_grocy_file(g.content()), _ctx(async_test_user)
        )

        assert result['created_locations'] == []
        (record,) = await _records(db, 'Grocy tea')
        assert record.storage_location_id == async_test_storage_location.id


class TestTheSameFileTwice:
    async def test_a_second_run_adds_nothing_twice(
        self, real_async_db_session, async_test_user, async_test_storage_location
    ) -> None:
        db = real_async_db_session
        g, _ = _household()
        grocy = read_grocy_file(g.content())
        await import_grocy_file_async(db, grocy, _ctx(async_test_user))
        org = async_test_user.organization_id
        before = await db.scalar(
            select(func.count(Item.id)).where(Item.organization_id == org)
        )

        again = await import_grocy_file_async(db, grocy, _ctx(async_test_user))

        assert again['imported'] == 0
        assert again['skipped'] == 5
        assert again['created_locations'] == []
        assert again['created_categories'] == []
        assert again['created_suppliers'] == []
        after = await db.scalar(
            select(func.count(Item.id)).where(Item.organization_id == org)
        )
        assert after == before
        assert (
            await db.scalar(
                select(func.count(ProductTemplate.id)).where(
                    ProductTemplate.name == 'Grocy cookies'
                )
            )
        ) == 1

    async def test_a_batch_added_in_grocy_since_comes_across_alone(
        self, real_async_db_session, async_test_user, async_test_storage_location
    ) -> None:
        db = real_async_db_session
        g, ids = _household()
        await import_grocy_file_async(
            db, read_grocy_file(g.content()), _ctx(async_test_user)
        )
        g.stock(ids['flour'], 250, location=ids['pantry'])

        again = await import_grocy_file_async(
            db, read_grocy_file(g.content()), _ctx(async_test_user)
        )

        assert (again['imported'], again['joined_existing']) == (1, 1)
        assert sorted(r.quantity for r in await _records(db, 'Grocy flour')) == [
            Decimal('250'),
            Decimal('750'),
        ]

    async def test_a_product_already_in_the_catalogue_takes_the_stock(
        self, real_async_db_session, async_test_user, async_test_storage_location
    ) -> None:
        db = real_async_db_session
        org = async_test_user.organization_id
        own = ProductTemplate(organization_id=org, name='Grocy flour', sku='OWN-FLOUR')
        db.add(own)
        await db.flush()
        g, _ = _household()

        result = await import_grocy_file_async(
            db, read_grocy_file(g.content()), _ctx(async_test_user)
        )

        (flour,) = await _records(db, 'Grocy flour')
        assert flour.template_id == own.id
        assert result['joined_existing'] == 2


class TestTheStepBeforeTheMove:
    async def test_the_analysis_says_what_comes_across_and_writes_nothing(
        self, real_async_db_session, async_test_user, async_test_storage_location
    ) -> None:
        db = real_async_db_session
        g, _ = _household()
        org = async_test_user.organization_id

        analysis = await analyze_grocy_file_async(
            db, _ctx(async_test_user), read_grocy_file(g.content())
        )

        assert analysis['products'] == 4
        assert analysis['stock_entries'] == 4
        assert analysis['steps'] == 5
        assert analysis['already_imported'] == 0
        assert (
            analysis['locations'],
            analysis['product_groups'],
            analysis['stores'],
        ) == (2, 2, 1)
        assert analysis['new_locations'] == ['Grocy pantry', 'Grocy chest freezer']
        assert analysis['new_suppliers'] == ['Grocy corner shop']
        assert analysis['currency']
        assert (
            await db.scalar(
                select(func.count(Category.id)).where(Category.organization_id == org)
            )
        ) == 0
        assert (
            await db.scalar(
                select(func.count(StorageLocation.id)).where(
                    StorageLocation.organization_id == org,
                    StorageLocation.name.like('Grocy%'),
                )
            )
        ) == 0


class TestTheDoor:
    def test_the_file_is_read_and_moved_through_the_api(
        self, client: TestClient, auth_headers: dict, test_storage_location
    ) -> None:
        g, _ = _household()
        files = {'file': ('grocy.db', g.content(), 'application/octet-stream')}

        analysis = client.post(
            '/api/v1/items/import/grocy/analyze', files=files, headers=auth_headers
        )
        moved = client.post(
            '/api/v1/items/import/grocy', files=files, headers=auth_headers
        )

        assert analysis.status_code == 200, analysis.text
        assert analysis.json()['products'] == 4
        assert moved.status_code == 200, moved.text
        assert moved.json()['imported'] == 5
        assert moved.json()['created_suppliers'] == ['Grocy corner shop']

    def test_a_file_that_is_not_grocys_is_refused_with_its_reason(
        self, client: TestClient, auth_headers: dict
    ) -> None:
        files = {
            'file': ('grocy.db', b'name,amount\nTea,2\n', 'application/octet-stream')
        }

        answer = client.post(
            '/api/v1/items/import/grocy', files=files, headers=auth_headers
        )

        assert answer.status_code == 400
        assert answer.json()['detail']['code'] == 'GROCY_FILE_UNREADABLE'

    def test_matches_that_are_not_a_map_of_ids_are_refused(
        self, client: TestClient, auth_headers: dict
    ) -> None:
        g, _ = _household()
        files = {'file': ('grocy.db', g.content(), 'application/octet-stream')}

        answer = client.post(
            '/api/v1/items/import/grocy',
            files=files,
            data={'category_matches_json': '{"Nabiał": "not an id"}'},
            headers=auth_headers,
        )

        assert answer.status_code == 400
        assert answer.json()['detail']['code'] == 'INVALID_MAPPING_JSON'

    def test_a_long_file_is_moved_by_a_job(
        self,
        client: TestClient,
        auth_headers: dict,
        test_storage_location,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        spawned: list[dict] = []
        monkeypatch.setattr(import_jobs, 'INLINE_ROW_LIMIT', 3)
        monkeypatch.setattr(
            import_jobs, 'spawn', lambda job_id, factory, **kw: spawned.append(kw)
        )
        g, _ = _household()
        files = {'file': ('grocy.db', g.content(), 'application/octet-stream')}

        answer = client.post(
            '/api/v1/items/import/grocy', files=files, headers=auth_headers
        )

        assert answer.status_code == 202, answer.text
        assert answer.json()['total'] == 5
        assert callable(spawned[0]['work'])


class TestAnOpenedPackage:
    async def test_what_is_left_of_an_opened_piece_comes_across_as_its_fraction(
        self, real_async_db_session, async_test_user, async_test_storage_location
    ) -> None:
        db = real_async_db_session
        g = GrocyDb()
        shelf = g.location('Grocy fridge')
        piece = g.unit('Piece')
        cheese = g.product('Grocy cheese', location=shelf, unit=piece)
        g.stock(cheese, 0.5, location=shelf, opened='2026-11-24 19:00:00')

        result = await import_grocy_file_async(
            db, read_grocy_file(g.content()), _ctx(async_test_user)
        )

        assert result['failed'] == 0, result['errors']
        (record,) = await _records(db, 'Grocy cheese')
        assert record.quantity == Decimal('0.5')
        assert opened_at(record.meta_data) == '2026-11-24'

    async def test_two_and_a_half_pieces_are_two_sealed_and_half_of_an_opened_one(
        self, real_async_db_session, async_test_user, async_test_storage_location
    ) -> None:
        db = real_async_db_session
        g = GrocyDb()
        shelf = g.location('Grocy fridge')
        piece = g.unit('Piece')
        butter = g.product('Grocy butter', location=shelf, unit=piece)
        g.stock(butter, 2.5, location=shelf, purchased='2026-11-10')

        result = await import_grocy_file_async(
            db, read_grocy_file(g.content()), _ctx(async_test_user)
        )

        assert (result['imported'], result['failed']) == (1, 0), result['errors']
        sealed, opened = await _records(db, 'Grocy butter')
        assert (sealed.quantity, opened_at(sealed.meta_data)) == (Decimal('2'), None)
        assert (opened.quantity, opened_at(opened.meta_data)) == (
            Decimal('0.5'),
            '2026-11-10',
        )


class TestACategoryTheScreenRecognised:
    async def test_a_group_the_screen_matched_files_under_that_category(
        self, real_async_db_session, async_test_user, async_test_storage_location
    ) -> None:
        db = real_async_db_session
        org = async_test_user.organization_id
        # A seeded category: stored in English, shown by its code's translation.
        dairy = Category(name='Dairy', code='dairy', organization_id=org)
        foreign = Category(name='Elsewhere', code='dairy')
        db.add_all([dairy, foreign])
        await db.flush()
        g = GrocyDb()
        shelf = g.location('Lodówka')
        piece = g.unit('Sztuka')
        milk_group = g.group('Nabiał')
        cheese_group = g.group('Sery')
        milk = g.product('Mleko', location=shelf, unit=piece, group=milk_group)
        g.stock(milk, 2, location=shelf)
        cheese = g.product('Gouda', location=shelf, unit=piece, group=cheese_group)
        g.stock(cheese, 1, location=shelf)

        result = await import_grocy_file_async(
            db,
            read_grocy_file(g.content()),
            _ctx(async_test_user),
            category_matches={'Nabiał': dairy.id, 'Sery': foreign.id},
        )

        # Another organization's category is no match: the group is founded.
        assert result['created_categories'] == ['Sery']
        (record,) = await _records(db, 'Mleko')
        assert record.category_id == dairy.id


class TestAPriceARecordCannotHold:
    async def test_a_price_per_gram_under_a_cent_is_left_behind_not_written_as_zero(
        self, real_async_db_session, async_test_user, async_test_storage_location
    ) -> None:
        db = real_async_db_session
        g = GrocyDb()
        shelf = g.location('Grocy pantry')
        gram = g.unit('Gram', 'Grams')
        flour = g.product('Grocy rye flour', location=shelf, unit=gram)
        g.stock(flour, 850, price=0.0035, location=shelf)
        g.stock(flour, 500, price=0.012, location=shelf)

        result = await import_grocy_file_async(
            db, read_grocy_file(g.content()), _ctx(async_test_user)
        )

        assert sorted(
            (r.quantity, r.purchase_price)
            for r in await _records(db, 'Grocy rye flour')
        ) == [(Decimal('500'), Decimal('0.01')), (Decimal('850'), None)]
        assert {'what': 'prices_below_a_cent', 'count': 1, 'names': []} in result[
            'left_behind'
        ]
