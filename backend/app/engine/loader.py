"""Load and validate Domain Packs from folders, YAML/JSON bundles or zip uploads."""
from __future__ import annotations

import hashlib
import io
import json
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from ..schemas.domain_pack import PACK_FILES, DomainPackContent

REFERENCE_DIR = "_reference"


class PackValidationError(Exception):
    def __init__(self, errors: list[dict[str, str]]):
        self.errors = errors
        super().__init__("; ".join(f"{e['location']}: {e['message']}" for e in errors))


@dataclass
class LoadedPack:
    content: DomainPackContent
    raw: dict[str, Any]
    checksum: str
    path: Path | None = None
    warnings: list[str] = field(default_factory=list)


def checksum_of(raw: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(raw, sort_keys=True, default=str).encode()).hexdigest()


def _format_pydantic(err: ValidationError) -> list[dict[str, str]]:
    out = []
    for e in err.errors():
        loc = ".".join(str(p) for p in e["loc"]) or "(root)"
        msg = e["msg"].removeprefix("Value error, ")
        out.append({"location": loc, "message": msg, "type": e["type"]})
    return out


def _normalise_sections(raw: dict[str, Any]) -> dict[str, Any]:
    """Allow section files to be either a bare list or ``{section: [...]}``."""
    out: dict[str, Any] = {}
    for section, value in raw.items():
        if isinstance(value, dict) and set(value.keys()) == {section}:
            value = value[section]
        out[section] = value
    return out


def validate_raw(raw: dict[str, Any], known_global_dimensions: set[str] | None = None) -> LoadedPack:
    raw = _normalise_sections(raw)
    if "domain" not in raw or not raw.get("domain"):
        raise PackValidationError([{"location": "domain", "message": "domain.yaml (domain metadata) is required", "type": "missing"}])
    try:
        content = DomainPackContent.model_validate(raw)
    except ValidationError as e:
        raise PackValidationError(_format_pydantic(e)) from e
    errors: list[dict[str, str]] = []
    if known_global_dimensions is not None and content.domain.kind.value != "global":
        for msg in content.check_dimensions(known_global_dimensions):
            loc, _, m = msg.partition(": ")
            errors.append({"location": loc, "message": m, "type": "reference"})
    if errors:
        raise PackValidationError(errors)
    warnings = []
    if not content.questions and content.domain.kind.value != "global":
        warnings.append("pack defines no questions")
    if content.domain.kind.value == "industry" and not content.domain.sub_domains:
        warnings.append("industry pack defines no sub-domains")
    return LoadedPack(content=content, raw=raw, checksum=checksum_of(raw), warnings=warnings)


def read_pack_dir(path: Path) -> dict[str, Any]:
    raw: dict[str, Any] = {}
    for section, filename in PACK_FILES.items():
        for candidate in (path / filename, path / filename.replace(".yaml", ".yml"), path / filename.replace(".yaml", ".json")):
            if candidate.exists():
                text = candidate.read_text(encoding="utf-8")
                try:
                    data = json.loads(text) if candidate.suffix == ".json" else yaml.safe_load(text)
                except (yaml.YAMLError, json.JSONDecodeError) as e:
                    raise PackValidationError([{"location": candidate.name, "message": f"parse error: {e}", "type": "parse"}]) from e
                if data is not None:
                    raw[section] = data
                break
    unknown = [p.name for p in path.iterdir() if p.is_file() and p.suffix in (".yaml", ".yml", ".json")
               and p.stem not in {f.split(".")[0] for f in PACK_FILES.values()}]
    if unknown:
        raise PackValidationError([{"location": n, "message": f"unknown pack file (allowed: {sorted(PACK_FILES.values())})", "type": "unknown_file"} for n in unknown])
    return raw


def load_pack_dir(path: Path, known_global_dimensions: set[str] | None = None) -> LoadedPack:
    lp = validate_raw(read_pack_dir(path), known_global_dimensions)
    lp.path = path
    return lp


def discover_pack_dirs(root: Path) -> list[Path]:
    """Any folder containing domain.yaml is a pack; folders starting with '_' are skipped."""
    found = []
    for p in sorted(root.rglob("domain.y*ml")):
        if any(part.startswith("_") for part in p.relative_to(root).parts[:-1]):
            continue
        found.append(p.parent)
    return found


def parse_upload(filename: str, data: bytes) -> dict[str, Any]:
    """Accept a single bundle (.yaml/.yml/.json containing all sections) or a .zip of a pack folder."""
    name = filename.lower()
    try:
        if name.endswith(".zip"):
            raw: dict[str, Any] = {}
            stems = {f.split(".")[0]: s for s, f in PACK_FILES.items()}
            with zipfile.ZipFile(io.BytesIO(data)) as zf:
                for info in zf.infolist():
                    if info.is_dir():
                        continue
                    p = Path(info.filename)
                    if p.suffix not in (".yaml", ".yml", ".json") or p.stem not in stems:
                        continue
                    text = zf.read(info).decode("utf-8")
                    raw[stems[p.stem]] = json.loads(text) if p.suffix == ".json" else yaml.safe_load(text)
            return raw
        text = data.decode("utf-8")
        parsed = json.loads(text) if name.endswith(".json") else yaml.safe_load(text)
    except (yaml.YAMLError, json.JSONDecodeError, UnicodeDecodeError, zipfile.BadZipFile) as e:
        raise PackValidationError([{"location": filename, "message": f"could not parse upload: {e}", "type": "parse"}]) from e
    if not isinstance(parsed, dict):
        raise PackValidationError([{"location": filename, "message": "bundle must be a mapping of sections (domain, questions, ...)", "type": "parse"}])
    return parsed


def load_reference_data(root: Path) -> dict[str, Any]:
    path = root / REFERENCE_DIR / "reference_data.yaml"
    if not path.exists():
        return {}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
