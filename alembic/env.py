from logging.config import fileConfig

from sqlalchemy import engine_from_config
from sqlalchemy import pool

from alembic import context

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

from app.config import settings
from app.database import Base
import app.models  # noqa: F401 - registers all models with Base

target_metadata = Base.metadata


def _resolve_sqlalchemy_url() -> str:
    """Resolve migration database URL with explicit Alembic override precedence.

    During setup provisioning we inject ``sqlalchemy.url`` directly into the
    Alembic config object. That value must take precedence over ``settings``
    because ``settings.database_url`` can be intentionally empty before
    provisioning completes.
    """
    configured_url = config.get_main_option("sqlalchemy.url")
    if configured_url:
        return configured_url

    if settings.database_url:
        return settings.database_url

    raise RuntimeError(
        "No database URL configured for Alembic migrations. "
        "Set sqlalchemy.url or DATABASE_URL before running migrations."
    )


def run_migrations_offline() -> None:
    url = _resolve_sqlalchemy_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    configuration = config.get_section(config.config_ini_section, {})
    configuration["sqlalchemy.url"] = _resolve_sqlalchemy_url()
    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection, target_metadata=target_metadata
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
