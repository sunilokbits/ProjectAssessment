"""Build domain-aware AI context (32.14).

Domain-pack configuration and verified client evidence are placed ahead of
general model knowledge, and the rules are stated explicitly.
"""
from __future__ import annotations

from typing import Any

from .context import AssessmentContext

PRIORITY_RULES = """Source priority (highest first):
1. Verified client evidence (answers marked verified, uploaded client documents).
2. The selected Domain Pack configuration below (terminology, rules, risks, KPIs, compliance references).
3. General model knowledge – use only to fill gaps, and say when you do.

Rules:
- Use the domain terminology defined below; map client wording to these terms.
- Never invent client KPI targets, budgets, volumes or dates. Ask instead.
- Never state that the client IS compliant with a regulation. Regulations are only
  'potentially applicable' until confirmed by the client's legal/compliance team.
- Only recommend architecture components that the client's requirements support.
- Mark every inference with a confidence level and the evidence it is based on."""


def _name_of(ctx: AssessmentContext, key: str | None) -> str:
    if not key:
        return "Not selected"
    p = ctx.pack(key)
    return p.name if p else key


def _sub_names(ctx: AssessmentContext) -> str:
    p = ctx.pack(ctx.primary_industry) if ctx.primary_industry else None
    if not p:
        return "Not selected"
    names = {s.key: s.name for s in p.content.domain.sub_domains}
    return ", ".join(names.get(s, s) for s in ctx.sub_domains) or "Not selected"


def build_context(ctx: AssessmentContext, profile: dict[str, Any], max_terms: int = 60) -> dict[str, Any]:
    geo_name = ctx.geography or "Not specified"
    for g in ctx.reference.get("geographies", []):
        if ctx.geography and g.get("code", "").upper() == ctx.geography.upper():
            geo_name = g.get("name", geo_name)
    header = "\n".join([
        f"Client: {ctx.client_name or 'Not specified'}",
        f"Industry: {_name_of(ctx, ctx.primary_industry)}",
        f"Sub-domain: {_sub_names(ctx)}",
        "Secondary domains: " + (", ".join(_name_of(ctx, s['key']) for s in ctx.secondary_industries) or "None"),
        f"Geography: {geo_name}",
        "Regulatory regions: " + (", ".join(ctx.regulatory_regions) or "Not specified"),
        "Technology: " + (", ".join(_name_of(ctx, t) for t in ctx.technologies) or "Not selected"),
        "Project: " + (", ".join(_name_of(ctx, t) for t in ctx.project_types) or ctx.project_name or "Not selected"),
        "Data classification: " + (", ".join(ctx.data_classifications) or "Not confirmed"),
        f"Stage: {ctx.stage.title()}",
    ])
    terms = profile.get("terminology", [])[:max_terms]
    glossary = "\n".join(
        f"- {t['term']}: {t['definition']}" + (f" (synonyms: {', '.join(t['synonyms'])})" if t["synonyms"] else "")
        for t in terms)
    pack_lines = "\n".join(f"- {p['name']} v{p['version']} ({p['role']})" for p in profile.get("packs", []))
    additions = "\n\n".join(f"[{a['pack_key']}] {a['text']}" for a in profile.get("prompt_additions", []))
    compliance = "\n".join(f"- {c['short_name']}: {c['status_label']}" for c in profile.get("compliance", []))
    verified = [k for k, v in ctx.answers.items() if v is not None]
    system = "\n\n".join(filter(None, [
        "You are assisting a delivery team with a domain-specific project assessment.",
        "## Assessment context\n" + header,
        "## Domain packs in use\n" + pack_lines,
        PRIORITY_RULES,
        "## Domain-pack instructions\n" + additions if additions else "",
        "## Domain terminology\n" + glossary if glossary else "",
        "## Regulatory items (status as recorded)\n" + compliance if compliance else "",
    ]))
    return {"header": header, "system_prompt": system, "terminology_count": len(profile.get("terminology", [])),
            "answers_available": len(verified), "packs": profile.get("packs", [])}
