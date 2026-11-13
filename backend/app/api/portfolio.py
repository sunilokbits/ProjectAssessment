"""Leadership portfolio view + demo-portfolio seeding."""
from __future__ import annotations

import random
from pathlib import Path
from typing import Any

import yaml
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import services
from ..db import get_db
from ..engine.registry import RegistryError, content_of, latest_published
from ..models import Assessment, AssessmentAnswer, AssessmentDocument, AssessmentItem, DomainPack
from .deps import User, current_user, require_admin

router = APIRouter(prefix="/api", tags=["portfolio"])
DEMO_USER = "demo"


def _platform(db: Session) -> dict[str, Any]:
    kinds: dict[str, int] = {}
    totals = {"questions": 0, "risks": 0, "kpis": 0, "compliance": 0, "terminology": 0, "architecture_patterns": 0}
    industries = []
    for p in db.scalars(select(DomainPack).where(DomainPack.enabled.is_(True)).order_by(DomainPack.name)):
        v = latest_published(db, p.key)
        if not v:
            continue
        kinds[p.kind] = kinds.get(p.kind, 0) + 1
        for k in totals:
            totals[k] += len(v.content.get(k) or [])
        if p.kind == "industry":
            c = content_of(v)
            industries.append({"key": p.key, "name": p.name, "version": v.version,
                               "sub_domains": [s.name for s in c.domain.sub_domains],
                               "questions": len(c.questions), "risks": len(c.risks), "kpis": len(c.kpis),
                               "compliance": len(c.compliance), "terms": len(c.terminology),
                               "dimensions": [d.name for d in c.scoring.dimensions]})
    return {"packs_by_kind": kinds, "totals": totals, "industries": industries}


@router.get("/portfolio")
def portfolio(db: Session = Depends(get_db), _: User = Depends(current_user)):
    rows = []
    for a in db.scalars(select(Assessment).where(Assessment.status != "classification_pending").order_by(Assessment.id)):
        d = services.dashboard(db, a)
        s, sc, c = d["summary"], d["scores"], d["classification"]
        rows.append({
            "id": a.id, "client_name": a.client_name, "project_name": a.project_name, "stage": a.stage,
            "demo": a.created_by == DEMO_USER,
            "industry": c["industry"][0] if c["industry"] else None,
            "sub_domains": [x["name"] for x in c["sub_domains"]],
            "technologies": [x["name"] for x in c["technologies"]],
            "project_types": [x["name"] for x in c["project_types"]],
            "geography": c["geography"]["name"] if c["geography"] else None,
            "overall": sc["overall"],
            "groups": {g["group"]: {"score": g["score"], "rag": g["rag"], "label": g["label"]} for g in sc["groups"]},
            "answered": sc["questions_answered"], "questions": sc["questions_total"],
            "critical_gaps": len(s["critical_gaps"]), "risks": s["risks"], "compliance": s["compliance"],
            "conflicts_pending": s["conflicts_pending"], "human_verification": s["human_verification"]["progress"],
            "evidence_coverage": s["evidence_coverage"]["answered_with_evidence"],
            "questions_by_origin": s["questions_by_origin"],
        })
    return {"assessments": rows, "platform": _platform(db), "reference": {
        "rag_thresholds": services.reference().get("rag_thresholds", {"green": 75, "amber": 50})}}


# ------------------------------------------------------------------ demo seeding
def _answer(q: dict[str, Any], rnd: random.Random, maturity: float) -> Any:
    t = q["answer_type"]
    good = rnd.random() < maturity
    if t == "yes_no":
        opts = [o["value"] for o in q["options"]] or ["yes", "partial", "no"]
        if "yes" in opts and good:
            return "yes"
        return rnd.choice([o for o in opts if o not in ("yes", "unknown")] or opts)
    if t == "scale":
        base = 1 + maturity * 4
        return max(1, min(5, round(base + rnd.uniform(-1.2, 1.2))))
    if t in ("single_choice", "multi_choice"):
        scored = sorted([o for o in q["options"] if o.get("score") is not None], key=lambda o: -o["score"])
        pool = scored or q["options"]
        pick = pool[0] if good else rnd.choice(pool)
        return [pick["value"]] if t == "multi_choice" else pick["value"]
    if t == "number":
        return rnd.randint(1, 100)
    return rnd.choice(["Documented in discovery workshop.", "Confirmed with client architecture team.",
                       "Partially known - follow-up scheduled.", "See RFP section 3."])


@router.post("/demo/seed")
def seed_demo(db: Session = Depends(get_db), user: User = Depends(require_admin)):
    data = yaml.safe_load((Path(__file__).resolve().parents[1] / "demo_portfolio.yaml").read_text(encoding="utf-8"))
    for old in db.scalars(select(Assessment).where(Assessment.created_by == DEMO_USER)):
        db.delete(old)
    db.flush()
    created, skipped = [], []
    for i, sc in enumerate(data["scenarios"]):
        rnd = random.Random(1000 + i)
        a = Assessment(client_name=sc["client_name"], project_name=sc["project_name"], stage=sc["stage"],
                       created_by=DEMO_USER, description="Demo assessment (synthetic data)")
        db.add(a)
        db.flush()
        db.add(AssessmentDocument(assessment=a, filename="rfp-summary.txt", doc_type="rfp",
                                  content_text=sc["document"], uploaded_by=DEMO_USER))
        try:
            services.confirm_classification(db, a, {**sc["classification"], "stage": sc["stage"]}, user.name)
        except RegistryError as e:  # a pack may be disabled/missing in this installation
            skipped.append({"client": sc["client_name"], "reason": str(e)})
            db.delete(a)
            db.flush()
            continue
        services.process_documents(db, a)
        _, prof = services.profile(db, a)
        for q in prof["questions"]:
            if rnd.random() > sc["coverage"]:
                continue
            ev = rnd.choice(["", "", "Discovery workshop notes", "RFP §4.2", "Architecture review deck"])
            verified = bool(ev) and rnd.random() < 0.5
            db.add(AssessmentAnswer(assessment=a, question_key=q["key"], value=_answer(q, rnd, sc["maturity"]),
                                    evidence=ev, answered_by=DEMO_USER, verified=verified,
                                    verified_by="demo-reviewer" if verified else None,
                                    verified_at=services.now() if verified else None))
        for c in prof["compliance"][: max(1, len(prof["compliance"]) // 2)]:
            st = rnd.choice(["confirmed_applicable", "unknown", "not_applicable"])
            db.add(AssessmentItem(assessment=a, kind="compliance", key=c["key"], status=st, source="human",
                                  reviewer="demo-reviewer", reviewed_at=services.now(), data={"evidence": ""}))
        for k in prof["kpis"][:4]:
            db.add(AssessmentItem(assessment=a, kind="kpi", key=k["key"], status="confirmed", source="human",
                                  reviewer="demo-reviewer", reviewed_at=services.now(), data={}))
        db.flush()
        services.persist_rule_sources(db, a)
        created.append({"id": a.id, "client": a.client_name})
    db.commit()
    return {"created": created, "skipped": skipped}


@router.delete("/demo/seed")
def clear_demo(db: Session = Depends(get_db), _: User = Depends(require_admin)):
    n = 0
    for old in db.scalars(select(Assessment).where(Assessment.created_by == DEMO_USER)):
        db.delete(old)
        n += 1
    db.commit()
    if not n:
        raise HTTPException(404, "no demo assessments")
    return {"deleted": n}
