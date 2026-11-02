"""Rendering one label to a PNG.

Three things decide whether a label looks made or looks generated, and this
file used to get all three wrong at once.

**A QR is a grid, and a grid survives only whole-number scaling.** The
generator drew it at ten pixels to a module and then LANCZOS'd the square
down to whatever the label had left. Module edges land between pixels, so
every module comes out a slightly different width with grey along its edges,
and a decoder has to guess the grid back. The module size is chosen first
now, and the code is drawn once at that size — identical squares, edges
black or white, nothing in between.

**Antialiasing is what makes letters look like letters.** The old pipeline
rendered four times over and downscaled — which does produce smooth greys —
and then threw every one of them away on ``point(p < 128)``. An office
printer lays down grey, and a screen showing the file at label size has
nothing to smooth the strokes with, so the file keeps the greys the glyphs
were drawn with. A thermal head prints a dot or no dot; making the label
1-bit for one is the print agent's job, next to the head that needs it.

**A QR does not need the whole label, and the caption is not sized by it.**
Sized as "the height, less padding", the square took 22.6 mm of a 50 x 24
label — 45% of its width — while the caption used a fifth of the room left
over. The square takes all of the height when no caption shares the label.
Beside a caption it starts from a third of the width and grows into the
height for as long as the caption keeps the size it has beside that third;
it grows past the third to keep its modules readable too, and never shrinks
them below that. The short code sits
under it as part of the same column, and the caption keeps one size of its
own beside them — whether or not the code is printed, since the sentence has
not changed when a switch is flipped.
"""

import io
import math
from collections.abc import Callable, Sequence
from functools import lru_cache
from typing import NamedTuple, Protocol

import qrcode
from PIL import Image, ImageDraw, ImageFont

from app.core.exceptions import ServiceRejectionError
from app.core.logging import get_logger
from app.core.scan_links import scan_url
from app.modules.printing.services.label_geometry import LABEL_DPI, raster_for

logger = get_logger(__name__)

FONT_BOLD = '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf'

#: The share of a label's width the square starts from when a caption shares
#: it. A share, not a size in millimetres: a fixed 18 mm cap meant that asking
#: for a 100 x 50 label bought 100 x 50 of blank paper around the same small
#: square, because the only thing the size changed was the canvas. A third
#: leaves the sentence the other two, whatever the label measures.
#:
#: It is where the square starts, not where it stops: held at a third, a
#: 50 x 24 label drew 12.3 mm of code with white above and below it while a
#: two-word caption used half of the width it was left. The square grows into
#: the label's height as long as the caption keeps the size it has here (see
#: ``_square_beside_caption``), so a short caption gets a bigger code and a
#: long one keeps the width it needs.
QR_WIDTH_SHARE = 1 / 3

#: How small a single QR module may get. A 300 dpi print at half a
#: millimetre per module is read by an ordinary phone at arm's length; below
#: that the reader starts working for it. The square is allowed to grow past
#: its share rather than fall under this, because a long scan URL needs a
#: bigger matrix and shrinking the modules to keep the square pretty is how a
#: label stops scanning.
MIN_MODULE_MM = 0.5

#: The most the floor may push the code's dark modules to span when the
#: square shares the label with a caption. The quiet zone around them is
#: paper, and is not counted. At ``MIN_MODULE_MM`` this holds 36 modules; a
#: matrix that needs more than that at error-correction M is drawn at L
#: instead (see ``_render_qr``), rather than growing past it.
#:
#: It bounds growth the floor forces, not the size a label offers. A bare
#: square (``qr_only``, or no caption to leave room for) takes the room it
#: has, at M: 19.6 mm on a 50 x 24 label at a typical address, 32 mm on the 40 x 40 square preset
#: that exists for it. Dropping to L there would buy a smaller square nobody
#: asked to be small with half the error correction.
QR_MAX_MM = 18.0

#: Modules of quiet zone the QR carries on each side.
QR_BORDER = 2

#: Below this a caption is not small, it is unreadable; a label that cannot
#: fit its text at this size is telling the caller the text is too long.
MIN_FONT_PX = 8

#: Distance between baselines, as a multiple of the font size.
LINE_SPACING = 1.25

#: The caption's size, as a fraction of the label's height. A fixed size, not
#: one derived from whatever else is on the label: the caption is the same
#: sentence about the same thing whether or not the code is printed beside
#: it, so it has no business changing size when a switch is flipped.
CAPTION_RATIO = 0.15

#: The most lines a caption wraps to before it is drawn smaller instead.
CAPTION_MAX_LINES = 3

#: The short code's size, as a fraction of the label's height. It sits under
#: the QR now rather than beside it — small is the point, as long as a person
#: can copy it out when a scan fails.
CODE_RATIO = 0.11


class LabelLike(Protocol):
    short_code: str
    description: str | None


class _Frame(NamedTuple):
    """The label's canvas and the white the layout keeps, in pixels."""

    width: int
    height: int
    #: Around the label's edge.
    padding: int
    #: Between the square's quiet zone and the caption.
    gap: int


@lru_cache(maxsize=256)
def _font(size: int) -> ImageFont.FreeTypeFont:
    """The label face at one size, kept because a sheet asks for it per label."""
    return ImageFont.truetype(FONT_BOLD, size)


def generate_label_png(
    label: LabelLike,
    width_mm: float = 50.0,
    height_mm: float = 24.0,
    base_url: str = 'http://localhost:5173',
    qr_only: bool = False,
    qr_url_override: str | None = None,
    show_code: bool = False,
    *,
    dpi: float = LABEL_DPI,
    max_height_px: int | None = None,
    edge_to_edge: bool = False,
) -> bytes:
    """Render one label as a PNG: W x H mm, whatever will print it.

    The file is the label at ``LABEL_DPI`` and says so in its header, so a
    printer driver prints it at its size. A print agent may ask for its own
    raster instead — ``dpi``, and at most ``max_height_px`` tall — and gets
    the same layout in millimetres, scaled down as a whole when the label is
    taller than that (see ``label_geometry``).

    ``qr_only`` silences the caption — including the one the API fills in
    from the assigned product when the caller sends none — and ``show_code``
    prints the short code under the square. They are independent, so all
    four arrangements are reachable: caption, caption and code, code alone,
    or the bare square.

    The code is off by default and small when it is on: on a shelf a person
    reads "minced beef 8.2026", not "STM-K9XP". It is there for the moment a
    scan fails and somebody types the code in, so it belongs to the square
    rather than to the caption's column, where it used to be the biggest
    thing on the label.

    ``edge_to_edge`` is a printer's word that it leaves a white edge of its
    own above and below the label — a P-touch's tape is wider than its head
    prints. A QR-only label, and a square beside a caption with nothing under
    it, then need no white of their own across the label: see
    ``_bare_square_edge_to_edge`` and ``_square_beside_caption``.
    """
    if width_mm <= 0 or height_mm <= 0:
        # Refused rather than clamped: the caller has asked for a label with
        # no size, and every downstream number (QR side, font size, padding)
        # is a fraction of one of these. It used to reach Pillow and come
        # back as "height and width must be > 0" from the QR resize.
        raise ServiceRejectionError('label_size_invalid')

    raster = raster_for(width_mm, height_mm, dpi, max_height_px)
    target_w, target_h = raster.width_px, raster.height_px
    px_per_mm = raster.px_per_mm

    # The QR carries the one canonical scan-link shape — scan_url() owns the
    # format (and its trailing-slash guard); extract_scan_code unwraps it.
    qr_url = qr_url_override or scan_url(label.short_code, base_url)
    caption = label.description or None
    shares_the_label = not qr_only and caption is not None

    if edge_to_edge and qr_only and not show_code:
        return _png(_bare_square_edge_to_edge(qr_url, target_w, target_h), raster.dpi)

    img = Image.new('L', (target_w, target_h), color=255)
    draw = ImageDraw.Draw(img)

    padding = max(1, round(target_h * 0.03))
    # The two switches are independent: ``qr_only`` silences the caption,
    # ``show_code`` prints the short code. Both off is the caption alone,
    # both on is the code alone — the arrangement for a label pool nobody has
    # described yet, which used to be unreachable because ``qr_only`` was
    # taken to mean "no text at all" rather than "no caption".
    prints_code = show_code
    code_line_h = (
        round(round(CODE_RATIO * target_h) * LINE_SPACING) if prints_code else 0
    )

    qr_room = target_h - 2 * padding - code_line_h
    # The share is where the square starts beside a caption, measured against
    # the label's width so it grows with it. With no caption there is nothing
    # to leave room for, and the square takes the room it has.
    preferred = (
        round(width_mm * QR_WIDTH_SHARE * px_per_mm) if shares_the_label else qr_room
    )
    min_module_px = max(1, round(MIN_MODULE_MM * px_per_mm))
    qr_img = _render_qr(
        qr_url,
        min(qr_room, preferred),
        room_px=qr_room,
        ceiling_px=math.floor(QR_MAX_MM * px_per_mm),
        min_module_px=min_module_px,
    )
    gap = max(1, round(target_h * 0.06))
    if shares_the_label and caption:
        qr_img = _square_beside_caption(
            draw,
            qr_url,
            caption,
            qr_img,
            frame=_Frame(target_w, target_h, padding, gap),
            room_px=qr_room,
            min_module_px=min_module_px,
            edge_to_edge=edge_to_edge and not prints_code,
        )
    qr_px, qr_h = qr_img.size

    # QR and short code are one column, centred together: the code belongs to
    # the square above it, not to the sentence beside it. With no sentence,
    # the column is centred on the label rather than pushed against its left
    # edge, where it reads as something missing beside it.
    column_left = padding if shares_the_label else max(padding, (target_w - qr_px) // 2)
    column_top = (target_h - (qr_h + code_line_h)) // 2
    img.paste(qr_img, (column_left, column_top))
    if prints_code:
        _draw_code_under_qr(
            draw, label.short_code, column_left, column_top + qr_h, qr_px, target_h
        )

    if shares_the_label:
        text_x = column_left + qr_px + gap
        _render_caption(
            draw,
            caption,
            text_x=text_x,
            box_width=target_w - text_x - padding,
            box_height=target_h - 2 * padding,
            canvas_height=target_h,
        )

    return _png(img, raster.dpi)


def _png(img: Image.Image, dpi: float, *, optimize: bool = True) -> bytes:
    """The image as PNG bytes that state their resolution.

    Without it a driver or an image viewer has to guess the size, and prints
    the label at whatever resolution it assumes rather than at its own.
    """
    buffer = io.BytesIO()
    img.save(buffer, format='PNG', optimize=optimize, dpi=(dpi, dpi))
    return buffer.getvalue()


def _render_qr(
    url: str, max_px: int, *, room_px: int, ceiling_px: int, min_module_px: int
) -> Image.Image:
    """The QR at a whole number of pixels per module, drawn once.

    Returns a square at most ``max_px`` across — usually a little less,
    because the side is a multiple of the module count and the remainder is
    left to the label rather than smeared across the grid by a resize.

    ``max_px`` is a preference, ``min_module_px`` is not. A longer scan URL
    needs more modules, and holding the square at its preferred size would
    pay for them by making each module smaller until the code stops being
    read. When that happens the square grows instead, up to ``room_px`` —
    the label runs out of space before the reader runs out of patience. The
    same rule saves a small label, where a third of the width is not enough
    square to carry the matrix.

    Error correction is the one other thing that buys modules. Level M
    rebuilds 15% of a damaged code and is what a label gets whenever growing
    can save the floor. Where growing is the floor's doing — ``max_px``
    would put the modules under it — and the grown square would span more
    than ``ceiling_px`` of dark modules, or more than the label's
    ``room_px``, level L (7%) is taken instead if it needs fewer modules.
    A long base URL beside a caption is where that happens: 58 characters
    need 37 dark modules at M, 18.8 mm at the floor, and 33 at L, 16.8 mm.
    A bare square is never there: ``max_px`` is its whole room, and what it
    spans is the label's offer, not the floor's demand (see ``QR_MAX_MM``).
    """

    def outgrows(modules: int) -> bool:
        dark_px = (modules - 2 * QR_BORDER) * min_module_px
        return modules * min_module_px > room_px or dark_px > ceiling_px

    qr = _qr_matrix(url, qrcode.constants.ERROR_CORRECT_M)
    modules = len(qr.get_matrix())
    if max_px // modules < min_module_px and outgrows(modules):
        sparer = _qr_matrix(url, qrcode.constants.ERROR_CORRECT_L)
        if len(sparer.get_matrix()) < modules:
            qr, modules = sparer, len(sparer.get_matrix())
    box = max_px // modules
    if box < min_module_px:
        box = min(min_module_px, room_px // modules)
    qr.box_size = max(1, box)
    grey: Image.Image = qr.make_image(fill_color='black', back_color='white').convert(
        'L'
    )
    return grey


def _bare_square_edge_to_edge(url: str, width_px: int, height_px: int) -> Image.Image:
    """A bare QR as tall as the label, for a printer with white edges of its own.

    On 24 mm tape a P-touch prints 128 dots across and leaves 3 mm white on
    either side. Drawn like a paper label, the square kept 3% padding and a
    two-module quiet zone inside those 128 dots, and its modules had to be
    whole dots: a 29-module code got 3 dots a module, 12.3 mm on 24 mm tape,
    and the white took almost half of it. The tape's own edges are wider than
    the quiet zone a reader needs, so across the tape the square takes the
    whole height: 4 dots a module, 16.4 mm. Along the tape there is no such
    edge, so the quiet zone stays there, and the label grows to hold it when
    it is shorter than the code with its quiet zone.

    Error correction stays at M: the room is the label's height, and level L
    would buy a bigger square by halving how much damage the code survives.
    """
    qr = _qr_matrix(url, qrcode.constants.ERROR_CORRECT_M)
    box = max(1, height_px // qr.modules_count)
    qr.box_size = box
    qr.border = 0
    square = qr.make_image(fill_color='black', back_color='white').convert('L')
    side = square.size[0]
    width = max(width_px, side + 2 * QR_BORDER * box)
    img = Image.new('L', (width, height_px), color=255)
    img.paste(square, ((width - side) // 2, (height_px - side) // 2))
    return img


def _square_beside_caption(
    draw: ImageDraw.ImageDraw,
    url: str,
    caption: str,
    third: Image.Image,
    *,
    frame: _Frame,
    room_px: int,
    min_module_px: int,
    edge_to_edge: bool,
) -> Image.Image:
    """The biggest square that leaves the caption the size it has beside a third.

    ``third`` is the square at its share of the label's width. Held there, a
    50 x 24 label drew 14.7 mm of code at a typical address and left white
    above and below it, while a two-word caption used half the width it was
    left. The square grows a whole pixel a module at a time, up to the
    label's height, and keeps the biggest step at which the caption is still
    drawn whole at the size it has beside ``third``. A caption long enough to
    need its width stops the growth at the first step, and the label is drawn
    as it was.

    The bigger square is drawn at M, as a bare square is: the label offers
    the room, nothing forces it, so there is no reason to spend correction.

    On a printer with white edges of its own (``edge_to_edge``) the square
    loses its quiet zone across the label and takes the whole height, as a
    bare one does: 24 mm tape gives a 29-module code 4 dots a module, 16.4 mm,
    where the third gave it 3. The quiet zone along the label stays, before
    the code and between it and the caption.
    """
    caption_room = frame.height - 2 * frame.padding
    max_size = round(CAPTION_RATIO * frame.height)

    def caption_size(square_width: int) -> int | None:
        box_width = frame.width - square_width - frame.gap - 2 * frame.padding
        if box_width <= 0:
            return None
        try:
            return _caption_size(draw, caption, box_width, caption_room, max_size)
        except OSError:
            # No usable font on this machine: there is no caption size to
            # keep, so the square stays at its third and ``_render_caption``
            # draws what it can, as it did before the square grew.
            return None

    wanted = caption_size(third.size[0])
    if wanted is None:
        return third
    qr = _qr_matrix(url, qrcode.constants.ERROR_CORRECT_M)
    modules = len(qr.get_matrix())
    across = modules - 2 * QR_BORDER if edge_to_edge else modules
    top = (frame.height if edge_to_edge else room_px) // across
    # Where the room cannot hold the floor, the third is drawn under it too,
    # and the biggest step the room holds is the one left to try.
    for box in range(top, min(min_module_px, top) - 1, -1):
        if modules * box <= third.size[0]:
            break
        size = caption_size(modules * box)
        if size is None or size < wanted:
            continue
        qr.box_size = box
        square: Image.Image = qr.make_image(
            fill_color='black', back_color='white'
        ).convert('L')
        if edge_to_edge:
            quiet = QR_BORDER * box
            square = square.crop((0, quiet, square.size[0], square.size[1] - quiet))
        return square
    return third


def _qr_matrix(url: str, error_correction: int) -> qrcode.QRCode:
    """The smallest QR that holds *url* at one error-correction level."""
    qr = qrcode.QRCode(
        version=None,  # Auto-version based on data size
        error_correction=error_correction,
        box_size=1,
        border=QR_BORDER,
    )
    qr.add_data(url)
    qr.make(fit=True)
    return qr


def _draw_code_under_qr(
    draw: ImageDraw.ImageDraw,
    short_code: str,
    left: int,
    top: int,
    width: int,
    canvas_height: int,
) -> None:
    """The short code centred under the square, shrunk to the square's width.

    It used to stand beside the QR in the caption's column, where it was the
    biggest thing on the label and the caption a footnote under it. Nobody
    reads a shelf by short code; it is there for the moment a scan fails and
    somebody types it in, so it belongs to the square and stays small.
    """

    def fits(size: int) -> bool:
        bbox = draw.textbbox((0, 0), short_code, font=_font(size))
        return bbox[2] - bbox[0] <= width

    size = _largest_fitting(fits, round(CODE_RATIO * canvas_height))
    if size is None:
        # A short code wider than the square at the smallest size. It is one
        # token with nowhere to wrap, so the only way to keep it inside the
        # label is to show as much as fits and say that it is cut — an
        # unmarked truncation reads as a whole code and gets typed in as one.
        font = _font(MIN_FONT_PX)
        text = _clipped_to_width(draw, short_code, font, width)
    else:
        font = _font(size)
        text = short_code
    bbox = draw.textbbox((0, 0), text, font=font)
    draw.text((left + (width - (bbox[2] - bbox[0])) // 2, top), text, fill=0, font=font)


def _wrapped_lines(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.FreeTypeFont,
    max_width: int,
    *,
    split_long_words: bool = False,
) -> list[str]:
    """Break `text` into lines, each no wider than `max_width` if it can be.

    A word longer than the whole box normally gets a line to itself and
    overflows it — wrapping cannot help a single word, and hyphenating a
    product name would invent a break that is not in it. ``_overflows`` is
    what stops that line from being accepted at a size where it does not fit.

    ``split_long_words`` is the last resort for when no size works at all: a
    single unbroken run of characters wider than the box at the smallest
    legible size. Then the choice is not between a break and no break, it is
    between a break and a line running off the label, so the run is cut into
    pieces that fit.
    """
    lines: list[str] = []
    current: list[str] = []
    for word in text.split():
        candidate = ' '.join([*current, word])
        bbox = draw.textbbox((0, 0), candidate, font=font)
        if bbox[2] - bbox[0] <= max_width:
            current.append(word)
            continue
        if current:
            lines.append(' '.join(current))
            current = []
        if split_long_words and _text_width(draw, word, font) > max_width:
            *whole, last = _split_to_width(draw, word, font, max_width)
            lines.extend(whole)
            current = [last]
        else:
            current = [word]
    if current:
        lines.append(' '.join(current))
    return lines


def _text_width(
    draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont
) -> int:
    """How wide `text` comes out, rounded away from the box it must fit.

    ``textbbox`` measures in floats. Rounding a width of 40.4 down to 40
    would let a line that is four tenths of a pixel too wide report that it
    fits, which is the wrong direction to be wrong in for a guard whose one
    job is keeping ink off the edge.
    """
    bbox = draw.textbbox((0, 0), text, font=font)
    return math.ceil(bbox[2] - bbox[0])


def _clipped_to_width(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.FreeTypeFont,
    max_width: int,
) -> str:
    """As much of `text` as fits `max_width`, with an ellipsis for the rest.

    The ellipsis is not decoration. A code cut without one looks like a
    whole code, and the whole reason the short code is on the label is that
    somebody types it in when a scan fails.
    """
    ellipsis = '\u2026'
    if _text_width(draw, text, font) <= max_width:
        return text
    kept = ''
    for char in text:
        if _text_width(draw, kept + char + ellipsis, font) > max_width:
            break
        kept += char
    return (kept + ellipsis) if kept else ellipsis


def _split_to_width(
    draw: ImageDraw.ImageDraw,
    word: str,
    font: ImageFont.FreeTypeFont,
    max_width: int,
) -> list[str]:
    """One over-long run cut into pieces, none wider than `max_width`.

    Greedy by character, because the run has no word boundary to respect —
    a serial number, a URL, a scanned code typed in as one string. At least
    one character goes on every piece even when a single glyph is wider than
    the box, so the loop cannot stall on an impossible width.
    """
    pieces: list[str] = []
    current = ''
    for char in word:
        if current and _text_width(draw, current + char, font) > max_width:
            pieces.append(current)
            current = char
        else:
            current += char
    pieces.append(current)
    return pieces


def _overflows(
    draw: ImageDraw.ImageDraw,
    lines: list[str],
    font: ImageFont.FreeTypeFont,
    max_width: int,
) -> bool:
    """True when any line is wider than the box it has to sit in.

    The fitter used to ask only how many lines the text broke into, never
    how wide they came out. A caption whose longest word does not fit was
    then accepted at any size: "opis etykiety" printed at full height with
    "etykiety" running off the right edge of the label — visible in the
    preview, and cut off by the die on paper.
    """
    return any(draw.textbbox((0, 0), line, font=font)[2] > max_width for line in lines)


def _largest_fitting(fits: Callable[[int], bool], ceiling: int) -> int | None:
    """The biggest font size for which `fits` holds, by bisection.

    The old fitter only ever shrank, from a start size that was a fraction
    of the label's height. That is why a two-word caption came out under
    2 mm tall in a box 20 mm high: nothing in the loop could make it grow
    into the room it had. Searching from both ends means the text is as
    large as its box allows, whatever the box turned out to be.

    ``None`` when even ``MIN_FONT_PX`` does not fit, and that return is the
    whole point of the signature. Seeding ``best`` with the floor instead
    made the fitter answer "8 px" to a question it had failed: a run of
    characters with no space in it was drawn at the smallest size and ran
    off the label anyway, with ``_overflows`` reporting the failure to
    nobody. A fitter that cannot fail cannot be trusted by its callers.
    """
    low, high = MIN_FONT_PX, max(MIN_FONT_PX, ceiling)
    best: int | None = None
    while low <= high:
        mid = (low + high) // 2
        if fits(mid):
            best, low = mid, mid + 1
        else:
            high = mid - 1
    return best


def _caption_size(
    draw: ImageDraw.ImageDraw,
    text: str,
    max_width: int,
    max_height: int,
    max_size: int,
    max_lines: int = CAPTION_MAX_LINES,
) -> int | None:
    """The largest size at which `text` fits its box whole, or None."""

    def fits(size: int) -> bool:
        font = _font(size)
        lines = _wrapped_lines(draw, text, font, max_width)
        return (
            len(lines) <= max_lines
            and not _overflows(draw, lines, font, max_width)
            and len(lines) * round(size * LINE_SPACING) <= max_height
        )

    return _largest_fitting(fits, min(max_height, max_size))


def _fitted_caption(
    draw: ImageDraw.ImageDraw,
    text: str,
    max_width: int,
    max_height: int,
    max_lines: int,
    max_size: int,
) -> tuple[ImageFont.FreeTypeFont, list[str], int]:
    """The largest size at which `text` fits the space it has been given.

    ``max_height`` bounds the whole block, ``max_size`` a single line — two
    different limits that must not be confused. Bounded by height alone, a
    two-word caption grows until it fills a 24 mm label, which reads as a
    poster; bounded by size alone, a caption that wraps to three lines walks
    off the bottom.
    """
    size = _caption_size(draw, text, max_width, max_height, max_size, max_lines)
    if size is not None:
        font = _font(size)
        return (
            font,
            _wrapped_lines(draw, text, font, max_width)[:max_lines],
            round(size * LINE_SPACING),
        )

    # Nothing fits, so the caption carries a run of characters with no space
    # in it that is wider than its box even at the smallest legible size — a
    # serial number, a URL, a code typed in as one string. Drawing it anyway
    # is what put text over the edge of the label; cut it into pieces that
    # fit instead. The line budget still applies, so a run long enough to
    # exhaust it loses its tail rather than the label losing its margin.
    font = _font(MIN_FONT_PX)
    return (
        font,
        _wrapped_lines(draw, text, font, max_width, split_long_words=True)[:max_lines],
        round(MIN_FONT_PX * LINE_SPACING),
    )


def _render_caption(
    draw: ImageDraw.ImageDraw,
    caption: str | None,
    *,
    text_x: int,
    box_width: int,
    box_height: int,
    canvas_height: int,
) -> None:
    """Draw the caption beside the QR, at one size whatever else is printed.

    The caption used to be sized against the short code — so flipping "also
    print the code" changed the sentence's size, though the sentence had not
    changed. It is a fraction of the label now, shrinking only when the text
    is too long for the room, and the code has moved under the square where
    it does not compete for the width.
    """
    if not caption or box_width <= 0 or box_height <= 0:
        return

    try:
        font, lines, line_height = _fitted_caption(
            draw,
            caption,
            box_width,
            box_height,
            max_lines=CAPTION_MAX_LINES,
            max_size=round(CAPTION_RATIO * canvas_height),
        )
        start_y = (canvas_height - len(lines) * line_height) // 2
        for index, line in enumerate(lines):
            draw.text((text_x, start_y + index * line_height), line, fill=0, font=font)
    except OSError as exc:
        # No usable font on this machine. Draw what can be drawn rather than
        # failing the whole label: a QR with no caption still scans.
        logger.error(f'Font loading failed: {exc}')
        draw.text(
            (text_x, canvas_height // 2),
            caption[:20],
            fill=0,
            font=ImageFont.load_default(),
        )


def generate_label_batch_png(
    labels: Sequence[LabelLike],
    width_mm: float = 50.0,
    height_mm: float = 24.0,
    columns: int = 100,
    base_url: str = 'http://localhost:5173',
    qr_only: bool = False,
    show_code: bool = False,
    *,
    dpi: float = LABEL_DPI,
    max_height_px: int | None = None,
    edge_to_edge: bool = False,
) -> bytes:
    """
    Generates a sheet with multiple labels with ZERO extra margins.
    """
    if not labels:
        raise ServiceRejectionError('no_labels_available')

    # Every tile renders exactly once, and only then is the grid measured —
    # from the widest of them. Tiles are all one size now that nothing is
    # cropped to its content, but the grid measured on tiles[0] once let a
    # wider one land on its neighbour, and measuring every tile costs nothing.
    tiles = [
        Image.open(
            io.BytesIO(
                generate_label_png(
                    label,
                    width_mm,
                    height_mm,
                    base_url=base_url,
                    qr_only=qr_only,
                    show_code=show_code,
                    dpi=dpi,
                    max_height_px=max_height_px,
                    edge_to_edge=edge_to_edge,
                )
            )
        )
        for label in labels
    ]

    return sheet_png(
        tiles, columns, raster_for(width_mm, height_mm, dpi, max_height_px).dpi
    )


def sheet_png(tiles: Sequence[Image.Image], columns: int, dpi: float) -> bytes:
    """Rendered labels laid out in a grid, with no margin at the sheet's edges."""
    label_w = max(tile.width for tile in tiles)
    label_h = max(tile.height for tile in tiles)
    gap = 10
    actual_cols = min(len(tiles), columns)
    rows = math.ceil(len(tiles) / actual_cols)

    # No extra margins at the edges
    img_w = actual_cols * label_w + (actual_cols - 1) * gap
    img_h = rows * label_h
    # The sheet is whatever the tiles are: greyscale, so the antialiasing
    # each label was drawn with survives being pasted onto it.
    batch_img = Image.new(tiles[0].mode, (img_w, img_h), color=255)

    for idx, tile in enumerate(tiles):
        col, row = idx % actual_cols, idx // actual_cols
        batch_img.paste(tile, (col * (label_w + gap), row * label_h))

    # Every tile states the same resolution; the sheet states it too, so a
    # driver prints each label on it at its size.
    # Not optimized, as before: a sheet of a hundred labels is a large image
    # and the smaller file is not worth the time.
    return _png(batch_img, dpi, optimize=False)
