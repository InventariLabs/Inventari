"""Tree guard: the SPA's nginx names no version and answers dotfile probes with 404.

Scanners walk the public site asking for ``/.env``, ``/.git/config``,
``/.aws/credentials`` and the like. Nothing leaked — the SPA fallback answers
any unknown path with ``index.html`` — but it answered with ``200``, which a
scanner reads as a hit worth following up, and every response carried
``Server: nginx/<version>``, which tells it which advisories to try.

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


def _nginx_conf() -> str:
    root = Path(os.environ.get('INVENTARI_REPO_ROOT') or _CHECKER.parents[2])
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
