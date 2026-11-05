"""What a file-backed column keeps, and the address a reader is handed.

A row never stores the address a browser loads. It stores the **storage key**
the file was saved under — ``<organization_id>/<module>/<relative>``, the path
:meth:`CoreFileStorageAPI.save_for_org_async` returns — or, for a picture that lives
on somebody else's server (a product photo copied from a catalogue), that
absolute ``http(s)`` address. The address the client is given is built when
the row is read, from whichever backend answers today.

That is what makes the storage backend configuration: a stack that moves its
files to a bucket keeps its rows as they are, and ``FileStorageService``
serving ``/uploads/<key>`` reads through the backend the configuration names.
Storing the address instead pinned every row to the backend that wrote it.

The two functions are deliberately total and idempotent: a value that is
already an address (ours under ``/uploads/``, or a foreign ``http(s)`` one)
passes through :func:`served_url` untouched, and an address under
``/uploads/`` comes back as its key. A client may therefore post back what it
was shown.
"""

from __future__ import annotations

import hashlib
import re

#: The route that serves every stored file, owned and verified by the app
#: rather than by the storage backend (``app/api/uploads.py``).
UPLOAD_ROUTE_PREFIX = '/uploads/'

#: What a reference starts with when it is already an address rather than a
#: key: our own route, or a foreign server's absolute address.
_ADDRESS_PREFIXES = ('http://', 'https://', '/')

#: The extensions a cover leaf can carry: what the upload paths derive from the
#: validated MIME type (`_items_images._MIME_TO_EXT`, the recipe re-encoder),
#: plus ``jpeg``, which older uploads wrote.
_COVER_EXTENSIONS = frozenset({'jpg', 'jpeg', 'png', 'gif', 'webp'})


def served_url(reference: str | None) -> str | None:
    """The address a client loads for *reference*.

    A storage key becomes the app's own ``/uploads/<key>``, which the upload
    route serves through whatever backend is configured. An address — one of
    ours that was already built, a foreign ``http(s)`` one kept from somebody
    else's catalogue — is returned unchanged, so this can be applied twice
    without doubling the prefix.
    """
    if not reference:
        return reference
    if reference.startswith(_ADDRESS_PREFIXES):
        return reference
    return f'{UPLOAD_ROUTE_PREFIX}{reference}'


def stored_reference(value: str | None) -> str | None:
    """What a file-backed column keeps for *value*, an address or a key.

    A served address comes back as the key under it, so a form that posts the
    picture it was shown does not write the address back into the row. A
    foreign absolute address is not ours to rewrite and is kept as it is.
    """
    if value is None:
        return None
    if value.startswith(UPLOAD_ROUTE_PREFIX):
        return value[len(UPLOAD_ROUTE_PREFIX) :]
    return value


def cover_extension(reference: str | None) -> str | None:
    """The extension *reference* names, if it names one of our covers.

    A delete may not take a file-backed column at face value: the item and
    recipe forms write ``image_url``, so one row can name another row's
    picture — or a foreign address — and a delete that followed the value would
    remove an object the row does not own. What a delete keeps from the
    reference is therefore the extension alone; it rebuilds the key from the
    organization and the entity id it is serving, and the facade rebuilds the
    ``<org>/<module>/`` prefix. A foreign absolute address, and a tail that is
    not a cover extension, answer ``None``.
    """
    if not reference or reference.startswith(('http://', 'https://')):
        return None
    extension = reference.rsplit('.', 1)[-1].lower() if '.' in reference else ''
    return extension if extension in _COVER_EXTENSIONS else None


#: ``cover.<ext>`` as older uploads wrote it, or ``cover.<digest>.<ext>``.
_COVER_LEAF = re.compile(
    r'cover(?:\.[0-9a-f]{12})?\.(?:' + '|'.join(sorted(_COVER_EXTENSIONS)) + r')'
)


def cover_leaf(content: bytes, extension: str) -> str:
    """The file name a cover with these bytes is saved under.

    A fixed ``cover.<ext>`` made the address of a replaced picture the address
    of the old one, so a page that had shown the old picture kept showing it:
    the browser reuses an image it already holds for the same address. The
    name carries a digest of the bytes instead, so a different picture is a
    different address on every screen that shows it, and the same bytes saved
    twice stay one file. The name still starts ``cover.`` and ends in the
    extension, which is all the upload resolvers read.
    """
    return f'cover.{hashlib.sha256(content).hexdigest()[:12]}.{extension}'


def cover_leaf_of(reference: str | None) -> str | None:
    """The cover file name *reference* ends in, if it ends in one of ours.

    Like :func:`cover_extension`, this keeps only the tail of a column the
    forms can write: a delete rebuilds the key from the organization and the
    entity it is serving and adds this leaf, so a reference cannot pick
    another row's file. A foreign address, and a tail that is not a cover
    name, answer ``None``.
    """
    if not reference or reference.startswith(('http://', 'https://')):
        return None
    leaf = reference.rsplit('/', 1)[-1]
    return leaf if _COVER_LEAF.fullmatch(leaf) else None
