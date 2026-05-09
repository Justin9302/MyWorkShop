#!/usr/bin/env python3
"""
test_rollout_manager.py — Phase 7e: 灰度发布管理器单元测试

测试覆盖:
  1. 灰度策略配置加载
  2. 候选变更验证（正常/异常路径）
  3. 状态转换验证
  4. 灰度发布启动（canary / full）
  5. 灰度状态查询
  6. 全量发布 (promote)
  7. 回滚 (rollback)
  8. 活跃灰度发布列表
  9. 回滚条件检查
  10. 指标快照记录
  11. 观察期解析
  12. 端到端灰度发布工作流

运行:
  python -m pytest tests/phase7e/test_rollout_manager.py -v
  python -m pytest tests/phase7e/test_rollout_manager.py -v --tb=short
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

from scripts.rollout_manager import (
    # 常量
    STATUS_PENDING,
    STATUS_CANARY,
    STATUS_FULL,
    STATUS_COMPLETED,
    STATUS_ROLLED_BACK,
    STATUS_FAILED,
    VALID_STATUSES,
    ALLOWED_TRANSITIONS,
    DEFAULT_METRICS,
    # 配置加载
    load_rollout_config,
    _parse_observation_period,
    # 验证
    _validate_candidate_for_rollout,
    _validate_status_transition,
    # 核心操作
    start_rollout,
    get_rollout_status,
    promote_rollout,
    rollback_rollout,
    list_active_rollouts,
    check_rollback_conditions,
    record_metrics_snapshot,
    # 文件 I/O
    _load_json,
    _write_json,
    _load_yaml,
    _write_yaml,
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
def sample_candidate_change():
    """创建一个通过沙箱测试和人工审批的候选变更。"""
    change_id = f"change_{uuid.uuid4().hex[:8]}"
    return {
        "change_id": change_id,
        "source": {
            "run_id": "run_sample_001",
            "report_path": "outputs/eval_reports/run_sample_001_eval.json",
            "suggestion_index": 0,
        },
        "target": {
            "component": "constraint_rules",
            "file_path": "constraints/industries/legal.yaml",
            "change_type": "add_rule",
        },
        "diff": {
            "summary": "增加中国民法典第506条作为合同审查强制引用",
            "before": "...existing rules...",
            "after": "...patched rules...",
        },
        "validation": {
            "status": "sandbox_pass",
            "sandbox_report": "outputs/eval_reports/regression/change_regression_report.json",
            "regression_result": {
                "overall_score_change": 0.03,
                "regressions": [],
                "improvements": ["citation_accuracy +0.06"],
            },
        },
        "approval": {
            "required": True,
            "approved_by": "feng",
            "approved_at": "2026-05-06T10:00:00Z",
            "review_notes": "变更合理，通过审批",
        },
        "rollout": {
            "strategy": "canary",
            "traffic_split": 0.1,
            "status": STATUS_PENDING,
        },
        "created_at": "2026-05-05T00:00:00Z",
    }


@pytest.fixture
def sample_regression_report():
    """创建一个回归测试报告。"""
    return {
        "change_id": "change_abc12345",
        "status": "sandbox_pass",
        "baseline_version": "0.1.0",
        "patched_version": "0.1.1-candidate",
        "eval_set": "tests/eval_cases/",
        "sample_count": 12,
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
        "created_at": "2026-05-06T00:00:00Z",
    }


@pytest.fixture
def setup_rollout_env(temp_dir, sample_candidate_change):
    """设置完整的灰度发布测试环境。"""
    # 创建候选变更目录
    change_dir = os.path.join(temp_dir, "candidate_changes")
    os.makedirs(change_dir, exist_ok=True)

    # 创建输出目录
    output_dir = os.path.join(temp_dir, "rollout")
    os.makedirs(output_dir, exist_ok=True)

    # 写入候选变更文件
    change_path = os.path.join(change_dir, f"{sample_candidate_change['change_id']}.json")
    _write_json(change_path, sample_candidate_change)

    return {
        "temp_dir": temp_dir,
        "change_dir": change_dir,
        "output_dir": output_dir,
        "change_path": change_path,
        "change_id": sample_candidate_change["change_id"],
        "candidate": sample_candidate_change,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# 1. 灰度策略配置加载
# ═══════════════════════════════════════════════════════════════════════════════


class TestRolloutConfigLoading:
    """测试灰度策略配置加载功能。"""

    def test_load_default_config(self):
        """测试加载默认配置文件。"""
        config = load_rollout_config()
        assert config is not None
        assert "default_strategy" in config
        assert config["default_strategy"] == "canary"
        assert "canary" in config
        assert "full_rollout" in config

    def test_canary_config_values(self):
        """测试金丝雀发布配置值。"""
        config = load_rollout_config()
        canary = config["canary"]
        assert canary["enabled"] is True
        assert canary["traffic_split"] == 0.1
        assert canary["observation_period"] == "7d"
        assert "rollback_conditions" in canary

    def test_full_rollout_config_values(self):
        """测试全量发布配置值。"""
        config = load_rollout_config()
        full = config["full_rollout"]
        assert full["observation_period"] == "14d"
        assert "rollback_conditions" in full

    def test_rollback_conditions(self):
        """测试回滚条件配置。"""
        config = load_rollout_config()
        canary_conditions = config["canary"]["rollback_conditions"]
        assert canary_conditions["score_drop_threshold"] == 0.1
        assert canary_conditions["risk_increase_threshold"] == "high"
        assert canary_conditions["human_modification_increase"] == 0.2
        assert canary_conditions["critical_regression_count"] == 1

    def test_config_file_not_found(self):
        """测试配置文件不存在时的行为。"""
        with pytest.raises(FileNotFoundError):
            load_rollout_config("nonexistent_config.yaml")


# ═══════════════════════════════════════════════════════════════════════════════
# 2. 观察期解析
# ═══════════════════════════════════════════════════════════════════════════════


class TestObservationPeriodParsing:
    """测试观察期字符串解析。"""

    def test_parse_days(self):
        """测试解析天数。"""
        delta = _parse_observation_period("7d")
        assert delta == timedelta(days=7)

    def test_parse_hours(self):
        """测试解析小时数。"""
        delta = _parse_observation_period("24h")
        assert delta == timedelta(hours=24)

    def test_parse_weeks(self):
        """测试解析周数。"""
        delta = _parse_observation_period("2w")
        assert delta == timedelta(weeks=2)

    def test_parse_invalid_format(self):
        """测试解析无效格式（应返回默认 7 天）。"""
        delta = _parse_observation_period("invalid")
        assert delta == timedelta(days=7)

    def test_parse_empty_string(self):
        """测试解析空字符串（应返回默认 7 天）。"""
        delta = _parse_observation_period("")
        assert delta == timedelta(days=7)

    def test_parse_single_digit(self):
        """测试解析单个数字。"""
        delta = _parse_observation_period("1d")
        assert delta == timedelta(days=1)

    def test_parse_large_number(self):
        """测试解析大数字。"""
        delta = _parse_observation_period("30d")
        assert delta == timedelta(days=30)


# ═══════════════════════════════════════════════════════════════════════════════
# 3. 候选变更验证
# ═══════════════════════════════════════════════════════════════════════════════


class TestCandidateValidation:
    """测试候选变更验证功能。"""

    def test_valid_candidate(self, sample_candidate_change):
        """测试有效的候选变更。"""
        valid, msg = _validate_candidate_for_rollout(sample_candidate_change)
        assert valid is True
        assert msg == ""

    def test_missing_change_id(self, sample_candidate_change):
        """测试缺少 change_id。"""
        change = sample_candidate_change.copy()
        change["change_id"] = ""
        valid, msg = _validate_candidate_for_rollout(change)
        assert valid is False
        assert "缺少 change_id" in msg

    def test_not_sandbox_pass(self, sample_candidate_change):
        """测试未通过沙箱测试。"""
        change = sample_candidate_change.copy()
        change["validation"]["status"] = "sandbox_fail"
        valid, msg = _validate_candidate_for_rollout(change)
        assert valid is False
        assert "sandbox_pass" in msg

    def test_not_approved(self, sample_candidate_change):
        """测试未通过人工审批。"""
        change = sample_candidate_change.copy()
        change["approval"]["approved_by"] = None
        valid, msg = _validate_candidate_for_rollout(change)
        assert valid is False
        assert "approved_by" in msg

    def test_already_rolled_out(self, sample_candidate_change):
        """测试已经灰度发布过的变更。"""
        change = sample_candidate_change.copy()
        change["rollout"]["status"] = STATUS_COMPLETED
        valid, msg = _validate_candidate_for_rollout(change)
        assert valid is False
        assert "rollout.status" in msg

    def test_already_rolled_back(self, sample_candidate_change):
        """测试已经回滚过的变更。"""
        change = sample_candidate_change.copy()
        change["rollout"]["status"] = STATUS_ROLLED_BACK
        valid, msg = _validate_candidate_for_rollout(change)
        assert valid is False
        assert "rollout.status" in msg

    def test_approval_not_required(self, sample_candidate_change):
        """测试不需要审批的变更（approval.required=False）。"""
        change = sample_candidate_change.copy()
        change["approval"]["required"] = False
        change["approval"]["approved_by"] = None
        valid, msg = _validate_candidate_for_rollout(change)
        assert valid is True


# ═══════════════════════════════════════════════════════════════════════════════
# 4. 状态转换验证
# ═══════════════════════════════════════════════════════════════════════════════


class TestStatusTransition:
    """测试灰度状态转换验证。"""

    def test_pending_to_canary(self):
        """测试 pending → canary。"""
        valid, msg = _validate_status_transition(STATUS_PENDING, STATUS_CANARY)
        assert valid is True

    def test_pending_to_full(self):
        """测试 pending → full。"""
        valid, msg = _validate_status_transition(STATUS_PENDING, STATUS_FULL)
        assert valid is True

    def test_pending_to_rolled_back(self):
        """测试 pending → rolled_back。"""
        valid, msg = _validate_status_transition(STATUS_PENDING, STATUS_ROLLED_BACK)
        assert valid is True

    def test_canary_to_full(self):
        """测试 canary → full。"""
        valid, msg = _validate_status_transition(STATUS_CANARY, STATUS_FULL)
        assert valid is True

    def test_canary_to_rolled_back(self):
        """测试 canary → rolled_back。"""
        valid, msg = _validate_status_transition(STATUS_CANARY, STATUS_ROLLED_BACK)
        assert valid is True

    def test_full_to_completed(self):
        """测试 full → completed。"""
        valid, msg = _validate_status_transition(STATUS_FULL, STATUS_COMPLETED)
        assert valid is True

    def test_full_to_rolled_back(self):
        """测试 full → rolled_back。"""
        valid, msg = _validate_status_transition(STATUS_FULL, STATUS_ROLLED_BACK)
        assert valid is True

    def test_invalid_transition(self):
        """测试无效转换。"""
        valid, msg = _validate_status_transition(STATUS_COMPLETED, STATUS_CANARY)
        assert valid is False

    def test_completed_to_anything(self):
        """测试 completed 不能转换到任何状态。"""
        for target in VALID_STATUSES:
            if target != STATUS_COMPLETED:
                valid, _ = _validate_status_transition(STATUS_COMPLETED, target)
                assert valid is False

    def test_rolled_back_to_anything(self):
        """测试 rolled_back 不能转换到任何状态。"""
        for target in VALID_STATUSES:
            if target != STATUS_ROLLED_BACK:
                valid, _ = _validate_status_transition(STATUS_ROLLED_BACK, target)
                assert valid is False


# ═══════════════════════════════════════════════════════════════════════════════
# 5. 灰度发布启动
# ═══════════════════════════════════════════════════════════════════════════════


class TestStartRollout:
    """测试灰度发布启动功能。"""

    def test_start_canary_rollout(self, setup_rollout_env):
        """测试启动金丝雀发布。"""
        env = setup_rollout_env
        record = start_rollout(
            change_path=env["change_path"],
            strategy="canary",
            rollout_config_path="config/rollout-policy.yaml",
            output_dir=env["output_dir"],
        )
        assert record["status"] == STATUS_CANARY
        assert record["strategy"] == "canary"
        assert record["traffic_split"] == 0.1
        assert record["change_id"] == env["change_id"]
        assert len(record["events"]) == 1
        assert record["events"][0]["event"] == "started"

    def test_start_full_rollout(self, setup_rollout_env):
        """测试启动全量发布。"""
        env = setup_rollout_env
        record = start_rollout(
            change_path=env["change_path"],
            strategy="full",
            rollout_config_path="config/rollout-policy.yaml",
            output_dir=env["output_dir"],
        )
        assert record["status"] == STATUS_FULL
        assert record["strategy"] == "full"
        assert record["traffic_split"] == 1.0

    def test_start_rollout_updates_candidate(self, setup_rollout_env):
        """测试启动灰度发布后候选变更被更新。"""
        env = setup_rollout_env
        start_rollout(
            change_path=env["change_path"],
            strategy="canary",
            rollout_config_path="config/rollout-policy.yaml",
            output_dir=env["output_dir"],
        )
        # 重新加载候选变更
        updated = _load_json(env["change_path"])
        assert updated["rollout"]["status"] == STATUS_CANARY
        assert updated["rollout"]["strategy"] == "canary"
        assert updated["rollout"]["traffic_split"] == 0.1

    def test_start_rollout_with_custom_traffic_split(self, setup_rollout_env):
        """测试使用自定义流量比例。"""
        env = setup_rollout_env
        record = start_rollout(
            change_path=env["change_path"],
            strategy="canary",
            traffic_split=0.2,
            rollout_config_path="config/rollout-policy.yaml",
            output_dir=env["output_dir"],
        )
        assert record["traffic_split"] == 0.2

    def test_start_rollout_without_approval(self, setup_rollout_env):
        """测试未审批的变更启动灰度发布应失败。"""
        env = setup_rollout_env
        # 修改候选变更为未审批状态
        change = _load_json(env["change_path"])
        change["approval"]["approved_by"] = None
        _write_json(env["change_path"], change)

        with pytest.raises(ValueError, match="approved_by"):
            start_rollout(
                change_path=env["change_path"],
                strategy="canary",
                rollout_config_path="config/rollout-policy.yaml",
                output_dir=env["output_dir"],
            )

    def test_start_rollout_force(self, setup_rollout_env):
        """测试 force 模式跳过验证。"""
        env = setup_rollout_env
        # 修改候选变更为未审批状态
        change = _load_json(env["change_path"])
        change["approval"]["approved_by"] = None
        _write_json(env["change_path"], change)

        # force=True 应跳过验证
        record = start_rollout(
            change_path=env["change_path"],
            strategy="canary",
            rollout_config_path="config/rollout-policy.yaml",
            output_dir=env["output_dir"],
            force=True,
        )
        assert record["status"] == STATUS_CANARY

    def test_start_rollout_creates_record_file(self, setup_rollout_env):
        """测试启动灰度发布后创建记录文件。"""
        env = setup_rollout_env
        start_rollout(
            change_path=env["change_path"],
            strategy="canary",
            rollout_config_path="config/rollout-policy.yaml",
            output_dir=env["output_dir"],
        )
        record_path = os.path.join(env["output_dir"], f"{env['change_id']}_rollout.json")
        assert os.path.exists(record_path)

    def test_start_rollout_invalid_strategy(self, setup_rollout_env):
        """测试无效的灰度策略。"""
        env = setup_rollout_env
        with pytest.raises(ValueError, match="无效的灰度策略"):
            start_rollout(
                change_path=env["change_path"],
                strategy="invalid",
                rollout_config_path="config/rollout-policy.yaml",
                output_dir=env["output_dir"],
            )


# ═══════════════════════════════════════════════════════════════════════════════
# 6. 灰度状态查询
# ═══════════════════════════════════════════════════════════════════════════════


class TestGetRolloutStatus:
    """测试灰度状态查询功能。"""

    def test_get_status_after_start(self, setup_rollout_env):
        """测试启动后查询状态。"""
        env = setup_rollout_env
        start_rollout(
            change_path=env["change_path"],
            strategy="canary",
            rollout_config_path="config/rollout-policy.yaml",
            output_dir=env["output_dir"],
        )
        status = get_rollout_status(
            change_id=env["change_id"],
            change_dir=env["change_dir"],
            output_dir=env["output_dir"],
        )
        assert status["status"] == STATUS_CANARY
        assert status["strategy"] == "canary"
        assert status["traffic_split"] == 0.1
        assert status["change_id"] == env["change_id"]

    def test_get_status_not_found(self, setup_rollout_env):
        """测试查询不存在的灰度发布。"""
        env = setup_rollout_env
        status = get_rollout_status(
            change_id="nonexistent_change",
            change_dir=env["change_dir"],
            output_dir=env["output_dir"],
        )
        assert status["status"] == "not_found"

    def test_get_status_with_change_info(self, setup_rollout_env):
        """测试查询状态包含候选变更信息。"""
        env = setup_rollout_env
        start_rollout(
            change_path=env["change_path"],
            strategy="canary",
            rollout_config_path="config/rollout-policy.yaml",
            output_dir=env["output_dir"],
        )
        status = get_rollout_status(
            change_id=env["change_id"],
            change_dir=env["change_dir"],
            output_dir=env["output_dir"],
        )
        assert "change" in status
        assert status["change"]["target_component"] == "constraint_rules"
        assert status["change"]["change_type"] == "add_rule"
        assert status["change"]["approved_by"] == "feng"

    def test_get_status_observation_not_expired(self, setup_rollout_env):
        """测试观察期未到期。"""
        env = setup_rollout_env
        start_rollout(
            change_path=env["change_path"],
            strategy="canary",
            rollout_config_path="config/rollout-policy.yaml",
            output_dir=env["output_dir"],
        )
        status = get_rollout_status(
            change_id=env["change_id"],
            change_dir=env["change_dir"],
            output_dir=env["output_dir"],
        )
        assert status["observation_expired"] is False
        assert status["remaining_time"] is not None


# ═══════════════════════════════════════════════════════════════════════════════
# 7. 全量发布 (Promote)
# ═══════════════════════════════════════════════════════════════════════════════


class TestPromoteRollout:
    """测试全量发布功能。"""

    def test_promote_canary_to_full(self, setup_rollout_env):
        """测试从 canary 晋升到 full。"""
        env = setup_rollout_env
        # 先启动 canary
        start_rollout(
            change_path=env["change_path"],
            strategy="canary",
            rollout_config_path="config/rollout-policy.yaml",
            output_dir=env["output_dir"],
        )
        # 晋升到 full（使用 force 跳过观察期检查）
        record = promote_rollout(
            change_id=env["change_id"],
            change_dir=env["change_dir"],
            output_dir=env["output_dir"],
            force=True,
        )
        assert record["status"] == STATUS_FULL
        assert len(record["events"]) == 2  # started + promoted

    def test_promote_full_to_completed(self, setup_rollout_env):
        """测试从 full 晋升到 completed。"""
        env = setup_rollout_env
        # 先启动 full
        start_rollout(
            change_path=env["change_path"],
            strategy="full",
            rollout_config_path="config/rollout-policy.yaml",
            output_dir=env["output_dir"],
        )
        # 晋升到 completed
        record = promote_rollout(
            change_id=env["change_id"],
            change_dir=env["change_dir"],
            output_dir=env["output_dir"],
            force=True,
        )
        assert record["status"] == STATUS_COMPLETED
        assert record["completed_at"] is not None

    def test_promote_updates_candidate(self, setup_rollout_env):
        """测试 promote 后候选变更被更新。"""
        env = setup_rollout_env
        start_rollout(
            change_path=env["change_path"],
            strategy="canary",
            rollout_config_path="config/rollout-policy.yaml",
            output_dir=env["output_dir"],
        )
        promote_rollout(
            change_id=env["change_id"],
            change_dir=env["change_dir"],
            output_dir=env["output_dir"],
            force=True,
        )
        updated = _load_json(env["change_path"])
        assert updated["rollout"]["status"] == STATUS_FULL

    def test_promote_completed_to_full(self, setup_rollout_env):
        """测试 completed 状态不能 promote。"""
        env = setup_rollout_env
        start_rollout(
            change_path=env["change_path"],
            strategy="full",
            rollout_config_path="config/rollout-policy.yaml",
            output_dir=env["output_dir"],
        )
        promote_rollout(
            change_id=env["change_id"],
            change_dir=env["change_dir"],
            output_dir=env["output_dir"],
            force=True,
        )
        # 已经是 completed，再次 promote 应失败
        with pytest.raises(ValueError, match="不允许 promote"):
            promote_rollout(
                change_id=env["change_id"],
                change_dir=env["change_dir"],
                output_dir=env["output_dir"],
                force=True,
            )

    def test_promote_not_found(self, setup_rollout_env):
        """测试 promote 不存在的变更。"""
        with pytest.raises(ValueError, match="未找到灰度发布记录"):
            promote_rollout(
                change_id="nonexistent",
                change_dir=setup_rollout_env["change_dir"],
                output_dir=setup_rollout_env["output_dir"],
            )


# ═══════════════════════════════════════════════════════════════════════════════
# 8. 回滚
# ═══════════════════════════════════════════════════════════════════════════════


class TestRollbackRollout:
    """测试回滚功能。"""

    def test_rollback_canary(self, setup_rollout_env):
        """测试回滚 canary 发布。"""
        env = setup_rollout_env
        start_rollout(
            change_path=env["change_path"],
            strategy="canary",
            rollout_config_path="config/rollout-policy.yaml",
            output_dir=env["output_dir"],
        )
        record = rollback_rollout(
            change_id=env["change_id"],
            reason="测试回滚",
            change_dir=env["change_dir"],
            output_dir=env["output_dir"],
        )
        assert record["status"] == STATUS_ROLLED_BACK
        assert record["rollback_reason"] == "测试回滚"
        assert record["rolled_back_at"] is not None

    def test_rollback_full(self, setup_rollout_env):
        """测试回滚 full 发布。"""
        env = setup_rollout_env
        start_rollout(
            change_path=env["change_path"],
            strategy="full",
            rollout_config_path="config/rollout-policy.yaml",
            output_dir=env["output_dir"],
        )
        record = rollback_rollout(
            change_id=env["change_id"],
            reason="score dropped",
            change_dir=env["change_dir"],
            output_dir=env["output_dir"],
        )
        assert record["status"] == STATUS_ROLLED_BACK

    def test_rollback_updates_candidate(self, setup_rollout_env):
        """测试回滚后候选变更被更新。"""
        env = setup_rollout_env
        start_rollout(
            change_path=env["change_path"],
            strategy="canary",
            rollout_config_path="config/rollout-policy.yaml",
            output_dir=env["output_dir"],
        )
        rollback_rollout(
            change_id=env["change_id"],
            reason="测试",
            change_dir=env["change_dir"],
            output_dir=env["output_dir"],
        )
        updated = _load_json(env["change_path"])
        assert updated["rollout"]["status"] == STATUS_ROLLED_BACK

    def test_rollback_completed_fails(self, setup_rollout_env):
        """测试 completed 状态不能回滚。"""
        env = setup_rollout_env
        start_rollout(
            change_path=env["change_path"],
            strategy="full",
            rollout_config_path="config/rollout-policy.yaml",
            output_dir=env["output_dir"],
        )
        promote_rollout(
            change_id=env["change_id"],
            change_dir=env["change_dir"],
            output_dir=env["output_dir"],
            force=True,
        )
        with pytest.raises(ValueError, match="不允许的状态转换"):
            rollback_rollout(
                change_id=env["change_id"],
                reason="test",
                change_dir=env["change_dir"],
                output_dir=env["output_dir"],
            )

    def test_rollback_not_found(self, setup_rollout_env):
        """测试回滚不存在的变更。"""
        with pytest.raises(ValueError, match="未找到灰度发布记录"):
            rollback_rollout(
                change_id="nonexistent",
                reason="test",
                change_dir=setup_rollout_env["change_dir"],
                output_dir=setup_rollout_env["output_dir"],
            )


# ═══════════════════════════════════════════════════════════════════════════════
# 9. 活跃灰度发布列表
# ═══════════════════════════════════════════════════════════════════════════════


class TestListActiveRollouts:
    """测试活跃灰度发布列表功能。"""

    def test_list_active_empty(self, temp_dir):
        """测试没有活跃灰度发布。"""
        active = list_active_rollouts(
            change_dir=temp_dir,
            output_dir=temp_dir,
        )
        assert active == []

    def test_list_active_single(self, setup_rollout_env):
        """测试单个活跃灰度发布。"""
        env = setup_rollout_env
        start_rollout(
            change_path=env["change_path"],
            strategy="canary",
            rollout_config_path="config/rollout-policy.yaml",
            output_dir=env["output_dir"],
        )
        active = list_active_rollouts(
            change_dir=env["change_dir"],
            output_dir=env["output_dir"],
        )
        assert len(active) == 1
        assert active[0]["change_id"] == env["change_id"]
        assert active[0]["status"] == STATUS_CANARY

    def test_list_active_multiple(self, setup_rollout_env, sample_candidate_change):
        """测试多个活跃灰度发布。"""
        env = setup_rollout_env

        # 启动第一个
        start_rollout(
            change_path=env["change_path"],
            strategy="canary",
            rollout_config_path="config/rollout-policy.yaml",
            output_dir=env["output_dir"],
        )

        # 创建第二个候选变更
        change2 = sample_candidate_change.copy()
        change2["change_id"] = f"change_{uuid.uuid4().hex[:8]}"
        change2_path = os.path.join(env["change_dir"], f"{change2['change_id']}.json")
        _write_json(change2_path, change2)

        # 启动第二个
        start_rollout(
            change_path=change2_path,
            strategy="full",
            rollout_config_path="config/rollout-policy.yaml",
            output_dir=env["output_dir"],
        )

        active = list_active_rollouts(
            change_dir=env["change_dir"],
            output_dir=env["output_dir"],
        )
        assert len(active) == 2

    def test_list_active_excludes_completed(self, setup_rollout_env):
        """测试 completed 状态不被列为活跃。"""
        env = setup_rollout_env
        start_rollout(
            change_path=env["change_path"],
            strategy="full",
            rollout_config_path="config/rollout-policy.yaml",
            output_dir=env["output_dir"],
        )
        promote_rollout(
            change_id=env["change_id"],
            change_dir=env["change_dir"],
            output_dir=env["output_dir"],
            force=True,
        )
        active = list_active_rollouts(
            change_dir=env["change_dir"],
            output_dir=env["output_dir"],
        )
        assert len(active) == 0

    def test_list_active_excludes_rolled_back(self, setup_rollout_env):
        """测试 rolled_back 状态不被列为活跃。"""
        env = setup_rollout_env
        start_rollout(
            change_path=env["change_path"],
            strategy="canary",
            rollout_config_path="config/rollout-policy.yaml",
            output_dir=env["output_dir"],
        )
        rollback_rollout(
            change_id=env["change_id"],
            reason="test",
            change_dir=env["change_dir"],
            output_dir=env["output_dir"],
        )
        active = list_active_rollouts(
            change_dir=env["change_dir"],
            output_dir=env["output_dir"],
        )
        assert len(active) == 0


# ═══════════════════════════════════════════════════════════════════════════════
# 10. 回滚条件检查
# ═══════════════════════════════════════════════════════════════════════════════


class TestCheckRollbackConditions:
    """测试回滚条件检查功能。"""

    def test_no_rollback_needed(self, setup_rollout_env, sample_regression_report):
        """测试不需要回滚。"""
        env = setup_rollout_env
        start_rollout(
            change_path=env["change_path"],
            strategy="canary",
            rollout_config_path="config/rollout-policy.yaml",
            output_dir=env["output_dir"],
        )
        result = check_rollback_conditions(
            change_id=env["change_id"],
            regression_report=sample_regression_report,
            change_dir=env["change_dir"],
            output_dir=env["output_dir"],
        )
        assert result["should_rollback"] is False
        assert len(result["triggered_conditions"]) == 0
        assert "overall_score" in result["details"]

    def test_rollback_needed_score_drop(self, setup_rollout_env, sample_regression_report):
        """测试综合评分下降触发回滚。"""
        env = setup_rollout_env
        start_rollout(
            change_path=env["change_path"],
            strategy="canary",
            rollout_config_path="config/rollout-policy.yaml",
            output_dir=env["output_dir"],
        )
        # 修改回归报告使综合评分大幅下降
        report = sample_regression_report.copy()
        for dim in report["summary"]["dimensions"]:
            report["summary"]["dimensions"][dim]["baseline"] = 0.90
            report["summary"]["dimensions"][dim]["patched"] = 0.50

        result = check_rollback_conditions(
            change_id=env["change_id"],
            regression_report=report,
            change_dir=env["change_dir"],
            output_dir=env["output_dir"],
        )
        assert result["should_rollback"] is True
        assert len(result["triggered_conditions"]) > 0

    def test_rollback_needed_high_risk_miss(self, setup_rollout_env, sample_regression_report):
        """测试高风险漏检率上升触发回滚。"""
        env = setup_rollout_env
        start_rollout(
            change_path=env["change_path"],
            strategy="canary",
            rollout_config_path="config/rollout-policy.yaml",
            output_dir=env["output_dir"],
        )
        # 修改回归报告使高风险漏检率大幅上升
        report = sample_regression_report.copy()
        report["summary"]["dimensions"]["high_risk_miss_rate"]["baseline"] = 0.05
        report["summary"]["dimensions"]["high_risk_miss_rate"]["patched"] = 0.50

        result = check_rollback_conditions(
            change_id=env["change_id"],
            regression_report=report,
            change_dir=env["change_dir"],
            output_dir=env["output_dir"],
        )
        assert result["should_rollback"] is True
        assert any("高风险漏检率" in c for c in result["triggered_conditions"])

    def test_rollback_needed_human_modification(self, setup_rollout_env, sample_regression_report):
        """测试人工修改率上升触发回滚。"""
        env = setup_rollout_env
        start_rollout(
            change_path=env["change_path"],
            strategy="canary",
            rollout_config_path="config/rollout-policy.yaml",
            output_dir=env["output_dir"],
        )
        report = sample_regression_report.copy()
        report["summary"]["dimensions"]["human_modification_rate"]["baseline"] = 0.10
        report["summary"]["dimensions"]["human_modification_rate"]["patched"] = 0.50

        result = check_rollback_conditions(
            change_id=env["change_id"],
            regression_report=report,
            change_dir=env["change_dir"],
            output_dir=env["output_dir"],
        )
        assert result["should_rollback"] is True
        assert any("人工修改率" in c for c in result["triggered_conditions"])

    def test_check_rollback_with_direct_scores(self, setup_rollout_env):
        """测试直接传入分数检查回滚条件。"""
        env = setup_rollout_env
        start_rollout(
            change_path=env["change_path"],
            strategy="canary",
            rollout_config_path="config/rollout-policy.yaml",
            output_dir=env["output_dir"],
        )
        baseline = {m: 0.85 for m in DEFAULT_METRICS}
        patched = {m: 0.40 for m in DEFAULT_METRICS}

        result = check_rollback_conditions(
            change_id=env["change_id"],
            baseline_scores=baseline,
            patched_scores=patched,
            change_dir=env["change_dir"],
            output_dir=env["output_dir"],
        )
        assert result["should_rollback"] is True

    def test_check_rollback_no_scores(self, setup_rollout_env):
        """测试没有分数数据时不应回滚。"""
        env = setup_rollout_env
        start_rollout(
            change_path=env["change_path"],
            strategy="canary",
            rollout_config_path="config/rollout-policy.yaml",
            output_dir=env["output_dir"],
        )
        result = check_rollback_conditions(
            change_id=env["change_id"],
            change_dir=env["change_dir"],
            output_dir=env["output_dir"],
        )
        assert result["should_rollback"] is False
        assert "error" in result["details"]

    def test_check_rollback_records_check(self, setup_rollout_env, sample_regression_report):
        """测试回滚检查结果被记录。"""
        env = setup_rollout_env
        start_rollout(
            change_path=env["change_path"],
            strategy="canary",
            rollout_config_path="config/rollout-policy.yaml",
            output_dir=env["output_dir"],
        )
        check_rollback_conditions(
            change_id=env["change_id"],
            regression_report=sample_regression_report,
            change_dir=env["change_dir"],
            output_dir=env["output_dir"],
        )
        # 重新加载记录
        record_path = os.path.join(env["output_dir"], f"{env['change_id']}_rollout.json")
        record = _load_json(record_path)
        assert len(record["rollback_checks"]) == 1
        assert record["rollback_checks"][0]["should_rollback"] is False


# ═══════════════════════════════════════════════════════════════════════════════
# 11. 指标快照记录
# ═══════════════════════════════════════════════════════════════════════════════


class TestRecordMetricsSnapshot:
    """测试指标快照记录功能。"""

    def test_record_canary_snapshot(self, setup_rollout_env):
        """测试记录 canary 组指标快照。"""
        env = setup_rollout_env
        start_rollout(
            change_path=env["change_path"],
            strategy="canary",
            rollout_config_path="config/rollout-policy.yaml",
            output_dir=env["output_dir"],
        )
        scores = {m: 0.75 for m in DEFAULT_METRICS}
        record = record_metrics_snapshot(
            change_id=env["change_id"],
            scores=scores,
            group="canary",
            output_dir=env["output_dir"],
        )
        assert len(record["metrics_snapshots"]) == 1
        assert record["metrics_snapshots"][0]["group"] == "canary"
        assert record["metrics_snapshots"][0]["scores"] == scores

    def test_record_baseline_snapshot(self, setup_rollout_env):
        """测试记录 baseline 组指标快照。"""
        env = setup_rollout_env
        start_rollout(
            change_path=env["change_path"],
            strategy="canary",
            rollout_config_path="config/rollout-policy.yaml",
            output_dir=env["output_dir"],
        )
        scores = {m: 0.80 for m in DEFAULT_METRICS}
        record = record_metrics_snapshot(
            change_id=env["change_id"],
            scores=scores,
            group="baseline",
            output_dir=env["output_dir"],
        )
        assert record["metrics_snapshots"][0]["group"] == "baseline"

    def test_record_multiple_snapshots(self, setup_rollout_env):
        """测试记录多个指标快照。"""
        env = setup_rollout_env
        start_rollout(
            change_path=env["change_path"],
            strategy="canary",
            rollout_config_path="config/rollout-policy.yaml",
            output_dir=env["output_dir"],
        )
        for i in range(3):
            scores = {m: 0.70 + i * 0.05 for m in DEFAULT_METRICS}
            record_metrics_snapshot(
                change_id=env["change_id"],
                scores=scores,
                group="canary",
                output_dir=env["output_dir"],
            )
        record_path = os.path.join(env["output_dir"], f"{env['change_id']}_rollout.json")
        record = _load_json(record_path)
        assert len(record["metrics_snapshots"]) == 3

    def test_record_snapshot_not_found(self, setup_rollout_env):
        """测试记录不存在的灰度发布的快照。"""
        with pytest.raises(ValueError, match="未找到灰度发布记录"):
            record_metrics_snapshot(
                change_id="nonexistent",
                scores={},
                group="canary",
                output_dir=setup_rollout_env["output_dir"],
            )


# ═══════════════════════════════════════════════════════════════════════════════
# 12. 端到端灰度发布工作流
# ═══════════════════════════════════════════════════════════════════════════════


class TestEndToEndRolloutWorkflow:
    """测试完整的灰度发布工作流。"""

    def test_full_canary_workflow(self, setup_rollout_env, sample_regression_report):
        """测试完整的 canary 工作流: start → check → promote → completed。"""
        env = setup_rollout_env

        # Step 1: 启动 canary
        record = start_rollout(
            change_path=env["change_path"],
            strategy="canary",
            rollout_config_path="config/rollout-policy.yaml",
            output_dir=env["output_dir"],
        )
        assert record["status"] == STATUS_CANARY

        # Step 2: 检查回滚条件（不应触发）
        result = check_rollback_conditions(
            change_id=env["change_id"],
            regression_report=sample_regression_report,
            change_dir=env["change_dir"],
            output_dir=env["output_dir"],
        )
        assert result["should_rollback"] is False

        # Step 3: 记录指标快照
        scores = {m: 0.78 for m in DEFAULT_METRICS}
        record_metrics_snapshot(
            change_id=env["change_id"],
            scores=scores,
            group="canary",
            output_dir=env["output_dir"],
        )

        # Step 4: 晋升到 full
        record = promote_rollout(
            change_id=env["change_id"],
            change_dir=env["change_dir"],
            output_dir=env["output_dir"],
            force=True,
        )
        assert record["status"] == STATUS_FULL

        # Step 5: 晋升到 completed
        record = promote_rollout(
            change_id=env["change_id"],
            change_dir=env["change_dir"],
            output_dir=env["output_dir"],
            force=True,
        )
        assert record["status"] == STATUS_COMPLETED

        # Step 6: 验证最终状态
        status = get_rollout_status(
            change_id=env["change_id"],
            change_dir=env["change_dir"],
            output_dir=env["output_dir"],
        )
        assert status["status"] == STATUS_COMPLETED

    def test_full_rollback_workflow(self, setup_rollout_env):
        """测试完整的回滚工作流: start → rollback。"""
        env = setup_rollout_env

        # Step 1: 启动 canary
        record = start_rollout(
            change_path=env["change_path"],
            strategy="canary",
            rollout_config_path="config/rollout-policy.yaml",
            output_dir=env["output_dir"],
        )
        assert record["status"] == STATUS_CANARY

        # Step 2: 回滚
        record = rollback_rollout(
            change_id=env["change_id"],
            reason="测试回滚",
            change_dir=env["change_dir"],
            output_dir=env["output_dir"],
        )
        assert record["status"] == STATUS_ROLLED_BACK

        # Step 3: 验证最终状态
        status = get_rollout_status(
            change_id=env["change_id"],
            change_dir=env["change_dir"],
            output_dir=env["output_dir"],
        )
        assert status["status"] == STATUS_ROLLED_BACK

        # Step 4: 验证不再活跃
        active = list_active_rollouts(
            change_dir=env["change_dir"],
            output_dir=env["output_dir"],
        )
        assert len(active) == 0

    def test_direct_full_workflow(self, setup_rollout_env):
        """测试直接全量发布工作流: start(full) → completed。"""
        env = setup_rollout_env

        # Step 1: 直接启动 full
        record = start_rollout(
            change_path=env["change_path"],
            strategy="full",
            rollout_config_path="config/rollout-policy.yaml",
            output_dir=env["output_dir"],
        )
        assert record["status"] == STATUS_FULL

        # Step 2: 晋升到 completed
        record = promote_rollout(
            change_id=env["change_id"],
            change_dir=env["change_dir"],
            output_dir=env["output_dir"],
            force=True,
        )
        assert record["status"] == STATUS_COMPLETED

    def test_workflow_with_metrics_tracking(self, setup_rollout_env):
        """测试带指标追踪的完整工作流。"""
        env = setup_rollout_env

        # 启动 canary
        start_rollout(
            change_path=env["change_path"],
            strategy="canary",
            rollout_config_path="config/rollout-policy.yaml",
            output_dir=env["output_dir"],
        )

        # 记录多组指标快照
        for day in range(3):
            scores = {m: 0.75 + day * 0.02 for m in DEFAULT_METRICS}
            record_metrics_snapshot(
                change_id=env["change_id"],
                scores=scores,
                group="canary",
                output_dir=env["output_dir"],
            )
            # 同时记录 baseline
            baseline_scores = {m: 0.73 for m in DEFAULT_METRICS}
            record_metrics_snapshot(
                change_id=env["change_id"],
                scores=baseline_scores,
                group="baseline",
                output_dir=env["output_dir"],
            )

        # 验证快照数量
        record_path = os.path.join(env["output_dir"], f"{env['change_id']}_rollout.json")
        record = _load_json(record_path)
        assert len(record["metrics_snapshots"]) == 6  # 3 canary + 3 baseline

    def test_workflow_state_persistence(self, setup_rollout_env):
        """测试工作流状态持久化。"""
        env = setup_rollout_env

        # 启动 canary
        start_rollout(
            change_path=env["change_path"],
            strategy="canary",
            rollout_config_path="config/rollout-policy.yaml",
            output_dir=env["output_dir"],
        )

        # 模拟重新加载（从文件读取）
        record_path = os.path.join(env["output_dir"], f"{env['change_id']}_rollout.json")
        loaded = _load_json(record_path)

        assert loaded["change_id"] == env["change_id"]
        assert loaded["status"] == STATUS_CANARY
        assert loaded["strategy"] == "canary"
        assert loaded["traffic_split"] == 0.1
        assert len(loaded["events"]) == 1
        assert loaded["events"][0]["event"] == "started"

        # 验证候选变更也被持久化
        change = _load_json(env["change_path"])
        assert change["rollout"]["status"] == STATUS_CANARY
        assert change["rollout"]["strategy"] == "canary"


# ═══════════════════════════════════════════════════════════════════════════════
# 13. 文件 I/O 辅助函数
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
