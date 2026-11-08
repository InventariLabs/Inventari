"""Every photograph is scaled into 1200 px before a model sees it.

The ten-megabyte limit on an uploaded photograph rests on this: nothing past
the box survives to the model anyway. Only the nutrition-table path used to do
it; the label path handed the model the bytes as they came, so an API client
that did not shrink its photograph sent all of it — billed by size, and
refused by some providers past a few megabytes.

What is checked is what reaches Core's extraction call, on both paths.
"""

from __future__ import annotations

import io
from collections.abc import Iterator
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from PIL import Image

from app.core.public_api import core_api
from app.modules.vision._image_helpers import compress_image
from app.modules.vision.field_contributions import (
    LabelFieldContribution,
    clear_label_fields,
    register_label_fields,
    registered_label_fields,
)
from app.modules.vision.schemas import VisionExtractResult
from app.modules.vision.service import VisionService

#: The EXIF tag that says how a camera held the picture; 6 = turn it 90°.
_ORIENTATION = 0x0112


def _photo(width: int, height: int, *, orientation: int | None = None) -> bytes:
    image = Image.new('RGB', (width, height), (180, 30, 30))
    buf = io.BytesIO()
    if orientation is None:
        image.save(buf, format='JPEG')
    else:
        exif = Image.Exif()
        exif[_ORIENTATION] = orientation
        image.save(buf, format='JPEG', exif=exif.tobytes())
    return buf.getvalue()


def _size(image: bytes) -> tuple[int, int]:
    return Image.open(io.BytesIO(image)).size


async def _sent_on_the_label_path(images: list[bytes]) -> list[bytes]:
    extract = AsyncMock(return_value=VisionExtractResult())
    with patch.object(core_api.llm, 'extract_from_images_async', extract):
        await VisionService.extract_from_bytes_list(
            images, db=AsyncMock(), organization_id=uuid4()
        )
    assert extract.await_args is not None
    return list(extract.await_args.kwargs['images'])


@pytest.mark.unit
class TestTheLabelPath:
    @pytest.fixture(autouse=True)
    def _no_contributions(self) -> Iterator[None]:
        """No module rides along, so no organization is asked about one."""
        saved = list(registered_label_fields())
        clear_label_fields()
        yield
        clear_label_fields()
        for contribution in saved:
            register_label_fields(contribution)

    async def test_a_large_photograph_is_scaled_into_the_box(self) -> None:
        (sent,) = await _sent_on_the_label_path([_photo(4000, 3000)])

        assert _size(sent) == (1200, 900)

    async def test_a_photograph_inside_the_box_keeps_its_size(self) -> None:
        (sent,) = await _sent_on_the_label_path([_photo(1024, 768)])

        assert _size(sent) == (1024, 768)

    async def test_every_photograph_of_the_item_is_scaled(self) -> None:
        sent = await _sent_on_the_label_path([_photo(3000, 3000), _photo(2400, 600)])

        assert [_size(image) for image in sent] == [(1200, 1200), (1200, 300)]

    async def test_a_photograph_held_upright_stays_upright(self) -> None:
        """The JPEG sent on carries no EXIF, so the camera's turn is applied."""
        (sent,) = await _sent_on_the_label_path([_photo(4000, 3000, orientation=6)])

        assert _size(sent) == (900, 1200)


@pytest.mark.unit
class TestTheContributedPath:
    @pytest.fixture(autouse=True)
    def _one_group(self) -> Iterator[None]:
        saved = list(registered_label_fields())
        clear_label_fields()
        register_label_fields(
            LabelFieldContribution(
                module='nutrition',
                schema=VisionExtractResult,
                instructions='Read the table.',
                context_tags=None,
            )
        )
        yield
        clear_label_fields()
        for contribution in saved:
            register_label_fields(contribution)

    async def test_a_large_photograph_is_scaled_into_the_box(self) -> None:
        extract = AsyncMock(return_value=VisionExtractResult())
        with patch.object(core_api.llm, 'extract_from_images_async', extract):
            await VisionService.extract_contributed_fields(
                'nutrition',
                [_photo(4000, 3000)],
                db=AsyncMock(),
                organization_id=uuid4(),
            )

        assert extract.await_args is not None
        (sent,) = extract.await_args.kwargs['images']
        assert _size(sent) == (1200, 900)


@pytest.mark.unit
class TestEveryColourModeCanBeSent:
    """A picture JPEG cannot hold as it is must still reach the model."""

    @pytest.mark.parametrize('mode', ['LA', 'I;16', 'P', 'RGBA', 'CMYK', '1'])
    def test_it_becomes_a_jpeg(self, mode: str) -> None:
        image = Image.new(mode, (40, 20))
        buf = io.BytesIO()
        image.save(buf, format='TIFF' if mode == 'CMYK' else 'PNG')

        result = compress_image(buf.getvalue(), max_size=(1200, 1200))

        sent = Image.open(io.BytesIO(result))
        assert sent.format == 'JPEG'
        assert sent.size == (40, 20)
