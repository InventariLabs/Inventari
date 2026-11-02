"""The installer verifies what it installs.

A signature over the package content is what makes "certified"
checkable instead of claimable: a tampered package is refused where its
intact twin installs, an unsigned package installs only after the
explicit --allow-unsigned switch, and the tracking file records who
signed the package and when the install verified it.
"""

from __future__ import annotations

import base64
import json
from pathlib import Path
from unittest.mock import patch

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from app.cli import module_packaging
from app.cli._module_signing import module_tree_digest, sign_module, signed_payload
from app.config import settings

MODULE_YAML = (
    'name: probe_mod\n'
    'version: 0.1.0\n'
    'inventari_min_version: "0.1.0"\n'
    'author: test\n'
    'description: probe module\n'
    'license: MIT\n'
    'homepage: ""\n'
    'requires: []\n'
    'components:\n'
    '  backend: true\n'
    '  frontend: false\n'
)


def _make_package(tmp_path: Path) -> Path:
    """A minimal, AST-clean module package: module.yaml + backend tree."""
    source = tmp_path / 'source'
    backend = source / 'backend'
    backend.mkdir(parents=True)
    (backend / '__init__.py').write_text('')
    (backend / 'module.py').write_text('LABEL = "probe"\n')
    (backend / 'manifest.json').write_text(
        json.dumps(
            {
                'name': 'probe_mod',
                'version': '0.1.0',
                'inventari_min_version': '0.1.0',
                'category': 'integrations',
                'display_name': 'Probe Module',
                'description': 'probe module for the signature tests',
                'icon': 'package',
                'module_type': 'community',
                'requires': [],
                'capabilities': [],
                'permissions': [],
            }
        )
    )
    (source / 'module.yaml').write_text(MODULE_YAML)
    return source


def _write_keypair(tmp_path: Path, name: str) -> tuple[Path, str]:
    """A base64 private-key file and the matching base64 public key."""
    key = Ed25519PrivateKey.generate()
    private_file = tmp_path / f'{name}.private.key'
    private_file.write_text(
        base64.b64encode(
            key.private_bytes(
                encoding=serialization.Encoding.Raw,
                format=serialization.PrivateFormat.Raw,
                encryption_algorithm=serialization.NoEncryption(),
            )
        ).decode('ascii'),
        encoding='ascii',
    )
    public = base64.b64encode(
        key.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
    ).decode('ascii')
    return private_file, public


@pytest.fixture
def install_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point the installer's destinations and tracking at tmp_path."""
    dest_backend = tmp_path / 'installed_backend'
    dest_frontend = tmp_path / 'installed_frontend'
    tracking_file = tmp_path / 'community_modules.json'
    with (
        patch.object(module_packaging, 'BACKEND_MODULES_DIR', dest_backend),
        patch.object(module_packaging, 'FRONTEND_MODULES_DIR', dest_frontend),
        patch('app.cli._module_meta.BACKEND_MODULES_DIR', dest_backend),
        patch('app.cli._module_meta.FRONTEND_MODULES_DIR', dest_frontend),
        patch('app.cli._module_meta.TRACKING_FILE', tracking_file),
    ):
        yield dest_backend


class TestSignedInstalls:
    def test_an_intact_signed_package_installs_and_records_the_verification(
        self, tmp_path: Path, install_env: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        source = _make_package(tmp_path)
        private_file, public = _write_keypair(tmp_path, 'publisher')
        sign_module(
            source,
            {
                'name': 'probe_mod',
                'version': '0.1.0',
                'components': {'backend': True, 'frontend': False},
            },
            private_file,
            'publisher-1',
        )
        monkeypatch.setattr(
            settings, 'MODULE_SIGNING_PUBLIC_KEYS', f'publisher-1={public}'
        )

        module_packaging.install_module(str(source))

        assert (install_env / 'probe_mod').exists()
        tracking_file = tmp_path / 'community_modules.json'
        entry = json.loads(tracking_file.read_text(encoding='utf-8'))['modules'][
            'probe_mod'
        ]
        assert entry['signature_status'] == 'verified'
        assert entry['signature_key_id'] == 'publisher-1'
        assert entry['signature_verified_at']

    def test_a_tampered_package_is_refused_and_leaves_nothing_behind(
        self, tmp_path: Path, install_env: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        source = _make_package(tmp_path)
        private_file, public = _write_keypair(tmp_path, 'publisher')
        sign_module(
            source,
            {
                'name': 'probe_mod',
                'version': '0.1.0',
                'components': {'backend': True, 'frontend': False},
            },
            private_file,
            'publisher-1',
        )
        # One byte of the signed tree changes after signing.
        (source / 'backend' / 'module.py').write_text('LABEL = "tampered"\n')
        monkeypatch.setattr(
            settings, 'MODULE_SIGNING_PUBLIC_KEYS', f'publisher-1={public}'
        )

        with pytest.raises(SystemExit) as exc_info:
            module_packaging.install_module(str(source))

        assert exc_info.value.code == 1
        assert not (install_env / 'probe_mod').exists()

    def test_a_package_signed_by_an_untrusted_key_is_refused(
        self, tmp_path: Path, install_env: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        source = _make_package(tmp_path)
        private_file, _public = _write_keypair(tmp_path, 'stranger')
        stranger_private, trusted_public = _write_keypair(tmp_path, 'publisher')
        del stranger_private
        sign_module(
            source,
            {
                'name': 'probe_mod',
                'version': '0.1.0',
                'components': {'backend': True, 'frontend': False},
            },
            private_file,
            'stranger',
        )
        monkeypatch.setattr(
            settings, 'MODULE_SIGNING_PUBLIC_KEYS', f'publisher-1={trusted_public}'
        )

        with pytest.raises(SystemExit) as exc_info:
            module_packaging.install_module(str(source))

        assert exc_info.value.code == 1
        assert not (install_env / 'probe_mod').exists()


class TestUnsignedInstalls:
    def test_an_unsigned_package_needs_the_explicit_switch(
        self, tmp_path: Path, install_env: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        source = _make_package(tmp_path)
        _, public = _write_keypair(tmp_path, 'publisher')
        monkeypatch.setattr(
            settings, 'MODULE_SIGNING_PUBLIC_KEYS', f'publisher-1={public}'
        )

        with pytest.raises(SystemExit) as exc_info:
            module_packaging.install_module(str(source))

        assert exc_info.value.code == 1
        assert not (install_env / 'probe_mod').exists()

    def test_allow_unsigned_installs_and_records_the_risk(
        self, tmp_path: Path, install_env: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        source = _make_package(tmp_path)
        monkeypatch.setattr(settings, 'MODULE_SIGNING_PUBLIC_KEYS', '')

        module_packaging.install_module(str(source), allow_unsigned=True)

        assert (install_env / 'probe_mod').exists()
        tracking_file = tmp_path / 'community_modules.json'
        entry = json.loads(tracking_file.read_text(encoding='utf-8'))['modules'][
            'probe_mod'
        ]
        assert entry['signature_status'] == 'unsigned'
        # No verification happened, so no timestamp: the field would
        # describe an event that never happened. The record still writes
        # the field — as an explicit null, not by omitting the key — which
        # is exactly what the tracking entry's docstring promises.
        assert 'signature_verified_at' in entry
        assert entry['signature_verified_at'] is None


class TestWhatWasVerifiedIsWhatInstalls:
    """The digest and the copy are one walk, and the walk trusts nothing.

    Two walks with two policies was the hole the first round missed: the
    digest never descended into symlinked directories while the copy
    expanded them, and __pycache__ was hashed out but copied in — a
    bytecode cache nobody signed could stand in for the signed source.
    """

    def test_a_pycache_file_added_after_signing_is_refused(
        self, tmp_path: Path, install_env: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        source = _make_package(tmp_path)
        private_file, public = _write_keypair(tmp_path, 'publisher')
        sign_module(
            source,
            {
                'name': 'probe_mod',
                'version': '0.1.0',
                'components': {'backend': True, 'frontend': False},
            },
            private_file,
            'publisher-1',
        )
        pycache = source / 'backend' / '__pycache__'
        pycache.mkdir()
        # PEP 552 unchecked-hash bytecode: Python loads it without
        # checking the source it claims to come from.
        (pycache / 'module.cpython-313.pyc').write_bytes(b'\x00\x01 poisoned')

        monkeypatch.setattr(
            settings, 'MODULE_SIGNING_PUBLIC_KEYS', f'publisher-1={public}'
        )
        # The copy reads the same walk the digest does, and the walk skips
        # __pycache__: the cache file does not install, so refusing is not
        # even needed — the poisoned bytecode simply never ships.
        module_packaging.install_module(str(source))

        assert (install_env / 'probe_mod' / 'module.py').exists()
        assert not (install_env / 'probe_mod' / '__pycache__').exists()

    def test_a_symlinked_directory_in_the_package_is_refused(
        self, tmp_path: Path, install_env: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        source = _make_package(tmp_path)
        private_file, public = _write_keypair(tmp_path, 'publisher')
        sign_module(
            source,
            {
                'name': 'probe_mod',
                'version': '0.1.0',
                'components': {'backend': True, 'frontend': False},
            },
            private_file,
            'publisher-1',
        )
        # A directory symlink pointing outside the package: the content it
        # expands to was never part of what got signed.
        payload = tmp_path / 'payload'
        payload.mkdir()
        (payload / 'evil.py').write_text('LABEL = "smuggled"\n')
        (source / 'backend' / 'extra').symlink_to(payload, target_is_directory=True)

        monkeypatch.setattr(
            settings, 'MODULE_SIGNING_PUBLIC_KEYS', f'publisher-1={public}'
        )
        with pytest.raises(SystemExit):
            module_packaging.install_module(str(source))

        assert not (install_env / 'probe_mod').exists()
        assert not (install_env / 'probe_mod' / 'extra').exists()

    def test_allow_unsigned_does_not_accept_a_tampered_package(
        self, tmp_path: Path, install_env: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """--allow-unsigned covers the absence of a signature, nothing else.

        A package whose content changed after signing is evidence of
        tampering, not an unsigned delivery: the switch named for the one
        must not open the door for the other.
        """
        source = _make_package(tmp_path)
        private_file, public = _write_keypair(tmp_path, 'publisher')
        sign_module(
            source,
            {
                'name': 'probe_mod',
                'version': '0.1.0',
                'components': {'backend': True, 'frontend': False},
            },
            private_file,
            'publisher-1',
        )
        (source / 'backend' / 'module.py').write_text('LABEL = "tampered"\n')
        monkeypatch.setattr(
            settings, 'MODULE_SIGNING_PUBLIC_KEYS', f'publisher-1={public}'
        )

        with pytest.raises(SystemExit) as exc_info:
            module_packaging.install_module(str(source), allow_unsigned=True)

        assert exc_info.value.code == 1
        assert not (install_env / 'probe_mod').exists()

    def test_allow_unsigned_does_not_accept_an_untrusted_signer(
        self, tmp_path: Path, install_env: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        source = _make_package(tmp_path)
        stranger_private, trusted_public = _write_keypair(tmp_path, 'publisher')
        del stranger_private
        stranger_file, stranger_public = _write_keypair(tmp_path, 'stranger')
        sign_module(
            source,
            {
                'name': 'probe_mod',
                'version': '0.1.0',
                'components': {'backend': True, 'frontend': False},
            },
            stranger_file,
            'stranger',
        )
        monkeypatch.setattr(
            settings, 'MODULE_SIGNING_PUBLIC_KEYS', f'publisher-1={trusted_public}'
        )

        with pytest.raises(SystemExit) as exc_info:
            module_packaging.install_module(str(source), allow_unsigned=True)

        assert exc_info.value.code == 1
        assert not (install_env / 'probe_mod').exists()


class TestUnscannableExecutablesNeverShip:
    """The scan reads Python source; the runtime executes more than that.

    The import machinery also loads sourceless bytecode (.pyc, .pyo)
    and native extensions (.so, .pyd), and the OS maps raw libraries
    (.dll, .dylib) on request. A payload in any of those formats rides
    in behind a scan report that is perfectly true — of the source
    files — while the installed system executes bytes nobody read. The
    walk behind both the digest and the copy refuses the format class,
    so no signing flow can vouch for it and no install flow can ship
    it.
    """

    @pytest.mark.parametrize(
        'suffix', ['.pyc', '.pyo', '.so', '.pyd', '.dll', '.dylib']
    )
    def test_a_package_carrying_a_payload_the_scanner_cannot_read_is_refused(
        self, suffix: str, tmp_path: Path, install_env: Path
    ) -> None:
        source = _make_package(tmp_path)
        (source / 'backend' / f'legacy{suffix}').write_bytes(b'\xde\xad\xbe\xef')

        # allow_unsigned on purpose: the refusal must come from the
        # content walk, not from a missing signature.
        with pytest.raises(SystemExit) as exc_info:
            module_packaging.install_module(str(source), allow_unsigned=True)

        assert exc_info.value.code == 1
        assert not (install_env / 'probe_mod').exists()
        assert not (install_env / 'probe_mod' / f'legacy{suffix}').exists()

    def test_a_deployment_with_no_trusted_keys_is_told_to_add_one(
        self,
        tmp_path: Path,
        install_env: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """The refusal's remedy depends on whose side of it you are on.

        A deployment with no keys configured cannot verify *anyone*, and the
        publisher's package is intact: telling that operator to "re-sign the
        package" sends them to a key they do not own and away from the one
        line that fixes it. It is the operator who reads this screen.
        """
        source = _make_package(tmp_path)
        private_file, _public = _write_keypair(tmp_path, 'publisher')
        sign_module(
            source,
            {
                'name': 'probe_mod',
                'version': '0.1.0',
                'components': {'backend': True, 'frontend': False},
            },
            private_file,
            'publisher-1',
        )
        monkeypatch.setattr(settings, 'MODULE_SIGNING_PUBLIC_KEYS', '')

        with pytest.raises(SystemExit) as exc_info:
            module_packaging.install_module(str(source))

        assert exc_info.value.code == 1
        assert not (install_env / 'probe_mod').exists()
        out = capsys.readouterr().out
        assert 'MODULE_SIGNING_PUBLIC_KEYS' in out
        assert "publisher's key" in out
        assert 're-sign the package' not in out

    def test_the_signer_refuses_a_package_the_scanner_cannot_fully_read(
        self, tmp_path: Path
    ) -> None:
        source = _make_package(tmp_path)
        private_file, _public = _write_keypair(tmp_path, 'publisher')
        (source / 'backend' / 'legacy.pyc').write_bytes(b'\x00\x01 poisoned')

        with pytest.raises(ValueError, match='legacy.pyc'):
            sign_module(
                source,
                {
                    'name': 'probe_mod',
                    'version': '0.1.0',
                    'components': {'backend': True, 'frontend': False},
                },
                private_file,
                'publisher-1',
            )


PROBE_META = {
    'name': 'probe_mod',
    'version': '0.1.0',
    'components': {'backend': True, 'frontend': False},
}


class TestSignatureFormat:
    """``module.sig`` names the rules its digest was made with.

    Without a number, the first change to the file walk would turn every
    signature already in the field into "the package was modified after
    signing", and ``--allow-unsigned`` rightly accepts no invalid one: the
    authors would have to re-sign with nothing to tell old from new.
    """

    def test_the_signer_writes_format_1(self, tmp_path: Path) -> None:
        source = _make_package(tmp_path)
        private_file, _public = _write_keypair(tmp_path, 'publisher')

        sig_path = sign_module(source, PROBE_META, private_file, 'publisher-1')

        assert json.loads(sig_path.read_text(encoding='utf-8'))['format'] == 1

    @pytest.mark.parametrize(
        ('stored', 'hint'),
        [(2, 'a newer Inventari'), (None, 'sign the module again')],
    )
    def test_an_unknown_format_is_refused_by_its_number(
        self,
        stored: int | None,
        hint: str,
        tmp_path: Path,
        install_env: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        source = _make_package(tmp_path)
        private_file, public = _write_keypair(tmp_path, 'publisher')
        sig_path = sign_module(source, PROBE_META, private_file, 'publisher-1')
        data = json.loads(sig_path.read_text(encoding='utf-8'))
        if stored is None:
            del data['format']
        else:
            data['format'] = stored
        sig_path.write_text(json.dumps(data), encoding='utf-8')
        monkeypatch.setattr(
            settings, 'MODULE_SIGNING_PUBLIC_KEYS', f'publisher-1={public}'
        )

        # allow_unsigned on purpose: a format this installer cannot read is
        # not the absence of a signature.
        with pytest.raises(SystemExit) as exc_info:
            module_packaging.install_module(str(source), allow_unsigned=True)

        assert exc_info.value.code == 1
        assert not (install_env / 'probe_mod').exists()
        out = ' '.join(capsys.readouterr().out.split())
        assert f'signature format {stored!r}' in out
        assert hint in out

    @pytest.mark.parametrize('stored', [b'[1, 2]', b'"x"', b'7', b'null', b'\xff{}'])
    def test_a_signature_that_is_not_a_json_object_is_refused(
        self,
        stored: bytes,
        tmp_path: Path,
        install_env: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Valid JSON of the wrong shape is a bad package, not a crash.

        ``json.loads`` accepts any top-level value, and the checks after it
        read keys off a dict: an array or a string ended the install in an
        AttributeError traceback instead of the refusal with its reason. A
        file that is not UTF-8 at all failed the same way one step earlier.
        """
        source = _make_package(tmp_path)
        (source / 'module.sig').write_bytes(stored)

        with pytest.raises(SystemExit) as exc_info:
            module_packaging.install_module(str(source), allow_unsigned=True)

        assert exc_info.value.code == 1
        assert not (install_env / 'probe_mod').exists()
        out = ' '.join(capsys.readouterr().out.split())
        assert 'signature file is unreadable' in out

    def test_the_format_1_payload_of_a_fixed_package_is_pinned(
        self, tmp_path: Path
    ) -> None:
        """The exact bytes format 1 signs, for a package that exercises the walk.

        If this fails, the walk or the payload changed, and every module
        signed so far no longer verifies. That is a new format: give it a
        number of its own and keep reading format 1 — do not update the
        expected bytes here.
        """
        source = tmp_path / 'pinned'
        for rel, data in {
            'module.yaml': b'name: pinned_mod\nversion: 1.2.3\n',
            'module.sig': b'{"outside": "the digest"}\n',
            'README.md': b'not a component, not shipped\n',
            'backend/__init__.py': b'',
            'backend/module.py': b'LABEL = "pinned"\n',
            'backend/api/router.py': b'ROUTES = []\n',
            'backend/tests/test_module.py': b'def test(): ...\n',
            'backend/__pycache__/module.cpython-312.pyc': b'\x00\x01',
            'frontend/index.ts': b'export const pinned = 1;\n',
            'frontend/tests/index.test.ts': b'it("runs", () => {});\n',
        }.items():
            path = source / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        meta = {
            'name': 'pinned_mod',
            'version': '1.2.3',
            'components': {'backend': True, 'frontend': True},
        }

        payload = signed_payload(meta, module_tree_digest(source, meta))

        assert payload == (
            b'inventari-community-module/1\n'
            b'name: pinned_mod\n'
            b'version: 1.2.3\n'
            b'sha256: 216fcb782bb39cb9acc7c0068e288803e1f76ac4cdb697895e53ee3ae4a9c523\n'
        )
