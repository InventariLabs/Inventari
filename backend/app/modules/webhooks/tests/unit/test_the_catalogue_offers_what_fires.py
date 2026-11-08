"""The webhook catalogue offers only events something emits.

``item.transferred``, ``item.deactivated`` and ``item.status_changed`` stand in
``SystemEvent`` and the payload registry as part of the core contract, and
nothing in the codebase emits them. The catalogue offered all three, with
descriptions, so an administrator could subscribe an endpoint that would never
receive a delivery and read as healthy forever.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.modules.webhooks.schemas import (
    NEVER_EMITTED,
    WebhookEndpointCreate,
    valid_event_types,
)

pytestmark = pytest.mark.unit


@pytest.mark.parametrize('name', sorted(NEVER_EMITTED))
def test_a_name_nothing_emits_is_not_offered(name: str) -> None:
    assert name not in valid_event_types()


@pytest.mark.parametrize('name', sorted(NEVER_EMITTED))
def test_a_new_subscription_to_it_is_refused(name: str) -> None:
    with pytest.raises(ValidationError):
        WebhookEndpointCreate(
            name='Never fires',
            url='https://example.com/hook',
            event_types=[name],
        )


def test_the_neighbours_that_do_fire_stay() -> None:
    offered = valid_event_types()
    assert {'item.moved', 'item.used', 'item.disposed', 'item.updated'} <= offered


def test_nothing_in_the_codebase_emits_them() -> None:
    """The list is a fact about the code, so a new emitter has to retire it.

    Every emission names its event through ``SystemEvent`` or the wire string;
    a module that starts emitting one of these takes it off the list here.
    """
    import pathlib
    import re

    app_dir = pathlib.Path(__file__).resolve().parents[4]
    members = {'ITEM_TRANSFERRED', 'ITEM_DEACTIVATED', 'ITEM_STATUS_CHANGED'}
    pattern = re.compile(
        r'emit\w*\([^)]*?(?:SystemEvent\.(?:'
        + '|'.join(members)
        + r')|[\'"](?:'
        + '|'.join(re.escape(n) for n in NEVER_EMITTED)
        + r')[\'"])',
        re.DOTALL,
    )
    emitters = [
        str(path.relative_to(app_dir))
        for path in app_dir.rglob('*.py')
        if '/tests/' not in str(path) and pattern.search(path.read_text('utf-8'))
    ]
    assert emitters == []
