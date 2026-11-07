"""The Polish copy around a handover names the act *wydanie* and the thing *zasób*.

docs/MODULE_NAMES.md ("asset vs equipment vs record") settles it: Polish names
handing an asset over *wydać* and its record *wydanie*, the tracked thing is
*zasób*, and *przypisany do* stays only as the label of the field that names
the holder. The screens follow it; these server-side sentences did not --
an API refusal said *przypisanie* for the handover and *przedmiot* for the
asset, the My-Assets refusal said *aktywa*, the overdue notification said
*przypisany do* in a sentence, and the attestation e-mail asked the holder
about *przedmioty*.
"""

from __future__ import annotations

import re

import pytest

from app.i18n.service import get_error_message
from app.modules.equipment._attestation_email import _get_email_label
from app.modules.equipment._notification_labels import OVERDUE_CONTENT

#: The words the decision retired for the act and the thing. ``aktyw`` only
#: when it is not ``aktywny`` -- an active campaign is not the asset.
_RETIRED = re.compile(r'przypisan|przedmiot|aktyw(?!n)', re.IGNORECASE)


@pytest.mark.unit
@pytest.mark.parametrize(
    ('text', 'word'),
    [
        pytest.param(
            get_error_message('assignment_not_found', 'pl'),
            'wydani',
            id='unknown handover',
        ),
        pytest.param(
            get_error_message('equipment_assignment_already_active', 'pl'),
            'zasób',
            id='already handed over',
        ),
        pytest.param(
            get_error_message('equipment_assignment_already_checked_in', 'pl'),
            'zasób',
            id='already returned',
        ),
        pytest.param(
            get_error_message('user_email_required', 'pl'),
            'zasob',
            id='my assets without an e-mail',
        ),
        pytest.param(OVERDUE_CONTENT['pl'], 'wydany', id='overdue notification'),
        pytest.param(
            _get_email_label('pl', 'multiple_items_body'),
            'zasoby',
            id='attestation e-mail',
        ),
    ],
)
def test_the_sentence_uses_the_handover_words(text: str, word: str) -> None:
    assert _RETIRED.search(text) is None, text
    assert word in text.lower(), text
