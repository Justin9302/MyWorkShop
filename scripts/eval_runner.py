#!/usr/bin/env python3
"""
eval_runner.py — VS Code Task 模式评估运行器

替代 Codex Sidecar Service 的 HTTP POST /evaluation/run。
从命令行读取 run_snapshot JSON 和 rubric YAML，输出 eval_report JSON。

用法:
  python scripts/eval_runner.py \
    --snapshot runtime/snapshots/run_001.json \
    --rubric evaluators/rubrics/business_model_validation.yaml \
    --output outputs/eval_reports/run_001_eval.json

或批量模式:
  python scripts/eval_runner.py \
    --batch runtime/snapshots/ \
    --rubric evaluators/rubrics/business_model_validation.yaml \
    --output-dir outputs/eval_reports/
"""

import argparse
import json
import os
import sys
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

try:
    import yaml
except ImportError:
    print("⚠️  PyYAML not installed. Run: pip install pyyaml", file=sys.stderr)
    sys.exit(1)


# ── Schema helpers ──────────────────────────────────────────────

def load_yaml(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_json(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(data: Dict[str, Any], path: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


# ── Rubric engine ───────────────────────────────────────────────

CRITERION_CHECKS = {
    "fact_assumption_separation": "检查输出是否明确区分事实(facts)、假设(assumptions)、推断(inferences)和未知(unknowns)。",
    "evidence_quality": "检查关键声明是否附带证据等级、来源元数据或明确标注未经验证。",
    "unit_economics_consistency": "检查收入、成本、CAC、留存、回本周期和敏感性假设是否内部自洽。",
    "validation_plan_quality": "检查实验是否包含成功指标、失败阈值和下一步决策门禁。",
    "human_review_flagging": "检查投资、融资、预测或对外发布类输出是否标记为需要人审。",
    "citation_accuracy": "检查引用是否准确指向已检索的来源。",
    "constraint_compliance": "检查是否遵守行业、地区和组织约束规则。",
    "risk_detection": "检查是否识别了高风险事项。",
    "format_compliance": "检查输出格式是否符合规定的模板结构。",
    "completeness": "检查是否完成了所有必需步骤。",
}


def evaluate_criterion(
    criterion: Dict[str, Any], snapshot: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Evaluate a single rubric criterion against a run snapshot.
    Returns { criterion_id, score, weight, reasoning }.
    """
    cid = criterion["id"]
    weight = criterion.get("weight", 0.1)
    desc = criterion.get("description", "")

    # Heuristic-based scoring (production would use LLM-as-judge)
    score = _heuristic_score(cid, snapshot)

    return {
        "criterion_id": cid,
        "weight": weight,
        "score": score,
        "description": desc,
    }


def _heuristic_score(criterion_id: str, snapshot: Dict[str, Any]) -> float:
    """
    Simple heuristic scorer. In production, replace with LLM-as-judge.
    Checks for evidence of compliance in the snapshot structure.
    """
    output = snapshot.get("output_summary", {})
    constraints = snapshot.get("constraints_triggered", [])
    sources = snapshot.get("retrieved_sources", [])

    base = 0.5  # neutral baseline

    if criterion_id == "fact_assumption_separation":
        keywords = ["fact", "assumption", "inference", "unknown"]
        found = sum(1 for k in keywords if k in str(output).lower())
        base = min(1.0, 0.4 + found * 0.15)

    elif criterion_id == "evidence_quality":
        if sources:
            base = min(1.0, 0.5 + len(sources) * 0.1)
        else:
            base = 0.3

    elif criterion_id == "unit_economics_consistency":
        metrics = ["revenue", "cost", "cac", "retention", "payback"]
        found = sum(1 for m in metrics if m in str(output).lower())
        base = min(1.0, 0.3 + found * 0.14)

    elif criterion_id == "validation_plan_quality":
        keywords = ["experiment", "metric", "threshold", "decision"]
        found = sum(1 for k in keywords if k in str(output).lower())
        base = min(1.0, 0.3 + found * 0.18)

    elif criterion_id == "human_review_flagging":
        has_review = snapshot.get("human_review", {}).get("required", False)
        review_keywords = ["review", "approval", "human"]
        found = sum(1 for k in review_keywords if k in str(output).lower())
        base = 0.8 if has_review else min(1.0, 0.4 + found * 0.2)

    elif criterion_id == "citation_accuracy":
        if sources:
            base = min(1.0, 0.5 + len(sources) * 0.12)
        else:
            base = 0.4

    elif criterion_id == "constraint_compliance":
        violations = [c for c in constraints if c.get("severity") in ("high", "critical")]
        base = max(0.1, 1.0 - len(violations) * 0.3)

    elif criterion_id == "risk_detection":
        risk_keywords = ["risk", "high", "critical", "warning"]
        found = sum(1 for k in risk_keywords if k in str(output).lower())
        base = min(1.0, 0.3 + found * 0.15)

    elif criterion_id == "format_compliance":
        required = snapshot.get("output_summary", {}).get("sections", [])
        if required:
            base = min(1.0, 0.5 + len(required) * 0.1)
        else:
            base = 0.6

    elif criterion_id == "completeness":
        steps = snapshot.get("workflow_state", {}).get("completed_steps", [])
        total = snapshot.get("workflow_state", {}).get("total_steps", 1)
        base = len(steps) / max(total, 1)

    return round(base, 2)


# ── Report generation ───────────────────────────────────────────

def generate_report(
    snapshot: Dict[str, Any],
    rubric: Dict[str, Any],
    scores: List[Dict[str, Any]],
    evaluator_version: str,
) -> Dict[str, Any]:
    """Build an eval_report matching schemas/eval_report.schema.json."""

    weighted = sum(s["score"] * s["weight"] for s in scores)
    total_weight = sum(s["weight"] for s in scores)
    overall = round(weighted / max(total_weight, 0.001), 2)

    findings = []
    for s in scores:
        if s["score"] < 0.6:
            findings.append({
                "type": s["criterion_id"],
                "severity": "high" if s["score"] < 0.3 else "medium",
                "message": f"{s['criterion_id']}: score={s['score']} — {s['description']}",
            })

    risk_level = "low"
    if overall < 0.4:
        risk_level = "critical"
    elif overall < 0.6:
        risk_level = "high"
    elif overall < 0.8:
        risk_level = "medium"

    suggestions = []
    for s in scores:
        if s["score"] < 0.5:
            suggestions.append({
                "target": s["criterion_id"],
                "recommendation": f"Improve {s['criterion_id']}: {CRITERION_CHECKS.get(s['criterion_id'], 'review this area.')}",
            })

    return {
        "run_id": snapshot.get("run_id", str(uuid.uuid4())),
        "evaluator_version": evaluator_version,
        "score": overall,
        "risk_level": risk_level,
        "passed": overall >= 0.6,
        "metrics": {s["criterion_id"]: s["score"] for s in scores},
        "findings": findings,
        "suggestions": suggestions,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }


# ── Main ────────────────────────────────────────────────────────

def run_single(
    snapshot_path: str, rubric_path: str, output_path: str
) -> Dict[str, Any]:
    snapshot = load_json(snapshot_path)
    rubric = load_yaml(rubric_path)

    criteria = rubric.get("criteria", [])
    rubric_version = rubric.get("rubric", {}).get("version", "0.1.0")

    scores = [evaluate_criterion(c, snapshot) for c in criteria]
    report = generate_report(snapshot, rubric, scores, rubric_version)
    save_json(report, output_path)

    return report


def run_batch(
    snapshot_dir: str, rubric_path: str, output_dir: str
) -> List[Dict[str, Any]]:
    reports = []
    for fname in sorted(os.listdir(snapshot_dir)):
        if fname.endswith(".json"):
            snap_path = os.path.join(snapshot_dir, fname)
            out_path = os.path.join(
                output_dir, fname.replace(".json", "_eval.json")
            )
            report = run_single(snap_path, rubric_path, out_path)
            reports.append(report)
    return reports


def main():
    parser = argparse.ArgumentParser(
        description="VS Code Task 模式评估运行器"
    )
    parser.add_argument(
        "--snapshot", help="单个 run_snapshot JSON 文件路径"
    )
    parser.add_argument(
        "--batch", help="run_snapshot 目录路径 (批量模式)"
    )
    parser.add_argument(
        "--rubric", required=True, help="rubric YAML 文件路径"
    )
    parser.add_argument(
        "--output", help="单个报告输出路径"
    )
    parser.add_argument(
        "--output-dir", default="outputs/eval_reports",
        help="批量报告输出目录"
    )
    args = parser.parse_args()

    if args.snapshot:
        output = args.output or args.snapshot.replace(".json", "_eval.json")
        report = run_single(args.snapshot, args.rubric, output)
        print(f"✅ Eval complete: {output}")
        print(f"   Score: {report['score']} | Risk: {report['risk_level']} | Passed: {report['passed']}")
        if report["findings"]:
            print(f"   Findings: {len(report['findings'])}")
        if report["suggestions"]:
            print(f"   Suggestions: {len(report['suggestions'])}")

    elif args.batch:
        reports = run_batch(args.batch, args.rubric, args.output_dir)
        passed = sum(1 for r in reports if r["passed"])
        print(f"✅ Batch eval complete: {len(reports)} snapshots → {args.output_dir}")
        print(f"   Passed: {passed}/{len(reports)}")

    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
