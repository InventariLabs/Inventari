"""
Unit tests for equipment status_machine — pure transition validation.
"""

import pytest

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
        with pytest.raises(ValueError, match='Invalid status'):
            validate_transition('AVAILABLE', 'INVALID')

    def test_invalid_transition_available_to_available_raises(self) -> None:
        with pytest.raises(ValueError, match='Cannot change status'):
            validate_transition('AVAILABLE', 'AVAILABLE')

    def test_invalid_transition_retired_to_deployed_raises(self) -> None:
        with pytest.raises(ValueError, match='Cannot change status'):
            validate_transition('RETIRED', 'DEPLOYED')

    def test_invalid_transition_retired_to_maintenance_raises(self) -> None:
        with pytest.raises(ValueError, match='Cannot change status'):
            validate_transition('RETIRED', 'MAINTENANCE')

    def test_retired_hint_included_in_error_message(self) -> None:
        with pytest.raises(ValueError, match='Retired assets must be'):
            validate_transition('RETIRED', 'DEPLOYED')

    def test_empty_old_status_allows_any_valid(self) -> None:
        validate_transition('', 'AVAILABLE')
        validate_transition('', 'DEPLOYED')
        validate_transition('', 'MAINTENANCE')
        validate_transition('', 'RETIRED')

    def test_unknown_old_status_allows_any_valid(self) -> None:
        validate_transition('UNKNOWN', 'AVAILABLE')
        validate_transition('UNKNOWN', 'RETIRED')

    def test_polish_lang_error_message(self) -> None:
        with pytest.raises(ValueError, match='Nie'):
            validate_transition('AVAILABLE', 'INVALID', lang='pl')

    def test_german_lang_error_message(self) -> None:
        with pytest.raises(ValueError, match='Ung'):
            validate_transition('AVAILABLE', 'INVALID', lang='de')

    def test_french_lang_error_message(self) -> None:
        with pytest.raises(ValueError, match='Statut'):
            validate_transition('AVAILABLE', 'INVALID', lang='fr')

    def test_spanish_lang_error_message(self) -> None:
        with pytest.raises(ValueError, match='Estado'):
            validate_transition('AVAILABLE', 'INVALID', lang='es')

    def test_fallback_to_en_for_unknown_lang(self) -> None:
        with pytest.raises(ValueError, match='Invalid status'):
            validate_transition('AVAILABLE', 'INVALID', lang='xx')

    def test_valid_statuses_set(self) -> None:
        assert VALID_STATUSES == {'AVAILABLE', 'DEPLOYED', 'MAINTENANCE', 'RETIRED'}
