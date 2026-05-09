#!/usr/bin/env python3
"""
test_interruption_handler.py — Phase 9: 中断、补充、恢复与用户运行控制测试

测试覆盖:
  1. 中断事件创建 (create_interruption)
  2. Checkpoint 管理 (create_checkpoint / load_checkpoint)
  3. 结构化补丁提取 (extract_structured_patch)
  4. 恢复事件处理 (process_resume_event)
  5. 恢复条件验证 (validate_resume)
  6. 运行快照更新 (update_snapshot_with_interruption)
  7. 工作流状态辅助函数 (get_workflow_state_template, is_recoverable, get_recovery_path)
  8. CLI 接口
  9. 集成测试
"""

import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock

# 添加项目根目录到路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from scripts.interruption_handler import (
    # Constants
    INTERRUPTION_TYPES,
    MANDATORY_PAUSE_REASONS,
    WORKFLOW_STATUSES,
    VALIDATION_RESULTS,
    PATCH_TYPES,
    DEFAULT_CHECKPOINT_DIR,
    DEFAULT_INTERRUPTION_DIR,
    # File I/O
    load_json,
    save_json,
    resolve_path,
    # Checkpoint
    create_checkpoint,
    load_checkpoint,
    # Interruption
    create_interruption,
    # Structured Patch
    extract_structured_patch,
    # Resume
    process_resume_event,
    # Validation
    validate_resume,
    # Snapshot Update
    update_snapshot_with_interruption,
    # Helpers
    get_workflow_state_template,
    is_recoverable,
    get_recovery_path,
)

# ═══════════════════════════════════════════════════════════════
# Test Data — 使用工厂函数确保每个测试获得独立副本
# ═══════════════════════════════════════════════════════════════

def make_workflow_state(**overrides):
    """创建工作流状态测试数据。"""
    state = {
        "status": "running",
        "current_node": "confirm_intent",
        "checkpoint_id": "",
        "resume_node": "",
        "completed_steps": ["context_reading"],
        "total_steps": 5,
    }
    state.update(overrides)
    return state


def make_snapshot(**overrides):
    """创建运行快照测试数据。"""
    snapshot = {
        "run_id": "run_test_001",
        "workflow_id": "contract_review",
        "workflow_state": make_workflow_state(),
        "interruptions": [],
        "resume_events": [],
        "created_at": "2026-05-07T00:00:00+00:00",
        "updated_at": "2026-05-07T00:00:00+00:00",
    }
    snapshot.update(overrides)
    return snapshot


def make_interruption(**overrides):
    """创建中断事件测试数据。"""
    interruption = {
        "interruption_id": "int_test_001",
        "run_id": "run_test_001",
        "type": "workflow_pause",
        "pause_reason": "missing_required_input",
        "checkpoint_id": "cp_test_001",
        "node_id": "confirm_intent",
        "resume_condition": "用户补充缺失的输入信息",
        "cancel_condition": "用户放弃本次审查",
        "pending_questions": ["请提供合同文本", "请指定审查目标"],
        "status": "pending",
        "audit_fields": [
            "interruption_id", "type", "pause_reason",
            "checkpoint_id", "node_id",
            "resume_condition", "cancel_condition",
            "pending_questions", "created_at",
        ],
        "created_at": "2026-05-07T00:00:00+00:00",
    }
    interruption.update(overrides)
    return interruption


def make_resume_event(**overrides):
    """创建恢复事件测试数据。"""
    event = {
        "resume_event_id": "res_test_001",
        "interruption_id": "int_test_001",
        "run_id": "run_test_001",
        "source": "user",
        "user_supplement_summary": "用户补充了合同类型和审查目标",
        "structured_patch": {
            "intent_patch": {"goal": "用户补充了目标相关信息"},
            "context_patch": {"document": "用户补充了文档相关信息"},
            "approval_patch": {"decision": "approved", "reason": "用户包含关键词 '同意'"},
            "constraint_patch": {},
        },
        "validation_result": "pending",
        "created_at": "2026-05-07T00:00:00+00:00",
    }
    event.update(overrides)
    return event


def make_validation(**overrides):
    """创建验证结果测试数据。"""
    validation = {
        "accepted": True,
        "reason": "所有恢复条件均已满足",
        "requires_replan": False,
        "requires_regate": False,
        "checklist": {
            "supplement_answers_pause_reason": True,
            "intent_still_matches_workflow": True,
            "risk_level_recomputed": True,
            "context_load_plan_updated_if_needed": True,
            "approval_status_recorded": True,
        },
    }
    validation.update(overrides)
    return validation


# ═══════════════════════════════════════════════════════════════
# Tests
# ═══════════════════════════════════════════════════════════════

class TestConstants(unittest.TestCase):
    """测试常量定义。"""

    def test_interruption_types(self):
        """中断类型定义。"""
        expected = ["workflow_pause", "interrupted_by_user", "cancelled_by_user"]
        self.assertEqual(INTERRUPTION_TYPES, expected)

    def test_mandatory_pause_reasons(self):
        """强制中断原因定义。"""
        expected = [
            "missing_required_input",
            "high_risk_output",
            "requires_human_approval",
            "tool_permission_required",
            "schema_validation_failed",
            "context_budget_exceeded",
            "evidence_gap",
        ]
        self.assertEqual(MANDATORY_PAUSE_REASONS, expected)

    def test_workflow_statuses(self):
        """工作流状态定义。"""
        expected = [
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
        self.assertEqual(WORKFLOW_STATUSES, expected)

    def test_validation_results(self):
        """验证结果定义。"""
        expected = ["accepted", "rejected", "requires_more_information"]
        self.assertEqual(VALIDATION_RESULTS, expected)

    def test_patch_types(self):
        """补丁类型定义。"""
        expected = ["intent_patch", "context_patch", "approval_patch", "constraint_patch"]
        self.assertEqual(PATCH_TYPES, expected)

    def test_default_dirs(self):
        """默认目录定义。"""
        self.assertEqual(DEFAULT_CHECKPOINT_DIR, "runtime/checkpoints")
        self.assertEqual(DEFAULT_INTERRUPTION_DIR, "runtime/interruptions")


class TestFileIO(unittest.TestCase):
    """测试文件 I/O 辅助函数。"""

    def test_save_and_load_json(self):
        """save_json 和 load_json 往返。"""
        data = {"key": "value", "number": 42}
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            tmp_path = f.name
        try:
            save_json(data, tmp_path)
            loaded = load_json(tmp_path)
            self.assertEqual(loaded, data)
        finally:
            os.unlink(tmp_path)

    def test_save_json_creates_directory(self):
        """save_json 自动创建目录。"""
        data = {"test": True}
        with tempfile.TemporaryDirectory() as tmpdir:
            nested_path = os.path.join(tmpdir, "nested", "dir", "test.json")
            save_json(data, nested_path)
            self.assertTrue(os.path.exists(nested_path))
            loaded = load_json(nested_path)
            self.assertEqual(loaded, data)

    def test_load_json_not_found(self):
        """load_json 文件不存在时抛出异常。"""
        with self.assertRaises(FileNotFoundError):
            load_json("/tmp/nonexistent_file_12345.json")

    def test_resolve_path_absolute(self):
        """resolve_path 对绝对路径直接返回。"""
        result = resolve_path("/absolute/path")
        self.assertEqual(result, "/absolute/path")

    def test_resolve_path_relative(self):
        """resolve_path 对相对路径拼接项目根目录。"""
        result = resolve_path("config/interruption-policy.yaml")
        self.assertTrue(result.endswith("config/interruption-policy.yaml"))
        self.assertTrue(os.path.isabs(result))


class TestCheckpoint(unittest.TestCase):
    """测试 Checkpoint 管理。"""

    def test_create_checkpoint(self):
        """创建 Checkpoint。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            ws = make_workflow_state()
            checkpoint = create_checkpoint(
                run_id="run_test_001",
                node_id="confirm_intent",
                workflow_state=ws,
                checkpoint_dir=tmpdir,
            )

            self.assertIn("checkpoint_id", checkpoint)
            self.assertTrue(checkpoint["checkpoint_id"].startswith("cp_"))
            self.assertEqual(checkpoint["run_id"], "run_test_001")
            self.assertEqual(checkpoint["node_id"], "confirm_intent")
            self.assertEqual(checkpoint["workflow_state"], ws)
            self.assertIn("created_at", checkpoint)

            # 验证文件已保存
            cp_path = os.path.join(tmpdir, f"{checkpoint['checkpoint_id']}.json")
            self.assertTrue(os.path.exists(cp_path))

    def test_create_checkpoint_with_context_plan(self):
        """创建带上下文加载计划的 Checkpoint。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            context_plan = {"layers": [], "context_budget": {}}
            ws = make_workflow_state()
            checkpoint = create_checkpoint(
                run_id="run_test_001",
                node_id="confirm_intent",
                workflow_state=ws,
                context_load_plan=context_plan,
                checkpoint_dir=tmpdir,
            )

            self.assertEqual(checkpoint["context_load_plan"], context_plan)

    def test_load_checkpoint(self):
        """加载 Checkpoint。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            # 先创建
            ws = make_workflow_state()
            checkpoint = create_checkpoint(
                run_id="run_test_001",
                node_id="confirm_intent",
                workflow_state=ws,
                checkpoint_dir=tmpdir,
            )

            # 再加载
            loaded = load_checkpoint(checkpoint["checkpoint_id"], checkpoint_dir=tmpdir)
            self.assertEqual(loaded["checkpoint_id"], checkpoint["checkpoint_id"])
            self.assertEqual(loaded["run_id"], "run_test_001")
            self.assertEqual(loaded["node_id"], "confirm_intent")

    def test_load_checkpoint_not_found(self):
        """加载不存在的 Checkpoint 抛出异常。"""
        with self.assertRaises(FileNotFoundError):
            load_checkpoint("cp_nonexistent", checkpoint_dir="/tmp/nonexistent_dir")


class TestInterruptionCreation(unittest.TestCase):
    """测试中断事件创建。"""

    def test_create_interruption_workflow_pause(self):
        """创建 workflow_pause 类型中断。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            interruption = create_interruption(
                run_id="run_test_001",
                interruption_type="workflow_pause",
                pause_reason="missing_required_input",
                checkpoint_id="cp_test_001",
                node_id="confirm_intent",
                interruption_dir=tmpdir,
            )

            self.assertIn("interruption_id", interruption)
            self.assertTrue(interruption["interruption_id"].startswith("int_"))
            self.assertEqual(interruption["run_id"], "run_test_001")
            self.assertEqual(interruption["type"], "workflow_pause")
            self.assertEqual(interruption["pause_reason"], "missing_required_input")
            self.assertEqual(interruption["checkpoint_id"], "cp_test_001")
            self.assertEqual(interruption["node_id"], "confirm_intent")
            self.assertEqual(interruption["status"], "pending")
            self.assertIn("created_at", interruption)

    def test_create_interruption_interrupted_by_user(self):
        """创建 interrupted_by_user 类型中断。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            interruption = create_interruption(
                run_id="run_test_001",
                interruption_type="interrupted_by_user",
                pause_reason="requires_human_approval",
                checkpoint_id="cp_test_001",
                interruption_dir=tmpdir,
            )

            self.assertEqual(interruption["type"], "interrupted_by_user")

    def test_create_interruption_cancelled_by_user(self):
        """创建 cancelled_by_user 类型中断。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            interruption = create_interruption(
                run_id="run_test_001",
                interruption_type="cancelled_by_user",
                pause_reason="requires_human_approval",
                checkpoint_id="cp_test_001",
                interruption_dir=tmpdir,
            )

            self.assertEqual(interruption["type"], "cancelled_by_user")

    def test_create_interruption_invalid_type(self):
        """无效中断类型抛出异常。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            with self.assertRaises(ValueError):
                create_interruption(
                    run_id="run_test_001",
                    interruption_type="invalid_type",
                    pause_reason="missing_required_input",
                    checkpoint_id="cp_test_001",
                    interruption_dir=tmpdir,
                )

    def test_create_interruption_with_pending_questions(self):
        """创建带待回答问题的中断。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            questions = ["请提供合同文本", "请指定审查目标"]
            interruption = create_interruption(
                run_id="run_test_001",
                interruption_type="workflow_pause",
                pause_reason="missing_required_input",
                checkpoint_id="cp_test_001",
                node_id="confirm_intent",
                pending_questions=questions,
                interruption_dir=tmpdir,
            )

            self.assertEqual(interruption["pending_questions"], questions)

    def test_create_interruption_with_resume_cancel_conditions(self):
        """创建带恢复/取消条件的中断。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            interruption = create_interruption(
                run_id="run_test_001",
                interruption_type="workflow_pause",
                pause_reason="missing_required_input",
                checkpoint_id="cp_test_001",
                resume_condition="用户补充了缺失的输入信息",
                cancel_condition="用户放弃本次审查",
                interruption_dir=tmpdir,
            )

            self.assertEqual(interruption["resume_condition"], "用户补充了缺失的输入信息")
            self.assertEqual(interruption["cancel_condition"], "用户放弃本次审查")

    def test_create_interruption_audit_fields(self):
        """中断事件包含审计字段。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            interruption = create_interruption(
                run_id="run_test_001",
                interruption_type="workflow_pause",
                pause_reason="missing_required_input",
                checkpoint_id="cp_test_001",
                interruption_dir=tmpdir,
            )

            self.assertIn("audit_fields", interruption)
            self.assertIn("interruption_id", interruption["audit_fields"])
            self.assertIn("type", interruption["audit_fields"])
            self.assertIn("pause_reason", interruption["audit_fields"])


class TestStructuredPatch(unittest.TestCase):
    """测试结构化补丁提取。"""

    def test_extract_structured_patch_intent(self):
        """提取意图补丁。"""
        supplement = "用户补充了行业和地区信息，目标改为验证新能源充电业务"
        patch = extract_structured_patch(supplement, make_interruption())

        self.assertIn("intent_patch", patch)
        self.assertIn("industry", patch["intent_patch"])
        self.assertIn("goal", patch["intent_patch"])

    def test_extract_structured_patch_context(self):
        """提取上下文补丁。"""
        supplement = "请参考以下文档和资料"
        patch = extract_structured_patch(supplement, make_interruption())

        self.assertIn("context_patch", patch)
        self.assertIn("document", patch["context_patch"])
        self.assertIn("reference", patch["context_patch"])

    def test_extract_structured_patch_approval_approved(self):
        """提取审批补丁 — 批准。"""
        supplement = "我同意继续执行"
        patch = extract_structured_patch(supplement, make_interruption())

        self.assertIn("approval_patch", patch)
        self.assertEqual(patch["approval_patch"]["decision"], "approved")

    def test_extract_structured_patch_approval_rejected(self):
        """提取审批补丁 — 拒绝。"""
        supplement = "我不同意，请取消"
        patch = extract_structured_patch(supplement, make_interruption())

        self.assertIn("approval_patch", patch)
        self.assertEqual(patch["approval_patch"]["decision"], "rejected")

    def test_extract_structured_patch_approval_modified(self):
        """提取审批补丁 — 修改。"""
        supplement = "请修改输出格式"
        patch = extract_structured_patch(supplement, make_interruption())

        self.assertIn("approval_patch", patch)
        self.assertEqual(patch["approval_patch"]["decision"], "modified")

    def test_extract_structured_patch_constraint(self):
        """提取约束补丁。"""
        supplement = "必须遵守数据隐私限制，不能包含个人信息"
        patch = extract_structured_patch(supplement, make_interruption())

        self.assertIn("constraint_patch", patch)
        self.assertIn("requirement", patch["constraint_patch"])
        self.assertIn("forbidden", patch["constraint_patch"])

    def test_extract_structured_patch_empty(self):
        """空补充内容返回空补丁。"""
        patch = extract_structured_patch("", make_interruption())

        self.assertEqual(patch["intent_patch"], {})
        self.assertEqual(patch["context_patch"], {})
        self.assertEqual(patch["approval_patch"], {})
        self.assertEqual(patch["constraint_patch"], {})

    def test_extract_structured_patch_supplement_summary(self):
        """补丁包含补充摘要。"""
        supplement = "用户补充了合同类型和审查目标"
        patch = extract_structured_patch(supplement, make_interruption())

        self.assertIn("_supplement_summary", patch)
        self.assertEqual(patch["_supplement_summary"], supplement)


class TestResumeEvent(unittest.TestCase):
    """测试恢复事件处理。"""

    def test_process_resume_event(self):
        """处理恢复事件。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            interruption = make_interruption(status="pending")

            resume_event = process_resume_event(
                interruption=interruption,
                user_supplement="用户补充了合同类型和审查目标",
                interruption_dir=tmpdir,
            )

            self.assertIn("resume_event_id", resume_event)
            self.assertTrue(resume_event["resume_event_id"].startswith("res_"))
            self.assertEqual(resume_event["interruption_id"], "int_test_001")
            self.assertEqual(resume_event["run_id"], "run_test_001")
            self.assertEqual(resume_event["source"], "user")
            self.assertIn("structured_patch", resume_event)
            self.assertEqual(resume_event["validation_result"], "pending")

    def test_process_resume_event_not_pending(self):
        """非 pending 状态的中断事件抛出异常。"""
        interruption = make_interruption(status="completed")

        with self.assertRaises(ValueError):
            process_resume_event(
                interruption=interruption,
                user_supplement="补充内容",
            )

    def test_process_resume_event_cancelled(self):
        """已取消的中断事件抛出异常。"""
        interruption = make_interruption(status="pending", type="cancelled_by_user")

        with self.assertRaises(ValueError):
            process_resume_event(
                interruption=interruption,
                user_supplement="补充内容",
            )

    def test_process_resume_event_saves_file(self):
        """恢复事件保存到文件。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            interruption = make_interruption(status="pending")

            resume_event = process_resume_event(
                interruption=interruption,
                user_supplement="补充内容",
                interruption_dir=tmpdir,
            )

            res_path = os.path.join(tmpdir, f"{resume_event['resume_event_id']}.json")
            self.assertTrue(os.path.exists(res_path))


class TestResumeValidation(unittest.TestCase):
    """测试恢复条件验证。"""

    def test_validate_resume_accepted(self):
        """验证通过。"""
        interruption = make_interruption(pause_reason="missing_required_input")
        resume_event = make_resume_event()

        validation = validate_resume(interruption, resume_event)

        self.assertTrue(validation["accepted"])
        self.assertIn("reason", validation)
        self.assertIn("checklist", validation)

    def test_validate_resume_missing_input_with_patch(self):
        """missing_required_input 且有补丁内容时通过。"""
        interruption = make_interruption(pause_reason="missing_required_input")
        resume_event = make_resume_event()

        validation = validate_resume(interruption, resume_event)

        self.assertTrue(validation["accepted"])
        self.assertTrue(validation["checklist"]["supplement_answers_pause_reason"])

    def test_validate_resume_missing_input_without_patch(self):
        """missing_required_input 但无补丁内容时拒绝。"""
        interruption = make_interruption(pause_reason="missing_required_input")
        resume_event = make_resume_event()
        resume_event["structured_patch"] = {
            "intent_patch": {},
            "context_patch": {},
            "approval_patch": {},
            "constraint_patch": {},
        }

        validation = validate_resume(interruption, resume_event)

        self.assertFalse(validation["accepted"])

    def test_validate_resume_human_approval_approved(self):
        """requires_human_approval 且已批准时通过。"""
        interruption = make_interruption(pause_reason="requires_human_approval")
        resume_event = make_resume_event()

        validation = validate_resume(interruption, resume_event)

        self.assertTrue(validation["accepted"])
        self.assertTrue(validation["checklist"]["supplement_answers_pause_reason"])
        self.assertTrue(validation["checklist"]["approval_status_recorded"])

    def test_validate_resume_human_approval_rejected(self):
        """requires_human_approval 且已拒绝时通过 (拒绝也是有效决策)。"""
        interruption = make_interruption(pause_reason="requires_human_approval")
        resume_event = make_resume_event()
        resume_event["structured_patch"]["approval_patch"] = {
            "decision": "rejected",
            "reason": "用户包含关键词 '拒绝'",
        }

        validation = validate_resume(interruption, resume_event)

        self.assertTrue(validation["accepted"])

    def test_validate_resume_human_approval_no_decision(self):
        """requires_human_approval 但无决策时拒绝。"""
        interruption = make_interruption(pause_reason="requires_human_approval")
        resume_event = make_resume_event()
        resume_event["structured_patch"]["approval_patch"] = {}

        validation = validate_resume(interruption, resume_event)

        self.assertFalse(validation["accepted"])

    def test_validate_resume_intent_changed(self):
        """意图变化时触发 replan 和 regate。"""
        interruption = make_interruption()
        resume_event = make_resume_event()
        resume_event["structured_patch"]["intent_patch"] = {
            "industry": "用户补充了行业相关信息",
            "goal": "用户补充了目标相关信息",
        }

        validation = validate_resume(interruption, resume_event)

        self.assertTrue(validation["accepted"])
        self.assertFalse(validation["checklist"]["intent_still_matches_workflow"])
        self.assertTrue(validation["requires_replan"])
        self.assertTrue(validation["requires_regate"])

    def test_validate_resume_high_risk_triggers_regate(self):
        """高风险输出触发 regate。"""
        interruption = make_interruption(pause_reason="high_risk_output")
        resume_event = make_resume_event()

        validation = validate_resume(interruption, resume_event)

        self.assertTrue(validation["requires_regate"])

    def test_validate_resume_checklist_structure(self):
        """验证清单包含所有必需检查项。"""
        interruption = make_interruption()
        resume_event = make_resume_event()

        validation = validate_resume(interruption, resume_event)

        expected_checks = [
            "supplement_answers_pause_reason",
            "intent_still_matches_workflow",
            "risk_level_recomputed",
            "context_load_plan_updated_if_needed",
            "approval_status_recorded",
        ]
        for check in expected_checks:
            self.assertIn(check, validation["checklist"])


class TestSnapshotUpdate(unittest.TestCase):
    """测试运行快照更新。"""

    def test_update_snapshot_with_interruption(self):
        """更新快照记录中断事件。"""
        snapshot = make_snapshot()
        interruption = make_interruption()

        updated = update_snapshot_with_interruption(
            snapshot=snapshot,
            interruption=interruption,
        )

        # 检查状态更新
        self.assertEqual(updated["workflow_state"]["status"], "workflow_pause")
        self.assertEqual(updated["workflow_state"]["current_node"], "confirm_intent")
        self.assertEqual(updated["workflow_state"]["checkpoint_id"], "cp_test_001")

        # 检查中断事件追加
        self.assertEqual(len(updated["interruptions"]), 1)
        self.assertEqual(updated["interruptions"][0]["interruption_id"], "int_test_001")

        # 检查时间戳更新
        self.assertIn("updated_at", updated)

    def test_update_snapshot_interrupted_by_user(self):
        """interrupted_by_user 类型中断。"""
        snapshot = make_snapshot()
        interruption = make_interruption(type="interrupted_by_user")

        updated = update_snapshot_with_interruption(
            snapshot=snapshot,
            interruption=interruption,
        )

        self.assertEqual(updated["workflow_state"]["status"], "interrupted_by_user")

    def test_update_snapshot_cancelled_by_user(self):
        """cancelled_by_user 类型中断清除 resume_node。"""
        snapshot = make_snapshot()
        interruption = make_interruption(type="cancelled_by_user")

        updated = update_snapshot_with_interruption(
            snapshot=snapshot,
            interruption=interruption,
        )

        self.assertEqual(updated["workflow_state"]["status"], "cancelled_by_user")
        self.assertEqual(updated["workflow_state"]["resume_node"], "")

    def test_update_snapshot_with_resume_event(self):
        """更新快照记录恢复事件。"""
        snapshot = make_snapshot()
        interruption = make_interruption()
        resume_event = make_resume_event()

        updated = update_snapshot_with_interruption(
            snapshot=snapshot,
            interruption=interruption,
            resume_event=resume_event,
        )

        self.assertEqual(len(updated["resume_events"]), 1)
        self.assertEqual(updated["resume_events"][0]["resume_event_id"], "res_test_001")

    def test_update_snapshot_with_validation_accepted(self):
        """验证通过后更新状态。"""
        snapshot = make_snapshot()
        interruption = make_interruption()
        validation = make_validation()

        updated = update_snapshot_with_interruption(
            snapshot=snapshot,
            interruption=interruption,
            validation=validation,
        )

        self.assertEqual(updated["workflow_state"]["status"], "running")
        self.assertEqual(updated["workflow_state"]["current_node"], "confirm_intent")

    def test_update_snapshot_with_validation_requires_regate(self):
        """需要退回门禁时更新状态。"""
        snapshot = make_snapshot()
        interruption = make_interruption()
        validation = make_validation(requires_regate=True)

        updated = update_snapshot_with_interruption(
            snapshot=snapshot,
            interruption=interruption,
            validation=validation,
        )

        self.assertEqual(updated["workflow_state"]["status"], "context_intent_pending")
        self.assertEqual(updated["workflow_state"]["current_node"], "context_reading")

    def test_update_snapshot_with_validation_requires_replan(self):
        """需要重新规划时更新状态。"""
        snapshot = make_snapshot()
        interruption = make_interruption()
        validation = make_validation(requires_replan=True, requires_regate=False)

        updated = update_snapshot_with_interruption(
            snapshot=snapshot,
            interruption=interruption,
            validation=validation,
        )

        self.assertEqual(updated["workflow_state"]["status"], "running")
        self.assertEqual(updated["workflow_state"]["current_node"], "context_planning")

    def test_update_snapshot_no_duplicate_interruptions(self):
        """避免重复添加中断事件。"""
        snapshot = make_snapshot()
        interruption = make_interruption()

        # 第一次添加
        updated = update_snapshot_with_interruption(
            snapshot=snapshot,
            interruption=interruption,
        )
        self.assertEqual(len(updated["interruptions"]), 1)

        # 第二次添加 (相同 ID)
        updated2 = update_snapshot_with_interruption(
            snapshot=updated,
            interruption=interruption,
        )
        self.assertEqual(len(updated2["interruptions"]), 1)


class TestWorkflowStateHelpers(unittest.TestCase):
    """测试工作流状态辅助函数。"""

    def test_get_workflow_state_template(self):
        """获取工作流状态模板。"""
        template = get_workflow_state_template()

        self.assertEqual(template["status"], "created")
        self.assertEqual(template["current_node"], "")
        self.assertEqual(template["checkpoint_id"], "")
        self.assertEqual(template["resume_node"], "")
        self.assertEqual(template["completed_steps"], [])
        self.assertEqual(template["total_steps"], 0)

    def test_is_recoverable_workflow_pause(self):
        """workflow_pause 可恢复。"""
        interruption = {"type": "workflow_pause"}
        self.assertTrue(is_recoverable(interruption))

    def test_is_recoverable_interrupted_by_user(self):
        """interrupted_by_user 可恢复。"""
        interruption = {"type": "interrupted_by_user"}
        self.assertTrue(is_recoverable(interruption))

    def test_is_recoverable_cancelled_by_user(self):
        """cancelled_by_user 不可恢复。"""
        interruption = {"type": "cancelled_by_user"}
        self.assertFalse(is_recoverable(interruption))

    def test_get_recovery_path_resume(self):
        """正常恢复路径。"""
        interruption = {"type": "workflow_pause"}
        validation = {
            "accepted": True,
            "requires_replan": False,
            "requires_regate": False,
        }
        self.assertEqual(get_recovery_path(interruption, validation), "resume")

    def test_get_recovery_path_replan(self):
        """需要重新规划。"""
        interruption = {"type": "workflow_pause"}
        validation = {
            "accepted": True,
            "requires_replan": True,
            "requires_regate": False,
        }
        self.assertEqual(get_recovery_path(interruption, validation), "replan")

    def test_get_recovery_path_regate(self):
        """需要退回门禁。"""
        interruption = {"type": "workflow_pause"}
        validation = {
            "accepted": True,
            "requires_replan": False,
            "requires_regate": True,
        }
        self.assertEqual(get_recovery_path(interruption, validation), "regate")

    def test_get_recovery_path_terminate_cancelled(self):
        """已取消的运行终止。"""
        interruption = {"type": "cancelled_by_user"}
        validation = {"accepted": True}
        self.assertEqual(get_recovery_path(interruption, validation), "terminate")

    def test_get_recovery_path_terminate_not_accepted(self):
        """验证未通过时终止。"""
        interruption = {"type": "workflow_pause"}
        validation = {"accepted": False}
        self.assertEqual(get_recovery_path(interruption, validation), "terminate")


class TestCLI(unittest.TestCase):
    """测试 CLI 接口。"""

    def test_cli_help(self):
        """CLI 帮助信息。"""
        from scripts.interruption_handler import main
        self.assertTrue(callable(main))

    def test_cli_subcommands_exist(self):
        """验证所有子命令在帮助文本中。"""
        import scripts.interruption_handler as ih
        self.assertTrue(hasattr(ih, "main"))


class TestIntegration(unittest.TestCase):
    """集成测试。"""

    def test_full_interruption_flow(self):
        """完整的中断-恢复流程。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            # 1. 创建 Checkpoint
            ws = make_workflow_state()
            checkpoint = create_checkpoint(
                run_id="run_integration_001",
                node_id="confirm_intent",
                workflow_state=ws,
                checkpoint_dir=tmpdir,
            )
            self.assertIn("checkpoint_id", checkpoint)

            # 2. 创建中断事件
            interruption = create_interruption(
                run_id="run_integration_001",
                interruption_type="workflow_pause",
                pause_reason="missing_required_input",
                checkpoint_id=checkpoint["checkpoint_id"],
                node_id="confirm_intent",
                pending_questions=["请提供合同文本"],
                interruption_dir=tmpdir,
            )
            self.assertEqual(interruption["status"], "pending")

            # 3. 处理恢复事件
            resume_event = process_resume_event(
                interruption=interruption,
                user_supplement="用户补充了合同类型和审查目标",
                interruption_dir=tmpdir,
            )
            self.assertIn("resume_event_id", resume_event)

            # 4. 验证恢复条件
            validation = validate_resume(interruption, resume_event)
            self.assertTrue(validation["accepted"])

            # 5. 更新快照
            snapshot = make_snapshot(run_id="run_integration_001")
            updated = update_snapshot_with_interruption(
                snapshot=snapshot,
                interruption=interruption,
                resume_event=resume_event,
                validation=validation,
            )

            # 6. 验证最终状态
            # 补充内容 "用户补充了合同类型和审查目标" 包含 "目标" 关键词，
            # 触发 intent_patch，导致 requires_regate=True，状态变为 context_intent_pending
            self.assertEqual(updated["workflow_state"]["status"], "context_intent_pending")
            self.assertEqual(len(updated["interruptions"]), 1)
            self.assertEqual(len(updated["resume_events"]), 1)


if __name__ == "__main__":
    unittest.main()
