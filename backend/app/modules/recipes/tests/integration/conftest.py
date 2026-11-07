"""Recipe tests write ingredient lines the way the recipe form does.

The create and update endpoints refuse a line without a unit, and the form
never sends one without. Most tests here care about something else than the
unit, so their requests get the unit a form would have sent — the linked product's own, else ``g`` — filled
in only where the payload names no ``uom_id`` at all. A test that sends an
explicit ``uom_id`` (even ``null``) keeps what it wrote, and a module that is
about the refusal itself overrides ``a_unit_on_every_recipe_line``.
"""

from __future__ import annotations

import re
from typing import Any
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

_RECIPE_WRITE = re.compile(r'/recipes(/[0-9a-fA-F-]{36})?/?$')


@pytest.fixture(autouse=True)
def a_unit_on_every_recipe_line(
    client: TestClient, db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    unit = db_session.execute(text("SELECT id FROM uoms WHERE symbol = 'g'")).scalar()
    assert unit is not None, 'the system unit "g" is not seeded'
    unit_id = str(unit)
    send = client.request

    def unit_of(line: dict[str, Any]) -> str:
        template_id = line.get('template_id')
        try:
            template_id = str(UUID(str(template_id))) if template_id else None
        except ValueError:
            template_id = None  # a malformed id is the test's own business
        if template_id:
            own = db_session.execute(
                text('SELECT uom_id FROM product_templates WHERE id = :id'),
                {'id': template_id},
            ).scalar()
            if own is not None:
                return str(own)
        return unit_id

    def request(method: str, url: Any, **kwargs: Any) -> Any:
        body = kwargs.get('json')
        writes = method.upper() in {'POST', 'PUT'} and _RECIPE_WRITE.search(str(url))
        if (
            writes
            and isinstance(body, dict)
            and isinstance(body.get('ingredients'), list)
        ):
            body = {
                **body,
                'ingredients': [
                    {'uom_id': unit_of(line), **line}
                    if isinstance(line, dict)
                    else line
                    for line in body['ingredients']
                ],
            }
            kwargs['json'] = body
        return send(method, url, **kwargs)

    monkeypatch.setattr(client, 'request', request)
