"""Copy every table from one database to another (e.g. SQLite -> Azure Database for PostgreSQL).

    python -m app.migrate_db --source sqlite:///path/assessment.db --target "postgresql://user:pw@host:5432/db?sslmode=require"

Creates the schema on the target, copies rows table by table in foreign-key order, then resets the
PostgreSQL id sequences. Refuses to write into a target that already has data unless --replace is given.
The target URL can also come from PAT_MIGRATE_TARGET so the password stays out of shell history.
"""
from __future__ import annotations

import argparse
import os
import sys

from sqlalchemy import Integer, create_engine, func, insert, select, text

from . import models  # noqa: F401  (register tables)
from .db import Base, normalise_url

BATCH = 500


def migrate(source: str, target: str, replace: bool = False) -> dict[str, int]:
    src = create_engine(normalise_url(source))
    dst = create_engine(normalise_url(target))
    tables = Base.metadata.sorted_tables
    Base.metadata.create_all(dst)
    with dst.connect() as c:
        existing = {t.name: c.execute(select(func.count()).select_from(t)).scalar_one() for t in tables}
    if any(existing.values()):
        if not replace:
            raise SystemExit(f"target already has data {[(k, v) for k, v in existing.items() if v]}; use --replace")
        Base.metadata.drop_all(dst)
        Base.metadata.create_all(dst)

    copied: dict[str, int] = {}
    with src.connect() as s, dst.begin() as d:
        for t in tables:
            rows = [dict(r._mapping) for r in s.execute(select(t))]
            for i in range(0, len(rows), BATCH):
                d.execute(insert(t), rows[i:i + BATCH])
            copied[t.name] = len(rows)
        if dst.dialect.name == "postgresql":
            for t in tables:
                pk = list(t.primary_key.columns)
                if len(pk) == 1 and isinstance(pk[0].type, Integer) and copied[t.name]:
                    d.execute(text(f"SELECT setval(pg_get_serial_sequence('{t.name}', '{pk[0].name}'), "
                                   f"(SELECT MAX({pk[0].name}) FROM {t.name}))"))
    with src.connect() as s, dst.connect() as d:
        for t in tables:
            a = s.execute(select(func.count()).select_from(t)).scalar_one()
            b = d.execute(select(func.count()).select_from(t)).scalar_one()
            if a != b:
                raise SystemExit(f"row count mismatch in {t.name}: source {a}, target {b}")
    return copied


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--source", required=True)
    p.add_argument("--target", default=os.environ.get("PAT_MIGRATE_TARGET"))
    p.add_argument("--replace", action="store_true", help="drop and recreate tables on the target first")
    a = p.parse_args()
    if not a.target:
        p.error("--target or PAT_MIGRATE_TARGET is required")
    for name, n in migrate(a.source, a.target, a.replace).items():
        print(f"{name:32} {n:6} rows")
    print("done - row counts verified")
    return 0


if __name__ == "__main__":
    sys.exit(main())
