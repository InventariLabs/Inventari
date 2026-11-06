"""A closed-period refusal and a missing approval workflow read in the reader's language."""

from datetime import date
from unittest.mock import AsyncMock, patch

import pytest

from app.core.exceptions import PeriodClosedError
from app.i18n.service import get_error_message, set_current_lang
from app.modules.warehouse.inventory_period_service import (
    check_period_not_closed_async,
)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ('lang', 'fragment', 'month'),
    [
        ('pl', 'zamknięty', 'wrzesień 2025'),
        ('en', 'is closed', 'September 2025'),
        ('de', 'geschlossen', 'September 2025'),
    ],
)
async def test_closed_period_refusal_follows_the_request_language(
    lang, fragment, month
):
    set_current_lang(lang)
    try:
        with patch(
            'app.modules.warehouse.inventory_period_service.is_period_closed',
            AsyncMock(return_value=True),
        ):
            with pytest.raises(PeriodClosedError) as caught:
                await check_period_not_closed_async(None, None, date(2025, 9, 15))
    finally:
        set_current_lang('en')
    # The month is named the way the period screen names it, not as 2025-09.
    assert month in str(caught.value)
    assert '2025-09' not in str(caught.value)
    assert fragment in str(caught.value)


def test_missing_workflow_refusal_speaks_to_the_floor():
    # A storekeeper reads this, so it says whom to ask, not what to configure.
    polish = get_error_message('documents_approval_workflow_missing', 'pl')
    assert 'administratora' in polish
    english = get_error_message('documents_approval_workflow_missing', 'en')
    assert 'administrator' in english
    assert 'Workflows' not in english
