"""Merge the domain packs mapped to an assessment into one resolved profile.

Layering (32.4 / 32.9 / 32.13):
    GLOBAL + INDUSTRY (+ SUB-DOMAIN) + TECHNOLOGY + PROJECT + AI-DISCOVERED

Rules
- Items are filtered by sub-domain and by their declarative ``when`` condition.
- Duplicates (same equivalence key or semantically similar text) are removed; the
  higher-priority source wins (primary domain > project > technology > secondary > global)
  and the losing copies are recorded in ``merged_from`` and as rule sources.
- Conflicting recommendations (same decision key, different option, or explicit
  ``conflicts_with``) are all kept and surfaced for human review.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Iterable

from ..schemas.domain_pack import KNOWLEDGE_SECTIONS
from . import architecture, compliance
from .conditions import evaluate, sub_domain_applies
from .context import ORIGIN_ORDER, AssessmentContext, PackRef
from .text import contains_keyword, token_similarity, tokens

DEFAULT_THRESHOLD = 0.82


@dataclass
class Candidate:
    pack: PackRef | None
    item: Any
    idx: int
    key: str
    text: str
    origin: str
    source: dict[str, Any]
    reasons: list[str] = field(default_factory=list)
    equivalence: str | None = None
    merged_from: list[dict[str, Any]] = field(default_factory=list)

    @property
    def priority(self) -> tuple:
        if self.pack is None:  # AI-discovered: lowest priority, never overrides configuration
            return (10, 0, self.idx)
        p = self.pack.priority
        # sub-domain specific items beat industry-wide items of the same pack
        return (p[0], p[1], 0 if self.origin == "SUB-DOMAIN" else 1, self.idx)


class Resolver:
    def __init__(self, ctx: AssessmentContext, extras: dict[str, Any] | None = None):
        self.ctx = ctx
        self.extras = extras or {}
        ref = ctx.reference.get("dedupe", {})
        self.threshold = float(ref.get("similarity_threshold", DEFAULT_THRESHOLD))
        self.packs = sorted(ctx.packs, key=lambda p: p.priority)
        self.rule_sources: list[dict[str, Any]] = []
        self.synonyms = self._synonym_map()

    # ------------------------------------------------------------------ helpers
    def _synonym_map(self) -> dict[str, str]:
        from .text import _stem

        out: dict[str, str] = {}
        for p in self.packs:
            for t in p.content.terminology:
                canon = t.term.lower()
                if " " in canon:
                    continue
                for s in t.synonyms:
                    if " " not in s:
                        out[_stem(s.lower())] = _stem(canon)
        return out

    def _src(self, rule_type: str, c: Candidate, status: str = "included", merged_into: str | None = None):
        self.rule_sources.append({
            "rule_type": rule_type, "rule_key": c.key, "origin": c.origin,
            "pack_key": c.source.get("pack_key"), "pack_version": c.source.get("pack_version"),
            "role": c.source.get("role"), "sub_domain": c.source.get("sub_domain"),
            "status": status, "merged_into": merged_into,
        })

    def _candidates(self, getter: Callable[[Any], Iterable[Any]], text_of: Callable[[Any], str],
                    equiv: Callable[[Any], str | None] = lambda it: None) -> list[Candidate]:
        out: list[Candidate] = []
        for pack in self.packs:
            for idx, it in enumerate(getter(pack.content)):
                subs = getattr(it, "sub_domains", []) or []
                if not sub_domain_applies(subs, pack):
                    continue
                ok, reasons = evaluate(getattr(it, "when", None), self.ctx, pack)
                if not ok:
                    continue
                item_id = getattr(it, "id", None) or getattr(it, "term", str(idx))
                out.append(Candidate(
                    pack=pack, item=it, idx=idx, key=f"{pack.key}:{item_id}", text=text_of(it),
                    origin=pack.origin_for(subs), source=pack.source(subs), reasons=reasons,
                    equivalence=equiv(it),
                ))
        out.sort(key=lambda c: c.priority)
        return out

    def _dedupe(self, rule_type: str, cands: list[Candidate]) -> list[Candidate]:
        accepted: list[Candidate] = []
        toks: dict[int, frozenset[str]] = {}
        for c in cands:
            dup = None
            tc = toks.setdefault(id(c), tokens(c.text, self.synonyms))
            for a in accepted:
                if c.equivalence and a.equivalence and c.equivalence == a.equivalence:
                    dup, why = a, f"same equivalence key '{c.equivalence}'"
                    break
                sim = token_similarity(tc, toks[id(a)], self.threshold)
                if sim >= self.threshold:
                    dup, why = a, f"semantically equivalent ({sim:.0%} similar)"
                    break
            if dup is not None:
                dup.merged_from.append({**c.source, "key": c.key, "origin": c.origin, "text": c.text, "reason": why})
                self._src(rule_type, c, "duplicate", dup.key)
            else:
                accepted.append(c)
                self._src(rule_type, c)
        return accepted

    @staticmethod
    def _origin_sort(cands: list[Candidate]) -> list[Candidate]:
        return sorted(cands, key=lambda c: (ORIGIN_ORDER.index(c.origin), c.priority))

    def _base(self, c: Candidate) -> dict[str, Any]:
        return {"key": c.key, "origin": c.origin, "source": c.source, "merged_from": c.merged_from,
                "applies_because": c.reasons}

    # --------------------------------------------------------------- sections
    def questions(self) -> list[dict[str, Any]]:
        cands = self._candidates(lambda c: c.questions, lambda q: q.text, lambda q: q.equivalence_key)
        for i, aq in enumerate(self.extras.get("ai_questions", [])):
            cands.append(Candidate(
                pack=None, item=aq, idx=i, key=f"ai:{aq['key']}", text=aq["text"], origin="AI-DISCOVERED",
                source={"pack_key": None, "pack_name": "AI (client documents)", "pack_version": None,
                        "role": "ai", "sub_domain": None},
                reasons=[aq.get("rationale", "generated from client documents")],
            ))
        out = []
        for c in self._origin_sort(self._dedupe("question", cands)):
            if c.pack is None:
                aq = c.item
                out.append({**self._base(c), "id": aq["key"], "text": aq["text"], "category": aq.get("category", "clarification"),
                            "dimension": aq.get("dimension"), "answer_type": "text", "options": [], "weight": 1.0,
                            "critical": False, "evidence_required": False, "help": aq.get("rationale", ""),
                            "confidence": aq.get("confidence"), "status": aq.get("status", "pending")})
                continue
            q = c.item
            out.append({**self._base(c), "id": q.id, "text": q.text, "category": q.category, "dimension": q.dimension,
                        "answer_type": q.answer_type.value, "options": [o.model_dump() for o in q.options],
                        "weight": q.weight, "critical": q.critical, "evidence_required": q.evidence_required,
                        "help": q.help})
        return out

    def risks(self) -> list[dict[str, Any]]:
        text = self.ctx.document_text.lower()
        cands = self._candidates(lambda c: c.risks, lambda r: f"{r.title}")
        out = []
        for c in self._origin_sort(self._dedupe("risk", cands)):
            r = c.item
            hits = [k for k in r.indicators if contains_keyword(text, k)] if text else []
            if not r.always_include and not hits:
                continue
            score = r.likelihood * r.impact
            out.append({**self._base(c), "id": r.id, "title": r.title, "description": r.description,
                        "category": r.category, "likelihood": r.likelihood, "impact": r.impact, "score": score,
                        "rating": _risk_rating(score), "mitigation": r.mitigation,
                        "evidence": hits, "evidenced": bool(hits)})
        for i, pr in enumerate(self.extras.get("project_risks", [])):
            score = int(pr.get("likelihood", 3)) * int(pr.get("impact", 3))
            out.append({"key": f"project:{pr['key']}", "origin": "PROJECT", "id": pr["key"],
                        "source": {"pack_key": None, "pack_name": pr.get("source_label", "Project-specific"),
                                   "pack_version": None, "role": "project", "sub_domain": None},
                        "merged_from": [], "applies_because": [pr.get("rationale", "added for this project")],
                        "title": pr["title"], "description": pr.get("description", ""),
                        "category": pr.get("category", "project"), "likelihood": int(pr.get("likelihood", 3)),
                        "impact": int(pr.get("impact", 3)), "score": score, "rating": _risk_rating(score),
                        "mitigation": pr.get("mitigation", ""), "evidence": [], "evidenced": False,
                        "added_by": pr.get("added_by")})
        return out

    def kpis(self) -> list[dict[str, Any]]:
        reviews = self.extras.get("kpi_reviews", {})
        cands = self._candidates(lambda c: c.kpis, lambda k: k.name)
        out = []
        for c in self._origin_sort(self._dedupe("kpi", cands)):
            k = c.item
            rv = reviews.get(c.key, {})
            out.append({**self._base(c), "id": k.id, "name": k.name, "description": k.description,
                        "formula": k.formula, "unit": k.unit, "direction": k.direction, "category": k.category,
                        "status": rv.get("status", "suggested"),
                        # targets are only ever client-provided (never generated)
                        "client_target": rv.get("client_target"), "target_source": rv.get("target_source"),
                        "reviewer": rv.get("reviewer")})
        return out

    def terminology(self) -> list[dict[str, Any]]:
        merged: dict[str, dict[str, Any]] = {}
        for pack in self.packs:
            for t in pack.content.terminology:
                if not sub_domain_applies(t.sub_domains, pack):
                    continue
                k = t.term.lower()
                if k in merged:
                    merged[k]["synonyms"] = sorted(set(merged[k]["synonyms"]) | set(t.synonyms))
                    merged[k]["also_defined_by"].append(pack.key)
                    continue
                merged[k] = {"term": t.term, "definition": t.definition, "synonyms": list(t.synonyms),
                             "entity_type": t.entity_type, "category": t.category,
                             "origin": pack.origin_for(t.sub_domains), "source": pack.source(t.sub_domains),
                             "also_defined_by": []}
        return list(merged.values())

    def knowledge(self) -> dict[str, list[dict[str, Any]]]:
        out: dict[str, list[dict[str, Any]]] = {}
        for section in KNOWLEDGE_SECTIONS:
            cands = self._candidates(lambda c, s=section: getattr(c.knowledge, s), lambda k: k.text)
            out[section] = [{**self._base(c), "id": c.item.id, "text": c.item.text, "category": c.item.category}
                            for c in self._origin_sort(self._dedupe(section, cands))]
        return out

    def dimensions(self) -> list[dict[str, Any]]:
        dims: dict[str, dict[str, Any]] = {}
        for pack in sorted(self.packs, key=lambda p: p.priority, reverse=True):  # lowest priority first, overwritten
            for d in pack.content.scoring.dimensions:
                prev = dims.get(d.key)
                if prev and prev["comparable"]:
                    # Global dimensions keep their weights so scores stay comparable across projects.
                    prev["ignored_overrides"].append(pack.key)
                    continue
                dims[d.key] = {"key": d.key, "name": d.name, "group": d.group, "weight": d.weight,
                               "description": d.description, "comparable": pack.kind == "global",
                               "source": pack.source(), "origin": pack.origin_for(), "ignored_overrides": [],
                               "overrides": ([prev["source"]["pack_key"]] + prev.get("overrides", [])) if prev else []}
        return list(dims.values())

    def recommendations(self) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        resolutions = self.extras.get("conflict_resolutions", {})
        cands = self._dedupe("recommendation", self._candidates(lambda c: c.recommendations, lambda r: r.title))
        recs = []
        for c in self._origin_sort(cands):
            r = c.item
            recs.append({**self._base(c), "id": r.id, "title": r.title, "text": r.text, "category": r.category,
                         "priority": r.priority, "rationale": r.rationale, "decision_key": r.decision_key,
                         "decision_option": r.decision_option, "conflicts_with": r.conflicts_with,
                         "_prio": c.priority, "conflict": False, "preferred": True})
        conflicts: list[dict[str, Any]] = []
        groups: dict[str, list[dict[str, Any]]] = {}
        for r in recs:
            if r["decision_key"]:
                groups.setdefault(r["decision_key"], []).append(r)
        for key, members in groups.items():
            if len({m["decision_option"] for m in members}) > 1:
                conflicts.append(self._conflict(key, members, resolutions, "different options for the same decision"))
        by_ref = {r["key"]: r for r in recs} | {r["id"]: r for r in recs}
        seen_pairs: set[frozenset[str]] = set()
        for r in recs:
            for ref in r["conflicts_with"]:
                other = by_ref.get(ref)
                if not other or other is r:
                    continue
                pair = frozenset({r["key"], other["key"]})
                if pair in seen_pairs:
                    continue
                seen_pairs.add(pair)
                ckey = "explicit:" + "|".join(sorted(pair))
                conflicts.append(self._conflict(ckey, [r, other], resolutions, "declared as mutually exclusive"))
        for c in conflicts:
            for opt in c["options"]:
                rec = by_ref[opt["key"]]
                rec["conflict"] = True
                rec["conflict_key"] = c["key"]
                rec["preferred"] = rec["preferred"] and opt["key"] == c["effective"]
            for opt in c["options"]:
                self.rule_sources.append({"rule_type": "recommendation", "rule_key": opt["key"], "origin": opt["origin"],
                                          "pack_key": opt["source"]["pack_key"], "pack_version": opt["source"]["pack_version"],
                                          "role": opt["source"]["role"], "sub_domain": opt["source"]["sub_domain"],
                                          "status": "conflict", "merged_into": c["key"]})
        for r in recs:
            r.pop("_prio", None)
        return recs, conflicts

    @staticmethod
    def _conflict(key: str, members: list[dict[str, Any]], resolutions: dict[str, Any], why: str) -> dict[str, Any]:
        members = sorted(members, key=lambda m: m["_prio"])
        res = resolutions.get(key)
        preferred = members[0]["key"]
        return {"key": key, "reason": why,
                "options": [{"key": m["key"], "title": m["title"], "option": m["decision_option"],
                             "origin": m["origin"], "source": m["source"]} for m in members],
                "system_preferred": preferred,
                "system_preferred_reason": "highest-priority source (primary domain first)",
                "status": "resolved" if res else "pending_review",
                "resolution": res, "effective": (res or {}).get("chosen") or preferred}

    def prompt_additions(self) -> list[dict[str, Any]]:
        out = []
        for p in self.packs:
            pr = p.content.prompts
            parts = [pr.system_addition] if pr.system_addition else []
            if self.ctx.stage in pr.stage_additions:
                parts.append(pr.stage_additions[self.ctx.stage])
            if parts:
                out.append({"pack_key": p.key, "role": p.role, "text": "\n".join(parts),
                            "extraction_hints": pr.extraction_hints})
        return out

    # --------------------------------------------------------------- resolve
    def resolve(self) -> dict[str, Any]:
        recs, conflicts = self.recommendations()
        profile = {
            "packs": [{"key": p.key, "name": p.name, "kind": p.kind, "role": p.role, "version": p.version,
                       "version_id": p.version_id, "sub_domains": p.sub_domains} for p in self.packs],
            "questions": self.questions(),
            "risks": self.risks(),
            "kpis": self.kpis(),
            "terminology": self.terminology(),
            "knowledge": self.knowledge(),
            "dimensions": self.dimensions(),
            "recommendations": recs,
            "conflicts": conflicts,
            "compliance": compliance.suggest(self.ctx, self.packs, self.extras.get("compliance_reviews", {}), self.rule_sources),
            "architecture": architecture.recommend(self.ctx, self.packs, self.rule_sources),
            "prompt_additions": self.prompt_additions(),
        }
        profile["rule_sources"] = self.rule_sources
        return profile


def _risk_rating(score: int) -> str:
    if score >= 15:
        return "high"
    if score >= 8:
        return "medium"
    return "low"


def resolve(ctx: AssessmentContext, extras: dict[str, Any] | None = None) -> dict[str, Any]:
    return Resolver(ctx, extras).resolve()
