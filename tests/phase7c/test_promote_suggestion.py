#!/usr/bin/env python3
"""
Phase 7c — promote_suggestion.py 自动化测试套件

覆盖全部 9 个核心函数：
  - _validate_report
  - _normalize_suggestion_target
  - promote_suggestion
  - promote_all_suggestions
  - approve_change
  - reject_change
  - validate_against_schema
  - list_pending_changes
  - find_change_file

运行:
  python -m pytest tests/phase7c/test_promote_suggestion.py -v
  python tests/phase7c/test_promote_suggestion.py  # 直接运行
"""

import json
import os
import sys
import tempfile
import unittest

# 确保可以从项目根目录 import
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

import scripts.promote_suggestion as ps


class TestValidateReport(unittest.TestCase):
    """_validate_report: 检查评估报告是否包含必要字段"""

    def test_valid_report(self):
        report = {"run_id": "test_001", "workflow_id": "test", "suggestions": []}
        self.assertTrue(ps._validate_report(report))

    def test_missing_suggestions(self):
        report = {"run_id": "test_001", "workflow_id": "test"}
        self.assertFalse(ps._validate_report(report))

    def test_missing_run_id(self):
        report = {"workflow_id": "test", "suggestions": []}
        self.assertFalse(ps._validate_report(report))

    def test_empty_dict(self):
        self.assertFalse(ps._validate_report({}))

    def test_suggestions_is_none(self):
        report = {"run_id": "test", "workflow_id": "test", "suggestions": None}
        self.assertTrue(ps._validate_report(report))  # 只有缺失才返回 False


class TestNormalizeSuggestionTarget(unittest.TestCase):
    """_normalize_suggestion_target: 将变体 target 归一化为标准值"""

    def test_exact_match(self):
        self.assertEqual(ps._normalize_suggestion_target("constraint_rules"), "constraint_rules")
        self.assertEqual(ps._normalize_suggestion_target("prompts"), "prompts")
        self.assertEqual(ps._normalize_suggestion_target("model_routing"), "model_routing")

    def test_case_insensitive(self):
        self.assertEqual(ps._normalize_suggestion_target("Constraint Rules"), "constraint_rules")
        self.assertEqual(ps._normalize_suggestion_target("PROMPTS"), "prompts")

    def test_spaces_to_underscores(self):
        self.assertEqual(ps._normalize_suggestion_target("workflow steps"), "workflow_steps")
        self.assertEqual(ps._normalize_suggestion_target("model routing"), "model_routing")
        self.assertEqual(ps._normalize_suggestion_target("  constraint rules  "), "constraint_rules")

    def test_dimension_mapping(self):
        self.assertEqual(ps._normalize_suggestion_target("citation_accuracy"), "retrieval_strategy")
        self.assertEqual(ps._normalize_suggestion_target("constraint_compliance"), "constraint_rules")
        self.assertEqual(ps._normalize_suggestion_target("format_compliance"), "output_templates")
        self.assertEqual(ps._normalize_suggestion_target("risk_detection"), "workflow_steps")
        self.assertEqual(ps._normalize_suggestion_target("human_modification_rate"), "prompts")
        self.assertEqual(ps._normalize_suggestion_target("output_adoption_rate"), "output_templates")
        self.assertEqual(ps._normalize_suggestion_target("high_risk_miss_rate"), "workflow_steps")
        self.assertEqual(ps._normalize_suggestion_target("cost_latency"), "model_routing")

    def test_unknown_target(self):
        self.assertEqual(ps._normalize_suggestion_target("unknown_target"), "unknown_target")


class TestPromoteSuggestion(unittest.TestCase):
    """promote_suggestion: 将单条 suggestion 提升为候选变更文件"""

    def setUp(self):
        self.sample_report = {
            "run_id": "run_sample_002",
            "workflow_id": "contract_review",
            "suggestions": [
                {
                    "target": "constraint_rules",
                    "recommendation": "Improve jurisdiction_awareness: add CN rules",
                    "priority": "medium",
                    "requires_human_approval": True,
                    "expected_impact": {
                        "affected_metrics": ["constraint_compliance"],
                        "estimated_improvement": 0.3,
                    },
                }
            ],
        }

    def test_create_change_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            report_path = os.path.join(tmpdir, "report.json")
            with open(report_path, "w") as f:
                json.dump(self.sample_report, f)

            output_dir = os.path.join(tmpdir, "changes")
            result = ps.promote_suggestion(
                self.sample_report, report_path,
                self.sample_report["suggestions"][0], 0, output_dir
            )
            self.assertIsNotNone(result)
            self.assertTrue(os.path.exists(result))

    def test_change_id_format(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            report_path = os.path.join(tmpdir, "report.json")
            with open(report_path, "w") as f:
                json.dump(self.sample_report, f)
            output_dir = os.path.join(tmpdir, "changes")
            result = ps.promote_suggestion(
                self.sample_report, report_path,
                self.sample_report["suggestions"][0], 0, output_dir
            )
            with open(result) as f:
                change = json.load(f)
            self.assertTrue(change["change_id"].startswith("change_"))
            self.assertEqual(len(change["change_id"]), 15)  # "change_" (7) + 8 hex

    def test_source_fields(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            report_path = os.path.join(tmpdir, "report.json")
            with open(report_path, "w") as f:
                json.dump(self.sample_report, f)
            output_dir = os.path.join(tmpdir, "changes")
            result = ps.promote_suggestion(
                self.sample_report, report_path,
                self.sample_report["suggestions"][0], 0, output_dir
            )
            with open(result) as f:
                change = json.load(f)
            self.assertEqual(change["source"]["run_id"], "run_sample_002")
            self.assertEqual(change["source"]["suggestion_index"], 0)
            self.assertTrue(change["source"]["report_path"].endswith("report.json"))

    def test_target_fields(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            report_path = os.path.join(tmpdir, "report.json")
            with open(report_path, "w") as f:
                json.dump(self.sample_report, f)
            output_dir = os.path.join(tmpdir, "changes")
            result = ps.promote_suggestion(
                self.sample_report, report_path,
                self.sample_report["suggestions"][0], 0, output_dir
            )
            with open(result) as f:
                change = json.load(f)
            self.assertEqual(change["target"]["component"], "constraint_rules")
            self.assertEqual(change["target"]["change_type"], "add_rule")

    def test_validation_defaults(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            report_path = os.path.join(tmpdir, "report.json")
            with open(report_path, "w") as f:
                json.dump(self.sample_report, f)
            output_dir = os.path.join(tmpdir, "changes")
            result = ps.promote_suggestion(
                self.sample_report, report_path,
                self.sample_report["suggestions"][0], 0, output_dir
            )
            with open(result) as f:
                change = json.load(f)
            self.assertEqual(change["validation"]["status"], "pending")
            self.assertIsNone(change["validation"]["sandbox_report"])
            self.assertIsNone(change["validation"]["regression_result"])

    def test_approval_defaults(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            report_path = os.path.join(tmpdir, "report.json")
            with open(report_path, "w") as f:
                json.dump(self.sample_report, f)
            output_dir = os.path.join(tmpdir, "changes")
            result = ps.promote_suggestion(
                self.sample_report, report_path,
                self.sample_report["suggestions"][0], 0, output_dir
            )
            with open(result) as f:
                change = json.load(f)
            self.assertTrue(change["approval"]["required"])
            self.assertIsNone(change["approval"]["approved_by"])
            self.assertIsNone(change["approval"]["approved_at"])
            self.assertIsNone(change["approval"]["review_notes"])

    def test_rollout_defaults(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            report_path = os.path.join(tmpdir, "report.json")
            with open(report_path, "w") as f:
                json.dump(self.sample_report, f)
            output_dir = os.path.join(tmpdir, "changes")
            result = ps.promote_suggestion(
                self.sample_report, report_path,
                self.sample_report["suggestions"][0], 0, output_dir
            )
            with open(result) as f:
                change = json.load(f)
            self.assertEqual(change["rollout"]["strategy"], "canary")
            self.assertEqual(change["rollout"]["traffic_split"], 0.1)
            self.assertEqual(change["rollout"]["status"], "pending")

    def test_diff_summary_includes_recommendation(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            report_path = os.path.join(tmpdir, "report.json")
            with open(report_path, "w") as f:
                json.dump(self.sample_report, f)
            output_dir = os.path.join(tmpdir, "changes")
            result = ps.promote_suggestion(
                self.sample_report, report_path,
                self.sample_report["suggestions"][0], 0, output_dir
            )
            with open(result) as f:
                change = json.load(f)
            self.assertIn("Improve jurisdiction_awareness", change["diff"]["summary"])

    def test_created_at_iso_format(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            report_path = os.path.join(tmpdir, "report.json")
            with open(report_path, "w") as f:
                json.dump(self.sample_report, f)
            output_dir = os.path.join(tmpdir, "changes")
            result = ps.promote_suggestion(
                self.sample_report, report_path,
                self.sample_report["suggestions"][0], 0, output_dir
            )
            with open(result) as f:
                change = json.load(f)
            # ISO format check: must contain T and Z or timezone offset
            self.assertIn("T", change["created_at"])

    def test_suggestion_without_expected_impact(self):
        simple_suggestion = {
            "target": "prompts",
            "recommendation": "Fix prompt wording",
            "priority": "high",
            "requires_human_approval": True,
        }
        simple_report = {
            "run_id": "simple",
            "workflow_id": "test",
            "suggestions": [simple_suggestion],
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            report_path = os.path.join(tmpdir, "report.json")
            with open(report_path, "w") as f:
                json.dump(simple_report, f)
            output_dir = os.path.join(tmpdir, "changes")
            result = ps.promote_suggestion(
                simple_report, report_path, simple_suggestion, 0, output_dir
            )
            with open(result) as f:
                change = json.load(f)
            self.assertEqual(change["diff"]["summary"], "Fix prompt wording")


class TestPromoteAllSuggestions(unittest.TestCase):
    """promote_all_suggestions: 从评估报告中提取所有建议"""

    def test_empty_suggestions(self):
        report = {"run_id": "empty", "workflow_id": "test", "suggestions": []}
        with tempfile.TemporaryDirectory() as tmpdir:
            report_path = os.path.join(tmpdir, "report.json")
            with open(report_path, "w") as f:
                json.dump(report, f)
            result = ps.promote_all_suggestions(report, report_path, tmpdir)
            self.assertEqual(result, [])

    def test_multiple_suggestions(self):
        report = {
            "run_id": "multi",
            "workflow_id": "test",
            "suggestions": [
                {"target": "prompts", "recommendation": "Fix A", "priority": "high",
                 "requires_human_approval": True},
                {"target": "constraint_rules", "recommendation": "Add B", "priority": "medium",
                 "requires_human_approval": True},
            ],
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            report_path = os.path.join(tmpdir, "report.json")
            with open(report_path, "w") as f:
                json.dump(report, f)
            result = ps.promote_all_suggestions(report, report_path, tmpdir)
            self.assertEqual(len(result), 2)
            for r in result:
                self.assertTrue(os.path.exists(r))

    def test_invalid_report(self):
        report = {"run_id": "invalid"}
        with tempfile.TemporaryDirectory() as tmpdir:
            report_path = os.path.join(tmpdir, "report.json")
            with open(report_path, "w") as f:
                json.dump(report, f)
            result = ps.promote_all_suggestions(report, report_path, tmpdir)
            self.assertEqual(result, [])


class TestApproveReject(unittest.TestCase):
    """approve_change / reject_change: 审核候选变更"""

    def setUp(self):
        self.sample_report = {
            "run_id": "r002",
            "workflow_id": "test",
            "suggestions": [
                {"target": "constraint_rules", "recommendation": "test rule",
                 "priority": "medium", "requires_human_approval": True}
            ],
        }

    def test_approve_change(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            report_path = os.path.join(tmpdir, "report.json")
            with open(report_path, "w") as f:
                json.dump(self.sample_report, f)
            change_path = ps.promote_suggestion(
                self.sample_report, report_path,
                self.sample_report["suggestions"][0], 0, tmpdir
            )
            self.assertTrue(ps.approve_change(change_path))
            with open(change_path) as f:
                change = json.load(f)
            self.assertEqual(change["validation"]["status"], "approved")
            self.assertEqual(change["approval"]["approved_by"], "cli_user")
            self.assertIsNotNone(change["approval"]["approved_at"])

    def test_reject_change(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            report_path = os.path.join(tmpdir, "report.json")
            with open(report_path, "w") as f:
                json.dump(self.sample_report, f)
            change_path = ps.promote_suggestion(
                self.sample_report, report_path,
                self.sample_report["suggestions"][0], 0, tmpdir
            )
            reason = "需要更多证据"
            self.assertTrue(ps.reject_change(change_path, reason=reason))
            with open(change_path) as f:
                change = json.load(f)
            self.assertEqual(change["validation"]["status"], "rejected")
            self.assertIn(reason, change["approval"]["review_notes"])

    def test_approve_nonexistent(self):
        self.assertFalse(ps.approve_change("/nonexistent/path.json"))

    def test_reject_nonexistent(self):
        self.assertFalse(ps.reject_change("/nonexistent/path.json"))


class TestValidateAgainstSchema(unittest.TestCase):
    """validate_against_schema: 对 candidate_change 做 Schema 合规校验"""

    def setUp(self):
        self.sample_report = {
            "run_id": "schema_test",
            "workflow_id": "test",
            "suggestions": [
                {"target": "model_routing", "recommendation": "Switch model",
                 "priority": "high", "requires_human_approval": True}
            ],
        }

    def test_valid_change(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            report_path = os.path.join(tmpdir, "report.json")
            with open(report_path, "w") as f:
                json.dump(self.sample_report, f)
            change_path = ps.promote_suggestion(
                self.sample_report, report_path,
                self.sample_report["suggestions"][0], 0, tmpdir
            )
            with open(change_path) as f:
                change = json.load(f)
            self.assertTrue(ps.validate_against_schema(change))

    def test_missing_change_id(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            report_path = os.path.join(tmpdir, "report.json")
            with open(report_path, "w") as f:
                json.dump(self.sample_report, f)
            change_path = ps.promote_suggestion(
                self.sample_report, report_path,
                self.sample_report["suggestions"][0], 0, tmpdir
            )
            with open(change_path) as f:
                change = json.load(f)
            del change["change_id"]
            self.assertFalse(ps.validate_against_schema(change))

    def test_missing_target_component(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            report_path = os.path.join(tmpdir, "report.json")
            with open(report_path, "w") as f:
                json.dump(self.sample_report, f)
            change_path = ps.promote_suggestion(
                self.sample_report, report_path,
                self.sample_report["suggestions"][0], 0, tmpdir
            )
            with open(change_path) as f:
                change = json.load(f)
            del change["target"]["component"]
            self.assertFalse(ps.validate_against_schema(change))


class TestListPendingChanges(unittest.TestCase):
    """list_pending_changes: 列出待审核的候选变更"""

    def test_empty_directory(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            self.assertEqual(ps.list_pending_changes(tmpdir), [])

    def test_nonexistent_directory(self):
        self.assertEqual(ps.list_pending_changes("/nonexistent_dir_12345"), [])

    def test_filters_non_json(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a non-JSON file
            with open(os.path.join(tmpdir, "readme.md"), "w") as f:
                f.write("# readme")
            self.assertEqual(ps.list_pending_changes(tmpdir), [])

    def test_filters_non_pending(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            report = {"run_id": "t", "workflow_id": "t",
                      "suggestions": [{"target": "prompts", "recommendation": "x",
                                       "priority": "low", "requires_human_approval": False}]}
            rp = os.path.join(tmpdir, "r.json")
            with open(rp, "w") as f:
                json.dump(report, f)
            cp = ps.promote_suggestion(report, rp, report["suggestions"][0], 0, tmpdir)
            # Approved changes should not appear in pending list
            ps.approve_change(cp)
            pending = ps.list_pending_changes(tmpdir)
            self.assertEqual(len(pending), 0)


class TestFindChangeFile(unittest.TestCase):
    """find_change_file: 根据 change_id 查找文件路径"""

    def test_find_by_filename(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            report = {"run_id": "t", "workflow_id": "t",
                      "suggestions": [{"target": "prompts", "recommendation": "x",
                                       "priority": "low", "requires_human_approval": False}]}
            rp = os.path.join(tmpdir, "r.json")
            with open(rp, "w") as f:
                json.dump(report, f)
            cp = ps.promote_suggestion(report, rp, report["suggestions"][0], 0, tmpdir)
            with open(cp) as f:
                change = json.load(f)
            found = ps.find_change_file(change["change_id"], tmpdir)
            self.assertEqual(found, cp)

    def test_not_found(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            found = ps.find_change_file("change_nonexistent", tmpdir)
            self.assertIsNone(found)


class TestTARGET_TO_COMPONENT(unittest.TestCase):
    """TARGET_TO_COMPONENT 映射完整性"""

    def test_all_expected_targets_present(self):
        expected = [
            "prompts", "workflow_steps", "constraint_rules",
            "retrieval_strategy", "knowledge_base_metadata",
            "output_templates", "tool_permissions", "model_routing",
        ]
        for t in expected:
            self.assertIn(t, ps.TARGET_TO_COMPONENT)

    def test_all_targets_map_to_themselves(self):
        for target, component in ps.TARGET_TO_COMPONENT.items():
            self.assertEqual(target, component)


class TestTARGET_TO_FILE_PATH(unittest.TestCase):
    """TARGET_TO_FILE_PATH 映射完整性"""

    def test_all_targets_have_path(self):
        for target in ps.TARGET_TO_COMPONENT:
            self.assertIn(target, ps.TARGET_TO_FILE_PATH)

    def test_all_paths_are_strings(self):
        for path in ps.TARGET_TO_FILE_PATH.values():
            self.assertIsInstance(path, str)
            self.assertTrue(len(path) > 0)


class TestTARGET_TO_CHANGE_TYPE(unittest.TestCase):
    """TARGET_TO_CHANGE_TYPE 映射完整性"""

    def test_all_targets_have_change_type(self):
        for target in ps.TARGET_TO_COMPONENT:
            self.assertIn(target, ps.TARGET_TO_CHANGE_TYPE)


class TestConstants(unittest.TestCase):
    """模块级别的常量验证"""

    def test_change_dir_default(self):
        self.assertEqual(ps.CHANGE_DIR_DEFAULT, "runtime/candidate_changes/")

    def test_schema_path(self):
        self.assertTrue(ps.SCHEMA_PATH.endswith("candidate_change.schema.json"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
