#!/usr/bin/env python3
"""
dashboard.py — Phase 7f: 质量仪表盘数据聚合 + 自动回滚

可视化的质量趋势看板，并在触发预设条件时自动执行回滚。

核心功能:
  1. 趋势数据聚合 — 从 eval_reports/ 目录聚合多日趋势数据
  2. 自动告警检查 — 检查是否触发预设的告警/回滚条件
  3. 自动回滚触发 — 满足条件时自动调用 rollout_manager.py 执行回滚
  4. HTML 仪表盘生成 — 生成可视化 HTML 页面（后续版本）

数据流:
  eval_reports/ (评估报告 JSON)
      │
      ▼
  aggregate_trends() → _trend_data.json (时间序列聚合)
      │
      ▼
  check_alerts() → _alerts.json (告警记录)
      │
      ▼
  auto_rollback() → rollout_manager.py rollback (自动回滚)

用法:
  # 聚合趋势数据
  python scripts/dashboard.py aggregate \\
      --report-dir outputs/eval_reports/ \\
      --output outputs/dashboard/_trend_data.json

  # 检查告警
  python scripts/dashboard.py check-alerts \\
      --trend outputs/dashboard/_trend_data.json

  # 自动回滚检查（检查 + 自动执行回滚）
  python scripts/dashboard.py auto-rollback \\
      --trend outputs/dashboard/_trend_data.json \\
      --rollout-dir outputs/rollout/

  # 生成 HTML 仪表盘（后续版本）
  python scripts/dashboard.py generate-html \\
      --trend outputs/dashboard/_trend_data.json \\
      --output outputs/dashboard/index.html

  # 查看仪表盘统计
  python scripts/dashboard.py stats \\
      --trend outputs/dashboard/_trend_data.json

Schema: schemas/eval_report.schema.json
Config: config/dashboard-config.yaml
"""

import argparse
import json
import logging
import os
import re
import sys
import uuid
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional, Tuple

# ── Constants ──

DEFAULT_DASHBOARD_CONFIG = "config/dashboard-config.yaml"
DEFAULT_REPORT_DIR = "outputs/eval_reports/"
DEFAULT_OUTPUT_DIR = "outputs/dashboard/"
DEFAULT_ROLLOUT_DIR = "outputs/rollout/"
DEFAULT_CHANGE_DIR = "runtime/candidate_changes/"
SCHEMA_PATH = "schemas/eval_report.schema.json"

# 默认评估维度（与 dashboard-config.yaml 保持一致）
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

# 告警严重级别
SEVERITY_CRITICAL = "critical"
SEVERITY_WARNING = "warning"
SEVERITY_INFO = "info"

# 告警操作类型
ACTION_ROLLBACK_CANARY = "rollback_canary"
ACTION_NOTIFY_ONLY = "notify_only"

# ── Logging ──

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("dashboard")


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


# ── Config Loading ──


def load_dashboard_config(config_path: str = DEFAULT_DASHBOARD_CONFIG) -> Dict[str, Any]:
    """加载仪表盘配置。"""
    config = _load_yaml(config_path)
    if not config:
        logger.warning("仪表盘配置为空，使用默认值")
        config = _get_default_config()
    return config


def _get_default_config() -> Dict[str, Any]:
    """获取默认仪表盘配置。"""
    return {
        "dashboard": {
            "aggregation": {
                "trend_window_days": 30,
                "min_data_points": 3,
                "granularity": "daily",
                "output_path": "outputs/dashboard/",
            },
            "metrics": [
                {"id": m, "name": m, "higher_is_better": True, "weight": 1.0}
                for m in DEFAULT_METRICS
            ],
            "scoring": {
                "method": "weighted_average",
                "tiers": {
                    "excellent": 0.90,
                    "good": 0.80,
                    "fair": 0.70,
                    "poor": 0.50,
                    "critical": 0.0,
                },
            },
        },
        "alerts": {
            "auto_rollback_triggers": [],
            "notification": {
                "console_output": True,
                "alerts_output_path": "outputs/dashboard/_alerts.json",
                "dedup_window": "1h",
            },
            "dashboard": {
                "output_path": "outputs/dashboard/",
                "generate_html": False,
                "trend_data_path": "outputs/dashboard/_trend_data.json",
            },
        },
    }


# ── Time Parsing Helpers ──


def _parse_time_window(window_str: str) -> timedelta:
    """解析时间窗口字符串为 timedelta。

    支持格式:
      - "24h" → 24 小时
      - "7d" → 7 天
      - "2w" → 2 周
    """
    match = re.match(r"^(\d+)([hdw])$", window_str.strip().lower())
    if not match:
        logger.warning("无法解析时间窗口: %s，使用默认 24h", window_str)
        return timedelta(hours=24)

    value = int(match.group(1))
    unit = match.group(2)

    if unit == "h":
        return timedelta(hours=value)
    elif unit == "d":
        return timedelta(days=value)
    elif unit == "w":
        return timedelta(weeks=value)
    else:
        return timedelta(hours=24)


def _parse_timestamp(ts_str: str) -> Optional[datetime]:
    """解析 ISO 时间戳字符串为 datetime 对象。"""
    try:
        return datetime.fromisoformat(ts_str)
    except (ValueError, TypeError):
        return None


def _get_date_key(dt: datetime) -> str:
    """获取日期键（用于按天聚合）。"""
    return dt.strftime("%Y-%m-%d")


def _get_hour_key(dt: datetime) -> str:
    """获取小时键（用于按小时聚合）。"""
    return dt.strftime("%Y-%m-%dT%H:00:00")


# ── Report Scanning ──


def scan_eval_reports(report_dir: str) -> List[Dict[str, Any]]:
    """扫描评估报告目录，返回所有有效的评估报告列表。

    支持的报告文件命名模式:
      - *_eval.json
      - *_eval_report.json
      - *_regression_report.json
      - *_batch_summary.json（跳过）
    """
    if not os.path.isdir(report_dir):
        logger.warning("评估报告目录不存在: %s", report_dir)
        return []

    reports = []
    skipped = 0

    for fname in sorted(os.listdir(report_dir)):
        fpath = os.path.join(report_dir, fname)

        # 只处理 JSON 文件
        if not fname.endswith(".json"):
            continue

        # 跳过批量汇总和趋势数据文件
        if fname.startswith("_") or fname == "_batch_summary.json":
            skipped += 1
            continue

        try:
            report = _load_json(fpath)
            # 验证报告包含必要字段
            if _is_valid_eval_report(report):
                report["_file_path"] = fpath
                report["_file_name"] = fname
                reports.append(report)
            else:
                skipped += 1
                logger.debug("跳过无效报告: %s", fname)
        except (json.JSONDecodeError, Exception) as e:
            skipped += 1
            logger.debug("跳过无法解析的报告: %s — %s", fname, e)
            continue

    logger.info("扫描完成: %d 个有效报告, %d 个跳过", len(reports), skipped)
    return reports


def _is_valid_eval_report(report: Dict[str, Any]) -> bool:
    """验证评估报告是否包含必要字段。"""
    # 检查是否包含 summary 字段
    summary = report.get("summary")
    if not summary:
        return False

    # 检查是否包含 dimensions
    dimensions = summary.get("dimensions")
    if not dimensions:
        return False

    # 检查是否有 created_at 或 timestamp
    if not report.get("created_at") and not report.get("timestamp"):
        return False

    return True


def _extract_report_timestamp(report: Dict[str, Any]) -> Optional[datetime]:
    """从报告中提取时间戳。"""
    for key in ["created_at", "timestamp", "updated_at"]:
        ts = report.get(key)
        if ts:
            dt = _parse_timestamp(ts)
            if dt:
                return dt
    return None


def _extract_report_scores(report: Dict[str, Any]) -> Dict[str, float]:
    """从报告中提取各维度分数。"""
    summary = report.get("summary", {})
    dimensions = summary.get("dimensions", {})

    scores = {}
    for dim, data in dimensions.items():
        if isinstance(data, dict):
            # 回归报告格式: { "baseline": 0.72, "patched": 0.78, ... }
            # 取 patched 分数（如果有），否则取 baseline
            score = data.get("patched") or data.get("baseline") or data.get("score")
            if score is not None:
                scores[dim] = float(score)
        elif isinstance(data, (int, float)):
            # 简单格式: 0.72
            scores[dim] = float(data)

    return scores


def _extract_report_workflow_id(report: Dict[str, Any]) -> Optional[str]:
    """从报告中提取工作流 ID。"""
    for key in ["workflow_id", "workflow", "eval_set", "change_id"]:
        val = report.get(key)
        if val and isinstance(val, str):
            return val
    return None


# ── Trend Aggregation ──


def aggregate_trends(
    report_dir: str = DEFAULT_REPORT_DIR,
    output_path: Optional[str] = None,
    config: Optional[Dict[str, Any]] = None,
    window_days: Optional[int] = None,
    granularity: Optional[str] = None,
) -> Dict[str, Any]:
    """
    从 eval_reports/ 目录聚合趋势数据。

    Args:
        report_dir: 评估报告目录
        output_path: 输出文件路径（如果提供，写入文件）
        config: 仪表盘配置（可选，默认从文件加载）
        window_days: 趋势窗口天数（覆盖配置）
        granularity: 聚合粒度（覆盖配置）

    Returns:
        trend_data: {
            "generated_at": str,
            "window_days": int,
            "granularity": str,
            "report_count": int,
            "date_range": { "start": str, "end": str },
            "overall_trend": [ { "date": str, "average_score": float, ... } ],
            "dimension_trends": { "dimension_id": [ { "date": str, "score": float } ] },
            "workflow_trends": { "workflow_id": [ { "date": str, "score": float } ] },
            "summary": { ... },
        }
    """
    # 1. 加载配置
    if config is None:
        config = load_dashboard_config()

    dashboard_config = config.get("dashboard", {})
    aggregation_config = dashboard_config.get("aggregation", {})

    if window_days is None:
        window_days = aggregation_config.get("trend_window_days", 30)
    if granularity is None:
        granularity = aggregation_config.get("granularity", "daily")

    min_data_points = aggregation_config.get("min_data_points", 3)

    # 2. 扫描报告
    reports = scan_eval_reports(report_dir)
    if not reports:
        logger.warning("未找到有效的评估报告")
        empty_result = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "window_days": window_days,
            "granularity": granularity,
            "report_count": 0,
            "date_range": {"start": None, "end": None},
            "overall_trend": [],
            "dimension_trends": {},
            "workflow_trends": {},
            "summary": {
                "average_score": None,
                "score_tier": "no_data",
                "dimension_averages": {},
                "workflow_averages": {},
                "trend_direction": "stable",
            },
        }
        if output_path:
            _write_json(output_path, empty_result)
        return empty_result

    # 3. 按时间窗口过滤
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=window_days)

    filtered_reports = []
    for report in reports:
        ts = _extract_report_timestamp(report)
        if ts and ts >= cutoff:
            filtered_reports.append((ts, report))

    if not filtered_reports:
        logger.warning("在时间窗口内未找到报告")
        empty_result = {
            "generated_at": now.isoformat(),
            "window_days": window_days,
            "granularity": granularity,
            "report_count": 0,
            "date_range": {"start": None, "end": None},
            "overall_trend": [],
            "dimension_trends": {},
            "workflow_trends": {},
            "summary": {
                "average_score": None,
                "score_tier": "no_data",
                "dimension_averages": {},
                "workflow_averages": {},
                "trend_direction": "stable",
            },
        }
        if output_path:
            _write_json(output_path, empty_result)
        return empty_result

    # 4. 按时间排序
    filtered_reports.sort(key=lambda x: x[0])

    # 5. 按粒度分组
    time_key_fn = _get_date_key if granularity == "daily" else _get_hour_key
    time_groups: Dict[str, List[Tuple[datetime, Dict[str, Any]]]] = defaultdict(list)

    for ts, report in filtered_reports:
        key = time_key_fn(ts)
        time_groups[key].append((ts, report))

    # 6. 计算每个时间点的聚合分数
    overall_trend = []
    dimension_data: Dict[str, List[Tuple[str, float]]] = defaultdict(list)
    workflow_data: Dict[str, List[Tuple[str, float]]] = defaultdict(list)

    for time_key in sorted(time_groups.keys()):
        group_reports = time_groups[time_key]

        # 收集该时间点的所有分数
        all_scores = []
        dim_scores: Dict[str, List[float]] = defaultdict(list)
        wf_scores: Dict[str, List[float]] = defaultdict(list)

        for ts, report in group_reports:
            scores = _extract_report_scores(report)
            if scores:
                all_scores.append(scores)
                for dim, score in scores.items():
                    dim_scores[dim].append(score)

                wf_id = _extract_report_workflow_id(report)
                if wf_id:
                    wf_scores[wf_id].append(
                        sum(scores.values()) / len(scores) if scores else 0.0
                    )

        if not all_scores:
            continue

        # 计算综合平均分
        overall_avg = sum(
            sum(s.values()) / len(s) for s in all_scores
        ) / len(all_scores)

        trend_point = {
            "date": time_key,
            "average_score": round(overall_avg, 4),
            "report_count": len(group_reports),
        }
        overall_trend.append(trend_point)

        # 各维度趋势
        for dim, scores in dim_scores.items():
            dim_avg = sum(scores) / len(scores)
            dimension_data[dim].append((time_key, round(dim_avg, 4)))

        # 各工作流趋势
        for wf_id, scores in wf_scores.items():
            wf_avg = sum(scores) / len(scores)
            workflow_data[wf_id].append((time_key, round(wf_avg, 4)))

    # 7. 构建维度趋势
    dimension_trends = {}
    for dim, points in dimension_data.items():
        dimension_trends[dim] = [
            {"date": p[0], "score": p[1]} for p in points
        ]

    # 8. 构建工作流趋势
    workflow_trends = {}
    for wf_id, points in workflow_data.items():
        workflow_trends[wf_id] = [
            {"date": p[0], "score": p[1]} for p in points
        ]

    # 9. 计算汇总统计
    # 9a. 各维度平均分
    dimension_averages = {}
    for dim, points in dimension_data.items():
        scores = [p[1] for p in points]
        dimension_averages[dim] = round(sum(scores) / len(scores), 4) if scores else 0.0

    # 9b. 各工作流平均分
    workflow_averages = {}
    for wf_id, points in workflow_data.items():
        scores = [p[1] for p in points]
        workflow_averages[wf_id] = round(sum(scores) / len(scores), 4) if scores else 0.0

    # 9c. 总体平均分
    all_avg_scores = [p["average_score"] for p in overall_trend]
    overall_average = round(sum(all_avg_scores) / len(all_avg_scores), 4) if all_avg_scores else 0.0

    # 9d. 趋势方向
    trend_direction = _calculate_trend_direction(all_avg_scores)

    # 9e. 评分等级
    score_tier = _calculate_score_tier(overall_average, config)

    # 10. 构建结果
    date_range = {
        "start": filtered_reports[0][0].isoformat() if filtered_reports else None,
        "end": filtered_reports[-1][0].isoformat() if filtered_reports else None,
    }

    trend_data = {
        "generated_at": now.isoformat(),
        "window_days": window_days,
        "granularity": granularity,
        "report_count": len(filtered_reports),
        "date_range": date_range,
        "overall_trend": overall_trend,
        "dimension_trends": dimension_trends,
        "workflow_trends": workflow_trends,
        "summary": {
            "average_score": overall_average,
            "score_tier": score_tier,
            "dimension_averages": dimension_averages,
            "workflow_averages": workflow_averages,
            "trend_direction": trend_direction,
        },
    }

    # 11. 写入文件
    if output_path:
        _write_json(output_path, trend_data)

    return trend_data


def _calculate_trend_direction(scores: List[float]) -> str:
    """计算趋势方向。

    比较前半段和后半段的平均值来判断趋势。
    """
    if len(scores) < 4:
        return "stable"

    mid = len(scores) // 2
    first_half = scores[:mid]
    second_half = scores[mid:]

    first_avg = sum(first_half) / len(first_half)
    second_avg = sum(second_half) / len(second_half)

    diff = second_avg - first_avg

    if diff > 0.03:
        return "improving"
    elif diff < -0.03:
        return "declining"
    else:
        return "stable"


def _calculate_score_tier(score: float, config: Dict[str, Any]) -> str:
    """计算评分等级。"""
    if score is None:
        return "no_data"

    dashboard_config = config.get("dashboard", {})
    scoring_config = dashboard_config.get("scoring", {})
    tiers = scoring_config.get("tiers", {})

    for tier_name in ["excellent", "good", "fair", "poor", "critical"]:
        threshold = tiers.get(tier_name, 0.0)
        if score >= threshold:
            return tier_name

    return "critical"


# ── Alert Checking ──


def check_alerts(
    trend_data: Dict[str, Any],
    config: Optional[Dict[str, Any]] = None,
    output_path: Optional[str] = None,
    alerts_history_path: Optional[str] = None,
) -> Dict[str, Any]:
    """
    检查趋势数据是否触发告警条件。

    Args:
        trend_data: 趋势数据（由 aggregate_trends 生成）
        config: 仪表盘配置（可选，默认从文件加载）
        output_path: 告警输出文件路径
        alerts_history_path: 历史告警记录路径（用于去重）

    Returns:
        alert_result: {
            "checked_at": str,
            "alerts_triggered": int,
            "alerts": [ { "id": str, "severity": str, "action": str, ... } ],
            "auto_rollback_needed": bool,
            "rollback_changes": [str],
        }
    """
    # 1. 加载配置
    if config is None:
        config = load_dashboard_config()

    alerts_config = config.get("alerts", {})
    triggers = alerts_config.get("auto_rollback_triggers", [])
    notification_config = alerts_config.get("notification", {})
    dedup_window_str = notification_config.get("dedup_window", "1h")
    dedup_window = _parse_time_window(dedup_window_str)

    # 2. 加载历史告警（用于去重）
    history_alerts = []
    if alerts_history_path and os.path.exists(alerts_history_path):
        try:
            history_data = _load_json(alerts_history_path)
            history_alerts = history_data.get("alerts", [])
        except Exception:
            history_alerts = []

    # 3. 提取趋势数据
    overall_trend = trend_data.get("overall_trend", [])
    dimension_trends = trend_data.get("dimension_trends", {})
    summary = trend_data.get("summary", {})

    now = datetime.now(timezone.utc)

    # 4. 检查每个触发条件
    triggered_alerts = []

    for trigger in triggers:
        trigger_id = trigger.get("id", "")
        metric = trigger.get("metric", "")
        operator = trigger.get("operator", "")
        threshold = trigger.get("threshold", 0.0)
        window_str = trigger.get("window", "24h")
        window = _parse_time_window(window_str)
        min_points = trigger.get("min_data_points", 2)
        consecutive = trigger.get("consecutive", False)
        action = trigger.get("action", "notify_only")
        severity = trigger.get("severity", "info")
        description = trigger.get("description", "")

        # 4a. 检查去重
        if _is_alert_deduped(trigger_id, history_alerts, now, dedup_window):
            logger.debug("告警已去重: %s", trigger_id)
            continue

        # 4b. 检查条件
        alert = None

        if metric == "average_score":
            alert = _check_average_score_alert(
                overall_trend, operator, threshold, window,
                min_points, consecutive, trigger_id, action, severity, description
            )
        elif metric in dimension_trends:
            alert = _check_dimension_alert(
                dimension_trends.get(metric, []), metric, operator, threshold,
                window, min_points, consecutive, trigger_id, action, severity, description
            )
        else:
            logger.debug("未知指标: %s", metric)
            continue

        if alert:
            alert["checked_at"] = now.isoformat()
            triggered_alerts.append(alert)

    # 5. 判断是否需要自动回滚
    rollback_changes = []
    auto_rollback_needed = False
    for alert in triggered_alerts:
        if alert.get("action") == ACTION_ROLLBACK_CANARY:
            auto_rollback_needed = True
            change_id = alert.get("change_id")
            if change_id and change_id not in rollback_changes:
                rollback_changes.append(change_id)

    # 6. 构建结果
    result = {
        "checked_at": now.isoformat(),
        "alerts_triggered": len(triggered_alerts),
        "alerts": triggered_alerts,
        "auto_rollback_needed": auto_rollback_needed,
        "rollback_changes": rollback_changes,
    }

    # 7. 控制台输出
    if notification_config.get("console_output", True):
        _print_alerts(result)

    # 8. 写入告警记录
    if output_path:
        # 合并历史告警
        all_alerts = history_alerts + triggered_alerts
        alerts_data = {
            "generated_at": now.isoformat(),
            "total_alerts": len(all_alerts),
            "alerts": all_alerts,
        }
        _write_json(output_path, alerts_data)

    return result


def _is_alert_deduped(
    trigger_id: str,
    history_alerts: List[Dict[str, Any]],
    now: datetime,
    dedup_window: timedelta,
) -> bool:
    """检查告警是否在去重窗口内已触发过。"""
    for alert in history_alerts:
        if alert.get("id") == trigger_id:
            checked_at = alert.get("checked_at")
            if checked_at:
                ts = _parse_timestamp(checked_at)
                if ts and (now - ts) < dedup_window:
                    return True
    return False


def _check_average_score_alert(
    overall_trend: List[Dict[str, Any]],
    operator: str,
    threshold: float,
    window: timedelta,
    min_points: int,
    consecutive: bool,
    trigger_id: str,
    action: str,
    severity: str,
    description: str,
) -> Optional[Dict[str, Any]]:
    """检查综合评分告警条件。"""
    if len(overall_trend) < min_points:
        return None

    now = datetime.now(timezone.utc)
    window_start = now - window

    # 筛选窗口内的数据点
    window_points = []
    for point in overall_trend:
        point_date = point.get("date", "")
        ts = _parse_timestamp(point_date) if "T" in point_date else None
        if ts is None:
            # 尝试解析日期格式
            try:
                ts = datetime.strptime(point_date, "%Y-%m-%d")
                # 使 offset-naive datetime 变为 offset-aware
                ts = ts.replace(tzinfo=timezone.utc)
            except (ValueError, TypeError):
                continue

        if ts >= window_start:
            window_points.append(point)

    if len(window_points) < min_points:
        return None

    scores = [p.get("average_score", 0.0) for p in window_points]

    # 检查条件
    triggered = False
    details = {}

    if operator == "drop_by":
        # 检查分数是否下降超过阈值
        if len(scores) >= 2:
            first_score = scores[0]
            last_score = scores[-1]
            drop = first_score - last_score
            details = {
                "first_score": first_score,
                "last_score": last_score,
                "drop": round(drop, 4),
                "threshold": threshold,
            }
            if drop > threshold:
                triggered = True

    elif operator == "increase_by":
        # 检查分数是否上升超过阈值（用于 negative 指标）
        if len(scores) >= 2:
            first_score = scores[0]
            last_score = scores[-1]
            increase = last_score - first_score
            details = {
                "first_score": first_score,
                "last_score": last_score,
                "increase": round(increase, 4),
                "threshold": threshold,
            }
            if increase > threshold:
                triggered = True

    elif operator == "below":
        # 检查分数是否低于阈值
        if consecutive:
            # 连续低于阈值
            triggered = all(s < threshold for s in scores[-min_points:])
        else:
            # 任意低于阈值
            triggered = any(s < threshold for s in scores)

        details = {
            "scores": scores,
            "threshold": threshold,
            "consecutive": consecutive,
        }

    if not triggered:
        return None

    return {
        "id": trigger_id,
        "metric": "average_score",
        "operator": operator,
        "threshold": threshold,
        "severity": severity,
        "action": action,
        "description": description,
        "details": details,
        "window_points": len(window_points),
    }


def _check_dimension_alert(
    dimension_data: List[Dict[str, Any]],
    dimension_id: str,
    operator: str,
    threshold: float,
    window: timedelta,
    min_points: int,
    consecutive: bool,
    trigger_id: str,
    action: str,
    severity: str,
    description: str,
) -> Optional[Dict[str, Any]]:
    """检查维度告警条件。"""
    if len(dimension_data) < min_points:
        return None

    now = datetime.now(timezone.utc)
    window_start = now - window

    # 筛选窗口内的数据点
    window_points = []
    for point in dimension_data:
        point_date = point.get("date", "")
        ts = _parse_timestamp(point_date) if "T" in point_date else None
        if ts is None:
            try:
                ts = datetime.strptime(point_date, "%Y-%m-%d")
                # 使 offset-naive datetime 变为 offset-aware
                ts = ts.replace(tzinfo=timezone.utc)
            except (ValueError, TypeError):
                continue

        if ts >= window_start:
            window_points.append(point)

    if len(window_points) < min_points:
        return None

    scores = [p.get("score", 0.0) for p in window_points]

    # 检查条件
    triggered = False
    details = {}

    if operator == "drop_by":
        if len(scores) >= 2:
            first_score = scores[0]
            last_score = scores[-1]
            drop = first_score - last_score
            details = {
                "first_score": first_score,
                "last_score": last_score,
                "drop": round(drop, 4),
                "threshold": threshold,
            }
            if drop > threshold:
                triggered = True

    elif operator == "increase_by":
        if len(scores) >= 2:
            first_score = scores[0]
            last_score = scores[-1]
            increase = last_score - first_score
            details = {
                "first_score": first_score,
                "last_score": last_score,
                "increase": round(increase, 4),
                "threshold": threshold,
            }
            if increase > threshold:
                triggered = True

    elif operator == "below":
        if consecutive:
            triggered = all(s < threshold for s in scores[-min_points:])
        else:
            triggered = any(s < threshold for s in scores)
        details = {
            "scores": scores,
            "threshold": threshold,
            "consecutive": consecutive,
        }

    if not triggered:
        return None

    return {
        "id": trigger_id,
        "metric": dimension_id,
        "operator": operator,
        "threshold": threshold,
        "severity": severity,
        "action": action,
        "description": description,
        "details": details,
        "window_points": len(window_points),
    }


# ── Auto Rollback ──


def auto_rollback(
    trend_data: Dict[str, Any],
    rollout_dir: str = DEFAULT_ROLLOUT_DIR,
    change_dir: str = DEFAULT_CHANGE_DIR,
    config: Optional[Dict[str, Any]] = None,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """
    自动回滚检查 — 检查告警条件并自动执行回滚。

    Args:
        trend_data: 趋势数据
        rollout_dir: 灰度发布记录目录
        change_dir: 候选变更目录
        config: 仪表盘配置
        dry_run: 是否仅模拟（不实际执行回滚）

    Returns:
        rollback_result: {
            "checked_at": str,
            "dry_run": bool,
            "alerts_checked": bool,
            "rollbacks_executed": int,
            "rollbacks": [ { "change_id": str, "reason": str, "success": bool } ],
        }
    """
    # 1. 检查告警
    alert_result = check_alerts(trend_data, config)

    if not alert_result["auto_rollback_needed"]:
        logger.info("未触发自动回滚条件")
        return {
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "dry_run": dry_run,
            "alerts_checked": True,
            "rollbacks_executed": 0,
            "rollbacks": [],
        }

    # 2. 查找需要回滚的变更
    # 如果 check_alerts 没有返回具体的 change_id，则扫描 rollout 目录
    rollback_changes = alert_result.get("rollback_changes", [])
    if not rollback_changes:
        # 扫描 rollout 目录中处于 canary 状态的变更
        if os.path.isdir(rollout_dir):
            for fname in sorted(os.listdir(rollout_dir)):
                if fname.endswith("_rollout.json"):
                    try:
                        record = _load_json(os.path.join(rollout_dir, fname))
                        if record.get("status") == "canary":
                            cid = record.get("change_id")
                            if cid and cid not in rollback_changes:
                                rollback_changes.append(cid)
                    except Exception:
                        continue

    rollbacks = []

    for change_id in rollback_changes:
        # 查找灰度发布记录
        rollout_record_path = os.path.join(rollout_dir, f"{change_id}_rollout.json")
        if not os.path.exists(rollout_record_path):
            logger.warning("未找到灰度发布记录: %s", change_id)
            rollbacks.append({
                "change_id": change_id,
                "reason": "自动回滚: 触发告警条件",
                "success": False,
                "error": "未找到灰度发布记录",
            })
            continue

        # 查找触发该回滚的告警
        reasons = []
        for alert in alert_result["alerts"]:
            if alert.get("action") == ACTION_ROLLBACK_CANARY:
                reasons.append(f"{alert.get('description', '')} ({alert.get('id', '')})")

        reason = "; ".join(reasons) if reasons else "自动回滚: 触发告警条件"

        if dry_run:
            logger.info("[DRY RUN] 将回滚: %s — %s", change_id, reason)
            rollbacks.append({
                "change_id": change_id,
                "reason": reason,
                "success": True,
                "dry_run": True,
            })
        else:
            try:
                # 导入 rollout_manager 并执行回滚
                from scripts.rollout_manager import rollback_rollout
                rollback_rollout(
                    change_id=change_id,
                    reason=reason,
                    change_dir=change_dir,
                    output_dir=rollout_dir,
                )
                logger.info("自动回滚成功: %s", change_id)
                rollbacks.append({
                    "change_id": change_id,
                    "reason": reason,
                    "success": True,
                })
            except Exception as e:
                logger.error("自动回滚失败: %s — %s", change_id, e)
                rollbacks.append({
                    "change_id": change_id,
                    "reason": reason,
                    "success": False,
                    "error": str(e),
                })

    # 3. 构建结果
    result = {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "dry_run": dry_run,
        "alerts_checked": True,
        "rollbacks_executed": len([r for r in rollbacks if r.get("success")]),
        "rollbacks": rollbacks,
    }

    # 4. 打印摘要
    _print_auto_rollback_summary(result)

    return result


# ── HTML Dashboard Generation (Stub) ──


def generate_html_dashboard(
    trend_data: Dict[str, Any],
    output_path: str = "outputs/dashboard/index.html",
    config: Optional[Dict[str, Any]] = None,
) -> str:
    """
    生成 HTML 仪表盘（Phase 7 第一版为 stub，后续版本实现）。

    Args:
        trend_data: 趋势数据
        output_path: HTML 输出路径
        config: 仪表盘配置

    Returns:
        html_path: 生成的 HTML 文件路径
    """
    logger.info("HTML 仪表盘生成功能将在后续版本实现")
    logger.info("当前版本仅输出 JSON 数据: %s", trend_data.get("generated_at", ""))

    # 生成简单的 HTML 占位
    summary = trend_data.get("summary", {})
    overall_trend = trend_data.get("overall_trend", [])

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>质量仪表盘 — Phase 7f</title>
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; margin: 0; padding: 20px; background: #f5f5f5; color: #333; }}
        .container {{ max-width: 1200px; margin: 0 auto; }}
        .header {{ background: #fff; padding: 20px; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); margin-bottom: 20px; }}
        .header h1 {{ margin: 0; font-size: 24px; }}
        .header .meta {{ color: #666; font-size: 14px; margin-top: 8px; }}
        .summary-cards {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 16px; margin-bottom: 20px; }}
        .card {{ background: #fff; padding: 16px; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }}
        .card .value {{ font-size: 32px; font-weight: bold; }}
        .card .label {{ font-size: 14px; color: #666; margin-top: 4px; }}
        .card .tier {{ display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 12px; font-weight: bold; }}
        .tier-excellent {{ background: #d4edda; color: #155724; }}
        .tier-good {{ background: #cce5ff; color: #004085; }}
        .tier-fair {{ background: #fff3cd; color: #856404; }}
        .tier-poor {{ background: #f8d7da; color: #721c24; }}
        .tier-critical {{ background: #f8d7da; color: #721c24; }}
        .tier-no_data {{ background: #e2e3e5; color: #383d41; }}
        .section {{ background: #fff; padding: 20px; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); margin-bottom: 20px; }}
        .section h2 {{ margin: 0 0 16px 0; font-size: 18px; }}
        table {{ width: 100%; border-collapse: collapse; }}
        th, td {{ padding: 8px 12px; text-align: left; border-bottom: 1px solid #eee; }}
        th {{ font-weight: 600; color: #666; font-size: 13px; }}
        .trend-up {{ color: #28a745; }}
        .trend-down {{ color: #dc3545; }}
        .trend-stable {{ color: #6c757d; }}
        .footer {{ text-align: center; color: #999; font-size: 12px; padding: 20px; }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>📊 质量仪表盘</h1>
            <div class="meta">
                生成时间: {trend_data.get('generated_at', 'N/A')} |
                报告数: {trend_data.get('report_count', 0)} |
                窗口: {trend_data.get('window_days', '?')} 天
            </div>
        </div>

        <div class="summary-cards">
            <div class="card">
                <div class="value">{summary.get('average_score', 'N/A')}</div>
                <div class="label">综合评分</div>
                <div class="tier tier-{summary.get('score_tier', 'no_data')}">{summary.get('score_tier', 'no_data')}</div>
            </div>
            <div class="card">
                <div class="value">{summary.get('trend_direction', 'stable')}</div>
                <div class="label">趋势方向</div>
            </div>
            <div class="card">
                <div class="value">{trend_data.get('report_count', 0)}</div>
                <div class="label">评估报告数</div>
            </div>
        </div>

        <div class="section">
            <h2>各维度平均分</h2>
            <table>
                <tr><th>维度</th><th>平均分</th></tr>
                {''.join(f'<tr><td>{dim}</td><td>{score}</td></tr>' for dim, score in summary.get('dimension_averages', {}).items())}
            </table>
        </div>

        <div class="section">
            <h2>各工作流平均分</h2>
            <table>
                <tr><th>工作流</th><th>平均分</th></tr>
                {''.join(f'<tr><td>{wf}</td><td>{score}</td></tr>' for wf, score in summary.get('workflow_averages', {}).items())}
            </table>
        </div>

        <div class="section">
            <h2>趋势数据（最近 {min(len(overall_trend), 10)} 个时间点）</h2>
            <table>
                <tr><th>日期</th><th>综合评分</th><th>报告数</th></tr>
                {''.join(f'<tr><td>{p.get("date", "")}</td><td>{p.get("average_score", "")}</td><td>{p.get("report_count", "")}</td></tr>' for p in overall_trend[-10:])}
            </table>
        </div>

        <div class="footer">
            Phase 7f — 质量仪表盘 | 自动生成
        </div>
    </div>
</body>
</html>"""

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)

    logger.info("HTML 仪表盘已生成: %s", output_path)
    return output_path


# ── Stats ──


def get_dashboard_stats(
    trend_data: Dict[str, Any],
    config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    获取仪表盘统计信息。

    Args:
        trend_data: 趋势数据
        config: 仪表盘配置

    Returns:
        stats: 统计信息
    """
    summary = trend_data.get("summary", {})
    overall_trend = trend_data.get("overall_trend", [])
    dimension_trends = trend_data.get("dimension_trends", {})
    workflow_trends = trend_data.get("workflow_trends", {})

    # 计算各维度的趋势方向
    dimension_directions = {}
    for dim, points in dimension_trends.items():
        scores = [p.get("score", 0.0) for p in points]
        dimension_directions[dim] = _calculate_trend_direction(scores)

    # 计算各工作流的趋势方向
    workflow_directions = {}
    for wf_id, points in workflow_trends.items():
        scores = [p.get("score", 0.0) for p in points]
        workflow_directions[wf_id] = _calculate_trend_direction(scores)

    # 评分分布
    score_distribution = {"excellent": 0, "good": 0, "fair": 0, "poor": 0, "critical": 0}
    for point in overall_trend:
        score = point.get("average_score", 0.0)
        tier = _calculate_score_tier(score, config or {})
        if tier in score_distribution:
            score_distribution[tier] += 1

    return {
        "generated_at": trend_data.get("generated_at", ""),
        "report_count": trend_data.get("report_count", 0),
        "date_range": trend_data.get("date_range", {}),
        "summary": summary,
        "dimension_directions": dimension_directions,
        "workflow_directions": workflow_directions,
        "score_distribution": score_distribution,
        "trend_points_count": len(overall_trend),
        "dimension_count": len(dimension_trends),
        "workflow_count": len(workflow_trends),
    }


# ── Print Helpers ──


def _print_alerts(alert_result: Dict[str, Any]) -> None:
    """打印告警结果。"""
    alerts = alert_result.get("alerts", [])
    triggered = alert_result.get("alerts_triggered", 0)

    print(f"\n{'=' * 60}")
    print(f"  📊 告警检查结果")
    print(f"  检查时间: {alert_result.get('checked_at', '?')}")
    print(f"  触发告警: {triggered}")
    print(f"{'=' * 60}")

    if not alerts:
        print(f"  ✅ 未触发告警条件\n")
        return

    for alert in alerts:
        severity = alert.get("severity", "info")
        severity_icon = {
            "critical": "🔴",
            "warning": "🟡",
            "info": "🔵",
        }.get(severity, "⚪")

        action = alert.get("action", "notify_only")
        action_label = "自动回滚" if action == "rollback_canary" else "仅通知"

        print(f"\n  {severity_icon} [{severity.upper()}] {alert.get('description', '?')}")
        print(f"     指标: {alert.get('metric', '?')}")
        print(f"     操作: {action_label}")
        print(f"     详情: {json.dumps(alert.get('details', {}), ensure_ascii=False)}")

    print(f"\n  自动回滚: {'是' if alert_result.get('auto_rollback_needed') else '否'}")
    if alert_result.get("rollback_changes"):
        print(f"  回滚变更: {', '.join(alert_result['rollback_changes'])}")
    print(f"{'=' * 60}\n")


def _print_auto_rollback_summary(result: Dict[str, Any]) -> None:
    """打印自动回滚摘要。"""
    rollbacks = result.get("rollbacks", [])
    executed = result.get("rollbacks_executed", 0)

    print(f"\n{'=' * 60}")
    print(f"  🔄 自动回滚结果")
    print(f"  检查时间: {result.get('checked_at', '?')}")
    print(f"  模拟模式: {'是' if result.get('dry_run') else '否'}")
    print(f"  执行回滚: {executed}/{len(rollbacks)}")
    print(f"{'=' * 60}")

    for rb in rollbacks:
        success = rb.get("success", False)
        icon = "✅" if success else "❌"
        print(f"\n  {icon} {rb.get('change_id', '?')}")
        print(f"     原因: {rb.get('reason', '?')}")
        if not success and rb.get("error"):
            print(f"     错误: {rb['error']}")

    print(f"{'=' * 60}\n")


def _print_stats(stats: Dict[str, Any]) -> None:
    """打印仪表盘统计信息。"""
    summary = stats.get("summary", {})

    print(f"\n{'=' * 60}")
    print(f"  📊 仪表盘统计")
    print(f"  生成时间: {stats.get('generated_at', '?')}")
    print(f"{'=' * 60}")

    print(f"\n  综合评分: {summary.get('average_score', 'N/A')}")
    print(f"  评分等级: {summary.get('score_tier', 'N/A')}")
    print(f"  趋势方向: {summary.get('trend_direction', 'stable')}")
    print(f"  报告总数: {stats.get('report_count', 0)}")
    print(f"  趋势点数: {stats.get('trend_points_count', 0)}")
    print(f"  维度数: {stats.get('dimension_count', 0)}")
    print(f"  工作流数: {stats.get('workflow_count', 0)}")

    print(f"\n  各维度趋势:")
    for dim, direction in stats.get("dimension_directions", {}).items():
        icon = {"improving": "📈", "declining": "📉", "stable": "➡️"}.get(direction, "➡️")
        print(f"    {icon} {dim}: {direction}")

    print(f"\n  评分分布:")
    for tier, count in stats.get("score_distribution", {}).items():
        if count > 0:
            print(f"    {tier}: {count}")

    print(f"\n  日期范围: {stats.get('date_range', {}).get('start', '?')} ~ {stats.get('date_range', {}).get('end', '?')}")
    print(f"{'=' * 60}\n")


# ── CLI ──


def main():
    parser = argparse.ArgumentParser(
        description="Phase 7f: 质量仪表盘数据聚合 + 自动回滚",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 聚合趋势数据
  python scripts/dashboard.py aggregate \\
      --report-dir outputs/eval_reports/ \\
      --output outputs/dashboard/_trend_data.json

  # 检查告警
  python scripts/dashboard.py check-alerts \\
      --trend outputs/dashboard/_trend_data.json

  # 自动回滚检查（检查 + 自动执行回滚）
  python scripts/dashboard.py auto-rollback \\
      --trend outputs/dashboard/_trend_data.json \\
      --rollout-dir outputs/rollout/

  # 生成 HTML 仪表盘
  python scripts/dashboard.py generate-html \\
      --trend outputs/dashboard/_trend_data.json \\
      --output outputs/dashboard/index.html

  # 查看仪表盘统计
  python scripts/dashboard.py stats \\
      --trend outputs/dashboard/_trend_data.json
        """,
    )

    subparsers = parser.add_subparsers(dest="command", help="可用命令")

    # ── aggregate ──
    agg_parser = subparsers.add_parser("aggregate", help="聚合趋势数据")
    agg_parser.add_argument(
        "--report-dir", type=str, default=DEFAULT_REPORT_DIR,
        help=f"评估报告目录 (默认: {DEFAULT_REPORT_DIR})"
    )
    agg_parser.add_argument(
        "--output", type=str, default=None,
        help="趋势数据输出路径 (默认: outputs/dashboard/_trend_data.json)"
    )
    agg_parser.add_argument(
        "--config", type=str, default=DEFAULT_DASHBOARD_CONFIG,
        help=f"仪表盘配置文件 (默认: {DEFAULT_DASHBOARD_CONFIG})"
    )
    agg_parser.add_argument(
        "--window-days", type=int, default=None,
        help="趋势窗口天数 (覆盖配置)"
    )
    agg_parser.add_argument(
        "--granularity", choices=["daily", "hourly"], default=None,
        help="聚合粒度 (覆盖配置)"
    )

    # ── check-alerts ──
    alert_parser = subparsers.add_parser("check-alerts", help="检查告警条件")
    alert_parser.add_argument(
        "--trend", type=str, required=True,
        help="趋势数据 JSON 文件路径"
    )
    alert_parser.add_argument(
        "--config", type=str, default=DEFAULT_DASHBOARD_CONFIG,
        help=f"仪表盘配置文件 (默认: {DEFAULT_DASHBOARD_CONFIG})"
    )
    alert_parser.add_argument(
        "--output", type=str, default=None,
        help="告警输出路径 (默认: outputs/dashboard/_alerts.json)"
    )
    alert_parser.add_argument(
        "--alerts-history", type=str, default=None,
        help="历史告警记录路径（用于去重）"
    )

    # ── auto-rollback ──
    rollback_parser = subparsers.add_parser("auto-rollback", help="自动回滚检查并执行")
    rollback_parser.add_argument(
        "--trend", type=str, required=True,
        help="趋势数据 JSON 文件路径"
    )
    rollback_parser.add_argument(
        "--rollout-dir", type=str, default=DEFAULT_ROLLOUT_DIR,
        help=f"灰度发布记录目录 (默认: {DEFAULT_ROLLOUT_DIR})"
    )
    rollback_parser.add_argument(
        "--change-dir", type=str, default=DEFAULT_CHANGE_DIR,
        help=f"候选变更目录 (默认: {DEFAULT_CHANGE_DIR})"
    )
    rollback_parser.add_argument(
        "--config", type=str, default=DEFAULT_DASHBOARD_CONFIG,
        help=f"仪表盘配置文件 (默认: {DEFAULT_DASHBOARD_CONFIG})"
    )
    rollback_parser.add_argument(
        "--dry-run", action="store_true",
        help="仅模拟，不实际执行回滚"
    )

    # ── generate-html ──
    html_parser = subparsers.add_parser("generate-html", help="生成 HTML 仪表盘")
    html_parser.add_argument(
        "--trend", type=str, required=True,
        help="趋势数据 JSON 文件路径"
    )
    html_parser.add_argument(
        "--output", type=str, default="outputs/dashboard/index.html",
        help="HTML 输出路径 (默认: outputs/dashboard/index.html)"
    )
    html_parser.add_argument(
        "--config", type=str, default=DEFAULT_DASHBOARD_CONFIG,
        help=f"仪表盘配置文件 (默认: {DEFAULT_DASHBOARD_CONFIG})"
    )

    # ── stats ──
    stats_parser = subparsers.add_parser("stats", help="查看仪表盘统计")
    stats_parser.add_argument(
        "--trend", type=str, required=True,
        help="趋势数据 JSON 文件路径"
    )
    stats_parser.add_argument(
        "--config", type=str, default=DEFAULT_DASHBOARD_CONFIG,
        help=f"仪表盘配置文件 (默认: {DEFAULT_DASHBOARD_CONFIG})"
    )

    args = parser.parse_args()

    # ── 执行命令 ──
    if args.command == "aggregate":
        config = load_dashboard_config(args.config)
        output_path = args.output or os.path.join(
            config.get("dashboard", {}).get("aggregation", {}).get("output_path", DEFAULT_OUTPUT_DIR),
            "_trend_data.json"
        )
        trend_data = aggregate_trends(
            report_dir=args.report_dir,
            output_path=output_path,
            config=config,
            window_days=args.window_days,
            granularity=args.granularity,
        )
        print(f"\n✅ 趋势数据已聚合: {output_path}")
        print(f"   报告数: {trend_data['report_count']}")
        print(f"   综合评分: {trend_data['summary']['average_score']}")
        print(f"   趋势方向: {trend_data['summary']['trend_direction']}\n")

    elif args.command == "check-alerts":
        config = load_dashboard_config(args.config)
        trend_data = _load_json(args.trend)
        output_path = args.output or config.get("alerts", {}).get("notification", {}).get(
            "alerts_output_path", "outputs/dashboard/_alerts.json"
        )
        alerts_history_path = args.alerts_history or output_path
        result = check_alerts(
            trend_data=trend_data,
            config=config,
            output_path=output_path,
            alerts_history_path=alerts_history_path,
        )

    elif args.command == "auto-rollback":
        config = load_dashboard_config(args.config)
        trend_data = _load_json(args.trend)
        result = auto_rollback(
            trend_data=trend_data,
            rollout_dir=args.rollout_dir,
            change_dir=args.change_dir,
            config=config,
            dry_run=args.dry_run,
        )

    elif args.command == "generate-html":
        config = load_dashboard_config(args.config)
        trend_data = _load_json(args.trend)
        html_path = generate_html_dashboard(
            trend_data=trend_data,
            output_path=args.output,
            config=config,
        )
        print(f"\n✅ HTML 仪表盘已生成: {html_path}\n")

    elif args.command == "stats":
        config = load_dashboard_config(args.config)
        trend_data = _load_json(args.trend)
        stats = get_dashboard_stats(trend_data, config)
        _print_stats(stats)

    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
