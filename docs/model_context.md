# Model Context Brief

This brief is the required first-read entry point for models and agents working in this repository.

## Software Identity

This workspace is an AI-assisted industry workflow platform asset repository.

It manages how the platform works, not the real business content processed by the platform. The product direction is not a general AI chat application. It is an industry workflow platform with constraint packs, auditable reference material, structured outputs, evaluations, and version governance.

Core operating idea:

- The model performs reasoning and generation.
- The platform owns boundaries, evidence, permissions, process, auditability, and rollback.

## Current Stage

Current release: `release_2026_05_05_001`, status: **published**.

The workspace is at **Stage 6: Version Governance**.

Already present:

- All 6 stages complete (skeleton → workflows → constraints → audit → eval sidecar → version governance).
- 10 active workflows across 4 industries (legal, business, finance, energy).
- System prompts, constraint packs (baseline + industry + jurisdiction), evaluator rules + rubric.
- Schema contracts (workflow, run_snapshot, eval_report, citation, context_load_plan, interruption_event, release_manifest).
- Three-agent orchestration (task-planner + task-reviewer).
- Knowledge bases: AEMO NEM market data, CER LGC, Sichuan energy policy 2025-2026.
- Release governance: promote/rollback scripts, CHANGELOG, release manifests.

## Required Startup Reading

Before answering project-level questions, modifying platform assets, creating workflows, adding rules, or proposing implementation plans, read these files in order:

1. `config/active-release.yaml` — active component versions
2. `README.md` — project overview
3. `docs/current_workspace_creation_plan.md` — platform governance rules

Then load only as needed:

- Overall platform design: `docs/workspace_plan.md`
- Git and rollback boundary: `docs/gitman.md`
- Evaluation and evolution design: `docs/eval.md`
- Runtime record contract: `schemas/run_snapshot.schema.json`
- Evaluation report contract: `schemas/eval_report.schema.json`

## Working Rules For Models

Treat this repository as the source of truth for platform capability assets.

Do:

- Preserve the boundary between platform assets and business content.
- Prefer versioned workflows, constraints, prompts, schemas, tests, and release manifests.
- Read the active release manifest before assuming a workflow, prompt, constraint pack, evaluator, or knowledge base is active.
- Use staged, task-specific context loading rather than loading every document at once.
- Record or design for auditability, traceability, human review, and rollback.
- Keep high-risk actions behind explicit human approval.

Do not:

- Store customer documents, user uploads, raw feedback, runtime logs, model outputs, vector indexes, secrets, or local environment files in Git.
- Treat planning examples as active production workflows.
- Assume any MCP tool is project-approved until it appears in a versioned MCP/tool configuration file.
- Let an evaluation process directly modify production prompts, constraints, workflows, or model routing.

## Mandatory Request Gate

Every workflow or platform-change task must begin with a context and intent gate.

The gate should identify:

- User goal.
- Relevant industry, jurisdiction, scenario, and risk level.
- Target output or platform asset to change.
- Active release and relevant component versions.
- Required workflow, constraints, prompts, schemas, tools, and references.
- Missing information or approval needs.
- Files that may be edited and files that must remain untouched.

If the task is high risk, under-specified, permission-sensitive, or changes platform behavior, pause for confirmation or route to a human review step.

## Context Loading Policy

Use layered context loading:

1. Load this brief and the active release manifest.
2. Load the minimal global governance context.
3. Load only the relevant workflow, constraint, prompt, schema, evaluator, or document metadata.
4. Load source details only when needed for the specific task.
5. Summarize, filter, or run a second retrieval pass when context is too large.

Context loading decisions should be auditable in future run snapshots.

## Current Platform Capabilities

Core platform (all active):

- Multi-model routing (`config/model-routing.yaml`).
- RAG and auditable reference library (knowledge bases in `active-release.yaml`).
- Tool system, including MCP-style tools/resources/prompts (`config/mcp-tools.yaml`).
- Permission controls (`config/permissions.yaml`).
- Workflow runner with 10 workflows across 4 industries.
- Audit logs and run snapshots (`schemas/run_snapshot.schema.json`).
- Human approval nodes (`config/interruption-policy.yaml`).
- Evaluation sidecar service (`scripts/eval_runner.py`).
- Version governance (release manifest, promote/rollback, CHANGELOG).

Active industry workflow packages:

- Legal: contract review, policy Q&A.
- Business: business model design & validation, go-to-market review, unit economics check.
- Finance: investment research, risk summary, due diligence.
- Energy: solar financial model.

Three-Agent Orchestration: task-planner → execution → task-reviewer (with auto-retry and human escalation).

Governance and evaluation:

- Structured output schemas.
- Run snapshots.
- Evaluation sidecar service.
- Regression tests.
- Dynamic evaluation set.
- Human-approved evolution.
- Grey release and rollback.

## MCP And Tool Awareness

This repository plans a versioned MCP/tool manifest at `config/mcp-tools.yaml`, but that file is not present yet.

Until such a file exists, distinguish between:

- Tools available in the current Codex runtime.
- Tools approved as part of this platform's versioned design.

Runtime availability does not automatically mean project approval.

## Immediate Next Build Priorities

Recommended next assets:

1. `config/context-loading.yaml`
2. `config/mcp-tools.yaml`
3. `config/permissions.yaml`
4. `config/model-routing.yaml`
5. `config/interruption-policy.yaml`
6. `schemas/workflow.schema.json`
7. `schemas/context_load_plan.schema.json`
8. `schemas/interruption_event.schema.json`
9. First draft workflow YAML files for legal, finance, and operations.
10. Baseline constraint packs for privacy, safety, citation, and human review.
