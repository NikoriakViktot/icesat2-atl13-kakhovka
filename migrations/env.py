"""Alembic environment: the URL comes from DATABASE_URL (or -x url=...)."""

from __future__ import annotations

import os

from alembic import context
from sqlalchemy import create_engine


def _url() -> str:
    url = context.get_x_argument(as_dictionary=True).get("url") or os.environ["DATABASE_URL"]
    # The service uses plain psycopg URLs; SQLAlchemy needs the driver spelled out.
    if url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url[len("postgresql://"):]
    return url


def run_migrations_online() -> None:
    engine = create_engine(_url())
    with engine.connect() as conn:
        context.configure(connection=conn, version_table_schema="public")
        with context.begin_transaction():
            context.run_migrations()


run_migrations_online()
