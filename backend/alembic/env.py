import os
from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool

from alembic import context

# Import target_metadata from ORM models so Alembic can detect model changes
from app.models.base import metadata as target_metadata

# Model modules register their tables on Base.metadata only when imported.
import app.models.dimensions  # noqa: F401
import app.models.facts  # noqa: F401
import app.models.ml_results  # noqa: F401

# Tables created by migrations without an ORM model, plus materialized views.
UNMANAGED_TABLES = {"audit_ingestao"}


def include_object(object, name, type_, reflected, compare_to):
    if type_ == "table" and (name in UNMANAGED_TABLES or name.startswith("mv_")):
        return False
    return True


# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Read DATABASE_URL_SYNC from environment — explicit config enforced, no default
try:
    url = os.environ["DATABASE_URL_SYNC"]
except KeyError as exc:
    raise KeyError(
        "DATABASE_URL_SYNC environment variable is required for Alembic migrations. "
        "Set it to a psycopg2 URL: postgresql+psycopg2://user:password@host:5432/dbname"
    ) from exc

config.set_main_option("sqlalchemy.url", url)


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.
    """
    context.configure(
        url=url,
        target_metadata=target_metadata,
        include_object=include_object,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
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
            compare_type=True,
            compare_server_default=True,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
