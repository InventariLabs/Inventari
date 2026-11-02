"""The actions the To do queue emits are the ones its response declares."""

from __future__ import annotations

import inspect
import re
from typing import get_args

import pytest

from app.modules.warehouse import document_todo_service
from app.modules.warehouse.document_todo_service import NextAction
from app.modules.warehouse.schemas import DocumentListRowSchema, DocumentSchema


def _declared(model: type[DocumentSchema | DocumentListRowSchema]) -> set[str]:
    annotation = model.model_fields['next_action'].annotation
    literal = next(arg for arg in get_args(annotation) if get_args(arg))
    return set(get_args(literal))


@pytest.mark.parametrize('model', [DocumentSchema, DocumentListRowSchema])
def test_every_next_action_the_queue_sets_is_declared_by_the_response(
    model: type[DocumentSchema | DocumentListRowSchema],
) -> None:
    source = inspect.getsource(document_todo_service)
    emitted = set(re.findall(r"'next_action': '(\w+)'", source)) | set(
        get_args(NextAction)
    )

    assert 'request_approval' in emitted
    assert emitted <= _declared(model)
