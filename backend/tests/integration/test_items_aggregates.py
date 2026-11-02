"""Totals for the whole filtered set, not the current page.

The products list paginates server-side, so its footer sums cannot be added
up from the rows on screen. ``GET /items/aggregates`` answers with the same
filter the list applied, from the same query builder — one source of filter,
no totals that contradict the rows. The numbers are the ones the retired
inventory report showed: item count, total weight (the line weight of
ADR-015, derived not stored), total value (price x quantity).
"""

from __future__ import annotations

import pytest
from fastapi import status

from app.models.item import Item

pytestmark = pytest.mark.integration


def _create_item(client, auth_headers, storage_id, **overrides):
    payload = {
        'name': 'Aggregate me',
        'quantity': 1,
        'location_id': str(storage_id),
    }
    payload.update(overrides)
    response = client.post('/api/v1/items', headers=auth_headers, json=payload)
    assert response.status_code == status.HTTP_201_CREATED
    return response.json()


class TestItemsAggregates:
    def test_missing_currency_refusal_speaks_polish(
        self, client, auth_headers, test_household, db_session
    ):
        test_household.currency = ''
        db_session.commit()
        response = client.get(
            '/api/v1/items/aggregates',
            headers={**auth_headers, 'Accept-Language': 'pl'},
        )
        assert response.status_code == 400
        assert (
            response.json()['detail']['message']
            == 'Waluta organizacji nie jest skonfigurowana'
        )
        assert response.json()['detail']['lang'] == 'pl'

    def test_empty_organization_aggregates_to_zeros(self, client, auth_headers):
        response = client.get('/api/v1/items/aggregates', headers=auth_headers)

        assert response.status_code == status.HTTP_200_OK
        assert response.json() == {
            'count': 0,
            'product_count': 0,
            'total_weight': 0.0,
            'total_volume': 0.0,
            'total_value': 0.0,
            # An empty ledger prices nothing; the records are the source
            # until the first receipt is posted — the rule the overview uses.
            'value_source': 'purchase_price',
            'unpriced_count': 0,
            'excludes_module_items': False,
            'excludes_unlisted_layers': False,
        }

    def test_aggregates_cover_the_whole_set_not_a_page(
        self, client, auth_headers, test_storage_location
    ):
        """More rows than the default page, one request — the sum must not
        stop at the page boundary the list stops at."""
        # Two weighed lines: 3 x 500 g = 1.5 kg and 2 x 1000 g = 2 kg.
        _create_item(
            client,
            auth_headers,
            test_storage_location.id,
            name='Milk 500 g',
            quantity=3,
            weight_value=500.0,
            purchase_price=4.50,
        )
        _create_item(
            client,
            auth_headers,
            test_storage_location.id,
            name='Flour 1 kg',
            quantity=2,
            weight_value=1000.0,
            purchase_price=3.00,
        )
        # An unweighed, unpriced line counts for the headcount only.
        _create_item(
            client,
            auth_headers,
            test_storage_location.id,
            name='Loose screws',
            quantity=5,
        )

        response = client.get('/api/v1/items/aggregates', headers=auth_headers)

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data['count'] == 3
        assert data['total_weight'] == pytest.approx(3.5)
        # 3 x 4.50 + 2 x 3.00 = 19.50
        assert data['total_value'] == pytest.approx(19.50)

    def test_a_storage_filter_narrows_the_count_and_withholds_the_value(
        self, client, auth_headers, test_storage_location, db_session, test_user
    ):
        from app.models.storage_location import StorageLocation

        second = StorageLocation(
            organization_id=test_user.organization_id,
            created_by=test_user.id,
            storage_type_id=test_storage_location.storage_type_id,
            name='Pantry',
        )
        db_session.add(second)
        db_session.commit()

        _create_item(
            client,
            auth_headers,
            test_storage_location.id,
            name='Freezer peas',
            quantity=2,
            purchase_price=5.00,
        )
        _create_item(
            client,
            auth_headers,
            second.id,
            name='Pantry rice',
            quantity=4,
            purchase_price=2.00,
        )

        data = _aggregates(client, auth_headers, location_id=str(second.id))

        # The count still describes the slice the filter picked out.
        assert data['count'] == 1
        # The value does not: the ledger figure is withheld under a filter.
        assert data['total_value'] is None
        assert data['value_source'] == 'not_available_under_filter'

    def test_a_search_filter_narrows_the_count_and_withholds_the_value(
        self, client, auth_headers, test_storage_location
    ):
        _create_item(
            client,
            auth_headers,
            test_storage_location.id,
            name='Apple juice',
            quantity=2,
            purchase_price=6.00,
        )
        _create_item(
            client,
            auth_headers,
            test_storage_location.id,
            name='Apple sauce',
            quantity=1,
            purchase_price=4.00,
        )
        _create_item(
            client,
            auth_headers,
            test_storage_location.id,
            name='Pear juice',
            quantity=10,
            purchase_price=1.00,
        )

        data = _aggregates(client, auth_headers, search='apple')

        assert data['count'] == 2
        assert data['total_value'] is None
        assert data['value_source'] == 'not_available_under_filter'

    def test_count_matches_the_list_total_under_the_same_filter(
        self, client, auth_headers, test_storage_location
    ):
        """The one guarantee that matters: the footer never disagrees with
        the rows above it."""
        for i in range(4):
            _create_item(
                client,
                auth_headers,
                test_storage_location.id,
                name=f'Counted {i}',
                quantity=1,
            )

        aggregates = client.get('/api/v1/items/aggregates', headers=auth_headers).json()
        listing = client.get(
            '/api/v1/items', headers=auth_headers, params={'limit': 2}
        ).json()

        assert aggregates['count'] == 4
        assert listing['total'] == aggregates['count']
        # The page really is shorter than the set — otherwise the test proves nothing.
        assert len(listing['items']) == 2


class TestTheWeightIsExact:
    def test_a_unit_weight_a_double_cannot_hold_sums_to_the_gram(
        self, client, auth_headers, test_storage_location, db_session
    ):
        """Three pieces of 0.1 kg weigh 0.3 kg — not 0.30000000000000004.

        The unit weight is multiplied by the quantity in SQL. Stored as a
        double it drags the whole expression into binary floating point,
        and 0.1 is the textbook value a double cannot hold.
        """
        from sqlalchemy import select

        from app.models.uom import Uom

        kg = db_session.scalars(select(Uom).where(Uom.symbol == 'kg')).one()
        _create_item(
            client,
            auth_headers,
            test_storage_location.id,
            name='Butter 100 g',
            quantity=3,
            weight_value=0.1,
            weight_uom_id=str(kg.id),
        )

        response = client.get('/api/v1/items/aggregates', headers=auth_headers)

        assert response.status_code == status.HTTP_200_OK
        assert response.json()['total_weight'] == 0.3

    def test_the_arithmetic_never_leaves_numeric(self, db_session):
        """The SQL that sums the weight multiplies a quantity by a unit
        weight; ``numeric * double`` is ``double``, so the column type of
        the unit weight decides whether the whole total is exact."""
        from sqlalchemy import text

        product_type = db_session.execute(
            text(
                'SELECT pg_typeof('
                '(SELECT quantity FROM items LIMIT 1)'
                ' * (SELECT weight_value FROM product_templates LIMIT 1)'
                ')::text'
            )
        ).scalar_one()
        assert product_type == 'numeric'


class TestVolumeIsNotWeight:
    """Two quantities, two sums.

    A litre is not a kilogram, and the footer used to add them: 2 l of milk
    arrived in ``total_weight``, which the footer labels kilograms. The
    sum now splits by the same rule ``Item.total_weight_unit`` applies per
    row — a line counted in a volume unit reports litres, and a kilogram
    total exists only when the set really holds weight.
    """

    def _litre(self, db_session):
        from sqlalchemy import select

        from app.models.uom import Uom

        return db_session.scalars(select(Uom).where(Uom.symbol == 'l')).one()

    def test_a_litre_only_list_reports_litres_and_no_kilograms(
        self, client, auth_headers, test_storage_location, db_session
    ):
        litre = self._litre(db_session)
        _create_item(
            client,
            auth_headers,
            test_storage_location.id,
            name='Mleko 2%',
            quantity=2,
            uom_id=str(litre.id),
        )

        data = _aggregates(client, auth_headers)

        assert data['total_volume'] == pytest.approx(2.0)
        assert data['total_weight'] == 0.0

    def test_weight_and_volume_never_share_a_sum(
        self, client, auth_headers, test_storage_location, db_session
    ):
        litre = self._litre(db_session)
        _create_item(
            client,
            auth_headers,
            test_storage_location.id,
            name='Mleko 2%',
            quantity=2,
            uom_id=str(litre.id),
        )
        # A weighed line: 3 x 500 g = 1.5 kg.
        _create_item(
            client,
            auth_headers,
            test_storage_location.id,
            name='Flour 500 g',
            quantity=3,
            weight_value=500.0,
        )

        data = _aggregates(client, auth_headers)

        assert data['total_weight'] == pytest.approx(1.5)
        assert data['total_volume'] == pytest.approx(2.0)


def _reprice(client, auth_headers, item, price):
    response = client.put(
        f'/api/v1/items/{item["id"]}',
        headers=auth_headers,
        json={'purchase_price': price},
    )
    assert response.status_code == status.HTTP_200_OK, response.text


def _aggregates(client, auth_headers, **params):
    response = client.get(
        '/api/v1/items/aggregates', headers=auth_headers, params=params
    )
    assert response.status_code == status.HTTP_200_OK, response.text
    return response.json()


class TestTheFooterNamesItsSource:
    """The footer's value comes from the same place the statistics read.

    The list stands on the module's front screen, beside "Stock on a date"
    and "Statistics" — both of which read the cost ledger. The footer used
    to read the price typed on the record instead, so a delivery posted by
    document changed the ledger and left the footer where it was, while a
    typo corrected on a card moved the footer and left the ledger alone.

    That holds for the whole organization. A filtered slice gets no ledger
    figure at all — the layers know products, not shelves.
    """

    def test_module_scoping_alone_keeps_the_ledger_value(
        self, client, auth_headers, test_storage_location
    ):
        """The default list request excludes other modules' items — that is
        scoping, not a filter, and the ledger figure stays.

        A freshly onboarded organization sends exclude_module_contexts on
        every list call without the reader touching a filter; withholding
        the value there turned the footer into a number-less sentence
        beside a statistics tile that shows the figure."""
        _create_item(
            client,
            auth_headers,
            test_storage_location.id,
            name='Cocoa',
            quantity=3,
            purchase_price=4.50,
        )
        overview = client.get('/api/v1/stats/overview', headers=auth_headers)
        assert overview.status_code == status.HTTP_200_OK
        ledger_value = overview.json()['total_value']
        assert ledger_value is not None

        data = _aggregates(client, auth_headers, exclude_module_contexts='true')

        assert data['value_source'] == 'valuation_layers'
        assert data['total_value'] == pytest.approx(ledger_value)
        # The scoping is active on every default list call, but this
        # organization owns no module-claimed record — nothing was removed,
        # and a sentence claiming a slice would stand under a full total
        # forever. The flag comes from the query's own result.
        assert data['excludes_module_items'] is False

    def test_the_slice_names_the_module_items_it_leaves_out(
        self, client, auth_headers, test_storage_location, db_session
    ):
        """The footer and the statistics tile declare the same book and used
        to disagree in silence: the list's default view leaves the items a
        vertical module owns to that module, while the tile sums the whole
        ledger. The difference is real money — the footer says what it is
        made of."""
        from app.models.category import Category

        claimed = Category(
            name='Laptop',
            code='LAPTOP-CLAIMED',
            context_tag='equipment',
            organization_id=None,
            field_definitions=[],
        )
        db_session.add(claimed)
        db_session.commit()
        db_session.refresh(claimed)

        _create_item(
            client,
            auth_headers,
            test_storage_location.id,
            name='Flour',
            quantity=2,
            purchase_price=3.00,
        )
        _create_item(
            client,
            auth_headers,
            test_storage_location.id,
            name='ThinkPad',
            quantity=1,
            purchase_price=100.00,
            category_id=str(claimed.id),
        )

        # An organization that shows module data in its lists: the tile
        # counts the laptop, a list asked to hide it does not.
        org = test_storage_location.organization
        org.settings = {**(org.settings or {}), 'show_module_data': True}
        db_session.commit()

        data = _aggregates(client, auth_headers, exclude_module_contexts='true')

        # The claimed laptop (100.00) is out of the list's sum; the flag
        # says the sum is a slice, not the book the tile sums.
        assert data['excludes_module_items'] is True
        assert data['total_value'] == pytest.approx(6.0)

        tile = client.get('/api/v1/stats/overview', headers=auth_headers)
        assert tile.json()['total_value'] == pytest.approx(106.0)

    def test_where_the_organization_hides_module_data_the_two_agree(
        self, client, auth_headers, test_storage_location, db_session
    ):
        """The statistics follow the organization's setting too, so with
        module data hidden the tile leaves the laptop out as the list does:
        the same figure, and no sentence claiming the tile counts it."""
        from app.models.category import Category

        claimed = Category(
            name='Laptop',
            code='LAPTOP-CLAIMED-AGREE',
            context_tag='equipment',
            organization_id=None,
            field_definitions=[],
        )
        db_session.add(claimed)
        db_session.commit()
        db_session.refresh(claimed)
        _create_item(
            client,
            auth_headers,
            test_storage_location.id,
            name='Flour',
            quantity=2,
            purchase_price=3.00,
        )
        _create_item(
            client,
            auth_headers,
            test_storage_location.id,
            name='ThinkPad',
            quantity=1,
            purchase_price=100.00,
            category_id=str(claimed.id),
        )

        data = _aggregates(client, auth_headers, exclude_module_contexts='true')
        tile = client.get('/api/v1/stats/overview', headers=auth_headers)

        assert data['total_value'] == pytest.approx(6.0)
        assert tile.json()['total_value'] == pytest.approx(6.0)
        assert data['excludes_module_items'] is False

    def test_under_a_filter_the_difference_belongs_to_the_filter(
        self, client, auth_headers, test_storage_location, db_session
    ):
        """With a filter on, the footer's figure differs from the tile by
        the filter's doing; a sentence about modules would point the
        reader the wrong way, so it stands down even though the scoping
        removed the same records."""
        from app.models.category import Category

        claimed = Category(
            name='Laptop',
            code='LAPTOP-CLAIMED-FILTER',
            context_tag='equipment',
            organization_id=None,
            field_definitions=[],
        )
        db_session.add(claimed)
        db_session.commit()
        db_session.refresh(claimed)

        _create_item(
            client,
            auth_headers,
            test_storage_location.id,
            name='Flour',
            quantity=2,
            purchase_price=3.00,
        )
        _create_item(
            client,
            auth_headers,
            test_storage_location.id,
            name='ThinkPad',
            quantity=1,
            purchase_price=100.00,
            category_id=str(claimed.id),
        )

        data = _aggregates(
            client,
            auth_headers,
            exclude_module_contexts='true',
            search='Flour',
        )

        assert data['count'] == 1
        assert data['excludes_module_items'] is False

    def test_a_ledger_organization_values_its_list_from_the_layers(
        self, client, auth_headers, test_storage_location
    ):
        item = _create_item(
            client,
            auth_headers,
            test_storage_location.id,
            name='Cocoa',
            quantity=3,
            purchase_price=4.50,
        )
        # The receipt posted a layer: 3 x 4.50 = 13.50 on the shelf.
        assert _aggregates(client, auth_headers)['total_value'] == pytest.approx(13.5)

        # Correcting the card's price is not a purchase, so it does not
        # change what the stock cost.
        _reprice(client, auth_headers, item, '100.00')

        data = _aggregates(client, auth_headers)
        assert data['value_source'] == 'valuation_layers'
        assert data['total_value'] == pytest.approx(13.5)
        assert data['unpriced_count'] == 0

    def test_records_without_a_cost_history_are_counted_out_loud(
        self, client, auth_headers, test_storage_location
    ):
        _create_item(
            client,
            auth_headers,
            test_storage_location.id,
            name='Priced',
            quantity=2,
            purchase_price=3.00,
        )
        _create_item(
            client, auth_headers, test_storage_location.id, name='Unpriced', quantity=5
        )

        data = _aggregates(client, auth_headers)

        assert data['count'] == 2
        assert data['total_value'] == pytest.approx(6.0)
        # One record the ledger never priced — left out of the sum, and
        # said so, rather than summed as if it were worth nothing.
        assert data['unpriced_count'] == 1

    def test_a_filtered_slice_claims_no_ledger_value(
        self, client, auth_headers, test_storage_location, db_session
    ):
        """The layers know products, not shelves, so the
        ledger rates are organization-wide. Pricing a filtered slice with
        them priced stock lying on one shelf at a rate earned by a receipt
        into another warehouse — a figure no screen could trace. Under a
        filter the ledger value is withheld and the response says so."""
        from app.models.storage_location import StorageLocation

        other = StorageLocation(
            organization_id=test_storage_location.organization_id,
            created_by=test_storage_location.created_by,
            storage_type_id=test_storage_location.storage_type_id,
            name='Pantry',
        )
        db_session.add(other)
        db_session.commit()

        _create_item(
            client,
            auth_headers,
            test_storage_location.id,
            name='Here',
            quantity=2,
            purchase_price=3.00,
        )
        _create_item(
            client,
            auth_headers,
            other.id,
            name='There',
            quantity=1,
            purchase_price=7.00,
        )

        # Unfiltered, the footer reads the ledger: 2 x 3.00 + 1 x 7.00 —
        # the same figure the statistics tile shows for the organization.
        whole = _aggregates(client, auth_headers)
        assert whole['total_value'] == pytest.approx(13.0)
        assert whole['value_source'] == 'valuation_layers'

        # Under a filter, no ledger value is claimed at all — not the
        # shelf's stock at the organization's rates, not zero either.
        data = _aggregates(client, auth_headers, location_id=str(other.id))

        assert data['count'] == 1
        assert data['total_value'] is None
        assert data['value_source'] == 'not_available_under_filter'
        assert data['unpriced_count'] == 0

    def test_a_records_valued_organization_still_prices_a_filtered_slice(
        self, client, auth_headers, test_storage_location, test_household, db_session
    ):
        """The withholding is the ledger's limitation, not the filter's:
        where the value is read off the records themselves, the price sits
        on the very rows the filter keeps, and the slice gets its number."""
        test_household.enabled_modules = ['core', 'items', 'locations']
        db_session.commit()

        from app.models.storage_location import StorageLocation

        _create_item(
            client,
            auth_headers,
            test_storage_location.id,
            name='Here',
            quantity=2,
            purchase_price=3.00,
        )
        other = StorageLocation(
            organization_id=test_storage_location.organization_id,
            created_by=test_storage_location.created_by,
            storage_type_id=test_storage_location.storage_type_id,
            name='Pantry',
        )
        db_session.add(other)
        db_session.commit()
        _create_item(
            client,
            auth_headers,
            other.id,
            name='There',
            quantity=4,
            purchase_price=2.00,
        )

        data = _aggregates(client, auth_headers, location_id=str(other.id))

        assert data['count'] == 1
        assert data['value_source'] == 'purchase_price'
        assert data['total_value'] == pytest.approx(8.0)

    def test_card_quantity_the_ledger_never_received_is_not_priced(
        self,
        client,
        auth_headers,
        test_storage_location,
        db_session,
    ):
        """The footer priced card stock at the template's ledger
        rate, so stock that arrived without a priced receipt — a count
        overwrite, a production run, a hand-made record — added value
        nobody's ledger held, and the footer disagreed with the statistics
        tile by exactly that invented amount."""
        first = _create_item(
            client,
            auth_headers,
            test_storage_location.id,
            name='Yoghurt',
            quantity=5,
            purchase_price=7.25,
        )
        second = _create_item(
            client,
            auth_headers,
            test_storage_location.id,
            name='Yoghurt',
            quantity=3,
            template_id=first['template_id'],
            purchase_price=7.25,
        )
        # A count overwrite (the stock-take close, a production run, an
        # import) moves the card without the ledger. Done here the way
        # those paths leave the data: the card says eleven, the ledger
        # still holds the eight received units. The six units nobody
        # received used to be priced at the received rate.
        from sqlalchemy import update as _update

        db_session.execute(
            _update(Item).where(Item.id == second['id']).values(quantity=11)
        )
        db_session.commit()

        data = _aggregates(client, auth_headers)

        assert data['count'] == 2
        # The ledger holds eight received at 7.25: 58.00 — the same figure
        # the statistics tile reads. The three card units nobody received
        # no longer ride the received rate.
        assert data['total_value'] == pytest.approx(58.0)
        assert data['value_source'] == 'valuation_layers'

    def test_an_organization_without_a_ledger_values_its_list_from_the_records(
        self, client, auth_headers, test_storage_location, test_household, db_session
    ):
        # No StockQuant-consuming module: no cost ledger, so the price on
        # the record is the only figure there is — and the footer says so.
        test_household.enabled_modules = ['core', 'items', 'locations']
        db_session.commit()

        item = _create_item(
            client,
            auth_headers,
            test_storage_location.id,
            name='Priced',
            quantity=2,
            purchase_price=3.00,
        )
        _create_item(
            client, auth_headers, test_storage_location.id, name='Unpriced', quantity=1
        )
        _reprice(client, auth_headers, item, '4.00')

        data = _aggregates(client, auth_headers)

        assert data['value_source'] == 'purchase_price'
        assert data['total_value'] == pytest.approx(8.0)
        assert data['unpriced_count'] == 1


class TestTheFooterNamesEveryReasonItIsSmaller:
    """Two reasons the footer is below the tile, and both have to be said.

    The tile sums the cost ledger; the footer clamps each product to what
    the list can see (`least(cards, ledger)`), so a layer whose product has
    no record on this list contributes to one number and not the other. The
    module sentence used to be the footer's only explanation — and with a
    layer like that in the book it accounted for part of the gap while
    implying it accounted for all of it.
    """

    def test_a_layer_whose_product_has_no_record_is_named(
        self, client, auth_headers, test_storage_location, db_session, test_household
    ):
        from decimal import Decimal

        from app.models.product_template import ProductTemplate
        from app.models.stock_valuation_layer import CostBasis, StockValuationLayer

        _create_item(
            client,
            auth_headers,
            test_storage_location.id,
            name='Flour',
            quantity=2,
            purchase_price=3.00,
        )

        orphan = ProductTemplate(organization_id=test_household.id, name='Ghost stock')
        db_session.add(orphan)
        db_session.flush()
        db_session.add(
            StockValuationLayer(
                organization_id=test_household.id,
                product_template_id=orphan.id,
                quantity=Decimal('1'),
                remaining_qty=Decimal('1'),
                unit_cost=Decimal('100.00'),
                total_value=Decimal('100.00'),
                direction='IN',
                cost_basis=CostBasis.STATED,
            )
        )
        db_session.commit()

        data = _aggregates(client, auth_headers)

        assert data['total_value'] == pytest.approx(6.0)
        assert data['excludes_unlisted_layers'] is True, (
            'the tile counts 100.00 the footer cannot show, and the footer '
            'said nothing about it'
        )

    def test_a_book_the_list_can_show_whole_says_nothing(
        self, client, auth_headers, test_storage_location
    ):
        _create_item(
            client,
            auth_headers,
            test_storage_location.id,
            name='Flour',
            quantity=2,
            purchase_price=3.00,
        )

        data = _aggregates(client, auth_headers)

        assert data['excludes_unlisted_layers'] is False

    def test_under_a_filter_the_difference_belongs_to_the_filter_too(
        self, client, auth_headers, test_storage_location, db_session, test_household
    ):
        """Same rule as the module sentence: under a filter the footer is
        smaller because of the filter, and a sentence about the ledger would
        point the reader somewhere else."""
        from decimal import Decimal

        from app.models.product_template import ProductTemplate
        from app.models.stock_valuation_layer import CostBasis, StockValuationLayer

        _create_item(
            client,
            auth_headers,
            test_storage_location.id,
            name='Flour',
            quantity=2,
            purchase_price=3.00,
        )
        orphan = ProductTemplate(organization_id=test_household.id, name='Ghost stock')
        db_session.add(orphan)
        db_session.flush()
        db_session.add(
            StockValuationLayer(
                organization_id=test_household.id,
                product_template_id=orphan.id,
                quantity=Decimal('1'),
                remaining_qty=Decimal('1'),
                unit_cost=Decimal('100.00'),
                total_value=Decimal('100.00'),
                direction='IN',
                cost_basis=CostBasis.STATED,
            )
        )
        db_session.commit()

        data = _aggregates(client, auth_headers, search='Flour')

        assert data['excludes_unlisted_layers'] is False

    def _claimed_laptop_category(self, db_session):
        from app.models.category import Category

        claimed = Category(
            name='Laptop',
            code='LAPTOP-CLAIMED',
            context_tag='equipment',
            organization_id=None,
            field_definitions=[],
        )
        db_session.add(claimed)
        db_session.commit()
        db_session.refresh(claimed)
        return claimed

    def _tile_counts_module_data(self, db_session, organization):
        """The statistics tile counts module data only where the
        organization shows it; the module sentence is about that case."""
        organization.settings = {
            **(organization.settings or {}),
            'show_module_data': True,
        }
        db_session.commit()

    def _open_layer_for(self, db_session, organization_id, template_id):
        from decimal import Decimal

        from app.models.stock_valuation_layer import CostBasis, StockValuationLayer

        db_session.add(
            StockValuationLayer(
                organization_id=organization_id,
                product_template_id=template_id,
                quantity=Decimal('1'),
                remaining_qty=Decimal('1'),
                unit_cost=Decimal('100.00'),
                total_value=Decimal('100.00'),
                direction='IN',
                cost_basis=CostBasis.STATED,
            )
        )
        db_session.commit()

    def test_a_module_claimed_product_is_not_also_an_unlisted_layer(
        self, client, auth_headers, test_storage_location, db_session, test_household
    ):
        """The scoping hid the laptop and the module sentence named it; the
        layer predicate inherited the same hiding through the list of
        listed templates, so the product's ledger layer lit the layer
        sentence too — two explanations pointing at one 100.00, and a
        reader adding them up charged the laptop twice. Hiding by module
        scoping is the module sentence's money alone."""
        self._tile_counts_module_data(db_session, test_household)
        claimed = self._claimed_laptop_category(db_session)
        item = _create_item(
            client,
            auth_headers,
            test_storage_location.id,
            name='ThinkPad',
            quantity=1,
            purchase_price=100.00,
            category_id=str(claimed.id),
        )
        self._open_layer_for(db_session, test_household.id, item['template_id'])

        data = _aggregates(client, auth_headers, exclude_module_contexts='true')

        assert data['excludes_module_items'] is True
        assert data['excludes_unlisted_layers'] is False, (
            'the module sentence already accounts for this 100.00; lighting '
            'the layer sentence for it makes a reader count it twice'
        )

    def test_module_money_and_cardless_money_are_named_separately(
        self, client, auth_headers, test_storage_location, db_session, test_household
    ):
        """Both sentences stay, each owning its own money: the claimed
        laptop belongs to the module sentence, the ghost template's layer
        to the layer sentence — no amount is left unexplained and none is
        named twice. Green on the pre-fix behaviour as well; it pins the
        arrangement the fix must not break."""
        from app.models.product_template import ProductTemplate

        self._tile_counts_module_data(db_session, test_household)
        claimed = self._claimed_laptop_category(db_session)
        item = _create_item(
            client,
            auth_headers,
            test_storage_location.id,
            name='ThinkPad',
            quantity=1,
            purchase_price=100.00,
            category_id=str(claimed.id),
        )
        self._open_layer_for(db_session, test_household.id, item['template_id'])

        ghost = ProductTemplate(organization_id=test_household.id, name='Ghost stock')
        db_session.add(ghost)
        db_session.flush()
        self._open_layer_for(db_session, test_household.id, ghost.id)

        data = _aggregates(client, auth_headers, exclude_module_contexts='true')

        assert data['excludes_module_items'] is True
        assert data['excludes_unlisted_layers'] is True

    def test_without_module_scoping_a_claimed_product_is_just_listed(
        self, client, auth_headers, test_storage_location, db_session, test_household
    ):
        """The same shelf read without the module scoping lists the laptop
        with everything else — neither sentence has anything to own, and
        the layer on the claimed product is money the footer already
        shows. Green on the pre-fix behaviour as well; it pins the
        off-side of the grid."""
        claimed = self._claimed_laptop_category(db_session)
        item = _create_item(
            client,
            auth_headers,
            test_storage_location.id,
            name='ThinkPad',
            quantity=1,
            purchase_price=100.00,
            category_id=str(claimed.id),
        )
        self._open_layer_for(db_session, test_household.id, item['template_id'])

        data = _aggregates(client, auth_headers)

        assert data['excludes_module_items'] is False
        assert data['excludes_unlisted_layers'] is False


class TestWideningKeepsTheLedgerValue:
    """A value that only ADDS rows beyond the default view keeps the figure.

    The withholding decision read every difference from the
    default view as a filter, so an empty ``location_usage`` — which drops
    the usage clause and only widens the set — refused the ledger value
    for a screen whose rows were the default view's rows exactly. The
    refusal is for values that REMOVE rows; a widening keeps the figure,
    because the rates price products and every product in the wider set
    still belongs to this organization.
    """

    def _customer_location(self, db_session, test_storage_location):
        from app.models.storage_location import StorageLocation

        customer = StorageLocation(
            organization_id=test_storage_location.organization_id,
            created_by=test_storage_location.created_by,
            storage_type_id=test_storage_location.storage_type_id,
            name='Shipped out',
            usage='customer',
        )
        db_session.add(customer)
        db_session.commit()
        return customer

    def _record_outside_the_default_view(self, db_session, location, item, **fields):
        """A record the default view does not hold: its anchor first, then
        the row — the API's own write path would file it under the same
        group, so the test builds the group by hand."""
        from app.models.item import Item as ItemModel
        from app.models.stock_anchor import StockAnchor

        db_session.add(
            StockAnchor(
                organization_id=location.organization_id,
                product_template_id=item['template_id'],
                storage_location_id=location.id,
            )
        )
        # Two commits: the unit of work flushes independent tables in its
        # own order, and the record's anchor has to be on disk before the
        # foreign key pointing at it is checked.
        db_session.commit()
        db_session.add(
            ItemModel(
                organization_id=location.organization_id,
                storage_location_id=location.id,
                template_id=item['template_id'],
                name=fields.pop('name'),
                **fields,
            )
        )
        db_session.commit()

    def test_an_empty_usage_value_answers_what_the_default_view_answers(
        self, client, auth_headers, test_storage_location
    ):
        """The reporter's walkthrough: all stock internal, one parameter
        sent empty — the same rows, so the same footer, valuation
        included."""
        _create_item(
            client,
            auth_headers,
            test_storage_location.id,
            name='Freezer peas',
            quantity=2,
            purchase_price=5.00,
        )
        _create_item(
            client,
            auth_headers,
            test_storage_location.id,
            name='Pantry rice',
            quantity=4,
            purchase_price=2.00,
        )

        default_view = _aggregates(client, auth_headers)
        empty_usage = _aggregates(client, auth_headers, location_usage='')

        for key in (
            'count',
            'total_weight',
            'total_volume',
            'total_value',
            'value_source',
            'unpriced_count',
        ):
            assert empty_usage[key] == default_view[key], (
                f'`{key}` differs between the default view and an empty '
                'location_usage — an empty value only drops the usage '
                'clause, so the answer must not change on all-internal '
                'stock.'
            )
        assert empty_usage['value_source'] == 'valuation_layers'

    def test_a_wider_usage_prices_the_wider_set_a_narrower_one_refuses(
        self,
        client,
        auth_headers,
        test_storage_location,
        db_session,
    ):
        """Same product on both sides of the usage split: the widened set
        keeps the ledger figure (clamped to what the layers hold), the
        narrowed one gets the refusal the filters get."""
        item = _create_item(
            client,
            auth_headers,
            test_storage_location.id,
            name='Flour',
            quantity=1,
            purchase_price=100.00,
        )
        # The receipt the API's own create posts is the layer: one unit
        # received at 100.00, so the wider cards are clamped to one unit
        # of ledger money.
        customer = self._customer_location(db_session, test_storage_location)
        self._record_outside_the_default_view(
            db_session, customer, item, name='Flour, shipped', quantity=2
        )

        wider = _aggregates(client, auth_headers, location_usage='')

        assert wider['count'] == 2
        assert wider['value_source'] == 'valuation_layers'
        # The reconciliation clamps each product to the layers on hand:
        # one unit received, one unit priced — the wider cards cannot
        # invent money the ledger never held.
        assert wider['total_value'] == pytest.approx(100.0)

        narrower = _aggregates(client, auth_headers, location_usage='customer')

        assert narrower['count'] == 1
        assert narrower['total_value'] is None
        assert narrower['value_source'] == 'not_available_under_filter'

    def test_the_emptied_records_widen_the_count_not_the_refusal(
        self,
        client,
        auth_headers,
        test_storage_location,
        db_session,
    ):
        """include_empty adds the emptied records wherever they sit — rows
        the default view does not hold, added without removing any, so the
        figure stands beside a wider count."""
        item = _create_item(
            client,
            auth_headers,
            test_storage_location.id,
            name='Olive oil',
            quantity=1,
            purchase_price=100.00,
        )
        customer = self._customer_location(db_session, test_storage_location)
        self._record_outside_the_default_view(
            db_session, customer, item, name='Olive oil, used up', quantity=0
        )

        data = _aggregates(client, auth_headers, include_empty='true')

        assert data['count'] == 2
        assert data['value_source'] == 'valuation_layers'
        assert data['total_value'] == pytest.approx(100.0)
