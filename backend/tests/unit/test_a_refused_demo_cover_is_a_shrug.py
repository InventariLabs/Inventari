"""A cover a demo refuses to store leaves the recipe saved, without a cover."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from app.core.exceptions import AppException
from app.modules.recipes import _recipe_cover


def _refusal(code: str, status: int = 413) -> AppException:
    return AppException(status_code=status, code=code, message='refused')


@pytest.mark.parametrize('code', ['DEMO_UPLOAD_TOTAL_LIMIT', 'DEMO_UPLOAD_FILE_LIMIT'])
async def test_a_demo_refusal_leaves_the_recipe_without_a_cover(code):
    recipe = SimpleNamespace(id=uuid4(), organization_id=uuid4())
    setter = AsyncMock()
    with (
        patch.object(
            _recipe_cover,
            'fetch_remote_cover',
            AsyncMock(return_value=(b'x', 'image/png')),
        ),
        patch.object(
            _recipe_cover, 'store_cover', AsyncMock(side_effect=_refusal(code))
        ),
        patch('app.modules.recipes.services.set_recipe_image_url', setter),
    ):
        await _recipe_cover.adopt_remote_cover(
            AsyncMock(), recipe, 'https://example.com/a.png'
        )
    setter.assert_awaited_once()
    assert setter.await_args.args[2] is None


async def test_any_other_storage_failure_still_propagates():
    recipe = SimpleNamespace(id=uuid4(), organization_id=uuid4())
    with (
        patch.object(
            _recipe_cover,
            'fetch_remote_cover',
            AsyncMock(return_value=(b'x', 'image/png')),
        ),
        patch.object(
            _recipe_cover,
            'store_cover',
            AsyncMock(side_effect=_refusal('OTHER', 500)),
        ),
        patch('app.modules.recipes.services.set_recipe_image_url', AsyncMock()),
    ):
        with pytest.raises(AppException):
            await _recipe_cover.adopt_remote_cover(
                AsyncMock(), recipe, 'https://example.com/a.png'
            )
