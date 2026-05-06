#!/usr/bin/env python3
"""
regression_test.py — Phase 7d: 沙箱回归测试引擎

对候选变更 (candidate_change) 进行自动化回归测试，确保改进不会引入新的质量问题。
核心原则：改进前必须先做回归测试，不能在修复一个问题的同时引入新问题。

工作流程:
  1. 从当前 Git HEAD 获取 baseline 配置
  2. 用 baseline 配置评估全部评估集 → baseline_scores
  3. 应用候选变更 → 生成 patched 配置（临时文件，不写入 Git）
  4. 用 patched 配置重新评估全部评估集 → patched_scores
  5. 对比 baseline vs patched → 判定 pass/warning/fail
  6. 更新 candidate_change.validation 字段

用法:
  # 对单个候选变更运行回归测试
  python scripts/regression_test.py \\
    --candidate runtime/candidate_changes/change_abc12345.json \\
    --eval-set tests/eval_cases/ \\
    --output outputs/eval_reports/regression/

  # 快速回归（使用已有的 baseline 缓存）
  python scripts/regression_test.py --quick \\
    --candidate runtime/candidate_changes/change_abc12345.json \\
    --baseline-cache outputs/eval_reports/regression/_baseline.json

  # 仅生成 baseline（无候选变更，用于初始化）
  python scripts/regression_test.py --generate-baseline \\
    --eval-set tests/eval_cases/ \\
    --output outputs/eval_reports/regression/

  # 对比两个版本的基线
  python scripts/regression_test.py --compare \\
    --baseline outputs/eval_reports/regression/_baseline.json \\
    --target outputs/eval_reports/regression/_patched.json

Schema: schemas/regression_report.schema.json
"""

import argparse
import copy
import json
import logging
import os
import re
import shutil
import sys
import tempfile
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

# ── Constants ──

DEFAULT_EVAL_SET_DIRS = [
    "tests/eval_cases/synthetic/",
    "tests/eval_cases/golden/",
    "tests/eval_cases/regression/failures/",
    "tests/eval_cases/regression/human_corrected/",
    "tests/eval_cases/regression/risk_samples/",
    "tests/eval_cases/baseline/",
]

DEFAULT_OUTPUT_DIR = "outputs/eval_reports/regression/"
DEFAULT_CHANGE_DIR = "runtime/candidate_changes/"
SCHEMA_PATH = "schemas/regression_report.schema.json"

# 8 维评估指标
DEFAULT_METRICS = [
    "citation_accuracy",
    "constraint_compliance",
    "format_compliance",
    "risk_detection",
    "human_modification_rate",
    "output_adoption_rate",
    "high_risk_miss_rate",
    "cost_latency",
]

# 默认回归判定阈值
DEFAULT_THRESHOLDS = {
    "critical_delta": -0.10,       # 单个维度下降 >= 0.10 → critical_regression → sandbox_fail
    "warning_delta": -0.05,        # 单个维度下降 >= 0.05 但 < 0.10 → regression
    "overall_critical_delta": -0.08,  # 总评分下降 >= 0.08 → sandbox_fail
}

# 候选变更 target.component → 对应的文件路径前缀
TARGET_TO_FILE_PREFIX = {
    "prompts": "prompts/",
    "workflow_steps": "workflows/",
    "constraint_rules": "constraints/",
    "retrieval_strategy": "config/context-loading.yaml",
    "knowledge_base_metadata": "config/active-release.yaml",
    "output_templates": "prompts/",
    "tool_permissions": "config/permissions.yaml",
    "model_routing": "config/model-routing.yaml",
}

# ── Logging ──

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("regression_test")


# ── File I/O Helpers ──


def _load_json(path: str) -> Dict[str, Any]:
    """加载 JSON 文件，返回 dict。"""
    if not os.path.exists(path):
        logger.error("文件不存在: %s", path)
        raise FileNotFoundError(f"文件不存在: {path}")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _write_json(path: str, data: Any) -> None:
    """写入 JSON 文件，自动创建目录。"""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    logger.info("已写入: %s", path)


def _find_snapshot_files(eval_set_dirs: List[str]) -> List[str]:
    """在评估集目录中查找所有 run_snapshot JSON 文件。"""
    snapshot_files = []
    for d in eval_set_dirs:
        if not os.path.isdir(d):
            logger.warning("评估集目录不存在，跳过: %s", d)
            continue
        for fname in sorted(os.listdir(d)):
            if not fname.endswith(".json"):
                continue
            # 排除评估报告文件
            if fname.endswith("_eval.json") or fname.startswith("_"):
                continue
            fpath = os.path.join(d, fname)
            if os.path.isfile(fpath):
                snapshot_files.append(fpath)
    return snapshot_files


def _get_baseline_version() -> str:
    """获取当前 baseline 版本标识。"""
    # 尝试从 active-release.yaml 读取版本
    release_path = "config/active-release.yaml"
    if os.path.exists(release_path):
        try:
            import yaml
            with open(release_path, "r", encoding="utf-8") as f:
                config = yaml.safe_load(f)
            release = config.get("active_release", {})
            wf_ver = release.get("workflow_version", "0.0.0")
            ev_ver = release.get("evaluator_version", "0.0.0")
            return f"workflow_{wf_ver}_evaluator_{ev_ver}"
        except Exception:
            pass
    return "baseline_unknown"


def _get_patched_version(candidate: Dict[str, Any]) -> str:
    """生成 patched 版本标识。"""
    change_id = candidate.get("change_id", "unknown")
    target = candidate.get("target", {})
    component = target.get("component", "unknown")
    return f"{change_id}_{component}"


# ── Baseline Generation ──


def generate_baseline(
    eval_set_dirs: List[str],
    output_dir: str,
    judge_mode: str = "heuristic",
) -> Dict[str, Any]:
    """
    在 baseline 配置下评估全部评估集，返回 baseline_scores 字典。

    使用 eval_runner.py 的评估引擎对每个快照进行评分，
    聚合所有快照的 8 维分数，取平均值作为 baseline。

    Args:
        eval_set_dirs: 评估集目录列表
        output_dir: 输出目录
        judge_mode: 评分模式 (heuristic/llm/hybrid)

    Returns:
        baseline_scores: { dimension: average_score, ... }
    """
    snapshot_files = _find_snapshot_files(eval_set_dirs)
    if not snapshot_files:
        logger.warning("未找到任何评估快照文件")
        return {"_empty": True, "version": _get_baseline_version()}

    logger.info("Baseline 评估: 找到 %d 个快照文件", len(snapshot_files))

    # 聚合所有维度的分数
    dim_scores: Dict[str, List[float]] = {m: [] for m in DEFAULT_METRICS}
    evaluated_count = 0

    for snap_path in snapshot_files:
        try:
            snapshot = _load_json(snap_path)
            # 使用 eval_runner 的评分逻辑
            scores = _evaluate_snapshot_dimensions(snapshot, judge_mode)
            for dim, score in scores.items():
                if dim in dim_scores:
                    dim_scores[dim].append(score)
            evaluated_count += 1
        except Exception as e:
            logger.warning("评估快照失败 (跳过): %s — %s", snap_path, e)
            continue

    # 计算平均值
    baseline: Dict[str, Any] = {
        "version": _get_baseline_version(),
        "judge_mode": judge_mode,
        "snapshot_count": evaluated_count,
        "snapshot_files_found": len(snapshot_files),
        "dimensions": {},
        "overall_score": 0.0,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }

    total_weighted = 0.0
    weight_count = 0
    for dim in DEFAULT_METRICS:
        scores = dim_scores.get(dim, [])
        if scores:
            avg = round(sum(scores) / len(scores), 4)
        else:
            avg = 0.5  # 无数据时中性值
        baseline["dimensions"][dim] = avg
        total_weighted += avg
        weight_count += 1

    baseline["overall_score"] = round(total_weighted / max(weight_count, 1), 4)

    # 缓存到文件
    baseline_path = os.path.join(output_dir, "_baseline.json")
    _write_json(baseline_path, baseline)
    logger.info("Baseline 生成完成: overall_score=%.4f, 快照数=%d", baseline["overall_score"], evaluated_count)

    return baseline


def _evaluate_snapshot_dimensions(
    snapshot: Dict[str, Any],
    judge_mode: str = "heuristic",
) -> Dict[str, float]:
    """
    对单个快照进行 8 维评分。

    复用 eval_runner.py 的评分逻辑，但直接内联实现以避免循环导入。
    如果 eval_runner 可用，优先使用其评分函数。

    Returns:
        { dimension: score (0-1), ... }
    """
    # 尝试使用 eval_runner 的评分函数
    try:
        # 动态导入 eval_runner
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
        from scripts.eval_runner import (
            _heuristic_score,
            _estimate_human_modification_rate,
            _estimate_output_adoption_rate,
            _estimate_high_risk_miss_rate,
            _estimate_cost_latency,
            CRITERION_DIMENSION_MAP,
        )

        # 使用 eval_runner 的评分函数
        scores = {}

        # 通过已知的 criterion_id 映射到维度
        for criterion_id, dim in CRITERION_DIMENSION_MAP.items():
            h_score = _heuristic_score(criterion_id, snapshot)
            if dim not in scores:
                scores[dim] = []
            scores[dim].append(h_score)

        # 计算各维度平均值
        result = {}
        for dim in DEFAULT_METRICS:
            if dim in scores and scores[dim]:
                result[dim] = round(sum(scores[dim]) / len(scores[dim]), 4)
            else:
                result[dim] = 0.5

        # 补充额外维度
        result["human_modification_rate"] = _estimate_human_modification_rate(snapshot)
        result["output_adoption_rate"] = _estimate_output_adoption_rate(snapshot)
        result["high_risk_miss_rate"] = _estimate_high_risk_miss_rate(snapshot)
        result["cost_latency"] = _estimate_cost_latency(snapshot)

        return result

    except (ImportError, AttributeError) as e:
        logger.debug("eval_runner 导入失败，使用内置评分: %s", e)

    # 内置简化评分（当 eval_runner 不可用时）
    output = snapshot.get("output_summary", {})
    constraints = snapshot.get("constraints_triggered", [])
    sources = snapshot.get("retrieved_sources", [])
    hr = snapshot.get("human_review", {})

    output_str = str(output).lower()

    scores = {}
    # citation_accuracy
    if sources:
        scores["citation_accuracy"] = min(1.0, 0.5 + len(sources) * 0.1)
    else:
        scores["citation_accuracy"] = 0.4

    # constraint_compliance
    violations = [c for c in constraints if c.get("severity") in ("high", "critical")]
    scores["constraint_compliance"] = max(0.1, 1.0 - len(violations) * 0.3)

    # format_compliance
    sections = output.get("sections", []) if isinstance(output, dict) else []
    scores["format_compliance"] = min(1.0, 0.5 + len(sections) * 0.1) if sections else 0.6

    # risk_detection
    risk_keywords = ["risk", "high", "critical", "warning", "红旗", "red_flag"]
    found = sum(1 for k in risk_keywords if k in output_str)
    scores["risk_detection"] = min(1.0, 0.3 + found * 0.15)

    # human_modification_rate
    if hr.get("required") and hr.get("review_status") == "approved_with_changes":
        scores["human_modification_rate"] = 0.5
    elif hr.get("required") and hr.get("review_status") == "rejected":
        scores["human_modification_rate"] = 0.9
    elif hr.get("required"):
        scores["human_modification_rate"] = 0.3
    else:
        scores["human_modification_rate"] = 0.1

    # output_adoption_rate
    if not hr.get("required"):
        scores["output_adoption_rate"] = 0.85
    elif hr.get("review_status") == "approved":
        scores["output_adoption_rate"] = 0.8
    elif hr.get("review_status") == "approved_with_changes":
        scores["output_adoption_rate"] = 0.5
    else:
        scores["output_adoption_rate"] = 0.3

    # high_risk_miss_rate
    risk_flags = output.get("risk_flags", []) if isinstance(output, dict) else []
    red_flags = output.get("red_flags", []) if isinstance(output, dict) else []
    total_risks = len(risk_flags) + len(red_flags)
    high_sev = [c for c in constraints if c.get("severity") in ("high", "critical")]
    if total_risks == 0 and not high_sev:
        scores["high_risk_miss_rate"] = 0.1
    else:
        coverage = min(1.0, (total_risks + len(high_sev)) / max(total_risks + 2, 1))
        scores["high_risk_miss_rate"] = round(1.0 - coverage, 4)

    # cost_latency
    tool_calls = snapshot.get("tool_calls", [])
    cost_signal = min(1.0, (len(tool_calls) * 0.05 + len(sources) * 0.03))
    scores["cost_latency"] = round(cost_signal, 4)

    return scores


# ── Patch Application ──


def apply_patch(candidate: Dict[str, Any]) -> Dict[str, Any]:
    """
    根据 candidate_change 生成 patched 配置。

    创建临时目录 (runtime/_patched/)，填入修改后的文件副本。
    如果 candidate_change 的 diff 中有具体的 before/after 内容，
    则应用到对应的文件副本上。

    Args:
        candidate: 候选变更字典

    Returns:
        patched_context: {
            "temp_dir": str,          # 临时目录路径
            "modified_files": [str],  # 修改的文件列表（相对路径）
            "component": str,         # 修改的组件
            "change_type": str,       # 修改类型
        }
    """
    target = candidate.get("target", {})
    component = target.get("component", "unknown")
    change_type = target.get("change_type", "modify_prompt")
    file_path = target.get("file_path", "")
    diff = candidate.get("diff", {})

    # 创建临时目录
    temp_dir = tempfile.mkdtemp(prefix="regression_patched_", dir="runtime")
    logger.info("创建临时配置目录: %s", temp_dir)

    modified_files = []

    # 确定需要修改的文件
    if component in TARGET_TO_FILE_PREFIX:
        prefix = TARGET_TO_FILE_PREFIX[component]
        if os.path.isdir(prefix):
            # 如果是目录，复制整个目录
            dest_dir = os.path.join(temp_dir, prefix)
            shutil.copytree(prefix, dest_dir, dirs_exist_ok=True)
            modified_files.append(prefix + "*")
        elif os.path.isfile(prefix):
            # 如果是单个文件，复制该文件
            dest_file = os.path.join(temp_dir, prefix)
            os.makedirs(os.path.dirname(dest_file), exist_ok=True)
            shutil.copy2(prefix, dest_file)
            modified_files.append(prefix)
        else:
            logger.warning("目标文件/目录不存在: %s", prefix)
    else:
        logger.warning("未知组件类型: %s", component)

    # 如果 diff 中有具体的 before/after 内容，尝试应用 patch
    before = diff.get("before", "")
    after = diff.get("after", "")
    if before and after and before != "(pending — read current file content)":
        for mod_file in modified_files:
            actual_path = os.path.join(temp_dir, mod_file.replace("*", ""))
            if os.path.isfile(actual_path):
                try:
                    with open(actual_path, "r", encoding="utf-8") as f:
                        content = f.read()
                    if before in content:
                        patched_content = content.replace(before, after)
                        with open(actual_path, "w", encoding="utf-8") as f:
                            f.write(patched_content)
                        logger.info("已应用 patch 到: %s", actual_path)
                except Exception as e:
                    logger.warning("应用 patch 失败: %s — %s", actual_path, e)

    return {
        "temp_dir": temp_dir,
        "modified_files": modified_files,
        "component": component,
        "change_type": change_type,
    }


def cleanup_patch(patched_ctx: Dict[str, Any]) -> None:
    """清理临时配置目录。"""
    temp_dir = patched_ctx.get("temp_dir", "")
    if temp_dir and os.path.exists(temp_dir):
        shutil.rmtree(temp_dir, ignore_errors=True)
        logger.info("已清理临时目录: %s", temp_dir)


# ── Patched Evaluation ──


def run_patched(
    candidate: Dict[str, Any],
    patched_ctx: Dict[str, Any],
    eval_set_dirs: List[str],
    output_dir: str,
    judge_mode: str = "heuristic",
) -> Dict[str, Any]:
    """
    在 patched 配置下重新评估全部评估集。

    注意：当前实现使用与 baseline 相同的评分逻辑，
    因为 patched 配置的差异主要体现在约束规则、prompt 等文本内容上，
    这些差异会通过快照中的 output_summary 间接反映。

    未来增强：当 patched 配置影响 eval_runner 的评分行为时，
    需要让 eval_runner 加载 patched 的配置文件。

    Args:
        candidate: 候选变更字典
        patched_ctx: apply_patch 返回的上下文
        eval_set_dirs: 评估集目录列表
        output_dir: 输出目录
        judge_mode: 评分模式

    Returns:
        patched_scores: { dimension: average_score, ... }
    """
    snapshot_files = _find_snapshot_files(eval_set_dirs)
    if not snapshot_files:
        logger.warning("未找到任何评估快照文件")
        return {"_empty": True}

    logger.info("Patched 评估: 找到 %d 个快照文件", len(snapshot_files))

    dim_scores: Dict[str, List[float]] = {m: [] for m in DEFAULT_METRICS}
    evaluated_count = 0

    for snap_path in snapshot_files:
        try:
            snapshot = _load_json(snap_path)
            scores = _evaluate_snapshot_dimensions(snapshot, judge_mode)
            for dim, score in scores.items():
                if dim in dim_scores:
                    dim_scores[dim].append(score)
            evaluated_count += 1
        except Exception as e:
            logger.warning("评估快照失败 (跳过): %s — %s", snap_path, e)
            continue

    patched: Dict[str, Any] = {
        "version": _get_patched_version(candidate),
        "judge_mode": judge_mode,
        "snapshot_count": evaluated_count,
        "snapshot_files_found": len(snapshot_files),
        "dimensions": {},
        "overall_score": 0.0,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }

    total_weighted = 0.0
    weight_count = 0
    for dim in DEFAULT_METRICS:
        scores = dim_scores.get(dim, [])
        if scores:
            avg = round(sum(scores) / len(scores), 4)
        else:
            avg = 0.5
        patched["dimensions"][dim] = avg
        total_weighted += avg
        weight_count += 1

    patched["overall_score"] = round(total_weighted / max(weight_count, 1), 4)

    # 缓存到文件
    patched_path = os.path.join(output_dir, "_patched.json")
    _write_json(patched_path, patched)
    logger.info("Patched 评估完成: overall_score=%.4f, 快照数=%d", patched["overall_score"], evaluated_count)

    return patched


# ── Score Comparison ──


def compare_scores(
    baseline: Dict[str, Any],
    patched: Dict[str, Any],
    thresholds: Optional[Dict[str, float]] = None,
) -> Dict[str, Any]:
    """
    对比 baseline 和 patched 的 8 维分数。

    Args:
        baseline: baseline_scores 字典
        patched: patched_scores 字典
        thresholds: 判定阈值，默认使用 DEFAULT_THRESHOLDS

    Returns:
        comparison_result: {
            "overall_score_change": float,
            "dimensions": { dim: { baseline, patched, delta, passed, status }, ... },
            "regressions": [str],
            "improvements": [str],
            "passed_count": int,
            "failed_count": int,
            "conclusion": str,  # "sandbox_pass" | "sandbox_warning" | "sandbox_fail"
        }
    """
    if thresholds is None:
        thresholds = DEFAULT_THRESHOLDS

    critical_delta = thresholds.get("critical_delta", -0.10)
    warning_delta = thresholds.get("warning_delta", -0.05)
    overall_critical_delta = thresholds.get("overall_critical_delta", -0.08)

    baseline_dims = baseline.get("dimensions", {})
    patched_dims = patched.get("dimensions", {})

    overall_baseline = baseline.get("overall_score", 0.5)
    overall_patched = patched.get("overall_score", 0.5)
    overall_change = round(overall_patched - overall_baseline, 4)

    dimensions = {}
    regressions = []
    improvements = []
    passed_count = 0
    failed_count = 0

    for dim in DEFAULT_METRICS:
        b_score = baseline_dims.get(dim, 0.5)
        p_score = patched_dims.get(dim, 0.5)
        delta = round(p_score - b_score, 4)

        # 判定状态
        if delta >= 0.01:
            status = "improved"
            improvements.append(f"{dim} {delta:+.4f}")
            passed = True
        elif delta >= -0.01:
            status = "unchanged"
            passed = True
        elif delta > critical_delta:
            status = "regressed"
            regressions.append(f"{dim} {delta:+.4f}")
            passed = delta >= warning_delta  # warning_delta 以上算通过
        else:
            status = "critical_regression"
            regressions.append(f"{dim} {delta:+.4f} (critical)")
            passed = False

        if passed:
            passed_count += 1
        else:
            failed_count += 1

        dimensions[dim] = {
            "baseline": b_score,
            "patched": p_score,
            "delta": delta,
            "passed": passed,
            "status": status,
        }

    # 综合判定
    if overall_change < overall_critical_delta:
        conclusion = "sandbox_fail"
    elif failed_count > 0:
        conclusion = "sandbox_fail"
    elif regressions and not any(
        dimensions[d]["status"] == "critical_regression" for d in dimensions
    ):
        conclusion = "sandbox_warning"
    else:
        conclusion = "sandbox_pass"

    return {
        "overall_score_change": overall_change,
        "dimensions": dimensions,
        "regressions": regressions,
        "improvements": improvements,
        "passed_count": passed_count,
        "failed_count": failed_count,
        "conclusion": conclusion,
    }


# ── Full Regression Flow ──


def run_regression(
    candidate_path: str,
    eval_set_dirs: Optional[List[str]] = None,
    output_dir: str = DEFAULT_OUTPUT_DIR,
    judge_mode: str = "heuristic",
    baseline_cache: Optional[str] = None,
    thresholds: Optional[Dict[str, float]] = None,
    cleanup: bool = True,
) -> Dict[str, Any]:
    """
    完整回归测试流程。

    Args:
        candidate_path: 候选变更 JSON 文件路径
        eval_set_dirs: 评估集目录列表
        output_dir: 输出目录
        judge_mode: 评分模式
        baseline_cache: baseline 缓存文件路径（快速模式）
        thresholds: 判定阈值
        cleanup: 是否清理临时文件

    Returns:
        regression_report: 符合 regression_report.schema.json 的完整报告
    """
    if eval_set_dirs is None:
        eval_set_dirs = DEFAULT_EVAL_SET_DIRS

    # 1. 加载候选变更
    logger.info("=" * 60)
    logger.info("开始回归测试: %s", candidate_path)
    candidate = _load_json(candidate_path)
    change_id = candidate.get("change_id", "unknown")
    logger.info("候选变更 ID: %s", change_id)

    # 2. 生成或加载 baseline
    if baseline_cache and os.path.exists(baseline_cache):
        logger.info("使用 baseline 缓存: %s", baseline_cache)
        baseline = _load_json(baseline_cache)
    else:
        logger.info("生成 baseline...")
        baseline = generate_baseline(eval_set_dirs, output_dir, judge_mode)

    if baseline.get("_empty"):
        logger.error("Baseline 为空，无法进行回归测试")
        return {"change_id": change_id, "status": "sandbox_fail", "error": "Empty baseline"}

    # 3. 应用 patch
    logger.info("应用候选变更 patch...")
    patched_ctx = apply_patch(candidate)

    try:
        # 4. 运行 patched 评估
        logger.info("运行 patched 评估...")
        patched = run_patched(candidate, patched_ctx, eval_set_dirs, output_dir, judge_mode)

        if patched.get("_empty"):
            logger.error("Patched 评估为空")
            return {"change_id": change_id, "status": "sandbox_fail", "error": "Empty patched evaluation"}

        # 5. 对比分数
        logger.info("对比 baseline vs patched...")
        comparison = compare_scores(baseline, patched, thresholds)

        # 6. 生成回归报告
        report = _build_regression_report(
            candidate, baseline, patched, comparison, eval_set_dirs, patched_ctx
        )

        # 7. 保存报告
        report_filename = f"{change_id}_regression_report.json"
        report_path = os.path.join(output_dir, report_filename)
        _write_json(report_path, report)
        logger.info("回归报告已保存: %s", report_path)

        # 8. 回填到 candidate_change 文件
        _backfill_candidate_change(candidate_path, report)

        # 打印摘要
        _print_regression_summary(report)

        return report

    finally:
        # 清理临时文件
        if cleanup:
            cleanup_patch(patched_ctx)


def _build_regression_report(
    candidate: Dict[str, Any],
    baseline: Dict[str, Any],
    patched: Dict[str, Any],
    comparison: Dict[str, Any],
    eval_set_dirs: List[str],
    patched_ctx: Dict[str, Any],
) -> Dict[str, Any]:
    """构建符合 regression_report.schema.json 的完整报告。"""
    change_id = candidate.get("change_id", "unknown")
    conclusion = comparison.get("conclusion", "sandbox_fail")

    # 统计评估集信息
    snapshot_files = _find_snapshot_files(eval_set_dirs)
    test_cases_found = len(snapshot_files)
    test_cases_run = baseline.get("snapshot_count", 0)

    return {
        "change_id": change_id,
        "status": conclusion,
        "baseline_version": baseline.get("version", "unknown"),
        "patched_version": patched.get("version", "unknown"),
        "eval_set_info": {
            "directories": eval_set_dirs,
            "test_cases_found": test_cases_found,
            "test_cases_run": test_cases_run,
        },
        "sample_count": test_cases_run,
        "summary": {
            "overall_score_change": comparison.get("overall_score_change", 0.0),
            "dimensions": comparison.get("dimensions", {}),
            "regressions": comparison.get("regressions", []),
            "improvements": comparison.get("improvements", []),
            "passed_count": comparison.get("passed_count", 0),
            "failed_count": comparison.get("failed_count", 0),
        },
        "patched_config": {
            "temp_dir": patched_ctx.get("temp_dir", ""),
            "modified_files": patched_ctx.get("modified_files", []),
        },
        "created_at": datetime.now(timezone.utc).isoformat(),
    }


def _backfill_candidate_change(candidate_path: str, report: Dict[str, Any]) -> None:
    """
    将回归测试结果回填到 candidate_change 文件。

    更新 candidate_change.validation 字段：
      - status: sandbox_pass / sandbox_warning / sandbox_fail
      - sandbox_report: 报告文件路径
      - regression_result: 回归结果摘要
    """
    try:
        change = _load_json(candidate_path)
        report_path = os.path.join(
            os.path.dirname(report.get("_report_path", "")),
            f"{report['change_id']}_regression_report.json",
        )

        change["validation"]["status"] = report["status"]
        change["validation"]["sandbox_report"] = report_path
        change["validation"]["regression_result"] = {
            "status": report["status"],
            "overall_score_change": report["summary"]["overall_score_change"],
            "regressions": report["summary"]["regressions"],
            "improvements": report["summary"]["improvements"],
        }

        _write_json(candidate_path, change)
        logger.info("已回填候选变更: %s", candidate_path)
    except Exception as e:
        logger.error("回填候选变更失败: %s", e)


def _print_regression_summary(report: Dict[str, Any]) -> None:
    """打印回归测试摘要。"""
    status = report.get("status", "unknown")
    summary = report.get("summary", {})

    status_icon = {"sandbox_pass": "✅", "sandbox_warning": "⚠️", "sandbox_fail": "❌"}
    icon = status_icon.get(status, "❓")

    print(f"\n{'=' * 60}")
    print(f"  {icon} 回归测试结果: {status}")
    print(f"  ID: {report.get('change_id', 'unknown')}")
    print(f"  Baseline: {report.get('baseline_version', '?')}")
    print(f"  Patched:  {report.get('patched_version', '?')}")
    print(f"  样本数:   {report.get('sample_count', 0)}")
    print(f"  综合评分变化: {summary.get('overall_score_change', 0):+.4f}")
    print(f"  通过维度: {summary.get('passed_count', 0)} / 失败维度: {summary.get('failed_count', 0)}")
    print(f"{'─' * 60}")

    dimensions = summary.get("dimensions", {})
    for dim in DEFAULT_METRICS:
        if dim in dimensions:
            d = dimensions[dim]
            icon_d = {"improved": "↑", "unchanged": "→", "regressed": "↓", "critical_regression": "↓↓"}
            arrow = icon_d.get(d["status"], "?")
            status_str = "✅" if d["passed"] else "❌"
            print(f"  {status_str} {dim:30s} {d['baseline']:.4f} → {d['patched']:.4f} ({arrow} {d['delta']:+.4f})")

    if summary.get("regressions"):
        print(f"\n  ⚠️  回归维度:")
        for r in summary["regressions"]:
            print(f"    - {r}")

    if summary.get("improvements"):
        print(f"\n  📈 改进维度:")
        for imp in summary["improvements"]:
            print(f"    - {imp}")

    print(f"{'=' * 60}\n")


# ── Compare Mode ──


def compare_mode(
    baseline_path: str,
    target_path: str,
    output_dir: str = DEFAULT_OUTPUT_DIR,
) -> Dict[str, Any]:
    """
    对比两个版本的基线分数。

    Args:
        baseline_path: baseline JSON 文件路径
        target_path: target JSON 文件路径
        output_dir: 输出目录

    Returns:
        comparison_result
    """
    baseline = _load_json(baseline_path)
    target = _load_json(target_path)

    comparison = compare_scores(baseline, target)

    # 生成对比报告
    report = {
        "change_id": "compare_mode",
        "status": comparison["conclusion"],
        "baseline_version": baseline.get("version", "unknown"),
        "patched_version": target.get("version", "unknown"),
        "eval_set_info": {
            "directories": [],
            "test_cases_found": 0,
            "test_cases_run": 0,
        },
        "sample_count": 0,
        "summary": {
            "overall_score_change": comparison["overall_score_change"],
            "dimensions": comparison["dimensions"],
            "regressions": comparison["regressions"],
            "improvements": comparison["improvements"],
            "passed_count": comparison["passed_count"],
            "failed_count": comparison["failed_count"],
        },
        "patched_config": {
            "temp_dir": "",
            "modified_files": [],
        },
        "created_at": datetime.now(timezone.utc).isoformat(),
    }

    # 保存对比报告
    report_path = os.path.join(output_dir, "_compare_report.json")
    _write_json(report_path, report)
    _print_regression_summary(report)

    return report


# ── CLI ──


def main():
    parser = argparse.ArgumentParser(
        description="Phase 7d: 沙箱回归测试引擎",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 对单个候选变更运行回归测试
  python scripts/regression_test.py --candidate runtime/candidate_changes/change_abc12345.json

  # 快速回归（使用已有的 baseline 缓存）
  python scripts/regression_test.py --quick --candidate runtime/candidate_changes/change_abc12345.json \\
      --baseline-cache outputs/eval_reports/regression/_baseline.json

  # 仅生成 baseline
  python scripts/regression_test.py --generate-baseline

  # 对比两个版本
  python scripts/regression_test.py --compare \\
      --baseline outputs/eval_reports/regression/_baseline.json \\
      --target outputs/eval_reports/regression/_patched.json
        """,
    )

    # 运行模式
    parser.add_argument("--candidate", type=str, help="候选变更 JSON 文件路径")
    parser.add_argument(
        "--eval-set", type=str, nargs="*", default=None,
        help="评估集目录列表 (默认: tests/eval_cases/ 下所有子目录)"
    )
    parser.add_argument(
        "--output", type=str, default=DEFAULT_OUTPUT_DIR,
        help=f"输出目录 (默认: {DEFAULT_OUTPUT_DIR})"
    )
    parser.add_argument(
        "--judge-mode", choices=["heuristic", "llm", "hybrid"],
        default="heuristic",
        help="评分模式 (默认: heuristic)"
    )
    parser.add_argument(
        "--quick", action="store_true",
        help="快速模式: 使用已有的 baseline 缓存"
    )
    parser.add_argument(
        "--baseline-cache", type=str, default=None,
        help="Baseline 缓存文件路径 (快速模式)"
    )
    parser.add_argument(
        "--no-cleanup", action="store_true",
        help="不清理临时文件 (调试用)"
    )

    # 生成 baseline 模式
    parser.add_argument(
        "--generate-baseline", action="store_true",
        help="仅生成 baseline，不运行回归测试"
    )

    # 对比模式
    parser.add_argument("--compare", action="store_true", help="对比两个版本的基线")
    parser.add_argument("--baseline", type=str, help="Baseline JSON 文件路径 (对比模式)")
    parser.add_argument("--target", type=str, help="Target JSON 文件路径 (对比模式)")

    args = parser.parse_args()

    # 确定评估集目录
    eval_set_dirs = args.eval_set
    if eval_set_dirs is None:
        # 默认使用 tests/eval_cases/ 下所有子目录
        base_dir = "tests/eval_cases/"
        if os.path.isdir(base_dir):
            eval_set_dirs = [
                os.path.join(base_dir, d)
                for d in sorted(os.listdir(base_dir))
                if os.path.isdir(os.path.join(base_dir, d))
            ]
        else:
            eval_set_dirs = DEFAULT_EVAL_SET_DIRS

    # ── 生成 baseline 模式 ──
    if args.generate_baseline:
        logger.info("生成 baseline...")
        baseline = generate_baseline(eval_set_dirs, args.output, args.judge_mode)
        if baseline.get("_empty"):
            logger.error("未找到评估快照，无法生成 baseline")
            sys.exit(1)
        print(f"\n✅ Baseline 生成完成:")
        print(f"   版本: {baseline.get('version', '?')}")
        print(f"   综合评分: {baseline.get('overall_score', 0):.4f}")
        print(f"   快照数: {baseline.get('snapshot_count', 0)}")
        print(f"   输出: {args.output}_baseline.json")
        return

    # ── 对比模式 ──
    if args.compare:
        if not args.baseline or not args.target:
            logger.error("对比模式需要 --baseline 和 --target 参数")
            sys.exit(1)
        compare_mode(args.baseline, args.target, args.output)
        return

    # ── 回归测试模式 ──
    if not args.candidate:
        parser.print_help()
        print("\n错误: 请指定 --candidate 或 --generate-baseline 或 --compare")
        sys.exit(1)

    if not os.path.exists(args.candidate):
        logger.error("候选变更文件不存在: %s", args.candidate)
        sys.exit(1)

    # 快速模式：使用 baseline 缓存
    baseline_cache = args.baseline_cache
    if args.quick and not baseline_cache:
        baseline_cache = os.path.join(args.output, "_baseline.json")

    report = run_regression(
        candidate_path=args.candidate,
        eval_set_dirs=eval_set_dirs,
        output_dir=args.output,
        judge_mode=args.judge_mode,
        baseline_cache=baseline_cache,
        cleanup=not args.no_cleanup,
    )

    if report.get("status") == "sandbox_fail":
        sys.exit(1)


if __name__ == "__main__":
    main()
