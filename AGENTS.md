# Repository memory

- The sandbox checkout is `/projects/cybersec-career-intelligence`; the user-provided `/home/ravi-tamilarasan/OpenHands/projects/...` path and sibling projects are not mounted here.
- Docker CLI uses the `default` context, but the Docker Desktop daemon socket was unavailable during Phase 6 validation. Do not start a second daemon or run global cleanup.
- Compose is project-scoped as `cybersec-career-intelligence`; Ollama remains external at `host.docker.internal:11434` and must not be added to Compose.
- Migrations currently reach Alembic head `ph12contractpipeline`; the contract-pipeline migration isolates legacy proposals. Backend tests use SQLite through the test fixture; frontend uses Vitest and Vite. Latest validation: 130 backend tests and 48 frontend tests pass; frontend production build and `docker compose config` pass.
- Automated research uses the existing admin key and Research Review workflow. Source collection is bounded, SSRF-checked, redirect-revalidated, content-hash deduplicated, provenance-preserving, and scheduler-backed by Redis locks.
