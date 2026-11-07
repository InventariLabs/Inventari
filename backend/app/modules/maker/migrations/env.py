"""Per-module Alembic environment for maker.

Uses a separate version_table (alembic_version_maker) so that
core migrations and module migrations are completely independent.
"""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

config = context.config

if config.config_file_name is not None:
    # disable_existing_loggers=False: the default (True) switches off every
    # logger created before this call. Harmless for the alembic CLI, but tests
    # run migrations in-process, and from then on the app's own loggers stay
    # silent for the rest of the session.
    fileConfig(config.config_file_name, disable_existing_loggers=False)

from app.core.db_facade import Base  # noqa: E402

target_metadata = Base.metadata

MODULE_NAME = 'maker'
VERSION_TABLE = f'alembic_version_{MODULE_NAME}'


def run_migrations_offline() -> None:
    url = config.get_main_option('sqlalchemy.url')
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={'paramstyle': 'named'},
        version_table=VERSION_TABLE,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix='sqlalchemy.',
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            version_table=VERSION_TABLE,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
