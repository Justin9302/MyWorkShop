#!/usr/bin/env python3
"""
lattice_runner.py — LatticeWork 主运行器（CLINE入口点）

这是 CLINE 执行 LatticeWork 工作流的主入口点。
它整合了 lattice_core, lattice_blocker, lattice_pcdca 三个模块，
提供完整的端到端执行流程。

执行流程:
  1. load_lattice()       → 加载晶格方案
  2. generate_order()     → 生成逆向执行顺序
  3. execute_layer()      → 逐层执行（从核心层到外层）
  4. execute_task()       → 执行原子任务（PCDCA循环）
  5. assemble_layer()     → 层组装测试
  6. align_intent()       → 意图对齐检查
  7. next_layer()         → 进入下一层

用法:
  # 完整执行晶格方案
  python lattice/scripts/lattice_runner.py run \\
      --lattice lattice/examples/quant_trading/lattice_basis_arbitrage.yaml

  # 仅执行指定层
  python lattice/scripts/lattice_runner.py run-layer \\
      --lattice lattice/examples/quant_trading/lattice_basis_arbitrage.yaml \\
      --layer 4

  # 仅执行指定任务
  python lattice/scripts/lattice_runner.py run-task \\
      --lattice lattice/examples/quant_trading/lattice_basis_arbitrage.yaml \\
      --task-id task_0001

  # 查看执行状态
  python lattice/scripts/lattice_runner.py status \\
      --lattice lattice/examples/quant_trading/lattice_basis_arbitrage.yaml

  # 生成CLINE执行指令
  python lattice/scripts/lattice_runner.py cline-instructions \\
      --lattice lattice/examples/quant_trading/lattice_basis_arbitrage.yaml
"""

import argparse
import json
import logging
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

# 导入 LatticeWork 模块
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from scripts.lattice_core import (
    parse_lattice, get_lattice_id, get_layers, get_layer_by_number,
    get_all_tasks, generate_execution_order, create_layer_assembly,
    validate_lattice, generate_pcdca_cycle_template,
)
from scripts.lattice_blocker import (
    register_blocker, get_blockers_by_task, generate_blocker_report,
)
from scripts.lattice_pcdca import (
    start_cycle, record_plan, record_plan_check, record_do_step,
    record_check, record_action, get_cycle_status, get_task_cycles,
)
from scripts.lattice_checkpoint import (
    create_checkpoint, get_latest_checkpoint, generate_resume_prompt,
    resume_from_checkpoint, list_checkpoints,
)

# ═══════════════════════════════════════════════════════════════
# Constants
# ═══════════════════════════════════════════════════════════════

LATTICE_DIR = os.path.join(os.path.dirname(__file__), "..")
RUNTIME_DIR = os.path.join(LATTICE_DIR, "lattice_runtime")
CURRENT_LATTICE_PATH = os.path.join(RUNTIME_DIR, "current_lattice.yaml")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("lattice_runner")


# ═══════════════════════════════════════════════════════════════
# Execution State Management
# ═══════════════════════════════════════════════════════════════

def _state_path(lattice_id: str) -> str:
    """获取执行状态文件路径。"""
    return os.path.join(RUNTIME_DIR, f"state_{lattice_id}.json")


def load_state(lattice_id: str) -> Dict[str, Any]:
    """加载执行状态。"""
    path = _state_path(lattice_id)
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {
        "lattice_id": lattice_id,
        "status": "created",
        "current_layer": None,
        "current_task": None,
        "current_cycle": None,
        "completed_layers": [],
        "completed_tasks": [],
        "layer_assemblies": {},
        "started_at": None,
        "updated_at": None,
    }


def save_state(state: Dict[str, Any]) -> None:
    """保存执行状态。"""
    state["updated_at"] = datetime.now(timezone.utc).isoformat()
    os.makedirs(RUNTIME_DIR, exist_ok=True)
    with open(_state_path(state["lattice_id"]), "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)


def set_current_lattice(lattice_path: str) -> None:
    """设置当前正在执行的晶格方案。"""
    os.makedirs(RUNTIME_DIR, exist_ok=True)
    lattice = parse_lattice(lattice_path)
    with open(CURRENT_LATTICE_PATH, "w", encoding="utf-8") as f:
        yaml.dump(lattice, f, default_flow_style=False, allow_unicode=True, sort_keys=False)
    logger.info(f"当前晶格方案已设置: {lattice_path}")


# ═══════════════════════════════════════════════════════════════
# Task Execution (PCDCA Loop)
# ═══════════════════════════════════════════════════════════════

def execute_task(
    lattice: Dict[str, Any],
    task_id: str,
    state: Dict[str, Any],
    max_cycles: int = 5,
) -> Dict[str, Any]:
    """
    执行单个原子任务（PCDCA循环）。

    这是 CLINE 执行的核心逻辑。每个任务通过 PCDCA 循环完成：
      P → C(HITL) → D → C → A

    参数:
      lattice: 晶格方案
      task_id: 任务ID
      state: 当前执行状态
      max_cycles: 最大PCDCA循环次数

    返回:
      任务执行结果
    """
    all_tasks = get_all_tasks(lattice)
    task_info = all_tasks.get(task_id)

    if not task_info:
        logger.error(f"任务不存在: {task_id}")
        return {"task_id": task_id, "status": "fail", "error": "Task not found"}

    logger.info(f"开始执行任务: {task_id} ({task_info.get('name', '')})")

    # 检查是否有阻塞点
    blockers = get_blockers_by_task(task_id)
    blocking_blockers = [b for b in blockers if b["severity"] == "blocking" and b["status"] == "open"]

    if blocking_blockers:
        logger.warning(f"任务 {task_id} 被阻塞: {len(blocking_blockers)} 个阻塞级阻塞点")
        return {
            "task_id": task_id,
            "status": "blocked",
            "blockers": blocking_blockers,
            "message": "存在未解决的阻塞级阻塞点",
        }

    # PCDCA 循环
    cycle_number = 1
    while cycle_number <= max_cycles:
        logger.info(f"PCDCA 循环 #{cycle_number}/{max_cycles}")

        # 1. P: Plan
        cycle = start_cycle(task_id, cycle_number)
        state["current_cycle"] = cycle["cycle_id"]
        save_state(state)

        # Plan 阶段由 CLINE 自主完成（识别阻塞 + 制定计划）
        # 这里生成 Plan 阶段的占位记录
        plan_summary = f"执行任务: {task_info.get('name', '')}"
        steps_planned = len(task_info.get("depends_on", [])) + 1
        record_plan(cycle["cycle_id"], plan_summary, steps_planned)

        # 2. C(HITL): Plan-Check — 需要人工审核
        # 在实际执行中，CLINE 会展示计划给用户，等待用户确认
        # 这里标记为 pending，由 CLINE 在实际执行时更新
        logger.info(f"等待人工审核计划 (cycle: {cycle['cycle_id']})")

        # 3. D: Do — 由 CLINE 执行具体步骤
        # 4. C: Check — 验证产物
        # 5. A: Action — 决策

        # 如果达到最大循环次数，标记为 fail
        if cycle_number >= max_cycles:
            record_action(
                cycle["cycle_id"],
                "retry",
                f"达到最大循环次数 ({max_cycles})",
                "需要人工介入",
            )
            return {
                "task_id": task_id,
                "status": "fail",
                "cycles": cycle_number,
                "message": f"达到最大PCDCA循环次数 ({max_cycles})",
            }

        cycle_number += 1

    return {
        "task_id": task_id,
        "status": "pending",
        "message": "等待CLINE执行",
    }


# ═══════════════════════════════════════════════════════════════
# Layer Execution
# ═══════════════════════════════════════════════════════════════

def execute_layer(
    lattice: Dict[str, Any],
    layer_num: int,
    state: Dict[str, Any],
) -> Dict[str, Any]:
    """
    执行指定层级的所有原子任务。

    流程:
      1. 获取该层所有任务
      2. 按依赖关系排序
      3. 逐个执行任务（PCDCA循环）
      4. 所有任务完成后执行层组装
      5. 执行意图对齐检查
    """
    layer = get_layer_by_number(lattice, layer_num)
    if not layer:
        logger.error(f"层级不存在: Layer {layer_num}")
        return {"layer": layer_num, "status": "fail", "error": "Layer not found"}

    logger.info(f"开始执行 Layer {layer_num}: {layer.get('name', '')}")
    state["current_layer"] = layer_num
    save_state(state)

    # 获取该层所有任务
    tasks = layer.get("tasks", [])
    all_tasks = get_all_tasks(lattice)

    # 按依赖关系排序
    task_ids = [t["task_id"] for t in tasks]
    from scripts.lattice_core import _topological_sort
    sorted_task_ids = _topological_sort(task_ids, all_tasks)

    # 逐个执行任务
    task_results = []
    all_pass = True

    for task_id in sorted_task_ids:
        # 检查依赖是否全部完成
        task_info = all_tasks.get(task_id, {})
        deps = task_info.get("depends_on", [])
        for dep in deps:
            if dep in task_ids:  # 同层依赖
                dep_result = next(
                    (r for r in task_results if r["task_id"] == dep),
                    None,
                )
                if dep_result and dep_result["status"] != "pass":
                    logger.error(f"任务 {task_id} 的依赖 {dep} 未通过")
                    task_results.append({
                        "task_id": task_id,
                        "status": "blocked",
                        "message": f"依赖任务 {dep} 未通过",
                    })
                    all_pass = False
                    continue

        # 执行任务
        result = execute_task(lattice, task_id, state)
        task_results.append(result)

        if result["status"] != "pass":
            all_pass = False

        # 更新状态
        state["completed_tasks"].append(task_id)
        save_state(state)

    # 创建层组装记录
    task_statuses = {r["task_id"]: r["status"] for r in task_results}
    assembly = create_layer_assembly(lattice, layer_num, task_statuses)

    if all_pass:
        assembly["status"] = "completed"
        assembly["started_at"] = state.get("started_at")
        assembly["completed_at"] = datetime.now(timezone.utc).isoformat()
    else:
        assembly["status"] = "failed"

    state["layer_assemblies"][str(layer_num)] = assembly
    state["completed_layers"].append(layer_num)
    save_state(state)

    return {
        "layer": layer_num,
        "name": layer.get("name", ""),
        "status": "completed" if all_pass else "failed",
        "tasks": task_results,
        "assembly": assembly,
    }


# ═══════════════════════════════════════════════════════════════
# Full Execution
# ═══════════════════════════════════════════════════════════════

def run_full_lattice(lattice_path: str) -> Dict[str, Any]:
    """
    完整执行晶格方案。

    流程:
      1. 验证晶格方案
      2. 生成执行顺序
      3. 从核心层到外层逐层执行
      4. 每层完成后执行层组装和意图对齐
    """
    lattice = parse_lattice(lattice_path)
    lattice_id = get_lattice_id(lattice)

    # 验证
    validation = validate_lattice(lattice)
    if not validation["valid"]:
        logger.error(f"晶格方案验证失败: {validation['errors']}")
        return {"status": "fail", "errors": validation["errors"]}

    # 设置当前晶格方案
    set_current_lattice(lattice_path)

    # 初始化状态
    state = load_state(lattice_id)
    state["status"] = "running"
    state["started_at"] = datetime.now(timezone.utc).isoformat()
    save_state(state)

    # 生成执行顺序
    order = generate_execution_order(lattice)
    logger.info(f"执行顺序已生成: {len(order['execution_order'])} 个阶段")

    # 逐层执行（从核心层到外层）
    results = []
    for phase in order["execution_order"]:
        layer_num = phase["layer"]
        logger.info(f"=== Phase {phase['phase']}/{phase['total_phases']}: Layer {layer_num} ({phase['layer_name']}) ===")

        layer_result = execute_layer(lattice, layer_num, state)
        results.append(layer_result)

        if layer_result["status"] == "failed":
            logger.error(f"Layer {layer_num} 执行失败")
            state["status"] = "failed"
            save_state(state)
            return {
                "status": "failed",
                "failed_layer": layer_num,
                "results": results,
            }

    # 全部完成
    state["status"] = "completed"
    save_state(state)

    return {
        "status": "completed",
        "lattice_id": lattice_id,
        "total_layers": len(order["execution_order"]),
        "results": results,
    }


# ═══════════════════════════════════════════════════════════════
# CLINE Instructions Generator
# ═══════════════════════════════════════════════════════════════

def generate_cline_instructions(lattice_path: str) -> Dict[str, Any]:
    """
    生成 CLINE 执行指令。

    这些指令告诉 CLINE 如何执行 LatticeWork 工作流。
    包括每个步骤的具体动作、需要读取的文件、需要执行的命令等。
    """
    lattice = parse_lattice(lattice_path)
    lattice_id = get_lattice_id(lattice)
    order = generate_execution_order(lattice)

    instructions = {
        "title": f"LatticeWork 执行指令: {lattice_id}",
        "lattice_path": lattice_path,
        "overview": f"执行晶格方案 '{lattice_id}'，共 {len(order['execution_order'])} 层",
        "execution_flow": [
            {
                "step": 1,
                "action": "validate_lattice",
                "description": "验证晶格方案完整性",
                "command": f"python lattice/scripts/lattice_core.py validate --lattice {lattice_path}",
            },
            {
                "step": 2,
                "action": "generate_execution_order",
                "description": "生成逆向执行顺序",
                "command": f"python lattice/scripts/lattice_core.py execution-order --lattice {lattice_path}",
            },
            {
                "step": 3,
                "action": "start_execution",
                "description": "开始执行晶格方案",
                "command": f"python lattice/scripts/lattice_runner.py run --lattice {lattice_path}",
            },
        ],
        "layer_execution": [],
        "pcdca_protocol": {
            "description": "每个原子任务执行 PCDCA 循环",
            "phases": [
                {
                    "phase": "P (Plan)",
                    "cline_action": "识别阻塞点 + 制定执行计划",
                    "command": "python lattice/scripts/lattice_pcdca.py plan --cycle-id {cycle_id} --plan-summary \"...\" --steps-planned N",
                    "human_interaction": "展示计划给用户",
                },
                {
                    "phase": "C (Check-HITL)",
                    "cline_action": "等待用户审核计划",
                    "command": "python lattice/scripts/lattice_pcdca.py plan-check --cycle-id {cycle_id} --result pass/fail",
                    "human_interaction": "用户审核并确认",
                },
                {
                    "phase": "D (Do)",
                    "cline_action": "执行计划中的步骤（write_to_file/execute_command等）",
                    "command": "python lattice/scripts/lattice_pcdca.py do --cycle-id {cycle_id} --step-id {step_id} --action {action} --status success",
                    "human_interaction": "无",
                },
                {
                    "phase": "C (Check)",
                    "cline_action": "验证产物是否符合验收标准",
                    "command": "python lattice/scripts/lattice_pcdca.py check --cycle-id {cycle_id} --result pass/fail",
                    "human_interaction": "仅失败时通知用户",
                },
                {
                    "phase": "A (Action)",
                    "cline_action": "决策: proceed/retry/block/escalate/skip",
                    "command": "python lattice/scripts/lattice_pcdca.py action --cycle-id {cycle_id} --decision proceed",
                    "human_interaction": "仅block/escalate时通知用户",
                },
            ],
        },
        "layer_assembly_protocol": {
            "description": "每层完成后执行层组装",
            "steps": [
                "1. 验证该层所有任务状态为 pass",
                "2. 运行组装测试",
                "3. 检查意图对齐",
                "4. 记录层组装结果",
                "5. 进入下一层",
            ],
            "command": "python lattice/scripts/lattice_core.py assemble --lattice {lattice_path} --layer {layer_num}",
        },
        "blocker_protocol": {
            "description": "阻塞点处理",
            "register": "python lattice/scripts/lattice_blocker.py register --type discovered --description \"...\" --severity blocking --affected-tasks task_id",
            "resolve": "python lattice/scripts/lattice_blocker.py resolve --blocker-id {blocker_id} --resolution \"...\"",
            "escalate": "python lattice/scripts/lattice_blocker.py escalate --blocker-id {blocker_id} --escalate-to human",
        },
        "notes": [
            "CLINE 应按照 execution_flow 的顺序执行",
            "每个原子任务必须完成完整的 PCDCA 循环",
            "Plan 阶段必须展示给用户审核（Human-in-the-loop）",
            "Check 阶段失败时自动回退到 Plan 阶段",
            "阻塞级阻塞点必须升级到人工处理",
            "每层完成后必须执行层组装和意图对齐",
        ],
    }

    # 添加每层的执行指令
    for phase in order["execution_order"]:
        layer_instruction = {
            "layer": phase["layer"],
            "name": phase["layer_name"],
            "phase": f"{phase['phase']}/{phase['total_phases']}",
            "tasks": [],
        }
        for task_id in phase["tasks"]:
            task_info = get_all_tasks(lattice).get(task_id, {})
            layer_instruction["tasks"].append({
                "task_id": task_id,
                "name": task_info.get("name", ""),
                "pcdca_required": True,
                "start_command": f"python lattice/scripts/lattice_pcdca.py start --task-id {task_id}",
            })
        instructions["layer_execution"].append(layer_instruction)

    return instructions


# ═══════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="LatticeWork 主运行器（CLINE入口点）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
子命令:
  run                 完整执行晶格方案
  run-layer           仅执行指定层
  run-task            仅执行指定任务
  status              查看执行状态
  cline-instructions  生成CLINE执行指令

示例:
  # 完整执行
  python lattice/scripts/lattice_runner.py run \\
      --lattice lattice/examples/quant_trading/lattice_basis_arbitrage.yaml

  # 生成CLINE指令
  python lattice/scripts/lattice_runner.py cline-instructions \\
      --lattice lattice/examples/quant_trading/lattice_basis_arbitrage.yaml
        """,
    )
    subparsers = parser.add_subparsers(dest="command", help="子命令")

    # run
    run_parser = subparsers.add_parser("run", help="完整执行晶格方案")
    run_parser.add_argument("-l", "--lattice", required=True, help="晶格方案 YAML 路径")
    run_parser.add_argument("-o", "--output", default="", help="输出路径")

    # run-layer
    rl_parser = subparsers.add_parser("run-layer", help="仅执行指定层")
    rl_parser.add_argument("-l", "--lattice", required=True, help="晶格方案 YAML 路径")
    rl_parser.add_argument("--layer", type=int, required=True, help="层级编号")
    rl_parser.add_argument("-o", "--output", default="", help="输出路径")

    # run-task
    rt_parser = subparsers.add_parser("run-task", help="仅执行指定任务")
    rt_parser.add_argument("-l", "--lattice", required=True, help="晶格方案 YAML 路径")
    rt_parser.add_argument("--task-id", required=True, help="任务ID")
    rt_parser.add_argument("-o", "--output", default="", help="输出路径")

    # status
    status_parser = subparsers.add_parser("status", help="查看执行状态")
    status_parser.add_argument("-l", "--lattice", required=True, help="晶格方案 YAML 路径")

    # cline-instructions
    ci_parser = subparsers.add_parser("cline-instructions", help="生成CLINE执行指令")
    ci_parser.add_argument("-l", "--lattice", required=True, help="晶格方案 YAML 路径")
    ci_parser.add_argument("-o", "--output", default="", help="输出路径")

    # resume (断点续传)
    resume_parser = subparsers.add_parser("resume", help="从检查点恢复执行")
    resume_parser.add_argument("--checkpoint-id", help="检查点ID（默认使用最新）")
    resume_parser.add_argument("-p", "--prompt-only", action="store_true", help="仅生成恢复提示词，不执行")

    # checkpoint
    cp_parser = subparsers.add_parser("checkpoint", help="管理检查点")
    cp_parser.add_argument("action", choices=["create", "list", "latest", "update"],
                          help="检查点操作")
    cp_parser.add_argument("-n", "--lattice", help="晶格方案名称（create时必需）")
    cp_parser.add_argument("-s", "--section", help="最后完成的章节（create时必需）")
    cp_parser.add_argument("--next-section", help="下一个要执行的章节（create时必需）")
    cp_parser.add_argument("--completed", nargs="*", default=[], help="已完成的章节列表")
    cp_parser.add_argument("-f", "--file", help="目标输出文件路径")
    cp_parser.add_argument("--lines", type=int, help="已写入的总行数")
    cp_parser.add_argument("--last-line", default="", help="最后写入行的内容")
    cp_parser.add_argument("--total", type=int, default=0, help="总章节数")
    cp_parser.add_argument("-m", "--memento", default="", help="上下文记忆摘要")
    cp_parser.add_argument("--checkpoint-id", help="检查点ID（update时必需）")

    args = parser.parse_args()

    if args.command == "run":
        result = run_full_lattice(args.lattice)
        output = args.output or os.path.join(
            RUNTIME_DIR, f"run_result_{result.get('lattice_id', 'unknown')}.json"
        )
        os.makedirs(os.path.dirname(output), exist_ok=True)
        with open(output, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2, ensure_ascii=False)

        if result["status"] == "completed":
            print(f"✅ 晶格方案执行完成")
            print(f"   总层数: {result['total_layers']}")
            for r in result["results"]:
                status_icon = "✅" if r["status"] == "completed" else "❌"
                print(f"   {status_icon} Layer {r['layer']} ({r['name']}): {r['status']}")
        else:
            print(f"❌ 晶格方案执行失败")
            if "failed_layer" in result:
                print(f"   失败层: Layer {result['failed_layer']}")
            if "errors" in result:
                for e in result["errors"]:
                    print(f"   ❌ {e}")

    elif args.command == "run-layer":
        lattice = parse_lattice(args.lattice)
        lattice_id = get_lattice_id(lattice)
        state = load_state(lattice_id)
        result = execute_layer(lattice, args.layer, state)
        output = args.output or os.path.join(
            RUNTIME_DIR, f"layer_result_{args.layer}_{lattice_id}.json"
        )
        with open(output, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2, ensure_ascii=False)

        status_icon = "✅" if result["status"] == "completed" else "❌"
        print(f"{status_icon} Layer {args.layer} 执行结果: {result['status']}")
        print(f"   任务数: {len(result.get('tasks', []))}")
        for t in result.get("tasks", []):
            t_icon = "✅" if t["status"] == "pass" else "❌"
            print(f"   {t_icon} {t['task_id']}: {t['status']}")

    elif args.command == "run-task":
        lattice = parse_lattice(args.lattice)
        lattice_id = get_lattice_id(lattice)
        state = load_state(lattice_id)
        result = execute_task(lattice, args.task_id, state)
        output = args.output or os.path.join(
            RUNTIME_DIR, f"task_result_{args.task_id}_{lattice_id}.json"
        )
        with open(output, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2, ensure_ascii=False)

        status_icon = {
            "pass": "✅", "fail": "❌", "blocked": "⛔", "pending": "⏳",
        }
        print(f"{status_icon.get(result['status'], '❓')} 任务 {args.task_id} 执行结果: {result['status']}")
        if "message" in result:
            print(f"   消息: {result['message']}")

    elif args.command == "status":
        lattice = parse_lattice(args.lattice)
        lattice_id = get_lattice_id(lattice)
        state = load_state(lattice_id)

        print(f"📋 执行状态: {lattice_id}")
        print(f"   状态: {state['status']}")
        print(f"   当前层: {state['current_layer']}")
        print(f"   当前任务: {state['current_task']}")
        print(f"   已完成层: {len(state['completed_layers'])} 个")
        print(f"   已完成任务: {len(state['completed_tasks'])} 个")
        print(f"   开始时间: {state.get('started_at', 'N/A')}")
        print(f"   更新时间: {state.get('updated_at', 'N/A')}")

        # 显示阻塞点报告
        blocker_report = generate_blocker_report()
        if blocker_report["open_count"] > 0:
            print(f"\n   ⚠️  开放阻塞点: {blocker_report['open_count']} 个")
        if blocker_report["blocking_count"] > 0:
            print(f"   🚫 阻塞级阻塞点: {blocker_report['blocking_count']} 个")

    elif args.command == "cline-instructions":
        instructions = generate_cline_instructions(args.lattice)
        output = args.output or os.path.join(
            RUNTIME_DIR, f"cline_instructions_{instructions.get('title', 'unknown').split(':')[1].strip()}.json"
        )
        with open(output, "w", encoding="utf-8") as f:
            json.dump(instructions, f, indent=2, ensure_ascii=False)

        print(f"✅ CLINE执行指令已生成: {output}")
        print(f"   晶格方案: {instructions['title']}")
        print(f"   总层数: {len(instructions['layer_execution'])}")
        print(f"   总任务数: {sum(len(l['tasks']) for l in instructions['layer_execution'])}")
        print()
        print("📋 执行流程:")
        for step in instructions["execution_flow"]:
            print(f"   {step['step']}. {step['description']}")
            print(f"      命令: {step['command']}")
        print()
        print("📋 PCDCA协议:")
        for phase in instructions["pcdca_protocol"]["phases"]:
            print(f"   {phase['phase']}: {phase['cline_action']}")
            print(f"      命令: {phase['command']}")
        print()
        print("📋 层执行顺序:")
        for layer in instructions["layer_execution"]:
            print(f"   Phase {layer['phase']}: Layer {layer['layer']} ({layer['name']})")
            print(f"      任务: {len(layer['tasks'])} 个")

    elif args.command == "resume":
        if args.prompt_only:
            prompt = generate_resume_prompt(args.checkpoint_id)
            print(prompt)
        else:
            result = resume_from_checkpoint(args.checkpoint_id)
            if result["status"] == "error":
                print(f"❌ {result['message']}")
            else:
                print(f"✅ 恢复就绪")
                print(f"   下一步: {result['next_section']}")
                print(f"   最后完成: {result['last_completed']}")
                print()
                print("=" * 60)
                print("📋 恢复提示词（复制到新对话中使用）:")
                print("=" * 60)
                print(result["resume_prompt"])
                print("=" * 60)
                if result.get("file_tail"):
                    print()
                    print("📄 目标文件末尾内容:")
                    print(result["file_tail"])

    elif args.command == "checkpoint":
        if args.action == "create":
            if not all([args.lattice, args.section, args.next_section, args.file]):
                print("❌ create 需要 --lattice, --section, --next-section, --file 参数")
                sys.exit(1)
            cp = create_checkpoint(
                lattice_name=args.lattice,
                last_completed_section=args.section,
                next_section=args.next_section,
                completed_sections=args.completed,
                target_file=args.file,
                total_lines_written=args.lines or 0,
                last_line_content=args.last_line,
                context_memento=args.memento,
                total_sections=args.total,
            )
            print(f"✅ 检查点已创建: {cp['checkpoint_id']}")
            print(f"   最后完成: {cp['last_completed_section']}")
            print(f"   下一步: {cp['next_section']}")
            print(f"   文件: {cp['file_status']['target_file']} ({cp['file_status']['total_lines_written']} 行)")

        elif args.action == "list":
            checkpoints = list_checkpoints()
            if not checkpoints:
                print("📭 没有找到检查点")
            else:
                print(f"📋 检查点列表 ({len(checkpoints)} 个):")
                for cp in checkpoints:
                    print(f"   [{cp['status']}] {cp['checkpoint_id']}")
                    print(f"       晶格: {cp['lattice_name']}")
                    print(f"       进度: {cp['last_completed_section']} → {cp['next_section']}")
                    print(f"       文件: {cp['file']} ({cp['lines']} 行)")
                    print()

        elif args.action == "latest":
            cp = get_latest_checkpoint()
            if cp:
                print(f"📌 最新检查点: {cp['checkpoint_id']}")
                print(f"   晶格: {cp['lattice_name']}")
                print(f"   时间: {cp['timestamp']}")
                print(f"   进度: {cp['last_completed_section']} → {cp['next_section']}")
                print(f"   文件: {cp['file_status']['target_file']} ({cp['file_status']['total_lines_written']} 行)")
                print(f"   记忆: {cp.get('context_memento', '无')[:100]}...")
            else:
                print("📭 没有找到检查点")

        elif args.action == "update":
            if not args.checkpoint_id:
                print("❌ update 需要 --checkpoint-id 参数")
                sys.exit(1)
            updates = {}
            if args.section:
                updates["last_completed_section"] = args.section
            if args.next_section:
                updates["next_section"] = args.next_section
            if args.lines is not None:
                updates["file_status"] = {"total_lines_written": args.lines}
            if args.memento:
                updates["context_memento"] = args.memento
            from scripts.lattice_checkpoint import update_checkpoint as _update_cp
            result = _update_cp(args.checkpoint_id, updates)
            if result:
                print(f"✅ 检查点已更新: {args.checkpoint_id}")
            else:
                print(f"❌ 检查点不存在: {args.checkpoint_id}")

    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
