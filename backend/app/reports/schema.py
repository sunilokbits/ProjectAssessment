"""Content model shared by the AI generator, the template generator and both renderers.

The same model is sent to Claude as a JSON schema (structured outputs), so every field is
plain text / numbers and list lengths are clamped by the renderers rather than the schema.
"""
from __future__ import annotations

import copy
from typing import Any

from pydantic import BaseModel, Field

SECTIONS: dict[str, str] = {
    "summary": "Executive summary",
    "opportunity": "The opportunity",
    "findings": "Assessment findings",
    "approach": "Approach / framework",
    "accelerators": "Accelerators",
    "value": "Business value",
    "operating_model": "Operating model",
    "roadmap": "Delivery plan & governance",
    "why_us": "Why Insight",
    "options": "Engagement options & next steps",
    "battle_cards": "Battle cards (internal)",
}


class Block(BaseModel):
    headline: str
    text: str


class TitleText(BaseModel):
    title: str
    text: str


class QA(BaseModel):
    question: str
    answer: str


class Stage(BaseModel):
    letter: str = Field(description="One letter or short number shown in the stage circle")
    name: str
    text: str
    tooling: str


class WhenLabel(BaseModel):
    when: str
    label: str


class Accelerator(BaseModel):
    name: str
    stage_tags: str = Field(description="Which approach stages it supports, e.g. 'D · R'")
    text: str
    live: bool = Field(description="True only for accelerators that exist and can be demonstrated today")
    url: str = Field(description="Demo URL or empty string")


class Stat(BaseModel):
    value: str
    label: str
    category: str


class ValueChart(BaseModel):
    title: str
    categories: list[str]
    benefit: list[float]
    investment: list[float]


class Comparison(BaseModel):
    dimension: str
    traditional: str
    ours: str


class Phase(BaseModel):
    name: str
    start_week: int
    end_week: int


class Milestone(BaseModel):
    week: int
    label: str


class RiskMitigation(BaseModel):
    risk: str
    mitigation: str


class Option(BaseModel):
    tag: str
    name: str
    terms: str
    outputs: list[str]
    recommended: bool


class Competitor(BaseModel):
    type: str
    pitch: str
    strengths: str
    weaknesses: str
    how_we_win: str


class Objection(BaseModel):
    objection: str
    response: str


class ExecSummary(BaseModel):
    title: str
    intro: str
    need: Block
    response: Block
    why_us: Block
    value: Block
    ask: str


class Opportunity(BaseModel):
    title: str
    intro: str
    challenges: list[TitleText]
    client_questions: list[QA]


class Findings(BaseModel):
    title: str
    intro: str
    key_findings: list[str]


class Approach(BaseModel):
    title: str
    framework_name: str
    intro: str
    stages: list[Stage]
    core_stage_index: int
    first_value_headline: str
    first_value_text: str
    timeline: list[WhenLabel]


class Accelerators(BaseModel):
    title: str
    intro: str
    items: list[Accelerator]
    footnote: str


class Value(BaseModel):
    title: str
    intro: str
    stats: list[Stat]
    chart: ValueChart
    payback_note: str
    disclaimer: str


class OperatingModel(BaseModel):
    title: str
    intro: str
    hub_label: str
    roles: list[TitleText]
    comparison_title: str
    comparison: list[Comparison]


class Roadmap(BaseModel):
    title: str
    intro: str
    phases: list[Phase]
    milestones: list[Milestone]
    governance: list[TitleText]
    risks: list[RiskMitigation]


class WhyUs(BaseModel):
    title: str
    commitment: str
    proof_stats: list[WhenLabel]
    themes: list[TitleText]


class Options(BaseModel):
    title: str
    intro: str
    items: list[Option]
    next_steps: list[WhenLabel]


class Closing(BaseModel):
    title: str
    message: str
    next_step: str


class BattleCards(BaseModel):
    competitors: list[Competitor]
    objections: list[Objection]
    questions: list[str]


class Analysis(BaseModel):
    executive_narrative: str
    context_narrative: str
    readiness_commentary: str
    risk_commentary: str
    compliance_commentary: str
    recommendations: list[str]
    next_steps_narrative: str


class ReportContent(BaseModel):
    title: str
    subtitle: str
    tagline: str
    meta_line: str
    sections: list[str] = Field(description="Ordered section keys to include")
    summary: ExecSummary
    opportunity: Opportunity
    findings: Findings
    approach: Approach
    accelerators: Accelerators
    value: Value
    operating_model: OperatingModel
    roadmap: Roadmap
    why_us: WhyUs
    options: Options
    closing: Closing
    battle_cards: BattleCards
    analysis: Analysis


def strict_json_schema(model: type[BaseModel]) -> dict[str, Any]:
    """Pydantic schema -> structured-outputs schema (every object closed, every property required)."""
    schema = copy.deepcopy(model.model_json_schema())

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            # schema keywords only (a *property* called "title"/"default" maps to a dict, keep it)
            for k in ("default", "title"):
                if k in node and not isinstance(node[k], dict):
                    node.pop(k)
            if node.get("type") == "object" and "properties" in node:
                node["additionalProperties"] = False
                node["required"] = list(node["properties"].keys())
            for v in list(node.values()):
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(schema)
    return schema
