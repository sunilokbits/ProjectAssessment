"""Evaluate declarative ``Condition`` rules from domain packs against an assessment."""
from __future__ import annotations

from typing import Any

from ..schemas.domain_pack import Condition
from .context import AssessmentContext, PackRef
from .text import contains_keyword


def _lower(xs: list[str]) -> set[str]:
    return {x.lower() for x in xs}


def _answer_matches(actual: Any, expected: Any) -> bool:
    if actual is None:
        return False
    exp = expected if isinstance(expected, list) else [expected]
    exp_norm = {str(e).lower() for e in exp}
    if isinstance(actual, list):
        return bool({str(a).lower() for a in actual} & exp_norm)
    if isinstance(actual, bool):
        return ("yes" if actual else "no") in exp_norm or str(actual).lower() in exp_norm
    return str(actual).lower() in exp_norm


def evaluate(cond: Condition | None, ctx: AssessmentContext, pack: PackRef | None = None) -> tuple[bool, list[str]]:
    """Return (matched, reasons). An empty / missing condition always matches."""
    if cond is None:
        return True, []
    reasons: list[str] = []

    def check(values: list[str], actual: set[str], label: str) -> bool:
        if not values:
            return True
        hit = _lower(values) & {a.lower() for a in actual}
        if hit:
            reasons.append(f"{label}: {', '.join(sorted(hit))}")
            return True
        return False

    subs = set(pack.sub_domains if pack else []) | set(ctx.all_sub_domains)
    checks = [
        check(cond.sub_domains_any, subs, "sub-domain"),
        check(cond.industries_any, set(ctx.industries), "industry"),
        check(cond.technologies_any, set(ctx.technologies), "technology"),
        check(cond.project_types_any, set(ctx.project_types), "project type"),
        check(cond.geographies_any, ctx.geo_codes, "geography"),
        check(cond.regulatory_regions_any, {r.upper() for r in ctx.regulatory_regions} | {r.lower() for r in ctx.regulatory_regions}, "regulatory region"),
        check(cond.data_classifications_any, set(ctx.data_classifications), "data classification"),
        check(cond.stages_any, {ctx.stage}, "stage"),
    ]
    if not all(checks):
        return False, []

    if cond.keywords_any:
        text = ctx.document_text.lower()
        hits = [k for k in cond.keywords_any if contains_keyword(text, k)]
        if not hits:
            return False, []
        reasons.append(f"document mentions: {', '.join(hits[:5])}")

    for qid, expected in cond.answers.items():
        if not _answer_matches(ctx.answer_by_id(qid), expected):
            return False, []
        reasons.append(f"answer {qid} = {expected}")

    if cond.any_of:
        matched_any = False
        for sub in cond.any_of:
            ok, r = evaluate(sub, ctx, pack)
            if ok:
                matched_any = True
                reasons += r
                break
        if not matched_any:
            return False, []

    if cond.not_ is not None:
        ok, _ = evaluate(cond.not_, ctx, pack)
        if ok:
            return False, []
    return True, reasons


def sub_domain_applies(item_sub_domains: list[str], pack: PackRef) -> bool:
    return not item_sub_domains or bool(set(item_sub_domains) & set(pack.sub_domains))
