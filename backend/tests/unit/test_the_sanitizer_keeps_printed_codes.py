"""A printout through an organization template keeps its barcode and QR.

The codes reach the template as ``data:`` URIs inside ``<img src>``. The
engine cleans the *rendered* HTML with nh3, whose default URL schemes have
no ``data:``, so the whole ``src`` used to be stripped and the printout
(and the editor preview, which goes through the same call) came out with
two empty ``<img>`` tags. The pins here measure the rendered result — the
bytes of the image that survive, and what WeasyPrint draws from them — not
just that an attribute exists, and they pin the other side of the policy:
``data:`` stays confined to raster/vector images in ``<img src>``.
"""

from __future__ import annotations

import base64
import io
import re
from types import SimpleNamespace

import pytest
from PIL import Image
from weasyprint import HTML
from weasyprint.formatting_structure import boxes

from app.core.file_storage.service import FileStorageService
from app.core.print_identity import build_issuer_context
from app.core.public_api import core_api
from app.services.pdf_utils import generate_code128, generate_qr
from app.services.template_engine import TemplateEngine, sanitize_html

_TEMPLATE = (
    '<div><img class="code128" alt="{{ number }}" src="{{ code128_img }}">'
    '<img class="qr" alt="{{ number }}" src="{{ qr_img }}"></div>'
)


def _context() -> dict[str, str]:
    code128 = generate_code128('IN/2026/001')
    qr = generate_qr('IN/2026/001')
    return {
        'number': 'IN/2026/001',
        'code128_img': code128.data_uri,
        'qr_img': qr.data_uri,
    }


def _srcs(html: str) -> list[str]:
    return re.findall(r'<img\b[^>]*?\bsrc="([^"]*)"', html)


def _decoded(data_uri: str) -> bytes:
    return base64.b64decode(data_uri.split(',', 1)[1])


def _images_on_page(html: str) -> int:
    """What the printer draws: an <img> WeasyPrint cannot load collapses
    to its alt text, so a replaced box in the layout is an image on paper."""
    document = HTML(string=html).render()
    return sum(
        isinstance(box, boxes.ReplacedBox)
        for box in document.pages[0]._page_box.descendants()
    )


@pytest.mark.unit
class TestPrintedCodesSurviveSanitization:
    def test_rendered_template_keeps_both_images_byte_for_byte(self):
        context = _context()
        rendered = TemplateEngine().render(_TEMPLATE, context)

        srcs = _srcs(rendered)
        assert len(srcs) == 2
        assert _decoded(srcs[0]) == _decoded(context['code128_img'])
        assert _decoded(srcs[1]) == _decoded(context['qr_img'])

    def test_preview_render_path_keeps_the_images(self):
        rendered = core_api.pdf.render_html(_TEMPLATE, _context())
        assert len(_srcs(rendered)) == 2

    def test_printout_lays_out_both_codes_as_images(self):
        context = _context()
        assert _images_on_page(core_api.pdf.render_html(_TEMPLATE, context)) == 2
        assert (
            _images_on_page(
                core_api.pdf.render_html(
                    _TEMPLATE, {**context, 'code128_img': '', 'qr_img': ''}
                )
            )
            == 0
        )


@pytest.mark.unit
class TestDataUrisStayConfinedToImages:
    @pytest.mark.parametrize(
        'html',
        [
            '<a href="data:text/html;base64,PHNjcmlwdD4=">x</a>',
            '<a href="data:image/png;base64,AAAA">x</a>',
            '<img src="data:text/html;base64,PHNjcmlwdD4=" alt="x">',
            '<img src="data:image/png;base64,AA AA<script>" alt="x">',
            '<img src="javascript:alert(1)" alt="x">',
            '<img src="DATA:image/png;base64,AAAA" alt="x">',
            '<a href="da&#10;ta:text/html;base64,PHNjcmlwdD4=">x</a>',
            '<blockquote cite="data:image/png;base64,AAAA">x</blockquote>',
        ],
    )
    def test_other_data_uris_are_still_stripped(self, html):
        assert 'data:' not in sanitize_html(html).lower()
        assert 'ta:text' not in sanitize_html(html)
        assert 'javascript:' not in sanitize_html(html)

    @pytest.mark.parametrize('mime', ['png', 'jpeg', 'gif', 'svg+xml', 'webp'])
    def test_image_data_uri_in_img_src_is_kept(self, mime):
        uri = f'data:image/{mime};base64,AAAA'
        assert uri in sanitize_html(f'<img src="{uri}" alt="x">')


@pytest.mark.unit
class TestTextThatStartsWithDataIsNotAUrl:
    """The Polish label for a date, "Data:", is text, not a URL scheme.

    The ``data:`` check ran on every attribute, so a Polish template's
    ``alt="Data: 14.10"`` or ``title="Data: 2026-10-14"`` vanished from the
    printout and the editor preview without a word. Only an attribute that
    holds a URL can carry a ``data:`` document.
    """

    @pytest.mark.parametrize(
        ('html', 'kept'),
        [
            ('<img alt="Data: 14.10" src="https://x/y.png">', 'alt="Data: 14.10"'),
            ('<span title="Data: 2026-10-14">y</span>', 'title="Data: 2026-10-14"'),
            ('<span class="data:x">y</span>', 'class="data:x"'),
        ],
    )
    def test_a_text_attribute_starting_with_data_survives(self, html, kept):
        assert kept in sanitize_html(html)


@pytest.mark.unit
class TestAWebpLogoPrints:
    """The logo upload takes WebP, and the issuer block embeds it as
    ``data:image/webp``; the image allowlist knew only png, jpeg, gif and
    svg, so an organization template printed ``{{ issuer.logo }}`` as an
    empty ``<img>``."""

    async def test_an_uploaded_webp_logo_prints_through_an_organization_template(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        buffer = io.BytesIO()
        Image.new('RGB', (4, 4), 'red').save(buffer, 'WEBP')
        webp = buffer.getvalue()

        async def stored_logo(self, path: str) -> io.BytesIO:
            return io.BytesIO(webp)

        monkeypatch.setattr(FileStorageService, 'get', stored_logo)
        issuer = await build_issuer_context(
            SimpleNamespace(logo_url='org/organizations/logo.webp'), lang='pl'
        )
        assert issuer.logo is not None
        assert issuer.logo.startswith('data:image/webp;base64,')

        rendered = core_api.pdf.render_html(
            '<div><img alt="logo" src="{{ issuer.logo }}"></div>', {'issuer': issuer}
        )

        assert [_decoded(src) for src in _srcs(rendered)] == [webp]
        assert _images_on_page(rendered) == 1
