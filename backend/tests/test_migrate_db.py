"""Database copy used to move SQLite data into Azure Database for PostgreSQL."""
from __future__ import annotations

import pytest
from conftest import BANK_C360, new_assessment


def test_migrate_copies_all_rows_and_refuses_non_empty_target(client, tmp_path):
    import os

    from app.migrate_db import migrate

    if os.environ.get("PAT_TEST_DATABASE_URL"):
        pytest.skip("source must be SQLite")
    aid = new_assessment(client, **BANK_C360)
    src = os.environ["PAT_DATABASE_URL"]
    dst = f"sqlite:///{(tmp_path / 'copy.db').as_posix()}"
    copied = migrate(src, dst)
    assert copied["assessment"] == 1 and copied["domain_pack"] > 0
    with pytest.raises(SystemExit):
        migrate(src, dst)
    assert migrate(src, dst, replace=True)["assessment"] == 1
    from sqlalchemy import create_engine, text
    with create_engine(dst).connect() as c:
        assert c.execute(text("select client_name from assessment where id=:i"), {"i": aid}).scalar() == "Acme Bank"
