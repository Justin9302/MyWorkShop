#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════════════════════╗
║  run_with_constraints.py — 带外部条件约束的财务模型运行入口                ║
║                                                                              ║
║  职责：                                                                      ║
║  1. 读取 project_config.yaml                                                ║
║  2. 如果配置中启用了 external_constraints，调用约束引擎推演参数覆盖值       ║
║  3. 将约束覆盖值注入 config                                                ║
║  4. 调用 run_financial_model.py 的现有逻辑（交易策略 + 财务引擎）           ║
║                                                                              ║
║  数据流：                                                                    ║
║    project_config.yaml                                                       ║
║      │                                                                       ║
║      ├── external_constraints.enabled = true?                                ║
║      │     ├── 是 → constraint_engine.solve(year, region)                    ║
║      │     │         → 返回 overrides (电价/CAPEX/小时数/FCAS/融资)          ║
║      │     │         → 注入 config                                          ║
║      │     └── 否 → 使用 config 原始值                                      ║
║      │                                                                       ║
║      └── → run_financial_model.py 现有流程                                   ║
║            → trading 策略 → 财务引擎 → 输出                                  ║
║                                                                              ║
║  用法：                                                                      ║
║      # 从项目配置中读取约束声明                                              ║
║      python3 scripts/run_with_constraints.py \                               ║
║          --config OUTPUT/项目A/project_config.yaml \                         ║
║          --output OUTPUT/项目A/outputs/                                      ║
║                                                                              ║
║      # 命令行覆盖约束参数（不修改配置）                                      ║
║      python3 scripts/run_with_constraints.py \                               ║
║          --config OUTPUT/项目A/project_config.yaml \                         ║
║          --output OUTPUT/项目A/outputs/ \                                    ║
║          --assessment-year 2030 \                                            ║
║          --region NSW                                                        ║
║                                                                              ║
║      # 手动指定BESS新增容量（覆盖推演）                                      ║
║      python3 scripts/run_with_constraints.py \                               ║
║          --config OUTPUT/项目A/project_config.yaml \                         ║
║          --output OUTPUT/项目A/outputs/ \                                    ║
║          --bess-addition 10                                                  ║
║                                                                              ║
║      # 跨年份扫描                                                           ║
║      python3 scripts/run_with_constraints.py \                               ║
║          --config OUTPUT/项目A/project_config.yaml \                         ║
║          --output OUTPUT/项目A/outputs/ \                                    ║
║          --sweep-year 2025:2035:2                                            ║
║                                                                              ║
╚══════════════════════════════════════════════════════════════════════════════╝
"""

import json
import os
import sys
import copy
import argparse
from pathlib import Path

# 将项目根目录加入 Python 路径
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.constraint_engine import ConstraintEngine
from scripts.run_financial_model import main as run_financial_model_main


def load_config(config_path):
    """加载 YAML 配置文件"""
    import yaml
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def get_external_constraints_config(config):
    """
    从配置中提取外部约束声明。

    支持两种格式：
    1. 顶层 external_constraints 区块（模板格式）
    2. project.external_constraints 嵌套格式
    """
    # 尝试顶层格式
    ec = config.get("external_constraints", {})

    # 尝试嵌套格式
    if not ec:
        project = config.get("project", {})
        ec = project.get("external_constraints", {})

    return ec


def apply_overrides(config, overrides):
    """
    将约束覆盖值注入 config。

    支持点号分隔的路径语法，如 "revenue.ppa_price_per_kwh"
    会递归创建/更新嵌套字典。
    """
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


def run_single_assessment(config, output_dir, constraint_engine, year, region, manual_overrides):
    """
    运行单次约束评估。

    参数：
        config (dict): 原始项目配置
        output_dir (Path): 输出目录
        constraint_engine (ConstraintEngine): 约束引擎实例
        year (int): 评估年份
        region (str): NEM区域
        manual_overrides (dict): 手动覆盖的约束变量

    返回：
        dict: 约束引擎结果
    """
    print(f"\n{'='*60}")
    print(f"  评估年份: {year} | 区域: {region}")
    print(f"{'='*60}")

    # 运行约束引擎
    constraint_result = constraint_engine.solve(
        year=year,
        region=region,
        manual_overrides=manual_overrides,
    )

    # 生成约束报告
    report = constraint_engine.generate_report(constraint_result)
    report_path = output_dir / f"constraint_report_{year}.md"
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(report)
    print(f"约束报告已保存: {report_path}")

    # 保存约束结果（JSON）
    result_path = output_dir / f"constraint_result_{year}.json"
    with open(result_path, "w", encoding="utf-8") as f:
        json.dump(constraint_result, f, indent=2, ensure_ascii=False, default=str)
    print(f"约束结果已保存: {result_path}")

    # 应用约束覆盖值到 config
    overrides = constraint_result.get("overrides", {})
    if overrides:
        print(f"应用 {len(overrides)} 个约束覆盖值...")
        config = apply_overrides(config, overrides)

        # 保存约束后的配置（用于审计）
        constrained_config_path = output_dir / f"project_config_constrained_{year}.yaml"
        import yaml
        with open(constrained_config_path, "w", encoding="utf-8") as f:
            yaml.dump(config, f, allow_unicode=True, default_flow_style=False)
        print(f"约束后配置已保存: {constrained_config_path}")
    else:
        print("无约束覆盖值，使用原始配置")

    # 保存约束后的配置到临时文件，供 run_financial_model 使用
    temp_config = output_dir / f"_temp_constrained_config_{year}.yaml"
    import yaml
    with open(temp_config, "w", encoding="utf-8") as f:
        yaml.dump(config, f, allow_unicode=True, default_flow_style=False)

    # 调用财务模型
    print("运行财务模型引擎...")
    year_output_dir = output_dir / f"financial_{year}"
    year_output_dir.mkdir(parents=True, exist_ok=True)

    # 直接调用 run_financial_model 的核心逻辑
    _run_financial_model(str(temp_config), str(year_output_dir))

    # 清理临时文件
    temp_config.unlink()

    return constraint_result


def _run_financial_model(config_path, output_dir):
    """
    调用财务模型引擎（复用 run_financial_model.py 的逻辑）。

    参数：
        config_path (str): 配置文件路径
        output_dir (str): 输出目录路径
    """
    # 复用 run_financial_model 的 main 函数
    # 但需要修改 sys.argv
    import sys
    original_argv = sys.argv
    sys.argv = [
        "run_financial_model.py",
        "--config", config_path,
        "--output", output_dir,
    ]
    try:
        run_financial_model_main()
    except SystemExit:
        pass
    finally:
        sys.argv = original_argv


def parse_sweep_spec(sweep_str):
    """
    解析扫描规格字符串 "start:end:step"

    参数：
        sweep_str (str): 如 "2025:2035:2"

    返回：
        list: 年份列表
    """
    parts = sweep_str.split(":")
    if len(parts) != 3:
        raise ValueError(f"扫描规格格式错误，应为 start:end:step，收到: {sweep_str}")
    start = int(parts[0])
    end = int(parts[1])
    step = int(parts[2])
    return list(range(start, end + 1, step))


def main():
    parser = argparse.ArgumentParser(
        description="带外部条件约束的财务模型运行入口",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 基本用法（从配置读取约束声明）
  python3 scripts/run_with_constraints.py --config OUTPUT/项目A/project_config.yaml --output OUTPUT/项目A/outputs/

  # 命令行覆盖年份和区域
  python3 scripts/run_with_constraints.py --config OUTPUT/项目A/project_config.yaml --output OUTPUT/项目A/outputs/ --assessment-year 2030 --region NSW

  # 手动指定BESS新增容量
  python3 scripts/run_with_constraints.py --config OUTPUT/项目A/project_config.yaml --output OUTPUT/项目A/outputs/ --bess-addition 10

  # 跨年份扫描
  python3 scripts/run_with_constraints.py --config OUTPUT/项目A/project_config.yaml --output OUTPUT/项目A/outputs/ --sweep-year 2025:2035:2
        """
    )
    parser.add_argument("--config", required=True, help="项目参数配置文件路径 (project_config.yaml)")
    parser.add_argument("--output", required=True, help="输出目录路径")
    parser.add_argument("--constraint-file", default=None, help="约束数据文件路径（默认自动查找）")
    parser.add_argument("--assessment-year", type=int, default=None, help="评估年份（覆盖配置中的声明）")
    parser.add_argument("--region", default=None, help="NEM区域（覆盖配置中的声明）")
    parser.add_argument("--bess-addition", type=float, default=None, help="手动指定BESS新增容量(GW)")
    parser.add_argument("--coal-retirement", type=float, default=None, help="手动指定煤电退役容量(GW)")
    parser.add_argument("--sweep-year", default=None, help="跨年份扫描，格式 start:end:step，如 2025:2035:2")
    args = parser.parse_args()

    config_path = Path(args.config)
    output_dir = Path(args.output)

    if not config_path.exists():
        print(f"错误: 配置文件不存在: {config_path}")
        sys.exit(1)

    output_dir.mkdir(parents=True, exist_ok=True)

    # 加载配置
    config = load_config(config_path)

    # 获取项目名称
    proj_name = "未命名"
    if "project" in config and isinstance(config["project"], dict):
        proj_name = config["project"].get("name", "未命名")
    else:
        proj_name = config.get("project_name", "未命名")
    print(f"加载项目配置: {proj_name}")

    # 获取外部约束声明
    ec_config = get_external_constraints_config(config)
    enabled = ec_config.get("enabled", False)

    # 检查命令行是否强制启用了约束
    if args.assessment_year is not None or args.sweep_year is not None:
        enabled = True

    if not enabled:
        print("外部约束未启用，使用标准财务模型流程...")
        print("提示: 在 project_config.yaml 中设置 external_constraints.enabled: true 启用约束引擎")
        print("       或使用 --assessment-year 参数指定评估年份\n")

        # 直接调用标准流程
        _run_financial_model(str(config_path), str(output_dir))
        return

    # ── 约束引擎已启用 ──
    print("外部约束引擎已启用")

    # 初始化约束引擎
    constraint_file = args.constraint_file or ec_config.get("constraint_file", None)
    engine = ConstraintEngine(constraint_file)

    # 确定评估年份和区域
    year = args.assessment_year or ec_config.get("assessment_year", 2030)
    region = args.region or ec_config.get("region", "NSW")

    # 构建手动覆盖
    manual_overrides = {}
    if args.bess_addition is not None:
        manual_overrides["bess_capacity_addition_gw"] = args.bess_addition
    if args.coal_retirement is not None:
        manual_overrides["coal_retirement_gw"] = args.coal_retirement

    # 从配置中读取其他手动覆盖
    for key in ["bess_capacity_addition_gw", "construction_cost_escalation_pct",
                "grid_connection_cost_premium_pct", "fcas_price_decline_pct"]:
        if key in ec_config and ec_config[key] != 0:
            if key not in manual_overrides:
                manual_overrides[key] = ec_config[key]

    # ── 运行评估 ──
    if args.sweep_year:
        # 跨年份扫描
        years = parse_sweep_spec(args.sweep_year)
        print(f"跨年份扫描: {years[0]} → {years[-1]}, 步长 {years[1] - years[0]} 年")
        print(f"共 {len(years)} 个评估点\n")

        all_results = []
        for y in years:
            result = run_single_assessment(
                config, output_dir, engine, y, region, manual_overrides
            )
            all_results.append(result)

        # 生成汇总报告
        summary_lines = []
        summary_lines.append("# 跨年份约束扫描汇总报告")
        summary_lines.append("")
        summary_lines.append(f"**项目**: {proj_name}")
        summary_lines.append(f"**区域**: {region}")
        summary_lines.append(f"**扫描范围**: {years[0]} → {years[-1]}")
        summary_lines.append("")
        summary_lines.append("| 年份 | BESS存量 | 加权电价 | CAPEX/kW | 项目IRR | 资本金IRR | 项目NPV |")
        summary_lines.append("|------|----------|----------|----------|---------|-----------|---------|")

        for result in all_results:
            yr = result["assessment_year"]
            market = result.get("market_state", {})
            bess = market.get("bess_installed_gw", "N/A")
            overrides = result.get("overrides", {})
            price = overrides.get("revenue.ppa_price_per_kwh", "N/A")
            capex = overrides.get("costs.capex_per_watt", "N/A")

            # 尝试从财务结果中读取IRR/NPV
            yr_output = output_dir / f"financial_{yr}" / "financial_results.json"
            irr_str = "N/A"
            eirr_str = "N/A"
            npv_str = "N/A"
            if yr_output.exists():
                try:
                    with open(yr_output, "r") as f:
                        fin = json.load(f)
                    base = fin.get("base_result", {})
                    irr = base.get("project_irr")
                    eirr = base.get("equity_irr")
                    npv = base.get("project_npv")
                    irr_str = f"{irr*100:.2f}%" if irr else "N/A"
                    eirr_str = f"{eirr*100:.2f}%" if eirr else "N/A"
                    npv_str = f"${npv:,.0f}" if npv else "N/A"
                except Exception:
                    pass

            price_str = f"${price:.4f}" if isinstance(price, float) else str(price)
            capex_str = f"${capex:.4f}" if isinstance(capex, float) else str(capex)
            summary_lines.append(f"| {yr} | {bess} GW | {price_str} | {capex_str}/W | {irr_str} | {eirr_str} | {npv_str} |")

        summary_lines.append("")
        summary_path = output_dir / "constraint_sweep_summary.md"
        with open(summary_path, "w", encoding="utf-8") as f:
            f.write("\n".join(summary_lines))
        print(f"\n扫描汇总报告已保存: {summary_path}")
        print("\n" + "\n".join(summary_lines))

    else:
        # 单次评估
        run_single_assessment(config, output_dir, engine, year, region, manual_overrides)

    print("\n完成!")


if __name__ == "__main__":
    main()
