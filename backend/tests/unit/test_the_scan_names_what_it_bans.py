"""The safety scan's lists say exactly what they ban and what they grant.

``FORBIDDEN_IMPORT_PREFIXES`` was matched with a bare ``startswith``, so
``socketserver`` read as ``socket`` and ``subprocess_tee`` as ``subprocess``,
while the capability map was already bounded by the dot. And
``CORE_EXEMPTIONS`` granted imports nobody made — ``printing`` held
``subprocess``, ``webhooks`` held ``socket`` — so a later such import in those
modules would have passed unseen. Every exemption now has to be one the scan
would refuse without it.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.core._registry_class import REPO_MODULES_ROOT
from app.core.module_safety import CORE_EXEMPTIONS
from app.core.module_safety_analysis import SafetyFinding, analyze_module_safety


def _community_module(tmp_path: Path, source: str) -> Path:
    module = tmp_path / 'demo_mod'
    module.mkdir()
    (module / 'manifest.json').write_text(
        json.dumps(
            {
                'name': 'demo_mod',
                'version': '0.1.0',
                'module_type': 'community',
                'capabilities': ['database'],
            }
        ),
        encoding='utf-8',
    )
    (module / 'service.py').write_text(source, encoding='utf-8')
    return module


def _forbidden(findings: list[SafetyFinding]) -> list[str]:
    return [f.subject for f in findings if f.kind == 'forbidden_import']


@pytest.mark.unit
class TestABanIsAModuleNotAPrefix:
    @pytest.mark.parametrize(
        'source',
        [
            'import socketserver\n',
            'import subprocess_tee\n',
            'from socketserver import X\n',
        ],
    )
    def test_a_name_that_only_starts_like_a_banned_one_is_not_banned(
        self, tmp_path, source
    ):
        module = _community_module(tmp_path, source)

        assert _forbidden(analyze_module_safety(module, [], use_cache=False)) == []

    @pytest.mark.parametrize(
        ('source', 'subject'),
        [
            ('import socket\n', 'socket'),
            ('import urllib.request\n', 'urllib.request'),
            ('from subprocess import run\n', 'subprocess'),
            ('import subprocess.run\n', 'subprocess.run'),
        ],
    )
    def test_the_banned_module_and_what_is_inside_it_stay_banned(
        self, tmp_path, source, subject
    ):
        module = _community_module(tmp_path, source)

        assert _forbidden(analyze_module_safety(module, [], use_cache=False)) == [
            subject
        ]


def _declared_capabilities(module_name: str) -> list[str]:
    manifest = json.loads(
        (REPO_MODULES_ROOT / module_name / 'manifest.json').read_text(encoding='utf-8')
    )
    return [str(c) for c in manifest.get('capabilities', [])]


@pytest.mark.unit
@pytest.mark.parametrize(
    ('module_name', 'granted'),
    [(name, entry) for name, entries in CORE_EXEMPTIONS.items() for entry in entries],
)
def test_every_exemption_grants_an_import_the_scan_would_refuse(
    monkeypatch: pytest.MonkeyPatch, module_name: str, granted: str
) -> None:
    rest = [entry for entry in CORE_EXEMPTIONS[module_name] if entry != granted]
    monkeypatch.setitem(CORE_EXEMPTIONS, module_name, rest)

    findings = analyze_module_safety(
        REPO_MODULES_ROOT / module_name,
        _declared_capabilities(module_name),
        use_cache=False,
    )

    assert any(
        f.subject == granted or f.subject.startswith(granted + '.') for f in findings
    ), f'{module_name} holds an exemption for {granted} that grants nothing'
