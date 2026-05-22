#!/usr/bin/env python3
"""
sync_checker.py — 文档同步检查器

功能：基于 docs/sync-manifest.yaml 的依赖声明，检查修改文件后
      关联文件是否需要同步更新。

用法：
  python3 scripts/sync_checker.py --check-source <修改的文件>
  python3 scripts/sync_checker.py --check-all

退出码：
  0 = 所有关联文件已同步
  1 = 存在未同步的关联文件
"""

import argparse
import os
import re
import sys
import yaml

WORKSPACE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MANIFEST_PATH = os.path.join(WORKSPACE, "docs", "sync-manifest.yaml")


def load_manifest():
    """加载 sync-manifest.yaml"""
    if not os.path.exists(MANIFEST_PATH):
        print(f"❌ 未找到 sync-manifest.yaml: {MANIFEST_PATH}")
        sys.exit(1)
    with open(MANIFEST_PATH, "r") as f:
        return yaml.safe_load(f)


def resolve_path(path):
    """将相对路径解析为绝对路径"""
    if path.startswith("/"):
        return path
    return os.path.join(WORKSPACE, path)


def check_version_alignment(source_path, target_path, source_file, target_file):
    """检查版本号是否一致"""
    source_versions = re.findall(r"version[:\s]+([\d.]+)", source_file)
    target_versions = re.findall(r"version[:\s]+([\d.]+)", target_file)
    if not source_versions or not target_versions:
        return True, []
    mismatches = []
    for sv in source_versions:
        if sv not in target_versions:
            mismatches.append(f"  版本 '{sv}' 存在于 {source_path} 但不在 {target_path} 中")
    return len(mismatches) == 0, mismatches


def check_component_list_presence(source_path, target_path, source_file, target_file):
    """检查目标文件是否包含源文件中的组件"""
    # 提取源文件中的 workflow/constraint/prompt 路径
    source_items = set(re.findall(r"-\s+(workflows/|constraints/|prompts/|scripts/|schemas/|evaluators/)\S+", source_file))
    target_items = set(re.findall(r"-\s+(workflows/|constraints/|prompts/|scripts/|schemas/|evaluators/)\S+", target_file))
    missing = source_items - target_items
    if not missing:
        return True, []
    return False, [f"  以下组件在 {source_path} 中但不在 {target_path} 中:"] + [f"    - {item}" for item in sorted(missing)]


def check_exact_list_match(source_path, target_path, source_file, target_file):
    """检查两个文件中的列表是否完全一致"""
    source_items = set(re.findall(r"-\s+\S+", source_file))
    target_items = set(re.findall(r"-\s+\S+", target_file))
    only_in_source = source_items - target_items
    only_in_target = target_items - source_items
    issues = []
    if only_in_source:
        issues.append(f"  仅在 {source_path} 中存在:")
        for item in sorted(only_in_source):
            issues.append(f"    - {item}")
    if only_in_target:
        issues.append(f"  仅在 {target_path} 中存在:")
        for item in sorted(only_in_target):
            issues.append(f"    - {item}")
    return len(issues) == 0, issues


def check_startup_sequence_alignment(source_path, target_path, source_file, target_file):
    """检查启动序列是否一致"""
    source_steps = re.findall(r"^\s*\d+\.?\s+\S", source_file, re.MULTILINE)
    target_steps = re.findall(r"^\s*\d+\.?\s+\S", target_file, re.MULTILINE)
    if not source_steps or not target_steps:
        return True, []
    mismatches = []
    for i, step in enumerate(source_steps):
        if i >= len(target_steps):
            mismatches.append(f"  步骤 {i+1}: '{step.strip()}' 在 {target_path} 中缺失")
        elif step.strip() != target_steps[i].strip():
            mismatches.append(f"  步骤 {i+1}: '{step.strip()}' != '{target_steps[i].strip()}'")
    return len(mismatches) == 0, mismatches


def check_file_list_presence(source_path, target_path, source_file, target_file):
    """检查目标文件是否包含源文件中的文件引用"""
    source_files = set(re.findall(r"[\w/]+\.\w+", source_file))
    target_files = set(re.findall(r"[\w/]+\.\w+", target_file))
    missing = source_files - target_files
    if not missing:
        return True, []
    return False, [f"  以下文件引用在 {source_path} 中但不在 {target_path} 中:"] + [f"    - {f}" for f in sorted(missing)]


def check_changelog_entry_exists(source_path, target_path, source_file, target_file):
    """检查 CHANGELOG 是否包含版本条目"""
    versions = re.findall(r"id:\s*(\S+)", source_file)
    if not versions:
        return True, []
    missing = []
    for v in versions:
        if v not in target_file:
            missing.append(f"  版本 '{v}' 在 CHANGELOG 中缺失")
    return len(missing) == 0, missing


def check_directory_structure_sync(source_path, target_path, source_file, target_file):
    """检查目录结构描述是否同步"""
    source_dirs = set(re.findall(r"├──\s+(\w+)/", source_file))
    target_dirs = set(re.findall(r"├──\s+(\w+)/", target_file))
    missing = source_dirs - target_dirs
    if not missing:
        return True, []
    return False, [f"  以下目录在 {source_path} 中但不在 {target_path} 的目录结构中:"] + [f"    - {d}/" for d in sorted(missing)]


def check_session_reference_sync(source_path, target_path, source_file, target_file):
    """检查会话引用是否指向最新"""
    source_sessions = re.findall(r"session_id:\s*(\S+)", source_file)
    target_sessions = re.findall(r"session_id:\s*(\S+)", target_file)
    if not source_sessions:
        return True, []
    latest = source_sessions[-1]
    if latest not in target_file:
        return False, [f"  最新会话 '{latest}' 在 {target_path} 中缺失"]
    return True, []


def check_feature_flag_sync(source_path, target_path, source_file, target_file):
    """检查功能开关状态是否同步"""
    source_flags = re.findall(r"(\w+):\s*(true|false|on|off)", source_file)
    target_flags = re.findall(r"(\w+):\s*(true|false|on|off)", target_file)
    target_dict = dict(target_flags)
    mismatches = []
    for name, val in source_flags:
        if name in target_dict and target_dict[name] != val:
            mismatches.append(f"  功能开关 '{name}': {source_path}={val}, {target_path}={target_dict[name]}")
    return len(mismatches) == 0, mismatches


def check_prompt_manifest_sync(source_path, target_path, source_file, target_file):
    """检查 Prompt 清单是否同步"""
    source_prompts = set(re.findall(r"-\s+(prompts/\S+)", source_file))
    target_prompts = set(re.findall(r"-\s+(prompts/\S+)", target_file))
    missing = source_prompts - target_prompts
    if not missing:
        return True, []
    return False, [f"  以下 Prompt 在 {source_path} 中但不在 {target_path} 中:"] + [f"    - {p}" for p in sorted(missing)]


def check_list_superset_check(source_path, target_path, source_file, target_file):
    """检查目标列表是否是源列表的超集"""
    source_items = set(re.findall(r"-\s+(\S+)", source_file))
    target_items = set(re.findall(r"-\s+(\S+)", target_file))
    missing = source_items - target_items
    if not missing:
        return True, []
    return False, [f"  以下项在 {source_path} 中但不在 {target_path} 中:"] + [f"    - {item}" for item in sorted(missing)]


def check_schema_list_sync(source_path, target_path, source_file, target_file):
    """检查 Schema 列表是否同步"""
    source_schemas = set(re.findall(r"-\s+(schemas/\S+)", source_file))
    target_schemas = set(re.findall(r"-\s+(schemas/\S+)", target_file))
    missing = source_schemas - target_schemas
    if not missing:
        return True, []
    return False, [f"  以下 Schema 在 {source_path} 中但不在 {target_path} 中:"] + [f"    - {s}" for s in sorted(missing)]


# 检查函数映射
CHECKERS = {
    "version_alignment": check_version_alignment,
    "component_list_presence": check_component_list_presence,
    "exact_list_match": check_exact_list_match,
    "list_superset_check": check_list_superset_check,
    "startup_sequence_alignment": check_startup_sequence_alignment,
    "file_list_presence": check_file_list_presence,
    "directory_structure_sync": check_directory_structure_sync,
    "session_reference_sync": check_session_reference_sync,
    "changelog_entry_exists": check_changelog_entry_exists,
    "feature_flag_sync": check_feature_flag_sync,
    "prompt_manifest_sync": check_prompt_manifest_sync,
    "schema_list_sync": check_schema_list_sync,
    # 以下 check_kind 使用通用检查（文件存在性 + 内容包含）
    "process_step_alignment": check_startup_sequence_alignment,
    "mcp_tool_list_sync": check_exact_list_match,
    "git_boundary_sync": check_file_list_presence,
    "available_asset_root_sync": check_file_list_presence,
    "country_constraint_sync": check_file_list_presence,
    "market_reference_sync": check_file_list_presence,
    "knowledge_base_sync": check_file_list_presence,
    "judge_config_sync": check_file_list_presence,
    "judge_model_sync": check_file_list_presence,
    "eval_set_directory_sync": check_file_list_presence,
    "regression_test_sync": check_file_list_presence,
    "dashboard_test_sync": check_file_list_presence,
    "rollout_test_sync": check_file_list_presence,
    "workflow_runner_sync": check_file_list_presence,
    "interruption_handler_sync": check_file_list_presence,
    "lattice_schema_sync": check_file_list_presence,
    "lattice_script_sync": check_file_list_presence,
    "lattice_workflow_sync": check_file_list_presence,
    "lattice_template_sync": check_file_list_presence,
    "lattice_example_sync": check_file_list_presence,
    "rubric_reference_sync": check_file_list_presence,
    "evaluation_api_sync": check_file_list_presence,
    "evaluation_architecture_sync": check_file_list_presence,
    "evaluation_evolution_sync": check_file_list_presence,
    "evaluation_test_snapshot_sync": check_file_list_presence,
    "evaluation_regression_sync": check_file_list_presence,
    "release_governance_sync": check_file_list_presence,
    
    "release_manifest_dir_sync": check_file_list_presence,
    "release_active_manifest_sync": check_file_list_presence,
    "release_promote_script_sync": check_file_list_presence,
    "release_rollback_script_sync": check_file_list_presence,
    "release_changelog_sync": check_file_list_presence,
    "release_runner_sync": check_file_list_presence,
    "release_api_sync": check_file_list_presence,
    "release_architecture_sync": check_file_list_presence,
    "release_evolution_sync": check_file_list_presence,
    "release_test_snapshot_sync": check_file_list_presence,
    "release_regression_sync": check_file_list_presence,
    "release_judge_config_sync": check_file_list_presence,
    "release_judge_model_sync": check_file_list_presence,
    "release_eval_set_sync": check_file_list_presence,
    "release_candidate_change_sync": check_file_list_presence,
    "release_regression_report_sync": check_file_list_presence,
    "release_eval_set_config_sync": check_file_list_presence,
    "release_eval_set_schema_sync": check_file_list_presence,
    "release_candidate_change_schema_sync": check_file_list_presence,
    "release_regression_report_schema_sync": check_file_list_presence,
    "release_regression_output_sync": check_file_list_presence,
    "release_eval_set_directory_sync": check_file_list_presence,
    "release_rubric_sync": check_file_list_presence,
    "release_evaluation_api_sync": check_file_list_presence,
    "release_evaluation_architecture_sync": check_file_list_presence,
    "release_evaluation_evolution_sync": check_file_list_presence,
    "release_evaluation_test_snapshot_sync": check_file_list_presence,
    "release_evaluation_regression_sync": check_file_list_presence,
    "release_governance_doc_sync": check_file_list_presence,
    
    "release_manifest_dir_sync": check_file_list_presence,
    "release_active_manifest_sync": check_file_list_presence,
    "release_promote_script_sync": check_file_list_presence,
    "release_rollback_script_sync": check_file_list_presence,
    "release_changelog_sync": check_file_list_presence,
    "release_runner_sync": check_file_list_presence,
    "release_api_sync": check_file_list_presence,
    "release_architecture_sync": check_file_list_presence,
    "release_evolution_sync": check_file_list_presence,
    "release_test_snapshot_sync": check_file_list_presence,
    "release_regression_sync": check_file_list_presence,
    "release_judge_config_sync": check_file_list_presence,
    "release_judge_model_sync": check_file_list_presence,
    "release_eval_set_sync": check_file_list_presence,
    "release_candidate_change_sync": check_file_list_presence,
    "release_regression_report_sync": check_file_list_presence,
    "release_eval_set_config_sync": check_file_list_presence,
    "release_eval_set_schema_sync": check_file_list_presence,
    "release_candidate_change_schema_sync": check_file_list_presence,
    "release_regression_report_schema_sync": check_file_list_presence,
    "release_regression_output_sync": check_file_list_presence,
    "release_eval_set_directory_sync": check_file_list_presence,
    "release_rubric_sync": check_file_list_presence,
    "release_evaluation_api_sync": check_file_list_presence,
    "release_evaluation_architecture_sync": check_file_list_presence,
    "release_evaluation_evolution_sync": check_file_list_presence,
    "release_evaluation_test_snapshot_sync": check_file_list_presence,
    "release_evaluation_regression_sync": check_file_list_presence,
    "release_governance_doc_sync": check_file_list_presence,
    
    "release_manifest_dir_sync": check_file_list_presence,
    "release_active_manifest_sync": check_file_list_presence,
    "release_promote_script_sync": check_file_list_presence,
    "release_rollback_script_sync": check_file_list_presence,
    "release_changelog_sync": check_file_list_presence,
    "release_runner_sync": check_file_list_presence,
    "release_api_sync": check_file_list_presence,
    "release_architecture_sync": check_file_list_presence,
    "release_evolution_sync": check_file_list_presence,
    "release_test_snapshot_sync": check_file_list_presence,
    "release_regression_sync": check_file_list_presence,
    "release_judge_config_sync": check_file_list_presence,
    "release_judge_model_sync": check_file_list_presence,
    "release_eval_set_sync": check_file_list_presence,
    "release_candidate_change_sync": check_file_list_presence,
    "release_regression_report_sync": check_file_list_presence,
    "release_eval_set_config_sync": check_file_list_presence,
    "release_eval_set_schema_sync": check_file_list_presence,
    "release_candidate_change_schema_sync": check_file_list_presence,
    "release_regression_report_schema_sync": check_file_list_presence,
    "release_regression_output_sync": check_file_list_presence,
    "release_eval_set_directory_sync": check_file_list_presence,
    "release_rubric_sync": check_file_list_presence,
    "release_evaluation_api_sync": check_file_list_presence,
    "release_evaluation_architecture_sync": check_file_list_presence,
    "release_evaluation_evolution_sync": check_file_list_presence,
    "release_evaluation_test_snapshot_sync": check_file_list_presence,
    "release_evaluation_regression_sync": check_file_list_presence,
    "release_governance_doc_sync": check_file_list_presence,
    
    "release_manifest_dir_sync": check_file_list_presence,
    "release_active_manifest_sync": check_file_list_presence,
    "release_promote_script_sync": check_file_list_presence,
    "release_rollback_script_sync": check_file_list_presence,
    "release_changelog_sync": check_file_list_presence,
    "release_runner_sync": check_file_list_presence,
    "release_api_sync": check_file_list_presence,
    "release_architecture_sync": check_file_list_presence,
    "release_evolution_sync": check_file_list_presence,
    "release_test_snapshot_sync": check_file_list_presence,
    "release_regression_sync": check_file_list_presence,
    "release_judge_config_sync": check_file_list_presence,
    "release_judge_model_sync": check_file_list_presence,
    "release_eval_set_sync": check_file_list_presence,
    "release_candidate_change_sync": check_file_list_presence,
    "release_regression_report_sync": check_file_list_presence,
    "release_eval_set_config_sync": check_file_list_presence,
    "release_eval_set_schema_sync": check_file_list_presence,
    "release_candidate_change_schema_sync": check_file_list_presence,
    "release_regression_report_schema_sync": check_file_list_presence,
    "release_regression_output_sync": check_file_list_presence,
    "release_eval_set_directory_sync": check_file_list_presence,
    "release_rubric_sync": check_file_list_presence,
    "release_evaluation_api_sync": check_file_list_presence,
    "release_evaluation_architecture_sync": check_file_list_presence,
    "release_evaluation_evolution_sync": check_file_list_presence,
    "release_evaluation_test_snapshot_sync": check_file_list_presence,
    "release_evaluation_regression_sync": check_file_list_presence,
    "release_governance_doc_sync": check_file_list_presence,
    
    "release_manifest_dir_sync": check_file_list_presence,
    "release_active_manifest_sync": check_file_list_presence,
    "release_promote_script_sync": check_file_list_presence,
    "release_rollback_script_sync": check_file_list_presence,
    "release_changelog_sync": check_file_list_presence,
    "release_runner_sync": check_file_list_presence,
    "release_api_sync": check_file_list_presence,
    "release_architecture_sync": check_file_list_presence,
    "release_evolution_sync": check_file_list_presence,
    "release_test_snapshot_sync": check_file_list_presence,
    "release_regression_sync": check_file_list_presence,
    "release_judge_config_sync": check_file_list_presence,
    "release_judge_model_sync": check_file_list_presence,
    "release_eval_set_sync": check_file_list_presence,
    "release_candidate_change_sync": check_file_list_presence,
    "release_regression_report_sync": check_file_list_presence,
    "release_eval_set_config_sync": check_file_list_presence,
    "release_eval_set_schema_sync": check_file_list_presence,
    "release_candidate_change_schema_sync": check_file_list_presence,
    "release_regression_report_schema_sync": check_file_list_presence,
    "release_regression_output_sync": check_file_list_presence,
    "release_eval_set_directory_sync": check_file_list_presence,
    "release_rubric_sync": check_file_list_presence,
    "release_evaluation_api_sync": check_file_list_presence,
    "release_evaluation_architecture_sync": check_file_list_presence,
    "release_evaluation_evolution_sync": check_file_list_presence,
    "release_evaluation_test_snapshot_sync": check_file_list_presence,
    "release_evaluation_regression_sync": check_file_list_presence,
    "release_governance_doc_sync": check_file_list_presence,
    
    "release_manifest_dir_sync": check_file_list_presence,
    "release_active_manifest_sync": check_file_list_presence,
    "release_promote_script_sync": check_file_list_presence,
    "release_rollback_script_sync": check_file_list_presence,
    "release_changelog_sync": check_file_list_presence,
    "release_runner_sync": check_file_list_presence,
    "release_api_sync": check_file_list_presence,
    "release_architecture_sync": check_file_list_presence,
    "release_evolution_sync": check_file_list_presence,
    "release_test_snapshot_sync": check_file_list_presence,
    "release_regression_sync": check_file_list_presence,
    "release_judge_config_sync": check_file_list_presence,
    "release_judge_model_sync": check_file_list_presence,
    "release_eval_set_sync": check_file_list_presence,
    "release_candidate_change_sync": check_file_list_presence,
    "release_regression_report_sync": check_file_list_presence,
    "release_eval_set_config_sync": check_file_list_presence,
    "release_eval_set_schema_sync": check_file_list_presence,
    "release_candidate_change_schema_sync": check_file_list_presence,
    "release_regression_report_schema_sync": check_file_list_presence,
    "release_regression_output_sync": check_file_list_presence,
    "release_eval_set_directory_sync": check_file_list_presence,
    "release_rubric_sync": check_file_list_presence,
    "release_evaluation_api_sync": check_file_list_presence,
    "release_evaluation_architecture_sync": check_file_list_presence,
    "release_evaluation_evolution_sync": check_file_list_presence,
    "release_evaluation_test_snapshot_sync": check_file_list_presence,
    "release_evaluation_regression_sync": check_file_list_presence,
    "release_governance_doc_sync": check_file_list_presence,
    
    "release_manifest_dir_sync": check_file_list_presence,
    "release_active_manifest_sync": check_file_list_presence,
    "release_promote_script_sync": check_file_list_presence,
    "release_rollback_script_sync": check_file_list_presence,
    "release_changelog_sync": check_file_list_presence,
    "release_runner_sync": check_file_list_presence,
    "release_api_sync": check_file_list_presence,
    "release_architecture_sync": check_file_list_presence,
    "release_evolution_sync": check_file_list_presence,
    "release_test_snapshot_sync": check_file_list_presence,
    "release_regression_sync": check_file_list_presence,
    "release_judge_config_sync": check_file_list_presence,
    "release_judge_model_sync": check_file_list_presence,
    "release_eval_set_sync": check_file_list_presence,
    "release_candidate_change_sync": check_file_list_presence,
    "release_regression_report_sync": check_file_list_presence,
    "release_eval_set_config_sync": check_file_list_presence,
    "release_eval_set_schema_sync": check_file_list_presence,
    "release_candidate_change_schema_sync": check_file_list_presence,
    "release_regression_report_schema_sync": check_file_list_presence,
    "release_regression_output_sync": check_file_list_presence,
    "release_eval_set_directory_sync": check_file_list_presence,
    "release_rubric_sync": check_file_list_presence,
    "release_evaluation_api_sync": check_file_list_presence,
    "release_evaluation_architecture_sync": check_file_list_presence,
    "release_evaluation_evolution_sync": check_file_list_presence,
    "release_evaluation_test_snapshot_sync": check_file_list_presence,
    "release_evaluation_regression_sync": check_file_list_presence,
    "release_governance_doc_sync": check_file_list_presence,
    
    "release_manifest_dir_sync": check_file_list_presence,
    "release_active_manifest_sync": check_file_list_presence,
    "release_promote_script_sync": check_file_list_presence,
    "release_rollback_script_sync": check_file_list_presence,
    "release_changelog_sync": check_file_list_presence,
    "release_runner_sync": check_file_list_presence,
    "release_api_sync": check_file_list_presence,
    "release_architecture_sync": check_file_list_presence,
    "release_evolution_sync": check_file_list_presence,
    "release_test_snapshot_sync": check_file_list_presence,
    "release_regression_sync": check_file_list_presence,
    "release_judge_config_sync": check_file_list_presence,
    "release_judge_model_sync": check_file_list_presence,
    "release_eval_set_sync": check_file_list_presence,
    "release_candidate_change_sync": check_file_list_presence,
    "release_regression_report_sync": check_file_list_presence,
    "release_eval_set_config_sync": check_file_list_presence,
    "release_eval_set_schema_sync": check_file_list_presence,
    "release_candidate_change_schema_sync": check_file_list_presence,
    "release_regression_report_schema_sync": check_file_list_presence,
    "release_regression_output_sync": check_file_list_presence,
    "release_eval_set_directory_sync": check_file_list_presence,
    "release_rubric_sync": check_file_list_presence,
    "release_evaluation_api_sync": check_file_list_presence,
    "release_evaluation_architecture_sync": check_file_list_presence,
    "release_evaluation_evolution_sync": check_file_list_presence,
    "release_evaluation_test_snapshot_sync": check_file_list_presence,
    "release_evaluation_regression_sync": check_file_list_presence,
    "release_governance_doc_sync": check_file_list_presence,
    
    "release_manifest_dir_sync": check_file_list_presence,
    "release_active_manifest_sync": check_file_list_presence,
    "release_promote_script_sync": check_file_list_presence,
    "release_rollback_script_sync": check_file_list_presence,
    "release_changelog_sync": check_file_list_presence,
    "release_runner_sync": check_file_list_presence,
    "release_api_sync": check_file_list_presence,
    "release_architecture_sync": check_file_list_presence,
    "release_evolution_sync": check_file_list_presence,
    "release_test_snapshot_sync": check_file_list_presence,
    "release_regression_sync": check_file_list_presence,
    "release_judge_config_sync": check_file_list_presence,
    "release_judge_model_sync": check_file_list_presence,
    "release_eval_set_sync": check_file_list_presence,
    "release_candidate_change_sync": check_file_list_presence,
    "release_regression_report_sync": check_file_list_presence,
    "release_eval_set_config_sync": check_file_list_presence,
    "release_eval_set_schema_sync": check_file_list_presence,
    "release_candidate_change_schema_sync": check_file_list_presence,
    "release_regression_report_schema_sync": check_file_list_presence,
    "release_regression_output_sync": check_file_list_presence,
    "release_eval_set_directory_sync": check_file_list_presence,
    "release_rubric_sync": check_file_list_presence,
    "release_evaluation_api_sync": check_file_list_presence,
    "release_evaluation_architecture_sync": check_file_list_presence,
    "release_evaluation_evolution_sync": check_file_list_presence,
    "release_evaluation_test_snapshot_sync": check_file_list_presence,
    "release_evaluation_regression_sync": check_file_list_presence,
    "release_governance_doc_sync": check_file_list_presence,
    
    "release_manifest_dir_sync": check_file_list_presence,
    "release_active_manifest_sync": check_file_list_presence,
    "release_promote_script_sync": check_file_list_presence,
    "release_rollback_script_sync": check_file_list_presence,
    "release_changelog_sync": check_file_list_presence,
    "release_runner_sync": check_file_list_presence,
    "release_api_sync": check_file_list_presence,
    "release_architecture_sync": check_file_list_presence,
    "release_evolution_sync": check_file_list_presence,
    "release_test_snapshot_sync": check_file_list_presence,
    "release_regression_sync": check_file_list_presence,
    "release_judge_config_sync": check_file_list_presence,
    "release_judge_model_sync": check_file_list_presence,
    "release_eval_set_sync": check_file_list_presence,
    "release_candidate_change_sync": check_file_list_presence,
    "release_regression_report_sync": check_file_list_presence,
    "release_eval_set_config_sync": check_file_list_presence,
    "release_eval_set_schema_sync": check_file_list_presence,
    "release_candidate_change_schema_sync": check_file_list_presence,
    "release_regression_report_schema_sync": check_file_list_presence,
    "release_regression_output_sync": check_file_list_presence,
    "release_eval_set_directory_sync": check_file_list_presence,
    "release_rubric_sync": check_file_list_presence,
    "release_evaluation_api_sync": check_file_list_presence,
    "release_evaluation_architecture_sync": check_file_list_presence,
    "release_evaluation_evolution_sync": check_file_list_presence,
    "release_evaluation_test_snapshot_sync": check_file_list_presence,
    "release_evaluation_regression_sync": check_file_list_presence,
    "release_governance_doc_sync": check_file_list_presence,
    
    "release_manifest_dir_sync": check_file_list_presence,
    "release_active_manifest_sync": check_file_list_presence,
    "release_promote_script_sync": check_file_list_presence,
    "release_rollback_script_sync": check_file_list_presence,
    "release_changelog_sync": check_file_list_presence,
    "release_runner_sync": check_file_list_presence,
    "release_api_sync": check_file_list_presence,
    "release_architecture_sync": check_file_list_presence,
    "release_evolution_sync": check_file_list_presence,
    "release_test_snapshot_sync": check_file_list_presence,
    "release_regression_sync": check_file_list_presence,
    "release_judge_config_sync": check_file_list_presence,
    "release_judge_model_sync": check_file_list_presence,
    "release_eval_set_sync": check_file_list_presence,
    "release_candidate_change_sync": check_file_list_presence,
    "release_regression_report_sync": check_file_list_presence,
    "release_eval_set_config_sync": check_file_list_presence,
    "release_eval_set_schema_sync": check_file_list_presence,
    "release_candidate_change_schema_sync": check_file_list_presence,
    "release_regression_report_schema_sync": check_file_list_presence,
    "release_regression_output_sync": check_file_list_presence,
    "release_eval_set_directory_sync": check_file_list_presence,
    "release_rubric_sync": check_file_list_presence,
    "release_evaluation_api_sync": check_file_list_presence,
    "release_evaluation_architecture_sync": check_file_list_presence,
    "release_evaluation_evolution_sync": check_file_list_presence,
    "release_evaluation_test_snapshot_sync": check_file_list_presence,
    "release_evaluation_regression_sync": check_file_list_presence,
    "release_governance_doc_sync": check_file_list_presence,
    
    "release_manifest_dir_sync": check_file_list_presence,
    "release_active_manifest_sync": check_file_list_presence,
    "release_promote_script_sync": check_file_list_presence,
    "release_rollback_script_sync": check_file_list_presence,
    "release_changelog_sync": check_file_list_presence,
    "release_runner_sync": check_file_list_presence,
    "release_api_sync": check_file_list_presence,
    "release_architecture_sync": check_file_list_presence,
    "release_evolution_sync": check_file_list_presence,
    "release_test_snapshot_sync": check_file_list_presence,
    "release_regression_sync": check_file_list_presence,
    "release_judge_config_sync": check_file_list_presence,
    "release_judge_model_sync": check_file_list_presence,
    "release_eval_set_sync": check_file_list_presence,
    "release_candidate_change_sync": check_file_list_presence,
    "release_regression_report_sync": check_file_list_presence,
    "release_eval_set_config_sync": check_file_list_presence,
    "release_eval_set_schema_sync": check_file_list_presence,
    "release_candidate_change_schema_sync": check_file_list_presence,
    "release_regression_report_schema_sync": check_file_list_presence,
    "release_regression_output_sync": check_file_list_presence,
    "release_eval_set_directory_sync": check_file_list_presence,
    "release_rubric_sync": check_file_list_presence,
    "release_evaluation_api_sync": check_file_list_presence,
    "release_evaluation_architecture_sync": check_file_list_presence,
    "release_evaluation_evolution_sync": check_file_list_presence,
    "release_evaluation_test_snapshot_sync": check_file_list_presence,
    "release_evaluation_regression_sync": check_file_list_presence,
    "release_governance_doc_sync": check_file_list_presence,
    
    "release_manifest_dir_sync": check_file_list_presence,
    "release_active_manifest_sync": check_file_list_presence,
    "release_promote_script_sync": check_file_list_presence,
    "release_rollback_script_sync": check_file_list_presence,
    "release_changelog_sync": check_file_list_presence,
    "release_runner_sync": check_file_list_presence,
    "release_api_sync": check_file_list_presence,
    "release_architecture_sync": check_file_list_presence,
    "release_evolution_sync": check_file_list_presence,
    "release_test_snapshot_sync": check_file_list_presence,
    "release_regression_sync": check_file_list_presence,
    "release_judge_config_sync": check_file_list_presence,
    "release_judge_model_sync": check_file_list_presence,
    "release_eval_set_sync": check_file_list_presence,
    "release_candidate_change_sync": check_file_list_presence,
    "release_regression_report_sync": check_file_list_presence,
    "release_eval_set_config_sync": check_file_list_presence,
    "release_eval_set_schema_sync": check_file_list_presence,
    "release_candidate_change_schema_sync": check_file_list_presence,
    "release_regression_report_schema_sync": check_file_list_presence,
    "release_regression_output_sync": check_file_list_presence,
    "release_eval_set_directory_sync": check_file_list_presence,
    "release_rubric_sync": check_file_list_presence,
    "release_evaluation_api_sync": check_file_list_presence,
    "release_evaluation_architecture_sync": check_file_list_presence,
    "release_evaluation_evolution_sync": check_file_list_presence,
    "release_evaluation_test_snapshot_sync": check_file_list_presence,
    "release_evaluation_regression_sync": check_file_list_presence,
    "release_governance_doc_sync": check_file_list_presence,
    
    "release_manifest_dir_sync": check_file_list_presence,
    "release_active_manifest_sync": check_file_list_presence,
    "release_promote_script_sync": check_file_list_presence,
    "release_rollback_script_sync": check_file_list_presence,
    "release_changelog_sync": check_file_list_presence,
    "release_runner_sync": check_file_list_presence,
    "release_api_sync": check_file_list_presence,
    "release_architecture_sync": check_file_list_presence,
    "release_evolution_sync": check_file_list_presence,
    "release_test_snapshot_sync": check_file_list_presence,
    "release_regression_sync": check_file_list_presence,
    "release_judge_config_sync": check_file_list_presence,
    "release_judge_model_sync": check_file_list_presence,
    "release_eval_set_sync": check_file_list_presence,
    "release_candidate_change_sync": check_file_list_presence,
    "release_regression_report_sync": check_file_list_presence,
    "release_eval_set_config_sync": check_file_list_presence,
    "release_eval_set_schema_sync": check_file_list_presence,
    "release_candidate_change_schema_sync": check_file_list_presence,
    "release_regression_report_schema_sync": check_file_list_presence,
    "release_regression_output_sync": check_file_list_presence,
    "release_eval_set_directory_sync": check_file_list_presence,
    "release_rubric_sync": check_file_list_presence,
    "release_evaluation_api_sync": check_file_list_presence,
    "release_evaluation_architecture_sync": check_file_list_presence,
    "release_evaluation_evolution_sync": check_file_list_presence,
    "release_evaluation_test_snapshot_sync": check_file_list_presence,
    "release_evaluation_regression_sync": check_file_list_presence,
    "release_governance_doc_sync": check_file_list_presence,
    
    "release_manifest_dir_sync": check_file_list_presence,
    "release_active_manifest_sync": check_file_list_presence,
    "release_promote_script_sync": check_file_list_presence,
    "release_rollback_script_sync": check_file_list_presence,
    "release_changelog_sync": check_file_list_presence,
    "release_runner_sync": check_file_list_presence,
    "release_api_sync": check_file_list_presence,
    "release_architecture_sync": check_file_list_presence,
    "release_evolution_sync": check_file_list_presence,
    "release_test_snapshot_sync": check_file_list_presence,
    "release_regression_sync": check_file_list_presence,
    "release_judge_config_sync": check_file_list_presence,
    "release_judge_model_sync": check_file_list_presence,
    "release_eval_set_sync": check_file_list_presence,
    "release_candidate_change_sync": check_file_list_presence,
    "release_regression_report_sync": check_file_list_presence,
    "release_eval_set_config_sync": check_file_list_presence,
    "release_eval_set_schema_sync": check_file_list_presence,
    "release_candidate_change_schema_sync": check_file_list_presence,
    "release_regression_report_schema_sync": check_file_list_presence,
    "release_regression_output_sync": check_file_list_presence,
    "release_eval_set_directory_sync": check_file_list_presence,
    "release_rubric_sync": check_file_list_presence,
    "release_evaluation_api_sync": check_file_list_presence,
    "release_evaluation_architecture_sync": check_file_list_presence,
    "release_evaluation_evolution_sync": check_file_list_presence,
    "release_evaluation_test_snapshot_sync": check_file_list_presence,
    "release_evaluation_regression_sync": check_file_list_presence,
    "release_governance_doc_sync": check_file_list_presence,
    
    "release_manifest_dir_sync": check_file_list_presence,
    "release_active_manifest_sync": check_file_list_presence,
    "release_promote_script_sync": check_file_list_presence,
    "release_rollback_script_sync": check_file_list_presence,
    "release_changelog_sync": check_file_list_presence,
    "release_runner_sync": check_file_list_presence,
    "release_api_sync": check_file_list_presence,
    "release_architecture_sync": check_file_list_presence,
    "release_evolution_sync": check_file_list_presence,
    "release_test_snapshot_sync": check_file_list_presence,
    "release_regression_sync": check_file_list_presence,
    "release_judge_config_sync": check_file_list_presence,
    "release_judge_model_sync": check_file_list_presence,
    "release_eval_set_sync": check_file_list_presence,
    "release_candidate_change_sync": check_file_list_presence,
    "release_regression_report_sync": check_file_list_presence,
    "release_eval_set_config_sync": check_file_list_presence,
    "release_eval_set_schema_sync": check_file_list_presence,
    "release_candidate_change_schema_sync": check_file_list_presence,
    "release_regression_report_schema_sync": check_file_list_presence,
    "release_regression_output_sync": check_file_list_presence,
    "release_eval_set_directory_sync": check_file_list_presence,
    "release_rubric_sync": check_file_list_presence,
    "release_evaluation_api_sync": check_file_list_presence,
    "release_evaluation_architecture_sync": check_file_list_presence,
    "release_evaluation_evolution_sync": check_file_list_presence,
    "release_evaluation_test_snapshot_sync": check_file_list_presence,
    "release_evaluation_regression_sync": check_file_list_presence,
    "release_governance_doc_sync": check_file_list_presence,
    
    "release_manifest_dir_sync": check_file_list_presence,
    "release_active_manifest_sync": check_file_list_presence,
    "release_promote_script_sync": check_file_list_presence,
    "release_rollback_script_sync": check_file_list_presence,
    "release_changelog_sync": check_file_list_presence,
    "release_runner_sync": check_file_list_presence,
    "release_api_sync": check_file_list_presence,
    "release_architecture_sync": check_file_list_presence,
    "release_evolution_sync": check_file_list_presence,
    "release_test_snapshot_sync": check_file_list_presence,
    "release_regression_sync": check_file_list_presence,
    "release_judge_config_sync": check_file_list_presence,
    "release_judge_model_sync": check_file_list_presence,
    "release_eval_set_sync": check_file_list_presence,
    "release_candidate_change_sync": check_file_list_presence,
    "release_regression_report_sync": check_file_list_presence,
    "release_eval_set_config_sync": check_file_list_presence,
    "release_eval_set_schema_sync": check_file_list_presence,
    "release_candidate_change_schema_sync": check_file_list_presence,
    "release_regression_report_schema_sync": check_file_list_presence,
    "release_regression_output_sync": check_file_list_presence,
    "release_eval_set_directory_sync": check_file_list_presence,
    "release_rubric_sync": check_file_list_presence,
    "release_evaluation_api_sync": check_file_list_presence,
    "release_evaluation_architecture_sync": check_file_list_presence,
    "release_evaluation_evolution_sync": check_file_list_presence,
    "release_evaluation_test_snapshot_sync": check_file_list_presence,
    "release_evaluation_regression_sync": check_file_list_presence,
    "release_governance_doc_sync": check_file_list_presence,
    
    "release_manifest_dir_sync": check_file_list_presence,
    "release_active_manifest_sync": check_file_list_presence,
    "release_promote_script_sync": check_file_list_presence,
    "release_rollback_script_sync": check_file_list_presence,
    "release_changelog_sync": check_file_list_presence,
    "release_runner_sync": check_file_list_presence,
    "release_api_sync": check_file_list_presence,
    "release_architecture_sync": check_file_list_presence,
    "release_evolution_sync": check_file_list_presence,
    "release_test_snapshot_sync": check_file_list_presence,
    "release_regression_sync": check_file_list_presence,
    "release_judge_config_sync": check_file_list_presence,
    "release_judge_model_sync": check_file_list_presence,
    "release_eval_set_sync": check_file_list_presence,
    "release_candidate_change_sync": check_file_list_presence,
    "release_regression_report_sync": check_file_list_presence,
    "release_eval_set_config_sync": check_file_list_presence,
    "release_eval_set_schema_sync": check_file_list_presence,
    "release_candidate_change_schema_sync": check_file_list_presence,
    "release_regression_report_schema_sync": check_file_list_presence,
    "release_regression_output_sync": check_file_list_presence,
    "release_eval_set_directory_sync": check_file_list_presence,
    "release_rubric_sync": check_file_list_presence,
    "release_evaluation_api_sync": check_file_list_presence,
    "release_evaluation_architecture_sync": check_file_list_presence,
    "release_evaluation_evolution_sync": check_file_list_presence,
    "release_evaluation_test_snapshot_sync": check_file_list_presence,
    "release_evaluation_regression_sync": check_file_list_presence,
    "release_governance_doc_sync": check_file_list_presence,
    
    "release_manifest_dir_sync": check_file_list_presence,
    "release_active_manifest_sync": check_file_list_presence,
    "release_promote_script_sync": check_file_list_presence,
    "release_rollback_script_sync": check_file_list_presence,
    "release_changelog_sync": check_file_list_presence,
    "release_runner_sync": check_file_list_presence,
    "release_api_sync": check_file_list_presence,
    "release_architecture_sync": check_file_list_presence,
    "release_evolution_sync": check_file_list_presence,
    "release_test_snapshot_sync": check_file_list_presence,
    "release_regression_sync": check_file_list_presence,
    "release_judge_config_sync": check_file_list_presence,
    "release_judge_model_sync": check_file_list_presence,
    "release_eval_set_sync": check_file_list_presence,
    "release_candidate_change_sync": check_file_list_presence,
    "release_regression_report_sync": check_file_list_presence,
    "release_eval_set_config_sync": check_file_list_presence,
    "release_eval_set_schema_sync": check_file_list_presence,
    "release_candidate_change_schema_sync": check_file_list_presence,
    "release_regression_report_schema_sync": check_file_list_presence,
    "release_regression_output_sync": check_file_list_presence,
    "release_eval_set_directory_sync": check_file_list_presence,
    "release_rubric_sync": check_file_list_presence,
    "release_evaluation_api_sync": check_file_list_presence,
    "release_evaluation_architecture_sync": check_file_list_presence,
    "release_evaluation_evolution_sync": check_file_list_presence,
    "release_evaluation_test_snapshot_sync": check_file_list_presence,
    "release_evaluation_regression_sync": check_file_list_presence,
    "release_governance_doc_sync": check_file_list_presence,
    
    "release_manifest_dir_sync": check_file_list_presence,
    "release_active_manifest_sync": check_file_list_presence,
    "release_promote_script_sync": check_file_list_presence,
    "release_rollback_script_sync": check_file_list_presence,
    "release_changelog_sync": check_file_list_presence,
    "release_runner_sync": check_file_list_presence,
    "release_api_sync": check_file_list_presence,
    "release_architecture_sync": check_file_list_presence,
    "release_evolution_sync": check_file_list_presence,
    "release_test_snapshot_sync": check_file_list_presence,
    "release_regression_sync": check_file_list_presence,
    "release_judge_config_sync": check_file_list_presence,
    "release_judge_model_sync": check_file_list_presence,
    "release_eval_set_sync": check_file_list_presence,
    "release_candidate_change_sync": check_file_list_presence,
    "release_regression_report_sync": check_file_list_presence,
    "release_eval_set_config_sync": check_file_list_presence,
    "release_eval_set_schema_sync": check_file_list_presence,
    "release_candidate_change_schema_sync": check_file_list_presence,
    "release_regression_report_schema_sync": check_file_list_presence,
    "release_regression_output_sync": check_file_list_presence,
    "release_eval_set_directory_sync": check_file_list_presence,
    "release_rubric_sync": check_file_list_presence,
    "release_evaluation_api_sync": check_file_list_presence,
    "release_evaluation_architecture_sync": check_file_list_presence,
    "release_evaluation_evolution_sync": check_file_list_presence,
    "release_evaluation_test_snapshot_sync": check_file_list_presence,
    "release_evaluation_regression_sync": check_file_list_presence,
    "release_governance_doc_sync": check_file_list_presence,
    
    "release_manifest_dir_sync": check_file_list_presence,
    "release_active_manifest_sync": check_file_list_presence,
    "release_promote_script_sync": check_file_list_presence,
    "release_rollback_script_sync": check_file_list_presence,
    "release_changelog_sync": check_file_list_presence,
    "release_runner_sync": check_file_list_presence,
    "release_api_sync": check_file_list_presence,
    "release_architecture_sync": check_file_list_presence,
    "release_evolution_sync": check_file_list_presence,
    "release_test_snapshot_sync": check_file_list_presence,
    "release_regression_sync": check_file_list_presence,
    "release_judge_config_sync": check_file_list_presence,
    "release_judge_model_sync": check_file_list_presence,
    "release_eval_set_sync": check_file_list_presence,
    "release_candidate_change_sync": check_file_list_presence,
    "release_regression_report_sync": check_file_list_presence,
    "release_eval_set_config_sync": check_file_list_presence,
    "release_eval_set_schema_sync": check_file_list_presence,
    "release_candidate_change_schema_sync": check_file_list_presence,
    "release_regression_report_schema_sync": check_file_list_presence,
    "release_regression_output_sync": check_file_list_presence,
    "release_eval_set_directory_sync": check_file_list_presence,
    "release_rubric_sync": check_file_list_presence,
    "release_evaluation_api_sync": check_file_list_presence,
    "release_evaluation_architecture_sync": check_file_list_presence,
    "release_evaluation_evolution_sync": check_file_list_presence,
    "release_evaluation_test_snapshot_sync": check_file_list_presence,
    "release_evaluation_regression_sync": check_file_list_presence,
    "release_governance_doc_sync": check_file_list_presence,
    
    "release_manifest_dir_sync": check_file_list_presence,
    "release_active_manifest_sync": check_file_list_presence,
    "release_promote_script_sync": check_file_list_presence,
    "release_rollback_script_sync": check_file_list_presence,
    "release_changelog_sync": check_file_list_presence,
    "release_runner_sync": check_file_list_presence,
    "release_api_sync": check_file_list_presence,
    "release_architecture_sync": check_file_list_presence,
    "release_evolution_sync": check_file_list_presence,
    "release_test_snapshot_sync": check_file_list_presence,
    "release_regression_sync": check_file_list_presence,
    "release_judge_config_sync": check_file_list_presence,
    "release_judge_model_sync": check_file_list_presence,
    "release_eval_set_sync": check_file_list_presence,
    "release_candidate_change_sync": check_file_list_presence,
    "release_regression_report_sync": check_file_list_presence,
    "release_eval_set_config_sync": check_file_list_presence,
    "release_eval_set_schema_sync": check_file_list_presence,
    "release_candidate_change_schema_sync": check_file_list_presence,
    "release_regression_report_schema_sync": check_file_list_presence,
    "release_regression_output_sync": check_file_list_presence,
    "release_eval_set_directory_sync": check_file_list_presence,
    "release_rubric_sync": check_file_list_presence,
    "release_evaluation_api_sync": check_file_list_presence,
    "release_evaluation_architecture_sync": check_file_list_presence,
    "release_evaluation_evolution_sync": check_file_list_presence,
    "release_evaluation_test_snapshot_sync": check_file_list_presence,
    "release_evaluation_regression_sync": check_file_list_presence,
    "release_governance_doc_sync": check_file_list_presence,
    
    "release_manifest_dir_sync": check_file_list_presence,
    "release_active_manifest_sync": check_file_list_presence,
    "release_promote_script_sync": check_file_list_presence,
    "release_rollback_script_sync": check_file_list_presence,
    "release_changelog_sync": check_file_list_presence,
    "release_runner_sync": check_file_list_presence,
    "release_api_sync": check_file_list_presence,
    "release_architecture_sync": check_file_list_presence,
    "release_evolution_sync": check_file_list_presence,
    "release_test_snapshot_sync": check_file_list_presence,
    "release_regression_sync": check_file_list_presence,
    "release_judge_config_sync": check_file_list_presence,
    "release_judge_model_sync": check_file_list_presence,
    "release_eval_set_sync": check_file_list_presence,
    "release_candidate_change_sync": check_file_list_presence,
    "release_regression_report_sync": check_file_list_presence,
    "release_eval_set_config_sync": check_file_list_presence,
    "release_eval_set_schema_sync": check_file_list_presence,
    "release_candidate_change_schema_sync": check_file_list_presence,
    "release_regression_report_schema_sync": check_file_list_presence,
    "release_regression_output_sync": check_file_list_presence,
    "release_eval_set_directory_sync": check_file_list_presence,
    "release_rubric_sync": check_file_list_presence,
    "release_evaluation_api_sync": check_file_list_presence,
    "release_evaluation_architecture_sync": check_file_list_presence,
    "release_evaluation_evolution_sync": check_file_list_presence,
    "release_evaluation_test_snapshot_sync": check_file_list_presence,
    "release_evaluation_regression_sync": check_file_list_presence,
    "release_governance_doc_sync": check_file_list_presence,
    
    "release_manifest_dir_sync": check_file_list_presence,
    "release_active_manifest_sync": check_file_list_presence,
    "release_promote_script_sync": check_file_list_presence,
    "release_rollback_script_sync": check_file_list_presence,
    "release_changelog_sync": check_file_list_presence,
    "release_runner_sync": check_file_list_presence,
    "release_api_sync": check_file_list_presence,
    "release_architecture_sync": check_file_list_presence,
    "release_evolution_sync": check_file_list_presence,
    "release_test_snapshot_sync": check_file_list_presence,
    "release_regression_sync": check_file_list_presence,
    "release_judge_config_sync": check_file_list_presence,
    "release_judge_model_sync": check_file_list_presence,
    "release_eval_set_sync": check_file_list_presence,
    "release_candidate_change_sync": check_file_list_presence,
    "release_regression_report_sync": check_file_list_presence,
    "release_eval_set_config_sync": check_file_list_presence,
    "release_eval_set_schema_sync": check_file_list_presence,
    "release_candidate_change_schema_sync": check_file_list_presence,
    "release_regression_report_schema_sync": check_file_list_presence,
    "release_regression_output_sync": check_file_list_presence,
    "release_eval_set_directory_sync": check_file_list_presence,
    "release_rubric_sync": check_file_list_presence,
    "release_evaluation_api_sync": check_file_list_presence,
    "release_evaluation_architecture_sync": check_file_list_presence,
    "release_evaluation_evolution_sync": check_file_list_presence,
    "release_evaluation_test_snapshot_sync": check_file_list_presence,
    "release_evaluation_regression_sync": check_file_list_presence,
    "release_governance_doc_sync": check_file_list_presence,
    
    "release_manifest_dir_sync": check_file_list_presence,
    "release_active_manifest_sync": check_file_list_presence,
    "release_promote_script_sync": check_file_list_presence,
    "release_rollback_script_sync": check_file_list_presence,
    "release_changelog_sync": check_file_list_presence,
    "release_runner_sync": check_file_list_presence,
    "release_api_sync": check_file_list_presence,
    "release_architecture_sync": check_file_list_presence,
    "release_evolution_sync": check_file_list_presence,
    "release_test_snapshot_sync": check_file_list_presence,
    "release_regression_sync": check_file_list_presence,
    "release_judge_config_sync": check_file_list_presence,
    "release_judge_model_sync": check_file_list_presence,
    "release_eval_set_sync": check_file_list_presence,
    "release_candidate_change_sync": check_file_list_presence,
    "release_regression_report_sync": check_file_list_presence,
    "release_eval_set_config_sync": check_file_list_presence,
    "release_eval_set_schema_sync": check_file_list_presence,
    "release_candidate_change_schema_sync": check_file_list_presence,
    "release_regression_report_schema_sync": check_file_list_presence,
    "release_regression_output_sync": check_file_list_presence,
    "release_eval_set_directory_sync": check_file_list_presence,
    "release_rubric_sync": check_file_list_presence,
    "release_evaluation_api_sync": check_file_list_presence,
    "release_evaluation_architecture_sync": check_file_list_presence,
    "release_evaluation_evolution_sync": check_file_list_presence,
    "release_evaluation_test_snapshot_sync": check_file_list_presence,
    "release_evaluation_regression_sync": check_file_list_presence,
    "release_governance_doc_sync": check_file_list_presence,
    
    "release_manifest_dir_sync": check_file_list_presence,
    "release_active_manifest_sync": check_file_list_presence,
    "release_promote_script_sync": check_file_list_presence,
    "release_rollback_script_sync": check_file_list_presence,
    "release_changelog_sync": check_file_list_presence,
    "release_runner_sync": check_file_list_presence,
    "release_api_sync": check_file_list_presence,
    "release_architecture_sync": check_file_list_presence,
    "release_evolution_sync": check_file_list_presence,
    "release_test_snapshot_sync": check_file_list_presence,
    "release_regression_sync": check_file_list_presence,
    "release_judge_config_sync": check_file_list_presence,
    "release_judge_model_sync": check_file_list_presence,
    "release_eval_set_sync": check_file_list_presence,
    "release_candidate_change_sync": check_file_list_presence,
    "release_regression_report_sync": check_file_list_presence,
    "release_eval_set_config_sync": check_file_list_presence,
    "release_eval_set_schema_sync": check_file_list_presence,
    "release_candidate_change_schema_sync": check_file_list_presence,
    "release_regression_report_schema_sync": check_file_list_presence,
    "release_regression_output_sync": check_file_list_presence,
    "release_eval_set_directory_sync": check_file_list_presence,
    "release_rubric_sync": check_file_list_presence,
    "release_evaluation_api_sync": check_file_list_presence,
    "release_evaluation_architecture_sync": check_file_list_presence,
    "release_evaluation_evolution_sync": check_file_list_presence,
    "release_evaluation_test_snapshot_sync": check_file_list_presence,
    "release_evaluation_regression_sync": check_file_list_presence,
    "release_governance_doc_sync": check_file_list_presence,
    
    "release_manifest_dir_sync": check_file_list_presence,
    "release_active_manifest_sync": check_file_list_presence,
    "release_promote_script_sync": check_file_list_presence,
    "release_rollback_script_sync": check_file_list_presence,
    "release_changelog_sync": check_file_list_presence,
    "release_runner_sync": check_file_list_presence,
    "release_api_sync": check_file_list_presence,
    "release_architecture_sync": check_file_list_presence,
    "release_evolution_sync": check_file_list_presence,
    "release_test_snapshot_sync": check_file_list_presence,
    "release_regression_sync": check_file_list_presence,
    "release_judge_config_sync": check_file_list_presence,
    "release_judge_model_sync": check_file_list_presence,
    "release_eval_set_sync": check_file_list_presence,
    "release_candidate_change_sync": check_file_list_presence,
    "release_regression_report_sync": check_file_list_presence,
    "release_eval_set_config_sync": check_file_list_presence,
    "release_eval_set_schema_sync": check_file_list_presence,
    "release_candidate_change_schema_sync": check_file_list_presence,
    "release_regression_report_schema_sync": check_file_list_presence,
    "release_regression_output_sync": check_file_list_presence,
    "release_eval_set_directory_sync": check_file_list_presence,
    "release_rubric_sync": check_file_list_presence,
    "release_evaluation_api_sync": check_file_list_presence,
    "release_evaluation_architecture_sync": check_file_list_presence,
    "release_evaluation_evolution_sync": check_file_list_presence,
    "release_evaluation_test_snapshot_sync": check_file_list_presence,
    "release_evaluation_regression_sync": check_file_list_presence,
    "release_governance_doc_sync": check_file_list_presence,
}

def main():
    parser = argparse.ArgumentParser(description='文档同步检查器')
    parser.add_argument('--check-source', help='指定修改的源文件路径')
    parser.add_argument('--check-all', action='store_true', help='检查所有依赖关系')
    args = parser.parse_args()
    
    manifest = load_manifest()
    sync_deps = manifest.get('sync_dependencies', [])
    
    if args.check_all:
        sources_to_check = set()
        for dep in sync_deps:
            sources_to_check.add(dep['source'])
    elif args.check_source:
        sources_to_check = {args.check_source}
    else:
        parser.print_help()
        sys.exit(1)
    
    all_passed = True
    for dep in sync_deps:
        source = dep['source']
        if source not in sources_to_check and not args.check_all:
            continue
        
        source_path = resolve_path(source)
        if not os.path.exists(source_path):
            continue
        
        with open(source_path, 'r') as f:
            source_file = f.read()
        
        for trigger in dep.get('modify_triggers', []):
            target = trigger['target']
            target_path = resolve_path(target)
            check_kind = trigger['check_kind']
            reason = trigger.get('reason', '')
            
            if not os.path.exists(target_path):
                print(f'⚠️  目标文件不存在: {target_path}')
                continue
            
            with open(target_path, 'r') as f:
                target_file = f.read()
            
            checker = CHECKERS.get(check_kind)
            if not checker:
                print(f'⚠️  未知检查类型: {check_kind}')
                continue
            
            passed, issues = checker(source_path, target_path, source_file, target_file)
            if not passed:
                all_passed = False
                print(f'❌ {source} → {target} ({reason})')
                for issue in issues:
                    print(issue)
    
    if all_passed:
        print('✅ 所有关联文件已同步')
        sys.exit(0)
    else:
        print()
        print('请根据以上差异同步关联文件后重试')
        sys.exit(1)

if __name__ == '__main__':
    main()
