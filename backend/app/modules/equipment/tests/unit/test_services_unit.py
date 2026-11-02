"""
Unit tests for services.py helper functions.
"""

from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.modules.equipment.services import (
    _get_assignment_or_404,
    _get_log_or_404,
)


def _mock_db_with_result(first_val: Any = None) -> MagicMock:
    db = MagicMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = first_val
    db.execute = AsyncMock(return_value=result)
    return db


@pytest.mark.unit
class TestGetAssignmentOr404:
    async def test_found(self) -> None:
        assignment = MagicMock()
        assignment.id = uuid4()
        db = _mock_db_with_result(first_val=assignment)

        result = await _get_assignment_or_404(db, assignment.id, uuid4())

        assert result == assignment

    async def test_not_found_raises(self) -> None:
        db = _mock_db_with_result(first_val=None)

        with pytest.raises(HTTPException) as exc_info:
            await _get_assignment_or_404(db, uuid4(), uuid4())

        assert exc_info.value.status_code == 404


@pytest.mark.unit
class TestGetLogOr404:
    async def test_found(self) -> None:
        log = MagicMock()
        log.id = uuid4()
        db = _mock_db_with_result(first_val=log)

        result = await _get_log_or_404(db, log.id, uuid4())

        assert result == log

    async def test_not_found_raises(self) -> None:
        db = _mock_db_with_result(first_val=None)

        with pytest.raises(HTTPException) as exc_info:
            await _get_log_or_404(db, uuid4(), uuid4())

        assert exc_info.value.status_code == 404
