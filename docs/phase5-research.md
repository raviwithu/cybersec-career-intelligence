# Phase 5 research consolidation

Phase 5 adds an administrator-only research workflow under `/api/v1/research`.

## Workflow

1. Submit pasted text, a UTF-8 `.txt`, `.json`, or `.csv` file, or fetch a public job page with `POST /api/v1/research/import-url`.
2. URL imports return an editable title/description preview; they are not submitted to an AI provider until the administrator clicks the analyze action. The preview then uses the same submission pipeline as pasted text and files.
3. The backend hashes the analyzed input and sends it to the persisted active AI provider/model route.
4. The model receives the current domains, career levels, categories, and competencies as taxonomy context.
5. Findings are normalized to existing competency IDs where possible. Unmapped findings remain reviewable but cannot produce drafts.
6. Draft expectations retain confidence and source excerpts as evidence.
7. An administrator edits, approves, rejects, and explicitly publishes drafts. Only published expectations are visible through the public knowledge APIs.

The submitted job-description body is not stored. The database retains the SHA-256 digest, metadata, extracted structured fields, and bounded evidence excerpts. Duplicate input hashes are rejected, and equivalent mapped drafts are consolidated.
URL fetching is server-side and deliberately conservative: only HTTP(S) URLs are accepted; DNS results must be public; connections are pinned to a validated public IP while preserving TLS hostname validation; redirects are revalidated and capped; only HTML/XHTML responses within the configured byte and timeout limits are parsed. JSON-LD `JobPosting` data is preferred, with bounded HTML fallback extraction. A failed, blocked, rate-limited, or malformed page should be pasted manually.


## Local configuration

Set `ADMIN_API_KEY` in the project `.env` before using the research console. The key is sent in `X-Admin-API-Key` and is kept only in browser `sessionStorage` for the current browser session, shared by Research Admin and Research Review. The Lock controls clear it immediately; closing the browser session clears it as well. If the variable is unset, research administration and all knowledge-base mutation endpoints return `503` by design.

The backend uses the Ollama instance running on the Ubuntu host:

```dotenv
OLLAMA_BASE_URL=http://host.docker.internal:11434
OLLAMA_MODEL=gpt-oss:20b
```

Do not add an Ollama service to this Compose project. `extra_hosts` maps `host.docker.internal` to the Docker host for Docker Desktop/Linux compatibility.

## Run

From this project directory, with Docker Desktop running:

```bash
docker compose up -d --build
```

The backend entrypoint applies Alembic migrations before starting Uvicorn. It also detects the unversioned database created by earlier project versions, stamps the existing Phase 5 schema, and applies only the model-selection migration. This preserves the existing project volume without touching other projects. To apply the migration manually after updating an already-running image:

```bash
docker compose exec backend alembic upgrade head
docker compose restart backend
```

The frontend is at `http://localhost:3100`; the backend is at `http://localhost:8100`. Existing sibling projects are not referenced by this Compose file. PostgreSQL, Redis, the network, and the named volume use `cybersec-career-intelligence-*` names.

Backend tests:

```bash
cd backend
.venv/bin/pytest -q
```

Frontend tests and build:

```bash
cd frontend
npm test -- --run
npm run build
```


## Ollama model selection

The Research Admin console uses the configured Ollama and optional OpenWebUI endpoints. It never manages either installation, and does not pull, install, or delete models.

- **Refresh Models** calls each configured provider independently and lists only models returned by that provider.
- **Manual selection** stores the administrator's selected model in `model_selection` with `mode=manual`. The choice is used for subsequent research submissions until changed.
- **Evaluate Models** runs every installed model against the fixed, versioned dataset `cybersec-job-extraction-v1`. The cases cover cloud API authorization, Kubernetes/container security and threat modeling, and embedded secure-boot trust. Each request uses temperature `0` and the same taxonomy-shaped prompt.
- **Automatic selection** computes deterministic metrics from structured output: competency extraction accuracy (40% of score), the average of domain and career-level classification accuracy (25%), valid structured JSON (20%), inverse hallucination rate (10%), and bounded latency preference (5%). The separate domain and career-level scores are shown in the console; the highest overall score wins, with processing time as a deterministic tie-breaker.
- The selected model and evaluation version are stored with each `research_submissions` record. This makes later findings traceable to the model configuration used at submission time.
- If discovery or every model evaluation fails, the existing active selection is preserved and the API returns an error. The configured `OLLAMA_MODEL` remains the fallback when no selection record exists.

Evaluation limitations: this is a small regression benchmark rather than a general model-quality test. It measures exact taxonomy-label coverage on three representative descriptions and does not prove broad cybersecurity knowledge, production reliability, fairness, or resistance to every prompt-injection pattern. Latency varies with host load. Scores should therefore inform administrator choice rather than replace review of extracted findings.

## Unified AI model selection

The administrator console supports both configured providers. Set these variables in the project `.env`:

```dotenv
AI_PROVIDER=ollama
AI_MODEL=
OLLAMA_BASE_URL=http://host.docker.internal:11434
OLLAMA_MODEL=gpt-oss:20b
OPENWEBUI_BASE_URL=http://openwebui.example.internal
OPENWEBUI_API_KEY=replace-with-openwebui-key
OPENWEBUI_TIMEOUT_SECONDS=90
```

`AI_MODEL` is preferred for the initial fallback selection; when it is empty, the legacy `OLLAMA_MODEL` value remains the fallback. `OPENWEBUI_BASE_URL` and `OPENWEBUI_API_KEY` are optional. The OpenWebUI key is used only by the backend and is never included in API responses or frontend state.

The authenticated unified endpoints are:

- `GET /api/v1/research/models` — independently discovers Ollama `/api/tags` and OpenWebUI `/api/models`, returning connected, unavailable, or unconfigured status for each provider.
- `POST /api/v1/research/models/refresh` — repeats discovery.
- `POST /api/v1/research/models/select` with `{ "provider": "openwebui", "model_id": "custom-model" }` — persists the administrator selection.
- `POST /api/v1/research/models/test` — invokes the selected route through the backend and returns reachability and latency without exposing credentials.
- `POST /api/v1/research/models/evaluate` — evaluates every model from every connected provider against the same versioned benchmark.

Ollama uses its native `/api/generate` contract. OpenWebUI uses `POST /api/chat/completions` with the exact discovered model ID and only provider-neutral chat fields; Ollama-specific options are not sent to OpenWebUI. Both response shapes are normalized to the existing `ExtractionResult` schema and validated before consolidation. A provider failure does not suppress models from the other provider. Possible duplicate model routes are marked in the response but are never merged automatically.

Known limitations: OpenWebUI deployments can expose remote models and custom routing, so discovery does not prove local hosting or identical behavior to an Ollama route. The connectivity test consumes a real provider completion. Evaluation scores are directional results from the small `cybersec-job-extraction-v1` benchmark, not an objective ranking or production quality guarantee. Provider endpoint URLs are environment configuration only; administrators cannot supply arbitrary URLs through the API.


## Research Review

The Research Review page is available from the administrator workspace and uses the same `X-Admin-API-Key` protection. It is intentionally separate from the extraction console: imported findings are presented with source excerpts, confidence (including an explicit “not provided” state), structured fields, classification gaps, existing matches, and multi-domain impact.

Review endpoints are under `/api/v1/research/review`:

- `GET /dashboard` lists pending submissions, approved/rejected/history cards, and domain, career-level, category, and source filters.
- `GET /submissions/{id}` returns source metadata, extracted findings, evidence, comparisons, and affected-domain impact.
- `GET /changes/{id}/comparison` returns original, incoming, proposed, evidence, and field-level differences.
- `POST /changes/{id}/accept`, `PATCH /changes/{id}`, `POST /changes/{id}/merge`, and `POST /changes/{id}/reject` record administrator decisions with optimistic version checks and immutable audit entries.
- `GET /publication-preview` calculates new competencies, updated expectations, merges, affected domains, career levels, and blockers.
- `POST /publish` requires `{ "confirm": true }` and expected change versions. All selected approved changes publish in one database transaction; any validation or conflict rolls the transaction back.
- `GET /history` returns decision audit history. `GET /history/expectations/{id}` returns snapshots of previous published expectation versions.

Publication preserves existing structured knowledge when an incoming proposal omits a field. Supporting excerpts are linked to the published expectation, and repeated excerpts from one source are consolidated to respect the existing source-link uniqueness rule. Rejected findings remain stored and auditable but never update the public knowledge base.

