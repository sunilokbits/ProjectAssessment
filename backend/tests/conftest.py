from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

FIXTURE_PACKS = ["_reference", "global", "industries/banking", "technologies/databricks", "project_types/customer_360"]

ADMIN = {"X-User-Name": "alice", "X-User-Role": "admin"}
REVIEWER = {"X-User-Name": "rita", "X-User-Role": "reviewer"}
ASSESSOR = {"X-User-Name": "sam", "X-User-Role": "assessor"}


@pytest.fixture()
def packs_dir(tmp_path: Path) -> Path:
    root = tmp_path / "domain_packs"
    for rel in FIXTURE_PACKS:
        shutil.copytree(ROOT / "domain_packs" / rel, root / rel)
    # minimal stub so tests don't depend on the full (separately authored) Azure pack
    write_pack(root, "technologies/azure", {"domain.yaml": "key: azure\nname: Azure\nkind: technology\nversion: 1.0.0\n"
                                                           "detection:\n  keywords: {azure: 3}\n"})
    return root


@pytest.fixture()
def client(tmp_path: Path, packs_dir: Path, monkeypatch):
    monkeypatch.setenv("PAT_DATABASE_URL", f"sqlite:///{(tmp_path / 'test.db').as_posix()}")
    monkeypatch.setenv("PAT_DOMAIN_PACKS_DIR", str(packs_dir))
    monkeypatch.setenv("PAT_AI_ENABLED", "false")
    from app import config, services

    config.get_settings.cache_clear()
    services.reload_reference()
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as c:
        yield c
    config.get_settings.cache_clear()
    services.reload_reference()


def write_pack(root: Path, rel: str, files: dict[str, str]) -> Path:
    d = root / rel
    d.mkdir(parents=True, exist_ok=True)
    for name, text in files.items():
        (d / name).write_text(text, encoding="utf-8")
    return d


def new_assessment(client, **classification) -> int:
    r = client.post("/api/assessments", json={"client_name": "Acme Bank", "project_name": "C360"}, headers=ASSESSOR)
    assert r.status_code == 201, r.text
    aid = r.json()["id"]
    if classification:
        r = client.post(f"/api/assessments/{aid}/classification", json=classification, headers=ASSESSOR)
        assert r.status_code == 200, r.text
    return aid


BANK_C360 = dict(primary_industry="banking", sub_domains=["retail_banking"], technologies=["databricks", "azure"],
                 project_types=["customer_360"], geography="IN", data_classifications=["pii", "financial"])
