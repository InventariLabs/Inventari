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
import re

import pytest
from weasyprint import HTML
from weasyprint.formatting_structure import boxes

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
        # What the printer draws: an <img> WeasyPrint cannot load collapses
        # to its alt text, so a replaced box in the layout is a code on paper.
        def images_on_page(html: str) -> int:
            document = HTML(string=html).render()
            return sum(
                isinstance(box, boxes.ReplacedBox)
                for box in document.pages[0]._page_box.descendants()
            )

        context = _context()
        assert images_on_page(core_api.pdf.render_html(_TEMPLATE, context)) == 2
        assert (
            images_on_page(
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

    @pytest.mark.parametrize('mime', ['png', 'jpeg', 'gif', 'svg+xml'])
    def test_image_data_uri_in_img_src_is_kept(self, mime):
        uri = f'data:image/{mime};base64,AAAA'
        assert uri in sanitize_html(f'<img src="{uri}" alt="x">')
