from logging.config import fileConfig

from sqlalchemy import engine_from_config
from sqlalchemy import pool

from alembic import context
import os
# from dotenv import load_dotenv # Optional: if you use .env files for local dev
# load_dotenv() # Optional

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# add your model's MetaData object here
# for 'autogenerate' support
# from myapp import mymodel
# target_metadata = mymodel.Base.metadata
import sys
from os.path import abspath, dirname
sys.path.insert(0, dirname(dirname(abspath(__file__))))
from app.models import Base
target_metadata = Base.metadata

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
    # Get the base URL from alembic.ini, then override with DATABASE_URL if set
    ini_url = config.get_main_option("sqlalchemy.url")
    db_url = os.getenv("DATABASE_URL", ini_url)

    context.configure(
        url=db_url,
        target_metadata=target_metadata,
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
    # Construct the database URL from environment variables
    # Ensure DATABASE_URL is set in the environment where alembic commands are run.
    db_url = os.getenv("DATABASE_URL", config.get_main_option("sqlalchemy.url"))

    # If using a file like .env, ensure it's loaded before this point for local execution.
    # For production, DATABASE_URL should be set directly in the environment.

    # Get the Alembic config object
    alembic_config = context.config

    # Set the sqlalchemy.url in the config object dynamically
    alembic_config.set_main_option("sqlalchemy.url", db_url)

    connectable = engine_from_config(
        alembic_config.get_section(alembic_config.config_ini_section), # Use the modified config
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
