"""Licence classification for declared dependencies.

This answers "what did we install". It was once unguarded: a GPL package sat
in ``pyproject.toml`` as a direct runtime dependency for months, because
nothing read the licences of what the manifests declare.

Scope is what actually ships. Backend: the runtime set from
``uv export --no-dev`` intersected with installed distribution metadata.
Frontend: the production tree from ``npm ls --omit=dev``. Dev dependencies are
never distributed, so they must not be able to block a release.

Multiple licences on one package are read as alternatives ("MIT or GPL" means
we may take MIT), which is what a list of PyPI classifiers and an SPDX ``OR``
both mean. An SPDX ``AND`` is the opposite and every part has to pass.
"""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

# Permissive enough to ship inside a closed distribution.
ALLOWED = {
    '0BSD',
    'Apache-2.0',
    'BSD',
    'BSD-2-Clause',
    'BSD-3-Clause',
    'BlueOak-1.0.0',
    'CC0-1.0',
    'ISC',
    'MIT',
    'MIT-0',
    'MIT-CMU',
    'MPL-2.0',
    'PSF-2.0',
    'Python-2.0',
    'Unlicense',
    'W3C',
    'WTFPL',
    'Zlib',
}

# Copyleft or source-available: incompatible with a commercial licence, or not
# open source at all. A hit here fails the gate.
BLOCKED = {
    'AGPL-3.0',
    'BUSL-1.1',
    'CDDL-1.0',
    'Commons-Clause',
    'Elastic-2.0',
    'EUPL-1.2',
    'GPL-2.0',
    'GPL-3.0',
    'RSAL-2.0',
    'SSPL-1.0',
}

# Usable, but only under conditions somebody has to have decided on: dynamic
# linking for LGPL, attribution for CC-BY, per-file copyleft for MPL-1.1.
REVIEW = {
    'CC-BY-4.0',
    'LGPL',  # version left unstated by the metadata
    'LGPL-2.1',
    'LGPL-3.0',
    'MPL-1.1',
    'Proprietary',
    'UNKNOWN',
}

# Packages whose metadata cannot be trusted at face value. Every entry needs a
# reason — a bare name here is an unexplained hole in the gate.
EXCEPTIONS: dict[str, tuple[str, str]] = {
    'qrcode': (
        'BSD-3-Clause',
        'ships a bogus "License :: Other/Proprietary License" classifier next '
        'to "BSD License"; upstream LICENSE is BSD-3-Clause',
    ),
    'pyphen': (
        'MPL-1.1',
        'tri-licensed GPL-2.0+/LGPL-2.1+/MPL-1.1 — we take MPL-1.1, so a naive '
        'substring match on "GPL" must not read this as a blocker',
    ),
    'caniuse-lite': (
        'CC-BY-4.0',
        'browser-support data consumed at build time, never shipped as code; '
        'needs attribution, not a block',
    ),
}

# Ordered longest-first so "LGPLv2+" is not read as "GPL" and "MPL 1.1" is not
# read as "MPL-2.0". First match wins.
_ALIASES: tuple[tuple[str, str], ...] = (
    ('AFFERO GENERAL PUBLIC', 'AGPL-3.0'),
    ('AGPL', 'AGPL-3.0'),
    ('LESSER GENERAL PUBLIC LICENSE V3', 'LGPL-3.0'),
    ('LESSER GENERAL PUBLIC LICENSE V2', 'LGPL-2.1'),
    ('LGPLV3', 'LGPL-3.0'),
    ('LGPL-3', 'LGPL-3.0'),
    ('LGPLV2', 'LGPL-2.1'),
    ('LGPL-2', 'LGPL-2.1'),
    # Version left unstated (psycopg2 says only "LGPL with exceptions") — do
    # not invent one.
    ('LESSER GENERAL PUBLIC', 'LGPL'),
    ('LGPL', 'LGPL'),
    ('GENERAL PUBLIC LICENSE V3', 'GPL-3.0'),
    ('GPLV3', 'GPL-3.0'),
    ('GPL-3', 'GPL-3.0'),
    ('GENERAL PUBLIC LICENSE V2', 'GPL-2.0'),
    ('GPLV2', 'GPL-2.0'),
    ('GPL-2', 'GPL-2.0'),
    ('GENERAL PUBLIC', 'GPL-2.0'),
    ('GPL', 'GPL-2.0'),
    ('MOZILLA PUBLIC LICENSE 1.1', 'MPL-1.1'),
    ('MPL 1.1', 'MPL-1.1'),
    ('MPL-1.1', 'MPL-1.1'),
    ('MOZILLA', 'MPL-2.0'),
    ('MPL', 'MPL-2.0'),
    ('SERVER SIDE PUBLIC', 'SSPL-1.0'),
    ('SSPL', 'SSPL-1.0'),
    ('REDIS SOURCE AVAILABLE', 'RSAL-2.0'),
    ('RSAL', 'RSAL-2.0'),
    ('BUSINESS SOURCE', 'BUSL-1.1'),
    ('BUSL', 'BUSL-1.1'),
    ('COMMONS CLAUSE', 'Commons-Clause'),
    ('ELASTIC', 'Elastic-2.0'),
    ('EUPL', 'EUPL-1.2'),
    ('CDDL', 'CDDL-1.0'),
    ('MIT-CMU', 'MIT-CMU'),
    ('CMU', 'MIT-CMU'),
    # MIT-0 (cffi) drops the attribution clause; reading it as plain MIT would
    # state a stricter licence than the one the package ships under.
    ('MIT-0', 'MIT-0'),
    ('MIT', 'MIT'),
    ('APACHE', 'Apache-2.0'),
    ('ISC', 'ISC'),
    ('BSD-3', 'BSD-3-Clause'),
    ('BSD 3', 'BSD-3-Clause'),
    ('BSD-2', 'BSD-2-Clause'),
    ('BSD 2', 'BSD-2-Clause'),
    ('0BSD', '0BSD'),
    ('BSD', 'BSD'),
    ('PYTHON SOFTWARE FOUNDATION', 'PSF-2.0'),
    ('PSF', 'PSF-2.0'),
    ('PYTHON-2.0', 'Python-2.0'),
    ('BLUEOAK', 'BlueOak-1.0.0'),
    ('CC0', 'CC0-1.0'),
    ('CC-BY', 'CC-BY-4.0'),
    ('UNLICENSE', 'Unlicense'),
    ('W3C', 'W3C'),
    ('WTFPL', 'WTFPL'),
    ('ZLIB', 'Zlib'),
    ('PROPRIETARY', 'Proprietary'),
)

_SPLIT_RE = re.compile(r'\s+OR\s+|\s*[,;/|]\s*', re.IGNORECASE)
_AND_RE = re.compile(r'\s+AND\s+', re.IGNORECASE)


@dataclass(frozen=True)
class Dependency:
    """One shipped dependency and the verdict on its licence."""

    name: str
    version: str
    licence: str
    verdict: str  # 'allowed' | 'review' | 'blocked'
    ecosystem: str  # 'backend' | 'frontend' | 'image' | 'system'
    raw: str = ''
    note: str = ''


@dataclass
class ScanResult:
    dependencies: list[Dependency] = field(default_factory=list)

    def by_verdict(self, verdict: str) -> list[Dependency]:
        return [d for d in self.dependencies if d.verdict == verdict]

    def by_ecosystem(self, ecosystem: str) -> list[Dependency]:
        return sorted(
            (d for d in self.dependencies if d.ecosystem == ecosystem),
            key=lambda d: d.name.lower(),
        )


def normalize_licence(raw: str) -> str:
    """Map a metadata licence string onto an SPDX-ish identifier."""
    text = raw.strip()
    if not text:
        return 'UNKNOWN'
    # Classifiers arrive as "License :: OSI Approved :: MIT License".
    if '::' in text:
        text = text.rsplit('::', 1)[-1]
    upper = text.upper()
    for needle, spdx in _ALIASES:
        if needle in upper:
            return spdx
    return 'UNKNOWN'


def _verdict_for(licence: str) -> str:
    if licence in ALLOWED:
        return 'allowed'
    if licence in BLOCKED:
        return 'blocked'
    if licence in REVIEW:
        return 'review'
    # Something nobody has classified yet. Blocking would break the build on
    # every newly-published licence name; passing it silently is how the last
    # gate missed a GPL package. So: a decision, from a human.
    return 'review'


def classify(licences: list[str], *, conjunctive: bool = False) -> str:
    """Return the verdict for a set of licence identifiers.

    Alternatives (the default) pass on the best option available; a conjunctive
    set has to satisfy every part.
    """
    if not licences:
        return 'review'
    verdicts = [_verdict_for(lic) for lic in licences]
    if conjunctive:
        if 'blocked' in verdicts:
            return 'blocked'
        return 'review' if 'review' in verdicts else 'allowed'
    if 'allowed' in verdicts:
        return 'allowed'
    return 'review' if 'review' in verdicts else 'blocked'


def split_expression(expression: str) -> tuple[list[str], bool]:
    """Split an SPDX expression into identifiers plus an is-conjunctive flag."""
    cleaned = expression.strip().strip('()')
    conjunctive = bool(_AND_RE.search(cleaned))
    parts = _AND_RE.split(cleaned) if conjunctive else _SPLIT_RE.split(cleaned)
    return [normalize_licence(p) for p in parts if p.strip()], conjunctive


def _resolve(
    name: str, candidates: list[str], conjunctive: bool
) -> tuple[str, str, str]:
    """Return (licence, verdict, note), honouring the exception table."""
    override = EXCEPTIONS.get(name.lower())
    if override:
        licence, reason = override
        verdict = classify([licence])
        return licence, verdict, f'exception: {reason}'
    unique = list(dict.fromkeys(candidates)) or ['UNKNOWN']
    verdict = classify(unique, conjunctive=conjunctive)
    joiner = ' AND ' if conjunctive else ' OR '
    return joiner.join(unique), verdict, ''


def _run(cmd: list[str], cwd: Path) -> str:
    try:
        result = subprocess.run(
            cmd, cwd=cwd, capture_output=True, text=True, check=False, timeout=600
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise RuntimeError(f'could not run `{cmd[0]}`: {exc}') from exc
    if result.returncode != 0 and not result.stdout.strip():
        raise RuntimeError(f'`{" ".join(cmd)}` failed: {result.stderr.strip()[:400]}')
    return result.stdout


def runtime_backend_names(backend_dir: Path) -> set[str]:
    """Names of the backend packages that ship, from ``uv export --no-dev``."""
    out = _run(
        ['uv', 'export', '--no-dev', '--no-hashes', '--no-emit-project'], backend_dir
    )
    names: set[str] = set()
    for line in out.splitlines():
        line = line.strip()
        if not line or line.startswith(('#', '-')):
            continue
        match = re.match(r'^([A-Za-z0-9._-]+)', line)
        if match:
            names.add(match.group(1).lower().replace('_', '-'))
    return names


def collect_backend(backend_dir: Path) -> list[Dependency]:
    """Read licences of the installed distributions that ship at runtime."""
    import importlib.metadata as md

    shipped = runtime_backend_names(backend_dir)
    found: list[Dependency] = []
    seen: set[str] = set()

    for dist in md.distributions():
        name = (dist.metadata['Name'] or '').strip()
        key = name.lower().replace('_', '-')
        if not name or key in seen or (shipped and key not in shipped):
            continue
        seen.add(key)

        meta = dist.metadata
        expression = (meta.get('License-Expression') or '').strip()
        conjunctive = False
        if expression:
            candidates, conjunctive = split_expression(expression)
            raw = expression
        else:
            classifiers = [
                c for c in (meta.get_all('Classifier') or []) if c.startswith('License')
            ]
            free_text = (meta.get('License') or '').strip()
            # A whole licence body is sometimes pasted into the field; only the
            # first line can carry a name.
            free_text = free_text.splitlines()[0] if free_text else ''
            raw = ' | '.join(classifiers) or free_text
            candidates = [normalize_licence(c) for c in classifiers]
            if not candidates and free_text:
                candidates = [normalize_licence(free_text)]

        licence, verdict, note = _resolve(name, candidates, conjunctive)
        found.append(
            Dependency(
                name=name,
                version=dist.version or '?',
                licence=licence,
                verdict=verdict,
                ecosystem='backend',
                raw=raw,
                note=note,
            )
        )
    return found


def _package_licence(pkg_json: Path) -> tuple[list[str], bool, str]:
    try:
        data = json.loads(pkg_json.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError):
        return ['UNKNOWN'], False, ''
    declared = data.get('license') or data.get('licenses')
    if isinstance(declared, dict):
        declared = declared.get('type', '')
    if isinstance(declared, list):
        entries = [
            d.get('type', '') if isinstance(d, dict) else str(d) for d in declared
        ]
        return [normalize_licence(e) for e in entries], False, ' OR '.join(entries)
    if not declared:
        return ['UNKNOWN'], False, ''
    identifiers, conjunctive = split_expression(str(declared))
    return identifiers, conjunctive, str(declared)


def collect_frontend(frontend_dir: Path) -> list[Dependency]:
    """Read licences of the frontend production tree from ``npm ls``."""
    out = _run(['npm', 'ls', '--omit=dev', '--all', '--parseable'], frontend_dir)
    found: list[Dependency] = []
    # Keyed by name *and* version: npm legitimately installs two versions of
    # the same package at different depths, and both are shipped.
    seen: set[tuple[str, str]] = set()

    for line in out.splitlines():
        path = Path(line.strip())
        if not line.strip() or 'node_modules' not in path.parts:
            continue  # the first line is the project itself
        pkg_json = path / 'package.json'
        if not pkg_json.is_file():
            continue
        try:
            data = json.loads(pkg_json.read_text(encoding='utf-8'))
        except (OSError, json.JSONDecodeError):
            continue
        name = data.get('name') or path.name
        version = str(data.get('version', '?'))
        if (name, version) in seen:
            continue
        seen.add((name, version))

        candidates, conjunctive, raw = _package_licence(pkg_json)
        licence, verdict, note = _resolve(name, candidates, conjunctive)
        found.append(
            Dependency(
                name=name,
                version=version,
                licence=licence,
                verdict=verdict,
                ecosystem='frontend',
                raw=raw,
                note=note,
            )
        )
    return found
