# MCP 工具待建清单与实施方案

> 版本: 0.1.0
> 更新日期: 2026-05-22
> 状态: 规划中（待评审后实施）

---

## 一、背景

当前工作环境已配置 8 个 MCP 服务器，覆盖通用基础设施（filesystem、fetch、git、github）、金融计算（financial-calculator）、市场数据（market-data）、数据可视化（data-viz）、PDF 解析（pdf-parser）和数据库查询（database-query）。

然而，部分领域技能（Skills）缺乏专用 MCP 工具支持，且所有计算结果均需严格验证后方可投入生产环境。本文档列出待建 MCP 工具清单及与现有 Skills/Workflows 的关联关系。

---

## 二、待建 MCP 工具清单

### P0 — 高优先级（影响核心工作流）

| #   | 工具名称                    | 领域     | 功能描述                                                        | 关联 Skill                                      | 关联 Workflow                                             | 验证要求                                             |
| --- | --------------------------- | -------- | --------------------------------------------------------------- | ----------------------------------------------- | --------------------------------------------------------- | ---------------------------------------------------- |
| 1   | `business-model-calculator` | Business | 单位经济模型计算器：CAC/LTV/回收期/毛利率/盈亏平衡点/敏感性分析 | unit_economics_check, business_model_validation | unit_economics_check.yaml, business_model_validation.yaml | 每个指标需与行业基准交叉验证，输出置信区间而非单点值 |
| 2   | `market-sizing`             | Business | 市场规模估算：TAM/SAM/SOM 计算、市场增长率预测、竞争份额分析    | business_model_design, go_to_market_review      | business_model_design.yaml, go_to_market_review.yaml      | 需标注数据来源和估算方法（Top-down vs Bottom-up）    |
| 3   | `compliance-checker`        | Legal    | 合规检查引擎：法域规则匹配、合规差距评分、监管变更追踪          | policy_qa, contract_review                      | policy_qa.yaml, contract_review.yaml                      | 每条合规规则需可追溯至具体法条，输出需人工复核       |

### P1 — 中优先级（提升效率）

| #   | 工具名称                  | 领域            | 功能描述                                                    | 关联 Skill                  | 关联 Workflow                         | 验证要求                               |
| --- | ------------------------- | --------------- | ----------------------------------------------------------- | --------------------------- | ------------------------------------- | -------------------------------------- |
| 4   | `risk-matrix-engine`      | Finance/General | 风险矩阵计算器：影响×概率评分、风险热力图生成、风险聚合计算 | risk_summary, due_diligence | risk_summary.yaml, due_diligence.yaml | 评分方法需文档化，支持自定义权重       |
| 5   | `contract-clause-library` | Legal           | 合同条款库：标准条款模板、风险条款模式匹配、缺失条款检测    | contract_review             | contract_review.yaml                  | 条款库需定期更新，匹配结果需标注置信度 |
| 6   | `country-data-query`      | Country         | 国家数据查询：经济指标/法律体系/营商环境/风险评级           | country_report              | country_report.yaml                   | 数据需标注时效性，过期数据需警告       |

### P2 — 低优先级（锦上添花）

| #   | 工具名称                 | 领域       | 功能描述                                                           | 关联 Skill           | 关联 Workflow             | 验证要求                       |
| --- | ------------------------ | ---------- | ------------------------------------------------------------------ | -------------------- | ------------------------- | ------------------------------ |
| 7   | `meeting-action-tracker` | Operations | 会议行动项追踪：行动项提取、负责人分配、截止日期提醒、完成状态追踪 | meeting_summary      | meeting_summary.yaml      | 行动项提取需人工确认           |
| 8   | `decision-log`           | General    | 决策记录器：决策树记录、方案评分历史、决策回溯分析                 | ideation_convergence | ideation_convergence.yaml | 每次决策需记录上下文和评分依据 |

---

## 三、需同步更新的 Skill 与 Workflow 清单

以下 Skills 和 Workflows 在新增 MCP 工具后需要同步更新：

### 3.1 Prompt 文件更新（需添加"可用 MCP 工具"章节）

| Skill ID                    | 当前 Prompt 路径                                     | 当前状态  | 需新增的工具引用 |
| --------------------------- | ---------------------------------------------------- | --------- | ---------------- |
| business_model_design       | prompts/business/business_model_design.system.md     | ✅ 已更新 | —                |
| business_model_validation   | prompts/business/business_model_validation.system.md | ✅ 已更新 | —                |
| go_to_market_review         | prompts/business/go_to_market_review.system.md       | ✅ 已更新 | —                |
| unit_economics_check        | prompts/business/unit_economics_check.system.md      | ✅ 已更新 | —                |
| new_energy_project_analysis | prompts/energy/new_energy_project_analysis.system.md | ✅ 已更新 | —                |
| research_summary            | prompts/finance/research_summary.system.md           | ✅ 已更新 | —                |
| risk_summary                | prompts/finance/risk_summary.system.md               | ✅ 已更新 | —                |
| due_diligence               | prompts/finance/due_diligence.system.md              | ✅ 已更新 | —                |
| contract_review             | prompts/legal/contract_review.system.md              | ✅ 已更新 | —                |
| policy_qa                   | prompts/legal/policy_qa.system.md                    | ✅ 已更新 | —                |
| sop_generation              | prompts/operations/sop_generation.system.md          | ✅ 已更新 | —                |
| meeting_summary             | prompts/operations/meeting_summary.system.md         | ✅ 已更新 | —                |
| project_retrospective       | prompts/operations/project_retrospective.system.md   | ✅ 已更新 | —                |
| ideation_convergence        | prompts/general/ideation_convergence.system.md       | ✅ 已更新 | —                |
| country_report              | prompts/country/country_report.system.md             | ✅ 已更新 | —                |
| llm_judge                   | prompts/evaluation/llm_judge.system.md               | ✅ 已更新 | —                |

### 3.2 Workflow 文件更新（需添加 MCP 工具调用步骤）

| Workflow ID                 | 当前 Workflow 路径                                | 当前状态  | 需新增的步骤                                            |
| --------------------------- | ------------------------------------------------- | --------- | ------------------------------------------------------- |
| unit_economics_check        | workflows/business/unit_economics_check.yaml      | ⏳ 待更新 | 在 steps 中添加"调用 financial-calculator 验证指标"     |
| business_model_validation   | workflows/business/business_model_validation.yaml | ⏳ 待更新 | 在 steps 中添加"调用 financial-calculator 验证单位经济" |
| due_diligence               | workflows/finance/due_diligence.yaml              | ⏳ 待更新 | 在 steps 中添加"调用 financial-calculator 计算财务指标" |
| new_energy_project_analysis | workflows/energy/new_energy_project_analysis.yaml | ⏳ 待更新 | 在 steps 中添加"调用 market-data 获取市场数据"          |

### 3.3 Governance 文件更新

| 文件路径                   | 当前状态  | 更新内容                                             |
| -------------------------- | --------- | ---------------------------------------------------- |
| config/mcp-tools.yaml      | ✅ 已更新 | 注册所有实际 MCP 服务器，添加 associated_skills 映射 |
| config/active-release.yaml | ⏳ 待更新 | 更新 mcp_tools 版本号引用                            |
| prompt_manifest.yaml       | ⏳ 待更新 | 更新 prompt 版本号和 target_model                    |

---

## 四、实施方案

### 阶段 1：基础治理同步（当前已完成 ✅）

- [x] 更新 `config/mcp-tools.yaml` — 注册所有实际 MCP 服务器
- [x] 更新所有 `prompts/*.system.md` — 添加"可用 MCP 工具"章节

### 阶段 2：Workflow 集成（预计 1-2 天）

- [ ] 更新 `workflows/business/unit_economics_check.yaml` — 添加 financial-calculator 调用步骤
- [ ] 更新 `workflows/business/business_model_validation.yaml` — 添加 financial-calculator 调用步骤
- [ ] 更新 `workflows/finance/due_diligence.yaml` — 添加 financial-calculator 调用步骤
- [ ] 更新 `workflows/energy/new_energy_project_analysis.yaml` — 添加 market-data 调用步骤

### 阶段 3：P0 工具开发（预计 1-2 周）

- [ ] 设计 `business-model-calculator` 的输入/输出规范
- [ ] 开发 `business-model-calculator` MCP 服务器（参考 financial-calculator 架构）
- [ ] 编写单元测试和集成测试
- [ ] 设计 `market-sizing` 的输入/输出规范
- [ ] 开发 `market-sizing` MCP 服务器
- [ ] 编写单元测试和集成测试
- [ ] 设计 `compliance-checker` 的输入/输出规范
- [ ] 开发 `compliance-checker` MCP 服务器
- [ ] 编写单元测试和集成测试

### 阶段 4：验证与发布（预计 3-5 天）

- [ ] 对每个新 MCP 工具进行沙箱测试
- [ ] 使用 eval_set 进行回归测试
- [ ] 更新 `config/active-release.yaml` 发布新版本
- [ ] 更新 `docs/workspace_usage_guide.md` 添加工具使用说明

### 阶段 5：P1-P2 工具规划（持续）

- [ ] 根据使用反馈调整 P1/P2 工具优先级
- [ ] 制定详细的开发计划

---

## 五、验证策略

由于所有计算结果均需严格验证后方可投入生产环境，建议采用以下验证策略：

### 5.1 计算验证

- **交叉验证**：每个计算结果需至少与一个独立数据源或行业基准进行交叉验证
- **置信区间**：输出必须包含置信区间或不确定性范围，而非单点值
- **敏感性分析**：关键指标必须附带敏感性分析结果

### 5.2 数据验证

- **数据溯源**：所有外部数据必须标注来源和获取时间
- **时效性检查**：过期数据（>90天）需标注警告
- **异常检测**：超出正常范围的数据需自动标记

### 5.3 人工审核

- **高风险标记**：涉及投资决策、法律合规、重大财务影响的计算结果必须标记为"需人工审核"
- **审核记录**：所有人工审核操作需记录在审计日志中

---

## 六、关联文档

| 文档           | 路径                            | 说明                   |
| -------------- | ------------------------------- | ---------------------- |
| MCP 工具注册表 | config/mcp-tools.yaml           | MCP 工具治理核心索引   |
| MCP 配置       | cline_chinese_mcp_settings.json | 实际 MCP 服务器配置    |
| 活跃版本       | config/active-release.yaml      | 当前发布版本与组件清单 |
| 提示词清单     | prompts/prompt_manifest.yaml    | 提示词版本管理与元数据 |
| 工作流引擎     | scripts/workflow_runner.py      | 工作流编排引擎         |
| 评估系统       | docs/evaluation_sidecar.md      | 评估架构文档           |
