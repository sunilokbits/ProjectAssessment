"""Layered questionnaire, dedupe, cross-domain merge, compliance, scoring, detection, architecture."""
from __future__ import annotations

from conftest import ADMIN, ASSESSOR, BANK_C360, REVIEWER, new_assessment, write_pack

RETAIL_FIN = {
    "domain.yaml": """
key: retail
name: Retail
kind: industry
version: 1.0.0
sub_domains:
  - {key: ecommerce, name: E-commerce}
detection:
  keywords: {sku: 3, basket: 3, store: 2}
""",
    "questions.yaml": """
- {id: sku-master, text: "Is there a single product / SKU master?", dimension: data_quality}
- {id: objectives, text: "Are the business objectives and expected outcomes documented and agreed by the sponsor?", dimension: business_alignment}
""",
    "recommendations.yaml": """
- {id: big-bang, title: Big-bang cut-over at season end, decision_key: delivery_approach, decision_option: big_bang}
""",
}


def _questions(client, aid):
    return client.get(f"/api/assessments/{aid}/questionnaire", headers=ASSESSOR).json()["questions"]


def test_four_layer_questionnaire_with_origins(client):
    aid = new_assessment(client, **BANK_C360)
    qs = _questions(client, aid)
    origins = {q["origin"] for q in qs}
    assert {"GLOBAL", "INDUSTRY", "SUB-DOMAIN", "TECHNOLOGY", "PROJECT"} <= origins
    keys = {q["key"] for q in qs}
    # sub-domain filtering: retail banking applies, cards-only question does not
    assert "banking:customer-consent" in keys and "banking:card-data-scope" not in keys
    # 'when' conditions: cloud approval question appears because databricks/azure selected
    assert "banking:outsourcing-cloud-approval" in keys
    q = next(q for q in qs if q["key"] == "banking:outsourcing-cloud-approval")
    assert any("technology" in r for r in q["applies_because"])
    # origin order: GLOBAL first ... PROJECT last
    order = ["GLOBAL", "INDUSTRY", "SUB-DOMAIN", "TECHNOLOGY", "PROJECT", "AI-DISCOVERED"]
    seq = [order.index(q["origin"]) for q in qs]
    assert seq == sorted(seq)


def test_duplicate_questions_removed_with_provenance(client):
    aid = new_assessment(client, **BANK_C360)
    qs = _questions(client, aid)
    skills = [q for q in qs if q["key"] in ("global:client-team-skills", "databricks:dbx-skills")]
    assert len(skills) == 1, "equivalence_key client_skills must dedupe"
    kept = skills[0]
    assert kept["key"] == "databricks:dbx-skills"  # technology beats global
    assert kept["merged_from"][0]["key"] == "global:client-team-skills"
    rs = client.get(f"/api/assessments/{aid}/rule-sources", headers=ASSESSOR).json()
    dup = next(r for r in rs if r["rule_key"] == "global:client-team-skills")
    assert dup["status"] == "duplicate" and dup["merged_into"] == "databricks:dbx-skills"


def test_cross_domain_merge_semantic_dedupe_and_conflicts(client, packs_dir):
    write_pack(packs_dir, "industries/retail", RETAIL_FIN)
    client.post("/api/admin/domain-packs/sync", headers=ADMIN)
    aid = new_assessment(client, primary_industry="retail", sub_domains=["ecommerce"],
                         secondary_industries=[{"key": "banking", "sub_domains": ["cards"]}],
                         technologies=["databricks"], project_types=["customer_360"], geography="IN")
    qs = _questions(client, aid)
    keys = {q["key"] for q in qs}
    # semantically equivalent retail question merges with the global one; primary domain wins
    assert "retail:objectives" in keys and "global:business-objectives" not in keys
    obj = next(q for q in qs if q["key"] == "retail:objectives")
    assert any(m["key"] == "global:business-objectives" and "similar" in m["reason"] for m in obj["merged_from"])
    # secondary domain contributes its sub-domain questions
    assert "banking:card-data-scope" in keys
    assert next(q for q in qs if q["key"] == "banking:card-data-scope")["source"]["role"] == "secondary"

    rec = client.get(f"/api/assessments/{aid}/recommendations", headers=ASSESSOR).json()
    conflict = next(c for c in rec["conflicts"] if c["key"] == "delivery_approach")
    opts = {o["key"] for o in conflict["options"]}
    assert {"retail:big-bang", "banking:parallel-run", "global:mvp-first"} <= opts
    assert conflict["system_preferred"] == "retail:big-bang"  # primary domain priority
    assert conflict["status"] == "pending_review"
    # assessors cannot resolve; reviewers can
    url = f"/api/assessments/{aid}/conflicts/delivery_approach"
    assert client.put(url, json={"chosen": "banking:parallel-run", "rationale": "card data"}, headers=ASSESSOR).status_code == 403
    r = client.put(url, json={"chosen": "banking:parallel-run", "rationale": "regulated card data needs parallel run"}, headers=REVIEWER)
    assert r.status_code == 200
    conflict = next(c for c in client.get(f"/api/assessments/{aid}/recommendations", headers=ASSESSOR).json()["conflicts"]
                    if c["key"] == "delivery_approach")
    assert conflict["status"] == "resolved" and conflict["effective"] == "banking:parallel-run"


def test_compliance_suggestions_require_human_review(client):
    aid = new_assessment(client, **BANK_C360)
    comp = client.get(f"/api/assessments/{aid}/compliance", headers=ASSESSOR).json()
    keys = {c["key"]: c for c in comp["items"]}
    assert "india-dpdp" in keys and "rbi-it-governance" in keys and "rbi-outsourcing" in keys
    assert "gdpr" not in keys and "hipaa" not in keys and "pci-dss" not in keys  # no cardholder data selected
    assert all(c["status"] == "potentially_applicable" for c in comp["items"])
    assert "not legal advice" in comp["disclaimer"]
    url = f"/api/assessments/{aid}/compliance/india-dpdp"
    assert client.put(url, json={"status": "confirmed_applicable"}, headers=ASSESSOR).status_code == 403
    assert client.put(url, json={"status": "verified"}, headers=REVIEWER).status_code == 422  # evidence required
    assert client.put(url, json={"status": "unknown"}, headers=ASSESSOR).status_code == 200
    assert client.put(url, json={"status": "verified", "evidence": "DPO sign-off ref 123"}, headers=REVIEWER).status_code == 200
    item = next(c for c in client.get(f"/api/assessments/{aid}/compliance", headers=ASSESSOR).json()["items"] if c["key"] == "india-dpdp")
    assert item["status"] == "verified" and item["reviewer"] == "rita"


def test_scoring_transparent_and_comparable(client):
    aid = new_assessment(client, **BANK_C360)
    put = lambda k, v, ev="": client.put(f"/api/assessments/{aid}/answers/{k}", json={"value": v, "evidence": ev}, headers=ASSESSOR)
    put("global:business-objectives", "yes", "Charter v2")
    put("global:success-criteria", "no")
    put("banking:gl-reconciliation", "partial")
    put("databricks:unity-catalog", "yes")
    d = client.get(f"/api/assessments/{aid}/dashboard", headers=ASSESSOR).json()
    sc = d["scores"]
    ba = next(x for x in sc["dimensions"] if x["key"] == "business_alignment")
    # weights 2 (yes) and 1.5 (no) -> 2/3.5
    assert ba["score"] == round(100 * 2 / 3.5, 1) and ba["comparable"] is True
    fdg = next(x for x in sc["dimensions"] if x["key"] == "financial_data_governance")
    assert fdg["comparable"] is False and fdg["score"] == 50.0 and fdg["group"] == "domain"
    assert sc["overall"]["comparable"] is not None and sc["overall"]["domain_adjusted"] is not None
    assert {g["group"] for g in sc["groups"]} >= {"business", "data", "domain", "technology", "security", "delivery"}
    assert all("label" in g["rag"] for g in sc["groups"])
    assert "rag_thresholds" in sc["method"]
    assert any(g["question_key"] == "global:executive-sponsor" for g in sc["critical_gaps"])
    s = d["summary"]
    assert s["evidence_coverage"]["answered_with_evidence"] == 25.0
    assert d["classification"]["industry"][0]["name"] == "Banking and Financial Services"
    assert d["classification"]["geography"]["name"] == "India"


def test_kpis_never_invent_targets(client):
    aid = new_assessment(client, **BANK_C360)
    kpis = client.get(f"/api/assessments/{aid}/kpis", headers=ASSESSOR).json()
    assert all(k["client_target"] is None and k["status"] == "suggested" for k in kpis)
    assert "banking:npa-ratio" not in {k["key"] for k in kpis}  # lending-only KPI filtered by sub-domain
    url = f"/api/assessments/{aid}/kpis/banking:fraud-rate"
    assert client.put(url, json={"status": "confirmed", "client_target": "< 5 bps"}, headers=ASSESSOR).status_code == 422
    assert client.put(url, json={"status": "confirmed", "client_target": "< 5 bps", "target_source": "RFP section 4.2"},
                      headers=ASSESSOR).status_code == 200


def test_detection_suggests_but_never_locks(client):
    aid = new_assessment(client)
    doc = ("RFP: The Bank requires a Customer 360 / single customer view for retail banking customers across savings "
           "account, current account and mobile banking channels. KYC and AML attributes must be included. "
           "The solution shall be built on Azure Databricks with Unity Catalog and Delta Lake, with Power BI reporting. "
           "Data must be available in near real-time.")
    client.post(f"/api/assessments/{aid}/documents", data={"text": doc, "filename": "rfp.txt"}, headers=ASSESSOR)
    det = client.post(f"/api/assessments/{aid}/detect", headers=ASSESSOR).json()
    assert det["industry"]["key"] == "banking" and det["requires_confirmation"] is True
    assert 0 < det["industry"]["confidence"] <= 0.99
    assert det["sub_domains"][0]["key"] == "retail_banking"
    assert "databricks" in {t["key"] for t in det["technologies"]}
    assert "customer_360" in {t["key"] for t in det["project_types"]}
    a = client.get(f"/api/assessments/{aid}", headers=ASSESSOR).json()
    assert a["status"] == "classification_pending" and a["classification"] == {} and a["mappings"] == []
    # user changes the suggestion (here: confirms with an extra geography) -> recorded
    client.post(f"/api/assessments/{aid}/classification", json=BANK_C360, headers=ASSESSOR)
    assert client.get(f"/api/assessments/{aid}/detect", headers=ASSESSOR).json()["status"] == "confirmed"

    # domain-aware extraction + AI-discovered (rules) questions
    r = client.post(f"/api/assessments/{aid}/process-documents", headers=ASSESSOR).json()
    assert r["requirements"] >= 2
    reqs = client.get(f"/api/assessments/{aid}/requirements", headers=ASSESSOR).json()
    terms = {t["term"] for rq in reqs for t in rq["domain_terms"]}
    assert {"KYC", "AML", "Customer"} <= terms
    qs = _questions(client, aid)
    ai = [q for q in qs if q["origin"] == "AI-DISCOVERED"]
    assert any("real-time" in q["text"] for q in ai)


def test_architecture_only_supported_components(client):
    aid = new_assessment(client, **BANK_C360)
    arch = client.get(f"/api/assessments/{aid}/architecture", headers=ASSESSOR).json()
    dbx = next(p for p in arch["patterns"] if p["key"] == "databricks:databricks-medallion")
    included = {c["id"] for layer in dbx["layers"] for c in layer["components"]}
    excluded = {c["id"] for c in dbx["excluded_components"]}
    assert "adls" in included and "s3" in excluded and "gcs" in excluded  # Azure selected
    assert "powerbi" in excluded and "vector-search" in excluded  # not required
    bank = next(p for p in arch["patterns"] if p["key"] == "banking:regulated-lakehouse")
    b_in = {c["id"] for layer in bank["layers"] for c in layer["components"]}
    assert "customer-golden-record" in b_in and "pii-tokenisation" in b_in and "pci-segment" not in b_in


def test_ai_context_uses_domain_pack(client):
    aid = new_assessment(client, **BANK_C360)
    ctx = client.get(f"/api/assessments/{aid}/ai-context", headers=ASSESSOR).json()
    sp = ctx["system_prompt"]
    assert "Industry: Banking and Financial Services" in sp and "Sub-domain: Retail Banking" in sp
    assert "Geography: India" in sp and "Databricks" in sp and "Stage: Discovery" in sp
    assert "Domain Pack configuration" in sp and "KYC" in sp
    assert "Never state that the client IS compliant" in sp


def test_demo_seed_and_portfolio(client, packs_dir):
    for k in ("power_bi", "data_governance"):
        write_pack(packs_dir, f"technologies/{k}", {"domain.yaml": f"key: {k}\nname: {k}\nkind: technology\nversion: 1.0.0\n"})
    client.post("/api/admin/domain-packs/sync", headers=ADMIN)
    assert client.post("/api/demo/seed", headers=ASSESSOR).status_code == 403
    r = client.post("/api/demo/seed", headers=ADMIN).json()
    # the test fixture only has banking/databricks/azure/customer_360 -> other scenarios are skipped, not errors
    assert [c["client"] for c in r["created"]] == ["Meridian Bank"] and len(r["skipped"]) == 4
    p = client.get("/api/portfolio", headers=ASSESSOR).json()
    row = p["assessments"][0]
    assert row["demo"] and row["industry"]["key"] == "banking" and row["answered"] > 0
    assert row["overall"]["comparable"] is not None and "domain" in row["groups"]
    assert p["platform"]["packs_by_kind"]["industry"] == 1 and p["platform"]["industries"][0]["sub_domains"]
    # re-seeding replaces demo data instead of duplicating it
    client.post("/api/demo/seed", headers=ADMIN)
    assert len(client.get("/api/portfolio", headers=ASSESSOR).json()["assessments"]) == 1
    assert client.delete("/api/demo/seed", headers=ADMIN).json()["deleted"] == 1
