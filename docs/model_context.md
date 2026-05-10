# Model Context Brief

This brief is the required first-read entry point for models and agents working in this repository.

## Software Identity

This workspace is an AI-assisted industry workflow platform asset repository.

It manages how the platform works, not the real business content processed by the platform. The product direction is not a general AI chat application. It is an industry workflow platform with constraint packs, auditable reference material, structured outputs, evaluations, and version governance.

Core operating idea:

- The model performs reasoning and generation.
- The platform owns boundaries, evidence, permissions, process, auditability, and rollback.

## Current Stage

Current release: `release_2026_05_10_001`, status: **draft** (pending promotion).

The workspace is at **Stage 9: Interruption Recovery**.

### Completed Stages

| Stage   | Description                                                                      | Status      |
| ------- | -------------------------------------------------------------------------------- | ----------- |
| Stage 1 | Workspace skeleton & Git boundary                                                | ✅ Complete |
| Stage 2 | Core platform config + 14 industry workflows                                     | ✅ Complete |
| Stage 3 | Constraints & reference metadata (baseline, industry, jurisdiction)              | ✅ Complete |
| Stage 4 | Audit logging, run snapshots, evaluator rules                                    | ✅ Complete |
| Stage 5 | Evaluation sidecar service (eval_runner + API + synthetic snapshots)             | ✅ Complete |
| Stage 6 | Version governance (release manifest, promote/rollback, CHANGELOG)               | ✅ Complete |
| Stage 7 | Dynamic evolution — LLM-as-Judge, eval set management, candidate change pipeline | ✅ Complete |
| Stage 8 | Workflow orchestration engine                                                    | ✅ Complete |
| Stage 9 | Interruption handling & recovery                                                 | ✅ Complete |

### Completed Phases

| Phase    | Description                                        | Status      |
| -------- | -------------------------------------------------- | ----------- |
| Phase 7a | LLM-as-Judge evaluation engine upgrade             | ✅ Complete |
| Phase 7b | Dynamic eval set precipitation & classification    | ✅ Complete |
| Phase 7c | Improvement suggestion → candidate change pipeline | ✅ Complete |
| Phase 7d | Sandbox regression testing                         | ✅ Complete |
| Phase 7e | Canary release mechanism                           | ✅ Complete |
| Phase 7f | Quality dashboard & auto-rollback                  | ✅ Complete |
| Phase 8  | Workflow orchestration engine                      | ✅ Complete |
| Phase 9  | Interruption handling & recovery                   | ✅ Complete |

### Active Component Versions

| Component            | Version  |
| -------------------- | -------- |
| Workflow             | 0.3.0    |
| Constraint           | 0.4.0    |
| Prompt               | 0.2.0    |
| Evaluator            | 0.2.0    |
| Judge (LLM-as-Judge) | 0.1.0    |
| Knowledge Base       | kb_0.3.0 |
| Lattice Framework    | 1.0.0    |

### Key Assets

- `docs/` for planning and architecture documents
- `config/` for versioned platform configuration
- `schemas/` for shared data contracts (workflow, run_snapshot, eval_report, citation, context_load_plan, interruption_event, release_manifest, eval_set, candidate_change, regression_report)
- `workflows/` — 14 workflows across 5 domains (legal, business, finance, operations, energy, general)
- `constraints/` — baseline (6), industry (5), jurisdiction (4) constraint packs
- `prompts/` — system prompts per workflow + evaluation judge prompts
- `evaluators/` — 3 rule packs + 6 rubrics + shared judge config
- `scripts/` — eval_runner.py, llm_judge.py, eval_set_manager.py, promote_suggestion.py, release_promote.sh, rollback.sh, rollout_manager.py, dashboard.py, workflow_runner.py, interruption_handler.py
- `lattice/` — LatticeWork structured task decomposition & execution framework (schemas, scripts, workflows, templates, examples)
- `runtime/`, `outputs/`, and `logs/` for local-only run data

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
- Lattice framework: `lattice/README.md`

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
- Workflow runner with 14 workflows across 5 domains.
- Audit logs and run snapshots (`schemas/run_snapshot.schema.json`).
- Human approval nodes (`config/interruption-policy.yaml`).
- Evaluation sidecar service (`scripts/eval_runner.py`).
- Version governance (release manifest, promote/rollback, CHANGELOG).
- LLM-as-Judge evaluation engine (`scripts/llm_judge.py`).
- Dynamic eval set management (`scripts/eval_set_manager.py`).
- Candidate change pipeline (`scripts/promote_suggestion.py`).
- Sandbox regression testing (`scripts/regression_test.py`).
- Canary release mechanism (`scripts/rollout_manager.py`).
- Quality dashboard & auto-rollback (`scripts/dashboard.py`).
- Workflow orchestration engine (`scripts/workflow_runner.py`).
- Interruption handling & recovery (`scripts/interruption_handler.py`).
- LatticeWork structured task decomposition framework (`lattice/`).

Active industry workflow packages:

- Legal: contract review, policy Q&A.
- Business: business model design & validation, go-to-market review, unit economics check.
- Finance: investment research, risk summary, due diligence.
- Energy: solar financial model.
- Operations: SOP generation, meeting summary, project retrospective.
- General: ideation convergence.

Three-Agent Orchestration: task-planner → execution → task-reviewer (with auto-retry and human escalation).

Governance and evaluation:

- Structured output schemas.
- Run snapshots.
- Evaluation sidecar service.
- Regression tests.
- Dynamic evaluation set.
- Human-approved evolution.
- Grey release and rollback.
- Interruption handling with checkpoint/resume.

## MCP And Tool Awareness

This repository maintains a versioned MCP/tool manifest at `config/mcp-tools.yaml`.

Distinguish between:

- Tools available in the current runtime.
- Tools approved as part of this platform's versioned design.

Runtime availability does not automatically mean project approval.

## Immediate Next Build Priorities

The platform has completed all 9 planned stages. Future evolution priorities:

1. Cross-release regression trend analysis & quality gates
2. Automated test case generation from production failures
3. Multi-agent orchestration with Lattice framework integration
4. Real-time monitoring & alerting for evaluation metrics
5. Knowledge base auto-refresh pipeline
