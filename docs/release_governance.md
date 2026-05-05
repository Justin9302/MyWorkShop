# Release Governance — 版本治理规范

> 版本: 0.1.0 | 关联: Phase 6 | 状态: draft

---

## 1. 概述

本文档定义 AI Work Platform 的**版本治理、发布管理与回滚机制**。所有平台资产（工作流、约束、prompt、schema、评估器、配置）的版本变更均应遵循本规范。

### 核心原则

1. **可追溯** — 每个 release 对应一个 Git tag，所有组件版本精确记录在 Manifest 中
2. **可回滚** — 任何 release 均可通过 Git 回退 + 组件一致性验证恢复
3. **可审计** — 每次版本晋升/回滚均记录时间、操作人和原因
4. **兼容性声明** — 每个 release 声明组件间兼容性关系

---

## 2. 版本号规范

采用 **SemVer 2.0** (`主版本.次版本.修订号`) 原则，各组件独立版本管理：

| 组件标识                  | 示例       | 递增触发条件                        |
| ------------------------- | ---------- | ----------------------------------- |
| `workflow_version`        | `0.1.0`    | 工作流逻辑、步骤、输入/输出定义变更 |
| `constraint_pack_version` | `0.4.0`    | 约束规则新增/修改/废弃              |
| `prompt_version`          | `0.1.0`    | System prompt 模板内容变更          |
| `evaluator_version`       | `0.1.0`    | 评估规则、量规或评分逻辑变更        |
| `knowledge_base_version`  | `kb_0.2.0` | 知识库引用数据更新                  |

> **0.x.y 阶段**: 平台建设期，次版本变更可能不向后兼容。
> **1.0.0 之后**: 遵循严格 SemVer，主版本变更需发布公告。

---

## 3. Release 生命周期

```
                  ┌──────────┐
                  │  Draft   │ ◄── 开发中，可任意修改
                  └────┬─────┘
                       │ promote (review)
                       ▼
                  ┌──────────┐
                  │  Review  │ ◄── 冻结修改，进行验证
                  └────┬─────┘
                       │ approve / promote
                       ▼
                  ┌───────────┐
                  │ Published │ ◄── 已打 Git tag，不可变
                  └─────┬─────┘
                        │ supersede
                        ▼
                  ┌────────────┐
                  │ Deprecated │ ◄── 被新 release 取代
                  └─────┬──────┘
                        │ emergency revert
                        ▼
                  ┌─────────────┐
                  │ Rolled Back │ ◄── 紧急回退到上一个 Published
                  └─────────────┘
```

### 3.1 Draft（草稿）

- 开发中的 release，组件可任意修改
- 所有变更记录在 `CHANGELOG.md` 的 `[Unreleased]` 区
- 不要求完整的 Schema 验证通过

### 3.2 Review（审查）

- 代码冻结，只允许修复性修改
- 必须通过所有 Schema 验证
- 必须通过回归测试
- 必须生成完整的 `release_manifest` 并验证格式

### 3.3 Published（已发布）

- 打 Git tag（格式: `release_YYYY_MM_DD_NNN`）
- Manifest 不可修改（immutable snapshot）
- 组件版本在该 release 范围内视为锁定

### 3.4 Deprecated（已废弃）

- 被后续 release 取代
- 标记为 deprecated 后仍可回滚到该 release

### 3.5 Rolled Back（已回滚）

- 从失败的 release 紧急回退到上一个 Published release
- 回滚后需执行组件一致性验证
- 记录回滚原因供事后复盘

---

## 4. 发布晋升流程

### 4.1 晋升条件 (Draft → Review)

- [ ] CHANGELOG.md 中 `[Unreleased]` 区填写完整
- [ ] 所有新增/修改的 YAML/JSON 文件通过对应 Schema 验证
- [ ] 无未解决的 Git 冲突
- [ ] `active-release.yaml` 中的版本号与 Manifest 一致

### 4.2 晋升条件 (Review → Published)

- [ ] 通过所有回归测试
- [ ] 评估运行通过（如有评估旁路）
- [ ] 获得至少 1 人审核批准
- [ ] Git 工作区干净（无未提交修改）
- [ ] Release Manifest 经过 `release_manifest.schema.json` 验证

### 4.3 晋升条件 (Published → Deprecated)

- [ ] 新 release 已成功 Published
- [ ] 迁移指引已就绪

---

## 5. 回滚 SOP

### 5.1 触发条件

- 新 release 导致工作流运行失败
- 约束规则误触发
- Prompt 模板输出质量严重下降
- 评估器产生大量误报/漏报

### 5.2 回滚步骤

```bash
# 步骤 1: 确认回滚目标
git tag --list 'release_*'  # 列出所有 release

# 步骤 2: 执行回滚
scripts/rollback.sh release_2026_05_05_001

# 步骤 3: 验证组件一致性
# 脚本自动执行:
#   - Git 恢复到目标 release 的 commit
#   - 检查 active-release.yaml 与 target release 版本一致
#   - 检查所有组件文件存在且匹配版本号

# 步骤 4: 确认运行正常
# 手动运行一个测试工作流验证
```

### 5.3 回滚后处理

- 在失败 release 的 Manifest 中记录 `rollback` 字段
- 创建 Fix release 修正问题后重新发布
- 事后复盘：什么原因导致需要回滚？如何防止再次发生？

---

## 6. 文件规范

### 6.1 Release Manifest 位置

```
config/releases/
  release_YYYY_MM_DD_NNN.yaml    # 正式发布清单
  .gitkeep
```

### 6.2 Manifest 模板

每个 release 创建时复制 `schemas/release_manifest.schema.json` 作为参考，确保 YAML 文件结构符合 Schema 定义。

### 6.3 CHANGELOG 格式

遵循 [Keep a Changelog](https://keepachangelog.com/) 规范：

```markdown
# Changelog

## [Unreleased]

### Added

- 新功能/新组件

### Changed

- 现有组件修改

### Deprecated

- 即将废弃的组件

### Removed

- 已移除的组件

### Fixed

- 问题修复

### Security

- 安全修复

## [release_2026_05_05_001] - 2026-05-05

### Added

- 初始版本
```

---

## 7. 角色与责任

| 角色       | 职责                                               |
| ---------- | -------------------------------------------------- |
| **维护者** | 管理 release 晋升流程，审核变更，打 Git tag        |
| **贡献者** | 提交组件变更，更新 CHANGELOG，确保 Schema 验证通过 |
| **审核者** | Review → Published 阶段审核变更内容                |
| **系统**   | 自动执行 Schema 验证、回归测试、版本一致性检查     |

---

## 8. 与现有机制的关系

| 现有资产                     | 与本规范的关系                                          |
| ---------------------------- | ------------------------------------------------------- |
| `config/active-release.yaml` | 运行时指针 — 指向当前活跃的 release，由晋升脚本自动更新 |
| `config/releases/*.yaml`     | 正式 Manifest 存储，每个 release 一个文件               |
| `docs/gitman.md`             | Git 边界原则 — 本规范是其版本治理层面的具体实现         |
| `CHANGELOG.md`               | 变更的人类可读摘要                                      |
| Git tag (`release_*`)        | 不可变的发布快照                                        |
