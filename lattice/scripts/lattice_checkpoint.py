#!/usr/bin/env python3
"""
lattice_checkpoint.py — 检查点管理器（断点续传核心）

用于在 LatticeWork 执行过程中创建和恢复检查点，
解决上下文截断后 AI 丢失状态的问题。

核心功能:
  1. create_checkpoint()   → 创建检查点（持久化当前执行状态）
  2. resume_from_checkpoint() → 从检查点恢复执行
  3. list_checkpoints()    → 列出所有检查点
  4. get_latest_checkpoint() → 获取最新的检查点
  5. generate_resume_prompt() → 生成恢复上下文提示词

用法:
  # 创建检查点
  python lattice/scripts/lattice_checkpoint.py create \\
      --lattice lattice/examples/energy/lattice_vpp_ems_standard.yaml \\
      --section "6.5" \\
      --next-section "6.5.2" \\
      --file output/VPP_EMS_能量路由器综合标准规范_v2.0.md \\
      --lines 650 \\
      --memento "已完成物理约束校验层，当前正在编写通信协议层的设备注册子章节"

  # 列出所有检查点
  python lattice/scripts/lattice_checkpoint.py list

  # 获取最新检查点
  python lattice/scripts/lattice_checkpoint.py latest

  # 生成恢复提示词（用于新对话的上下文恢复）
  python lattice/scripts/lattice_checkpoint.py resume-prompt \\
      --checkpoint-id vpp_ems_standard_v2.0_20260509_180000
"""

import argparse
import json
import logging
import os
import sys
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

try:
    import yaml
except ImportError:
    print("⚠️  PyYAML not installed. Run: pip install pyyaml", file=sys.stderr)
    sys.exit(1)

# ═══════════════════════════════════════════════════════════════
# Constants
# ═══════════════════════════════════════════════════════════════

LATTICE_DIR = os.path.join(os.path.dirname(__file__), "..")
RUNTIME_DIR = os.path.join(LATTICE_DIR, "lattice_runtime")
CHECKPOINTS_DIR = os.path.join(RUNTIME_DIR, "checkpoints")
CHECKPOINT_INDEX_PATH = os.path.join(CHECKPOINTS_DIR, "checkpoint_index.json")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("lattice_checkpoint")


# ═══════════════════════════════════════════════════════════════
# Checkpoint CRUD
# ═══════════════════════════════════════════════════════════════

def _ensure_dirs():
    """确保检查点目录存在。"""
    os.makedirs(CHECKPOINTS_DIR, exist_ok=True)


def _load_index() -> Dict[str, Any]:
    """加载检查点索引。"""
    _ensure_dirs()
    if os.path.exists(CHECKPOINT_INDEX_PATH):
        with open(CHECKPOINT_INDEX_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"checkpoints": [], "latest": None}


def _save_index(index: Dict[str, Any]):
    """保存检查点索引。"""
    _ensure_dirs()
    with open(CHECKPOINT_INDEX_PATH, "w", encoding="utf-8") as f:
        json.dump(index, f, indent=2, ensure_ascii=False)


def create_checkpoint(
    lattice_name: str,
    last_completed_section: str,
    next_section: str,
    completed_sections: List[str],
    target_file: str,
    total_lines_written: int,
    last_line_content: str = "",
    file_complete: bool = False,
    context_memento: str = "",
    total_sections: int = 0,
    pcdca_cycles: Optional[List[Dict]] = None,
    blockers: Optional[List[Dict]] = None,
    metadata: Optional[Dict] = None,
) -> Dict[str, Any]:
    """
    创建执行检查点。

    参数:
      lattice_name: 晶格方案名称
      last_completed_section: 最后完成的章节/任务
      next_section: 下一个要执行的章节/任务
      completed_sections: 已完成的章节列表
      target_file: 目标输出文件路径
      total_lines_written: 已写入的总行数
      last_line_content: 最后写入行的内容摘要
      file_complete: 文件是否已完成
      context_memento: 上下文记忆摘要
      total_sections: 总章节数
      pcdca_cycles: PCDCA循环状态列表
      blockers: 阻塞点列表
      metadata: 元数据

    返回:
      创建的检查点对象
    """
    _ensure_dirs()

    timestamp = datetime.now(timezone.utc)
    timestamp_str = timestamp.strftime("%Y%m%d_%H%M%S")
    checkpoint_id = f"{lattice_name}_{timestamp_str}"

    checkpoint = {
        "checkpoint_id": checkpoint_id,
        "lattice_name": lattice_name,
        "timestamp": timestamp.isoformat(),
        "status": "in_progress",
        "last_completed_section": last_completed_section,
        "next_section": next_section,
        "total_sections": total_sections,
        "completed_sections": completed_sections,
        "file_status": {
            "target_file": target_file,
            "total_lines_written": total_lines_written,
            "last_line_content": last_line_content,
            "file_complete": file_complete,
        },
        "pcdca_cycles": pcdca_cycles or [],
        "context_memento": context_memento,
        "blockers": blockers or [],
        "metadata": metadata or {
            "model": "claude",
            "context_usage_pct": None,
            "version": "1.0",
        },
    }

    # 写入检查点文件
    checkpoint_path = os.path.join(CHECKPOINTS_DIR, f"{checkpoint_id}.json")
    with open(checkpoint_path, "w", encoding="utf-8") as f:
        json.dump(checkpoint, f, indent=2, ensure_ascii=False)

    # 更新索引
    index = _load_index()
    index["checkpoints"].append(checkpoint_id)
    index["latest"] = checkpoint_id
    _save_index(index)

    logger.info(f"检查点已创建: {checkpoint_id}")
    logger.info(f"  最后完成: {last_completed_section}")
    logger.info(f"  下一步: {next_section}")
    logger.info(f"  文件: {target_file} ({total_lines_written} 行)")

    return checkpoint


def get_checkpoint(checkpoint_id: str) -> Optional[Dict[str, Any]]:
    """获取指定检查点。"""
    checkpoint_path = os.path.join(CHECKPOINTS_DIR, f"{checkpoint_id}.json")
    if not os.path.exists(checkpoint_path):
        logger.error(f"检查点不存在: {checkpoint_id}")
        return None
    with open(checkpoint_path, "r", encoding="utf-8") as f:
        return json.load(f)


def get_latest_checkpoint() -> Optional[Dict[str, Any]]:
    """获取最新的检查点。"""
    index = _load_index()
    latest_id = index.get("latest")
    if not latest_id:
        logger.info("没有找到检查点")
        return None
    return get_checkpoint(latest_id)


def list_checkpoints() -> List[Dict[str, Any]]:
    """列出所有检查点。"""
    index = _load_index()
    checkpoints = []
    for cid in index["checkpoints"]:
        cp = get_checkpoint(cid)
        if cp:
            checkpoints.append({
                "checkpoint_id": cid,
                "timestamp": cp.get("timestamp"),
                "lattice_name": cp.get("lattice_name"),
                "status": cp.get("status"),
                "last_completed_section": cp.get("last_completed_section"),
                "next_section": cp.get("next_section"),
                "file": cp.get("file_status", {}).get("target_file"),
                "lines": cp.get("file_status", {}).get("total_lines_written"),
            })
    return checkpoints


def update_checkpoint(
    checkpoint_id: str,
    updates: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    """更新检查点。"""
    checkpoint = get_checkpoint(checkpoint_id)
    if not checkpoint:
        return None

    # 递归更新
    for key, value in updates.items():
        if isinstance(value, dict) and isinstance(checkpoint.get(key), dict):
            checkpoint[key].update(value)
        else:
            checkpoint[key] = value

    checkpoint["timestamp"] = datetime.now(timezone.utc).isoformat()

    checkpoint_path = os.path.join(CHECKPOINTS_DIR, f"{checkpoint_id}.json")
    with open(checkpoint_path, "w", encoding="utf-8") as f:
        json.dump(checkpoint, f, indent=2, ensure_ascii=False)

    logger.info(f"检查点已更新: {checkpoint_id}")
    return checkpoint


# ═══════════════════════════════════════════════════════════════
# Resume Logic
# ═══════════════════════════════════════════════════════════════

def generate_resume_prompt(checkpoint_id: str = None) -> str:
    """
    生成恢复上下文提示词。

    这个提示词用于新对话中，告诉 AI 从哪个位置继续执行。
    包含:
      - 当前进度摘要
      - 下一步要做什么
      - 上下文记忆
      - 文件状态

    参数:
      checkpoint_id: 检查点ID（None 则使用最新）

    返回:
      恢复提示词文本
    """
    if checkpoint_id:
        checkpoint = get_checkpoint(checkpoint_id)
    else:
        checkpoint = get_latest_checkpoint()

    if not checkpoint:
        return "⚠️ 没有找到检查点，无法恢复执行。"

    file_status = checkpoint.get("file_status", {})
    completed = checkpoint.get("completed_sections", [])
    total = checkpoint.get("total_sections", 0)
    pct = f"{len(completed)}/{total}" if total > 0 else f"{len(completed)}"

    prompt = f"""# 🔄 任务恢复：断点续传

## 检查点信息
- **检查点ID**: {checkpoint['checkpoint_id']}
- **晶格方案**: {checkpoint['lattice_name']}
- **创建时间**: {checkpoint['timestamp']}
- **状态**: {checkpoint['status']}

## 当前进度
- **已完成章节**: {pct}
- **最后完成**: {checkpoint['last_completed_section']}
- **下一步**: {checkpoint['next_section']}

## 文件状态
- **目标文件**: {file_status.get('target_file', 'N/A')}
- **已写入行数**: {file_status.get('total_lines_written', 0)}
- **文件是否完成**: {'是' if file_status.get('file_complete') else '否'}
- **最后写入内容**: {file_status.get('last_line_content', 'N/A')}

## 上下文记忆
{checkpoint.get('context_memento', '无')}

## 阻塞点
{chr(10).join(f"- [{b.get('severity','')}] {b.get('description','')}" for b in checkpoint.get('blockers', [])) if checkpoint.get('blockers') else '无'}

## 执行指令
请从 **{checkpoint['next_section']}** 继续执行。
首先读取目标文件确认当前状态，然后继续编写后续内容。
"""
    return prompt


def resume_from_checkpoint(checkpoint_id: str = None) -> Dict[str, Any]:
    """
    从检查点恢复执行。

    返回恢复所需的所有上下文信息，包括:
      - 检查点数据
      - 恢复提示词
      - 目标文件最后几行（用于确认位置）
      - 下一步执行计划

    参数:
      checkpoint_id: 检查点ID（None 则使用最新）

    返回:
      恢复上下文
    """
    if checkpoint_id:
        checkpoint = get_checkpoint(checkpoint_id)
    else:
        checkpoint = get_latest_checkpoint()

    if not checkpoint:
        return {"status": "error", "message": "没有找到检查点"}

    # 读取目标文件最后几行
    target_file = checkpoint.get("file_status", {}).get("target_file", "")
    file_tail = ""
    if target_file and os.path.exists(target_file):
        try:
            with open(target_file, "r", encoding="utf-8") as f:
                lines = f.readlines()
            # 取最后20行
            tail_lines = lines[-20:] if len(lines) > 20 else lines
            file_tail = "".join(tail_lines)
        except Exception as e:
            file_tail = f"（读取文件失败: {e}）"

    resume_prompt = generate_resume_prompt(checkpoint_id)

    return {
        "status": "ready",
        "checkpoint": checkpoint,
        "resume_prompt": resume_prompt,
        "file_tail": file_tail,
        "next_section": checkpoint.get("next_section"),
        "last_completed": checkpoint.get("last_completed_section"),
        "context_memento": checkpoint.get("context_memento"),
    }


# ═══════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="LatticeWork 检查点管理器（断点续传核心）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
子命令:
  create          创建检查点
  list            列出所有检查点
  latest          获取最新检查点
  get             获取指定检查点
  update          更新检查点
  resume-prompt   生成恢复提示词
  resume          从检查点恢复执行

示例:
  # 创建检查点
  python lattice/scripts/lattice_checkpoint.py create \\
      --lattice "vpp_ems_standard_v2.0" \\
      --section "6.5" \\
      --next-section "6.5.2" \\
      --file output/VPP_EMS_能量路由器综合标准规范_v2.0.md \\
      --lines 650

  # 生成恢复提示词
  python lattice/scripts/lattice_checkpoint.py resume-prompt

  # 从检查点恢复
  python lattice/scripts/lattice_checkpoint.py resume
        """,
    )
    subparsers = parser.add_subparsers(dest="command", help="子命令")

    # create
    create_parser = subparsers.add_parser("create", help="创建检查点")
    create_parser.add_argument("-n", "--lattice", required=True, help="晶格方案名称")
    create_parser.add_argument("-s", "--section", required=True, help="最后完成的章节")
    create_parser.add_argument("--next-section", required=True, help="下一个要执行的章节")
    create_parser.add_argument("--completed", nargs="*", default=[], help="已完成的章节列表")
    create_parser.add_argument("-f", "--file", required=True, help="目标输出文件路径")
    create_parser.add_argument("--lines", type=int, required=True, help="已写入的总行数")
    create_parser.add_argument("--last-line", default="", help="最后写入行的内容")
    create_parser.add_argument("--total", type=int, default=0, help="总章节数")
    create_parser.add_argument("-m", "--memento", default="", help="上下文记忆摘要")

    # list
    subparsers.add_parser("list", help="列出所有检查点")

    # latest
    subparsers.add_parser("latest", help="获取最新检查点")

    # get
    get_parser = subparsers.add_parser("get", help="获取指定检查点")
    get_parser.add_argument("--checkpoint-id", required=True, help="检查点ID")

    # update
    update_parser = subparsers.add_parser("update", help="更新检查点")
    update_parser.add_argument("--checkpoint-id", required=True, help="检查点ID")
    update_parser.add_argument("--section", help="最后完成的章节")
    update_parser.add_argument("--next-section", help="下一个要执行的章节")
    update_parser.add_argument("--lines", type=int, help="已写入的总行数")
    update_parser.add_argument("--memento", help="上下文记忆摘要")

    # resume-prompt
    rp_parser = subparsers.add_parser("resume-prompt", help="生成恢复提示词")
    rp_parser.add_argument("--checkpoint-id", help="检查点ID（默认使用最新）")

    # resume
    resume_parser = subparsers.add_parser("resume", help="从检查点恢复执行")
    resume_parser.add_argument("--checkpoint-id", help="检查点ID（默认使用最新）")

    args = parser.parse_args()

    if args.command == "create":
        checkpoint = create_checkpoint(
            lattice_name=args.lattice,
            last_completed_section=args.section,
            next_section=args.next_section,
            completed_sections=args.completed,
            target_file=args.file,
            total_lines_written=args.lines,
            last_line_content=args.last_line,
            context_memento=args.memento,
            total_sections=args.total,
        )
        print(f"✅ 检查点已创建: {checkpoint['checkpoint_id']}")
        print(f"   最后完成: {checkpoint['last_completed_section']}")
        print(f"   下一步: {checkpoint['next_section']}")
        print(f"   文件: {checkpoint['file_status']['target_file']} ({checkpoint['file_status']['total_lines_written']} 行)")

    elif args.command == "list":
        checkpoints = list_checkpoints()
        if not checkpoints:
            print("📭 没有找到检查点")
        else:
            print(f"📋 检查点列表 ({len(checkpoints)} 个):")
            for cp in checkpoints:
                print(f"   [{cp['status']}] {cp['checkpoint_id']}")
                print(f"       晶格: {cp['lattice_name']}")
                print(f"       进度: {cp['last_completed_section']} → {cp['next_section']}")
                print(f"       文件: {cp['file']} ({cp['lines']} 行)")
                print()

    elif args.command == "latest":
        checkpoint = get_latest_checkpoint()
        if checkpoint:
            print(f"📌 最新检查点: {checkpoint['checkpoint_id']}")
            print(f"   晶格: {checkpoint['lattice_name']}")
            print(f"   时间: {checkpoint['timestamp']}")
            print(f"   进度: {checkpoint['last_completed_section']} → {checkpoint['next_section']}")
            print(f"   文件: {checkpoint['file_status']['target_file']} ({checkpoint['file_status']['total_lines_written']} 行)")
            print(f"   记忆: {checkpoint.get('context_memento', '无')[:100]}...")
        else:
            print("📭 没有找到检查点")

    elif args.command == "get":
        checkpoint = get_checkpoint(args.checkpoint_id)
        if checkpoint:
            print(json.dumps(checkpoint, indent=2, ensure_ascii=False))
        else:
            print(f"❌ 检查点不存在: {args.checkpoint_id}")

    elif args.command == "update":
        updates = {}
        if args.section:
            updates["last_completed_section"] = args.section
        if args.next_section:
            updates["next_section"] = args.next_section
        if args.lines is not None:
            updates["file_status"] = {"total_lines_written": args.lines}
        if args.memento:
            updates["context_memento"] = args.memento

        result = update_checkpoint(args.checkpoint_id, updates)
        if result:
            print(f"✅ 检查点已更新: {args.checkpoint_id}")
        else:
            print(f"❌ 检查点不存在: {args.checkpoint_id}")

    elif args.command == "resume-prompt":
        prompt = generate_resume_prompt(args.checkpoint_id)
        print(prompt)

    elif args.command == "resume":
        result = resume_from_checkpoint(args.checkpoint_id)
        if result["status"] == "error":
            print(f"❌ {result['message']}")
        else:
            print(f"✅ 恢复就绪")
            print(f"   下一步: {result['next_section']}")
            print(f"   最后完成: {result['last_completed']}")
            print()
            print("=" * 60)
            print("📋 恢复提示词（复制到新对话中使用）:")
            print("=" * 60)
            print(result["resume_prompt"])
            print("=" * 60)
            if result.get("file_tail"):
                print()
                print("📄 目标文件末尾内容:")
                print(result["file_tail"])

    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
