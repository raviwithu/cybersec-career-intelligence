# Phase 2 architecture: competency knowledge base

## Purpose

Phase 2 stores a centralized cybersecurity competency and career-expectations knowledge base. It is not a job portal, job tracker, job aggregator, or job-search system.

The database stores normalized knowledge extracted from research or future AI analysis. Individual job descriptions, companies, job IDs, and company-specific requirements are intentionally not stored.

## Taxonomy

- Five top-level domains: Web Application Security, Cloud API Security, Cloud Infrastructure Security, Traditional Server Infrastructure Security, and Embedded Systems Security.
- Embedded Systems Security has five child domains: Embedded Application Security, Operating System Security, Boot Security, Hardware Security, and Wireless Security.
- Six career levels are seeded: Junior, Intermediate, Senior, Manager, Architect, and Director.
- Manager and Director use the management track; Architect uses the technical track; Junior, Intermediate, and Senior are shared. The data model does not impose a hierarchy between technical and management tracks.

Domains use a self-referencing `parent_id`, so additional domains and subdomains can be added without a schema change.

## Core entities

- `security_domains`: hierarchical domain taxonomy.
- `career_levels`: level name, track, and display order.
- `competency_categories`: extensible classification such as Technical Knowledge, Leadership, and Risk Management.
- `competencies`: reusable canonical capability definitions.
- `domain_level_expectations`: consolidated expectations linking a domain, career level, and reusable competency. Multiple records are allowed for one domain/level/competency combination when responsibilities differ.
- `competency_relationships`: prerequisite, related, specialization, or dependency edges between competencies.
- `research_sources`: optional traceability references without retaining full job descriptions.
- `expectation_sources`: many-to-many evidence links with a supporting excerpt.
- `analysis_versions`: versioned snapshots of methodology and consolidated knowledge.

All operational timestamps use timezone-aware UTC values at the application boundary.

## Seed-data status

The competency and expectation examples are explicitly labeled in descriptions as **illustrative development seed; not verified market research**. They exist for development, API examples, and automated tests only. They must not be presented as market findings.

## API surface

All routes use the existing `/api/v1` prefix:

- `GET /taxonomy`
- `POST /domains`
- `POST /career-levels`
- `POST /competency-categories`
- `POST /competencies`
- `POST /competency-relationships`
- `POST /expectations`
- `GET /expectations?domain_id=&career_level_id=`
- `POST /research-sources`
- `POST /expectations/{expectation_id}/sources/{source_id}`
- `POST /analysis-versions`

Phase 1 profile, liveness, readiness, and service-health routes remain available.

## Migrations and local development

From `backend/` with the project virtual environment active:

```bash
alembic upgrade head
pytest -q
```

The application still calls `create_all` during startup for Phase 1 compatibility. Production deployments should apply the Alembic revision as the authoritative schema operation before starting the API.

## Future Ollama workflow

A future phase may supply job descriptions to an Ollama-powered analysis pipeline. The pipeline can extract requirements, normalize equivalent competencies, assign domain/level expectations, attach research evidence, and write a new `analysis_versions` record. This phase only provides the durable knowledge model; it does not implement collection, extraction, scraping, or AI analysis.
