# Phase 7：动态评估与进化实施规划

> 版本: 0.1.0 | 状态: draft | 前置: Phase 5（评估旁路服务预留）
>
> 本文件是 `docs/eval.md`（架构原则）和 `docs/evaluation_sidecar.md`（Phase 5 实现）的执行规划。
> 三者应配套阅读。

---

## 1. 概述

### 1.1 当前阶段 vs 目标

| 维度       | Phase 5 现状                       | Phase 7 目标                          |
| ---------- | ---------------------------------- | ------------------------------------- |
| 评分方式   | 关键词启发式（`_heuristic_score`） | LLM-as-Judge 语义评分                 |
| 测试集     | 3 个手动合成快照                   | 从真实运行自动沉淀 + 黄金样本         |
| 改进闭环   | 只生成 JSON 文本建议               | 建议→候选变更→沙箱回归→人审→灰度→回滚 |
| 回归测试   | 手动运行 `eval_runner.py`          | CI 集成 + 自动回归 + baseline 对比    |
| 可观测性   | 无                                 | 质量仪表盘 + 趋势图表                 |
| 自动化程度 | 手动触发                           | 工作流完成事件自动触发评估            |

### 1.2 核心原则

1. **避免"模型自己改自己并自动上线"** — 所有改进必须经过人审
2. **改进前必须先做回归测试** — 不能在修复一个问题的同时引入新问题
3. **灰度发布 + 可回滚** — 新版本只对部分流量生效，指标下降自动回退
4. **可归因** — 每个输出都能追溯到当时使用的 prompt、约束、资料和评估器版本
5. **从 Phase 5 增量演进** — 不推翻已有数据结构，在 Phase 5 接口基础上增强

---

## 2. 实施路线（6 个子阶段）

```text
Phase 7a ── LLM-as-Judge 评估引擎升级
      │
      ▼
Phase 7b ── 动态评估集沉淀（从真实运行自动抽取）
      │
      ▼
Phase 7c ── 改进建议 → 候选变更管线
      │
      ▼
Phase 7d ── 沙箱回归测试
      │
      ▼
Phase 7e ── 灰度发布机制
      │
      ▼
Phase 7f ── 质量仪表盘 + 自动回滚
```

各子阶段可并行开发部分模块，但依赖关系上 **7a → 7b → 7c → 7d → 7e → 7f** 是推荐顺序。

---

## 3. Phase 7a：LLM-as-Judge 评估引擎升级

### 3.1 目标

将 `eval_runner.py` 中基于关键词匹配的 `_heuristic_score()` 替换为 LLM 语义评分，使评估结果更准确、可解释。

### 3.2 新增文件

| 文件                                                 | 说明                                 |
| ---------------------------------------------------- | ------------------------------------ |
| `scripts/llm_judge.py`                               | LLM 评判封装模块                     |
| `prompts/evaluation/llm_judge.system.md`             | LLM-as-Judge system prompt           |
| `prompts/evaluation/llm_judge.rubric_{id}.system.md` | 各量规的专用评判 prompt（按需）      |
| `evaluators/rubrics/shared_judge_config.yaml`        | 评判行为配置（温度、示例数、语言等） |

### 3.3 接口设计

```python
# scripts/llm_judge.py — 核心接口

def judge_criterion(
    criterion: Dict,          # { id, weight, description }
    snapshot: Dict,           # run_snapshot（含 output、sources、constraints）
    judge_prompt: str,        # 评判 prompt 模板
    model: str = "default"    # 可选不同评判模型
) -> JudgeResult:
    """
    调用 LLM 评估单条 criterion，返回：
    - score: float (0-1)
    - reasoning: str
    - evidence: List[str]  # 从 snapshot 中引用支持判断的片段
    - confidence: float (0-1)  # LLM 对自己的判断有多确定
    """
```

### 3.4 评判 Prompt 模板

```markdown
<!-- prompts/evaluation/llm_judge.system.md -->

你是一个工作流输出评估裁判。你的任务是根据给定的评估标准（criterion）
和运行快照（run_snapshot），判断输出的质量。

## 评估标准

{criterion_description}

## 要求

1. 只基于快照中提供的证据评分，不要假设未提供的信息。
2. 如果证据不足，给出低分并标注 "insufficient_evidence"。
3. 输出必须是 JSON 格式：{ score, reasoning, evidence, confidence }。
4. 打分标准：
   - 0.0-0.2: 完全没有满足标准
   - 0.3-0.4: 大部分未满足
   - 0.5-0.6: 部分满足但有明显不足
   - 0.7-0.8: 基本满足，少量可改进
   - 0.9-1.0: 完全满足

## Criterion

{criterion}

## Output Summary

{output_summary}

## Retrieved Sources

{sources}

## Constraints Triggered

{constraints}
```

### 3.5 混合评分策略

为避免 LLM 调用成本过高，采用混合策略：

```yaml
# evaluators/rubrics/shared_judge_config.yaml
judge_strategy:
  default: "heuristic" # 默认用启发式
  criteria_requiring_llm: # 以下标准强制用 LLM
    - "legal_citation_quality"
    - "jurisdiction_awareness"
    - "no_investment_advice"
  score_below_threshold: 0.4 # 启发式得分低于此值→用 LLM 复核
  llm_model: "deepseek-chat"
  fallback_on_error: "heuristic" # LLM 失败时降级
```

### 3.6 修改现有文件

| 文件                              | 修改内容                                                              |
| --------------------------------- | --------------------------------------------------------------------- |
| `scripts/eval_runner.py`          | 在 `_heuristic_score()` 中增加 LLM 调用分支，新增 `--judge-mode` 参数 |
| `schemas/eval_report.schema.json` | findings 中增加 `llm_reasoning`、`confidence` 可选字段                |
| `config/active-release.yaml`      | 注册新 prompt 和 judge 配置                                           |

---

## 4. Phase 7b：动态评估集沉淀

### 4.1 目标

从真实运行产出中自动筛选有价值的评估样本，构建可复用的动态评估集，用于回归测试和质量基线。

### 4.2 新增文件

| 文件                           | 说明                               |
| ------------------------------ | ---------------------------------- |
| `scripts/eval_set_manager.py`  | 评估集管理器：自动分类、去重、标注 |
| `schemas/eval_set.schema.json` | 评估集 Schema                      |
| `config/eval-set-config.yaml`  | 自动分类规则配置                   |

### 4.3 新增目录

```text
tests/eval_cases/
  golden/                  # 高质量黄金样本（人工标注）
  regression/
    failures/              # 评估未通过的快照
    human_corrected/       # 人工大幅修改的快照
    risk_samples/          # 触发关键约束的快照
  synthetic/               # 已有合成样本（保留不变）
  baseline/                # 基线评估集（当前版本的参考分数）
```

### 4.4 自动分类规则

```yaml
# config/eval-set-config.yaml
eval_set_rules:
  auto_classify:
    # 低分样本 → 回归测试失败集
    - condition: "report.score < 0.4"
      target: "tests/eval_cases/regression/failures/"
      dedup_key: "workflow_id + input_summary hash"

    # 人工修改过 → 人工修正集
    - condition: "snapshot.human_review.review_status in ('approved_with_changes', 'rejected')"
      target: "tests/eval_cases/regression/human_corrected/"
      dedup_key: "workflow_id + input_summary hash"

    # 触发关键约束 → 风险样本集
    - condition: "any(c.severity == 'critical' for c in snapshot.constraints_triggered)"
      target: "tests/eval_cases/regression/risk_samples/"
      dedup_key: "constraint_id + workflow_id"

    # 用户反馈高分或人工未修改 → 候选黄金样本
    - condition: "report.metrics.output_adoption_rate >= 0.8 and not snapshot.human_review.required"
      target: "tests/eval_cases/golden/"
      requires_human_approval: true
      dedup_key: "workflow_id + output_summary hash"

  max_samples_per_category: 200
  retention_days: 180
```

### 4.5 评估集 Schema

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "Eval Set",
  "type": "object",
  "required": ["eval_set_id", "version", "category", "samples", "created_at"],
  "properties": {
    "eval_set_id": { "type": "string" },
    "version": { "type": "string" },
    "category": {
      "type": "string",
      "enum": [
        "golden",
        "regression_failure",
        "regression_human_corrected",
        "regression_risk",
        "synthetic"
      ]
    },
    "source_workflow_ids": { "type": "array", "items": { "type": "string" } },
    "samples": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "snapshot_id": { "type": "string" },
          "input_hash": { "type": "string" },
          "expected_score": { "type": "number" },
          "critical_findings": {
            "type": "array",
            "items": { "type": "string" }
          },
          "human_notes": { "type": "string" }
        }
      }
    },
    "created_at": { "type": "string", "format": "date-time" },
    "golden_standard": { "type": "boolean", "default": false }
  }
}
```

### 4.6 脚本接口

```bash
# 手动运行自动分类
python scripts/eval_set_manager.py classify \
  --report-dir outputs/eval_reports/ \
  --config config/eval-set-config.yaml

# 查看评估集统计
python scripts/eval_set_manager.py stats

# 从已有快照创建基线
python scripts/eval_set_manager.py create-baseline \
  --eval-set tests/eval_cases/regression/failures/ \
  --output outputs/eval_reports/baseline/
```

---

## 5. Phase 7c：改进建议 → 候选变更管线

### 5.1 目标

将 `eval_report` 中的 `suggestions[]` 转化为结构化的候选变更，进入审核队列。

### 5.2 新增文件

| 文件                                   | 说明                         |
| -------------------------------------- | ---------------------------- |
| `scripts/promote_suggestion.py`        | 建议提升为候选变更           |
| `schemas/candidate_change.schema.json` | 候选变更 Schema              |
| `runtime/candidate_changes/.gitkeep`   | 候选变更存储目录（不进 Git） |

### 5.3 候选变更 Schema

```yaml
# schemas/candidate_change.schema.json (核心结构)
candidate_change:
  change_id: "change_{uuid8}"
  source:
    run_id: "run_sample_002"
    report_path: "outputs/eval_reports/run_sample_002_eval.json"
    suggestion_index: 0
  target:
    component: "constraint_rules" # 见可进化对象列表
    file_path: "constraints/industries/legal.yaml"
    change_type: "add_rule" # add_rule / modify_prompt / update_template / etc
  diff:
    summary: "增加中国民法典第506条作为合同审查强制引用"
    before: "...existing rules..."
    after: "...patched rules..."
  validation:
    status: "pending" # pending / sandbox_pass / sandbox_fail / approved / rejected
    sandbox_report: null # Phase 7d 回填
    regression_result: null # Phase 7d 回填
  approval:
    required: true
    approved_by: null
    approved_at: null
    review_notes: null
  rollout:
    strategy: "canary" # canary / full
    traffic_split: 0.1
    status: "pending" # pending / canary / full / rolled_back
  created_at: "2026-05-05T00:00:00Z"
```

### 5.4 脚本接口

```bash
# 从最新评估报告中提取建议并提升为候选变更
python scripts/promote_suggestion.py \
  --report outputs/eval_reports/run_sample_002_eval.json \
  --output runtime/candidate_changes/

# 列出所有待审核的候选变更
python scripts/promote_suggestion.py --list-pending

# 审核候选变更
python scripts/promote_suggestion.py --approve change_001
python scripts/promote_suggestion.py --reject change_001 --reason "需要更多证据"
```

### 5.5 可进化对象（与 `docs/eval.md` 一致）

```yaml
evolution_targets:
  - prompts # 调整 system/step/output prompt 措辞
  - workflow_steps # 增加/删除/重排工作流步骤
  - constraint_rules # 增加/修改行业/地区/安全约束
  - retrieval_strategy # 调整检索顺序、来源优先级
  - knowledge_base_metadata # 标记过期资料、更新有效期
  - output_templates # 增加/修改输出字段和格式
  - tool_permissions # 调整工具可访问范围
  - model_routing # 切换不同场景的模型
```

---

## 6. Phase 7d：沙箱回归测试

### 6.1 目标

对候选变更进行自动化回归测试，确保改进不会引入新的质量问题。

### 6.2 新增文件

| 文件                                    | 说明                |
| --------------------------------------- | ------------------- |
| `scripts/regression_test.py`            | 回归测试引擎        |
| `schemas/regression_report.schema.json` | 回归测试报告 Schema |

### 6.3 核心流程

```text
候选变更 (candidate_change)
     │
     ▼
① 从 Git 获取当前 baseline 配置
     │
     ▼
② 用 baseline 配置评估全部评估集 → baseline_scores[]
     │
     ▼
③ 应用候选变更 → 生成 patched 配置（临时文件，不写入 Git）
     │
     ▼
④ 用 patched 配置重新评估全部评估集 → patched_scores[]
     │
     ▼
⑤ 对比 baseline vs patched
     ├── 所有维度不下降 → ✅ sandbox_pass
     ├── 部分维度下降但影响 < 阈值 → ⚠️ 人工判断
     └── 关键维度下降 → ❌ sandbox_fail
     │
     ▼
⑥ 更新 candidate_change.validation
```

### 6.4 脚本接口

```bash
# 对单个候选变更运行回归测试
python scripts/regression_test.py \
  --candidate runtime/candidate_changes/change_001.json \
  --eval-set tests/eval_cases/ \
  --output outputs/eval_reports/regression/

# 对比两个版本的基线
python scripts/regression_test.py --compare \
  --baseline outputs/eval_reports/baseline/v0.1.0.json \
  --target outputs/eval_reports/baseline/v0.2.0.json
```

### 6.5 回归报告示例

```json
{
  "change_id": "change_001",
  "status": "sandbox_pass",
  "baseline_version": "0.1.0",
  "patched_version": "0.1.1-candidate",
  "eval_set": "tests/eval_cases/",
  "sample_count": 12,
  "summary": {
    "overall_score_change": 0.03,
    "dimensions": {
      "citation_accuracy": {
        "baseline": 0.72,
        "patched": 0.78,
        "delta": 0.06,
        "passed": true
      },
      "constraint_compliance": {
        "baseline": 0.85,
        "patched": 0.85,
        "delta": 0.0,
        "passed": true
      },
      "risk_detection": {
        "baseline": 0.68,
        "patched": 0.67,
        "delta": -0.01,
        "passed": true
      },
      "format_compliance": {
        "baseline": 0.8,
        "patched": 0.8,
        "delta": 0.0,
        "passed": true
      }
    },
    "regressions": [],
    "improvements": ["citation_accuracy +0.06"]
  },
  "created_at": "2026-05-05T00:00:00Z"
}
```

---

## 7. Phase 7e：灰度发布机制

### 7.1 目标

将通过的候选变更分阶段推向生产环境，先小流量验证，再全量发布。

### 7.2 新增文件

| 文件                         | 说明             |
| ---------------------------- | ---------------- |
| `config/rollout-policy.yaml` | 灰度发布策略配置 |
| `scripts/rollout_manager.py` | 灰度发布管理器   |

### 7.3 灰度策略配置

```yaml
# config/rollout-policy.yaml
rollout:
  default_strategy: "canary"

  canary:
    enabled: false
    traffic_split: 0.1 # 10% 流量使用新版本
    observation_period: "7d" # 观察 7 天
    rollback_conditions:
      score_drop_threshold: 0.1 # 综合评分下降 > 0.1 → 回滚
      risk_increase_threshold: "high" # 出现 high 级以上新风险 → 回滚
      human_modification_increase: 0.2 # 人工修改率上升 > 0.2 → 回滚

  full_rollout:
    observation_period: "14d"
    rollback_conditions:
      score_drop_threshold: 0.05
      risk_increase_threshold: "medium"

  tenants: # 按团队/租户灰度
    pilot_teams: []
    excluded_teams: []
```

### 7.4 灰度工作流

```text
sandbox_pass 的候选变更
     │
     ▼
人工审批通过
     │
     ▼
active-release.yaml 增加 canary_components 字段
     │
     ▼
10% 流量使用新配置，90% 使用 baseline
     │
     ▼
评估系统分别记录 canary 组 vs baseline 组的 8 维指标
     │
     ├── 7 天后指标稳定 → 全量发布
     ├── 触发回滚条件 → 自动回退，记录事件
     └── 指标不明朗 → 延长观察或人工决策
```

### 7.5 脚本接口

```bash
# 启动灰度发布
python scripts/rollout_manager.py start \
  --change change_001 \
  --strategy canary \
  --traffic-split 0.1

# 检查灰度状态
python scripts/rollout_manager.py status change_001

# 全量发布
python scripts/rollout_manager.py promote change_001

# 回滚
python scripts/rollout_manager.py rollback change_001 --reason "score dropped 0.12"
```

---

## 8. Phase 7f：质量仪表盘 + 自动回滚

### 8.1 目标

可视化的质量趋势看板，并在触发预设条件时自动执行回滚。

### 8.2 新增文件

| 文件                           | 说明                 |
| ------------------------------ | -------------------- |
| `scripts/dashboard.py`         | 质量仪表盘数据聚合   |
| `config/dashboard-config.yaml` | 仪表盘配置和告警规则 |

### 8.3 仪表盘数据源

```
outputs/eval_reports/
  _batch_summary.json          ← 批量汇总（已有）
  _trend_data.json             ← 新增：按时间序列聚合的多日趋势
  _alerts.json                 ← 新增：自动告警记录
```

### 8.4 趋势聚合

```python
# scripts/dashboard.py 核心逻辑
def aggregate_trends(report_dir: str, window_days: int = 30) -> TrendData:
    """
    从 eval_reports/ 目录聚合趋势数据：
    - 每日平均分、通过率
    - 各维度得分趋势（折线图数据）
    - 按工作流分组的质量趋势
    - top findings 分布变化
    - 人工修改率趋势
    """
```

### 8.5 自动回滚触发条件

```yaml
# config/dashboard-config.yaml
alerts:
  auto_rollback_triggers:
    # 综合评分大幅下降
    - metric: "average_score"
      operator: "drop_by"
      threshold: 0.1
      window: "24h"
      action: "rollback_canary"

    # 高风险漏检率上升
    - metric: "high_risk_miss_rate"
      operator: "increase_by"
      threshold: 0.2
      window: "24h"
      action: "rollback_canary"

    # 人工修改率大幅上升
    - metric: "human_modification_rate"
      operator: "increase_by"
      threshold: 0.3
      window: "24h"
      action: "notify_only" # 仅通知，不自动回滚

  notification:
    slack_webhook: "" # Phase 7 不强制实现
    console_output: true # 第一版输出到终端

  dashboard:
    output_path: "outputs/dashboard/"
    generate_html: false # Phase 7 第一版只输出 JSON
```

### 8.6 脚本接口

```bash
# 聚合趋势数据
python scripts/dashboard.py aggregate \
  --report-dir outputs/eval_reports/ \
  --output outputs/dashboard/_trend_data.json

# 检查告警
python scripts/dashboard.py check-alerts \
  --trend outputs/dashboard/_trend_data.json

# 生成 HTML 仪表盘（后续版本）
python scripts/dashboard.py generate-html \
  --trend outputs/dashboard/_trend_data.json \
  --output outputs/dashboard/index.html
```

---

## 9. 完整 Phase 7 交付清单

### 9.1 新增文件（共 14 个）

| #   | 文件                                          | 所属子阶段 |
| --- | --------------------------------------------- | ---------- |
| 1   | `scripts/llm_judge.py`                        | 7a         |
| 2   | `prompts/evaluation/llm_judge.system.md`      | 7a         |
| 3   | `evaluators/rubrics/shared_judge_config.yaml` | 7a         |
| 4   | `scripts/eval_set_manager.py`                 | 7b         |
| 5   | `schemas/eval_set.schema.json`                | 7b         |
| 6   | `config/eval-set-config.yaml`                 | 7b         |
| 7   | `scripts/promote_suggestion.py`               | 7c         |
| 8   | `schemas/candidate_change.schema.json`        | 7c         |
| 9   | `runtime/candidate_changes/.gitkeep`          | 7c         |
| 10  | `scripts/regression_test.py`                  | 7d         |
| 11  | `schemas/regression_report.schema.json`       | 7d         |
| 12  | `config/rollout-policy.yaml`                  | 7e         |
| 13  | `scripts/rollout_manager.py`                  | 7e         |
| 14  | `scripts/dashboard.py`                        | 7f         |
| 15  | `config/dashboard-config.yaml`                | 7f         |

### 9.2 新增目录

```text
prompts/evaluation/            # LLM-as-Judge prompt 模板
tests/eval_cases/golden/       # 黄金样本
tests/eval_cases/regression/   # 回归测试样本
  failures/
  human_corrected/
  risk_samples/
tests/eval_cases/baseline/     # 基线分数
runtime/candidate_changes/     # 候选变更（不进 Git）
outputs/dashboard/             # 仪表盘数据（不进 Git）
outputs/eval_reports/regression/  # 回归报告（不进 Git）
```

### 9.3 修改现有文件（共 5 个）

| 文件                              | 修改内容                                                 | 所属 |
| --------------------------------- | -------------------------------------------------------- | ---- |
| `scripts/eval_runner.py`          | 增加 `--judge-mode` 参数，LLM 调用分支                   | 7a   |
| `schemas/eval_report.schema.json` | 增加 `llm_reasoning`、`confidence` 字段                  | 7a   |
| `config/active-release.yaml`      | Stage 更新为 `stage_7_dynamic_evolution`，注册全部新资产 | 7f   |
| `.gitignore`                      | 排除 `runtime/candidate_changes/`、`outputs/dashboard/`  | 7c   |
| `docs/evaluation_sidecar.md`      | 更新 Phase 7 演进预留表                                  | 7f   |

---

## 10. 审核要点

对照 `current_workspace_creation_plan.md` §10 审核点：

- [ ] 是否避免"模型自己改自己并自动上线"？
  - ✅ LLM-as-Judge 只输出评分和建议，不直接修改文件
  - ✅ 所有候选变更需要人工审批
  - ✅ 灰度发布可回滚
- [ ] 是否所有改进都经过测试和人工审批？
  - ✅ 7b（动态评估集提供测试数据）→ 7d（沙箱回归测试）→ 7c（人审）→ 7e（灰度）
- [ ] 是否能区分 prompt 问题、检索问题、资料问题、约束问题和模型路由问题？
  - ✅ `suggestions[].target` 枚举了 8 种进化对象
  - ✅ `candidate_change.target.component` 可追踪问题类型

---

## 11. 建议实施顺序

### 第一阶段（最小可用）

```text
Phase 7a → LLM-as-Judge 评估引擎
  （立刻提升评分准确性，为后续决策提供可靠数据）
```

预计工作量：2-3 天（含 prompt 调优和集成测试）

### 第二阶段（闭环基础）

```text
Phase 7b → 动态评估集沉淀
Phase 7c → 建议→候选变更管线
Phase 7d → 沙箱回归测试
```

预计工作量：5-7 天

### 第三阶段（生产就绪）

```text
Phase 7e → 灰度发布机制
Phase 7f → 质量仪表盘 + 自动回滚
```

预计工作量：3-5 天

### 总体

全部 Phase 7 预计 **10-15 天** 完成 MVP 版本。
