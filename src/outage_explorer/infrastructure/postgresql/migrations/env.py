"""Alembic environment: only an explicitly supplied connection is permitted."""

from alembic import context
from sqlalchemy.engine import Connection


def run() -> None:
    connection = context.config.attributes.get("connection")
    if not isinstance(connection, Connection):
        raise RuntimeError("Migrations require an explicitly supplied connection")
    context.configure(connection=connection, transactional_ddl=True)
    with context.begin_transaction():
        context.run_migrations()


run()
