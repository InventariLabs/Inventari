"""
Unit tests for equipment status_machine — pure transition validation.
"""

import pytest

from app.core.exceptions import ServiceRejectionError
from app.i18n import Language
from app.i18n.service import set_current_lang
from app.modules.equipment.status_machine import (
    VALID_STATUSES,
    validate_transition,
)


@pytest.mark.integration
class TestValidateTransition:
    @pytest.mark.parametrize(
        ('old_status', 'new_status'),
        [
            ('AVAILABLE', 'DEPLOYED'),
            ('AVAILABLE', 'MAINTENANCE'),
            ('AVAILABLE', 'RETIRED'),
            ('DEPLOYED', 'AVAILABLE'),
            ('DEPLOYED', 'MAINTENANCE'),
            ('DEPLOYED', 'RETIRED'),
            ('MAINTENANCE', 'AVAILABLE'),
            ('MAINTENANCE', 'DEPLOYED'),
            ('MAINTENANCE', 'RETIRED'),
            ('RETIRED', 'AVAILABLE'),
        ],
        ids=[
            'available_to_deployed',
            'available_to_maintenance',
            'available_to_retired',
            'deployed_to_available',
            'deployed_to_maintenance',
            'deployed_to_retired',
            'maintenance_to_available',
            'maintenance_to_deployed',
            'maintenance_to_retired',
            'retired_to_available',
        ],
    )
    def test_valid_transition(self, old_status: str, new_status: str) -> None:
        validate_transition(old_status, new_status)

    def test_invalid_status_raises(self) -> None:
        with pytest.raises(ServiceRejectionError) as refusal:
            validate_transition('AVAILABLE', 'INVALID')
        assert refusal.value.key == 'equipment_status_invalid'
        assert str(refusal.value) == 'Invalid status: INVALID'

    @pytest.mark.parametrize(
        ('old_status', 'new_status'),
        [
            ('AVAILABLE', 'AVAILABLE'),
            ('RETIRED', 'DEPLOYED'),
            ('RETIRED', 'MAINTENANCE'),
        ],
    )
    def test_a_refused_transition_carries_its_catalogue_key(
        self, old_status: str, new_status: str
    ) -> None:
        with pytest.raises(ServiceRejectionError) as refusal:
            validate_transition(old_status, new_status)
        expected = (
            'equipment_status_transition_from_retired'
            if old_status == 'RETIRED'
            else 'equipment_status_transition_denied'
        )
        assert refusal.value.key == expected
        assert f'from {old_status} to {new_status}' in str(refusal.value)

    def test_retired_hint_included_in_error_message(self) -> None:
        with pytest.raises(ValueError, match='Retired assets must be'):
            validate_transition('RETIRED', 'DEPLOYED')

    def test_the_hint_belongs_to_retired_assets_only(self) -> None:
        with pytest.raises(ValueError) as refusal:
            validate_transition('AVAILABLE', 'AVAILABLE')
        assert 'Retired assets' not in str(refusal.value)

    def test_empty_old_status_allows_any_valid(self) -> None:
        validate_transition('', 'AVAILABLE')
        validate_transition('', 'DEPLOYED')
        validate_transition('', 'MAINTENANCE')
        validate_transition('', 'RETIRED')

    def test_unknown_old_status_allows_any_valid(self) -> None:
        validate_transition('UNKNOWN', 'AVAILABLE')
        validate_transition('UNKNOWN', 'RETIRED')

    @pytest.mark.parametrize(
        ('lang', 'sentence'),
        [
            ('pl', 'Nieprawidłowy status: INVALID'),
            ('de', 'Ungültiger Status: INVALID'),
            ('fr', 'Statut invalide : INVALID'),
            ('es', 'Estado no válido: INVALID'),
            ('en', 'Invalid status: INVALID'),
        ],
    )
    def test_the_refusal_speaks_the_language_of_the_request(
        self, lang: Language, sentence: str
    ) -> None:
        set_current_lang(lang)
        try:
            with pytest.raises(ServiceRejectionError) as refusal:
                validate_transition('AVAILABLE', 'INVALID')
        finally:
            set_current_lang('en')
        assert str(refusal.value) == sentence

    def test_the_retired_hint_is_translated_too(self) -> None:
        set_current_lang('pl')
        try:
            with pytest.raises(ServiceRejectionError) as refusal:
                validate_transition('RETIRED', 'DEPLOYED')
        finally:
            set_current_lang('en')
        assert str(refusal.value) == (
            'Nie można zmienić statusu z RETIRED na DEPLOYED. '
            'Wycofane zasoby muszą być najpierw jawnie przywrócone.'
        )

    def test_valid_statuses_set(self) -> None:
        assert VALID_STATUSES == {'AVAILABLE', 'DEPLOYED', 'MAINTENANCE', 'RETIRED'}
