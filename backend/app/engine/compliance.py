"""Configuration-driven regulatory suggestions (32.8).

The engine only ever produces ``potentially_applicable`` suggestions. Every other
status is a human decision recorded with reviewer + timestamp. The system never
infers compliance from the presence of a technology or control.
"""
from __future__ import annotations

from typing import Any

from .conditions import evaluate, sub_domain_applies
from .context import AssessmentContext, PackRef

STATUSES = {
    "potentially_applicable": "Potentially applicable (system suggestion – needs review)",
    "confirmed_applicable": "Confirmed applicable by client / legal / compliance",
    "not_applicable": "Confirmed not applicable by client / legal / compliance",
    "verified": "Compliance requirement verified (evidence reviewed)",
    "unknown": "Unknown – awaiting information",
}
HUMAN_ONLY_STATUSES = {"confirmed_applicable", "not_applicable", "verified"}

DISCLAIMER = (
    "Regulatory items are suggestions derived from domain-pack configuration "
    "(industry + geography + data classification + project type). They are not legal advice, "
    "and the presence of a technology or control does not establish compliance. An authorised "
    "human reviewer must confirm applicability and verify each requirement."
)


def _match(values: list[str], actual: set[str]) -> tuple[bool | None, list[str]]:
    """None = cannot decide (context missing), True/False otherwise."""
    if not values:
        return True, []
    if not actual:
        return None, []
    hit = {v.lower() for v in values} & {a.lower() for a in actual}
    return (bool(hit), sorted(hit))


def suggest(ctx: AssessmentContext, packs: list[PackRef], reviews: dict[str, Any],
            rule_sources: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    seen: dict[str, dict[str, Any]] = {}
    for pack in packs:
        for c in pack.content.compliance:
            if not sub_domain_applies(c.sub_domains, pack):
                continue
            ok, when_reasons = evaluate(c.when, ctx, pack)
            if not ok:
                continue
            reasons, unknowns = list(when_reasons), []
            geo_ok, geo_hit = _match(c.geographies, ctx.geo_codes if ctx.geography or ctx.regulatory_regions else set())
            if geo_ok is False:
                continue
            if geo_ok is None:
                unknowns.append("geography not specified")
            elif geo_hit:
                reasons.append(f"geography/region: {', '.join(geo_hit)}")
            dc_ok, dc_hit = _match(c.data_classifications_any, set(ctx.data_classifications))
            if dc_ok is False:
                continue
            if dc_ok is None:
                unknowns.append(f"data classification not confirmed (applies to: {', '.join(c.data_classifications_any)})")
            elif dc_hit:
                reasons.append(f"data classification: {', '.join(dc_hit)}")
            for vals, actual, label in ((c.project_types_any, set(ctx.project_types), "project type"),
                                        (c.industries_any, set(ctx.industries), "industry"),
                                        (c.technologies_any, set(ctx.technologies), "technology")):
                m, hit = _match(vals, actual)
                if m is False or m is None and vals:
                    break
                if hit:
                    reasons.append(f"{label}: {', '.join(hit)}")
            else:
                if pack.kind != "global":
                    reasons.insert(0, f"{pack.role} domain: {pack.name}")
                key = c.id
                if key in seen:
                    seen[key]["also_suggested_by"].append(pack.key)
                    continue
                review = reviews.get(key, {})
                status = review.get("status", "potentially_applicable")
                seen[key] = {
                    "key": key, "id": c.id, "name": c.name, "short_name": c.short_name or c.name,
                    "description": c.description, "jurisdiction": c.jurisdiction, "reference": c.reference,
                    "obligations": c.obligations, "applicability_note": c.applicability_note,
                    "origin": pack.origin_for(c.sub_domains), "source": pack.source(c.sub_domains),
                    "suggestion_reasons": reasons, "open_factors": unknowns, "also_suggested_by": [],
                    "status": status, "status_label": STATUSES.get(status, status),
                    "reviewer": review.get("reviewer"), "reviewed_at": review.get("reviewed_at"),
                    "evidence": review.get("evidence"), "notes": review.get("notes"),
                    "human_reviewed": status in HUMAN_ONLY_STATUSES or status == "unknown" and bool(review.get("reviewer")),
                }
                if rule_sources is not None:
                    rule_sources.append({"rule_type": "compliance", "rule_key": f"{pack.key}:{c.id}",
                                         "origin": seen[key]["origin"], "pack_key": pack.key,
                                         "pack_version": pack.version, "role": pack.role,
                                         "sub_domain": seen[key]["source"]["sub_domain"],
                                         "status": "included", "merged_into": None})
    return list(seen.values())
