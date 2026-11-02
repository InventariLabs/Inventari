"""Reading the bars back off a rendered product label.

A scanner reads a 1D code across the bars, module by module. This does the
same on the PNG: it finds a row across the bars, measures the narrowest run
(one module) and samples the row at that pitch, so a test can compare what
the label carries with the pattern its code should produce.
"""

import io
from collections import Counter

from PIL import Image


def _runs(row: list[bool]) -> list[tuple[bool, int]]:
    runs: list[tuple[bool, int]] = []
    for dark in row:
        if runs and runs[-1][0] == dark:
            runs[-1] = (dark, runs[-1][1] + 1)
        else:
            runs.append((dark, 1))
    return runs


def read_bars(png: bytes) -> str:
    """The modules of the barcode on a one-label PNG, ``1`` for a bar."""
    img = Image.open(io.BytesIO(png)).convert('L')
    pixels = list(img.tobytes())
    rows = [
        [value < 128 for value in pixels[y * img.width : (y + 1) * img.width]]
        for y in range(img.height)
    ]
    # Bars are vertical, so the row across them repeats for their whole
    # height; no line of text repeats itself that many times.
    inked = [tuple(r) for r in rows if any(r)]
    row = Counter(inked).most_common(1)[0][0]
    runs = _runs(list(row))
    while runs and not runs[0][0]:
        runs.pop(0)
    while runs and not runs[-1][0]:
        runs.pop()
    module = min(length for _, length in runs)
    return ''.join(('1' if dark else '0') * (length // module) for dark, length in runs)
