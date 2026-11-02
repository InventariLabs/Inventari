import io
from collections.abc import Callable, Sequence
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
import qrcode
from PIL import Image

from app.core.scan_links import scan_url
from app.modules.printing.services import label_print_service as lps
from app.modules.printing.services.label_geometry import raster_for
from app.modules.printing.services.label_print_service import (
    generate_label_batch_png,
    generate_label_png,
)


def _make_label(
    short_code: str = 'ABC123', description: str | None = 'Test Product'
) -> MagicMock:
    label = MagicMock()
    label.short_code = short_code
    label.description = description
    return label


def _dark_bbox(img: Image.Image) -> tuple[int, int, int, int] | None:
    """Bounding box of the dark pixels, or None for a blank image."""
    return Image.eval(img.convert('L'), lambda v: 255 if v < 128 else 0).getbbox()


def _assert_every_tile_sits_whole_in_its_slot(
    sheet: Image.Image,
    tiles: Sequence[Image.Image],
    slot: int,
    gap: int,
    columns: int = 100,
) -> None:
    """Placement, not canvas size: tile k's ink lies wholly inside its slot,
    at the place its own render puts it, and the gap columns stay white.
    A canvas of the right size with tiles stepped on the wrong pitch passes
    every dimension check and fails this one."""
    cols = min(len(tiles), columns)
    row_h = max(tile.height for tile in tiles)
    pitch = slot + gap
    sheet_l = sheet.convert('L')

    for idx, tile in enumerate(tiles):
        col, row = idx % cols, idx // cols
        x0, y0 = col * pitch, row * row_h
        own = _dark_bbox(tile)
        assert own is not None, f'tile {idx} drew nothing'
        in_slot = sheet_l.crop((x0, y0, x0 + slot, y0 + row_h))
        found = _dark_bbox(in_slot)
        assert found == own, f'tile {idx} ink is {found} in its slot, expected {own}'
        assert list(in_slot.crop((0, 0, tile.width, tile.height)).getdata()) == list(
            tile.convert('L').getdata()
        ), f'tile {idx} is not pasted whole into its slot'

    # Everything outside the slots is paper.
    for col in range(cols - 1):
        gx = col * pitch + slot
        gap_cols = sheet_l.crop((gx, 0, gx + gap, sheet.height))
        assert _dark_bbox(gap_cols) is None, f'ink in the gap after column {col}'


#: A caption that needs the two thirds of a 50 x 24 label it is left.
LONG_CAPTION = 'Minced beef from the shoulder, frozen 8.2026, for goulash'


def _held_at_a_third() -> Any:
    """The layout before the square grew: it stays at its third beside a caption."""
    return patch.object(
        lps,
        '_square_beside_caption',
        lambda _draw, _url, _caption, third, **_: third,
    )


def _caption_as_drawn(render: Callable[[], bytes]) -> tuple[int, str]:
    """The font size and the words a label's caption was drawn with."""
    drawn: list[tuple[int, str]] = []
    real = lps._fitted_caption

    def recording(*args: Any, **kwargs: Any) -> Any:
        font, lines, line_height = real(*args, **kwargs)
        drawn.append((int(font.size), ' '.join(lines)))
        return font, lines, line_height

    with patch.object(lps, '_fitted_caption', recording):
        render()
    assert len(drawn) == 1
    return drawn[0]


@pytest.mark.unit
class TestGenerateLabelPng:
    def test_qr_only_mode(self) -> None:
        label = _make_label()
        result = generate_label_png(label, qr_only=True)
        assert isinstance(result, bytes)
        assert len(result) > 0
        img = Image.open(__import__('io').BytesIO(result))
        assert img.format == 'PNG'

    def test_a_label_with_no_size_is_refused(self) -> None:
        """Every other number on the label is a fraction of these two.

        This used to reach Pillow and come back from the QR resize, which
        told the caller about a resize they never asked for.
        """
        label = _make_label()
        with pytest.raises(ValueError, match='height and width must be > 0'):
            generate_label_png(label, height_mm=0)

    def test_qr_url_override(self) -> None:
        label = _make_label()
        result = generate_label_png(label, qr_url_override='https://custom.url/scan')
        assert isinstance(result, bytes)

    def test_no_description(self) -> None:
        label = _make_label(description=None)
        result = generate_label_png(label)
        assert isinstance(result, bytes)

    def test_empty_description(self) -> None:
        label = _make_label(description='')
        result = generate_label_png(label)
        assert isinstance(result, bytes)

    def test_long_description_wraps(self) -> None:
        label = _make_label(
            description='This is a very long description that should wrap to multiple lines on the label'
        )
        result = generate_label_png(label)
        assert isinstance(result, bytes)


@pytest.mark.unit
class TestGenerateLabelBatchPng:
    def test_single_label_batch(self) -> None:
        labels = [_make_label('A1', 'Product A')]
        result = generate_label_batch_png(labels)
        assert isinstance(result, bytes)
        img = Image.open(__import__('io').BytesIO(result))
        assert img.format == 'PNG'

    def test_multiple_labels_same_row(self) -> None:
        labels = [_make_label(f'L{i}') for i in range(3)]
        result = generate_label_batch_png(labels, columns=100)
        img = Image.open(__import__('io').BytesIO(result))
        assert img.format == 'PNG'
        tiles = [Image.open(io.BytesIO(generate_label_png(tile))) for tile in labels]
        slot = max(tile.width for tile in tiles)
        assert img.width == slot * 3 + 10 * 2
        _assert_every_tile_sits_whole_in_its_slot(img, tiles, slot, 10)

    def test_labels_wrap_to_next_row(self) -> None:
        labels = [_make_label(f'L{i}') for i in range(5)]
        result = generate_label_batch_png(labels, columns=3)
        img = Image.open(__import__('io').BytesIO(result))
        assert img.format == 'PNG'
        tiles = [Image.open(io.BytesIO(generate_label_png(tile))) for tile in labels]
        slot = max(tile.width for tile in tiles)
        assert img.size == (slot * 3 + 10 * 2, tiles[0].height * 2)
        _assert_every_tile_sits_whole_in_its_slot(img, tiles, slot, 10, columns=3)

    def test_batch_with_qr_only(self) -> None:
        labels = [_make_label('QR1'), _make_label('QR2')]
        result = generate_label_batch_png(labels, qr_only=True)
        assert isinstance(result, bytes)

    def test_qr_uses_error_correct_m_and_border_2(self) -> None:
        with patch(
            'app.modules.printing.services.label_print_service.qrcode.QRCode'
        ) as mock_qr_cls:
            mock_qr_instance = mock_qr_cls.return_value
            mock_qr_instance.make_image.return_value = Image.new('L', (100, 100))
            mock_qr_instance.get_matrix.return_value = [[True] * 25] * 25
            generate_label_png(_make_label('STM-QR'))
            _, kwargs = mock_qr_cls.call_args
            assert kwargs['version'] is None
            assert kwargs['error_correction'] == qrcode.constants.ERROR_CORRECT_M
            assert kwargs['border'] == 2
            # The construction size no longer decides anything: the module
            # size is set from the room the label has, once the matrix is
            # known, and is a whole number of pixels. The property that
            # matters is measured on a real render — see
            # TestTheCodeIsAGridNotAPicture.
            assert isinstance(mock_qr_instance.box_size, int)
            assert mock_qr_instance.box_size >= 1


@pytest.mark.unit
class TestTheImageIsTheLabel:
    """A file for a 50 x 24 label is 50 x 24 mm, and says so.

    It used to depend on a media profile. The tape one drew only the
    cassette's printable strip, snapped its height and cropped the label to
    its content, so one label had a size in the settings, another in the file,
    a third in the preview and a fourth on the tape. There is one geometry
    now, the label's own, for the download, the preview and the printer.
    """

    def test_a_label_is_its_size_in_millimetres_at_300_dpi(self) -> None:
        img = Image.open(io.BytesIO(generate_label_png(_make_label(), 50.0, 24.0)))

        assert img.size == (591, 283)
        assert img.info['dpi'] == pytest.approx((300, 300), abs=0.5)

    def test_a_square_alone_is_not_cropped_to_itself(self) -> None:
        """The code alone used to come out as a 12 x 18 mm strip of a 50 x 24."""
        img = Image.open(
            io.BytesIO(
                generate_label_png(
                    _make_label(), 50.0, 24.0, qr_only=True, show_code=True
                )
            )
        )

        assert img.size == (591, 283)

    def test_a_sheet_of_labels_states_the_resolution_too(self) -> None:
        labels = [_make_label('A-1', 'first'), _make_label('B-2', 'second')]

        img = Image.open(io.BytesIO(generate_label_batch_png(labels, 50.0, 24.0)))

        assert img.height == 283
        assert img.info['dpi'] == pytest.approx((300, 300), abs=0.5)

    def test_a_sheet_label_has_the_proportions_it_was_asked_for(self) -> None:
        img = Image.open(io.BytesIO(generate_label_png(_make_label(), 50.0, 24.0)))

        assert img.width / img.height == pytest.approx(50 / 24, rel=0.01)

    def test_every_preset_keeps_its_proportions(self) -> None:
        for width_mm, height_mm in (
            (50.0, 24.0),
            (38.0, 15.0),
            (62.0, 29.0),
            (50.0, 12.0),
            (100.0, 50.0),
        ):
            img = Image.open(
                io.BytesIO(generate_label_png(_make_label(), width_mm, height_mm))
            )
            assert img.width / img.height == pytest.approx(
                width_mm / height_mm, rel=0.01
            ), f'{width_mm}x{height_mm}'

    def test_a_sheet_label_is_not_trimmed_to_its_content(self) -> None:
        """A die-cut label is the size it is; a trimmed image prints short."""
        short = Image.open(io.BytesIO(generate_label_png(_make_label('A', 'B'))))
        long = Image.open(
            io.BytesIO(
                generate_label_png(_make_label('LONG-CODE-12345', 'A longer caption'))
            )
        )

        assert short.size == long.size


def _dark_pixels(image: Image.Image) -> tuple[list[int], int, int]:
    """Flat 0/1 map of where the image carries ink, with its dimensions."""
    grey = image.convert('L')
    width, height = grey.size
    values: list[int] = list(grey.getdata())
    return [1 if value < 128 else 0 for value in values], width, height


def _ink_columns(image: Image.Image) -> list[int]:
    """Columns of the image that carry any ink at all."""
    ink, width, height = _dark_pixels(image)
    return [x for x in range(width) if any(ink[y * width + x] for y in range(height))]


def _greys(image: Image.Image) -> int:
    """Pixels that are neither ink nor paper — the antialiasing."""
    values: list[int] = list(image.convert('L').getdata())
    return sum(1 for value in values if 20 < value < 235)


def _qr_box(image: Image.Image) -> tuple[int, int, int, int]:
    """Bounding box of the inked block on the left — the QR's dark modules."""
    ink, width, height = _dark_pixels(image)
    columns = _ink_columns(image)
    left = last = min(columns)
    for x in columns:
        if x - last > image.width * 0.02:
            break
        last = x
    rows = [
        y
        for y in range(height)
        if any(ink[y * width + x] for x in range(left, last + 1))
    ]
    return left, rows[0], last, rows[-1]


@pytest.mark.unit
@pytest.mark.unit
class TestTheCodeIsAGridNotAPicture:
    """A QR resized by a fraction stops being a grid.

    It was drawn ten pixels to a module and then LANCZOS'd down to whatever
    the label had left over. Module edges land between pixels: every module
    comes out a slightly different width, with grey along its edges, and a
    decoder has to guess the grid back from it.
    """

    def test_the_code_is_drawn_at_whole_pixels_per_module(self) -> None:
        label = _make_label('STM-K9XP', 'Minced beef 8.2026')
        image = Image.open(io.BytesIO(generate_label_png(label)))

        qr = qrcode.QRCode(
            version=None,
            error_correction=qrcode.constants.ERROR_CORRECT_M,
            box_size=1,
            border=2,
        )
        qr.add_data(scan_url(label.short_code, 'http://localhost:5173'))
        qr.make(fit=True)
        # The quiet zone is white, so what can be measured is the dark span:
        # the matrix less its two-module border on each side.
        dark_modules = len(qr.get_matrix()) - 4

        left, top, right, bottom = _qr_box(image)
        assert (right - left + 1) % dark_modules == 0
        assert (bottom - top + 1) == (right - left + 1)

    def test_the_code_carries_no_half_tones(self) -> None:
        """Grey inside a QR is the fingerprint of a resize.

        Passes on the old renderer too, which is worth saying: there the
        whole label was thresholded to 1-bit at the end, so the resize's
        greys were flattened along with the letters' antialiasing. Now that
        a sheet label keeps its greys, this is what stops a resize from
        coming back into the code unnoticed.
        """
        image = Image.open(io.BytesIO(generate_label_png(_make_label()))).convert('L')
        left, top, right, bottom = _qr_box(image)

        assert _greys(image.crop((left, top, right + 1, bottom + 1))) == 0


@pytest.mark.unit
class TestALabelForThePrintersRaster:
    """A print agent asks for the label at its own raster.

    A 180 dpi head printing a 300 dpi file resampled to it puts the QR's
    modules on two dots and three in turn — the grid a decoder has to guess
    back. Drawn at the head's own resolution, a module is whole dots again,
    and the layout in millimetres is the same label.
    """

    def test_a_label_that_fits_is_drawn_at_the_printers_resolution(self) -> None:
        img = Image.open(
            io.BytesIO(
                generate_label_png(
                    _make_label(), 50.0, 18.0, dpi=180, max_height_px=128
                )
            )
        )

        assert img.size == (354, 128)
        assert img.info['dpi'] == pytest.approx((180, 180), abs=0.5)

    def test_a_label_taller_than_the_head_is_scaled_down_whole(self) -> None:
        """A 24 mm label on 24 mm tape: the head prints 18 of them."""
        raster = raster_for(50.0, 24.0, dpi=180, max_height_px=128)
        img = Image.open(
            io.BytesIO(
                generate_label_png(
                    _make_label(), 50.0, 24.0, dpi=180, max_height_px=128
                )
            )
        )

        assert raster.scale == pytest.approx(0.75, abs=0.01)
        assert img.height == 128
        assert img.width / img.height == pytest.approx(50 / 24, rel=0.01)

    @pytest.mark.parametrize('batch', [False, True], ids=['single', 'sheet'])
    def test_a_shrunk_label_states_the_printers_resolution(self, batch: bool) -> None:
        """The file says how big it prints: the shrunk size, not the label's.

        A driver that honours the stated resolution would otherwise stretch
        the 128 dots back to 24 mm, and the shrink the agent reports would
        not be what comes out of the printer.
        """
        png = (
            generate_label_batch_png(
                [_make_label()], 50.0, 24.0, columns=1, dpi=180, max_height_px=128
            )
            if batch
            else generate_label_png(
                _make_label(), 50.0, 24.0, dpi=180, max_height_px=128
            )
        )
        img = Image.open(io.BytesIO(png))
        dpi_x, dpi_y = img.info['dpi']

        assert (dpi_x, dpi_y) == pytest.approx((180, 180), abs=0.5)
        assert img.height / dpi_y * 25.4 == pytest.approx(18.06, abs=0.1)
        assert img.width / dpi_x * 25.4 == pytest.approx(37.7, abs=0.2)

    def test_a_raster_with_room_to_spare_changes_nothing(self) -> None:
        assert raster_for(50.0, 24.0, max_height_px=1000) == raster_for(50.0, 24.0)
        assert raster_for(50.0, 24.0).scale == 1.0

    def test_the_code_is_whole_dots_at_the_printers_raster(self) -> None:
        label = _make_label('STM-K9XP', 'Minced beef 8.2026')
        image = Image.open(
            io.BytesIO(
                generate_label_png(label, 50.0, 24.0, dpi=180, max_height_px=128)
            )
        )
        qr = qrcode.QRCode(
            version=None,
            error_correction=qrcode.constants.ERROR_CORRECT_M,
            box_size=1,
            border=2,
        )
        qr.add_data(scan_url(label.short_code, 'http://localhost:5173'))
        qr.make(fit=True)
        dark_modules = len(qr.get_matrix()) - 4

        left, top, right, bottom = _qr_box(image)

        assert (right - left + 1) % dark_modules == 0
        assert _greys(image.convert('L').crop((left, top, right + 1, bottom + 1))) == 0


@pytest.mark.unit
@pytest.mark.unit
class TestLettersKeepTheirEdges:
    """Antialiasing is what makes letters look like letters.

    The generator rendered four times over and downscaled — which does
    produce smooth greys — and then threw every one of them away on a
    threshold. That is all a thermal head can print, and it is not what an
    office printer or a screen does with the file.
    """

    def test_a_sheet_label_keeps_the_greys_its_letters_were_drawn_with(self) -> None:
        image = Image.open(
            io.BytesIO(generate_label_png(_make_label('STM-K9XP'), show_code=True))
        )

        assert image.mode == 'L'
        assert _greys(image) > 0

    def test_a_sheet_of_labels_is_not_flattened_by_the_canvas(self) -> None:
        """A 1-bit sheet would threshold every tile pasted onto it."""
        labels = [_make_label('A-1', 'first'), _make_label('B-2', 'second')]

        image = Image.open(io.BytesIO(generate_label_batch_png(labels)))

        assert image.mode == 'L'
        assert _greys(image) > 0


@pytest.mark.unit
@pytest.mark.unit
class TestTheSquareLeavesRoomForTheRest:
    """The square was sized as "the label's height, less padding".

    On a 50 x 24 sheet label that is 22.6 mm — 45% of the label — while the
    caption used a fifth of the room left over, because its fitter could
    only ever shrink from a fraction of the label's height.

    The square still grows into the height beside a caption that keeps its
    size by it (``TestBesideACaptionTheSquareTakesTheHeight``); these are the
    labels whose caption needs the width, where it stays at its share.
    """

    def test_the_square_leaves_the_label_more_than_it_takes(self) -> None:
        image = Image.open(
            io.BytesIO(generate_label_png(_make_label(description=LONG_CAPTION)))
        )

        left, _, right, _ = _qr_box(image)
        assert (right - left + 1) < image.width * 0.35

    def test_the_square_grows_with_the_label(self) -> None:
        """The cap used to be 18 mm whatever the label measured.

        So asking for a 100 x 50 label bought 100 x 50 of blank paper around
        the same small square: the only thing the size changed was the area
        around the code. The share is measured against the width now.
        """
        label = _make_label('STM-K9XP', 'Minced beef 8.2026')

        def module_mm(width_mm: float, height_mm: float) -> float:
            image = Image.open(
                io.BytesIO(generate_label_png(label, width_mm, height_mm))
            )
            return _module_px(image) / (image.height / height_mm)

        assert module_mm(100.0, 50.0) > module_mm(50.0, 24.0) * 1.5

    def test_a_lone_square_takes_the_room_no_caption_is_using(self) -> None:
        """The cap is there to leave the caption its width.

        With no caption there is nothing to leave it to, and a lone QR was
        printing at 16.8 mm on a 50 x 24 label with two thirds of it blank —
        on continuous tape, blank the printer still has to feed.
        """
        label = _make_label('STM-K9XP', LONG_CAPTION)

        shared = Image.open(io.BytesIO(generate_label_png(label)))
        alone = Image.open(io.BytesIO(generate_label_png(label, qr_only=True)))

        assert _module_px(alone) > _module_px(shared)

    def test_a_caption_never_runs_off_the_label(self) -> None:
        """The fitter asked how many lines the text broke into, never how
        wide they came out.

        A word that does not fit gets a line of its own — wrapping cannot
        help one word — and that line was then accepted at any size.
        "opis etykiety" printed at full height with "etykiety" running past
        the right edge: 0 px of margin, cut off by the die on paper.
        """
        image = Image.open(
            io.BytesIO(generate_label_png(_make_label('STM-K9XP', 'opis etykiety')))
        )

        assert max(_ink_columns(image)) < image.width - 2


@pytest.mark.unit
class TestTheCodeBelongsToTheSquare:
    """The short code was the biggest thing on every label.

    It was added so a product could be found without a scanner, but a shelf
    is read as "minced beef 8.2026", not "STM-K9XP". It is off by default,
    and when it is asked for it goes under the QR — small, in the square's
    own column — because it is there for the moment a scan fails and
    somebody types it in, not to compete with the sentence beside it.
    """

    def test_the_code_is_not_printed_unless_it_is_asked_for(self) -> None:
        label = _make_label('STM-K9XP', description=None)

        without = Image.open(io.BytesIO(generate_label_png(label)))
        with_code = Image.open(io.BytesIO(generate_label_png(label, show_code=True)))

        # Neither puts text beside the square: with no caption the column is
        # centred, so what ink there is sits around the middle either way.
        assert _ink_beside_the_square(without) == 0
        assert _ink_beside_the_square(with_code) == 0
        # A square on its own is square; a square with a line under it is
        # taller than it is wide. That is the whole difference here.
        bare_w, bare_h = _ink_box(without)
        coded_w, coded_h = _ink_box(with_code)
        assert bare_h == pytest.approx(bare_w, rel=0.02)
        assert coded_h > coded_w

    def test_the_caption_is_the_same_size_either_way(self) -> None:
        """Flipping a switch does not resize a sentence it did not change.

        The caption used to be sized as a fraction of the short code, so
        turning the code on shrank the caption to 1.95 mm and turning it off
        let it grow to 8.8 mm — the same words, three times the size,
        because of a checkbox about something else.
        """
        label = _make_label('STM-K9XP', 'Minced beef 8.2026')

        caption_only = Image.open(io.BytesIO(generate_label_png(label)))
        with_code = Image.open(io.BytesIO(generate_label_png(label, show_code=True)))

        assert caption_only.size == with_code.size
        assert _caption_height(caption_only) == _caption_height(with_code)

    def test_the_caption_does_not_fill_the_label(self) -> None:
        """A two-word caption grew until it filled a 24 mm label.

        Nothing capped it: the fitter was asked for the largest size that
        fit the box, and the box was the whole height.
        """
        image = Image.open(
            io.BytesIO(generate_label_png(_make_label('STM-K9XP', 'Mąka')))
        )

        px_per_mm = image.height / 24.0
        assert _caption_height(image) / px_per_mm < 5.0

    def test_the_code_can_be_printed_without_a_caption(self) -> None:
        """The fourth arrangement, which used to be unreachable.

        ``qr_only`` was taken to mean "no text at all" and forced the code
        off with the caption, so a pool label could carry the square and the
        string to type when a scan fails — and nothing else — only by having
        no description in the first place.
        """
        label = _make_label('STM-K9XP', 'Minced beef 8.2026')

        image = Image.open(
            io.BytesIO(generate_label_png(label, qr_only=True, show_code=True))
        )
        bare = Image.open(io.BytesIO(generate_label_png(label, qr_only=True)))

        # No caption: nothing at all stands beside the square.
        assert _ink_beside_the_square(image) == 0
        # …but the code is there, under the square, which the bare one has
        # not: with it the ink is taller than it is wide, without it square.
        coded_w, coded_h = _ink_box(image)
        bare_w, bare_h = _ink_box(bare)
        assert coded_h > coded_w
        assert bare_h == pytest.approx(bare_w, rel=0.02)

    def test_the_code_keeps_the_module_size_the_square_had(self) -> None:
        """Room for the code comes out of the square, not out of the grid.

        The square is a little shorter when the code is printed under it —
        that line has to come from somewhere — but a module is the unit a
        reader has to resolve, and it stays the size it was.

        Passes on the previous layout too, where the code stood beside the
        square and took nothing from it. It is here for this one, where the
        code does take a line and the temptation is to pay for it by
        shrinking the grid.

        Beside a short caption the square grows into the height, and the
        code's line comes out of that growth: the module is no smaller than
        the one the square has at its third.
        """
        label = _make_label('STM-K9XP', LONG_CAPTION)

        caption_only = Image.open(io.BytesIO(generate_label_png(label)))
        with_code = Image.open(io.BytesIO(generate_label_png(label, show_code=True)))

        assert _module_px(caption_only) == _module_px(with_code)

        short = _make_label('STM-K9XP', 'Minced beef 8.2026')
        grown = Image.open(io.BytesIO(generate_label_png(short, show_code=True)))
        with _held_at_a_third():
            held = Image.open(io.BytesIO(generate_label_png(short, show_code=True)))
        assert _module_px(grown) >= _module_px(held)


@pytest.mark.unit
class TestTheCodeStaysReadable:
    """A square that looks right and does not scan is worse than an ugly one.

    ``QR_MAX_MM`` is a preference. A longer scan URL needs a bigger matrix,
    and holding the square at its preferred size pays for those modules by
    making each one smaller — which is how a label quietly stops scanning on
    a real deployment, whose base URL is longer than a dev machine's.
    """

    def test_a_long_scan_url_grows_the_square_instead_of_the_grid(self) -> None:
        # A caption that needs its width holds the square at its share, where
        # the module is at the floor; beside a short one both squares would
        # take the label's height instead.
        label = _make_label(description=LONG_CAPTION)
        short = Image.open(
            io.BytesIO(generate_label_png(label, base_url='http://localhost:5173'))
        )
        long = Image.open(
            io.BytesIO(
                generate_label_png(
                    label,
                    base_url='https://inventari.a-rather-long-company-domain.example/app',
                )
            )
        )

        assert _module_px(long) == _module_px(short)
        assert _qr_width(long) > _qr_width(short)

    def test_a_module_is_never_smaller_than_the_floor_when_there_is_room(
        self,
    ) -> None:
        # Imported here rather than at module scope so the rest of this file
        # still collects against a renderer that has no such floor — which
        # is how the control run for this change was measured.
        from app.modules.printing.services.label_print_service import MIN_MODULE_MM

        image = Image.open(io.BytesIO(generate_label_png(_make_label())))

        px_per_mm = image.height / 24.0
        assert _module_px(image) / px_per_mm >= MIN_MODULE_MM


#: A 58-character base URL — the length the square was measured on when
#: the floor first won over the ceiling.
LONG_BASE_URL = 'https://inventari12.warehouse-north.example-co.example.org'


@pytest.mark.unit
class TestALongAddressStaysInsideTheSquare:
    """The ceiling and the floor used to contradict each other.

    A label leaves the code 18 mm, and a phone wants half a millimetre per
    module; 37 modules at that floor are 18.8 mm. A 58-character base URL
    under the old ``?code=`` address at error-correction M needed exactly 37,
    so the renderer could keep only one of the two promises. The payload is shorter
    now (``/s/<code>``) and the matrix drops to level L when M could keep
    the floor only by growing past the ceiling — 33 modules, both promises
    kept.

    Measured the way the review measured it: the span of the dark modules on
    a 50 x 24 sheet label at 300 dpi.
    """

    def _render(self) -> Image.Image:
        # A caption that needs its width, so the square stays at its share.
        # Beside a short one it takes the label's height at M instead, as a
        # bare square does: the room is the label's offer, not the floor's.
        label = _make_label('STM-K9XP', LONG_CAPTION)
        return Image.open(io.BytesIO(generate_label_png(label, base_url=LONG_BASE_URL)))

    def test_the_square_stays_under_18_mm_at_the_module_floor(self) -> None:
        from app.modules.printing.services.label_print_service import MIN_MODULE_MM

        assert len(LONG_BASE_URL) == 58
        image = self._render()
        px_per_mm = image.height / 24.0
        left, top, right, bottom = _qr_box(image)

        assert (right - left + 1) / px_per_mm <= 18.0
        assert (bottom - top + 1) / px_per_mm <= 18.0
        assert _module_px(image) / px_per_mm >= MIN_MODULE_MM

    def test_the_square_reads_back_module_by_module_as_the_scan_address(
        self,
    ) -> None:
        """Every module, sampled at its centre, is the bit the matrix says.

        The expected matrix is built here from ``scan_url`` at level L, not
        taken from the renderer, so a pass means the label carries the short
        address — and carries it whole.
        """
        qr = qrcode.QRCode(
            version=None,
            error_correction=qrcode.constants.ERROR_CORRECT_L,
            box_size=1,
            border=0,
        )
        qr.add_data(scan_url('STM-K9XP', LONG_BASE_URL))
        qr.make(fit=True)
        expected = qr.get_matrix()

        image = self._render()
        ink, width, _ = _dark_pixels(image)
        module = _module_px(image)
        left, top, right, _ = _qr_box(image)

        assert (right - left + 1) == module * len(expected)
        read = [
            [
                bool(
                    ink[
                        (top + row * module + module // 2) * width
                        + left
                        + col * module
                        + module // 2
                    ]
                )
                for col in range(len(expected))
            ]
            for row in range(len(expected))
        ]
        mismatches = sum(
            read[row][col] != expected[row][col]
            for row in range(len(expected))
            for col in range(len(expected))
        )
        assert mismatches == 0

    def test_a_short_address_keeps_the_stronger_correction(self) -> None:
        """Level L is spent only where M would not fit: a typical address
        still prints at M, which rebuilds twice as much of a scuffed code.

        Passes on the renderer before L existed, which printed everything at
        M. It is here for the rule that replaced it: dropping to L whenever
        M pushed the square past its third of the label took L on this very
        address, two pixels over the share on a 50 x 24 label.
        """
        label = _make_label('STM-K9XP', 'Minced beef 8.2026')
        with patch(
            'app.modules.printing.services.label_print_service.qrcode.QRCode',
            wraps=qrcode.QRCode,
        ) as spy:
            generate_label_png(label, base_url='https://wh.example.test')

        levels = {call.kwargs['error_correction'] for call in spy.call_args_list}
        assert levels == {qrcode.constants.ERROR_CORRECT_M}

    def test_a_bare_square_takes_the_room_at_m(self) -> None:
        """With no caption the ceiling does not apply: the square has the
        label to itself and is drawn at M at the size the room gives it,
        past 18 mm, rather than at L to stay under a ceiling that exists to
        leave a caption its width.

        Passes on the renderer before L existed too. It pins the decision
        against the other reading of the ceiling, which would take L here
        and still not land under 18 mm: 37 modules in this room are 7 px
        each, 19.6 mm.
        """
        from app.modules.printing.services.label_print_service import MIN_MODULE_MM

        label = _make_label('STM-K9XP', 'Minced beef 8.2026')
        with patch(
            'app.modules.printing.services.label_print_service.qrcode.QRCode',
            wraps=qrcode.QRCode,
        ) as spy:
            png = generate_label_png(label, base_url=LONG_BASE_URL, qr_only=True)

        levels = {call.kwargs['error_correction'] for call in spy.call_args_list}
        assert levels == {qrcode.constants.ERROR_CORRECT_M}
        image = Image.open(io.BytesIO(png))
        px_per_mm = image.height / 24.0
        assert _module_px(image) / px_per_mm >= MIN_MODULE_MM


def _ink_beside_the_square(image: Image.Image) -> int:
    """Columns carrying ink to the right of the QR's own column.

    Measured against the square rather than against a fraction of the label:
    with no caption the column is centred, so it reaches past the middle and
    a fixed cut-off counts the square itself as text.
    """
    ink, width, height = _dark_pixels(image)
    _, _, right, _ = _qr_box(image)
    gap = int(width * 0.02)
    return sum(
        1
        for x in range(min(right + gap + 1, width), width)
        if any(ink[y * width + x] for y in range(height))
    )


def _ink_box(image: Image.Image) -> tuple[int, int]:
    """Width and height of everything inked on the label."""
    ink, width, height = _dark_pixels(image)
    cols = [x for x in range(width) if any(ink[y * width + x] for y in range(height))]
    rows = [y for y in range(height) if any(ink[y * width + x] for x in range(width))]
    return cols[-1] - cols[0] + 1, rows[-1] - rows[0] + 1


def _module_px(image: Image.Image) -> int:
    """Pixels per QR module, read off the top-left finder pattern.

    The finder is seven modules across and solid, so the first unbroken run
    of ink on the square's top row is exactly seven modules wide. Measured
    from that row's own first ink pixel, not from the column's left edge:
    the short code printed underneath can be wider than the square.
    """
    ink, width, height = _dark_pixels(image)
    _, top, _, _ = _qr_box(image)
    start = next(x for x in range(width) if ink[top * width + x])
    run = 0
    for x in range(start, width):
        if not ink[top * width + x]:
            break
        run += 1
    return run // 7


def _caption_height(image: Image.Image) -> int:
    """Rows carrying ink in the right-hand half — the text block."""
    ink, width, height = _dark_pixels(image)
    left = int(width * 0.55)
    return sum(
        1 for y in range(height) if any(ink[y * width + x] for x in range(left, width))
    )


def _qr_width(image: Image.Image) -> int:
    """Width of the inked block on the left — the QR."""
    columns = _ink_columns(image)
    left = min(columns)
    last = left
    for x in columns:
        if x - last > image.width * 0.02:
            break
        last = x
    return last - left


@pytest.mark.unit
class TestGenerateLabelBatchRendersEachLabelOnce:
    def test_three_labels_render_three_times_not_four(self) -> None:
        """The sheet measures its tile from the first label's own render.

        The batch used to render labels[0] to learn the tile size and then
        ran the very same label through the loop again — one wasted full
        render per sheet. The render count is the property to keep: exactly
        one render per label on the sheet."""
        labels = [_make_label(f'CODE-{n}') for n in range(3)]
        with patch(
            'app.modules.printing.services.label_print_service.generate_label_png',
            side_effect=generate_label_png,
        ) as render_spy:
            png = generate_label_batch_png(labels)

        assert render_spy.call_count == len(labels)
        img = Image.open(io.BytesIO(png))
        assert img.format == 'PNG'

    def test_refuses_an_empty_sheet(self) -> None:
        with pytest.raises(ValueError):
            generate_label_batch_png([])


@pytest.mark.unit
class TestNothingRunsOffTheLabel:
    """A run of characters with no space in it stays inside the label.

    The fitter used to answer ``MIN_FONT_PX`` to a question it had failed:
    ``_overflows`` reported that the longest line did not fit at any size,
    and the bisection returned the floor anyway because that was its seed.
    So a serial number or a URL pasted into a description was drawn at 8 px
    and ran out through the right edge — the guard existed and nothing read
    what it said.
    """

    @staticmethod
    def _ink_bbox(png: bytes) -> tuple[int, int, int, int]:
        from PIL import ImageOps

        img = Image.open(io.BytesIO(png)).convert('L')
        bbox = ImageOps.invert(img).getbbox()
        assert bbox is not None, 'a blank label proves nothing'
        return bbox

    def test_an_unbreakable_run_is_split_instead_of_leaving_the_label(self) -> None:
        long_run = 'A' * 114
        png = generate_label_png(_make_label(description=long_run), height_mm=24.0)
        img = Image.open(io.BytesIO(png))
        right_edge = self._ink_bbox(png)[2]

        assert right_edge < img.size[0], (
            f'ink reaches {right_edge} of {img.size[0]} px — the caption is '
            f'being drawn past the right edge of the label'
        )

    def test_a_run_that_already_fitted_still_fits(self) -> None:
        """Pin, not a discriminator: this one passed before the fix too.

        It is here so a future change to the splitting cannot buy the long
        case by breaking the ordinary one.
        """
        png = generate_label_png(_make_label(description='A' * 41), height_mm=24.0)
        img = Image.open(io.BytesIO(png))

        assert self._ink_bbox(png)[2] < img.size[0]

    def test_a_short_code_too_wide_for_the_square_is_cut_and_says_so(self) -> None:
        from PIL import ImageDraw

        from app.modules.printing.services.label_print_service import (
            MIN_FONT_PX,
            _clipped_to_width,
            _font,
        )

        draw = ImageDraw.Draw(Image.new('L', (10, 10), color=255))
        clipped = _clipped_to_width(draw, 'X' * 80, _font(MIN_FONT_PX), 40)

        assert clipped.endswith('…'), 'a code cut without a mark reads as whole'
        assert len(clipped) < 80


@pytest.mark.unit
class TestOnTapeABareSquareFillsTheBand:
    """A P-touch on 24 mm tape prints 128 dots across and leaves 3 mm white.

    The owner's QR-only label (Square 24 x 24, a 29-module link) printed at
    3 dots a module, 12.3 mm on 24 mm tape: the padding and the quiet zone
    drawn inside the 128 dots, and the rounding to whole dots, took almost
    half the tape. The tape's own edges are the quiet zone across it, so
    there the square takes the whole height; along the tape it keeps its own.
    """

    _BASE = 'https://inventari.app'
    _CODE = 'STM-MCLY'

    def _tape(
        self,
        *,
        edge_to_edge: bool,
        dots: int = 128,
        qr_only: bool = True,
        show_code: bool = False,
        description: str | None = None,
    ) -> Image.Image:
        png = generate_label_png(
            _make_label(short_code=self._CODE, description=description),
            24.0,
            24.0,
            base_url=self._BASE,
            qr_only=qr_only,
            show_code=show_code,
            dpi=180.0,
            max_height_px=dots,
            edge_to_edge=edge_to_edge,
        )
        return Image.open(io.BytesIO(png))

    @staticmethod
    def _square(img: Image.Image) -> tuple[int, int, int, int]:
        box = _dark_bbox(img)
        assert box is not None, 'the label carries no code'
        return box

    def _matrix(self) -> list[list[bool]]:
        qr = qrcode.QRCode(
            error_correction=qrcode.constants.ERROR_CORRECT_M, border=0, box_size=1
        )
        qr.add_data(scan_url(self._CODE, self._BASE))
        qr.make(fit=True)
        return [[bool(cell) for cell in row] for row in qr.get_matrix()]

    def test_the_square_is_as_tall_as_the_tape_prints(self) -> None:
        img = self._tape(edge_to_edge=True)
        left, top, right, bottom = self._square(img)

        assert len(self._matrix()) == 29
        assert img.height == 128
        # 4 dots a module: 116 dots, 16.4 mm of code on 24 mm tape.
        assert (right - left, bottom - top) == (116, 116)

    def test_it_was_three_dots_a_module_with_the_white_drawn_inside(self) -> None:
        """Pin of the old layout, which a printer without white edges keeps."""
        left, top, right, bottom = self._square(self._tape(edge_to_edge=False))

        assert (right - left, bottom - top) == (87, 87)

    def test_the_square_is_the_scan_links_matrix_on_whole_dots(self) -> None:
        matrix = self._matrix()
        img = self._tape(edge_to_edge=True)
        left, top, _, _ = self._square(img)
        ink, width, _ = _dark_pixels(img)
        box = 4

        drawn = [
            [
                ink[(top + row * box + box // 2) * width + left + col * box + box // 2]
                == 1
                for col in range(len(matrix))
            ]
            for row in range(len(matrix))
        ]
        assert drawn == matrix

    def test_the_quiet_zone_along_the_tape_stays(self) -> None:
        img = self._tape(edge_to_edge=True)
        left, _, right, _ = self._square(img)

        # Two modules of 4 dots before and after the code, along the tape.
        assert left >= 8
        assert img.width - right >= 8

    def test_on_twelve_millimetre_tape_it_fills_the_band_too(self) -> None:
        img = self._tape(edge_to_edge=True, dots=64)
        left, top, right, bottom = self._square(img)

        assert img.height == 64
        # 2 dots a module: 58 dots, 8.2 mm on 12 mm tape.
        assert (right - left, bottom - top) == (58, 58)

    @pytest.mark.parametrize(
        ('qr_only', 'show_code'),
        [(True, True), (False, False)],
        ids=['with the short code', 'with a caption'],
    )
    def test_a_label_with_text_is_laid_out_as_before(
        self, qr_only: bool, show_code: bool
    ) -> None:
        def pixels(edge_to_edge: bool) -> bytes:
            return self._tape(
                edge_to_edge=edge_to_edge,
                qr_only=qr_only,
                show_code=show_code,
                description='Minced beef',
            ).tobytes()

        assert pixels(edge_to_edge=True) == pixels(edge_to_edge=False)


@pytest.mark.unit
class TestBesideACaptionTheSquareTakesTheHeight:
    """The square beside a caption was held at a third of the label's width.

    The owner's "Kiełbasa w słoiku" on a 50 x 24 label drew 14.7 mm of code
    with white above and below it, and the two words used half the width
    they were left; on 24 mm tape the same label printed 12.3 mm of code on
    an 18 mm band. The square grows into the height now, as long as the
    caption keeps the size and the words it has beside the third.
    """

    _BASE = 'https://inventari.app'
    _CODE = 'STM-MCLY'

    def _render(self, caption: str | None, **options: Any) -> bytes:
        return generate_label_png(
            _make_label(short_code=self._CODE, description=caption),
            base_url=self._BASE,
            **options,
        )

    def _image(self, caption: str | None, **options: Any) -> Image.Image:
        return Image.open(io.BytesIO(self._render(caption, **options)))

    def _matrix(self) -> list[list[bool]]:
        qr = qrcode.QRCode(
            error_correction=qrcode.constants.ERROR_CORRECT_M, border=0, box_size=1
        )
        qr.add_data(scan_url(self._CODE, self._BASE))
        qr.make(fit=True)
        return [[bool(cell) for cell in row] for row in qr.get_matrix()]

    def test_beside_a_short_caption_the_square_is_as_big_as_a_bare_one(
        self,
    ) -> None:
        captioned = self._image('Kiełbasa w słoiku')
        bare = self._image(None)
        left, top, right, bottom = _qr_box(captioned)

        px_per_mm = captioned.height / 24.0
        assert _module_px(captioned) == _module_px(bare) == 8
        assert (right - left + 1) / px_per_mm >= 17.0
        with _held_at_a_third():
            assert _module_px(self._image('Kiełbasa w słoiku')) == 6

    def test_the_caption_keeps_its_size_and_its_words(self) -> None:
        grown = _caption_as_drawn(lambda: self._render('Kiełbasa w słoiku'))
        with _held_at_a_third():
            held = _caption_as_drawn(lambda: self._render('Kiełbasa w słoiku'))

        assert grown == held
        assert grown[1] == 'Kiełbasa w słoiku'

    def test_a_caption_that_needs_its_width_keeps_the_third(self) -> None:
        grown = self._render(LONG_CAPTION)
        with _held_at_a_third():
            held = self._render(LONG_CAPTION)

        assert grown == held

    def test_the_grown_square_is_the_scan_links_matrix_at_m(self) -> None:
        matrix = self._matrix()
        image = self._image('Kiełbasa w słoiku')
        ink, width, _ = _dark_pixels(image)
        module = _module_px(image)
        left, top, right, _ = _qr_box(image)

        assert right - left + 1 == module * len(matrix)
        drawn = [
            [
                ink[
                    (top + row * module + module // 2) * width
                    + left
                    + col * module
                    + module // 2
                ]
                == 1
                for col in range(len(matrix))
            ]
            for row in range(len(matrix))
        ]
        assert drawn == matrix

    def test_on_tape_it_fills_the_band(self) -> None:
        image = self._image(
            'Kiełbasa w słoiku',
            dpi=180.0,
            max_height_px=128,
            edge_to_edge=True,
        )
        left, top, right, bottom = _qr_box(image)

        assert image.height == 128
        # 4 dots a module: 116 dots, 16.4 mm of code on 24 mm tape.
        assert (right - left + 1, bottom - top + 1) == (116, 116)
        assert _module_px(image) == 4

    def test_on_tape_it_was_three_dots_a_module(self) -> None:
        """Pin of the old layout, which a printer without white edges keeps
        while its caption needs the width."""
        with _held_at_a_third():
            image = self._image(
                'Kiełbasa w słoiku',
                dpi=180.0,
                max_height_px=128,
                edge_to_edge=True,
            )
        left, _, right, _ = _qr_box(image)

        assert right - left + 1 == 87

    def test_on_tape_the_quiet_zone_along_it_stays(self) -> None:
        image = self._image(
            'Kiełbasa w słoiku',
            dpi=180.0,
            max_height_px=128,
            edge_to_edge=True,
        )
        left, _, right, _ = _qr_box(image)
        columns = _ink_columns(image)
        caption_left = min(x for x in columns if x > right)

        # Two modules of 4 dots before the code and between it and the words.
        assert left >= 8
        assert caption_left - right - 1 >= 8

    def test_on_tape_a_square_with_the_code_under_it_keeps_its_white(self) -> None:
        def pixels(edge_to_edge: bool) -> bytes:
            return self._image(
                'Kiełbasa w słoiku',
                show_code=True,
                dpi=180.0,
                max_height_px=128,
                edge_to_edge=edge_to_edge,
            ).tobytes()

        assert pixels(edge_to_edge=True) == pixels(edge_to_edge=False)

    @pytest.mark.parametrize('caption', [None, ''], ids=['none', 'empty'])
    def test_on_tape_a_caption_mode_label_with_no_caption_is_drawn_as_before(
        self, caption: str | None
    ) -> None:
        """Only an explicit QR-only label fills the band across the tape.

        With no caption to share it a label in caption mode is a lone square
        too, but filling the band is decided for the QR-only choice alone.
        """

        def pixels(edge_to_edge: bool) -> bytes:
            return self._image(
                caption,
                dpi=180.0,
                max_height_px=128,
                edge_to_edge=edge_to_edge,
            ).tobytes()

        assert pixels(edge_to_edge=True) == pixels(edge_to_edge=False)

    def test_without_a_font_the_square_stays_at_its_third(self) -> None:
        """A machine with no usable font still gets its label.

        The caption's fallback draws what it can when the face will not load;
        measuring the caption to grow the square happens outside it, and a
        font that would not load failed the whole label there.
        """
        unavailable = OSError('cannot open resource')

        with patch.object(lps, '_font', side_effect=unavailable):
            grown = self._render('Kiełbasa w słoiku')
            with _held_at_a_third():
                held = self._render('Kiełbasa w słoiku')

        assert grown == held
