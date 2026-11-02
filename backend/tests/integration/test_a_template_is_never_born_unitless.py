"""A catalogue row is never born without a unit.

The template is the row the rest of the app reads: the BoM convertibility
guard and the stock screen both take the unit from it, so a template born
unitless silenced the one and showed "—" on the other. Three doors minted
such rows: the bare product-templates POST, the document quick-create
stub, and (until the record path started inheriting) the automatic
resolver. Every door now answers "pieces" when nobody chose a unit — the
same answer the record path gives — and an explicitly chosen unit still
wins.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.uom import Uom

CREATE_URL = '/api/v1/items/product-templates'
QUICK_URL = '/api/v1/warehouse/product-search/quick-create'


def _pcs_id(db: Session) -> str:
    return str(db.scalars(select(Uom).where(Uom.symbol == 'pcs')).one().id)


def _kg_id(db: Session) -> str:
    return str(db.scalars(select(Uom).where(Uom.symbol == 'kg')).one().id)


def _template_uom_symbol(db: Session, template_id: str) -> str | None:
    from app.models.product_template import ProductTemplate

    tpl = db.scalars(
        select(ProductTemplate).where(ProductTemplate.id == template_id)
    ).one()
    return (
        db.scalars(select(Uom).where(Uom.id == tpl.uom_id)).one().symbol
        if tpl.uom_id
        else None
    )


def test_the_bare_template_post_answers_pieces(
    client, auth_headers, db_session
) -> None:
    response = client.post(
        CREATE_URL,
        headers=auth_headers,
        json={'name': 'Born unitless'},
    )

    assert response.status_code == 201, response.text
    assert response.json()['uom_id'] == _pcs_id(db_session)


def test_the_quick_create_stub_answers_pieces(client, auth_headers, db_session) -> None:
    response = client.post(
        QUICK_URL,
        headers=auth_headers,
        json={'name': 'Quick born unitless'},
    )

    assert response.status_code == 201, response.text
    template_id = response.json()['product_template_id']
    assert _template_uom_symbol(db_session, template_id) == 'pcs'


def test_an_explicitly_chosen_unit_still_wins(client, auth_headers, db_session) -> None:
    response = client.post(
        CREATE_URL,
        headers=auth_headers,
        json={'name': 'Weighed template', 'uom_id': _kg_id(db_session)},
    )

    assert response.status_code == 201, response.text
    assert response.json()['uom_id'] == _kg_id(db_session)
