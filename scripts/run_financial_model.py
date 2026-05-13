#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════════════════════╗
║  run_financial_model.py - 财务模型运行入口                                 ║
║                                                                              ║
║  职责：                                                                      ║
║  1. 读取 project_config.yaml                                                ║
║  2. 根据 technology_type 加载对应的交易策略                                  ║
║  3. 运行交易策略，输出加权平均电价和等效小时数                               ║
║  4. 将策略输出注入 config，传递给 financial_model_engine.py                  ║
║  5. 运行引擎，输出财务指标                                                   ║
║                                                                              ║
║  用法：                                                                      ║
║      python3 scripts/run_financial_model.py                                 ║
║          --config OUTPUT/项目名/project_config.yaml                         ║
║          --output OUTPUT/项目名/outputs/                                     ║
║                                                                              ║
║  注意：                                                                      ║
║      financial_model_engine.py 是文件锁定的，此文件不修改引擎。              ║
║      交易策略层在 scripts/trading/ 下，可扩展不修改引擎。                    ║
║                                                                              ║
╚══════════════════════════════════════════════════════════════════════════════╝
"""

import json
import os
import sys
import argparse
from pathlib import Path

# 将项目根目录加入 Python 路径
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.trading import run_strategy
from scripts.financial_model_engine import run_scenario, run_sensitivity_analysis, generate_summary_report


def main():
    parser = argparse.ArgumentParser(description="财务模型运行入口（交易策略 + 财务引擎）")
    parser.add_argument("--config", required=True, help="项目参数配置文件路径 (project_config.yaml)")
    parser.add_argument("--output", required=True, help="输出目录路径")
    args = parser.parse_args()

    config_path = Path(args.config)
    output_dir = Path(args.output)

    if not config_path.exists():
        print(f"错误: 配置文件不存在: {config_path}")
        sys.exit(1)

    output_dir.mkdir(parents=True, exist_ok=True)

    # 加载配置
    import yaml
    with open(config_path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    # 获取项目名称
    proj_name = "未命名"
    if "project" in config and isinstance(config["project"], dict):
        proj_name = config["project"].get("name", "未命名")
    else:
        proj_name = config.get("project_name", "未命名")
    print(f"加载项目配置: {proj_name}")

    # 获取技术类型
    tech_type = config.get("project", {}).get("technology_type", "solar")
    print(f"技术类型: {tech_type}")

    # ── 步骤0: 自动加载外部条件约束（如启用） ──
    ec_config = _get_external_constraints_config(config)
    if ec_config.get("enabled", False):
        print("检测到外部条件约束已启用，正在加载约束引擎...")
        try:
            from scripts.constraint_engine import ConstraintEngine
            engine = ConstraintEngine(ec_config.get("constraint_file", None))
            year = ec_config.get("assessment_year", 2030)
            region = ec_config.get("region", "NSW")

            # 构建手动覆盖
            manual_overrides = {}
            for key in ["bess_capacity_addition_gw", "construction_cost_escalation_pct",
                        "grid_connection_cost_premium_pct", "fcas_price_decline_pct"]:
                if key in ec_config and ec_config[key] != 0:
                    manual_overrides[key] = ec_config[key]

            constraint_result = engine.solve(year=year, region=region, manual_overrides=manual_overrides)
            overrides = constraint_result.get("overrides", {})

            if overrides:
                print(f"约束引擎推演完成，应用 {len(overrides)} 个参数覆盖:")
                for key, value in overrides.items():
                    print(f"  {key} = {value}")
                config = _apply_overrides(config, overrides)

                # 保存约束报告
                report = engine.generate_report(constraint_result)
                report_path = output_dir / "constraint_report.md"
                with open(report_path, "w", encoding="utf-8") as f:
                    f.write(report)
                print(f"约束分析报告已保存: {report_path}")
            else:
                print("约束引擎未产生覆盖值，使用原始配置")
        except Exception as e:
            print(f"⚠️ 约束引擎加载失败: {e}")
            print("   将跳过约束调整，使用原始配置继续运行")
    else:
        print("外部条件约束未启用（在 project_config.yaml 中设置 external_constraints.enabled: true 可启用）")

    # ── 步骤1: 运行交易策略 ──
    print("运行交易策略...")
    strategy_result = run_strategy(config)

    print(f"  加权平均电价: ${strategy_result['weighted_avg_price']:.4f}/kWh")
    print(f"  等效年利用小时数: {strategy_result['effective_hours']:.0f}h")
    print(f"  年上网电量: {strategy_result['annual_energy_kwh']/1e6:.2f}GWh")
    if strategy_result.get("bess_cycles", 0) > 0:
        print(f"  BESS年循环次数: {strategy_result['bess_cycles']:.0f}")
    if strategy_result.get("curtailment_kwh", 0) > 0:
        curt_pct = strategy_result["curtailment_kwh"] / max(strategy_result["annual_energy_kwh"], 1) * 100
        print(f"  弃电率: {curt_pct:.1f}%")

    # ── 步骤2: 将策略输出注入 config ──
    # 确保 revenue 部分存在
    if "revenue" not in config:
        config["revenue"] = {}
    config["revenue"]["ppa_price_per_kwh"] = strategy_result["weighted_avg_price"]
    config["revenue"]["annual_generation_kwh"] = strategy_result["annual_energy_kwh"]
    config["revenue"]["equivalent_hours"] = strategy_result["effective_hours"]

    # 确保 technical 部分存在
    if "technical" not in config:
        config["technical"] = {}
    config["technical"]["equivalent_hours"] = strategy_result["effective_hours"]
    config["technical"]["degradation_rate"] = strategy_result.get("degradation_rate", 0.005)

    # 保存策略输出到文件（用于审计）
    strategy_output_path = output_dir / "trading_strategy_output.json"
    with open(strategy_output_path, "w", encoding="utf-8") as f:
        # 移除 trading_log（太大）
        output_for_save = {k: v for k, v in strategy_result.items() if k != "trading_log"}
        json.dump(output_for_save, f, indent=2, ensure_ascii=False, default=str)
    print(f"交易策略输出已保存: {strategy_output_path}")

    # ── 步骤3: 运行财务引擎 ──
    print("运行财务模型引擎...")
    base_result = run_scenario(config)

    # 运行多情景分析
    scenario_results = {}
    scenarios = config.get("scenarios", {})
    if scenarios:
        print(f"运行 {len(scenarios)} 个情景分析...")
        for scenario_name, scenario_overrides in scenarios.items():
            merged = _deep_merge(config, scenario_overrides)
            scenario_results[scenario_name] = run_scenario(merged)

    # 运行敏感性分析
    print("运行敏感性分析...")
    sensitivity_results = run_sensitivity_analysis(config)

    # ── 步骤4: 生成报告 ──
    print("生成报告...")
    report = generate_summary_report(config, base_result, scenario_results, sensitivity_results)

    # 输出结果
    results_path = output_dir / "financial_results.json"
    with open(results_path, "w", encoding="utf-8") as f:
        json.dump({
            "trading_strategy": {k: v for k, v in strategy_result.items() if k != "trading_log"},
            "base_result": base_result,
            "scenario_results": scenario_results,
            "sensitivity_results": sensitivity_results,
        }, f, indent=2, ensure_ascii=False, default=str)
    print(f"结构化结果已保存: {results_path}")

    summary_path = output_dir / "financial_summary.md"
    with open(summary_path, "w", encoding="utf-8") as f:
        f.write(report)
    print(f"摘要报告已保存: {summary_path}")

    print("完成!")


def _deep_merge(base, override):
    """深度合并两个字典"""
    result = {}
    for key in base:
        if key in override:
            if isinstance(base[key], dict) and isinstance(override[key], dict):
                result[key] = _deep_merge(base[key], override[key])
            else:
                result[key] = override[key]
        else:
            result[key] = base[key]
    for key in override:
        if key not in base:
            result[key] = override[key]
    return result


def _get_external_constraints_config(config):
    """
    从配置中提取外部约束声明。

    支持两种格式：
    1. 顶层 external_constraints 区块（模板格式）
    2. project.external_constraints 嵌套格式
    """
    ec = config.get("external_constraints", {})
    if not ec:
        project = config.get("project", {})
        ec = project.get("external_constraints", {})
    return ec


def _apply_overrides(config, overrides):
    """
    将约束覆盖值注入 config。

    支持点号分隔的路径语法，如 "revenue.ppa_price_per_kwh"
    会递归创建/更新嵌套字典。
    """
    import copy
    config = copy.deepcopy(config)

    for key_path, value in overrides.items():
        parts = key_path.split(".")
        current = config
        for part in parts[:-1]:
            if part not in current:
                current[part] = {}
            current = current[part]
        current[parts[-1]] = value

    return config


if __name__ == "__main__":
    main()
