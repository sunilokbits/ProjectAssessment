"""Builds report content for an assessment.

* ``baseline`` is deterministic: assessment data (classification, documents, readiness, risks,
  compliance, KPIs, recommendations) plus the editable catalogue in ``catalog.yaml``.
* ``generate`` sends the assessment context, the baseline draft and the user's prompt to Claude,
  which returns the full content (structured output). Without credentials, or on any AI failure,
  the baseline is used and the prompt is applied with simple section keywords.
"""
from __future__ import annotations

import functools
import json
import re
from datetime import date
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError
from sqlalchemy.orm import Session

from .. import services
from ..engine import llm
from ..models import Assessment
from .schema import SECTIONS, ReportContent, strict_json_schema  # noqa: F401  (re-exported)

CATALOG_PATH = Path(__file__).with_name("catalog.yaml")
MAX_DOC_CHARS = 60_000
DEFAULT_SECTIONS = [k for k in SECTIONS if k != "battle_cards"]


@functools.lru_cache(maxsize=1)
def catalog() -> dict[str, Any]:
    return yaml.safe_load(CATALOG_PATH.read_text(encoding="utf-8"))


# ----------------------------------------------------------------------------- facts
def facts(db: Session, a: Assessment) -> dict[str, Any]:
    """Everything the generators and the analysis document need, in plain dicts."""
    ctx, prof = services.profile(db, a)
    dash = services.dashboard(db, a)
    cls = dash["classification"]
    names = lambda xs: [x["name"] for x in xs]  # noqa: E731
    risks = sorted(prof["risks"], key=lambda r: (-(r.get("score") or 0), r["title"]))
    comp = prof["compliance"]
    reqs = services.items(db, a, "requirement")
    docs = [{"filename": d.filename, "text": d.content_text} for d in a.documents]
    return {
        "client": a.client_name,
        "project": a.project_name,
        "description": a.description or "",
        "stage": a.stage,
        "industry": (names(cls["industry"]) or ["Not classified"])[0],
        "sub_domains": names(cls["sub_domains"]),
        "technologies": names(cls["technologies"]),
        "project_types": names(cls["project_types"]),
        "geography": (cls.get("geography") or {}).get("name") or "",
        "regions": cls.get("regulatory_regions") or [],
        "data_classes": cls.get("data_classifications") or [],
        "pack_keys": [m.pack.key for m in a.mappings],
        "scores": dash["scores"],
        "summary": dash["summary"],
        "risks": [{"title": r["title"], "rating": r["rating"], "likelihood": r["likelihood"], "impact": r["impact"],
                   "category": r.get("category", ""), "mitigation": r.get("mitigation", ""), "origin": r["origin"]} for r in risks],
        "compliance": [{"name": c.get("short_name") or c["name"], "full_name": c["name"], "status": c.get("status_label") or c.get("status"),
                        "origin": c["origin"]} for c in comp],
        "kpis": [{"name": k["name"], "unit": k.get("unit", ""), "direction": k.get("direction", ""), "status": k.get("status")} for k in prof["kpis"]],
        "recommendations": [{"title": r["title"], "text": r.get("text", ""), "priority": r.get("priority", ""), "origin": r["origin"]}
                            for r in prof["recommendations"] if r.get("preferred", True)],
        "architecture": [{"name": p["name"], "description": p.get("description", "")} for p in prof["architecture"].get("patterns", [])],
        "assumptions": [x["text"] for x in prof["knowledge"].get("assumptions", [])],
        "dependencies": [x["text"] for x in prof["knowledge"].get("dependencies", [])],
        "ai_opportunities": [x["text"] for x in prof["knowledge"].get("ai_opportunities", [])],
        "requirements": [r.data.get("text", "") for r in reqs],
        "documents": docs,
    }


# ----------------------------------------------------------------------------- baseline
def _pick_accelerators(f: dict[str, Any], prompt: str = "") -> list[dict[str, Any]]:
    keys = set(f["pack_keys"])
    p = prompt.lower()
    named = lambda acc: any(w in p for w in re.findall(r"[a-z]{3,}", acc["name"].lower()) if w not in ("and", "the"))  # noqa: E731
    out = [acc for acc in catalog()["accelerators"] if named(acc)] if p else []
    for acc in catalog()["accelerators"]:
        if acc in out:
            continue
        if acc.get("always") or keys & set(acc.get("match", [])):
            out.append(acc)
    out.sort(key=lambda acc: not acc.get("live"))
    return [{k: acc[k] for k in ("name", "stage_tags", "text", "live", "url")} for acc in out[:6]]


def clip(s: str, n: int) -> str:
    s = " ".join((s or "").split())
    if len(s) <= n:
        return s
    cut = s[:n].rsplit(" ", 1)[0].rstrip(",;:-–—")
    return cut + "…"


def baseline(f: dict[str, Any], sections: list[str] | None = None, prompt: str = "") -> ReportContent:
    cat = catalog()
    short_project = re.split(r"\s+[-–—|:]\s+", f["project"])[0]
    c, geo = f["client"], f["geography"]
    where = f" in {geo}" if geo else ""
    tech = ", ".join(f["technologies"][:4]) or "modern data and AI platforms"
    ptypes = ", ".join(f["project_types"][:3]) or f["project"]
    high = [r for r in f["risks"] if r["rating"] == "high"]
    sc = f["scores"]["overall"]
    overall = sc.get("domain_adjusted") if sc.get("domain_adjusted") is not None else sc.get("comparable")
    answered = f["summary"]["evidence_coverage"].get("answered") or 0
    fw = cat["framework"]
    regs = ", ".join(x["name"] for x in f["compliance"][:3]) or "applicable regulations"
    gaps = len(f["scores"]["critical_gaps"])

    key_findings = [
        f"Classified as {f['industry']}" + (f" ({', '.join(f['sub_domains'][:3])})" if f["sub_domains"] else "") + f"; technologies: {tech}.",
        f"{f['summary']['questions_total']} tailored assessment questions; {answered:.0f}% answered so far." if answered else
        f"{f['summary']['questions_total']} tailored assessment questions generated; answers not yet captured.",
        f"Overall readiness {overall:.0f}% ({sc.get('domain_adjusted_rag', sc.get('comparable_rag', {})).get('label', '')})." if overall is not None
        else "Readiness not yet scored — answer the critical questions to produce comparable scores.",
        f"{f['summary']['risks']['total']} risks identified, {f['summary']['risks']['high']} rated high.",
        f"{len(f['compliance'])} regulations suggested for legal review, including {regs}.",
        f"{gaps} critical gaps to close before solutioning." if gaps else "No critical gaps outstanding.",
    ]
    doc_hint = f["documents"][0]["filename"] if f["documents"] else "client brief"
    content = {
        "title": clip(short_project if short_project.lower().startswith(c.lower()) else f"{c} {short_project}", 60),
        "subtitle": clip(f"{f['industry']}{(' · ' + geo) if geo else ''} — from discovery to delivery", 80),
        "tagline": f"{fw['name']} Framework  |  Aurora Accelerators  |  FDE Operating Model",
        "meta_line": f"Insight proposal for {c}  |  {f['industry']}  |  {date.today():%B %Y}",
        "sections": sections or DEFAULT_SECTIONS,
        "summary": {
            "title": "One partner, a proven method and value in 8 weeks",
            "intro": f"{c} is looking to deliver {f['project']}{where}. Insight responds with an AI-assisted method, ready "
                     f"accelerators and engineers embedded in {c}'s teams.",
            "need": {"headline": clip(short_project, 40), "text": clip(f["description"] or f"Deliver {f['project']} with one accountable partner.", 150)},
            "response": {"headline": f"{fw['name']}, made real with Aurora",
                         "text": f"Discover and rank opportunities, redesign, then deliver with {tech}."},
            "why_us": {"headline": "Accelerators and engineers, locally",
                       "text": "Live accelerators and Forward Deployed Engineers who build inside the business."},
            "value": {"headline": "Payback within the first year",
                      "text": "Illustrative targets: " + ", ".join(f"{s['value']} {s['label']}" for s in cat["value"]["stats"][:2]) + "."},
            "ask": f"Approve a fixed-fee, 2-week {fw['name']} sprint with {c}'s sponsors, led by an Insight FDE lead.",
        },
        "opportunity": {
            "title": f"{c} needs one partner from roadmap to run",
            "intro": clip((f["description"] or f"{c} wants to deliver {f['project']}{where}.") + f" Source: {doc_hint}.", 220),
            "challenges": [
                {"title": "Manual, resource-heavy work", "text": "Teams re-key, check and chase information across systems — slow turnaround and avoidable errors."},
                {"title": "No clear way to prioritise", "text": "Many candidate opportunities; the business needs value and feasibility evidence before it invests."},
                {"title": "One end-to-end partner", "text": "A roadmap alone is not enough: design and delivery must follow through to production."},
            ],
            "client_questions": [
                {"question": f"Local presence & delivery capability{where}?", "answer": "Yes — Insight's local leadership and Solutions team are engaged."},
                {"question": "Can Insight support it end to end?", "answer": f"Yes — {fw['name']} discovery, Aurora accelerators and FDE-led delivery."},
                {"question": "Which outcomes matter most?", "answer": "Efficiency, experience, quality and turnaround time — each baselined and tracked."},
            ],
        },
        "findings": {
            "title": f"What the assessment tells us about {c}",
            "intro": f"Generated by Project Assessment Studio from the {f['industry']} domain pack and {len(f['documents'])} client document(s).",
            "key_findings": key_findings,
        },
        "approach": {
            "title": f"{fw['name']} turns an opportunity inventory into a funded roadmap",
            "framework_name": fw["name"],
            "intro": "A five-stage, AI-assisted method that prioritises by business value and feasibility — and proves value in weeks. Click to build each stage.",
            "stages": fw["stages"],
            "core_stage_index": fw.get("core_stage_index", 2),
            "first_value_headline": "First value in 8 weeks",
            "first_value_text": "Every stage uses AI tooling and reusable assets, so the team spends its time on the client's processes, not on plumbing.",
            "timeline": fw["timeline"],
        },
        "accelerators": {
            "title": "Aurora accelerators make every stage faster",
            "intro": "Proven, reusable Insight assets instead of building from scratch.",
            "items": _pick_accelerators(f, prompt),
            "footnote": cat["accelerators_footnote"],
        },
        "value": {"title": "Targeted value: payback within the first year",
                  "intro": "Illustrative targets for in-scope processes — baselined in Discover and confirmed in Verify before scaling.",
                  **{k: cat["value"][k] for k in ("stats", "chart", "payback_note", "disclaimer")}},
        "operating_model": {"title": clip(cat["operating_model"]["title"].replace("the client's", f"{c}'s"), 62),
                            "intro": f"Small, senior Forward Deployed Engineer pods sit with {c}'s process owners — building in the flow of work and handing over a capability.",
                            "hub_label": c, "roles": cat["operating_model"]["roles"],
                            "comparison_title": cat["operating_model"]["comparison_title"],
                            "comparison": cat["operating_model"]["comparison"]},
        "roadmap": {"title": "A 90-day plan with enterprise-grade governance",
                    "intro": "From kick-off to a scale decision in 12 weeks, with clear milestones, decision gates and compliance checkpoints.",
                    **{k: cat["roadmap"][k] for k in ("phases", "milestones", "governance")},
                    "risks": [{"risk": clip(r["title"], 40), "mitigation": clip(r["mitigation"] or "Mitigation agreed with the client", 46)}
                              for r in (high or f["risks"])[:4]]},
        "why_us": {"title": f"Why Insight is the right partner for {c}",
                   "commitment": f"We prove value in 8 weeks — with live accelerators and engineers embedded in {c}'s teams — then scale what works.",
                   **{k: cat["why_us"][k] for k in ("proof_stats", "themes")}},
        "options": {"title": f"Engagement options that de-risk {c}'s decision",
                    "intro": "Start small with a fixed-fee sprint, prove value in a pilot, then scale on outcomes — the client decides at every gate.",
                    "items": cat["options"]["items"],
                    "next_steps": [{"when": "This week", "label": f"Discovery call with {c}'s sponsors"},
                                   {"when": "Week 1", "label": "Agree sprint scope, sponsors and shortlist"},
                                   {"when": "Weeks 2–3", "label": f"Run the {fw['name']} sprint; baseline in Assessment Studio"},
                                   {"when": "Week 4", "label": "Present roadmap & business case; decide on the pilot"}]},
        "closing": {"title": "Let's partner", "message": "Drive it in weeks. Make it real with Aurora. Scale it with FDEs.",
                    "next_step": f"Next step: discovery call with {c} and Insight's local leadership"},
        "battle_cards": cat["battle_cards"],
        "analysis": {
            "executive_narrative": f"This document summarises Insight's assessment of {c}'s {f['project']} opportunity. "
                                   f"The engagement is classified as {f['industry']}{(' (' + ', '.join(f['sub_domains']) + ')') if f['sub_domains'] else ''}"
                                   f"{where}, using {tech}. {key_findings[2]}",
            "context_narrative": f["description"] or f"{c} is assessing {f['project']}.",
            "readiness_commentary": key_findings[2] + " " + key_findings[1],
            "risk_commentary": key_findings[3] + (" The highest-rated risks are: " + "; ".join(r["title"] for r in high[:5]) + "." if high else ""),
            "compliance_commentary": key_findings[4] + " Applicability must be confirmed by an authorised reviewer.",
            "recommendations": [f"{r['title']}: {r['text']}" for r in f["recommendations"][:8]],
            "next_steps_narrative": "Agree the sprint scope and sponsors, answer the critical questions with evidence, confirm regulatory "
                                    "applicability with legal, and present the roadmap and business case at the end of the sprint.",
        },
    }
    return ReportContent.model_validate(content)


# ----------------------------------------------------------------------------- prompt handling
_KEYWORDS = {
    "battle_cards": ["battle card", "battlecard", "competit", "objection"],
    "findings": ["finding", "readiness", "assessment result", "score"],
    "value": ["value", "roi", "cost", "productiv", "efficien", "payback"],
    "operating_model": ["operating model", "fde", "forward deployed", "team model"],
    "accelerators": ["accelerator", "aurora", "migrator", "asset"],
    "roadmap": ["roadmap", "plan", "governance", "timeline"],
    "options": ["commercial", "option", "pricing", "next step"],
    "why_us": ["why insight", "win theme", "differentiat"],
    "approach": ["framework", "drive", "prove", "approach", "method"],
}


def sections_from_prompt(prompt: str, chosen: list[str] | None) -> list[str]:
    """Template mode: honour 'include/without X' style prompts on top of the chosen sections."""
    secs = list(chosen or DEFAULT_SECTIONS)
    p = (prompt or "").lower()
    for key, words in _KEYWORDS.items():
        if any(w in p for w in words):
            neg = any(re.search(rf"(without|exclude|no|skip|remove)\s+(the\s+)?[\w\s]{{0,20}}{re.escape(w)}", p) for w in words)
            if neg and key in secs:
                secs.remove(key)
            elif not neg and key not in secs:
                secs.append(key)
    return [k for k in SECTIONS if k in secs]


SYSTEM = """You are a senior Insight bid strategist. You write the content for an Insight-branded proposal deck and a \
companion analysis document for a client opportunity.

Rules:
- Ground every client fact in the assessment context and client documents provided. Never invent client names, \
people, numbers, systems or commitments. If a figure is not in the client material, keep it clearly illustrative \
(say so in the disclaimer/intro).
- Follow the user's prompt for focus, audience, tone, framework and which sections to include. Put the section keys \
to include, in order, in `sections` (allowed keys: {keys}). Include `battle_cards` only when the prompt asks for \
battle cards, competition or objections.
- Start from the draft content supplied (Insight's standard catalogue) and tailor it to this client and prompt. Keep \
Insight assets that are marked live as live; do not mark new accelerators as live.
- Slides are read by executives: titles are full-sentence messages under 65 characters; bullet-like texts are under \
140 characters; lists: 3 challenges, 3 client questions, 4-6 findings, 3-6 stages, 4 timeline items, up to 6 \
accelerators, 4 stats, 6 roles, 4 comparisons, up to 6 phases (weeks 0-16), up to 4 milestones, 3 governance \
forums, 4 risks, 3 proof stats, 5 themes, 3 options (one recommended) with 3 outputs each, 4 next steps, up to 5 \
competitors, 5 objections, 5 questions. Chart arrays must have equal length.
- The analysis section is prose for a Word document: 2-4 sentences per narrative, up to 8 recommendations.
- Use British English. Do not use the client's personal names or email addresses."""


def _context_text(f: dict[str, Any]) -> tuple[str, list[str]]:
    warnings: list[str] = []
    slim = {k: v for k, v in f.items() if k not in ("documents", "scores")}
    slim["readiness"] = {"overall": f["scores"]["overall"],
                         "groups": [{"label": g["label"], "score": g["score"], "rag": g["rag"]["label"]} for g in f["scores"]["groups"]],
                         "critical_gaps": [g["text"] for g in f["scores"]["critical_gaps"][:15]]}
    slim["risks"] = f["risks"][:25]
    docs, used = [], 0
    for d in f["documents"]:
        room = MAX_DOC_CHARS - used
        if room <= 0:
            warnings.append(f"Document '{d['filename']}' was not sent to the AI (document budget of {MAX_DOC_CHARS:,} characters reached).")
            continue
        text = d["text"]
        if len(text) > room:
            warnings.append(f"Document '{d['filename']}' was shortened to {room:,} characters for the AI.")
            text = text[:room]
        used += len(text)
        docs.append(f"<document name=\"{d['filename']}\">\n{text}\n</document>")
    return json.dumps(slim, default=str, indent=1) + "\n\n" + "\n".join(docs), warnings


def generate(db: Session, a: Assessment, prompt: str, sections: list[str] | None = None,
             use_ai: bool = True) -> dict[str, Any]:
    f = facts(db, a)
    chosen = sections_from_prompt(prompt, sections)
    base = baseline(f, chosen, prompt)
    warnings: list[str] = []
    if use_ai and llm.available():
        ctx, w = _context_text(f)
        warnings += w
        user = (f"<assessment_context>\n{ctx}\n</assessment_context>\n\n"
                f"<draft_content>\n{base.model_dump_json(indent=1)}\n</draft_content>\n\n"
                f"<user_prompt>\n{prompt.strip() or 'Create a professional leadership proposal deck.'}\n</user_prompt>\n\n"
                "Return the complete tailored content.")
        out = llm.complete_json(SYSTEM.format(keys=", ".join(SECTIONS)), user, strict_json_schema(ReportContent), max_tokens=20000)
        if out is not None:
            try:
                content = ReportContent.model_validate(out)
                content.sections = [k for k in content.sections if k in SECTIONS] or chosen
                return {"content": content.model_dump(), "method": "ai", "warnings": warnings}
            except ValidationError as e:
                warnings.append(f"AI output did not match the report format ({e.error_count()} issues); the template was used.")
        else:
            warnings.append("The AI call failed; the template content was used.")
    elif use_ai:
        warnings.append("AI is not configured on this server (set ANTHROPIC_API_KEY). Template content was generated from "
                        "the assessment data; the prompt was applied to section selection only.")
    return {"content": base.model_dump(), "method": "template", "warnings": warnings}
