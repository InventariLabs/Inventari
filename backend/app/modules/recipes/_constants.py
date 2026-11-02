"""Constants the recipe module writes down once.

The quantization step used to live here: it appeared in eight places as a
bare ``Decimal('0.001')`` or a ``_QUANTIZE_3`` of its own, was gathered into
one name, and then turned out not to be a constant at all. What a computed
quantity is rounded to is the step of the unit it is stated in — ``pcs`` is
counted in ones — so consumers ask ``core_api.uoms`` for it per unit and this
module no longer has an opinion. See ``app.services.uom_service.quantity_step``.
"""

from __future__ import annotations

from typing import Any


def localized(pattern: dict[str, str], lang: str, **kwargs: Any) -> str:
    """One of a phrase's translations, filled in. English when the language
    has none — a missing translation is a sentence in the wrong language,
    not a KeyError in front of the reader."""
    return pattern.get(lang, pattern['en']).format(**kwargs)
