# Changelog

所有对本平台的显著变更均记录在此文件。

格式基于 [Keep a Changelog](https://keepachangelog.com/)，
版本号遵循 [SemVer](https://semver.org/)。

---

## [Unreleased]

### Added

- Lattice 框架：结构化任务分解与执行引擎
  - `lattice/schemas/` — Lattice、AtomicTask、LayerAssembly、Blocker、PDCA Cycle Schema
  - `lattice/templates/` — 模板文件（lattice、atomic_task、layer_assembly）
  - `lattice/scripts/` — 核心引擎（lattice_core.py、lattice_blocker.py、lattice_pcdca.py、lattice_runner.py）
  - `lattice/workflows/` — 工作流定义（lattice、pcdca、blocker）
  - `lattice/examples/` — 示例（量化交易、软件设计、商业模式、贪吃蛇游戏）
  - `lattice/README.md` — 框架文档
- Phase 7e: 灰度发布管理
  - `scripts/rollout_manager.py` — 灰度发布管理器
  - `config/rollout-policy.yaml` — 灰度发布策略配置
  - `tests/phase7e/test_rollout_manager.py` — 测试套件
- Phase 7f: 仪表盘与监控
  - `scripts/dashboard.py` — 仪表盘脚本
  - `config/dashboard-config.yaml` — 仪表盘配置
  - `tests/phase7f/test_dashboard.py` — 测试套件
- Phase 8: 工作流编排引擎（补充）
  - `scripts/workflow_runner.py` — 工作流编排引擎
  - `scripts/workflow_status_indicator.py` — 状态指示器
  - `config/session-tracking.yaml` — 会话追踪配置
  - `tests/phase8/test_workflow_runner.py` — 测试套件（42 项）
- Phase 9: 中断处理（补充）
  - `scripts/interruption_handler.py` — 中断处理核心脚本
  - `tests/phase9/test_interruption_handler.py` — 测试套件（63 项）
- 通用工作流与提示词
  - `workflows/general/ideation_convergence.yaml` — 创意收敛工作流
  - `prompts/general/ideation_convergence.system.md` — 创意收敛 system prompt
  - `evaluators/rubrics/ideation_convergence.yaml` — 创意收敛评估量规
- 文档补充
  - `docs/user_profile.md` — 用户画像文档
  - `docs/workspace_usage_guide.md` — 工作空间使用指南
- 评估样本补充
  - `tests/eval_cases/synthetic/run_snapshot_sample_001_eval.json`
  - `tests/eval_cases/synthetic/run_snapshot_sample_002_eval.json`

### Changed

- `.github/copilot-instructions.md` — 大幅更新 Copilot 指令
- `config/active-release.yaml` — 更新组件注册（workflow_runner、interruption_handler、rollout_manager、dashboard 等）
- `config/interruption-policy.yaml` — 从 draft 升级为正式版 v0.2.0
- `constraints/baseline/human_review.yaml` — 添加中断触发规则
- `scripts/llm_judge.py` — 小幅优化
- `scripts/validate_interruption_flow.sh` — 扩展验证覆盖
- `docs/evaluation_sidecar.md` — 文档微调
- `README.md` — 更新项目说明

### Fixed

- `.gitignore` — 排除 `lattice/lattice_runtime/` 运行态数据

- Phase 6: 版本治理体系
  - `schemas/release_manifest.schema.json` — 发布 Manifest Schema
  - `config/releases/` — 正式 Release 清单目录
  - `config/releases/release_2026_05_05_001.yaml` — 当前 release 的完整 Manifest
  - `docs/release_governance.md` — 版本治理规范文档
  - `CHANGELOG.md` — 本变更日志
  - `scripts/release_promote.sh` — 发布晋升脚本 (draft→review→published)
  - `scripts/rollback.sh` — 回滚验证脚本
- `active-release.yaml`: 增加 lifecycle 字段、release_manifest 引用

- Phase 7a: LLM-as-Judge 评估引擎升级
  - `scripts/llm_judge.py` — LLM 评判封装模块 (judge_criterion 核心接口)
  - `prompts/evaluation/llm_judge.system.md` — LLM-as-Judge system prompt
  - `evaluators/rubrics/shared_judge_config.yaml` — 评判行为配置
  - `eval_runner.py`: 新增 --judge-mode 参数 (heuristic/llm/hybrid)
  - `eval_report.schema.json`: 新增 llm_reasoning/confidence 字段
  - 39 项自动化测试全部通过

- Phase 7b: 动态评估集沉淀
  - `scripts/eval_set_manager.py` — 评估集管理器 (自动分类/去重/标注)
  - `schemas/eval_set.schema.json` — 评估集 Schema
  - `config/eval-set-config.yaml` — 自动分类规则配置
  - 5 个评估样本目录 (golden/regression_failures/human_corrected/risk_samples/baseline)
  - 30 项自动化测试全部通过

- Phase 7c: 改进建议 → 候选变更管线
  - `schemas/candidate_change.schema.json` — 候选变更 Schema (8 必填字段)
  - `scripts/promote_suggestion.py` — 建议提升为候选变更脚本 (CLI: create/list/approve/reject)
  - `runtime/candidate_changes/.gitkeep` — 候选变更存储目录
  - 43 项自动化测试全部通过
- `active-release.yaml`: Stage 更新为 stage_7_dynamic_evolution，注册 judge 组件、eval_set 组件、candidate_change 组件
- `.gitignore`: 排除 runtime/candidate_changes/, outputs/dashboard/, outputs/eval_reports/regression/

- Phase 8: 工作流编排引擎
  - `scripts/workflow_runner.py` — 工作流编排引擎 (run/list/status/interrupt/resume/checkpoint)
  - `schemas/workflow.schema.json` — 工作流 Schema
  - `config/context-loading.yaml` — 上下文加载策略配置
  - `config/interruption-policy.yaml` — 中断策略配置 (draft)
  - `config/model-routing.yaml` — 模型路由配置
  - `config/permissions.yaml` — 权限配置
  - `config/rollout-policy.yaml` — 灰度发布策略
  - `config/feature-flags.yaml` — 功能开关配置
  - `config/dashboard-config.yaml` — 仪表盘配置
  - `tests/phase8/test_workflow_runner.py` — 工作流编排引擎测试 (42 项)
  - 42 项自动化测试全部通过

- Phase 9: 中断、补充、恢复与用户运行控制
  - `scripts/interruption_handler.py` — 中断处理核心脚本 (CLI: create-interruption/process-resume/validate-resume/create-checkpoint/update-snapshot)
  - `config/interruption-policy.yaml` — 从 draft 升级为正式版 v0.2.0
  - `constraints/baseline/human_review.yaml` — 添加中断触发规则 (interruption_trigger: true)
  - `scripts/workflow_runner.py` — 新增 interrupt/resume/checkpoint 子命令
  - `scripts/validate_interruption_flow.sh` — 9 项全面验证脚本
  - `tests/phase9/test_interruption_handler.py` — 中断处理测试套件 (63 项)
  - 所有 14 个工作流 YAML 已定义中断节点
  - 63 项自动化测试全部通过

---

## [release_2026_05_05_001] - 2026-05-05

### Added

- 初始平台创建工作区
- Stage 1: 工作区骨架与 Git 边界 (`.gitignore`, `README.md`, `docs/`)
- Stage 2: 核心平台配置 + 12 行业工作流 + 12 system prompt
- Stage 3: 约束包 — 6 基线 + 5 行业 + 4 地区
- Stage 4: 运行快照 & 审计日志 Schema + 评估规则
- Stage 5: 评估旁路服务 — `eval_runner.py` + API 契约 + 合成测试快照
- 三 Agent 编排体系: `task-planner` + `task-reviewer`
- Copilot 指令迁移: `.github/copilot-instructions.md`
- 能源行业约束包扩展 + 中国电力监管约束

### Notes

- 此 release 为初始草稿版本，包含前 5 个阶段的全部资产
- 组件版本: workflow 0.1.0 / constraint 0.4.0 / prompt 0.1.0 / evaluator 0.1.0 / kb_0.2.0
- Phase 6（本 changelog）在此 release 基础上实施
