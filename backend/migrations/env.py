from logging.config import fileConfig
import os

from sqlalchemy import engine_from_config
from sqlalchemy import pool

from alembic import context

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Override sqlalchemy.url with DATABASE_URL from environment
database_url = os.getenv("DATABASE_URL")
if database_url:
    config.set_main_option("sqlalchemy.url", database_url)

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    # disable_existing_loggers=False: the default (True) switches off every
    # logger created before this call. Harmless for the alembic CLI, but tests
    # run migrations in-process, and from then on the app's own loggers stay
    # silent for the rest of the session.
    fileConfig(config.config_file_name, disable_existing_loggers=False)

# The models autogenerate compares against, and what it leaves out: the
# version tables of module chains and the indexes migrations build by hand.
from app.core.autogenerate_scope import include_object, load_model_metadata

target_metadata = load_model_metadata()


def _skip_an_empty_revision(context, revision, directives) -> None:
    """Write no file when autogenerate found no model change.

    An empty revision is a file a contributor would commit and apply for
    nothing; ``manage.py db migrate`` reports that none was written. A
    hand-written revision never gets here: without ``revision_environment``
    in alembic.ini, ``alembic revision`` runs this file only to autogenerate.
    """
    if directives[0].upgrade_ops.is_empty():
        directives[:] = []


# other values from the config, defined by the needs of env.py,
# can be acquired:
# my_important_option = config.get_main_option("my_important_option")
# ... etc.


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.

    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        include_object=include_object,
        process_revision_directives=_skip_an_empty_revision,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode.

    In this scenario we need to create an Engine
    and associate a connection with the context.

    """
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            include_object=include_object,
            process_revision_directives=_skip_an_empty_revision,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
