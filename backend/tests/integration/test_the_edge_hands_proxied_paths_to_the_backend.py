"""Tree guard: no regex location of the SPA's nginx takes a proxied path.

nginx picks the longest matching prefix location and then, unless that prefix
carries ``^~``, tries the regex locations in order and answers with the first
that matches. The static-asset regex matches every path that ends in ``.jpg``
or ``.png``, so a plain ``location /uploads`` handed each stored photo to the
static block, which looked for it on disk and answered nginx's own 404. Behind
Caddy nobody saw it — Caddy sends ``/uploads/*`` to the backend before the
frontend container is asked — but a deployment that reaches that container
directly lost every photo. ``/api`` carries the same modifier for the same
reason: a module's route that ends in a file name is a path the static block
would otherwise take.

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
class TestTheEdgeHandsProxiedPathsToTheBackend:
    def test_the_shipped_config_keeps_every_proxied_prefix_from_the_regexes(
        self,
    ) -> None:
        problems = _load_checker().check_nginx_proxy_precedence(_nginx_conf())
        assert not problems, '\n  '.join(
            ['a regex location answers paths meant for the backend:', *problems]
        )

    def test_the_check_refuses_a_plain_prefix_in_front_of_stored_files(
        self,
    ) -> None:
        """The shape the file had: ``location /uploads`` without ``^~``."""
        checker = _load_checker()
        conf = _nginx_conf()
        plain = conf.replace('location ^~ /uploads ', 'location /uploads ')
        assert plain != conf, 'the shipped config has no `^~ /uploads` to undo'
        problems = checker.check_nginx_proxy_precedence(plain)
        assert any('/uploads' in problem for problem in problems), repr(problems)

    def test_the_check_leaves_a_location_that_serves_files_from_disk_alone(
        self,
    ) -> None:
        """Only a block that proxies is refused; the SPA fallback stays plain."""
        checker = _load_checker()
        conf = """server {
    location / {
        try_files $uri $uri/ /index.html;
    }
    location ~* \\.(js|png)$ {
        expires 1y;
    }
}
"""
        assert checker.check_nginx_proxy_precedence(conf) == []
