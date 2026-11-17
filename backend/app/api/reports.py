"""Report generation: AI-assisted (prompt-driven) PPT deck and analysis document in Insight format."""
from __future__ import annotations

import re
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy.orm import Session

from ..db import get_db
from ..engine import llm
from ..models import Assessment
from ..reports import generator
from ..reports.docx_render import render_docx
from ..reports.pptx_render import render_pptx
from ..reports.schema import SECTIONS, ReportContent
from .deps import User, current_user, require_editor

router = APIRouter(prefix="/api", tags=["reports"])

PPTX_MIME = "application/vnd.openxmlformats-officedocument.presentationml.presentation"
DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


class GenerateRequest(BaseModel):
    prompt: str = Field("", max_length=4000)
    sections: list[str] | None = None
    use_ai: bool = True


class RenderRequest(BaseModel):
    content: dict[str, Any] | None = None
    prompt: str = Field("", max_length=4000)
    sections: list[str] | None = None
    use_ai: bool = False


def _get(db: Session, aid: int) -> Assessment:
    a = db.get(Assessment, aid)
    if not a:
        raise HTTPException(404, "assessment not found")
    if not a.classification_confirmed_by:
        raise HTTPException(409, "confirm the domain classification before generating reports")
    return a


def _check_sections(sections: list[str] | None) -> None:
    bad = [s for s in sections or [] if s not in SECTIONS]
    if bad:
        raise HTTPException(422, f"unknown sections: {bad}; allowed: {list(SECTIONS)}")


def _content(db: Session, a: Assessment, body: RenderRequest) -> ReportContent:
    if body.content:
        try:
            return ReportContent.model_validate(body.content)
        except ValidationError as e:
            raise HTTPException(422, f"content does not match the report format: {e.error_count()} issue(s)")
    _check_sections(body.sections)
    return ReportContent.model_validate(generator.generate(db, a, body.prompt, body.sections, body.use_ai)["content"])


def _filename(a: Assessment, kind: str, ext: str) -> str:
    stem = re.sub(r"[^A-Za-z0-9]+", "_", f"{a.client_name} {kind}").strip("_")
    return f"{stem}.{ext}"


@router.get("/reports/options")
def report_options(_: User = Depends(current_user)):
    return {"sections": SECTIONS, "default_sections": generator.DEFAULT_SECTIONS, "ai_available": llm.available(),
            "example_prompts": [
                "Leadership bid deck: DRIVE framework, Aurora accelerators incl. DBx Migrator, ROI and productivity value, "
                "FDE operating model, and add battle cards.",
                "Short executive briefing for the client's CIO: findings, approach and next steps only.",
                "Technical deep-dive for architects: assessment findings, accelerators, delivery plan and risks.",
            ]}


@router.post("/assessments/{aid}/reports/generate")
def generate_report(aid: int, body: GenerateRequest, db: Session = Depends(get_db), _: User = Depends(require_editor)):
    _check_sections(body.sections)
    a = _get(db, aid)
    return generator.generate(db, a, body.prompt, body.sections, body.use_ai)


@router.post("/assessments/{aid}/reports/pptx")
def download_pptx(aid: int, body: RenderRequest, db: Session = Depends(get_db), _: User = Depends(require_editor)):
    a = _get(db, aid)
    data = render_pptx(_content(db, a, body), generator.facts(db, a))
    return Response(data, media_type=PPTX_MIME,
                    headers={"Content-Disposition": f'attachment; filename="{_filename(a, "Insight Proposal", "pptx")}"'})


@router.post("/assessments/{aid}/reports/docx")
def download_docx(aid: int, body: RenderRequest, db: Session = Depends(get_db), _: User = Depends(require_editor)):
    a = _get(db, aid)
    data = render_docx(_content(db, a, body), generator.facts(db, a))
    return Response(data, media_type=DOCX_MIME,
                    headers={"Content-Disposition": f'attachment; filename="{_filename(a, "Analysis Document", "docx")}"'})
