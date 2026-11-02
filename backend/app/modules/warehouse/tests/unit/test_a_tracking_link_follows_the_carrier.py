"""Which tracking page a carrier's name and number lead to."""

from __future__ import annotations

from app.modules.warehouse.shipment_service import tracking_url


class TestATrackingLinkFollowsTheCarrier:
    def test_a_built_in_carrier_is_matched_however_it_is_typed(self) -> None:
        assert tracking_url('  poczta   POLSKA ', 'RR123456789PL') == (
            'https://emonitoring.poczta-polska.pl/?numer=RR123456789PL'
        )

    def test_the_organization_template_wins_over_the_built_in_one(self) -> None:
        own = {'DHL': 'https://dhl.example.pl/?n={tracking_number}'}

        assert tracking_url('dhl', '00340', own) == 'https://dhl.example.pl/?n=00340'

    def test_an_organization_defined_carrier_is_linked(self) -> None:
        own = {'Raben': 'https://raben.example/track/{tracking_number}'}

        assert tracking_url('RABEN', 'a b&c', own) == (
            'https://raben.example/track/a%20b%26c'
        )

    def test_an_unknown_carrier_has_no_link(self) -> None:
        assert (
            tracking_url('Our van', 'V-7', {'Raben': 'https://r/{tracking_number}'})
            is None
        )

    def test_no_number_means_no_link(self) -> None:
        assert tracking_url('InPost', None) is None
