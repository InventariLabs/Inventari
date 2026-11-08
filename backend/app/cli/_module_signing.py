"""Package signing and verification for community module installs.

The trust model (ADR-019) is certification, and the signature is what
makes "certified" checkable instead of claimable: the package author
signs a digest of the package content with an Ed25519 key, and the
installer verifies that signature against keys the deployment trusts.

- The digest covers module.yaml and every file of the declared
  components, walked in a stable order, so any byte a stranger touches
  breaks the signature. The signature file itself (``module.sig``) is
  outside the digest for the obvious reason.
- The signed payload binds the digest to the module's name and version,
  so a signature made for one package cannot be replayed on another.
- ``module.sig`` names its format, and the payload's first line names it
  too: the file walk, the digest framing and the payload text together
  are format 1. Changing any of them is a new format with a number of its
  own, and the verifier keeps reading format 1 — signatures already in
  the field were made with it, and nothing else can tell them apart from
  a package modified after signing.
- Trusted keys come from ``MODULE_SIGNING_PUBLIC_KEYS`` — entries
  separated by commas or newlines, each ``key_id=<base64 public key>``
  or a bare base64 key. Nothing configured means nothing is trusted:
  every install is unsigned and needs the explicit switch.

Verification never mutates anything; the installer decides what an
unverified or unsigned package means for the flow.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

from app.config import settings
from app.core.logging import get_logger
from app.core.operator_error import OperatorError

if TYPE_CHECKING:
    from ._module_meta import ModuleYaml

logger = get_logger(__name__)

SIGNATURE_FILE = 'module.sig'
SUPPORTED_ALGORITHM = 'ed25519'
# The format ``sign_module`` writes. A later one is added beside format 1,
# never in its place: ``verify_module_signature`` then picks the payload
# by the number it reads, and format 1 keeps its own walk even if the
# installer's copy changes (``package_walk`` feeds both today).
SIGNATURE_FORMAT = 1

# Formats the safety scan cannot read but the runtime can execute:
# sourceless bytecode loads through the sourceless file loader, native
# extensions through the extension loader, and the OS maps the raw
# libraries on request. Nothing a module legitimately ships lives in
# these — code arrives as .py source, the only thing the scan can vouch
# for.
UNREADABLE_EXECUTABLE_SUFFIXES = frozenset(
    {'.pyc', '.pyo', '.so', '.pyd', '.dll', '.dylib'}
)


@dataclass(frozen=True)
class SignatureVerification:
    ok: bool
    key_id: str | None = None
    reason: str | None = None
    outcome: str = 'invalid'
    missing_trusted_keys: bool = False
    """'verified', 'unsigned' (no signature file at all) or 'invalid'.

    The installer may accept an *unsigned* package behind an explicit
    switch — nobody vouched for it, and the operator takes that risk
    knowingly. An *invalid* result (tampered content, untrusted key,
    unreadable signature) is evidence of a problem, not the absence of
    one, and no switch accepts it.

    ``missing_trusted_keys`` marks the one invalid outcome that is the
    deployment's fault rather than the package's: the package is signed,
    the signature may well be perfect, and this installation has no key
    to check it against. The remedy belongs to the operator — add the
    publisher's key — not to the publisher, who has nothing to re-sign."""


def packaged_files(source_dir: Path, meta: ModuleYaml) -> list[Path]:
    """The exact file set a package consists of, in stable order.

    One walk serving both readers of a package: the digest hashes this
    list and the installer copies this list, so what was signed is — file
    for file — what gets installed. Two walks with two policies was the
    hole: ``rglob`` never descended into a symlinked directory while
    ``copytree`` cheerfully expanded it, and ``__pycache__`` was hashed
    out but copied in, so a stale bytecode cache could stand in for the
    signed source.

    The walk refuses symlinks outright (a package containing one is not a
    self-contained package and cannot be signed meaningfully), refuses
    files whose format the runtime executes while the safety scan cannot
    read it — sourceless bytecode and native binaries, which would
    otherwise ride in behind a scan report that is true only of the
    source files — skips ``__pycache__`` bytecode, and drops every
    ``tests/`` directory on **both** halves — the author's workbench does
    not ship, and hashing what will not install would let a signature
    vouch for files the running system never sees. ``module.yaml`` is
    hashed for identity but is not itself installed — its identity fields
    land in ``manifest.json`` through the metadata merge.

    The frontend half used to keep its tests, on the grounds that a
    frontend test cannot run by being copied: nothing in the bundle
    imports it. True of the bundle, and beside the point — vitest has no
    ``include``, so it collects ``**/*.{test,spec}.*`` from the whole
    tree, and a stranger's test file ran in node, with the file system,
    for anyone who typed ``npm run test:run`` after installing.
    """
    return package_walk(source_dir, meta)[0]


def package_walk(source_dir: Path, meta: ModuleYaml) -> tuple[list[Path], list[Path]]:
    """``(shipped, dropped)`` — the package, and what the walk left out.

    The second list is why this exists: dropping the author's tests is a
    decision the installer is entitled to make, but making it in silence
    hands back a tree nobody asked for. A module whose fixtures or
    vendored library sit in a directory named ``tests`` installs short of
    what was sent, and without this list the author finds out from a
    runtime error and the certifier from an unexplained hole.
    """
    files: list[Path] = [source_dir / 'module.yaml']
    dropped: list[Path] = []
    for component in ('backend', 'frontend'):
        if not meta['components'].get(component, True):
            continue
        root = source_dir / component
        if not root.exists():
            continue
        for path in sorted(root.rglob('*')):
            rel = path.relative_to(source_dir)
            if path.is_symlink():
                raise OperatorError(
                    f'package contains a symlink ({rel.as_posix()}) — '
                    'symlinks cannot be signed or shipped'
                )
            if not path.is_file() or '__pycache__' in rel.parts:
                continue
            if 'tests' in path.relative_to(root).parts:
                dropped.append(path)
                continue
            if path.suffix.lower() in UNREADABLE_EXECUTABLE_SUFFIXES:
                raise OperatorError(
                    'package contains executable code the safety scanner '
                    f'cannot read ({rel.as_posix()}) — bytecode and native '
                    'binaries cannot be signed or shipped'
                )
            files.append(path)
    return files, dropped


def module_tree_digest(source_dir: Path, meta: ModuleYaml) -> str:
    """sha256 over module.yaml and every declared component file (format 1).

    Files are hashed in the order ``package_walk`` returns them, each as
    the UTF-8 POSIX relative path, a NUL byte, the length as 8 bytes
    big-endian, the bytes themselves and a NUL byte, so the digest cannot
    be rearranged without changing.
    """
    hasher = hashlib.sha256()
    files = packaged_files(source_dir, meta)
    for path in files:
        rel = path.relative_to(source_dir).as_posix()
        data = path.read_bytes()
        hasher.update(rel.encode('utf-8'))
        hasher.update(b'\0')
        hasher.update(len(data).to_bytes(8, 'big'))
        hasher.update(data)
        hasher.update(b'\0')
    return hasher.hexdigest()


def signed_payload(meta: ModuleYaml, digest: str) -> bytes:
    """Bind the content digest to this module's identity (format 1)."""
    return (
        'inventari-community-module/1\n'
        f'name: {meta["name"]}\n'
        f'version: {meta["version"]}\n'
        f'sha256: {digest}\n'
    ).encode()


def load_private_key(path: Path) -> Ed25519PrivateKey:
    """Read a base64 raw Ed25519 private key from *path*."""
    raw = base64.b64decode(path.read_text().strip())
    return Ed25519PrivateKey.from_private_bytes(raw)


def sign_module(
    source_dir: Path, meta: ModuleYaml, private_key_path: Path, key_id: str
) -> Path:
    """Sign the package in place and return the signature file path."""
    digest = module_tree_digest(source_dir, meta)
    signature = load_private_key(private_key_path).sign(signed_payload(meta, digest))
    sig_path = source_dir / SIGNATURE_FILE
    sig_path.write_text(
        json.dumps(
            {
                'format': SIGNATURE_FORMAT,
                'algorithm': SUPPORTED_ALGORITHM,
                'key_id': key_id,
                'signature': base64.b64encode(signature).decode('ascii'),
            },
            indent=2,
        )
        + '\n',
        encoding='utf-8',
    )
    return sig_path


def _trusted_keys() -> dict[str, Ed25519PublicKey]:
    """The keys this deployment trusts, by id."""
    raw = (settings.MODULE_SIGNING_PUBLIC_KEYS or '').strip()
    keys: dict[str, Ed25519PublicKey] = {}
    if not raw:
        return keys
    for entry in re.split(r'[,\n]+', raw):
        entry = entry.strip()
        if not entry:
            continue
        key_id, _, b64 = (part.strip() for part in entry.partition('='))
        if not key_id or not b64:
            # A key without an id is not trusted: a signature names the key it
            # was made with, and an id this installation made up would never
            # match it. A bare key also carries its own '=' — the padding of a
            # 32-byte Ed25519 key — so it reads as an id with no key behind it;
            # the warning says what is missing rather than call the key
            # invalid base64.
            logger.warning(
                '[module-signing] a MODULE_SIGNING_PUBLIC_KEYS entry has no key '
                'id — list it as <key_id>=<base64 public key>, with the id the '
                'publisher signs under; skipped'
            )
            continue
        try:
            keys[key_id] = Ed25519PublicKey.from_public_bytes(
                base64.b64decode(b64.strip())
            )
        except (binascii.Error, ValueError) as exc:
            logger.warning(
                '[module-signing] trusted key %r is not valid base64 (%s) — skipped',
                key_id,
                exc,
            )
    return keys


def verify_module_signature(
    source_dir: Path, meta: ModuleYaml, signature_file: Path | None = None
) -> SignatureVerification:
    """Verify the package signature against the deployment's trusted keys.

    Never mutates anything and never raises for a bad package — the
    refusal is the installer's decision, made with the reason in hand.
    """
    sig_path = signature_file or source_dir / SIGNATURE_FILE
    if not sig_path.exists():
        return SignatureVerification(
            ok=False, reason='no signature file found', outcome='unsigned'
        )

    try:
        data = json.loads(sig_path.read_text(encoding='utf-8'))
    except (OSError, ValueError) as exc:  # JSONDecodeError, UnicodeDecodeError
        return SignatureVerification(
            ok=False,
            reason=f'signature file is unreadable: {exc}',
            outcome='invalid',
        )
    if not isinstance(data, dict):
        # Valid JSON of another shape — an array, a string — has no keys to
        # read below, and an AttributeError there is a traceback, not a refusal.
        return SignatureVerification(
            ok=False,
            reason='signature file is unreadable: its JSON is not an object',
            outcome='invalid',
        )

    if data.get('format') != SIGNATURE_FORMAT:
        # No format at all is a signature from before formats existed, so the
        # way forward is re-signing; a number this installation does not know
        # comes from a newer Inventari.
        hint = (
            'it predates signature formats; sign the module again'
            if data.get('format') is None
            else 'a newer Inventari may have signed it'
        )
        return SignatureVerification(
            ok=False,
            reason=f'unsupported signature format {data.get("format")!r} — this '
            f'installation reads format {SIGNATURE_FORMAT}; {hint}',
            outcome='invalid',
        )

    if data.get('algorithm') != SUPPORTED_ALGORITHM:
        return SignatureVerification(
            ok=False,
            reason=f'unsupported signature algorithm {data.get("algorithm")!r}',
            outcome='invalid',
        )

    keys = _trusted_keys()
    if not keys:
        return SignatureVerification(
            ok=False,
            reason='no trusted signing keys are configured '
            '(MODULE_SIGNING_PUBLIC_KEYS)',
            outcome='invalid',
            missing_trusted_keys=True,
        )

    key_id = data.get('key_id')
    if key_id is not None and key_id not in keys:
        return SignatureVerification(
            ok=False,
            reason=f'signing key {key_id!r} is not trusted',
            outcome='invalid',
        )
    candidates = {key_id: keys[key_id]} if key_id is not None else keys

    try:
        signature = base64.b64decode(data.get('signature') or '', validate=True)
    except (binascii.Error, ValueError):
        return SignatureVerification(
            ok=False, reason='signature field is not valid base64', outcome='invalid'
        )

    try:
        payload = signed_payload(meta, module_tree_digest(source_dir, meta))
    except ValueError as exc:
        # The walk refuses packages it cannot vouch for (symlinks,
        # executable formats the scanner cannot read); such a package has
        # no well-defined, scannable content to verify against.
        return SignatureVerification(ok=False, reason=str(exc), outcome='invalid')
    for candidate_id, public_key in candidates.items():
        try:
            public_key.verify(signature, payload)
            return SignatureVerification(
                ok=True, key_id=candidate_id, outcome='verified'
            )
        except InvalidSignature:
            continue

    # A failed check cannot tell a changed package from a different key: the
    # same bytes fail both ways. Saying "modified after signing" alone sent an
    # operator whose installation lists another key under the signer's id
    # hunting for a tampering that never happened.
    if key_id is not None:
        reason = (
            f'signature does not verify with the key this installation trusts '
            f'as {key_id!r} — the package was modified after signing, or it was '
            f'signed with a different key under that id'
        )
    else:
        reason = (
            'signature matches none of the trusted keys — the package was '
            'modified after signing, or its signer is not one this '
            'installation trusts'
        )
    return SignatureVerification(ok=False, reason=reason, outcome='invalid')
