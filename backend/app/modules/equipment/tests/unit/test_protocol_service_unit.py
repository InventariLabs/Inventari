"""
Unit tests for protocol_service helper functions — pure logic, no DB.
"""

import pytest

from app.modules.equipment.protocol_service import _LABELS, AVAILABLE_PLACEHOLDERS


@pytest.mark.unit
class TestLabels:
    def test_english_labels_exist(self) -> None:
        assert 'checkout_title' in _LABELS['en']
        assert 'checkin_title' in _LABELS['en']
        assert 'section_asset' in _LABELS['en']
        assert 'footer' in _LABELS['en']

    def test_polish_labels_exist(self) -> None:
        assert 'checkout_title' in _LABELS['pl']
        assert 'checkin_title' in _LABELS['pl']

    def test_label_dicts_have_same_keys(self) -> None:
        en_keys = set(_LABELS['en'].keys())
        pl_keys = set(_LABELS['pl'].keys())
        assert en_keys == pl_keys


@pytest.mark.unit
class TestAvailablePlaceholders:
    def test_placeholders_is_non_empty_list(self) -> None:
        assert isinstance(AVAILABLE_PLACEHOLDERS, list)
        assert len(AVAILABLE_PLACEHOLDERS) > 0

    def test_each_placeholder_has_key_and_description(self) -> None:
        for p in AVAILABLE_PLACEHOLDERS:
            assert 'key' in p
            assert 'description' in p
            assert p['key'].startswith('{{')
            assert p['key'].endswith('}}')


@pytest.mark.unit
class TestSharedPdfRendering:
    async def test_protocol_uses_shared_filters_and_converter(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Filters already worked; converter delegation fails before the fix."""
        from types import SimpleNamespace
        from unittest.mock import AsyncMock, MagicMock
        from uuid import uuid4

        from app.core.pdf_base_service import PdfServiceBase
        from app.modules.equipment import protocol_service as service

        rendered: list[str] = []

        def convert(html: str) -> bytes:
            rendered.append(html)
            return b'shared-pdf'

        monkeypatch.setattr(
            service,
            'get_org_owned_or_404_async',
            AsyncMock(return_value=SimpleNamespace(checked_in_at=None)),
        )
        monkeypatch.setattr(
            service.core_api.templates,
            'get_default_async',
            AsyncMock(
                return_value=SimpleNamespace(
                    body_html='<p>{{ quantity | format_decimal }}</p>'
                )
            ),
        )
        monkeypatch.setattr(
            service, '_build_context_async', AsyncMock(return_value={'quantity': 12.5})
        )
        monkeypatch.setattr(
            service, 'resolve_page_size_async', AsyncMock(return_value='letter')
        )
        monkeypatch.setattr(
            PdfServiceBase,
            'render_to_pdf',
            staticmethod(convert),
        )
        result = await service.render_protocol_pdf_async(MagicMock(), uuid4(), uuid4())
        assert result == b'shared-pdf'
        assert '<p>12.50</p>' in rendered[0]
        assert 'Letter' in rendered[0]
