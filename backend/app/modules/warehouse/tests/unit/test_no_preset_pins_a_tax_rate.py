"""No preset quotes a tax rate or a partner-tax-id requirement.

A preset is a way of working, not a country — and the numbers and
requirements written into one are a country in disguise. ``Full Value``
shipped with the UK basic rate (20%), and the ``equipment_wms`` profile
applies that preset at onboarding, so a Polish company taking the
"Equipment & WMS" profile found a silent 20% waiting on every document it
would ever raise. The same argument already retired pinned currencies (see
the note beside ``PL Magazyn``): the rate is stronger still, because it
enters the net/tax/gross arithmetic instead of labelling a number. A rate
is either the organization's own choice or no rate at all — an untaxed
document is worth its net, which is long-settled behaviour
(``compute_line_gross``).

The partner-tax-id requirement is the second legal axis a preset used to
pin (``PL Magazyn`` and ``DE Lager`` demanded it, the others did not). It
belongs to the country too, and the profile carries ``None`` — "no
opinion" — until the organization says otherwise.
"""

from __future__ import annotations

import pytest

from app.modules.warehouse import document_profile_service


@pytest.mark.unit
class TestNoPresetPinsATaxRate:
    def test_every_preset_carries_no_default_tax_rate(self) -> None:
        for name, preset in document_profile_service.PRESETS.items():
            assert preset['default_tax_rate'] is None, (
                f'preset {name!r} pins a default tax rate '
                f'({preset["default_tax_rate"]}). Presets are not regional: '
                'a rate enters the net/tax/gross arithmetic, so it belongs '
                'to the organization (or nowhere), never to a preset.'
            )

    def test_every_preset_leaves_the_partner_tax_id_requirement_open(self) -> None:
        for name, preset in document_profile_service.PRESETS.items():
            assert preset['require_partner_tax_id'] is None, (
                f'preset {name!r} pins require_partner_tax_id '
                f'({preset["require_partner_tax_id"]}). Whether a partner '
                'must carry a tax id is law, and law is where the '
                'organization sits — the country answers, the preset does '
                'not.'
            )
