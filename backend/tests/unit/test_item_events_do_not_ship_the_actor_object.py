"""Item events name the actor by ``user_id`` alone.

``data.user`` was an ORM object attached by the emitters "until they
migrate"; the docs called it outside the contract while every delivery
carried it, so removing it later would have broken receivers that read it.
It never reaches the envelope now: the payload models do not declare it and
no emitter attaches it.
"""

from pathlib import Path

import pytest

from app.core.contracts.events import (
    ItemCreatedPayload,
    ItemDeletedPayload,
    ItemUpdatedPayload,
)

_SERVICES = Path(__file__).resolve().parents[2] / 'app' / 'services' / 'items'


@pytest.mark.parametrize(
    'model', [ItemCreatedPayload, ItemUpdatedPayload, ItemDeletedPayload]
)
def test_the_payload_model_declares_no_user_object(model: type) -> None:
    assert 'user' not in model.model_fields
    assert 'user_id' in model.model_fields


@pytest.mark.parametrize('name', ['_create.py', '_lifecycle.py', 'scan_service.py'])
def test_no_item_emitter_attaches_the_user_object(name: str) -> None:
    source = (_SERVICES / name).read_text(encoding='utf-8')
    assert "'user':" not in source, f'{name} still attaches the actor object'
