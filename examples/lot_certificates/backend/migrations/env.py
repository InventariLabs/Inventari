"""Alembic environment for this module's own migration chain.

The chain is recorded in ``alembic_version_lot_certificates``, apart from the
platform's ``alembic_version``: ``manage.py db upgrade-modules`` applies this
one, and neither waits for the other.
"""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

# Importing the model declares its table on the module base's metadata —
# the metadata this chain compares against.
from app.modules.lot_certificates.models import LotCertificate

config = context.config

if config.config_file_name is not None:
    # disable_existing_loggers=False: the default switches off every logger
    # created before this call, and the platform's loggers are older than it.
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = LotCertificate.metadata

VERSION_TABLE = 'alembic_version_lot_certificates'


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option('sqlalchemy.url'),
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
