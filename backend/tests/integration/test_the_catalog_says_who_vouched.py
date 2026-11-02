"""Who says this module is by whom.

``module.yaml`` carries the author and the licence, and the installer
merges them into the manifest the registry reads. Without that merge every
community module introduced itself to the store as the core team with an
empty description — so the merge stays. What it cannot do is make those
fields *true*: a package that writes its own author line is a package
vouching for itself.

The signature can. ``module_tree_digest`` hashes ``module.yaml`` along with
every shipped file, so a verified signature says the author and licence on
the card are exactly the ones the holder of that key published. The card
needs the difference, and the API is where it starts: the catalogue carries
the verification result next to the fields it does or does not stand
behind.
"""

from __future__ import annotations

import pytest

from app.api.modules import get_available_modules_list

pytestmark = pytest.mark.integration


def _module(modules, name: str):
    return next((m for m in modules if m.name == name), None)


def test_a_verified_install_names_the_key_that_signed_it(monkeypatch):
    monkeypatch.setattr(
        'app.core.module_tracking.load_module_tracking',
        lambda: {
            'printing': {
                'version': '1.0.0',
                'has_frontend': True,
                'signature_status': 'verified',
                'signature_key_id': 'publisher-1',
                'signature_verified_at': '2026-09-12T00:00:00Z',
            }
        },
    )

    printing = _module(get_available_modules_list(), 'printing')

    assert printing is not None
    assert printing.signature_status == 'verified'
    assert printing.signed_by == 'publisher-1'


def test_an_unsigned_install_says_so_and_names_nobody(monkeypatch):
    monkeypatch.setattr(
        'app.core.module_tracking.load_module_tracking',
        lambda: {
            'printing': {
                'version': '1.0.0',
                'has_frontend': True,
                'signature_status': 'unsigned',
                'signature_key_id': '',
            }
        },
    )

    printing = _module(get_available_modules_list(), 'printing')

    assert printing is not None
    assert printing.signature_status == 'unsigned'
    assert printing.signed_by is None


def test_a_module_from_the_tree_claims_no_signature_either_way():
    """Core modules are not installed packages: their code is in the
    repository, and a signature line about them would be theatre."""
    printing = _module(get_available_modules_list(), 'printing')

    assert printing is not None
    assert printing.signature_status is None
    assert printing.signed_by is None


def _fake_package_module(module_type: str):
    """A registry entry shaped like a package that shipped its own trust
    claim in manifest.json."""
    from types import SimpleNamespace

    return SimpleNamespace(
        metadata=SimpleNamespace(
            name='printing',
            display_name='Printing',
            description='',
            icon='printer',
            module_type=module_type,
            category='business',
            capabilities=[],
            requires=[],
            optional_requires=[],
            version='1.0.0',
            author='Some Vendor',
            license='MIT',
            homepage=None,
            is_trusted=False,
            is_reference=False,
            requires_api_key=False,
        )
    )


def test_a_package_cannot_crown_itself_official(monkeypatch):
    """module_type rides in from the package's own manifest.json, and
    nothing verified it. The store does not take a package's word for
    who stands behind it: an installed package reads as community, an
    official badge is something a signature chain would have to earn."""

    from app.api.modules import module_registry

    monkeypatch.setattr(
        module_registry,
        'get_all',
        lambda: [_fake_package_module('official')],
    )
    monkeypatch.setattr(
        'app.core.module_tracking.load_module_tracking',
        lambda: {
            'printing': {
                'version': '1.0.0',
                'has_frontend': True,
                'signature_status': 'unsigned',
            }
        },
    )

    printing = _module(get_available_modules_list(), 'printing')

    assert printing is not None
    assert printing.module_type == 'community'


def test_an_old_install_without_signature_status_reads_as_unsigned(monkeypatch):
    """Installations recorded before signatures existed (or with signing
    off) carry no signature_status. Their truth is 'unsigned' — a card
    that looks exactly like an in-tree module's claims a verification
    nobody did."""
    monkeypatch.setattr(
        'app.core.module_tracking.load_module_tracking',
        lambda: {
            'printing': {
                'version': '1.0.0',
                'has_frontend': True,
            }
        },
    )

    printing = _module(get_available_modules_list(), 'printing')

    assert printing is not None
    assert printing.signature_status == 'unsigned'
    assert printing.signed_by is None


def _fake_tree_module(name: str, module_type: str, is_trusted: bool = False):
    """A registry entry shaped like a directory discovered on disk — the
    registry walks the filesystem, so a module nobody installed still
    reaches this catalogue carrying whatever its manifest claims."""
    from types import SimpleNamespace

    return SimpleNamespace(
        metadata=SimpleNamespace(
            name=name,
            display_name=name,
            description='',
            icon='box',
            module_type=module_type,
            category='business',
            capabilities=[],
            requires=[],
            optional_requires=[],
            version='0.1.0',
            author='Some Vendor',
            license='MIT',
            homepage=None,
            is_trusted=is_trusted,
            is_reference=False,
            requires_api_key=False,
        )
    )


def test_an_untracked_directory_cannot_crown_itself_official(monkeypatch):
    """The registry discovers modules from the filesystem, so a directory
    dropped into backend/app/modules/ is a full runtime citizen — routes,
    migrations, the store card — without the installer ever writing a
    tracking entry. The old gate kept the manifest's module_type for
    exactly that shape, and the comment above it said why it should not:
    only code the repository ships may keep its type. A directory nobody
    shipped reads as community, whatever its manifest claims."""
    from app.api.modules import module_registry

    monkeypatch.setattr(
        module_registry,
        'get_all',
        lambda: [_fake_tree_module('revdemo', 'official')],
    )
    monkeypatch.setattr(
        'app.core.module_tracking.load_module_tracking',
        lambda: {},
    )

    revdemo = _module(get_available_modules_list(), 'revdemo')

    assert revdemo is not None
    assert revdemo.module_type == 'community'


def test_a_repo_module_keeps_its_type_without_a_tracking_entry(monkeypatch):
    """The honest side of the same rule: code the repository ships — the
    modules beyond the trusted-core set too (equipment, nutrition and
    friends are repo code no installer ever tracked) — keeps its type
    with no tracking entry. Green before the fix as well; it pins the
    shape the discriminator must not break."""
    from app.api.modules import module_registry

    monkeypatch.setattr(
        module_registry,
        'get_all',
        lambda: [_fake_tree_module('equipment', 'official')],
    )
    monkeypatch.setattr(
        'app.core.module_tracking.load_module_tracking',
        lambda: {},
    )

    equipment = _module(get_available_modules_list(), 'equipment')

    assert equipment is not None
    assert equipment.module_type == 'official'
