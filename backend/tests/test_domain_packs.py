"""Domain-pack validation, registry, versioning and expansion (32.3, 32.12, 33)."""
from __future__ import annotations

import yaml

from conftest import ADMIN, ASSESSOR, BANK_C360, ROOT, new_assessment, write_pack

BV = yaml.safe_load((ROOT / "domain_packs/industries/banking/domain.yaml").read_text(encoding="utf-8"))["version"]
_a, _b, _c = BV.split(".")
NEXT = f"{_a}.{_b}.{int(_c) + 1}"

AVIATION = {
    "domain.yaml": """
key: aviation
name: Aviation
kind: industry
version: 1.0.0
sub_domains:
  - {key: airline_ops, name: Airline Operations, keywords: [flight ops, crew scheduling]}
  - {key: mro, name: MRO, keywords: [maintenance repair overhaul]}
detection:
  keywords: {aircraft: 3, airline: 3, flight: 2}
""",
    "scoring.yaml": "dimensions:\n  - {key: airworthiness, name: Airworthiness Data, group: domain, weight: 1.5}\n",
    "questions.yaml": """
- {id: tail-data, text: "Is aircraft tail-level maintenance data available?", dimension: airworthiness, sub_domains: [mro], critical: true}
- {id: crew-rules, text: "Are crew duty-time rules digitised?", dimension: business_alignment, sub_domains: [airline_ops]}
""",
    "kpis.yaml": "- {id: otp, name: On-time performance, unit: '%'}\n",
    "compliance.yaml": "- {id: easa-part-145, name: EASA Part-145, geographies: [EU]}\n",
}


def test_builtin_packs_sync_and_catalog(client):
    cat = client.get("/api/catalog", headers=ASSESSOR).json()
    assert [i["key"] for i in cat["industries"]] == ["banking"]
    assert {t["key"] for t in cat["technologies"]} == {"databricks", "azure"}
    assert cat["industries"][0]["sub_domains"][0]["key"] == "retail_banking"
    assert any(g["code"] == "IN" for g in cat["geographies"])


def test_new_industry_without_code_change(client, packs_dir):
    """Requirement 33: dropping a new pack folder makes it selectable after sync + publish."""
    write_pack(packs_dir, "industries/aviation", AVIATION)
    rep = client.post("/api/admin/domain-packs/sync", headers=ADMIN).json()
    assert "industries/aviation" in rep["imported"], rep
    cat = client.get("/api/catalog", headers=ASSESSOR).json()
    assert "aviation" in [i["key"] for i in cat["industries"]]
    aid = new_assessment(client, primary_industry="aviation", sub_domains=["mro"], geography="DE")
    q = client.get(f"/api/assessments/{aid}/questionnaire", headers=ASSESSOR).json()["questions"]
    keys = {x["key"] for x in q}
    assert "aviation:tail-data" in keys and "aviation:crew-rules" not in keys  # sub-domain filtering
    assert next(x for x in q if x["key"] == "aviation:tail-data")["origin"] == "SUB-DOMAIN"
    comp = client.get(f"/api/assessments/{aid}/compliance", headers=ASSESSOR).json()["items"]
    assert any(c["key"] == "easa-part-145" for c in comp)
    dims = {d["key"] for d in client.get(f"/api/assessments/{aid}/dashboard", headers=ASSESSOR).json()["scores"]["dimensions"]}
    assert "airworthiness" in dims


def test_invalid_pack_rejected_with_clear_errors(client):
    bad = {
        "domain": {"key": "Bad Key", "name": "x", "kind": "industry", "version": "1.0"},
    }
    r = client.post("/api/admin/domain-packs/validate", json={"content": bad}, headers=ADMIN).json()
    assert r["valid"] is False
    locs = {e["location"] for e in r["errors"]}
    assert "domain.key" in locs and "domain.version" in locs

    bad2 = {
        "domain": {"key": "aviation", "name": "Aviation", "kind": "industry", "sub_domains": [{"key": "mro", "name": "MRO"}]},
        "questions": [{"id": "q1", "text": "x?", "dimension": "nope", "sub_domains": ["cargo"]},
                      {"id": "q1", "text": "dup", "dimension": "business_alignment"}],
        "kpis": [{"id": "otp", "name": "OTP", "target": "95%"}],
    }
    r = client.post("/api/admin/domain-packs/validate", json={"content": bad2}, headers=ADMIN).json()
    msgs = " | ".join(f"{e['location']}: {e['message']}" for e in r["errors"])
    assert "target" in msgs  # KPI targets are not allowed in packs
    # cross-reference errors are reported once the structural ones are fixed
    bad2["kpis"] = [{"id": "otp", "name": "OTP"}]
    r = client.post("/api/admin/domain-packs/validate", json={"content": bad2}, headers=ADMIN).json()
    msgs = " | ".join(f"{e['location']}: {e['message']}" for e in r["errors"])
    assert "unknown sub-domain 'cargo'" in msgs and "duplicate id 'q1'" in msgs
    bad2["questions"] = [{"id": "q1", "text": "x?", "dimension": "nope"}]
    r = client.post("/api/admin/domain-packs/validate", json={"content": bad2}, headers=ADMIN).json()
    assert "unknown scoring dimension 'nope'" in r["errors"][0]["message"]


def test_upload_and_admin_only(client):
    bundle = {"domain": yaml.safe_load(AVIATION["domain.yaml"]), "scoring": yaml.safe_load(AVIATION["scoring.yaml"]),
              "questions": yaml.safe_load(AVIATION["questions.yaml"])}
    data = yaml.safe_dump(bundle).encode()
    r = client.post("/api/admin/domain-packs/upload", files={"file": ("aviation.yaml", data)}, headers=ASSESSOR)
    assert r.status_code == 403
    r = client.post("/api/admin/domain-packs/upload", files={"file": ("aviation.yaml", data)}, headers=ADMIN)
    assert r.status_code == 201, r.text
    assert r.json()["status"] == "draft"
    # drafts are not selectable
    assert "aviation" not in [i["key"] for i in client.get("/api/catalog", headers=ASSESSOR).json()["industries"]]
    r = client.post("/api/admin/domain-packs/aviation/versions/1.0.0/publish", headers=ADMIN)
    assert r.json()["status"] == "published"
    assert "aviation" in [i["key"] for i in client.get("/api/catalog", headers=ASSESSOR).json()["industries"]]
    r = client.post("/api/admin/domain-packs/upload", files={"file": ("bad.yaml", b"domain: [unclosed")}, headers=ADMIN)
    assert r.status_code == 422 and r.json()["detail"]["errors"]


def test_published_versions_immutable_and_pinned(client):
    aid = new_assessment(client, **BANK_C360)
    # editing a published version is refused
    r = client.put(f"/api/admin/domain-packs/banking/versions/{BV}/sections/kpis", json={"value": []}, headers=ADMIN)
    assert r.status_code == 409
    # clone -> edit draft -> publish 1.0.1
    r = client.post(f"/api/admin/domain-packs/banking/versions/{BV}/clone", headers=ADMIN)
    assert r.status_code == 201 and r.json()["version"] == NEXT
    full = client.get(f"/api/admin/domain-packs/banking/versions/{NEXT}", headers=ADMIN).json()["content"]
    qs = full["questions"] + [{"id": "new-q", "text": "Is open banking API consent tracked?", "dimension": "regulatory_readiness"}]
    r = client.put(f"/api/admin/domain-packs/banking/versions/{NEXT}/sections/questions", json={"value": qs}, headers=ADMIN)
    assert r.status_code == 200, r.text
    client.post(f"/api/admin/domain-packs/banking/versions/{NEXT}/publish", headers=ADMIN)

    old = {q["key"] for q in client.get(f"/api/assessments/{aid}/questionnaire", headers=ASSESSOR).json()["questions"]}
    assert "banking:new-q" not in old  # existing assessment keeps 1.0.0
    a = client.get(f"/api/assessments/{aid}", headers=ASSESSOR).json()
    bm = next(m for m in a["mappings"] if m["pack_key"] == "banking")
    assert bm["version"] == BV and bm["latest_published"] == NEXT
    # re-confirming classification still keeps the pinned version
    client.post(f"/api/assessments/{aid}/classification", json=BANK_C360, headers=ASSESSOR)
    assert "banking:new-q" not in {q["key"] for q in client.get(f"/api/assessments/{aid}/questionnaire", headers=ASSESSOR).json()["questions"]}

    aid2 = new_assessment(client, **BANK_C360)
    assert "banking:new-q" in {q["key"] for q in client.get(f"/api/assessments/{aid2}/questionnaire", headers=ASSESSOR).json()["questions"]}
    # explicit upgrade by a reviewer
    r = client.post(f"/api/assessments/{aid}/mappings/banking/upgrade", headers={"X-User-Name": "r", "X-User-Role": "reviewer"})
    assert r.status_code == 200
    assert "banking:new-q" in {q["key"] for q in client.get(f"/api/assessments/{aid}/questionnaire", headers=ASSESSOR).json()["questions"]}


def test_disable_domain_blocks_new_selection_only(client):
    aid = new_assessment(client, **BANK_C360)
    client.patch("/api/admin/domain-packs/banking", json={"enabled": False}, headers=ADMIN)
    assert client.get("/api/catalog", headers=ASSESSOR).json()["industries"] == []
    r = client.post("/api/assessments", json={"client_name": "B", "project_name": "P"}, headers=ASSESSOR)
    r = client.post(f"/api/assessments/{r.json()['id']}/classification", json=BANK_C360, headers=ASSESSOR)
    assert r.status_code == 422 and "disabled" in r.text
    # existing assessment still works
    assert client.get(f"/api/assessments/{aid}/dashboard", headers=ASSESSOR).status_code == 200


def test_unpublish_keeps_existing_assessments(client):
    aid = new_assessment(client, **BANK_C360)
    r = client.post(f"/api/admin/domain-packs/banking/versions/{BV}/unpublish", headers=ADMIN)
    assert r.json()["status"] == "unpublished"
    assert r.json()["assessments_using"] == 1
    assert client.get(f"/api/assessments/{aid}/questionnaire", headers=ASSESSOR).status_code == 200
    assert client.get("/api/catalog", headers=ASSESSOR).json()["industries"] == []


def test_stored_versions_load_even_if_rules_tighten(client):
    """A pinned version stored before a stricter authoring rule existed must still load."""
    from app.engine.registry import content_of
    from app.models import DomainPackVersion

    class V:  # minimal stand-in for a stored version row
        content = {"domain": {"key": "legacy", "name": "Legacy", "kind": "industry",
                              "source_systems": ["Core (A", "B)"]}}
    assert content_of(V()).domain.key == "legacy"
    r = client.post("/api/admin/domain-packs/validate", json={"content": V.content}, headers=ADMIN).json()
    assert r["valid"] is False and "unbalanced parentheses" in r["errors"][0]["message"]
    assert DomainPackVersion  # imported model exists
