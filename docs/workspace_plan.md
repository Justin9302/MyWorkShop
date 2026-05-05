# 通用 AI 辅助工作平台方案

我的建议：不要先做“通用 AI 聊天平台”，而是做成 **行业工作流平台 + 约束引擎 + 可审计参考资料库**。核心思想是：模型负责推理和生成，平台负责边界、证据、权限、流程和追责。

## 推荐总体架构

### 1. 通用底座

- 多模型接口：OpenAI / Claude / Gemini / 本地模型可切换。
- RAG 知识库：支持法规、标准、SOP、案例、模板、公司内部文档。
- 工具系统：CRM、ERP、邮箱、表格、数据库、文档系统等。
- 审计日志：每次回答引用了哪些资料、触发了哪些规则、调用了哪些工具。
- 权限控制：不同角色看到不同资料，能执行不同动作。

### 2. 约束层

把“专业约束”从 prompt 里拿出来，做成可版本化的规则包：

- 硬约束：不能诊断、不能给确定性法律结论、不能自动执行付款、不能泄露隐私。
- 软约束：必须引用来源、必须说明假设、必须给风险等级、必须建议人工复核。
- 行业约束：医疗、金融、法律、HR、工程、教育等分别配置。
- 地区约束：美国、欧盟、中国、澳洲等法规差异单独管理。
- 输出约束：用 JSON Schema / 表单 / 报告模板强制结构化。

### 3. 参考资料库

资料不要只存向量，建议每份资料带元数据：

- 行业、地区、适用场景、生效日期、失效日期
- 权威等级：法律法规 > 官方指南 > 公司政策 > 行业白皮书 > 示例模板
- 保密等级、来源链接、版本号、负责人
- 是否可直接引用、是否需要人工确认

### 4. 行业工作流包

每个行业包最好包含：

- 角色：用户是谁，例如律师助理、医生助理、财务分析师、HRBP。
- 场景：合同审查、病历摘要、投研初稿、招聘筛选、质量审计。
- 输入表单：需要用户提供哪些字段。
- 检索范围：允许查哪些资料库。
- 约束规则：哪些话不能说，哪些动作必须人工批准。
- 输出模板：备忘录、清单、风险矩阵、邮件草稿、报告。
- 测试集：典型问题、边界问题、恶意提示、幻觉检测。

## 技术选型建议

- 对话和工具调用：可以用 OpenAI Responses API，它支持工具、文件搜索、结构化输出等能力。
- 知识库：OpenAI File Search / 自建向量库如 pgvector、Qdrant、Weaviate，配合关键词搜索做 hybrid search。
- 复杂工作流：LangGraph 适合长流程、可恢复、人审节点；LlamaIndex 适合 RAG、文档解析和知识工作流。
- 工具接入标准：可以参考 MCP，把外部系统抽象成 tools / resources / prompts。
- 结构化输出：强烈建议所有关键任务都用 JSON Schema，避免“看起来专业但不可验证”的回答。
- 评测：为每个行业包建立 eval，包括引用准确率、拒答正确率、格式合规率、风险识别率。

## MVP 路线

我会先做 3 层，而不是一上来做十几个行业：

### 1. 核心平台

- 用户、组织、权限
- 文档上传、检索、引用
- 工作流运行器
- 审计日志
- 人工审批节点

### 2. 3 个高价值行业包

建议从这些开始：

- 法律/合规：合同审查、政策问答、合规清单
- 金融/投研：行业研究、风险摘要、尽调清单
- 企业运营：SOP 生成、会议纪要、项目复盘、销售支持

### 3. 治理与安全

- 基于 NIST AI RMF 和 ISO/IEC 42001 做 AI 风险管理框架
- 基于 OWASP LLM Top 10 做安全基线
- 高风险动作必须 human-in-the-loop

## 示例行业工作流

```yaml
workflow: contract_review
industry: legal
jurisdiction: US
inputs:
  - contract_file
  - contract_type
  - business_goal
retrieval_scopes:
  - company_playbook
  - clause_library
  - applicable_law_refs
constraints:
  - do_not_provide_final_legal_opinion
  - cite_sources_for_legal_claims
  - escalate_high_risk_clauses
steps:
  - extract_key_terms
  - classify_risk
  - compare_against_playbook
  - draft_redlines
  - human_review
outputs:
  - executive_summary
  - risk_table
  - suggested_revisions
  - open_questions
```

## 关键建议

你真正要卖的不是“AI 能回答问题”，而是：**在特定行业语境下，AI 能按专业流程、专业资料、专业边界完成工作，并且过程可审计、可复核、可持续更新。**

## 参考资料

- [OpenAI Responses API](https://platform.openai.com/docs/api-reference/responses)
- [OpenAI File Search](https://platform.openai.com/docs/guides/tools-file-search/)
- [OpenAI Structured Outputs](https://platform.openai.com/docs/guides/structured-outputs)
- [LangGraph durable execution](https://docs.langchain.com/oss/python/langgraph/durable-execution)
- [LlamaIndex workflows](https://docs.llamaindex.ai/en/stable/module_guides/workflow/)
- [Model Context Protocol](https://modelcontextprotocol.io/specification/2025-11-25/server/index)
- [NIST AI RMF](https://www.nist.gov/publications/artificial-intelligence-risk-management-framework-ai-rmf-10)
- [ISO/IEC 42001](https://www.iso.org/standard/81230.html)
- [OWASP LLM Top 10](https://genai.owasp.org/resource/owasp-top-10-for-llm-applications-2025/)
