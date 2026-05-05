# 动态评估与进化方案

本方案建议将“动态评估与进化”设计成一个独立的 **旁路系统 / Sidecar Service**。它不直接改动主平台已有的工作流、约束、知识库或模型配置，只通过标准接口读取运行快照，并输出评估结果与改进建议。

## 设计目标

- 不影响已建立的主平台体系。
- 对每次 AI 工作流运行进行独立评估。
- 持续沉淀真实案例，形成动态评估集。
- 输出评分、风险、缺陷和改进建议。
- 支持未来的灰度发布、A/B 测试、回归测试和版本治理。

## 架构边界

主平台负责：

- 工作流执行
- 知识库检索
- 约束引擎
- 工具调用
- 用户交互
- 审计日志

评估旁路服务负责：

- 接收运行快照
- 运行评估规则
- 输出评估报告
- 生成改进建议
- 写入独立评估库
- 构建动态评估集

两者之间只通过事件或 API 通信：

```text
WorkflowCompleted Event
        ↓
Evaluation Service
        ↓
EvaluationReport
```

## 核心原则

### 1. 只读输入

评估系统只能读取运行快照，不能直接访问或修改生产知识库、prompt、约束包、工作流配置。

### 2. 只输出建议

评估系统可以输出评分、风险、缺陷和改进建议，但不能自动发布变更。

### 3. 异步运行

默认在主流程之后执行，不阻塞用户拿到结果。只有高风险场景才可配置为同步拦截。

### 4. 版本隔离

评估逻辑本身也要版本化，例如：

```json
{
  "evaluator_version": "0.3.1"
}
```

这样评估系统升级不会改变历史记录的解释方式。

## 最小集成方式

第一版只需要主平台在工作流结束后发送一份 JSON 快照：

```yaml
integration_mode: sidecar
trigger: workflow_completed
blocking: false
input: run_snapshot
output: evaluation_report
write_back: disabled
```

这意味着评估系统不会碰现有体系，只在旁边完成“看、评、记、建议”。

## 调用入口

主平台可以只暴露一个评估调用入口：

```http
POST /evaluation/run
```

### 输入示例

```json
{
  "run_id": "run_123",
  "workflow_id": "contract_review",
  "workflow_version": "1.2.0",
  "input": {},
  "retrieved_sources": [],
  "output": {},
  "constraints_triggered": [],
  "human_feedback": {}
}
```

### 输出示例

```json
{
  "run_id": "run_123",
  "score": 0.87,
  "risk_level": "medium",
  "findings": [
    {
      "type": "citation_gap",
      "severity": "medium",
      "message": "有一处法律判断缺少引用来源。"
    }
  ],
  "suggestions": [
    {
      "target": "retrieval_strategy",
      "recommendation": "优先检索公司条款库，再检索外部法规库。"
    }
  ],
  "passed": false
}
```

## 推荐接口

前期建议只做三个接口：

```http
POST /evaluation/run
GET /evaluation/reports/{run_id}
POST /evaluation/batch
```

后续再增加：

```http
POST /evaluation/suggestions/promote
POST /evaluation/evalsets/generate
POST /evaluation/compare
```

其中 `promote` 也只是提交候选改进，不能直接改生产配置。

## 运行时观测

每次工作流执行建议记录：

- 用户输入、行业场景、角色、地区
- 检索到的资料、引用片段、资料版本
- 模型输出、工具调用、人工修改
- 触发的约束规则、拒答原因、风险等级
- 用户反馈、审批结果、最终采用版本

这些数据可以作为动态评估集和质量分析的基础。

## 动态评估集

评估集不应只靠人工手写，而应从真实任务中持续沉淀：

- 高频问题自动进入回归测试
- 人工大幅修改的输出进入缺陷样本
- 被拒绝、升级、投诉的案例进入风险样本
- 新法规、新政策发布后自动生成专项测试
- 行业专家定期标注“黄金答案”或评分标准

## 多维评分体系

动态评估不只评估“答得像不像”，而是按工作流目标评分：

- 事实准确率：是否基于资料回答，是否引用正确
- 约束合规率：是否遵守行业、地区、组织规则
- 流程完成率：是否完成必要步骤
- 风险识别率：是否识别高风险事项
- 可用性评分：人工修改幅度、采纳率、用户满意度
- 稳定性评分：同类输入多次运行是否一致
- 成本/延迟评分：是否值得在该场景使用更强模型

## 进化机制

进化不要直接“让模型自己改自己”，而是走受控发布流程：

1. 自动发现问题：从日志、反馈、失败案例中聚类。
2. 自动提出改进：建议更新 prompt、约束规则、检索策略、模板或工具流程。
3. 沙箱验证：用动态评估集回归测试。
4. 人工审批：行业专家或平台管理员确认。
5. 灰度发布：只对部分团队或低风险场景启用。
6. 回滚机制：新版本表现下降时自动退回。

## 版本治理

每个行业包都应该记录：

- `workflow_version`
- `prompt_version`
- `constraint_pack_version`
- `knowledge_base_version`
- `model_version`
- `eval_set_version`
- `evaluator_version`

这样可以追踪某次输出到底是由哪套资料、哪套规则、哪个模型和哪套评估逻辑产生的。

## 可进化对象

不要只优化 prompt。建议将平台的进化对象拆成几类：

```yaml
evolution_targets:
  - prompts
  - workflow_steps
  - constraint_rules
  - retrieval_strategy
  - knowledge_base_metadata
  - output_templates
  - tool_permissions
  - model_routing
```

这样平台可以更准确地判断问题来源：

- 答错事实：可能是检索或资料问题。
- 格式混乱：可能是输出 schema 问题。
- 风险漏掉：可能是约束规则或测试集问题。
- 成本太高：可能是模型路由问题。
- 用户总修改同一段：可能是模板或行业风格问题。

## 实施阶段

建议将该部分作为平台的最后实施阶段。

```text
阶段 4：动态评估与进化层

目标：
让平台能够基于真实使用数据持续发现问题、验证改进、灰度发布和回滚。

核心能力：
- 全链路日志与审计
- 动态评估集生成
- 行业专家标注台
- 自动回归测试
- 约束规则与 prompt 版本管理
- A/B 测试与灰度发布
- 质量仪表盘
- 自动回滚机制

关键指标：
- 引用准确率
- 约束合规率
- 人工修改率
- 输出采纳率
- 高风险漏检率
- 投诉/升级率
- 平均任务完成时间
- 单任务成本
```

## 总结

动态评估与进化层可以作为独立的“AI 质量评估服务”。主平台只需要向它提供运行快照，它只返回结构化评估结果和改进建议。

前期可以晚做完整能力，但日志、版本号、反馈入口和运行快照格式必须从第一版就预留好。
