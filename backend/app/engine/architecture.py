"""Domain-aware architecture recommendation (32.11).

Patterns and components come from domain packs. A pattern is only proposed when
its condition matches the assessment, and each non-core component is only
included when its own condition is supported by the client's requirements,
answers or selections. Excluded components are listed with the reason, so the
architecture is never a generic "everything" diagram.
"""
from __future__ import annotations

from typing import Any

from ..schemas.domain_pack import Condition
from .conditions import evaluate, sub_domain_applies
from .context import AssessmentContext, PackRef

DEFAULT_LAYERS = ["sources", "ingestion", "storage", "processing", "modelling", "serving", "consumption", "ai",
                  "governance", "security", "operations"]


def describe(cond: Condition | None) -> str:
    if cond is None:
        return "always"
    parts = []
    for field, label in (("sub_domains_any", "sub-domain"), ("industries_any", "industry"),
                         ("technologies_any", "technology"), ("project_types_any", "project type"),
                         ("geographies_any", "geography"), ("data_classifications_any", "data classification"),
                         ("keywords_any", "requirement mentioning")):
        vals = getattr(cond, field)
        if vals:
            parts.append(f"{label} in [{', '.join(vals)}]")
    for q, v in cond.answers.items():
        parts.append(f"answer to {q} = {v}")
    if cond.any_of:
        parts.append("any of (" + " | ".join(describe(c) for c in cond.any_of) + ")")
    if cond.not_ is not None:
        parts.append(f"not ({describe(cond.not_)})")
    return "; ".join(parts) or "always"


def recommend(ctx: AssessmentContext, packs: list[PackRef], rule_sources: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    selected, considered = [], 0
    for pack in packs:
        for p in pack.content.architecture_patterns:
            considered += 1
            if not sub_domain_applies(p.sub_domains, pack):
                continue
            ok, reasons = evaluate(p.when, ctx, pack)
            if not ok:
                continue
            comps_in, comps_out = [], []
            for c in p.components:
                if c.core:
                    comps_in.append({"id": c.id, "name": c.name, "layer": c.layer, "purpose": c.purpose,
                                     "alternatives": c.alternatives, "why": ["core component of this pattern"]})
                    continue
                c_ok, c_reasons = evaluate(c.when, ctx, pack)
                if c_ok and c.when is not None:
                    comps_in.append({"id": c.id, "name": c.name, "layer": c.layer, "purpose": c.purpose,
                                     "alternatives": c.alternatives, "why": c_reasons or ["condition satisfied"]})
                elif c_ok:
                    comps_in.append({"id": c.id, "name": c.name, "layer": c.layer, "purpose": c.purpose,
                                     "alternatives": c.alternatives, "why": ["pattern default"]})
                else:
                    comps_out.append({"id": c.id, "name": c.name, "layer": c.layer,
                                      "excluded_because": f"not supported by current requirements – needs {describe(c.when)}"})
            order = p.layer_order or DEFAULT_LAYERS
            layers: dict[str, list[dict[str, Any]]] = {}
            for c in comps_in:
                layers.setdefault(c["layer"], []).append(c)
            ordered = [{"layer": l, "components": layers[l]} for l in order if l in layers]
            ordered += [{"layer": l, "components": cs} for l, cs in layers.items() if l not in order]
            selected.append({
                "key": f"{pack.key}:{p.id}", "id": p.id, "name": p.name, "description": p.description,
                "use_cases": p.use_cases, "origin": pack.origin_for(p.sub_domains), "source": pack.source(p.sub_domains),
                "selected_because": reasons or ["applies to the selected domain"], "relevance": len(reasons),
                "layers": ordered, "excluded_components": comps_out, "considerations": p.considerations,
                "diagram": _diagram(ordered),
            })
            if rule_sources is not None:
                rule_sources.append({"rule_type": "architecture_pattern", "rule_key": f"{pack.key}:{p.id}",
                                     "origin": pack.origin_for(p.sub_domains), "pack_key": pack.key,
                                     "pack_version": pack.version, "role": pack.role, "sub_domain": None,
                                     "status": "included", "merged_into": None})
    selected.sort(key=lambda s: -s["relevance"])
    inputs = {
        "industry": ctx.primary_industry, "sub_domains": ctx.sub_domains, "technologies": ctx.technologies,
        "project_types": ctx.project_types, "geography": ctx.geography,
        "data_classifications": ctx.data_classifications,
        "constraints_from_answers": len(ctx.answers), "documents_considered": bool(ctx.document_text),
    }
    return {"patterns": selected, "patterns_considered": considered, "inputs": inputs,
            "note": "Components are included only when supported by client requirements, answers or selections; "
                    "validate against existing architecture, budget and team skills before committing."}


def _diagram(layers: list[dict[str, Any]]) -> str:
    lines = []
    for i, l in enumerate(layers):
        names = ", ".join(c["name"] for c in l["components"])
        lines.append(f"[{l['layer'].upper()}] {names}")
        if i < len(layers) - 1:
            lines.append("        |")
            lines.append("        v")
    return "\n".join(lines)
