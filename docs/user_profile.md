# 用户配置文件 (User Profile)

> 此文件用于记录用户的工作习惯、偏好和项目上下文，帮助 AI 助手在跨对话中保持一致的理解。
> 请根据实际情况更新此文件。

---

## 基本信息

- **用户**: Justin9302 (GitHub)
- **工作区**: Workspace_1
- **项目类型**: Codex AI 辅助工作流系统
- **主要语言**: Python, YAML, Shell
- **关联仓库**: `git@github.com:Justin9302/MyWorkShop.git`

---

## 工作习惯与偏好

### 沟通风格

- [ ] 偏好详细的技术说明
- [ ] 偏好简洁直接的回复
- [x] 希望 AI 主动提供选项供选择
- [ ] 其他: **\*\***\_\_\_\_**\*\***

### 代码风格

- **Python**: PEP 8 标准
- **YAML**: 2 空格缩进
- **Shell**: 使用 `bash`，包含错误处理
- **命名规范**: snake_case (Python), kebab-case (YAML 文件)

### 工作流

- [x] 喜欢分步骤执行，每步确认结果
- [x] 偏好 AI 主动探索项目结构后再行动
- [x] 希望 AI 在修改前先展示计划
- [ ] 其他: **\*\***\_\_\_\_**\*\***

---

## 常用工具与命令

| 用途       | 命令                                                       |
| ---------- | ---------------------------------------------------------- |
| 运行工作流 | `python scripts/workflow_runner.py <workflow-path>`        |
| 运行评估   | `python scripts/eval_runner.py --workflow <workflow-path>` |
| 回归测试   | `python scripts/regression_test.py`                        |
| 启动仪表盘 | `python scripts/dashboard.py`                              |
| 发布新版本 | `bash scripts/release_promote.sh`                          |
| 回滚       | `bash scripts/rollback.sh`                                 |

---

## 项目关键路径速查

| 路径           | 说明                        |
| -------------- | --------------------------- |
| `workflows/`   | 各领域工作流定义 (YAML)     |
| `scripts/`     | 核心执行脚本 (Python/Shell) |
| `evaluators/`  | 评估规则和评分标准          |
| `config/`      | 系统配置                    |
| `constraints/` | 约束规则                    |
| `prompts/`     | 系统提示词                  |
| `schemas/`     | JSON Schema 和 OpenAPI 定义 |
| `tests/`       | 测试用例                    |
| `docs/`        | 文档                        |

---

## 会话历史摘要

> 每次重要会话结束后，在此记录关键决策和进展。

### 2026-05-08: 建立跨对话记忆系统

- **内容**: 创建了 `docs/user_profile.md` 和 `config/session-tracking.yaml`
- **决策**: 建立用户配置 + 会话跟踪的双重记录系统
- **状态**: ✅ 完成

---

## 偏好设置

### AI 助手行为

- [x] 使用工具前先分析项目结构
- [x] 分步骤执行任务
- [x] 提供清晰的进度跟踪
- [ ] 自动执行无需确认（高风险操作除外）
- [ ] 其他: **\*\***\_\_\_\_**\*\***

### 通知与更新

- [x] 希望 AI 主动报告错误和异常
- [x] 希望 AI 提供优化建议
- [ ] 不希望 AI 主动修改配置文件
- [ ] 其他: **\*\***\_\_\_\_**\*\***

---

> **维护说明**: 此文件应随着用户习惯的变化和项目的进展而更新。每次重要会话结束后，建议在"会话历史摘要"部分添加记录。
