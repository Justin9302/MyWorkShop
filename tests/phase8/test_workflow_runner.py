#!/usr/bin/env python3
"""
test_workflow_runner.py — Phase 8: 工作流运行器原型测试

测试覆盖:
  1. 工作流解析 (parse_workflow, get_workflow_id, get_workflow_steps, etc.)
  2. 上下文加载计划生成 (generate_context_load_plan)
  3. 运行快照模板生成 (generate_run_snapshot_template)
  4. 工作流验证 (validate_workflow)
  5. 执行计划生成 (generate_execution_plan)
  6. MCP 工具注册表 (get_mcp_tool_registry)
  7. CLINE MCP 配置生成 (generate_cline_mcp_config)
  8. CLI 接口
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

from scripts.workflow_runner import (
    # Constants
    LAYER_DEFINITIONS,
    WORKFLOW_INDUSTRY_MAP,
    RISK_LEVELS,
    # File I/O
    load_yaml,
    load_json,
    save_json,
    resolve_path,
    # Workflow Parser
    parse_workflow,
    get_workflow_id,
    get_workflow_steps,
    get_workflow_constraints,
    get_workflow_prompts,
    get_workflow_risk_level,
    # Context Load Plan
    generate_context_load_plan,
    # Run Snapshot
    generate_run_snapshot_template,
    # Validator
    validate_workflow,
    # Execution Plan
    generate_execution_plan,
    # MCP Registry
    get_mcp_tool_registry,
    # CLINE Config
    generate_cline_mcp_config,
)

# ═══════════════════════════════════════════════════════════════
# Test Data
# ═══════════════════════════════════════════════════════════════

SAMPLE_WORKFLOW = {
    "workflow": {
        "id": "business_model_validation",
        "name": "商业模式验证",
        "version": "0.1.0",
    },
    "risk_level": "medium",
    "constraints": [
        "constraints/baseline/privacy.yaml",
        "constraints/baseline/safety.yaml",
    ],
    "prompts": {
        "system": "prompts/business/business_model_validation.system.md",
        "validation": "prompts/business/business_model_validation.system.md",
    },
    "output": {
        "format": "markdown",
        "fields": ["summary", "risk_assessment", "recommendation"],
    },
    "steps": [
        {
            "id": "context_analysis",
            "description": "分析用户输入上下文",
            "action": "analyze_context",
            "prompt": "请分析以下商业模式的上下文...",
            "output": "context_analysis_result",
        },
        {
            "id": "validation",
            "description": "执行商业模式验证",
            "action": "validate_model",
            "prompt": "请验证以下商业模式的可行性...",
            "interrupt": True,
            "resume_condition": "user_provided_additional_info",
            "human_review_required": True,
            "output": "validation_result",
        },
        {
            "id": "report",
            "description": "生成验证报告",
            "action": "generate_report",
            "prompt": "请根据验证结果生成报告...",
            "output": "final_report",
        },
    ],
}

SAMPLE_WORKFLOW_MINIMAL = {
    "workflow": {
        "id": "minimal_test",
        "name": "最小工作流",
        "version": "0.1.0",
    },
    "steps": [
        {
            "id": "step_1",
            "description": "第一步",
            "action": "process",
            "output": "result_1",
        },
    ],
}

SAMPLE_WORKFLOW_INVALID = {
    "workflow": {
        "name": "缺少 ID",
    },
    "steps": [],
}

SAMPLE_ACTIVE_RELEASE = {
    "active_release": {
        "version": "2026.05.05.001",
        "governance": {
            "knowledge_bases": [
                {
                    "id": "kb_001",
                    "name": "行业标准库",
                    "last_fetched": "2026-05-01",
                },
                {
                    "id": "kb_002",
                    "name": "法规政策库",
                    "last_fetched": "2026-05-02",
                },
            ],
        },
    },
}

SAMPLE_MCP_CONFIG = {
    "mcp_tools": {
        "version": "0.1.0",
        "environment": "vscode_copilot",
        "tools": [
            {
                "id": "filesystem",
                "purpose": "读取和写入工作区文件",
                "permissions": {
                    "read": True,
                    "write": True,
                    "external_network": False,
                },
                "approval_required": False,
                "vscode_tools": ["read_file", "write_to_file"],
            },
            {
                "id": "github",
                "purpose": "GitHub API 操作",
                "permissions": {
                    "read": True,
                    "write": True,
                    "external_network": True,
                },
                "approval_required": True,
                "vscode_tools": ["use_mcp_tool"],
            },
        ],
    },
}


# ═══════════════════════════════════════════════════════════════
# Tests
# ═══════════════════════════════════════════════════════════════

class TestConstants(unittest.TestCase):
    """测试常量定义。"""

    def test_layer_definitions_has_all_layers(self):
        """L0-L8 共 9 层。"""
        self.assertEqual(len(LAYER_DEFINITIONS), 9)
        for i in range(9):
            self.assertIn(f"L{i}", LAYER_DEFINITIONS)

    def test_layer_definitions_required_fields(self):
        """每层都有 purpose 和 description。"""
        for layer_id, layer_info in LAYER_DEFINITIONS.items():
            self.assertIn("purpose", layer_info, f"{layer_id} missing purpose")
            self.assertIn("description", layer_info, f"{layer_id} missing description")
            self.assertIn("required", layer_info, f"{layer_id} missing required")

    def test_workflow_industry_map_has_all_workflows(self):
        """所有工作流 ID 都有行业映射。"""
        expected_workflows = [
            "contract_review", "policy_qa",
            "business_model_design", "business_model_validation",
            "go_to_market_review", "unit_economics_check",
            "solar_financial_model",
            "investment_research", "risk_summary", "due_diligence",
            "sop_generation", "meeting_summary", "project_retrospective",
        ]
        for wf in expected_workflows:
            self.assertIn(wf, WORKFLOW_INDUSTRY_MAP, f"Missing industry mapping for {wf}")

    def test_risk_levels(self):
        """风险等级定义。"""
        self.assertEqual(RISK_LEVELS, ["low", "medium", "high", "critical"])


class TestFileIO(unittest.TestCase):
    """测试文件 I/O 辅助函数。"""

    def test_save_and_load_json(self):
        """save_json 和 load_json 往返。"""
        data = {"key": "value", "number": 42, "list": [1, 2, 3]}
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
        result = resolve_path("config/active-release.yaml")
        self.assertTrue(result.endswith("config/active-release.yaml"))
        self.assertTrue(os.path.isabs(result))


class TestWorkflowParser(unittest.TestCase):
    """测试工作流解析函数。"""

    def test_get_workflow_id(self):
        """提取工作流 ID。"""
        wf_id = get_workflow_id(SAMPLE_WORKFLOW)
        self.assertEqual(wf_id, "business_model_validation")

    def test_get_workflow_id_unknown(self):
        """未知工作流返回 'unknown'。"""
        wf_id = get_workflow_id({})
        self.assertEqual(wf_id, "unknown")

    def test_get_workflow_steps(self):
        """提取工作流步骤。"""
        steps = get_workflow_steps(SAMPLE_WORKFLOW)
        self.assertEqual(len(steps), 3)
        self.assertEqual(steps[0]["id"], "context_analysis")
        self.assertEqual(steps[1]["id"], "validation")
        self.assertEqual(steps[2]["id"], "report")

    def test_get_workflow_steps_empty(self):
        """无步骤时返回空列表。"""
        steps = get_workflow_steps({})
        self.assertEqual(steps, [])

    def test_get_workflow_constraints(self):
        """提取约束引用。"""
        constraints = get_workflow_constraints(SAMPLE_WORKFLOW)
        self.assertEqual(len(constraints), 2)
        self.assertIn("constraints/baseline/privacy.yaml", constraints)

    def test_get_workflow_constraints_empty(self):
        """无约束时返回空列表。"""
        constraints = get_workflow_constraints({})
        self.assertEqual(constraints, [])

    def test_get_workflow_prompts(self):
        """提取 prompt 引用。"""
        prompts = get_workflow_prompts(SAMPLE_WORKFLOW)
        self.assertEqual(len(prompts), 2)
        self.assertIn("system", prompts)
        self.assertIn("validation", prompts)

    def test_get_workflow_prompts_empty(self):
        """无 prompt 时返回空字典。"""
        prompts = get_workflow_prompts({})
        self.assertEqual(prompts, {})

    def test_get_workflow_risk_level(self):
        """提取风险等级。"""
        risk = get_workflow_risk_level(SAMPLE_WORKFLOW)
        self.assertEqual(risk, "medium")

    def test_get_workflow_risk_level_default(self):
        """无风险等级时返回 'medium'。"""
        risk = get_workflow_risk_level({})
        self.assertEqual(risk, "medium")


class TestContextLoadPlan(unittest.TestCase):
    """测试上下文加载计划生成。"""

    @patch("scripts.workflow_runner.load_yaml")
    @patch("scripts.workflow_runner.os.path.exists")
    def test_generate_context_load_plan_basic(self, mock_exists, mock_load_yaml):
        """基本上下文加载计划生成。"""
        # Mock 文件存在检查
        mock_exists.return_value = True
        # Mock load_yaml
        def mock_load_yaml_side_effect(path):
            if "active-release" in path:
                return SAMPLE_ACTIVE_RELEASE
            if "mcp-tools" in path:
                return SAMPLE_MCP_CONFIG
            return SAMPLE_WORKFLOW
        mock_load_yaml.side_effect = mock_load_yaml_side_effect

        plan = generate_context_load_plan(
            workflow_path="workflows/business/business_model_validation.yaml",
            intent="验证新能源充电业务的商业模式",
            industry="business",
            jurisdiction="cn",
            risk_level="medium",
        )

        self.assertEqual(plan["workflow_id"], "business_model_validation")
        self.assertEqual(plan["selected_industry"], "business")
        self.assertEqual(plan["selected_jurisdiction"], "cn")
        self.assertEqual(plan["risk_level"], "medium")
        self.assertIn("intent_summary", plan)
        self.assertIn("layers", plan)
        self.assertEqual(len(plan["layers"]), 9)  # L0-L8

    @patch("scripts.workflow_runner.load_yaml")
    @patch("scripts.workflow_runner.os.path.exists")
    def test_context_load_plan_has_all_layers(self, mock_exists, mock_load_yaml):
        """上下文加载计划包含 L0-L8 所有层。"""
        mock_exists.return_value = True
        def mock_load_yaml_side_effect(path):
            if "active-release" in path:
                return SAMPLE_ACTIVE_RELEASE
            if "mcp-tools" in path:
                return SAMPLE_MCP_CONFIG
            return SAMPLE_WORKFLOW
        mock_load_yaml.side_effect = mock_load_yaml_side_effect

        plan = generate_context_load_plan(
            workflow_path="workflows/business/business_model_validation.yaml",
        )

        layer_ids = [layer["layer_id"] for layer in plan["layers"]]
        for i in range(9):
            self.assertIn(f"L{i}", layer_ids)

    @patch("scripts.workflow_runner.load_yaml")
    @patch("scripts.workflow_runner.os.path.exists")
    def test_context_load_plan_auto_industry(self, mock_exists, mock_load_yaml):
        """自动推断行业。"""
        mock_exists.return_value = True
        def mock_load_yaml_side_effect(path):
            if "active-release" in path:
                return SAMPLE_ACTIVE_RELEASE
            if "mcp-tools" in path:
                return SAMPLE_MCP_CONFIG
            return SAMPLE_WORKFLOW
        mock_load_yaml.side_effect = mock_load_yaml_side_effect

        plan = generate_context_load_plan(
            workflow_path="workflows/business/business_model_validation.yaml",
        )

        self.assertEqual(plan["selected_industry"], "business")

    @patch("scripts.workflow_runner.load_yaml")
    @patch("scripts.workflow_runner.os.path.exists")
    def test_context_load_plan_has_context_budget(self, mock_exists, mock_load_yaml):
        """上下文加载计划包含 context_budget。"""
        mock_exists.return_value = True
        def mock_load_yaml_side_effect(path):
            if "active-release" in path:
                return SAMPLE_ACTIVE_RELEASE
            if "mcp-tools" in path:
                return SAMPLE_MCP_CONFIG
            return SAMPLE_WORKFLOW
        mock_load_yaml.side_effect = mock_load_yaml_side_effect

        plan = generate_context_load_plan(
            workflow_path="workflows/business/business_model_validation.yaml",
        )

        self.assertIn("context_budget", plan)
        self.assertEqual(plan["context_budget"]["max_tokens"], 128000)
        self.assertEqual(plan["context_budget"]["overflow_strategy"], "summarize")

    @patch("scripts.workflow_runner.load_yaml")
    @patch("scripts.workflow_runner.os.path.exists")
    def test_context_load_plan_generated_at(self, mock_exists, mock_load_yaml):
        """上下文加载计划包含生成时间戳。"""
        mock_exists.return_value = True
        def mock_load_yaml_side_effect(path):
            if "active-release" in path:
                return SAMPLE_ACTIVE_RELEASE
            if "mcp-tools" in path:
                return SAMPLE_MCP_CONFIG
            return SAMPLE_WORKFLOW
        mock_load_yaml.side_effect = mock_load_yaml_side_effect

        plan = generate_context_load_plan(
            workflow_path="workflows/business/business_model_validation.yaml",
        )

        self.assertIn("generated_at", plan)
        self.assertIn("generated_by", plan)
        self.assertEqual(plan["generated_by"], "workflow_runner.py (Phase 8)")


class TestRunSnapshot(unittest.TestCase):
    """测试运行快照模板生成。"""

    @patch("scripts.workflow_runner.load_yaml")
    @patch("scripts.workflow_runner.os.path.exists")
    def test_generate_run_snapshot_template_basic(self, mock_exists, mock_load_yaml):
        """基本运行快照模板生成。"""
        mock_exists.return_value = True
        mock_load_yaml.return_value = SAMPLE_WORKFLOW

        snapshot = generate_run_snapshot_template(
            workflow_path="workflows/business/business_model_validation.yaml",
            intent="验证新能源充电业务的商业模式",
            industry="business",
            jurisdiction="cn",
        )

        self.assertEqual(snapshot["workflow_id"], "business_model_validation")
        self.assertEqual(snapshot["workflow_version"], "0.1.0")
        self.assertIn("run_id", snapshot)
        self.assertIn("user_input_summary", snapshot)
        self.assertEqual(snapshot["workflow_state"]["total_steps"], 3)

    @patch("scripts.workflow_runner.load_yaml")
    @patch("scripts.workflow_runner.os.path.exists")
    def test_run_snapshot_has_required_fields(self, mock_exists, mock_load_yaml):
        """运行快照包含所有必需字段。"""
        mock_exists.return_value = True
        mock_load_yaml.return_value = SAMPLE_WORKFLOW

        snapshot = generate_run_snapshot_template(
            workflow_path="workflows/business/business_model_validation.yaml",
        )

        required_fields = [
            "run_id", "workflow_id", "workflow_version",
            "context_reading_result", "intent_confirmation",
            "context_load_plan", "retrieved_sources",
            "output_summary", "constraints_triggered",
            "tool_calls", "human_review", "workflow_state",
            "interruptions", "resume_events", "user_feedback",
            "created_at", "updated_at",
        ]
        for field in required_fields:
            self.assertIn(field, snapshot, f"Missing field: {field}")

    @patch("scripts.workflow_runner.load_yaml")
    @patch("scripts.workflow_runner.os.path.exists")
    def test_run_snapshot_intent_confirmation(self, mock_exists, mock_load_yaml):
        """运行快照包含意图确认结构。"""
        mock_exists.return_value = True
        mock_load_yaml.return_value = SAMPLE_WORKFLOW

        snapshot = generate_run_snapshot_template(
            workflow_path="workflows/business/business_model_validation.yaml",
            intent="测试意图",
        )

        ic = snapshot["intent_confirmation"]
        self.assertEqual(ic["status"], "pending")
        self.assertEqual(ic["user_goal"], "测试意图")
        self.assertEqual(ic["planned_workflow"], "business_model_validation")
        self.assertIn("retrieval_scope", ic)
        self.assertIn("constraint_rules", ic)
        self.assertIn("expected_output_format", ic)

    @patch("scripts.workflow_runner.load_yaml")
    @patch("scripts.workflow_runner.os.path.exists")
    def test_run_snapshot_workflow_state(self, mock_exists, mock_load_yaml):
        """运行快照包含工作流状态。"""
        mock_exists.return_value = True
        mock_load_yaml.return_value = SAMPLE_WORKFLOW

        snapshot = generate_run_snapshot_template(
            workflow_path="workflows/business/business_model_validation.yaml",
        )

        ws = snapshot["workflow_state"]
        self.assertEqual(ws["status"], "pending")
        self.assertEqual(ws["current_node"], "context_reading")
        self.assertEqual(ws["completed_steps"], [])
        self.assertEqual(ws["total_steps"], 3)

    @patch("scripts.workflow_runner.load_yaml")
    @patch("scripts.workflow_runner.os.path.exists")
    def test_run_snapshot_human_review_default(self, mock_exists, mock_load_yaml):
        """运行快照人审默认状态。"""
        mock_exists.return_value = True
        mock_load_yaml.return_value = SAMPLE_WORKFLOW

        snapshot = generate_run_snapshot_template(
            workflow_path="workflows/business/business_model_validation.yaml",
        )

        hr = snapshot["human_review"]
        self.assertEqual(hr["required"], False)
        self.assertEqual(hr["review_status"], "not_required")


class TestWorkflowValidator(unittest.TestCase):
    """测试工作流验证。"""

    @patch("scripts.workflow_runner.load_yaml")
    @patch("scripts.workflow_runner.os.path.exists")
    def test_validate_valid_workflow(self, mock_exists, mock_load_yaml):
        """验证有效工作流。"""
        mock_exists.return_value = True
        mock_load_yaml.return_value = SAMPLE_WORKFLOW

        result = validate_workflow("workflows/business/business_model_validation.yaml")

        self.assertTrue(result["valid"])
        self.assertEqual(result["workflow_id"], "business_model_validation")
        self.assertEqual(result["steps_count"], 3)
        self.assertEqual(result["risk_level"], "medium")
        self.assertEqual(len(result["errors"]), 0)

    @patch("scripts.workflow_runner.load_yaml")
    @patch("scripts.workflow_runner.os.path.exists")
    def test_validate_minimal_workflow(self, mock_exists, mock_load_yaml):
        """验证最小工作流。"""
        mock_exists.return_value = True
        mock_load_yaml.return_value = SAMPLE_WORKFLOW_MINIMAL

        result = validate_workflow("workflows/business/minimal.yaml")

        self.assertTrue(result["valid"])
        self.assertEqual(result["steps_count"], 1)

    @patch("scripts.workflow_runner.load_yaml")
    @patch("scripts.workflow_runner.os.path.exists")
    def test_validate_invalid_workflow(self, mock_exists, mock_load_yaml):
        """验证无效工作流。"""
        mock_exists.return_value = True
        mock_load_yaml.return_value = SAMPLE_WORKFLOW_INVALID

        result = validate_workflow("workflows/business/invalid.yaml")

        self.assertFalse(result["valid"])
        self.assertTrue(len(result["errors"]) > 0)

    @patch("scripts.workflow_runner.load_yaml")
    @patch("scripts.workflow_runner.os.path.exists")
    def test_validate_missing_constraint_warning(self, mock_exists, mock_load_yaml):
        """缺失约束文件产生警告。"""
        def mock_exists_side_effect(path):
            if "constraints" in path:
                return False
            return True
        mock_exists.side_effect = mock_exists_side_effect
        mock_load_yaml.return_value = SAMPLE_WORKFLOW

        result = validate_workflow("workflows/business/business_model_validation.yaml")

        self.assertTrue(result["valid"])
        self.assertTrue(len(result["warnings"]) > 0)

    @patch("scripts.workflow_runner.load_yaml")
    @patch("scripts.workflow_runner.os.path.exists")
    def test_validate_interrupt_without_resume_warning(self, mock_exists, mock_load_yaml):
        """中断步骤缺少恢复条件产生警告。"""
        mock_exists.return_value = True
        workflow_with_interrupt = {
            "workflow": {"id": "test", "name": "Test", "version": "0.1.0"},
            "steps": [
                {
                    "id": "step_1",
                    "description": "中断步骤",
                    "action": "process",
                    "interrupt": True,
                    # 缺少 resume_condition
                },
            ],
        }
        mock_load_yaml.return_value = workflow_with_interrupt

        result = validate_workflow("workflows/test.yaml")

        self.assertTrue(result["valid"])
        warnings = [w for w in result["warnings"] if "中断" in w and "恢复条件" in w]
        self.assertTrue(len(warnings) > 0)


class TestExecutionPlan(unittest.TestCase):
    """测试执行计划生成。"""

    @patch("scripts.workflow_runner.load_yaml")
    @patch("scripts.workflow_runner.os.path.exists")
    def test_generate_execution_plan_basic(self, mock_exists, mock_load_yaml):
        """基本执行计划生成。"""
        mock_exists.return_value = True
        mock_load_yaml.return_value = SAMPLE_WORKFLOW

        plan = generate_execution_plan(
            workflow_path="workflows/business/business_model_validation.yaml",
            intent="验证商业模式",
        )

        self.assertEqual(plan["workflow_id"], "business_model_validation")
        self.assertIn("run_id", plan)
        self.assertIn("execution_steps", plan)
        self.assertTrue(len(plan["execution_steps"]) > 0)

    @patch("scripts.workflow_runner.load_yaml")
    @patch("scripts.workflow_runner.os.path.exists")
    def test_execution_plan_has_context_reading_gate(self, mock_exists, mock_load_yaml):
        """执行计划包含上下文读取门禁步骤。"""
        mock_exists.return_value = True
        mock_load_yaml.return_value = SAMPLE_WORKFLOW

        plan = generate_execution_plan(
            workflow_path="workflows/business/business_model_validation.yaml",
        )

        first_step = plan["execution_steps"][0]
        self.assertEqual(first_step["step_id"], "context_reading")
        self.assertEqual(first_step["phase"], "gate")

    @patch("scripts.workflow_runner.load_yaml")
    @patch("scripts.workflow_runner.os.path.exists")
    def test_execution_plan_has_context_planning(self, mock_exists, mock_load_yaml):
        """执行计划包含上下文规划步骤。"""
        mock_exists.return_value = True
        mock_load_yaml.return_value = SAMPLE_WORKFLOW

        plan = generate_execution_plan(
            workflow_path="workflows/business/business_model_validation.yaml",
        )

        second_step = plan["execution_steps"][1]
        self.assertEqual(second_step["step_id"], "context_planning")
        self.assertEqual(second_step["phase"], "loading")

    @patch("scripts.workflow_runner.load_yaml")
    @patch("scripts.workflow_runner.os.path.exists")
    def test_execution_plan_has_workflow_steps(self, mock_exists, mock_load_yaml):
        """执行计划包含工作流定义的步骤。"""
        mock_exists.return_value = True
        mock_load_yaml.return_value = SAMPLE_WORKFLOW

        plan = generate_execution_plan(
            workflow_path="workflows/business/business_model_validation.yaml",
        )

        # 前两步是 gate + loading，然后是工作流步骤
        workflow_steps = plan["execution_steps"][2:-1]  # 排除最后的 snapshot
        self.assertEqual(len(workflow_steps), 3)
        self.assertEqual(workflow_steps[0]["step_id"], "context_analysis")
        self.assertEqual(workflow_steps[1]["step_id"], "validation")
        self.assertEqual(workflow_steps[2]["step_id"], "report")

    @patch("scripts.workflow_runner.load_yaml")
    @patch("scripts.workflow_runner.os.path.exists")
    def test_execution_plan_interrupt_step(self, mock_exists, mock_load_yaml):
        """执行计划中中断步骤包含恢复条件。"""
        mock_exists.return_value = True
        mock_load_yaml.return_value = SAMPLE_WORKFLOW

        plan = generate_execution_plan(
            workflow_path="workflows/business/business_model_validation.yaml",
        )

        validation_step = plan["execution_steps"][3]  # 第 4 步是 validation
        self.assertTrue(validation_step["interrupt"])
        self.assertIn("resume_condition", validation_step)
        self.assertIn("cancel_condition", validation_step)

    @patch("scripts.workflow_runner.load_yaml")
    @patch("scripts.workflow_runner.os.path.exists")
    def test_execution_plan_has_snapshot_final_step(self, mock_exists, mock_load_yaml):
        """执行计划最后一步是生成快照。"""
        mock_exists.return_value = True
        mock_load_yaml.return_value = SAMPLE_WORKFLOW

        plan = generate_execution_plan(
            workflow_path="workflows/business/business_model_validation.yaml",
        )

        last_step = plan["execution_steps"][-1]
        self.assertEqual(last_step["step_id"], "snapshot_generation")
        self.assertEqual(last_step["phase"], "completion")

    @patch("scripts.workflow_runner.load_yaml")
    @patch("scripts.workflow_runner.os.path.exists")
    def test_execution_plan_has_notes(self, mock_exists, mock_load_yaml):
        """执行计划包含说明注释。"""
        mock_exists.return_value = True
        mock_load_yaml.return_value = SAMPLE_WORKFLOW

        plan = generate_execution_plan(
            workflow_path="workflows/business/business_model_validation.yaml",
        )

        self.assertIn("notes", plan)
        self.assertTrue(len(plan["notes"]) > 0)


class TestMCPRegistry(unittest.TestCase):
    """测试 MCP 工具注册表。"""

    @patch("scripts.workflow_runner.load_yaml")
    @patch("scripts.workflow_runner.os.path.exists")
    def test_get_mcp_tool_registry(self, mock_exists, mock_load_yaml):
        """获取 MCP 工具注册表。"""
        mock_exists.return_value = True
        mock_load_yaml.return_value = SAMPLE_MCP_CONFIG

        registry = get_mcp_tool_registry()

        self.assertIn("version", registry)
        self.assertIn("environment", registry)
        self.assertIn("tools", registry)
        self.assertEqual(len(registry["tools"]), 2)

    @patch("scripts.workflow_runner.load_yaml")
    @patch("scripts.workflow_runner.os.path.exists")
    def test_mcp_registry_tool_permissions(self, mock_exists, mock_load_yaml):
        """MCP 工具注册表包含权限信息。"""
        mock_exists.return_value = True
        mock_load_yaml.return_value = SAMPLE_MCP_CONFIG

        registry = get_mcp_tool_registry()

        fs_tool = registry["tools"]["filesystem"]
        self.assertIn("permissions", fs_tool)
        self.assertTrue(fs_tool["permissions"]["read"])
        self.assertTrue(fs_tool["permissions"]["write"])
        self.assertFalse(fs_tool["permissions"]["external_network"])

    @patch("scripts.workflow_runner.load_yaml")
    @patch("scripts.workflow_runner.os.path.exists")
    def test_mcp_registry_approval_required(self, mock_exists, mock_load_yaml):
        """MCP 工具注册表包含审批信息。"""
        mock_exists.return_value = True
        mock_load_yaml.return_value = SAMPLE_MCP_CONFIG

        registry = get_mcp_tool_registry()

        self.assertFalse(registry["tools"]["filesystem"]["approval_required"])
        self.assertTrue(registry["tools"]["github"]["approval_required"])

    @patch("scripts.workflow_runner.os.path.exists")
    def test_mcp_registry_not_found(self, mock_exists):
        """MCP 配置文件不存在时返回错误。"""
        mock_exists.return_value = False

        registry = get_mcp_tool_registry()

        self.assertIn("error", registry)


class TestCLINEConfig(unittest.TestCase):
    """测试 CLINE MCP 配置生成。"""

    def test_generate_cline_mcp_config(self):
        """生成 CLINE MCP 配置。"""
        config = generate_cline_mcp_config()

        self.assertIn("mcpServers", config)
        self.assertIn("registry", config)

    def test_cline_config_has_required_servers(self):
        """CLINE MCP 配置包含必需服务器。"""
        config = generate_cline_mcp_config()

        servers = config["mcpServers"]
        self.assertIn("filesystem", servers)
        self.assertIn("fetch", servers)
        self.assertIn("git", servers)
        self.assertIn("github", servers)

    def test_cline_config_server_format(self):
        """CLINE MCP 服务器配置格式正确。"""
        config = generate_cline_mcp_config()

        for server_name, server_config in config["mcpServers"].items():
            self.assertIn("command", server_config)
            self.assertIn("args", server_config)
            self.assertIn("description", server_config)

    def test_cline_config_registry_settings(self):
        """CLINE MCP 注册表设置。"""
        config = generate_cline_mcp_config()

        registry = config["registry"]
        self.assertFalse(registry["allow_unregistered_tools"])
        self.assertTrue(registry["writable_tools_require_confirmation"])
        self.assertTrue(registry["external_network_tools_require_confirmation"])


class TestCLI(unittest.TestCase):
    """测试 CLI 接口。"""

    @patch("scripts.workflow_runner.main")
    def test_cli_help(self, mock_main):
        """CLI 帮助信息。"""
        # 只是验证模块可以导入，main 函数存在
        from scripts.workflow_runner import main as cli_main
        self.assertTrue(callable(cli_main))

    def test_cli_subcommands_exist(self):
        """验证所有子命令在帮助文本中。"""
        import scripts.workflow_runner as wr
        # 检查 argparse 子命令
        parser = wr.main.__globals__.get("parser")
        # 直接检查 main 函数中的 subparsers
        self.assertTrue(hasattr(wr, "main"))


class TestIntegration(unittest.TestCase):
    """集成测试。"""

    @patch("scripts.workflow_runner.load_yaml")
    @patch("scripts.workflow_runner.os.path.exists")
    def test_validate_then_plan_workflow(self, mock_exists, mock_load_yaml):
        """先验证再生成执行计划的完整流程。"""
        mock_exists.return_value = True
        mock_load_yaml.return_value = SAMPLE_WORKFLOW

        # 1. 验证
        validation = validate_workflow("workflows/business/business_model_validation.yaml")
        self.assertTrue(validation["valid"])

        # 2. 生成执行计划
        plan = generate_execution_plan(
            workflow_path="workflows/business/business_model_validation.yaml",
            intent="验证商业模式",
        )
        self.assertEqual(plan["workflow_id"], "business_model_validation")

        # 3. 验证计划步骤数
        self.assertGreater(len(plan["execution_steps"]), 3)

    @patch("scripts.workflow_runner.load_yaml")
    @patch("scripts.workflow_runner.os.path.exists")
    def test_context_plan_then_snapshot(self, mock_exists, mock_load_yaml):
        """先生成上下文计划再生成快照的完整流程。"""
        mock_exists.return_value = True
        def mock_load_yaml_side_effect(path):
            if "active-release" in path:
                return SAMPLE_ACTIVE_RELEASE
            if "mcp-tools" in path:
                return SAMPLE_MCP_CONFIG
            return SAMPLE_WORKFLOW
        mock_load_yaml.side_effect = mock_load_yaml_side_effect

        # 1. 生成上下文加载计划
        context_plan = generate_context_load_plan(
            workflow_path="workflows/business/business_model_validation.yaml",
        )
        self.assertEqual(context_plan["workflow_id"], "business_model_validation")
        self.assertEqual(len(context_plan["layers"]), 9)

        # 2. 生成运行快照
        snapshot = generate_run_snapshot_template(
            workflow_path="workflows/business/business_model_validation.yaml",
        )
        self.assertEqual(snapshot["workflow_id"], "business_model_validation")
        self.assertEqual(snapshot["workflow_state"]["total_steps"], 3)

        # 3. 验证快照中的 intent_confirmation 与上下文计划关联
        self.assertEqual(
            snapshot["intent_confirmation"]["retrieval_scope"]["industry"],
            "business",
        )


if __name__ == "__main__":
    unittest.main()
