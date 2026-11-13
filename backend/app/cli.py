"""CLI: validate domain packs without running the server.

    python -m app.cli validate                       # every pack under domain_packs/
    python -m app.cli validate ../domain_packs/industries/aviation
    python -m app.cli schema > domain_pack.schema.json
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from .config import get_settings
from .engine.loader import PackValidationError, discover_pack_dirs, load_pack_dir
from .schemas.domain_pack import json_schema


def validate(paths: list[str]) -> int:
    root = get_settings().domain_packs_dir
    dirs = [Path(p) for p in paths] if paths else discover_pack_dirs(root)
    global_dims: set[str] = set()
    for d in discover_pack_dirs(root):
        try:
            lp = load_pack_dir(d)
            if lp.content.domain.kind.value == "global":
                global_dims = {x.key for x in lp.content.scoring.dimensions}
        except PackValidationError:
            pass
    failed = 0
    for d in dirs:
        try:
            lp = load_pack_dir(d, global_dims or None)
            c = lp.content
            print(f"OK    {d}  [{c.domain.kind.value}] {c.domain.key} v{c.domain.version}: "
                  f"{len(c.domain.sub_domains)} sub-domains, {len(c.questions)} questions, {len(c.risks)} risks, "
                  f"{len(c.kpis)} KPIs, {len(c.compliance)} compliance, {len(c.terminology)} terms"
                  + (f"  (warnings: {'; '.join(lp.warnings)})" if lp.warnings else ""))
        except PackValidationError as e:
            failed += 1
            print(f"FAIL  {d}")
            for err in e.errors:
                print(f"      - {err['location']}: {err['message']}")
    print(f"\n{len(dirs) - failed}/{len(dirs)} packs valid")
    return 1 if failed else 0


def main() -> int:
    if len(sys.argv) < 2 or sys.argv[1] not in ("validate", "schema"):
        print(__doc__)
        return 2
    if sys.argv[1] == "schema":
        print(json.dumps(json_schema(), indent=2))
        return 0
    return validate(sys.argv[2:])


if __name__ == "__main__":
    raise SystemExit(main())
