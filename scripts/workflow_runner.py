#!/usr/bin/env python3
"""
workflow_runner.py — Phase 8: 工作流运行器原型 (VS Code + CLINE 模式)

在 VS Code + CLINE 环境下，工作流执行不再依赖 Codex 工作流运行时引擎，
而是通过 CLINE 的 Agent 能力 + 本运行器脚本协同完成。

本运行器职责:
  1. 解析工作流 YAML 定义
  2. 生成上下文加载计划 (Context Load Plan)
  3. 验证约束规则
  4. 生成运行快照 (Run Snapshot)
  5. 输出执行指令供 CLINE Agent 执行

CLINE Agent 负责:
  - 读取项目文件 (read_file)
  - 写入文件 (write_to_file)
  - 执行命令 (execute_command)
  - 调用 MCP 工具 (use_mcp_tool)
  - 与用户交互

用法:
  # 解析工作流并生成执行计划
  python scripts/workflow_runner.py plan \\
      --workflow workflows/business/business_model_validation.yaml \\
      --output runtime/workflow_runtime/plan.json

  # 生成上下文加载计划
  python scripts/workflow_runner.py context-plan \\
      --workflow workflows/business/business_model_validation.yaml \\
      --intent "验证新能源充电业务的商业模式" \\
      --industry business \\
      --jurisdiction cn \\
      --output runtime/workflow_runtime/context_plan.json

  # 生成运行快照模板
  python scripts/workflow_runner.py snapshot \\
      --workflow workflows/business/business_model_validation.yaml \\
      --output runtime/workflow_runtime/snapshot.json

  # 验证工作流完整性
  python scripts/workflow_runner.py validate \\
      --workflow workflows/business/business_model_validation.yaml
"""

import argparse
import json
import logging
import os
import sys
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

try:
    import yaml
except ImportError:
    print("⚠️  PyYAML not installed. Run: pip install pyyaml", file=sys.stderr)
    sys.exit(1)

# ═══════════════════════════════════════════════════════════════
# Constants
# ═══════════════════════════════════════════════════════════════

WORKFLOWS_DIR = "workflows"
CONSTRAINTS_DIR = "constraints"
PROMPTS_DIR = "prompts"
SCHEMAS_DIR = "schemas"
CONFIG_DIR = "config"

# L0-L8 分层加载定义
LAYER_DEFINITIONS = {
    "L0": {
        "purpose": "全局安全与治理基线",
        "description": "隐私、安全、引用、人审、工具权限和 Git 边界等全局硬规则",
        "required": True,
    },
    "L1": {
        "purpose": "当前项目状态与 Active Release",
        "description": "active-release.yaml、相关版本号、当前目录状态和可用资产清单",
        "required": True,
    },
    "L2": {
        "purpose": "用户意图与工作流选择",
        "description": "根据用户输入判断行业、地区、任务类型、风险等级、目标产物和缺失信息",
        "required": True,
    },
    "L3": {
        "purpose": "行业、地区、组织和任务约束",
        "description": "只加载命中的行业、地区、组织和任务规则，不加载无关规则包",
        "required": True,
    },
    "L4": {
        "purpose": "当前工作流 prompt 与输出模板",
        "description": "只加载被选中工作流的 system prompt、步骤 prompt 和输出模板",
        "required": True,
    },
    "L5": {
        "purpose": "参考资料元数据与候选检索结果",
        "description": "先加载资料元数据、摘要、权威等级、有效期和引用许可",
        "required": False,
    },
    "L6": {
        "purpose": "必要原文片段、案例和示例",
        "description": "只有当 L5 证明相关且权限允许时，才加载必要原文片段",
        "required": False,
    },
    "L7": {
        "purpose": "工具权限、审批节点和执行计划",
        "description": "根据任务动作决定是否启用文件、Git、GitHub、Fetch、数据库等工具",
        "required": True,
    },
    "L8": {
        "purpose": "评估规则与运行快照字段",
        "description": "根据工作流风险选择评估规则，并确定本次 run_snapshot 必须记录的字段",
        "required": False,
    },
}

# 工作流 ID → 行业映射
WORKFLOW_INDUSTRY_MAP = {
    "contract_review": "legal",
    "policy_qa": "legal",
    "business_model_design": "business",
    "business_model_validation": "business",
    "go_to_market_review": "business",
    "unit_economics_check": "business",
    "solar_financial_model": "energy",
    "investment_research": "finance",
    "risk_summary": "finance",
    "due_diligence": "finance",
    "sop_generation": "operations",
    "meeting_summary": "operations",
    "project_retrospective": "operations",
    "ideation_convergence": "general",
}

# 风险等级定义
RISK_LEVELS = ["low", "medium", "high", "critical"]


# ═══════════════════════════════════════════════════════════════
# File I/O helpers
# ═══════════════════════════════════════════════════════════════

def load_yaml(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_json(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(data: Dict[str, Any], path: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def resolve_path(path: str) -> str:
    """Resolve a path relative to the project root."""
    if os.path.isabs(path):
        return path
    return os.path.join(os.path.dirname(__file__), "..", path)


# ═══════════════════════════════════════════════════════════════
# Workflow Parser
# ═══════════════════════════════════════════════════════════════

def parse_workflow(workflow_path: str) -> Dict[str, Any]:
    """Parse a workflow YAML file and return its contents."""
    resolved = resolve_path(workflow_path)
    if not os.path.exists(resolved):
        print(f"❌ 工作流文件不存在: {resolved}", file=sys.stderr)
        sys.exit(1)
    return load_yaml(resolved)


def get_workflow_id(workflow: Dict[str, Any]) -> str:
    """Extract workflow ID from workflow definition."""
    return workflow.get("workflow", {}).get("id", "unknown")


def get_workflow_steps(workflow: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Extract workflow steps."""
    return workflow.get("steps", [])


def get_workflow_constraints(workflow: Dict[str, Any]) -> List[str]:
    """Extract constraint references from workflow."""
    return workflow.get("constraints", [])


def get_workflow_prompts(workflow: Dict[str, Any]) -> Dict[str, str]:
    """Extract prompt references from workflow."""
    return workflow.get("prompts", {})


def get_workflow_risk_level(workflow: Dict[str, Any]) -> str:
    """Determine the risk level of a workflow."""
    return workflow.get("risk_level", "medium")


# ═══════════════════════════════════════════════════════════════
# Context Load Plan Generator (L0-L8 分层加载)
# ═══════════════════════════════════════════════════════════════

def generate_context_load_plan(
    workflow_path: str,
    intent: str = "",
    industry: str = "",
    jurisdiction: str = "",
    risk_level: str = "medium",
) -> Dict[str, Any]:
    """
    生成上下文加载计划 (Context Load Plan)。

    根据 L0-L8 分层加载策略，为指定工作流生成上下文加载计划。
    该计划描述了需要加载哪些配置、规则、prompt、资料和工具权限。
    """
    workflow = parse_workflow(workflow_path)
    workflow_id = get_workflow_id(workflow)
    run_id = str(uuid.uuid4())[:8]

    # 自动推断行业
    if not industry:
        industry = WORKFLOW_INDUSTRY_MAP.get(workflow_id, "unknown")

    # 加载 active-release.yaml
    active_release = load_yaml(resolve_path(f"{CONFIG_DIR}/active-release.yaml"))

    # 构建分层加载计划
    layers = []

    # L0: 全局安全与治理基线
    l0_assets = []
    baseline_constraints = [
        "constraints/baseline/privacy.yaml",
        "constraints/baseline/safety.yaml",
        "constraints/baseline/citation.yaml",
        "constraints/baseline/human_review.yaml",
        "constraints/baseline/tool_permissions.yaml",
        "constraints/baseline/context_intent_gate.yaml",
    ]
    for c in baseline_constraints:
        if os.path.exists(resolve_path(c)):
            l0_assets.append({
                "path_or_id": c,
                "asset_type": "constraint",
                "reason": "全局安全与治理基线 — 所有工作流必须加载",
            })

    layers.append({
        "layer_id": "L0",
        "purpose": LAYER_DEFINITIONS["L0"]["purpose"],
        "assets": l0_assets,
        "status": "planned",
    })

    # L1: 当前项目状态与 Active Release
    l1_assets = [
        {
            "path_or_id": "config/active-release.yaml",
            "asset_type": "config",
            "reason": "当前发布版本和组件版本信息",
        },
        {
            "path_or_id": "README.md",
            "asset_type": "doc",
            "reason": "项目概述和结构说明",
        },
    ]
    layers.append({
        "layer_id": "L1",
        "purpose": LAYER_DEFINITIONS["L1"]["purpose"],
        "assets": l1_assets,
        "status": "planned",
    })

    # L2: 用户意图与工作流选择
    l2_assets = [
        {
            "path_or_id": workflow_path,
            "asset_type": "workflow",
            "reason": f"选中的工作流: {workflow_id}",
        },
    ]
    if intent:
        l2_assets.append({
            "path_or_id": "intent",
            "asset_type": "intent",
            "reason": f"用户意图: {intent[:200]}",
        })
    layers.append({
        "layer_id": "L2",
        "purpose": LAYER_DEFINITIONS["L2"]["purpose"],
        "assets": l2_assets,
        "status": "planned",
    })

    # L3: 行业、地区、组织和任务约束
    l3_assets = []
    # 行业约束
    industry_constraint = f"constraints/industries/{industry}.yaml"
    if os.path.exists(resolve_path(industry_constraint)):
        l3_assets.append({
            "path_or_id": industry_constraint,
            "asset_type": "constraint",
            "reason": f"行业约束: {industry}",
        })
    # 地区约束
    if jurisdiction:
        jurisdiction_constraint = f"constraints/jurisdictions/{jurisdiction}.yaml"
        if os.path.exists(resolve_path(jurisdiction_constraint)):
            l3_assets.append({
                "path_or_id": jurisdiction_constraint,
                "asset_type": "constraint",
                "reason": f"地区约束: {jurisdiction}",
            })
    # 工作流特定约束
    for c in get_workflow_constraints(workflow):
        if os.path.exists(resolve_path(c)):
            l3_assets.append({
                "path_or_id": c,
                "asset_type": "constraint",
                "reason": f"工作流特定约束",
            })
    layers.append({
        "layer_id": "L3",
        "purpose": LAYER_DEFINITIONS["L3"]["purpose"],
        "assets": l3_assets,
        "status": "planned",
    })

    # L4: 当前工作流 prompt 与输出模板
    l4_assets = []
    prompts = get_workflow_prompts(workflow)
    for prompt_key, prompt_path in prompts.items():
        if os.path.exists(resolve_path(prompt_path)):
            l4_assets.append({
                "path_or_id": prompt_path,
                "asset_type": "prompt",
                "reason": f"工作流 prompt: {prompt_key}",
            })
    # 添加 system prompt
    system_prompt = f"prompts/{industry}/{workflow_id}.system.md"
    if os.path.exists(resolve_path(system_prompt)):
        l4_assets.append({
            "path_or_id": system_prompt,
            "asset_type": "prompt",
            "reason": f"System prompt for {workflow_id}",
        })
    layers.append({
        "layer_id": "L4",
        "purpose": LAYER_DEFINITIONS["L4"]["purpose"],
        "assets": l4_assets,
        "status": "planned",
    })

    # L5: 参考资料元数据
    l5_assets = []
    knowledge_bases = active_release.get("active_release", {}).get("governance", {}).get("knowledge_bases", [])
    for kb in knowledge_bases:
        l5_assets.append({
            "path_or_id": kb.get("id", "unknown"),
            "asset_type": "knowledge_base",
            "reason": f"参考资料: {kb.get('name', 'unknown')} (最后更新: {kb.get('last_fetched', 'never')})",
        })
    layers.append({
        "layer_id": "L5",
        "purpose": LAYER_DEFINITIONS["L5"]["purpose"],
        "assets": l5_assets,
        "status": "planned",
    })

    # L6: 必要原文片段 (占位，实际由 CLINE Agent 按需加载)
    layers.append({
        "layer_id": "L6",
        "purpose": LAYER_DEFINITIONS["L6"]["purpose"],
        "assets": [],
        "status": "planned",
    })

    # L7: 工具权限、审批节点和执行计划
    l7_assets = []
    # 从 mcp-tools.yaml 加载工具权限
    mcp_config = load_yaml(resolve_path(f"{CONFIG_DIR}/mcp-tools.yaml"))
    for tool in mcp_config.get("mcp_tools", {}).get("tools", []):
        l7_assets.append({
            "path_or_id": tool.get("id", "unknown"),
            "asset_type": "tool",
            "reason": f"工具: {tool.get('purpose', 'unknown')[:100]}",
        })
    layers.append({
        "layer_id": "L7",
        "purpose": LAYER_DEFINITIONS["L7"]["purpose"],
        "assets": l7_assets,
        "status": "planned",
    })

    # L8: 评估规则与运行快照字段
    l8_assets = []
    eval_rules = [
        "evaluators/rules/citation_check.yaml",
        "evaluators/rules/risk_check.yaml",
        "evaluators/rules/schema_check.yaml",
    ]
    for rule in eval_rules:
        if os.path.exists(resolve_path(rule)):
            l8_assets.append({
                "path_or_id": rule,
                "asset_type": "evaluator",
                "reason": f"评估规则: {rule}",
            })
    layers.append({
        "layer_id": "L8",
        "purpose": LAYER_DEFINITIONS["L8"]["purpose"],
        "assets": l8_assets,
        "status": "planned",
    })

    # 构建完整的 Context Load Plan
    plan = {
        "run_id": run_id,
        "workflow_id": workflow_id,
        "workflow_path": workflow_path,
        "intent_summary": intent[:500] if intent else "",
        "selected_industry": industry,
        "selected_jurisdiction": jurisdiction,
        "risk_level": risk_level,
        "layers": layers,
        "excluded_assets": [],
        "context_budget": {
            "max_tokens": 128000,
            "overflow_strategy": "summarize",
        },
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "generated_by": "workflow_runner.py (Phase 8)",
    }

    return plan


# ═══════════════════════════════════════════════════════════════
# Run Snapshot Generator
# ═══════════════════════════════════════════════════════════════

def generate_run_snapshot_template(
    workflow_path: str,
    intent: str = "",
    industry: str = "",
    jurisdiction: str = "",
) -> Dict[str, Any]:
    """
    生成运行快照 (Run Snapshot) 模板。

    该模板符合 schemas/run_snapshot.schema.json 规范，
    供 CLINE Agent 在执行工作流时填充。
    """
    workflow = parse_workflow(workflow_path)
    workflow_id = get_workflow_id(workflow)
    run_id = str(uuid.uuid4())[:8]

    if not industry:
        industry = WORKFLOW_INDUSTRY_MAP.get(workflow_id, "unknown")

    snapshot = {
        "run_id": run_id,
        "workflow_id": workflow_id,
        "workflow_version": workflow.get("workflow", {}).get("version", "0.1.0"),
        "prompt_version": "0.1.0",
        "constraint_pack_version": "0.4.0",
        "knowledge_base_version": "kb_0.3.0",
        "model_version": "claude-3.5-sonnet",
        "evaluator_version": "0.2.0",
        "user_input_summary": intent[:500] if intent else "",
        "context_reading_result": {
            "status": "pending",
            "loaded_layers": [],
            "intent_confirmed": False,
        },
        "intent_confirmation": {
            "status": "pending",
            "user_goal": intent[:500] if intent else "",
            "known_info": [],
            "gap_questions": [],
            "planned_workflow": workflow_id,
            "retrieval_scope": {
                "industry": industry,
                "jurisdiction": jurisdiction,
                "risk_level": get_workflow_risk_level(workflow),
            },
            "constraint_rules": get_workflow_constraints(workflow),
            "expected_output_format": workflow.get("output", {}).get("format", "markdown"),
        },
        "context_load_plan": {
            "run_id": run_id,
            "workflow_id": workflow_id,
            "layers": [],
            "excluded_assets": [],
            "context_budget": {
                "max_tokens": 128000,
                "overflow_strategy": "summarize",
            },
        },
        "retrieved_sources": [],
        "output_summary": {},
        "constraints_triggered": [],
        "tool_calls": [],
        "human_review": {
            "required": False,
            "review_status": "not_required",
            "reviewer": "",
            "comments": "",
        },
        "workflow_state": {
            "status": "pending",
            "current_node": "context_reading",
            "last_checkpoint_id": "",
            "resume_from_node": "",
            "completed_steps": [],
            "total_steps": len(get_workflow_steps(workflow)),
        },
        "interruptions": [],
        "resume_events": [],
        "user_feedback": "",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }

    return snapshot


# ═══════════════════════════════════════════════════════════════
# Workflow Validator
# ═══════════════════════════════════════════════════════════════

def validate_workflow(workflow_path: str) -> Dict[str, Any]:
    """
    验证工作流定义的完整性。

    检查项:
      - 必需字段是否存在
      - 引用的约束文件是否存在
      - 引用的 prompt 文件是否存在
      - 步骤定义是否完整
      - 中断节点是否定义了恢复条件
    """
    workflow = parse_workflow(workflow_path)
    workflow_id = get_workflow_id(workflow)
    errors = []
    warnings = []

    # 检查必需字段
    required_fields = ["workflow.id", "workflow.name", "steps"]
    for field in required_fields:
        parts = field.split(".")
        obj = workflow
        for part in parts:
            if isinstance(obj, dict):
                obj = obj.get(part, {})
            else:
                obj = None
                break
        if not obj and obj != 0:
            errors.append(f"缺少必需字段: {field}")

    # 检查版本 (可能在 workflow 下或顶层)
    wf_version = workflow.get("workflow", {}).get("version") or workflow.get("version")
    if not wf_version:
        errors.append("缺少必需字段: workflow.version 或顶层 version")

    # 检查步骤定义
    steps = get_workflow_steps(workflow)
    if not steps:
        errors.append("工作流没有定义任何步骤")
    else:
        for i, step in enumerate(steps):
            step_id = step.get("id", f"step_{i}")
            if "action" not in step and "prompt" not in step:
                errors.append(f"步骤 '{step_id}' 缺少 action 或 prompt 字段")
            if step.get("interrupt") and not step.get("resume_condition"):
                warnings.append(f"步骤 '{step_id}' 定义了中断但未定义恢复条件")

    # 检查约束引用
    for c in get_workflow_constraints(workflow):
        resolved = resolve_path(c)
        if not os.path.exists(resolved):
            warnings.append(f"引用的约束文件不存在: {c}")

    # 检查 prompt 引用
    prompts = get_workflow_prompts(workflow)
    for key, prompt_path in prompts.items():
        resolved = resolve_path(prompt_path)
        if not os.path.exists(resolved):
            warnings.append(f"引用的 prompt 文件不存在: {prompt_path}")

    # 检查输出定义 (支持 output 或 outputs)
    output = workflow.get("output", {}) or workflow.get("outputs", {})
    if not output:
        warnings.append("工作流未定义输出格式")
    elif "format" not in output:
        warnings.append("输出定义缺少 format 字段")

    # 检查风险等级
    risk = get_workflow_risk_level(workflow)
    if risk not in RISK_LEVELS:
        errors.append(f"无效的风险等级: {risk} (有效值: {RISK_LEVELS})")

    # 检查人审节点
    has_human_review = any(
        step.get("human_review_required", False) for step in steps
    )
    if risk in ("high", "critical") and not has_human_review:
        warnings.append(f"高风险工作流 ({risk}) 未定义人工审批节点")

    return {
        "workflow_id": workflow_id,
        "workflow_path": workflow_path,
        "valid": len(errors) == 0,
        "errors": errors,
        "warnings": warnings,
        "steps_count": len(steps),
        "risk_level": risk,
        "has_human_review": has_human_review,
    }


# ═══════════════════════════════════════════════════════════════
# Execution Plan Generator (for CLINE Agent)
# ═══════════════════════════════════════════════════════════════

def generate_execution_plan(workflow_path: str, intent: str = "") -> Dict[str, Any]:
    """
    生成工作流执行计划。

    该计划将工作流 YAML 定义转换为 CLINE Agent 可执行的指令序列。
    每个步骤包含:
      - step_id: 步骤 ID
      - action: 执行动作 (read_file / write_to_file / execute_command / use_mcp_tool / ask_user)
      - params: 动作参数
      - description: 步骤描述
    """
    workflow = parse_workflow(workflow_path)
    workflow_id = get_workflow_id(workflow)
    steps = get_workflow_steps(workflow)
    run_id = str(uuid.uuid4())[:8]

    execution_steps = []

    # Step 0: 上下文读取与意图确认 (强制前置门禁)
    execution_steps.append({
        "step_id": "context_reading",
        "phase": "gate",
        "description": "上下文读取与意图确认 — 强制前置门禁",
        "action": "read_project_state",
        "params": {
            "required_reads": [
                "config/active-release.yaml",
                workflow_path,
            ],
            "intent": intent[:500] if intent else "",
        },
        "prompt": (
            "在开始执行工作流之前，必须先完成上下文读取与意图确认。\n"
            "1. 读取当前项目结构、相关配置、工作流定义、约束包、Prompt 版本\n"
            "2. 识别用户输入所属场景、行业、地区、风险等级、目标产物\n"
            "3. 对照当前项目状态判断可执行范围、依赖条件、权限边界\n"
            "4. 形成意图确认结果，包括用户目标、已知信息、缺口问题\n"
            "5. 在高风险、信息不足或权限不明确的情况下，先向用户确认"
        ),
        "output": "intent_confirmation",
    })

    # Step 1: 生成上下文加载计划
    execution_steps.append({
        "step_id": "context_planning",
        "phase": "loading",
        "description": "生成上下文加载计划 (L0-L8 分层加载)",
        "action": "execute_command",
        "params": {
            "command": f"python3 scripts/workflow_runner.py context-plan --workflow {workflow_path} --intent \"{intent[:200]}\" --output runtime/workflow_runtime/context_plan_{run_id}.json",
        },
        "prompt": "根据 L0-L8 分层加载策略，生成上下文加载计划",
        "output": "context_load_plan",
    })

    # Step 2-N: 工作流步骤
    for i, step in enumerate(steps):
        step_id = step.get("id", f"step_{i+1}")
        step_action = step.get("action", "process")
        step_prompt = step.get("prompt", "")
        step_interrupt = step.get("interrupt", False)
        step_human_review = step.get("human_review_required", False)

        exec_step = {
            "step_id": step_id,
            "phase": "execution",
            "step_number": i + 1,
            "description": step.get("description", f"步骤 {i+1}"),
            "action": step_action,
            "params": step.get("params", {}),
            "prompt": step_prompt,
            "interrupt": step_interrupt,
            "human_review_required": step_human_review,
            "output": step.get("output", ""),
        }

        # 如果步骤定义了中断，添加恢复条件
        if step_interrupt:
            exec_step["resume_condition"] = step.get("resume_condition", "user_confirmation")
            exec_step["cancel_condition"] = step.get("cancel_condition", "user_cancellation")

        execution_steps.append(exec_step)

    # Final step: 生成运行快照
    execution_steps.append({
        "step_id": "snapshot_generation",
        "phase": "completion",
        "description": "生成运行快照",
        "action": "execute_command",
        "params": {
            "command": f"python3 scripts/workflow_runner.py snapshot --workflow {workflow_path} --output runtime/workflow_runtime/snapshot_{run_id}.json",
        },
        "prompt": "工作流执行完成后，生成运行快照以记录本次运行",
        "output": "run_snapshot",
    })

    return {
        "run_id": run_id,
        "workflow_id": workflow_id,
        "workflow_path": workflow_path,
        "intent": intent[:500] if intent else "",
        "total_steps": len(execution_steps),
        "execution_steps": execution_steps,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "generated_by": "workflow_runner.py (Phase 8)",
        "notes": [
            "此执行计划供 CLINE Agent 参考执行",
            "CLINE Agent 应按照步骤顺序执行，并在每个步骤完成后更新运行快照",
            "中断步骤需要用户确认后才能继续",
            "高风险步骤需要人工审批",
        ],
    }


# ═══════════════════════════════════════════════════════════════
# MCP Tool Registry
# ═══════════════════════════════════════════════════════════════

def get_mcp_tool_registry() -> Dict[str, Any]:
    """
    获取 MCP 工具注册表。

    返回当前项目配置的所有 MCP 工具及其权限信息。
    用于 CLINE Agent 在执行工作流时判断可用工具。
    """
    mcp_config_path = resolve_path(f"{CONFIG_DIR}/mcp-tools.yaml")
    if not os.path.exists(mcp_config_path):
        return {"error": "mcp-tools.yaml not found"}

    mcp_config = load_yaml(mcp_config_path)
    tools = mcp_config.get("mcp_tools", {}).get("tools", [])

    registry = {
        "version": mcp_config.get("mcp_tools", {}).get("version", "0.1.0"),
        "environment": mcp_config.get("mcp_tools", {}).get("environment", "vscode_copilot"),
        "tools": {},
    }

    for tool in tools:
        tool_id = tool.get("id", "unknown")
        registry["tools"][tool_id] = {
            "purpose": tool.get("purpose", ""),
            "permissions": {
                "read": tool.get("permissions", {}).get("read", False),
                "write": tool.get("permissions", {}).get("write", False),
                "external_network": tool.get("permissions", {}).get("external_network", False),
            },
            "approval_required": tool.get("approval_required", False),
            "vscode_tools": tool.get("vscode_tools", []),
        }

    return registry


# ═══════════════════════════════════════════════════════════════
# CLINE MCP Config Generator
# ═══════════════════════════════════════════════════════════════

def generate_cline_mcp_config() -> Dict[str, Any]:
    """
    生成 CLINE MCP 配置文件。

    CLINE 使用自己的 MCP 服务器配置格式 (cline_mcp_settings.json)。
    此函数将项目中的 MCP 工具配置转换为 CLINE 兼容的格式。

    CLINE MCP 配置格式:
    {
      "mcpServers": {
        "server-name": {
          "command": "npx",
          "args": ["-y", "package-name", ...],
          "env": {
            "KEY": "value"
          }
        }
      }
    }
    """
    return {
        "mcpServers": {
            "filesystem": {
                "command": "npx",
                "args": ["-y", "@anthropic/mcp-filesystem", "."],
                "description": "读取和写入工作区文件，带权限控制",
            },
            "fetch": {
                "command": "npx",
                "args": ["-y", "@anthropic/mcp-fetch"],
                "description": "获取外部 URL 用于官方参考检索",
            },
            "git": {
                "command": "npx",
                "args": ["-y", "@anthropic/mcp-git", "."],
                "description": "Git 状态和版本控制操作",
            },
            "github": {
                "command": "npx",
                "args": ["-y", "@anthropic/mcp-github"],
                "description": "GitHub API 操作 (PR, Issue, 代码审查)",
                "env": {
                    "GITHUB_TOKEN": "${GITHUB_TOKEN}",
                },
            },
        },
        "registry": {
            "allow_unregistered_tools": False,
            "writable_tools_require_confirmation": True,
            "external_network_tools_require_confirmation": True,
        },
    }


# ═══════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="Phase 8: 工作流运行器原型 — MCP 工具接入、分步加载与运行器实现",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
子命令:
  plan           生成工作流执行计划 (供 CLINE Agent 执行)
  context-plan   生成上下文加载计划 (L0-L8 分层加载)
  snapshot       生成运行快照模板
  validate       验证工作流定义完整性
  mcp-registry   查看 MCP 工具注册表
  cline-config   生成 CLINE MCP 配置文件

示例:
  # 验证工作流
  python scripts/workflow_runner.py validate \\
      --workflow workflows/business/business_model_validation.yaml

  # 生成执行计划
  python scripts/workflow_runner.py plan \\
      --workflow workflows/business/business_model_validation.yaml \\
      --intent "验证新能源充电业务的商业模式"

  # 生成上下文加载计划
  python scripts/workflow_runner.py context-plan \\
      --workflow workflows/business/business_model_validation.yaml \\
      --industry business --jurisdiction cn

  # 生成运行快照模板
  python scripts/workflow_runner.py snapshot \\
      --workflow workflows/business/business_model_validation.yaml

  # 查看 MCP 工具注册表
  python scripts/workflow_runner.py mcp-registry

  # 生成 CLINE MCP 配置
  python scripts/workflow_runner.py cline-config
        """,
    )
    subparsers = parser.add_subparsers(dest="command", help="子命令")

    # plan
    plan_parser = subparsers.add_parser("plan", help="生成工作流执行计划")
    plan_parser.add_argument("-w", "--workflow", required=True, help="工作流 YAML 路径")
    plan_parser.add_argument("-i", "--intent", default="", help="用户意图描述")
    plan_parser.add_argument("-o", "--output", default="", help="输出路径 (默认: runtime/workflow_runtime/plan_<run_id>.json)")

    # context-plan
    cp_parser = subparsers.add_parser("context-plan", help="生成上下文加载计划")
    cp_parser.add_argument("-w", "--workflow", required=True, help="工作流 YAML 路径")
    cp_parser.add_argument("-i", "--intent", default="", help="用户意图描述")
    cp_parser.add_argument("--industry", default="", help="行业 (legal/business/finance/operations/energy)")
    cp_parser.add_argument("--jurisdiction", default="", help="地区 (us/eu/cn/au)")
    cp_parser.add_argument("--risk-level", default="medium", choices=RISK_LEVELS, help="风险等级")
    cp_parser.add_argument("-o", "--output", default="", help="输出路径 (默认: runtime/workflow_runtime/context_plan_<run_id>.json)")

    # snapshot
    snap_parser = subparsers.add_parser("snapshot", help="生成运行快照模板")
    snap_parser.add_argument("-w", "--workflow", required=True, help="工作流 YAML 路径")
    snap_parser.add_argument("-i", "--intent", default="", help="用户意图描述")
    snap_parser.add_argument("--industry", default="", help="行业 (legal/business/finance/operations/energy)")
    snap_parser.add_argument("--jurisdiction", default="", help="地区 (us/eu/cn/au)")
    snap_parser.add_argument("-o", "--output", default="", help="输出路径 (默认: runtime/workflow_runtime/snapshot_<run_id>.json)")

    # validate
    val_parser = subparsers.add_parser("validate", help="验证工作流定义完整性")
    val_parser.add_argument("-w", "--workflow", required=True, help="工作流 YAML 路径")

    # mcp-registry
    subparsers.add_parser("mcp-registry", help="查看 MCP 工具注册表")

    # cline-config
    subparsers.add_parser("cline-config", help="生成 CLINE MCP 配置文件")

    # interrupt (Phase 9)
    int_parser = subparsers.add_parser("interrupt", help="中断当前运行 (Phase 9)")
    int_parser.add_argument("--snapshot", required=True, help="运行快照 JSON 文件路径")
    int_parser.add_argument("--reason", required=True, help="中断原因 (如 missing_required_input)")
    int_parser.add_argument("--type", default="workflow_pause", choices=["workflow_pause", "interrupted_by_user", "cancelled_by_user"], help="中断类型")
    int_parser.add_argument("--node-id", default="", help="中断发生的节点 ID")
    int_parser.add_argument("--pending-questions", nargs="*", default=[], help="待用户回答的问题")
    int_parser.add_argument("-o", "--output", default="", help="输出路径")

    # resume (Phase 9)
    res_parser = subparsers.add_parser("resume", help="恢复中断的运行 (Phase 9)")
    res_parser.add_argument("--snapshot", required=True, help="运行快照 JSON 文件路径")
    res_parser.add_argument("--interruption", required=True, help="中断事件 JSON 文件路径")
    res_parser.add_argument("--supplement", required=True, help="用户补充输入内容")
    res_parser.add_argument("-o", "--output", default="", help="输出路径")

    # checkpoint (Phase 9)
    cp_parser = subparsers.add_parser("checkpoint", help="创建运行 Checkpoint (Phase 9)")
    cp_parser.add_argument("--snapshot", required=True, help="运行快照 JSON 文件路径")
    cp_parser.add_argument("--node-id", required=True, help="当前节点 ID")
    cp_parser.add_argument("-o", "--output", default="", help="输出路径")

    args = parser.parse_args()

    if args.command == "plan":
        workflow_path = args.workflow
        intent = args.intent
        plan = generate_execution_plan(workflow_path, intent)
        output = args.output or f"runtime/workflow_runtime/plan_{plan['run_id']}.json"
        save_json(plan, output)
        print(f"✅ 执行计划已生成: {output}")
        print(f"   工作流: {plan['workflow_id']}")
        print(f"   步骤数: {plan['total_steps']}")
        print(f"   运行 ID: {plan['run_id']}")

    elif args.command == "context-plan":
        workflow_path = args.workflow
        intent = args.intent
        industry = args.industry
        jurisdiction = args.jurisdiction
        risk_level = args.risk_level
        plan = generate_context_load_plan(workflow_path, intent, industry, jurisdiction, risk_level)
        output = args.output or f"runtime/workflow_runtime/context_plan_{plan['run_id']}.json"
        save_json(plan, output)
        print(f"✅ 上下文加载计划已生成: {output}")
        print(f"   工作流: {plan['workflow_id']}")
        print(f"   行业: {plan['selected_industry']}")
        print(f"   地区: {plan['selected_jurisdiction']}")
        print(f"   层数: {len(plan['layers'])}")
        for layer in plan['layers']:
            asset_count = len(layer['assets'])
            print(f"     {layer['layer_id']}: {layer['purpose'][:40]} ({asset_count} assets)")

    elif args.command == "snapshot":
        workflow_path = args.workflow
        intent = args.intent
        industry = args.industry
        jurisdiction = args.jurisdiction
        snapshot = generate_run_snapshot_template(workflow_path, intent, industry, jurisdiction)
        output = args.output or f"runtime/workflow_runtime/snapshot_{snapshot['run_id']}.json"
        save_json(snapshot, output)
        print(f"✅ 运行快照模板已生成: {output}")
        print(f"   工作流: {snapshot['workflow_id']}")
        print(f"   运行 ID: {snapshot['run_id']}")
        print(f"   总步骤数: {snapshot['workflow_state']['total_steps']}")

    elif args.command == "validate":
        workflow_path = args.workflow
        result = validate_workflow(workflow_path)
        if result["valid"]:
            print(f"✅ 工作流验证通过: {result['workflow_id']}")
        else:
            print(f"❌ 工作流验证失败: {result['workflow_id']}")
        print(f"   步骤数: {result['steps_count']}")
        print(f"   风险等级: {result['risk_level']}")
        if result["errors"]:
            print(f"   错误 ({len(result['errors'])}):")
            for e in result["errors"]:
                print(f"     ❌ {e}")
        if result["warnings"]:
            print(f"   警告 ({len(result['warnings'])}):")
            for w in result["warnings"]:
                print(f"     ⚠️  {w}")

    elif args.command == "mcp-registry":
        registry = get_mcp_tool_registry()
        if "error" in registry:
            print(f"❌ {registry['error']}")
        else:
            print(f"✅ MCP 工具注册表 (v{registry['version']})")
            print(f"   环境: {registry['environment']}")
            print(f"   工具数: {len(registry['tools'])}")
            for tool_id, tool_info in registry['tools'].items():
                perms = tool_info['permissions']
                perm_str = f"R={'✓' if perms['read'] else '✗'} W={'✓' if perms['write'] else '✗'} N={'✓' if perms['external_network'] else '✗'}"
                print(f"     {tool_id}: {tool_info['purpose'][:60]}")
                print(f"       权限: {perm_str} | 审批: {'需要' if tool_info['approval_required'] else '不需要'}")

    elif args.command == "cline-config":
        config = generate_cline_mcp_config()
        output = "runtime/workflow_runtime/cline_mcp_settings.json"
        save_json(config, output)
        print(f"✅ CLINE MCP 配置已生成: {output}")
        print(f"   MCP 服务器数: {len(config['mcpServers'])}")
        for server_name in config['mcpServers']:
            print(f"     - {server_name}")
        print("")
        print("📋 使用说明:")
        print("   1. 将此文件内容复制到 CLINE MCP 配置中")
        print("   2. 或在 VS Code 设置中配置 cline.mcpServers")
        print("   3. 确保已安装必要的 npm 包")

    elif args.command == "interrupt":
        # Phase 9: 中断当前运行
        from scripts.interruption_handler import (
            create_interruption,
            create_checkpoint,
            update_snapshot_with_interruption,
        )
        snapshot = load_json(args.snapshot)
        run_id = snapshot.get("run_id", "unknown")
        node_id = args.node_id or snapshot.get("workflow_state", {}).get("current_node", "unknown")

        # 1. 创建 Checkpoint
        checkpoint = create_checkpoint(
            run_id=run_id,
            node_id=node_id,
            workflow_state=snapshot.get("workflow_state", {}),
        )

        # 2. 创建中断事件
        interruption = create_interruption(
            run_id=run_id,
            interruption_type=args.type,
            pause_reason=args.reason,
            checkpoint_id=checkpoint["checkpoint_id"],
            node_id=node_id,
            pending_questions=args.pending_questions,
        )

        # 3. 更新快照
        updated = update_snapshot_with_interruption(
            snapshot=snapshot,
            interruption=interruption,
        )

        output = args.output or f"runtime/workflow_runtime/snapshot_{run_id}_interrupted.json"
        save_json(updated, output)
        print(f"✅ 运行已中断: {output}")
        print(f"   中断 ID: {interruption['interruption_id']}")
        print(f"   类型: {interruption['type']}")
        print(f"   原因: {interruption['pause_reason']}")
        print(f"   Checkpoint: {checkpoint['checkpoint_id']}")
        print(f"   状态: {updated['workflow_state']['status']}")

    elif args.command == "resume":
        # Phase 9: 恢复中断的运行
        from scripts.interruption_handler import (
            process_resume_event,
            validate_resume,
            update_snapshot_with_interruption,
        )
        snapshot = load_json(args.snapshot)
        interruption = load_json(args.interruption)

        # 1. 处理恢复事件
        resume_event = process_resume_event(
            interruption=interruption,
            user_supplement=args.supplement,
        )

        # 2. 验证恢复条件
        validation = validate_resume(interruption, resume_event)

        # 3. 更新快照
        updated = update_snapshot_with_interruption(
            snapshot=snapshot,
            interruption=interruption,
            resume_event=resume_event,
            validation=validation,
        )

        output = args.output or f"runtime/workflow_runtime/snapshot_{snapshot.get('run_id', 'unknown')}_resumed.json"
        save_json(updated, output)
        print(f"✅ 恢复处理完成: {output}")
        print(f"   恢复事件 ID: {resume_event['resume_event_id']}")
        print(f"   验证结果: {'✅ 通过' if validation['accepted'] else '❌ 拒绝'}")
        print(f"   原因: {validation['reason']}")
        print(f"   恢复路径: {'regate' if validation.get('requires_regate') else 'replan' if validation.get('requires_replan') else 'resume'}")
        print(f"   状态: {updated['workflow_state']['status']}")

    elif args.command == "checkpoint":
        # Phase 9: 创建运行 Checkpoint
        from scripts.interruption_handler import create_checkpoint
        snapshot = load_json(args.snapshot)
        run_id = snapshot.get("run_id", "unknown")
        node_id = args.node_id

        checkpoint = create_checkpoint(
            run_id=run_id,
            node_id=node_id,
            workflow_state=snapshot.get("workflow_state", {}),
        )

        output = args.output or f"runtime/checkpoints/{checkpoint['checkpoint_id']}.json"
        save_json(checkpoint, output)
        print(f"✅ Checkpoint 已创建: {output}")
        print(f"   Checkpoint ID: {checkpoint['checkpoint_id']}")
        print(f"   运行 ID: {checkpoint['run_id']}")
        print(f"   节点: {checkpoint['node_id']}")

    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
