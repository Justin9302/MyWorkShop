# AI Work Platform

This workspace contains the versioned platform assets for an AI-assisted industry workflow platform.

The repository is intended to manage **how the platform works**, not the real business content processed by the platform.

## Quick Start

```
├── docs/          → Architecture & planning documents
├── config/        → Versioned platform configuration
├── schemas/       → Shared data contracts
├── workflows/     → 14 workflows across 5 domains
├── constraints/   → Baseline, industry & jurisdiction constraint packs
├── prompts/       → System prompts per workflow
├── evaluators/    → Rule packs, rubrics & judge config
├── scripts/       → Platform runtime scripts
├── lattice/       → Structured task decomposition framework
├── tests/         → Synthetic test cases
├── runtime/       → Local-only run data (excluded from Git)
├── outputs/       → Model outputs (excluded from Git)
└── logs/          → Runtime logs (excluded from Git)
```

## Tech Stack

Multi-model routing · RAG & auditable references · MCP tool system · Workflow orchestration · Evaluation sidecar · Version governance · LLM-as-Judge · Canary release · Interruption recovery · LatticeWork framework

## Current Status

**Stage 9 — Interruption Recovery** · Release `release_2026_05_10_001` (draft)

See `docs/model_context.md` for detailed platform context and active component versions.

## Scope

**Versioned in Git:** docs, workflows, constraints, prompts, schemas, evaluators, test cases, release manifests, Lattice framework.

**Excluded from Git:** customer documents, user uploads, runtime logs, model outputs, raw feedback, vector indexes, secrets, local environment files.
