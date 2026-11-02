"""The contract probe for ``vision.extract``.

What the connection test sends when it wants to know whether a model can do
the job, rather than whether its API key is valid. The request is built by the
same helper production uses and judged by the same parser, so a green result
here means the same thing as a green result in the field.

The reference label is drawn in-process rather than shipped as a file: no
binary blob in the repository, no question about where the photograph came
from, and nothing recognisable from anybody's real inventory.
"""

from __future__ import annotations

import io
import re
from datetime import date
from functools import lru_cache
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from app.core.public_api.llm import AiContractProbe, LlmRequest, parse_into

from ._text_norm import normalise_text
from .schemas import VisionExtractResult

# Everything the probe expects the model to come back with. Kept mundane —
# the point is the shape of the answer, not the difficulty of the reading.
_LABEL_LINES = [
    'OAT DRINK',
    'Barista Edition',
    '1 L',
    'Best before: 2027-01-31',
]

#: What the drawn label says, keyed by the field that should carry it. The
#: probe is the only reader in the application that knows the right answer in
#: advance — it drew the picture — so this is where "did the model read it"
#: can be asked at all.
#:
#: ``brand`` is deliberately absent. The label establishes no maker: nothing
#: on it is recognisable as a manufacturer, and "Barista Edition" is a
#: variant name. A field whose truth the picture does not carry cannot be
#: scored — expecting 'Barista Edition' there reported six of nine measured
#: hosted models as missing a field they had read correctly (one answered
#: name='OAT DRINK Barista Edition', brand=None, which is the better reading).
#: Real photographs, where a maker is visible, keep their brand scoring in
#: the corpus matrix.
_EXPECTED: dict[str, str] = {
    'name': 'OAT DRINK',
    'weight': '1 L',
    'expiry_date': '2027-01-31',
}

_WIDTH = 560
_HEIGHT = 300


@lru_cache(maxsize=1)
def reference_label() -> bytes:
    """A synthetic product label, rendered once per process."""
    image = Image.new('RGB', (_WIDTH, _HEIGHT), (255, 255, 255))
    draw = ImageDraw.Draw(image)
    draw.rectangle([(8, 8), (_WIDTH - 9, _HEIGHT - 9)], outline=(0, 0, 0), width=3)

    title_font = ImageFont.load_default(size=46)
    body_font = ImageFont.load_default(size=30)

    y = 48
    for index, line in enumerate(_LABEL_LINES):
        font = title_font if index == 0 else body_font
        draw.text((40, y), line, fill=(0, 0, 0), font=font)
        y += 62 if index == 0 else 48

    buffer = io.BytesIO()
    image.save(buffer, format='JPEG', quality=92)
    return buffer.getvalue()


def build_probe_request() -> LlmRequest:
    """The production extract request, pointed at the reference label.

    Built the same way the service builds a real one — Core renders the shape
    from the schema, so a field added to the label model is a field the probe
    starts checking, with nothing to keep in step by hand.
    """
    from app.core.public_api.llm import build_shape_prompt

    from .service import _INSTRUCTIONS

    return LlmRequest(
        prompt=f'{_INSTRUCTIONS}\n\n{build_shape_prompt(VisionExtractResult)}',
        images=[reference_label()],
        json_schema=VisionExtractResult.model_json_schema(),
        temperature=0.2,
        # Both of these are what ``extract_from_images`` asks for, and the
        # probe has to ask for the same or it is testing a different call.
        # It briefly was: the budget went to 8000 and reasoning was switched
        # off on the production path, and this one kept 2000 and left
        # reasoning on. A reasoning model then spends the whole budget
        # thinking, the content arrives empty, and the test fails a model
        # that would have worked in the field — measured on qwen3-vl:8b,
        # which needs 2162 completion tokens for this label and produced
        # exactly nothing at 2000.
        max_tokens=8000,
        disable_reasoning=True,
    )


def _same_text(expected: str, read: str) -> bool:
    """Case, spacing and typography are the model's to choose; the words are not."""
    return normalise_text(expected) == normalise_text(read)


def _contains_text(expected: str, read: str) -> bool:
    """A fuller reading is not a misreading, and a fragment is not a reading.

    The label's name line is 'OAT DRINK', and a model that answers
    'OAT DRINK Barista Edition' read the line and then some — the variant
    rides under the same heading. Equality called that a miss on six of the
    nine hosted models measured while choosing one, which is why containment
    is here at all.

    Containment runs one way here: the expected name has to appear inside
    what the model read. The other direction was copied from the corpus
    scorer, floor and all, and it accepted 'OAT' — the header alone, and
    exactly as wide as the scorer's three-character floor — as having read
    the name. Every real answer this comparison exists to accept is fuller
    than the expected line, so no floor is needed: a read shorter than the
    name it claims to be is a fragment, and a fragment is the failure mode
    the screen has to show.
    """
    return normalise_text(expected) in normalise_text(read)


def _same_date(expected: str, read: str) -> bool:
    """A date is the day it names, however it is spelled.

    The field asks for YYYY-MM-DD and most models oblige, but "31 January
    2027" and "2027-01-31" are the same answer and only one of them survives
    string equality. Reporting the first as a misreading would teach people
    that the reading column lies, and a column people discount is worse than
    no column.
    """
    wanted = date.fromisoformat(expected)
    text = read.strip()
    for pattern, order in (
        (r'^(\d{4})-(\d{2})-(\d{2})$', 'ymd'),
        (r'^(\d{2})[./](\d{2})[./](\d{4})$', 'dmy'),
    ):
        match = re.match(pattern, text)
        if match:
            parts = [int(group) for group in match.groups()]
            year, month, day = parts if order == 'ymd' else parts[::-1]
            return date(year, month, day) == wanted
    months = {
        name.casefold(): number
        for number, name in enumerate(
            (
                'January',
                'February',
                'March',
                'April',
                'May',
                'June',
                'July',
                'August',
                'September',
                'October',
                'November',
                'December',
            ),
            start=1,
        )
    }
    match = re.match(r'^(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})$', text)
    if match and match.group(2).casefold() in months:
        return (
            date(
                int(match.group(3)),
                months[match.group(2).casefold()],
                int(match.group(1)),
            )
            == wanted
        )
    return False


def _same_quantity(expected: str, read: str) -> bool:
    """One litre is one litre, written 1 L, 1l, 1.0 L or 1000 ml."""
    units = {'l': 1000.0, 'litre': 1000.0, 'liter': 1000.0, 'ml': 1.0}

    def parse(value: str) -> float | None:
        match = re.match(r'^\s*([\d.,]+)\s*([a-zA-Z]+)\s*$', value.replace(',', '.'))
        if not match:
            return None
        unit = match.group(2).casefold().rstrip('s')
        if unit not in units:
            return None
        return float(match.group(1)) * units[unit]

    left, right = parse(expected), parse(read)
    if left is None or right is None:
        return _same_text(expected, read)
    return abs(left - right) < 0.001


_COMPARE = {
    'name': _contains_text,
    'expiry_date': _same_date,
    'weight': _same_quantity,
}


def read_back(parsed: Any) -> dict[str, Any]:
    """What the model made of the reference label, field by field.

    This does not decide the verdict. A model that answers in the agreed shape
    has satisfied the contract, which is what the verdict is about; whether it
    also read the picture is a second question the person choosing a model
    needs answered, and until now the test gave the same green for both.
    """
    fields = {}
    for field, expected in _EXPECTED.items():
        read = getattr(parsed, field, None)
        matches = (
            _COMPARE.get(field, _same_text)(expected, read)
            if isinstance(read, str) and read.strip()
            else False
        )
        fields[field] = {'expected': expected, 'read': read, 'matches': matches}
    return {
        'fields': fields,
        'matched': sum(1 for entry in fields.values() if entry['matches']),
        'of': len(fields),
    }


probe = AiContractProbe(
    build_request=build_probe_request,
    validate=lambda content: parse_into(VisionExtractResult, content),
    read_back=read_back,
)
