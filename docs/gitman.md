# Git 同步与回退管理方案

本方案建议将 GitHub 作为 **系统配置与能力版本库**，而不是具体工作内容仓库。

目标是：把平台骨架、配置、规则、工作流定义、评估逻辑纳入 Git 版本管理；同时排除具体业务内容、用户输入、运行日志、客户文档和生成结果。这样当修改设置或进化策略效果不佳时，可以安全回退，而不会把真实工作内容同步到 GitHub。

## 核心原则

### 1. 同步“规则”，不同步“内容”

Git 里保存的是系统怎么工作，不保存用户实际做了什么。

### 2. 同步“模板”，不同步“实例”

例如保存 `contract_review.yaml`，但不保存某个真实客户合同的分析结果。

### 3. 同步“脱敏评估样本”，不同步原始业务样本

如果真实案例要进入评估集，必须先做匿名化、摘要化、重写或合成化。

### 4. 同步“可回滚配置”，不同步“运行态数据”

配置、规则、prompt、schema、评估逻辑可以通过 Git 回退。运行态数据、用户文件、业务日志应由数据库、对象存储、审计日志系统或向量数据库管理。

## 建议同步到 GitHub 的内容

适合同步：

```text
/config
  model-routing.yaml
  permissions.yaml
  tenants.example.yaml

/workflows
  contract_review.yaml
  policy_qa.yaml
  investment_research.yaml

/constraints
  legal_us.yaml
  finance_general.yaml
  privacy_baseline.yaml

/evaluators
  citation_check.yaml
  risk_scoring.yaml
  regression_suite.yaml

/schemas
  contract_review.output.schema.json
  eval_report.schema.json

/prompts
  legal/
  finance/
  operations/

/tests
  eval_cases/
  regression_cases/

/docs
  architecture.md
  eval.md
  workspace_plan.md
```

## 不适合同步的内容

不适合同步：

```text
/data
/uploads
/runtime
/logs
/outputs
/customer_docs
/vector_store
/secrets
/.env
/feedback/raw
```

这些内容可能包含用户输入、客户文件、商业机密、个人信息、运行轨迹、模型输出或密钥，应该放在专门的数据系统中，而不是 GitHub。

## 推荐仓库结构

```text
ai-work-platform/
  README.md
  docs/
    workspace_plan.md
    eval.md
    architecture.md

  config/
    model-routing.yaml
    feature-flags.yaml
    permissions.yaml

  workflows/
    legal/
      contract_review.yaml
    finance/
      investment_research.yaml
    operations/
      sop_generation.yaml

  constraints/
    baseline/
      privacy.yaml
      safety.yaml
      citation.yaml
    industries/
      legal.yaml
      finance.yaml
      healthcare.yaml

  prompts/
    legal/
      contract_review.system.md
      contract_review.review.md
    finance/
      research_summary.system.md

  schemas/
    run_snapshot.schema.json
    eval_report.schema.json
    workflow.schema.json

  evaluators/
    rules/
      citation_check.yaml
      risk_check.yaml
    rubrics/
      contract_review.yaml
      research_summary.yaml

  tests/
    eval_cases/
      synthetic/
      anonymized/
    regression/

  examples/
    fake_contract.md
    fake_policy.md

  .gitignore
```

## `.gitignore` 示例

```gitignore
# secrets
.env
.env.*
*.pem
*.key
secrets/
credentials/

# runtime data
data/
uploads/
runtime/
logs/
outputs/
tmp/

# customer/business content
customer_docs/
client_files/
workspaces/*/documents/
workspaces/*/outputs/
workspaces/*/logs/

# vector/index/cache
vector_store/
indexes/
embeddings/
.cache/

# raw feedback and traces
feedback/raw/
traces/
```

## 版本回退机制

每次平台行为变化都应该打版本，例如：

```yaml
release:
  version: "0.4.2"
  changes:
    - updated legal contract review constraints
    - changed retrieval priority
    - added citation gap evaluator
  components:
    workflow_version: "1.3.0"
    constraint_pack_version: "1.5.1"
    prompt_version: "2.1.0"
    evaluator_version: "0.4.0"
```

当效果不好时，可以整体回退：

```bash
git checkout v0.4.1
```

或者只回退某类配置：

```bash
git checkout v0.4.1 -- constraints/legal.yaml
git checkout v0.4.1 -- prompts/legal/contract_review.system.md
```

## Active Release Manifest

更专业的做法是将生产环境正在使用的配置固定到一个 manifest：

```yaml
active_release:
  id: "release_2026_05_05_001"
  git_commit: "abc1234"
  workflow_version: "1.3.0"
  constraint_pack_version: "1.5.1"
  prompt_version: "2.1.0"
  evaluator_version: "0.4.0"
  knowledge_base_version: "kb_2026_05_01"
```

每次运行都记录当前 `git_commit` 和相关组件版本。以后发现某次进化效果不好，就能明确知道是哪个提交、哪套规则或哪组 prompt 引入的问题。

## 推荐存储边界

GitHub 适合放：

- 配置
- 代码
- 模板
- 规则
- schema
- 脱敏测试样本
- 文档

真实业务数据应该放：

- 数据库
- 对象存储
- 私有文档系统
- 向量数据库
- 审计日志系统

## 总结

GitHub 管“平台怎么工作”，业务存储管“用户实际做了什么”。

这样既能回滚平台能力，又不会把具体工作内容同步到 Git 上。
