"""Unit tests for the typed partner address schema."""

import pytest
from pydantic import ValidationError

from app.schemas.partner import (
    PartnerAddressOut,
    PartnerCreate,
)


class TestPartnerAddressInput:
    def test_rejects_unknown_address_keys(self) -> None:
        with pytest.raises(ValidationError):
            PartnerCreate(
                name='X',
                type='SUPPLIER',
                address={'street': 'Main St', 'floor': '3'},
            )

    def test_rejects_invalid_country_code(self) -> None:
        with pytest.raises(ValidationError):
            PartnerCreate(
                name='X',
                type='SUPPLIER',
                address={'country': 'Polska'},
            )

    def test_rejects_fabricated_country_code(self) -> None:
        # "ZZ" satisfies the old two-letter format but is not an assigned
        # ISO 3166-1 alpha-2 code.
        with pytest.raises(ValidationError):
            PartnerCreate(
                name='X',
                type='SUPPLIER',
                address={'country': 'ZZ'},
            )

    @pytest.mark.parametrize('code', ['PL', 'US'])
    def test_accepts_real_iso_country_codes(self, code: str) -> None:
        data = PartnerCreate(
            name='X',
            type='SUPPLIER',
            address={'country': code},
        )
        assert data.address is not None
        assert data.address.country == code

    def test_normalizes_country_code_to_uppercase(self) -> None:
        data = PartnerCreate(
            name='X',
            type='SUPPLIER',
            address={'country': 'pl'},
        )
        assert data.address is not None
        assert data.address.country == 'PL'

    def test_empty_country_becomes_none(self) -> None:
        data = PartnerCreate(
            name='X',
            type='SUPPLIER',
            address={'country': ''},
        )
        assert data.address is not None
        assert data.address.country is None


class TestPartnerAddressOutLegacy:
    def test_tolerates_free_text_country_and_extra_keys(self) -> None:
        addr = PartnerAddressOut.model_validate(
            {
                'street': 'Old St',
                'country': 'Polska',
                'floor': '2',
            }
        )
        assert addr.country == 'Polska'
        assert addr.floor == '2'
