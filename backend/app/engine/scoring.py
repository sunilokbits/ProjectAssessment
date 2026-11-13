"""Transparent readiness scoring (32.10).

- Each question contributes to one dimension (weight visible).
- Each dimension belongs to a readiness group (weight visible).
- "Overall (comparable)" uses only the global dimensions, so it can be compared
  across projects and industries. "Overall (domain-adjusted)" adds the domain /
  technology dimensions contributed by the selected packs.
- Unanswered questions are excluded from the score but reduce coverage.
"""
from __future__ import annotations

from typing import Any

GROUP_LABELS = {
    "business": "Business Readiness",
    "data": "Data Readiness",
    "architecture": "Architecture Readiness",
    "security": "Security Readiness",
    "domain": "Industry / Domain Readiness",
    "technology": "Technology Readiness",
    "delivery": "Delivery Readiness",
}
DEFAULT_YES_NO = {"yes": 1.0, "partial": 0.5, "no": 0.0}
NOT_SCORED_VALUES = {"unknown", "n/a", "na", "not_applicable", ""}


def score_answer(q: dict[str, Any], value: Any) -> float | None:
    if value is None:
        return None
    t = q["answer_type"]
    opts = {o["value"].lower(): o.get("score") for o in q.get("options", [])}
    if isinstance(value, str) and value.strip().lower() in NOT_SCORED_VALUES:
        return None
    if t == "yes_no":
        v = ("yes" if value else "no") if isinstance(value, bool) else str(value).lower()
        table = opts or DEFAULT_YES_NO
        return table.get(v)
    if t == "scale":
        try:
            n = float(value)
        except (TypeError, ValueError):
            return None
        return max(0.0, min(1.0, (n - 1) / 4))
    if t == "single_choice":
        return opts.get(str(value).lower())
    if t == "multi_choice":
        vals = value if isinstance(value, list) else [value]
        scores = [opts.get(str(v).lower()) for v in vals]
        scores = [s for s in scores if s is not None]
        return sum(scores) / len(scores) if scores else None
    return None  # text / number answers are recorded but not scored


def rag(score: float | None, thresholds: dict[str, float]) -> dict[str, str]:
    if score is None:
        return {"state": "grey", "label": "Not assessed"}
    if score >= thresholds.get("green", 75):
        return {"state": "green", "label": "Green – on track"}
    if score >= thresholds.get("amber", 50):
        return {"state": "amber", "label": "Amber – attention needed"}
    return {"state": "red", "label": "Red – at risk"}


def _is_answered(v: Any) -> bool:
    return v is not None and v != "" and v != []


def compute(profile: dict[str, Any], answers: dict[str, dict[str, Any]], reference: dict[str, Any]) -> dict[str, Any]:
    thresholds = reference.get("rag_thresholds", {"green": 75, "amber": 50})
    group_weights = reference.get("readiness_group_weights", {})
    dims = {d["key"]: {**d, "questions": 0, "scorable": 0, "answered": 0, "w_sum": 0.0, "s_sum": 0.0}
            for d in profile["dimensions"]}
    critical_gaps = []
    for q in profile["questions"]:
        d = dims.get(q.get("dimension") or "")
        a = answers.get(q["key"], {})
        val = a.get("value")
        s = score_answer(q, val)
        if d is not None:
            d["questions"] += 1
            if q["answer_type"] not in ("text", "number"):
                d["scorable"] += 1
            if _is_answered(val):
                d["answered"] += 1
            if s is not None:
                d["w_sum"] += q["weight"]
                d["s_sum"] += q["weight"] * s
        if q.get("critical") and (not _is_answered(val) or (s is not None and s < 0.5)):
            critical_gaps.append({"question_key": q["key"], "text": q["text"], "origin": q["origin"],
                                  "dimension": q.get("dimension"),
                                  "reason": "unanswered" if not _is_answered(val) else "answered with low readiness"})
    dim_out = []
    for d in dims.values():
        score = round(100 * d["s_sum"] / d["w_sum"], 1) if d["w_sum"] else None
        dim_out.append({"key": d["key"], "name": d["name"], "group": d["group"], "weight": d["weight"],
                        "comparable": d["comparable"], "source": d["source"], "origin": d["origin"],
                        "description": d["description"], "score": score, "rag": rag(score, thresholds),
                        "questions": d["questions"], "answered": d["answered"],
                        "coverage": round(100 * d["answered"] / d["questions"], 1) if d["questions"] else None,
                        "ignored_overrides": d.get("ignored_overrides", [])})

    def weighted(items: list[dict[str, Any]]) -> float | None:
        scored = [i for i in items if i["score"] is not None]
        w = sum(i["weight"] for i in scored)
        return round(sum(i["score"] * i["weight"] for i in scored) / w, 1) if w else None

    groups = []
    for g, label in GROUP_LABELS.items():
        members = [d for d in dim_out if d["group"] == g]
        if not members:
            continue
        sc = weighted(members)
        groups.append({"group": g, "label": label, "score": sc, "rag": rag(sc, thresholds),
                       "weight": float(group_weights.get(g, 1.0)),
                       "dimensions": [{"key": m["key"], "weight": m["weight"], "score": m["score"]} for m in members]})
    comparable = weighted([{"score": d["score"], "weight": d["weight"]} for d in dim_out if d["comparable"]])
    adjusted = weighted([{"score": gr["score"], "weight": gr["weight"]} for gr in groups])
    total_q = len(profile["questions"])
    answered = sum(1 for q in profile["questions"] if _is_answered(answers.get(q["key"], {}).get("value")))
    return {
        "overall": {"comparable": comparable, "comparable_rag": rag(comparable, thresholds),
                    "domain_adjusted": adjusted, "domain_adjusted_rag": rag(adjusted, thresholds)},
        "groups": groups, "dimensions": dim_out, "critical_gaps": critical_gaps,
        "questions_total": total_q, "questions_answered": answered,
        "method": {
            "question_score": "yes=1, partial=0.5, no=0; scale 1–5 → 0–1; choice options carry their own score; "
                              "unknown / n/a / text answers are not scored",
            "dimension_score": "Σ(question weight × score) / Σ(question weight) over scored answers × 100",
            "group_score": "Σ(dimension weight × dimension score) / Σ(dimension weight)",
            "overall_comparable": "weighted mean of GLOBAL dimensions only – comparable across projects",
            "overall_domain_adjusted": "weighted mean of readiness groups incl. domain/technology dimensions "
                                       f"(group weights: {group_weights or 'all 1.0'})",
            "rag_thresholds": thresholds,
        },
    }
