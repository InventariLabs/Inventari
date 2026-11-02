"""What a photographed label is asked to yield.

The field descriptions are the prompt: Core renders them into the request
(:func:`app.core.llm.structured_extraction.build_shape_prompt`), so the
vocabulary of a domain lives beside the field it fills and cannot drift away
from it. A hand-written prompt block listing the same keys used to sit in
``_prompts.py``; when a field was added to one, the other kept its old shape.

What is *not* here: fields a particular vertical cares about. Nutrition
figures used to share this model with ``expiry_date``, which made every
reader of an equipment nameplate carry six null grams-per-100g. Those fields
belong to the module that wants them and arrive through
:mod:`app.modules.vision.field_contributions`.

One thing here is still not neutral, and saying so is better than implying
otherwise: ``category`` offers a closed list of food categories, so a
photographed equipment nameplate is asked to choose between dairy and
spices. Moving that vocabulary to the contributing module is the same move
the nutrition fields already made, and it changes what the model returns for
every existing caller — a decision, not a tidy-up.
"""

from typing import Any

from pydantic import BaseModel, Field


class VisionExtractResult(BaseModel):
    """Identity read off a label: what the thing is, not what it contains."""

    name: str | None = Field(
        None, description="product name, precise, in the product's own language"
    )
    # Worded without naming any vertical: a nameplate on a machine is read
    # through this same field, and an integration test rightly refuses a
    # prompt that mentions food to a reader of equipment.
    #
    # The three exclusions and the word "null" are here from measurement, not
    # from taste. Over fourteen photographs of well-known products, models
    # supplied a net weight that was nowhere in the frame eighteen times —
    # always plausible, twice the product's real weight recalled from
    # training — while inventing no nutrition value at all in the same
    # requests. The difference was that the nutrition module's instructions
    # say null is the right answer and this description said "look in the
    # package's bottom corners", which is an instruction to keep looking.
    #
    # The three things named are the three that actually appeared: a per-bar
    # nutrition figure read as a net weight, a "+50g free" flash, and a pack
    # count. Naming them cost nothing and stopped a 7B model fabricating
    # seven weights out of seven.
    #
    # Dose matters. Longer versions of this text, and a matching rule in the
    # shared instructions, cut fabrication further and took a mid-sized model
    # down with them: it began answering null for "Coca-Cola" printed across
    # half the pack. Whatever replaces this, measure the models that answer
    # too little, not only the ones that answer too much —
    # ``backend/scripts/vision_model_matrix.py`` exists for that.
    weight: str | None = Field(
        None,
        description=(
            'net weight or volume of the whole package as printed, with its '
            'unit (e.g. 500g, 1L, 200ml); null when it is not visible. A '
            'per-serving or per-100g figure, a "+50g free" flash and a count '
            'of pieces are not it.'
        ),
    )
    expiry_date: str | None = Field(
        None,
        description=(
            'expiry / best-before date as YYYY-MM-DD; convert from '
            'DD.MM.YYYY or DD/MM/YY when printed that way'
        ),
    )
    production_date: str | None = Field(
        None, description='production or freezing date as YYYY-MM-DD, if printed'
    )
    brand: str | None = Field(None, description='brand or manufacturer name')
    category: str | None = Field(
        None,
        description=(
            'best-fitting category from: dairy, meat, vegetables, fruits, '
            'drinks, frozen, dry, canned, spices, other'
        ),
    )
    barcode: str | None = Field(None, description='barcode digits, if legible')

    # Structural weight/volume data (Logistics 2.0)
    weight_value: float | None = Field(
        None, description='numeric net weight or volume, e.g. 500.0'
    )
    weight_uom: str | None = Field(
        None, description='unit for weight_value: g, kg, ml, l, lb, oz, fl oz'
    )
    volume_value: float | None = Field(None, description='numeric volume, if separate')
    volume_uom: str | None = Field(None, description='unit for volume_value')


class VisionExtractResponse(VisionExtractResult):
    """The label reading, plus whatever the enabled modules asked for.

    Every contributed group sits under its own key, the way module data sits
    under its own namespace in ``meta_data`` — so a reader can tell who owns a
    value without a lookup table, and a module that is switched off simply
    leaves its key absent instead of a row of nulls.
    """

    extra: dict[str, Any] = Field(
        default_factory=dict,
        description='Contributed field groups, keyed by contributing module.',
    )
    resolved: dict[str, Any] | None = Field(
        None,
        description=(
            'A product template a scan resolver recognised from the barcode '
            'read off the label, or null when nothing recognised it.'
        ),
    )


class VisionReceiptItem(BaseModel):
    name: str
    quantity: float = 1.0
    unit: str | None = 'pcs'
    brand: str | None = None
    category: str | None = None
    price: float | None = None
