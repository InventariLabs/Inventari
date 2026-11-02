"""The recipe module's argument refusals answer with their catalogue code.

They were free-text sentences, which the envelope answered with the shared
``VALIDATION_ERROR``: an integration importing recipes could not tell a missing
URL from an unknown format without reading the sentence. Every refusal here is
decided before the database is touched, so no session is needed.
"""

from collections.abc import Awaitable, Callable
from typing import Any
from uuid import uuid4

import pytest

from app.core.exceptions import ServiceRejectionError
from app.modules.recipes._picking_lifecycle import terminate_session
from app.modules.recipes.import_export_service import import_recipe, preview_import
from app.modules.recipes.tag_service import _validate_hex_color


@pytest.mark.parametrize('parse', [import_recipe, preview_import])
@pytest.mark.parametrize(
    ('import_format', 'payload', 'code'),
    [
        ('json', {}, 'RECIPE_IMPORT_DATA_REQUIRED'),
        ('url', {}, 'RECIPE_IMPORT_URL_REQUIRED'),
        ('yaml', {'data': {}}, 'UNSUPPORTED_IMPORT_FORMAT'),
    ],
)
async def test_an_import_without_what_it_needs_is_refused_with_a_code(
    parse: Callable[..., Awaitable[object]],
    import_format: str,
    payload: dict[str, Any],
    code: str,
) -> None:
    with pytest.raises(ServiceRejectionError) as exc_info:
        await parse(None, import_format, uuid4(), uuid4(), **payload)

    assert exc_info.value.code == code


def test_a_tag_colour_that_is_not_hex_is_refused_with_a_code() -> None:
    with pytest.raises(ServiceRejectionError) as exc_info:
        _validate_hex_color('red')

    assert exc_info.value.code == 'HEX_COLOR_INVALID'


async def test_an_unknown_reason_to_end_picking_is_refused_with_a_code() -> None:
    # The signature narrows the reason to a Literal; the runtime check is for
    # the callers the type checker never sees, so the test speaks as one.
    untyped_terminate: Callable[..., Awaitable[object]] = terminate_session
    with pytest.raises(ServiceRejectionError) as exc_info:
        await untyped_terminate(None, None, 'bored')

    assert exc_info.value.code == 'PICKING_TERMINATE_REASON_INVALID'
