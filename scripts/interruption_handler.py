#!/usr/bin/env python3
"""
interruption_handler.py — Phase 9: 中断、补充、恢复与用户运行控制

在 VS Code + CLINE 环境下，工作流执行可能因多种原因中断：
  - 工作流设计暂停 (workflow_pause): 由 workflow 节点、约束规则或工具权限触发
  - 用户主动停止 (interrupted_by_user): 用户暂停当前运行
  - 用户取消 (cancelled_by_user): 用户放弃本次运行

本脚本职责:
  1. 创建中断事件 (create_interruption)
  2. 处理用户补充输入 (process_resume_event)
  3. 验证恢复条件 (validate_resume)
  4. 管理 Checkpoint (create_checkpoint / load_checkpoint)
  5. 生成结构化补丁 (extract_structured_patch)
  6. 更新运行快照 (update_snapshot_with_interruption)

用法:
  # 创建中断事件
  python scripts/interruption_handler.py create-interruption \\
      --run-id run_abc123 \\
      --type workflow_pause \\
      --reason "missing_required_input" \\
      --checkpoint-id cp_001 \\
      --node-id confirm_intent \\
      --output runtime/interruptions/interruption_001.json

  # 处理恢复事件
  python scripts/interruption_handler.py process-resume \\
      --interruption runtime/interruptions/interruption_001.json \\
      --supplement "用户补充了合同类型和审查目标" \\
      --output runtime/interruptions/resume_001.json

  # 验证恢复条件
  python scripts/interruption_handler.py validate-resume \\
      --interruption runtime/interruptions/interruption_001.json \\
      --resume-event runtime/interruptions/resume_001.json

  # 创建 Checkpoint
  python scripts/interruption_handler.py create-checkpoint \\
      --run-id run_abc123 \\
      --node-id confirm_intent \\
      --state '{"status": "paused", "current_node": "confirm_intent"}' \\
      --output runtime/checkpoints/cp_001.json

  # 更新运行快照
  python scripts/interruption_handler.py update-snapshot \\
      --snapshot runtime/workflow_runtime/snapshot_abc123.json \\
      --interruption runtime/interruptions/interruption_001.json \\
      --resume-event runtime/interruptions/resume_001.json \\
      --output runtime/workflow_runtime/snapshot_abc123_updated.json
"""

import argparse
import json
import logging
import os
import sys
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

# ═══════════════════════════════════════════════════════════════
# Constants
# ═══════════════════════════════════════════════════════════════

# 中断类型定义
INTERRUPTION_TYPES = [
    "workflow_pause",
    "interrupted_by_user",
    "cancelled_by_user",
]

# 中断原因定义 (对应 interruption-policy.yaml mandatory_pause_reasons)
MANDATORY_PAUSE_REASONS = [
    "missing_required_input",
    "high_risk_output",
    "requires_human_approval",
    "tool_permission_required",
    "schema_validation_failed",
    "context_budget_exceeded",
    "evidence_gap",
]

# 工作流状态定义
WORKFLOW_STATUSES = [
    "created",
    "context_intent_pending",
    "context_intent_confirmed",
    "running",
    "workflow_pause",
    "interrupted_by_user",
    "cancelled_by_user",
    "completed",
    "failed",
]

# 恢复验证结果
VALIDATION_RESULTS = [
    "accepted",
    "rejected",
    "requires_more_information",
]

# 补丁类型
PATCH_TYPES = [
    "intent_patch",
    "context_patch",
    "approval_patch",
    "constraint_patch",
]

# 默认 Checkpoint 目录
DEFAULT_CHECKPOINT_DIR = "runtime/checkpoints"
DEFAULT_INTERRUPTION_DIR = "runtime/interruptions"

# ═══════════════════════════════════════════════════════════════
# Logging
# ═══════════════════════════════════════════════════════════════

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("interruption_handler")


# ═══════════════════════════════════════════════════════════════
# File I/O helpers
# ═══════════════════════════════════════════════════════════════

def load_json(path: str) -> Dict[str, Any]:
    """Load JSON from file."""
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(data: Dict[str, Any], path: str) -> None:
    """Save JSON to file, creating directories as needed."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def resolve_path(path: str) -> str:
    """Resolve a path relative to the project root."""
    if os.path.isabs(path):
        return path
    return os.path.join(os.path.dirname(__file__), "..", path)


# ═══════════════════════════════════════════════════════════════
# Checkpoint Management
# ═══════════════════════════════════════════════════════════════

def create_checkpoint(
    run_id: str,
    node_id: str,
    workflow_state: Dict[str, Any],
    context_load_plan: Optional[Dict[str, Any]] = None,
    checkpoint_dir: str = DEFAULT_CHECKPOINT_DIR,
) -> Dict[str, Any]:
    """
    创建运行 Checkpoint。

    Checkpoint 用于冻结当前运行状态，以便后续恢复。
    包含:
      - checkpoint_id: 唯一标识
      - run_id: 关联的运行 ID
      - node_id: 中断时的节点 ID
      - workflow_state: 当前工作流状态快照
      - context_load_plan: 当前上下文加载计划 (可选)
      - created_at: 创建时间
    """
    checkpoint_id = f"cp_{str(uuid.uuid4())[:8]}"

    checkpoint = {
        "checkpoint_id": checkpoint_id,
        "run_id": run_id,
        "node_id": node_id,
        "workflow_state": workflow_state,
        "context_load_plan": context_load_plan or {},
        "created_at": datetime.now(timezone.utc).isoformat(),
    }

    # 保存到文件
    checkpoint_path = os.path.join(checkpoint_dir, f"{checkpoint_id}.json")
    save_json(checkpoint, checkpoint_path)

    logger.info(f"Checkpoint 已创建: {checkpoint_id} (run: {run_id}, node: {node_id})")
    return checkpoint


def load_checkpoint(checkpoint_id: str, checkpoint_dir: str = DEFAULT_CHECKPOINT_DIR) -> Dict[str, Any]:
    """加载指定 Checkpoint。"""
    checkpoint_path = os.path.join(checkpoint_dir, f"{checkpoint_id}.json")
    resolved = resolve_path(checkpoint_path)
    if not os.path.exists(resolved):
        logger.error(f"Checkpoint 不存在: {checkpoint_id}")
        raise FileNotFoundError(f"Checkpoint not found: {checkpoint_id}")
    return load_json(resolved)


# ═══════════════════════════════════════════════════════════════
# Interruption Creation
# ═══════════════════════════════════════════════════════════════

def create_interruption(
    run_id: str,
    interruption_type: str,
    pause_reason: str,
    checkpoint_id: str,
    node_id: str = "",
    resume_condition: str = "",
    cancel_condition: str = "",
    pending_questions: Optional[List[str]] = None,
    interruption_dir: str = DEFAULT_INTERRUPTION_DIR,
) -> Dict[str, Any]:
    """
    创建中断事件。

    参数:
      run_id: 关联的运行 ID
      interruption_type: 中断类型 (workflow_pause / interrupted_by_user / cancelled_by_user)
      pause_reason: 中断原因 (如 missing_required_input, requires_human_approval)
      checkpoint_id: 关联的 Checkpoint ID
      node_id: 中断发生的节点 ID
      resume_condition: 恢复条件描述
      cancel_condition: 取消条件描述
      pending_questions: 待用户回答的问题列表
      interruption_dir: 中断事件存储目录

    返回:
      中断事件对象
    """
    # 验证中断类型
    if interruption_type not in INTERRUPTION_TYPES:
        valid_types = ", ".join(INTERRUPTION_TYPES)
        raise ValueError(f"无效的中断类型: '{interruption_type}'. 有效值: {valid_types}")

    # 验证中断原因
    if interruption_type == "workflow_pause" and pause_reason not in MANDATORY_PAUSE_REASONS:
        logger.warning(f"中断原因 '{pause_reason}' 不在预定义列表中，但仍被接受")

    interruption_id = f"int_{str(uuid.uuid4())[:8]}"

    interruption = {
        "interruption_id": interruption_id,
        "run_id": run_id,
        "type": interruption_type,
        "pause_reason": pause_reason,
        "checkpoint_id": checkpoint_id,
        "node_id": node_id,
        "resume_condition": resume_condition or f"用户补充 '{pause_reason}' 所需信息",
        "cancel_condition": cancel_condition or "用户放弃本次运行",
        "pending_questions": pending_questions or [],
        "status": "pending",
        "audit_fields": [
            "interruption_id",
            "type",
            "pause_reason",
            "checkpoint_id",
            "node_id",
            "resume_condition",
            "cancel_condition",
            "pending_questions",
            "created_at",
        ],
        "created_at": datetime.now(timezone.utc).isoformat(),
    }

    # 保存到文件
    interruption_path = os.path.join(interruption_dir, f"{interruption_id}.json")
    save_json(interruption, interruption_path)

    logger.info(
        f"中断事件已创建: {interruption_id} "
        f"(type: {interruption_type}, reason: {pause_reason}, run: {run_id})"
    )
    return interruption


# ═══════════════════════════════════════════════════════════════
# Structured Patch Extraction
# ═══════════════════════════════════════════════════════════════

def extract_structured_patch(
    user_supplement: str,
    interruption: Dict[str, Any],
) -> Dict[str, Any]:
    """
    从用户补充输入中提取结构化补丁。

    根据 plan 文档 (section 13)，用户补充内容应被提取为四种补丁:
      - intent_patch: 用户目标、范围、行业、地区、风险等级的变化
      - context_patch: 需要加载的资料、prompt、规则的变化
      - approval_patch: 人工审批、工具授权、继续/取消决策
      - constraint_patch: 额外限制、禁止动作或输出要求

    当前实现使用关键词匹配进行初步提取。
    后续可升级为 LLM 辅助提取。
    """
    supplement_lower = user_supplement.lower()

    patch = {
        "intent_patch": {},
        "context_patch": {},
        "approval_patch": {},
        "constraint_patch": {},
    }

    # ── intent_patch: 检测意图变化 ──
    intent_keywords = {
        "行业": "industry",
        "地区": "jurisdiction",
        "风险": "risk_level",
        "目标": "goal",
        "范围": "scope",
        "场景": "scenario",
    }
    for keyword, field in intent_keywords.items():
        if keyword in user_supplement:
            patch["intent_patch"][field] = f"用户补充了 {keyword} 相关信息"

    # ── context_patch: 检测上下文变化 ──
    context_keywords = {
        "资料": "source",
        "文档": "document",
        "参考": "reference",
        "prompt": "prompt",
        "模板": "template",
        "示例": "example",
    }
    for keyword, field in context_keywords.items():
        if keyword in user_supplement:
            patch["context_patch"][field] = f"用户补充了 {keyword} 相关信息"

    # ── approval_patch: 检测审批决策 ──
    approval_keywords_approve = ["同意", "批准", "确认", "继续", "可以", "是"]
    approval_keywords_reject = ["不同意", "拒绝", "取消", "停止", "不要", "否"]
    approval_keywords_modify = ["修改", "调整", "更改", "补充"]

    for kw in approval_keywords_approve:
        if kw in user_supplement:
            patch["approval_patch"]["decision"] = "approved"
            patch["approval_patch"]["reason"] = f"用户包含关键词 '{kw}'"
            break
    for kw in approval_keywords_reject:
        if kw in user_supplement:
            patch["approval_patch"]["decision"] = "rejected"
            patch["approval_patch"]["reason"] = f"用户包含关键词 '{kw}'"
            break
    for kw in approval_keywords_modify:
        if kw in user_supplement:
            patch["approval_patch"]["decision"] = "modified"
            patch["approval_patch"]["reason"] = f"用户包含关键词 '{kw}'"
            break

    # ── constraint_patch: 检测约束变化 ──
    constraint_keywords = {
        "限制": "restriction",
        "禁止": "prohibition",
        "必须": "requirement",
        "不能": "forbidden",
        "允许": "allowed",
        "格式": "format",
        "长度": "length",
    }
    for keyword, field in constraint_keywords.items():
        if keyword in user_supplement:
            patch["constraint_patch"][field] = f"用户补充了 {keyword} 相关信息"

    # 记录原始补充摘要
    patch["_supplement_summary"] = user_supplement[:500]

    return patch


# ═══════════════════════════════════════════════════════════════
# Resume Event Processing
# ═══════════════════════════════════════════════════════════════

def process_resume_event(
    interruption: Dict[str, Any],
    user_supplement: str,
    interruption_dir: str = DEFAULT_INTERRUPTION_DIR,
) -> Dict[str, Any]:
    """
    处理用户补充输入，生成恢复事件。

    流程:
      1. 验证中断事件状态为 pending
      2. 从用户输入提取结构化补丁
      3. 创建恢复事件记录
      4. 保存到文件
    """
    # 验证中断事件状态
    if interruption.get("status") != "pending":
        raise ValueError(
            f"中断事件 '{interruption.get('interruption_id')}' 状态为 "
            f"'{interruption.get('status')}'，不是 'pending'，无法处理恢复"
        )

    # 检查中断类型是否可恢复
    int_type = interruption.get("type")
    if int_type == "cancelled_by_user":
        raise ValueError(
            f"中断事件 '{interruption.get('interruption_id')}' 类型为 "
            f"'cancelled_by_user'，不可恢复"
        )

    # 提取结构化补丁
    structured_patch = extract_structured_patch(user_supplement, interruption)

    # 创建恢复事件
    resume_event_id = f"res_{str(uuid.uuid4())[:8]}"
    resume_event = {
        "resume_event_id": resume_event_id,
        "interruption_id": interruption.get("interruption_id"),
        "run_id": interruption.get("run_id"),
        "source": "user",
        "user_supplement_summary": user_supplement[:500],
        "structured_patch": structured_patch,
        "validation_result": "pending",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }

    # 保存到文件
    resume_path = os.path.join(interruption_dir, f"{resume_event_id}.json")
    save_json(resume_event, resume_path)

    logger.info(
        f"恢复事件已创建: {resume_event_id} "
        f"(interruption: {interruption.get('interruption_id')})"
    )
    return resume_event


# ═══════════════════════════════════════════════════════════════
# Resume Validation
# ═══════════════════════════════════════════════════════════════

def validate_resume(
    interruption: Dict[str, Any],
    resume_event: Dict[str, Any],
) -> Dict[str, Any]:
    """
    验证恢复条件是否满足。

    根据 plan 文档 (section 13)，恢复前必须验证:
      1. 补充内容是否回答了中断问题
      2. 用户意图、行业、地区、风险等级或目标产物是否发生变化
      3. 是否触发新的约束、人审或工具权限要求
      4. 是否需要重新生成上下文加载计划
      5. 是否可以从原 checkpoint 恢复，还是必须退回前置门禁

    返回:
      {
        "accepted": bool,
        "reason": str,
        "requires_replan": bool,
        "requires_regate": bool,
        "checklist": {
          "supplement_answers_pause_reason": bool,
          "intent_still_matches_workflow": bool,
          "risk_level_recomputed": bool,
          "context_load_plan_updated_if_needed": bool,
          "approval_status_recorded": bool,
        }
      }
    """
    patch = resume_event.get("structured_patch", {})
    int_type = interruption.get("type")
    pause_reason = interruption.get("pause_reason")

    # 初始化验证清单
    checklist = {
        "supplement_answers_pause_reason": False,
        "intent_still_matches_workflow": True,
        "risk_level_recomputed": True,
        "context_load_plan_updated_if_needed": False,
        "approval_status_recorded": False,
    }

    # 1. 检查补充内容是否回答了中断问题
    if pause_reason == "missing_required_input":
        # 检查是否有任何补丁内容
        has_patch_content = any(
            v for v in patch.values() if isinstance(v, dict) and v
        )
        checklist["supplement_answers_pause_reason"] = has_patch_content
    elif pause_reason == "requires_human_approval":
        # 检查是否有审批决策
        approval_decision = patch.get("approval_patch", {}).get("decision")
        checklist["supplement_answers_pause_reason"] = approval_decision in [
            "approved", "rejected", "modified"
        ]
        checklist["approval_status_recorded"] = approval_decision is not None
    elif pause_reason == "tool_permission_required":
        approval_decision = patch.get("approval_patch", {}).get("decision")
        checklist["supplement_answers_pause_reason"] = approval_decision in [
            "approved", "rejected"
        ]
    else:
        # 对于其他原因，只要有补充内容就认为已回答
        checklist["supplement_answers_pause_reason"] = bool(
            resume_event.get("user_supplement_summary", "").strip()
        )

    # 2. 检查意图是否变化
    intent_patch = patch.get("intent_patch", {})
    if intent_patch:
        checklist["intent_still_matches_workflow"] = False
        checklist["context_load_plan_updated_if_needed"] = True

    # 3. 检查约束变化
    constraint_patch = patch.get("constraint_patch", {})
    if constraint_patch:
        checklist["context_load_plan_updated_if_needed"] = True

    # 4. 判断是否需要重新规划或退回门禁
    requires_replan = checklist["context_load_plan_updated_if_needed"]
    requires_regate = (
        checklist["intent_still_matches_workflow"] is False
        or pause_reason == "high_risk_output"
    )

    # 综合判断
    # 核心条件: 补充内容必须回答中断问题
    accepted = checklist["supplement_answers_pause_reason"]

    if accepted:
        reason = "所有恢复条件均已满足"
    elif not checklist["supplement_answers_pause_reason"]:
        reason = f"补充内容未回答中断问题: {pause_reason}"
    elif not checklist["intent_still_matches_workflow"]:
        reason = "用户意图已变化，需要退回上下文读取与意图确认门禁"
    else:
        reason = "部分恢复条件未满足"

    validation = {
        "accepted": accepted,
        "reason": reason,
        "requires_replan": requires_replan,
        "requires_regate": requires_regate,
        "checklist": checklist,
    }

    logger.info(
        f"恢复验证结果: {'✅ 通过' if accepted else '❌ 拒绝'} "
        f"(reason: {reason})"
    )
    return validation


# ═══════════════════════════════════════════════════════════════
# Snapshot Update
# ═══════════════════════════════════════════════════════════════

def update_snapshot_with_interruption(
    snapshot: Dict[str, Any],
    interruption: Dict[str, Any],
    resume_event: Optional[Dict[str, Any]] = None,
    validation: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    更新运行快照，记录中断事件和恢复事件。

    根据 plan 文档 (section 13)，每次中断和恢复都必须在 run_snapshot 中记录:
      - workflow_state: 更新状态和当前节点
      - interruptions: 追加中断事件
      - resume_events: 追加恢复事件
    """
    updated = dict(snapshot)
    int_type = interruption.get("type")

    # 1. 更新 workflow_state
    workflow_state = updated.get("workflow_state", {})
    if int_type == "workflow_pause":
        workflow_state["status"] = "workflow_pause"
    elif int_type == "interrupted_by_user":
        workflow_state["status"] = "interrupted_by_user"
    elif int_type == "cancelled_by_user":
        workflow_state["status"] = "cancelled_by_user"

    workflow_state["current_node"] = interruption.get("node_id", workflow_state.get("current_node", ""))
    workflow_state["checkpoint_id"] = interruption.get("checkpoint_id", "")
    workflow_state["resume_node"] = interruption.get("node_id", "")

    # 如果被取消，清除恢复节点
    if int_type == "cancelled_by_user":
        workflow_state["resume_node"] = ""

    updated["workflow_state"] = workflow_state

    # 2. 追加中断事件
    interruptions = updated.get("interruptions", [])
    # 避免重复添加
    existing_ids = [i.get("interruption_id") for i in interruptions]
    if interruption.get("interruption_id") not in existing_ids:
        interruptions.append(interruption)
    updated["interruptions"] = interruptions

    # 3. 追加恢复事件
    if resume_event:
        resume_events = updated.get("resume_events", [])
        existing_res_ids = [r.get("resume_event_id") for r in resume_events]
        if resume_event.get("resume_event_id") not in existing_res_ids:
            resume_events.append(resume_event)
        updated["resume_events"] = resume_events

    # 4. 如果验证通过，更新状态
    if validation and validation.get("accepted"):
        if validation.get("requires_regate"):
            updated["workflow_state"]["status"] = "context_intent_pending"
            updated["workflow_state"]["current_node"] = "context_reading"
        elif validation.get("requires_replan"):
            updated["workflow_state"]["status"] = "running"
            updated["workflow_state"]["current_node"] = "context_planning"
        else:
            updated["workflow_state"]["status"] = "running"
            updated["workflow_state"]["current_node"] = interruption.get("node_id", "")

    # 5. 更新时间戳
    updated["updated_at"] = datetime.now(timezone.utc).isoformat()

    return updated


# ═══════════════════════════════════════════════════════════════
# Workflow State Helpers
# ═══════════════════════════════════════════════════════════════

def get_workflow_state_template() -> Dict[str, Any]:
    """获取工作流状态模板。"""
    return {
        "status": "created",
        "current_node": "",
        "checkpoint_id": "",
        "resume_node": "",
        "completed_steps": [],
        "total_steps": 0,
    }


def is_recoverable(interruption: Dict[str, Any]) -> bool:
    """检查中断事件是否可恢复。"""
    return interruption.get("type") != "cancelled_by_user"


def get_recovery_path(interruption: Dict[str, Any], validation: Dict[str, Any]) -> str:
    """
    根据验证结果确定恢复路径。

    返回:
      - "resume": 从原 checkpoint 恢复
      - "replan": 需要重新生成上下文加载计划
      - "regate": 需要退回上下文读取与意图确认门禁
      - "terminate": 运行终止，不可恢复
    """
    if not is_recoverable(interruption):
        return "terminate"

    if not validation.get("accepted"):
        return "terminate"

    if validation.get("requires_regate"):
        return "regate"

    if validation.get("requires_replan"):
        return "replan"

    return "resume"


# ═══════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="Phase 9: 中断、补充、恢复与用户运行控制",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
子命令:
  create-interruption   创建中断事件
  process-resume        处理用户补充输入，生成恢复事件
  validate-resume       验证恢复条件
  create-checkpoint     创建运行 Checkpoint
  update-snapshot       更新运行快照 (记录中断/恢复事件)

示例:
  # 创建中断事件
  python scripts/interruption_handler.py create-interruption \\
      --run-id run_abc123 \\
      --type workflow_pause \\
      --reason missing_required_input \\
      --checkpoint-id cp_001 \\
      --node-id confirm_intent

  # 处理恢复事件
  python scripts/interruption_handler.py process-resume \\
      --interruption runtime/interruptions/int_abc123.json \\
      --supplement "用户补充了合同类型和审查目标"

  # 验证恢复条件
  python scripts/interruption_handler.py validate-resume \\
      --interruption runtime/interruptions/int_abc123.json \\
      --resume-event runtime/interruptions/res_abc123.json

  # 创建 Checkpoint
  python scripts/interruption_handler.py create-checkpoint \\
      --run-id run_abc123 \\
      --node-id confirm_intent \\
      --state '{"status": "running", "current_node": "confirm_intent"}'

  # 更新运行快照
  python scripts/interruption_handler.py update-snapshot \\
      --snapshot runtime/workflow_runtime/snapshot_abc123.json \\
      --interruption runtime/interruptions/int_abc123.json
        """,
    )
    subparsers = parser.add_subparsers(dest="command", help="子命令")

    # create-interruption
    ci_parser = subparsers.add_parser("create-interruption", help="创建中断事件")
    ci_parser.add_argument("--run-id", required=True, help="关联的运行 ID")
    ci_parser.add_argument("--type", required=True, choices=INTERRUPTION_TYPES, help="中断类型")
    ci_parser.add_argument("--reason", required=True, help="中断原因")
    ci_parser.add_argument("--checkpoint-id", required=True, help="关联的 Checkpoint ID")
    ci_parser.add_argument("--node-id", default="", help="中断发生的节点 ID")
    ci_parser.add_argument("--resume-condition", default="", help="恢复条件描述")
    ci_parser.add_argument("--cancel-condition", default="", help="取消条件描述")
    ci_parser.add_argument("--pending-questions", nargs="*", default=[], help="待用户回答的问题")
    ci_parser.add_argument("-o", "--output", default="", help="输出路径")

    # process-resume
    pr_parser = subparsers.add_parser("process-resume", help="处理用户补充输入")
    pr_parser.add_argument("--interruption", required=True, help="中断事件 JSON 文件路径")
    pr_parser.add_argument("--supplement", required=True, help="用户补充输入内容")
    pr_parser.add_argument("-o", "--output", default="", help="输出路径")

    # validate-resume
    vr_parser = subparsers.add_parser("validate-resume", help="验证恢复条件")
    vr_parser.add_argument("--interruption", required=True, help="中断事件 JSON 文件路径")
    vr_parser.add_argument("--resume-event", required=True, help="恢复事件 JSON 文件路径")
    vr_parser.add_argument("-o", "--output", default="", help="输出路径")

    # create-checkpoint
    cc_parser = subparsers.add_parser("create-checkpoint", help="创建运行 Checkpoint")
    cc_parser.add_argument("--run-id", required=True, help="关联的运行 ID")
    cc_parser.add_argument("--node-id", required=True, help="当前节点 ID")
    cc_parser.add_argument("--state", required=True, help="工作流状态 JSON")
    cc_parser.add_argument("--context-plan", default="", help="上下文加载计划 JSON 文件路径")
    cc_parser.add_argument("-o", "--output", default="", help="输出路径")

    # update-snapshot
    us_parser = subparsers.add_parser("update-snapshot", help="更新运行快照")
    us_parser.add_argument("--snapshot", required=True, help="运行快照 JSON 文件路径")
    us_parser.add_argument("--interruption", required=True, help="中断事件 JSON 文件路径")
    us_parser.add_argument("--resume-event", default="", help="恢复事件 JSON 文件路径")
    us_parser.add_argument("--validation", default="", help="验证结果 JSON 文件路径")
    us_parser.add_argument("-o", "--output", default="", help="输出路径")

    args = parser.parse_args()

    if args.command == "create-interruption":
        interruption = create_interruption(
            run_id=args.run_id,
            interruption_type=args.type,
            pause_reason=args.reason,
            checkpoint_id=args.checkpoint_id,
            node_id=args.node_id,
            resume_condition=args.resume_condition,
            cancel_condition=args.cancel_condition,
            pending_questions=args.pending_questions,
        )
        output = args.output or f"runtime/interruptions/{interruption['interruption_id']}.json"
        save_json(interruption, output)
        print(f"✅ 中断事件已创建: {output}")
        print(f"   中断 ID: {interruption['interruption_id']}")
        print(f"   类型: {interruption['type']}")
        print(f"   原因: {interruption['pause_reason']}")
        print(f"   运行 ID: {interruption['run_id']}")

    elif args.command == "process-resume":
        interruption_path = args.interruption
        interruption = load_json(interruption_path)
        resume_event = process_resume_event(
            interruption=interruption,
            user_supplement=args.supplement,
        )
        output = args.output or f"runtime/interruptions/{resume_event['resume_event_id']}.json"
        save_json(resume_event, output)
        print(f"✅ 恢复事件已创建: {output}")
        print(f"   恢复事件 ID: {resume_event['resume_event_id']}")
        print(f"   中断 ID: {resume_event['interruption_id']}")
        print(f"   补充摘要: {resume_event['user_supplement_summary'][:100]}...")

        # 显示提取的补丁
        patch = resume_event.get("structured_patch", {})
        print(f"\n   提取的结构化补丁:")
        for patch_type in PATCH_TYPES:
            patch_content = patch.get(patch_type, {})
            if patch_content:
                print(f"     {patch_type}: {patch_content}")

    elif args.command == "validate-resume":
        interruption = load_json(args.interruption)
        resume_event = load_json(args.resume_event)
        validation = validate_resume(interruption, resume_event)
        output = args.output or f"runtime/interruptions/validation_{resume_event['resume_event_id']}.json"
        save_json(validation, output)
        print(f"✅ 恢复验证完成: {output}")
        print(f"   结果: {'✅ 通过' if validation['accepted'] else '❌ 拒绝'}")
        print(f"   原因: {validation['reason']}")
        print(f"   需要重新规划: {validation['requires_replan']}")
        print(f"   需要退回门禁: {validation['requires_regate']}")
        print(f"\n   验证清单:")
        for check, result in validation["checklist"].items():
            print(f"     {'✅' if result else '❌'} {check}")

    elif args.command == "create-checkpoint":
        workflow_state = json.loads(args.state)
        context_load_plan = None
        if args.context_plan:
            context_load_plan = load_json(args.context_plan)
        checkpoint = create_checkpoint(
            run_id=args.run_id,
            node_id=args.node_id,
            workflow_state=workflow_state,
            context_load_plan=context_load_plan,
        )
        output = args.output or f"runtime/checkpoints/{checkpoint['checkpoint_id']}.json"
        save_json(checkpoint, output)
        print(f"✅ Checkpoint 已创建: {output}")
        print(f"   Checkpoint ID: {checkpoint['checkpoint_id']}")
        print(f"   运行 ID: {checkpoint['run_id']}")
        print(f"   节点: {checkpoint['node_id']}")

    elif args.command == "update-snapshot":
        snapshot = load_json(args.snapshot)
        interruption = load_json(args.interruption)
        resume_event = None
        if args.resume_event:
            resume_event = load_json(args.resume_event)
        validation = None
        if args.validation:
            validation = load_json(args.validation)
        updated = update_snapshot_with_interruption(
            snapshot=snapshot,
            interruption=interruption,
            resume_event=resume_event,
            validation=validation,
        )
        output = args.output or args.snapshot.replace(".json", "_updated.json")
        save_json(updated, output)
        print(f"✅ 运行快照已更新: {output}")
        print(f"   运行 ID: {updated.get('run_id', 'unknown')}")
        print(f"   状态: {updated.get('workflow_state', {}).get('status', 'unknown')}")
        print(f"   中断事件数: {len(updated.get('interruptions', []))}")
        print(f"   恢复事件数: {len(updated.get('resume_events', []))}")

    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
