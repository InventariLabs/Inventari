"""`scripts/install.sh` installs a release with one command, and the guides open with it.

Six steps and a fork between building and downloading the images made a
reader give up before the first command. The installer asks only what the
reader alone knows, does the rest in the order that keeps a new installation
out of a stranger's hands — the administrator first, the proxy and its public
certificate after — and can be run again: a finished installation is left as
it is, and a failed step is where the next run continues.

The script runs for real here, under the system's ``sh``, with ``git`` cloning
a local repository that carries the release tag and ``scripts/init-env.sh``
writing the real ``.env``. The commands that need a server — ``docker``,
``curl``, ``tailscale``, ``getent``, ``sudo`` — are stand-ins that record how
they were called and answer from a state directory, so what is pinned is the
script's own decisions: what it runs, in which order, what it asks, what it
says and when it stops. That the stack really comes up, the certificate is
issued and the sign-in works was walked on a clean machine.
"""

from __future__ import annotations

import os
import re
import shutil
import stat
import subprocess
from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.unit

_REPO_ROOT = Path(
    os.environ.get('INVENTARI_REPO_ROOT') or Path(__file__).resolve().parents[3]
)
_INSTALLER = _REPO_ROOT / 'scripts/install.sh'
_SH = shutil.which('sh') or '/bin/sh'
_GIT = shutil.which('git') or '/usr/bin/git'
# GitHub runs a step's `run` under bash -e.
_BASH = shutil.which('bash') or '/bin/bash'
_PASSWORD = 'Correct-Horse-7'
_ONE_LINE = (
    'curl -fsSL https://github.com/InventariLabs/Inventari/releases/latest/'
    'download/install.sh | sh -s -- {mode}'
)

#: The files of a release the installer reads; the rest of the tree is not
#: needed to decide anything it does.
_RELEASE_FILES = (
    'scripts/init-env.sh',
    '.env.production.example',
    'backend/pyproject.toml',
    'docker-compose.prod.yml',
    'docker-compose.images.yml',
    'docker-compose.tailscale.yml',
)

_FAKE_DOCKER = r"""#!/bin/sh
state="$FAKE_STATE"
printf '%s\n' "$*" >> "$state/calls"
if [ "$1" != compose ]; then
    case "$1" in
        info) [ ! -e "$state/docker-down" ] ;;
        image) [ ! -e "$state/pull-fails" ] || [ ! -e "$state/no-local-images" ] ;;
        *) true ;;
    esac
    exit $?
fi
shift
case "$*" in
    "version --short") echo 2.40.3 ;;
    "ps --status running --services") cat "$state/running" 2>/dev/null || true ;;
    "pull --ignore-pull-failures") true ;;
    "config --images") printf 'ghcr.io/inventarilabs/inventari-backend:1\npostgres:17-alpine\n' ;;
    "up -d --pull never --scale caddy=0") printf 'db\nbackend\nfrontend\n' > "$state/running" ;;
    "up -d --pull never")
        [ ! -e "$state/proxy-fails" ] && printf 'db\nbackend\nfrontend\ncaddy\n' > "$state/running" ;;
    "exec -T backend curl -sf http://localhost:8000/health/ready") true ;;
    "exec -T backend curl -sf http://localhost:8000/api/v1/auth/init-status")
        if [ -e "$state/admin" ]; then echo '{"is_initialized":true,"is_demo":false}'
        else echo '{"is_initialized":false,"is_demo":false}'; fi ;;
    "exec -T backend sh -c "*)
        cat > "$state/admin-stdin"
        eval "email=\${$#}"
        printf '%s\n' "$email" > "$state/admin" ;;
    "cp caddy:/data/caddy/pki/authorities/local/root.crt "*)
        eval "target=\${$#}"
        echo 'ROOT CERTIFICATE' > "$target" ;;
    *) echo "fake docker: unexpected: compose $*" >&2; exit 3 ;;
esac
"""

_FAKE_CURL = """#!/bin/sh
printf 'curl %s\\n' "$*" >> "$FAKE_STATE/calls"
grep -qx caddy "$FAKE_STATE/running" 2>/dev/null
"""

_FAKE_GETENT = """#!/bin/sh
[ ! -e "$FAKE_STATE/no-dns" ] && echo "203.0.113.7 $2"
"""

_FAKE_TAILSCALE = """#!/bin/sh
printf 'tailscale %s\\n' "$*" >> "$FAKE_STATE/calls"
case "$1" in
    status) cat "$FAKE_STATE/tailscale.json" ;;
    up) sed -i 's/"NeedsLogin"/"Running"/' "$FAKE_STATE/tailscale.json" ;;
esac
"""

_FAKE_SUDO = """#!/bin/sh
printf 'sudo %s\\n' "$*" >> "$FAKE_STATE/calls"
exec "$@"
"""

_FAKE_SS = '#!/bin/sh\ncat "$FAKE_STATE/ports" 2>/dev/null || true\n'

_TAILNET_STATUS = """{
  "Version": "1.90.0",
  "BackendState": "%s",
  "Self": {"DNSName": "box.tail1234.ts.net.", "HostName": "box"},
  "CertDomains": [
    "box.tail1234.ts.net"
  ],
  "Peer": {}
}
"""


def _version() -> str:
    found = re.search(
        r'^version = "([^"]+)"',
        (_REPO_ROOT / 'backend/pyproject.toml').read_text(encoding='utf-8'),
        re.M,
    )
    assert found
    return found.group(1)


@pytest.fixture(scope='module')
def release(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A repository holding the release's files under the release's tag."""
    origin = tmp_path_factory.mktemp('origin')
    for name in _RELEASE_FILES:
        (origin / name).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(_REPO_ROOT / name, origin / name)
    env = {
        **os.environ,
        'GIT_AUTHOR_NAME': 'test',
        'GIT_AUTHOR_EMAIL': 'test@example.com',
        'GIT_COMMITTER_NAME': 'test',
        'GIT_COMMITTER_EMAIL': 'test@example.com',
        'GIT_CONFIG_GLOBAL': '/dev/null',
    }
    for command in (
        [_GIT, 'init', '-q', '-b', 'main'],
        [_GIT, 'add', '-A'],
        [_GIT, 'commit', '-q', '-m', 'release'],
        [_GIT, 'tag', f'v{_version()}'],
    ):
        subprocess.run(command, cwd=origin, env=env, check=True)
    return origin


@pytest.fixture
def machine(tmp_path: Path) -> Path:
    """The state the stand-ins answer from, and the directory they live in."""
    state = tmp_path / 'state'
    state.mkdir()
    (state / 'calls').write_text('', encoding='utf-8')
    (state / 'tailscale.json').write_text(_TAILNET_STATUS % 'Running', encoding='utf-8')
    shims = tmp_path / 'bin'
    shims.mkdir()
    for name, body in (
        ('docker', _FAKE_DOCKER),
        ('curl', _FAKE_CURL),
        ('getent', _FAKE_GETENT),
        ('tailscale', _FAKE_TAILSCALE),
        ('sudo', _FAKE_SUDO),
        ('ss', _FAKE_SS),
    ):
        (shims / name).write_text(body, encoding='utf-8')
        (shims / name).chmod(0o755)
    return state


def _install(
    machine: Path, release: Path, *args: str, **env: str
) -> subprocess.CompletedProcess[str]:
    """Run the installer with no terminal behind it, as a pipe from curl has."""
    return subprocess.run(
        [_SH, str(_INSTALLER), *args],
        env={
            **os.environ,
            'PATH': f'{machine.parent / "bin"}:{os.environ["PATH"]}',
            'FAKE_STATE': str(machine),
            'INVENTARI_DIR': str(machine.parent / 'opt-inventari'),
            'INVENTARI_REPO': str(release),
            'INVENTARI_VERSION': _version(),
            'INVENTARI_ADMIN_PASSWORD': _PASSWORD,
            'GIT_CONFIG_GLOBAL': '/dev/null',
            **env,
        },
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        start_new_session=True,  # no controlling terminal: /dev/tty is not there
        timeout=120,
    )


def _server(
    machine: Path, release: Path, **env: str
) -> subprocess.CompletedProcess[str]:
    return _install(
        machine,
        release,
        'vps',
        '--domain',
        'inv.example.com',
        '--email',
        'certs@example.com',
        '--admin-email',
        'admin@example.com',
        **env,
    )


def _calls(machine: Path) -> list[str]:
    return (machine / 'calls').read_text(encoding='utf-8').splitlines()


def _env(machine: Path) -> dict[str, str]:
    text = (machine.parent / 'opt-inventari/.env').read_text(encoding='utf-8')
    return dict(re.findall(r'^([A-Z][A-Z0-9_]*)=(.*)$', text, flags=re.M))


class TestAServerInstall:
    def test_it_ends_by_printing_the_https_address(
        self, machine: Path, release: Path
    ) -> None:
        result = _server(machine, release)

        assert result.returncode == 0, result.stderr
        assert 'https://inv.example.com' in result.stdout

    def test_the_administrator_exists_before_the_proxy_starts(
        self, machine: Path, release: Path
    ) -> None:
        """The certificate is public the moment the proxy asks for it."""
        _server(machine, release)
        calls = _calls(machine)

        without_proxy = calls.index('compose up -d --pull never --scale caddy=0')
        admin = next(i for i, c in enumerate(calls) if 'create-admin' in c)
        proxy = calls.index('compose up -d --pull never')
        assert without_proxy < admin < proxy
        assert (machine / 'admin').read_text().strip() == 'admin@example.com'

    def test_the_password_reaches_no_command_line(
        self, machine: Path, release: Path
    ) -> None:
        """sudo logs the commands it runs, and a command line is public."""
        _server(machine, release)

        assert not [call for call in _calls(machine) if _PASSWORD in call]
        assert (machine / 'admin-stdin').read_text().strip() == _PASSWORD

    def test_the_env_holds_the_answers_and_names_the_published_images(
        self, machine: Path, release: Path
    ) -> None:
        """No `-f` in any later command: `.env` names the files."""
        _server(machine, release)
        values = _env(machine)
        env_file = machine.parent / 'opt-inventari/.env'

        assert values['DOMAIN'] == 'inv.example.com'
        assert values['ACME_EMAIL'] == 'certs@example.com'
        assert values['INVENTARI_VERSION'] == _version()
        assert values['COMPOSE_FILE'] == (
            'docker-compose.prod.yml:docker-compose.images.yml'
        )
        assert re.fullmatch(r'[0-9a-f]{64}', values['FERNET_SALT'])
        assert stat.S_IMODE(env_file.stat().st_mode) == 0o600

    def test_the_files_are_a_checkout_of_the_release_tag(
        self, machine: Path, release: Path
    ) -> None:
        """What DEPLOYMENT.md's update moves from one tag to the next."""
        _server(machine, release)

        described = subprocess.run(
            [_GIT, 'describe', '--tags', '--exact-match'],
            cwd=machine.parent / 'opt-inventari',
            capture_output=True,
            text=True,
            check=True,
            env={**os.environ, 'GIT_CONFIG_GLOBAL': '/dev/null'},
        )
        assert described.stdout.strip() == f'v{_version()}'


class TestRunAgain:
    def test_a_finished_installation_is_left_as_it_is_and_says_so(
        self, machine: Path, release: Path
    ) -> None:
        _server(machine, release)
        env_before = (machine.parent / 'opt-inventari/.env').read_bytes()
        (machine / 'calls').write_text('', encoding='utf-8')

        again = _server(machine, release)

        assert again.returncode == 0, again.stderr
        assert 'Nothing was changed' in again.stdout
        changing = [
            call
            for call in _calls(machine)
            if call.startswith(('compose up', 'compose pull', 'compose exec'))
        ]
        assert changing == []
        assert (machine.parent / 'opt-inventari/.env').read_bytes() == env_before

    def test_a_failed_step_says_what_failed_and_the_next_run_continues(
        self, machine: Path, release: Path
    ) -> None:
        (machine / 'pull-fails').touch()
        (machine / 'no-local-images').touch()

        failed = _server(machine, release)

        assert failed.returncode != 0
        assert 'Stopped: These images could not be downloaded:' in failed.stderr
        assert 'ghcr.io/inventarilabs/inventari-backend:1' in failed.stderr
        assert 'run the same command again' in failed.stderr
        assert not [c for c in _calls(machine) if c.startswith('compose up')]
        secrets_kept = _env(machine)['FERNET_SALT']

        (machine / 'pull-fails').unlink()
        resumed = _server(machine, release)

        assert resumed.returncode == 0, resumed.stderr
        assert 'https://inv.example.com' in resumed.stdout
        assert _env(machine)['FERNET_SALT'] == secrets_kept

    def test_images_already_on_the_machine_do_when_a_download_fails(
        self, machine: Path, release: Path
    ) -> None:
        """One image that fails must not stop the others from downloading."""
        (machine / 'pull-fails').touch()

        result = _server(machine, release)

        assert result.returncode == 0, result.stderr
        assert 'compose pull --ignore-pull-failures' in _calls(machine)

    def test_a_run_after_the_administrator_exists_asks_for_no_password(
        self, machine: Path, release: Path
    ) -> None:
        """The next run must not reset the account it made, nor ask for it."""
        (machine / 'proxy-fails').touch()
        assert _server(machine, release).returncode != 0
        (machine / 'proxy-fails').unlink()
        (machine / 'calls').write_text('', encoding='utf-8')

        resumed = _install(
            machine, release, 'vps', INVENTARI_ADMIN_PASSWORD='', INVENTARI_VERSION=''
        )

        assert resumed.returncode == 0, resumed.stderr
        assert not [c for c in _calls(machine) if 'create-admin' in c]
        assert 'compose up -d --pull never' in _calls(machine)


class TestItStopsBeforeChangingAnything:
    def test_without_a_terminal_a_missing_answer_names_the_option(
        self, machine: Path, release: Path
    ) -> None:
        result = _install(machine, release, 'vps')

        assert result.returncode != 0
        assert 'There is no terminal to ask on' in result.stderr
        assert not (machine.parent / 'opt-inventari').exists()

    def test_a_domain_that_does_not_resolve(self, machine: Path, release: Path) -> None:
        (machine / 'no-dns').touch()

        result = _server(machine, release)

        assert result.returncode != 0
        assert 'inv.example.com does not resolve' in result.stderr
        assert not (machine.parent / 'opt-inventari').exists()

    def test_a_password_the_backend_would_refuse(
        self, machine: Path, release: Path
    ) -> None:
        result = _server(machine, release, INVENTARI_ADMIN_PASSWORD='alllowercase1')

        assert result.returncode != 0
        assert 'needs an uppercase letter' in result.stderr
        assert not (machine.parent / 'opt-inventari').exists()

    def test_ports_another_program_holds(self, machine: Path, release: Path) -> None:
        (machine / 'ports').write_text('LISTEN 0 511 0.0.0.0:80 0.0.0.0:*\n')

        result = _server(machine, release)

        assert result.returncode != 0
        assert 'Ports 80 and 443 must be free' in result.stderr
        assert not (machine.parent / 'opt-inventari').exists()

    def test_a_copy_that_names_no_release(self, machine: Path, release: Path) -> None:
        result = _server(machine, release, INVENTARI_VERSION='')

        assert result.returncode != 0
        assert 'names no release' in result.stderr


class TestAtHome:
    def test_through_tailscale_the_address_is_the_machines_tailnet_name(
        self, machine: Path, release: Path
    ) -> None:
        result = _install(
            machine, release, 'home', '--admin-email', 'admin@example.com'
        )

        assert result.returncode == 0, result.stderr
        assert 'https://box.tail1234.ts.net' in result.stdout
        values = _env(machine)
        assert values['DOMAIN'] == 'box.tail1234.ts.net'
        assert values['COMPOSE_FILE'].split(':')[-1] == 'docker-compose.tailscale.yml'

    def test_a_signed_out_machine_is_signed_in_first(
        self, machine: Path, release: Path
    ) -> None:
        (machine / 'tailscale.json').write_text(_TAILNET_STATUS % 'NeedsLogin')

        result = _install(
            machine, release, 'home', '--admin-email', 'admin@example.com'
        )

        assert result.returncode == 0, result.stderr
        calls = _calls(machine)
        sign_in = calls.index('tailscale up')
        assert sign_in < calls.index('compose up -d --pull never --scale caddy=0')

    def test_with_the_local_authority_the_root_certificate_is_left_to_share(
        self, machine: Path, release: Path
    ) -> None:
        result = _install(
            machine,
            release,
            'home',
            '--local-ca',
            '--name',
            'inventari.home.arpa',
            '--admin-email',
            'admin@example.com',
        )

        assert result.returncode == 0, result.stderr
        assert (machine.parent / 'opt-inventari/inventari-root.crt').is_file()
        assert 'inventari-root.crt' in result.stdout
        values = _env(machine)
        assert values['DOMAIN'] == 'inventari.home.arpa'
        assert 'tailscale' not in values['COMPOSE_FILE']
        assert not [c for c in _calls(machine) if c.startswith('tailscale')]

    def test_a_local_name_no_local_authority_can_certify_is_refused(
        self, machine: Path, release: Path
    ) -> None:
        result = _install(
            machine,
            release,
            'home',
            '--local-ca',
            '--name',
            'inventari',
            '--admin-email',
            'admin@example.com',
        )

        assert result.returncode != 0
        assert '.home.arpa, .local or .internal' in result.stderr


class TestTheTailscaleFile:
    def test_caddy_reaches_the_daemon_through_its_socket_directory(self) -> None:
        overlay = yaml.safe_load(
            (_REPO_ROOT / 'docker-compose.tailscale.yml').read_text(encoding='utf-8')
        )

        assert overlay['services']['caddy']['volumes'] == [
            '/var/run/tailscale:/var/run/tailscale:ro'
        ]


class TestTheReleaseCarriesTheInstaller:
    def test_the_workflow_writes_the_release_into_the_published_copy(
        self, tmp_path: Path
    ) -> None:
        """The installer of a release installs that release."""
        workflow = yaml.safe_load(
            (_REPO_ROOT / '.github/workflows/release-installer.yml').read_text(
                encoding='utf-8'
            )
        )
        steps = workflow['jobs']['installer']['steps']
        write = next(s for s in steps if s.get('name', '').startswith('Write'))
        (tmp_path / 'scripts').mkdir()
        shutil.copy(_INSTALLER, tmp_path / 'scripts/install.sh')

        subprocess.run(
            [_BASH, '-e', '-c', write['run']],
            cwd=tmp_path,
            env={**os.environ, 'TAG': 'v9.8.7'},
            check=True,
        )

        published = (tmp_path / 'install.sh').read_text(encoding='utf-8')
        assert re.search(r'^published_release="9\.8\.7"$', published, re.M)
        upload = next(s for s in steps if s.get('name', '').startswith('Attach'))
        assert 'gh release upload "$TAG" install.sh' in upload['run']


class TestTheGuidesOpenWithTheLine:
    @pytest.mark.parametrize(
        'guide, mode', [('QUICK_DEPLOY.md', 'vps'), ('docs/HOME_INSTALL.md', 'home')]
    )
    def test_the_first_command_is_the_installer(self, guide: str, mode: str) -> None:
        text = (_REPO_ROOT / guide).read_text(encoding='utf-8')
        first_block = re.search(r'```(?:bash|sh)\n(.*?)```', text, flags=re.S)

        assert first_block is not None
        assert first_block.group(1).strip() == _ONE_LINE.format(mode=mode)

    @pytest.mark.parametrize('guide', ['QUICK_DEPLOY.md', 'docs/HOME_INSTALL.md'])
    def test_the_guide_has_no_fork_and_no_compose_file_flag(self, guide: str) -> None:
        text = (_REPO_ROOT / guide).read_text(encoding='utf-8')

        assert '-f docker-compose' not in text
        assert 'Choose one' not in text

    def test_the_line_is_the_one_the_installer_describes(self) -> None:
        header = _INSTALLER.read_text(encoding='utf-8')

        for mode in ('vps', 'home', 'home --local-ca'):
            assert f'#   {_ONE_LINE.format(mode=mode)}' in header


class TestTheHomeGuideExplainsHttpsFirst:
    @pytest.fixture(scope='class')
    def guide(self) -> str:
        return (_REPO_ROOT / 'docs/HOME_INSTALL.md').read_text(encoding='utf-8')

    def test_why_https_comes_before_the_phones_are_set_up(self, guide: str) -> None:
        why = guide.index('## Why HTTPS, even at home')
        phones = guide.index('## The phones')

        assert why < phones

    def test_it_quotes_what_the_scanner_says_without_it(self, guide: str) -> None:
        """The reader recognises the message on the screen."""
        scan = (_REPO_ROOT / 'frontend/src/i18n/locales/en/scan.json').read_text(
            encoding='utf-8'
        )
        said = re.search(r'"errorInsecureContext": "([^"]+)"', scan)

        assert said is not None
        assert said.group(1) in ' '.join(guide.split())

    def test_the_sign_in_is_named_alongside_the_camera(self, guide: str) -> None:
        section = guide.split('## Why HTTPS, even at home', 1)[1].split('\n## ', 1)[0]

        assert 'camera' in section
        assert 'reload' in section
        assert 'works either way' not in guide

    def test_the_local_authority_is_an_option_below_the_main_line(
        self, guide: str
    ) -> None:
        main_line = guide.index(_ONE_LINE.format(mode='home'))
        local = guide.index(_ONE_LINE.format(mode='home --local-ca'))

        assert main_line < local
