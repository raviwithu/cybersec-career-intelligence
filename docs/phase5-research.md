# Phase 5 research consolidation

Phase 5 adds an administrator-only research workflow under `/api/v1/research`.

## Workflow

1. Submit pasted text, a UTF-8 `.txt`, `.json`, or `.csv` file, or fetch a public job page with `POST /api/v1/research/import-url`.
2. URL imports return an editable title/description preview; they are not submitted to Ollama until the administrator clicks **Analyze with Ollama**. The preview then uses the same submission pipeline as pasted text and files.
3. The backend hashes the analyzed input and sends it to the existing host Ollama instance.
4. The model receives the current domains, career levels, categories, and competencies as taxonomy context.
5. Findings are normalized to existing competency IDs where possible. Unmapped findings remain reviewable but cannot produce drafts.
6. Draft expectations retain confidence and source excerpts as evidence.
7. An administrator edits, approves, rejects, and explicitly publishes drafts. Only published expectations are visible through the public knowledge APIs.

The submitted job-description body is not stored. The database retains the SHA-256 digest, metadata, extracted structured fields, and bounded evidence excerpts. Duplicate input hashes are rejected, and equivalent mapped drafts are consolidated.
URL fetching is server-side and deliberately conservative: only HTTP(S) URLs are accepted; DNS results must be public; connections are pinned to a validated public IP while preserving TLS hostname validation; redirects are revalidated and capped; only HTML/XHTML responses within the configured byte and timeout limits are parsed. JSON-LD `JobPosting` data is preferred, with bounded HTML fallback extraction. A failed, blocked, rate-limited, or malformed page should be pasted manually.


## Local configuration

Set `ADMIN_API_KEY` in the project `.env` before using the research console. The key is sent in `X-Admin-API-Key` and is not persisted by the frontend. If the variable is unset, research administration and all knowledge-base mutation endpoints return `503` by design.

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

The Research Admin console uses the existing `OLLAMA_BASE_URL` and never manages the Ollama installation. It does not pull, install, or delete models.

- **Refresh Models** calls Ollama `GET /api/tags` and lists only models already installed on the host.
- **Manual selection** stores the administrator's selected model in `model_selection` with `mode=manual`. The choice is used for subsequent research submissions until changed.
- **Evaluate Models** runs every installed model against the fixed, versioned dataset `cybersec-job-extraction-v1`. The cases cover cloud API authorization, Kubernetes/container security and threat modeling, and embedded secure-boot trust. Each request uses temperature `0` and the same taxonomy-shaped prompt.
- **Automatic selection** computes deterministic metrics from structured output: competency extraction accuracy (40% of score), domain/career classification accuracy (25%), valid structured JSON (20%), inverse hallucination rate (10%), and bounded latency preference (5%). The highest overall score wins; processing time is also used as a deterministic tie-breaker.
- The selected model and evaluation version are stored with each `research_submissions` record. This makes later findings traceable to the model configuration used at submission time.
- If discovery or every model evaluation fails, the existing active selection is preserved and the API returns an error. The configured `OLLAMA_MODEL` remains the fallback when no selection record exists.

Evaluation limitations: this is a small regression benchmark rather than a general model-quality test. It measures exact taxonomy-label coverage on three representative descriptions and does not prove broad cybersecurity knowledge, production reliability, fairness, or resistance to every prompt-injection pattern. Latency varies with host load. Scores should therefore inform administrator choice rather than replace review of extracted findings.

