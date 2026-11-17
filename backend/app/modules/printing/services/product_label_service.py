"""Rendering a product label: the name, the product's code in bars, lot and expiry.

A made product's label and its batch's may also carry the ingredient list
and the allergens, as a block of text under the name. It is set as large as
the label leaves room for and never smaller than the letter EU Regulation
1169/2011 allows on a small package (Art. 13 and Annex IV: an x-height of
0.9 mm); a list that does not fit at that size is refused, naming the label
size, rather than printed too small to be lawful or cut short.

A pool label carries a QR that opens a scan address; a product label carries
the product's own code as a 1D barcode, the thing a receiving or picking scan
looks the product up by. A code that is a valid EAN-13 (a manufacturer's, or
one Inventari generated) is drawn as EAN-13, which every scanner reads; any
other code — a SKU, a supplier's alphanumeric code — as Code 128.

Bars are a grid along one axis, so they get the QR's rule: the module width
is chosen first, in whole pixels, and every bar is a whole number of them.
A code whose bars and quiet zones do not fit the label at one pixel a module
is refused, naming the width that would hold it: a symbol clipped at its end
loses the stop pattern and no scanner reads it. The same goes for a label too
short to leave the bars a usable height once the name and the text under them
have their lines.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import NamedTuple

import barcode as barcode_lib
import qrcode
from PIL import Image, ImageDraw

from app.core.barcode import validate_checksum
from app.core.exceptions import catalogue_refusal
from app.modules.printing.services.label_geometry import (
    LABEL_DPI,
    Raster,
    raster_for,
)
from app.modules.printing.services.label_print_service import (
    LINE_SPACING,
    MIN_FONT_PX,
    _clipped_to_width,
    _font,
    _largest_fitting,
    _overflows,
    _png,
    _qr_matrix,
    _wrapped_lines,
    sheet_png,
)

#: White around the label's edge, in millimetres.
PADDING_MM = 1.5

#: White between the bars and the text above and below them, in millimetres.
GAP_MM = 0.5

#: The name's largest size, as a fraction of the label's height; it wraps to
#: two lines before it shrinks.
NAME_RATIO = 0.15
NAME_MAX_LINES = 2

#: The code's digits and the lot line, as a fraction of the label's height.
TEXT_RATIO = 0.1

#: The least x-height of the ingredient list, in millimetres: the letter EU
#: Regulation 1169/2011 allows on a package whose largest side is under
#: 80 cm² (Annex IV); a larger package asks 1.2 mm, a larger label.
COMPOSITION_MIN_X_HEIGHT_MM = 0.9

#: The least height the bars may have, in millimetres: shorter than this a
#: handheld scanner's beam misses them.
MIN_BAR_MM = 5.0

#: Modules of white a scanner needs on each side of the bars: GS1's 11 and 7
#: for EAN-13, the 10 of Code 128.
_QUIET_ZONES = {'ean13': (11, 7), 'code128': (10, 10)}


class ProductLabel(NamedTuple):
    """What one label with bars says: a product's, or a shelf's.

    A shelf label puts its code where a product's name goes, large, so a
    person reads the place off the sticker without scanning; the code is not
    printed a second time under the bars then, and the location's name goes
    on the line beneath.
    """

    name: str
    code: str
    #: The lot and expiry line, already in the reader's language; None
    #: when the record has neither or the person left them off. A shelf
    #: label's location name. A newline starts another line under it.
    details: str | None = None
    #: What a QR square at the label's left end carries, when the label has
    #: one: a phone camera reads it where a 1D scanner reads the bars.
    qr: str | None = None
    #: A made product's ingredient list and allergens, under the name.
    composition: str | None = None


def symbology(code: str) -> str | None:
    """How *code* is drawn: ``ean13``, ``code128``, or None when it cannot be."""
    if len(code) == 13 and code.isdigit() and validate_checksum(code):
        return 'ean13'
    if code and code.isascii() and code.isprintable():
        return 'code128'
    return None


def barcode_modules(code: str) -> str | None:
    """The bars of *code*, one ``1`` (bar) or ``0`` (space) per module.

    An EAN-13 is handed over without its check digit: the library recomputes
    the digit from the other twelve and would silently print a different
    code than the one asked for if the two ever disagreed.
    """
    kind = symbology(code)
    if kind is None:
        return None
    data = code[:12] if kind == 'ean13' else code
    return str(barcode_lib.get(kind, data).build()[0])


def _require_width(
    code: str,
    width_mm: float,
    height_mm: float,
    *,
    dpi: float = LABEL_DPI,
    max_height_px: int | None = None,
    beside_px: int = 0,
) -> None:
    """Refuse *code* when its bars cannot be drawn whole on this label.

    *beside_px* is what a QR square takes of the width, gap included.
    """
    modules = barcode_modules(code)
    kind = symbology(code)
    if modules is None or kind is None:
        return
    raster = raster_for(width_mm, height_mm, dpi, max_height_px)
    padding = _padding_px(raster)
    needed_px = len(modules) + sum(_QUIET_ZONES[kind]) + beside_px
    if raster.width_px - 2 * padding >= needed_px:
        return
    raise catalogue_refusal(
        'product_label_too_narrow',
        code=code,
        width=f'{width_mm:g}',
        needed=math.ceil((needed_px + 2 * padding) / raster.px_per_mm),
    )


def require_fits(
    label: ProductLabel,
    width_mm: float,
    height_mm: float,
    *,
    dpi: float = LABEL_DPI,
    max_height_px: int | None = None,
) -> None:
    """Refuse *label* when it cannot be drawn whole, readable and scannable.

    The layout decides how much height is left for the bars, so it is drawn
    to find out; a queued job calls this at the click, the renderers reach
    it through ``_draw``.
    """
    _draw(label, width_mm, height_mm, dpi, max_height_px)


def generate_product_label_png(
    label: ProductLabel,
    width_mm: float = 50.0,
    height_mm: float = 24.0,
    *,
    dpi: float = LABEL_DPI,
    max_height_px: int | None = None,
) -> bytes:
    """One product label, W x H mm at ``dpi``, as a PNG."""
    return _png(_draw(label, width_mm, height_mm, dpi, max_height_px), dpi)


#: Labels across the sheet a person downloads and previews. Three of the wide
#: presets (50 and 62 mm) fit the width of an A4 page and stay readable in the
#: preview at any number of labels. The print queue keeps its one strip: a roll
#: printer takes them side by side.
DOWNLOAD_SHEET_COLUMNS = 3


def generate_product_label_batch_png(
    labels: Sequence[ProductLabel],
    width_mm: float = 50.0,
    height_mm: float = 24.0,
    columns: int = 100,
    *,
    dpi: float = LABEL_DPI,
    max_height_px: int | None = None,
) -> bytes:
    """Several product labels side by side, the sheet the pool download makes.

    The callers refuse an empty choice before they get here, in words the
    reader is given.
    """
    tiles = [_draw(label, width_mm, height_mm, dpi, max_height_px) for label in labels]
    return sheet_png(tiles, columns, dpi)


def _draw(
    label: ProductLabel,
    width_mm: float,
    height_mm: float,
    dpi: float,
    max_height_px: int | None,
) -> Image.Image:
    raster = raster_for(width_mm, height_mm, dpi, max_height_px)
    padding = _padding_px(raster)
    gap = round(GAP_MM * raster.px_per_mm)
    square = _qr_square(label.qr, raster.height_px - 2 * padding) if label.qr else None
    beside = square.size[0] + gap if square is not None else 0
    _require_width(
        label.code,
        width_mm,
        height_mm,
        dpi=dpi,
        max_height_px=max_height_px,
        beside_px=beside,
    )
    img = Image.new('L', (raster.width_px, raster.height_px), color=255)
    draw = ImageDraw.Draw(img)
    if square is not None:
        img.paste(square, (padding, (raster.height_px - square.size[1]) // 2))
    left, width = padding + beside, raster.width_px - 2 * padding - beside
    top, bottom = padding, raster.height_px - padding

    top = _draw_name(draw, label.name, left, top, width, raster.height_px) + gap

    text_size = max(MIN_FONT_PX, round(raster.height_px * TEXT_RATIO))
    text_line = round(text_size * LINE_SPACING)
    if label.details:
        # A line each, the last at the bottom: a batch label says the day it
        # was made and its best-before on two lines, where one would clip the
        # date a reader needs most.
        for line in reversed(label.details.split('\n')):
            bottom -= text_line
            _draw_fitted(draw, line, left, bottom, width, text_size)
    if label.name != label.code:
        bottom -= text_line
        _draw_fitted(draw, label.code, left, bottom, width, text_size)
    bottom -= gap

    kind = symbology(label.code)
    modules = barcode_modules(label.code)
    if label.composition:
        bars_px = math.ceil(MIN_BAR_MM * raster.px_per_mm) if modules is not None else 0
        top = (
            _draw_composition(
                draw,
                label.composition,
                (left, top, width, bottom - bars_px - gap - top),
                raster,
                text_size,
                (width_mm, height_mm),
            )
            + gap
        )
    if kind is not None and modules is not None:
        _require_height(label.code, height_mm, raster, bottom - top)
        _draw_bars(draw, modules, _QUIET_ZONES[kind], left, top, width, bottom - top)
    return img


def _draw_composition(
    draw: ImageDraw.ImageDraw,
    text: str,
    box: tuple[int, int, int, int],
    raster: Raster,
    ceiling: int,
    size_mm: tuple[float, float],
) -> int:
    """The ingredient list under the name, left-aligned; returns its bottom.

    As large as the room above the bars allows, up to the label's text size,
    and never under the legal x-height; a list that does not fit even then
    is refused in the reader's language, naming the label's size.
    """
    left, top, width, room = box
    floor = _x_height_size(COMPOSITION_MIN_X_HEIGHT_MM * raster.px_per_mm)

    def lines_at(size: int) -> list[str] | None:
        font = _font(size)
        lines = _wrapped_lines(draw, text, font, width, split_long_words=True)
        fits = len(lines) * round(size * LINE_SPACING) <= room
        return lines if fits and not _overflows(draw, lines, font, width) else None

    for size in range(max(ceiling, floor), floor - 1, -1):
        lines = lines_at(size)
        if lines is None:
            continue
        step = round(size * LINE_SPACING)
        for line in lines:
            draw.text((left, top), line, fill=0, font=_font(size))
            top += step
        return top
    raise catalogue_refusal(
        'product_label_composition_does_not_fit',
        width=f'{size_mm[0]:g}',
        height=f'{size_mm[1]:g}',
    )


def _x_height_size(x_height_px: float) -> int:
    """The smallest size of the label face whose letter x is *x_height_px* tall."""
    size = MIN_FONT_PX
    while True:
        bbox = _font(size).getbbox('x')
        if bbox[3] - bbox[1] >= x_height_px:
            return size
        size += 1


def _qr_square(payload: str, side_px: int) -> Image.Image:
    """The QR as large as *side_px* holds, a whole number of pixels a module."""
    qr = _qr_matrix(payload, qrcode.constants.ERROR_CORRECT_M)
    # The matrix with its quiet zone, which the square carries on every side.
    qr.box_size = max(1, side_px // len(qr.get_matrix()))
    square: Image.Image = qr.make_image(fill_color='black', back_color='white').convert(
        'L'
    )
    return square


def _require_height(code: str, height_mm: float, raster: Raster, bar_px: int) -> None:
    """Refuse a label whose bars were left less than ``MIN_BAR_MM`` of height."""
    if bar_px >= MIN_BAR_MM * raster.px_per_mm:
        return
    raise catalogue_refusal(
        'product_label_too_short', code=code, height=f'{height_mm:g}'
    )


def _padding_px(raster: Raster) -> int:
    return max(2, round(PADDING_MM * raster.px_per_mm))


def _draw_name(
    draw: ImageDraw.ImageDraw,
    name: str,
    left: int,
    top: int,
    width: int,
    label_height: int,
) -> int:
    """The name across the top, as large as two lines allow; returns its bottom."""
    ceiling = max(MIN_FONT_PX, round(label_height * NAME_RATIO))

    def fits(size: int) -> bool:
        lines = _wrapped_lines(draw, name, _font(size), width)
        return len(lines) <= NAME_MAX_LINES and not _overflows(
            draw, lines, _font(size), width
        )

    size = _largest_fitting(fits, ceiling)
    if size is None:
        # No size fits it whole: one line at the smallest size, cut short
        # with an ellipsis rather than running off the label.
        size = MIN_FONT_PX
        lines = [_clipped_to_width(draw, name, _font(size), width)]
    else:
        lines = _wrapped_lines(draw, name, _font(size), width)
    step = round(size * LINE_SPACING)
    for line in lines:
        _draw_centred(draw, line, left, top, width, size)
        top += step
    return top


def _draw_centred(
    draw: ImageDraw.ImageDraw, text: str, left: int, top: int, width: int, size: int
) -> None:
    font = _font(size)
    text = _clipped_to_width(draw, text, font, width)
    bbox = draw.textbbox((0, 0), text, font=font)
    draw.text((left + (width - (bbox[2] - bbox[0])) // 2, top), text, fill=0, font=font)


def _draw_fitted(
    draw: ImageDraw.ImageDraw, text: str, left: int, top: int, width: int, ceiling: int
) -> None:
    """A centred line at the largest size up to *ceiling* that holds it whole.

    The text size follows the label's height, so on a tall, narrow-ish label
    it is large enough that a lot and best-before line, or a long code, runs
    past the width and would be cut. It shrinks to fit instead, and is cut with an
    ellipsis only when even the smallest size cannot hold it.
    """
    size = _largest_fitting(
        lambda s: not _overflows(draw, [text], _font(s), width), ceiling
    )
    _draw_centred(draw, text, left, top, width, size or MIN_FONT_PX)


def _draw_bars(
    draw: ImageDraw.ImageDraw,
    modules: str,
    quiet: tuple[int, int],
    left: int,
    top: int,
    width: int,
    height: int,
) -> None:
    """The bars centred in the box, each module a whole number of pixels.

    ``_require_width`` and ``_require_height`` have made sure the symbol with its zones fits the box.
    """
    module_px = width // (len(modules) + quiet[0] + quiet[1])
    # The quiet zones sit inside the box: centre the symbol with its zones
    # and the bars land where the left zone ends.
    x = left + (width - module_px * (len(modules) + sum(quiet))) // 2
    x += module_px * quiet[0]
    for i, bit in enumerate(modules):
        if bit == '1':
            x0 = x + i * module_px
            draw.rectangle((x0, top, x0 + module_px - 1, top + height - 1), fill=0)
