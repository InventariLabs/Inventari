"""The usage row outlives the request that refused the model's answer.

The provider answered and charged tokens; the endpoint still refuses the
answer (422 — prose where the contract wanted JSON, twice). The AI usage
row is bookkeeping, not part of the business transaction: it must survive
the request's rollback, because the provider's invoice does not care that
the answer was unusable. This is the endpoint-level half of the ledger
contract; the session-level half lives in
``backend/tests/integration/test_the_ai_ledger_records_what_the_provider_charged.py``.
"""

from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock

import pytest
from fastapi import status
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from starlette.testclient import TestClient

from app.core.llm.base import LlmResponse
from app.models.ai_usage_log import AIUsageLog
from app.modules.vision.tests.integration._llm_double import (
    jpeg_bytes,
    never_reached,
    patch_client,
)

_JPEG = jpeg_bytes()

_PROSE = (
    'I can see a carton of milk, but the label text is too blurry for me '
    'to make out any of the details reliably.'
)


def _metered(*contents: str) -> AsyncMock:
    """A client that answers with real, billed usage every attempt."""
    client = AsyncMock()
    client.connection_name = 'Label Reader'
    client.model_name = 'gpt-4o-mini'
    client.connection_provider = 'openrouter'
    client.complete = AsyncMock(
        side_effect=[
            LlmResponse(
                content=c,
                usage={
                    'prompt_tokens': 100,
                    'completion_tokens': 30,
                    'total_tokens': 130,
                },
            )
            for c in contents
        ]
    )
    return client


@pytest.mark.integration
class TestTheLedgerSurvivesThe422:
    def test_a_refused_answer_still_leaves_its_billed_row(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
        test_user: Any,
    ) -> None:
        org_id = test_user.organization_id

        def _rows() -> int:
            return int(
                db_session.scalar(
                    select(func.count(AIUsageLog.id)).where(
                        AIUsageLog.organization_id == org_id
                    )
                )
                or 0
            )

        before = _rows()

        with patch_client(_metered(_PROSE, _PROSE)):
            response = client.post(
                '/api/v1/vision/extract',
                headers=auth_headers,
                files={'images': ('label.jpg', _JPEG, 'image/jpeg')},
                data={'location_type': 'PANTRY'},
            )

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
        db_session.expire_all()
        # Both attempts reached the provider and were billed; at least one
        # row with tokens must survive the request's error response.
        after = _rows()
        assert after > before
        latest = db_session.scalars(
            select(AIUsageLog)
            .where(AIUsageLog.organization_id == org_id)
            .order_by(AIUsageLog.created_at.desc())
        ).first()
        assert latest is not None
        assert latest.total_tokens > 0
        assert Decimal(str(latest.estimated_cost_usd)) >= 0

    def test_an_unreachable_provider_leaves_no_row_behind(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
        test_user: Any,
    ) -> None:
        """No answer from the provider means nothing was delivered and
        nothing was charged — the ledger must stay exactly as it was. The
        only thing standing between a future refactor and writing rows for
        unanswered calls is this count: the logging callback fires per
        received answer today, and nothing else pins that arrangement."""
        org_id = test_user.organization_id

        def _rows() -> int:
            return int(
                db_session.scalar(
                    select(func.count(AIUsageLog.id)).where(
                        AIUsageLog.organization_id == org_id
                    )
                )
                or 0
            )

        before = _rows()

        with patch_client(never_reached()):
            response = client.post(
                '/api/v1/vision/extract',
                headers=auth_headers,
                files={'images': ('label.jpg', _JPEG, 'image/jpeg')},
                data={'location_type': 'PANTRY'},
            )

        assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
        db_session.expire_all()
        assert _rows() == before
