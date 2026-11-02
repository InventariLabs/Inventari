"""The register says when a document still has a picking session open.

The register is where a dispatch goes back to after the picking sheet is
closed — and closing the sheet mid-way leaves the session over the scans
already made. The list said nothing about it: the row looked like work
nobody had begun, and the only way to learn otherwise was to start picking
and be refused.

The stage is the To do queue's own answer, read from the session rather than
stored on the document, so both screens say the same thing: *in progress*,
the holder's name, and *resume* as the one action left.
"""

from __future__ import annotations

from typing import Any, cast

import pytest
from fastapi import status
from fastapi.testclient import TestClient

from app.models.partner import Partner
from app.models.product_template import ProductTemplate
from app.models.storage_location import StorageLocation
from app.models.user import User
from app.modules.warehouse.tests.integration.test_the_todo_queue_shows_the_work_stage import (
    _create_document,
)

pytestmark = pytest.mark.integration


def _register(
    client: TestClient, headers: dict[str, str], *, limit: int = 50
) -> dict[str, Any]:
    response = client.get(
        '/api/v1/warehouse/documents', headers=headers, params={'limit': limit}
    )
    assert response.status_code == status.HTTP_200_OK, response.text
    return cast(dict[str, Any], response.json())


def _row(register: dict[str, Any], doc_id: str) -> dict[str, Any]:
    for row in register['items']:
        if row['id'] == doc_id:
            return cast(dict[str, Any], row)
    raise AssertionError(f'{doc_id} is not in the register: {register}')


def _confirmed_dispatch(
    client: TestClient,
    headers: dict[str, str],
    *,
    partner: Partner,
    source: StorageLocation,
    target: StorageLocation,
    template: ProductTemplate,
    item_id: Any,
) -> str:
    """A confirmed dispatch the register lists."""
    return _create_document(
        client,
        headers,
        doc_type='OUT',
        partner=partner,
        source=source,
        target=target,
        template=template,
        item_id=item_id,
    )


class TestTheRegisterMarksAPickingSessionLeftOpen:
    def test_the_sheet_left_open_midway_marks_the_row_in_progress(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_user: User,
        doc_partner: Partner,
        doc_source_location: StorageLocation,
        doc_target_location: StorageLocation,
        doc_template: ProductTemplate,
        doc_stock_item: Any,
    ) -> None:
        """Start, close the sheet, and the register still shows the walk."""
        doc_id = _confirmed_dispatch(
            client,
            doc_auth_headers,
            partner=doc_partner,
            source=doc_source_location,
            target=doc_target_location,
            template=doc_template,
            item_id=doc_stock_item.id,
        )
        started = client.post(
            f'/api/v1/warehouse/documents/{doc_id}/picking/start',
            headers=doc_auth_headers,
        )
        assert started.status_code == status.HTTP_201_CREATED, started.text
        session_id = started.json()['id']
        closed = client.post(
            f'/api/v1/warehouse/documents/{doc_id}/picking/{session_id}/pause',
            headers=doc_auth_headers,
        )
        assert closed.status_code == status.HTTP_204_NO_CONTENT, closed.text

        row = _row(_register(client, doc_auth_headers), doc_id)

        assert row['work_stage'] == 'in_progress'
        assert row['next_action'] == 'resume'
        assert row['stage_holder_name'] == (doc_user.full_name or doc_user.email)

    def test_a_session_still_being_scanned_marks_the_row_in_progress(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_user: User,
        doc_partner: Partner,
        doc_source_location: StorageLocation,
        doc_target_location: StorageLocation,
        doc_template: ProductTemplate,
        doc_stock_item: Any,
    ) -> None:
        """The session open in a sheet still counts, not only the paused one."""
        doc_id = _confirmed_dispatch(
            client,
            doc_auth_headers,
            partner=doc_partner,
            source=doc_source_location,
            target=doc_target_location,
            template=doc_template,
            item_id=doc_stock_item.id,
        )
        started = client.post(
            f'/api/v1/warehouse/documents/{doc_id}/picking/start',
            headers=doc_auth_headers,
        )
        assert started.status_code == status.HTTP_201_CREATED, started.text

        row = _row(_register(client, doc_auth_headers), doc_id)

        assert row['work_stage'] == 'in_progress'
        assert row['next_action'] == 'resume'
        assert row['stage_holder_name'] == (doc_user.full_name or doc_user.email)
