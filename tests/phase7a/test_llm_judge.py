#!/usr/bin/env python3
"""
tests/phase7a/test_llm_judge.py — Phase 7a LLM Judge 模块自动化测试

测试范围:
  - JudgeResult 数据类构造和序列化
  - _parse_judge_response 容错 JSON 解析
  - load_judge_config 配置加载（默认 + 文件）
  - _call_llm 异常处理
  - _format_sources / _format_constraints / _format_output 格式化工具
"""

import json
import os
import sys
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "scripts"))

from llm_judge import (
    JudgeResult,
    LLMJudgeError,
    LLMConnectionError,
    LLMResponseError,
    load_judge_config,
    _parse_judge_response,
    _format_sources,
    _format_constraints,
    _format_output,
)


class TestJudgeResult(unittest.TestCase):
    """Test JudgeResult dataclass construction and serialization."""

    def test_default_construction(self):
        """JudgeResult default values should be safe defaults."""
        r = JudgeResult()
        self.assertEqual(r.score, 0.0)
        self.assertEqual(r.reasoning, "")
        self.assertEqual(r.evidence, [])
        self.assertEqual(r.confidence, 0.0)

    def test_full_construction(self):
        """JudgeResult with all fields populated."""
        r = JudgeResult(
            score=0.85,
            reasoning="Good citation quality",
            evidence=["src1: correctly cited", "src2: partial match"],
            confidence=0.92,
        )
        self.assertEqual(r.score, 0.85)
        self.assertEqual(r.reasoning, "Good citation quality")
        self.assertEqual(len(r.evidence), 2)
        self.assertEqual(r.confidence, 0.92)

    def test_to_dict(self):
        """to_dict() should return a dict with all fields."""
        r = JudgeResult(score=0.75, reasoning="OK", evidence=["e1"], confidence=0.8)
        d = r.to_dict()
        self.assertIsInstance(d, dict)
        self.assertEqual(d["score"], 0.75)
        self.assertEqual(d["reasoning"], "OK")
        self.assertEqual(d["evidence"], ["e1"])
        self.assertEqual(d["confidence"], 0.8)


class TestParseJudgeResponse(unittest.TestCase):
    """Test _parse_judge_response JSON parsing with various formats."""

    def test_standard_json(self):
        """Standard valid JSON should parse correctly."""
        raw = '{"score": 0.85, "reasoning": "Good", "evidence": ["e1"], "confidence": 0.9}'
        r = _parse_judge_response(raw)
        self.assertEqual(r.score, 0.85)
        self.assertEqual(r.reasoning, "Good")
        self.assertEqual(r.evidence, ["e1"])
        self.assertEqual(r.confidence, 0.9)

    def test_reason_fallback(self):
        """Should accept 'reason' as alternative to 'reasoning'."""
        raw = '{"score": 0.7, "reason": "Alt key", "evidence": [], "confidence": 0.8}'
        r = _parse_judge_response(raw)
        self.assertEqual(r.reasoning, "Alt key")

    def test_evidences_fallback(self):
        """Should accept 'evidences' as alternative to 'evidence'."""
        raw = '{"score": 0.6, "reasoning": "x", "evidences": ["a", "b"], "confidence": 0.7}'
        r = _parse_judge_response(raw)
        self.assertEqual(r.evidence, ["a", "b"])

    def test_markdown_fence_json(self):
        """Should strip markdown code fences from response."""
        raw = '```json\n{"score": 0.9, "reasoning": "Great", "evidence": ["e1"], "confidence": 0.95}\n```'
        r = _parse_judge_response(raw)
        self.assertEqual(r.score, 0.9)
        self.assertEqual(r.reasoning, "Great")

    def test_score_clamping(self):
        """Score should be clamped to [0.0, 1.0]."""
        raw = '{"score": 2.5, "reasoning": "Over", "evidence": [], "confidence": 1.0}'
        r = _parse_judge_response(raw)
        self.assertEqual(r.score, 1.0)

        raw2 = '{"score": -0.5, "reasoning": "Under", "evidence": [], "confidence": 1.0}'
        r2 = _parse_judge_response(raw2)
        self.assertEqual(r2.score, 0.0)

    def test_confidence_clamping(self):
        """Confidence should be clamped to [0.0, 1.0]."""
        raw = '{"score": 0.5, "reasoning": "x", "evidence": [], "confidence": 1.5}'
        r = _parse_judge_response(raw)
        self.assertEqual(r.confidence, 1.0)

    def test_evidence_capped_at_10(self):
        """Evidence list should be capped at 10 items."""
        ev = [f"e{i}" for i in range(15)]
        raw = json.dumps({"score": 0.5, "reasoning": "x", "evidence": ev, "confidence": 0.5})
        r = _parse_judge_response(raw)
        self.assertLessEqual(len(r.evidence), 10)

    def test_non_json_raises_error(self):
        """Non-JSON response should raise LLMResponseError."""
        with self.assertRaises(LLMResponseError):
            _parse_judge_response("this is not json at all")

    def test_empty_string_raises_error(self):
        """Empty string should raise LLMResponseError."""
        with self.assertRaises(LLMResponseError):
            _parse_judge_response("")


class TestLoadJudgeConfig(unittest.TestCase):
    """Test load_judge_config default and file loading."""

    def test_default_config(self):
        """Default config should have expected keys and values."""
        config = load_judge_config()
        self.assertEqual(config["default_mode"], "heuristic")
        self.assertIn("legal_citation_quality", config["llm_criteria"])
        self.assertEqual(config["fallback_mode"], "heuristic")
        self.assertEqual(config["llm_model"], "deepseek-chat")
        self.assertEqual(config["max_tokens"], 1024)
        self.assertEqual(config["temperature"], 0.3)

    def test_nonexistent_file_fallback(self):
        """Non-existent config file path should return defaults."""
        config = load_judge_config("/nonexistent/path.yaml")
        self.assertEqual(config["default_mode"], "heuristic")

    def test_file_loading(self):
        """Loading from actual file should return correct values."""
        config_path = os.path.join(
            os.path.dirname(__file__), "..", "..",
            "evaluators", "rubrics", "shared_judge_config.yaml"
        )
        config = load_judge_config(config_path)
        strategy = config.get("judge_strategy", {})
        self.assertEqual(strategy.get("default_mode"), "hybrid")
        self.assertIn("legal_citation_quality", strategy.get("criteria_requiring_llm", []))
        self.assertEqual(strategy.get("low_score_threshold"), 0.4)
        self.assertEqual(strategy.get("fallback_mode"), "heuristic")
        self.assertEqual(config.get("llm", {}).get("model"), "deepseek-chat")


class TestFormatHelpers(unittest.TestCase):
    """Test _format_sources, _format_constraints, _format_output."""

    def test_format_sources_empty(self):
        self.assertIn("no sources", _format_sources([]))

    def test_format_sources_with_data(self):
        sources = [
            {"source_id": "doc1", "title": "Doc One", "snippet": "Some content here"}
        ]
        result = _format_sources(sources)
        self.assertIn("doc1", result)
        self.assertIn("Doc One", result)

    def test_format_constraints_empty(self):
        self.assertIn("no constraints", _format_constraints([]))

    def test_format_constraints_with_data(self):
        constraints = [
            {"constraint_id": "c1", "severity": "high", "message": "Must cite sources"}
        ]
        result = _format_constraints(constraints)
        self.assertIn("high", result)
        self.assertIn("c1", result)

    def test_format_output_empty(self):
        self.assertIn("empty", _format_output({}))

    def test_format_output_with_data(self):
        result = _format_output({"key": "value"})
        self.assertIn("key", result)
        self.assertIn("value", result)


if __name__ == "__main__":
    unittest.main()
