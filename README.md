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

Stage 7 — Dynamic Evolution (`stage_7_dynamic_evolution`, published)

Current release: `release_2026_05_05_001`

Completed stages:

| Stage   | Description                                                                      | Status         |
| ------- | -------------------------------------------------------------------------------- | -------------- |
| Stage 1 | Workspace skeleton & Git boundary                                                | ✅ Complete    |
| Stage 2 | Core platform config + 10 industry workflows                                     | ✅ Complete    |
| Stage 3 | Constraints & reference metadata (baseline, industry, jurisdiction)              | ✅ Complete    |
| Stage 4 | Audit logging, run snapshots, evaluator rules                                    | ✅ Complete    |
| Stage 5 | Evaluation sidecar service (eval_runner + API + synthetic snapshots)             | ✅ Complete    |
| Stage 6 | Version governance (release manifest, promote/rollback, CHANGELOG)               | ✅ Complete    |
| Stage 7 | Dynamic evolution — LLM-as-Judge, eval set management, candidate change pipeline | ✅ In Progress |

Completed Phase 7 sub-stages:

| Sub-stage | Description                                        | Status         |
| --------- | -------------------------------------------------- | -------------- |
| Phase 7a  | LLM-as-Judge evaluation engine upgrade             | ✅ Complete    |
| Phase 7b  | Dynamic eval set precipitation & classification    | ✅ Complete    |
| Phase 7c  | Improvement suggestion → candidate change pipeline | ✅ Complete    |
| Phase 7d  | Sandbox regression testing                         | ✅ Complete    |
| Phase 7e  | Canary release mechanism                           | 🚧 In Progress |
| Phase 7f  | Quality dashboard & auto-rollback                  | 🚧 In Progress |

Active component versions:

| Component            | Version  |
| -------------------- | -------- |
| Workflow             | 0.2.0    |
| Constraint           | 0.4.0    |
| Prompt               | 0.1.0    |
| Evaluator            | 0.2.0    |
| Judge (LLM-as-Judge) | 0.1.0    |
| Knowledge Base       | kb_0.3.0 |

Key assets:

- `docs/` for planning and architecture documents
- `config/` for versioned platform configuration
- `schemas/` for shared data contracts (workflow, run_snapshot, eval_report, citation, context_load_plan, interruption_event, release_manifest, eval_set, candidate_change)
- `workflows/` — 13 workflows across 4 industries (legal, business, finance, operations, energy)
- `constraints/` — baseline (6), industry (5), jurisdiction (4) constraint packs
- `prompts/` — system prompts per workflow + evaluation judge prompts
- `evaluators/` — 3 rule packs + 5 rubrics + shared judge config
- `runtime/`, `outputs/`, and `logs/` for local-only run data
- `scripts/` — eval_runner.py, llm_judge.py, eval_set_manager.py, promote_suggestion.py, release_promote.sh, rollback.sh

## Review Entry Points

- `docs/model_context.md`
- `docs/current_workspace_creation_plan.md`
- `config/active-release.yaml`
- `schemas/run_snapshot.schema.json`
- `schemas/eval_report.schema.json`
