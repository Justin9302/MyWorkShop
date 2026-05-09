#!/usr/bin/env python3
"""
lattice_core.py — LatticeWork 晶格引擎核心

职责:
  1. 解析晶格方案 (Lattice) YAML 文件
  2. 生成逆向执行顺序 (Bottom-Up Execution Order)
  3. 管理原子任务状态机
  4. 执行层组装 (Layer Assembly)
  5. 执行意图对齐检查 (Intent Alignment)
  6. 生成 PCDCA 循环记录

用法:
  # 解析晶格方案
  python lattice/scripts/lattice_core.py parse \\
      --lattice lattice/examples/quant_trading/lattice_basis_arbitrage.yaml

  # 生成执行顺序
  python lattice/scripts/lattice_core.py execution-order \\
      --lattice lattice/examples/quant_trading/lattice_basis_arbitrage.yaml

  # 执行层组装
  python lattice/scripts/lattice_core.py assemble \\
      --lattice lattice/examples/quant_trading/lattice_basis_arbitrage.yaml \\
      --layer 4

  # 检查意图对齐
  python lattice/scripts/lattice_core.py align \\
      --lattice lattice/examples/quant_trading/lattice_basis_arbitrage.yaml \\
      --layer 4

  # 生成PCDCA循环记录模板
  python lattice/scripts/lattice_core.py pcdca-template \\
      --task-id task_0001
"""

import argparse
import json
import logging
import os
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

LATTICE_DIR = os.path.join(os.path.dirname(__file__), "..")
SCHEMAS_DIR = os.path.join(LATTICE_DIR, "schemas")
TEMPLATES_DIR = os.path.join(LATTICE_DIR, "templates")
RUNTIME_DIR = os.path.join(LATTICE_DIR, "lattice_runtime")
PCDCA_LOG_DIR = os.path.join(RUNTIME_DIR, "pcdca_log")
CHECKPOINTS_DIR = os.path.join(RUNTIME_DIR, "checkpoints")

# 任务状态枚举
TASK_STATUSES = [
    "pending", "blocked", "in_plan", "plan_approved",
    "in_progress", "in_check", "pass", "fail", "skipped"
]

# 层组装状态枚举
ASSEMBLY_STATUSES = ["pending", "in_progress", "completed", "failed", "blocked"]

# 日志配置
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("lattice_core")


# ═══════════════════════════════════════════════════════════════
# File I/O helpers
# ═══════════════════════════════════════════════════════════════

def load_yaml(path: str) -> Dict[str, Any]:
    """加载 YAML 文件。"""
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def save_yaml(data: Dict[str, Any], path: str) -> None:
    """保存 YAML 文件，自动创建目录。"""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        yaml.dump(data, f, default_flow_style=False, allow_unicode=True, sort_keys=False)


def load_json(path: str) -> Dict[str, Any]:
    """加载 JSON 文件。"""
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(data: Dict[str, Any], path: str) -> None:
    """保存 JSON 文件，自动创建目录。"""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def resolve_path(path: str) -> str:
    """解析相对于项目根目录的路径。"""
    if os.path.isabs(path):
        return path
    return os.path.join(os.path.dirname(__file__), "..", "..", path)


# ═══════════════════════════════════════════════════════════════
# Lattice Parser
# ═══════════════════════════════════════════════════════════════

def parse_lattice(lattice_path: str) -> Dict[str, Any]:
    """解析晶格方案 YAML 文件。"""
    resolved = resolve_path(lattice_path)
    if not os.path.exists(resolved):
        logger.error(f"晶格方案文件不存在: {resolved}")
        sys.exit(1)
    return load_yaml(resolved)


def get_lattice_id(lattice: Dict[str, Any]) -> str:
    """获取晶格方案ID。"""
    return lattice.get("lattice", {}).get("id", "unknown")


def get_layers(lattice: Dict[str, Any]) -> List[Dict[str, Any]]:
    """获取所有层级定义。"""
    return lattice.get("layers", [])


def get_layer_by_number(lattice: Dict[str, Any], layer_num: int) -> Optional[Dict[str, Any]]:
    """按编号获取层级定义。"""
    for layer in get_layers(lattice):
        if layer.get("layer") == layer_num:
            return layer
    return None


def get_all_tasks(lattice: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """获取所有原子任务的扁平字典 {task_id: task_info}。"""
    tasks = {}
    for layer in get_layers(lattice):
        for task in layer.get("tasks", []):
            tasks[task["task_id"]] = {
                **task,
                "layer": layer["layer"],
                "layer_name": layer["name"],
            }
    return tasks


# ═══════════════════════════════════════════════════════════════
# Execution Order Generator (Bottom-Up)
# ═══════════════════════════════════════════════════════════════

def generate_execution_order(lattice: Dict[str, Any]) -> Dict[str, Any]:
    """
    生成逆向执行顺序。

    规则:
      1. 从最高层（最内层核心）开始
      2. 同一层内，按依赖关系排序（被依赖的先执行）
      3. 同一层内，无依赖关系的任务可并行执行
      4. 一层全部完成后，进入下一层（递减）
      5. 直到 Layer 0 完成

    返回:
      {
        "lattice_id": "...",
        "execution_order": [
          {
            "layer": 4,
            "phase": 1,
            "tasks": ["task_0001", "task_0002", "task_0003"],
            "parallel_groups": [
              ["task_0001"],
              ["task_0002", "task_0003"]   # 可并行
            ]
          },
          ...
        ]
      }
    """
    lattice_id = get_lattice_id(lattice)
    layers = get_layers(lattice)
    all_tasks = get_all_tasks(lattice)

    # 按层级从高到低排序
    sorted_layers = sorted(layers, key=lambda l: l["layer"], reverse=True)

    execution_order = []
    total_phases = len(sorted_layers)

    for phase_idx, layer in enumerate(sorted_layers):
        layer_num = layer["layer"]
        tasks = layer.get("tasks", [])

        # 拓扑排序（同层内按依赖关系）
        task_ids = [t["task_id"] for t in tasks]
        sorted_task_ids = _topological_sort(task_ids, all_tasks)

        # 分组可并行任务
        parallel_groups = _group_parallel_tasks(sorted_task_ids, all_tasks)

        execution_order.append({
            "layer": layer_num,
            "phase": phase_idx + 1,
            "total_phases": total_phases,
            "layer_name": layer.get("name", f"Layer {layer_num}"),
            "tasks": sorted_task_ids,
            "parallel_groups": parallel_groups,
            "assembly_required": True,
        })

    return {
        "lattice_id": lattice_id,
        "execution_order": execution_order,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "notes": [
            "执行方向: Bottom-Up (从核心层到外层)",
            f"总层数: {total_phases}",
            "每层完成后执行: 层组装测试 → 意图对齐检查",
            "同层内无依赖的任务可并行执行",
        ],
    }


def _topological_sort(task_ids: List[str], all_tasks: Dict[str, Dict]) -> List[str]:
    """
    同层内拓扑排序。被依赖的任务排在前面。
    使用 Kahn 算法。
    """
    # 构建依赖图
    in_degree = {tid: 0 for tid in task_ids}
    adj_list = {tid: [] for tid in task_ids}

    for tid in task_ids:
        task_info = all_tasks.get(tid, {})
        deps = task_info.get("depends_on", [])
        for dep in deps:
            if dep in task_ids:  # 只考虑同层依赖
                if dep not in adj_list:
                    adj_list[dep] = []
                adj_list[dep].append(tid)
                in_degree[tid] = in_degree.get(tid, 0) + 1

    # Kahn 算法
    queue = [tid for tid in task_ids if in_degree.get(tid, 0) == 0]
    sorted_tasks = []

    while queue:
        # 按 task_id 排序以保证确定性
        queue.sort()
        node = queue.pop(0)
        sorted_tasks.append(node)

        for neighbor in adj_list.get(node, []):
            in_degree[neighbor] -= 1
            if in_degree[neighbor] == 0:
                queue.append(neighbor)

    # 检查是否有环
    if len(sorted_tasks) != len(task_ids):
        remaining = set(task_ids) - set(sorted_tasks)
        logger.warning(f"检测到循环依赖: {remaining}")
        # 将剩余任务追加到末尾
        sorted_tasks.extend(remaining)

    return sorted_tasks


def _group_parallel_tasks(sorted_task_ids: List[str], all_tasks: Dict[str, Dict]) -> List[List[str]]:
    """
    将无依赖关系的任务分组（可并行执行）。
    同一组内的任务可以同时执行。
    """
    groups = []
    used = set()

    for tid in sorted_task_ids:
        if tid in used:
            continue

        # 找到所有可以与该任务并行的任务
        group = [tid]
        used.add(tid)

        task_info = all_tasks.get(tid, {})
        tid_deps = set(task_info.get("depends_on", []))

        for other_tid in sorted_task_ids:
            if other_tid in used:
                continue
            other_info = all_tasks.get(other_tid, {})
            other_deps = set(other_info.get("depends_on", []))

            # 如果两个任务没有相互依赖，可以并行
            if tid not in other_deps and other_tid not in tid_deps:
                group.append(other_tid)
                used.add(other_tid)

        groups.append(group)

    return groups


# ═══════════════════════════════════════════════════════════════
# Layer Assembly
# ═══════════════════════════════════════════════════════════════

def create_layer_assembly(
    lattice: Dict[str, Any],
    layer_num: int,
    task_statuses: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """
    创建层组装记录。

    参数:
      lattice: 晶格方案
      layer_num: 层级编号
      task_statuses: 任务状态字典 {task_id: status}，可选

    返回:
      层组装记录 (符合 layer_assembly.schema.json)
    """
    lattice_id = get_lattice_id(lattice)
    layer = get_layer_by_number(lattice, layer_num)

    if not layer:
        logger.error(f"层级 {layer_num} 不存在")
        return {"error": f"Layer {layer_num} not found"}

    task_statuses = task_statuses or {}

    # 构建任务列表
    tasks = []
    for task in layer.get("tasks", []):
        task_id = task["task_id"]
        tasks.append({
            "task_id": task_id,
            "name": task.get("name", ""),
            "status": task_statuses.get(task_id, "pending"),
            "provides": task.get("provides", []),
        })

    # 构建组装测试
    assembly_test_def = layer.get("assembly_test", {})
    tests = []
    for test_desc in assembly_test_def.get("tests", []):
        tests.append({
            "id": f"assembly_test_{len(tests) + 1:02d}",
            "description": test_desc,
            "result": "pending",
            "detail": None,
        })

    # 获取所有层级编号，找到下一层
    all_layers = sorted([l["layer"] for l in get_layers(lattice)], reverse=True)
    current_idx = all_layers.index(layer_num)
    next_layer = all_layers[current_idx + 1] if current_idx + 1 < len(all_layers) else None

    assembly = {
        "layer": layer_num,
        "lattice_id": lattice_id,
        "name": layer.get("name", f"Layer {layer_num}"),
        "status": "pending",
        "tasks": tasks,
        "assembly_test": {
            "name": assembly_test_def.get("name", f"Layer {layer_num} 组装测试"),
            "description": assembly_test_def.get("description", ""),
            "tests": tests,
            "overall_result": "pending",
        },
        "intent_alignment": {
            "original_goal": layer.get("description", ""),
            "verification": [
                f"所有 {len(tasks)} 个原子任务已完成",
                "组装测试全部通过",
                "接口契约与上下层匹配",
            ],
            "alignment_result": "pending",
            "gap_analysis": [],
        },
        "next_layer": next_layer,
        "started_at": None,
        "completed_at": None,
    }

    return assembly


def update_assembly_task_status(
    assembly: Dict[str, Any],
    task_id: str,
    status: str,
) -> Dict[str, Any]:
    """更新层组装中的任务状态。"""
    for task in assembly.get("tasks", []):
        if task["task_id"] == task_id:
            task["status"] = status
            break
    return assembly


def run_assembly_test(
    assembly: Dict[str, Any],
    test_results: Dict[str, str],
) -> Dict[str, Any]:
    """
    运行组装测试并更新结果。

    参数:
      assembly: 层组装记录
      test_results: {test_id: "pass"|"fail"}
    """
    for test in assembly.get("assembly_test", {}).get("tests", []):
        test_id = test["id"]
        if test_id in test_results:
            test["result"] = test_results[test_id]

    # 计算总体结果
    all_pass = all(
        t["result"] == "pass"
        for t in assembly["assembly_test"]["tests"]
    )
    assembly["assembly_test"]["overall_result"] = "pass" if all_pass else "fail"

    return assembly


def check_intent_alignment(
    assembly: Dict[str, Any],
    verification_results: Dict[str, bool],
    gap_analysis: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    检查意图对齐。

    参数:
      assembly: 层组装记录
      verification_results: {verification_item: True/False}
      gap_analysis: 差距分析列表
    """
    all_aligned = all(verification_results.values())
    assembly["intent_alignment"]["alignment_result"] = "aligned" if all_aligned else "misaligned"
    assembly["intent_alignment"]["gap_analysis"] = gap_analysis or []
    return assembly


# ═══════════════════════════════════════════════════════════════
# PCDCA Cycle Template Generator
# ═══════════════════════════════════════════════════════════════

def generate_pcdca_cycle_template(task_id: str) -> Dict[str, Any]:
    """
    生成 PCDCA 循环记录模板。

    符合 pcdca_cycle.schema.json 规范。
    """
    now = datetime.now(timezone.utc).isoformat()

    return {
        "cycle_id": f"cycle_{str(uuid.uuid4())[:8]}",
        "task_id": task_id,
        "cycle_number": 1,
        "phases": {
            "plan": {
                "blockers_identified": [],
                "plan_summary": "",
                "steps_planned": 0,
            },
            "plan_check": {
                "reviewer": "human",
                "result": "pending",
                "feedback": None,
                "reviewed_at": None,
            },
            "do": {
                "steps_executed": [],
                "artifacts_produced": [],
            },
            "check": {
                "validation_results": [],
                "result": "pending",
                "fail_reason": None,
            },
            "action": {
                "decision": "pending",
                "decision_reason": "",
                "next_cycle_plan": None,
            },
        },
        "result": "pending",
        "timestamp": {
            "started_at": now,
            "completed_at": None,
        },
    }


# ═══════════════════════════════════════════════════════════════
# Lattice Validator
# ═══════════════════════════════════════════════════════════════

def validate_lattice(lattice: Dict[str, Any]) -> Dict[str, Any]:
    """
    验证晶格方案的完整性。

    检查项:
      - 必需字段是否存在
      - 层级编号是否连续
      - 任务ID是否唯一
      - 依赖关系是否有效
      - 执行策略是否正确
    """
    lattice_id = get_lattice_id(lattice)
    errors = []
    warnings = []

    # 1. 检查必需字段
    if not lattice.get("lattice"):
        errors.append("缺少顶层 'lattice' 字段")
    if not lattice.get("intent"):
        errors.append("缺少 'intent' 字段")
    if not lattice.get("layers"):
        errors.append("缺少 'layers' 字段")
    if not lattice.get("execution_strategy"):
        errors.append("缺少 'execution_strategy' 字段")

    if errors:
        return {"valid": False, "errors": errors, "warnings": warnings}

    # 2. 检查执行策略
    strategy = lattice.get("execution_strategy", {})
    if strategy.get("direction") != "bottom_up":
        errors.append("execution_strategy.direction 必须为 'bottom_up'")
    if strategy.get("pcdca_required") is not True:
        errors.append("execution_strategy.pcdca_required 必须为 true")

    # 3. 检查层级
    layers = get_layers(lattice)
    if not layers:
        errors.append("至少需要一个层级")
    else:
        layer_numbers = [l["layer"] for l in layers]
        # 检查是否有重复层级编号
        if len(layer_numbers) != len(set(layer_numbers)):
            errors.append(f"层级编号重复: {layer_numbers}")

        # 检查层级编号是否从0开始连续
        sorted_layers = sorted(layer_numbers)
        if sorted_layers != list(range(len(sorted_layers))):
            warnings.append(f"层级编号不连续: {sorted_layers}，建议从0到{len(sorted_layers)-1}")

    # 4. 检查任务
    all_tasks = get_all_tasks(lattice)
    task_ids = list(all_tasks.keys())

    # 检查任务ID唯一性
    if len(task_ids) != len(set(task_ids)):
        errors.append("任务ID不唯一")

    # 检查依赖关系
    for tid, task_info in all_tasks.items():
        for dep in task_info.get("depends_on", []):
            if dep not in task_ids:
                warnings.append(f"任务 '{tid}' 依赖的任务 '{dep}' 不存在")

    # 5. 检查意图
    intent = lattice.get("intent", {})
    if not intent.get("user_goal"):
        errors.append("intent.user_goal 不能为空")
    if not intent.get("acceptance_criteria"):
        warnings.append("intent.acceptance_criteria 为空")

    return {
        "lattice_id": lattice_id,
        "valid": len(errors) == 0,
        "errors": errors,
        "warnings": warnings,
        "layers_count": len(layers),
        "tasks_count": len(task_ids),
    }


# ═══════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="LatticeWork 晶格引擎核心",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
子命令:
  parse             解析并显示晶格方案信息
  execution-order   生成逆向执行顺序
  assemble          创建层组装记录
  align             检查意图对齐
  pcdca-template    生成PCDCA循环记录模板
  validate          验证晶格方案完整性

示例:
  # 解析晶格方案
  python lattice/scripts/lattice_core.py parse \\
      --lattice lattice/examples/quant_trading/lattice_basis_arbitrage.yaml

  # 生成执行顺序
  python lattice/scripts/lattice_core.py execution-order \\
      --lattice lattice/examples/quant_trading/lattice_basis_arbitrage.yaml

  # 验证晶格方案
  python lattice/scripts/lattice_core.py validate \\
      --lattice lattice/examples/quant_trading/lattice_basis_arbitrage.yaml
        """,
    )
    subparsers = parser.add_subparsers(dest="command", help="子命令")

    # parse
    parse_parser = subparsers.add_parser("parse", help="解析并显示晶格方案信息")
    parse_parser.add_argument("-l", "--lattice", required=True, help="晶格方案 YAML 路径")

    # execution-order
    order_parser = subparsers.add_parser("execution-order", help="生成逆向执行顺序")
    order_parser.add_argument("-l", "--lattice", required=True, help="晶格方案 YAML 路径")
    order_parser.add_argument("-o", "--output", default="", help="输出路径")

    # assemble
    assemble_parser = subparsers.add_parser("assemble", help="创建层组装记录")
    assemble_parser.add_argument("-l", "--lattice", required=True, help="晶格方案 YAML 路径")
    assemble_parser.add_argument("--layer", type=int, required=True, help="层级编号")
    assemble_parser.add_argument("-o", "--output", default="", help="输出路径")

    # align
    align_parser = subparsers.add_parser("align", help="检查意图对齐")
    align_parser.add_argument("-l", "--lattice", required=True, help="晶格方案 YAML 路径")
    align_parser.add_argument("--layer", type=int, required=True, help="层级编号")
    align_parser.add_argument("-o", "--output", default="", help="输出路径")

    # pcdca-template
    pcdca_parser = subparsers.add_parser("pcdca-template", help="生成PCDCA循环记录模板")
    pcdca_parser.add_argument("--task-id", required=True, help="原子任务ID")
    pcdca_parser.add_argument("-o", "--output", default="", help="输出路径")

    # validate
    validate_parser = subparsers.add_parser("validate", help="验证晶格方案完整性")
    validate_parser.add_argument("-l", "--lattice", required=True, help="晶格方案 YAML 路径")

    args = parser.parse_args()

    if args.command == "parse":
        lattice = parse_lattice(args.lattice)
        lattice_id = get_lattice_id(lattice)
        layers = get_layers(lattice)
        all_tasks = get_all_tasks(lattice)

        print(f"📋 晶格方案: {lattice_id}")
        print(f"   名称: {lattice.get('lattice', {}).get('name', 'N/A')}")
        print(f"   领域: {lattice.get('lattice', {}).get('domain', 'N/A')}")
        print(f"   类型: {lattice.get('lattice', {}).get('domain_type', 'N/A')}")
        print(f"   层级数: {len(layers)}")
        print(f"   任务数: {len(all_tasks)}")
        print(f"   执行方向: {lattice.get('execution_strategy', {}).get('direction', 'N/A')}")
        print(f"   PCDCA强制: {lattice.get('execution_strategy', {}).get('pcdca_required', 'N/A')}")
        print()
        for layer in sorted(layers, key=lambda l: l["layer"], reverse=True):
            print(f"  Layer {layer['layer']}: {layer.get('name', '')}")
            print(f"    {layer.get('description', '')}")
            for task in layer.get("tasks", []):
                deps = task.get("depends_on", [])
                dep_str = f" (依赖: {', '.join(deps)})" if deps else ""
                print(f"    ├─ {task['task_id']}: {task.get('name', '')}{dep_str}")

    elif args.command == "execution-order":
        lattice = parse_lattice(args.lattice)
        order = generate_execution_order(lattice)
        output = args.output or os.path.join(RUNTIME_DIR, f"execution_order_{order['lattice_id']}.json")
        save_json(order, output)

        print(f"✅ 执行顺序已生成: {output}")
        print(f"   晶格方案: {order['lattice_id']}")
        print(f"   总层数: {len(order['execution_order'])}")
        print()
        for phase in order["execution_order"]:
            print(f"  Phase {phase['phase']}/{phase['total_phases']}: Layer {phase['layer']} ({phase['layer_name']})")
            print(f"    任务: {', '.join(phase['tasks'])}")
            print(f"    并行组: {len(phase['parallel_groups'])} 组")
            for i, group in enumerate(phase["parallel_groups"]):
                print(f"      组{i+1}: {', '.join(group)}")
            print(f"    需要组装: {'是' if phase['assembly_required'] else '否'}")
            print()

    elif args.command == "assemble":
        lattice = parse_lattice(args.lattice)
        assembly = create_layer_assembly(lattice, args.layer)
        if "error" in assembly:
            print(f"❌ {assembly['error']}")
            sys.exit(1)
        output = args.output or os.path.join(
            RUNTIME_DIR, f"assembly_layer{args.layer}_{assembly['lattice_id']}.json"
        )
        save_json(assembly, output)
        print(f"✅ 层组装记录已创建: {output}")
        print(f"   层级: Layer {assembly['layer']} ({assembly['name']})")
        print(f"   任务数: {len(assembly['tasks'])}")
        print(f"   组装测试数: {len(assembly['assembly_test']['tests'])}")
        print(f"   下一层: {assembly['next_layer']}")

    elif args.command == "align":
        lattice = parse_lattice(args.lattice)
        assembly = create_layer_assembly(lattice, args.layer)
        if "error" in assembly:
            print(f"❌ {assembly['error']}")
            sys.exit(1)
        output = args.output or os.path.join(
            RUNTIME_DIR, f"alignment_layer{args.layer}_{assembly['lattice_id']}.json"
        )
        save_json(assembly["intent_alignment"], output)
        print(f"✅ 意图对齐检查已创建: {output}")
        print(f"   层级: Layer {assembly['layer']} ({assembly['name']})")
        print(f"   原始目标: {assembly['intent_alignment']['original_goal'][:100]}...")
        print(f"   验证项: {len(assembly['intent_alignment']['verification'])} 项")

    elif args.command == "pcdca-template":
        template = generate_pcdca_cycle_template(args.task_id)
        output = args.output or os.path.join(PCDCA_LOG_DIR, f"{template['cycle_id']}.json")
        save_json(template, output)
        print(f"✅ PCDCA循环模板已生成: {output}")
        print(f"   循环ID: {template['cycle_id']}")
        print(f"   任务ID: {template['task_id']}")
        print(f"   循环次数: {template['cycle_number']}")

    elif args.command == "validate":
        lattice = parse_lattice(args.lattice)
        result = validate_lattice(lattice)
        if result["valid"]:
            print(f"✅ 晶格方案验证通过: {result['lattice_id']}")
        else:
            print(f"❌ 晶格方案验证失败: {result['lattice_id']}")
        print(f"   层级数: {result['layers_count']}")
        print(f"   任务数: {result['tasks_count']}")
        if result["errors"]:
            print(f"   错误 ({len(result['errors'])}):")
            for e in result["errors"]:
                print(f"     ❌ {e}")
        if result["warnings"]:
            print(f"   警告 ({len(result['warnings'])}):")
            for w in result["warnings"]:
                print(f"     ⚠️  {w}")

    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
