# 评估旁路服务（Evaluation Sidecar）— Phase 5 架构文档

> 版本: 0.1.0 | 阶段: Phase 5 | 状态: draft

## 1. 设计目标

评估旁路服务（Sidecar Service）是一个**独立于主平台**的评估系统：

- **不影响**主平台已有的工作流、约束、知识库或模型配置
- **只读输入**：通过标准接口读取 `run_snapshot`
- **只输出建议**：输出 `eval_report` 含评分、发现、建议，但**不能自动修改生产配置**
- **异步运行**：默认在主流程之后执行，不阻塞用户拿到结果
- **版本隔离**：评估逻辑自身版本化，升级不改变历史记录解释方式

## 2. 架构边界

```
┌─────────────────────────────────────────────────────────┐
│                    主平台 (Primary)                       │
│                                                         │
│  工作流执行 → 检索 → 约束引擎 → 工具调用 → 用户交互        │
│       │                                                 │
│       │ WorkflowCompleted Event                         │
│       ▼                                                 │
│  run_snapshot (JSON)                                    │
└──────────────┬──────────────────────────────────────────┘
               │
               │ 只读接口 (API / File)
               ▼
┌──────────────────────────────────────────────────────────┐
│              评估旁路 (Evaluation Sidecar)                │
│                                                          │
│  接收快照 → 运行评估规则 → 生成报告 → 沉淀评估集           │
│       │                                                  │
│       │ 只输出 eval_report                               │
│       ▼                                                  │
│  ┌──────────────────────────────────────┐               │
│  │  outputs/eval_reports/ (本地)         │               │
│  │  Phase 7+: 独立评估数据库              │               │
│  └──────────────────────────────────────┘               │
└──────────────────────────────────────────────────────────┘
```

### 主平台负责

- 工作流执行、知识库检索、约束引擎
- 工具调用、用户交互、审计日志
- 生成 `run_snapshot`

### 评估旁路负责

- 接收 `run_snapshot`
- 运行评估规则 & 量规
- 输出 `eval_report`
- 沉淀动态评估集（Phase 7+）
- 生成改进建议（Phase 7+）

### 硬边界

| 规则       | 说明                                                             |
| ---------- | ---------------------------------------------------------------- |
| 只读输入   | 评估系统不能直接访问或修改生产知识库、prompt、约束包、工作流配置 |
| 只输出建议 | 评估结果仅作为改进建议，不能自动发布变更                         |
| 异步默认   | 默认 `blocking: false`，只有高风险场景可配置同步拦截             |
| 版本隔离   | 评估逻辑版本化，`evaluator_version` 记录在报告中                 |
| 不进 Git   | 评估报告存储在 `outputs/eval_reports/`，已被 `.gitignore` 排除   |

## 3. API 接口契约

完整 OpenAPI 3.1 定义见 `schemas/evaluation-api.openapi.yaml`。

### Phase 5 最小接口（已实现）

| 方法   | 路径                           | 说明                         |
| ------ | ------------------------------ | ---------------------------- |
| `POST` | `/evaluation/run`              | 单次评估：接收快照，返回报告 |
| `GET`  | `/evaluation/reports/{run_id}` | 查询历史报告                 |
| `POST` | `/evaluation/batch`            | 批量评估：多快照，汇总报告   |

### Phase 7+ 预留接口

| 方法   | 路径                              | 说明                         |
| ------ | --------------------------------- | ---------------------------- |
| `POST` | `/evaluation/suggestions/promote` | 提升建议为候选变更（需人审） |
| `POST` | `/evaluation/evalsets/generate`   | 从运行历史生成动态评估集     |
| `POST` | `/evaluation/compare`             | A/B 对比两次运行             |

### Phase 5 实现方式

第一版以 **VS Code Task 模式** 运行，由 `scripts/eval_runner.py` 模拟 HTTP API：

```bash
# 等效于 POST /evaluation/run
python3 scripts/eval_runner.py \
  --snapshot runtime/snapshots/run_001.json \
  --rubric evaluators/rubrics/business_model_validation.yaml \
  --output outputs/eval_reports/run_001_eval.json

# 等效于 POST /evaluation/batch
python3 scripts/eval_runner.py \
  --batch runtime/snapshots/ \
  --rubric evaluators/rubrics/business_model_validation.yaml \
  --output-dir outputs/eval_reports/
```

## 4. 8 维评估指标体系

| #   | 维度         | 指标 ID                   | 说明                           |
| --- | ------------ | ------------------------- | ------------------------------ |
| 1   | 引用准确率   | `citation_accuracy`       | 是否基于资料回答，引用是否正确 |
| 2   | 约束合规率   | `constraint_compliance`   | 是否遵守行业、地区、组织规则   |
| 3   | 格式合规率   | `format_compliance`       | 输出是否符合规定模板结构       |
| 4   | 风险识别率   | `risk_detection`          | 是否识别高风险事项             |
| 5   | 人工修改率   | `human_modification_rate` | 输出被人工修改的幅度           |
| 6   | 输出采纳率   | `output_adoption_rate`    | 用户直接采纳/使用的比例        |
| 7   | 高风险漏检率 | `high_risk_miss_rate`     | 应识别但未识别的高风险事项比例 |
| 8   | 成本与延迟   | `cost_latency`            | 模型调用成本+延迟的综合评分    |

## 5. 评估规则与量规

### 评估规则 (evaluators/rules/) — 跨工作流通用

| 规则包                | 说明                      |
| --------------------- | ------------------------- |
| `citation_check.yaml` | 引用准确性与事实/推断分离 |
| `risk_check.yaml`     | 风险识别与人审触发        |
| `schema_check.yaml`   | 输出结构与 Schema 合规    |

### 评估量规 (evaluators/rubrics/) — 工作流特定

| 量规                             | 适用工作流                |
| -------------------------------- | ------------------------- |
| `business_model_validation.yaml` | business_model_validation |
| `contract_review.yaml`           | contract_review           |
| `due_diligence.yaml`             | due_diligence             |
| `sop_generation.yaml`            | sop_generation            |

## 6. 数据流与集成模式

```yaml
integration_mode: sidecar
trigger: workflow_completed # 主流程完成后触发
blocking: false # 默认非阻塞
input: run_snapshot # 输入类型
output: evaluation_report # 输出类型
write_back: disabled # 禁止写回生产配置
retention:
  reports: "outputs/eval_reports/" # 报告存储位置
  ttl_days: 90 # 保留期限
```

## 7. 审核要点

根据 Phase 5 计划 Section 8：

- [x] 评估服务只读输入：通过 `run_snapshot` JSON 文件读取，不访问生产配置
- [x] 评估结果只作建议输出：`suggestions[].requires_human_approval` 默认为 `true`
- [x] 禁止自动修改生产 prompt、约束或工作流：`write_back: disabled`
- [x] 版本隔离：`evaluator_version` 记录在每份报告中
- [x] API 契约完整：OpenAPI 3.1 定义在 `schemas/evaluation-api.openapi.yaml`
- [x] 8 维指标覆盖：`eval_report.schema.json` 包含全部 8 维指标

## 8. Phase 7 演进预留

> 详细实施规划见 `docs/evaluation_evolution_plan.md`（6 个子阶段：7a-7f，含交付清单、文件设计、脚本接口）。

| 能力         | Phase 5 状态                                 | Phase 7 目标                       | Phase 7 当前状态                     |
| ------------ | -------------------------------------------- | ---------------------------------- | ------------------------------------ |
| 自动改进建议 | 脚本启发式评分                               | LLM-as-Judge 精细评估              | ✅ 7a 完成 — `llm_judge.py`          |
| 动态评估集   | 手动合成快照 (`tests/eval_cases/synthetic/`) | 从真实运行自动沉淀                 | ✅ 7b 完成 — `eval_set_manager.py`   |
| 改进审核队列 | 无                                           | `suggestions/promote` + 人审工作流 | ✅ 7c 完成 — `promote_suggestion.py` |
| 回归测试     | 手动运行 `eval_runner.py`                    | CI 集成 + 自动回归                 | ✅ 7d 完成 — `regression_test.py`    |
| 灰度发布     | 无                                           | A/B 测试 + 分团队灰度              | ✅ 7e 完成 — `rollout_manager.py`    |
| 质量仪表盘   | 无                                           | 实时指标 + 趋势图表                | ✅ 7f 完成 — `dashboard.py`          |
