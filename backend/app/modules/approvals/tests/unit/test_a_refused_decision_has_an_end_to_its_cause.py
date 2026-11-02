"""A refused decision re-raises its cause without making a loop of causes.

A listener refuses a decision by raising ``TargetDecisionRefusedError(exc)
from exc``, and the engine re-raises the original error. Chained back ``from``
the refusal, the two became each other's ``__cause__``: the retry middleware
walks that chain looking for a SQLSTATE and never came out, so an approval
whose posting was refused hung the request instead of answering it.
"""

from __future__ import annotations

from typing import cast
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.approvals.target_decisions import (
    TargetDecision,
    TargetDecisionRefusedError,
    notify_target_decided,
    register_target_decision_listener,
)

_TARGET = 'refusal_chain_probe'


class _PostingRefusedError(ValueError):
    pass


async def _refusing_listener(db: object, decision: TargetDecision) -> None:
    try:
        raise _PostingRefusedError('the month is closed')
    except _PostingRefusedError as exc:
        raise TargetDecisionRefusedError(exc) from exc


@pytest.mark.unit
async def test_the_cause_chain_of_a_refused_decision_ends() -> None:
    register_target_decision_listener(_TARGET, _refusing_listener)
    decision = TargetDecision(
        organization_id=uuid4(),
        target_type=_TARGET,
        target_id=uuid4(),
        request_id=uuid4(),
        outcome='APPROVED',
        requester_id=uuid4(),
    )

    with pytest.raises(_PostingRefusedError) as raised:
        await notify_target_decided(cast(AsyncSession, None), decision)

    seen: set[int] = set()
    link: BaseException | None = raised.value
    while link is not None:
        assert id(link) not in seen, 'the cause chain loops'
        seen.add(id(link))
        link = link.__cause__
