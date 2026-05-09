#!/usr/bin/env python3
"""
rollout_manager.py — Phase 7e: 灰度发布管理器

对通过沙箱回归测试的候选变更进行灰度发布管理。
核心原则：所有变更必须经过沙箱回归测试 → 人工审批 → 灰度发布 → 全量发布。

工作流程:
  1. 加载候选变更 (candidate_change) — 必须已通过 sandbox_pass
  2. 加载灰度策略配置 (rollout-policy.yaml)
  3. 启动灰度发布 → 更新 active-release.yaml 增加 canary_components
  4. 监控灰度状态 → 对比 canary 组 vs baseline 组的 8 维指标
  5. 满足条件 → 全量发布 / 触发回滚条件 → 自动回退

用法:
  # 启动灰度发布
  python scripts/rollout_manager.py start \\
    --change runtime/candidate_changes/change_abc12345.json \\
    --strategy canary

  # 检查灰度状态
  python scripts/rollout_manager.py status change_abc12345

  # 全量发布
  python scripts/rollout_manager.py promote change_abc12345

  # 回滚
  python scripts/rollout_manager.py rollback change_abc12345 --reason "score dropped 0.12"

  # 列出所有灰度中的变更
  python scripts/rollout_manager.py list-active

  # 自动检查回滚条件
  python scripts/rollout_manager.py check-rollback --change change_abc12345

Schema: schemas/candidate_change.schema.json
Config: config/rollout-policy.yaml
"""

import argparse
import json
import logging
import os
import re
import sys
import uuid
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional, Tuple

# ── Constants ──

DEFAULT_ROLLOUT_CONFIG = "config/rollout-policy.yaml"
DEFAULT_CHANGE_DIR = "runtime/candidate_changes/"
DEFAULT_OUTPUT_DIR = "outputs/rollout/"
SCHEMA_PATH = "schemas/candidate_change.schema.json"
ACTIVE_RELEASE_PATH = "config/active-release.yaml"

# 灰度状态枚举
STATUS_PENDING = "pending"
STATUS_CANARY = "canary"
STATUS_FULL = "full"
STATUS_COMPLETED = "completed"
STATUS_ROLLED_BACK = "rolled_back"
STATUS_FAILED = "failed"

VALID_STATUSES = [
    STATUS_PENDING,
    STATUS_CANARY,
    STATUS_FULL,
    STATUS_COMPLETED,
    STATUS_ROLLED_BACK,
    STATUS_FAILED,
]

# 允许的状态转换
ALLOWED_TRANSITIONS = {
    STATUS_PENDING: [STATUS_CANARY, STATUS_FULL, STATUS_ROLLED_BACK],
    STATUS_CANARY: [STATUS_FULL, STATUS_ROLLED_BACK, STATUS_FAILED],
    STATUS_FULL: [STATUS_COMPLETED, STATUS_ROLLED_BACK, STATUS_FAILED],
    STATUS_COMPLETED: [],
    STATUS_ROLLED_BACK: [],
    STATUS_FAILED: [],
}

# 8 维评估指标（与 regression_test.py 一致）
DEFAULT_METRICS = [
    "citation_accuracy",
    "constraint_compliance",
    "format_compliance",
    "risk_detection",
    "human_modification_rate",
    "output_adoption_rate",
    "high_risk_miss_rate",
    "cost_latency",
]

# ── Logging ──

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("rollout_manager")


# ── File I/O Helpers ──


def _load_json(path: str) -> Dict[str, Any]:
    """加载 JSON 文件，返回 dict。"""
    if not os.path.exists(path):
        logger.error("文件不存在: %s", path)
        raise FileNotFoundError(f"文件不存在: {path}")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _write_json(path: str, data: Any) -> None:
    """写入 JSON 文件，自动创建目录。"""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    logger.info("已写入: %s", path)


def _load_yaml(path: str) -> Dict[str, Any]:
    """加载 YAML 文件。"""
    try:
        import yaml
    except ImportError:
        logger.error("需要 PyYAML: pip install pyyaml")
        raise
    if not os.path.exists(path):
        logger.error("YAML 文件不存在: %s", path)
        raise FileNotFoundError(f"YAML 文件不存在: {path}")
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _write_yaml(path: str, data: Any) -> None:
    """写入 YAML 文件，自动创建目录。"""
    try:
        import yaml
    except ImportError:
        logger.error("需要 PyYAML: pip install pyyaml")
        raise
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        yaml.dump(data, f, default_flow_style=False, allow_unicode=True, sort_keys=False)
    logger.info("已写入: %s", path)


# ── Rollout Config Loading ──


def load_rollout_config(config_path: str = DEFAULT_ROLLOUT_CONFIG) -> Dict[str, Any]:
    """加载灰度发布策略配置。"""
    config = _load_yaml(config_path)
    rollout = config.get("rollout", {})
    if not rollout:
        logger.warning("灰度策略配置为空，使用默认值")
        rollout = {
            "default_strategy": "canary",
            "canary": {
                "enabled": True,
                "traffic_split": 0.1,
                "observation_period": "7d",
                "rollback_conditions": {
                    "score_drop_threshold": 0.1,
                    "risk_increase_threshold": "high",
                    "human_modification_increase": 0.2,
                    "high_risk_miss_rate_increase": 0.15,
                    "critical_regression_count": 1,
                },
            },
            "full_rollout": {
                "observation_period": "14d",
                "rollback_conditions": {
                    "score_drop_threshold": 0.05,
                    "risk_increase_threshold": "medium",
                    "human_modification_increase": 0.15,
                    "high_risk_miss_rate_increase": 0.1,
                    "critical_regression_count": 0,
                },
            },
        }
    return rollout


def _parse_observation_period(period_str: str) -> timedelta:
    """解析观察期字符串为 timedelta。

    支持格式:
      - "7d" → 7 天
      - "24h" → 24 小时
      - "2w" → 2 周
    """
    match = re.match(r"^(\d+)([hdw])$", period_str.strip().lower())
    if not match:
        logger.warning("无法解析观察期: %s，使用默认 7d", period_str)
        return timedelta(days=7)

    value = int(match.group(1))
    unit = match.group(2)

    if unit == "h":
        return timedelta(hours=value)
    elif unit == "d":
        return timedelta(days=value)
    elif unit == "w":
        return timedelta(weeks=value)
    else:
        return timedelta(days=7)


# ── Candidate Change Validation ──


def _validate_candidate_for_rollout(change: Dict[str, Any]) -> Tuple[bool, str]:
    """验证候选变更是否满足灰度发布条件。

    必要条件:
      1. 必须包含 change_id
      2. validation.status 必须为 sandbox_pass
      3. approval.required 必须为 True（需要人审）
      4. approval.approved_by 不能为 None（已通过人审）
      5. rollout.status 必须为 pending（尚未开始灰度）
    """
    change_id = change.get("change_id", "")
    if not change_id:
        return False, "缺少 change_id"

    validation = change.get("validation", {})
    val_status = validation.get("status", "")
    if val_status != "sandbox_pass":
        return False, f"validation.status 必须为 sandbox_pass，当前为: {val_status}"

    approval = change.get("approval", {})
    if approval.get("required", True) and not approval.get("approved_by"):
        return False, "候选变更尚未通过人工审批 (approval.approved_by 为空)"

    rollout = change.get("rollout", {})
    roll_status = rollout.get("status", STATUS_PENDING)
    if roll_status not in (STATUS_PENDING, STATUS_CANARY, STATUS_FULL):
        return False, f"rollout.status 必须为 pending/canary/full，当前为: {roll_status}"

    return True, ""


def _validate_status_transition(current: str, target: str) -> Tuple[bool, str]:
    """验证状态转换是否合法。"""
    allowed = ALLOWED_TRANSITIONS.get(current, [])
    if target not in allowed:
        return False, f"不允许的状态转换: {current} → {target} (允许: {allowed})"
    return True, ""


# ── Rollout Record Management ──


def _get_rollout_record_path(change_id: str, output_dir: str = DEFAULT_OUTPUT_DIR) -> str:
    """获取灰度发布记录文件路径。"""
    return os.path.join(output_dir, f"{change_id}_rollout.json")


def _load_rollout_record(change_id: str, output_dir: str = DEFAULT_OUTPUT_DIR) -> Optional[Dict[str, Any]]:
    """加载灰度发布记录。"""
    path = _get_rollout_record_path(change_id, output_dir)
    if os.path.exists(path):
        return _load_json(path)
    return None


def _save_rollout_record(record: Dict[str, Any], output_dir: str = DEFAULT_OUTPUT_DIR) -> str:
    """保存灰度发布记录。"""
    change_id = record.get("change_id", "unknown")
    path = _get_rollout_record_path(change_id, output_dir)
    _write_json(path, record)
    return path


def _create_rollout_record(
    change: Dict[str, Any],
    strategy: str,
    traffic_split: float,
    observation_period: str,
    config: Dict[str, Any],
) -> Dict[str, Any]:
    """创建新的灰度发布记录。"""
    change_id = change.get("change_id", "unknown")
    now = datetime.now(timezone.utc).isoformat()

    # 解析观察期
    obs_delta = _parse_observation_period(observation_period)
    expected_end = (datetime.now(timezone.utc) + obs_delta).isoformat()

    return {
        "change_id": change_id,
        "status": STATUS_CANARY if strategy == "canary" else STATUS_FULL,
        "strategy": strategy,
        "traffic_split": traffic_split,
        "observation_period": observation_period,
        "expected_end": expected_end,
        "rollback_conditions": config.get("rollback_conditions", {}),
        "started_at": now,
        "updated_at": now,
        "completed_at": None,
        "rolled_back_at": None,
        "rollback_reason": None,
        "events": [
            {
                "timestamp": now,
                "event": "started",
                "details": f"灰度发布启动: strategy={strategy}, traffic_split={traffic_split}",
            }
        ],
        "metrics_snapshots": [],
        "rollback_checks": [],
    }


# ── Rollout Operations ──


def start_rollout(
    change_path: str,
    strategy: Optional[str] = None,
    traffic_split: Optional[float] = None,
    rollout_config_path: str = DEFAULT_ROLLOUT_CONFIG,
    output_dir: str = DEFAULT_OUTPUT_DIR,
    force: bool = False,
) -> Dict[str, Any]:
    """
    启动灰度发布。

    Args:
        change_path: 候选变更 JSON 文件路径
        strategy: 灰度策略 (canary/full)，默认从配置读取
        traffic_split: 流量比例，默认从配置读取
        rollout_config_path: 灰度策略配置文件路径
        output_dir: 输出目录
        force: 是否跳过验证（用于测试）

    Returns:
        rollout_record: 灰度发布记录
    """
    # 1. 加载候选变更
    logger.info("=" * 60)
    logger.info("启动灰度发布: %s", change_path)
    change = _load_json(change_path)
    change_id = change.get("change_id", "unknown")
    logger.info("候选变更 ID: %s", change_id)

    # 2. 验证候选变更
    if not force:
        valid, msg = _validate_candidate_for_rollout(change)
        if not valid:
            logger.error("候选变更验证失败: %s", msg)
            raise ValueError(f"候选变更验证失败: {msg}")

    # 3. 加载灰度策略配置
    config = load_rollout_config(rollout_config_path)

    # 4. 确定策略和参数
    if strategy is None:
        strategy = config.get("default_strategy", "canary")

    if strategy == "canary":
        canary_config = config.get("canary", {})
        if traffic_split is None:
            traffic_split = canary_config.get("traffic_split", 0.1)
        observation_period = canary_config.get("observation_period", "7d")
    elif strategy == "full":
        full_config = config.get("full_rollout", {})
        if traffic_split is None:
            traffic_split = 1.0  # 全量发布 = 100% 流量
        observation_period = full_config.get("observation_period", "14d")
    else:
        raise ValueError(f"无效的灰度策略: {strategy} (可选: canary, full)")

    # 5. 创建灰度发布记录
    record = _create_rollout_record(change, strategy, traffic_split, observation_period, config)

    # 6. 更新候选变更的 rollout 字段
    change["rollout"]["strategy"] = strategy
    change["rollout"]["traffic_split"] = traffic_split
    change["rollout"]["status"] = record["status"]
    _write_json(change_path, change)
    logger.info("已更新候选变更 rollout 状态: %s", record["status"])

    # 7. 保存灰度发布记录
    record_path = _save_rollout_record(record, output_dir)
    logger.info("灰度发布记录已保存: %s", record_path)

    # 8. 打印摘要
    _print_rollout_summary(record, change)

    return record


def get_rollout_status(
    change_id: str,
    change_dir: str = DEFAULT_CHANGE_DIR,
    output_dir: str = DEFAULT_OUTPUT_DIR,
) -> Dict[str, Any]:
    """
    获取灰度发布状态。

    Args:
        change_id: 候选变更 ID
        change_dir: 候选变更目录
        output_dir: 输出目录

    Returns:
        status_info: 包含状态信息的字典
    """
    # 1. 加载灰度发布记录
    record = _load_rollout_record(change_id, output_dir)
    if not record:
        logger.warning("未找到灰度发布记录: %s", change_id)
        return {"change_id": change_id, "status": "not_found", "error": "未找到灰度发布记录"}

    # 2. 加载候选变更
    change_path = os.path.join(change_dir, f"{change_id}.json")
    change = None
    if os.path.exists(change_path):
        change = _load_json(change_path)

    # 3. 检查观察期是否到期
    now = datetime.now(timezone.utc)
    expected_end_str = record.get("expected_end", "")
    observation_expired = False
    remaining_time = None

    if expected_end_str:
        try:
            expected_end = datetime.fromisoformat(expected_end_str)
            if now >= expected_end:
                observation_expired = True
            else:
                remaining = expected_end - now
                remaining_time = str(remaining).split(".")[0]  # 去掉微秒
        except (ValueError, TypeError):
            pass

    # 4. 构建状态信息
    status_info = {
        "change_id": change_id,
        "status": record.get("status", "unknown"),
        "strategy": record.get("strategy", "unknown"),
        "traffic_split": record.get("traffic_split", 0),
        "observation_period": record.get("observation_period", ""),
        "expected_end": expected_end_str,
        "observation_expired": observation_expired,
        "remaining_time": remaining_time,
        "started_at": record.get("started_at", ""),
        "updated_at": record.get("updated_at", ""),
        "events_count": len(record.get("events", [])),
        "metrics_snapshots_count": len(record.get("metrics_snapshots", [])),
        "rollback_checks_count": len(record.get("rollback_checks", [])),
    }

    if change:
        status_info["change"] = {
            "target_component": change.get("target", {}).get("component", ""),
            "change_type": change.get("target", {}).get("change_type", ""),
            "validation_status": change.get("validation", {}).get("status", ""),
            "approved_by": change.get("approval", {}).get("approved_by", ""),
        }

    return status_info


def promote_rollout(
    change_id: str,
    change_dir: str = DEFAULT_CHANGE_DIR,
    output_dir: str = DEFAULT_OUTPUT_DIR,
    force: bool = False,
) -> Dict[str, Any]:
    """
    全量发布（从 canary 晋升到 full，或从 full 晋升到 completed）。

    Args:
        change_id: 候选变更 ID
        change_dir: 候选变更目录
        output_dir: 输出目录
        force: 是否跳过观察期检查

    Returns:
        updated_record: 更新后的灰度发布记录
    """
    # 1. 加载灰度发布记录
    record = _load_rollout_record(change_id, output_dir)
    if not record:
        raise ValueError(f"未找到灰度发布记录: {change_id}")

    current_status = record.get("status", "")
    now = datetime.now(timezone.utc).isoformat()

    # 2. 确定目标状态
    if current_status == STATUS_CANARY:
        target_status = STATUS_FULL
    elif current_status == STATUS_FULL:
        target_status = STATUS_COMPLETED
    else:
        raise ValueError(f"当前状态 {current_status} 不允许 promote（需要 canary 或 full）")

    # 3. 验证状态转换
    valid, msg = _validate_status_transition(current_status, target_status)
    if not valid:
        raise ValueError(msg)

    # 4. 检查观察期（非 force 模式）
    if not force and current_status == STATUS_CANARY:
        expected_end_str = record.get("expected_end", "")
        if expected_end_str:
            try:
                expected_end = datetime.fromisoformat(expected_end_str)
                if datetime.now(timezone.utc) < expected_end:
                    remaining = expected_end - datetime.now(timezone.utc)
                    remaining_str = str(remaining).split(".")[0]
                    logger.warning("观察期尚未结束，剩余: %s", remaining_str)
                    logger.warning("使用 --force 可跳过观察期检查")
                    raise ValueError(f"观察期尚未结束，剩余: {remaining_str}")
            except (ValueError, TypeError):
                pass

    # 5. 更新记录
    record["status"] = target_status
    record["updated_at"] = now
    if target_status == STATUS_COMPLETED:
        record["completed_at"] = now

    record["events"].append({
        "timestamp": now,
        "event": "promoted",
        "details": f"晋升到 {target_status}",
    })

    # 6. 更新候选变更
    change_path = os.path.join(change_dir, f"{change_id}.json")
    if os.path.exists(change_path):
        change = _load_json(change_path)
        change["rollout"]["status"] = target_status
        if target_status == STATUS_COMPLETED:
            change["rollout"]["traffic_split"] = 1.0
        _write_json(change_path, change)
        logger.info("已更新候选变更 rollout 状态: %s", target_status)

    # 7. 保存记录
    _save_rollout_record(record, output_dir)

    # 8. 打印摘要
    _print_rollout_summary(record)

    return record


def rollback_rollout(
    change_id: str,
    reason: str = "手动回滚",
    change_dir: str = DEFAULT_CHANGE_DIR,
    output_dir: str = DEFAULT_OUTPUT_DIR,
) -> Dict[str, Any]:
    """
    回滚灰度发布。

    Args:
        change_id: 候选变更 ID
        reason: 回滚原因
        change_dir: 候选变更目录
        output_dir: 输出目录

    Returns:
        updated_record: 更新后的灰度发布记录
    """
    # 1. 加载灰度发布记录
    record = _load_rollout_record(change_id, output_dir)
    if not record:
        raise ValueError(f"未找到灰度发布记录: {change_id}")

    current_status = record.get("status", "")
    now = datetime.now(timezone.utc).isoformat()

    # 2. 验证状态转换
    valid, msg = _validate_status_transition(current_status, STATUS_ROLLED_BACK)
    if not valid:
        raise ValueError(msg)

    # 3. 更新记录
    record["status"] = STATUS_ROLLED_BACK
    record["updated_at"] = now
    record["rolled_back_at"] = now
    record["rollback_reason"] = reason

    record["events"].append({
        "timestamp": now,
        "event": "rolled_back",
        "details": f"回滚原因: {reason}",
    })

    # 4. 更新候选变更
    change_path = os.path.join(change_dir, f"{change_id}.json")
    if os.path.exists(change_path):
        change = _load_json(change_path)
        change["rollout"]["status"] = STATUS_ROLLED_BACK
        _write_json(change_path, change)
        logger.info("已更新候选变更 rollout 状态: rolled_back")

    # 5. 保存记录
    _save_rollout_record(record, output_dir)

    # 6. 打印摘要
    _print_rollout_summary(record)

    return record


def list_active_rollouts(
    change_dir: str = DEFAULT_CHANGE_DIR,
    output_dir: str = DEFAULT_OUTPUT_DIR,
) -> List[Dict[str, Any]]:
    """
    列出所有活跃的灰度发布（canary 或 full 状态）。

    Args:
        change_dir: 候选变更目录
        output_dir: 输出目录

    Returns:
        active_rollouts: 活跃灰度发布列表
    """
    active = []
    active_statuses = {STATUS_CANARY, STATUS_FULL}

    # 从输出目录查找所有灰度发布记录
    if not os.path.isdir(output_dir):
        return active

    for fname in sorted(os.listdir(output_dir)):
        if not fname.endswith("_rollout.json"):
            continue
        fpath = os.path.join(output_dir, fname)
        try:
            record = _load_json(fpath)
            if record.get("status") in active_statuses:
                # 补充候选变更信息
                change_id = record.get("change_id", "")
                change_path = os.path.join(change_dir, f"{change_id}.json")
                if os.path.exists(change_path):
                    change = _load_json(change_path)
                    record["_change"] = {
                        "target_component": change.get("target", {}).get("component", ""),
                        "change_type": change.get("target", {}).get("change_type", ""),
                    }
                active.append(record)
        except Exception as e:
            logger.warning("读取灰度发布记录失败: %s — %s", fpath, e)
            continue

    return active


# ── Rollback Condition Checking ──


def check_rollback_conditions(
    change_id: str,
    baseline_scores: Optional[Dict[str, float]] = None,
    patched_scores: Optional[Dict[str, float]] = None,
    regression_report: Optional[Dict[str, Any]] = None,
    change_dir: str = DEFAULT_CHANGE_DIR,
    output_dir: str = DEFAULT_OUTPUT_DIR,
    rollout_config_path: str = DEFAULT_ROLLOUT_CONFIG,
) -> Dict[str, Any]:
    """
    检查灰度发布是否触发回滚条件。

    支持两种检查方式:
      1. 直接传入 baseline/patched 分数对比
      2. 传入 regression_report 自动提取分数

    Args:
        change_id: 候选变更 ID
        baseline_scores: baseline 各维度分数
        patched_scores: patched 各维度分数
        regression_report: 回归测试报告（自动提取分数）
        change_dir: 候选变更目录
        output_dir: 输出目录
        rollout_config_path: 灰度策略配置文件路径

    Returns:
        check_result: {
            "should_rollback": bool,
            "triggered_conditions": [str],
            "details": { ... },
        }
    """
    # 1. 加载灰度发布记录
    record = _load_rollout_record(change_id, output_dir)
    if not record:
        raise ValueError(f"未找到灰度发布记录: {change_id}")

    # 2. 加载灰度策略配置
    config = load_rollout_config(rollout_config_path)
    strategy = record.get("strategy", "canary")

    if strategy == "canary":
        strategy_config = config.get("canary", {})
    else:
        strategy_config = config.get("full_rollout", {})

    rollback_conditions = strategy_config.get("rollback_conditions", {})

    # 3. 提取分数
    if regression_report:
        summary = regression_report.get("summary", {})
        dimensions = summary.get("dimensions", {})
        baseline_scores = {}
        patched_scores = {}
        for dim, data in dimensions.items():
            baseline_scores[dim] = data.get("baseline", 0.5)
            patched_scores[dim] = data.get("patched", 0.5)

    if not baseline_scores or not patched_scores:
        return {
            "change_id": change_id,
            "should_rollback": False,
            "triggered_conditions": [],
            "details": {"error": "缺少分数数据，无法检查回滚条件"},
        }

    # 4. 检查各回滚条件
    triggered = []
    details = {}

    # 4a. 综合评分下降
    score_drop_threshold = rollback_conditions.get("score_drop_threshold", 0.1)
    baseline_overall = sum(baseline_scores.get(d, 0.5) for d in DEFAULT_METRICS) / len(DEFAULT_METRICS)
    patched_overall = sum(patched_scores.get(d, 0.5) for d in DEFAULT_METRICS) / len(DEFAULT_METRICS)
    score_drop = baseline_overall - patched_overall

    details["overall_score"] = {
        "baseline": round(baseline_overall, 4),
        "patched": round(patched_overall, 4),
        "drop": round(score_drop, 4),
        "threshold": score_drop_threshold,
    }

    if score_drop > score_drop_threshold:
        triggered.append(f"综合评分下降 {score_drop:.4f} > 阈值 {score_drop_threshold}")

    # 4b. 高风险漏检率上升
    hrmr_threshold = rollback_conditions.get("high_risk_miss_rate_increase", 0.15)
    baseline_hrmr = baseline_scores.get("high_risk_miss_rate", 0.5)
    patched_hrmr = patched_scores.get("high_risk_miss_rate", 0.5)
    hrmr_increase = patched_hrmr - baseline_hrmr

    details["high_risk_miss_rate"] = {
        "baseline": baseline_hrmr,
        "patched": patched_hrmr,
        "increase": round(hrmr_increase, 4),
        "threshold": hrmr_threshold,
    }

    if hrmr_increase > hrmr_threshold:
        triggered.append(f"高风险漏检率上升 {hrmr_increase:.4f} > 阈值 {hrmr_threshold}")

    # 4c. 人工修改率上升
    hmr_threshold = rollback_conditions.get("human_modification_increase", 0.2)
    baseline_hmr = baseline_scores.get("human_modification_rate", 0.5)
    patched_hmr = patched_scores.get("human_modification_rate", 0.5)
    hmr_increase = patched_hmr - baseline_hmr

    details["human_modification_rate"] = {
        "baseline": baseline_hmr,
        "patched": patched_hmr,
        "increase": round(hmr_increase, 4),
        "threshold": hmr_threshold,
    }

    if hmr_increase > hmr_threshold:
        triggered.append(f"人工修改率上升 {hmr_increase:.4f} > 阈值 {hmr_threshold}")

    # 4d. 风险等级上升
    risk_threshold = rollback_conditions.get("risk_increase_threshold", "high")
    baseline_risk = baseline_scores.get("risk_detection", 0.5)
    patched_risk = patched_scores.get("risk_detection", 0.5)
    risk_drop = baseline_risk - patched_risk

    details["risk_detection"] = {
        "baseline": baseline_risk,
        "patched": patched_risk,
        "drop": round(risk_drop, 4),
        "threshold_label": risk_threshold,
    }

    # 如果风险检测分数下降超过 0.2，视为风险等级上升
    risk_drop_threshold = 0.2
    if risk_drop > risk_drop_threshold:
        triggered.append(f"风险检测分数下降 {risk_drop:.4f} > 阈值 {risk_drop_threshold}")

    # 4e. Critical regression 数量
    if regression_report:
        summary = regression_report.get("summary", {})
        dimensions = summary.get("dimensions", {})
        critical_count = sum(
            1 for d in dimensions.values()
            if d.get("status") == "critical_regression"
        )
        critical_threshold = rollback_conditions.get("critical_regression_count", 1)

        details["critical_regressions"] = {
            "count": critical_count,
            "threshold": critical_threshold,
        }

        if critical_count > critical_threshold:
            triggered.append(f"Critical regression 数量 {critical_count} > 阈值 {critical_threshold}")

    # 5. 综合判定
    should_rollback = len(triggered) > 0

    # 6. 记录检查结果
    now = datetime.now(timezone.utc).isoformat()
    check_entry = {
        "timestamp": now,
        "should_rollback": should_rollback,
        "triggered_conditions": triggered,
        "details": details,
    }

    record["rollback_checks"].append(check_entry)
    record["updated_at"] = now
    _save_rollout_record(record, output_dir)

    return {
        "change_id": change_id,
        "should_rollback": should_rollback,
        "triggered_conditions": triggered,
        "details": details,
    }


# ── Metrics Snapshot Recording ──


def record_metrics_snapshot(
    change_id: str,
    scores: Dict[str, float],
    group: str = "canary",
    output_dir: str = DEFAULT_OUTPUT_DIR,
) -> Dict[str, Any]:
    """
    记录灰度组的指标快照。

    Args:
        change_id: 候选变更 ID
        scores: 各维度分数
        group: 分组 (canary/baseline)
        output_dir: 输出目录

    Returns:
        updated_record: 更新后的灰度发布记录
    """
    record = _load_rollout_record(change_id, output_dir)
    if not record:
        raise ValueError(f"未找到灰度发布记录: {change_id}")

    snapshot = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "group": group,
        "scores": scores,
    }

    record["metrics_snapshots"].append(snapshot)
    record["updated_at"] = snapshot["timestamp"]
    _save_rollout_record(record, output_dir)

    return record


# ── Print Helpers ──


def _print_rollout_summary(record: Dict[str, Any], change: Optional[Dict[str, Any]] = None) -> None:
    """打印灰度发布摘要。"""
    status = record.get("status", "unknown")
    strategy = record.get("strategy", "unknown")
    change_id = record.get("change_id", "unknown")

    status_icon = {
        STATUS_PENDING: "⏳",
        STATUS_CANARY: "🐤",
        STATUS_FULL: "🚀",
        STATUS_COMPLETED: "✅",
        STATUS_ROLLED_BACK: "↩️",
        STATUS_FAILED: "❌",
    }
    icon = status_icon.get(status, "❓")

    print(f"\n{'=' * 60}")
    print(f"  {icon} 灰度发布状态: {status}")
    print(f"  ID: {change_id}")
    print(f"  策略: {strategy}")
    print(f"  流量比例: {record.get('traffic_split', 0) * 100:.0f}%")
    print(f"  观察期: {record.get('observation_period', '?')}")
    print(f"  预计结束: {record.get('expected_end', '?')}")
    print(f"  开始时间: {record.get('started_at', '?')}")
    print(f"  事件数: {len(record.get('events', []))}")

    if change:
        target = change.get("target", {})
        print(f"  目标组件: {target.get('component', '?')}")
        print(f"  变更类型: {target.get('change_type', '?')}")

    if record.get("rollback_reason"):
        print(f"  回滚原因: {record['rollback_reason']}")

    print(f"{'=' * 60}\n")


def _print_status(status_info: Dict[str, Any]) -> None:
    """打印灰度状态详情。"""
    if status_info.get("status") == "not_found":
        print(f"\n⚠️  未找到灰度发布记录: {status_info.get('change_id', '?')}\n")
        return

    status = status_info.get("status", "unknown")
    status_icon = {
        STATUS_PENDING: "⏳",
        STATUS_CANARY: "🐤",
        STATUS_FULL: "🚀",
        STATUS_COMPLETED: "✅",
        STATUS_ROLLED_BACK: "↩️",
        STATUS_FAILED: "❌",
    }
    icon = status_icon.get(status, "❓")

    print(f"\n{'─' * 50}")
    print(f"  {icon} 灰度发布状态: {status}")
    print(f"  ID: {status_info.get('change_id', '?')}")
    print(f"  策略: {status_info.get('strategy', '?')}")
    print(f"  流量比例: {status_info.get('traffic_split', 0) * 100:.0f}%")
    print(f"  观察期: {status_info.get('observation_period', '?')}")
    print(f"  预计结束: {status_info.get('expected_end', '?')}")
    print(f"  观察期到期: {'是' if status_info.get('observation_expired') else '否'}")
    if status_info.get("remaining_time"):
        print(f"  剩余时间: {status_info['remaining_time']}")
    print(f"  开始时间: {status_info.get('started_at', '?')}")
    print(f"  事件数: {status_info.get('events_count', 0)}")
    print(f"  指标快照数: {status_info.get('metrics_snapshots_count', 0)}")
    print(f"  回滚检查数: {status_info.get('rollback_checks_count', 0)}")

    change = status_info.get("change")
    if change:
        print(f"  目标组件: {change.get('target_component', '?')}")
        print(f"  变更类型: {change.get('change_type', '?')}")
        print(f"  审批人: {change.get('approved_by', '?')}")

    print(f"{'─' * 50}\n")


def _print_active_rollouts(active: List[Dict[str, Any]]) -> None:
    """打印活跃灰度发布列表。"""
    if not active:
        print("\n📭 没有活跃的灰度发布\n")
        return

    print(f"\n{'─' * 60}")
    print(f"  活跃灰度发布 ({len(active)}):")
    print(f"{'─' * 60}")

    for i, record in enumerate(active, 1):
        change_id = record.get("change_id", "?")
        status = record.get("status", "?")
        strategy = record.get("strategy", "?")
        traffic = record.get("traffic_split", 0) * 100
        change = record.get("_change", {})

        print(f"  {i}. {change_id}")
        print(f"     状态: {status} | 策略: {strategy} | 流量: {traffic:.0f}%")
        if change:
            print(f"     组件: {change.get('target_component', '?')} | 类型: {change.get('change_type', '?')}")
        print()

    print(f"{'─' * 60}\n")


# ── CLI ──


def main():
    parser = argparse.ArgumentParser(
        description="Phase 7e: 灰度发布管理器",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 启动灰度发布
  python scripts/rollout_manager.py start \\
      --change runtime/candidate_changes/change_abc12345.json

  # 检查灰度状态
  python scripts/rollout_manager.py status change_abc12345

  # 全量发布
  python scripts/rollout_manager.py promote change_abc12345

  # 回滚
  python scripts/rollout_manager.py rollback change_abc12345 --reason "score dropped 0.12"

  # 列出所有灰度中的变更
  python scripts/rollout_manager.py list-active

  # 检查回滚条件
  python scripts/rollout_manager.py check-rollback \\
      --change change_abc12345 \\
      --regression-report outputs/eval_reports/regression/change_abc12345_regression_report.json
        """,
    )

    subparsers = parser.add_subparsers(dest="command", help="可用命令")

    # ── start ──
    start_parser = subparsers.add_parser("start", help="启动灰度发布")
    start_parser.add_argument(
        "--change", type=str, required=True,
        help="候选变更 JSON 文件路径"
    )
    start_parser.add_argument(
        "--strategy", choices=["canary", "full"], default=None,
        help="灰度策略 (默认: 从 rollout-policy.yaml 读取)"
    )
    start_parser.add_argument(
        "--traffic-split", type=float, default=None,
        help="流量比例 (默认: 从 rollout-policy.yaml 读取)"
    )
    start_parser.add_argument(
        "--config", type=str, default=DEFAULT_ROLLOUT_CONFIG,
        help=f"灰度策略配置文件 (默认: {DEFAULT_ROLLOUT_CONFIG})"
    )
    start_parser.add_argument(
        "--output", type=str, default=DEFAULT_OUTPUT_DIR,
        help=f"输出目录 (默认: {DEFAULT_OUTPUT_DIR})"
    )
    start_parser.add_argument(
        "--force", action="store_true",
        help="跳过候选变更验证"
    )

    # ── status ──
    status_parser = subparsers.add_parser("status", help="检查灰度发布状态")
    status_parser.add_argument(
        "change_id", type=str,
        help="候选变更 ID"
    )
    status_parser.add_argument(
        "--change-dir", type=str, default=DEFAULT_CHANGE_DIR,
        help=f"候选变更目录 (默认: {DEFAULT_CHANGE_DIR})"
    )
    status_parser.add_argument(
        "--output", type=str, default=DEFAULT_OUTPUT_DIR,
        help=f"输出目录 (默认: {DEFAULT_OUTPUT_DIR})"
    )

    # ── promote ──
    promote_parser = subparsers.add_parser("promote", help="全量发布")
    promote_parser.add_argument(
        "change_id", type=str,
        help="候选变更 ID"
    )
    promote_parser.add_argument(
        "--change-dir", type=str, default=DEFAULT_CHANGE_DIR,
        help=f"候选变更目录 (默认: {DEFAULT_CHANGE_DIR})"
    )
    promote_parser.add_argument(
        "--output", type=str, default=DEFAULT_OUTPUT_DIR,
        help=f"输出目录 (默认: {DEFAULT_OUTPUT_DIR})"
    )
    promote_parser.add_argument(
        "--force", action="store_true",
        help="跳过观察期检查"
    )

    # ── rollback ──
    rollback_parser = subparsers.add_parser("rollback", help="回滚灰度发布")
    rollback_parser.add_argument(
        "change_id", type=str,
        help="候选变更 ID"
    )
    rollback_parser.add_argument(
        "--reason", type=str, default="手动回滚",
        help="回滚原因"
    )
    rollback_parser.add_argument(
        "--change-dir", type=str, default=DEFAULT_CHANGE_DIR,
        help=f"候选变更目录 (默认: {DEFAULT_CHANGE_DIR})"
    )
    rollback_parser.add_argument(
        "--output", type=str, default=DEFAULT_OUTPUT_DIR,
        help=f"输出目录 (默认: {DEFAULT_OUTPUT_DIR})"
    )

    # ── list-active ──
    list_parser = subparsers.add_parser("list-active", help="列出所有活跃的灰度发布")
    list_parser.add_argument(
        "--change-dir", type=str, default=DEFAULT_CHANGE_DIR,
        help=f"候选变更目录 (默认: {DEFAULT_CHANGE_DIR})"
    )
    list_parser.add_argument(
        "--output", type=str, default=DEFAULT_OUTPUT_DIR,
        help=f"输出目录 (默认: {DEFAULT_OUTPUT_DIR})"
    )

    # ── check-rollback ──
    check_parser = subparsers.add_parser("check-rollback", help="检查回滚条件")
    check_parser.add_argument(
        "--change", type=str, required=True,
        help="候选变更 ID"
    )
    check_parser.add_argument(
        "--regression-report", type=str, default=None,
        help="回归测试报告 JSON 文件路径"
    )
    check_parser.add_argument(
        "--baseline-scores", type=str, default=None,
        help="Baseline 分数 JSON 文件路径"
    )
    check_parser.add_argument(
        "--patched-scores", type=str, default=None,
        help="Patched 分数 JSON 文件路径"
    )
    check_parser.add_argument(
        "--config", type=str, default=DEFAULT_ROLLOUT_CONFIG,
        help=f"灰度策略配置文件 (默认: {DEFAULT_ROLLOUT_CONFIG})"
    )
    check_parser.add_argument(
        "--change-dir", type=str, default=DEFAULT_CHANGE_DIR,
        help=f"候选变更目录 (默认: {DEFAULT_CHANGE_DIR})"
    )
    check_parser.add_argument(
        "--output", type=str, default=DEFAULT_OUTPUT_DIR,
        help=f"输出目录 (默认: {DEFAULT_OUTPUT_DIR})"
    )

    # ── record-metrics ──
    metrics_parser = subparsers.add_parser("record-metrics", help="记录指标快照")
    metrics_parser.add_argument(
        "--change", type=str, required=True,
        help="候选变更 ID"
    )
    metrics_parser.add_argument(
        "--scores", type=str, required=True,
        help="各维度分数 JSON 文件路径"
    )
    metrics_parser.add_argument(
        "--group", choices=["canary", "baseline"], default="canary",
        help="分组 (默认: canary)"
    )
    metrics_parser.add_argument(
        "--output", type=str, default=DEFAULT_OUTPUT_DIR,
        help=f"输出目录 (默认: {DEFAULT_OUTPUT_DIR})"
    )

    args = parser.parse_args()

    # ── 执行命令 ──
    if args.command == "start":
        record = start_rollout(
            change_path=args.change,
            strategy=args.strategy,
            traffic_split=args.traffic_split,
            rollout_config_path=args.config,
            output_dir=args.output,
            force=args.force,
        )
        if record.get("status") == "failed":
            sys.exit(1)

    elif args.command == "status":
        status_info = get_rollout_status(
            change_id=args.change_id,
            change_dir=args.change_dir,
            output_dir=args.output,
        )
        _print_status(status_info)

    elif args.command == "promote":
        record = promote_rollout(
            change_id=args.change_id,
            change_dir=args.change_dir,
            output_dir=args.output,
            force=args.force,
        )

    elif args.command == "rollback":
        record = rollback_rollout(
            change_id=args.change_id,
            reason=args.reason,
            change_dir=args.change_dir,
            output_dir=args.output,
        )

    elif args.command == "list-active":
        active = list_active_rollouts(
            change_dir=args.change_dir,
            output_dir=args.output,
        )
        _print_active_rollouts(active)

    elif args.command == "check-rollback":
        # 加载分数数据
        baseline_scores = None
        patched_scores = None
        regression_report = None

        if args.regression_report:
            regression_report = _load_json(args.regression_report)
        if args.baseline_scores:
            baseline_scores = _load_json(args.baseline_scores)
        if args.patched_scores:
            patched_scores = _load_json(args.patched_scores)

        result = check_rollback_conditions(
            change_id=args.change,
            baseline_scores=baseline_scores,
            patched_scores=patched_scores,
            regression_report=regression_report,
            change_dir=args.change_dir,
            output_dir=args.output,
            rollout_config_path=args.config,
        )

        # 打印结果
        print(f"\n{'─' * 50}")
        if result["should_rollback"]:
            print(f"  ❌ 触发回滚条件 ({len(result['triggered_conditions'])}):")
            for cond in result["triggered_conditions"]:
                print(f"     - {cond}")
        else:
            print(f"  ✅ 未触发回滚条件")
        print(f"{'─' * 50}\n")

    elif args.command == "record-metrics":
        scores = _load_json(args.scores)
        record = record_metrics_snapshot(
            change_id=args.change,
            scores=scores,
            group=args.group,
            output_dir=args.output,
        )
        print(f"\n✅ 指标快照已记录 (group={args.group})\n")

    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
