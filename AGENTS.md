# Repository memory

- The sandbox checkout is `/projects/cybersec-career-intelligence`; the user-provided `/home/ravi-tamilarasan/OpenHands/projects/...` path and sibling projects are not mounted here.
- Docker CLI uses the `default` context, but the Docker Desktop daemon socket was unavailable during Phase 6 validation. Do not start a second daemon or run global cleanup.
- Compose is project-scoped as `cybersec-career-intelligence`; Ollama remains external at `host.docker.internal:11434` and must not be added to Compose.
- Migrations currently reach Alembic head `ph12dunblockresolved`; Yahoo Mail uses encrypted app-password credentials, exact LinkedIn sender filtering, UIDVALIDITY/UID checkpoints, and administrator approval before research ingestion. Backend tests use SQLite through the test fixture; frontend uses Vitest and Vite. Latest validation: 166 backend tests and 62 frontend tests pass; frontend production build and `docker compose config` pass.
- Automated research uses the existing admin key and Research Review workflow. Source collection is bounded, SSRF-checked, redirect-revalidated, content-hash deduplicated, provenance-preserving, and scheduler-backed by Redis locks.
- Yahoo Mail is backend-only IMAP/TLS at `imap.mail.yahoo.com:993`; raw message bodies are not persisted. Compose passes mail settings to backend and scheduler, while Ollama remains external at `host.docker.internal:11434`.
