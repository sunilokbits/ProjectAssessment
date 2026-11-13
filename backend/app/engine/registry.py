"""Domain-pack registry: filesystem sync, versioning and publish lifecycle."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import DomainPack, DomainPackStatus, DomainPackStatusEvent, DomainPackVersion
from ..schemas.domain_pack import DomainPackContent
from .loader import (
    LoadedPack,
    PackValidationError,
    checksum_of,
    discover_pack_dirs,
    load_pack_dir,
    validate_raw,
)

log = logging.getLogger(__name__)


class RegistryError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        self.status_code = status_code
        super().__init__(message)


def _parse_semver(v: str) -> tuple[int, int, int]:
    a, b, c = (int(x) for x in v.split("."))
    return a, b, c


def bump_patch(v: str) -> str:
    a, b, c = _parse_semver(v)
    return f"{a}.{b}.{c + 1}"


def global_dimension_keys(db: Session) -> set[str]:
    gv = latest_published(db, kind="global")
    if not gv:
        return set()
    return {d["key"] for d in gv.content.get("scoring", {}).get("dimensions", [])}


def latest_published(db: Session, pack_key: str | None = None, kind: str | None = None) -> DomainPackVersion | None:
    stmt = select(DomainPackVersion).join(DomainPack).where(DomainPackVersion.status == DomainPackStatus.PUBLISHED)
    if pack_key:
        stmt = stmt.where(DomainPack.key == pack_key)
    if kind:
        stmt = stmt.where(DomainPack.kind == kind)
    versions = db.scalars(stmt).all()
    if not versions:
        return None
    return max(versions, key=lambda v: (_parse_semver(v.version), v.id))


def _record_status(db: Session, ver: DomainPackVersion, to: DomainPackStatus, actor: str, comment: str = "", frm: str | None = None):
    db.add(DomainPackStatusEvent(version=ver, from_status=frm, to_status=to.value, actor=actor, comment=comment))


def validate_content(db: Session, raw: dict[str, Any]) -> LoadedPack:
    kind = (raw.get("domain") or {}).get("kind")
    known = None if kind == "global" else global_dimension_keys(db)
    return validate_raw(raw, known)


def create_version(
    db: Session,
    raw: dict[str, Any],
    actor: str,
    notes: str = "",
    status: DomainPackStatus = DomainPackStatus.DRAFT,
    builtin: bool = False,
    source_path: str | None = None,
    expected_pack_key: str | None = None,
) -> DomainPackVersion:
    lp = validate_content(db, raw)
    meta = lp.content.domain
    if expected_pack_key and meta.key != expected_pack_key:
        raise RegistryError(f"pack key in content ('{meta.key}') does not match target domain '{expected_pack_key}'")
    pack = db.scalar(select(DomainPack).where(DomainPack.key == meta.key))
    if pack is None:
        pack = DomainPack(key=meta.key, name=meta.name, kind=meta.kind.value, description=meta.description,
                          builtin=builtin, source_path=source_path)
        db.add(pack)
        db.flush()
    elif pack.kind != meta.kind.value:
        raise RegistryError(f"domain '{meta.key}' already exists with kind '{pack.kind}', cannot change to '{meta.kind.value}'")
    existing = {v.version: v for v in pack.versions}
    version = meta.version
    if version in existing:
        if existing[version].checksum == lp.checksum:
            return existing[version]
        if existing[version].status != DomainPackStatus.DRAFT:
            raise RegistryError(
                f"version {version} of '{meta.key}' is {existing[version].status.value} and immutable; "
                f"bump the version (e.g. {bump_patch(max(existing, key=_parse_semver))})", 409)
        # overwrite a draft with the same version number
        ver = existing[version]
        ver.content = lp.raw
        ver.checksum = lp.checksum
        ver.notes = notes or ver.notes
        _sync_pack_meta(pack, lp.content)
        return ver
    ver = DomainPackVersion(pack=pack, version=version, status=DomainPackStatus.DRAFT, content=lp.raw,
                            checksum=lp.checksum, notes=notes, created_by=actor)
    db.add(ver)
    db.flush()
    _record_status(db, ver, DomainPackStatus.DRAFT, actor, "created")
    if status == DomainPackStatus.PUBLISHED:
        publish(db, ver, actor, "auto-published built-in pack" if builtin else "")
    return ver


def _sync_pack_meta(pack: DomainPack, content: DomainPackContent) -> None:
    pack.name = content.domain.name
    pack.description = content.domain.description


def publish(db: Session, ver: DomainPackVersion, actor: str, comment: str = "") -> DomainPackVersion:
    if ver.status == DomainPackStatus.PUBLISHED:
        return ver
    if ver.status == DomainPackStatus.ARCHIVED:
        raise RegistryError("archived versions cannot be published")
    lp = validate_content(db, ver.content)  # re-validate at publish time
    frm = ver.status.value
    ver.status = DomainPackStatus.PUBLISHED
    ver.published_at = datetime.now(timezone.utc)
    ver.published_by = actor
    _sync_pack_meta(ver.pack, lp.content)
    _record_status(db, ver, DomainPackStatus.PUBLISHED, actor, comment, frm)
    return ver


def unpublish(db: Session, ver: DomainPackVersion, actor: str, comment: str = "") -> DomainPackVersion:
    if ver.status != DomainPackStatus.PUBLISHED:
        raise RegistryError("only published versions can be unpublished")
    ver.status = DomainPackStatus.UNPUBLISHED
    _record_status(db, ver, DomainPackStatus.UNPUBLISHED, actor, comment, "published")
    return ver


def clone_to_draft(db: Session, ver: DomainPackVersion, actor: str, new_version: str | None = None) -> DomainPackVersion:
    taken = {v.version for v in ver.pack.versions}
    target = new_version or bump_patch(max(taken, key=_parse_semver))
    while target in taken:
        target = bump_patch(target)
    raw = dict(ver.content)
    raw["domain"] = {**raw["domain"], "version": target}
    return create_version(db, raw, actor, notes=f"cloned from {ver.version}")


def update_draft_section(db: Session, ver: DomainPackVersion, section: str, value: Any, actor: str) -> DomainPackVersion:
    if ver.status != DomainPackStatus.DRAFT:
        raise RegistryError(f"version {ver.version} is {ver.status.value}; clone it to a new draft before editing", 409)
    raw = dict(ver.content)
    if section == "domain":
        value = {**value, "key": ver.pack.key, "version": ver.version}
    raw[section] = value
    lp = validate_content(db, raw)
    ver.content = lp.raw
    ver.checksum = lp.checksum
    _sync_pack_meta(ver.pack, lp.content)
    return ver


def sync_filesystem(db: Session, root: Path, actor: str = "system") -> dict[str, Any]:
    """Import built-in packs from disk. Built-ins are vetted config and auto-publish.

    A new folder (e.g. ``domain_packs/industries/aviation``) becomes selectable after
    sync – no code, schema or API change required.
    """
    report: dict[str, Any] = {"imported": [], "unchanged": [], "errors": {}}
    dirs = discover_pack_dirs(root)
    # global pack first so its dimensions are known when validating others
    dirs.sort(key=lambda p: 0 if (p / "domain.yaml").read_text(encoding="utf-8").find("kind: global") >= 0 else 1)
    for d in dirs:
        rel = d.relative_to(root).as_posix()
        try:
            known = global_dimension_keys(db)
            lp = load_pack_dir(d, known or None)
            pack = db.scalar(select(DomainPack).where(DomainPack.key == lp.content.domain.key))
            if pack and any(v.checksum == lp.checksum for v in pack.versions):
                report["unchanged"].append(rel)
                continue
            if pack and lp.content.domain.version in {v.version for v in pack.versions}:
                report["errors"][rel] = [{
                    "location": "domain.version",
                    "message": f"content changed but version {lp.content.domain.version} already exists; bump the version",
                    "type": "version"}]
                continue
            create_version(db, lp.raw, actor, notes=f"imported from {rel}", status=DomainPackStatus.PUBLISHED,
                           builtin=True, source_path=rel)
            db.flush()
            report["imported"].append(rel)
        except PackValidationError as e:
            report["errors"][rel] = e.errors
            log.warning("invalid domain pack %s: %s", rel, e)
        except RegistryError as e:
            report["errors"][rel] = [{"location": rel, "message": str(e), "type": "registry"}]
    db.commit()
    return report


def content_of(ver: DomainPackVersion) -> DomainPackContent:
    # Stored versions are loaded leniently: rules added after a version was stored must not break
    # assessments pinned to it. Full validation happens when a version is created or published.
    return DomainPackContent.model_validate(ver.content, context={"stored": True})


def checksum(raw: dict[str, Any]) -> str:
    return checksum_of(raw)
