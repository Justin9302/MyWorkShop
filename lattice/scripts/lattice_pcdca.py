#!/usr/bin/env python3
"""
lattice_pcdca.py — LatticeWork PCDCA 循环执行器

职责:
  1. 管理 PCDCA 循环生命周期
  2. 记录每个阶段的详细数据
  3. 支持循环重试和阻塞升级
  4. 生成循环审计轨迹

PCDCA 循环:
  P (Plan)           → 识别阻塞 + 制定执行计划
  C (Check-HITL)     → 人工审核计划 (Pass/Fail)
  D (Do)             → 执行计划中的步骤
  C (Check)          → 验证产物是否符合验收标准 (Pass/Fail)
  A (Action)         → Pass→标记完成 | Fail→回退到Plan | Blocked→暂停

用法:
  # 开始PCDCA循环
  python lattice/scripts/lattice_pcdca.py start \\
      --task-id task_0001

  # 记录Plan阶段
  python lattice/scripts/lattice_pcdca.py plan \\
      --cycle-id cycle_001 \\
      --plan-summary "实现三次样条插值算法" \\
      --steps-planned 3

  # 记录Plan-Check阶段 (人工审核)
  python lattice/scripts/lattice_pcdca.py plan-check \\
      --cycle-id cycle_001 \\
      --result pass

  # 记录Do阶段
  python lattice/scripts/lattice_pcdca.py do \\
      --cycle-id cycle_001 \\
      --step-id step_01 \\
      --action write_to_file \\
      --status success

  # 记录Check阶段
  python lattice/scripts/lattice_pcdca.py check \\
      --cycle-id cycle_001 \\
      --result pass

  # 记录Action阶段
  python lattice/scripts/lattice_pcdca.py action \\
      --cycle-id cycle_001 \\
      --decision proceed

  # 查看循环状态
  python lattice/scripts/lattice_pcdca.py status \\
      --cycle-id cycle_001
"""

import argparse
import json
import logging
import os
import sys
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

# ═══════════════════════════════════════════════════════════════
# Constants
# ═══════════════════════════════════════════════════════════════

LATTICE_DIR = os.path.join(os.path.dirname(__file__), "..")
PCDCA_LOG_DIR = os.path.join(LATTICE_DIR, "lattice_runtime", "pcdca_log")

# PCDCA 阶段
PCDCA_PHASES = ["plan", "plan_check", "do", "check", "action"]

# 决策类型
PCDCA_DECISIONS = ["proceed", "retry", "block", "escalate", "skip"]

# 检查结果
CHECK_RESULTS = ["pass", "fail"]

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("lattice_pcdca")


# ═══════════════════════════════════════════════════════════════
# PCDCA Cycle Management
# ═══════════════════════════════════════════════════════════════

def _cycle_path(cycle_id: str) -> str:
    """获取循环记录文件路径。"""
    return os.path.join(PCDCA_LOG_DIR, f"{cycle_id}.json")


def _load_cycle(cycle_id: str) -> Dict[str, Any]:
    """加载循环记录。"""
    path = _cycle_path(cycle_id)
    if not os.path.exists(path):
        raise FileNotFoundError(f"PCDCA循环不存在: {cycle_id}")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _save_cycle(cycle: Dict[str, Any]) -> None:
    """保存循环记录。"""
    os.makedirs(PCDCA_LOG_DIR, exist_ok=True)
    path = _cycle_path(cycle["cycle_id"])
    with open(path, "w", encoding="utf-8") as f:
        json.dump(cycle, f, indent=2, ensure_ascii=False)


def start_cycle(task_id: str, cycle_number: int = 1) -> Dict[str, Any]:
    """
    开始新的 PCDCA 循环。

    参数:
      task_id: 原子任务ID
      cycle_number: 循环次数（第几次PCDCA）
    """
    now = datetime.now(timezone.utc).isoformat()
    cycle_id = f"cycle_{str(uuid.uuid4())[:8]}"

    cycle = {
        "cycle_id": cycle_id,
        "task_id": task_id,
        "cycle_number": cycle_number,
        "phases": {
            "plan": {
                "blockers_identified": [],
                "plan_summary": "",
                "steps_planned": 0,
            },
            "plan_check": {
                "reviewer": "human",
                "result": "pending",
                "feedback": None,
                "reviewed_at": None,
            },
            "do": {
                "steps_executed": [],
                "artifacts_produced": [],
            },
            "check": {
                "validation_results": [],
                "result": "pending",
                "fail_reason": None,
            },
            "action": {
                "decision": "pending",
                "decision_reason": "",
                "next_cycle_plan": None,
            },
        },
        "result": "in_progress",
        "timestamp": {
            "started_at": now,
            "completed_at": None,
        },
    }

    _save_cycle(cycle)
    logger.info(f"PCDCA循环已开始: {cycle_id} (task: {task_id}, cycle: {cycle_number})")
    return cycle


def record_plan(
    cycle_id: str,
    plan_summary: str,
    steps_planned: int,
    blockers: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """记录 Plan 阶段。"""
    cycle = _load_cycle(cycle_id)
    cycle["phases"]["plan"] = {
        "blockers_identified": blockers or [],
        "plan_summary": plan_summary,
        "steps_planned": steps_planned,
    }
    _save_cycle(cycle)
    logger.info(f"Plan阶段已记录: {cycle_id}")
    return cycle


def record_plan_check(
    cycle_id: str,
    result: str,
    reviewer: str = "human",
    feedback: Optional[str] = None,
) -> Dict[str, Any]:
    """记录 Plan-Check 阶段（人工审核）。"""
    if result not in CHECK_RESULTS:
        raise ValueError(f"无效的审核结果: {result}")

    cycle = _load_cycle(cycle_id)
    cycle["phases"]["plan_check"] = {
        "reviewer": reviewer,
        "result": result,
        "feedback": feedback,
        "reviewed_at": datetime.now(timezone.utc).isoformat(),
    }
    _save_cycle(cycle)
    logger.info(f"Plan-Check阶段已记录: {cycle_id} → {result}")
    return cycle


def record_do_step(
    cycle_id: str,
    step_id: str,
    action: str,
    status: str,
    output_summary: Optional[str] = None,
    artifacts: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """记录 Do 阶段的一个步骤。"""
    if status not in ["success", "failed", "skipped"]:
        raise ValueError(f"无效的步骤状态: {status}")

    cycle = _load_cycle(cycle_id)
    cycle["phases"]["do"]["steps_executed"].append({
        "step_id": step_id,
        "action": action,
        "status": status,
        "output_summary": output_summary or "",
    })

    if artifacts:
        cycle["phases"]["do"]["artifacts_produced"].extend(artifacts)

    _save_cycle(cycle)
    logger.info(f"Do步骤已记录: {cycle_id}/{step_id} → {status}")
    return cycle


def record_check(
    cycle_id: str,
    result: str,
    validation_results: Optional[List[Dict[str, Any]]] = None,
    fail_reason: Optional[str] = None,
) -> Dict[str, Any]:
    """记录 Check 阶段。"""
    if result not in CHECK_RESULTS:
        raise ValueError(f"无效的检查结果: {result}")

    cycle = _load_cycle(cycle_id)
    cycle["phases"]["check"] = {
        "validation_results": validation_results or [],
        "result": result,
        "fail_reason": fail_reason,
    }
    _save_cycle(cycle)
    logger.info(f"Check阶段已记录: {cycle_id} → {result}")
    return cycle


def record_action(
    cycle_id: str,
    decision: str,
    decision_reason: str = "",
    next_cycle_plan: Optional[str] = None,
) -> Dict[str, Any]:
    """记录 Action 阶段。"""
    if decision not in PCDCA_DECISIONS:
        raise ValueError(f"无效的决策: {decision}")

    cycle = _load_cycle(cycle_id)

    # 映射决策到循环结果
    result_map = {
        "proceed": "pass",
        "retry": "fail",
        "block": "blocked",
        "escalate": "escalated",
        "skip": "pass",
    }

    cycle["phases"]["action"] = {
        "decision": decision,
        "decision_reason": decision_reason,
        "next_cycle_plan": next_cycle_plan,
    }
    cycle["result"] = result_map.get(decision, "in_progress")
    cycle["timestamp"]["completed_at"] = datetime.now(timezone.utc).isoformat()

    _save_cycle(cycle)
    logger.info(f"Action阶段已记录: {cycle_id} → {decision} (result: {cycle['result']})")
    return cycle


def get_cycle_status(cycle_id: str) -> Dict[str, Any]:
    """获取循环状态摘要。"""
    cycle = _load_cycle(cycle_id)
    return {
        "cycle_id": cycle["cycle_id"],
        "task_id": cycle["task_id"],
        "cycle_number": cycle["cycle_number"],
        "result": cycle["result"],
        "phases_completed": [
            phase for phase in PCDCA_PHASES
            if cycle["phases"][phase].get("result") != "pending"
            or cycle["phases"][phase].get("decision") != "pending"
            or cycle["phases"][phase].get("steps_executed", [])
        ],
        "timestamp": cycle["timestamp"],
    }


def get_task_cycles(task_id: str) -> List[Dict[str, Any]]:
    """获取指定任务的所有循环。"""
    if not os.path.exists(PCDCA_LOG_DIR):
        return []

    cycles = []
    for filename in os.listdir(PCDCA_LOG_DIR):
        if filename.endswith(".json"):
            path = os.path.join(PCDCA_LOG_DIR, filename)
            with open(path, "r", encoding="utf-8") as f:
                cycle = json.load(f)
                if cycle.get("task_id") == task_id:
                    cycles.append(cycle)

    return sorted(cycles, key=lambda c: c.get("cycle_number", 0))


# ═══════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="LatticeWork PCDCA 循环执行器",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="command", help="子命令")

    # start
    start_parser = subparsers.add_parser("start", help="开始新的PCDCA循环")
    start_parser.add_argument("--task-id", required=True, help="原子任务ID")
    start_parser.add_argument("--cycle-number", type=int, default=1, help="循环次数")

    # plan
    plan_parser = subparsers.add_parser("plan", help="记录Plan阶段")
    plan_parser.add_argument("--cycle-id", required=True, help="循环ID")
    plan_parser.add_argument("--plan-summary", required=True, help="计划摘要")
    plan_parser.add_argument("--steps-planned", type=int, required=True, help="计划步骤数")
    plan_parser.add_argument("--blockers", default=None, help="阻塞点JSON (可选)")

    # plan-check
    pc_parser = subparsers.add_parser("plan-check", help="记录Plan-Check阶段")
    pc_parser.add_argument("--cycle-id", required=True, help="循环ID")
    pc_parser.add_argument("--result", required=True, choices=CHECK_RESULTS, help="审核结果")
    pc_parser.add_argument("--reviewer", default="human", help="审核者")
    pc_parser.add_argument("--feedback", default=None, help="审核反馈")

    # do
    do_parser = subparsers.add_parser("do", help="记录Do阶段步骤")
    do_parser.add_argument("--cycle-id", required=True, help="循环ID")
    do_parser.add_argument("--step-id", required=True, help="步骤ID")
    do_parser.add_argument("--action", required=True, help="执行动作")
    do_parser.add_argument("--status", required=True, choices=["success", "failed", "skipped"], help="步骤状态")
    do_parser.add_argument("--output-summary", default=None, help="输出摘要")
    do_parser.add_argument("--artifacts", nargs="*", default=None, help="产出物列表")

    # check
    check_parser = subparsers.add_parser("check", help="记录Check阶段")
    check_parser.add_argument("--cycle-id", required=True, help="循环ID")
    check_parser.add_argument("--result", required=True, choices=CHECK_RESULTS, help="检查结果")
    check_parser.add_argument("--fail-reason", default=None, help="失败原因")

    # action
    action_parser = subparsers.add_parser("action", help="记录Action阶段")
    action_parser.add_argument("--cycle-id", required=True, help="循环ID")
    action_parser.add_argument("--decision", required=True, choices=PCDCA_DECISIONS, help="决策")
    action_parser.add_argument("--decision-reason", default="", help="决策原因")
    action_parser.add_argument("--next-cycle-plan", default=None, help="下次循环计划")

    # status
    status_parser = subparsers.add_parser("status", help="查看循环状态")
    status_parser.add_argument("--cycle-id", required=True, help="循环ID")

    # task-cycles
    tc_parser = subparsers.add_parser("task-cycles", help="查看任务的所有循环")
    tc_parser.add_argument("--task-id", required=True, help="任务ID")

    args = parser.parse_args()

    if args.command == "start":
        cycle = start_cycle(args.task_id, args.cycle_number)
        print(f"✅ PCDCA循环已开始: {cycle['cycle_id']}")
        print(f"   任务: {cycle['task_id']}")
        print(f"   循环次数: {cycle['cycle_number']}")

    elif args.command == "plan":
        blockers = json.loads(args.blockers) if args.blockers else None
        cycle = record_plan(args.cycle_id, args.plan_summary, args.steps_planned, blockers)
        print(f"✅ Plan阶段已记录: {args.cycle_id}")
        print(f"   计划摘要: {args.plan_summary[:80]}...")
        print(f"   步骤数: {args.steps_planned}")

    elif args.command == "plan-check":
        cycle = record_plan_check(args.cycle_id, args.result, args.reviewer, args.feedback)
        result_str = "✅ 通过" if args.result == "pass" else "❌ 拒绝"
        print(f"✅ Plan-Check阶段已记录: {args.cycle_id} → {result_str}")

    elif args.command == "do":
        cycle = record_do_step(
            args.cycle_id, args.step_id, args.action,
            args.status, args.output_summary, args.artifacts,
        )
        status_icon = {"success": "✅", "failed": "❌", "skipped": "⏭️"}
        print(f"{status_icon.get(args.status, '❓')} Do步骤已记录: {args.cycle_id}/{args.step_id} → {args.status}")

    elif args.command == "check":
        cycle = record_check(args.cycle_id, args.result, fail_reason=args.fail_reason)
        result_str = "✅ 通过" if args.result == "pass" else "❌ 失败"
        print(f"✅ Check阶段已记录: {args.cycle_id} → {result_str}")
        if args.fail_reason:
            print(f"   失败原因: {args.fail_reason}")

    elif args.command == "action":
        cycle = record_action(args.cycle_id, args.decision, args.decision_reason, args.next_cycle_plan)
        decision_icon = {
            "proceed": "✅", "retry": "🔄", "block": "⛔",
            "escalate": "⬆️", "skip": "⏭️",
        }
        print(f"{decision_icon.get(args.decision, '❓')} Action阶段已记录: {args.cycle_id} → {args.decision}")
        print(f"   循环结果: {cycle['result']}")

    elif args.command == "status":
        status = get_cycle_status(args.cycle_id)
        print(f"📋 PCDCA循环状态: {status['cycle_id']}")
        print(f"   任务: {status['task_id']}")
        print(f"   循环次数: {status['cycle_number']}")
        print(f"   结果: {status['result']}")
        print(f"   已完成阶段: {', '.join(status['phases_completed']) or '无'}")
        print(f"   开始时间: {status['timestamp']['started_at']}")
        print(f"   完成时间: {status['timestamp']['completed_at'] or '进行中'}")

    elif args.command == "task-cycles":
        cycles = get_task_cycles(args.task_id)
        print(f"📋 任务 '{args.task_id}' 的PCDCA循环 ({len(cycles)} 个):")
        for c in cycles:
            print(f"   - {c['cycle_id']} (第{c['cycle_number']}次) → {c['result']}")

    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
