#!/usr/bin/env python3
"""
tests/phase7a/test_eval_runner_judge.py — Phase 7a eval_runner LLM 集成测试

测试范围:
  - _should_use_llm 三段逻辑（heuristic/llm/hybrid）
  - evaluate_criterion 在 LLM 模式下的降级行为
  - --judge-mode CLI 参数向后兼容
  - 完整 run_single 在 heuristic 模式下的向后兼容
"""

import json
import os
import sys
import tempfile
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "scripts"))

from eval_runner import (
    run_single,
    load_json,
    load_yaml,
    evaluate_criterion,
    _should_use_llm,
    _heuristic_score,
)


SNAPSHOT_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..",
    "tests", "eval_cases", "synthetic", "run_snapshot_sample_001.json"
)
RUBRIC_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..",
    "evaluators", "rubrics", "business_model_validation.yaml"
)


class TestShouldUseLLM(unittest.TestCase):
    """Test _should_use_llm decision logic."""

    def test_heuristic_mode_returns_false(self):
        """heuristic mode should always return False."""
        self.assertFalse(_should_use_llm("citation_accuracy", "heuristic"))
        self.assertFalse(_should_use_llm("legal_citation_quality", "heuristic"))

    def test_llm_mode_returns_true(self):
        """llm mode should always return True."""
        self.assertTrue(_should_use_llm("citation_accuracy", "llm"))

    def test_hybrid_mode_returns_true_for_llm_criteria(self):
        """hybrid mode with config should return True for criteria_requiring_llm."""
        config = {
            "judge_strategy": {
                "criteria_requiring_llm": [
                    "legal_citation_quality",
                    "jurisdiction_awareness",
                ]
            }
        }
        self.assertTrue(
            _should_use_llm("legal_citation_quality", "hybrid", config)
        )
        self.assertTrue(
            _should_use_llm("jurisdiction_awareness", "hybrid", config)
        )


class TestEvaluateCriterionHeuristic(unittest.TestCase):
    """Test evaluate_criterion in heuristic mode (backward compat)."""

    @classmethod
    def setUpClass(cls):
        cls.snapshot = load_json(SNAPSHOT_PATH)
        cls.rubric = load_yaml(RUBRIC_PATH)
        cls.criterion = cls.rubric["criteria"][0]

    def test_heuristic_mode_no_extra_fields(self):
        """heuristic mode should not produce llm_reasoning or confidence."""
        result = evaluate_criterion(self.criterion, self.snapshot, judge_mode="heuristic")
        self.assertEqual(result["judged_by"], "heuristic")
        self.assertNotIn("llm_reasoning", result)
        self.assertNotIn("confidence", result)

    def test_heuristic_mode_returns_score(self):
        """heuristic mode should return a score in [0, 1]."""
        result = evaluate_criterion(self.criterion, self.snapshot, judge_mode="heuristic")
        self.assertIn("score", result)
        self.assertGreaterEqual(result["score"], 0.0)
        self.assertLessEqual(result["score"], 1.0)

    def test_heuristic_mode_matches_original(self):
        """heuristic mode score should match original _heuristic_score."""
        cid = self.criterion["id"]
        expected = _heuristic_score(cid, self.snapshot)
        result = evaluate_criterion(self.criterion, self.snapshot, judge_mode="heuristic")
        self.assertEqual(result["score"], expected)


class TestRunSingleHeuristicBackwardCompat(unittest.TestCase):
    """Test run_single in heuristic mode (backward compat with Phase 5)."""

    @classmethod
    def setUpClass(cls):
        cls.snapshot_path = SNAPSHOT_PATH
        cls.rubric_path = RUBRIC_PATH

    def test_run_single_heuristic_basic(self):
        """run_single with heuristic mode should produce valid report."""
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            output_path = f.name
        try:
            report = run_single(
                self.snapshot_path, self.rubric_path, output_path,
                judge_mode="heuristic"
            )
            self.assertIn("score", report)
            self.assertIn("passed", report)
            self.assertIn("metrics", report)
            self.assertIn("findings", report)
            self.assertIn("suggestions", report)
            self.assertIn("heuristic", report["evaluated_by"])
            # Verify output file exists
            self.assertTrue(os.path.exists(output_path))
            with open(output_path) as f:
                saved = json.load(f)
            self.assertEqual(saved["score"], report["score"])
        finally:
            os.unlink(output_path)

    def test_run_single_heuristic_eight_dimensions(self):
        """heuristic mode should report all 8 dimensions."""
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            output_path = f.name
        try:
            report = run_single(
                self.snapshot_path, self.rubric_path, output_path,
                judge_mode="heuristic"
            )
            expected_dims = [
                "citation_accuracy", "constraint_compliance",
                "format_compliance", "risk_detection",
                "human_modification_rate", "output_adoption_rate",
                "high_risk_miss_rate", "cost_latency",
            ]
            for dim in expected_dims:
                self.assertIn(dim, report["metrics"])
        finally:
            os.unlink(output_path)


class TestEvaluateCriterionHybridMode(unittest.TestCase):
    """Test evaluate_criterion in hybrid mode (using mock for LLM branch)."""

    @classmethod
    def setUpClass(cls):
        cls.snapshot = load_json(SNAPSHOT_PATH)
        cls.rubric = load_yaml(RUBRIC_PATH)
        cls.criterion = cls.rubric["criteria"][0]
        cls.judge_config = {
            "judge_strategy": {
                "criteria_requiring_llm": ["fact_assumption_separation"],
                "low_score_threshold": 0.4,
            },
            "llm": {"model": "test-model"},
        }

    @patch("eval_runner.judge_criterion")
    def test_hybrid_llm_success(self, mock_judge):
        """hybrid mode should call LLM when criterion matches criteria_requiring_llm."""
        from llm_judge import JudgeResult
        mock_judge.return_value = JudgeResult(
            score=0.88, reasoning="LLM says good",
            evidence=["ev1"], confidence=0.9
        )
        result = evaluate_criterion(
            {"id": "fact_assumption_separation", "weight": 0.15, "description": "test"},
            self.snapshot,
            judge_mode="hybrid",
            judge_config=self.judge_config,
        )
        self.assertEqual(result["judged_by"], "llm")
        self.assertEqual(result["score"], 0.88)
        self.assertEqual(result["llm_reasoning"], "LLM says good")
        self.assertEqual(result["confidence"], 0.9)

    @patch("eval_runner.judge_criterion")
    def test_hybrid_llm_failure_fallback(self, mock_judge):
        """hybrid mode should fall back to heuristic when LLM fails."""
        from llm_judge import LLMConnectionError
        mock_judge.side_effect = LLMConnectionError("API unavailable")
        result = evaluate_criterion(
            {"id": "fact_assumption_separation", "weight": 0.15, "description": "test"},
            self.snapshot,
            judge_mode="hybrid",
            judge_config=self.judge_config,
        )
        self.assertIn("fallback", result["judged_by"])
        self.assertIn("score", result)
        self.assertGreaterEqual(result["score"], 0.0)

    @patch("eval_runner.judge_criterion")
    def test_hybrid_llm_response_error_fallback(self, mock_judge):
        """hybrid mode should fall back on LLMResponseError."""
        from llm_judge import LLMResponseError
        mock_judge.side_effect = LLMResponseError("Bad parse")
        result = evaluate_criterion(
            {"id": "fact_assumption_separation", "weight": 0.15, "description": "test"},
            self.snapshot,
            judge_mode="hybrid",
            judge_config=self.judge_config,
        )
        self.assertIn("fallback", result["judged_by"])


if __name__ == "__main__":
    unittest.main()
