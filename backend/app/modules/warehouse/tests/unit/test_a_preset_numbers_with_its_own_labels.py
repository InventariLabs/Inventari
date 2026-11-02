"""A preset that names a type labels numbers with those labels.

The ``UK Warehouse`` preset shipped GRN/DN/ST as its type labels while
numbering with ``{TYPE}``, so its documents came out ``IN/2026/0001`` —
the internal code, under a label that reads GRN. Two promises on one
screen then disagreed: the labels beside the format, and the format hint
that says ``{TYPE_LABEL}`` writes what the labels below read.

``{TYPE}`` stays what a preset without labels of its own uses — there is
no word to write, and the type's short code is the honest answer.
"""

from __future__ import annotations

import pytest

from app.modules.warehouse import document_profile_service


@pytest.mark.unit
class TestAPresetNumbersWithItsOwnLabels:
    def test_every_preset_that_names_a_type_numbers_with_that_label(self) -> None:
        for name, preset in document_profile_service.PRESETS.items():
            labels = preset.get('type_labels')
            if not labels:
                continue
            assert '{TYPE_LABEL}' in preset['numbering_format'], (
                f'preset {name!r} ships the labels {sorted(labels)} but '
                f'numbers with {preset["numbering_format"]!r}, so every '
                'document it raises wears a number its own labels '
                'contradict.'
            )

    def test_a_preset_without_labels_does_not_reach_for_the_label_token(
        self,
    ) -> None:
        for name, preset in document_profile_service.PRESETS.items():
            if preset.get('type_labels'):
                continue
            assert '{TYPE_LABEL}' not in preset['numbering_format'], (
                f'preset {name!r} numbers with {{TYPE_LABEL}} but ships no '
                'labels, so the number falls back to the internal code and '
                'the format promised a word that is not there.'
            )
