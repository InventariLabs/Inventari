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
    ('lang', 'fragment'),
    [('pl', 'zamknięty'), ('en', 'is closed'), ('de', 'geschlossen')],
)
async def test_closed_period_refusal_follows_the_request_language(lang, fragment):
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
    assert '2025-09' in str(caught.value)
    assert fragment in str(caught.value)


def test_missing_workflow_refusal_has_a_polish_sentence():
    text = get_error_message('documents_approval_workflow_missing', 'pl')
    assert 'przepływu' in text
