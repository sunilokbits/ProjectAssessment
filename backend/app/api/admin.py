"""Administration -> Domain Management (32.12)."""
from __future__ import annotations

from typing import Any

import yaml
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import get_db
from ..engine import registry
from ..engine.loader import PackValidationError, parse_upload
from ..models import DomainAssessmentMapping, DomainPack, DomainPackStatus, DomainPackVersion
from ..schemas.domain_pack import EDITABLE_SECTIONS, PACK_FILES, json_schema
from ..services import reload_reference
from .deps import User, require_admin

router = APIRouter(prefix="/api/admin", tags=["domain-management"])


def _version_out(v: DomainPackVersion, usage: int | None = None, with_content: bool = False) -> dict[str, Any]:
    out = {"id": v.id, "pack_key": v.pack.key, "version": v.version, "status": v.status.value, "notes": v.notes,
           "checksum": v.checksum, "created_by": v.created_by, "created_at": v.created_at,
           "published_at": v.published_at, "published_by": v.published_by,
           "counts": {s: len(v.content.get(s) or []) for s in ("questions", "risks", "kpis", "compliance",
                                                               "terminology", "architecture_patterns", "recommendations")},
           "assessments_using": usage,
           "history": [{"from": e.from_status, "to": e.to_status, "actor": e.actor, "comment": e.comment,
                        "at": e.created_at} for e in v.status_events]}
    if with_content:
        out["content"] = v.content
    return out


def _usage(db: Session) -> dict[int, int]:
    rows = db.execute(select(DomainAssessmentMapping.pack_version_id, func.count()).group_by(
        DomainAssessmentMapping.pack_version_id)).all()
    return {r[0]: r[1] for r in rows}


def _pack_out(db: Session, p: DomainPack, usage: dict[int, int]) -> dict[str, Any]:
    latest = registry.latest_published(db, p.key)
    return {"id": p.id, "key": p.key, "name": p.name, "kind": p.kind, "description": p.description,
            "enabled": p.enabled, "builtin": p.builtin, "source_path": p.source_path,
            "latest_published": latest.version if latest else None,
            "sub_domains": [s["key"] for s in ((latest.content if latest else p.versions[-1].content)["domain"].get("sub_domains") or [])] if p.versions else [],
            "versions": [_version_out(v, usage.get(v.id, 0)) for v in reversed(p.versions)]}


def _get_pack(db: Session, key: str) -> DomainPack:
    p = db.scalar(select(DomainPack).where(DomainPack.key == key))
    if not p:
        raise HTTPException(404, f"domain '{key}' not found")
    return p


def _get_version(db: Session, key: str, version: str) -> DomainPackVersion:
    p = _get_pack(db, key)
    v = next((v for v in p.versions if v.version == version), None)
    if not v:
        raise HTTPException(404, f"version {version} of '{key}' not found")
    return v


def _wrap(fn):
    try:
        return fn()
    except PackValidationError as e:
        raise HTTPException(422, {"message": "Domain pack validation failed", "errors": e.errors})
    except registry.RegistryError as e:
        raise HTTPException(e.status_code, str(e))


@router.get("/domain-packs")
def list_packs(kind: str | None = None, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    usage = _usage(db)
    stmt = select(DomainPack).order_by(DomainPack.kind, DomainPack.name)
    if kind:
        stmt = stmt.where(DomainPack.kind == kind)
    return [_pack_out(db, p, usage) for p in db.scalars(stmt)]


@router.get("/domain-packs/schema")
def pack_schema(_: User = Depends(require_admin)):
    return {"json_schema": json_schema(), "files": PACK_FILES, "sections": EDITABLE_SECTIONS}


class NewDomain(BaseModel):
    key: str
    name: str
    kind: str = "industry"
    description: str = ""
    sub_domains: list[dict[str, Any]] = []
    version: str = "0.1.0"


@router.post("/domain-packs", status_code=201)
def create_domain(body: NewDomain, db: Session = Depends(get_db), user: User = Depends(require_admin)):
    if db.scalar(select(DomainPack).where(DomainPack.key == body.key)):
        raise HTTPException(409, f"domain '{body.key}' already exists")
    raw = {"domain": {"key": body.key, "name": body.name, "kind": body.kind, "description": body.description,
                      "version": body.version, "sub_domains": body.sub_domains}}
    v = _wrap(lambda: registry.create_version(db, raw, user.name, notes="created in Domain Management"))
    db.commit()
    return _pack_out(db, v.pack, _usage(db))


@router.get("/domain-packs/{key}")
def get_pack(key: str, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    return _pack_out(db, _get_pack(db, key), _usage(db))


class PackPatch(BaseModel):
    enabled: bool | None = None


@router.patch("/domain-packs/{key}")
def patch_pack(key: str, body: PackPatch, db: Session = Depends(get_db), user: User = Depends(require_admin)):
    p = _get_pack(db, key)
    if body.enabled is not None:
        if p.kind == "global" and not body.enabled:
            raise HTTPException(400, "the global pack cannot be disabled")
        p.enabled = body.enabled
    db.commit()
    return _pack_out(db, p, _usage(db))


@router.get("/domain-packs/{key}/versions/{version}")
def get_version(key: str, version: str, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    v = _get_version(db, key, version)
    return _version_out(v, _usage(db).get(v.id, 0), with_content=True)


@router.get("/domain-packs/{key}/versions/{version}/export", response_class=PlainTextResponse)
def export_version(key: str, version: str, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    return yaml.safe_dump(_get_version(db, key, version).content, sort_keys=False, allow_unicode=True)


class ContentBody(BaseModel):
    content: dict[str, Any]
    notes: str = ""


@router.post("/domain-packs/validate")
def validate(body: ContentBody, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    try:
        lp = registry.validate_content(db, body.content)
    except PackValidationError as e:
        return {"valid": False, "errors": e.errors, "warnings": []}
    return {"valid": True, "errors": [], "warnings": lp.warnings, "key": lp.content.domain.key,
            "version": lp.content.domain.version}


@router.post("/domain-packs/versions", status_code=201)
def create_version(body: ContentBody, db: Session = Depends(get_db), user: User = Depends(require_admin)):
    v = _wrap(lambda: registry.create_version(db, body.content, user.name, notes=body.notes))
    db.commit()
    return _version_out(v, 0)


@router.post("/domain-packs/upload", status_code=201)
async def upload(file: UploadFile = File(...), notes: str = Form(""), validate_only: bool = Form(False),
                 db: Session = Depends(get_db), user: User = Depends(require_admin)):
    data = await file.read()
    try:
        raw = parse_upload(file.filename or "pack.yaml", data)
        lp = registry.validate_content(db, raw)
    except PackValidationError as e:
        raise HTTPException(422, {"message": "Domain pack validation failed", "errors": e.errors})
    if validate_only:
        return {"valid": True, "key": lp.content.domain.key, "version": lp.content.domain.version, "warnings": lp.warnings}
    v = _wrap(lambda: registry.create_version(db, raw, user.name, notes=notes or f"uploaded {file.filename}"))
    db.commit()
    return {**_version_out(v, 0), "warnings": lp.warnings}


@router.put("/domain-packs/{key}/versions/{version}/sections/{section}")
def update_section(key: str, version: str, section: str, body: dict[str, Any],
                   db: Session = Depends(get_db), user: User = Depends(require_admin)):
    if section not in EDITABLE_SECTIONS:
        raise HTTPException(404, f"unknown section '{section}' (allowed: {EDITABLE_SECTIONS})")
    v = _get_version(db, key, version)
    _wrap(lambda: registry.update_draft_section(db, v, section, body.get("value"), user.name))
    db.commit()
    return _version_out(v, 0, with_content=True)


class Transition(BaseModel):
    comment: str = ""
    new_version: str | None = None


@router.post("/domain-packs/{key}/versions/{version}/publish")
def publish(key: str, version: str, body: Transition | None = None, db: Session = Depends(get_db),
            user: User = Depends(require_admin)):
    v = _get_version(db, key, version)
    _wrap(lambda: registry.publish(db, v, user.name, (body.comment if body else "")))
    db.commit()
    return _version_out(v, _usage(db).get(v.id, 0))


@router.post("/domain-packs/{key}/versions/{version}/unpublish")
def unpublish(key: str, version: str, body: Transition | None = None, db: Session = Depends(get_db),
              user: User = Depends(require_admin)):
    v = _get_version(db, key, version)
    _wrap(lambda: registry.unpublish(db, v, user.name, (body.comment if body else "")))
    db.commit()
    return _version_out(v, _usage(db).get(v.id, 0))


@router.post("/domain-packs/{key}/versions/{version}/clone", status_code=201)
def clone(key: str, version: str, body: Transition | None = None, db: Session = Depends(get_db),
          user: User = Depends(require_admin)):
    v = _get_version(db, key, version)
    nv = _wrap(lambda: registry.clone_to_draft(db, v, user.name, body.new_version if body else None))
    db.commit()
    return _version_out(nv, 0)


@router.delete("/domain-packs/{key}/versions/{version}", status_code=204)
def delete_draft(key: str, version: str, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    v = _get_version(db, key, version)
    if v.status != DomainPackStatus.DRAFT:
        raise HTTPException(409, "only drafts can be deleted; unpublish published versions instead")
    if _usage(db).get(v.id):
        raise HTTPException(409, "version is used by assessments")
    db.delete(v)
    db.commit()


@router.post("/domain-packs/sync")
def sync(db: Session = Depends(get_db), user: User = Depends(require_admin)):
    reload_reference()
    return registry.sync_filesystem(db, get_settings().domain_packs_dir, user.name)
