"""Rendering side of the dependency licence gate.

The manual tables below carry what no manifest can: the system packages baked
into the backend image and the third-party images the stack pulls. Both are
redistributed with a self-hosted deployment, so a due-diligence request covers
them too — and neither shows up in ``uv export`` or ``npm ls``.
"""

from __future__ import annotations

from ._deps_licenses import Dependency, ScanResult

# Debian packages pulled into the backend image, and how the code reaches them.
SYSTEM_COMPONENTS: tuple[Dependency, ...] = (
    Dependency(
        name='libpango / libcairo / libgdk-pixbuf',
        version='distro',
        licence='LGPL-2.1',
        verdict='review',
        ecosystem='system',
        note='loaded by WeasyPrint through ctypes at runtime; dynamic linking '
        'against unmodified shared libraries, which LGPL permits',
    ),
    Dependency(
        name='age',
        version='distro',
        licence='BSD-3-Clause',
        verdict='allowed',
        ecosystem='system',
        note='the age-encryption CLI in the db-backup image; every database '
        'dump passes through it before it is written',
    ),
)

# Static assets under frontend/public that ship inside the frontend bundle.
# Every directory there needs an entry: check_licences_fresh.py lists the
# directory and refuses one the report does not cover, and refuses a row that
# names no directory. None of these has a manifest — the licence travels in
# the directory itself.
ASSET_COMPONENTS: tuple[Dependency, ...] = (
    Dependency(
        name='frontend/public/emoji',
        version='bundled',
        licence='MIT',
        verdict='allowed',
        ecosystem='asset',
        note='Fluent Emoji by Microsoft '
        '(https://github.com/microsoft/fluentui-emoji); the licence ships as '
        'frontend/public/emoji/LICENSE — Copyright (c) Microsoft Corporation',
    ),
    Dependency(
        name='frontend/public/fonts',
        version='bundled',
        licence='OFL-1.1',
        verdict='allowed',
        ecosystem='asset',
        note='Plus Jakarta Sans (https://github.com/tokotype/PlusJakartaSans); '
        'the licence ships as frontend/public/fonts/OFL.txt — Copyright 2020 '
        'The Plus Jakarta Sans Project Authors',
    ),
    Dependency(
        name='frontend/public/logos',
        version='bundled',
        licence='Trademark',
        verdict='review',
        ecosystem='asset',
        note='brand marks of the AI providers named by the file names (OpenAI, '
        'Google, Anthropic, Mistral AI, xAI, Groq and others) — trademarks of '
        'their respective owners, used only to name the provider in the AI '
        'connections screen',
    ),
)

# Images the stack pulls. Anything with a non-permissive licence has to be
# named here, because compose files are not scanned by anything else.
IMAGE_COMPONENTS: tuple[Dependency, ...] = (
    Dependency(
        name='postgres:17-alpine',
        version='17',
        licence='PostgreSQL',
        verdict='allowed',
        ecosystem='image',
        note='PostgreSQL Licence — permissive, BSD-style',
    ),
    Dependency(
        name='valkey/valkey:9.1.2-alpine',
        version='9.1.2',
        licence='BSD-3-Clause',
        verdict='allowed',
        ecosystem='image',
        note='the fork that stayed open source after Redis moved to RSALv2/SSPL',
    ),
    Dependency(
        name='caddy:2-alpine',
        version='2',
        licence='Apache-2.0',
        verdict='allowed',
        ecosystem='image',
    ),
    Dependency(
        name='edoburu/pgbouncer:v1.25.2-p0',
        version='1.25.2',
        licence='ISC',
        verdict='allowed',
        ecosystem='image',
        note='PgBouncer is ISC; the image wrapper is MIT',
    ),
    Dependency(
        name='rclone/rclone',
        version='1.75.1',
        licence='MIT',
        verdict='allowed',
        ecosystem='image',
        note='offsite copy of the encrypted backups, opt-in `offsite` profile',
    ),
    Dependency(
        name='axllent/mailpit:v1.31.4',
        version='1.31.4',
        licence='MIT',
        verdict='allowed',
        ecosystem='image',
        note="the demo stack's catch-all mail server, so a demo visitor can "
        'read what would have gone out; opt-in `demo` profile, never part of a '
        'production deployment',
    ),
    Dependency(
        name='mailhog/mailhog:latest',
        version='latest',
        licence='MIT',
        verdict='allowed',
        ecosystem='image',
        note='development only — never part of a production deployment',
    ),
    Dependency(
        name='grafana/k6:latest',
        version='latest',
        licence='AGPL-3.0',
        verdict='review',
        ecosystem='image',
        note='load-testing tool run on its own; not distributed with the '
        'product and nothing links against it',
    ),
    Dependency(
        name='grafana/grafana:latest',
        version='latest',
        licence='AGPL-3.0',
        verdict='review',
        ecosystem='image',
        note='load-test dashboards only; same reasoning as k6',
    ),
    Dependency(
        name='influxdb:1.13-alpine',
        version='1.13',
        licence='MIT',
        verdict='allowed',
        ecosystem='image',
        note='load-test metrics store only',
    ),
)

_HEADER = """# Third-party licences

Every component redistributed with Inventari, with the licence it ships under.
Generated — do not edit by hand. Run it from a checkout that has both
`backend/.venv` and `frontend/node_modules` installed:

```bash
cd backend && uv run python manage.py audit scan-dependencies --write
```

What keeps it true runs on this tree: the `licences-fresh` pre-commit hook
(installed by `make setup-hooks`) runs
`backend/scripts/check_licences_fresh.py` when a manifest, a lockfile, this
report or a bundled asset changes, and `make lint` runs the same check over
the whole tree. `.github/workflows/license-scan.yml` can still regenerate and
diff it, but only when someone starts it by hand — its pull-request trigger
is switched off to save runner minutes, so no CI run stands behind this file.

The backend container has no `npm`, so inside it the command only works with
`--skip-frontend` and the frontend section would come out empty.

Scope is what a deployment actually receives: backend runtime packages
(dev-dependencies excluded), the frontend production bundle, the system
packages inside the backend and backup images, the images the stack pulls,
and the static assets the frontend serves.
"""


def _table(rows: list[Dependency]) -> list[str]:
    lines = ['| Package | Version | Licence | Note |', '|---|---|---|---|']
    for dep in rows:
        note = dep.note.replace('|', '\\|') if dep.note else ''
        lines.append(f'| `{dep.name}` | {dep.version} | {dep.licence} | {note} |')
    return lines


def render_markdown(result: ScanResult) -> str:
    """Return the full THIRD_PARTY_LICENSES.md body."""
    backend = result.by_ecosystem('backend')
    frontend = result.by_ecosystem('frontend')
    sections = [_HEADER.rstrip(), '']

    sections.append(f'## Backend runtime ({len(backend)} packages)')
    sections.append('')
    sections.extend(_table(backend))
    sections.append('')

    sections.append(f'## Frontend production bundle ({len(frontend)} packages)')
    sections.append('')
    sections.extend(_table(frontend))
    sections.append('')

    sections.append('## Backend and backup images — system layer')
    sections.append('')
    sections.extend(_table(list(SYSTEM_COMPONENTS)))
    sections.append('')

    sections.append('## Container images')
    sections.append('')
    sections.extend(_table(list(IMAGE_COMPONENTS)))
    sections.append('')

    sections.append('## Bundled frontend assets')
    sections.append('')
    sections.extend(_table(list(ASSET_COMPONENTS)))
    sections.append('')

    sections.append('## Data')
    sections.append('')
    sections.append(
        'Open Food Facts product data is **not** bundled. The importer fetches '
        'it on request and the data is ODbL-1.0; a deployment that imports it '
        'takes on the share-alike obligation for the resulting database. See '
        '`NOTICE`.'
    )
    sections.append('')
    return '\n'.join(sections)


def summarize(result: ScanResult) -> dict[str, int]:
    return {
        'total': len(result.dependencies),
        'allowed': len(result.by_verdict('allowed')),
        'review': len(result.by_verdict('review')),
        'blocked': len(result.by_verdict('blocked')),
    }
