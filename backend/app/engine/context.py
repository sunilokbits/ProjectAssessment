from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..schemas.domain_pack import DomainPackContent

# Lower number = higher priority when de-duplicating / resolving conflicts.
ROLE_PRIORITY = {"primary": 0, "project_type": 1, "technology": 2, "secondary": 3, "global": 4}

ORIGIN_ORDER = ["GLOBAL", "INDUSTRY", "SUB-DOMAIN", "TECHNOLOGY", "PROJECT", "AI-DISCOVERED"]


@dataclass
class PackRef:
    key: str
    kind: str
    role: str  # global | primary | secondary | technology | project_type
    version: str
    version_id: int | None
    content: DomainPackContent
    sub_domains: list[str] = field(default_factory=list)
    order: int = 0  # position among packs of the same role (e.g. several technologies)

    @property
    def priority(self) -> tuple[int, int]:
        return ROLE_PRIORITY.get(self.role, 9), self.order

    @property
    def name(self) -> str:
        return self.content.domain.name

    def origin_for(self, item_sub_domains: list[str] | None = None) -> str:
        if self.kind == "global":
            return "GLOBAL"
        if self.kind == "technology":
            return "TECHNOLOGY"
        if self.kind == "project_type":
            return "PROJECT"
        return "SUB-DOMAIN" if item_sub_domains else "INDUSTRY"

    def source(self, item_sub_domains: list[str] | None = None) -> dict[str, Any]:
        subs = [s for s in (item_sub_domains or []) if s in self.sub_domains]
        return {
            "pack_key": self.key,
            "pack_name": self.name,
            "pack_version": self.version,
            "role": self.role,
            "sub_domain": subs[0] if subs else None,
        }


@dataclass
class AssessmentContext:
    client_name: str = ""
    project_name: str = ""
    primary_industry: str | None = None
    sub_domains: list[str] = field(default_factory=list)
    secondary_industries: list[dict[str, Any]] = field(default_factory=list)  # [{key, sub_domains}]
    technologies: list[str] = field(default_factory=list)
    project_types: list[str] = field(default_factory=list)
    geography: str | None = None
    regulatory_regions: list[str] = field(default_factory=list)
    data_classifications: list[str] = field(default_factory=list)
    stage: str = "discovery"
    document_text: str = ""
    answers: dict[str, Any] = field(default_factory=dict)  # question_key -> value
    packs: list[PackRef] = field(default_factory=list)
    reference: dict[str, Any] = field(default_factory=dict)

    @property
    def industries(self) -> list[str]:
        out = [self.primary_industry] if self.primary_industry else []
        return out + [s["key"] for s in self.secondary_industries]

    @property
    def all_sub_domains(self) -> list[str]:
        subs = list(self.sub_domains)
        for s in self.secondary_industries:
            subs += s.get("sub_domains", [])
        return subs

    @property
    def geo_codes(self) -> set[str]:
        """Geography + its parent regions + selected regulatory regions, upper-cased."""
        codes: set[str] = {"GLOBAL"}
        if self.geography:
            geo = str(self.geography).upper()
            codes.add(geo)
            for g in self.reference.get("geographies", []):
                if str(g.get("code", "")).upper() == geo:
                    codes |= {str(r).upper() for r in g.get("regions", [])}
        codes |= {str(r).upper() for r in self.regulatory_regions}
        return codes

    def answer_by_id(self, question_id: str) -> Any:
        """Answers are stored by qualified key 'pack:id'; conditions reference either form."""
        if question_id in self.answers:
            return self.answers[question_id]
        for k, v in self.answers.items():
            if k.split(":", 1)[-1] == question_id:
                return v
        return None

    def pack(self, key: str) -> PackRef | None:
        return next((p for p in self.packs if p.key == key), None)
