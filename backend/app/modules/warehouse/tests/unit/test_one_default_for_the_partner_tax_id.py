"""The country's default for the partner tax id is read in one place.

The settings screen shows the default from the offer endpoint and
confirmation applies it through the resolver. When each carried its own copy
of the lookup they could disagree after one of them changed; both now ask
``country_requires_partner_tax_id``, so a change there moves both.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest

from app.modules.warehouse import document_profile_service, tax_rate_router
from app.modules.warehouse.country_tax_rules import (
    COUNTRY_RULES,
    country_requires_partner_tax_id,
)


@pytest.mark.unit
class TestTheDefault:
    @pytest.mark.parametrize('country', sorted(COUNTRY_RULES))
    def test_it_is_the_rule_of_the_country_in_either_case(self, country: str) -> None:
        expected = COUNTRY_RULES[country].require_partner_tax_id
        assert country_requires_partner_tax_id(country) is expected
        assert country_requires_partner_tax_id(country.lower()) is expected

    @pytest.mark.parametrize('country', [None, '', 'ZZ'])
    def test_no_country_or_none_with_a_row_requires_nothing(
        self, country: str | None
    ) -> None:
        assert country_requires_partner_tax_id(country) is False


@pytest.mark.unit
class TestBothReadersAskTheSameFunction:
    async def test_the_offer_endpoint_and_the_resolver_follow_it(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        asked: list[str | None] = []

        def answer(country: str | None) -> bool:
            asked.append(country)
            return True

        async def org_of(_db: Any, _org_id: Any) -> Any:
            return SimpleNamespace(country='ZZ')

        monkeypatch.setattr(tax_rate_router, 'country_requires_partner_tax_id', answer)
        monkeypatch.setattr(
            document_profile_service, 'country_requires_partner_tax_id', answer
        )
        monkeypatch.setattr(
            document_profile_service.core_api.organizations, 'get_async', org_of
        )
        monkeypatch.setattr(tax_rate_router, '_org_country', _country_zz)

        user: Any = SimpleNamespace(organization_id=uuid4())
        db: Any = None
        profile: Any = SimpleNamespace(require_partner_tax_id=None)
        offer = await tax_rate_router.country_rates(current_user=user, db=db)
        resolved = await document_profile_service.resolve_partner_tax_id_required(
            db, uuid4(), profile
        )

        assert offer.require_partner_tax_id is True
        assert resolved is True
        assert asked == ['ZZ', 'ZZ']


async def _country_zz(_db: Any, _org_id: Any) -> str:
    return 'ZZ'
