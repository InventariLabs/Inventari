"""A preset that names no padding falls back to the one shared constant.

The number shape has a single source of truth: ``DEFAULT_NUMBER_PADDING``
is read by the column default, by the Simple preset and by the numbering
fallback. The ``apply_preset`` branch for a preset that omits
``number_padding`` carried its own literal instead — another
default-of-defaults in exactly the class the one-constant work set out to
remove, dormant only because every preset defines the key. This applies a
crafted preset without the key and holds the fallback to the constant; with
a literal back in that branch, an organization switching to a preset that
omits the key would number itself with a padding nothing else expects.
"""

from __future__ import annotations

import asyncio

import pytest
from sqlalchemy.orm import Session

from app.models.organization import Organization
from app.modules.warehouse import document_profile_service
from app.modules.warehouse.models import TaxHandling
from app.modules.warehouse.models.profile import (
    DEFAULT_NUMBER_PADDING,
    DEFAULT_NUMBERING_FORMAT,
)


@pytest.mark.integration
class TestAPresetWithoutPaddingReadsTheConstant:
    def test_preset_omitting_number_padding_gets_the_constant(
        self,
        db_session: Session,
        doc_org: Organization,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setitem(
            document_profile_service.PRESETS,
            'Probe',
            {
                'value_tracking_enabled': False,
                'tax_handling': TaxHandling.NONE.value,
                'default_tax_rate': None,
                'require_partner_tax_id': False,
                'numbering_format': DEFAULT_NUMBERING_FORMAT,
                'type_labels': None,
                'default_unit': 'pcs',
                'visible_line_fields': [],
                'print_template': 'standard',
                'default_currency': None,
                # number_padding deliberately absent — the branch under test
            },
        )

        profile = asyncio.run(
            document_profile_service.apply_preset(db_session, doc_org.id, 'Probe')
        )

        assert profile.number_padding == DEFAULT_NUMBER_PADDING, (
            f'fallback padding is {profile.number_padding}, '
            f'expected the shared constant {DEFAULT_NUMBER_PADDING}'
        )
