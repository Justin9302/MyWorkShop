# Copilot Instructions — AI Work Platform

This file is the required entry point for GitHub Copilot working in this repository. It replaces `docs/model_context.md` as the active instruction source when using VS Code + Copilot.

## Software Identity

This workspace is an **AI-assisted industry workflow platform asset repository**.

It manages **how the platform works**, not the real business content processed by the platform. The product direction is **not** a general AI chat application. It is an industry workflow platform with constraint packs, auditable reference material, structured outputs, evaluations, and version governance.

Core operating principle:

- The model (Copilot) performs reasoning and generation.
- The platform owns boundaries, evidence, permissions, process, auditability, and rollback.

## Current Stage

- **Release**: `release_2026_05_05_001` (draft)
- **Stage**: Stage 2 — Core platform configuration and first workflow set
- **Environment**: VS Code + GitHub Copilot (migrated from Codex)

## Mandatory Startup Reading

Before answering project-level questions, modifying platform assets, creating workflows, adding rules, or proposing implementation plans, read these files in order:

1. `config/active-release.yaml` — active component versions
2. `README.md` — project overview
3. `docs/current_workspace_creation_plan.md` — platform governance rules

Then load only as needed:

- `docs/workspace_plan.md` — overall platform architecture
- `docs/gitman.md` — Git and rollback boundaries
- `docs/eval.md` — evaluation and evolution design
- `docs/codex_to_vscode_migration.md` — migration reference
- `schemas/workflow.schema.json` — workflow definition contract
- `schemas/run_snapshot.schema.json` — runtime record contract

## Working Rules for Copilot

Treat this repository as the **source of truth** for platform capability assets.

### Do:

- Preserve the boundary between platform assets and business content.
- Prefer versioned workflows, constraints, prompts, schemas, tests, and release manifests.
- Read `config/active-release.yaml` before assuming any component is active.
- Use staged, task-specific context loading rather than loading every document at once.
- Record or design for auditability, traceability, human review, and rollback.
- Keep high-risk actions behind explicit human approval.
- Use structured outputs (JSON/YAML) for all key deliverables.

### Do NOT:

- Store customer documents, user uploads, raw feedback, runtime logs, model outputs, vector indexes, secrets, or local environment files in Git.
- Treat planning examples as active production workflows.
- Assume any MCP tool is project-approved until it appears in `config/mcp-tools.yaml`.
- Let an evaluation process directly modify production prompts, constraints, workflows, or model routing.

## Mandatory Context & Intent Gate

Every workflow or platform-change task **MUST** begin with a context and intent gate. Before executing any task, identify:

1. **User goal** — what are they trying to accomplish?
2. **Industry & jurisdiction** — legal/business/finance/operations + region
3. **Risk level** — low/medium/high/critical
4. **Target output** — what should be produced?
5. **Active release & versions** — from `config/active-release.yaml`
6. **Required assets** — which workflow, constraints, prompts, schemas, tools are needed?
7. **Missing information** — what do you still need to know?
8. **Approval needs** — does this require human review?

**If the task is high risk, under-specified, permission-sensitive, or changes platform behavior — PAUSE and ask the user to confirm before proceeding.**

## Context Loading Policy (Layered Loading)

Load context in layers, never all at once:

| Layer | Contents                                                            | When to Load               |
| ----- | ------------------------------------------------------------------- | -------------------------- |
| L0    | This instructions file + active-release.yaml                        | Always                     |
| L1    | Global governance (permissions, feature-flags, interruption-policy) | Platform changes           |
| L2    | Workflow YAML for the active task                                   | Workflow execution         |
| L3    | Constraints for the active industry + baseline                      | Workflow execution         |
| L4    | System prompt for the active workflow                               | Workflow execution         |
| L5    | Relevant schemas (output validation)                                | Before generating output   |
| L6    | Citations/reference metadata                                        | When sources are retrieved |
| L7    | Evaluator rubrics                                                   | Post-execution review      |
| L8    | Regression test cases                                               | Testing/validation         |

## Intent-to-Workflow Auto-Matching

When a user describes a task **without** specifying a workflow, infer the best match from this table:

| 用户意图关键词                               | 匹配工作流                  |
| -------------------------------------------- | --------------------------- |
| 合同、NDA、条款、审查、法律风险、签约        | `contract_review`           |
| 政策、合规、制度、规定、内部规则、法规疑问   | `policy_qa`                 |
| 商业模式、画布、价值主张、收入模式、商业想法 | `business_model_design`     |
| 商业模式验证、校验、假设验证、可行性         | `business_model_validation` |
| 市场进入、GTM、上市、渠道策略、获客          | `go_to_market_review`       |
| 单位经济、CAC、LTV、回本周期、毛利、留存     | `unit_economics_check`      |
| 行业研究、市场规模、竞争格局、投资研究       | `investment_research`       |
| 风险摘要、风险评估、风险清单、风险登记       | `risk_summary`              |
| 尽调、尽职调查、DD、交易审查、并购           | `due_diligence`             |
| SOP、流程、操作规范、标准作业、操作手册      | `sop_generation`            |
| 会议纪要、会议摘要、会议记录、讨论总结       | `meeting_summary`           |
| 项目复盘、回顾、事后分析、retro、改进        | `project_retrospective`     |

Inference rules:

- **User mentions a keyword from the table** → select the matching workflow, proceed to Gate check.
- **User mentions multiple keywords spanning different industries** → ask the user to clarify which task is primary.
- **User mentions nothing matching any workflow** → skip workflow execution; proceed as normal Copilot conversation.
- **User explicitly names a workflow ID or file path** → use that workflow directly, bypass auto-matching.

After matching, proceed to **Workflow Execution Rules** below.

## Workflow Execution Rules

When asked to execute a workflow:

1. **Gate check**: Run the context & intent gate. Confirm understanding with the user.
2. **Load the workflow YAML**: Read from `workflows/{industry}/{workflow_id}.yaml`
3. **Load relevant constraints**: Baseline + industry-specific from `constraints/`
4. **Source freshness & constraint update check**: Before proceeding, check whether the active knowledge base and reference data are up to date for the task's industry and jurisdiction:
   - Check `config/active-release.yaml` for `knowledge_base_version` and `knowledge_bases`
   - If the task is legal/finance/regulated and the active knowledge base is empty (v0.1.0 or `[]`), **flag that model training data may be outdated** and ask the user whether to:
     - (a) Proceed as-is with model knowledge (noting limitation)
     - (b) Pause and fetch current regulatory/official sources online (only if `external_fetch` is approved)
     - (c) Skip this workflow and return to normal conversation
   - If the user approves online fetch, use `fetch_webpage` or registered MCP fetch tools to retrieve current reference materials, then continue
   - Record the freshness decision and any fetched sources in the run snapshot
5. **Load the system prompt**: From `prompts/{industry}/{workflow_id}.system.md`
6. **Execute steps sequentially**: Follow the workflow's `steps` array in order
7. **Handle interruptions**: If a step triggers an interruption condition, pause and wait for user input
8. **Validate output**: Check against the workflow's output schema before presenting
9. **Record run snapshot**: Create a minimized run record (in `runtime/`, NOT in Git)

### Interruption Handling

When a workflow requires pausing (missing input, high risk, human approval needed):

- Save the current state description as a checkpoint
- Clearly state: what is missing, what is needed to resume, and options available
- Wait for explicit user instruction before continuing
- Record interruption details per `schemas/interruption_event.schema.json`

## Three-Agent Orchestration Flow

When a user presents a **task-level goal** (not a simple Q&A), follow this three-agent orchestration flow instead of executing workflows directly.

### Flow Diagram

```
用户目标
    │
    ▼
┌─────────────────────────────────────────────┐
│ ① Task Planner Agent（任务拆解）              │
│ .github/agents/task-planner.agent.md         │
│                                              │
│ 干净室 — 零工作上下文隔离                      │
│ 输出: 任务简报（intent + 验收标准 + 组装说明）  │
└──────────────────┬──────────────────────────┘
         ⬆         │ 任务简报
         │         ▼
         │  ┌─────────────────────────────────────┐
         │  │ 📋 持久化为计划文件                    │
         │  │ runtime/plans/task_plan_{ts}.md      │
         │  │ （带 checkbox 的人机共享视图）          │
         │  └──────────────────┬───────────────────┘
         │                     │ 计划文件
         │                     ▼
         │  ┌─────────────────────────────────────┐
         │  │ ② 执行阶段（本 Agent）                │
         │  │                                      │
         │  │ 按计划文件执行各子任务                  │
         │  │ 每完成一项 → 更新计划文件 checkbox      │
         │  │ 可调取 workflows/prompts/constraints   │
         │  │ 输出: 工作成果                         │
         │  └──────────────────┬───────────────────┘
         │                     │ 计划文件 + 工作成果
         │                     ▼
         │  ┌─────────────────────────────────────┐
         │  │ ③ Task Reviewer Agent（审核）        │
         │  │ .github/agents/task-reviewer.agent.md│
         │  │                                      │
         │  │ 读取计划文件（= 任务简报）+ 工作成果    │
         │  │ 只对比 intent vs result，不看工作过程  │
         │  │ 输出: 审核报告（通过/打回 + 差距分析）  │
         │  └──────────────────┬──────────────────┘
         │                     │ 审核结果
         │                     ▼
         │            ┌──── 通过？────┐
         │            │               │
         │           ✅              ❌
         │            │               │
         │        交付用户      第1次失败？
         │      计划文件归档      │        │
         │    状态: ✅ 已完成   第1次     第2次
         │            │          │        │
         └── 意图修正 ────────┘    ⚠️ 人工介入
            （反馈差距分析         （中断并等待用户）
              给 Planner 修正意图）
```

### Orchestration Rules

**Rule 1 — 任务拆解前置**：对于任何需要多步执行的任务，必须先调用 `task-planner` Agent 生成任务简报，不得直接执行工作流。

**Rule 2 — 干净室隔离**：调用 `task-planner` Agent 时，不得传递任何工作上下文（workflows/prompts/constraints/schemas），仅传递用户原始目标。

**Rule 3 — 审核后置**：每个任务执行完成后，必须调用 `task-reviewer` Agent 进行审核。

**Rule 4 — 审核反馈修正回路（关键规则）**：

- 第 1 次审核不通过 → **将审核报告中的差距分析反馈给 Task Planner Agent**
- Task Planner Agent 根据差距分析**修正意图定义、调整子任务拆解和验收标准**，输出修订版任务简报
- 执行阶段按修订版任务简报重新执行
- 第 2 次审核不通过 → **立即中断**，标记 `requires_human_intervention: true`，等待用户人工介入
- 审核轮次计数器存储在 `runtime/review_attempts_{timestamp}.json` 中

**Rule 5 — 反馈传递约束**：向 Task Planner 传递反馈时，只传递审核报告中的差距分析部分。不得传递任何工作执行上下文、中间产物、系统提示或工具调用记录。

**Rule 6 — 审核 Agent 上下文隔离**：调用 `task-reviewer` Agent 时，只传递任务简报 + 工作成果。不得传递执行过程中的中间产物、工具调用记录或系统提示。

**Rule 7 — 计划文件持久化**：Task Planner Agent 输出任务简报后，必须立即将其写入工作区文件 `runtime/plans/task_plan_{yyyyMMdd_HHmmss}.md`。该文件是任务执行期间的人机共享视图，包含：

- 以 `- [ ]` checkbox 格式列出的子任务清单
- 全局验收标准（同样以 checkbox 列出）
- 文件顶部状态标记：`🔄 执行中` / `⏸️ 已中断` / `✅ 已完成` / `❌ 已打回`

**Rule 8 — 进度实时同步**：执行阶段中，每完成或开始一个子任务，必须立即更新计划文件中对应条目的状态：

- 开始执行：在子任务行追加 `🔄 执行中 (HH:mm)`
- 完成：将 `- [ ]` 改为 `- [x]`，在子任务下方追加 `  - ✅ 完成 (HH:mm): {关键产出摘要}`
- 中断：文件顶部状态改为 `⏸️ 已中断`，在中止处追加 `⏸️ 中断点: {原因 + 恢复条件}`
- 打回重做：将对应子任务的 `[x]` 改回 `[ ]`，追加 `  - ❌ 打回 (HH:mm): {差距摘要}`

中断恢复时，首先读取计划文件定位当前进度，从中断点继续执行。

### 触发条件

此编排流程在以下条件下触发：

- 用户给出的是**高层目标**而非具体工作流请求（参见 Intent-to-Workflow Auto-Matching 表）
- 任务涉及 **2 个以上的子任务** 或 **跨行业/跨工作流的执行**
- 用户明确要求"规划""拆解""审核""把关"

对于**简单、单一工作流任务**（如"审查这份合同"），可以直接走现有 Workflow Execution Rules，跳过编排流程，但最终输出仍应调用 `task-reviewer` Agent 审核一次。

### Plan File Template

计划文件 `runtime/plans/task_plan_{yyyyMMdd_HHmmss}.md` 的标准格式：

```markdown
# 任务计划：{目标一句话摘要}

- 计划文件: `runtime/plans/task_plan_20260506_143000.md`
- 创建时间: 2026-05-06 14:30
- 状态: 🔄 执行中
- 版本: v1
- 审核轮次: 0

## 子任务

- [x] ① 读取市场参考数据
  - ✅ 完成 (14:32): 已加载 data/market_reference_au.yaml，验证 CAPEX/PPA/MLF 参数
- [ ] ② 确认边界参数 🔄 执行中 (14:35)
  - 意图: 验证输入参数在合理范围内，对比参考数据
  - 依赖: 子任务 ①
  - 风险: low
  - 验收标准:
    - [ ] 所有参数已对比 market_reference 数据
    - [ ] 异常偏差已标记并说明
- [ ] ③ 运行财务模型
  - 意图: 执行 solar_financial_engine.py 生成现金流和收益指标
  - 依赖: 子任务 ②
  - 风险: medium
  - 验收标准:
    - [ ] 引擎运行无错误
    - [ ] IRR/NPV/回本周期已产出
- [ ] ④ 生成分析报告
  - 意图: 汇总结果，产出结构化分析报告
  - 依赖: 子任务 ③
  - 风险: low
  - 验收标准:
    - [ ] 报告包含执行摘要、风险矩阵、敏感性分析
    - [ ] 所有数值经交叉校验

## 全局验收标准

- [ ] 意图一致性: 输出与用户原始目标一致
- [ ] 完整性: 所有子任务已产出
- [ ] 数值校验: IRR/NPV 经双路径交叉验证

## 中断记录

{仅在中断时填写，包含 checkpoint 位置和恢复条件}
```

## Constraint Enforcement

Always enforce these constraints from `constraints/baseline/` and `constraints/industries/`:

- **Privacy** (`privacy.yaml`): No secrets in Git, minimize sensitive content, record data classes
- **Citation** (`citation.yaml`): Cite sources for factual claims
- **Human Review** (`human_review.yaml`): Route high-risk outputs to human approval
- **Tool Permissions** (`tool_permissions.yaml`): Respect tool access boundaries

## Industry-Specific Behavior

### Legal

- Never provide final legal advice — always require human review
- Cite relevant laws, regulations, and precedents
- Flag jurisdiction-specific considerations

### Finance

- Never make definitive investment recommendations
- Disclose assumptions and limitations
- Flag missing data points

### Business

- Validate business model assumptions
- Flag market uncertainties
- Recommend validation steps (customer interviews, MVP tests)

### Operations

- Align SOPs with company policies
- Flag procedural gaps
- Suggest measurable success criteria

## Platform Asset Modification Rules

When asked to modify platform assets (workflows, constraints, prompts, schemas, config):

1. Read `config/active-release.yaml` first
2. Identify the specific component and version
3. Propose changes with rationale
4. Wait for explicit user confirmation before writing
5. After writing, verify with schema validation
6. Record the change in the next release manifest update

## Output Conventions

- Use proper Markdown formatting with KaTeX for math
- File paths in backticks: `workflows/legal/contract_review.yaml`
- Code blocks with language identifiers
- Structured data in JSON or YAML blocks

---

# Nature-Style Academic Skills (from nature-skills)

This section adds Nature-journal-standard academic writing, figure, citation, data, and presentation skills.
All rules are derived from primary sources — published Nature papers, journal author guidelines, and structured writing curricula.

## Intent-to-Skill Auto-Matching

When the user's request relates to academic writing or publication, match from this table:

| 用户意图关键词                                                      | 匹配技能           | 说明                         |
| ------------------------------------------------------------------- | ------------------ | ---------------------------- |
| 润色、polish、学术写作、academic writing、Nature风格、英文学术      | `nature-polishing` | 学术散文润色至Nature风格     |
| 科学图表、Nature figure、publication plot、scientific figure、SCI图 | `nature-figure`    | 生成符合Nature标准的科学图表 |
| 引用、citation、参考文献、EndNote、RIS、Zotero、支撑文献            | `nature-citation`  | Nature/CNS家族引用检索与导出 |
| 数据可用性、Data Availability、FAIR、数据存储库、数据声明           | `nature-data`      | 数据可用性声明与FAIR检查     |
| 论文PPT、paper PPT、文献汇报、journal club、论文做成PPT             | `nature-paper2ppt` | 从科学论文生成中文PPTX       |

---

## nature-polishing — Nature-Style Academic Prose Polishing

Use this skill when the user asks to polish a manuscript paragraph, abstract, introduction, results, discussion, conclusion, title, methods section, or Chinese academic draft for publication-quality English.

### Core Architecture

1. **Identify the paper type first**: Research paper / Methods paper / Hypothesis-based work / Algorithmic or device work. Do not use one narrative logic for all paper types.
2. **Write for the reader**: relevance → novelty → trust → reuse → meaning.
3. **Use the hourglass structure**: Introduction opens broadly then narrows; Discussion/Conclusion widens again.
4. **Use the correct writing order**: Results → Introduction & Conclusion → Title → Discussion → Methods → Abstract.
5. **Protect the core argument**: AI may help polish but should not invent or author the core argument.
6. **Diagnose the failure mode before editing**: paper type → section job → paragraph logic → claim/evidence/boundary → sentence polish.

### Section Responsibilities

| Section          | Key Rules                                                                                                                                                               |
| ---------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Introduction** | Tell why it matters, what gap it fills, what is known, what remains unresolved, what question the paper asks. Do NOT summarize Results or Conclusion.                   |
| **Results**      | Past tense. Report what was observed with quantitative support. Answer "what happened", not "what it means".                                                            |
| **Discussion**   | Answer how the work fits the field, what was added, whether findings support/complicate earlier results, when interpretation may fail.                                  |
| **Conclusion**   | Three-part close: restate contribution → summarize key evidence → state implication with boundary. No new data. Always run overclaim check.                             |
| **Title**        | Tell reader what to expect, avoid unnecessary technical language, be easy to search, substantiated by data. Use "curiosity with credibility".                           |
| **Methods**      | Specific, complete, transparent, reproducible. Never leave vague phrases like "under standard conditions", "using routine methods", "data were analyzed statistically". |
| **Abstract**     | Mini-paper: context/problem → gap/objective → approach → key results → implication.                                                                                     |

### Sentence & Paragraph Control

- Every sentence ≤ 30 words. If > 20 words, check for multiple propositions.
- Prefer one core subject-verb proposition per sentence.
- No em dashes in polished output (use commas, parentheses, or full stops).
- Each paragraph has one controlling idea followed by support.
- Use thematic linking, not repetitive "This suggests..." openings.

### Results vs Discussion Sentence Types

| Results (past tense, report)                       | Discussion (hedging, interpret)                                              |
| -------------------------------------------------- | ---------------------------------------------------------------------------- |
| was detected, increased, showed, enabled, achieved | may reflect, suggests that, could indicate, is likely due to, may facilitate |

### Chinese-to-English Mode

When source is Chinese: extract core propositions first → do not translate clause-by-clause → reconstruct explicit logical links (contrast, cause, implication, limitation) → verify terminology, causality, hedging → keep key technical terms stable.

### Citation & Ethics

- Cite the source you actually read and verified.
- Position attribution clearly: who was responsible for the earlier idea/method/data.
- Do not minimize others' contributions to make present work seem more original.
- AI traffic-light: Green (grammar/clarity/outline/translation) → Yellow (methods/results wording with human control) → Red (drafting core argument, fabricating references/data, uploading unpublished manuscripts).

### Output Format

1. Polished text as plain prose (not code block).
2. `Revision notes:` with 3-5 short bullets on major structural and stylistic changes.
3. If side-by-side: Original | Polished | Why changed.

---

## nature-figure — Publication-Quality Scientific Figures

Use this skill when the user asks to create, revise, audit, or polish manuscript figures, multi-panel scientific plots, or journal-ready SVG/PDF/TIFF outputs for Nature-family or other high-impact journals.

### First Move: Figure Contract Before Plotting

Before generating or editing code, establish:

1. **Core conclusion**: one-sentence claim the figure must defend.
2. **Evidence chain**: map each planned panel to the claim; drop panels that do not carry unique evidence.
3. **Archetype**: classify as `quantitative grid`, `schematic-led composite`, `image plate + quant`, or `asymmetric mixed-modality figure`.
4. **Backend**: Python (matplotlib/seaborn) or R (ggplot2/patchwork/ComplexHeatmap).
5. **Journal/export contract**: set final dimensions, editable text, source data, statistics, export formats.

### Python Quick-Start Template

```python
import matplotlib as mpl
import matplotlib.pyplot as plt

mpl.rcParams.update({
    "font.family": "sans-serif",
    "font.sans-serif": ["Arial", "Helvetica", "DejaVu Sans", "sans-serif"],
    "svg.fonttype": "none",       # editable text in SVG
    "pdf.fonttype": 42,           # editable TrueType text in PDF
    "font.size": 7,               # use 15-24 for large slide-sized panels
    "axes.spines.right": False,
    "axes.spines.top": False,
    "axes.linewidth": 0.8,
    "legend.frameon": False,
})

def save_pub_py(fig, filename, dpi=600):
    fig.savefig(f"{filename}.svg", bbox_inches="tight")
    fig.savefig(f"{filename}.pdf", bbox_inches="tight")
    fig.savefig(f"{filename}.tiff", dpi=dpi, bbox_inches="tight")
```

### R Quick-Start Template

```r
library(ggplot2)
library(patchwork)

theme_set(
  theme_classic(base_size = 6.5, base_family = "Arial") +
    theme(
      axis.line = element_line(linewidth = 0.35, colour = "black"),
      axis.ticks = element_line(linewidth = 0.35, colour = "black"),
      legend.title = element_text(size = 6.2),
      legend.text = element_text(size = 5.8),
      strip.text = element_text(size = 6.2, face = "bold"),
      plot.title = element_text(size = 7, face = "bold"),
      panel.grid = element_blank()
    )
)

save_pub_r <- function(plot, filename, width_mm = 183, height_mm = 120, dpi = 600) {
  w <- width_mm / 25.4; h <- height_mm / 25.4
  svglite::svglite(paste0(filename, ".svg"), width = w, height = h)
  print(plot); dev.off()
  grDevices::cairo_pdf(paste0(filename, ".pdf"), width = w, height = h, family = "Arial")
  print(plot); dev.off()
  ragg::agg_tiff(paste0(filename, ".tiff"), width = w, height = h, units = "in", res = dpi)
  print(plot); dev.off()
}
```

### Color Palette (Semantic)

```python
PALETTE = {
    "blue_main":      "#0F4D92",   # hero method
    "blue_secondary": "#3775BA",   # second author method
    "green_1": "#DDF3DE", "green_2": "#AADCA9", "green_3": "#8BCF8B",  # positive
    "red_1": "#F6CFCB", "red_2": "#E9A6A1", "red_strong": "#B64342",   # baseline
    "neutral_light": "#CFCECE", "neutral_mid": "#767676", "neutral_dark": "#4D4D4D",
    "gold": "#FFD700", "teal": "#42949E", "violet": "#9A4D8E",
}
```

For NMI-style pastel pages (unified family):

```python
PALETTE_NMI_PASTEL = {
    "baseline_dark": "#484878", "baseline_mid": "#7884B4", "baseline_soft": "#B4C0E4",
    "ours_tiny": "#E4E4F0", "ours_base": "#E4CCD8", "ours_large": "#F0C0CC",
    "delta_up": "#2E9E44", "delta_down": "#E53935",
}
```

### Key Design Rules

- **Typography**: Arial/Helvetica, SVG editable text (`svg.fonttype='none'`), font size 7-9 for journal-final dense panels.
- **Axes**: Only left + bottom spines. No grid lines. Frameless legends.
- **Layout**: Prefer one hero panel + subordinate evidence panels. Width ≈ 3-4× height for comparison bars.
- **Multi-panel information architecture**: Three-level progression — Overview (stacked bar/composition) → Deviation (z-score heatmap) → Relationship (scatter/bubble). No two panels may answer the same scientific question.
- **Export**: SVG is the required primary format. PNG at 300-600 dpi as secondary raster preview.
- **Bar charts**: In-bar value annotations, hatch encoding for print-safe grayscale, error bars with capsize.
- **Heatmaps**: Diverging colormap (RdBu_r for z-scores), per-column normalization, masked NaN as white.
- **Line plots**: Line width 2-3pt, marker size 8-12pt, fill_between for uncertainty bands (alpha 0.1-0.2).

### Supported Chart Types

Stacked bar, grouped bar, horizontal ablation bar, trend/line, sequential heatmap, diverging z-score heatmap, bubble scatter, radar/polar, 3D sphere illustration, fill-between area, log-scale bar, GridSpec multi-panel.

---

## nature-citation — Nature/CNS Citation Retrieval & Export

Use this skill when the user asks to add citations to manuscript text, search Nature-series or CNS support for statements, or export EndNote/RIS/Zotero RDF.

### Workflow

1. **Segment the text**: Split long text into citable segments (paragraph boundaries first, then sentence boundaries). Keep stable segment IDs (S001, S002...).
2. **Parse each segment**: Extract core claim, identify claim type (mechanism/association/method/clinical/background), convert to 2-4 English search queries.
3. **Search candidate papers**: Use Crossref API and PubMed E-utilities. Filter by journal family (Nature Portfolio / AAAS Science / Cell Press).
4. **Evaluate support level**: `strong support` / `partial support` / `background support` / `contradictory/limiting` / `metadata-only candidate`.
5. **Export**: One reference-manager file in ENW, RIS, or Zotero RDF format. Always generate HTML review artifacts for browsing/filtering.

### Scope Filtering

| User says                     | Search scope                                                                         |
| ----------------------------- | ------------------------------------------------------------------------------------ |
| "Nature系列"                  | Nature Portfolio (Nature, Nature [field], Nature Comms, Comms [field], Sci Rep, npj) |
| "CNS"                         | Cell, Nature, Science + major sister journals                                        |
| "CNS及其子刊"                 | Nature Portfolio + AAAS Science family + Cell Press                                  |
| "只要Nature/Science/Cell正刊" | Flagship only: Nature, Science, Cell                                                 |

### Search Quality Rules

- Prefer precision over volume (3-8 candidates, not 50 loosely related papers).
- Check journal identity — many journals contain "nature" in name but are not Nature Portfolio.
- Capture retractions, corrections, and expressions of concern.
- Do not fabricate DOI, pages, volume, issue, or journal metadata.

---

## nature-data — Data Availability & FAIR Metadata

Use this skill when the user asks about Nature data availability, research data sharing, repository selection, accession numbers, or FAIR metadata.

### Workflow

1. Identify target journal and article type.
2. Inventory every dataset supporting main and supplementary results.
3. Classify each dataset into access route: `public repository` / `controlled access` / `within paper or supplement` / `reused public source` / `third-party restricted` / `available on justified request`.
4. Choose repository and identifier strategy (prefer DOI, accession number, Handle, ARK).
5. Draft Data Availability statement with explicit dataset-to-location mapping.
6. Add formal dataset citations for public data.
7. Run FAIR metadata audit.

### Chinese-to-English Alignment

| Chinese phrase   | Nature-style English                                             |
| ---------------- | ---------------------------------------------------------------- |
| 数据可用性声明   | Data Availability                                                |
| 原始数据         | raw data                                                         |
| 处理后数据       | processed data                                                   |
| 源数据           | source data                                                      |
| 补充材料         | Supplementary Information                                        |
| 受限数据         | restricted data                                                  |
| 合理请求         | reasonable request (only with reason and review route)           |
| 可向通讯作者索取 | Too vague — specify restriction reason, controller, review route |

### Key Rules

- Do not invent DOIs, accession numbers, repository names, or licences.
- Prefer public, discipline-specific repositories over generalist ones.
- Flag "available upon request" as weak unless there is a specific legal/ethical/commercial restriction.
- Separate data, code, materials, and protocols unless the journal asks for combined section.

---

## nature-paper2ppt — Paper-to-Presentation PPTX

Use this skill when the user asks to make slides/PPT/PPTX for journal club, group meeting, paper sharing, thesis seminar, or lab meeting from a scientific paper.

### Core Principle

Use the paper's scientific argument as the presentation spine, not the manuscript section order.

### Default Structure (12-16 slides for 15-20 min)

1. 标题页
2. 研究背景：为什么这个问题重要
3. 知识缺口 / 技术瓶颈
4. 论文核心问题与主张
5. 研究设计 / 技术路线 / 分析框架
6. 关键证据 1
7. 关键证据 2
8. 关键证据 3
9. 验证、对照或稳健性证据
10. 机制模型 / 方法优势 / 综合框架
11. 创新点与可复用价值
12. 局限性与未解决问题
13. 总结与讨论

### Paper-Type Guidance

| Paper Type                  | Presentation Logic         |
| --------------------------- | -------------------------- |
| Discovery/mechanism         | question-to-evidence arc   |
| Methods/AI/Tool             | problem-to-solution arc    |
| Resource/Dataset/Omics      | workflow-to-validation arc |
| Clinical/Population         | design-to-inference arc    |
| Materials/Chemistry/Physics | property-to-mechanism arc  |
| Reviews/Perspectives        | evidence-map arc           |

### Style Rules

- Clean white background, dark readable text, one or two muted accent colors.
- Figure-first result slides: one dominant visual per slide, asymmetric layouts.
- Use conclusion-style titles (e.g., "PathAgent 主动识别信息不足并补充证据" not "Figure 3").
- Chinese suitable for oral academic reporting: avoid rigid translation, avoid long paragraphs.
- Preserve technical terms in English where Chinese translation would reduce precision.
- Build real `.pptx` as primary deliverable (python-pptx), not markdown outline.
