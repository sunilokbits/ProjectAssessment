"""Domain-aware requirement extraction and AI-discovered clarification questions (32.6 / 32.4 L4)."""
from __future__ import annotations

import hashlib
import re
from typing import Any

from . import llm
from .text import contains_keyword, split_sentences

DEFAULT_MARKERS = ["shall", "must", "should", "will need", "needs to", "need to", "required", "requirement",
                   "is expected to", "has to", "have to", "ability to", "support", "provide", "enable"]


def _key(text: str) -> str:
    return hashlib.sha1(text.lower().encode()).hexdigest()[:12]


def _term_index(profile: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    idx = []
    for t in profile.get("terminology", []):
        for w in [t["term"], *t["synonyms"]]:
            if len(w) >= 2:
                idx.append((w, t))
    idx.sort(key=lambda x: -len(x[0]))  # longest match first
    return idx


def extract_requirements(text: str, profile: dict[str, Any], reference: dict[str, Any], doc_name: str = "") -> list[dict[str, Any]]:
    markers = reference.get("requirement_markers", DEFAULT_MARKERS)
    categories: dict[str, list[str]] = reference.get("requirement_categories", {})
    nfr_categories = set(reference.get("non_functional_categories", []))
    terms = _term_index(profile)
    reqs = []
    for s in split_sentences(text):
        low = s.lower()
        if not any(contains_keyword(low, m) for m in markers):
            continue
        cats = [c for c, kws in categories.items() if any(contains_keyword(low, k) for k in kws)]
        found: dict[str, dict[str, Any]] = {}
        for w, t in terms:
            if t["term"] not in found and contains_keyword(low, w):
                found[t["term"]] = {"term": t["term"], "matched": w, "entity_type": t["entity_type"],
                                    "category": t["category"], "origin": t["origin"],
                                    "pack_key": t["source"]["pack_key"]}
        for f in found.values():  # domain terminology improves classification
            if f["category"] in categories and f["category"] not in cats:
                cats.append(f["category"])
        primary = cats[0] if cats else "functional"
        reqs.append({
            "key": _key(s), "text": s, "document": doc_name,
            "type": "non_functional" if primary in nfr_categories else "functional",
            "category": primary, "categories": cats or ["functional"],
            "domain_terms": list(found.values()),
            "regulatory_terms": [f["term"] for f in found.values() if f["entity_type"] == "regulation"],
            "confidence": round(min(0.95, 0.5 + 0.1 * len(cats) + 0.05 * len(found)), 2),
            "method": "rules+domain-terminology",
        })
    return reqs


def clarification_questions(text: str, requirements: list[dict[str, Any]], profile: dict[str, Any],
                            reference: dict[str, Any], ai_context: str | None = None) -> list[dict[str, Any]]:
    """Questions discovered from client documents (origin AI-DISCOVERED)."""
    out: dict[str, dict[str, Any]] = {}
    amb: dict[str, dict[str, str]] = reference.get("ambiguity_terms", {})
    cat_dim: dict[str, str] = reference.get("category_dimension", {})
    for r in requirements:
        low = r["text"].lower()
        for word, cfg in amb.items():
            word = str(word)
            if contains_keyword(low, word):
                excerpt = r["text"] if len(r["text"]) <= 160 else r["text"][:157] + "…"
                q = cfg["question"].format(term=word, excerpt=excerpt)
                k = _key(q)
                out.setdefault(k, {"key": k, "text": q, "category": cfg.get("category", "clarification"),
                                   "dimension": cfg.get("dimension") or cat_dim.get(r["category"]),
                                   "rationale": f"Ambiguous term '{word}' in: \"{excerpt}\"",
                                   "confidence": 0.7, "method": "rules", "source_excerpt": excerpt})
    # Domain entities mentioned without any data-source detail
    entity_terms = {t["term"] for r in requirements for t in r["domain_terms"] if t["entity_type"] == "entity"}
    if entity_terms and not re.search(r"\b(source system|system of record|from (the )?[A-Z]\w+)", text):
        q = ("Which source systems are the systems of record for: " + ", ".join(sorted(entity_terms)[:8]) + "?")
        k = _key(q)
        out[k] = {"key": k, "text": q, "category": "data", "dimension": cat_dim.get("data"),
                  "rationale": "Domain entities are referenced but no source systems are identified in the documents.",
                  "confidence": 0.6, "method": "rules", "source_excerpt": ""}
    for q in _ai_questions(text, profile, ai_context, cat_dim):
        out.setdefault(q["key"], q)
    return list(out.values())


_AI_SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["questions"],
    "properties": {"questions": {"type": "array", "items": {
        "type": "object", "additionalProperties": False,
        "required": ["text", "category", "rationale", "evidence", "confidence"],
        "properties": {"text": {"type": "string"}, "category": {"type": "string"}, "rationale": {"type": "string"},
                       "evidence": {"type": "string"}, "confidence": {"type": "number"}}}}},
}


def _ai_questions(text: str, profile: dict[str, Any], ai_context: str | None, cat_dim: dict[str, str]) -> list[dict[str, Any]]:
    if not ai_context or not llm.available() or not text.strip():
        return []
    existing = "\n".join(f"- {q['text']}" for q in profile.get("questions", [])[:150])
    user = ("Read the client documents and propose up to 12 clarification questions that are NOT already covered by "
            "the existing questionnaire. Focus on gaps, ambiguities, missing measurable targets and domain-specific "
            "concerns. Category must be one of: business, data, architecture, security, delivery, domain, technology.\n\n"
            f"Existing questionnaire:\n{existing}\n\n<documents>\n{text[:300_000]}\n</documents>")
    out = llm.complete_json(ai_context, user, _AI_SCHEMA, max_tokens=8000)
    if not out:
        return []
    res = []
    for q in out.get("questions", [])[:12]:
        k = _key(q["text"])
        res.append({"key": k, "text": q["text"], "category": q["category"], "dimension": cat_dim.get(q["category"]),
                    "rationale": q["rationale"], "confidence": round(float(q["confidence"]), 2), "method": "ai",
                    "source_excerpt": q["evidence"]})
    return res
