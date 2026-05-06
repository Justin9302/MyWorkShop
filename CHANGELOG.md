# Changelog

所有对本平台的显著变更均记录在此文件。

格式基于 [Keep a Changelog](https://keepachangelog.com/)，
版本号遵循 [SemVer](https://semver.org/)。

---

## [Unreleased]

### Added

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
