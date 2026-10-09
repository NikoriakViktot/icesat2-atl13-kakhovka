"""Alembic environment: the URL comes from DATABASE_URL (or -x url=...).

Everything of this service lives in the `icesat2` schema, including the version table
(`icesat2.alembic_version`), so it can share a database with other applications (e.g.
the platform's `geohydro` database) without touching their objects.
"""

from __future__ import annotations

import os

from alembic import context
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, text

SCHEMA = "icesat2"


def _url() -> str:
    url = context.get_x_argument(as_dictionary=True).get("url") or os.environ["DATABASE_URL"]
    # The service uses plain psycopg URLs; SQLAlchemy needs the driver spelled out.
    if url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url[len("postgresql://"):]
    return url


def _adopt_public_version_table(conn) -> None:
    """Deployments before the move kept `alembic_version` in `public`. Move it into our
    schema only if the revision recorded there is one of ours."""
    if conn.execute(text("SELECT to_regclass('public.alembic_version')")).scalar() is None:
        return
    if conn.execute(text(f"SELECT to_regclass('{SCHEMA}.alembic_version')")).scalar() is not None:
        return
    ours = {r.revision for r in ScriptDirectory.from_config(context.config).walk_revisions()}
    current = {row[0] for row in conn.execute(text("SELECT version_num FROM public.alembic_version"))}
    if current and current <= ours:
        conn.execute(text(f"ALTER TABLE public.alembic_version SET SCHEMA {SCHEMA}"))


def run_migrations_online() -> None:
    engine = create_engine(_url())
    with engine.connect() as conn:
        conn.execute(text(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}"))
        _adopt_public_version_table(conn)
        conn.commit()
        context.configure(connection=conn, version_table_schema=SCHEMA)
        with context.begin_transaction():
            context.run_migrations()


run_migrations_online()
