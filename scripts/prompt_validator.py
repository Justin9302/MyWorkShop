#!/usr/bin/env python3
"""
prompt_validator.py — 提示词验证与质量门禁

功能：
  1. 验证提示词文件是否存在、格式是否正确
  2. 校验提示词是否包含必需的结构化字段（角色定义、任务目标、输出格式、行为约束）
  3. 校验提示词中的占位符是否与 manifest 中声明的变量一致
  4. 校验 workflow YAML 引用的提示词路径是否与 manifest 一致
  5. 生成验证报告

用法:
  # 验证所有提示词
  python scripts/prompt_validator.py --all

  # 验证单个提示词
  python scripts/prompt_validator.py --prompt prompts/business/business_model_design.system.md

  # 验证提示词与工作流引用的交叉一致性
  python scripts/prompt_validator.py --cross-check

  # 验证并输出 JSON 报告
  python scripts/prompt_validator.py --all --json
"""

import argparse
import json
import logging
import os
import re
import sys
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

try:
    import yaml
except ImportError:
    print("⚠️  PyYAML not installed. Run: pip install pyyaml", file=sys.stderr)
    sys.exit(1)

# ── Constants ──

PROMPTS_DIR = "prompts"
WORKFLOWS_DIR = "workflows"
MANIFEST_PATH = "prompts/prompt_manifest.yaml"

# 提示词文件必须包含的结构化章节（正则匹配）
REQUIRED_SECTIONS = [
    (r"#\s*(角色定义|Role|角色)", "角色定义"),
    (r"#\s*(任务目标|Objective|目标)", "任务目标"),
    (r"#\s*(输出格式|Output Format|输出)", "输出格式"),
    (r"#\s*(行为约束|Constraints|约束|规则)", "行为约束"),
]

# 可选但推荐的结构化章节
RECOMMENDED_SECTIONS = [
    (r"#\s*(输入规范|Input|输入)", "输入规范"),
    (r"#\s*(评分标准|Scoring|评分)", "评分标准"),
    (r"#\s*(示例|Example|Examples)", "示例"),
]

# 占位符正则：{{placeholder}} 或 {placeholder}
PLACEHOLDER_PATTERN = re.compile(r"\{\{(\w+)\}\}|\{(\w+)\}")

# ── Logging ──

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("prompt_validator")


# ── File I/O ──

def load_yaml(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_text(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def save_json(data: Any, path: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


# ── Manifest Loading ──

def load_manifest() -> Dict[str, Any]:
    """加载 prompt_manifest.yaml，返回 prompts 列表的索引字典。"""
    if not os.path.exists(MANIFEST_PATH):
        logger.error("Manifest 文件不存在: %s", MANIFEST_PATH)
        return {"prompts": {}}

    manifest = load_yaml(MANIFEST_PATH)
    prompts_list = manifest.get("prompt_manifest", {}).get("prompts", [])

    # 构建 id → entry 的索引
    indexed = {}
    for p in prompts_list:
        indexed[p["id"]] = p

    return {"prompts": indexed, "raw": manifest}


# ── Individual Prompt Validation ──

def validate_prompt_file(prompt_path: str) -> Dict[str, Any]:
    """
    验证单个提示词文件。

    Returns:
        {
            "path": str,
            "exists": bool,
            "errors": [str],
            "warnings": [str],
            "sections_found": [str],
            "sections_missing": [str],
            "placeholders": [str],
            "declared_variables": [str],
            "unused_variables": [str],
            "undeclared_placeholders": [str],
            "file_size_bytes": int,
            "line_count": int,
        }
    """
    result = {
        "path": prompt_path,
        "exists": False,
        "errors": [],
        "warnings": [],
        "sections_found": [],
        "sections_missing": [],
        "placeholders": [],
        "declared_variables": [],
        "unused_variables": [],
        "undeclared_placeholders": [],
        "file_size_bytes": 0,
        "line_count": 0,
    }

    # 1. 检查文件是否存在
    if not os.path.exists(prompt_path):
        result["errors"].append(f"文件不存在: {prompt_path}")
        return result

    result["exists"] = True
    content = load_text(prompt_path)
    result["file_size_bytes"] = os.path.getsize(prompt_path)
    result["line_count"] = len(content.split("\n"))

    # 2. 检查文件大小（空文件或过小）
    if result["file_size_bytes"] < 50:
        result["errors"].append(f"文件过小 ({result['file_size_bytes']} bytes)，可能内容不完整")
    elif result["file_size_bytes"] < 200:
        result["warnings"].append(f"文件偏小 ({result['file_size_bytes']} bytes)，建议补充更多内容")

    # 3. 检查必需的结构化章节
    for pattern, section_name in REQUIRED_SECTIONS:
        if re.search(pattern, content, re.IGNORECASE | re.MULTILINE):
            result["sections_found"].append(section_name)
        else:
            result["errors"].append(f"缺少必需章节: {section_name}")

    # 4. 检查推荐的章节
    for pattern, section_name in RECOMMENDED_SECTIONS:
        if re.search(pattern, content, re.IGNORECASE | re.MULTILINE):
            result["sections_found"].append(section_name)
        else:
            result["warnings"].append(f"缺少推荐章节: {section_name}")

    # 5. 提取占位符
    placeholders = set()
    for match in PLACEHOLDER_PATTERN.finditer(content):
        ph = match.group(1) or match.group(2)
        placeholders.add(ph)
    result["placeholders"] = sorted(placeholders)

    return result


def validate_against_manifest(
    prompt_path: str,
    manifest_entry: Optional[Dict[str, Any]],
    file_result: Dict[str, Any],
) -> Dict[str, Any]:
    """
    将文件验证结果与 manifest 声明进行交叉校验。

    Returns:
        更新后的 file_result（添加 manifest 相关字段）
    """
    if not manifest_entry:
        file_result["warnings"].append(f"Manifest 中未找到该提示词的元数据")
        return file_result

    # 1. 检查 manifest 中声明的变量
    declared_vars = manifest_entry.get("variables", [])
    declared_var_names = [v["name"] for v in declared_vars]
    file_result["declared_variables"] = declared_var_names

    # 2. 检查占位符是否在 manifest 中声明
    for ph in file_result["placeholders"]:
        if ph not in declared_var_names:
            file_result["undeclared_placeholders"].append(ph)

    # 3. 检查 manifest 中声明的变量是否在文件中使用
    for var_name in declared_var_names:
        if var_name not in file_result["placeholders"]:
            file_result["unused_variables"].append(var_name)

    # 4. 检查版本一致性
    manifest_version = manifest_entry.get("version", "unknown")
    file_result["manifest_version"] = manifest_version

    return file_result


# ── Cross-check: Workflow YAML → Prompt Path ──

def cross_check_workflow_prompts() -> List[Dict[str, Any]]:
    """
    交叉校验 workflow YAML 中引用的提示词路径是否与 manifest 一致。

    Returns:
        [{
            "workflow_path": str,
            "workflow_id": str,
            "referenced_prompt": str,
            "manifest_entry": str | None,
            "file_exists": bool,
            "issues": [str],
        }, ...]
    """
    manifest_data = load_manifest()
    indexed_prompts = manifest_data.get("prompts", {})

    results = []

    # 遍历所有 workflow YAML
    for root, dirs, files in os.walk(WORKFLOWS_DIR):
        for fname in files:
            if not fname.endswith(".yaml"):
                continue

            wf_path = os.path.join(root, fname)
            try:
                workflow = load_yaml(wf_path)
            except Exception as e:
                results.append({
                    "workflow_path": wf_path,
                    "workflow_id": "unknown",
                    "referenced_prompt": "",
                    "manifest_entry": None,
                    "file_exists": False,
                    "issues": [f"无法解析 YAML: {e}"],
                })
                continue

            wf_id = workflow.get("workflow", {}).get("id", "unknown")

            # 检查 outputs.template 字段
            outputs = workflow.get("outputs", {}) or workflow.get("output", {})
            template_path = outputs.get("template", "")

            if not template_path:
                results.append({
                    "workflow_path": wf_path,
                    "workflow_id": wf_id,
                    "referenced_prompt": "",
                    "manifest_entry": None,
                    "file_exists": False,
                    "issues": ["工作流未定义 outputs.template"],
                })
                continue

            # 检查文件是否存在
            file_exists = os.path.exists(template_path)

            # 检查 manifest 中是否有对应条目
            manifest_entry = None
            for pid, entry in indexed_prompts.items():
                if entry.get("path") == template_path:
                    manifest_entry = pid
                    break

            issues = []
            if not file_exists:
                issues.append(f"引用的提示词文件不存在: {template_path}")
            if not manifest_entry:
                issues.append(f"Manifest 中未找到该提示词路径: {template_path}")

            results.append({
                "workflow_path": wf_path,
                "workflow_id": wf_id,
                "referenced_prompt": template_path,
                "manifest_entry": manifest_entry,
                "file_exists": file_exists,
                "issues": issues,
            })

    return results


# ── Full Validation ──

def run_full_validation(
    specific_prompt: Optional[str] = None,
    cross_check: bool = False,
) -> Dict[str, Any]:
    """
    运行完整的提示词验证。

    Args:
        specific_prompt: 如果指定，只验证该提示词文件
        cross_check: 是否执行交叉校验

    Returns:
        {
            "validated_at": str,
            "total_prompts": int,
            "passed": int,
            "failed": int,
            "results": [Dict],
            "cross_check_results": [Dict] | None,
            "summary": str,
        }
    """
    manifest_data = load_manifest()
    indexed_prompts = manifest_data.get("prompts", {})

    results = []

    if specific_prompt:
        # 验证单个提示词
        file_result = validate_prompt_file(specific_prompt)

        # 查找 manifest 条目
        manifest_entry = None
        for pid, entry in indexed_prompts.items():
            if entry.get("path") == specific_prompt:
                manifest_entry = entry
                break

        file_result = validate_against_manifest(specific_prompt, manifest_entry, file_result)
        results.append(file_result)
    else:
        # 验证所有提示词
        for pid, entry in indexed_prompts.items():
            prompt_path = entry.get("path", "")
            if not prompt_path:
                continue

            file_result = validate_prompt_file(prompt_path)
            file_result = validate_against_manifest(prompt_path, entry, file_result)
            results.append(file_result)

        # 也检查 prompts/ 目录下但不在 manifest 中的文件
        for root, dirs, files in os.walk(PROMPTS_DIR):
            for fname in files:
                if not fname.endswith(".system.md"):
                    continue
                fpath = os.path.join(root, fname)
                # 检查是否已在 manifest 中
                in_manifest = any(
                    entry.get("path") == fpath
                    for entry in indexed_prompts.values()
                )
                if not in_manifest:
                    file_result = validate_prompt_file(fpath)
                    file_result["warnings"].append(f"文件不在 manifest 中: {fpath}")
                    results.append(file_result)

    # 交叉校验
    cross_check_results = None
    if cross_check:
        cross_check_results = cross_check_workflow_prompts()

    # 统计
    total = len(results)
    passed = sum(
        1 for r in results
        if r["exists"] and len(r["errors"]) == 0
    )
    failed = total - passed

    # 生成摘要
    summary_lines = []
    summary_lines.append(f"验证完成: {total} 个提示词, {passed} 通过, {failed} 失败")
    for r in results:
        status = "✅" if r["exists"] and len(r["errors"]) == 0 else "❌"
        summary_lines.append(f"  {status} {r['path']}")
        for err in r["errors"]:
            summary_lines.append(f"    错误: {err}")
        for warn in r["warnings"]:
            summary_lines.append(f"    警告: {warn}")
        if r["undeclared_placeholders"]:
            summary_lines.append(f"    未声明占位符: {r['undeclared_placeholders']}")
        if r["unused_variables"]:
            summary_lines.append(f"    未使用变量: {r['unused_variables']}")

    if cross_check_results:
        summary_lines.append(f"\n交叉校验: {len(cross_check_results)} 个工作流")
        for cr in cross_check_results:
            if cr["issues"]:
                summary_lines.append(f"  ⚠️  {cr['workflow_path']}")
                for issue in cr["issues"]:
                    summary_lines.append(f"    - {issue}")

    return {
        "validated_at": datetime.now(timezone.utc).isoformat(),
        "total_prompts": total,
        "passed": passed,
        "failed": failed,
        "results": results,
        "cross_check_results": cross_check_results,
        "summary": "\n".join(summary_lines),
    }


# ── CLI ──

def main():
    parser = argparse.ArgumentParser(
        description="提示词验证与质量门禁",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 验证所有提示词
  python scripts/prompt_validator.py --all

  # 验证单个提示词
  python scripts/prompt_validator.py --prompt prompts/business/business_model_design.system.md

  # 交叉校验工作流引用
  python scripts/prompt_validator.py --cross-check

  # 完整验证 + 交叉校验 + JSON 输出
  python scripts/prompt_validator.py --all --cross-check --json
        """,
    )
    parser.add_argument("--all", action="store_true", help="验证所有提示词")
    parser.add_argument("--prompt", type=str, help="验证单个提示词文件")
    parser.add_argument("--cross-check", action="store_true", help="交叉校验工作流引用")
    parser.add_argument("--json", action="store_true", help="输出 JSON 格式报告")
    parser.add_argument("--output", type=str, default="", help="报告输出路径")

    args = parser.parse_args()

    if not args.all and not args.prompt:
        parser.print_help()
        print("\n错误: 请指定 --all 或 --prompt")
        sys.exit(1)

    # 运行验证
    report = run_full_validation(
        specific_prompt=args.prompt,
        cross_check=args.cross_check,
    )

    # 输出
    if args.json:
        output_path = args.output or "outputs/prompt_validation_report.json"
        save_json(report, output_path)
        print(f"✅ 验证报告已保存: {output_path}")
    else:
        print(report["summary"])

    # 退出码
    if report["failed"] > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
