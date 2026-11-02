"""The scan-link format has exactly one source.

A QR on a label carries ``{base}/s/{code}`` — ``{base}/scan?code={code}``
before it, which still has to resolve — and ``extract_scan_code`` unwraps
both through ``scan_code_in``: the formats live in ``app/core/scan_links.py``
and nobody re-spells them. The printing module used
to keep its own copy without the trailing-slash guard, so its QR carried
``…//scan?code=`` where the core produced ``…/scan?code=`` — the printed code
and the scan parser stopped speaking the same language.
"""

from __future__ import annotations

from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[2]
APP_ROOT = BACKEND_ROOT / 'app'


def test_scan_url_format_has_one_source():
    offenders = [
        str(path.relative_to(BACKEND_ROOT))
        for path in sorted(APP_ROOT.rglob('*.py'))
        if path.name != 'scan_links.py' and 'scan?code=' in _read(path)
    ]
    assert offenders == [], (
        'The scan-link format must come from app.core.scan_links.scan_url() — '
        f're-spelled in: {offenders}'
    )


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding='utf-8')
    except UnicodeDecodeError:
        return ''
