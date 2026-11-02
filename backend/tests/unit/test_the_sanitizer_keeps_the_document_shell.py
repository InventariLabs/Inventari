"""The sanitizer keeps the shell of a full document.

A review of the equipment protocol sanitization
measured the class: a fragment vocabulary applied to a full document
strips ``<!DOCTYPE>``, ``<html>``, ``<head>``, ``<meta charset>`` and
``<body>``, and the browser answers quirks mode — different line heights,
different table metrics — on the protocol an organization hands out by
default. The pin here is "the default templates render unchanged": the
sanitized output must parse to the same DOM the raw render parses to
(entities and implied ``<tbody>`` normalize out on both sides, because
both sides go through the same browser-grade parser), and the doctype —
which no parser inserts on its own — must still be on the wire.
"""

from __future__ import annotations

import html5lib
from jinja2 import sandbox

from app.modules.equipment._protocol_templates import (
    DEFAULT_CHECKIN_TEMPLATE,
    DEFAULT_CHECKOUT_TEMPLATE,
    LABELS,
)
from app.services.template_engine import sanitize_html

_CONTEXT = {
    'item_name': 'ThinkPad X1 Carbon',
    'item_barcode': 'STM-0042',
    'category_name': 'Laptops',
    'serial_number': 'SN-77',
    'asset_tag': 'IT-0042',
    'manufacturer': 'Lenovo',
    'model': 'X1 Carbon',
    'manufacturer_model': 'Lenovo X1 Carbon',
    'assigned_to_name': 'Jan Kowalski',
    'assigned_to_email': 'jan@example.com',
    'checked_out_at': '2026-10-01 12:00',
    'checked_in_at': None,
    'expected_return_at': '2026-10-08',
    'checkout_notes': 'Charger in the side pocket',
    'checkin_notes': None,
    'checkin_condition': 'GOOD',
    'issued_by_name': 'Anna Nowak',
    'issued_by_email': 'anna@example.com',
    'organization_name': 'Inventari QA',
    'document_date': '2026-10-01',
    'document_number': 'PRT-0001',
}


def _raw_render(template_html: str, lang: str) -> str:
    """The unsanitized render — the output the sanitizer receives."""
    env = sandbox.SandboxedEnvironment(autoescape=True)
    return env.from_string(template_html).render(
        L=LABELS.get(lang, LABELS['en']), **_CONTEXT
    )


def _normalized_dom(html_str: str):
    """Element tree with whitespace-run text and attribute order flattened.

    Both sides are parsed by html5lib, so parser normalizations — implied
    ``<tbody>``, decoded entities — cancel out; what remains different is
    what the sanitizer changed.
    """

    def walk(element):
        children = []
        for child in element:
            tag = child.tag.rsplit('}', 1)[-1]
            attrs = {k.rsplit('}', 1)[-1]: v for k, v in child.attrib.items()}
            inner = ' '.join(
                ' '.join(text.split())
                for text in [(child.text or ''), (child.tail or '')]
                if text and text.strip()
            )
            children.append((tag, sorted(attrs.items()), inner, walk(child)))
        return children

    return walk(html5lib.parse(html_str, treebuilder='etree'))


def test_default_templates_keep_their_document_shell() -> None:
    """DOCTYPE/html/head/meta/body survive sanitization, per language."""
    for template in (DEFAULT_CHECKOUT_TEMPLATE, DEFAULT_CHECKIN_TEMPLATE):
        for lang in ('en', 'pl'):
            sanitized = sanitize_html(_raw_render(template, lang))

            assert sanitized.lstrip().lower().startswith('<!doctype html'), (
                f'{lang}: doctype stripped — quirks mode on the wire'
            )
            for shell_tag in ('<html', '<head', '<meta charset', '<body'):
                assert shell_tag in sanitized.lower(), (
                    f'{lang}: {shell_tag} missing from the shell'
                )


def test_default_templates_render_unchanged() -> None:
    """Sanitized and raw renders parse to the same DOM, per language."""
    for template in (DEFAULT_CHECKOUT_TEMPLATE, DEFAULT_CHECKIN_TEMPLATE):
        for lang in ('en', 'pl'):
            raw = _raw_render(template, lang)
            sanitized = sanitize_html(raw)

            assert _normalized_dom(raw) == _normalized_dom(sanitized), (
                f'{lang}: the sanitizer changed the parsed document'
            )


def test_a_script_in_the_head_dies_like_one_in_the_body() -> None:
    """The HTML endpoint serves the document as a page, not only in the
    sandboxed preview iframe — head-hostile markup must not survive."""
    hostile = (
        '<!DOCTYPE html>\n<html>\n<head>\n'
        '<meta charset="utf-8">\n'
        '<script>alert(1)</script>\n'
        '<style>body { color: #1a1a1a; }</style>\n'
        '</head>\n<body><h1>Custom</h1></body>\n</html>\n'
    )
    sanitized = sanitize_html(hostile)

    assert '<script' not in sanitized
    assert 'alert(1)' not in sanitized
    assert sanitized.lstrip().lower().startswith('<!doctype html')
    assert '<meta charset' in sanitized.lower()
    assert '<style>' in sanitized
    assert '<h1>Custom</h1>' in sanitized


def test_a_body_fragment_is_cleaned_as_before() -> None:
    """Fragments — the documents/PO template shape — keep the old pass."""
    sanitized = sanitize_html('<p>ok</p><script>alert(1)</script>')

    assert sanitized == '<p>ok</p>'
