"""``pending_core_revisions`` names what ``db upgrade`` is about to apply."""

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine

from app.core.db_isolation import isolated_db_url
from app.core.migration_doctor import pending_core_revisions

pytestmark = pytest.mark.integration


def test_a_database_behind_head_lists_the_revisions_after_its_own(monkeypatch):
    with isolated_db_url('pendingcore') as url:
        monkeypatch.setenv('DATABASE_URL', url)
        config = Config('alembic.ini')
        command.upgrade(config, 'head')
        engine = create_engine(url)
        try:
            at_head = pending_core_revisions(engine)
            command.stamp(config, 'notifinbox01')
            behind = pending_core_revisions(engine)
        finally:
            engine.dispose()

    assert at_head == []
    assert behind[0] == 'aicost01'
