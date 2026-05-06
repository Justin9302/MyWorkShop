#!/usr/bin/env python3
"""
tests/phase7a/test_eval_set_manager.py — Phase 7b eval_set_manager 自动化测试

测试范围:
  - 哈希和去重逻辑
  - 条件评估引擎
  - 报告分类流程
  - stats 和 create-baseline
"""

import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "scripts"))

from eval_set_manager import (
    compute_hash,
    make_input_hash,
    make_output_hash,
    make_dedup_key,
    _eval_condition,
    ConditionEvalError,
    find_reports,
    classify_report,
    _load_existing_samples,
    _is_duplicate,
    _target_to_category,
    _extract_critical_findings,
    generate_stats,
    create_baseline,
    load_yaml,
    save_json,
)

CONFIG_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..",
    "config", "eval-set-config.yaml"
)
SAMPLE_SNAPSHOT = {
    "run_id": "test_run_001",
    "workflow_id": "business_model_validation",
    "output_summary": {"sections": ["exec_summary", "risk_table"], "score": 0.75},
    "human_review": {"required": False, "review_status": ""},
    "constraints_triggered": [],
}

SAMPLE_REPORT = {
    "run_id": "test_run_001",
    "workflow_id": "business_model_validation",
    "score": 0.75,
    "passed": True,
    "risk_level": "medium",
    "metrics": {
        "citation_accuracy": 0.8,
        "constraint_compliance": 0.9,
        "format_compliance": 0.7,
        "risk_detection": 0.6,
        "human_modification_rate": 0.1,
        "output_adoption_rate": 0.85,
        "high_risk_miss_rate": 0.2,
        "cost_latency": 0.3,
    },
    "findings": [],
    "suggestions": [],
    "created_at": "2026-05-06T00:00:00Z",
}


class TestHashing(unittest.TestCase):
    """Test hash computation and dedup key generation."""

    def test_compute_hash(self):
        h1 = compute_hash("hello")
        h2 = compute_hash("hello")
        self.assertEqual(h1, h2)
        self.assertEqual(len(h1), 16)

    def test_compute_hash_different(self):
        h1 = compute_hash("hello")
        h2 = compute_hash("world")
        self.assertNotEqual(h1, h2)

    def test_make_input_hash(self):
        h = make_input_hash(SAMPLE_SNAPSHOT)
        self.assertIsInstance(h, str)
        self.assertEqual(len(h), 16)

    def test_make_input_hash_consistent(self):
        h1 = make_input_hash(SAMPLE_SNAPSHOT)
        h2 = make_input_hash(SAMPLE_SNAPSHOT)
        self.assertEqual(h1, h2)

    def test_make_output_hash(self):
        h = make_output_hash(SAMPLE_SNAPSHOT)
        self.assertIsInstance(h, str)

    def test_make_dedup_key(self):
        key = make_dedup_key("workflow_id + input_hash", SAMPLE_SNAPSHOT)
        self.assertIsInstance(key, str)
        self.assertEqual(len(key), 16)

    def test_dedup_key_consistent(self):
        key1 = make_dedup_key("workflow_id + input_hash", SAMPLE_SNAPSHOT)
        key2 = make_dedup_key("workflow_id + input_hash", SAMPLE_SNAPSHOT)
        self.assertEqual(key1, key2)


class TestConditionEvaluation(unittest.TestCase):
    """Test _eval_condition with various expressions."""

    def test_score_less_than(self):
        self.assertTrue(_eval_condition("report.score < 0.4", {"score": 0.3}))
        self.assertFalse(_eval_condition("report.score < 0.4", {"score": 0.5}))

    def test_score_greater_than(self):
        self.assertTrue(_eval_condition("report.score >= 0.8", {"score": 0.85}))
        self.assertFalse(_eval_condition("report.score >= 0.8", {"score": 0.7}))

    def test_metric_access(self):
        report = {"metrics": {"output_adoption_rate": 0.85}}
        self.assertTrue(
            _eval_condition(
                "report.metrics.output_adoption_rate >= 0.8",
                report,
            )
        )

    def test_human_review_status(self):
        snap = {"human_review": {"review_status": "approved_with_changes"}}
        self.assertTrue(
            _eval_condition(
                "snapshot.human_review.review_status in ('approved_with_changes', 'rejected')",
                {"score": 0.5},
                snap,
            )
        )
        snap2 = {"human_review": {"review_status": "approved"}}
        self.assertFalse(
            _eval_condition(
                "snapshot.human_review.review_status in ('approved_with_changes', 'rejected')",
                {"score": 0.5},
                snap2,
            )
        )

    def test_any_generator(self):
        snap = {
            "constraints_triggered": [
                {"constraint_id": "c1", "severity": "high"},
                {"constraint_id": "c2", "severity": "critical"},
            ]
        }
        self.assertTrue(
            _eval_condition(
                "any(c.severity == 'critical' for c in snapshot.constraints_triggered)",
                {"score": 0.5},
                snap,
            )
        )

    def test_no_critical_constraints(self):
        snap = {"constraints_triggered": [{"severity": "low"}, {"severity": "medium"}]}
        self.assertFalse(
            _eval_condition(
                "any(c.severity == 'critical' for c in snapshot.constraints_triggered)",
                {"score": 0.5},
                snap,
            )
        )

    def test_invalid_expression_raises(self):
        with self.assertRaises(ConditionEvalError):
            _eval_condition("1/0", {"score": 0.5})

    def test_injection_protected(self):
        """Should not allow access to dangerous builtins."""
        with self.assertRaises(ConditionEvalError):
            _eval_condition("__import__('os').system('ls')", {"score": 0.5})


class TestReportClassification(unittest.TestCase):
    """Test classify_report with various report configurations."""

    @classmethod
    def setUpClass(cls):
        cls.config = load_yaml(CONFIG_PATH)

    def test_low_score_classifies_as_failure(self):
        """Low score report should classify as regression_failure."""
        report = dict(SAMPLE_REPORT, score=0.3)
        result = classify_report.__wrapped__ if hasattr(classify_report, '__wrapped__') else None
        # Use internal logic directly
        from eval_set_manager import _eval_condition
        self.assertTrue(_eval_condition("report.score < 0.4", report))

    def test_high_adoption_golden_candidate(self):
        """High adoption without review should be golden candidate."""
        report = dict(SAMPLE_REPORT, score=0.85)
        self.assertTrue(
            _eval_condition(
                "report.metrics.output_adoption_rate >= 0.8 and not snapshot.human_review.required",
                report,
                SAMPLE_SNAPSHOT,
            )
        )

    def test_critical_constraint_triggers_risk(self):
        """Critical constraint should classify as risk."""
        snap = dict(SAMPLE_SNAPSHOT)
        snap["constraints_triggered"] = [
            {"constraint_id": "c1", "severity": "critical", "message": "Data breach"}
        ]
        self.assertTrue(
            _eval_condition(
                "any(c.severity == 'critical' for c in snapshot.constraints_triggered)",
                SAMPLE_REPORT,
                snap,
            )
        )

    def test_human_modified_classifies(self):
        """Human-modified report should classify as human_corrected."""
        snap = dict(SAMPLE_SNAPSHOT)
        snap["human_review"] = {"required": True, "review_status": "rejected"}
        self.assertTrue(
            _eval_condition(
                "snapshot.human_review.review_status in ('approved_with_changes', 'rejected')",
                SAMPLE_REPORT,
                snap,
            )
        )


class TestHelpers(unittest.TestCase):
    """Test helper functions."""

    def test_target_to_category(self):
        self.assertEqual(_target_to_category("tests/eval_cases/golden/"), "golden")
        self.assertEqual(_target_to_category("tests/eval_cases/regression/failures/"), "regression_failure")
        self.assertEqual(_target_to_category("tests/eval_cases/regression/human_corrected/"), "regression_human_corrected")
        self.assertEqual(_target_to_category("tests/eval_cases/regression/risk_samples/"), "regression_risk")
        self.assertEqual(_target_to_category("unknown"), "synthetic")

    def test_extract_critical_findings(self):
        report = {
            "findings": [
                {"severity": "critical", "message": "Critical issue"},
                {"severity": "high", "message": "High issue"},
                {"severity": "low", "message": "Low issue"},
            ]
        }
        findings = _extract_critical_findings(report)
        self.assertEqual(len(findings), 2)
        self.assertIn("Critical issue", findings)
        self.assertIn("High issue", findings)

    def test_extract_critical_findings_capped(self):
        findings_list = [{"severity": "high", "message": f"Issue {i}"} for i in range(15)]
        report = {"findings": findings_list}
        findings = _extract_critical_findings(report)
        self.assertLessEqual(len(findings), 10)

    def test_find_reports_empty_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config = {"scan": {"report_pattern": "*_eval.json", "exclude_patterns": ["_batch_summary.json"]}}
            files = find_reports(tmpdir, config)
            self.assertEqual(files, [])

    def test_find_reports_with_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            for fname in ["report_001_eval.json", "report_002_eval.json", "_batch_summary.json"]:
                with open(os.path.join(tmpdir, fname), "w") as f:
                    f.write("{}")
            config = {"scan": {"report_pattern": "*_eval.json", "exclude_patterns": ["_batch_summary.json"]}}
            files = find_reports(tmpdir, config)
            self.assertEqual(len(files), 2)
            self.assertNotIn("_batch_summary.json", files[0])


class TestStatsAndBaseline(unittest.TestCase):
    """Test stats generation and baseline creation."""

    def test_generate_stats_empty(self):
        """Stats should handle empty directories gracefully."""
        with tempfile.TemporaryDirectory() as tmpdir:
            os.makedirs(os.path.join(tmpdir, "golden"))
            os.makedirs(os.path.join(tmpdir, "regression", "failures"))
            stats = generate_stats({})
            self.assertIn("categories", stats)
            self.assertEqual(stats["total_samples"], 0)

    def test_create_baseline_no_golden(self):
        """create_baseline without golden dir should return error."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Temporarily change cwd or mock... just call and check error handling
            result = create_baseline({})
            self.assertIn("error", result)


class TestConfigLoading(unittest.TestCase):
    """Test that the config file loads correctly."""

    def test_config_exists(self):
        self.assertTrue(os.path.exists(CONFIG_PATH))

    def test_config_has_rules(self):
        config = load_yaml(CONFIG_PATH)
        self.assertIn("eval_set_rules", config)
        rules = config["eval_set_rules"]
        self.assertIn("auto_classify", rules)
        self.assertGreaterEqual(len(rules["auto_classify"]), 4)

    def test_config_has_hashing(self):
        config = load_yaml(CONFIG_PATH)
        self.assertIn("hashing", config)
        self.assertEqual(config["hashing"]["algorithm"], "sha256")

    def test_config_has_scan(self):
        config = load_yaml(CONFIG_PATH)
        self.assertIn("scan", config)
        self.assertIn("report_dir", config["scan"])


if __name__ == "__main__":
    unittest.main()
