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

Stage 1 creates the workspace skeleton and Git boundary:

- `docs/` for planning and architecture documents
- `config/` for versioned platform configuration
- `schemas/` for shared data contracts
- `workflows/`, `constraints/`, `prompts/`, and `evaluators/` for platform behavior
- `runtime/`, `outputs/`, and `logs/` for local-only run data

## Review Entry Points

- `docs/model_context.md`
- `docs/current_workspace_creation_plan.md`
- `config/active-release.yaml`
- `schemas/run_snapshot.schema.json`
- `schemas/eval_report.schema.json`
