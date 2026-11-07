"""Magic-byte / file-signature validation for uploads.

Defends against content-type spoofing: validates the actual bytes of an
uploaded file rather than trusting the client-supplied ``Content-Type``
header or filename extension. A malicious ``evil.exe`` renamed to
``evil.png`` (with ``Content-Type: image/png``) is rejected because its
bytes do not begin with the PNG signature.

Usage::

    content = await file.read()
    validate_signature(content, file.content_type)  # raises HTTPException(400)
    # ... proceed to save / process content
"""

from app.core.exceptions import catalogue_refusal

# Magic-byte prefixes indexed by MIME type. Each tuple holds the acceptable
# leading bytes for that type. A file passes if its header startswith any
# entry in the tuple.
_SIGNATURES: dict[str, tuple[bytes, ...]] = {
    'image/png': (b'\x89PNG\r\n\x1a\n',),
    'image/jpeg': (b'\xff\xd8\xff',),
    'image/gif': (b'GIF87a', b'GIF89a'),
    'application/pdf': (b'%PDF',),
    # RIFF container (webp/wav/avi) — caller must refine for webp
    'image/webp': (b'RIFF',),
    # ZIP-based containers (xlsx, docx, zip, jar, apk, odt, etc.)
    'application/zip': (b'PK\x03\x04', b'PK\x05\x06', b'PK\x07\x08'),
    # Legacy MS Office (OLE2 Compound Document) — .xls, .doc, .ppt
    'application/vnd.ms-excel': (b'\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1',),
    'application/msword': (b'\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1',),
}

# OLE2-based MIME types. Like the ZIP family below, the magic bytes identify
# the container, not which Office format sits inside it — only an OLE2 parser
# tells .doc from .xls. Listing them keeps a declared .doc from being stored
# as the first OLE2 entry the sniffer happens to match.
# (No attachment accepts .doc — ``upload_validation.ATTACHMENT_CONTENT_TYPES``
# leaves it out. That is a product call, not a validator one.)
_OLE2_FAMILY_MIMES = frozenset(
    {
        'application/msword',
        'application/vnd.ms-excel',
    }
)

# MIME types that share the ZIP-container family. They all carry the PK magic
# bytes, so we normalise them to 'application/zip' for the signature lookup.
_ZIP_FAMILY_MIMES = frozenset(
    {
        'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',  # .xlsx
        'application/vnd.openxmlformats-officedocument.wordprocessingml.document',  # .docx
        'application/vnd.openxmlformats-officedocument.presentationml.presentation',  # .pptx
        'application/x-zip-compressed',
    }
)

# MIME types for which no reliable magic-byte signature exists (text formats).
# These are skipped — the caller's extension check remains the sole gate.
_NO_SIGNATURE_MIMES = frozenset(
    {
        'text/plain',
        'text/csv',
        'application/json',
        'application/xml',
        'text/xml',
        'image/svg+xml',  # XML text — relies on a separate sanitiser
    }
)


def _normalise_mime(declared_mime: str) -> str:
    """Map ZIP-family MIME types to the canonical 'application/zip' signature."""
    if declared_mime in _ZIP_FAMILY_MIMES:
        return 'application/zip'
    return declared_mime


def sniff_mime(content: bytes) -> str | None:
    """Return the MIME type implied by *content*'s magic bytes, or ``None``.

    ``None`` means "the bytes do not identify a type on their own": either the
    format carries no signature (text) or the signature is shared by a whole
    family (every OOXML file is a ZIP). Callers should fall back to a declared
    type only after :func:`validate_signature` has confirmed it matches.
    """
    if content.startswith(b'RIFF') and content[8:12] == b'WEBP':
        return 'image/webp'
    for mime, signatures in _SIGNATURES.items():
        if mime == 'image/webp':
            continue  # handled above: bare RIFF is not enough
        if any(content.startswith(sig) for sig in signatures):
            return mime
    return None


def resolve_mime(content: bytes, declared_mime: str) -> str:
    """Decide which MIME type to persist for *content*.

    Prefers what the bytes say over what the client claimed. Falls back to the
    declaration only where the bytes cannot be more specific — text formats,
    and ZIP-based containers where the declaration (``.xlsx`` vs ``.docx``)
    carries information the ``PK`` signature does not.

    Assumes :func:`validate_signature` has already passed, so the declaration
    is known to be consistent with the bytes rather than merely asserted.
    """
    sniffed = sniff_mime(content)
    if sniffed is None:
        return declared_mime
    if sniffed == 'application/zip' and declared_mime in _ZIP_FAMILY_MIMES:
        return declared_mime
    if sniffed in _OLE2_FAMILY_MIMES and declared_mime in _OLE2_FAMILY_MIMES:
        return declared_mime
    return sniffed


def validate_signature(content: bytes, declared_mime: str) -> None:
    """Raise ``HTTPException(400)`` if *content* bytes do not match *declared_mime*.

    For MIME types without a reliable signature (text/csv, text/plain,
    image/svg+xml, application/json), the check is skipped — those rely on
    extension validation and downstream parsers / sanitisers.

    Args:
        content: The full file bytes (already read into memory).
        declared_mime: The MIME type the client declared (``file.content_type``).
    """
    if not declared_mime:
        raise catalogue_refusal('file_content_type_missing')

    if declared_mime in _NO_SIGNATURE_MIMES:
        return  # no signature to verify — extension check handles these

    effective_mime = _normalise_mime(declared_mime)
    signatures = _SIGNATURES.get(effective_mime)
    if signatures is None:
        # Unknown MIME — be conservative and reject rather than accept blindly.
        raise catalogue_refusal('file_type_not_allowed')

    if not content:
        raise catalogue_refusal('file_empty')

    if not any(content.startswith(sig) for sig in signatures):
        raise catalogue_refusal('file_signature_mismatch')

    # Special case: WEBP is a RIFF container — must also carry 'WEBP' at offset 8.
    if declared_mime == 'image/webp' and content[8:12] != b'WEBP':
        raise catalogue_refusal('file_not_webp')
