# Project Assessment Tool – Industry / Domain-Specific Assessment Engine

Implements spec sections **32 (Industry / Domain-Specific Assessment Engine)** and **33 (Domain Expansion)**.

- **Backend:** FastAPI + Pydantic + SQLAlchemy (SQLite by default; set `PAT_DATABASE_URL` for Postgres)
- **Frontend:** React + Vite (TypeScript)
- **Domain knowledge:** YAML **Domain Packs** in `domain_packs/`. No domain knowledge is hard-coded in Python.

## Run

```bash
pip install -r backend/requirements.txt
```

```bash
python -m uvicorn app.main:app --app-dir backend --port 8000
```

```bash
npm --prefix frontend install
```

```bash
npm --prefix frontend run dev
```

Open http://localhost:5173. The app opens on the **Executive Showcase** (portfolio view for leadership); **How to use** has the step-by-step guide. As admin, click *Load demo portfolio* on the showcase to add 5 synthetic client assessments (banking, healthcare, retail, manufacturing, telecom); *Remove demo data* deletes only those.

**Branding:** colours and names live in `frontend/src/brand.ts` and the `:root` block of `frontend/src/styles.css` (approximate Insight palette – replace with official brand-guide values). Put the official logo at `frontend/public/brand/insight-logo.svg`; until then a text wordmark is shown. Use the role switcher in the header to act as `admin`, `reviewer`, `assessor` or `viewer`. This is placeholder identity sent as `X-User-Name` / `X-User-Role` headers; replace it with SSO.

Optional AI: set `ANTHROPIC_API_KEY` (or log in with `ant auth login`) to enable Claude-assisted domain detection and clarification questions (model `claude-opus-5-5`, override with `PAT_AI_MODEL`). Without credentials, or with `PAT_AI_ENABLED=false`, the deterministic keyword / rules engine is used. AI output is always a suggestion that a human confirms.

Tests:

```bash
python -m pytest backend/tests -q
```

Validate packs offline (CI-friendly):

```bash
cd backend && python -m app.cli validate
```

## Domain Packs

```
domain_packs/
  _reference/reference_data.yaml   geographies, regulatory regions, data classifications, RAG thresholds,
                                   requirement categories, ambiguity rules, technology categories
  global/                          Layer 1: global questions, risks, compliance + COMPARABLE scoring dimensions
  industries/<key>/                Layer 2: 24 industries with sub-domains
  technologies/<key>/              Layer 3: 41 technology domains
  project_types/<key>/             Layer 4 (static): 15 project types, e.g. customer_360
```

Each pack folder may contain `domain.yaml` (required), `questions.yaml`, `risks.yaml`, `kpis.yaml`, `compliance.yaml`, `terminology.yaml`, `architecture_patterns.yaml`, `recommendations.yaml`, `knowledge.yaml` (NFRs, assumptions, dependencies, security considerations, DQ checks, reporting, migration concerns, AI opportunities / risks, clarification questions), `scoring.yaml` and `prompts.yaml` (AI prompt additions).

- **Schema:** `backend/app/schemas/domain_pack.py` (Pydantic, unknown keys rejected). Export JSON Schema with `python -m app.cli schema` or from Domain Management.
- **Rules:** items can be limited to `sub_domains` and gated by a declarative `when:` condition (sub-domain, industry, technology, project type, geography, regulatory region, data classification, stage, document keywords, answers, `any_of`, `not`).
- **KPIs:** KPIs cannot carry targets. Client targets are recorded per assessment only, with a cited source.

### Adding a new industry (no code / schema / API change)

1. Create `domain_packs/industries/aviation/domain.yaml` (+ any other files).
2. Run `python -m app.cli validate ../domain_packs/industries/aviation`.
3. In **Administration → Domain Management**, click *Rescan domain_packs folder* (or restart). Folder packs auto-publish; uploaded packs arrive as drafts and must be published.
4. Aviation is now selectable by assessors.

## How the engine works

| Spec | Where |
|---|---|
| 32.4 Four-layer questionnaire, dedupe, origin labels | `engine/merger.py` – GLOBAL / INDUSTRY / SUB-DOMAIN / TECHNOLOGY / PROJECT / AI-DISCOVERED; `equivalence_key` + semantic similarity; losing copies kept in `merged_from` |
| 32.5 Auto-detection (never locks) | `engine/detection.py`; suggestion stored as `pending_confirmation`; assessment stays `classification_pending` until the user confirms or changes it |
| 32.6 Domain-aware extraction | `engine/extraction.py` – pack terminology and synonyms tag entities and categories; ambiguity rules create AI-DISCOVERED questions |
| 32.7 KPIs | per-assessment confirm / reject; target requires `target_source` |
| 32.8 Compliance | `engine/compliance.py` – system only suggests `potentially_applicable`; `confirmed_applicable` / `not_applicable` / `verified` need a reviewer; `verified` needs evidence |
| 32.9 Risks | global + industry + technology + project; indicators found in documents flag risks as evidenced |
| 32.10 Scoring | `engine/scoring.py` – comparable overall (global dimensions; weights can't be overridden by packs) + domain-adjusted overall; all weights shown in UI |
| 32.11 Architecture | `engine/architecture.py` – patterns and components only when conditions are supported; excluded components listed with reason |
| 32.12 Domain Management | `api/admin.py` + `DomainManagement.tsx` – create / modify / disable domains, sub-domains, upload YAML/JSON/zip, per-section editor with validation, versions, publish / unpublish, export |
| 32.13 Cross-domain | primary > project > technology > secondary > global priority; conflicts (same `decision_key`, different option, or `conflicts_with`) surfaced for reviewer decision |
| 32.14 Domain-aware AI | `engine/prompt_builder.py` – context header + source-priority rules + pack prompt additions + terminology |
| 32.15 Dashboard | `services.dashboard` + Dashboard tab |
| 33 Persistence | `DomainPack`, `DomainPackVersion` (immutable once published), `DomainPackStatus` (+ `DomainPackStatusEvent` audit), `DomainRuleSource` (provenance per rule), `DomainAssessmentMapping` (assessment → pinned pack version) |

Existing assessments keep the Domain Pack version they were classified with. A reviewer can explicitly upgrade a mapping to the latest published version.
