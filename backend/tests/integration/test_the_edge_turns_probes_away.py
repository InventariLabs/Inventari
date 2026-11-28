"""Tree guard: the SPA's nginx turns scanner probes away and serves no default security.txt.

Scanners walk the public site asking for ``/.env``, ``/.git/config``,
``/wp-admin``, ``/config.php~`` and the like. Nothing leaked — the SPA fallback
answers any unknown path with ``index.html`` — but it answered with ``200``,
which a scanner reads as a hit worth following up, and every response carried
``Server: nginx/<version>``, which tells it which advisories to try.
``/.well-known/security.txt`` is the same answer in reverse: it belongs to the
operator of the instance, and the image ships none, so the address must answer
404 rather than present the application start page as if it were a policy.

The rule lives in ``backend/scripts/check_edge_public_routes.py`` next to the
other edge checks; ``INVENTARI_REPO_ROOT`` names the checkout in the backend
container (``docker-compose.yml`` mounts it at ``/repo``).
"""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path

import pytest

_CHECKER = (
    Path(__file__).resolve().parents[2] / 'scripts' / 'check_edge_public_routes.py'
)


def _load_checker():
    spec = importlib.util.spec_from_file_location('check_edge_public_routes', _CHECKER)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _repo_root() -> Path:
    return Path(os.environ.get('INVENTARI_REPO_ROOT') or _CHECKER.parents[2])


def _nginx_conf() -> str:
    root = _repo_root()
    nginx = root / 'frontend' / 'nginx.conf'
    assert nginx.exists(), (
        f'{nginx} is not reachable, so this check would measure nothing; run on '
        'the host, or point INVENTARI_REPO_ROOT at the checkout — '
        'docker-compose.yml mounts it for the backend service.'
    )
    return nginx.read_text()


@pytest.mark.integration
class TestTheEdgeTurnsProbesAway:
    def test_the_shipped_config_hides_the_version_and_refuses_dotfiles(self) -> None:
        problems = _load_checker().check_nginx_probe_surface(_nginx_conf())
        assert not problems, '\n  '.join(['the edge invites probing:', *problems])

    def test_the_check_refuses_a_config_that_names_its_version(self) -> None:
        checker = _load_checker()
        conf = _nginx_conf().replace('server_tokens off;', '')
        problems = checker.check_nginx_probe_surface(conf)
        assert any('server_tokens' in problem for problem in problems), repr(problems)

    def test_the_check_refuses_a_config_that_serves_dotfiles(self) -> None:
        checker = _load_checker()
        conf = checker.NGINX_DOTFILES.sub('', _nginx_conf())
        problems = checker.check_nginx_probe_surface(conf)
        assert any('dot-segment' in problem for problem in problems), repr(problems)

    def test_the_check_refuses_a_dotfile_rule_behind_another_regex(self) -> None:
        """nginx takes the first matching regex location, so order is the rule.

        Behind the static-asset regex a probe for ``/.env.js`` or
        ``/.vite/manifest.json`` would be answered by that block instead.
        """
        checker = _load_checker()
        conf = _nginx_conf()
        rule = checker.NGINX_DOTFILES.search(conf)
        assert rule, 'the shipped config has no dotfile rule to move'
        moved = conf.replace(rule.group(0), '').rstrip().removesuffix('}')
        moved += '\n' + rule.group(0) + '\n}\n'
        problems = checker.check_nginx_probe_surface(moved)
        assert any('first regex' in problem for problem in problems), repr(problems)


def _without_nginx_block(conf: str, marker: str) -> str:
    """The config with the location block whose head contains ``marker`` removed."""
    start = conf.index(marker)
    end = conf.index('\n    }', start) + len('\n    }')
    return conf[:start] + conf[end:]


@pytest.mark.integration
class TestTheEdgeTurnsScannerProbesAway:
    def test_the_shipped_config_answers_scanner_probes_with_404(self) -> None:
        problems = _load_checker().check_nginx_probe_surface(_nginx_conf())
        assert not problems, '\n  '.join(['the edge invites probing:', *problems])

    def test_the_check_refuses_a_config_without_the_scanner_rule(self) -> None:
        checker = _load_checker()
        conf = _without_nginx_block(_nginx_conf(), 'location ~* (?:')
        problems = checker.check_nginx_probe_surface(conf)
        assert any('/wp-admin' in problem for problem in problems), repr(problems)

    def test_the_check_requires_the_scanner_rule_to_ignore_case(self) -> None:
        """A scanner sends ``/WP-ADMIN`` as readily as ``/wp-admin``."""
        checker = _load_checker()
        conf = _nginx_conf().replace('location ~* (?:', 'location ~ (?:', 1)
        problems = checker.check_nginx_probe_surface(conf)
        assert any('/WP-ADMIN' in problem for problem in problems), repr(problems)

    def test_the_check_refuses_an_earlier_regex_that_answers_a_probe(self) -> None:
        """nginx answers with the first matching regex location, not the 404 one."""
        checker = _load_checker()
        conf = _nginx_conf().replace(
            '    location ~* (?:',
            '    location ~ /vendor/ {\n    }\n\n    location ~* (?:',
            1,
        )
        problems = checker.check_nginx_probe_surface(conf)
        assert any(
            'other than 404' in problem and '/vendor/' in problem
            for problem in problems
        ), repr(problems)


@pytest.mark.integration
class TestTheEdgeServesSecurityTxtOnlyWhenProvided:
    def test_the_shipped_config_serves_the_operator_file_or_404(self) -> None:
        problems = _load_checker().check_nginx_security_txt(_nginx_conf())
        assert not problems, '\n  '.join(
            ['the edge answers security.txt wrong:', *problems]
        )

    def test_the_check_refuses_a_config_without_the_security_txt_location(self) -> None:
        checker = _load_checker()
        conf = _without_nginx_block(
            _nginx_conf(), 'location = /.well-known/security.txt'
        )
        problems = checker.check_nginx_security_txt(conf)
        assert any('start page' in problem for problem in problems), repr(problems)

    def test_the_check_refuses_a_location_without_text_plain(self) -> None:
        checker = _load_checker()
        conf = _nginx_conf().replace('        default_type text/plain;\n', '', 1)
        problems = checker.check_nginx_security_txt(conf)
        assert any('text/plain' in problem for problem in problems), repr(problems)

    def test_the_check_refuses_a_fallback_to_the_application(self) -> None:
        checker = _load_checker()
        conf = _nginx_conf().replace(
            '    location = /.well-known/security.txt {\n'
            '        default_type text/plain;\n'
            '        alias /operator/security-txt/security.txt;\n'
            '    }',
            '    location = /.well-known/security.txt {\n'
            '        default_type text/plain;\n'
            '        try_files $uri /index.html;\n'
            '    }',
        )
        problems = checker.check_nginx_security_txt(conf)
        assert any('index.html' in problem for problem in problems), repr(problems)

    def test_the_frontend_mounts_the_directory_the_alias_names(self) -> None:
        root = _repo_root()
        compose = (root / 'docker-compose.prod.yml').read_text()
        problems = _load_checker().check_security_txt_mount(
            compose, root / 'security-txt'
        )
        assert not problems, '\n  '.join(
            ['the operator file cannot reach nginx:', *problems]
        )

    def test_the_check_refuses_a_compose_without_the_mount(self) -> None:
        root = _repo_root()
        compose = (root / 'docker-compose.prod.yml').read_text()
        dropped = compose.replace(':/operator/security-txt:ro', ':/elsewhere:ro')
        problems = _load_checker().check_security_txt_mount(
            dropped, root / 'security-txt'
        )
        assert any('/operator/security-txt' in problem for problem in problems), repr(
            problems
        )

    def test_the_check_refuses_a_checkout_without_the_directory(self) -> None:
        root = _repo_root()
        compose = (root / 'docker-compose.prod.yml').read_text()
        problems = _load_checker().check_security_txt_mount(
            compose, root / 'no-such-security-txt'
        )
        assert any('security-txt/' in problem for problem in problems), repr(problems)
