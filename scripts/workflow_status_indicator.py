#!/usr/bin/env python3
"""
workflow_status_indicator.py — 工作流状态指示器

在 VS Code + CLINE 环境下，用户需要清晰知道当前是否处于工作流执行状态。
本脚本提供状态指示功能，帮助用户区分"普通对话"和"工作流执行中"两种模式。

功能:
  1. 读取运行快照，显示当前工作流状态
  2. 生成状态指示横幅（Banner），可嵌入对话上下文
  3. 检查是否有活跃的中断事件等待用户处理
  4. 显示当前工作流进度（当前步骤/总步骤数）
  5. 列出待用户回答的问题

用法:
  # 显示当前工作流状态
  python scripts/workflow_status_indicator.py status --snapshot runtime/workflow_runtime/snapshot_xxx.json

  # 生成状态横幅（用于对话上下文）
  python scripts/workflow_status_indicator.py banner --snapshot runtime/workflow_runtime/snapshot_xxx.json

  # 检查是否有待处理的中断
  python scripts/workflow_status_indicator.py pending --snapshot runtime/workflow_runtime/snapshot_xxx.json

  # 列出所有活跃的运行快照
  python scripts/workflow_status_indicator.py list-active

  # 生成 Markdown 状态报告
  python scripts/workflow_status_indicator.py report --snapshot runtime/workflow_runtime/snapshot_xxx.json
"""

import argparse
import json
import logging
import os
import sys
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

# ═══════════════════════════════════════════════════════════════
# Constants
# ═══════════════════════════════════════════════════════════════

# 状态 → 图标/颜色映射
STATUS_ICONS = {
    "created": "🆕",
    "context_intent_pending": "❓",
    "context_intent_confirmed": "✅",
    "running": "⚡",
    "workflow_pause": "⏸️",
    "interrupted_by_user": "🛑",
    "cancelled_by_user": "🚫",
    "completed": "✅",
    "failed": "❌",
}

STATUS_LABELS = {
    "created": "已创建",
    "context_intent_pending": "等待意图确认",
    "context_intent_confirmed": "意图已确认",
    "running": "执行中",
    "workflow_pause": "已暂停（等待用户输入）",
    "interrupted_by_user": "用户中断",
    "cancelled_by_user": "用户取消",
    "completed": "已完成",
    "failed": "失败",
}

# 状态分类
ACTIVE_STATUSES = ["running", "context_intent_pending", "context_intent_confirmed"]
PAUSED_STATUSES = ["workflow_pause", "interrupted_by_user"]
TERMINAL_STATUSES = ["completed", "failed", "cancelled_by_user"]

# 运行快照目录
RUNTIME_DIR = "runtime/workflow_runtime"

# ═══════════════════════════════════════════════════════════════
# File I/O helpers
# ═══════════════════════════════════════════════════════════════

def load_json(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(data: Dict[str, Any], path: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def resolve_path(path: str) -> str:
    if os.path.isabs(path):
        return path
    return os.path.join(os.path.dirname(__file__), "..", path)


def find_active_snapshots(runtime_dir: str = RUNTIME_DIR) -> List[Dict[str, Any]]:
    """
    扫描运行快照目录，找出所有活跃（未完成/未失败）的快照。
    """
    resolved = resolve_path(runtime_dir)
    if not os.path.exists(resolved):
        return []

    active_snapshots = []
    for fname in os.listdir(resolved):
        if fname.startswith("snapshot_") and fname.endswith(".json"):
            fpath = os.path.join(resolved, fname)
            try:
                snapshot = load_json(fpath)
                status = snapshot.get("workflow_state", {}).get("status", "")
                if status in ACTIVE_STATUSES + PAUSED_STATUSES:
                    active_snapshots.append(snapshot)
            except (json.JSONDecodeError, IOError):
                continue

    return active_snapshots


# ═══════════════════════════════════════════════════════════════
# Status Display Functions
# ═══════════════════════════════════════════════════════════════

def get_status_banner(snapshot: Dict[str, Any]) -> str:
    """
    生成状态指示横幅（Banner），用于在对话上下文中显示。
    让用户一眼就能看出当前是否在工作流执行状态。
    """
    workflow_state = snapshot.get("workflow_state", {})
    status = workflow_state.get("status", "unknown")
    current_node = workflow_state.get("current_node", "")
    workflow_id = snapshot.get("workflow_id", "unknown")
    run_id = snapshot.get("run_id", "unknown")

    icon = STATUS_ICONS.get(status, "❓")
    label = STATUS_LABELS.get(status, status)

    # 计算进度
    completed_steps = workflow_state.get("completed_steps", [])
    total_steps = workflow_state.get("total_steps", 0)
    progress = f"{len(completed_steps)}/{total_steps}" if total_steps > 0 else "?"

    # 检查是否有待处理的中断
    interruptions = snapshot.get("interruptions", [])
    pending_interruptions = [i for i in interruptions if i.get("status") == "pending"]

    # 构建横幅
    banner_lines = []
    separator = "═" * 60

    banner_lines.append(f"╔{separator}╗")
    banner_lines.append(f"║  {icon}  工作流状态: {label}")
    banner_lines.append(f"║")
    banner_lines.append(f"║  工作流: {workflow_id}")
    banner_lines.append(f"║  运行 ID: {run_id}")
    banner_lines.append(f"║  当前节点: {current_node}")
    banner_lines.append(f"║  进度: {progress}")

    if pending_interruptions:
        banner_lines.append(f"║")
        banner_lines.append(f"║  ⏸️  等待用户输入:")
        for int_event in pending_interruptions:
            reason = int_event.get("pause_reason", "unknown")
            questions = int_event.get("pending_questions", [])
            banner_lines.append(f"║     - 原因: {reason}")
            for q in questions:
                banner_lines.append(f"║       ❓ {q}")

    if status in ACTIVE_STATUSES:
        banner_lines.append(f"║")
        banner_lines.append(f"║  💡 当前处于工作流执行模式，AI 正在按步骤执行任务")
    elif status in PAUSED_STATUSES:
        banner_lines.append(f"║")
        banner_lines.append(f"║  💡 工作流已暂停，请回复补充信息以继续执行")
    elif status in TERMINAL_STATUSES:
        banner_lines.append(f"║")
        banner_lines.append(f"║  💡 工作流已结束，可以开始新的对话或任务")

    banner_lines.append(f"╚{separator}╝")

    return "\n".join(banner_lines)


def get_status_summary(snapshot: Dict[str, Any]) -> str:
    """
    生成简洁的状态摘要（单行），适合嵌入对话开头。
    """
    workflow_state = snapshot.get("workflow_state", {})
    status = workflow_state.get("status", "unknown")
    workflow_id = snapshot.get("workflow_id", "unknown")
    current_node = workflow_state.get("current_node", "")

    icon = STATUS_ICONS.get(status, "❓")
    label = STATUS_LABELS.get(status, status)

    completed_steps = workflow_state.get("completed_steps", [])
    total_steps = workflow_state.get("total_steps", 0)
    progress = f"{len(completed_steps)}/{total_steps}" if total_steps > 0 else "?"

    return f"{icon} [{workflow_id}] {label} | 节点: {current_node} | 进度: {progress}"


def get_pending_questions(snapshot: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    获取所有待用户回答的问题。
    """
    interruptions = snapshot.get("interruptions", [])
    pending = []

    for int_event in interruptions:
        if int_event.get("status") == "pending":
            pending.append({
                "interruption_id": int_event.get("interruption_id"),
                "pause_reason": int_event.get("pause_reason"),
                "questions": int_event.get("pending_questions", []),
                "resume_condition": int_event.get("resume_condition", ""),
                "cancel_condition": int_event.get("cancel_condition", ""),
            })

    return pending


def get_workflow_progress(snapshot: Dict[str, Any]) -> Dict[str, Any]:
    """
    获取工作流执行进度详情。
    """
    workflow_state = snapshot.get("workflow_state", {})
    completed_steps = workflow_state.get("completed_steps", [])
    total_steps = workflow_state.get("total_steps", 0)

    return {
        "completed": len(completed_steps),
        "total": total_steps,
        "percentage": round(len(completed_steps) / total_steps * 100, 1) if total_steps > 0 else 0,
        "completed_steps": completed_steps,
        "remaining": total_steps - len(completed_steps),
    }


def generate_markdown_report(snapshot: Dict[str, Any]) -> str:
    """
    生成 Markdown 格式的状态报告。
    """
    workflow_state = snapshot.get("workflow_state", {})
    status = workflow_state.get("status", "unknown")
    workflow_id = snapshot.get("workflow_id", "unknown")
    run_id = snapshot.get("run_id", "unknown")
    current_node = workflow_state.get("current_node", "")

    icon = STATUS_ICONS.get(status, "❓")
    label = STATUS_LABELS.get(status, status)

    progress = get_workflow_progress(snapshot)
    pending = get_pending_questions(snapshot)

    lines = []
    lines.append(f"# 工作流状态报告")
    lines.append(f"")
    lines.append(f"## 概览")
    lines.append(f"")
    lines.append(f"| 字段 | 值 |")
    lines.append(f"|------|-----|")
    lines.append(f"| 状态 | {icon} {label} |")
    lines.append(f"| 工作流 | `{workflow_id}` |")
    lines.append(f"| 运行 ID | `{run_id}` |")
    lines.append(f"| 当前节点 | `{current_node}` |")
    lines.append(f"| 进度 | {progress['completed']}/{progress['total']} ({progress['percentage']}%) |")
    lines.append(f"")

    if status in ACTIVE_STATUSES:
        lines.append(f"> ⚡ **当前处于工作流执行模式** — AI 正在按步骤执行任务，请等待完成或提供必要信息。")
    elif status in PAUSED_STATUSES:
        lines.append(f"> ⏸️ **工作流已暂停** — 需要您的输入才能继续执行。")
    elif status in TERMINAL_STATUSES:
        lines.append(f"> ✅ **工作流已结束** — 可以开始新的对话或任务。")

    lines.append(f"")

    if pending:
        lines.append(f"## ⏸️ 待处理的中断")
        lines.append(f"")
        for p in pending:
            lines.append(f"### 中断: {p['interruption_id']}")
            lines.append(f"")
            lines.append(f"- **原因**: {p['pause_reason']}")
            lines.append(f"- **恢复条件**: {p['resume_condition']}")
            lines.append(f"- **取消条件**: {p['cancel_condition']}")
            lines.append(f"")
            if p['questions']:
                lines.append(f"**待回答问题:**")
                for q in p['questions']:
                    lines.append(f"- ❓ {q}")
            lines.append(f"")

    if progress['completed_steps']:
        lines.append(f"## 已完成步骤")
        lines.append(f"")
        for step in progress['completed_steps']:
            lines.append(f"- ✅ {step}")
        lines.append(f"")

    # 中断历史
    interruptions = snapshot.get("interruptions", [])
    if interruptions:
        lines.append(f"## 中断历史")
        lines.append(f"")
        lines.append(f"| 中断 ID | 类型 | 原因 | 状态 |")
        lines.append(f"|---------|------|------|------|")
        for int_event in interruptions:
            iid = int_event.get("interruption_id", "")
            itype = int_event.get("type", "")
            ireason = int_event.get("pause_reason", "")
            istatus = int_event.get("status", "")
            lines.append(f"| `{iid}` | {itype} | {ireason} | {istatus} |")
        lines.append(f"")

    lines.append(f"---")
    lines.append(f"*报告生成时间: {datetime.now(timezone.utc).isoformat()}*")

    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="工作流状态指示器 — 让用户知道当前是否处于工作流执行状态",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
子命令:
  status        显示当前工作流状态（简洁）
  banner        生成状态指示横幅（醒目，适合嵌入对话）
  summary       生成单行状态摘要
  pending       列出待用户回答的问题
  progress      显示工作流执行进度
  report        生成 Markdown 格式的完整状态报告
  list-active   列出所有活跃的运行快照

示例:
  # 显示状态
  python scripts/workflow_status_indicator.py status \\
      --snapshot runtime/workflow_runtime/snapshot_abc123.json

  # 生成横幅
  python scripts/workflow_status_indicator.py banner \\
      --snapshot runtime/workflow_runtime/snapshot_abc123.json

  # 列出所有活跃运行
  python scripts/workflow_status_indicator.py list-active
        """,
    )
    subparsers = parser.add_subparsers(dest="command", help="子命令")

    # status
    status_parser = subparsers.add_parser("status", help="显示当前工作流状态")
    status_parser.add_argument("-s", "--snapshot", required=True, help="运行快照 JSON 文件路径")

    # banner
    banner_parser = subparsers.add_parser("banner", help="生成状态指示横幅")
    banner_parser.add_argument("-s", "--snapshot", required=True, help="运行快照 JSON 文件路径")

    # summary
    summary_parser = subparsers.add_parser("summary", help="生成单行状态摘要")
    summary_parser.add_argument("-s", "--snapshot", required=True, help="运行快照 JSON 文件路径")

    # pending
    pending_parser = subparsers.add_parser("pending", help="列出待用户回答的问题")
    pending_parser.add_argument("-s", "--snapshot", required=True, help="运行快照 JSON 文件路径")

    # progress
    progress_parser = subparsers.add_parser("progress", help="显示工作流执行进度")
    progress_parser.add_argument("-s", "--snapshot", required=True, help="运行快照 JSON 文件路径")

    # report
    report_parser = subparsers.add_parser("report", help="生成 Markdown 状态报告")
    report_parser.add_argument("-s", "--snapshot", required=True, help="运行快照 JSON 文件路径")
    report_parser.add_argument("-o", "--output", default="", help="输出路径")

    # list-active
    list_parser = subparsers.add_parser("list-active", help="列出所有活跃的运行快照")

    args = parser.parse_args()

    if args.command == "list-active":
        active = find_active_snapshots()
        if not active:
            print("📭 没有活跃的工作流运行")
            return

        print(f"📋 活跃的工作流运行 ({len(active)}):")
        print("")
        for snap in active:
            summary = get_status_summary(snap)
            print(f"  {summary}")
            print(f"    快照文件: runtime/workflow_runtime/snapshot_{snap.get('run_id', 'unknown')}.json")
            print()

    elif args.command in ("status", "banner", "summary", "pending", "progress", "report"):
        snapshot_path = args.snapshot
        resolved = resolve_path(snapshot_path)
        if not os.path.exists(resolved):
            print(f"❌ 快照文件不存在: {resolved}", file=sys.stderr)
            sys.exit(1)

        snapshot = load_json(resolved)

        if args.command == "status":
            workflow_state = snapshot.get("workflow_state", {})
            status = workflow_state.get("status", "unknown")
            workflow_id = snapshot.get("workflow_id", "unknown")
            current_node = workflow_state.get("current_node", "")
            icon = STATUS_ICONS.get(status, "❓")
            label = STATUS_LABELS.get(status, status)

            print(f"{icon} 工作流: {workflow_id}")
            print(f"   状态: {label}")
            print(f"   当前节点: {current_node}")
            print(f"   运行 ID: {snapshot.get('run_id', 'unknown')}")

            progress = get_workflow_progress(snapshot)
            print(f"   进度: {progress['completed']}/{progress['total']} ({progress['percentage']}%)")

            pending = get_pending_questions(snapshot)
            if pending:
                print(f"   待处理中断: {len(pending)}")
                for p in pending:
                    print(f"     - {p['pause_reason']}: {len(p['questions'])} 个问题待回答")

        elif args.command == "banner":
            banner = get_status_banner(snapshot)
            print(banner)

        elif args.command == "summary":
            summary = get_status_summary(snapshot)
            print(summary)

        elif args.command == "pending":
            pending = get_pending_questions(snapshot)
            if not pending:
                print("📭 没有待处理的中断")
                return

            print(f"⏸️  待处理的中断 ({len(pending)}):")
            print()
            for p in pending:
                print(f"  中断 ID: {p['interruption_id']}")
                print(f"  原因: {p['pause_reason']}")
                print(f"  恢复条件: {p['resume_condition']}")
                print(f"  取消条件: {p['cancel_condition']}")
                if p['questions']:
                    print(f"  待回答问题:")
                    for q in p['questions']:
                        print(f"    ❓ {q}")
                print()

        elif args.command == "progress":
            progress = get_workflow_progress(snapshot)
            workflow_state = snapshot.get("workflow_state", {})
            status = workflow_state.get("status", "unknown")

            bar_length = 30
            filled = int(progress['percentage'] / 100 * bar_length)
            bar = "█" * filled + "░" * (bar_length - filled)

            print(f"进度: [{bar}] {progress['percentage']}%")
            print(f"已完成: {progress['completed']}/{progress['total']} 步骤")
            print(f"状态: {STATUS_LABELS.get(status, status)}")
            if progress['completed_steps']:
                print(f"已完成步骤: {', '.join(progress['completed_steps'])}")

        elif args.command == "report":
            report = generate_markdown_report(snapshot)
            if args.output:
                output_path = resolve_path(args.output)
                os.makedirs(os.path.dirname(output_path), exist_ok=True)
                with open(output_path, "w", encoding="utf-8") as f:
                    f.write(report)
                print(f"✅ 报告已保存: {output_path}")
            else:
                print(report)

    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
