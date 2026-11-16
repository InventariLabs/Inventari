"""What a made product's label says, computed from its recipe.

A product carries its label facts in this module (``maker_label_facts``): the
name it goes under in an ingredient list, the allergens a person confirmed it
contains and the ones it may contain. A made product's label is computed from
its recipe out of those facts on every ingredient, the way EU Regulation
1169/2011 asks a food producer to write it:

* the ingredients in descending order of weight as recorded at their use
  (Art. 18) — the line's quantity with its loss, because that is what goes
  into the bowl; equal weights are ordered by name, so the list does not move
  between two reads;
* an ingredient that is itself made, a compound ingredient, followed by its
  own ingredients in brackets (Annex VII, part E), each level ordered by its
  own weights;
* an ingredient whose card names an allergen emphasised (Art. 21), and every
  allergen of every level collected on the made product with the ingredients
  that bring it — an allergen declared on the made product itself is kept;
* the nutrition declaration per 100 g of the made product (Art. 30–33), from
  the ingredients' own figures: what the ingredients put in, divided by what
  the batch weighs when it comes out, so the water a bake loses concentrates
  the figures as it does in the product. An ingredient without a figure is
  named and the figure is not given, never counted as zero.

What cannot be weighed — a line in pieces of a product whose card says
nothing of what a piece weighs — is named and listed last: an order by weight
cannot place it. The result is the producer's to check; every screen says so.

Where another rule set plugs in: the label name is free text, so a cosmetics
maker writes an INCI name in it and the order by weight is INCI's own above
1 %. The allergens are the 14 of the food regulation, and the composing is the
food regulation's. A module with its own labelling rules (cosmetics, wine)
has no seam here yet: it would read the same facts and the same recipe tree
through ``maker_api`` and compose its own text, the way a module that dates
its output another way opens its own batches.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from uuid import UUID

from sqlalchemy import delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import ProductTemplateDTO, UomDTO
from app.core.db_utils import acquire_advisory_lock
from app.core.exceptions import EntityNotFoundError, ServiceRejectionError
from app.core.module_sdk import pick_by_lang
from app.core.public_api import core_api
from app.modules.recipes.recipes_api import recipes_api

from . import bom_service
from .models import MakerLabelFacts, MakerRecipe, ProductionOrder, ProductionPortion

#: The 14 allergens of the food regulation, in the order every list shows.
ALLERGEN_KEYS: tuple[str, ...] = recipes_api.ALLERGEN_KEYS

#: The declaration's figures and the product card's names for them (per 100 g).
NUTRIENTS: tuple[tuple[str, str], ...] = (
    ('energy_kcal', 'calories_kcal'),
    ('fat', 'fat_g'),
    ('saturates', 'saturated_fat_g'),
    ('carbohydrate', 'carbs_g'),
    ('sugars', 'sugar_g'),
    ('protein', 'protein_g'),
    ('salt', 'salt_g'),
)

#: Annex XIV: one kilocalorie is 4.184 kilojoules.
_KJ_PER_KCAL = Decimal('4.184')

#: How each declared figure is rounded: energy to a whole number, salt to a
#: hundredth (it is read in small amounts), the rest to a tenth of a gram.
_PLACES = {
    'energy_kj': Decimal('1'),
    'energy_kcal': Decimal('1'),
    'salt': Decimal('0.01'),
}


@dataclass(frozen=True)
class LabelFacts:
    """What one product's card says for its label."""

    label_name: str | None = None
    #: None: nobody has checked; an empty tuple: checked, none.
    allergens: tuple[str, ...] | None = None
    may_contain: tuple[str, ...] = ()


def ordered_allergens(keys: Iterable[str]) -> tuple[str, ...]:
    """*keys* once each, in the regulation's order."""
    wanted = set(keys)
    return tuple(key for key in ALLERGEN_KEYS if key in wanted)


def suggested_allergens(*names: str | None) -> tuple[str, ...]:
    """The allergens the names suggest, for a person to confirm."""
    return ordered_allergens(
        key for name in names if name for key in recipes_api.infer_allergens(name)
    )


async def facts_async(
    db: AsyncSession, organization_id: UUID, template_ids: Iterable[UUID]
) -> dict[UUID, LabelFacts]:
    """The label facts of each product that has any, batched."""
    ids = list(dict.fromkeys(template_ids))
    if not ids:
        return {}
    rows = await db.scalars(
        select(MakerLabelFacts).where(
            MakerLabelFacts.organization_id == organization_id,
            MakerLabelFacts.product_template_id.in_(ids),
        )
    )
    return {
        row.product_template_id: LabelFacts(
            label_name=row.label_name,
            allergens=None if row.allergens is None else tuple(row.allergens),
            may_contain=tuple(row.may_contain or ()),
        )
        for row in rows.all()
    }


async def set_facts_async(
    db: AsyncSession, organization_id: UUID, template_id: UUID, facts: LabelFacts
) -> LabelFacts:
    """Keep what the product's card says for its label; nothing said clears it.

    The product must be one the organization can see; the row is the
    organization's own either way.
    """
    template = await core_api.product_templates.get_async(
        db, organization_id, template_id
    )
    if template is None:
        raise EntityNotFoundError('product_template', str(template_id))
    facts = LabelFacts(
        label_name=(facts.label_name or '').strip() or None,
        allergens=None
        if facts.allergens is None
        else ordered_allergens(facts.allergens),
        may_contain=ordered_allergens(facts.may_contain),
    )
    # Two people saving the card at once is a lost update, not a second row.
    await acquire_advisory_lock(
        db, f'maker_label_facts:{organization_id}:{template_id}'
    )
    if facts == LabelFacts():
        await db.execute(
            delete(MakerLabelFacts).where(
                MakerLabelFacts.organization_id == organization_id,
                MakerLabelFacts.product_template_id == template_id,
            )
        )
        return facts
    row = (
        await db.execute(
            select(MakerLabelFacts)
            .where(
                MakerLabelFacts.organization_id == organization_id,
                MakerLabelFacts.product_template_id == template_id,
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if row is None:
        row = MakerLabelFacts(
            organization_id=organization_id, product_template_id=template_id
        )
        db.add(row)
    row.label_name = facts.label_name
    row.allergens = None if facts.allergens is None else list(facts.allergens)
    row.may_contain = list(facts.may_contain)
    await db.flush()
    return facts


@dataclass(frozen=True)
class _Units:
    """The organization's units and the gram every weight is read in."""

    by_id: dict[UUID, UomDTO]
    gram: UomDTO | None

    def grams(
        self, qty: Decimal, uom_id: UUID | None, template: ProductTemplateDTO | None
    ) -> Decimal | None:
        """*qty* of *template* in *uom_id* as grams, or None when nothing says.

        A line that names no unit counts in its product's own. A weight
        converts directly; anything else goes through what one unit of the
        product weighs, as its card states it — three 250 g loaves are 750 g.
        """
        if self.gram is None:
            return None
        stock = (
            self.by_id.get(template.uom_id) if template and template.uom_id else None
        )
        uom = self.by_id.get(uom_id) if uom_id is not None else stock
        if uom is None:
            return None
        weighed, ok = core_api.uoms.convert_quantity(qty, uom, self.gram)
        if ok:
            return weighed
        if template is None or stock is None or not template.weight_value:
            return None
        weight_uom = (
            self.by_id.get(template.weight_uom_id) if template.weight_uom_id else None
        )
        per_unit, ok = core_api.uoms.convert_quantity(
            Decimal(str(template.weight_value)), weight_uom, self.gram
        )
        in_stock, same = core_api.uoms.convert_quantity(qty, uom, stock)
        return in_stock * per_unit if ok and same else None


async def _units_async(db: AsyncSession, organization_id: UUID) -> _Units:
    uoms = await core_api.uoms.list_for_org_async(db, organization_id)
    gram = next((u for u in uoms if u.is_reference and u.symbol == 'g'), None)
    return _Units(by_id={u.id: u for u in uoms}, gram=gram)


@dataclass
class Ingredient:
    """One ingredient as its parent's recipe uses it, or the made product."""

    template_id: UUID
    #: The label name, else the product's own.
    name: str
    product_name: str
    #: What the parent's batch uses, loss included; None: it cannot be weighed.
    weight_g: Decimal | None
    facts: LabelFacts
    #: Its own recipe's ingredients when it is made, ordered as listed.
    children: list[Ingredient] = field(default_factory=list)
    #: What its own recipe's batch weighs when it comes out.
    yield_g: Decimal | None = None

    @property
    def emphasised(self) -> bool:
        """Whether its card names an allergen, so the list emphasises it."""
        return bool(self.facts.allergens)


def _order(ingredient: Ingredient) -> tuple[bool, Decimal, str, str]:
    """Heaviest first; equal weights by name; what cannot be weighed last."""
    weight = ingredient.weight_g
    return (
        weight is None,
        -(weight or Decimal('0')),
        ingredient.name.casefold(),
        str(ingredient.template_id),
    )


@dataclass(frozen=True)
class _Tree:
    templates: dict[UUID, ProductTemplateDTO]
    facts: dict[UUID, LabelFacts]
    units: _Units
    recipes: dict[UUID, MakerRecipe | None]

    def node(
        self,
        template_id: UUID,
        weight_g: Decimal | None,
        recipe: MakerRecipe | None,
        depth: int,
        seen: frozenset[UUID],
    ) -> Ingredient:
        template = self.templates.get(template_id)
        facts = self.facts.get(template_id, LabelFacts())
        product_name = template.name if template is not None else str(template_id)
        ingredient = Ingredient(
            template_id=template_id,
            name=facts.label_name or product_name,
            product_name=product_name,
            weight_g=weight_g,
            facts=facts,
        )
        if recipe is None or not recipe.lines:
            return ingredient
        if depth > bom_service._MAX_DEPTH:
            raise ServiceRejectionError(
                'bom_depth_exceeded', max_depth=bom_service._MAX_DEPTH
            )
        if template_id in seen:
            raise ServiceRejectionError('bom_cycle_detected', template_id=template_id)
        ingredient.yield_g = self.units.grams(
            recipe.batch_yield_qty, recipe.batch_yield_uom_id, template
        )
        ingredient.children = sorted(
            (
                self.node(
                    line.child_template_id,
                    self.units.grams(
                        line.qty_per_batch
                        * (Decimal('1') + line.yield_loss_pct / Decimal('100')),
                        line.uom_id,
                        self.templates.get(line.child_template_id),
                    ),
                    self.recipes.get(line.child_template_id),
                    depth + 1,
                    seen | {template_id},
                )
                for line in recipe.lines
            ),
            key=_order,
        )
        return ingredient


def _below(ingredient: Ingredient) -> Iterator[Ingredient]:
    """Every ingredient under *ingredient*, in list order, depth first."""
    for child in ingredient.children:
        yield child
        yield from _below(child)


@dataclass(frozen=True)
class AllergenEntry:
    """One allergen of the made product and what brings it."""

    allergen: str
    #: The ingredients whose cards name it, in list order.
    sources: list[Ingredient]
    declared_on_product: bool


@dataclass(frozen=True)
class Nutrition:
    """The declaration per 100 g of the made product; None: not known."""

    per_100g: dict[str, Decimal | None]
    #: The ingredients that lack a figure, and which.
    missing: list[tuple[Ingredient, list[str]]]


@dataclass(frozen=True)
class Composition:
    """A made product's label, computed from one of its recipes."""

    #: The made product; its children are the ingredient list.
    product: Ingredient
    allergens: list[AllergenEntry]
    may_contain: list[AllergenEntry]
    #: Ingredients nobody has checked for allergens, with what their names suggest.
    unchecked: list[tuple[Ingredient, tuple[str, ...]]]
    #: Ingredients the list cannot weigh, so it cannot place them.
    unweighed: list[Ingredient]
    nutrition: Nutrition | None


def _distinct(ingredients: Iterable[Ingredient]) -> list[Ingredient]:
    seen: set[UUID] = set()
    out: list[Ingredient] = []
    for ingredient in ingredients:
        if ingredient.template_id not in seen:
            seen.add(ingredient.template_id)
            out.append(ingredient)
    return out


def _collected(
    product: Ingredient, keys_of: str, own: tuple[str, ...], leave_out: set[str]
) -> list[AllergenEntry]:
    """Every allergen the ingredients' cards name under *keys_of*, with them."""
    sources: dict[str, list[Ingredient]] = {}
    for ingredient in _below(product):
        named = getattr(ingredient.facts, keys_of) or ()
        for key in named:
            sources.setdefault(key, []).append(ingredient)
    return [
        AllergenEntry(
            allergen=key,
            sources=_distinct(sources.get(key, [])),
            declared_on_product=key in own,
        )
        for key in ALLERGEN_KEYS
        if (key in sources or key in own) and key not in leave_out
    ]


def _figure(value: object) -> Decimal | None:
    if value is None or value == '' or isinstance(value, bool):
        return None
    try:
        number = Decimal(str(value))
    except ArithmeticError:
        return None
    return number if number.is_finite() and number >= 0 else None


class _Nutrients:
    """Per gram of each ingredient, read up the tree."""

    def __init__(self, templates: dict[UUID, ProductTemplateDTO]) -> None:
        self.templates = templates
        self.missing: dict[UUID, tuple[Ingredient, set[str]]] = {}
        self.any_figure = False

    def per_gram(self, ingredient: Ingredient) -> dict[str, Decimal | None]:
        if ingredient.children:
            return self._made(ingredient)
        template = self.templates.get(ingredient.template_id)
        group = (template.meta_data or {}).get('nutrition') if template else None
        card = group if isinstance(group, dict) else {}
        values: dict[str, Decimal | None] = {}
        for key, card_key in NUTRIENTS:
            figure = _figure(card.get(card_key))
            values[key] = None if figure is None else figure / Decimal('100')
        lacking = {key for key, value in values.items() if value is None}
        self.any_figure = self.any_figure or len(lacking) < len(NUTRIENTS)
        if lacking:
            _entry, before = self.missing.get(
                ingredient.template_id, (ingredient, set())
            )
            self.missing[ingredient.template_id] = (ingredient, before | lacking)
        return values

    def _made(self, ingredient: Ingredient) -> dict[str, Decimal | None]:
        parts = [(child, self.per_gram(child)) for child in ingredient.children]
        out: dict[str, Decimal | None] = {}
        for key, _card_key in NUTRIENTS:
            total: Decimal | None = Decimal('0')
            for child, values in parts:
                value = values[key]
                if total is None or child.weight_g is None or value is None:
                    total = None
                    continue
                total += child.weight_g * value
            out[key] = (
                total / ingredient.yield_g
                if total is not None and ingredient.yield_g
                else None
            )
        return out


def _declared(per_gram: dict[str, Decimal | None]) -> dict[str, Decimal | None]:
    per_100g = {
        key: None if value is None else value * Decimal('100')
        for key, value in per_gram.items()
    }
    kcal = per_100g.get('energy_kcal')
    per_100g = {
        'energy_kj': None if kcal is None else kcal * _KJ_PER_KCAL,
        **per_100g,
    }
    return {
        key: None
        if value is None
        else value.quantize(_PLACES.get(key, Decimal('0.1')), rounding=ROUND_HALF_UP)
        for key, value in per_100g.items()
    }


def _nutrition(
    product: Ingredient, templates: dict[UUID, ProductTemplateDTO]
) -> Nutrition | None:
    reader = _Nutrients(templates)
    per_gram = reader.per_gram(product)
    if not reader.any_figure:
        return None
    order = {key: index for index, (key, _card) in enumerate(NUTRIENTS)}
    return Nutrition(
        per_100g=_declared(per_gram),
        missing=[
            (ingredient, sorted(lacking, key=order.__getitem__))
            for ingredient, lacking in reader.missing.values()
        ],
    )


async def compose_async(
    db: AsyncSession, organization_id: UUID, recipe: MakerRecipe
) -> Composition:
    """The label of *recipe*'s product, computed from that recipe.

    The recipe itself is the top level; an ingredient that is made is
    expanded through its default recipe, as a run explodes it.
    """
    recipes = await bom_service._warm_child_cache(db, organization_id, [recipe])
    ids = {recipe.output_template_id} | {
        line.child_template_id
        for each in [recipe, *recipes.values()]
        if each is not None
        for line in each.lines
    }
    templates = await core_api.product_templates.get_many_async(
        db, organization_id, list(ids)
    )
    facts = await facts_async(db, organization_id, ids)
    tree = _Tree(templates, facts, await _units_async(db, organization_id), recipes)
    product = tree.node(recipe.output_template_id, None, recipe, 0, frozenset())
    own = product.facts.allergens or ()
    allergens = _collected(product, 'allergens', own, set())
    contained = {entry.allergen for entry in allergens}
    below = list(_below(product))
    return Composition(
        product=product,
        allergens=allergens,
        may_contain=_collected(
            product, 'may_contain', product.facts.may_contain, contained
        ),
        unchecked=[
            (each, suggested_allergens(each.product_name, each.facts.label_name))
            for each in _distinct(
                each
                for each in below
                if not each.children and each.facts.allergens is None
            )
        ],
        unweighed=_distinct(each for each in below if each.weight_g is None),
        nutrition=_nutrition(product, templates),
    )


async def compose_for_label_async(
    db: AsyncSession,
    organization_id: UUID,
    template_id: UUID,
    lot_id: UUID | None = None,
) -> Composition | None:
    """The label of *template_id*, or of its batch *lot_id*; None when not made.

    A product may have several formulas, and a run records the one it used:
    a batch is labelled from the formula of the runs that filed their output
    under it. A batch no run filled — goods received, a batch opened by
    hand, or a product label with no batch — is labelled from the default
    formula, the one the product's card speaks of. A batch runs of two
    formulas filled holds what both put in and no single list is its own: it
    gets none, and its label carries no list rather than a wrong one.
    """
    used = await _formulas_of_batch_async(db, organization_id, template_id, lot_id)
    if len(used) > 1:
        return None
    if used:
        recipe = await db.scalar(
            select(MakerRecipe).where(
                MakerRecipe.organization_id == organization_id,
                MakerRecipe.id == used.pop(),
            )
        )
    else:
        recipe = await bom_service.find_default_recipe(db, organization_id, template_id)
    if recipe is None or not recipe.lines:
        return None
    return await compose_async(db, organization_id, recipe)


async def _formulas_of_batch_async(
    db: AsyncSession, organization_id: UUID, template_id: UUID, lot_id: UUID | None
) -> set[UUID]:
    """The formulas of the runs whose output is in the batch *lot_id*.

    A run's output is in its own batch and, when it was filled in portions,
    in each batch a portion named. A run undone took its output back off the
    shelf; a run from before runs kept their formula names none.
    """
    if lot_id is None:
        return set()
    lot = await core_api.stock.get_lot_detail_async(db, organization_id, lot_id)
    if lot is None:
        return set()
    portioned = select(ProductionPortion.production_order_id).where(
        ProductionPortion.organization_id == organization_id,
        ProductionPortion.lot_name == lot.name,
    )
    rows = await db.scalars(
        select(ProductionOrder.recipe_id).where(
            ProductionOrder.organization_id == organization_id,
            ProductionOrder.output_template_id == template_id,
            ProductionOrder.status != 'REVERSED',
            ProductionOrder.recipe_id.is_not(None),
            or_(
                ProductionOrder.output_lot_id == lot_id,
                ProductionOrder.id.in_(portioned),
            ),
        )
    )
    return {recipe_id for recipe_id in rows if recipe_id is not None}


# --- The label's words ------------------------------------------------------

_INGREDIENTS_WORD = {
    'en': 'Ingredients',
    'pl': 'Składniki',
    'de': 'Zutaten',
    'fr': 'Ingrédients',
    'es': 'Ingredientes',
}
_CONTAINS_WORD = {
    'en': 'Contains',
    'pl': 'Zawiera',
    'de': 'Enthält',
    'fr': 'Contient',
    'es': 'Contiene',
}
_MAY_CONTAIN_WORD = {
    'en': 'May contain',
    'pl': 'Może zawierać',
    'de': 'Kann enthalten',
    'fr': 'Peut contenir',
    'es': 'Puede contener',
}
#: The allergens' names as the regulation's annex gives them, in a sentence.
_ALLERGEN_NAMES: dict[str, dict[str, str]] = {
    'gluten': {
        'en': 'gluten',
        'pl': 'gluten',
        'de': 'Gluten',
        'fr': 'gluten',
        'es': 'gluten',
    },
    'crustaceans': {
        'en': 'crustaceans',
        'pl': 'skorupiaki',
        'de': 'Krebstiere',
        'fr': 'crustacés',
        'es': 'crustáceos',
    },
    'eggs': {'en': 'eggs', 'pl': 'jaja', 'de': 'Eier', 'fr': 'œufs', 'es': 'huevos'},
    'fish': {
        'en': 'fish',
        'pl': 'ryby',
        'de': 'Fisch',
        'fr': 'poisson',
        'es': 'pescado',
    },
    'peanuts': {
        'en': 'peanuts',
        'pl': 'orzeszki ziemne',
        'de': 'Erdnüsse',
        'fr': 'arachides',
        'es': 'cacahuetes',
    },
    'soy': {'en': 'soya', 'pl': 'soja', 'de': 'Soja', 'fr': 'soja', 'es': 'soja'},
    'milk': {'en': 'milk', 'pl': 'mleko', 'de': 'Milch', 'fr': 'lait', 'es': 'leche'},
    'nuts': {
        'en': 'nuts',
        'pl': 'orzechy',
        'de': 'Schalenfrüchte',
        'fr': 'fruits à coque',
        'es': 'frutos de cáscara',
    },
    'celery': {
        'en': 'celery',
        'pl': 'seler',
        'de': 'Sellerie',
        'fr': 'céleri',
        'es': 'apio',
    },
    'mustard': {
        'en': 'mustard',
        'pl': 'gorczyca',
        'de': 'Senf',
        'fr': 'moutarde',
        'es': 'mostaza',
    },
    'sesame': {
        'en': 'sesame',
        'pl': 'sezam',
        'de': 'Sesam',
        'fr': 'sésame',
        'es': 'sésamo',
    },
    'sulphites': {
        'en': 'sulphites',
        'pl': 'siarczyny',
        'de': 'Sulfite',
        'fr': 'sulfites',
        'es': 'sulfitos',
    },
    'lupin': {
        'en': 'lupin',
        'pl': 'łubin',
        'de': 'Lupinen',
        'fr': 'lupin',
        'es': 'altramuces',
    },
    'molluscs': {
        'en': 'molluscs',
        'pl': 'mięczaki',
        'de': 'Weichtiere',
        'fr': 'mollusques',
        'es': 'moluscos',
    },
}


def allergen_name(key: str, lang: str) -> str:
    """The allergen's name in *lang*, as it stands in a sentence."""
    names = _ALLERGEN_NAMES.get(key)
    return pick_by_lang(lang, **names) if names else key


def listed(ingredient: Ingredient) -> str:
    """One ingredient as the list writes it: emphasised, its own in brackets."""
    name = ingredient.name.upper() if ingredient.emphasised else ingredient.name
    if not ingredient.children:
        return name
    return f'{name} ({", ".join(listed(child) for child in ingredient.children)})'


def label_text(composition: Composition, lang: str) -> str | None:
    """The ingredient list and the allergens as a label prints them.

    Allergens are emphasised in capitals, which a one-colour label can carry
    where bold may not survive a small print. An allergen declared on the
    product and brought by no ingredient has no name in the list to emphasise,
    so it gets a "contains" sentence of its own; the cross-contact ones close
    the text.
    """
    product = composition.product
    if not product.children:
        return None
    sentences = [
        f'{pick_by_lang(lang, **_INGREDIENTS_WORD)}: '
        f'{", ".join(listed(child) for child in product.children)}.'
    ]
    unlisted = [entry.allergen for entry in composition.allergens if not entry.sources]
    if unlisted:
        sentences.append(
            f'{pick_by_lang(lang, **_CONTAINS_WORD)}: '
            f'{", ".join(allergen_name(key, lang).upper() for key in unlisted)}.'
        )
    if composition.may_contain:
        sentences.append(
            f'{pick_by_lang(lang, **_MAY_CONTAIN_WORD)}: '
            f'{", ".join(allergen_name(e.allergen, lang) for e in composition.may_contain)}.'
        )
    return ' '.join(sentences)
