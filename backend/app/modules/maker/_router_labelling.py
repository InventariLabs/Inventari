"""A product's label: what its card says, and what its recipe makes of it."""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import AuditAction, AuditTargetType, UserContextDTO
from app.core.deps import (
    get_async_db,
    get_current_user_context,
    require_org,
    require_permission,
)
from app.core.exceptions import map_service_errors
from app.core.public_api import core_api
from app.i18n.service import get_current_lang

from . import bom_service, labelling
from ._schemas_labelling import (
    LabelAllergen,
    LabelFactsRead,
    LabelFactsUpdate,
    LabelIngredient,
    LabelIngredientRef,
    LabelNutrientGap,
    LabelNutrition,
    LabelUnchecked,
    RecipeLabelRead,
)

router = APIRouter(prefix='/labelling', tags=['maker'])

_GRAM = Decimal('0.01')


def _ref(ingredient: labelling.Ingredient) -> LabelIngredientRef:
    return LabelIngredientRef(template_id=ingredient.template_id, name=ingredient.name)


def _allergens(entries: list[labelling.AllergenEntry]) -> list[LabelAllergen]:
    return [
        LabelAllergen(
            allergen=entry.allergen,
            sources=[_ref(source) for source in entry.sources],
            declared_on_product=entry.declared_on_product,
        )
        for entry in entries
    ]


def _ingredient(ingredient: labelling.Ingredient) -> LabelIngredient:
    return LabelIngredient(
        template_id=ingredient.template_id,
        name=ingredient.name,
        weight_g=None
        if ingredient.weight_g is None
        else ingredient.weight_g.quantize(_GRAM),
        emphasised=ingredient.emphasised,
        children=[_ingredient(child) for child in ingredient.children],
    )


def _nutrition(nutrition: labelling.Nutrition | None) -> LabelNutrition | None:
    if nutrition is None:
        return None
    return LabelNutrition(
        **nutrition.per_100g,
        missing=[
            LabelNutrientGap(
                template_id=ingredient.template_id,
                name=ingredient.name,
                nutrients=lacking,
            )
            for ingredient, lacking in nutrition.missing
        ],
    )


async def _facts_read(
    db: AsyncSession, org_id: UUID, template_id: UUID
) -> LabelFactsRead:
    template = await core_api.product_templates.get_async(db, org_id, template_id)
    facts = (await labelling.facts_async(db, org_id, [template_id])).get(
        template_id, labelling.LabelFacts()
    )
    recipe = await bom_service.find_default_recipe(db, org_id, template_id)
    composition = (
        await labelling.compose_async(db, org_id, recipe)
        if recipe is not None and recipe.lines
        else None
    )
    return LabelFactsRead(
        product_template_id=template_id,
        label_name=facts.label_name,
        allergens=None if facts.allergens is None else list(facts.allergens),
        may_contain=list(facts.may_contain),
        suggested_allergens=list(
            labelling.suggested_allergens(
                template.name if template else None, facts.label_name
            )
        ),
        recipe_id=recipe.id if composition is not None and recipe else None,
        recipe_name=recipe.name if composition is not None and recipe else None,
        derived_allergens=_allergens(composition.allergens) if composition else [],
        derived_may_contain=_allergens(composition.may_contain) if composition else [],
    )


@router.get('/products/{template_id}', response_model=LabelFactsRead)
@map_service_errors
async def get_label_facts(
    template_id: UUID,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    org_id: UUID = Depends(require_org),
) -> LabelFactsRead:
    """A product's label facts, what its name suggests and what its recipe adds."""
    return await _facts_read(db, org_id, template_id)


@router.put(
    '/products/{template_id}',
    response_model=LabelFactsRead,
    dependencies=[require_permission('maker:manage')],
)
@map_service_errors
async def set_label_facts(
    template_id: UUID,
    data: LabelFactsUpdate,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    org_id: UUID = Depends(require_org),
) -> LabelFactsRead:
    """Keep the product's label name, allergens and may-contain list.

    A fact about the product, so it lands in the organization journal with
    both sides, as its shelf life does.
    """
    before = (await labelling.facts_async(db, org_id, [template_id])).get(
        template_id, labelling.LabelFacts()
    )
    after = await labelling.set_facts_async(
        db,
        org_id,
        template_id,
        labelling.LabelFacts(
            label_name=data.label_name,
            allergens=None if data.allergens is None else tuple(data.allergens),
            may_contain=tuple(data.may_contain),
        ),
    )
    if after != before:
        template = await core_api.product_templates.get_async(db, org_id, template_id)
        await core_api.audit_log.log_action_async(
            db,
            organization_id=org_id,
            user_id=current_user.id,
            action=AuditAction.UPDATE,
            target_type=AuditTargetType.PRODUCT_TEMPLATE,
            target_id=template_id,
            snapshot={
                'name': template.name if template else None,
                'before': {
                    'label_name': before.label_name,
                    'allergens': None
                    if before.allergens is None
                    else list(before.allergens),
                    'may_contain': list(before.may_contain),
                },
                'after': {
                    'label_name': after.label_name,
                    'allergens': None
                    if after.allergens is None
                    else list(after.allergens),
                    'may_contain': list(after.may_contain),
                },
            },
        )
    return await _facts_read(db, org_id, template_id)


@router.get('/recipes/{recipe_id}', response_model=RecipeLabelRead)
@map_service_errors
async def get_recipe_label(
    recipe_id: UUID,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    org_id: UUID = Depends(require_org),
) -> RecipeLabelRead:
    """The ingredient list, allergens and nutrition this recipe makes.

    Computed on every read from the recipe and its ingredients' cards; the
    producer checks it before it goes on a label.
    """
    recipe = await bom_service.resolve_recipe(db, org_id, recipe_id)
    composition = await labelling.compose_async(db, org_id, recipe)
    product = composition.product
    return RecipeLabelRead(
        recipe_id=recipe.id,
        output_template_id=recipe.output_template_id,
        ingredients=[_ingredient(child) for child in product.children],
        text=labelling.label_text(composition, get_current_lang()),
        allergens=_allergens(composition.allergens),
        may_contain=_allergens(composition.may_contain),
        unchecked=[
            LabelUnchecked(
                template_id=ingredient.template_id,
                name=ingredient.name,
                suggested_allergens=list(suggested),
            )
            for ingredient, suggested in composition.unchecked
        ],
        unweighed=[_ref(ingredient) for ingredient in composition.unweighed],
        yield_weight_g=None
        if product.yield_g is None
        else product.yield_g.quantize(_GRAM),
        nutrition=_nutrition(composition.nutrition),
    )
