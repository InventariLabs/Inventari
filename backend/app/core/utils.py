import re
from datetime import date, datetime
from typing import Any
from urllib.parse import quote

from fastapi.responses import Response
from sqlalchemy.orm.attributes import instance_state


def pick_by_lang[T](
    lang: str,
    en: T,
    pl: T | None = None,
    de: T | None = None,
    fr: T | None = None,
    es: T | None = None,
) -> T:
    """Pick the *lang* variant of a value, falling back to English.

    i18n-lite dispatch for the PDF layer, which carries its label tables as
    plain module-level dicts instead of going through ``get_error_message``.
    Matching is by prefix, so ``pl``, ``pl-PL`` and ``pl_PL`` all resolve to
    the ``pl`` variant.

    A variant that is missing **or empty** falls back to *en*. The emptiness
    check is not incidental: ``PdfServiceBase`` declares ``labels_pl`` and
    friends as ``{}`` by default, so a subclass shipping English-only labels
    must get English back rather than an empty dict. Call sites that only
    have an EN/PL pair simply leave the rest unset.
    """
    for prefix, variant in (('pl', pl), ('de', de), ('fr', fr), ('es', es)):
        if lang.startswith(prefix):
            return variant if variant else en
    return en


def safe_get_loaded_attr(
    obj: Any, attr_name: str, nested_attr: str | None = None
) -> Any:
    """Get attribute without triggering SQLAlchemy lazy-load if not loaded."""
    if obj is None:
        return None
    state = instance_state(obj)
    if attr_name not in state.unloaded:
        val = getattr(obj, attr_name, None)
        if val is not None and nested_attr is not None:
            return safe_get_loaded_attr(val, nested_attr)
        return val
    return None


def isoformat_or_none(value: date | datetime | None) -> str | None:
    """ISO-8601 string for *value*, or ``None`` when it is unset.

    Replaces the ``x.isoformat() if x else None`` conditional that payload and
    audit builders repeat for every nullable timestamp — six occurrences before
    this helper, several of which the formatter had wrapped across three lines.
    """
    return value.isoformat() if value is not None else None


def strip_html(text: str | None) -> str | None:
    if not text:
        return text
    clean = re.compile('<.*?>')
    return re.sub(clean, '', text).strip()


def content_disposition(
    display_name: str | None, disposition: str = 'attachment'
) -> str:
    """Build a ``Content-Disposition`` value that survives the name it carries.

    The name is whatever the uploader typed. Interpolated straight into
    ``filename="..."`` a quote ends the parameter early and a CR or LF ends
    the header, so the value decided how the rest of the response was parsed.

    RFC 6266/5987: an ASCII-only ``filename`` for old clients, with every
    awkward character replaced rather than escaped, plus ``filename*`` in
    percent-encoded UTF-8, which every current browser prefers and which has
    no quoting problem to begin with.
    """
    if not display_name:
        return disposition

    ascii_fallback = (
        ''.join(
            ch if 32 <= ord(ch) < 127 and ch not in '"\\' else '_'
            for ch in display_name
        ).strip()
        or 'download'
    )
    encoded = quote(display_name, safe='')
    return f'{disposition}; filename="{ascii_fallback}"; filename*=UTF-8\'\'{encoded}'


def build_pdf_response(pdf_bytes: bytes, filename: str) -> Response:
    return Response(
        content=pdf_bytes,
        media_type='application/pdf',
        headers={
            'Content-Disposition': content_disposition(filename),
            'Content-Length': str(len(pdf_bytes)),
        },
    )


def sanitize_filename(number: str, prefix: str = 'document') -> str:
    safe_number = number.replace('/', '-').replace(' ', '_')
    return f'{prefix}_{safe_number}.pdf'
