"""Pydantic validation schema for Domain Packs.

A Domain Pack is pure configuration (YAML/JSON). Nothing domain-specific lives in
Python: this module only describes the *shape* every pack must have, so new
industries / technologies / project types can be added by authoring a pack.

Pack kinds
----------
- ``global``       : questions/risks/dimensions applicable to every assessment (Layer 1)
- ``industry``     : industry pack with sub-domains (Layer 2 + sub-domain layer)
- ``technology``   : technology domain pack (Layer 3)
- ``project_type`` : project-type pack, e.g. Customer 360 (Layer 4 static part)
"""
from __future__ import annotations

import re
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator, model_validator

SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9_\-]*$")
SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+$")

SCHEMA_VERSION = "1.0"


class Strict(BaseModel):
    """Base: unknown keys are rejected so typos surface as validation errors."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)


def _slug(v: str, field: str = "id") -> str:
    if not isinstance(v, str) or not SLUG_RE.match(v):
        raise ValueError(
            f"{field} '{v}' must be a lowercase slug (letters, digits, '_' or '-', "
            "starting with a letter or digit)"
        )
    return v


class PackKind(str, Enum):
    GLOBAL = "global"
    INDUSTRY = "industry"
    TECHNOLOGY = "technology"
    PROJECT_TYPE = "project_type"


# ---------------------------------------------------------------------------
# Conditions – a small declarative rule language evaluated by the engine
# ---------------------------------------------------------------------------
class Condition(Strict):
    """All non-empty fields must match (AND); values inside a list match ANY.

    ``answers`` maps question id -> accepted answer value(s).
    ``keywords_any`` is matched against uploaded client documents.
    """

    sub_domains_any: list[str] = Field(default_factory=list)
    industries_any: list[str] = Field(default_factory=list)
    technologies_any: list[str] = Field(default_factory=list)
    project_types_any: list[str] = Field(default_factory=list)
    geographies_any: list[str] = Field(default_factory=list)
    regulatory_regions_any: list[str] = Field(default_factory=list)
    data_classifications_any: list[str] = Field(default_factory=list)
    stages_any: list[str] = Field(default_factory=list)
    keywords_any: list[str] = Field(default_factory=list)
    answers: dict[str, list[str] | str | bool | int | float] = Field(default_factory=dict)
    any_of: list["Condition"] = Field(default_factory=list)
    not_: "Condition | None" = Field(default=None, alias="not")


class ItemBase(Strict):
    id: str
    sub_domains: list[str] = Field(
        default_factory=list,
        description="If set, the item only applies when one of these sub-domains is selected.",
    )
    when: Condition | None = None
    tags: list[str] = Field(default_factory=list)

    @field_validator("id")
    @classmethod
    def _id(cls, v: str) -> str:
        return _slug(v)


# ---------------------------------------------------------------------------
# domain.yaml
# ---------------------------------------------------------------------------
class SubDomain(Strict):
    key: str
    name: str
    description: str = ""
    keywords: list[str] = Field(default_factory=list)
    enabled: bool = True

    @field_validator("key")
    @classmethod
    def _key(cls, v: str) -> str:
        return _slug(v, "sub-domain key")


class Detection(Strict):
    """Signals used by domain auto-detection (32.5)."""

    keywords: dict[str, float] = Field(
        default_factory=dict, description="keyword/phrase -> weight (0.1 – 5)"
    )
    min_score: float = 1.0

    @field_validator("keywords")
    @classmethod
    def _weights(cls, v: dict[str, float]) -> dict[str, float]:
        for k, w in v.items():
            if not (0 < float(w) <= 5):
                raise ValueError(f"detection weight for '{k}' must be in (0, 5]")
        return v


class DomainMeta(Strict):
    key: str
    name: str
    kind: PackKind
    version: str = "1.0.0"
    schema_version: str = SCHEMA_VERSION
    description: str = ""
    aliases: list[str] = Field(default_factory=list)
    icon: str | None = None
    sort_order: int = 100
    sub_domains: list[SubDomain] = Field(default_factory=list)
    detection: Detection = Field(default_factory=Detection)
    business_processes: list[str] = Field(default_factory=list)
    capabilities: list[str] = Field(default_factory=list)
    source_systems: list[str] = Field(default_factory=list)
    data_entities: list[str] = Field(default_factory=list)
    integration_patterns: list[str] = Field(default_factory=list)
    related_technologies: list[str] = Field(default_factory=list)
    related_project_types: list[str] = Field(default_factory=list)

    @field_validator("key")
    @classmethod
    def _key(cls, v: str) -> str:
        return _slug(v, "domain key")

    @field_validator("version")
    @classmethod
    def _ver(cls, v: str) -> str:
        if not SEMVER_RE.match(v):
            raise ValueError(f"version '{v}' must be semantic (MAJOR.MINOR.PATCH)")
        return v

    @field_validator("business_processes", "capabilities", "source_systems", "data_entities",
                     "integration_patterns", "aliases")
    @classmethod
    def _balanced(cls, v: list[str], info: ValidationInfo) -> list[str]:
        # Unquoted flow lists like [A (x, y), B] silently split inside the parentheses.
        # Authoring-time lint only: already-stored versions stay loadable (assessments are pinned to them).
        if (info.context or {}).get("stored"):
            return v
        bad = [s for s in v if str(s).count("(") != str(s).count(")")]
        if bad:
            raise ValueError(f"items with unbalanced parentheses {bad} - quote list items that contain commas")
        return v

    @model_validator(mode="after")
    def _subdomains(self) -> "DomainMeta":
        keys = [s.key for s in self.sub_domains]
        dupes = {k for k in keys if keys.count(k) > 1}
        if dupes:
            raise ValueError(f"duplicate sub-domain keys: {sorted(dupes)}")
        if self.kind == PackKind.GLOBAL and self.sub_domains:
            raise ValueError("the global pack cannot declare sub-domains")
        return self


# ---------------------------------------------------------------------------
# questions.yaml
# ---------------------------------------------------------------------------
class AnswerType(str, Enum):
    YES_NO = "yes_no"
    SCALE = "scale"  # 1..5 maturity
    SINGLE_CHOICE = "single_choice"
    MULTI_CHOICE = "multi_choice"
    TEXT = "text"
    NUMBER = "number"


class AnswerOption(Strict):
    value: str
    label: str
    score: float | None = Field(
        default=None, ge=0, le=1, description="0..1 readiness contribution; null = not scored"
    )

    @field_validator("value", mode="before")
    @classmethod
    def _coerce(cls, v: Any) -> Any:
        # YAML 1.1 turns bare yes/no/on/off into booleans; keep authoring forgiving.
        if isinstance(v, bool):
            return "yes" if v else "no"
        if isinstance(v, (int, float)):
            return str(v)
        return v


class Question(ItemBase):
    text: str
    category: str = "general"
    dimension: str = Field(description="Scoring dimension key this question contributes to")
    answer_type: AnswerType = AnswerType.YES_NO
    options: list[AnswerOption] = Field(default_factory=list)
    weight: float = Field(default=1.0, gt=0, le=10)
    critical: bool = False
    evidence_required: bool = False
    help: str = ""
    equivalence_key: str | None = Field(
        default=None,
        description="Questions sharing an equivalence key across packs are treated as duplicates.",
    )

    @model_validator(mode="after")
    def _opts(self) -> "Question":
        if self.answer_type in (AnswerType.SINGLE_CHOICE, AnswerType.MULTI_CHOICE) and not self.options:
            raise ValueError(f"question '{self.id}': {self.answer_type.value} requires options")
        return self


# ---------------------------------------------------------------------------
# risks.yaml
# ---------------------------------------------------------------------------
class Risk(ItemBase):
    title: str
    description: str = ""
    category: str = "general"
    likelihood: int = Field(default=3, ge=1, le=5)
    impact: int = Field(default=3, ge=1, le=5)
    mitigation: str = ""
    indicators: list[str] = Field(
        default_factory=list,
        description="Keywords in client documents that raise this risk as evidenced",
    )
    always_include: bool = True


# ---------------------------------------------------------------------------
# kpis.yaml  (no targets allowed – client targets must come from the client)
# ---------------------------------------------------------------------------
class Kpi(ItemBase):
    name: str
    description: str = ""
    formula: str = ""
    unit: str = ""
    direction: Literal["higher_is_better", "lower_is_better", "target_range"] = "higher_is_better"
    category: str = "business"


# ---------------------------------------------------------------------------
# compliance.yaml
# ---------------------------------------------------------------------------
class ComplianceRef(ItemBase):
    name: str
    short_name: str = ""
    description: str = ""
    jurisdiction: str = ""
    geographies: list[str] = Field(
        default_factory=list,
        description="Country / region codes, or GLOBAL. Matched against geography + regulatory region.",
    )
    data_classifications_any: list[str] = Field(default_factory=list)
    project_types_any: list[str] = Field(default_factory=list)
    industries_any: list[str] = Field(default_factory=list)
    technologies_any: list[str] = Field(default_factory=list)
    reference: str = ""
    obligations: list[str] = Field(default_factory=list)
    applicability_note: str = ""


# ---------------------------------------------------------------------------
# terminology.yaml
# ---------------------------------------------------------------------------
class Term(Strict):
    term: str
    definition: str = ""
    synonyms: list[str] = Field(default_factory=list)
    entity_type: Literal[
        "entity", "process", "metric", "regulation", "system", "concept", "role", "event"
    ] = "concept"
    category: str = "general"
    sub_domains: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# knowledge.yaml  (NFRs, assumptions, dependencies, …)
# ---------------------------------------------------------------------------
class KnowledgeItem(ItemBase):
    text: str
    category: str = "general"


class Knowledge(Strict):
    nfrs: list[KnowledgeItem] = Field(default_factory=list)
    assumptions: list[KnowledgeItem] = Field(default_factory=list)
    dependencies: list[KnowledgeItem] = Field(default_factory=list)
    security_considerations: list[KnowledgeItem] = Field(default_factory=list)
    data_quality_checks: list[KnowledgeItem] = Field(default_factory=list)
    reporting_requirements: list[KnowledgeItem] = Field(default_factory=list)
    migration_concerns: list[KnowledgeItem] = Field(default_factory=list)
    ai_opportunities: list[KnowledgeItem] = Field(default_factory=list)
    ai_risks: list[KnowledgeItem] = Field(default_factory=list)
    clarification_questions: list[KnowledgeItem] = Field(default_factory=list)


KNOWLEDGE_SECTIONS = list(Knowledge.model_fields.keys())


# ---------------------------------------------------------------------------
# architecture_patterns.yaml
# ---------------------------------------------------------------------------
class ArchComponent(Strict):
    id: str
    name: str
    layer: str = Field(description="e.g. sources, ingestion, storage, processing, serving, consumption, governance")
    purpose: str = ""
    core: bool = Field(default=False, description="Always part of the pattern when the pattern applies")
    when: Condition | None = None
    alternatives: list[str] = Field(default_factory=list)

    @field_validator("id")
    @classmethod
    def _id(cls, v: str) -> str:
        return _slug(v, "component id")


class ArchitecturePattern(ItemBase):
    name: str
    description: str = ""
    use_cases: list[str] = Field(default_factory=list)
    components: list[ArchComponent] = Field(default_factory=list)
    layer_order: list[str] = Field(default_factory=list)
    considerations: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# recommendations.yaml
# ---------------------------------------------------------------------------
class Recommendation(ItemBase):
    title: str
    text: str = ""
    category: str = "general"
    priority: Literal["high", "medium", "low"] = "medium"
    rationale: str = ""
    decision_key: str | None = Field(
        default=None,
        description="Recommendations sharing a decision_key but differing decision_option conflict.",
    )
    decision_option: str | None = None
    conflicts_with: list[str] = Field(
        default_factory=list, description="Recommendation ids (optionally 'pack_key:id') this conflicts with"
    )


# ---------------------------------------------------------------------------
# scoring.yaml
# ---------------------------------------------------------------------------
READINESS_GROUPS = ["business", "data", "architecture", "security", "domain", "technology", "delivery"]


class Dimension(Strict):
    key: str
    name: str
    group: Literal["business", "data", "architecture", "security", "domain", "technology", "delivery"]
    weight: float = Field(default=1.0, gt=0, le=10)
    description: str = ""

    @field_validator("key")
    @classmethod
    def _key(cls, v: str) -> str:
        return _slug(v, "dimension key")


class Scoring(Strict):
    dimensions: list[Dimension] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# prompts.yaml
# ---------------------------------------------------------------------------
class Prompts(Strict):
    system_addition: str = ""
    stage_additions: dict[str, str] = Field(default_factory=dict)
    extraction_hints: str = ""


# ---------------------------------------------------------------------------
# The full pack
# ---------------------------------------------------------------------------
PACK_FILES = {
    "domain": "domain.yaml",
    "questions": "questions.yaml",
    "risks": "risks.yaml",
    "kpis": "kpis.yaml",
    "compliance": "compliance.yaml",
    "terminology": "terminology.yaml",
    "architecture_patterns": "architecture_patterns.yaml",
    "recommendations": "recommendations.yaml",
    "knowledge": "knowledge.yaml",
    "scoring": "scoring.yaml",
    "prompts": "prompts.yaml",
}
EDITABLE_SECTIONS = list(PACK_FILES.keys())


class DomainPackContent(Strict):
    domain: DomainMeta
    questions: list[Question] = Field(default_factory=list)
    risks: list[Risk] = Field(default_factory=list)
    kpis: list[Kpi] = Field(default_factory=list)
    compliance: list[ComplianceRef] = Field(default_factory=list)
    terminology: list[Term] = Field(default_factory=list)
    architecture_patterns: list[ArchitecturePattern] = Field(default_factory=list)
    recommendations: list[Recommendation] = Field(default_factory=list)
    knowledge: Knowledge = Field(default_factory=Knowledge)
    scoring: Scoring = Field(default_factory=Scoring)
    prompts: Prompts = Field(default_factory=Prompts)

    @model_validator(mode="after")
    def _cross_refs(self) -> "DomainPackContent":
        errors: list[str] = []
        sub_keys = {s.key for s in self.domain.sub_domains}

        def unique(section: str, ids: list[str]) -> None:
            seen: set[str] = set()
            for i in ids:
                if i in seen:
                    errors.append(f"{section}: duplicate id '{i}'")
                seen.add(i)

        def check_subs(section: str, item_id: str, subs: list[str]) -> None:
            for s in subs:
                if s not in sub_keys:
                    errors.append(
                        f"{section}.{item_id}: unknown sub-domain '{s}' "
                        f"(declared: {sorted(sub_keys) or 'none'})"
                    )

        for section in ("questions", "risks", "kpis", "compliance", "architecture_patterns", "recommendations"):
            items = getattr(self, section)
            unique(section, [i.id for i in items])
            for it in items:
                check_subs(section, it.id, it.sub_domains)
        for ks in KNOWLEDGE_SECTIONS:
            items = getattr(self.knowledge, ks)
            unique(f"knowledge.{ks}", [i.id for i in items])
            for it in items:
                check_subs(f"knowledge.{ks}", it.id, it.sub_domains)
        for t in self.terminology:
            check_subs("terminology", t.term, t.sub_domains)

        dim_keys = [d.key for d in self.scoring.dimensions]
        unique("scoring.dimensions", dim_keys)

        for p in self.architecture_patterns:
            unique(f"architecture_patterns.{p.id}.components", [c.id for c in p.components])

        if self.domain.kind == PackKind.GLOBAL:
            if not self.scoring.dimensions:
                errors.append("the global pack must define the comparable scoring dimensions")
        if errors:
            raise ValueError("; ".join(errors))
        return self

    def check_dimensions(self, known_global_dimensions: set[str]) -> list[str]:
        """Questions must reference a dimension defined in this pack or the global pack."""
        own = {d.key for d in self.scoring.dimensions}
        allowed = own | known_global_dimensions
        return [
            f"questions.{q.id}: unknown scoring dimension '{q.dimension}' "
            f"(define it in scoring.yaml or use a global dimension: {sorted(known_global_dimensions)})"
            for q in self.questions
            if q.dimension not in allowed
        ]


def json_schema() -> dict[str, Any]:
    """Export JSON Schema so packs can be validated outside Python (editors, CI)."""
    return DomainPackContent.model_json_schema(by_alias=True)
