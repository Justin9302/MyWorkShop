# AI Work Platform

This workspace contains the versioned platform assets for an AI-assisted industry workflow platform.

The repository is intended to manage how the platform works, not the real business content processed by the platform.

## Required Model Entry Point

Models and agents must read `docs/model_context.md` before answering project-level questions, modifying platform assets, creating workflows, adding rules, or proposing implementation plans.

After reading the brief, read `config/active-release.yaml` to determine which workflow, prompt, constraint, evaluator, and knowledge-base versions are currently active.

## Scope

Versioned in Git:

- Architecture and implementation docs
- Workflow definitions
- Constraint packs
- Prompt templates
- Output schemas
- Evaluation rules
- Synthetic or anonymized test cases
- Release manifests

Excluded from Git:

- Customer documents
- User uploads
- Runtime logs
- Model outputs
- Raw feedback
- Vector indexes
- Secrets and local environment files

## Current Stage

Stage 4 — Audit Logging & Run Snapshots (`stage_4_audit_logging`, draft)

Completed stages:

| Stage   | Description                                                         | Status                |
| ------- | ------------------------------------------------------------------- | --------------------- |
| Stage 1 | Workspace skeleton & Git boundary                                   | ✅ Complete           |
| Stage 2 | Core platform config + 12 industry workflows                        | ✅ Complete           |
| Stage 3 | Constraints & reference metadata (baseline, industry, jurisdiction) | ✅ Complete           |
| Stage 4 | Audit logging, run snapshots, evaluator rules                       | ✅ Complete (current) |

Key assets:

- `docs/` for planning and architecture documents
- `config/` for versioned platform configuration
- `schemas/` for shared data contracts (workflow, run_snapshot, eval_report, citation, context_load_plan, interruption_event)
- `workflows/` — 12 workflows across 4 industries (legal, business, finance, operations)
- `constraints/` — baseline (5), industry (4), jurisdiction (4) constraint packs
- `prompts/` — 12 system prompts
- `evaluators/` — 3 rule packs + 1 rubric
- `runtime/`, `outputs/`, and `logs/` for local-only run data

## Review Entry Points

- `docs/model_context.md`
- `docs/current_workspace_creation_plan.md`
- `config/active-release.yaml`
- `schemas/run_snapshot.schema.json`
- `schemas/eval_report.schema.json`
