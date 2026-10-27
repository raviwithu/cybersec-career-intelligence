# Phase 4 Frontend

## Architecture

The existing project frontend is a Vite React JavaScript application; it did not contain TypeScript, Tailwind, shadcn/ui, or React Query dependencies. Phase 4 preserves that working toolchain and implements equivalent reusable React functional components with a scoped CSS design system and a small dependency-aware data hook.

- `src/api.js` is the centralized environment-based API client. It maps directly to the Phase 3 FastAPI endpoints, serializes query parameters, and normalizes non-2xx responses into `ApiError`.
- `src/useApi.js` provides query-style loading, error, reload, and stale-response protection without adding an unrequested dependency.
- `src/components.jsx` contains reusable loading/error/empty states, badges, stat cards, headers, expectation cards, evidence links, and level controls.
- `src/pages.jsx` contains the dashboard, domain explorer, career matrix, comparison, competency explorer/detail, and global search views.
- `src/AppShell.jsx` provides the responsive sidebar/top navigation, route-like page state, shared domain/competency context, health indicator, and retained Phase 1 profile view.
- `src/app.css` is the responsive cybersecurity research dashboard design system. It includes desktop/mobile layouts, focus states, keyboard-friendly controls, track colors, matrix styling, and dark-mode-first presentation.

All dashboard statistics, domains, levels, categories, competencies, expectations, matrix cells, comparisons, and search results come from the backend API. The frontend contains no competency records, market statistics, job listings, company records, or direct database access.

## Pages and workflows

- **Overview:** backend-derived counts for domains, subdomains, competencies, expectations, and career-level coverage.
- **Domain Explorer:** nested root/subdomain tree, backend-derived counts, career-level chips, category filtering, expectation grouping, experience details, and research evidence links.
- **Career Matrix:** technical/management/shared track legend and clickable domain-level cells.
- **Compare levels:** live two-level comparison through `/api/v1/compare`, including shared, unique, and differing competencies.
- **Competencies:** search and filter by domain, level, and backend category; detail panel includes associations, related competencies, and level expectations.
- **Global Search:** keyword, domain, and level filters through `/api/v1/search`; result navigation opens the relevant competency or domain.
- **Profile:** retained Phase 1 profile creation/listing, separate from the knowledge-base read workflows.

## Launch

From the project root:

```bash
docker compose up --build
```

The frontend is exposed at `http://localhost:3100` by the existing Compose configuration and uses the configured `VITE_API_BASE_URL`. For local frontend-only development:

```bash
cd frontend
npm install
npm run dev -- --port 3100
```

The default development API URL is `http://localhost:8100`, and port 3100 matches the backend CORS allowlist. Set `VITE_API_BASE_URL` when the backend is hosted elsewhere. The project reuses the existing host Ollama configuration; the frontend does not create or configure an Ollama instance.

## Validation

```bash
cd frontend
npm test -- --run
npm run build
```

The Phase 4 suite covers dashboard rendering, domain/subdomain selection, career-level selection, expectation rendering, matrix navigation, comparison, competency detail/search, empty/error states, and responsive navigation.

## Known limitations

- The repository's existing frontend infrastructure is JavaScript/Vite with custom CSS rather than TypeScript/Tailwind/shadcn. Introducing a parallel toolchain would add dependencies and migration risk, so the implementation follows the available stack while keeping components and API contracts modular.
- The current app uses view state rather than a URL router. Deep links and browser history synchronization are recommended for a future enhancement.
- Search and detail requests are not cached between page visits; a production-scale frontend could adopt React Query once dependency policy permits.
- Screenshot verification in this environment showed the intentional API-unavailable error state because the Docker daemon and backend services were not running. Automated tests and the production build passed.
