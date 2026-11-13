"""Assessment APIs: classification, questionnaire, risks, KPIs, compliance, architecture, dashboard."""
from __future__ import annotations

import io
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import services
from ..db import get_db
from ..engine import compliance as compliance_engine
from ..engine import detection
from ..engine.registry import RegistryError, content_of, latest_published
from ..models import (
    Assessment,
    AssessmentAnswer,
    AssessmentDocument,
    AssessmentItem,
    DomainPack,
    DomainRuleSource,
)
from .deps import User, current_user, require_editor, require_reviewer

router = APIRouter(prefix="/api", tags=["assessments"])


def _get(db: Session, aid: int) -> Assessment:
    a = db.get(Assessment, aid)
    if not a:
        raise HTTPException(404, "assessment not found")
    return a


def _wrap(fn):
    try:
        return fn()
    except RegistryError as e:
        raise HTTPException(e.status_code, str(e))


def _upsert_item(db: Session, a: Assessment, kind: str, key: str) -> AssessmentItem:
    it = services._item(db, a, kind, key)
    if it is None:
        it = AssessmentItem(assessment=a, kind=kind, key=key, data={})
        db.add(it)
    return it


def _summary(a: Assessment) -> dict[str, Any]:
    return {"id": a.id, "client_name": a.client_name, "project_name": a.project_name, "description": a.description,
            "stage": a.stage, "status": a.status, "classification": a.classification,
            "classification_confirmed_by": a.classification_confirmed_by,
            "classification_confirmed_at": a.classification_confirmed_at, "created_at": a.created_at,
            "created_by": a.created_by,
            "documents": [{"id": d.id, "filename": d.filename, "doc_type": d.doc_type, "chars": len(d.content_text),
                           "uploaded_at": d.uploaded_at} for d in a.documents],
            "mappings": [{"pack_key": m.pack.key, "pack_name": m.pack.name, "kind": m.pack.kind, "role": m.role,
                          "version": m.pack_version.version, "sub_domains": m.sub_domains,
                          "latest_published": None}
                         for m in sorted(a.mappings, key=lambda m: m.priority)]}


# --------------------------------------------------------------------------- catalog
@router.get("/catalog")
def get_catalog(db: Session = Depends(get_db), _: User = Depends(current_user)):
    return services.catalog(db)


# --------------------------------------------------------------------------- assessments
class NewAssessment(BaseModel):
    client_name: str = Field(min_length=1)
    project_name: str = Field(min_length=1)
    description: str = ""
    stage: str = "discovery"


@router.get("/assessments")
def list_assessments(db: Session = Depends(get_db), _: User = Depends(current_user)):
    return [_summary(a) for a in db.scalars(select(Assessment).order_by(Assessment.id.desc()))]


@router.post("/assessments", status_code=201)
def create_assessment(body: NewAssessment, db: Session = Depends(get_db), user: User = Depends(require_editor)):
    a = Assessment(client_name=body.client_name, project_name=body.project_name, description=body.description,
                   stage=body.stage, created_by=user.name)
    db.add(a)
    db.commit()
    return _summary(a)


@router.get("/assessments/{aid}")
def get_assessment(aid: int, db: Session = Depends(get_db), _: User = Depends(current_user)):
    a = _get(db, aid)
    out = _summary(a)
    for m in out["mappings"]:
        lp = latest_published(db, m["pack_key"])
        m["latest_published"] = lp.version if lp else None
    return out


class StagePatch(BaseModel):
    stage: str | None = None
    status: str | None = None


@router.patch("/assessments/{aid}")
def patch_assessment(aid: int, body: StagePatch, db: Session = Depends(get_db), _: User = Depends(require_editor)):
    a = _get(db, aid)
    if body.stage:
        a.stage = body.stage
    if body.status:
        a.status = body.status
    db.commit()
    return _summary(a)


# --------------------------------------------------------------------------- documents + detection
def _extract_text(filename: str, data: bytes) -> str:
    name = filename.lower()
    if name.endswith(".docx"):
        import docx

        d = docx.Document(io.BytesIO(data))
        parts = [p.text for p in d.paragraphs]
        for t in d.tables:
            for row in t.rows:
                parts.append(" | ".join(c.text for c in row.cells))
        return "\n".join(parts)
    if name.endswith(".pdf"):
        from pypdf import PdfReader

        return "\n".join((p.extract_text() or "") for p in PdfReader(io.BytesIO(data)).pages)
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode("latin-1")


@router.post("/assessments/{aid}/documents", status_code=201)
async def upload_document(aid: int, file: UploadFile | None = File(None), text: str | None = Form(None),
                          filename: str | None = Form(None), doc_type: str = Form("other"),
                          db: Session = Depends(get_db), user: User = Depends(require_editor)):
    a = _get(db, aid)
    if file is not None:
        content = _extract_text(file.filename or "document", await file.read())
        name = file.filename or "document"
    elif text:
        content, name = text, filename or "pasted-text.txt"
    else:
        raise HTTPException(422, "provide a file or text")
    if not content.strip():
        raise HTTPException(422, "no text could be extracted from the document")
    d = AssessmentDocument(assessment=a, filename=name, doc_type=doc_type, content_text=content, uploaded_by=user.name)
    db.add(d)
    db.commit()
    return {"id": d.id, "filename": d.filename, "chars": len(content)}


@router.delete("/assessments/{aid}/documents/{doc_id}", status_code=204)
def delete_document(aid: int, doc_id: int, db: Session = Depends(get_db), _: User = Depends(require_editor)):
    d = db.get(AssessmentDocument, doc_id)
    if not d or d.assessment_id != aid:
        raise HTTPException(404, "document not found")
    db.delete(d)
    db.commit()


@router.post("/assessments/{aid}/detect")
def detect_domain(aid: int, db: Session = Depends(get_db), user: User = Depends(require_editor)):
    """Suggest industry / sub-domain / technology / project type. Never locks the classification."""
    a = _get(db, aid)
    text = "\n\n".join(d.content_text for d in a.documents)
    if not text.strip():
        raise HTTPException(422, "upload at least one client document before running auto-detection")
    packs = []
    for p in db.scalars(select(DomainPack).where(DomainPack.enabled.is_(True))):
        v = latest_published(db, p.key)
        if v:
            packs.append(content_of(v))
    res = detection.detect(text, packs, services.reference())
    it = _upsert_item(db, a, "classification_suggestion", "latest")
    it.data, it.status, it.source = res, "pending_confirmation", "ai" if res["method"] != "keyword" else "system"
    it.confidence = (res.get("industry") or {}).get("confidence")
    it.reviewer = it.reviewed_at = None
    db.commit()
    return res


@router.get("/assessments/{aid}/detect")
def get_detection(aid: int, db: Session = Depends(get_db), _: User = Depends(current_user)):
    it = services._item(db, _get(db, aid), "classification_suggestion", "latest")
    return {"suggestion": it.data if it else None, "status": it.status if it else None,
            "reviewer": it.reviewer if it else None}


class SecondaryDomain(BaseModel):
    key: str
    sub_domains: list[str] = []


class Classification(BaseModel):
    primary_industry: str
    sub_domains: list[str] = []
    secondary_industries: list[SecondaryDomain] = []
    technologies: list[str] = []
    project_types: list[str] = []
    geography: str | None = None
    regulatory_regions: list[str] = []
    data_classifications: list[str] = []
    stage: str | None = None


@router.post("/assessments/{aid}/classification")
def confirm_classification(aid: int, body: Classification, db: Session = Depends(get_db),
                           user: User = Depends(require_editor)):
    a = _get(db, aid)
    _wrap(lambda: services.confirm_classification(db, a, body.model_dump(), user.name))
    db.commit()
    return _summary(a)


@router.post("/assessments/{aid}/mappings/{pack_key}/upgrade")
def upgrade_mapping(aid: int, pack_key: str, db: Session = Depends(get_db), user: User = Depends(require_reviewer)):
    a = _get(db, aid)
    _wrap(lambda: services.upgrade_pack_version(db, a, pack_key, user.name))
    db.commit()
    return _summary(a)


@router.post("/assessments/{aid}/process-documents")
def process_documents(aid: int, db: Session = Depends(get_db), _: User = Depends(require_editor)):
    a = _get(db, aid)
    res = services.process_documents(db, a)
    db.commit()
    return res


# --------------------------------------------------------------------------- questionnaire
@router.get("/assessments/{aid}/questionnaire")
def questionnaire(aid: int, db: Session = Depends(get_db), _: User = Depends(current_user)):
    a = _get(db, aid)
    _, prof = services.profile(db, a)
    ans = {x.question_key: x for x in a.answers}
    out = []
    for q in prof["questions"]:
        x = ans.get(q["key"])
        out.append({**q, "answer": None if not x else {
            "value": x.value, "evidence": x.evidence, "notes": x.notes, "answered_by": x.answered_by,
            "verified": x.verified, "verified_by": x.verified_by, "verified_at": x.verified_at}})
    return {"questions": out, "dimensions": prof["dimensions"]}


class AnswerBody(BaseModel):
    value: Any = None
    evidence: str = ""
    notes: str = ""


@router.put("/assessments/{aid}/answers/{question_key:path}")
def put_answer(aid: int, question_key: str, body: AnswerBody, db: Session = Depends(get_db),
               user: User = Depends(require_editor)):
    a = _get(db, aid)
    x = db.scalar(select(AssessmentAnswer).where(AssessmentAnswer.assessment_id == a.id,
                                                 AssessmentAnswer.question_key == question_key))
    if x is None:
        x = AssessmentAnswer(assessment=a, question_key=question_key)
        db.add(x)
    if x.value != body.value or x.evidence != body.evidence:
        x.verified, x.verified_by, x.verified_at = False, None, None  # changed answers need re-verification
    x.value, x.evidence, x.notes, x.answered_by = body.value, body.evidence, body.notes, user.name
    db.commit()
    return {"ok": True}


@router.post("/assessments/{aid}/answers/{question_key:path}/verify")
def verify_answer(aid: int, question_key: str, db: Session = Depends(get_db), user: User = Depends(require_reviewer)):
    x = db.scalar(select(AssessmentAnswer).where(AssessmentAnswer.assessment_id == aid,
                                                 AssessmentAnswer.question_key == question_key))
    if not x:
        raise HTTPException(404, "answer not found")
    x.verified, x.verified_by, x.verified_at = True, user.name, services.now()
    db.commit()
    return {"ok": True}


class ReviewBody(BaseModel):
    status: str
    notes: str = ""


@router.patch("/assessments/{aid}/ai-questions/{key}")
def review_ai_question(aid: int, key: str, body: ReviewBody, db: Session = Depends(get_db),
                       user: User = Depends(require_editor)):
    if body.status not in ("accepted", "dismissed", "pending"):
        raise HTTPException(422, "status must be accepted, dismissed or pending")
    it = services._item(db, _get(db, aid), "ai_question", key)
    if not it:
        raise HTTPException(404, "AI question not found")
    it.status, it.notes, it.reviewer, it.reviewed_at = body.status, body.notes, user.name, services.now()
    db.commit()
    return {"ok": True}


@router.get("/assessments/{aid}/ai-questions")
def list_ai_questions(aid: int, db: Session = Depends(get_db), _: User = Depends(current_user)):
    return [{"key": i.key, "status": i.status, "confidence": i.confidence, "reviewer": i.reviewer, **i.data}
            for i in services.items(db, _get(db, aid), "ai_question")]


# --------------------------------------------------------------------------- profile sections
def _section(db: Session, aid: int, name: str):
    _, prof = services.profile(db, _get(db, aid))
    return prof[name]


@router.get("/assessments/{aid}/risks")
def risks(aid: int, db: Session = Depends(get_db), _: User = Depends(current_user)):
    return _section(db, aid, "risks")


class ProjectRisk(BaseModel):
    title: str
    description: str = ""
    category: str = "project"
    likelihood: int = Field(3, ge=1, le=5)
    impact: int = Field(3, ge=1, le=5)
    mitigation: str = ""


@router.post("/assessments/{aid}/risks", status_code=201)
def add_risk(aid: int, body: ProjectRisk, db: Session = Depends(get_db), user: User = Depends(require_editor)):
    a = _get(db, aid)
    key = f"r{len(services.items(db, a, 'risk')) + 1}"
    db.add(AssessmentItem(assessment=a, kind="risk", key=key, source="human", status="open",
                          data={**body.model_dump(), "added_by": user.name}))
    db.commit()
    return {"key": f"project:{key}"}


@router.get("/assessments/{aid}/kpis")
def kpis(aid: int, db: Session = Depends(get_db), _: User = Depends(current_user)):
    return _section(db, aid, "kpis")


class KpiReview(BaseModel):
    status: str  # confirmed | rejected | suggested
    client_target: str | None = None
    target_source: str | None = None
    notes: str = ""


@router.put("/assessments/{aid}/kpis/{key:path}")
def review_kpi(aid: int, key: str, body: KpiReview, db: Session = Depends(get_db), user: User = Depends(require_editor)):
    if body.status not in ("confirmed", "rejected", "suggested"):
        raise HTTPException(422, "status must be confirmed, rejected or suggested")
    if body.client_target and not body.target_source:
        raise HTTPException(422, "a KPI target must cite its client source (target_source); targets are never invented")
    it = _upsert_item(db, _get(db, aid), "kpi", key)
    it.status, it.notes, it.reviewer, it.reviewed_at, it.source = body.status, body.notes, user.name, services.now(), "human"
    it.data = {"client_target": body.client_target, "target_source": body.target_source}
    db.commit()
    return {"ok": True}


@router.get("/assessments/{aid}/compliance")
def compliance(aid: int, db: Session = Depends(get_db), _: User = Depends(current_user)):
    return {"items": _section(db, aid, "compliance"), "statuses": compliance_engine.STATUSES,
            "disclaimer": compliance_engine.DISCLAIMER}


class ComplianceReview(BaseModel):
    status: str
    evidence: str = ""
    notes: str = ""


@router.put("/assessments/{aid}/compliance/{key}")
def review_compliance(aid: int, key: str, body: ComplianceReview, db: Session = Depends(get_db),
                      user: User = Depends(require_editor)):
    if body.status not in compliance_engine.STATUSES:
        raise HTTPException(422, f"status must be one of {list(compliance_engine.STATUSES)}")
    if body.status in compliance_engine.HUMAN_ONLY_STATUSES and not user.can_review:
        raise HTTPException(403, "only an authorised reviewer (reviewer/admin) can confirm applicability or verify compliance")
    if body.status == "verified" and not body.evidence.strip():
        raise HTTPException(422, "verification requires evidence (e.g. audit report reference, control test result)")
    it = _upsert_item(db, _get(db, aid), "compliance", key)
    it.status, it.notes, it.reviewer, it.reviewed_at, it.source = body.status, body.notes, user.name, services.now(), "human"
    it.data = {"evidence": body.evidence}
    db.commit()
    return {"ok": True}


@router.get("/assessments/{aid}/architecture")
def architecture(aid: int, db: Session = Depends(get_db), _: User = Depends(current_user)):
    return _section(db, aid, "architecture")


@router.get("/assessments/{aid}/recommendations")
def recommendations(aid: int, db: Session = Depends(get_db), _: User = Depends(current_user)):
    _, prof = services.profile(db, _get(db, aid))
    return {"recommendations": prof["recommendations"], "conflicts": prof["conflicts"]}


class ConflictResolution(BaseModel):
    chosen: str
    rationale: str = Field(min_length=3)


@router.put("/assessments/{aid}/conflicts/{key:path}")
def resolve_conflict(aid: int, key: str, body: ConflictResolution, db: Session = Depends(get_db),
                     user: User = Depends(require_reviewer)):
    a = _get(db, aid)
    _, prof = services.profile(db, a)
    c = next((c for c in prof["conflicts"] if c["key"] == key), None)
    if not c:
        raise HTTPException(404, "conflict not found")
    if body.chosen not in {o["key"] for o in c["options"]}:
        raise HTTPException(422, "chosen must be one of the conflicting recommendation keys")
    it = _upsert_item(db, a, "conflict", key)
    it.status, it.reviewer, it.reviewed_at, it.source = "resolved", user.name, services.now(), "human"
    it.data = {"chosen": body.chosen, "rationale": body.rationale, "decided_by": user.name}
    db.commit()
    return {"ok": True}


@router.get("/assessments/{aid}/knowledge")
def knowledge(aid: int, db: Session = Depends(get_db), _: User = Depends(current_user)):
    return _section(db, aid, "knowledge")


@router.get("/assessments/{aid}/terminology")
def terminology(aid: int, db: Session = Depends(get_db), _: User = Depends(current_user)):
    return _section(db, aid, "terminology")


@router.get("/assessments/{aid}/requirements")
def requirements(aid: int, db: Session = Depends(get_db), _: User = Depends(current_user)):
    return [{"key": i.key, "status": i.status, **i.data} for i in services.items(db, _get(db, aid), "requirement")]


@router.get("/assessments/{aid}/rule-sources")
def rule_sources(aid: int, db: Session = Depends(get_db), _: User = Depends(current_user)):
    rows = db.scalars(select(DomainRuleSource).where(DomainRuleSource.assessment_id == aid)
                      .order_by(DomainRuleSource.rule_type, DomainRuleSource.id))
    return [{"rule_type": r.rule_type, "rule_key": r.rule_key, "origin": r.origin, "pack_key": r.pack_key,
             "pack_version": r.pack_version, "role": r.role, "sub_domain": r.sub_domain, "status": r.status,
             "merged_into": r.merged_into} for r in rows]


@router.get("/assessments/{aid}/ai-context")
def ai_context(aid: int, db: Session = Depends(get_db), _: User = Depends(current_user)):
    return services.ai_context(db, _get(db, aid))


@router.get("/assessments/{aid}/dashboard")
def dashboard(aid: int, db: Session = Depends(get_db), _: User = Depends(current_user)):
    return services.dashboard(db, _get(db, aid))
