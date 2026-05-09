#!/usr/bin/env python3
"""
lattice_blocker.py — LatticeWork 阻塞点管理器

职责:
  1. 注册阻塞点 (已知/发现/隐含)
  2. 追踪阻塞点状态 (open → in_progress → resolved/escalated)
  3. 阻塞点升级到人工处理
  4. 生成阻塞点报告

用法:
  # 注册阻塞点
  python lattice/scripts/lattice_blocker.py register \\
      --type discovered \\
      --description "需要Bloomberg API访问权限" \\
      --severity blocking \\
      --affected-tasks task_0009

  # 查看阻塞点状态
  python lattice/scripts/lattice_blocker.py status \\
      --blocker-id blocker_001

  # 解决阻塞点
  python lattice/scripts/lattice_blocker.py resolve \\
      --blocker-id blocker_001 \\
      --resolution "使用本地缓存的历史数据替代"

  # 升级阻塞点
  python lattice/scripts/lattice_blocker.py escalate \\
      --blocker-id blocker_001 \\
      --escalate-to human

  # 生成阻塞点报告
  python lattice/scripts/lattice_blocker.py report
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
RUNTIME_DIR = os.path.join(LATTICE_DIR, "lattice_runtime")
BLOCKER_REGISTRY_PATH = os.path.join(RUNTIME_DIR, "blocker_registry.json")

BLOCKER_TYPES = ["known", "discovered", "implicit"]
BLOCKER_SEVERITIES = ["low", "medium", "high", "blocking"]
BLOCKER_STATUSES = ["open", "in_progress", "resolved", "escalated", "workaround"]

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("lattice_blocker")


# ═══════════════════════════════════════════════════════════════
# Blocker Registry
# ═══════════════════════════════════════════════════════════════

def _load_registry() -> Dict[str, Any]:
    """加载阻塞点注册表。"""
    if os.path.exists(BLOCKER_REGISTRY_PATH):
        with open(BLOCKER_REGISTRY_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"blockers": [], "last_updated": None}


def _save_registry(registry: Dict[str, Any]) -> None:
    """保存阻塞点注册表。"""
    os.makedirs(os.path.dirname(BLOCKER_REGISTRY_PATH), exist_ok=True)
    registry["last_updated"] = datetime.now(timezone.utc).isoformat()
    with open(BLOCKER_REGISTRY_PATH, "w", encoding="utf-8") as f:
        json.dump(registry, f, indent=2, ensure_ascii=False)


def register_blocker(
    blocker_type: str,
    description: str,
    severity: str,
    affected_tasks: Optional[List[str]] = None,
    affected_layer: Optional[int] = None,
    discovered_in_cycle: Optional[str] = None,
    resolution: Optional[str] = None,
    workaround: Optional[str] = None,
) -> Dict[str, Any]:
    """
    注册阻塞点。

    参数:
      blocker_type: 类型 (known/discovered/implicit)
      description: 描述
      severity: 严重程度 (low/medium/high/blocking)
      affected_tasks: 受影响的任务ID列表
      affected_layer: 受影响的层级
      discovered_in_cycle: 在哪个PCDCA循环中发现
      resolution: 解决方案
      workaround: 临时绕过方案
    """
    if blocker_type not in BLOCKER_TYPES:
        raise ValueError(f"无效的阻塞点类型: {blocker_type}")
    if severity not in BLOCKER_SEVERITIES:
        raise ValueError(f"无效的严重程度: {severity}")

    blocker_id = f"blocker_{str(uuid.uuid4())[:8]}"
    now = datetime.now(timezone.utc).isoformat()

    blocker = {
        "blocker_id": blocker_id,
        "type": blocker_type,
        "description": description,
        "severity": severity,
        "status": "open",
        "affected_tasks": affected_tasks or [],
        "affected_layer": affected_layer,
        "resolution": resolution,
        "workaround": workaround,
        "escalation": None,
        "discovered_at": now if blocker_type in ("discovered", "implicit") else None,
        "discovered_in_cycle": discovered_in_cycle,
        "resolved_at": None,
        "notes": [],
    }

    registry = _load_registry()
    registry["blockers"].append(blocker)
    _save_registry(registry)

    logger.info(f"阻塞点已注册: {blocker_id} ({blocker_type}/{severity})")
    return blocker


def update_blocker_status(blocker_id: str, new_status: str) -> Optional[Dict[str, Any]]:
    """更新阻塞点状态。"""
    if new_status not in BLOCKER_STATUSES:
        raise ValueError(f"无效的状态: {new_status}")

    registry = _load_registry()
    for blocker in registry["blockers"]:
        if blocker["blocker_id"] == blocker_id:
            old_status = blocker["status"]
            blocker["status"] = new_status

            if new_status == "resolved":
                blocker["resolved_at"] = datetime.now(timezone.utc).isoformat()

            _save_registry(registry)
            logger.info(f"阻塞点状态更新: {blocker_id} {old_status} → {new_status}")
            return blocker

    logger.error(f"阻塞点不存在: {blocker_id}")
    return None


def escalate_blocker(
    blocker_id: str,
    escalate_to: str = "human",
    resolution_provided: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """升级阻塞点到人工处理。"""
    registry = _load_registry()
    for blocker in registry["blockers"]:
        if blocker["blocker_id"] == blocker_id:
            blocker["status"] = "escalated"
            blocker["escalation"] = {
                "escalated_to": escalate_to,
                "escalated_at": datetime.now(timezone.utc).isoformat(),
                "resolution_provided": resolution_provided,
            }
            _save_registry(registry)
            logger.info(f"阻塞点已升级: {blocker_id} → {escalate_to}")
            return blocker

    logger.error(f"阻塞点不存在: {blocker_id}")
    return None


def get_blocker(blocker_id: str) -> Optional[Dict[str, Any]]:
    """获取阻塞点详情。"""
    registry = _load_registry()
    for blocker in registry["blockers"]:
        if blocker["blocker_id"] == blocker_id:
            return blocker
    return None


def get_blockers_by_status(status: str) -> List[Dict[str, Any]]:
    """按状态获取阻塞点列表。"""
    registry = _load_registry()
    return [b for b in registry["blockers"] if b["status"] == status]


def get_blockers_by_severity(severity: str) -> List[Dict[str, Any]]:
    """按严重程度获取阻塞点列表。"""
    registry = _load_registry()
    return [b for b in registry["blockers"] if b["severity"] == severity]


def get_blockers_by_task(task_id: str) -> List[Dict[str, Any]]:
    """获取影响指定任务的阻塞点。"""
    registry = _load_registry()
    return [b for b in registry["blockers"] if task_id in b.get("affected_tasks", [])]


def generate_blocker_report() -> Dict[str, Any]:
    """生成阻塞点报告。"""
    registry = _load_registry()
    blockers = registry["blockers"]

    total = len(blockers)
    by_status = {}
    by_severity = {}
    by_type = {}

    for b in blockers:
        by_status[b["status"]] = by_status.get(b["status"], 0) + 1
        by_severity[b["severity"]] = by_severity.get(b["severity"], 0) + 1
        by_type[b["type"]] = by_type.get(b["type"], 0) + 1

    open_blockers = [b for b in blockers if b["status"] == "open"]
    blocking_blockers = [b for b in blockers if b["severity"] == "blocking" and b["status"] != "resolved"]

    return {
        "total_blockers": total,
        "by_status": by_status,
        "by_severity": by_severity,
        "by_type": by_type,
        "open_count": len(open_blockers),
        "blocking_count": len(blocking_blockers),
        "open_blockers": open_blockers,
        "blocking_blockers": blocking_blockers,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


# ═══════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="LatticeWork 阻塞点管理器",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="command", help="子命令")

    # register
    reg_parser = subparsers.add_parser("register", help="注册阻塞点")
    reg_parser.add_argument("--type", required=True, choices=BLOCKER_TYPES, help="阻塞点类型")
    reg_parser.add_argument("--description", required=True, help="阻塞点描述")
    reg_parser.add_argument("--severity", required=True, choices=BLOCKER_SEVERITIES, help="严重程度")
    reg_parser.add_argument("--affected-tasks", nargs="*", default=[], help="受影响的任务ID")
    reg_parser.add_argument("--affected-layer", type=int, default=None, help="受影响的层级")
    reg_parser.add_argument("--discovered-in-cycle", default=None, help="在哪个PCDCA循环中发现")
    reg_parser.add_argument("--resolution", default=None, help="解决方案")
    reg_parser.add_argument("--workaround", default=None, help="临时绕过方案")

    # status
    status_parser = subparsers.add_parser("status", help="查看阻塞点状态")
    status_parser.add_argument("--blocker-id", required=True, help="阻塞点ID")

    # update
    update_parser = subparsers.add_parser("update", help="更新阻塞点状态")
    update_parser.add_argument("--blocker-id", required=True, help="阻塞点ID")
    update_parser.add_argument("--status", required=True, choices=BLOCKER_STATUSES, help="新状态")

    # resolve
    resolve_parser = subparsers.add_parser("resolve", help="解决阻塞点")
    resolve_parser.add_argument("--blocker-id", required=True, help="阻塞点ID")
    resolve_parser.add_argument("--resolution", required=True, help="解决方案描述")

    # escalate
    escalate_parser = subparsers.add_parser("escalate", help="升级阻塞点")
    escalate_parser.add_argument("--blocker-id", required=True, help="阻塞点ID")
    escalate_parser.add_argument("--escalate-to", default="human", help="升级对象")
    escalate_parser.add_argument("--resolution", default=None, help="升级时提供的解决方案")

    # report
    subparsers.add_parser("report", help="生成阻塞点报告")

    # list-by-status
    list_status_parser = subparsers.add_parser("list-by-status", help="按状态列出阻塞点")
    list_status_parser.add_argument("--status", required=True, choices=BLOCKER_STATUSES, help="状态")

    # list-by-task
    list_task_parser = subparsers.add_parser("list-by-task", help="按任务列出阻塞点")
    list_task_parser.add_argument("--task-id", required=True, help="任务ID")

    args = parser.parse_args()

    if args.command == "register":
        blocker = register_blocker(
            blocker_type=args.type,
            description=args.description,
            severity=args.severity,
            affected_tasks=args.affected_tasks,
            affected_layer=args.affected_layer,
            discovered_in_cycle=args.discovered_in_cycle,
            resolution=args.resolution,
            workaround=args.workaround,
        )
        print(f"✅ 阻塞点已注册: {blocker['blocker_id']}")
        print(f"   类型: {blocker['type']}")
        print(f"   严重程度: {blocker['severity']}")
        print(f"   描述: {blocker['description']}")

    elif args.command == "status":
        blocker = get_blocker(args.blocker_id)
        if blocker:
            print(f"📋 阻塞点: {blocker['blocker_id']}")
            print(f"   类型: {blocker['type']}")
            print(f"   严重程度: {blocker['severity']}")
            print(f"   状态: {blocker['status']}")
            print(f"   描述: {blocker['description']}")
            print(f"   受影响任务: {', '.join(blocker.get('affected_tasks', [])) or '无'}")
            if blocker.get("resolution"):
                print(f"   解决方案: {blocker['resolution']}")
            if blocker.get("escalation"):
                print(f"   升级信息: {blocker['escalation']}")
        else:
            print(f"❌ 阻塞点不存在: {args.blocker_id}")

    elif args.command == "update":
        blocker = update_blocker_status(args.blocker_id, args.status)
        if blocker:
            print(f"✅ 阻塞点状态已更新: {blocker['blocker_id']} → {args.status}")
        else:
            print(f"❌ 阻塞点不存在: {args.blocker_id}")

    elif args.command == "resolve":
        blocker = update_blocker_status(args.blocker_id, "resolved")
        if blocker:
            # 同时更新解决方案
            registry = _load_registry()
            for b in registry["blockers"]:
                if b["blocker_id"] == args.blocker_id:
                    b["resolution"] = args.resolution
                    break
            _save_registry(registry)
            print(f"✅ 阻塞点已解决: {args.blocker_id}")
            print(f"   解决方案: {args.resolution}")
        else:
            print(f"❌ 阻塞点不存在: {args.blocker_id}")

    elif args.command == "escalate":
        blocker = escalate_blocker(args.blocker_id, args.escalate_to, args.resolution)
        if blocker:
            print(f"✅ 阻塞点已升级: {args.blocker_id} → {args.escalate_to}")
        else:
            print(f"❌ 阻塞点不存在: {args.blocker_id}")

    elif args.command == "report":
        report = generate_blocker_report()
        print(f"📊 阻塞点报告")
        print(f"   总数: {report['total_blockers']}")
        print(f"   开放中: {report['open_count']}")
        print(f"   阻塞级: {report['blocking_count']}")
        print()
        print(f"   按状态:")
        for status, count in report["by_status"].items():
            print(f"     {status}: {count}")
        print(f"   按严重程度:")
        for severity, count in report["by_severity"].items():
            print(f"     {severity}: {count}")
        print(f"   按类型:")
        for btype, count in report["by_type"].items():
            print(f"     {btype}: {count}")
        if report["blocking_blockers"]:
            print(f"\n   ⚠️  未解决的阻塞级阻塞点:")
            for b in report["blocking_blockers"]:
                print(f"     - {b['blocker_id']}: {b['description'][:80]}")

    elif args.command == "list-by-status":
        blockers = get_blockers_by_status(args.status)
        print(f"📋 状态 '{args.status}' 的阻塞点 ({len(blockers)} 个):")
        for b in blockers:
            print(f"   - {b['blocker_id']} [{b['severity']}]: {b['description'][:80]}")

    elif args.command == "list-by-task":
        blockers = get_blockers_by_task(args.task_id)
        print(f"📋 影响任务 '{args.task_id}' 的阻塞点 ({len(blockers)} 个):")
        for b in blockers:
            print(f"   - {b['blocker_id']} [{b['severity']}/{b['status']}]: {b['description'][:80]}")

    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
