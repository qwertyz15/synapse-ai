from typing import Any, Literal

from alembic import context
from alembic.autogenerate.api import AutogenContext
from sqlalchemy import create_engine

from db.engine import database_url
from db.models import Base, UTCDateTime

target_metadata = Base.metadata


def render_item(type_: str, obj: Any, autogen_context: AutogenContext) -> Literal[False] | str:
    # Keep migrations free of app imports: write the custom UTC type as a plain DateTime.
    if type_ == "type" and isinstance(obj, UTCDateTime):
        return "sa.DateTime(timezone=True)"
    return False


def configure(**kwargs: Any) -> None:
    context.configure(
        target_metadata=target_metadata, render_as_batch=True, render_item=render_item, **kwargs
    )


def run_migrations_online() -> None:
    # The app passes its own connection; the `alembic` CLI connects from settings.
    connection = context.config.attributes.get("connection")
    if connection is not None:
        configure(connection=connection)
        with context.begin_transaction():
            context.run_migrations()
        return
    with create_engine(database_url()).connect() as connection:
        configure(connection=connection)
        with context.begin_transaction():
            context.run_migrations()
        connection.commit()


def run_migrations_offline() -> None:
    configure(url=database_url(), literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
