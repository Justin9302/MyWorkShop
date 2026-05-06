#!/usr/bin/env python3
"""
promote_suggestion.py — Phase 7c: 改进建议 → 候选变更管线

将 eval_report 中的 suggestions[] 转化为结构化的候选变更 (candidate_change)，
进入审核队列。候选变更存储在 runtime/candidate_changes/（不进 Git）。

用法:
  # 从单个评估报告中提取建议并提升为候选变更
  python scripts/promote_suggestion.py \\
    --report outputs/eval_reports/run_sample_002_eval.json \\
    --output runtime/candidate_changes/

  # 批量处理目录下所有评估报告
  python scripts/promote_suggestion.py \\
    --report-dir outputs/eval_reports/ \\
    --output runtime/candidate_changes/

  # 列出所有待审核的候选变更
  python scripts/promote_suggestion.py --list-pending

  # 审核候选变更
  python scripts/promote_suggestion.py --approve change_abc12345
  python scripts/promote_suggestion.py --reject change_abc12345 --reason "需要更多证据"

Schema: schemas/candidate_change.schema.json
"""

import argparse
import json
import logging
import os
import re
import sys
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

# ── Constants ──

CHANGE_DIR_DEFAULT = "runtime/candidate_changes/"
SCHEMA_PATH = "schemas/candidate_change.schema.json"

# 从 suggestion.target → candidate_change.target.component 的映射
TARGET_TO_COMPONENT = {
    "prompts": "prompts",
    "workflow_steps": "workflow_steps",
    "constraint_rules": "constraint_rules",
    "retrieval_strategy": "retrieval_strategy",
    "knowledge_base_metadata": "knowledge_base_metadata",
    "output_templates": "output_templates",
    "tool_permissions": "tool_permissions",
    "model_routing": "model_routing",
}

# 从 suggestion.target → 默认候选文件路径的映射
TARGET_TO_FILE_PATH = {
    "prompts": "prompts/",
    "workflow_steps": "workflows/",
    "constraint_rules": "constraints/",
    "retrieval_strategy": "config/context-loading.yaml",
    "knowledge_base_metadata": "config/active-release.yaml",
    "output_templates": "prompts/",
    "tool_permissions": "config/permissions.yaml",
    "model_routing": "config/model-routing.yaml",
}

# 从 suggestion.target → 默认 change_type 的映射
TARGET_TO_CHANGE_TYPE = {
    "prompts": "modify_prompt",
    "workflow_steps": "add_step",
    "constraint_rules": "add_rule",
    "retrieval_strategy": "update_retrieval_order",
    "knowledge_base_metadata": "update_expiry",
    "output_templates": "update_template",
    "tool_permissions": "adjust_permission",
    "model_routing": "switch_model",
}

# ── Logging ──

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("promote_suggestion")


# ── Helpers ──


def _load_json(path: str) -> Dict[str, Any]:
    """加载 JSON 文件，返回 dict。"""
    if not os.path.exists(path):
        logger.error("文件不存在: %s", path)
        sys.exit(1)
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _write_json(path: str, data: Any) -> None:
    """写入 JSON 文件，自动创建目录。"""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    logger.info("已写入: %s", path)


def _generate_change_id() -> str:
    """生成 change_{uuid8} 格式的 ID。"""
    return f"change_{uuid.uuid4().hex[:8]}"


def _validate_report(report: Dict[str, Any]) -> bool:
    """检查评估报告是否包含必要字段。"""
    required_fields = ["run_id", "workflow_id", "suggestions"]
    for field in required_fields:
        if field not in report:
            logger.warning("评估报告缺少字段: %s", field)
            return False
    return True


def _normalize_suggestion_target(target: str) -> str:
    """将各种变体的 target 归一化为标准值。"""
    target_lower = target.strip().lower().replace("-", "_").replace(" ", "_")
    # 匹配已知组件
    for known in TARGET_TO_COMPONENT:
        if known in target_lower or target_lower in known:
            return known
    # 匹配 dimension 名称
    dimension_mapping = {
        "citation_accuracy": "retrieval_strategy",
        "constraint_compliance": "constraint_rules",
        "format_compliance": "output_templates",
        "risk_detection": "workflow_steps",
        "human_modification_rate": "prompts",
        "output_adoption_rate": "output_templates",
        "high_risk_miss_rate": "workflow_steps",
        "cost_latency": "model_routing",
    }
    if target_lower in dimension_mapping:
        return dimension_mapping[target_lower]
    return target_lower


# ── Core: 建议 → 候选变更 ──


def promote_suggestion(
    report: Dict[str, Any],
    report_path: str,
    suggestion: Dict[str, Any],
    suggestion_index: int,
    output_dir: str,
) -> Optional[str]:
    """
    将单条 suggestion 提升为候选变更文件。

    返回:
        str — 候选变更文件路径，如果跳过则返回 None。
    """
    target_raw = suggestion.get("target", "prompts")
    component = _normalize_suggestion_target(target_raw)

    change: Dict[str, Any] = {
        "change_id": _generate_change_id(),
        "source": {
            "run_id": report.get("run_id", "unknown"),
            "report_path": report_path,
            "suggestion_index": suggestion_index,
        },
        "target": {
            "component": TARGET_TO_COMPONENT.get(component, "prompts"),
            "file_path": TARGET_TO_FILE_PATH.get(component, "prompts/"),
            "change_type": TARGET_TO_CHANGE_TYPE.get(component, "modify_prompt"),
        },
        "diff": {
            "summary": suggestion.get("recommendation", "No description"),
            "before": "(pending — read current file content)",
            "after": "(pending — patch to be generated after review)",
        },
        "validation": {
            "status": "pending",
            "sandbox_report": None,
            "regression_result": None,
        },
        "approval": {
            "required": suggestion.get("requires_human_approval", True),
            "approved_by": None,
            "approved_at": None,
            "review_notes": None,
        },
        "rollout": {
            "strategy": "canary",
            "traffic_split": 0.1,
            "status": "pending",
        },
        "created_at": datetime.now(timezone.utc).isoformat(),
    }

    # 如果有 expected_impact，写入 validation 备注
    expected_impact = suggestion.get("expected_impact")
    if expected_impact:
        change["diff"]["summary"] += (
            f" | 影响指标: {expected_impact.get('affected_metrics', [])}"
            f" | 预期提升: {expected_impact.get('estimated_improvement', 'N/A')}"
        )

    # 写入文件
    change_path = os.path.join(output_dir, f"{change['change_id']}.json")
    _write_json(change_path, change)
    return change_path


def promote_all_suggestions(
    report: Dict[str, Any],
    report_path: str,
    output_dir: str,
    dry_run: bool = False,
) -> List[str]:
    """
    从单个评估报告中提取所有建议并提升为候选变更。

    返回:
        List[str] — 创建的候选变更文件路径列表。
    """
    if not _validate_report(report):
        logger.warning("跳过无效报告: %s", report_path)
        return []

    suggestions = report.get("suggestions", [])
    if not suggestions:
        logger.info("报告 %s 无建议，跳过", report.get("run_id", report_path))
        return []

    created = []
    for i, suggestion in enumerate(suggestions):
        if dry_run:
            logger.info(
                "[DRY RUN] 将创建: target=%s, recommendation=%s",
                suggestion.get("target"),
                suggestion.get("recommendation", "")[:60],
            )
            continue
        change_path = promote_suggestion(report, report_path, suggestion, i, output_dir)
        if change_path:
            created.append(change_path)

    logger.info(
        "报告 %s: 共 %d 条建议，创建 %d 个候选变更",
        report.get("run_id", report_path),
        len(suggestions),
        len(created),
    )
    return created


# ── 文件列表与管理 ──


def list_pending_changes(change_dir: str) -> List[Dict[str, Any]]:
    """列出所有待审核的候选变更。"""
    if not os.path.isdir(change_dir):
        logger.info("候选变更目录不存在: %s", change_dir)
        return []

    pending = []
    for fname in sorted(os.listdir(change_dir)):
        if not fname.endswith(".json"):
            continue
        fpath = os.path.join(change_dir, fname)
        try:
            change = _load_json(fpath)
            if change.get("validation", {}).get("status") == "pending":
                pending.append(change)
        except (json.JSONDecodeError, KeyError):
            continue
    return pending


def approve_change(change_path: str, approved_by: str = "cli_user") -> bool:
    """审核通过一个候选变更。"""
    if not os.path.exists(change_path):
        logger.error("候选变更文件不存在: %s", change_path)
        return False

    change = _load_json(change_path)
    change["validation"]["status"] = "approved"
    change["approval"]["approved_by"] = approved_by
    change["approval"]["approved_at"] = datetime.now(timezone.utc).isoformat()
    _write_json(change_path, change)
    logger.info("已通过: %s", change.get("change_id", change_path))
    return True


def reject_change(change_path: str, reason: str = "", rejected_by: str = "cli_user") -> bool:
    """驳回一个候选变更。"""
    if not os.path.exists(change_path):
        logger.error("候选变更文件不存在: %s", change_path)
        return False

    change = _load_json(change_path)
    change["validation"]["status"] = "rejected"
    change["approval"]["approved_by"] = rejected_by
    change["approval"]["approved_at"] = datetime.now(timezone.utc).isoformat()
    change["approval"]["review_notes"] = reason or "No reason provided"
    _write_json(change_path, change)
    logger.info("已驳回: %s", change.get("change_id", change_path))
    return True


def find_change_file(change_id: str, change_dir: str) -> Optional[str]:
    """根据 change_id 查找对应的文件路径。"""
    target = os.path.join(change_dir, f"{change_id}.json")
    if os.path.exists(target):
        return target
    # 遍历目录查找
    for fname in os.listdir(change_dir):
        if fname.endswith(".json"):
            try:
                change = _load_json(os.path.join(change_dir, fname))
                if change.get("change_id") == change_id:
                    return os.path.join(change_dir, fname)
            except (json.JSONDecodeError, KeyError):
                continue
    return None


# ── 格式化输出 ──


def _fmt_datetime(iso_str: Optional[str]) -> str:
    if not iso_str:
        return "N/A"
    try:
        dt = datetime.fromisoformat(iso_str)
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    except (ValueError, TypeError):
        return iso_str[:19]


def _fmt_component(comp: str) -> str:
    labels = {
        "prompts": "📝 Prompt",
        "workflow_steps": "⚙️ 工作流步骤",
        "constraint_rules": "🔒 约束规则",
        "retrieval_strategy": "🔍 检索策略",
        "knowledge_base_metadata": "📚 知识库元数据",
        "output_templates": "📋 输出模板",
        "tool_permissions": "🔧 工具权限",
        "model_routing": "🤖 模型路由",
    }
    return labels.get(comp, comp)


def print_change_summary(change: Dict[str, Any]) -> None:
    """打印单个候选变更的摘要。"""
    cid = change.get("change_id", "N/A")
    source = change.get("source", {})
    target = change.get("target", {})
    diff = change.get("diff", {})
    val = change.get("validation", {})
    appr = change.get("approval", {})

    print(f"\n{'=' * 72}")
    print(f"  ID:      {cid}")
    print(f"  来源:    {source.get('run_id', 'N/A')} (建议 #{source.get('suggestion_index', '?')})")
    print(f"  目标:    {_fmt_component(target.get('component', '?'))}")
    print(f"  文件:    {target.get('file_path', '?')}")
    print(f"  操作:    {target.get('change_type', '?')}")
    print(f"  摘要:    {diff.get('summary', '?')[:120]}")
    print(f"  状态:    {val.get('status', '?')}")
    print(f"  审批:    {'需要' if appr.get('required', True) else '不需要'}")
    print(f"  创建:    {_fmt_datetime(change.get('created_at'))}")
    if appr.get("review_notes"):
        print(f"  备注:    {appr['review_notes']}")
    print(f"{'=' * 72}")


def print_pending_list(changes: List[Dict[str, Any]]) -> None:
    """打印待审核列表。"""
    if not changes:
        print("\n✅ 没有待审核的候选变更。")
        return

    print(f"\n📋 待审核候选变更 ({len(changes)} 个):")
    print(f"{'─' * 72}")
    for c in changes:
        cid = c.get("change_id", "N/A")
        target = c.get("target", {})
        comp = _fmt_component(target.get("component", "?"))
        summary = c.get("diff", {}).get("summary", "")[:70]
        created = _fmt_datetime(c.get("created_at"))
        print(f"  {cid}  [{comp}] {summary}")
        print(f"       创建于 {created}")
    print(f"{'─' * 72}")


# ── Schema 验证 ──


def validate_against_schema(change: Dict[str, Any], schema_path: str = SCHEMA_PATH) -> bool:
    """对单个 candidate_change 做基本的 Schema 合规校验。"""
    required_root = ["change_id", "source", "target", "diff", "validation", "approval", "rollout", "created_at"]
    for field in required_root:
        if field not in change:
            logger.error("Schema 校验失败: 缺少根字段 '%s'", field)
            return False

    # target.required
    target = change.get("target", {})
    for field in ["component", "file_path", "change_type"]:
        if field not in target:
            logger.error("Schema 校验失败: target 缺少字段 '%s'", field)
            return False

    # change_type enum
    valid_change_types = [
        "add_rule", "modify_prompt", "update_template", "rename_step",
        "reorder_steps", "add_step", "remove_step", "update_retrieval_order",
        "mark_deprecated", "update_expiry", "adjust_permission", "switch_model",
    ]
    if target.get("change_type") not in valid_change_types:
        logger.warning("change_type '%s' 不在标准枚举中，但可以接受新类型", target.get("change_type"))

    # change_id pattern
    if not re.match(r"^change_[a-f0-9]{8}$", change.get("change_id", "")):
        logger.warning("change_id '%s' 格式非标准 (建议: change_{uuid8})", change.get("change_id"))

    return True


# ── CLI ──


def main():
    parser = argparse.ArgumentParser(
        description="Phase 7c: 改进建议 → 候选变更管线",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 从评估报告创建候选变更
  python scripts/promote_suggestion.py --report outputs/eval_reports/run_sample_002_eval.json

  # 批量处理
  python scripts/promote_suggestion.py --report-dir outputs/eval_reports/

  # 列出待审核
  python scripts/promote_suggestion.py --list-pending

  # 审核通过
  python scripts/promote_suggestion.py --approve change_abc12345

  # 驳回
  python scripts/promote_suggestion.py --reject change_abc12345 --reason "需要更多证据"
        """,
    )

    # 创建模式
    parser.add_argument("--report", type=str, help="单个评估报告 JSON 路径")
    parser.add_argument(
        "--report-dir", type=str,
        help="评估报告目录（批量处理所有 *_eval.json）"
    )
    parser.add_argument(
        "--output", type=str, default=CHANGE_DIR_DEFAULT,
        help=f"候选变更输出目录 (默认: {CHANGE_DIR_DEFAULT})"
    )
    parser.add_argument("--dry-run", action="store_true", help="仅预览，不写入文件")

    # 管理模式
    parser.add_argument("--list-pending", action="store_true", help="列出所有待审核的候选变更")
    parser.add_argument("--approve", type=str, metavar="CHANGE_ID", help="审核通过候选变更")
    parser.add_argument("--reject", type=str, metavar="CHANGE_ID", help="驳回候选变更")
    parser.add_argument("--reason", type=str, default="", help="驳回原因")
    parser.add_argument("--change-dir", type=str, default=CHANGE_DIR_DEFAULT, help="候选变更目录")

    args = parser.parse_args()

    # ── 管理命令 ──
    if args.list_pending:
        pending = list_pending_changes(args.change_dir)
        print_pending_list(pending)
        return

    if args.approve:
        change_path = find_change_file(args.approve, args.change_dir)
        if not change_path:
            logger.error("未找到候选变更: %s", args.approve)
            sys.exit(1)
        success = approve_change(change_path)
        if success:
            change = _load_json(change_path)
            print_change_summary(change)
        return

    if args.reject:
        change_path = find_change_file(args.reject, args.change_dir)
        if not change_path:
            logger.error("未找到候选变更: %s", args.reject)
            sys.exit(1)
        success = reject_change(change_path, reason=args.reason)
        if success:
            change = _load_json(change_path)
            print_change_summary(change)
        return

    # ── 创建模式 ──
    report_sources = []
    if args.report:
        report_sources.append(args.report)
    if args.report_dir:
        if os.path.isdir(args.report_dir):
            for fname in sorted(os.listdir(args.report_dir)):
                if fname.endswith("_eval.json") or fname.endswith("_eval_report.json"):
                    report_sources.append(os.path.join(args.report_dir, fname))
        else:
            logger.error("报告目录不存在: %s", args.report_dir)
            sys.exit(1)

    if not report_sources:
        parser.print_help()
        print("\n错误: 请指定 --report 或 --report-dir 或管理命令。")
        sys.exit(1)

    total_created = 0
    for report_path in report_sources:
        report = _load_json(report_path)
        created = promote_all_suggestions(report, report_path, args.output, dry_run=args.dry_run)
        total_created += len(created)

    if not args.dry_run:
        print(f"\n✅ 处理完成: {len(report_sources)} 个报告, 共创建 {total_created} 个候选变更")
        print(f"   存储目录: {os.path.abspath(args.output)}")

        # 列出新创建的变更
        pending = list_pending_changes(args.output)
        if pending:
            print_pending_list(pending)
    else:
        print(f"\n[DRY RUN] 处理 {len(report_sources)} 个报告, 将创建约 {total_created} 个候选变更")


if __name__ == "__main__":
    main()
