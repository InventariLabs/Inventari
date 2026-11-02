"""One normalisation for text read off a label.

Shared by the connection probe (``app.modules.vision._probe``) and the corpus
scorer (``backend/scripts/vision_model_matrix.py``): both ask whether a model
read what the label says, and both have to mean the same thing by "read".
Accents, trademark marks and punctuation are typography, not reading — a model
that writes 'Nestle' for 'Nestlé' or 'Barilla' for 'Barilla®' read the label,
and counting those as misreadings would make the column describe the model's
keyboard instead of the picture.
"""

from __future__ import annotations

import re
import unicodedata


def normalise_text(value: str) -> str:
    """Casefold, drop accents and trademark noise, collapse spacing.

    NFD splits a letter from its accent so the accent can be dropped by
    category. ``®``, ``™`` and ``°`` are printed marks rather than words;
    everything that is neither a word character nor whitespace becomes a
    space, so a dash or a slash separates words instead of gluing them into
    one nobody can match.
    """
    stripped = ''.join(
        char
        for char in unicodedata.normalize('NFD', value)
        if unicodedata.category(char) != 'Mn'
    )
    stripped = stripped.replace('®', '').replace('™', '').replace('°', ' ')
    stripped = re.sub(r'[^\w\s]', ' ', stripped)
    return re.sub(r'\s+', ' ', stripped).strip().casefold()
