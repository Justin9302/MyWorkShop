#!/usr/bin/env python3
"""
tests/phase7a/test_schema_validation.py — Phase 7a JSON Schema 兼容性测试

测试范围:
  - 含 llm_reasoning/confidence 字段的报告通过 Schema 校验
  - 不含新字段（旧格式）的报告仍然通过 Schema 校验
  - 新字段类型和约束正确
"""

import json
import os
import sys
import unittest

try:
    import jsonschema
    HAS_JSONSCHEMA = True
except ImportError:
    HAS_JSONSCHEMA = False


SCHEMA_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..",
    "schemas", "eval_report.schema.json"
)

SAMPLE_SNAPSHOT_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..",
    "tests", "eval_cases", "synthetic", "run_snapshot_sample_001.json"
)


def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


@unittest.skipIf(not HAS_JSONSCHEMA, "jsonschema package not installed")
class TestEvalReportSchema(unittest.TestCase):
    """Test eval_report.schema.json backward and forward compatibility."""

    @classmethod
    def setUpClass(cls):
        cls.schema = load_json(SCHEMA_PATH)

    def test_new_fields_exist_in_schema(self):
        """Schema should define llm_reasoning and confidence in findings."""
        findings_props = self.schema["properties"]["findings"]["items"]["properties"]
        self.assertIn("llm_reasoning", findings_props)
        self.assertIn("confidence", findings_props)

    def test_llm_reasoning_type(self):
        """llm_reasoning should be type string."""
        findings_props = self.schema["properties"]["findings"]["items"]["properties"]
        self.assertEqual(findings_props["llm_reasoning"]["type"], "string")

    def test_confidence_type_and_range(self):
        """confidence should be number with min 0 max 1."""
        findings_props = self.schema["properties"]["findings"]["items"]["properties"]
        conf = findings_props["confidence"]
        self.assertEqual(conf["type"], "number")
        self.assertEqual(conf["minimum"], 0)
        self.assertEqual(conf["maximum"], 1)

    def test_new_fields_not_required(self):
        """llm_reasoning and confidence should not be in the required list."""
        findings_required = self.schema["properties"]["findings"]["items"]["required"]
        self.assertNotIn("llm_reasoning", findings_required)
        self.assertNotIn("confidence", findings_required)

    def test_valid_report_with_new_fields(self):
        """A report with llm_reasoning and confidence should pass schema."""
        report = self._make_minimal_report()
        report["findings"] = [
            {
                "type": "citation_gap",
                "severity": "high",
                "message": "Missing citation",
                "llm_reasoning": "The output fails to cite source document #3",
                "confidence": 0.88,
            }
        ]
        try:
            jsonschema.validate(report, self.schema)
        except jsonschema.ValidationError as e:
            self.fail(f"Schema validation failed with new fields: {e}")

    def test_valid_report_without_new_fields(self):
        """A report without llm_reasoning/confidence should still pass (backward compat)."""
        report = self._make_minimal_report()
        report["findings"] = [
            {
                "type": "constraint_violation",
                "severity": "medium",
                "message": "Constraint not met",
            }
        ]
        try:
            jsonschema.validate(report, self.schema)
        except jsonschema.ValidationError as e:
            self.fail(f"Schema validation failed for backward compat: {e}")

    def test_mixed_findings(self):
        """Report with some findings having LLM fields and some not should pass."""
        report = self._make_minimal_report()
        report["findings"] = [
            {
                "type": "citation_gap",
                "severity": "high",
                "message": "LLM-found issue",
                "llm_reasoning": "Deep analysis here",
                "confidence": 0.95,
            },
            {
                "type": "format_error",
                "severity": "low",
                "message": "Heuristic-found issue",
            },
        ]
        try:
            jsonschema.validate(report, self.schema)
        except jsonschema.ValidationError as e:
            self.fail(f"Schema validation failed for mixed findings: {e}")

    def _make_minimal_report(self):
        """Create a minimal valid eval_report for schema testing."""
        return {
            "run_id": "test_run_001",
            "workflow_id": "business_model_validation",
            "rubric_id": "test_rubric",
            "evaluator_version": "0.1.0",
            "evaluation_mode": "async_nonblocking",
            "score": 0.75,
            "risk_level": "medium",
            "passed": True,
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


if __name__ == "__main__":
    unittest.main()
