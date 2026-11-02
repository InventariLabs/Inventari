"""Shared Jinja2 sandboxed template engine for user-authored document templates."""

from __future__ import annotations

import re
import secrets
from html import escape as html_escape
from pathlib import Path
from typing import Any

import nh3
from jinja2 import BaseLoader, sandbox

from app.core.logging import get_logger
from app.services.pdf_utils import register_pdf_filters

logger = get_logger(__name__)

_ALLOWED_TAGS = {
    'a',
    'abbr',
    'address',
    'article',
    'aside',
    'b',
    'bdi',
    'bdo',
    'blockquote',
    'br',
    'caption',
    'cite',
    'code',
    'col',
    'colgroup',
    'dd',
    'del',
    'details',
    'dfn',
    'div',
    'dl',
    'dt',
    'em',
    'figcaption',
    'figure',
    'footer',
    'h1',
    'h2',
    'h3',
    'h4',
    'h5',
    'h6',
    'header',
    'hgroup',
    'hr',
    'i',
    'img',
    'ins',
    'kbd',
    'li',
    'main',
    'mark',
    'nav',
    'ol',
    'p',
    'pre',
    'q',
    'rp',
    'rt',
    'ruby',
    's',
    'samp',
    'section',
    'small',
    'span',
    'strong',
    'sub',
    'summary',
    'sup',
    'table',
    'tbody',
    'td',
    'tfoot',
    'th',
    'thead',
    'time',
    'tr',
    'u',
    'ul',
    'var',
    'wbr',
    # Stylesheet blocks: the built-in templates (and their seeded copies)
    # style the printout with a <style> block, and the criterion
    # "renders correctly without any edits" demands the copy keep it. The
    # CSS passes through untouched — the same posture the style *attribute*
    # already has (nh3 does not sanitize CSS there either); WeasyPrint
    # renders with a data-only URL fetcher, so a stylesheet cannot reach
    # outside the PDF.
    'style',
}

_ALLOWED_ATTRIBUTES = {
    '*': {'class', 'id', 'style', 'title', 'lang', 'dir'},
    'a': {'href', 'target'},
    'img': {'src', 'alt', 'width', 'height', 'loading'},
    'td': {'colspan', 'rowspan'},
    'th': {'colspan', 'rowspan', 'scope'},
    'ol': {'start', 'type'},
    'time': {'datetime'},
    'col': {'span'},
    'colgroup': {'span'},
    'del': {'cite', 'datetime'},
    'ins': {'cite', 'datetime'},
    'blockquote': {'cite'},
    'q': {'cite'},
}


#: The shell a full HTML document carries and a body fragment does not.
#: A document-shaped template (the equipment protocol defaults, and any
#: custom template modelled on them) keeps its shell through sanitization:
#: a fragment sanitizer applied to a full document strips ``<!DOCTYPE>``,
#: ``<html>``, ``<head>``, ``<meta charset>`` and ``<body>``, and the
#: browser drops into quirks mode — different line heights, different
#: table metrics — on the protocol the organization hands out by default.
#: Ammonia parses fragments, so no tag vocabulary can make it keep the
#: wrappers: the document pass below splits the shell off, cleans the
#: head and the body as fragments, and re-wraps them with allowlisted
#: attributes on ``<html>``/``<body>`` (a ``<body onload=...>`` must not
#: survive its own re-wrap).
_DOCUMENT_HEAD_TAGS = {'meta', 'title'}

_DOCUMENT_HEAD_ATTRIBUTES = {
    'meta': {'charset', 'http-equiv', 'content', 'name'},
}

_HTML_OPEN_ATTRIBUTES = {'lang', 'dir'}

_LEADING_DOCTYPE_RE = re.compile(r'\s*(<!DOCTYPE[^>]*>)', re.IGNORECASE)
_HTML_OPEN_RE = re.compile(r'<html\b([^>]*)>', re.IGNORECASE)
_HEAD_SPAN_RE = re.compile(r'<head\b[^>]*>(.*?)</head\s*>', re.IGNORECASE | re.DOTALL)
_BODY_SPAN_RE = re.compile(r'<body\b([^>]*)>(.*)</body\s*>', re.IGNORECASE | re.DOTALL)
_CLOSE_HTML_RE = re.compile(r'\s*</html\s*>')
_ATTRIBUTE_RE = re.compile(
    r'([a-zA-Z_:][-a-zA-Z0-9_:.]*)\s*=\s*(?:"([^"]*)"|\'([^\']*)\')'
)


#: The one place a ``data:`` URI is allowed: an image embedded in
#: ``<img src>``. The printed Code128 (SVG) and QR (PNG) reach every print
#: template this way, and nh3's default URL schemes have no ``data:``, so the
#: whole ``src`` used to vanish and the printout came out without either
#: code. ``<img>`` never executes what it holds; the same URI in a link
#: (``data:text/html``) is a document of its own, so everywhere else it is
#: still dropped.
_DATA_IMAGE_RE = re.compile(
    r'data:image/(?:png|jpeg|gif|svg\+xml);base64,[A-Za-z0-9+/=]*'
)

#: Control characters and spaces a URL parser drops from inside a scheme
#: (``da\nta:`` is ``data:``), so the filter has to look past them too.
_URL_NOISE_RE = re.compile(r'[\x00-\x20]')

_URL_SCHEMES = set(nh3.ALLOWED_URL_SCHEMES) | {'data'}


def _only_data_images_in_img_src(tag: str, attribute: str, value: str) -> str | None:
    """Attribute filter: keep ``data:`` only on an image's ``src``."""
    if _URL_NOISE_RE.sub('', value).lower().startswith('data:') and not (
        tag == 'img' and attribute == 'src' and _DATA_IMAGE_RE.fullmatch(value)
    ):
        return None
    return value


def _nh3_clean(
    html: str,
    *,
    tags: set[str],
    attributes: dict[str, set[str]],
) -> str:
    """One cleaning pass with the shared policy options."""
    return nh3.clean(
        html,
        tags=tags,
        attributes=attributes,
        url_schemes=_URL_SCHEMES,
        attribute_filter=_only_data_images_in_img_src,
        # 'style' deliberately NOT here — it is an allowed tag (see
        # _ALLOWED_TAGS); ammonia panics when a tag is in both lists.
        clean_content_tags={'script', 'noscript'},
        link_rel='noopener noreferrer',
    )


def _reopen_tag(tag: str, raw_attributes: str, allowed: set[str]) -> str:
    """Re-emit a wrapper tag with only the attributes it may carry."""
    kept: list[str] = []
    for match in _ATTRIBUTE_RE.finditer(raw_attributes):
        name = match.group(1).lower()
        value = match.group(2) if match.group(2) is not None else match.group(3)
        if name in allowed:
            kept.append(f'{name}="{html_escape(value, quote=True)}"')
    joined = f' {" ".join(kept)}' if kept else ''
    return f'<{tag}{joined}>'


def _sanitize_document(html: str, doctype: str | None) -> str:
    """Clean a full document and hand back a full document.

    The head is cleaned with its own vocabulary (``meta``/``title`` beyond
    the body's) because the HTML protocol endpoint serves this markup as a
    page of its own, not only inside the sandboxed preview iframe — a
    ``<script>`` hiding in the head must die like one in the body. What
    sits between the shell's parts — stray markup before ``<html>``,
    between ``</head>`` and ``<body>``, after ``</html>`` — is dropped or
    cleaned rather than trusted: browsers fold it back into the document.
    """
    body = _BODY_SPAN_RE.search(html)
    if not body:
        cleaned = _nh3_clean(html, tags=_ALLOWED_TAGS, attributes=_ALLOWED_ATTRIBUTES)
        return f'{doctype}\n{cleaned}' if doctype else cleaned

    before_body = html[: body.start()]
    head = _HEAD_SPAN_RE.search(before_body)
    html_open = _HTML_OPEN_RE.search(before_body)

    head_attributes = dict(_ALLOWED_ATTRIBUTES)
    head_attributes.update(_DOCUMENT_HEAD_ATTRIBUTES)

    parts: list[str] = []
    if doctype:
        parts.append(doctype)
    if html_open:
        parts.append(_reopen_tag('html', html_open.group(1), _HTML_OPEN_ATTRIBUTES))
    if head:
        parts.append('<head>')
        parts.append(
            _nh3_clean(
                head.group(1),
                tags=_ALLOWED_TAGS | _DOCUMENT_HEAD_TAGS,
                attributes=head_attributes,
            )
        )
        parts.append('</head>')
    parts.append(_reopen_tag('body', body.group(1), _ALLOWED_ATTRIBUTES['*']))
    parts.append(
        _nh3_clean(body.group(2), tags=_ALLOWED_TAGS, attributes=_ALLOWED_ATTRIBUTES)
    )
    parts.append('</body>')

    remainder = html[body.end() :]
    close_html = _CLOSE_HTML_RE.match(remainder)
    if close_html:
        parts.append('</html>')
        extra = remainder[close_html.end() :]
    else:
        extra = remainder
    if extra.strip():
        cleaned_extra = _nh3_clean(
            extra, tags=_ALLOWED_TAGS, attributes=_ALLOWED_ATTRIBUTES
        )
        if cleaned_extra.strip():
            parts.append(cleaned_extra)

    return '\n'.join(part for part in parts if part)


def sanitize_html(body_html: str) -> str:
    """Strip dangerous tags/attributes from user-authored HTML.

    Uses nh3 (Rust-based HTML sanitizer) for robust protection against
    XSS bypass techniques that regex-based approaches are vulnerable to.

    Jinja spans are protected before cleaning and restored verbatim
    afterwards: nh3 escapes ``>`` in text nodes (``{% if x >= 0 %}`` would
    become ``{% if x &gt;= 0 %}`` and fail to render with a
    TemplateSyntaxError). A span is template code with the same trust level
    as the HTML the author wrote around it — the sandboxed engine is the
    actual boundary. The same treatment keeps ``{% include %}`` directives
    alive for ``inline_includes``, which runs after cleaning.

    A document-shaped input — a leading ``<!DOCTYPE>`` or a ``<body>`` tag
    — goes through the document pass above, which returns a document
    rather than a fragment.
    """
    protected, spans = _stash_jinja_spans(body_html)
    doctype = _LEADING_DOCTYPE_RE.match(protected)
    if doctype or _BODY_SPAN_RE.search(protected):
        cleaned = _sanitize_document(
            protected[doctype.end() :] if doctype else protected,
            doctype.group(1) if doctype else None,
        )
    else:
        cleaned = _nh3_clean(
            protected, tags=_ALLOWED_TAGS, attributes=_ALLOWED_ATTRIBUTES
        )
    for token, original in spans:
        cleaned = cleaned.replace(token, original)
    return cleaned


#: A Jinja construct that must survive sanitization byte-for-byte.
_JINJA_SPAN_RE = re.compile(r'\{%(?:.*?)%\}|{{(?:.*?)}}|{#(?:.*?)#}', re.DOTALL)


def _stash_jinja_spans(body_html: str) -> tuple[str, list[tuple[str, str]]]:
    """Replace Jinja spans with distinctive tokens so nh3 leaves them alone.

    The token is salted per call so a collision with literal template text
    is not something an author can arrange on purpose. Tokens inside content
    nh3 removes entirely (e.g. a span inside <script>) vanish with it and
    are never restored.
    """
    salt = secrets.token_hex(4)
    spans: list[tuple[str, str]] = []

    def _stash(match: re.Match[str]) -> str:
        token = f'__JINJA{salt}{len(spans)}__'
        spans.append((token, match.group(0)))
        return token

    return _JINJA_SPAN_RE.sub(_stash, body_html), spans


class TemplateEngine:
    """Shared Jinja2 sandboxed template engine for user-authored document templates."""

    def __init__(self, templates_dir: Path | None = None) -> None:
        # An organization's own template resolves includes the same way a
        # built-in does — its family's directory first, then the partials
        # every family shares.
        from app.core.pdf_base_service import print_template_loader

        # The core partials (print_header.html and friends) are a constant,
        # not a parameter: an engine without a family directory still resolves
        # {% include %} against them. A bare BaseLoader left the next caller
        # no way to keep them.
        loader: BaseLoader = print_template_loader(templates_dir)
        self._env = sandbox.SandboxedEnvironment(
            loader=loader,
            autoescape=True,
        )
        register_pdf_filters(self._env)

    def inline_includes(self, body_html: str, partials: dict[str, str]) -> str:
        """Resolve all {% include 'path' %} → inline HTML. Called at save time."""
        result = body_html
        include_pattern = re.compile(
            r"\{%\s*include\s+['\"]([^'\"]+)['\"]\s*%\}",
            re.IGNORECASE,
        )
        max_iterations = 10
        for _ in range(max_iterations):
            match = include_pattern.search(result)
            if not match:
                break
            path = match.group(1).strip()
            partial_html = partials.get(path)
            if partial_html is None:
                logger.warning('Template include not found in partials: %s', path)
                result = result[: match.start()] + result[match.end() :]
            else:
                result = result[: match.start()] + partial_html + result[match.end() :]
        return result

    def render(self, body_html: str | None, context: dict[str, Any]) -> str:
        """Render template string with sandboxed Jinja2, then sanitize.

        Sanitization happens on the *rendered* output, not on the source:
        a source-level nh3 pass reorders HTML around Jinja
        spans — html5lib foster-parents text out of table context, so
        ``{% for %}`` between ``<tbody>`` and ``<tr>`` ended up outside the
        table and the seeded copy of a built-in layout was structurally
        broken before it ever rendered. The rendered document has no Jinja
        left, so cleaning it cannot mangle the template — and it is the
        output that actually reaches the browser or the PDF.

        If body_html is None, returns empty string.
        When the engine was created with a templates_dir, ``{% include %}``
        directives are resolved from the filesystem.  Otherwise body_html
        must be a flat HTML string with no includes.
        """
        if not body_html:
            return ''
        template = self._env.from_string(body_html)
        rendered = template.render(**context)
        return sanitize_html(rendered)
