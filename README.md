# IND_ACABC_Architecture_ai

Decision-support backend for the **Agri-Clinics and Agri-Business Centres (ACABC)** programme: it reconciles official
sources, explains geographic and financial-support patterns, screens unusual observations for human review, and
produces traceable reports. One rule-based orchestrator, six task agents, seven read-only MCP tools.

> **Status: reference build on published aggregates.** The record-level ACABC file (AIKosh dataset
> `a6dd19e7-89b7-4348-85fb-ccbf07af94fc`, access *Restricted*) has not been obtained, so no private data is loaded and
> **no model accuracy is claimed**. Independent analysis; no Government or MeitY endorsement implied.
> It never approves loans or subsidies, never labels anyone as fraudulent, and never predicts profit or survival.

## What works today

| Layer | State |
|---|---|
| Seeded official aggregates (ACABC MIS 26 Oct 2026, MANAGE state-wise 1 Oct 2026, NABARD XII-F 30 Sep 2026) | Loaded, 8 integrity checks run in tests and at `/healthz` |
| 7 MCP tools, RBAC, strict arguments, small-cell suppression, audit on every call | Working, 74 tests |
| Agents 01, 02, 03, 05, 06 | Working on aggregates |
| Agent 04 (opportunity) | Phase 2: declines with prerequisites |
| MIS vs MANAGE reconciliation | Working: gap reported (+1,041 trained, -148 ventures), never averaged |
| Robust (MAD) screen, k-means with stability | Working. Clustering matches the browser app's JavaScript output exactly |
| Record-level ingestion | Written and tested on a **synthetic** fixture; gated on confirmed rights (M0) |
| District drill-down | Blocked until a verified district field is ingested |
| Policy Q&A | Lexical retrieval over 5 paraphrased seed passages; abstains on rates/eligibility. Needs curated official circulars |

## Quick start

```bash
pip install -e ".[dev]"
pytest -q                                  # 74 tests
uvicorn acabc.api:app --reload             # http://127.0.0.1:8000/docs
```

```bash
curl -s localhost:8000/v1/ask -H 'content-type: application/json' \
     -d '{"question":"Why do MIS and MANAGE totals differ?"}'
curl -s localhost:8000/v1/reports/export?download=true -H 'X-Actor-Role: analyst' \
     -H 'content-type: application/json' -d '{"format":"pdf"}' -o report.pdf
ACABC_ACTOR_ROLE=analyst python -m acabc.mcp_server      # MCP over stdio (pip install ".[mcp]")
```

## API (architecture section 10)

| Route | Role | Purpose |
|---|---|---|
| `GET /v1/coverage` | any | Available fields, geography, periods, rights status |
| `POST /v1/metrics/query` | any (private metrics: analyst+) | Bounded aggregate query; unsupported dimensions rejected |
| `GET /v1/benchmarks/{id}` | any | Dated Ministry/MANAGE/NABARD reference |
| `POST /v1/reconcile` | any | Differences with unit and scope warnings |
| `POST /v1/anomalies/screen` | analyst, reviewer, steward | Robust screen; opens review cases for flagged groups |
| `POST /v1/anomalies/{id}/disposition` | reviewer, steward | Record a decision (no "fraud" option; immutable) |
| `POST /v1/policy/answer` | any | Cited passages or abstention |
| `POST /v1/reports/export` | analyst, reviewer, steward | Evidence-linked CSV/JSON/PDF with provenance and hash |
| `POST /v1/ask` | any | Orchestrator: classify, guard, run agents, compose |

Roles come from the `X-Actor-Role` header **in this reference build only**. Read `docs/SECURITY.md` before deploying.

## When the real file arrives (milestones M0/M1)

1. Get access on AIKosh (the dataset is Restricted; see `docs/DATA_ACCESS.md`), then run
   `python scripts/fetch_and_profile.py`. It downloads the file and writes a **schema-only** `acabc_profile.json`.
2. `python scripts/map_schema.py acabc_profile.json > config/schema_map.toml`, then review each line and fill in `[rights]`.
3. `python scripts/ingest_check.py <file> config/schema_map.toml` prints the ingestion report (no row values).
4. Load it with `load_private(...)` and pass it to `build_state(private=store)`. Enterprise segments, private aggregates and
   group screening switch on; district views switch on only if a district field is mapped.

## Layout

```
src/acabc/        orchestrator.py  agents/  tools.py  mcp_server.py  api.py  ingest.py  policy.py  statistics.py
                  guardrails.py  audit.py  state.py  sources.py  units.py  seed/ (official aggregates, policy corpus)
tests/            74 tests incl. the architecture's six scenarios and JS-parity checks
sql/schema.sql    PostgreSQL/PostGIS logical schema (not yet wired; the reference build is in-memory)
docs/             ARCHITECTURE.md  SECURITY.md  MILESTONES.md  DATA_ACCESS.md
```

## Known limits

- Seed policy passages are paraphrased from project documents, not official circular text.
- The reference build is in-memory; PostgreSQL wiring is a later milestone.
- State names are canonicalised by name; ISO/LGD codes are an M1 task that needs verified source tables.
- Clusters at k=3 currently report `exploratory_only` (silhouette 0.3998 vs the 0.40 gate). That is the honest result.
