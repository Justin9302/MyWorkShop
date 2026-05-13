# 新能源项目分析工作流 — 实施方案

## 0. 最高原则

- **通用型财务模型**：不依赖 Excel 文件，通过加载生成的项目参数文件和约束文件实现计算
- **项目文件统一管理**：所有项目文件统一保存在 `OUTPUT/<项目名>/` 目录下
- **多层模块化组装**：Python 代码在生成时，意图分析后进行多层模块化组装，避免生成一个巨大的文件。通过多层模块组装，让文件尽量保持小巧，方便审核
- **地域可扩展**：可根据用户提供扩展到不同国家地区。当用户提示的国家不在过往记录中时，创建对应国家的约束及相应的数据，并且确保数据小于 90 天的历史有效期内
- **技术方案可配置**：通用型，支持光伏/风电/储能/光储混合/VPP/充电桩等

## 1. 整体架构

```
# ── 通用引擎（所有项目共享，仅维护一处） ──
scripts/financial_model_engine.py   # 通用型财务模型引擎

# ── 项目文件（每个项目独立，仅包含参数配置） ──
OUTPUT/<项目名>/
├── project_config.yaml          # 项目参数配置文件（唯一输入）
├── constraints/                 # 项目级约束（国家/地区/行业）
├── outputs/                     # 引擎输出（JSON + Markdown 报告）
│   ├── financial_results.json   # 结构化财务分析结果
│   ├── financial_summary.md     # 可读的财务摘要报告
│   ├── parameter_validation_report.md  # 参数校验报告
│   └── final_report.md          # 完整项目分析报告
└── run_snapshot.json            # 运行快照
```

### 核心设计原则

- **通用型财务模型引擎**：所有项目共享 `scripts/financial_model_engine.py`，不生成项目特定的硬编码 Python 模块
- **参数配置驱动**：每个项目仅生成 `project_config.yaml`，引擎通过读取该文件加载边界条件
- **引擎职责**：加载参数 → 构建现金流模型 → 计算 IRR/NPV/回收期/LCOE/DSCR → 运行多情景分析 → 运行敏感性分析 → 输出结构化结果
- **扩展方式**：如需新增功能（如税务计算、碳信用收入），只需修改 `financial_model_engine.py` 一处

## 2. 工作流设计（Lattice 分解）

### Layer 4（核心层）：项目参数与边界定义

| 任务 ID  | 名称         | 描述                                 |
| -------- | ------------ | ------------------------------------ |
| task_001 | 项目范围定义 | 技术方案/规模/地点/阶段/用户目标确认 |
| task_002 | 边界条件确认 | 资源/接入/许可/土地条件确认          |
| task_003 | 参数基线建立 | CAPEX/OPEX/电价/融资参数确认         |

### Layer 3：技术分析层

| 任务 ID  | 名称           | 描述                                  |
| -------- | -------------- | ------------------------------------- |
| task_004 | 资源评估       | 太阳能/风能资源、容量因子、发电量估算 |
| task_005 | 技术方案比选   | 设备选型、系统设计、效率分析          |
| task_006 | 并网与接入分析 | 接入条件、电网约束、MLF 估算          |

### Layer 2：经济分析层

| 任务 ID  | 名称         | 描述                           |
| -------- | ------------ | ------------------------------ |
| task_007 | 财务模型搭建 | 现金流模型、IRR/NPV/回收期计算 |
| task_008 | 收入模型构建 | 市场/PPA/补贴/辅助服务收入     |
| task_009 | 融资结构设计 | 杠杆率、偿债覆盖率、融资方案   |

### Layer 1：风险与敏感分析层

| 任务 ID  | 名称       | 描述                     |
| -------- | ---------- | ------------------------ |
| task_010 | 敏感性分析 | 关键参数敏感性、龙卷风图 |
| task_011 | 情景分析   | 保守/基准/乐观场景       |
| task_012 | 风险评估   | 风险识别、评级、缓解措施 |

### Layer 0（外层）：报告与决策层

| 任务 ID  | 名称         | 描述                       |
| -------- | ------------ | -------------------------- |
| task_013 | 分析报告生成 | 结构化报告、图表嵌入       |
| task_014 | 投资建议     | 结论、下一步行动、人审门禁 |

## 3. 实施步骤

### Phase 1：工作流定义（当前阶段）

| #   | 任务                  | 产出                                                       | 说明               |
| --- | --------------------- | ---------------------------------------------------------- | ------------------ |
| 1.1 | 创建 Lattice 方案文件 | `lattice/examples/energy/lattice_new_energy_analysis.yaml` | 顶层分解方案       |
| 1.2 | 创建工作流 YAML       | `workflows/energy/new_energy_project_analysis.yaml`        | 符合平台标准       |
| 1.3 | 创建 System Prompt    | `prompts/energy/new_energy_project_analysis.system.md`     | 角色定义与行为规范 |
| 1.4 | 创建国家约束模板      | `constraints/countries/_template.yaml`                     | 国家约束模板       |
| 1.5 | 创建国家数据模板      | `data/market_reference_index.yaml`                         | 市场参考数据索引   |
| 1.6 | 注册到 Release        | 更新 `active-release.yaml`                                 | 版本治理           |
| 1.7 | 创建测试案例          | `tests/eval_cases/synthetic/`                              | 合成测试数据       |

### Phase 2：Python 模块实现（后续阶段）

| #   | 任务           | 产出                                      | 说明                       |
| --- | -------------- | ----------------------------------------- | -------------------------- |
| 2.1 | 模块框架生成器 | `scripts/new_energy_project_generator.py` | 根据项目配置生成模块化代码 |
| 2.2 | 资源评估模块   | 模板代码                                  | 太阳能/风能资源计算        |
| 2.3 | 技术分析模块   | 模板代码                                  | 技术方案比选               |
| 2.4 | 财务模型模块   | 模板代码                                  | 现金流/IRR/NPV             |
| 2.5 | 市场分析模块   | 模板代码                                  | 市场/PPA/补贴              |
| 2.6 | 风险评估模块   | 模板代码                                  | 敏感性/情景分析            |
| 2.7 | 报告生成模块   | 模板代码                                  | 结构化报告                 |

## 4. 文件清单

### 新建文件

```
workflows/energy/new_energy_project_analysis.yaml
prompts/energy/new_energy_project_analysis.system.md
lattice/examples/energy/lattice_new_energy_analysis.yaml
constraints/countries/_template.yaml
data/market_reference_index.yaml
tests/eval_cases/synthetic/run_snapshot_new_energy_001.json
```

### 修改文件

```
config/active-release.yaml
```

## 5. 质量标准

- 每个工作流 YAML 必须通过 `workflow.schema.json` 校验
- 每个约束包必须标注版本号和生效日期
- 国家数据必须标注数据来源和获取日期
- 所有文件必须符合平台 Git 边界标准
- 高风险步骤必须有人审节点
- 中断点必须定义恢复条件和取消条件
  </docs/new_energy_project_analysis_plan.md>
  </write_to_file>
