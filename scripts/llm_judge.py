#!/usr/bin/env python3
"""
llm_judge.py — LLM-as-Judge 评判封装模块 (Phase 7a)

提供核心接口 `judge_criterion()`，调用 LLM 对工作流运行快照中的
单个评估标准 (criterion) 进行语义评分。

用法:
    from llm_judge import judge_criterion, JudgeResult

    result = judge_criterion(
        criterion={"id": "citation_accuracy", "weight": 0.15, "description": "..."},
        snapshot=snapshot_dict,
        judge_prompt="你是一个工作流输出评估裁判...",
        model="deepseek-chat",
    )
    print(result.score, result.reasoning)
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════
# Data Contract — JudgeResult
# ═══════════════════════════════════════════════════════════════

@dataclass
class JudgeResult:
    """
    LLM 评判单条 criterion 的结构化输出。

    Attributes:
        score:      评分 (0.0-1.0)
        reasoning:  评分理由（人类可读）
        evidence:   从 snapshot 中引用的支持判断的片段列表
        confidence: LLM 自身对判断的置信度 (0.0-1.0)
    """
    score: float = 0.0
    reasoning: str = ""
    evidence: List[str] = field(default_factory=list)
    confidence: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ═══════════════════════════════════════════════════════════════
# Configuration
# ═══════════════════════════════════════════════════════════════

def load_judge_config(config_path: Optional[str] = None) -> Dict[str, Any]:
    """
    Load shared judge configuration from YAML.

    Default config is used when no path is provided or file is missing.
    """
    default_config = {
        "default_mode": "heuristic",
        "llm_criteria": [
            "legal_citation_quality",
            "jurisdiction_awareness",
            "no_investment_advice",
        ],
        "low_score_threshold": 0.4,
        "fallback_mode": "heuristic",
        "llm_model": "deepseek-chat",
        "llm_api_base": None,
        "llm_api_key_env": "LLM_JUDGE_API_KEY",
        "max_tokens": 1024,
        "temperature": 0.3,
    }

    if not config_path or not os.path.exists(config_path):
        return default_config

    try:
        import yaml
        with open(config_path, "r", encoding="utf-8") as f:
            loaded = yaml.safe_load(f)
        if loaded and isinstance(loaded, dict):
            # Merge: loaded values override defaults
            result = dict(default_config)
            result.update(loaded)
            return result
    except Exception as e:
        logger.warning("Failed to load judge config from %s: %s. Using defaults.", config_path, e)

    return default_config


# ═══════════════════════════════════════════════════════════════
# LLM Call Abstraction
# ═══════════════════════════════════════════════════════════════

class LLMJudgeError(Exception):
    """Base exception for LLM judge failures."""
    pass


class LLMConnectionError(LLMJudgeError):
    """LLM API connection or timeout error."""
    pass


class LLMResponseError(LLMJudgeError):
    """LLM returned malformed or unparseable response."""
    pass


def _call_llm(
    system_prompt: str,
    user_message: str,
    config: Dict[str, Any],
) -> str:
    """
    Call the configured LLM with the given prompts.

    Supports OpenAI-compatible API. The API base URL and key are resolved from:
      1. config['llm_api_base'] / config['llm_api_key_env']
      2. Environment variable LLM_JUDGE_API_BASE / LLM_JUDGE_API_KEY
      3. Falls back to OPENAI_API_BASE / OPENAI_API_KEY

    Raises LLMConnectionError on network/API errors.
    Raises LLMResponseError on unparseable responses.
    """
    api_base = (
        config.get("llm_api_base")
        or os.environ.get("LLM_JUDGE_API_BASE")
        or os.environ.get("OPENAI_API_BASE")
        or "https://api.openai.com/v1"
    )
    api_key_env = config.get("llm_api_key_env", "LLM_JUDGE_API_KEY")
    api_key = os.environ.get(api_key_env) or os.environ.get("OPENAI_API_KEY")

    if not api_key:
        raise LLMConnectionError(
            f"LLM API key not found. Set {api_key_env} or OPENAI_API_KEY."
        )

    model = config.get("llm_model", "deepseek-chat")
    max_tokens = config.get("max_tokens", 1024)
    temperature = config.get("temperature", 0.3)

    # Build OpenAI-compatible request
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ],
        "max_tokens": max_tokens,
        "temperature": temperature,
        "response_format": {"type": "json_object"},
    }

    import urllib.request
    import urllib.error

    req = urllib.request.Request(
        f"{api_base.rstrip('/')}/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        error_detail = ""
        try:
            error_detail = e.read().decode("utf-8")
        except Exception:
            pass
        raise LLMConnectionError(
            f"LLM API HTTP {e.code}: {error_detail}"
        ) from e
    except (urllib.error.URLError, OSError, TimeoutError) as e:
        raise LLMConnectionError(f"LLM API connection failed: {e}") from e
    except json.JSONDecodeError as e:
        raise LLMResponseError(f"LLM API returned non-JSON response: {e}") from e

    # Extract content
    try:
        choices = body.get("choices", [])
        if not choices:
            raise LLMResponseError("LLM returned empty choices.")
        content = choices[0].get("message", {}).get("content", "")
        if not content:
            raise LLMResponseError("LLM returned empty message content.")
        return content
    except (KeyError, IndexError, TypeError) as e:
        raise LLMResponseError(f"Unexpected LLM response structure: {e}") from e


def _parse_judge_response(raw: str) -> JudgeResult:
    """
    Parse LLM response JSON into a JudgeResult.

    Expected JSON structure:
    {
        "score": 0.85,
        "reasoning": "...",
        "evidence": ["..."],
        "confidence": 0.9
    }
    """
    # Try to extract JSON from potential markdown fences
    content = raw.strip()
    if content.startswith("```"):
        # Remove markdown code fences: collect content INSIDE the fence
        lines = content.splitlines()
        cleaned = []
        in_fence = False
        for line in lines:
            if line.strip().startswith("```"):
                in_fence = not in_fence
                continue
            if in_fence:
                cleaned.append(line)
        content = "\n".join(cleaned).strip()

    try:
        data = json.loads(content)
    except json.JSONDecodeError as e:
        raise LLMResponseError(
            f"LLM response is not valid JSON: {e}\nRaw: {raw[:500]}"
        ) from e

    score = data.get("score", 0.0)
    reasoning = data.get("reasoning", "") or data.get("reason", "")
    evidence = data.get("evidence", []) or data.get("evidences", [])
    confidence = data.get("confidence", 0.0)

    # Validate types
    if not isinstance(score, (int, float)):
        score = 0.0
    if not isinstance(reasoning, str):
        reasoning = str(reasoning) if reasoning else ""
    if not isinstance(evidence, list):
        evidence = list(evidence) if evidence else []
    if not isinstance(confidence, (int, float)):
        confidence = 0.0

    # Clamp ranges
    score = max(0.0, min(1.0, float(score)))
    confidence = max(0.0, min(1.0, float(confidence)))
    evidence = [str(e) for e in evidence[:10]]  # cap at 10 items

    return JudgeResult(
        score=round(score, 2),
        reasoning=reasoning.strip(),
        evidence=evidence,
        confidence=round(confidence, 2),
    )


# ═══════════════════════════════════════════════════════════════
# Core Interface
# ═══════════════════════════════════════════════════════════════

def judge_criterion(
    criterion: Dict[str, Any],
    snapshot: Dict[str, Any],
    judge_prompt: str,
    model: Optional[str] = None,
    config: Optional[Dict[str, Any]] = None,
) -> JudgeResult:
    """
    Evaluate a single rubric criterion against a run snapshot using LLM.

    Args:
        criterion:     Rubric criterion dict with keys: id, weight, description
        snapshot:      Run snapshot dict (output_summary, retrieved_sources,
                       constraints_triggered, workflow_state, human_review, etc.)
        judge_prompt:  System prompt template for the LLM judge. The following
                       placeholders are supported:
                         - {criterion_description}
                         - {criterion}
                         - {output_summary}
                         - {sources}
                         - {constraints}
        model:         Optional model override (e.g. "gpt-4o", "claude-3-opus").
                       Falls back to config['llm_model'].
        config:        Judge configuration dict. If None, loaded from default path.

    Returns:
        JudgeResult with score, reasoning, evidence, confidence.

    Raises:
        LLMConnectionError: LLM API is unreachable or returned HTTP errors.
        LLMResponseError:   LLM response is malformed or unparseable.

    Example:
        >>> result = judge_criterion(
        ...     criterion={"id": "citation_accuracy", "weight": 0.15, "description": "..."},
        ...     snapshot=snapshot_dict,
        ...     judge_prompt=prompt_template,
        ... )
        >>> result.score
        0.85
        >>> result.reasoning
        "The output correctly cites 3 of 4 retrieved sources..."
    """
    if config is None:
        config = load_judge_config()

    effective_model = model or config.get("llm_model", "deepseek-chat")

    # Prepare placeholders
    criterion_description = criterion.get("description", "")
    output_summary = snapshot.get("output_summary", {})
    sources = snapshot.get("retrieved_sources", [])
    constraints = snapshot.get("constraints_triggered", [])

    # Format sources for prompt context
    sources_text = _format_sources(sources)
    constraints_text = _format_constraints(constraints)
    output_text = _format_output(output_summary)

    # Build user message by substituting placeholders
    user_message = judge_prompt.replace("{criterion_description}", str(criterion_description))
    user_message = user_message.replace("{criterion}", json.dumps(criterion, ensure_ascii=False, indent=2))
    user_message = user_message.replace("{output_summary}", output_text)
    user_message = user_message.replace("{sources}", sources_text)
    user_message = user_message.replace("{constraints}", constraints_text)

    # System prompt: fixed instruction for the judge role
    system_prompt = (
        "You are a strict workflow output evaluation judge. "
        "Your task is to score how well the output meets the given criterion. "
        "Respond ONLY with a JSON object containing: "
        '"score" (float 0.0-1.0), '
        '"reasoning" (string explaining the score), '
        '"evidence" (array of strings citing specific passages), '
        '"confidence" (float 0.0-1.0 indicating your certainty). '
        "Score strictly based on the evidence provided — do not assume unstated information."
    )

    # Call LLM
    raw = _call_llm(system_prompt, user_message, {**config, "llm_model": effective_model})

    # Parse response
    result = _parse_judge_response(raw)

    logger.info(
        "judge_criterion(%s): score=%.2f, confidence=%.2f",
        criterion.get("id", "?"), result.score, result.confidence,
    )

    return result


# ═══════════════════════════════════════════════════════════════
# Formatting Helpers
# ═══════════════════════════════════════════════════════════════

def _format_sources(sources: List[Dict[str, Any]]) -> str:
    """Format retrieved sources into a readable text block."""
    if not sources:
        return "(no sources retrieved)"
    lines = []
    for i, s in enumerate(sources, 1):
        sid = s.get("source_id", s.get("id", f"source_{i}"))
        title = s.get("title", s.get("name", ""))
        snippet = s.get("snippet", s.get("content", ""))
        if isinstance(snippet, str) and len(snippet) > 300:
            snippet = snippet[:300] + "..."
        lines.append(f"[{i}] ID: {sid} | Title: {title}")
        if snippet:
            lines.append(f"    Snippet: {snippet}")
    return "\n".join(lines)


def _format_constraints(constraints: List[Dict[str, Any]]) -> str:
    """Format triggered constraints into a readable text block."""
    if not constraints:
        return "(no constraints triggered)"
    lines = []
    for c in constraints:
        cid = c.get("constraint_id", c.get("id", "?"))
        severity = c.get("severity", "unknown")
        msg = c.get("message", c.get("description", ""))
        lines.append(f"- [{severity}] {cid}: {msg}")
    return "\n".join(lines)


def _format_output(output: Dict[str, Any]) -> str:
    """Format output summary into a readable text block."""
    if not output:
        return "(empty output)"
    return json.dumps(output, ensure_ascii=False, indent=2)


# ═══════════════════════════════════════════════════════════════
# CLI — Quick test
# ═══════════════════════════════════════════════════════════════

def main():
    """Quick test: run judge_criterion with a sample snapshot."""
    import argparse

    parser = argparse.ArgumentParser(description="LLM Judge — 单条 criterion 评判测试")
    parser.add_argument("--criterion-id", default="citation_accuracy", help="Criterion ID to test")
    parser.add_argument("--snapshot", required=True, help="Path to run_snapshot JSON")
    parser.add_argument("--prompt", default="prompts/evaluation/llm_judge.system.md", help="Judge prompt path")
    parser.add_argument("--model", default=None, help="LLM model override")
    parser.add_argument("--config", default=None, help="Judge config YAML path")
    parser.add_argument("--verbose", "-v", action="store_true", help="Enable debug logging")
    args = parser.parse_args()

    if args.verbose:
        logging.basicConfig(level=logging.DEBUG)
    else:
        logging.basicConfig(level=logging.INFO)

    # Load snapshot
    from eval_runner import load_json
    snapshot = load_json(args.snapshot)

    # Load rubric to find criterion definition
    # (For quick test, construct a minimal criterion)
    criterion = {"id": args.criterion_id, "weight": 0.15, "description": CRITERION_DESCRIPTIONS.get(args.criterion_id, "")}

    # Load judge prompt
    prompt_path = args.prompt
    if not os.path.exists(prompt_path):
        print(f"⚠️  Judge prompt not found: {prompt_path}. Using built-in fallback.")
        judge_prompt = "{criterion_description}\n\n{criterion}\n\n{output_summary}\n\n{sources}\n\n{constraints}"
    else:
        with open(prompt_path, "r", encoding="utf-8") as f:
            judge_prompt = f.read()

    # Run
    config = load_judge_config(args.config)
    try:
        result = judge_criterion(criterion, snapshot, judge_prompt, model=args.model, config=config)
        print(f"\n✅ Judge Result:")
        print(f"   Score:      {result.score}")
        print(f"   Confidence: {result.confidence}")
        print(f"   Reasoning:  {result.reasoning}")
        print(f"   Evidence:   {len(result.evidence)} items")
        for e in result.evidence:
            print(f"     - {e[:120]}")
    except LLMJudgeError as e:
        print(f"\n❌ Judge failed: {e}")
        sys.exit(1)


# Allow importing CRITERION_DESCRIPTIONS from eval_runner
# (Used only in CLI test mode)
try:
    from eval_runner import CRITERION_DESCRIPTIONS
except ImportError:
    CRITERION_DESCRIPTIONS = {}


if __name__ == "__main__":
    import sys
    main()
