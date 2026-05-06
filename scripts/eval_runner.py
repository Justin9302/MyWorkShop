#!/usr/bin/env python3
"""
eval_runner.py — Phase 5 评估旁路运行器 (VS Code Task 模式)

模拟 Evaluation Sidecar Service 的 HTTP API：
  POST /evaluation/run       → --snapshot + --rubric
  POST /evaluation/batch     → --batch + --rubric
  GET  /evaluation/reports/  → 读取 outputs/eval_reports/

8维评估指标体系 (per eval_report.schema.json):
  1. citation_accuracy       — 引用准确率
  2. constraint_compliance   — 约束合规率
  3. format_compliance       — 格式合规率
  4. risk_detection          — 风险识别率
  5. human_modification_rate — 人工修改率
  6. output_adoption_rate    — 输出采纳率
  7. high_risk_miss_rate     — 高风险漏检率
  8. cost_latency            — 成本与延迟

用法:
  # 单次评估
  python scripts/eval_runner.py \
    --snapshot tests/eval_cases/synthetic/run_snapshot_sample_001.json \
    --rubric evaluators/rubrics/business_model_validation.yaml \
    --output outputs/eval_reports/sample_001_eval.json

  # 自动匹配 rubric（根据 snapshot 中的 workflow_id）
  python scripts/eval_runner.py \
    --snapshot tests/eval_cases/synthetic/run_snapshot_sample_002.json \
    --auto-rubric

  # 批量评估
  python scripts/eval_runner.py \
    --batch tests/eval_cases/synthetic/ \
    --auto-rubric \
    --output-dir outputs/eval_reports/

  # 批量评估 + 生成汇总报告
  python scripts/eval_runner.py \
    --batch tests/eval_cases/synthetic/ \
    --auto-rubric \
    --output-dir outputs/eval_reports/ \
    --summary
"""

import argparse
import json
import logging
import os
import sys
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

# Phase 7a: LLM-as-Judge
try:
    from llm_judge import (
        judge_criterion,
        load_judge_config,
        JudgeResult,
        LLMJudgeError,
    )
    LLM_JUDGE_AVAILABLE = True
except ImportError:
    LLM_JUDGE_AVAILABLE = False

try:
    import yaml
except ImportError:
    print("⚠️  PyYAML not installed. Run: pip install pyyaml", file=sys.stderr)
    sys.exit(1)


# ═══════════════════════════════════════════════════════════════
# Constants
# ═══════════════════════════════════════════════════════════════

DEFAULT_THRESHOLD = 0.6
DEFAULT_RUBRICS_DIR = "evaluators/rubrics"

# 8 dimensions → default weight when rubric doesn't specify
DEFAULT_METRIC_WEIGHTS = {
    "citation_accuracy": 0.15,
    "constraint_compliance": 0.20,
    "format_compliance": 0.10,
    "risk_detection": 0.20,
    "human_modification_rate": 0.10,
    "output_adoption_rate": 0.10,
    "high_risk_miss_rate": 0.10,
    "cost_latency": 0.05,
}

# Rubric criterion → 8-dimension mapping
CRITERION_DIMENSION_MAP = {
    # Business model validation
    "fact_assumption_separation": "citation_accuracy",
    "evidence_quality": "citation_accuracy",
    "unit_economics_consistency": "format_compliance",
    "validation_plan_quality": "format_compliance",
    "human_review_flagging": "risk_detection",
    # Contract review
    "risk_clause_coverage": "risk_detection",
    "jurisdiction_awareness": "constraint_compliance",
    "legal_citation_quality": "citation_accuracy",
    "missing_clause_detection": "high_risk_miss_rate",
    "no_legal_advice_disclaimer": "constraint_compliance",
    # Due diligence
    "dd_scope_completeness": "format_compliance",
    "red_flag_detection": "risk_detection",
    "source_traceability": "citation_accuracy",
    "risk_classification_quality": "risk_detection",
    "decision_readiness": "format_compliance",
    "no_investment_advice": "constraint_compliance",
    # SOP generation
    "sop_structure_completeness": "format_compliance",
    "step_actionability": "format_compliance",
    "role_clarity": "format_compliance",
    "safety_compliance": "constraint_compliance",
    "exception_handling": "risk_detection",
    "measurable_success_criteria": "format_compliance",
    # Generic
    "citation_accuracy": "citation_accuracy",
    "constraint_compliance": "constraint_compliance",
    "risk_detection": "risk_detection",
    "format_compliance": "format_compliance",
    "completeness": "format_compliance",
}

CRITERION_DESCRIPTIONS = {
    "fact_assumption_separation": "检查输出是否明确区分事实(facts)、假设(assumptions)、推断(inferences)和未知(unknowns)。",
    "evidence_quality": "检查关键声明是否附带证据等级、来源元数据或明确标注未经验证。",
    "unit_economics_consistency": "检查收入、成本、CAC、留存、回本周期和敏感性假设是否内部自洽。",
    "validation_plan_quality": "检查实验是否包含成功指标、失败阈值和下一步决策门禁。",
    "human_review_flagging": "检查投资、融资、预测或对外发布类输出是否标记为需要人审。",
    "risk_clause_coverage": "检查关键风险条款是否全部覆盖。",
    "jurisdiction_awareness": "检查是否识别并标注适用法域。",
    "legal_citation_quality": "检查法律引用是否准确、可追溯。",
    "missing_clause_detection": "检查是否识别缺失的关键条款。",
    "no_legal_advice_disclaimer": "检查输出是否包含法律免责声明。",
    "dd_scope_completeness": "检查DD清单是否覆盖核心维度。",
    "red_flag_detection": "检查是否识别关键红旗信号。",
    "source_traceability": "检查每项发现是否可追溯到具体来源。",
    "risk_classification_quality": "检查风险是否按严重程度正确分级。",
    "decision_readiness": "检查输出是否清晰标记决策状态。",
    "no_investment_advice": "检查是否避免给出明确投资建议。",
    "sop_structure_completeness": "检查SOP是否包含标准章节。",
    "step_actionability": "检查每个步骤是否具体、可操作。",
    "role_clarity": "检查每个步骤是否明确责任人。",
    "safety_compliance": "检查是否识别安全合规关键控制点。",
    "exception_handling": "检查是否定义异常场景和升级路径。",
    "measurable_success_criteria": "检查是否包含可衡量的成功标准。",
    "citation_accuracy": "检查引用是否准确指向已检索的来源。",
    "constraint_compliance": "检查是否遵守行业、地区和组织约束规则。",
    "risk_detection": "检查是否识别了高风险事项。",
    "format_compliance": "检查输出格式是否符合规定的模板结构。",
    "completeness": "检查是否完成了所有必需步骤。",
}


# ═══════════════════════════════════════════════════════════════
# File I/O helpers
# ═══════════════════════════════════════════════════════════════

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


# ═══════════════════════════════════════════════════════════════
# Rubric auto-matching
# ═══════════════════════════════════════════════════════════════

WORKFLOW_TO_RUBRIC = {
    "business_model_validation": "business_model_validation",
    "business_model_design": "business_model_validation",
    "contract_review": "contract_review",
    "policy_qa": "contract_review",
    "due_diligence": "due_diligence",
    "investment_research": "due_diligence",
    "risk_summary": "due_diligence",
    "sop_generation": "sop_generation",
    "meeting_summary": "sop_generation",
    "project_retrospective": "sop_generation",
    "go_to_market_review": "business_model_validation",
    "unit_economics_check": "business_model_validation",
}


def find_rubric_path(workflow_id: str, rubrics_dir: str = DEFAULT_RUBRICS_DIR) -> Optional[str]:
    """Auto-match a rubric YAML for the given workflow_id."""
    rubric_id = WORKFLOW_TO_RUBRIC.get(workflow_id)
    if not rubric_id:
        return None
    path = os.path.join(rubrics_dir, f"{rubric_id}.yaml")
    return path if os.path.exists(path) else None


# ═══════════════════════════════════════════════════════════════
# 8-Dimension Heuristic Scorer
# ═══════════════════════════════════════════════════════════════

def _compute_dimension_scores(
    criterion_scores: List[Dict[str, Any]]
) -> Dict[str, float]:
    """
    Aggregate individual criterion scores into 8-dimension scores.
    Each criterion maps to one dimension; average if multiple criteria
    map to the same dimension.
    """
    dim_scores: Dict[str, List[float]] = {d: [] for d in DEFAULT_METRIC_WEIGHTS}

    for cs in criterion_scores:
        dim = CRITERION_DIMENSION_MAP.get(cs["criterion_id"], "format_compliance")
        dim_scores[dim].append(cs["score"])

    result = {}
    for dim, scores in dim_scores.items():
        if scores:
            result[dim] = round(sum(scores) / len(scores), 2)
        else:
            result[dim] = 0.5  # neutral when no data

    return result


def _heuristic_score(criterion_id: str, snapshot: Dict[str, Any]) -> float:
    """
    Simple heuristic scorer. In production, replace with LLM-as-judge.
    """
    output = snapshot.get("output_summary", {})
    constraints = snapshot.get("constraints_triggered", [])
    sources = snapshot.get("retrieved_sources", [])
    state = snapshot.get("workflow_state", {})
    hr = snapshot.get("human_review", {})

    base = 0.5

    # ── Business Model criteria ──
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
        has_review = hr.get("required", False)
        review_keywords = ["review", "approval", "human"]
        found = sum(1 for k in review_keywords if k in str(output).lower())
        base = 0.8 if has_review else min(1.0, 0.4 + found * 0.2)

    # ── Contract Review criteria ──
    elif criterion_id == "risk_clause_coverage":
        clauses = ["indemnif", "liability", "termination", "confidential", "dispute"]
        found = sum(1 for c in clauses if c in str(output).lower())
        base = min(1.0, 0.3 + found * 0.14)

    elif criterion_id == "jurisdiction_awareness":
        j_keywords = ["jurisdiction", "governing law", "applicable law", "cn", "china"]
        found = sum(1 for k in j_keywords if k in str(output).lower())
        base = min(1.0, 0.3 + found * 0.18)

    elif criterion_id == "legal_citation_quality":
        law_keywords = ["民法典", "contract law", "civil code", "statute", "法规"]
        found = sum(1 for k in law_keywords if k in str(output).lower())
        base = min(1.0, 0.3 + found * 0.15) if sources else 0.35

    elif criterion_id == "missing_clause_detection":
        gap_keywords = ["missing", "缺失", "未覆盖", "absence", "建议补充"]
        found = sum(1 for k in gap_keywords if k in str(output).lower())
        base = min(1.0, 0.3 + found * 0.2)

    elif criterion_id == "no_legal_advice_disclaimer":
        disc = ["disclaimer", "免责", "不构成", "not constitute", "legal advice"]
        found = sum(1 for d in disc if d in str(output).lower())
        base = 0.7 if found >= 2 else (0.4 if found == 1 else 0.2)

    # ── Due Diligence criteria ──
    elif criterion_id == "dd_scope_completeness":
        dims = ["financial", "legal", "commercial", "operational", "technology", "people"]
        covered = output.get("dimensions_covered", [])
        base = min(1.0, 0.3 + len(covered) * 0.12)

    elif criterion_id == "red_flag_detection":
        flags = output.get("red_flags", [])
        base = min(1.0, 0.4 + len(flags) * 0.15)

    elif criterion_id == "source_traceability":
        if sources:
            cited_in_output = sum(1 for s in sources if s.get("source_id", "") in str(output))
            base = min(1.0, 0.4 + (cited_in_output / max(len(sources), 1)) * 0.6)
        else:
            base = 0.3

    elif criterion_id == "risk_classification_quality":
        rc = output.get("risk_classification", {})
        levels = sum(1 for l in ["critical", "high", "medium", "low"] if l in rc)
        base = min(1.0, 0.3 + levels * 0.18)

    elif criterion_id == "decision_readiness":
        dr_keywords = ["deal_breaker", "conditional", "next_step", "下一步"]
        found = sum(1 for k in dr_keywords if k in str(output).lower())
        base = min(1.0, 0.3 + found * 0.18)

    elif criterion_id == "no_investment_advice":
        avoid = ["recommend", "建议投资", "建议买入", "should invest"]
        has_avoid = any(a in str(output).lower() for a in avoid)
        base = 0.2 if has_avoid else 0.8

    # ── SOP criteria ──
    elif criterion_id == "sop_structure_completeness":
        sections = ["purpose", "scope", "definition", "responsibilit", "procedure", "exception", "record"]
        found = sum(1 for s in sections if s in str(output).lower())
        base = min(1.0, 0.2 + found * 0.11)

    elif criterion_id == "step_actionability":
        action_words = ["必须", "检查", "确认", "填写", "提交", "审批"]
        found = sum(1 for w in action_words if w in str(output).lower())
        base = min(1.0, 0.3 + found * 0.1)

    elif criterion_id == "role_clarity":
        role_words = ["负责", "责任人", "RACI", "responsible", "owner"]
        found = sum(1 for w in role_words if w in str(output).lower())
        base = min(1.0, 0.3 + found * 0.15)

    elif criterion_id == "safety_compliance":
        safety_words = ["安全", "safety", "compliance", "强制", "mandatory", "不可跳过"]
        found = sum(1 for w in safety_words if w in str(output).lower())
        base = min(1.0, 0.3 + found * 0.15)

    elif criterion_id == "exception_handling":
        exc_words = ["异常", "exception", "升级", "escalation", "exception"]
        found = sum(1 for w in exc_words if w in str(output).lower())
        base = min(1.0, 0.2 + found * 0.2)

    elif criterion_id == "measurable_success_criteria":
        meas_words = ["KPI", "metric", "指标", "验收", "acceptance", "success criteria"]
        found = sum(1 for w in meas_words if w in str(output).lower())
        base = min(1.0, 0.2 + found * 0.2)

    # ── Generic criteria ──
    elif criterion_id == "citation_accuracy":
        if sources:
            base = min(1.0, 0.5 + len(sources) * 0.12)
        else:
            base = 0.4

    elif criterion_id == "constraint_compliance":
        violations = [c for c in constraints if c.get("severity") in ("high", "critical")]
        base = max(0.1, 1.0 - len(violations) * 0.3)

    elif criterion_id == "risk_detection":
        risk_keywords = ["risk", "high", "critical", "warning", "红旗", "red_flag"]
        found = sum(1 for k in risk_keywords if k in str(output).lower())
        base = min(1.0, 0.3 + found * 0.15)

    elif criterion_id == "format_compliance":
        sections = output.get("sections", [])
        if sections:
            base = min(1.0, 0.5 + len(sections) * 0.1)
        else:
            base = 0.6

    elif criterion_id == "completeness":
        steps = state.get("completed_steps", [])
        total = state.get("total_steps", 1)
        base = len(steps) / max(total, 1)

    return round(base, 2)


# ═══════════════════════════════════════════════════════════════
# Additional dimension heuristics (not from rubric criteria)
# ═══════════════════════════════════════════════════════════════

def _estimate_human_modification_rate(snapshot: Dict[str, Any]) -> float:
    """Estimate how much human modification was needed (0 = none, 1 = complete rewrite)."""
    hr = snapshot.get("human_review", {})
    if hr.get("required") and hr.get("review_status") == "approved_with_changes":
        return 0.5
    elif hr.get("required") and hr.get("review_status") == "rejected":
        return 0.9
    elif hr.get("required"):
        return 0.3
    return 0.1


def _estimate_output_adoption_rate(snapshot: Dict[str, Any]) -> float:
    """Estimate whether output was directly adopted."""
    hr = snapshot.get("human_review", {})
    output = snapshot.get("output_summary", {})
    # Higher adoption if human review not required or approved cleanly
    if not hr.get("required"):
        return 0.85
    if hr.get("review_status") == "approved":
        return 0.8
    if hr.get("review_status") == "approved_with_changes":
        return 0.5
    return 0.3


def _estimate_high_risk_miss_rate(snapshot: Dict[str, Any]) -> float:
    """Estimate rate of missed high-risk items (lower is better)."""
    output = snapshot.get("output_summary", {})
    constraints = snapshot.get("constraints_triggered", [])
    risk_flags = output.get("risk_flags", [])
    red_flags = output.get("red_flags", [])

    total_risks = len(risk_flags) + len(red_flags)
    high_severity_constraints = [c for c in constraints if c.get("severity") in ("high", "critical")]

    if total_risks == 0 and not high_severity_constraints:
        return 0.1  # low miss rate when few risks

    # More flagged risks + constraints triggered → lower miss rate
    coverage = min(1.0, (total_risks + len(high_severity_constraints)) / max(total_risks + 2, 1))
    return round(1.0 - coverage, 2)


def _estimate_cost_latency(snapshot: Dict[str, Any]) -> float:
    """Estimate cost/latency score (0 = optimal, higher = worse)."""
    tool_calls = snapshot.get("tool_calls", [])
    sources = snapshot.get("retrieved_sources", [])

    # Heuristic: more tool calls + sources → higher cost
    cost_signal = min(1.0, (len(tool_calls) * 0.05 + len(sources) * 0.03))
    return round(cost_signal, 2)


# ═══════════════════════════════════════════════════════════════
# Core evaluation engine
# ═══════════════════════════════════════════════════════════════

def _should_use_llm(
    criterion_id: str,
    judge_mode: str,
    judge_config: Optional[Dict[str, Any]] = None,
) -> bool:
    """Determine whether a criterion should be evaluated by LLM.

    Decision matrix:
      - judge_mode='heuristic' → False (always heuristic)
      - judge_mode='llm'       → True  (always LLM)
      - judge_mode='hybrid'    → True if criterion_id in criteria_requiring_llm
                                 or heuristic score < low_score_threshold
    """
    if judge_mode == "heuristic" or not LLM_JUDGE_AVAILABLE:
        return False
    if judge_mode == "llm":
        return True
    if judge_mode == "hybrid":
        if judge_config:
            llm_criteria = judge_config.get("judge_strategy", {}).get("criteria_requiring_llm", [])
            if criterion_id in llm_criteria:
                return True
            # For hybrid mode with threshold: we don't know heuristic score yet,
            # so the caller (evaluate_criterion) will handle the threshold check
            # after getting the heuristic score. We return True here to attempt LLM.
            return True
        return True
    return False


def evaluate_criterion(
    criterion: Dict[str, Any],
    snapshot: Dict[str, Any],
    judge_mode: str = "heuristic",
    judge_config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Evaluate a single rubric criterion against a run snapshot.

    Args:
        criterion:    Rubric criterion dict with keys: id, weight, description
        snapshot:     Run snapshot dict
        judge_mode:   'heuristic' | 'llm' | 'hybrid'
        judge_config: Judge configuration dict (for LLM mode)

    Returns:
        Dict with keys: criterion_id, weight, score, description,
                        plus optional: llm_reasoning, confidence, judged_by
    """
    cid = criterion["id"]
    weight = criterion.get("weight", 0.1)
    desc = criterion.get("description", "")

    # Determine whether to use LLM
    use_llm = _should_use_llm(cid, judge_mode, judge_config)
    score = None
    llm_reasoning = None
    confidence = None
    judged_by = "heuristic"

    if use_llm and LLM_JUDGE_AVAILABLE:
        try:
            # Load judge prompt
            prompt_dir = os.path.join(os.path.dirname(__file__), "..", "prompts", "evaluation")
            prompt_path = os.path.join(prompt_dir, "llm_judge.system.md")
            if os.path.exists(prompt_path):
                with open(prompt_path, "r", encoding="utf-8") as f:
                    judge_prompt = f.read()
            else:
                judge_prompt = "{criterion_description}\n\n{criterion}\n\n{output_summary}\n\n{sources}\n\n{constraints}"

            result = judge_criterion(
                criterion=criterion,
                snapshot=snapshot,
                judge_prompt=judge_prompt,
                config=judge_config,
            )
            score = result.score
            llm_reasoning = result.reasoning
            confidence = result.confidence
            judged_by = "llm"
        except LLMJudgeError as e:
            # Graceful degradation: fall back to heuristic
            logger = logging.getLogger(__name__)
            logger.warning("LLM judge failed for '%s': %s. Falling back to heuristic.", cid, e)
            print(f"⚠️  LLM judge failed for '{cid}': {e}. Falling back to heuristic.", file=sys.stderr)
            judged_by = "heuristic(fallback)"

    if score is None:
        score = _heuristic_score(cid, snapshot)

    result = {
        "criterion_id": cid,
        "weight": weight,
        "score": score,
        "description": desc,
        "judged_by": judged_by,
    }
    if llm_reasoning is not None:
        result["llm_reasoning"] = llm_reasoning
    if confidence is not None:
        result["confidence"] = confidence

    return result


def generate_report(
    snapshot: Dict[str, Any],
    rubric: Dict[str, Any],
    scores: List[Dict[str, Any]],
    evaluator_version: str,
    judge_mode: str = "heuristic",
) -> Dict[str, Any]:
    """
    Build an eval_report matching schemas/eval_report.schema.json (Phase 5 enhanced).
    Includes all 8 dimensions, findings, suggestions, and improvement plan skeleton.
    """
    rubric_info = rubric.get("rubric", {})
    rubric_id = rubric_info.get("id", "unknown")
    pass_threshold = rubric.get("pass_threshold", DEFAULT_THRESHOLD)

    # ── Weighted overall score ──
    weighted = sum(s["score"] * s["weight"] for s in scores)
    total_weight = sum(s["weight"] for s in scores)
    overall = round(weighted / max(total_weight, 0.001), 2)

    # ── 8-dimension scores ──
    dim_scores = _compute_dimension_scores(scores)

    # Add heuristic-only dimensions
    dim_scores["human_modification_rate"] = _estimate_human_modification_rate(snapshot)
    dim_scores["output_adoption_rate"] = _estimate_output_adoption_rate(snapshot)
    dim_scores["high_risk_miss_rate"] = _estimate_high_risk_miss_rate(snapshot)
    dim_scores["cost_latency"] = _estimate_cost_latency(snapshot)

    # ── Findings ──
    findings = []
    for s in scores:
        if s["score"] < 0.6:
            severity = "critical" if s["score"] < 0.2 else ("high" if s["score"] < 0.4 else "medium")
            dim = CRITERION_DIMENSION_MAP.get(s["criterion_id"], "format_compliance")
            finding = {
                "type": s["criterion_id"],
                "severity": severity,
                "message": f"{s['criterion_id']}: score={s['score']} — {s['description']}",
                "affected_dimension": dim,
                "remediation": CRITERION_DESCRIPTIONS.get(s["criterion_id"], "Review this area."),
            }
            # Phase 7a: include LLM reasoning when available
            if s.get("llm_reasoning"):
                finding["llm_reasoning"] = s["llm_reasoning"]
            if s.get("confidence") is not None:
                finding["confidence"] = s["confidence"]
            findings.append(finding)

    # Also include LLM-judged-but-passing criteria as informational findings
    for s in scores:
        if s["score"] >= 0.6 and s.get("judged_by", "").startswith("llm"):
            finding = {
                "type": s["criterion_id"],
                "severity": "low",
                "message": f"{s['criterion_id']}: score={s['score']} (LLM-judged, passed)",
                "affected_dimension": CRITERION_DIMENSION_MAP.get(s["criterion_id"], "format_compliance"),
            }
            if s.get("llm_reasoning"):
                finding["llm_reasoning"] = s["llm_reasoning"]
            if s.get("confidence") is not None:
                finding["confidence"] = s["confidence"]
            findings.append(finding)

    # ── Risk level ──
    risk_level = "low"
    if overall < 0.4:
        risk_level = "critical"
    elif overall < 0.6:
        risk_level = "high"
    elif overall < 0.8:
        risk_level = "medium"

    # ── Suggestions ──
    suggestions = []
    for s in scores:
        if s["score"] < 0.5:
            dim = CRITERION_DIMENSION_MAP.get(s["criterion_id"], "format_compliance")
            suggestions.append({
                "target": _suggest_target(dim),
                "recommendation": f"Improve {s['criterion_id']} (score={s['score']}): {s['description']}",
                "priority": "high" if s["score"] < 0.3 else "medium",
                "requires_human_approval": True,
                "expected_impact": {
                    "affected_metrics": [dim],
                    "estimated_improvement": round(0.6 - s["score"], 2),
                },
            })

    return {
        "run_id": snapshot.get("run_id", str(uuid.uuid4())),
        "workflow_id": snapshot.get("workflow_id", "unknown"),
        "rubric_id": rubric_id,
        "evaluator_version": evaluator_version,
        "evaluation_mode": "async_nonblocking",
        "score": overall,
        "risk_level": risk_level,
        "passed": overall >= pass_threshold,
        "pass_threshold": pass_threshold,
        "metrics": dim_scores,
        "metric_weights": DEFAULT_METRIC_WEIGHTS,
        "findings": findings,
        "suggestions": suggestions,
        "improvement_plan": {
            "generated": False,
            "candidate_changes": [],
            "rollback_plan": "N/A — Phase 7",
        },
        "created_at": datetime.now(timezone.utc).isoformat(),
        "evaluated_by": f"eval_runner.py ({judge_mode})",
    }


def _suggest_target(dimension: str) -> str:
    """Map dimension to suggested improvement target."""
    mapping = {
        "citation_accuracy": "retrieval_strategy",
        "constraint_compliance": "constraint_rules",
        "format_compliance": "output_templates",
        "risk_detection": "workflow_steps",
        "human_modification_rate": "prompts",
        "output_adoption_rate": "output_templates",
        "high_risk_miss_rate": "workflow_steps",
        "cost_latency": "model_routing",
    }
    return mapping.get(dimension, "prompts")


# ═══════════════════════════════════════════════════════════════
# Execution
# ═══════════════════════════════════════════════════════════════

def run_single(
    snapshot_path: str,
    rubric_path: str,
    output_path: str,
    judge_mode: str = "heuristic",
    judge_config_path: Optional[str] = None,
) -> Dict[str, Any]:
    """POST /evaluation/run — single snapshot evaluation."""
    snapshot = load_json(snapshot_path)
    rubric = load_yaml(rubric_path)

    criteria = rubric.get("criteria", [])
    rubric_version = rubric.get("rubric", {}).get("version", "0.1.0")

    # Load judge config if specified (for LLM mode)
    jc = None
    if judge_mode != "heuristic":
        jc = load_judge_config(judge_config_path)

    scores = [evaluate_criterion(c, snapshot, judge_mode, jc) for c in criteria]
    report = generate_report(snapshot, rubric, scores, rubric_version, judge_mode=judge_mode)
    save_json(report, output_path)

    return report


def run_batch(
    snapshot_dir: str,
    rubric_path: Optional[str],
    output_dir: str,
    auto_rubric: bool = False,
    judge_mode: str = "heuristic",
    judge_config_path: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """POST /evaluation/batch — multiple snapshot evaluation."""
    reports = []
    skipped = []

    for fname in sorted(os.listdir(snapshot_dir)):
        if not fname.endswith(".json") or fname.endswith("_eval.json"):
            continue

        snap_path = os.path.join(snapshot_dir, fname)

        # Determine rubric
        if auto_rubric:
            snapshot = load_json(snap_path)
            wf_id = snapshot.get("workflow_id", "")
            matched = find_rubric_path(wf_id)
            if not matched:
                skipped.append((fname, f"no rubric for workflow '{wf_id}'"))
                continue
            actual_rubric = matched
        elif rubric_path:
            actual_rubric = rubric_path
        else:
            skipped.append((fname, "no rubric specified"))
            continue

        out_path = os.path.join(output_dir, fname.replace(".json", "_eval.json"))
        try:
            report = run_single(snap_path, actual_rubric, out_path, judge_mode=judge_mode, judge_config_path=judge_config_path)
            reports.append(report)
        except Exception as e:
            skipped.append((fname, str(e)))

    if skipped:
        print(f"⚠️  Skipped {len(skipped)} files:")
        for name, reason in skipped:
            print(f"   - {name}: {reason}")

    return reports


def generate_batch_summary(
    reports: List[Dict[str, Any]],
    output_dir: str,
) -> Dict[str, Any]:
    """Generate a batch summary report."""
    total = len(reports)
    if total == 0:
        return {"total": 0, "message": "No reports to summarize."}

    passed = sum(1 for r in reports if r.get("passed", False))
    avg_score = round(sum(r.get("score", 0) for r in reports) / total, 2)

    # By workflow
    by_workflow: Dict[str, Dict[str, Any]] = {}
    for r in reports:
        wf = r.get("workflow_id", "unknown")
        if wf not in by_workflow:
            by_workflow[wf] = {"count": 0, "scores": [], "passed": 0}
        by_workflow[wf]["count"] += 1
        by_workflow[wf]["scores"].append(r.get("score", 0))
        if r.get("passed"):
            by_workflow[wf]["passed"] += 1

    by_wf_summary = {}
    for wf, data in by_workflow.items():
        by_wf_summary[wf] = {
            "count": data["count"],
            "average_score": round(sum(data["scores"]) / len(data["scores"]), 2),
            "pass_rate": round(data["passed"] / data["count"], 2),
        }

    # By risk level
    by_risk: Dict[str, Dict[str, Any]] = {}
    for r in reports:
        rl = r.get("risk_level", "unknown")
        if rl not in by_risk:
            by_risk[rl] = {"count": 0, "scores": []}
        by_risk[rl]["count"] += 1
        by_risk[rl]["scores"].append(r.get("score", 0))

    by_risk_summary = {}
    for rl, data in by_risk.items():
        by_risk_summary[rl] = {
            "count": data["count"],
            "average_score": round(sum(data["scores"]) / len(data["scores"]), 2),
        }

    # Top findings
    finding_counts: Dict[str, int] = {}
    for r in reports:
        for f in r.get("findings", []):
            ftype = f.get("type", "unknown")
            finding_counts[ftype] = finding_counts.get(ftype, 0) + 1

    top_findings = sorted(
        [{"type": k, "count": v} for k, v in finding_counts.items()],
        key=lambda x: x["count"],
        reverse=True,
    )[:10]

    summary = {
        "batch_id": str(uuid.uuid4())[:8],
        "total": total,
        "passed": passed,
        "failed": total - passed,
        "average_score": avg_score,
        "by_workflow": by_wf_summary,
        "by_risk_level": by_risk_summary,
        "top_findings": top_findings,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }

    summary_path = os.path.join(output_dir, "_batch_summary.json")
    save_json(summary, summary_path)
    return summary


# ═══════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="Phase 5 评估旁路运行器 — 8维评估指标体系",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 单次评估（指定 rubric）
  python scripts/eval_runner.py -s tests/eval_cases/synthetic/run_snapshot_sample_001.json \\
      -r evaluators/rubrics/business_model_validation.yaml

  # 单次评估（自动匹配 rubric）
  python scripts/eval_runner.py -s tests/eval_cases/synthetic/run_snapshot_sample_002.json --auto

  # 批量评估 + 汇总
  python scripts/eval_runner.py -b tests/eval_cases/synthetic/ --auto --summary
        """,
    )
    parser.add_argument(
        "-s", "--snapshot",
        help="单个 run_snapshot JSON 文件路径",
    )
    parser.add_argument(
        "-b", "--batch",
        help="run_snapshot 目录路径 (批量模式)",
    )
    parser.add_argument(
        "-r", "--rubric",
        help="rubric YAML 文件路径 (与 --auto 互斥)",
    )
    parser.add_argument(
        "--auto", "--auto-rubric",
        dest="auto_rubric",
        action="store_true",
        help="根据 snapshot 中的 workflow_id 自动匹配 rubric",
    )
    parser.add_argument(
        "-o", "--output",
        help="单个报告输出路径",
    )
    parser.add_argument(
        "-d", "--output-dir",
        default="outputs/eval_reports",
        help="批量报告输出目录 (默认: outputs/eval_reports)",
    )
    parser.add_argument(
        "--summary",
        action="store_true",
        help="批量评估后生成汇总报告",
    )
    # Phase 7a: LLM-as-Judge options
    parser.add_argument(
        "--judge-mode",
        choices=["heuristic", "llm", "hybrid"],
        default="heuristic",
        help="评分模式: heuristic(默认/关键词) | llm(全部LLM) | hybrid(混合策略)",
    )
    parser.add_argument(
        "--judge-config",
        default=None,
        help="Judge 配置 YAML 路径 (默认: evaluators/rubrics/shared_judge_config.yaml)",
    )
    args = parser.parse_args()

    # Validate
    if not args.auto_rubric and not args.rubric:
        print("❌ 必须指定 --rubric 或 --auto", file=sys.stderr)
        sys.exit(1)

    # ── Single snapshot ──
    if args.snapshot:
        if args.auto_rubric:
            snapshot = load_json(args.snapshot)
            wf_id = snapshot.get("workflow_id", "")
            rubric_path = find_rubric_path(wf_id)
            if not rubric_path:
                print(f"❌ 无法为 workflow '{wf_id}' 自动匹配 rubric", file=sys.stderr)
                sys.exit(1)
            print(f"🔍 Auto-matched rubric: {rubric_path}")
        else:
            rubric_path = args.rubric

        output = args.output or args.snapshot.replace(".json", "_eval.json")

        # Resolve default judge config path
        judge_config_path = args.judge_config
        if args.judge_mode != "heuristic" and not judge_config_path:
            default_jc = os.path.join(os.path.dirname(__file__), "..", "evaluators", "rubrics", "shared_judge_config.yaml")
            if os.path.exists(default_jc):
                judge_config_path = default_jc

        report = run_single(args.snapshot, rubric_path, output,
                           judge_mode=args.judge_mode,
                           judge_config_path=judge_config_path)

        print(f"✅ Eval complete: {output}")
        print(f"   Workflow: {report['workflow_id']} | Rubric: {report['rubric_id']}")
        print(f"   Score: {report['score']} | Risk: {report['risk_level']} | Passed: {report['passed']}")
        print(f"   Judge Mode: {report.get('evaluated_by', 'heuristic')}")
        print(f"   8-Dim Metrics:")
        for dim, val in report.get("metrics", {}).items():
            bar = "█" * int(val * 10) + "░" * (10 - int(val * 10))
            print(f"     {dim:30s} {bar} {val:.2f}")
        if report["findings"]:
            print(f"   Findings: {len(report['findings'])}")
            for f in report["findings"]:
                llm_tag = " [LLM]" if f.get("llm_reasoning") else ""
                conf_tag = f" conf={f['confidence']:.2f}" if f.get("confidence") is not None else ""
                print(f"     [{f['severity']}]{llm_tag}{conf_tag} {f['message'][:80]}")
        if report["suggestions"]:
            print(f"   Suggestions: {len(report['suggestions'])}")

    # ── Batch ──
    elif args.batch:
        judge_config_path = args.judge_config
        if args.judge_mode != "heuristic" and not judge_config_path:
            default_jc = os.path.join(os.path.dirname(__file__), "..", "evaluators", "rubrics", "shared_judge_config.yaml")
            if os.path.exists(default_jc):
                judge_config_path = default_jc

        reports = run_batch(
            args.batch,
            args.rubric if not args.auto_rubric else None,
            args.output_dir,
            auto_rubric=args.auto_rubric,
            judge_mode=args.judge_mode,
            judge_config_path=judge_config_path,
        )
        passed = sum(1 for r in reports if r.get("passed", False))
        print(f"✅ Batch eval complete: {len(reports)} snapshots → {args.output_dir}")
        print(f"   Passed: {passed}/{len(reports)}")

        if args.summary and reports:
            summary = generate_batch_summary(reports, args.output_dir)
            print(f"📊 Batch summary: {args.output_dir}/_batch_summary.json")
            print(f"   Avg Score: {summary['average_score']} | Pass Rate: {summary['passed']}/{summary['total']}")
            if summary.get("top_findings"):
                print(f"   Top finding: {summary['top_findings'][0]['type']} ({summary['top_findings'][0]['count']}×)")

    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()

