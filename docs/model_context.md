# Model Context Brief

This brief is the required first-read entry point for models and agents working in this repository.

## Software Identity

This workspace is an AI-assisted industry workflow platform asset repository.

It manages how the platform works, not the real business content processed by the platform. The product direction is not a general AI chat application. It is an industry workflow platform with constraint packs, auditable reference material, structured outputs, evaluations, and version governance.

Core operating idea:

- The model performs reasoning and generation.
- The platform owns boundaries, evidence, permissions, process, auditability, and rollback.

## Current Stage

Current release status: draft.

The workspace is at Stage 1: platform skeleton and Git boundary.

Already present:

- Planning and architecture documents.
- Initial repository structure.
- Active release manifest.
- Run snapshot schema.
- Evaluation report schema.

Not active yet:

- Production workflows.
- Production prompt templates.
- Production constraint packs.
- Production evaluators.
- MCP tool manifest.

## Required Startup Reading

Before answering project-level questions, modifying platform assets, creating workflows, adding rules, or proposing implementation plans, read these files in order:

1. `docs/model_context.md`
2. `config/active-release.yaml`
3. `README.md`
4. `docs/current_workspace_creation_plan.md`

Then load additional files only as needed:

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

## Current Planned Platform Capabilities

Core platform:

- Multi-model routing.
- RAG and auditable reference library.
- Tool system, eventually including MCP-style tools/resources/prompts.
- Permission controls.
- Workflow runner.
- Audit logs.
- Human approval nodes.

Industry workflow packages planned first:

- Legal/compliance: contract review, policy Q&A, compliance checklist.
- Finance/research: industry research, risk summary, due diligence checklist.
- Operations: SOP generation, meeting summary, project review, sales support.

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

