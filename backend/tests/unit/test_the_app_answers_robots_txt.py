"""Tree guard: the application ships a robots file that keeps crawlers out.

Every unknown path falls through to the single-page app, so without a file of
its own ``/robots.txt`` answered with the application's HTML. The file sits in
``frontend/public``, which the production build copies to the web root, and
``nginx`` serves an existing file before it falls back to ``index.html``.
"""

from __future__ import annotations

import os
from pathlib import Path

_ROOT = Path(os.environ.get('INVENTARI_REPO_ROOT') or Path(__file__).parents[3])


def test_the_public_directory_ships_a_robots_file_that_disallows_everything() -> None:
    robots = _ROOT / 'frontend' / 'public' / 'robots.txt'
    assert robots.is_file(), f'{robots} is missing: /robots.txt would be the app shell'
    rules = [
        line.strip()
        for line in robots.read_text(encoding='utf-8').splitlines()
        if line.strip() and not line.lstrip().startswith('#')
    ]
    assert rules == ['User-agent: *', 'Disallow: /']


def test_nginx_serves_a_file_of_the_web_root_before_the_app_fallback() -> None:
    conf = (_ROOT / 'frontend' / 'nginx.conf').read_text(encoding='utf-8')
    assert 'try_files $uri $uri/ /index.html;' in conf
