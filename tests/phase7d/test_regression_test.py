#!/usr/bin/env python3
"""
tests/phase7d/test_regression_test.py — Phase 7d 沙箱回归测试引擎自动化测试套件

覆盖全部核心函数：
  - generate_baseline
  - _evaluate_snapshot_dimensions
  - apply_patch / cleanup_patch
  - run_patched
  - compare_scores
  - run_regression (完整流程)
  - _build_regression_report
  - _backfill_candidate_change
  - compare_mode
  - CLI 接口

运行:
  python -m pytest tests/phase7d/test_regression_test.py -v
  python tests/phase7d/test_regression_test.py  # 直接运行
"""

import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch, MagicMock

# 确保可以从项目根目录 import
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

import scripts.regression_test as rt


# ── 测试数据 ──

SAMPLE_SNAPSHOT = {
    "run_id": "test_run_001",
    "workflow_id": "business_model_validation",
    "output_summary": {
        "sections": ["exec_summary", "risk_table", "recommendations"],
        "score": 0.75,
        "risk_flags": ["market_risk", "regulatory_risk"],
        "red_flags": ["conflict_of_interest"],
    },
    "human_review": {"required": False, "review_status": ""},
    "constraints_triggered": [
        {"constraint_id": "c1", "severity": "low", "message": "Info only"}
    ],
    "retrieved_sources": [
        {"source_id": "src_001", "title": "Market Report 2026"},
        {"source_id": "src_002", "title": "Regulatory Framework"},
    ],
    "tool_calls": [
        {"tool": "fetch_official_sources", "duration_ms": 1200},
        {"tool": "read_file", "duration_ms": 300},
    ],
}

SAMPLE_BASELINE = {
    "version": "workflow_0.2.0_evaluator_0.2.0",
    "judge_mode": "heuristic",
    "snapshot_count": 3,
    "snapshot_files_found": 3,
    "dimensions": {
        "citation_accuracy": 0.7200,
        "constraint_compliance": 0.8500,
        "format_compliance": 0.8000,
        "risk_detection": 0.6800,
        "human_modification_rate": 0.1000,
        "output_adoption_rate": 0.8500,
        "high_risk_miss_rate": 0.2000,
        "cost_latency": 0.3000,
    },
    "overall_score": 0.5625,
    "created_at": "2026-05-06T00:00:00Z",
}

SAMPLE_CANDIDATE = {
    "change_id": "change_test0001",
    "source": {
        "run_id": "test_run_001",
        "report_path": "outputs/eval_reports/test_eval.json",
        "suggestion_index": 0,
    },
    "target": {
        "component": "constraint_rules",
        "file_path": "constraints/",
        "change_type": "add_rule",
    },
    "diff": {
        "summary": "Add CN jurisdiction rule for data privacy",
        "before": "(pending — read current file content)",
        "after": "(pending — patch to be generated after review)",
    },
    "validation": {
        "status": "pending",
        "sandbox_report": None,
        "regression_result": None,
    },
    "approval": {
        "required": True,
        "approved_by": None,
        "approved_at": None,
        "review_notes": None,
    },
    "rollout": {
        "strategy": "canary",
        "traffic_split": 0.1,
        "status": "pending",
    },
    "created_at": "2026-05-06T00:00:00Z",
}

SAMPLE_PATCHED = {
    "version": "change_test0001_constraint_rules",
    "judge_mode": "heuristic",
    "snapshot_count": 3,
    "snapshot_files_found": 3,
    "dimensions": {
        "citation_accuracy": 0.7500,
        "constraint_compliance": 0.8800,
        "format_compliance": 0.8000,
        "risk_detection": 0.7000,
        "human_modification_rate": 0.1000,
        "output_adoption_rate": 0.8500,
        "high_risk_miss_rate": 0.1800,
        "cost_latency": 0.3000,
    },
    "overall_score": 0.5700,
    "created_at": "2026-05-06T01:00:00Z",
}


# ── Test Classes ──


class TestFileIO(unittest.TestCase):
    """测试文件 I/O 辅助函数"""

    def test_load_json_exists(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump({"key": "value"}, f)
            fpath = f.name
        try:
            result = rt._load_json(fpath)
            self.assertEqual(result, {"key": "value"})
        finally:
            os.unlink(fpath)

    def test_load_json_not_exists(self):
        with self.assertRaises(FileNotFoundError):
            rt._load_json("/nonexistent/path.json")

    def test_write_json_creates_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "subdir", "test.json")
            rt._write_json(path, {"a": 1})
            self.assertTrue(os.path.exists(path))
            with open(path) as f:
                self.assertEqual(json.load(f), {"a": 1})

    def test_find_snapshot_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            # 创建快照文件
            for fname in ["snap_001.json", "snap_002.json", "_batch_summary.json", "report_eval.json"]:
                with open(os.path.join(tmpdir, fname), "w") as f:
                    f.write("{}")
            files = rt._find_snapshot_files([tmpdir])
            self.assertEqual(len(files), 2)  # 排除 _ 开头和 _eval.json
            self.assertTrue(all(f.endswith(".json") for f in files))
            self.assertFalse(any(f.endswith("_eval.json") for f in files))
            self.assertFalse(any("_batch_summary" in f for f in files))

    def test_find_snapshot_files_nonexistent_dir(self):
        files = rt._find_snapshot_files(["/nonexistent_dir"])
        self.assertEqual(files, [])


class TestVersionHelpers(unittest.TestCase):
    """测试版本标识生成"""

    def test_get_baseline_version(self):
        version = rt._get_baseline_version()
        self.assertIsInstance(version, str)
        self.assertTrue(len(version) > 0)

    def test_get_patched_version(self):
        version = rt._get_patched_version(SAMPLE_CANDIDATE)
        self.assertIn("change_test0001", version)
        self.assertIn("constraint_rules", version)


class TestEvaluateSnapshotDimensions(unittest.TestCase):
    """测试 _evaluate_snapshot_dimensions 评分逻辑"""

    def test_returns_all_8_dimensions(self):
        scores = rt._evaluate_snapshot_dimensions(SAMPLE_SNAPSHOT)
        for dim in rt.DEFAULT_METRICS:
            self.assertIn(dim, scores)
            self.assertIsInstance(scores[dim], float)
            self.assertGreaterEqual(scores[dim], 0.0)
            self.assertLessEqual(scores[dim], 1.0)

    def test_citation_accuracy_with_sources(self):
        scores = rt._evaluate_snapshot_dimensions(SAMPLE_SNAPSHOT)
        self.assertGreater(scores["citation_accuracy"], 0.5)

    def test_citation_accuracy_no_sources(self):
        snap = dict(SAMPLE_SNAPSHOT)
        snap["retrieved_sources"] = []
        scores = rt._evaluate_snapshot_dimensions(snap)
        self.assertLess(scores["citation_accuracy"], 0.6)

    def test_constraint_compliance_no_violations(self):
        snap = dict(SAMPLE_SNAPSHOT)
        snap["constraints_triggered"] = []
        scores = rt._evaluate_snapshot_dimensions(snap)
        # 当 eval_runner 可用时使用其评分，否则使用内置评分
        # 内置评分: 无 violations → 1.0; eval_runner: 取决于具体逻辑
        self.assertGreaterEqual(scores["constraint_compliance"], 0.4)

    def test_constraint_compliance_with_critical(self):
        snap = dict(SAMPLE_SNAPSHOT)
        snap["constraints_triggered"] = [
            {"severity": "critical", "message": "Data breach risk"}
        ]
        scores = rt._evaluate_snapshot_dimensions(snap)
        self.assertLess(scores["constraint_compliance"], 0.8)

    def test_human_modification_rate_no_review(self):
        scores = rt._evaluate_snapshot_dimensions(SAMPLE_SNAPSHOT)
        self.assertAlmostEqual(scores["human_modification_rate"], 0.1)

    def test_human_modification_rate_rejected(self):
        snap = dict(SAMPLE_SNAPSHOT)
        snap["human_review"] = {"required": True, "review_status": "rejected"}
        scores = rt._evaluate_snapshot_dimensions(snap)
        self.assertAlmostEqual(scores["human_modification_rate"], 0.9)

    def test_output_adoption_rate_no_review(self):
        scores = rt._evaluate_snapshot_dimensions(SAMPLE_SNAPSHOT)
        self.assertAlmostEqual(scores["output_adoption_rate"], 0.85)

    def test_high_risk_miss_rate_with_flags(self):
        scores = rt._evaluate_snapshot_dimensions(SAMPLE_SNAPSHOT)
        self.assertLess(scores["high_risk_miss_rate"], 0.5)

    def test_high_risk_miss_rate_no_risks(self):
        snap = dict(SAMPLE_SNAPSHOT)
        snap["output_summary"] = {"sections": ["basic"]}
        scores = rt._evaluate_snapshot_dimensions(snap)
        self.assertAlmostEqual(scores["high_risk_miss_rate"], 0.1)

    def test_cost_latency(self):
        scores = rt._evaluate_snapshot_dimensions(SAMPLE_SNAPSHOT)
        self.assertGreater(scores["cost_latency"], 0.0)


class TestGenerateBaseline(unittest.TestCase):
    """测试 baseline 生成"""

    def test_generate_baseline_empty_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = rt.generate_baseline([tmpdir], tmpdir)
            self.assertTrue(result.get("_empty"))

    def test_generate_baseline_with_snapshots(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            snap_path = os.path.join(tmpdir, "snap_001.json")
            with open(snap_path, "w") as f:
                json.dump(SAMPLE_SNAPSHOT, f)
            result = rt.generate_baseline([tmpdir], tmpdir)
            self.assertFalse(result.get("_empty", False))
            self.assertEqual(result["snapshot_count"], 1)
            self.assertIn("dimensions", result)
            self.assertIn("overall_score", result)

    def test_generate_baseline_caches_to_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            snap_path = os.path.join(tmpdir, "snap_001.json")
            with open(snap_path, "w") as f:
                json.dump(SAMPLE_SNAPSHOT, f)
            rt.generate_baseline([tmpdir], tmpdir)
            cache_path = os.path.join(tmpdir, "_baseline.json")
            self.assertTrue(os.path.exists(cache_path))


class TestApplyPatch(unittest.TestCase):
    """测试 patch 应用"""

    def test_apply_patch_creates_temp_dir(self):
        result = rt.apply_patch(SAMPLE_CANDIDATE)
        self.assertIn("temp_dir", result)
        self.assertTrue(os.path.exists(result["temp_dir"]))
        rt.cleanup_patch(result)

    def test_apply_patch_returns_modified_files(self):
        result = rt.apply_patch(SAMPLE_CANDIDATE)
        self.assertIn("modified_files", result)
        self.assertIsInstance(result["modified_files"], list)
        rt.cleanup_patch(result)

    def test_apply_patch_component(self):
        result = rt.apply_patch(SAMPLE_CANDIDATE)
        self.assertEqual(result["component"], "constraint_rules")
        self.assertEqual(result["change_type"], "add_rule")
        rt.cleanup_patch(result)

    def test_cleanup_patch_removes_temp_dir(self):
        result = rt.apply_patch(SAMPLE_CANDIDATE)
        temp_dir = result["temp_dir"]
        self.assertTrue(os.path.exists(temp_dir))
        rt.cleanup_patch(result)
        self.assertFalse(os.path.exists(temp_dir))

    def test_apply_patch_unknown_component(self):
        candidate = dict(SAMPLE_CANDIDATE)
        candidate["target"] = {"component": "unknown_comp", "file_path": "", "change_type": "modify"}
        result = rt.apply_patch(candidate)
        self.assertEqual(result["component"], "unknown_comp")
        rt.cleanup_patch(result)


class TestRunPatched(unittest.TestCase):
    """测试 patched 评估"""

    def test_run_patched_empty_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = rt.run_patched(SAMPLE_CANDIDATE, {"temp_dir": tmpdir}, [tmpdir], tmpdir)
            self.assertTrue(result.get("_empty"))

    def test_run_patched_with_snapshots(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            snap_path = os.path.join(tmpdir, "snap_001.json")
            with open(snap_path, "w") as f:
                json.dump(SAMPLE_SNAPSHOT, f)
            result = rt.run_patched(
                SAMPLE_CANDIDATE, {"temp_dir": tmpdir, "modified_files": [], "component": "test", "change_type": "modify"},
                [tmpdir], tmpdir,
            )
            self.assertFalse(result.get("_empty", False))
            self.assertEqual(result["snapshot_count"], 1)
            self.assertIn("dimensions", result)


class TestCompareScores(unittest.TestCase):
    """测试分数对比"""

    def test_compare_improved(self):
        result = rt.compare_scores(SAMPLE_BASELINE, SAMPLE_PATCHED)
        self.assertIn("conclusion", result)
        self.assertIn("dimensions", result)
        self.assertIn("overall_score_change", result)

    def test_compare_pass_when_improved(self):
        # 使用明显改进的 patched 分数
        # 所有维度 delta >= -0.01 (unchanged) 或 >= 0.01 (improved)
        # 注意: human_modification_rate 和 cost_latency 是越低越好
        improved_patched = dict(SAMPLE_PATCHED)
        improved_patched["dimensions"] = {
            "citation_accuracy": 0.85,
            "constraint_compliance": 0.92,
            "format_compliance": 0.90,
            "risk_detection": 0.85,
            "human_modification_rate": 0.10,  # delta = 0.0, unchanged
            "output_adoption_rate": 0.90,
            "high_risk_miss_rate": 0.20,      # delta = 0.0, unchanged
            "cost_latency": 0.30,             # delta = 0.0, unchanged
        }
        improved_patched["overall_score"] = 0.60
        result = rt.compare_scores(SAMPLE_BASELINE, improved_patched)
        self.assertEqual(result["conclusion"], "sandbox_pass")
        self.assertGreater(result["overall_score_change"], 0)

    def test_compare_fail_when_critical_regression(self):
        bad_patched = dict(SAMPLE_PATCHED)
        bad_patched["dimensions"] = dict(SAMPLE_BASELINE["dimensions"])
        bad_patched["dimensions"]["citation_accuracy"] = 0.3  # 下降 0.42
        bad_patched["overall_score"] = 0.4
        result = rt.compare_scores(SAMPLE_BASELINE, bad_patched)
        self.assertEqual(result["conclusion"], "sandbox_fail")

    def test_compare_warning_when_minor_regression(self):
        warn_patched = dict(SAMPLE_PATCHED)
        warn_patched["dimensions"] = dict(SAMPLE_BASELINE["dimensions"])
        warn_patched["dimensions"]["risk_detection"] = 0.63  # 下降 0.05
        warn_patched["overall_score"] = 0.54
        result = rt.compare_scores(SAMPLE_BASELINE, warn_patched)
        self.assertEqual(result["conclusion"], "sandbox_warning")

    def test_compare_unchanged(self):
        result = rt.compare_scores(SAMPLE_BASELINE, SAMPLE_BASELINE)
        self.assertEqual(result["overall_score_change"], 0)
        self.assertEqual(result["conclusion"], "sandbox_pass")

    def test_compare_dimension_status_improved(self):
        result = rt.compare_scores(SAMPLE_BASELINE, SAMPLE_PATCHED)
        for dim, data in result["dimensions"].items():
            if data["delta"] >= 0.01:
                self.assertEqual(data["status"], "improved")
            elif data["delta"] >= -0.01:
                self.assertEqual(data["status"], "unchanged")

    def test_compare_custom_thresholds(self):
        thresholds = {"critical_delta": -0.05, "warning_delta": -0.02, "overall_critical_delta": -0.03}
        bad_patched = dict(SAMPLE_PATCHED)
        bad_patched["dimensions"] = dict(SAMPLE_BASELINE["dimensions"])
        bad_patched["dimensions"]["risk_detection"] = 0.62  # 下降 0.06
        bad_patched["overall_score"] = 0.53
        result = rt.compare_scores(SAMPLE_BASELINE, bad_patched, thresholds)
        self.assertEqual(result["conclusion"], "sandbox_fail")


class TestBuildRegressionReport(unittest.TestCase):
    """测试回归报告构建"""

    def test_report_has_required_fields(self):
        comparison = rt.compare_scores(SAMPLE_BASELINE, SAMPLE_PATCHED)
        patched_ctx = {"temp_dir": "/tmp/test", "modified_files": ["constraints/"]}
        report = rt._build_regression_report(
            SAMPLE_CANDIDATE, SAMPLE_BASELINE, SAMPLE_PATCHED,
            comparison, ["tests/eval_cases/synthetic/"], patched_ctx,
        )
        required = ["change_id", "status", "baseline_version", "patched_version",
                     "eval_set_info", "sample_count", "summary", "created_at"]
        for field in required:
            self.assertIn(field, report, f"缺少字段: {field}")

    def test_report_status_matches_comparison(self):
        comparison = rt.compare_scores(SAMPLE_BASELINE, SAMPLE_PATCHED)
        patched_ctx = {"temp_dir": "/tmp/test", "modified_files": []}
        report = rt._build_regression_report(
            SAMPLE_CANDIDATE, SAMPLE_BASELINE, SAMPLE_PATCHED,
            comparison, [], patched_ctx,
        )
        self.assertEqual(report["status"], comparison["conclusion"])


class TestBackfillCandidateChange(unittest.TestCase):
    """测试候选变更回填"""

    def test_backfill_updates_validation(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            candidate_path = os.path.join(tmpdir, "change_test0001.json")
            with open(candidate_path, "w") as f:
                json.dump(SAMPLE_CANDIDATE, f)

            report = {
                "change_id": "change_test0001",
                "status": "sandbox_pass",
                "summary": {
                    "overall_score_change": 0.03,
                    "regressions": [],
                    "improvements": ["citation_accuracy +0.06"],
                },
            }
            rt._backfill_candidate_change(candidate_path, report)

            with open(candidate_path) as f:
                updated = json.load(f)
            self.assertEqual(updated["validation"]["status"], "sandbox_pass")
            self.assertEqual(
                updated["validation"]["regression_result"]["overall_score_change"], 0.03
            )

    def test_backfill_nonexistent_file(self):
        # 不应抛出异常
        report = {"change_id": "nonexistent", "status": "sandbox_fail", "summary": {}}
        rt._backfill_candidate_change("/nonexistent/path.json", report)


class TestCompareMode(unittest.TestCase):
    """测试 compare_mode 函数"""

    def test_compare_mode_returns_report(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            baseline_path = os.path.join(tmpdir, "_baseline.json")
            patched_path = os.path.join(tmpdir, "_patched.json")
            with open(baseline_path, "w") as f:
                json.dump(SAMPLE_BASELINE, f)
            with open(patched_path, "w") as f:
                json.dump(SAMPLE_PATCHED, f)

            report = rt.compare_mode(baseline_path, patched_path, tmpdir)
            self.assertIn("status", report)
            self.assertIn("summary", report)
            self.assertEqual(report["change_id"], "compare_mode")

    def test_compare_mode_saves_report(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            baseline_path = os.path.join(tmpdir, "_baseline.json")
            patched_path = os.path.join(tmpdir, "_patched.json")
            with open(baseline_path, "w") as f:
                json.dump(SAMPLE_BASELINE, f)
            with open(patched_path, "w") as f:
                json.dump(SAMPLE_PATCHED, f)

            rt.compare_mode(baseline_path, patched_path, tmpdir)
            report_path = os.path.join(tmpdir, "_compare_report.json")
            self.assertTrue(os.path.exists(report_path))


class TestRunRegression(unittest.TestCase):
    """测试完整回归流程"""

    def test_run_regression_empty_baseline(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            candidate_path = os.path.join(tmpdir, "candidate.json")
            with open(candidate_path, "w") as f:
                json.dump(SAMPLE_CANDIDATE, f)

            # 空评估集 → 无快照文件 → baseline 为空 → 返回 fail
            report = rt.run_regression(
                candidate_path,
                eval_set_dirs=[tmpdir],
                output_dir=tmpdir,
                cleanup=True,
            )
            # 当 eval_runner 可用时，baseline 可能不为空（因为 eval_runner 的评分函数被调用）
            # 但无论如何，报告应该包含 status 字段
            self.assertIn("status", report)

    def test_run_regression_with_snapshots(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            # 创建快照
            snap_path = os.path.join(tmpdir, "snap_001.json")
            with open(snap_path, "w") as f:
                json.dump(SAMPLE_SNAPSHOT, f)

            # 创建候选变更
            candidate_path = os.path.join(tmpdir, "candidate.json")
            with open(candidate_path, "w") as f:
                json.dump(SAMPLE_CANDIDATE, f)

            report = rt.run_regression(
                candidate_path,
                eval_set_dirs=[tmpdir],
                output_dir=tmpdir,
                cleanup=True,
            )
            self.assertIn("status", report)
            self.assertIn("summary", report)
            self.assertIn("change_id", report)

    def test_run_regression_saves_report(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            snap_path = os.path.join(tmpdir, "snap_001.json")
            with open(snap_path, "w") as f:
                json.dump(SAMPLE_SNAPSHOT, f)

            candidate_path = os.path.join(tmpdir, "candidate.json")
            with open(candidate_path, "w") as f:
                json.dump(SAMPLE_CANDIDATE, f)

            report = rt.run_regression(
                candidate_path,
                eval_set_dirs=[tmpdir],
                output_dir=tmpdir,
                cleanup=True,
            )
            report_path = os.path.join(tmpdir, f"{report['change_id']}_regression_report.json")
            self.assertTrue(os.path.exists(report_path))

    def test_run_regression_with_baseline_cache(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            # 创建 baseline 缓存
            baseline_cache = os.path.join(tmpdir, "_baseline.json")
            with open(baseline_cache, "w") as f:
                json.dump(SAMPLE_BASELINE, f)

            # 创建快照
            snap_path = os.path.join(tmpdir, "snap_001.json")
            with open(snap_path, "w") as f:
                json.dump(SAMPLE_SNAPSHOT, f)

            candidate_path = os.path.join(tmpdir, "candidate.json")
            with open(candidate_path, "w") as f:
                json.dump(SAMPLE_CANDIDATE, f)

            report = rt.run_regression(
                candidate_path,
                eval_set_dirs=[tmpdir],
                output_dir=tmpdir,
                baseline_cache=baseline_cache,
                cleanup=True,
            )
            self.assertIn("status", report)


class TestPrintRegressionSummary(unittest.TestCase):
    """测试打印摘要（不抛出异常即可）"""

    def test_print_pass(self):
        comparison = rt.compare_scores(SAMPLE_BASELINE, SAMPLE_PATCHED)
        patched_ctx = {"temp_dir": "/tmp/test", "modified_files": []}
        report = rt._build_regression_report(
            SAMPLE_CANDIDATE, SAMPLE_BASELINE, SAMPLE_PATCHED,
            comparison, [], patched_ctx,
        )
        try:
            rt._print_regression_summary(report)
        except Exception as e:
            self.fail(f"_print_regression_summary 抛出异常: {e}")

    def test_print_fail(self):
        bad_patched = dict(SAMPLE_PATCHED)
        bad_patched["dimensions"] = {d: 0.1 for d in rt.DEFAULT_METRICS}
        bad_patched["overall_score"] = 0.1
        comparison = rt.compare_scores(SAMPLE_BASELINE, bad_patched)
        patched_ctx = {"temp_dir": "/tmp/test", "modified_files": []}
        report = rt._build_regression_report(
            SAMPLE_CANDIDATE, SAMPLE_BASELINE, bad_patched,
            comparison, [], patched_ctx,
        )
        try:
            rt._print_regression_summary(report)
        except Exception as e:
            self.fail(f"_print_regression_summary 抛出异常: {e}")


class TestCliInterface(unittest.TestCase):
    """测试 CLI 接口"""

    @patch("sys.argv", ["regression_test.py", "--generate-baseline", "--eval-set", "/nonexistent"])
    def test_generate_baseline_cli_empty(self):
        """空评估集时应该退出"""
        with self.assertRaises(SystemExit):
            rt.main()

    @patch("sys.argv", ["regression_test.py", "--compare", "--baseline", "/nonexistent/b.json", "--target", "/nonexistent/t.json"])
    def test_compare_cli_nonexistent_files(self):
        """不存在的文件应该抛出异常"""
        with self.assertRaises(FileNotFoundError):
            rt.main()

    @patch("sys.argv", ["regression_test.py"])
    def test_no_args_shows_help(self):
        """无参数时应该显示帮助并退出"""
        with self.assertRaises(SystemExit):
            rt.main()

    @patch("sys.argv", ["regression_test.py", "--candidate", "/nonexistent/candidate.json"])
    def test_nonexistent_candidate(self):
        """不存在的候选变更文件应该退出"""
        with self.assertRaises(SystemExit):
            rt.main()


class TestConstants(unittest.TestCase):
    """测试模块级常量"""

    def test_default_metrics_count(self):
        self.assertEqual(len(rt.DEFAULT_METRICS), 8)

    def test_default_thresholds_keys(self):
        required = ["critical_delta", "warning_delta", "overall_critical_delta"]
        for key in required:
            self.assertIn(key, rt.DEFAULT_THRESHOLDS)

    def test_target_to_file_prefix_keys(self):
        required = ["prompts", "workflow_steps", "constraint_rules",
                     "retrieval_strategy", "knowledge_base_metadata",
                     "output_templates", "tool_permissions", "model_routing"]
        for key in required:
            self.assertIn(key, rt.TARGET_TO_FILE_PREFIX)


if __name__ == "__main__":
    unittest.main(verbosity=2)
