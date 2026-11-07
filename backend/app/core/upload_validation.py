"""What an upload may be, asked once.

Two halves. The first is the import-sheet gate: extension, size, and the
decompressed size of a spreadsheet, for the endpoints that read files into
pandas. The second is the attachment policy below.

Two attachment services used to answer the same question apart: item
attachments (10 MB, their own MIME list, the extension read off the
uploaded filename) and equipment's (20 MB, a list of its own, the
extension read off the validated type). The limits differ on purpose — a
warranty scan is not a product photo — and whether the filename is gated
is each screen's own promise. The type list is not a per-screen call: both
read ``ATTACHMENT_CONTENT_TYPES``.
"""

from __future__ import annotations

import io
import os
import zipfile
from dataclasses import dataclass

from fastapi import HTTPException, UploadFile

from app.core.exceptions import ServiceRejectionError
from app.core.file_signature import resolve_mime, validate_signature
from app.i18n import Language
from app.i18n.service import get_current_lang

ALLOWED_IMPORT_EXTENSIONS = {'.csv', '.xlsx', '.xls'}
MAX_IMPORT_SIZE = 50 * 1024 * 1024  # 50 MB

# Ceiling on rows an import may carry. The byte limit alone does not bound the
# work: a small file can hold hundreds of thousands of rows, and each one costs
# lookups and inserts inside a single request.
MAX_IMPORT_ROWS = 10_000

# Read in slices so an oversized upload is refused at the moment it crosses
# the limit, instead of after the whole thing sits in memory.
_READ_CHUNK_SIZE = 64 * 1024

# Ceiling on what a ZIP-based import (xlsx) may expand to. Magic-byte checks
# only prove the file starts with ``PK``, so a few hundred kilobytes can
# still unpack into gigabytes and take the process down inside pandas.
# Real spreadsheets land orders of magnitude below this.
MAX_DECOMPRESSED_IMPORT_SIZE = 250 * 1024 * 1024  # 250 MB

_ZIP_BASED_EXTENSIONS = {'.xlsx'}

# Extension → canonical MIME for magic-byte validation.
# .csv has no reliable signature (text) and is skipped in validate_signature.
_EXT_TO_MIME = {
    '.xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    '.xls': 'application/vnd.ms-excel',
    '.csv': 'text/csv',
}


def validate_import_file(file: UploadFile, lang: Language | None = None) -> None:
    lang = lang or get_current_lang()
    if not file.filename:
        raise ServiceRejectionError('file_type_not_allowed')
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in ALLOWED_IMPORT_EXTENSIONS:
        raise ServiceRejectionError(
            'file_type_not_allowed_list',
            allowed=', '.join(sorted(ALLOWED_IMPORT_EXTENSIONS)),
        )


def format_size_limit(limit: int) -> str:
    """Bytes, said the way a refusal speaks: one unit, no decimals."""
    if limit >= 1024 * 1024:
        return f'{limit / (1024 * 1024):g} MB'
    if limit >= 1024:
        return f'{limit / 1024:g} KB'
    return f'{limit} B'


async def read_capped_upload(
    file: UploadFile, lang: Language | None = None, limit: int = MAX_IMPORT_SIZE
) -> bytes:
    """Copy an upload into memory, stopping the moment it passes *limit*.

    For endpoints that accept a format outside ``ALLOWED_IMPORT_EXTENSIONS``
    (JSON, say) and would otherwise call ``file.read()`` — which pulls the
    whole body into memory whatever its size.

    **What this bounds, and what it does not.** By the time a route is
    called, Starlette has already parsed the multipart body into a spooled
    temporary file: the bytes have been received. This caps the *copy* of
    them that reaches the process's memory, so a 30 MB upload costs 5 MB of
    RAM instead of 30 — measured, and the reason it exists. It is not an
    admission control: what bounds the request on the way in is
    ``MAX_REQUEST_BODY_SIZE`` in ``BodySizeLimitMiddleware``, which refuses a
    declared oversize without reading a byte and cuts a chunked one while it
    arrives. A per-file limit above that ceiling can never be reached, so
    each caller's limit belongs well below it.
    """
    return await _read_capped(file, limit, lang or get_current_lang())


async def _read_capped(file: UploadFile, limit: int, lang: Language) -> bytes:
    """Copy *file* into memory, stopping the moment it exceeds *limit* bytes.

    The stop is on the copy, not on the network read — see
    ``read_capped_upload``.
    """
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await file.read(_READ_CHUNK_SIZE)
        if not chunk:
            break
        total += len(chunk)
        if total > limit:
            raise ServiceRejectionError('file_too_large')
        chunks.append(chunk)
    return b''.join(chunks)


def _decompressed_size_exceeds(content: bytes, limit: int) -> bool:
    """True when the archive unpacks to more than *limit* bytes.

    The per-entry sizes in the central directory are attacker-controlled, so
    they are used only as a cheap early exit; the authoritative answer comes
    from decompressing with a running counter, which stops at the limit
    rather than at the end of the stream.
    """
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            entries = archive.infolist()
            if sum(max(entry.file_size, 0) for entry in entries) > limit:
                return True

            total = 0
            for entry in entries:
                with archive.open(entry) as stream:
                    while True:
                        chunk = stream.read(_READ_CHUNK_SIZE)
                        if not chunk:
                            break
                        total += len(chunk)
                        if total > limit:
                            return True
    except (zipfile.BadZipFile, OSError, RuntimeError, EOFError):
        # Not a readable archive — the signature check already ran, and the
        # parser downstream reports a malformed file better than we can.
        return False
    return False


async def read_import_file(file: UploadFile, lang: Language | None = None) -> bytes:
    lang = lang or get_current_lang()
    validate_import_file(file, lang)
    content = await _read_capped(file, MAX_IMPORT_SIZE, lang)
    # Verify magic bytes match the declared extension.
    ext = os.path.splitext(file.filename or '')[1].lower()
    mime = _EXT_TO_MIME.get(ext)
    if mime is not None:
        validate_signature(content, mime)
    if ext in _ZIP_BASED_EXTENSIONS and _decompressed_size_exceeds(
        content, MAX_DECOMPRESSED_IMPORT_SIZE
    ):
        raise ServiceRejectionError('file_too_large')
    return content


class UploadRejectedError(ValueError):
    """An attachment upload failed validation. Routers map subclasses onto
    HTTP codes."""


class FileTypeNotAllowedError(UploadRejectedError):
    """Extension, declared type, or actual bytes are not an accepted type."""


class FileSignatureMismatchError(FileTypeNotAllowedError):
    """Declared Content-Type does not match the file's magic bytes.

    A subclass of :class:`FileTypeNotAllowedError` so service-level callers
    keep catching one family, while routers can map it to 400 (the bytes are
    inconsistent with the claim) instead of 415 (the type itself is refused).
    """


class FileTooLargeError(UploadRejectedError):
    """Upload exceeds the policy's size limit."""


#: What an attachment may be, wherever one is filed — an item's papers or
#: an equipment record's. Two copies of this list drifted apart once, so a
#: caller narrows or widens it in its own code, where the difference shows.
#:
#: No ``.doc`` (``application/msword``), and by decision rather than for
#: want of a check: ``file_signature`` knows the OLE2 header an ``.xls``
#: passes with, and a ``.doc`` carries the same one. ``.docx`` is the Word
#: format to use.
ATTACHMENT_CONTENT_TYPES: frozenset[str] = frozenset(
    {
        'image/jpeg',
        'image/png',
        'image/gif',
        'image/webp',
        'application/pdf',
        'text/plain',
        'application/zip',
        'application/x-zip-compressed',
        'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        'application/vnd.ms-excel',
        'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    }
)

#: Extension per validated content type — never from the filename, which is
#: whatever the uploader typed. Only the storage provider's path check stood
#: behind that, and one check is not a policy.
CONTENT_TYPE_TO_EXT: dict[str, str] = {
    'application/pdf': 'pdf',
    'image/jpeg': 'jpg',
    'image/png': 'png',
    'image/gif': 'gif',
    'image/webp': 'webp',
    'application/msword': 'doc',
    'application/vnd.openxmlformats-officedocument.wordprocessingml.document': 'docx',
    'application/vnd.ms-excel': 'xls',
    'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': 'xlsx',
    'application/zip': 'zip',
    'application/x-zip-compressed': 'zip',
    'text/plain': 'txt',
}


@dataclass(frozen=True)
class UploadMessages:
    """What each refusal says, in the caller's own words and language.

    The policy decides *whether* to refuse; only the caller knows how its
    own screen phrases it — and one of them names a size the other does
    not have.
    """

    type_not_allowed: str
    too_large: str
    signature_mismatch: str


@dataclass(frozen=True)
class AcceptedUpload:
    """A file that passed. ``stored_type`` is what the bytes are, not what
    was claimed for them; ``extension`` is what to write it under."""

    stored_type: str
    extension: str


@dataclass(frozen=True)
class UploadPolicy:
    """One caller's limits: how big, which types, which filename extensions.

    ``extensions`` is optional. Where it is given, the name the uploader
    chose has to end in one of them — a second gate in front of the
    content-type list, not a replacement for it.
    """

    max_bytes: int
    content_types: frozenset[str]
    extensions: frozenset[str] | None = None

    def check(
        self,
        content: bytes,
        *,
        declared_type: str,
        messages: UploadMessages,
        filename: str | None = None,
    ) -> AcceptedUpload:
        """Accept the bytes, or raise the reason they are refused.

        The order is deliberate: the cheap refusals (extension, declared
        type, size) come before the signature is read, so a file of the
        wrong kind is turned away without being examined.
        """
        if self.extensions is not None:
            ext = os.path.splitext(os.path.basename(filename or ''))[1].lower()
            if ext not in self.extensions:
                raise FileTypeNotAllowedError(messages.type_not_allowed)

        if declared_type not in self.content_types:
            raise FileTypeNotAllowedError(messages.type_not_allowed)

        if len(content) > self.max_bytes:
            raise FileTooLargeError(messages.too_large)

        try:
            validate_signature(content, declared_type)
        except HTTPException as exc:
            # A signature mismatch is a rejected upload, not a transport
            # concern — the caller's router decides the status code.
            raise FileSignatureMismatchError(messages.signature_mismatch) from exc

        # Trust the bytes over the header: Content-Type is client-controlled,
        # and this value is later served back to browsers.
        stored_type = resolve_mime(content, declared_type)
        return AcceptedUpload(
            stored_type=stored_type,
            extension=CONTENT_TYPE_TO_EXT.get(stored_type, 'bin'),
        )
