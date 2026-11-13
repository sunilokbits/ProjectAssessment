"""Assessment services: classification, version pinning, profile resolution, dashboard."""
from __future__ import annotations

from datetime import datetime, timezone
from functools import lru_cache
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from .config import get_settings
from .engine import extraction, merger, prompt_builder, scoring
from .engine.context import ROLE_PRIORITY, AssessmentContext, PackRef
from .engine.loader import load_reference_data
from .engine.registry import RegistryError, content_of, latest_published
from .models import (
    Assessment,
    AssessmentItem,
    DomainAssessmentMapping,
    DomainPack,
    DomainPackStatus,
    DomainPackVersion,
    DomainRuleSource,
)


@lru_cache
def _reference_cached(path: str) -> dict[str, Any]:
    from pathlib import Path

    return load_reference_data(Path(path))


def reference() -> dict[str, Any]:
    return _reference_cached(str(get_settings().domain_packs_dir))


def reload_reference() -> None:
    _reference_cached.cache_clear()


def now() -> datetime:
    return datetime.now(timezone.utc)


# --------------------------------------------------------------------------- catalog
def catalog(db: Session) -> dict[str, Any]:
    """Selectable options: published + enabled packs only (new packs appear automatically)."""
    out: dict[str, list[dict[str, Any]]] = {"industry": [], "technology": [], "project_type": []}
    packs = db.scalars(select(DomainPack).where(DomainPack.enabled.is_(True))).all()
    for p in packs:
        if p.kind not in out:
            continue
        ver = latest_published(db, p.key)
        if not ver:
            continue
        c = content_of(ver)
        out[p.kind].append({
            "key": p.key, "name": c.domain.name, "description": c.domain.description, "version": ver.version,
            "sort_order": c.domain.sort_order, "aliases": c.domain.aliases, "icon": c.domain.icon,
            "category": (c.domain.aliases[0] if p.kind == "technology" and c.domain.aliases else None),
            "sub_domains": [{"key": s.key, "name": s.name, "description": s.description}
                            for s in c.domain.sub_domains if s.enabled],
        })
    for v in out.values():
        v.sort(key=lambda x: (x["sort_order"], x["name"]))
    ref = reference()
    return {"industries": out["industry"], "technologies": out["technology"], "project_types": out["project_type"],
            "geographies": ref.get("geographies", []), "regulatory_regions": ref.get("regulatory_regions", []),
            "data_classifications": ref.get("data_classifications", []), "stages": ref.get("stages", []),
            "technology_categories": ref.get("technology_categories", {})}


# --------------------------------------------------------------------------- classification
def _published_version(db: Session, key: str, kind: str) -> DomainPackVersion:
    pack = db.scalar(select(DomainPack).where(DomainPack.key == key))
    if not pack or pack.kind != kind:
        raise RegistryError(f"unknown {kind.replace('_', ' ')} domain '{key}'", 422)
    if not pack.enabled:
        raise RegistryError(f"domain '{key}' is disabled and cannot be selected for new classifications", 422)
    ver = latest_published(db, key)
    if not ver:
        raise RegistryError(f"domain '{key}' has no published version", 422)
    return ver


def confirm_classification(db: Session, a: Assessment, payload: dict[str, Any], actor: str) -> Assessment:
    primary = payload.get("primary_industry")
    if not primary:
        raise RegistryError("primary industry/domain is required before the detailed assessment can start", 422)
    existing = {m.pack.key: m for m in a.mappings}
    wanted: list[tuple[str, str, str, list[str], int]] = []  # key, kind, role, subs, order
    g = latest_published(db, kind="global")
    if not g:
        raise RegistryError("no published global domain pack", 500)
    wanted.append((g.pack.key, "global", "global", [], 0))
    wanted.append((primary, "industry", "primary", list(payload.get("sub_domains") or []), 0))
    for i, s in enumerate(payload.get("secondary_industries") or []):
        if s["key"] == primary:
            raise RegistryError("a secondary domain cannot be the same as the primary domain", 422)
        wanted.append((s["key"], "industry", "secondary", list(s.get("sub_domains") or []), i))
    for i, t in enumerate(payload.get("technologies") or []):
        wanted.append((t, "technology", "technology", [], i))
    for i, t in enumerate(payload.get("project_types") or []):
        wanted.append((t, "project_type", "project_type", [], i))

    keep = set()
    for key, kind, role, subs, order in wanted:
        if key in keep:
            continue
        keep.add(key)
        m = existing.get(key)
        if m is not None:
            # Existing assessments retain their original Domain Pack version.
            ver = m.pack_version
            if m.pack.kind != kind:
                raise RegistryError(f"'{key}' is a {m.pack.kind} domain, not {kind}", 422)
        else:
            ver = _published_version(db, key, kind)
        valid_subs = {s.key for s in content_of(ver).domain.sub_domains}
        bad = [s for s in subs if s not in valid_subs]
        if bad:
            raise RegistryError(f"unknown sub-domain(s) {bad} for '{key}' (valid: {sorted(valid_subs)})", 422)
        if m is None:
            m = DomainAssessmentMapping(assessment=a, pack_id=ver.pack_id, pack_version_id=ver.id)
            db.add(m)
        m.role, m.sub_domains, m.priority = role, subs, ROLE_PRIORITY[role] * 100 + order
    for key, m in existing.items():
        if key not in keep:
            db.delete(m)

    a.classification = {
        "primary_industry": primary,
        "sub_domains": list(payload.get("sub_domains") or []),
        "secondary_industries": [{"key": s["key"], "sub_domains": list(s.get("sub_domains") or [])}
                                 for s in payload.get("secondary_industries") or []],
        "technologies": list(payload.get("technologies") or []),
        "project_types": list(payload.get("project_types") or []),
        "geography": payload.get("geography"),
        "regulatory_regions": list(payload.get("regulatory_regions") or []),
        "data_classifications": list(payload.get("data_classifications") or []),
    }
    if payload.get("stage"):
        a.stage = payload["stage"]
    a.classification_confirmed_by = actor
    a.classification_confirmed_at = now()
    if a.status == "classification_pending":
        a.status = "in_progress"
    sug = _item(db, a, "classification_suggestion", "latest")
    if sug is not None:
        detected = (sug.data.get("industry") or {}).get("key")
        sug.status = "confirmed" if detected == primary else "changed_by_user"
        sug.reviewer, sug.reviewed_at = actor, now()
    db.flush()
    db.refresh(a)
    persist_rule_sources(db, a)
    return a


def upgrade_pack_version(db: Session, a: Assessment, pack_key: str, actor: str) -> DomainAssessmentMapping:
    """Explicit, user-initiated move of one mapping to the latest published version."""
    m = next((m for m in a.mappings if m.pack.key == pack_key), None)
    if m is None:
        raise RegistryError(f"assessment does not use '{pack_key}'", 404)
    ver = latest_published(db, pack_key)
    if not ver:
        raise RegistryError("no published version available", 409)
    m.pack_version_id = ver.id
    db.flush()
    db.refresh(a)
    persist_rule_sources(db, a)
    return m


# --------------------------------------------------------------------------- context + profile
def _item(db: Session, a: Assessment, kind: str, key: str) -> AssessmentItem | None:
    return db.scalar(select(AssessmentItem).where(AssessmentItem.assessment_id == a.id, AssessmentItem.kind == kind,
                                                  AssessmentItem.key == key))


def items(db: Session, a: Assessment, kind: str) -> list[AssessmentItem]:
    return list(db.scalars(select(AssessmentItem).where(AssessmentItem.assessment_id == a.id,
                                                        AssessmentItem.kind == kind).order_by(AssessmentItem.id)))


def build_context(db: Session, a: Assessment) -> AssessmentContext:
    cl = a.classification or {}
    packs = []
    for m in sorted(a.mappings, key=lambda m: m.priority):
        v = m.pack_version
        packs.append(PackRef(key=m.pack.key, kind=m.pack.kind, role=m.role, version=v.version, version_id=v.id,
                             content=content_of(v), sub_domains=list(m.sub_domains or []), order=m.priority % 100))
    if not packs:  # not yet classified – global layer only
        g = latest_published(db, kind="global")
        if g:
            packs.append(PackRef(key=g.pack.key, kind="global", role="global", version=g.version, version_id=g.id,
                                 content=content_of(g)))
    return AssessmentContext(
        client_name=a.client_name, project_name=a.project_name,
        primary_industry=cl.get("primary_industry"), sub_domains=cl.get("sub_domains", []),
        secondary_industries=cl.get("secondary_industries", []), technologies=cl.get("technologies", []),
        project_types=cl.get("project_types", []), geography=cl.get("geography"),
        regulatory_regions=cl.get("regulatory_regions", []), data_classifications=cl.get("data_classifications", []),
        stage=a.stage, document_text="\n\n".join(d.content_text for d in a.documents),
        answers={x.question_key: x.value for x in a.answers}, packs=packs, reference=reference(),
    )


def extras(db: Session, a: Assessment) -> dict[str, Any]:
    def reviews(kind: str) -> dict[str, Any]:
        return {i.key: {**i.data, "status": i.status, "reviewer": i.reviewer,
                        "reviewed_at": i.reviewed_at.isoformat() if i.reviewed_at else None, "notes": i.notes}
                for i in items(db, a, kind)}

    return {
        "ai_questions": [{**i.data, "key": i.key, "confidence": i.confidence, "status": i.status}
                         for i in items(db, a, "ai_question") if i.status != "dismissed"],
        "project_risks": [{**i.data, "key": i.key} for i in items(db, a, "risk")],
        "kpi_reviews": reviews("kpi"),
        "compliance_reviews": reviews("compliance"),
        "conflict_resolutions": {i.key: {**i.data, "reviewer": i.reviewer} for i in items(db, a, "conflict")},
    }


def profile(db: Session, a: Assessment) -> tuple[AssessmentContext, dict[str, Any]]:
    ctx = build_context(db, a)
    return ctx, merger.resolve(ctx, extras(db, a))


def persist_rule_sources(db: Session, a: Assessment) -> int:
    _, prof = profile(db, a)
    db.execute(delete(DomainRuleSource).where(DomainRuleSource.assessment_id == a.id))
    for rs in prof["rule_sources"]:
        db.add(DomainRuleSource(assessment_id=a.id, **rs))
    db.flush()
    return len(prof["rule_sources"])


def ai_context(db: Session, a: Assessment) -> dict[str, Any]:
    ctx, prof = profile(db, a)
    return prompt_builder.build_context(ctx, prof)


# --------------------------------------------------------------------------- documents
def process_documents(db: Session, a: Assessment) -> dict[str, Any]:
    ctx, prof = profile(db, a)
    ref = reference()
    reqs = []
    for d in a.documents:
        reqs += extraction.extract_requirements(d.content_text, prof, ref, d.filename)
    seen = set()
    for r in reqs:
        if r["key"] in seen:
            continue
        seen.add(r["key"])
        it = _item(db, a, "requirement", r["key"])
        if it is None:
            db.add(AssessmentItem(assessment=a, kind="requirement", key=r["key"], data=r, source="system",
                                  confidence=r["confidence"], status="extracted"))
        elif it.status == "extracted":
            it.data, it.confidence = r, r["confidence"]
    sys_prompt = prompt_builder.build_context(ctx, prof)["system_prompt"]
    qs = extraction.clarification_questions(ctx.document_text, reqs, prof, ref, sys_prompt)
    added = 0
    for q in qs:
        if _item(db, a, "ai_question", q["key"]) is None:
            db.add(AssessmentItem(assessment=a, kind="ai_question", key=q["key"], data=q,
                                  source="ai" if q["method"] == "ai" else "system", confidence=q["confidence"]))
            added += 1
    db.flush()
    persist_rule_sources(db, a)
    return {"requirements": len(seen), "ai_questions_added": added}


# --------------------------------------------------------------------------- dashboard
def _names(ctx: AssessmentContext, keys: list[str]) -> list[dict[str, str]]:
    return [{"key": k, "name": ctx.pack(k).name if ctx.pack(k) else k} for k in keys]


def dashboard(db: Session, a: Assessment) -> dict[str, Any]:
    ctx, prof = profile(db, a)
    ref = reference()
    answers = {x.question_key: {"value": x.value, "evidence": x.evidence, "verified": x.verified} for x in a.answers}
    sc = scoring.compute(prof, answers, ref)
    prim = ctx.pack(ctx.primary_industry) if ctx.primary_industry else None
    sub_names = {s.key: s.name for s in prim.content.domain.sub_domains} if prim else {}
    geo = next((g for g in ref.get("geographies", []) if ctx.geography and g["code"] == ctx.geography), None)

    qs = prof["questions"]
    answered = [q for q in qs if answers.get(q["key"], {}).get("value") not in (None, "", [])]
    with_evidence = [q for q in answered if (answers[q["key"]].get("evidence") or "").strip()]
    needs_evidence = [q for q in qs if q.get("evidence_required")]
    verified = [q for q in answered if answers[q["key"]].get("verified")]
    ai_qs = [q for q in qs if q["origin"] == "AI-DISCOVERED"]
    comp = prof["compliance"]
    kpis = prof["kpis"]
    conflicts = prof["conflicts"]
    sug = _item(db, a, "classification_suggestion", "latest")
    reqs = items(db, a, "requirement")

    def pct(n: int, d: int) -> float | None:
        return round(100 * n / d, 1) if d else None

    ai_conf_values = [q["confidence"] for q in ai_qs if q.get("confidence") is not None] + \
                     [r.confidence for r in reqs if r.confidence is not None]
    verification_parts = {
        "classification_confirmed": 1 if a.classification_confirmed_by else 0,
        "answers_verified": f"{len(verified)}/{len(answered)}",
        "compliance_reviewed": f"{sum(1 for c in comp if c['status'] != 'potentially_applicable')}/{len(comp)}",
        "kpis_reviewed": f"{sum(1 for k in kpis if k['status'] != 'suggested')}/{len(kpis)}",
        "conflicts_resolved": f"{sum(1 for c in conflicts if c['status'] == 'resolved')}/{len(conflicts)}",
        "ai_questions_reviewed": f"{sum(1 for q in ai_qs if q.get('status') not in (None, 'pending'))}/{len(ai_qs)}",
    }
    num = len(verified) + sum(1 for c in comp if c["status"] != "potentially_applicable") + \
        sum(1 for k in kpis if k["status"] != "suggested") + sum(1 for c in conflicts if c["status"] == "resolved") + \
        sum(1 for q in ai_qs if q.get("status") not in (None, "pending")) + (1 if a.classification_confirmed_by else 0)
    den = len(answered) + len(comp) + len(kpis) + len(conflicts) + len(ai_qs) + 1
    return {
        "assessment": {"id": a.id, "client_name": a.client_name, "project_name": a.project_name, "stage": a.stage,
                       "status": a.status},
        "classification": {
            "client": a.client_name,
            "industry": _names(ctx, [ctx.primary_industry] if ctx.primary_industry else []),
            "sub_domains": [{"key": s, "name": sub_names.get(s, s)} for s in ctx.sub_domains],
            "secondary_industries": _names(ctx, [s["key"] for s in ctx.secondary_industries]),
            "project_types": _names(ctx, ctx.project_types),
            "technologies": _names(ctx, ctx.technologies),
            "geography": {"code": ctx.geography, "name": geo["name"] if geo else ctx.geography} if ctx.geography else None,
            "regulatory_regions": ctx.regulatory_regions,
            "data_classifications": [
                next((d["name"] for d in ref.get("data_classifications", []) if d["key"] == k), k)
                for k in ctx.data_classifications],
            "confirmed_by": a.classification_confirmed_by,
            "confirmed_at": a.classification_confirmed_at.isoformat() if a.classification_confirmed_at else None,
            "packs": prof["packs"],
        },
        "scores": sc,
        "summary": {
            "critical_gaps": sc["critical_gaps"],
            "open_questions": len(qs) - len(answered),
            "questions_total": len(qs),
            "questions_by_origin": {o: sum(1 for q in qs if q["origin"] == o) for o in
                                    ["GLOBAL", "INDUSTRY", "SUB-DOMAIN", "TECHNOLOGY", "PROJECT", "AI-DISCOVERED"]},
            "duplicates_removed": sum(len(q["merged_from"]) for q in qs),
            "risks": {"total": len(prof["risks"]), "high": sum(1 for r in prof["risks"] if r["rating"] == "high"),
                      "evidenced": sum(1 for r in prof["risks"] if r["evidenced"])},
            "assumptions": len(prof["knowledge"]["assumptions"]),
            "dependencies": len(prof["knowledge"]["dependencies"]),
            "compliance": {s: sum(1 for c in comp if c["status"] == s) for s in
                           ["potentially_applicable", "confirmed_applicable", "verified", "not_applicable", "unknown"]},
            "conflicts_pending": sum(1 for c in conflicts if c["status"] != "resolved"),
            "requirements_extracted": len(reqs),
            "evidence_coverage": {"answered_with_evidence": pct(len(with_evidence), len(answered)),
                                  "evidence_required_met": pct(sum(1 for q in needs_evidence if q in with_evidence), len(needs_evidence)),
                                  "answered": pct(len(answered), len(qs))},
            "ai_confidence": {
                "classification": (sug.data.get("industry") or {}).get("confidence") if sug and sug.data else None,
                "classification_method": sug.data.get("method") if sug and sug.data else None,
                "extracted_items_avg": round(sum(ai_conf_values) / len(ai_conf_values), 2) if ai_conf_values else None,
            },
            "human_verification": {"progress": pct(num, den), **verification_parts},
        },
    }
