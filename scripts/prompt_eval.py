#!/usr/bin/env python3
"""
prompt_eval.py — 提示词质量评估脚本

功能：
  1. 对单个提示词进行质量评分（基于结构化完整性、清晰度、可执行性等维度）
  2. 对比提示词变更前后的质量得分
  3. 生成提示词质量评估报告
  4. 作为质量门禁：如果变更后得分下降超过阈值则阻断 promote

用法:
  # 评估单个提示词
  python scripts/prompt_eval.py --prompt prompts/business/business_model_design.system.md

  # 评估所有提示词
  python scripts/prompt_eval.py --all

  # 对比两个版本的提示词
  python scripts/prompt_eval.py --compare --before prompts/business/model_design_v1.md --after prompts/business/model_design_v2.md

  # 评估并输出 JSON 报告
  python scripts/prompt_eval.py --all --json
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
MANIFEST_PATH = "prompts/prompt_manifest.yaml"

# 质量评估维度及权重
QUALITY_DIMENSIONS = {
    "structure_completeness": {
        "weight": 0.20,
        "description": "结构化完整性 — 是否包含角色定义、任务目标、输出格式、行为约束等必需章节",
    },
    "clarity": {
        "weight": 0.20,
        "description": "清晰度 — 语言是否明确、无歧义，指令是否具体可执行",
    },
    "constraint_coverage": {
        "weight": 0.15,
        "description": "约束覆盖 — 是否包含行为边界、禁止事项、质量要求",
    },
    "output_specification": {
        "weight": 0.15,
        "description": "输出规范 — 输出格式定义是否清晰，是否包含示例或 schema",
    },
    "variable_usage": {
        "weight": 0.10,
        "description": "变量使用 — 占位符是否合理，是否与 manifest 声明一致",
    },
    "example_quality": {
        "weight": 0.10,
        "description": "示例质量 — 是否包含示例，示例是否有助于理解任务",
    },
    "conciseness": {
        "weight": 0.10,
        "description": "简洁性 — 是否在保持完整性的前提下避免冗余",
    },
}

# 必需章节检查（与 prompt_validator.py 保持一致）
REQUIRED_SECTION_PATTERNS = [
    (r"#\s*(角色定义|Role|角色)", "角色定义"),
    (r"#\s*(任务目标|Objective|目标)", "任务目标"),
    (r"#\s*(输出格式|Output Format|输出)", "输出格式"),
    (r"#\s*(行为约束|Constraints|约束|规则)", "行为约束"),
]

RECOMMENDED_SECTION_PATTERNS = [
    (r"#\s*(输入规范|Input|输入)", "输入规范"),
    (r"#\s*(评分标准|Scoring|评分)", "评分标准"),
    (r"#\s*(示例|Example|Examples)", "示例"),
]

# ── Logging ──

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("prompt_eval")


# ── File I/O ──

def load_text(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def save_json(data: Any, path: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


# ── Scoring Functions ──

def score_structure_completeness(content: str) -> Tuple[float, str]:
    """评估结构化完整性。"""
    found = 0
    total = len(REQUIRED_SECTION_PATTERNS)
    missing = []

    for pattern, name in REQUIRED_SECTION_PATTERNS:
        if re.search(pattern, content, re.IGNORECASE | re.MULTILINE):
            found += 1
        else:
            missing.append(name)

    # 也检查推荐章节
    rec_found = 0
    for pattern, name in RECOMMENDED_SECTION_PATTERNS:
        if re.search(pattern, content, re.IGNORECASE | re.MULTILINE):
            rec_found += 1

    # 得分：必需章节占 80%，推荐章节占 20%
    required_score = found / total if total > 0 else 0
    recommended_score = rec_found / len(RECOMMENDED_SECTION_PATTERNS) if RECOMMENDED_SECTION_PATTERNS else 0
    final_score = required_score * 0.8 + recommended_score * 0.2

    reasoning = f"必需章节: {found}/{total} 通过"
    if missing:
        reasoning += f", 缺少: {', '.join(missing)}"
    reasoning += f"; 推荐章节: {rec_found}/{len(RECOMMENDED_SECTION_PATTERNS)}"

    return round(final_score, 2), reasoning


def score_clarity(content: str) -> Tuple[float, str]:
    """评估清晰度。"""
    score = 0.5
    reasoning_parts = []

    # 1. 检查是否有明确的指令动词
    action_verbs = ["必须", "需要", "应当", "should", "must", "shall", "请", "请确保"]
    verb_count = sum(1 for v in action_verbs if v in content.lower())
    if verb_count >= 5:
        score += 0.2
        reasoning_parts.append("指令动词丰富")
    elif verb_count >= 3:
        score += 0.1
        reasoning_parts.append("有基本指令动词")
    else:
        score -= 0.1
        reasoning_parts.append("指令动词不足")

    # 2. 检查是否有否定/排除指令
    negation_patterns = ["不要", "禁止", "避免", "do not", "don't", "never", "avoid"]
    has_negation = any(p in content.lower() for p in negation_patterns)
    if has_negation:
        score += 0.1
        reasoning_parts.append("包含否定/排除指令")

    # 3. 检查是否有条件逻辑
    condition_patterns = ["如果", "当", "若", "if", "when", "in case", "unless"]
    has_conditions = any(p in content.lower() for p in condition_patterns)
    if has_conditions:
        score += 0.1
        reasoning_parts.append("包含条件逻辑")

    # 4. 检查是否有优先级/排序
    priority_patterns = ["优先", "首先", "然后", "最后", "first", "then", "finally", "优先级"]
    has_priority = any(p in content.lower() for p in priority_patterns)
    if has_priority:
        score += 0.1
        reasoning_parts.append("包含优先级/排序")

    # 5. 检查文件大小（过小说明不够详细）
    lines = content.split("\n")
    if len(lines) >= 50:
        score += 0.1
        reasoning_parts.append("内容详细")
    elif len(lines) < 15:
        score -= 0.1
        reasoning_parts.append("内容过于简短")

    final_score = max(0.0, min(1.0, score))
    reasoning = "; ".join(reasoning_parts) if reasoning_parts else "基础清晰度"

    return round(final_score, 2), reasoning


def score_constraint_coverage(content: str) -> Tuple[float, str]:
    """评估约束覆盖。"""
    score = 0.3
    reasoning_parts = []

    # 检查各种约束类型
    constraint_categories = {
        "质量约束": ["质量", "quality", "准确", "accuracy", "精确"],
        "安全约束": ["安全", "safety", "隐私", "privacy", "保密"],
        "格式约束": ["格式", "format", "结构", "structure", "schema"],
        "行为约束": ["禁止", "不要", "避免", "must not", "should not"],
        "边界约束": ["范围", "scope", "限制", "limit", "仅限"],
    }

    found_categories = 0
    for category, keywords in constraint_categories.items():
        if any(k in content.lower() for k in keywords):
            found_categories += 1
            reasoning_parts.append(f"包含{category}")

    score += found_categories * 0.12
    if found_categories >= 3:
        score += 0.1  # 覆盖多种约束类型加分

    # 检查是否有明确的"禁止"列表
    if re.search(r"[-*]\s*(不要|禁止|避免|do not|must not)", content, re.IGNORECASE):
        score += 0.1
        reasoning_parts.append("有明确禁止列表")

    final_score = max(0.0, min(1.0, score))
    reasoning = "; ".join(reasoning_parts) if reasoning_parts else "约束覆盖不足"

    return round(final_score, 2), reasoning


def score_output_specification(content: str) -> Tuple[float, str]:
    """评估输出规范。"""
    score = 0.3
    reasoning_parts = []

    # 1. 检查是否有输出格式定义
    format_patterns = [
        r"输出格式", r"Output Format", r"输出结构", r"output structure",
        r"JSON", r"Markdown", r"markdown", r"YAML", r"yaml",
    ]
    has_format = any(re.search(p, content, re.IGNORECASE) for p in format_patterns)
    if has_format:
        score += 0.2
        reasoning_parts.append("有输出格式定义")

    # 2. 检查是否有输出字段/属性列表
    field_patterns = [r"字段", r"field", r"属性", r"property", r"attribute"]
    has_fields = any(p in content.lower() for p in field_patterns)
    if has_fields:
        score += 0.15
        reasoning_parts.append("有输出字段列表")

    # 3. 检查是否有 schema 或模板
    schema_patterns = [r"```json", r"```yaml", r"schema", r"template", r"模板"]
    has_schema = any(p in content.lower() for p in schema_patterns)
    if has_schema:
        score += 0.2
        reasoning_parts.append("包含 schema/模板")

    # 4. 检查是否有示例输出
    example_patterns = [r"示例", r"example", r"例如", r"for example", r"e\.g\."]
    has_example = any(re.search(p, content, re.IGNORECASE) for p in example_patterns)
    if has_example:
        score += 0.15
        reasoning_parts.append("包含输出示例")

    final_score = max(0.0, min(1.0, score))
    reasoning = "; ".join(reasoning_parts) if reasoning_parts else "输出规范不足"

    return round(final_score, 2), reasoning


def score_variable_usage(content: str, manifest_entry: Optional[Dict] = None) -> Tuple[float, str]:
    """评估变量使用。"""
    score = 0.5
    reasoning_parts = []

    # 提取占位符
    placeholder_pattern = re.compile(r"\{\{(\w+)\}\}|\{(\w+)\}")
    placeholders = set()
    for match in placeholder_pattern.finditer(content):
        ph = match.group(1) or match.group(2)
        placeholders.add(ph)

    if not placeholders:
        score = 0.7  # 没有占位符也可以接受（静态提示词）
        reasoning_parts.append("静态提示词，无需变量")
    else:
        score += 0.1
        reasoning_parts.append(f"使用了 {len(placeholders)} 个占位符")

        # 如果提供了 manifest 条目，检查一致性
        if manifest_entry:
            declared_vars = [v["name"] for v in manifest_entry.get("variables", [])]
            undeclared = [ph for ph in placeholders if ph not in declared_vars]
            unused = [v for v in declared_vars if v not in placeholders]

            if undeclared:
                score -= 0.2
                reasoning_parts.append(f"未声明占位符: {undeclared}")
            if unused:
                score -= 0.1
                reasoning_parts.append(f"未使用变量: {unused}")
            if not undeclared and not unused:
                score += 0.1
                reasoning_parts.append("变量声明与使用一致")

    final_score = max(0.0, min(1.0, score))
    reasoning = "; ".join(reasoning_parts) if reasoning_parts else "基础变量使用"

    return round(final_score, 2), reasoning


def score_example_quality(content: str) -> Tuple[float, str]:
    """评估示例质量。"""
    score = 0.3
    reasoning_parts = []

    # 1. 检查是否有示例章节
    has_example_section = bool(re.search(
        r"#\s*(示例|Example|Examples)", content, re.IGNORECASE | re.MULTILINE
    ))
    if has_example_section:
        score += 0.3
        reasoning_parts.append("有独立示例章节")

    # 2. 检查示例数量
    example_markers = ["示例", "Example", "例如", "For example", "e.g."]
    example_count = sum(1 for m in example_markers if m in content)
    if example_count >= 3:
        score += 0.2
        reasoning_parts.append("示例丰富")
    elif example_count >= 1:
        score += 0.1
        reasoning_parts.append("有基本示例")

    # 3. 检查是否有代码块示例
    code_blocks = re.findall(r"```", content)
    if len(code_blocks) >= 2:  # 至少一对 ``` ```
        score += 0.2
        reasoning_parts.append("包含代码块示例")

    final_score = max(0.0, min(1.0, score))
    reasoning = "; ".join(reasoning_parts) if reasoning_parts else "缺少示例"

    return round(final_score, 2), reasoning


def score_conciseness(content: str) -> Tuple[float, str]:
    """评估简洁性。"""
    lines = content.split("\n")
    total_lines = len(lines)
    total_chars = len(content)

    # 理想范围：100-500 行，2000-10000 字符
    reasoning_parts = []

    if total_lines < 10:
        score = 0.3
        reasoning_parts.append("过于简短，可能信息不足")
    elif total_lines < 30:
        score = 0.6
        reasoning_parts.append("较为简洁")
    elif total_lines < 100:
        score = 0.8
        reasoning_parts.append("长度适中")
    elif total_lines < 300:
        score = 0.7
        reasoning_parts.append("偏长但可接受")
    else:
        score = 0.5
        reasoning_parts.append("过长，建议精简")

    # 检查是否有冗余重复
    # 简单的重复检测：检查是否有连续重复的行
    unique_lines_ratio = len(set(lines)) / max(len(lines), 1)
    if unique_lines_ratio < 0.8:
        score -= 0.1
        reasoning_parts.append("存在重复内容")

    # 检查注释比例（注释过多可能影响可读性）
    comment_lines = sum(1 for l in lines if l.strip().startswith("#") or l.strip().startswith("<!--"))
    comment_ratio = comment_lines / max(total_lines, 1)
    if comment_ratio > 0.3:
        score -= 0.1
        reasoning_parts.append("注释比例偏高")

    final_score = max(0.0, min(1.0, score))
    reasoning = "; ".join(reasoning_parts) if reasoning_parts else "简洁性适中"

    return round(final_score, 2), reasoning


# ── Full Evaluation ──

def evaluate_prompt(
    prompt_path: str,
    manifest_entry: Optional[Dict] = None,
) -> Dict[str, Any]:
    """
    对单个提示词进行完整质量评估。

    Returns:
        {
            "path": str,
            "exists": bool,
            "dimension_scores": { dim: { score, reasoning } },
            "overall_score": float,
            "passed": bool,
            "threshold": float,
        }
    """
    result = {
        "path": prompt_path,
        "exists": False,
        "dimension_scores": {},
        "overall_score": 0.0,
        "passed": False,
        "threshold": 0.5,
    }

    if not os.path.exists(prompt_path):
        result["errors"] = [f"文件不存在: {prompt_path}"]
        return result

    result["exists"] = True
    content = load_text(prompt_path)

    # 逐维度评分
    dim_scores = {}

    # 1. 结构完整性
    s, r = score_structure_completeness(content)
    dim_scores["structure_completeness"] = {"score": s, "reasoning": r}

    # 2. 清晰度
    s, r = score_clarity(content)
    dim_scores["clarity"] = {"score": s, "reasoning": r}

    # 3. 约束覆盖
    s, r = score_constraint_coverage(content)
    dim_scores["constraint_coverage"] = {"score": s, "reasoning": r}

    # 4. 输出规范
    s, r = score_output_specification(content)
    dim_scores["output_specification"] = {"score": s, "reasoning": r}

    # 5. 变量使用
    s, r = score_variable_usage(content, manifest_entry)
    dim_scores["variable_usage"] = {"score": s, "reasoning": r}

    # 6. 示例质量
    s, r = score_example_quality(content)
    dim_scores["example_quality"] = {"score": s, "reasoning": r}

    # 7. 简洁性
    s, r = score_conciseness(content)
    dim_scores["conciseness"] = {"score": s, "reasoning": r}

    result["dimension_scores"] = dim_scores

    # 计算加权总分
    overall = 0.0
    for dim, info in QUALITY_DIMENSIONS.items():
        if dim in dim_scores:
            overall += dim_scores[dim]["score"] * info["weight"]

    result["overall_score"] = round(overall, 2)
    result["passed"] = overall >= result["threshold"]

    return result


def evaluate_all_prompts() -> Dict[str, Any]:
    """评估所有在 manifest 中注册的提示词。"""
    # 加载 manifest
    manifest_data = {}
    if os.path.exists(MANIFEST_PATH):
        with open(MANIFEST_PATH, "r") as f:
            manifest_data = yaml.safe_load(f)

    prompts_list = manifest_data.get("prompt_manifest", {}).get("prompts", [])
    indexed = {p["id"]: p for p in prompts_list}

    results = []
    for pid, entry in indexed.items():
        prompt_path = entry.get("path", "")
        if not prompt_path:
            continue
        eval_result = evaluate_prompt(prompt_path, entry)
        results.append(eval_result)

    # 统计
    total = len(results)
    passed = sum(1 for r in results if r.get("passed", False))
    failed = total - passed
    avg_score = round(
        sum(r.get("overall_score", 0) for r in results) / max(total, 1),
        2,
    )

    return {
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
        "total_prompts": total,
        "passed": passed,
        "failed": failed,
        "average_score": avg_score,
        "results": results,
    }


# ── Comparison ──

def compare_prompts(before_path: str, after_path: str) -> Dict[str, Any]:
    """对比两个版本的提示词质量。"""
    before_result = evaluate_prompt(before_path)
    after_result = evaluate_prompt(after_path)

    comparison = {
        "before": {
            "path": before_path,
            "overall_score": before_result.get("overall_score", 0),
            "dimension_scores": before_result.get("dimension_scores", {}),
        },
        "after": {
            "path": after_path,
            "overall_score": after_result.get("overall_score", 0),
            "dimension_scores": after_result.get("dimension_scores", {}),
        },
        "delta": round(
            after_result.get("overall_score", 0) - before_result.get("overall_score", 0),
            2,
        ),
        "dimension_deltas": {},
        "verdict": "",
    }

    # 逐维度对比
    all_dims = set(list(before_result.get("dimension_scores", {}).keys()) +
                   list(after_result.get("dimension_scores", {}).keys()))

    for dim in sorted(all_dims):
        before_score = before_result.get("dimension_scores", {}).get(dim, {}).get("score", 0)
        after_score = after_result.get("dimension_scores", {}).get(dim, {}).get("score", 0)
        comparison["dimension_deltas"][dim] = round(after_score - before_score, 2)

    # 判定
    delta = comparison["delta"]
    if delta >= 0.05:
        comparison["verdict"] = "improved"
    elif delta >= -0.05:
        comparison["verdict"] = "unchanged"
    else:
        comparison["verdict"] = "degraded"

    return comparison


# ── CLI ──

def main():
    parser = argparse.ArgumentParser(
        description="提示词质量评估脚本",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 评估单个提示词
  python scripts/prompt_eval.py --prompt prompts/business/business_model_design.system.md

  # 评估所有提示词
  python scripts/prompt_eval.py --all

  # 对比两个版本
  python scripts/prompt_eval.py --compare --before prompts/v1.md --after prompts/v2.md

  # 评估并输出 JSON
  python scripts/prompt_eval.py --all --json
        """,
    )
    parser.add_argument("--prompt", type=str, help="评估单个提示词文件")
    parser.add_argument("--all", action="store_true", help="评估所有提示词")
    parser.add_argument("--compare", action="store_true", help="对比模式")
    parser.add_argument("--before", type=str, help="对比模式：旧版本路径")
    parser.add_argument("--after", type=str, help="对比模式：新版本路径")
    parser.add_argument("--json", action="store_true", help="输出 JSON 格式报告")
    parser.add_argument("--output", type=str, default="", help="报告输出路径")

    args = parser.parse_args()

    if args.compare:
        if not args.before or not args.after:
            parser.print_help()
            print("\n错误: 对比模式需要 --before 和 --after")
            sys.exit(1)

        comparison = compare_prompts(args.before, args.after)

        if args.json:
            output_path = args.output or "outputs/prompt_comparison_report.json"
            save_json(comparison, output_path)
            print(f"✅ 对比报告已保存: {output_path}")
        else:
            print(f"\n{'=' * 60}")
            print(f"提示词质量对比")
            print(f"{'─' * 60}")
            print(f"  Before: {comparison['before']['path']}")
            print(f"  After:  {comparison['after']['path']}")
            print(f"  总分变化: {comparison['delta']:+.2f}")
            print(f"  判定: {comparison['verdict']}")
            print(f"{'─' * 60}")
            print(f"  维度变化:")
            for dim, delta in comparison["dimension_deltas"].items():
                icon = "↑" if delta > 0 else ("↓" if delta < 0 else "→")
                print(f"    {dim:25s} {icon} {delta:+.2f}")
            print(f"{'=' * 60}")

        return

    if args.prompt:
        manifest_entry = None
        if os.path.exists(MANIFEST_PATH):
            with open(MANIFEST_PATH, "r") as f:
                manifest_data = yaml.safe_load(f)
            for p in manifest_data.get("prompt_manifest", {}).get("prompts", []):
                if p.get("path") == args.prompt:
                    manifest_entry = p
                    break

        result = evaluate_prompt(args.prompt, manifest_entry)

        if args.json:
            output_path = args.output or "outputs/prompt_eval_report.json"
            save_json(result, output_path)
            print(f"✅ 评估报告已保存: {output_path}")
        else:
            print(f"\n{'=' * 60}")
            print(f"提示词质量评估: {result['path']}")
            print(f"{'─' * 60}")
            print(f"  总分: {result['overall_score']:.2f} / 1.00")
            print(f"  状态: {'✅ 通过' if result.get('passed') else '❌ 未通过'}")
            print(f"{'─' * 60}")
            print(f"  维度评分:")
            for dim, info in result.get("dimension_scores", {}).items():
                bar = "█" * int(info["score"] * 10) + "░" * (10 - int(info["score"] * 10))
                print(f"    {dim:25s} {bar} {info['score']:.2f}")
                print(f"    {' ' * 25}  {info['reasoning']}")
            print(f"{'=' * 60}")

    elif args.all:
        report = evaluate_all_prompts()

        if args.json:
            output_path = args.output or "outputs/prompt_eval_report_all.json"
            save_json(report, output_path)
            print(f"✅ 评估报告已保存: {output_path}")
        else:
            print(f"\n{'=' * 60}")
            print(f"提示词质量评估汇总")
            print(f"{'─' * 60}")
            print(f"  总数: {report['total_prompts']}")
            print(f"  通过: {report['passed']}")
            print(f"  未通过: {report['failed']}")
            print(f"  平均分: {report['average_score']:.2f}")
            print(f"{'─' * 60}")
            for r in report.get("results", []):
                status = "✅" if r.get("passed") else "❌"
                print(f"  {status} {r['path']:55s} {r['overall_score']:.2f}")
            print(f"{'=' * 60}")

    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
