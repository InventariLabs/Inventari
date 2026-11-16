"""A made product's ingredient list, allergens and nutrition come from its recipe.

EU Regulation 1169/2011 asks a food producer for the ingredients in
descending order of weight as used, a compound ingredient's own ingredients
in brackets, the allergens emphasised and, where given, a nutrition
declaration per 100 g. A product's card carries the 14 allergens, a
may-contain list and the name it goes under in a list; the recipe computes
the rest from its ingredients' cards, every level down.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from decimal import Decimal
from typing import Any, get_args

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.audit_log import AuditLog
from app.models.organization import Organization
from app.models.product_template import ProductTemplate
from app.models.uom import Uom
from app.modules.maker._schemas_labelling import AllergenKey
from app.modules.maker.models import BoMLine, MakerRecipe
from app.modules.recipes.recipes_api import recipes_api

pytestmark = pytest.mark.integration

FACTS = '/api/v1/maker/labelling/products'
LABEL = '/api/v1/maker/labelling/recipes'


def _uom(db: Session, symbol: str) -> Uom:
    uom = db.scalars(select(Uom).where(Uom.symbol == symbol)).first()
    assert uom is not None, f'the seed has no {symbol!r} unit'
    return uom


def _product(
    db: Session,
    org: Organization,
    name: str,
    *,
    uom: Uom,
    nutrition: Mapping[str, float] | None = None,
    weight: tuple[str, Uom] | None = None,
) -> ProductTemplate:
    template = ProductTemplate(
        organization_id=org.id,
        name=name,
        sku=f'SKU-{uuid.uuid4().hex[:8]}',
        uom_id=uom.id,
        meta_data={'nutrition': dict(nutrition)} if nutrition else None,
        weight_value=Decimal(weight[0]) if weight else None,
        weight_uom_id=weight[1].id if weight else None,
    )
    db.add(template)
    db.flush()
    return template


def _recipe(
    db: Session,
    org: Organization,
    output: ProductTemplate,
    lines: list[tuple[ProductTemplate, str, Uom, str]],
    *,
    yield_qty: str,
    yield_uom: Uom,
) -> MakerRecipe:
    """A default recipe; each line is (ingredient, qty, unit, loss %)."""
    recipe = MakerRecipe(
        organization_id=org.id,
        output_template_id=output.id,
        name=f'{output.name} batch',
        batch_yield_qty=Decimal(yield_qty),
        batch_yield_uom_id=yield_uom.id,
        is_default=True,
    )
    db.add(recipe)
    db.flush()
    for child, qty, uom, loss in lines:
        db.add(
            BoMLine(
                organization_id=org.id,
                recipe_id=recipe.id,
                parent_template_id=output.id,
                child_template_id=child.id,
                qty_per_batch=Decimal(qty),
                uom_id=uom.id,
                unit=uom.symbol,
                yield_loss_pct=Decimal(loss),
            )
        )
    db.commit()
    return recipe


def _facts(
    client: TestClient,
    headers: dict[str, str],
    product: ProductTemplate,
    **body: Any,
) -> dict[str, Any]:
    response = client.put(f'{FACTS}/{product.id}', headers=headers, json=body)
    assert response.status_code == 200, response.text
    return dict(response.json())


def _label(
    client: TestClient, headers: dict[str, str], recipe: MakerRecipe
) -> dict[str, Any]:
    response = client.get(f'{LABEL}/{recipe.id}', headers=headers)
    assert response.status_code == 200, response.text
    return dict(response.json())


def _names(entries: list[dict[str, Any]]) -> list[str]:
    return [entry['name'] for entry in entries]


class TestTheProductCardCarriesItsAllergens:
    def test_a_name_suggests_and_a_person_confirms(
        self,
        client: TestClient,
        db_session: Session,
        mk_org: Organization,
        mk_auth_headers: dict[str, str],
    ) -> None:
        butter = _product(db_session, mk_org, 'Butter', uom=_uom(db_session, 'g'))
        db_session.commit()

        # Fails without the change: the endpoint does not exist (404).
        unchecked = client.get(f'{FACTS}/{butter.id}', headers=mk_auth_headers)
        assert unchecked.status_code == 200, unchecked.text
        assert unchecked.json()['allergens'] is None
        assert unchecked.json()['suggested_allergens'] == ['milk']

        saved = _facts(
            client,
            mk_auth_headers,
            butter,
            allergens=['milk'],
            may_contain=['nuts', 'gluten'],
            label_name='Butter (cream, salt)',
        )
        assert saved['allergens'] == ['milk']
        # Kept in the regulation's order, whatever order they were ticked in.
        assert saved['may_contain'] == ['gluten', 'nuts']
        assert saved['label_name'] == 'Butter (cream, salt)'

        entry = db_session.scalars(
            select(AuditLog).where(AuditLog.target_id == butter.id)
        ).one()
        assert entry.snapshot is not None
        assert entry.snapshot['before']['allergens'] is None
        assert entry.snapshot['after']['allergens'] == ['milk']

    def test_checked_and_none_is_not_unchecked(
        self,
        client: TestClient,
        db_session: Session,
        mk_org: Organization,
        mk_auth_headers: dict[str, str],
    ) -> None:
        water = _product(db_session, mk_org, 'Water', uom=_uom(db_session, 'g'))
        db_session.commit()
        assert _facts(client, mk_auth_headers, water, allergens=[])['allergens'] == []

    def test_the_schema_knows_the_same_allergens_as_the_inference(self) -> None:
        # The request schema spells the 14 keys out; they must stay the ones
        # the culinary inference suggests and the screens name.
        assert get_args(AllergenKey) == recipes_api.ALLERGEN_KEYS

    def test_an_unknown_allergen_is_refused(
        self,
        client: TestClient,
        db_session: Session,
        mk_org: Organization,
        mk_auth_headers: dict[str, str],
    ) -> None:
        water = _product(db_session, mk_org, 'Water', uom=_uom(db_session, 'g'))
        db_session.commit()
        response = client.put(
            f'{FACTS}/{water.id}',
            headers=mk_auth_headers,
            json={'allergens': ['chocolate']},
        )
        assert response.status_code == 422


class TestTheIngredientList:
    def test_heaviest_first_as_used_and_ties_by_name(
        self,
        client: TestClient,
        db_session: Session,
        mk_org: Organization,
        mk_auth_headers: dict[str, str],
    ) -> None:
        g, kg = _uom(db_session, 'g'), _uom(db_session, 'kg')
        flour = _product(db_session, mk_org, 'Flour', uom=kg)
        water = _product(db_session, mk_org, 'Water', uom=g)
        sugar = _product(db_session, mk_org, 'Sugar', uom=g)
        yeast = _product(db_session, mk_org, 'Yeast', uom=g)
        salt = _product(db_session, mk_org, 'Salt', uom=g)
        bread = _product(db_session, mk_org, 'Bread', uom=g)
        recipe = _recipe(
            db_session,
            mk_org,
            bread,
            [
                (water, '300', g, '0'),
                # 280 g with a tenth lost on the way is 308 g used: above the
                # water, though less is written on the line.
                (sugar, '280', g, '10'),
                (flour, '0.5', kg, '0'),
                (yeast, '10', g, '0'),
                (salt, '10', g, '0'),
            ],
            yield_qty='900',
            yield_uom=g,
        )

        label = _label(client, mk_auth_headers, recipe)

        # Equal weights by name: Salt before Yeast, whichever was added first.
        assert _names(label['ingredients']) == [
            'Flour',
            'Sugar',
            'Water',
            'Salt',
            'Yeast',
        ]
        assert [i['weight_g'] for i in label['ingredients']] == [
            '500.00',
            '308.00',
            '300.00',
            '10.00',
            '10.00',
        ]
        assert label['yield_weight_g'] == '900.00'

    def test_a_made_ingredient_is_listed_with_its_own_in_brackets(
        self,
        client: TestClient,
        db_session: Session,
        mk_org: Organization,
        mk_auth_headers: dict[str, str],
    ) -> None:
        g = _uom(db_session, 'g')
        flour = _product(db_session, mk_org, 'Flour T550', uom=g)
        butter = _product(db_session, mk_org, 'Butter', uom=g)
        plums = _product(db_session, mk_org, 'Plums', uom=g)
        dough = _product(db_session, mk_org, 'Dough', uom=g)
        cake = _product(db_session, mk_org, 'Plum cake', uom=g)
        _recipe(
            db_session,
            mk_org,
            dough,
            [(butter, '100', g, '0'), (flour, '200', g, '0')],
            yield_qty='300',
            yield_uom=g,
        )
        recipe = _recipe(
            db_session,
            mk_org,
            cake,
            [(plums, '400', g, '0'), (dough, '600', g, '0')],
            yield_qty='900',
            yield_uom=g,
        )
        _facts(
            client,
            mk_auth_headers,
            flour,
            label_name='Wheat flour',
            allergens=['gluten'],
        )
        _facts(client, mk_auth_headers, butter, allergens=['milk'])
        _facts(client, mk_auth_headers, plums, allergens=[])
        # Declared on the cake itself, brought by no ingredient: kept.
        _facts(client, mk_auth_headers, cake, allergens=['sesame'])

        label = _label(client, mk_auth_headers, recipe)

        assert _names(label['ingredients']) == ['Dough', 'Plums']
        dough_entry = label['ingredients'][0]
        assert _names(dough_entry['children']) == ['Wheat flour', 'Butter']
        assert [c['emphasised'] for c in dough_entry['children']] == [True, True]
        assert label['ingredients'][1]['emphasised'] is False
        assert label['text'] == (
            'Ingredients: Dough (WHEAT FLOUR, BUTTER), Plums. Contains: SESAME.'
        )

        allergens = {a['allergen']: a for a in label['allergens']}
        assert list(allergens) == ['gluten', 'milk', 'sesame']
        assert _names(allergens['gluten']['sources']) == ['Wheat flour']
        assert _names(allergens['milk']['sources']) == ['Butter']
        assert allergens['sesame']['sources'] == []
        assert allergens['sesame']['declared_on_product'] is True
        assert label['unchecked'] == []

        # The cake's card shows the same allergens as derived, with what
        # brings each, beside the one it declares itself — and names the
        # formula it read them from, as a product may have several.
        card = client.get(f'{FACTS}/{cake.id}', headers=mk_auth_headers).json()
        assert card['recipe_id'] == str(recipe.id)
        assert card['recipe_name'] == 'Plum cake batch'
        assert card['allergens'] == ['sesame']
        assert [a['allergen'] for a in card['derived_allergens']] == [
            'gluten',
            'milk',
            'sesame',
        ]

    def test_may_contain_rolls_up_unless_the_product_contains_it(
        self,
        client: TestClient,
        db_session: Session,
        mk_org: Organization,
        mk_auth_headers: dict[str, str],
    ) -> None:
        g = _uom(db_session, 'g')
        chocolate = _product(db_session, mk_org, 'Chocolate', uom=g)
        cream = _product(db_session, mk_org, 'Cream', uom=g)
        truffles = _product(db_session, mk_org, 'Truffles', uom=g)
        recipe = _recipe(
            db_session,
            mk_org,
            truffles,
            [(chocolate, '300', g, '0'), (cream, '200', g, '0')],
            yield_qty='500',
            yield_uom=g,
        )
        _facts(
            client,
            mk_auth_headers,
            chocolate,
            allergens=['soy'],
            may_contain=['nuts', 'milk'],
        )
        _facts(client, mk_auth_headers, cream, allergens=['milk'])
        _facts(client, mk_auth_headers, truffles, may_contain=['peanuts'])

        label = _label(client, mk_auth_headers, recipe)

        may = {m['allergen']: m for m in label['may_contain']}
        # Milk is in the cream, so it is contained, not "may contain".
        assert list(may) == ['peanuts', 'nuts']
        assert _names(may['nuts']['sources']) == ['Chocolate']
        assert may['peanuts']['declared_on_product'] is True
        assert label['text'] == (
            'Ingredients: CHOCOLATE, CREAM. May contain: peanuts, nuts.'
        )

    def test_an_unchecked_ingredient_is_named_with_what_its_name_suggests(
        self,
        client: TestClient,
        db_session: Session,
        mk_org: Organization,
        mk_auth_headers: dict[str, str],
    ) -> None:
        g = _uom(db_session, 'g')
        milk = _product(db_session, mk_org, 'Milk 3.2%', uom=g)
        pudding = _product(db_session, mk_org, 'Pudding', uom=g)
        recipe = _recipe(
            db_session,
            mk_org,
            pudding,
            [(milk, '500', g, '0')],
            yield_qty='500',
            yield_uom=g,
        )

        label = _label(client, mk_auth_headers, recipe)

        assert label['unchecked'] == [
            {
                'template_id': str(milk.id),
                'name': 'Milk 3.2%',
                'suggested_allergens': ['milk'],
            }
        ]
        # A suggestion is not an allergen until a person confirms it.
        assert label['allergens'] == []

    def test_what_cannot_be_weighed_is_named_and_listed_last(
        self,
        client: TestClient,
        db_session: Session,
        mk_org: Organization,
        mk_auth_headers: dict[str, str],
    ) -> None:
        g, pcs = _uom(db_session, 'g'), _uom(db_session, 'pcs')
        eggs = _product(db_session, mk_org, 'Eggs', uom=pcs, weight=('60', g))
        vanilla = _product(db_session, mk_org, 'Vanilla pod', uom=pcs)
        sugar = _product(db_session, mk_org, 'Sugar', uom=g)
        custard = _product(db_session, mk_org, 'Custard', uom=g)
        recipe = _recipe(
            db_session,
            mk_org,
            custard,
            [(vanilla, '1', pcs, '0'), (sugar, '100', g, '0'), (eggs, '4', pcs, '0')],
            yield_qty='300',
            yield_uom=g,
        )

        label = _label(client, mk_auth_headers, recipe)

        # Four eggs of 60 g each are 240 g; nothing says what a pod weighs.
        assert _names(label['ingredients']) == ['Eggs', 'Sugar', 'Vanilla pod']
        assert label['ingredients'][0]['weight_g'] == '240.00'
        assert label['ingredients'][2]['weight_g'] is None
        assert _names(label['unweighed']) == ['Vanilla pod']


class TestTheNutritionDeclaration:
    def test_per_100_g_of_what_the_batch_yields(
        self,
        client: TestClient,
        db_session: Session,
        mk_org: Organization,
        mk_auth_headers: dict[str, str],
    ) -> None:
        g = _uom(db_session, 'g')
        flour = _product(
            db_session,
            mk_org,
            'Flour',
            uom=g,
            nutrition={
                'calories_kcal': 350,
                'fat_g': 1.2,
                'saturated_fat_g': 0.2,
                'carbs_g': 72,
                'sugar_g': 1.5,
                'protein_g': 10,
                'salt_g': 0,
            },
        )
        water = _product(
            db_session,
            mk_org,
            'Water',
            uom=g,
            nutrition={
                'calories_kcal': 0,
                'fat_g': 0,
                'saturated_fat_g': 0,
                'carbs_g': 0,
                'sugar_g': 0,
                'protein_g': 0,
                'salt_g': 0,
            },
        )
        bread = _product(db_session, mk_org, 'Bread', uom=g)
        # 600 g of flour and 400 g of water bake into 800 g of bread: the
        # water the oven takes concentrates what the flour put in.
        recipe = _recipe(
            db_session,
            mk_org,
            bread,
            [(flour, '600', g, '0'), (water, '400', g, '0')],
            yield_qty='800',
            yield_uom=g,
        )

        nutrition = _label(client, mk_auth_headers, recipe)['nutrition']

        assert nutrition['energy_kcal'] == '263'  # 350 * 600 / 800
        assert nutrition['energy_kj'] == '1098'  # 262.5 kcal * 4.184
        assert nutrition['fat'] == '0.9'
        assert nutrition['saturates'] == '0.2'  # 0.15
        assert nutrition['carbohydrate'] == '54.0'
        assert nutrition['sugars'] == '1.1'  # 1.125
        assert nutrition['protein'] == '7.5'
        assert nutrition['salt'] == '0.00'
        assert nutrition['missing'] == []

    def test_an_ingredient_without_figures_is_named_not_counted_as_zero(
        self,
        client: TestClient,
        db_session: Session,
        mk_org: Organization,
        mk_auth_headers: dict[str, str],
    ) -> None:
        g = _uom(db_session, 'g')
        flour = _product(
            db_session,
            mk_org,
            'Flour',
            uom=g,
            nutrition={'calories_kcal': 350, 'protein_g': 10},
        )
        seeds = _product(db_session, mk_org, 'Seeds', uom=g)
        bread = _product(db_session, mk_org, 'Seeded bread', uom=g)
        recipe = _recipe(
            db_session,
            mk_org,
            bread,
            [(flour, '500', g, '0'), (seeds, '50', g, '0')],
            yield_qty='500',
            yield_uom=g,
        )

        nutrition = _label(client, mk_auth_headers, recipe)['nutrition']

        assert nutrition['energy_kcal'] is None
        assert nutrition['protein'] is None
        missing = {m['name']: m['nutrients'] for m in nutrition['missing']}
        assert missing['Seeds'] == [
            'energy_kcal',
            'fat',
            'saturates',
            'carbohydrate',
            'sugars',
            'protein',
            'salt',
        ]
        assert missing['Flour'] == [
            'fat',
            'saturates',
            'carbohydrate',
            'sugars',
            'salt',
        ]

    def test_no_figures_at_all_gives_no_declaration(
        self,
        client: TestClient,
        db_session: Session,
        mk_org: Organization,
        mk_auth_headers: dict[str, str],
    ) -> None:
        g = _uom(db_session, 'g')
        sugar = _product(db_session, mk_org, 'Sugar', uom=g)
        syrup = _product(db_session, mk_org, 'Syrup', uom=g)
        recipe = _recipe(
            db_session,
            mk_org,
            syrup,
            [(sugar, '100', g, '0')],
            yield_qty='100',
            yield_uom=g,
        )
        assert _label(client, mk_auth_headers, recipe)['nutrition'] is None

    def test_a_two_level_recipe_reads_through_its_intermediate(
        self,
        client: TestClient,
        db_session: Session,
        mk_org: Organization,
        mk_auth_headers: dict[str, str],
    ) -> None:
        g = _uom(db_session, 'g')
        full = {
            'calories_kcal': 400,
            'fat_g': 10,
            'saturated_fat_g': 5,
            'carbs_g': 60,
            'sugar_g': 30,
            'protein_g': 8,
            'salt_g': 1,
        }
        base = _product(db_session, mk_org, 'Base mix', uom=g, nutrition=full)
        water = _product(
            db_session,
            mk_org,
            'Water',
            uom=g,
            nutrition=dict.fromkeys(full, 0),
        )
        batter = _product(db_session, mk_org, 'Batter', uom=g)
        waffles = _product(db_session, mk_org, 'Waffles', uom=g)
        # 500 g of mix and 500 g of water make 1000 g of batter; 1000 g of
        # batter bakes into 500 g of waffles.
        _recipe(
            db_session,
            mk_org,
            batter,
            [(base, '500', g, '0'), (water, '500', g, '0')],
            yield_qty='1000',
            yield_uom=g,
        )
        recipe = _recipe(
            db_session,
            mk_org,
            waffles,
            [(batter, '1000', g, '0')],
            yield_qty='500',
            yield_uom=g,
        )

        nutrition = _label(client, mk_auth_headers, recipe)['nutrition']

        # All of the 500 g of mix ends in 500 g of waffles: its own figures.
        assert nutrition['energy_kcal'] == '400'
        assert nutrition['sugars'] == '30.0'
        assert nutrition['salt'] == '1.00'
