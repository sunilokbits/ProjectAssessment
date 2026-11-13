"""Domain auto-detection from client documents (32.5).

Produces a *suggestion* only. The assessment is never classified until a user
confirms (or changes) the suggestion through the confirm-classification API.
"""
from __future__ import annotations

import math
from typing import Any

from ..schemas.domain_pack import DomainPackContent
from . import llm
from .text import count_keyword

MAX_AI_CHARS = 400_000


def _signal(text: str, pairs: list[tuple[str, float]]) -> tuple[float, list[str]]:
    score, evidence = 0.0, []
    for kw, w in pairs:
        n = count_keyword(text, kw)
        if n:
            score += w * (1 + math.log(n))
            evidence.append(f"{kw} ×{n}")
    return score, evidence


def _pack_pairs(c: DomainPackContent) -> list[tuple[str, float]]:
    pairs = [(k, float(w)) for k, w in c.domain.detection.keywords.items()]
    seen = {k.lower() for k, _ in pairs}
    for t in c.terminology:
        for term in [t.term, *t.synonyms]:
            if term.lower() not in seen and len(term) > 2:
                pairs.append((term, 0.3))
                seen.add(term.lower())
    return pairs


def detect(text: str, packs: list[DomainPackContent], reference: dict[str, Any]) -> dict[str, Any]:
    low = text.lower()
    by_kind: dict[str, list[dict[str, Any]]] = {"industry": [], "technology": [], "project_type": []}
    contents = {p.domain.key: p for p in packs}
    for c in packs:
        kind = c.domain.kind.value
        if kind not in by_kind:
            continue
        score, ev = _signal(low, _pack_pairs(c))
        if score >= c.domain.detection.min_score:
            by_kind[kind].append({"key": c.domain.key, "name": c.domain.name, "score": round(score, 2), "evidence": ev[:8]})
    for lst in by_kind.values():
        lst.sort(key=lambda x: -x["score"])

    sat = float(reference.get("detection", {}).get("saturation", 12))
    industries = by_kind["industry"]
    for i, ind in enumerate(industries):
        nxt = industries[i + 1]["score"] if i + 1 < len(industries) else 0.0
        top = industries[0]["score"]
        rel = ind["score"] / (ind["score"] + (nxt if i == 0 else top))
        ind["confidence"] = round(min(0.99, rel * min(1.0, ind["score"] / sat)), 2)

    result: dict[str, Any] = {"industry": industries[0] if industries else None,
                              "industry_alternatives": industries[1:4], "sub_domains": [],
                              "technologies": [], "project_types": [], "method": "keyword",
                              "requires_confirmation": True}
    if industries:
        c = contents[industries[0]["key"]]
        subs = []
        for s in c.domain.sub_domains:
            sc, ev = _signal(low, [(k, 1.0) for k in [s.name, *s.keywords]])
            if sc > 0:
                subs.append({"key": s.key, "name": s.name, "score": round(sc, 2), "evidence": ev[:5]})
        subs.sort(key=lambda x: -x["score"])
        total = sum(s["score"] for s in subs) or 1
        for s in subs:
            s["confidence"] = round(min(0.99, (s["score"] / total) * min(1.0, s["score"] / 4)), 2)
        result["sub_domains"] = subs[:3]
    for kind in ("technology", "project_type"):
        items = by_kind[kind]
        for t in items:
            t["confidence"] = round(min(0.99, t["score"] / (t["score"] + 3)), 2)
        result["technologies" if kind == "technology" else "project_types"] = [t for t in items if t["confidence"] >= 0.3][:8]

    ai = _ai_refine(text, packs, result)
    if ai:
        result = ai
    return result


_AI_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["industry", "industry_confidence", "industry_evidence", "sub_domains", "technologies", "project_types"],
    "properties": {
        "industry": {"type": "string"},
        "industry_confidence": {"type": "number"},
        "industry_evidence": {"type": "array", "items": {"type": "string"}},
        "sub_domains": {"type": "array", "items": {
            "type": "object", "additionalProperties": False, "required": ["key", "confidence", "evidence"],
            "properties": {"key": {"type": "string"}, "confidence": {"type": "number"}, "evidence": {"type": "string"}}}},
        "technologies": {"type": "array", "items": {
            "type": "object", "additionalProperties": False, "required": ["key", "confidence", "evidence"],
            "properties": {"key": {"type": "string"}, "confidence": {"type": "number"}, "evidence": {"type": "string"}}}},
        "project_types": {"type": "array", "items": {
            "type": "object", "additionalProperties": False, "required": ["key", "confidence", "evidence"],
            "properties": {"key": {"type": "string"}, "confidence": {"type": "number"}, "evidence": {"type": "string"}}}},
    },
}


def _ai_refine(text: str, packs: list[DomainPackContent], baseline: dict[str, Any]) -> dict[str, Any] | None:
    if not llm.available() or not text.strip():
        return None
    catalog = []
    for c in packs:
        k = c.domain.kind.value
        if k == "industry":
            subs = ", ".join(f"{s.key} ({s.name})" for s in c.domain.sub_domains)
            catalog.append(f"INDUSTRY {c.domain.key} ({c.domain.name}); sub-domains: {subs}")
        elif k in ("technology", "project_type"):
            catalog.append(f"{k.upper()} {c.domain.key} ({c.domain.name})")
    truncated = len(text) > MAX_AI_CHARS
    system = ("You classify client documents (RFP, RFI, BRD, SOW, architecture or requirements documents) "
              "for a project assessment tool. Choose ONLY keys from the catalog. Confidence is 0–1. "
              "Quote short evidence from the document. If the industry is unclear use 'unknown'.")
    user = (f"Catalog:\n" + "\n".join(catalog) +
            f"\n\nKeyword baseline (may be wrong): industry={baseline['industry']['key'] if baseline['industry'] else 'none'}"
            f"\n\nDocument{' (first part only)' if truncated else ''}:\n<document>\n{text[:MAX_AI_CHARS]}\n</document>")
    out = llm.complete_json(system, user, _AI_SCHEMA, max_tokens=4000)
    if not out:
        return None
    names = {c.domain.key: c for c in packs}
    ind = names.get(out["industry"])
    if not ind or ind.domain.kind.value != "industry":
        return None
    subs_ok = {s.key: s.name for s in ind.domain.sub_domains}

    def items(lst, kind):
        res = []
        for x in lst:
            c = names.get(x["key"])
            if c and c.domain.kind.value == kind:
                res.append({"key": x["key"], "name": c.domain.name, "confidence": round(float(x["confidence"]), 2),
                            "evidence": [x["evidence"]]})
        return res

    alts = [a for a in ([baseline["industry"]] if baseline["industry"] else []) + baseline["industry_alternatives"]
            if a and a["key"] != ind.domain.key]
    return {
        "industry": {"key": ind.domain.key, "name": ind.domain.name,
                     "confidence": round(float(out["industry_confidence"]), 2), "evidence": out["industry_evidence"][:6]},
        "industry_alternatives": alts[:3],
        "sub_domains": [{"key": s["key"], "name": subs_ok[s["key"]], "confidence": round(float(s["confidence"]), 2),
                         "evidence": [s["evidence"]]} for s in out["sub_domains"] if s["key"] in subs_ok][:3],
        "technologies": items(out["technologies"], "technology")[:8],
        "project_types": items(out["project_types"], "project_type")[:4],
        "method": "keyword+ai", "document_truncated_for_ai": truncated, "requires_confirmation": True,
        "keyword_baseline": baseline,
    }
