#!/usr/bin/env python3
"""
test_dashboard.py — Phase 7f: 质量仪表盘单元测试

测试覆盖:
  1. 仪表盘配置加载
  2. 报告扫描与验证
  3. 趋势数据聚合
  4. 告警条件检查
  5. 自动回滚触发
  6. HTML 仪表盘生成
  7. 仪表盘统计
  8. 端到端工作流

运行:
  python -m pytest tests/phase7f/test_dashboard.py -v
  python -m pytest tests/phase7f/test_dashboard.py -v --tb=short
"""

import json
import os
import sys
import tempfile
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch, MagicMock

# 确保可以从项目根目录导入
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

import pytest

from scripts.dashboard import (
    # 常量
    DEFAULT_METRICS,
    SEVERITY_CRITICAL,
    SEVERITY_WARNING,
    SEVERITY_INFO,
    ACTION_ROLLBACK_CANARY,
    ACTION_NOTIFY_ONLY,
    # 配置加载
    load_dashboard_config,
    _get_default_config,
    # 时间解析
    _parse_time_window,
    _parse_timestamp,
    _get_date_key,
    _get_hour_key,
    # 报告扫描
    scan_eval_reports,
    _is_valid_eval_report,
    _extract_report_timestamp,
    _extract_report_scores,
    _extract_report_workflow_id,
    # 趋势聚合
    aggregate_trends,
    _calculate_trend_direction,
    _calculate_score_tier,
    # 告警检查
    check_alerts,
    _is_alert_deduped,
    _check_average_score_alert,
    _check_dimension_alert,
    # 自动回滚
    auto_rollback,
    # HTML 生成
    generate_html_dashboard,
    # 统计
    get_dashboard_stats,
    # 文件 I/O
    _load_json,
    _write_json,
    _load_yaml,
)


# ═══════════════════════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.fixture
def temp_dir():
    """创建临时目录用于测试文件操作。"""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield tmpdir


@pytest.fixture
def sample_eval_report():
    """创建一个样本评估报告。"""
    return {
        "eval_id": f"eval_{uuid.uuid4().hex[:8]}",
        "workflow_id": "contract_review",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "summary": {
            "overall_score": 0.82,
            "dimensions": {
                "citation_accuracy": 0.78,
                "constraint_compliance": 0.85,
                "format_compliance": 0.80,
                "risk_detection": 0.72,
                "human_modification_rate": 0.12,
                "output_adoption_rate": 0.75,
                "high_risk_miss_rate": 0.05,
                "cost_latency": 0.90,
            },
        },
    }


@pytest.fixture
def sample_regression_report():
    """创建一个样本回归报告（与 phase7d 格式一致）。"""
    return {
        "change_id": f"change_{uuid.uuid4().hex[:8]}",
        "status": "sandbox_pass",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "summary": {
            "overall_score_change": 0.03,
            "dimensions": {
                "citation_accuracy": {
                    "baseline": 0.72,
                    "patched": 0.78,
                    "delta": 0.06,
                    "passed": True,
                },
                "constraint_compliance": {
                    "baseline": 0.85,
                    "patched": 0.85,
                    "delta": 0.0,
                    "passed": True,
                },
                "risk_detection": {
                    "baseline": 0.68,
                    "patched": 0.67,
                    "delta": -0.01,
                    "passed": True,
                },
                "format_compliance": {
                    "baseline": 0.80,
                    "patched": 0.80,
                    "delta": 0.0,
                    "passed": True,
                },
                "human_modification_rate": {
                    "baseline": 0.10,
                    "patched": 0.12,
                    "delta": 0.02,
                    "passed": True,
                },
                "output_adoption_rate": {
                    "baseline": 0.75,
                    "patched": 0.78,
                    "delta": 0.03,
                    "passed": True,
                },
                "high_risk_miss_rate": {
                    "baseline": 0.05,
                    "patched": 0.04,
                    "delta": -0.01,
                    "passed": True,
                },
                "cost_latency": {
                    "baseline": 0.90,
                    "patched": 0.88,
                    "delta": -0.02,
                    "passed": True,
                },
            },
            "regressions": [],
            "improvements": ["citation_accuracy +0.06"],
        },
    }


@pytest.fixture
def sample_trend_data():
    """创建一个样本趋势数据。"""
    now = datetime.now(timezone.utc)
    return {
        "generated_at": now.isoformat(),
        "window_days": 7,
        "granularity": "daily",
        "report_count": 10,
        "date_range": {
            "start": (now - timedelta(days=6)).isoformat(),
            "end": now.isoformat(),
        },
        "overall_trend": [
            {"date": (now - timedelta(days=i)).strftime("%Y-%m-%d"),
             "average_score": round(0.80 + i * 0.01, 4),
             "report_count": 2}
            for i in range(6, -1, -1)
        ],
        "dimension_trends": {
            "citation_accuracy": [
                {"date": (now - timedelta(days=i)).strftime("%Y-%m-%d"),
                 "score": round(0.75 + i * 0.01, 4)}
                for i in range(6, -1, -1)
            ],
            "risk_detection": [
                {"date": (now - timedelta(days=i)).strftime("%Y-%m-%d"),
                 "score": round(0.70 + i * 0.01, 4)}
                for i in range(6, -1, -1)
            ],
        },
        "workflow_trends": {
            "contract_review": [
                {"date": (now - timedelta(days=i)).strftime("%Y-%m-%d"),
                 "score": round(0.82 + i * 0.005, 4)}
                for i in range(6, -1, -1)
            ],
        },
        "summary": {
            "average_score": 0.83,
            "score_tier": "good",
            "dimension_averages": {
                "citation_accuracy": 0.78,
                "risk_detection": 0.73,
            },
            "workflow_averages": {
                "contract_review": 0.84,
            },
            "trend_direction": "improving",
        },
    }


@pytest.fixture
def setup_report_dir(temp_dir, sample_eval_report, sample_regression_report):
    """设置评估报告测试目录。"""
    report_dir = os.path.join(temp_dir, "eval_reports")
    os.makedirs(report_dir, exist_ok=True)

    # 写入多个评估报告
    for i in range(5):
        report = sample_eval_report.copy()
        report["eval_id"] = f"eval_{uuid.uuid4().hex[:8]}"
        report["workflow_id"] = ["contract_review", "due_diligence", "sop_generation"][i % 3]
        report["created_at"] = (datetime.now(timezone.utc) - timedelta(days=i)).isoformat()
        report["summary"]["overall_score"] = round(0.75 + i * 0.03, 2)
        for dim in report["summary"]["dimensions"]:
            report["summary"]["dimensions"][dim] = round(0.70 + i * 0.02, 2)

        fpath = os.path.join(report_dir, f"{report['eval_id']}_eval.json")
        _write_json(fpath, report)

    # 写入一个回归报告
    reg_report = sample_regression_report.copy()
    reg_report["change_id"] = f"change_{uuid.uuid4().hex[:8]}"
    reg_report["created_at"] = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    fpath = os.path.join(report_dir, f"{reg_report['change_id']}_regression_report.json")
    _write_json(fpath, reg_report)

    # 写入一个无效报告（缺少必要字段）
    invalid_report = {"invalid": True}
    _write_json(os.path.join(report_dir, "invalid_report.json"), invalid_report)

    # 写入一个批量汇总文件（应被跳过）
    batch_summary = {"batch": True}
    _write_json(os.path.join(report_dir, "_batch_summary.json"), batch_summary)

    return report_dir


# ═══════════════════════════════════════════════════════════════════════════════
# 1. 仪表盘配置加载
# ═══════════════════════════════════════════════════════════════════════════════


class TestDashboardConfigLoading:
    """测试仪表盘配置加载功能。"""

    def test_load_default_config(self):
        """测试加载默认配置文件。"""
        config = load_dashboard_config()
        assert config is not None
        assert "dashboard" in config
        assert "alerts" in config
        assert "workflow_groups" in config

    def test_dashboard_config_values(self):
        """测试仪表盘配置值。"""
        config = load_dashboard_config()
        dashboard = config["dashboard"]
        assert dashboard["aggregation"]["trend_window_days"] == 30
        assert dashboard["aggregation"]["min_data_points"] == 3
        assert dashboard["aggregation"]["granularity"] == "daily"

    def test_metrics_config(self):
        """测试评估维度配置。"""
        config = load_dashboard_config()
        metrics = config["dashboard"]["metrics"]
        metric_ids = [m["id"] for m in metrics]
        for m in DEFAULT_METRICS:
            assert m in metric_ids

    def test_scoring_tiers(self):
        """测试评分等级配置。"""
        config = load_dashboard_config()
        tiers = config["dashboard"]["scoring"]["tiers"]
        assert tiers["excellent"] == 0.90
        assert tiers["good"] == 0.80
        assert tiers["fair"] == 0.70
        assert tiers["poor"] == 0.50

    def test_alert_triggers(self):
        """测试告警触发条件配置。"""
        config = load_dashboard_config()
        triggers = config["alerts"]["auto_rollback_triggers"]
        trigger_ids = [t["id"] for t in triggers]
        assert "score_drop" in trigger_ids
        assert "high_risk_miss_rate_increase" in trigger_ids
        assert "risk_detection_drop" in trigger_ids

    def test_workflow_groups(self):
        """测试工作流分组配置。"""
        config = load_dashboard_config()
        groups = config["workflow_groups"]
        group_ids = [g["id"] for g in groups]
        assert "legal" in group_ids
        assert "business" in group_ids
        assert "energy" in group_ids
        assert "finance" in group_ids
        assert "operations" in group_ids

    def test_get_default_config(self):
        """测试获取默认配置。"""
        config = _get_default_config()
        assert config["dashboard"]["aggregation"]["trend_window_days"] == 30
        assert len(config["dashboard"]["metrics"]) == len(DEFAULT_METRICS)

    def test_config_file_not_found(self):
        """测试配置文件不存在时的行为。"""
        with pytest.raises(FileNotFoundError):
            load_dashboard_config("nonexistent_config.yaml")


# ═══════════════════════════════════════════════════════════════════════════════
# 2. 时间解析
# ═══════════════════════════════════════════════════════════════════════════════


class TestTimeParsing:
    """测试时间解析功能。"""

    def test_parse_time_window_hours(self):
        """测试解析小时。"""
        delta = _parse_time_window("24h")
        assert delta == timedelta(hours=24)

    def test_parse_time_window_days(self):
        """测试解析天数。"""
        delta = _parse_time_window("7d")
        assert delta == timedelta(days=7)

    def test_parse_time_window_weeks(self):
        """测试解析周数。"""
        delta = _parse_time_window("2w")
        assert delta == timedelta(weeks=2)

    def test_parse_time_window_invalid(self):
        """测试解析无效格式。"""
        delta = _parse_time_window("invalid")
        assert delta == timedelta(hours=24)

    def test_parse_timestamp_iso(self):
        """测试解析 ISO 时间戳。"""
        ts = "2026-05-06T10:00:00+00:00"
        dt = _parse_timestamp(ts)
        assert dt is not None
        assert dt.year == 2026
        assert dt.month == 5
        assert dt.day == 6

    def test_parse_timestamp_invalid(self):
        """测试解析无效时间戳。"""
        dt = _parse_timestamp("not-a-timestamp")
        assert dt is None

    def test_get_date_key(self):
        """测试获取日期键。"""
        dt = datetime(2026, 5, 6, 10, 30, 0)
        assert _get_date_key(dt) == "2026-05-06"

    def test_get_hour_key(self):
        """测试获取小时键。"""
        dt = datetime(2026, 5, 6, 10, 30, 0)
        assert _get_hour_key(dt) == "2026-05-06T10:00:00"


# ═══════════════════════════════════════════════════════════════════════════════
# 3. 报告扫描与验证
# ═══════════════════════════════════════════════════════════════════════════════


class TestReportScanning:
    """测试报告扫描与验证功能。"""

    def test_scan_eval_reports(self, setup_report_dir):
        """测试扫描评估报告目录。"""
        reports = scan_eval_reports(setup_report_dir)
        # 5 个评估报告 + 1 个回归报告 = 6 个有效报告
        assert len(reports) == 6

    def test_scan_empty_directory(self, temp_dir):
        """测试扫描空目录。"""
        reports = scan_eval_reports(temp_dir)
        assert reports == []

    def test_scan_nonexistent_directory(self):
        """测试扫描不存在的目录。"""
        reports = scan_eval_reports("/nonexistent/path")
        assert reports == []

    def test_is_valid_eval_report(self, sample_eval_report):
        """测试验证有效评估报告。"""
        assert _is_valid_eval_report(sample_eval_report) is True

    def test_is_valid_regression_report(self, sample_regression_report):
        """测试验证有效回归报告。"""
        assert _is_valid_eval_report(sample_regression_report) is True

    def test_is_valid_report_missing_summary(self):
        """测试缺少 summary 的报告。"""
        report = {"created_at": "2026-05-06T00:00:00Z"}
        assert _is_valid_eval_report(report) is False

    def test_is_valid_report_missing_dimensions(self):
        """测试缺少 dimensions 的报告。"""
        report = {"created_at": "2026-05-06T00:00:00Z", "summary": {}}
        assert _is_valid_eval_report(report) is False

    def test_is_valid_report_missing_timestamp(self):
        """测试缺少时间戳的报告。"""
        report = {"summary": {"dimensions": {"accuracy": 0.8}}}
        assert _is_valid_eval_report(report) is False

    def test_extract_report_timestamp(self, sample_eval_report):
        """测试提取报告时间戳。"""
        ts = _extract_report_timestamp(sample_eval_report)
        assert ts is not None

    def test_extract_report_timestamp_missing(self):
        """测试提取缺失的时间戳。"""
        report = {"summary": {"dimensions": {}}}
        ts = _extract_report_timestamp(report)
        assert ts is None

    def test_extract_report_scores(self, sample_eval_report):
        """测试提取报告分数。"""
        scores = _extract_report_scores(sample_eval_report)
        assert len(scores) == 8
        assert scores["citation_accuracy"] == 0.78
        assert scores["constraint_compliance"] == 0.85

    def test_extract_report_scores_regression(self, sample_regression_report):
        """测试从回归报告提取分数（取 patched）。"""
        scores = _extract_report_scores(sample_regression_report)
        assert scores["citation_accuracy"] == 0.78  # patched
        assert scores["constraint_compliance"] == 0.85  # patched

    def test_extract_report_workflow_id(self, sample_eval_report):
        """测试提取工作流 ID。"""
        wf_id = _extract_report_workflow_id(sample_eval_report)
        assert wf_id == "contract_review"

    def test_extract_report_workflow_id_missing(self):
        """测试提取缺失的工作流 ID。"""
        report = {"summary": {"dimensions": {}}}
        wf_id = _extract_report_workflow_id(report)
        assert wf_id is None


# ═══════════════════════════════════════════════════════════════════════════════
# 4. 趋势数据聚合
# ═══════════════════════════════════════════════════════════════════════════════


class TestTrendAggregation:
    """测试趋势数据聚合功能。"""

    def test_aggregate_trends(self, setup_report_dir):
        """测试聚合趋势数据。"""
        trend_data = aggregate_trends(
            report_dir=setup_report_dir,
            window_days=30,
        )
        assert trend_data["report_count"] > 0
        assert "overall_trend" in trend_data
        assert "dimension_trends" in trend_data
        assert "workflow_trends" in trend_data
        assert "summary" in trend_data

    def test_aggregate_trends_empty_dir(self, temp_dir):
        """测试聚合空目录。"""
        trend_data = aggregate_trends(report_dir=temp_dir)
        assert trend_data["report_count"] == 0
        assert trend_data["summary"]["score_tier"] == "no_data"

    def test_aggregate_trends_with_output(self, setup_report_dir, temp_dir):
        """测试聚合趋势数据并写入文件。"""
        output_path = os.path.join(temp_dir, "_trend_data.json")
        trend_data = aggregate_trends(
            report_dir=setup_report_dir,
            output_path=output_path,
            window_days=30,
        )
        assert os.path.exists(output_path)
        loaded = _load_json(output_path)
        assert loaded["report_count"] == trend_data["report_count"]

    def test_aggregate_trends_summary_fields(self, setup_report_dir):
        """测试趋势数据汇总字段。"""
        trend_data = aggregate_trends(
            report_dir=setup_report_dir,
            window_days=30,
        )
        summary = trend_data["summary"]
        assert "average_score" in summary
        assert "score_tier" in summary
        assert "dimension_averages" in summary
        assert "workflow_averages" in summary
        assert "trend_direction" in summary

    def test_aggregate_trends_dimension_trends(self, setup_report_dir):
        """测试维度趋势数据。"""
        trend_data = aggregate_trends(
            report_dir=setup_report_dir,
            window_days=30,
        )
        dim_trends = trend_data["dimension_trends"]
        assert len(dim_trends) > 0
        for dim, points in dim_trends.items():
            assert len(points) > 0
            assert "date" in points[0]
            assert "score" in points[0]

    def test_aggregate_trends_workflow_trends(self, setup_report_dir):
        """测试工作流趋势数据。"""
        trend_data = aggregate_trends(
            report_dir=setup_report_dir,
            window_days=30,
        )
        wf_trends = trend_data["workflow_trends"]
        assert len(wf_trends) > 0

    def test_calculate_trend_direction_improving(self):
        """测试计算上升趋势。"""
        scores = [0.70, 0.72, 0.75, 0.78, 0.80, 0.82, 0.85]
        assert _calculate_trend_direction(scores) == "improving"

    def test_calculate_trend_direction_declining(self):
        """测试计算下降趋势。"""
        scores = [0.85, 0.82, 0.80, 0.78, 0.75, 0.72, 0.70]
        assert _calculate_trend_direction(scores) == "declining"

    def test_calculate_trend_direction_stable(self):
        """测试计算稳定趋势。"""
        scores = [0.80, 0.81, 0.79, 0.80, 0.81, 0.80, 0.79]
        assert _calculate_trend_direction(scores) == "stable"

    def test_calculate_trend_direction_insufficient_data(self):
        """测试数据不足时返回 stable。"""
        scores = [0.80, 0.81]
        assert _calculate_trend_direction(scores) == "stable"

    def test_calculate_score_tier_excellent(self):
        """测试计算 excellent 等级。"""
        config = _get_default_config()
        assert _calculate_score_tier(0.95, config) == "excellent"

    def test_calculate_score_tier_good(self):
        """测试计算 good 等级。"""
        config = _get_default_config()
        assert _calculate_score_tier(0.85, config) == "good"

    def test_calculate_score_tier_fair(self):
        """测试计算 fair 等级。"""
        config = _get_default_config()
        assert _calculate_score_tier(0.75, config) == "fair"

    def test_calculate_score_tier_poor(self):
        """测试计算 poor 等级。"""
        config = _get_default_config()
        assert _calculate_score_tier(0.55, config) == "poor"

    def test_calculate_score_tier_critical(self):
        """测试计算 critical 等级。"""
        config = _get_default_config()
        assert _calculate_score_tier(0.30, config) == "critical"

    def test_calculate_score_tier_none(self):
        """测试 None 分数返回 no_data。"""
        config = _get_default_config()
        assert _calculate_score_tier(None, config) == "no_data"


# ═══════════════════════════════════════════════════════════════════════════════
# 5. 告警条件检查
# ═══════════════════════════════════════════════════════════════════════════════


class TestAlertChecking:
    """测试告警条件检查功能。"""

    def test_check_alerts_no_triggers(self, sample_trend_data):
        """测试无触发条件。"""
        config = _get_default_config()
        result = check_alerts(
            trend_data=sample_trend_data,
            config=config,
        )
        assert result["alerts_triggered"] == 0
        assert result["auto_rollback_needed"] is False

    def test_check_alerts_score_drop(self, sample_trend_data):
        """测试综合评分下降触发告警（使用 below 操作符）。"""
        config = _get_default_config()
        # 添加触发条件 — 使用 below 操作符（趋势数据分数都低于 0.90）
        config["alerts"]["auto_rollback_triggers"] = [
            {
                "id": "score_drop",
                "name": "综合评分下降",
                "metric": "average_score",
                "operator": "below",
                "threshold": 0.90,
                "window": "7d",
                "min_data_points": 2,
                "action": "rollback_canary",
                "severity": "critical",
                "description": "测试告警",
            }
        ]
        result = check_alerts(
            trend_data=sample_trend_data,
            config=config,
        )
        assert result["alerts_triggered"] > 0

    def test_check_alerts_dimension_drop(self, sample_trend_data):
        """测试维度下降触发告警（使用 below 操作符）。"""
        config = _get_default_config()
        config["alerts"]["auto_rollback_triggers"] = [
            {
                "id": "risk_detection_drop",
                "name": "风险检测率下降",
                "metric": "risk_detection",
                "operator": "below",
                "threshold": 0.90,
                "window": "7d",
                "min_data_points": 2,
                "action": "rollback_canary",
                "severity": "critical",
                "description": "测试维度告警",
            }
        ]
        result = check_alerts(
            trend_data=sample_trend_data,
            config=config,
        )
        assert result["alerts_triggered"] > 0

    def test_check_alerts_with_output(self, sample_trend_data, temp_dir):
        """测试告警结果写入文件。"""
        config = _get_default_config()
        config["alerts"]["auto_rollback_triggers"] = [
            {
                "id": "score_drop",
                "name": "综合评分下降",
                "metric": "average_score",
                "operator": "below",
                "threshold": 0.90,
                "window": "7d",
                "min_data_points": 2,
                "action": "rollback_canary",
                "severity": "critical",
                "description": "测试告警",
            }
        ]
        output_path = os.path.join(temp_dir, "_alerts.json")
        result = check_alerts(
            trend_data=sample_trend_data,
            config=config,
            output_path=output_path,
        )
        assert os.path.exists(output_path)
        loaded = _load_json(output_path)
        assert loaded["total_alerts"] > 0

    def test_check_alerts_dedup(self, sample_trend_data, temp_dir):
        """测试告警去重。"""
        config = _get_default_config()
        config["alerts"]["auto_rollback_triggers"] = [
            {
                "id": "score_drop",
                "name": "综合评分下降",
                "metric": "average_score",
                "operator": "below",
                "threshold": 0.90,
                "window": "7d",
                "min_data_points": 2,
                "action": "rollback_canary",
                "severity": "critical",
                "description": "测试告警",
            }
        ]
        # 第一次检查
        output_path = os.path.join(temp_dir, "_alerts.json")
        result1 = check_alerts(
            trend_data=sample_trend_data,
            config=config,
            output_path=output_path,
        )
        assert result1["alerts_triggered"] > 0

        # 第二次检查（应去重）
        result2 = check_alerts(
            trend_data=sample_trend_data,
            config=config,
            alerts_history_path=output_path,
        )
        assert result2["alerts_triggered"] == 0

    def test_is_alert_deduped_true(self):
        """测试告警已去重。"""
        now = datetime.now(timezone.utc)
        history = [
            {"id": "score_drop", "checked_at": now.isoformat()}
        ]
        assert _is_alert_deduped("score_drop", history, now, timedelta(hours=1)) is True

    def test_is_alert_deduped_false(self):
        """测试告警未去重。"""
        now = datetime.now(timezone.utc)
        history = [
            {"id": "other_alert", "checked_at": now.isoformat()}
        ]
        assert _is_alert_deduped("score_drop", history, now, timedelta(hours=1)) is False

    def test_check_average_score_alert_drop(self, sample_trend_data):
        """测试综合评分下降告警。"""
        # 使用下降趋势的数据（从旧到新，分数递减）
        now = datetime.now(timezone.utc)
        declining_trend = [
            {"date": (now - timedelta(days=i)).strftime("%Y-%m-%d"),
             "average_score": round(0.85 - (6 - i) * 0.02, 4),
             "report_count": 2}
            for i in range(6, -1, -1)
        ]
        alert = _check_average_score_alert(
            overall_trend=declining_trend,
            operator="drop_by",
            threshold=0.05,
            window=timedelta(days=7),
            min_points=2,
            consecutive=False,
            trigger_id="test",
            action="rollback_canary",
            severity="critical",
            description="测试",
        )
        assert alert is not None
        assert alert["metric"] == "average_score"
        assert alert["operator"] == "drop_by"
        assert alert["details"]["drop"] > 0.05

    def test_check_average_score_alert_below(self, sample_trend_data):
        """测试综合评分低于阈值告警。"""
        trend = sample_trend_data["overall_trend"]
        alert = _check_average_score_alert(
            overall_trend=trend,
            operator="below",
            threshold=0.90,
            window=timedelta(days=7),
            min_points=2,
            consecutive=False,
            trigger_id="test",
            action="notify_only",
            severity="warning",
            description="测试",
        )
        assert alert is not None
        assert alert["metric"] == "average_score"

    def test_check_dimension_alert_drop(self, sample_trend_data):
        """测试维度下降告警。"""
        dim_data = sample_trend_data["dimension_trends"]["citation_accuracy"]
        alert = _check_dimension_alert(
            dimension_data=dim_data,
            dimension_id="citation_accuracy",
            operator="drop_by",
            threshold=0.01,
            window=timedelta(days=7),
            min_points=2,
            consecutive=False,
            trigger_id="test",
            action="rollback_canary",
            severity="critical",
            description="测试",
        )
        # citation_accuracy 趋势从 0.81 下降到 0.75，drop=0.06 > 0.01
        assert alert is not None
        assert alert["metric"] == "citation_accuracy"
        assert alert["operator"] == "drop_by"
        assert alert["details"]["drop"] > 0.01

    def test_check_dimension_alert_insufficient_data(self):
        """测试数据不足时不触发告警。"""
        alert = _check_dimension_alert(
            dimension_data=[{"date": "2026-05-06", "score": 0.8}],
            dimension_id="test",
            operator="drop_by",
            threshold=0.1,
            window=timedelta(days=7),
            min_points=5,
            consecutive=False,
            trigger_id="test",
            action="notify_only",
            severity="warning",
            description="测试",
        )
        assert alert is None


# ═══════════════════════════════════════════════════════════════════════════════
# 6. 自动回滚触发
# ═══════════════════════════════════════════════════════════════════════════════


class TestAutoRollback:
    """测试自动回滚触发功能。"""

    def test_auto_rollback_no_trigger(self, sample_trend_data):
        """测试未触发自动回滚。"""
        config = _get_default_config()
        result = auto_rollback(
            trend_data=sample_trend_data,
            config=config,
            dry_run=True,
        )
        assert result["rollbacks_executed"] == 0
        assert len(result["rollbacks"]) == 0

    def test_auto_rollback_dry_run(self, sample_trend_data):
        """测试模拟模式。"""
        config = _get_default_config()
        config["alerts"]["auto_rollback_triggers"] = [
            {
                "id": "score_drop",
                "name": "综合评分下降",
                "metric": "average_score",
                "operator": "below",
                "threshold": 0.90,
                "window": "7d",
                "min_data_points": 2,
                "action": "rollback_canary",
                "severity": "critical",
                "description": "测试自动回滚",
            }
        ]
        result = auto_rollback(
            trend_data=sample_trend_data,
            config=config,
            dry_run=True,
        )
        assert result["dry_run"] is True
        # 没有 change_id 关联，所以不会执行回滚
        assert result["rollbacks_executed"] == 0

    def test_auto_rollback_with_rollout_record(self, sample_trend_data, temp_dir):
        """测试有灰度发布记录时的自动回滚。"""
        # 创建灰度发布记录
        rollout_dir = os.path.join(temp_dir, "rollout")
        change_dir = os.path.join(temp_dir, "candidate_changes")
        os.makedirs(rollout_dir, exist_ok=True)
        os.makedirs(change_dir, exist_ok=True)

        change_id = f"change_{uuid.uuid4().hex[:8]}"
        rollout_record = {
            "change_id": change_id,
            "status": "canary",
            "strategy": "canary",
            "events": [{"event": "started", "timestamp": datetime.now(timezone.utc).isoformat()}],
        }
        _write_json(os.path.join(rollout_dir, f"{change_id}_rollout.json"), rollout_record)

        # 创建候选变更
        candidate = {
            "change_id": change_id,
            "rollout": {"status": "canary", "strategy": "canary"},
        }
        _write_json(os.path.join(change_dir, f"{change_id}.json"), candidate)

        config = _get_default_config()
        config["alerts"]["auto_rollback_triggers"] = [
            {
                "id": "score_drop",
                "name": "综合评分下降",
                "metric": "average_score",
                "operator": "below",
                "threshold": 0.90,
                "window": "7d",
                "min_data_points": 2,
                "action": "rollback_canary",
                "severity": "critical",
                "description": "测试自动回滚",
            }
        ]

        # 模拟模式
        result = auto_rollback(
            trend_data=sample_trend_data,
            rollout_dir=rollout_dir,
            change_dir=change_dir,
            config=config,
            dry_run=True,
        )
        assert result["dry_run"] is True
        assert len(result["rollbacks"]) > 0
        assert result["rollbacks"][0]["dry_run"] is True


# ═══════════════════════════════════════════════════════════════════════════════
# 7. HTML 仪表盘生成
# ═══════════════════════════════════════════════════════════════════════════════


class TestHTMLDashboard:
    """测试 HTML 仪表盘生成功能。"""

    def test_generate_html(self, sample_trend_data, temp_dir):
        """测试生成 HTML 仪表盘。"""
        output_path = os.path.join(temp_dir, "index.html")
        html_path = generate_html_dashboard(
            trend_data=sample_trend_data,
            output_path=output_path,
        )
        assert os.path.exists(html_path)
        with open(html_path, "r", encoding="utf-8") as f:
            content = f.read()
        assert "质量仪表盘" in content
        assert "Phase 7f" in content
        assert "综合评分" in content

    def test_generate_html_empty_data(self, temp_dir):
        """测试空数据生成 HTML。"""
        empty_data = {
            "generated_at": "2026-05-07T00:00:00Z",
            "report_count": 0,
            "window_days": 30,
            "summary": {
                "average_score": None,
                "score_tier": "no_data",
                "dimension_averages": {},
                "workflow_averages": {},
                "trend_direction": "stable",
            },
            "overall_trend": [],
        }
        output_path = os.path.join(temp_dir, "empty.html")
        html_path = generate_html_dashboard(
            trend_data=empty_data,
            output_path=output_path,
        )
        assert os.path.exists(html_path)


# ═══════════════════════════════════════════════════════════════════════════════
# 8. 仪表盘统计
# ═══════════════════════════════════════════════════════════════════════════════


class TestDashboardStats:
    """测试仪表盘统计功能。"""

    def test_get_stats(self, sample_trend_data):
        """测试获取仪表盘统计。"""
        stats = get_dashboard_stats(sample_trend_data)
        assert stats["report_count"] == 10
        assert stats["trend_points_count"] == 7
        assert stats["dimension_count"] == 2
        assert stats["workflow_count"] == 1
        assert "dimension_directions" in stats
        assert "workflow_directions" in stats
        assert "score_distribution" in stats

    def test_get_stats_empty_data(self):
        """测试空数据统计。"""
        empty_data = {
            "generated_at": "2026-05-07T00:00:00Z",
            "report_count": 0,
            "summary": {},
            "overall_trend": [],
            "dimension_trends": {},
            "workflow_trends": {},
        }
        stats = get_dashboard_stats(empty_data)
        assert stats["report_count"] == 0
        assert stats["trend_points_count"] == 0

    def test_get_stats_dimension_directions(self, sample_trend_data):
        """测试维度趋势方向。"""
        stats = get_dashboard_stats(sample_trend_data)
        for dim, direction in stats["dimension_directions"].items():
            assert direction in ["improving", "declining", "stable"]

    def test_get_stats_score_distribution(self, sample_trend_data):
        """测试评分分布。"""
        stats = get_dashboard_stats(sample_trend_data)
        distribution = stats["score_distribution"]
        assert "excellent" in distribution
        assert "good" in distribution
        assert "fair" in distribution
        assert "poor" in distribution
        assert "critical" in distribution


# ═══════════════════════════════════════════════════════════════════════════════
# 9. 文件 I/O 辅助函数
# ═══════════════════════════════════════════════════════════════════════════════


class TestFileIO:
    """测试文件 I/O 辅助函数。"""

    def test_load_json_not_found(self, temp_dir):
        """测试加载不存在的 JSON 文件。"""
        path = os.path.join(temp_dir, "nonexistent.json")
        with pytest.raises(FileNotFoundError):
            _load_json(path)

    def test_write_and_load_json(self, temp_dir):
        """测试写入和加载 JSON 文件。"""
        data = {"key": "value", "number": 42}
        path = os.path.join(temp_dir, "test.json")
        _write_json(path, data)
        loaded = _load_json(path)
        assert loaded == data

    def test_write_json_creates_directory(self, temp_dir):
        """测试写入 JSON 时自动创建目录。"""
        data = {"test": True}
        path = os.path.join(temp_dir, "subdir", "nested", "test.json")
        _write_json(path, data)
        assert os.path.exists(path)
        loaded = _load_json(path)
        assert loaded == data

    def test_load_yaml_not_found(self):
        """测试加载不存在的 YAML 文件。"""
        with pytest.raises(FileNotFoundError):
            _load_yaml("nonexistent.yaml")


# ═══════════════════════════════════════════════════════════════════════════════
# 10. 端到端工作流
# ═══════════════════════════════════════════════════════════════════════════════


class TestEndToEndDashboardWorkflow:
    """测试完整的仪表盘工作流。"""

    def test_full_workflow(self, setup_report_dir, temp_dir):
        """测试完整工作流: 扫描 → 聚合 → 检查告警 → 统计。"""
        # Step 1: 聚合趋势数据
        trend_data = aggregate_trends(
            report_dir=setup_report_dir,
            window_days=30,
        )
        assert trend_data["report_count"] > 0
        assert trend_data["summary"]["average_score"] is not None

        # Step 2: 检查告警（无触发条件）
        config = _get_default_config()
        alert_result = check_alerts(
            trend_data=trend_data,
            config=config,
        )
        assert alert_result["alerts_triggered"] == 0

        # Step 3: 获取统计
        stats = get_dashboard_stats(trend_data)
        assert stats["report_count"] > 0
        assert stats["trend_points_count"] > 0

    def test_workflow_with_alerts(self, setup_report_dir, temp_dir):
        """测试带告警的工作流。"""
        # Step 1: 聚合趋势数据
        trend_data = aggregate_trends(
            report_dir=setup_report_dir,
            window_days=30,
        )

        # Step 2: 配置告警条件
        config = _get_default_config()
        config["alerts"]["auto_rollback_triggers"] = [
            {
                "id": "score_drop",
                "name": "综合评分下降",
                "metric": "average_score",
                "operator": "below",
                "threshold": 0.90,
                "window": "30d",
                "min_data_points": 2,
                "action": "rollback_canary",
                "severity": "critical",
                "description": "测试告警",
            }
        ]

        # Step 3: 检查告警
        alert_result = check_alerts(
            trend_data=trend_data,
            config=config,
        )
        assert alert_result["alerts_triggered"] > 0

    def test_workflow_with_html(self, setup_report_dir, temp_dir):
        """测试带 HTML 生成的工作流。"""
        # Step 1: 聚合趋势数据
        trend_data = aggregate_trends(
            report_dir=setup_report_dir,
            window_days=30,
        )

        # Step 2: 生成 HTML
        output_path = os.path.join(temp_dir, "dashboard.html")
        html_path = generate_html_dashboard(
            trend_data=trend_data,
            output_path=output_path,
        )
        assert os.path.exists(html_path)

    def test_workflow_with_auto_rollback(self, setup_report_dir, temp_dir):
        """测试带自动回滚的工作流。"""
        # Step 1: 创建灰度发布记录
        rollout_dir = os.path.join(temp_dir, "rollout")
        change_dir = os.path.join(temp_dir, "candidate_changes")
        os.makedirs(rollout_dir, exist_ok=True)
        os.makedirs(change_dir, exist_ok=True)

        change_id = f"change_{uuid.uuid4().hex[:8]}"
        rollout_record = {
            "change_id": change_id,
            "status": "canary",
            "strategy": "canary",
            "events": [{"event": "started", "timestamp": datetime.now(timezone.utc).isoformat()}],
        }
        _write_json(os.path.join(rollout_dir, f"{change_id}_rollout.json"), rollout_record)

        candidate = {
            "change_id": change_id,
            "rollout": {"status": "canary", "strategy": "canary"},
        }
        _write_json(os.path.join(change_dir, f"{change_id}.json"), candidate)

        # Step 2: 聚合趋势数据
        trend_data = aggregate_trends(
            report_dir=setup_report_dir,
            window_days=30,
        )

        # Step 3: 配置告警并执行自动回滚（模拟模式）
        config = _get_default_config()
        config["alerts"]["auto_rollback_triggers"] = [
            {
                "id": "score_drop",
                "name": "综合评分下降",
                "metric": "average_score",
                "operator": "below",
                "threshold": 0.90,
                "window": "30d",
                "min_data_points": 2,
                "action": "rollback_canary",
                "severity": "critical",
                "description": "测试自动回滚",
            }
        ]

        result = auto_rollback(
            trend_data=trend_data,
            rollout_dir=rollout_dir,
            change_dir=change_dir,
            config=config,
            dry_run=True,
        )
        assert result["dry_run"] is True
        assert len(result["rollbacks"]) > 0

    def test_workflow_state_persistence(self, setup_report_dir, temp_dir):
        """测试工作流状态持久化。"""
        # Step 1: 聚合趋势数据并写入文件
        trend_output = os.path.join(temp_dir, "_trend_data.json")
        trend_data = aggregate_trends(
            report_dir=setup_report_dir,
            output_path=trend_output,
            window_days=30,
        )

        # Step 2: 从文件重新加载
        loaded = _load_json(trend_output)
        assert loaded["report_count"] == trend_data["report_count"]
        assert loaded["summary"]["average_score"] == trend_data["summary"]["average_score"]

        # Step 3: 检查告警并写入文件
        config = _get_default_config()
        config["alerts"]["auto_rollback_triggers"] = [
            {
                "id": "score_drop",
                "name": "综合评分下降",
                "metric": "average_score",
                "operator": "below",
                "threshold": 0.90,
                "window": "30d",
                "min_data_points": 2,
                "action": "rollback_canary",
                "severity": "critical",
                "description": "测试告警",
            }
        ]
        alert_output = os.path.join(temp_dir, "_alerts.json")
        alert_result = check_alerts(
            trend_data=loaded,
            config=config,
            output_path=alert_output,
        )

        # Step 4: 从文件重新加载告警
        loaded_alerts = _load_json(alert_output)
        assert loaded_alerts["total_alerts"] > 0
        assert loaded_alerts["total_alerts"] == alert_result["alerts_triggered"]
