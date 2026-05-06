#!/usr/bin/env python3
"""
eval_set_manager.py — Phase 7b 动态评估集管理器

从 outputs/eval_reports/ 目录读取评估报告，按 config/eval-set-config.yaml
定义的规则自动分类、去重，写入 tests/eval_cases/ 下各分类目录。

用法:
  # 自动分类（从报告目录读取并分类到各目标目录）
  python scripts/eval_set_manager.py classify

  # 查看评估集统计
  python scripts/eval_set_manager.py stats

  # 从黄金样本创建基线
  python scripts/eval_set_manager.py create-baseline

  # 指定报告目录
  python scripts/eval_set_manager.py classify --report-dir outputs/eval_reports/
"""

from __future__ import annotations

import argparse
import glob
import hashlib
import json
import os
import re
import sys
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

try:
    import yaml
except ImportError:
    print("⚠️  PyYAML not installed. Run: pip install pyyaml", file=sys.stderr)
    sys.exit(1)


# ═══════════════════════════════════════════════════════════════
# Constants
# ═══════════════════════════════════════════════════════════════

DEFAULT_CONFIG_PATH = "config/eval-set-config.yaml"
DEFAULT_REPORT_DIR = "outputs/eval_reports/"
EVAL_SET_SCHEMA_PATH = "schemas/eval_set.schema.json"
MANAGER_VERSION = "0.1.0"


# ═══════════════════════════════════════════════════════════════
# I/O Helpers
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
# Hashing
# ═══════════════════════════════════════════════════════════════

def compute_hash(data: str, algorithm: str = "sha256") -> str:
    """Compute a hash of the given string."""
    h = hashlib.new(algorithm)
    h.update(data.encode("utf-8"))
    return h.hexdigest()[:16]  # Use first 16 chars for readability


def make_input_hash(snapshot: Dict[str, Any], max_chars: int = 2000) -> str:
    """Create a deterministic hash from snapshot input fields."""
    parts = [
        str(snapshot.get("workflow_id", "")),
        str(snapshot.get("run_id", "")),
    ]
    # Include input-related fields
    for key in ("input_summary", "user_input", "query"):
        val = snapshot.get(key)
        if val:
            parts.append(str(val)[:max_chars])
    raw = "||".join(parts)
    return compute_hash(raw)


def make_output_hash(snapshot: Dict[str, Any], max_chars: int = 2000) -> str:
    """Create a deterministic hash from snapshot output fields."""
    output = snapshot.get("output_summary", {})
    if isinstance(output, dict):
        raw = json.dumps(output, sort_keys=True, ensure_ascii=False)[:max_chars]
    else:
        raw = str(output)[:max_chars]
    return compute_hash(raw)


def make_dedup_key(
    template: str,
    snapshot: Dict[str, Any],
    constraint_id: Optional[str] = None,
) -> str:
    """Build a dedup key based on the template string.

    Supported placeholders:
      - workflow_id
      - input_hash
      - output_hash
      - constraint_id
    """
    input_h = make_input_hash(snapshot)
    output_h = make_output_hash(snapshot)

    key = template.replace("workflow_id", snapshot.get("workflow_id", "unknown"))
    key = key.replace("input_hash", input_h)
    key = key.replace("output_hash", output_h)
    if constraint_id:
        key = key.replace("constraint_id", constraint_id)
    else:
        key = key.replace("constraint_id", "none")
    return compute_hash(key)


# ═══════════════════════════════════════════════════════════════
# Condition Evaluation
# ═══════════════════════════════════════════════════════════════

class ConditionEvalError(Exception):
    """Error evaluating a classification condition."""
    pass


class _AttrDict:
    """Recursively wrap a dict to support attribute-style access (d.key)."""
    def __init__(self, data):
        for k, v in data.items():
            if isinstance(v, dict):
                object.__setattr__(self, k, _AttrDict(v))
            elif isinstance(v, list):
                object.__setattr__(self, k, [
                    _AttrDict(item) if isinstance(item, dict) else item
                    for item in v
                ])
            else:
                object.__setattr__(self, k, v)

    def __repr__(self):
        items = {k: v for k, v in self.__dict__.items()}
        return f"_AttrDict({items})"


def _to_attr(obj):
    """Convert a dict (or nested dicts/lists) to attribute-accessible form."""
    if isinstance(obj, dict):
        return _AttrDict(obj)
    return obj


def _eval_condition(
    condition_str: str,
    report: Dict[str, Any],
    snapshot: Optional[Dict[str, Any]] = None,
) -> bool:
    """Safely evaluate a condition expression.

    Uses a restricted set of builtins to prevent injection.
    Converts report and snapshot to attribute-accessible objects
    so that expressions like 'report.score < 0.4' work on dict inputs.

    Supported patterns:
      - "report.score < 0.4"
      - "snapshot.human_review.review_status in ('approved_with_changes', 'rejected')"
      - "any(c.severity == 'critical' for c in snapshot.constraints_triggered)"
    """
    safe_dict = {
        "report": _to_attr(report),
        "snapshot": _to_attr(snapshot or {}),
        "True": True,
        "False": False,
        "any": any,
        "all": all,
    }

    try:
        result = eval(condition_str, {"__builtins__": {}}, safe_dict)
        return bool(result)
    except AttributeError as e:
        # Missing attribute likely means snapshot data is not available
        # for this condition. Return False gracefully.
        return False
    except Exception as e:
        raise ConditionEvalError(
            f"Failed to evaluate condition: {condition_str!r}: {e}"
        ) from e


# ═══════════════════════════════════════════════════════════════
# Classification
# ═══════════════════════════════════════════════════════════════

def find_reports(report_dir: str, config: Dict[str, Any]) -> List[str]:
    """Find all eval report JSON files in the report directory."""
    rules = config.get("eval_set_rules", {})
    scan = config.get("scan", {})
    pattern = scan.get("report_pattern", "*_eval.json")
    exclude_patterns = scan.get("exclude_patterns", [])

    search_path = os.path.join(report_dir, pattern)
    files = sorted(glob.glob(search_path))

    # Filter out excluded patterns
    for excl in exclude_patterns:
        excl_path = os.path.join(report_dir, excl)
        files = [f for f in files if not glob.fnmatch.fnmatch(f, excl_path)]

    return files


def classify_report(
    report_path: str,
    config: Dict[str, Any],
    snapshot_cache: Dict[str, Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    """
    Classify a single eval report based on the configured rules.

    Returns an eval set sample dict if a rule matches, or None.
    """
    try:
        report = load_json(report_path)
    except (json.JSONDecodeError, IOError) as e:
        print(f"⚠️  Skipping {report_path}: {e}", file=sys.stderr)
        return None

    snapshot_id = report.get("run_id", "")
    workflow_id = report.get("workflow_id", "unknown")

    # Load snapshot from cache or from original path
    # (Snapshots might be in tests/eval_cases/synthetic/ or elsewhere)
    snapshot = _resolve_snapshot(report, snapshot_cache)

    rules = config.get("eval_set_rules", {})
    auto_classify = rules.get("auto_classify", [])
    max_per_category = rules.get("max_samples_per_category", 200)

    for rule in auto_classify:
        condition = rule.get("condition", "")
        target = rule.get("target", "")
        dedup_key_template = rule.get("dedup_key", "workflow_id + input_hash")
        requires_approval = rule.get("requires_human_approval", False)
        rule_max = rule.get("max_samples_per_category", max_per_category)

        try:
            matches = _eval_condition(condition, report, snapshot)
        except ConditionEvalError as e:
            print(f"⚠️  Condition eval error for {report_path}: {e}", file=sys.stderr)
            continue

        if not matches:
            continue

        # Check category sample count
        target_dir = os.path.normpath(target)
        existing_count = len(_load_existing_samples(target_dir))
        if existing_count >= rule_max:
            print(f"  ⏭️  Skipping: {target} already has {existing_count} samples (max {rule_max})")
            return None

        # Build dedup key
        constraint_id = None
        if "constraint_id" in dedup_key_template and snapshot:
            triggered = snapshot.get("constraints_triggered", [])
            if triggered:
                constraint_id = triggered[0].get("constraint_id", triggered[0].get("id", "unknown"))

        dedup_key = make_dedup_key(dedup_key_template, snapshot or report, constraint_id)

        # Check existing samples for dup
        if _is_duplicate(target_dir, dedup_key):
            return None

        # Build sample entry
        output_hash = make_output_hash(snapshot or report) if snapshot else ""
        input_hash = make_input_hash(snapshot or report) if snapshot else ""

        sample = {
            "snapshot_id": snapshot_id,
            "input_hash": input_hash,
            "output_hash": output_hash,
            "workflow_id": workflow_id,
            "original_report_path": os.path.relpath(report_path),
            "score": report.get("score", 0.0),
            "critical_findings": _extract_critical_findings(report),
            "requires_human_approval": requires_approval,
            "classified_at": datetime.now(timezone.utc).isoformat(),
            "classified_by": f"eval_set_manager.py v{MANAGER_VERSION}",
        }

        # Determine category from target path
        category = _target_to_category(target)

        eval_set = {
            "eval_set_id": f"eval_set_{uuid.uuid4().hex[:8]}",
            "version": MANAGER_VERSION,
            "category": category,
            "source_workflow_ids": [workflow_id],
            "samples": [sample],
            "golden_standard": category == "golden",
            "created_at": datetime.now(timezone.utc).isoformat(),
        }

        return {
            "eval_set": eval_set,
            "target_dir": target_dir,
            "dedup_key": dedup_key,
            "category": category,
        }

    return None


def _resolve_snapshot(
    report: Dict[str, Any],
    cache: Dict[str, Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    """Try to find the original run snapshot for a report."""
    snapshot_id = report.get("run_id", "")

    # Check cache first
    if snapshot_id in cache:
        return cache[snapshot_id]

    # Try to find snapshot in known locations
    search_dirs = [
        "tests/eval_cases/synthetic/",
        "tests/eval_cases/golden/",
        "tests/eval_cases/regression/failures/",
        "tests/eval_cases/regression/human_corrected/",
        "tests/eval_cases/regression/risk_samples/",
    ]

    # Try to find by run_id in report's workflow_id
    workflow_id = report.get("workflow_id", "")
    for search_dir in search_dirs:
        if not os.path.isdir(search_dir):
            continue
        for fname in os.listdir(search_dir):
            if not fname.endswith(".json") or fname.endswith("_eval.json"):
                continue
            try:
                snap = load_json(os.path.join(search_dir, fname))
                if snap.get("run_id") == snapshot_id or snap.get("workflow_id") == workflow_id:
                    cache[snapshot_id] = snap
                    return snap
            except Exception:
                continue

    return None


def _target_to_category(target: str) -> str:
    """Infer eval set category from target directory path."""
    if "golden" in target:
        return "golden"
    if "failures" in target:
        return "regression_failure"
    if "human_corrected" in target:
        return "regression_human_corrected"
    if "risk_samples" in target:
        return "regression_risk"
    return "synthetic"


def _extract_critical_findings(report: Dict[str, Any]) -> List[str]:
    """Extract critical/high severity findings from report."""
    findings = report.get("findings", [])
    critical = []
    for f in findings:
        sev = f.get("severity", "")
        if sev in ("critical", "high"):
            critical.append(f.get("message", str(f)))
    return critical[:10]  # Cap at 10


def _load_existing_samples(target_dir: str) -> List[Dict[str, Any]]:
    """Load existing eval set files from a target directory."""
    samples = []
    if not os.path.isdir(target_dir):
        return samples
    for fname in sorted(os.listdir(target_dir)):
        if fname.endswith(".json") and fname != ".gitkeep":
            try:
                data = load_json(os.path.join(target_dir, fname))
                samples.extend(data.get("samples", []))
            except Exception:
                continue
    return samples


def _is_duplicate(target_dir: str, dedup_key: str) -> bool:
    """Check if a sample with the same dedup key already exists."""
    existing = _load_existing_samples(target_dir)
    for s in existing:
        existing_key = s.get("_dedup_key", "")
        if existing_key == dedup_key:
            return True
    return False


def save_classified_sample(
    result: Dict[str, Any],
    config: Dict[str, Any],
) -> bool:
    """Save a classified sample to its target directory.

    Returns True if saved successfully, False if skipped.
    """
    eval_set = result["eval_set"]
    target_dir = result["target_dir"]
    dedup_key = result["dedup_key"]

    # Add dedup key to sample
    if eval_set["samples"]:
        eval_set["samples"][0]["_dedup_key"] = dedup_key

    # Check duplicate one more time
    if _is_duplicate(target_dir, dedup_key):
        return False

    # Generate output filename based on snapshot_id and category
    snapshot_id = eval_set["samples"][0]["snapshot_id"]
    fname = f"{snapshot_id}_{eval_set['category']}.json"
    out_path = os.path.join(target_dir, fname)

    save_json(eval_set, out_path)
    return True


# ═══════════════════════════════════════════════════════════════
# Stats
# ═══════════════════════════════════════════════════════════════

def generate_stats(config: Dict[str, Any]) -> Dict[str, Any]:
    """Generate statistics about all classified eval sets."""
    category_dirs = {
        "golden": "tests/eval_cases/golden/",
        "regression_failure": "tests/eval_cases/regression/failures/",
        "regression_human_corrected": "tests/eval_cases/regression/human_corrected/",
        "regression_risk": "tests/eval_cases/regression/risk_samples/",
        "synthetic": "tests/eval_cases/synthetic/",
    }

    stats = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "manager_version": MANAGER_VERSION,
        "categories": {},
        "total_samples": 0,
        "total_eval_sets": 0,
    }

    for category, directory in category_dirs.items():
        if not os.path.isdir(directory):
            stats["categories"][category] = {
                "sample_count": 0,
                "eval_set_count": 0,
                "directory": directory,
                "latest": None,
                "workflow_ids": [],
                "pending_approval": 0,
            }
            continue

        sample_count = 0
        eval_set_count = 0
        latest_ts = None
        workflow_ids: set = set()
        pending_approval = 0

        for fname in sorted(os.listdir(directory)):
            if not fname.endswith(".json") or fname == ".gitkeep":
                continue
            eval_set_count += 1
            try:
                data = load_json(os.path.join(directory, fname))
                samples = data.get("samples", [])
                sample_count += len(samples)
                for s in samples:
                    wf = s.get("workflow_id", "")
                    if wf:
                        workflow_ids.add(wf)
                    if s.get("requires_human_approval"):
                        pending_approval += 1
                ts = data.get("created_at", "")
                if ts and (latest_ts is None or ts > latest_ts):
                    latest_ts = ts
            except Exception:
                continue

        stats["categories"][category] = {
            "sample_count": sample_count,
            "eval_set_count": eval_set_count,
            "directory": directory,
            "latest": latest_ts,
            "workflow_ids": sorted(workflow_ids),
            "pending_approval": pending_approval,
        }
        stats["total_samples"] += sample_count
        stats["total_eval_sets"] += eval_set_count

    return stats


# ═══════════════════════════════════════════════════════════════
# Baseline
# ═══════════════════════════════════════════════════════════════

def create_baseline(config: Dict[str, Any]) -> Dict[str, Any]:
    """Create a baseline score reference from golden samples."""
    golden_dir = "tests/eval_cases/golden/"
    baseline_dir = "tests/eval_cases/baseline/"

    if not os.path.isdir(golden_dir):
        print("⚠️  Golden directory not found. Run 'classify' first.", file=sys.stderr)
        return {"error": "Golden directory not found"}

    # Collect scores from golden samples
    scores_by_workflow: Dict[str, List[float]] = {}
    all_scores = []

    for fname in sorted(os.listdir(golden_dir)):
        if not fname.endswith(".json") or fname == ".gitkeep":
            continue
        try:
            data = load_json(os.path.join(golden_dir, fname))
            for s in data.get("samples", []):
                score = s.get("score", s.get("expected_score"))
                if score is not None:
                    wf = s.get("workflow_id", "unknown")
                    scores_by_workflow.setdefault(wf, []).append(score)
                    all_scores.append(score)
        except Exception:
            continue

    if not all_scores:
        print("⚠️  No golden samples found with scores.", file=sys.stderr)
        return {"error": "No golden samples with scores"}

    def _avg(vals: List[float]) -> float:
        return round(sum(vals) / len(vals), 3)

    def _min_val(vals: List[float]) -> float:
        return round(min(vals), 3)

    def _max_val(vals: List[float]) -> float:
        return round(max(vals), 3)

    baseline = {
        "baseline_id": f"baseline_{uuid.uuid4().hex[:8]}",
        "version": MANAGER_VERSION,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "total_samples": len(all_scores),
        "overall": {
            "average_score": _avg(all_scores),
            "min_score": _min_val(all_scores),
            "max_score": _max_val(all_scores),
        },
        "by_workflow": {
            wf: {
                "sample_count": len(scores),
                "average_score": _avg(scores),
                "min_score": _min_val(scores),
                "max_score": _max_val(scores),
            }
            for wf, scores in sorted(scores_by_workflow.items())
        },
    }

    fname = f"baseline_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.json"
    out_path = os.path.join(baseline_dir, fname)
    save_json(baseline, out_path)
    print(f"✅ Baseline saved: {out_path}")
    return baseline


# ═══════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="Phase 7b 动态评估集管理器 — 自动分类、统计、基线创建",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 自动分类
  python scripts/eval_set_manager.py classify

  # 指定报告目录分类
  python scripts/eval_set_manager.py classify --report-dir outputs/eval_reports/

  # 查看统计
  python scripts/eval_set_manager.py stats

  # 创建基线
  python scripts/eval_set_manager.py create-baseline
        """,
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # classify
    classify_parser = subparsers.add_parser("classify", help="自动分类评估报告")
    classify_parser.add_argument(
        "--report-dir", default=DEFAULT_REPORT_DIR,
        help=f"评估报告目录 (default: {DEFAULT_REPORT_DIR})",
    )
    classify_parser.add_argument(
        "--config", default=DEFAULT_CONFIG_PATH,
        help=f"分类规则配置 (default: {DEFAULT_CONFIG_PATH})",
    )
    classify_parser.add_argument(
        "--dry-run", action="store_true",
        help="仅预览分类结果，不写入文件",
    )

    # stats
    stats_parser = subparsers.add_parser("stats", help="查看评估集统计")
    stats_parser.add_argument(
        "--config", default=DEFAULT_CONFIG_PATH,
        help=f"分类规则配置 (default: {DEFAULT_CONFIG_PATH})",
    )

    # create-baseline
    baseline_parser = subparsers.add_parser(
        "create-baseline", help="从黄金样本创建基线"
    )
    baseline_parser.add_argument(
        "--config", default=DEFAULT_CONFIG_PATH,
        help=f"分类规则配置 (default: {DEFAULT_CONFIG_PATH})",
    )

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    # Load config
    config_path = args.config
    if not os.path.exists(config_path):
        print(f"❌ Config not found: {config_path}", file=sys.stderr)
        sys.exit(1)

    config = load_yaml(config_path)

    # ── Classify ──
    if args.command == "classify":
        report_dir = args.report_dir
        if not os.path.isdir(report_dir):
            print(f"❌ Report directory not found: {report_dir}", file=sys.stderr)
            sys.exit(1)

        report_files = find_reports(report_dir, config)
        if not report_files:
            print(f"⚠️  No report files found in {report_dir}")
            sys.exit(0)

        print(f"🔍 Found {len(report_files)} report(s) in {report_dir}")
        snapshot_cache: Dict[str, Dict[str, Any]] = {}
        classified = 0
        skipped = 0
        errors = 0

        for i, rpath in enumerate(report_files, 1):
            relpath = os.path.relpath(rpath)
            print(f"  [{i}/{len(report_files)}] {relpath} ...", end=" ")

            try:
                result = classify_report(rpath, config, snapshot_cache)
            except Exception as e:
                print(f"❌ Error: {e}")
                errors += 1
                continue

            if result is None:
                print("⏭️  No rule matched")
                skipped += 1
                continue

            if args.dry_run:
                category = result["category"]
                target = result["target_dir"]
                print(f"🔮 Would classify as {category} → {target}")
                classified += 1
                continue

            saved = save_classified_sample(result, config)
            if saved:
                category = result["category"]
                print(f"✅ Classified as {category}")
                classified += 1
            else:
                print("⏭️  Duplicate or skipped")
                skipped += 1

        print(f"\n📊 Summary: {classified} classified, {skipped} skipped, {errors} errors")

    # ── Stats ──
    elif args.command == "stats":
        stats = generate_stats(config)
        print(f"\n📊 动态评估集统计 (eval_set_manager.py v{MANAGER_VERSION})")
        print(f"   生成时间: {stats['generated_at']}")
        print(f"   总样本数: {stats['total_samples']}")
        print(f"   总评估集数: {stats['total_eval_sets']}")
        print()
        for cat, data in stats["categories"].items():
            bar = "█" * min(int(data["sample_count"] / 5) + 1, 20) if data["sample_count"] > 0 else "—"
            pending = f" ({data['pending_approval']} pending)" if data["pending_approval"] else ""
            print(f"  {cat:35s} {data['sample_count']:4d} samples  {bar}{pending}")
            if data["workflow_ids"]:
                print(f"   {'':35s} workflows: {', '.join(data['workflow_ids'][:5])}")
            if data["latest"]:
                print(f"   {'':35s} latest: {data['latest'][:19]}")

    # ── Create Baseline ──
    elif args.command == "create-baseline":
        baseline = create_baseline(config)
        if "error" not in baseline:
            print(f"\n✅ Baseline created:")
            print(f"   Total samples: {baseline['total_samples']}")
            print(f"   Overall avg score: {baseline['overall']['average_score']}")
            print(f"   Score range: {baseline['overall']['min_score']} - {baseline['overall']['max_score']}")
            for wf, wf_data in baseline.get("by_workflow", {}).items():
                print(f"   {wf}: avg={wf_data['average_score']} (n={wf_data['sample_count']})")


if __name__ == "__main__":
    main()
