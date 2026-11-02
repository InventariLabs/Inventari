"""A module's migration chain gets the database address it was given.

The address goes into Alembic's config, which configparser reads back and
interpolates: a ``%`` in it — a password with a URL-encoded character, ``%24``
for ``$`` — was an "invalid interpolation syntax" error, so on such an
installation no module could create or upgrade its tables.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.core import module_migrations


@pytest.mark.unit
def test_a_percent_in_the_password_reads_back_as_written(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / 'demo_mod' / 'migrations').mkdir(parents=True)
    monkeypatch.setattr(module_migrations, 'MODULES_ROOT', tmp_path)
    url = 'postgresql://inventari_user:p%24ss%25word@db:5432/inventari'

    config = module_migrations._build_alembic_config('demo_mod', url)

    assert config.get_main_option('sqlalchemy.url') == url
