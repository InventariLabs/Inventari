"""The approvals module gates documents through the warehouse's own seam.

The warehouse asks every registered pre-post check before it confirms or
posts a document; the approvals module's gate is one of them, registered from
this side, and the decisions on document requests reach the warehouse through
the listener registered beside it. The warehouse calls neither itself.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.modules.approvals.document_gate import (
    MODULE,
    follow_document_decision,
    gate_document_async,
    withdraw_request_async,
)
from app.modules.approvals.target_decisions import _LISTENERS
from app.modules.warehouse.pre_post_checks import _CHECKS, _WITHDRAWAL_LISTENERS


@pytest.mark.integration
def test_the_gate_and_its_listeners_are_registered(client: TestClient) -> None:
    assert MODULE == 'approvals'
    assert _CHECKS[MODULE] is gate_document_async
    assert _WITHDRAWAL_LISTENERS[MODULE] is withdraw_request_async
    assert _LISTENERS['document'] is follow_document_decision
