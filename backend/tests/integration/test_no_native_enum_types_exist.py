"""No PostgreSQL enum type exists: an enumerated value is text.

Core stores every enum as text and lets the application own the vocabulary.
A native type makes the next label an ``ALTER TYPE ... ADD VALUE`` — which
cannot run inside the transaction a migration runs in — in every installation,
and a label's spelling is then a second vocabulary that can drift from the
model's (it did: uppercase in one module, lowercase in another). A column that
must be closed over a set of values is ``varchar`` with a CHECK constraint.

Two halves: the models declare no native ``Enum`` column, and a database built
the way an install builds it (core chain, then every module's chain) holds no
enum type. The suite's own schema comes from ``create_all``, so only the second
half sees what the migrations do.
"""

from __future__ import annotations

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Enum as SAEnum
from sqlalchemy import create_engine, text

from app.core.db_isolation import isolated_db_url

pytestmark = pytest.mark.integration


def test_no_model_column_is_a_native_enum():
    import app.core.template_models  # noqa: F401
    import app.models  # noqa: F401
    from app.database import Base

    assert 'stock_takes' in Base.metadata.tables, (
        'module models not loaded — gate is blind'
    )
    native = sorted(
        f'{table.name}.{column.name}'
        for table in Base.metadata.tables.values()
        for column in table.columns
        if isinstance(column.type, SAEnum) and column.type.native_enum
    )
    assert not native, (
        f'these columns are native PostgreSQL enums, declare them with '
        f'native_enum=False and a CHECK constraint: {native}'
    )


def test_the_migrations_build_no_enum_type(monkeypatch):
    with isolated_db_url('schema') as url:
        monkeypatch.setenv('DATABASE_URL', url)
        command.upgrade(Config('alembic.ini'), 'head')

        from app.cli.commands_db import upgrade_modules

        upgrade_modules()

        engine = create_engine(url)
        with engine.connect() as conn:
            types = (
                conn.execute(
                    text(
                        'SELECT t.typname FROM pg_type t '
                        "WHERE t.typtype = 'e' ORDER BY t.typname"
                    )
                )
                .scalars()
                .all()
            )
        engine.dispose()

    assert not types, f'the migrations leave native enum types behind: {types}'
