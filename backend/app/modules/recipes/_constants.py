"""Constants the recipe module writes down once.

A computed quantity is rounded to the step of the unit it is stated in —
``pcs`` is counted in ones — so consumers ask ``core_api.uoms`` for it per unit.
This module has no quantization step of its own. See
``app.services.uom_service.quantity_step``.
"""

from __future__ import annotations

from typing import Any


def localized(pattern: dict[str, str], lang: str, **kwargs: Any) -> str:
    """One of a phrase's translations, filled in. English when the language
    has none — a missing translation is a sentence in the wrong language,
    not a KeyError in front of the reader."""
    return pattern.get(lang, pattern['en']).format(**kwargs)
