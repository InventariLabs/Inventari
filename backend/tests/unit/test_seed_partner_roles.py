"""Both sides of the trade exist in seeded and fixture data.

An organization seeded with suppliers alone can receive goods and never send
any: the partner picker on a delivery document comes up empty, and the whole
outbound half of the application is unreachable without someone adding a
partner by hand first.
"""

from __future__ import annotations

import pytest

from seed_demo_data import DEMO_PARTNERS


def _types() -> set[str]:
    return {ptype for _name, ptype, *_rest in DEMO_PARTNERS}


@pytest.mark.unit
class TestSeededPartnersCoverBothDirections:
    def test_there_is_someone_to_receive_from(self) -> None:
        assert 'SUPPLIER' in _types()

    def test_there_is_someone_to_dispatch_to(self) -> None:
        assert 'CUSTOMER' in _types()

    def test_partner_codes_are_unique(self) -> None:
        codes = [code for _name, _ptype, code, *_rest in DEMO_PARTNERS]
        assert len(codes) == len(set(codes))
