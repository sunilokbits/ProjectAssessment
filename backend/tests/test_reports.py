"""Report generation: prompt-driven content, Insight PPTX deck and analysis document."""
from __future__ import annotations

import io

from conftest import ADMIN, ASSESSOR, BANK_C360, new_assessment


def test_report_options_and_classification_gate(client):
    opts = client.get("/api/reports/options", headers=ASSESSOR).json()
    assert "battle_cards" in opts["sections"] and opts["ai_available"] is False
    aid = new_assessment(client)  # not classified yet
    r = client.post(f"/api/assessments/{aid}/reports/generate", json={"prompt": "x"}, headers=ASSESSOR)
    assert r.status_code == 409


def test_generate_without_ai_applies_prompt_sections(client):
    aid = new_assessment(client, **BANK_C360)
    r = client.post(f"/api/assessments/{aid}/reports/generate",
                    json={"prompt": "Leadership deck, add battle cards, without the roadmap"}, headers=ASSESSOR)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["method"] == "template"
    assert any("AI is not configured" in w for w in body["warnings"])
    secs = body["content"]["sections"]
    assert "battle_cards" in secs and "roadmap" not in secs
    c = body["content"]
    assert "Acme Bank" in c["title"]
    assert any("Banking" in k for k in c["findings"]["key_findings"])
    assert any(a["name"].startswith("DBx Migrator") for a in c["accelerators"]["items"])  # databricks selected
    assert c["approach"]["framework_name"] == "DRIVE"
    assert [s["letter"] for s in c["approach"]["stages"]] == list("DRIVE")
    assert "PROVE" not in str(c)
    bad = client.post(f"/api/assessments/{aid}/reports/generate", json={"sections": ["nope"]}, headers=ASSESSOR)
    assert bad.status_code == 422


def test_download_pptx_and_docx(client):
    from docx import Document
    from pptx import Presentation

    aid = new_assessment(client, **BANK_C360)
    content = client.post(f"/api/assessments/{aid}/reports/generate", json={"prompt": "include battle cards"},
                          headers=ASSESSOR).json()["content"]
    content["title"] = "Acme Bank Customer 360 proposal"  # user edits are honoured
    r = client.post(f"/api/assessments/{aid}/reports/pptx", json={"content": content}, headers=ADMIN)
    assert r.status_code == 200, r.text
    assert "Acme_Bank_Insight_Proposal.pptx" in r.headers["content-disposition"]
    prs = Presentation(io.BytesIO(r.content))
    texts = [sh.text_frame.text for s in prs.slides for sh in s.shapes if sh.has_text_frame]
    assert "Acme Bank Customer 360 proposal" in texts
    assert any("BID TEAM ONLY" in t for t in texts)
    assert len(prs.slides) >= 12
    xml = b"".join(s.part.blob for s in prs.slides)
    assert b"<p:transition" in xml and b"<p:timing" in xml

    r = client.post(f"/api/assessments/{aid}/reports/docx", json={"prompt": ""}, headers=ADMIN)
    assert r.status_code == 200, r.text
    doc = Document(io.BytesIO(r.content))
    heads = [p.text for p in doc.paragraphs if p.style.name.startswith("Heading")]
    assert "3. Readiness assessment" in heads and "5. Compliance considerations" in heads
    bad = client.post(f"/api/assessments/{aid}/reports/pptx", json={"content": {"title": "x"}}, headers=ADMIN)
    assert bad.status_code == 422


def test_ai_generation_uses_prompt_and_falls_back(client, monkeypatch):
    from app.engine import llm
    from app.reports import generator

    aid = new_assessment(client, **BANK_C360)
    seen = {}

    def fake_complete(system, user, schema, max_tokens=16000):
        seen["user"], seen["schema"] = user, schema
        draft = user.split("<draft_content>\n", 1)[1].split("\n</draft_content>", 1)[0]
        import json
        out = json.loads(draft)
        out["title"] = "AI tailored title"
        out["sections"] = ["summary", "value", "battle_cards", "bogus"]
        return out

    monkeypatch.setattr(llm, "available", lambda: True)
    monkeypatch.setattr(llm, "complete_json", fake_complete)
    body = client.post(f"/api/assessments/{aid}/reports/generate", json={"prompt": "Focus on ROI for the CFO"},
                       headers=ASSESSOR).json()
    assert body["method"] == "ai" and body["content"]["title"] == "AI tailored title"
    assert body["content"]["sections"] == ["summary", "value", "battle_cards"]
    assert "Focus on ROI for the CFO" in seen["user"] and "<assessment_context>" in seen["user"]
    assert seen["schema"]["additionalProperties"] is False

    monkeypatch.setattr(llm, "complete_json", lambda *a, **k: None)
    body = client.post(f"/api/assessments/{aid}/reports/generate", json={"prompt": "x"}, headers=ASSESSOR).json()
    assert body["method"] == "template" and any("AI call failed" in w for w in body["warnings"])
    assert generator.strict_json_schema  # imported for schema use


def test_questionnaire_excel_download(client):
    from openpyxl import load_workbook

    aid = new_assessment(client, **BANK_C360)
    qs = client.get(f"/api/assessments/{aid}/questionnaire", headers=ASSESSOR).json()["questions"]
    first = qs[0]
    client.put(f"/api/assessments/{aid}/answers/{first['key']}", json={"value": "yes", "evidence": "Charter v2"},
               headers=ASSESSOR)
    r = client.get(f"/api/assessments/{aid}/questionnaire.xlsx", headers={"X-User-Name": "v", "X-User-Role": "viewer"})
    assert r.status_code == 200, r.text
    assert "Acme_Bank_Assessment_Questionnaire.xlsx" in r.headers["content-disposition"]
    wb = load_workbook(io.BytesIO(r.content))
    assert wb.sheetnames == ["Cover", "Questionnaire", "Summary"]
    ws = wb["Questionnaire"]
    head = [c.value for c in ws[1]]
    assert {"Question", "Answer", "Evidence / reference", "Origin", "Critical"} <= set(head)
    rows = {row[head.index("Question ID")]: row for row in ws.iter_rows(min_row=2, values_only=True)}
    assert len(rows) == len(qs)  # every question, nothing dropped
    row = rows[first["key"]]
    assert row[head.index("Answer")] == "Yes" and row[head.index("Evidence / reference")] == "Charter v2"
    assert ws.data_validations.dataValidation  # drop-downs for fixed-option answers
    assert str(wb["Summary"]["C5"].value).startswith("=COUNTIF(")
    assert client.get("/api/assessments/99999/questionnaire.xlsx", headers=ASSESSOR).status_code == 404
