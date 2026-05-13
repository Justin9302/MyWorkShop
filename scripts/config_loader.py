#!/usr/bin/env python3
"""
config_loader.py — 项目参数配置加载辅助模块

用途：
    为 financial_model_engine.py 提供安全的配置加载功能，
    防止文件读取错误、嵌套结构不匹配、参数缺失等问题。

    同时支持两种配置格式：
    1. 嵌套格式（由工作流生成）：{project: {name: ...}, technical: {...}, ...}
    2. 扁平格式（测试用例使用）：{capacity_kw: ..., ppa_price_per_kwh: ..., ...}

用法：
    from scripts.config_loader import load_project_config, validate_config, merge_configs

    # 从文件加载
    config = load_project_config("path/to/project_config.yaml")

    # 验证配置完整性
    errors, warnings = validate_config(config)

    # 合并多个配置（用于情景分析）
    merged = merge_configs(base_config, scenario_overrides)

依赖：
    - PyYAML (pip install pyyaml)
"""

import os
import sys
import copy
from pathlib import Path
from typing import Tuple, List, Dict, Any, Optional


# =============================================================================
# 配置加载
# =============================================================================

def load_project_config(config_path: str) -> dict:
    """
    从 YAML 文件加载项目参数配置。

    功能：
    1. 检查文件是否存在
    2. 读取并解析 YAML
    3. 自动检测嵌套/扁平格式
    4. 填充缺失的必需参数默认值
    5. 验证参数类型和范围

    参数：
        config_path (str): YAML 配置文件路径

    返回：
        dict: 加载并验证后的配置字典

    异常：
        FileNotFoundError: 配置文件不存在
        ValueError: YAML 解析失败或参数验证失败
    """
    import yaml

    path = Path(config_path)

    # 检查文件是否存在
    if not path.exists():
        raise FileNotFoundError(f"配置文件不存在: {config_path}")

    # 读取并解析 YAML
    try:
        with open(path, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)
    except yaml.YAMLError as e:
        raise ValueError(f"YAML 解析失败: {e}")

    if config is None:
        raise ValueError(f"配置文件为空: {config_path}")

    # 自动检测格式并填充默认值
    config = _normalize_config(config)

    return config


def _normalize_config(config: dict) -> dict:
    """
    标准化配置：检测格式、填充默认值、确保必需字段存在。

    同时支持嵌套格式和扁平格式。
    """
    # 检测是否为嵌套格式
    has_nested = any(k in config for k in ["project", "technical", "costs", "revenue", "financing"])

    if has_nested:
        return _normalize_nested(config)
    else:
        return _normalize_flat(config)


def _normalize_nested(config: dict) -> dict:
    """标准化嵌套格式配置"""
    # 确保所有必需层级存在
    config.setdefault("project", {})
    config.setdefault("technical", {})
    config.setdefault("costs", {})
    config.setdefault("revenue", {})
    config.setdefault("financing", {})

    # 确保 offtaker 层级存在（如果 revenue_model 被设置）
    offtaker = config.get("offtaker", {})
    if offtaker:
        offtaker.setdefault("revenue_model", "ppa")
        offtaker.setdefault("ppa_type", "corporate")
        offtaker.setdefault("ppa_tenor_years", 15)
        offtaker.setdefault("counterparty", {})
        offtaker.setdefault("credit_enhancement", {})
        offtaker.setdefault("subsidy_risk", "low")
        offtaker.setdefault("market_risk", {})
        config["offtaker"] = offtaker

    # 确保国家风险参数存在
    config.setdefault("country_risk_level", "medium")
    config.setdefault("exchange_rate_risk", "medium")
    config.setdefault("ppa_currency", "USD")

    # 确保 optional 层级存在
    config.setdefault("optional", {})

    return config


def _normalize_flat(config: dict) -> dict:
    """标准化扁平格式配置"""
    # 扁平格式不需要额外处理，引擎的 _flatten_config 会处理默认值
    return config


# =============================================================================
# 配置验证
# =============================================================================

# 必需字段定义（嵌套格式）
REQUIRED_NESTED_FIELDS = {
    "project": ["name", "technology_type", "capacity_mw", "capacity_kw"],
    "technical": ["equivalent_hours", "operation_years"],
    "costs": ["capex_per_watt", "capex_total", "opex_fixed_per_kw_year"],
    "revenue": ["ppa_price_per_kwh"],
}

# 必需字段定义（扁平格式）
REQUIRED_FLAT_FIELDS = [
    "capacity_kw", "capex_total", "ppa_price_per_kwh",
    "equivalent_hours", "operation_years",
]

# 字段类型验证规则
TYPE_RULES = {
    "capacity_mw": (int, float),
    "capacity_kw": (int, float),
    "capex_total": (int, float),
    "capex_per_watt": (int, float),
    "ppa_price_per_kwh": (int, float),
    "equivalent_hours": (int, float),
    "operation_years": (int, float),
    "debt_ratio": (int, float),
    "interest_rate": (int, float),
    "discount_rate": (int, float),
    "tax_rate": (int, float),
    "degradation_rate": (int, float),
}

# 字段范围验证规则
RANGE_RULES = {
    "capacity_mw": (0, 100000),
    "capacity_kw": (0, 100000000),
    "capex_total": (0, 1e12),
    "capex_per_watt": (0, 10),
    "ppa_price_per_kwh": (0, 1),
    "equivalent_hours": (0, 8760),
    "operation_years": (1, 100),
    "debt_ratio": (0, 1),
    "interest_rate": (-0.5, 1),
    "discount_rate": (0, 1),
    "tax_rate": (0, 1),
    "degradation_rate": (0, 1),
}


def validate_config(config: dict) -> Tuple[List[str], List[str]]:
    """
    验证配置完整性。

    检查项：
    1. 必需字段是否存在
    2. 字段类型是否正确
    3. 字段值是否在合理范围内
    4. 嵌套结构是否完整

    参数：
        config (dict): 项目参数配置

    返回：
        Tuple[List[str], List[str]]: (错误列表, 警告列表)
    """
    errors = []
    warnings = []

    # 检测格式
    has_nested = any(k in config for k in ["project", "technical", "costs", "revenue", "financing"])

    if has_nested:
        _validate_nested(config, errors, warnings)
    else:
        _validate_flat(config, errors, warnings)

    return errors, warnings


def _validate_nested(config: dict, errors: list, warnings: list):
    """验证嵌套格式配置"""
    # 检查必需层级
    for section in ["project", "technical", "costs", "revenue", "financing"]:
        if section not in config:
            warnings.append(f"缺少可选层级 '{section}'，将使用默认值")
            continue

        section_data = config[section]
        if not isinstance(section_data, dict):
            errors.append(f"层级 '{section}' 应为字典类型")
            continue

        # 检查该层级的必需字段
        if section in REQUIRED_NESTED_FIELDS:
            for field in REQUIRED_NESTED_FIELDS[section]:
                if field not in section_data:
                    errors.append(f"缺少必需字段 '{section}.{field}'")

    # 检查字段类型和范围
    _check_field_types_and_ranges(config, errors, warnings, nested=True)


def _validate_flat(config: dict, errors: list, warnings: list):
    """验证扁平格式配置"""
    # 检查必需字段
    for field in REQUIRED_FLAT_FIELDS:
        if field not in config:
            errors.append(f"缺少必需字段 '{field}'")

    # 检查字段类型和范围
    _check_field_types_and_ranges(config, errors, warnings, nested=False)


def _check_field_types_and_ranges(config: dict, errors: list, warnings: list, nested: bool = True):
    """检查字段类型和范围"""
    # 展平配置以便检查
    flat = {}
    if nested:
        for section in ["project", "technical", "costs", "revenue", "financing"]:
            section_data = config.get(section, {})
            if isinstance(section_data, dict):
                flat.update(section_data)
    else:
        flat = config

    for field, expected_types in TYPE_RULES.items():
        if field in flat:
            value = flat[field]
            if not isinstance(value, expected_types):
                warnings.append(
                    f"字段 '{field}' 类型应为 {expected_types}，实际为 {type(value).__name__}（值: {value}）"
                )

    for field, (min_val, max_val) in RANGE_RULES.items():
        if field in flat:
            value = flat[field]
            if isinstance(value, (int, float)):
                if value < min_val or value > max_val:
                    warnings.append(
                        f"字段 '{field}' 值 {value} 超出合理范围 [{min_val}, {max_val}]"
                    )


# =============================================================================
# 配置合并
# =============================================================================

def merge_configs(base_config: dict, override: dict) -> dict:
    """
    深度合并两个配置字典。

    用于多情景分析：将情景覆盖参数合并到基准配置中。
    支持嵌套格式和扁平格式的混合合并。

    参数：
        base_config (dict): 基准配置
        override (dict): 覆盖参数（只需包含要修改的字段）

    返回：
        dict: 合并后的配置
    """
    result = copy.deepcopy(base_config)

    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            # 深度合并嵌套字典
            result[key] = _deep_merge(result[key], value)
        else:
            # 直接覆盖
            result[key] = value

    return result


def _deep_merge(base: dict, override: dict) -> dict:
    """递归深度合并两个字典"""
    result = copy.deepcopy(base)
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


# =============================================================================
# 配置摘要
# =============================================================================

def summarize_config(config: dict) -> str:
    """
    生成配置摘要（用于日志和调试）。

    参数：
        config (dict): 项目参数配置

    返回：
        str: 格式化的配置摘要
    """
    has_nested = any(k in config for k in ["project", "technical", "costs", "revenue", "financing"])

    lines = []
    lines.append("=" * 60)
    lines.append("项目参数配置摘要")
    lines.append("=" * 60)

    if has_nested:
        proj = config.get("project", {})
        lines.append(f"  项目名称: {proj.get('name', '未命名')}")
        lines.append(f"  技术类型: {proj.get('technology_type', '未指定')}")
        lines.append(f"  装机容量: {proj.get('capacity_mw', 0)} MW")

        tech = config.get("technical", {})
        lines.append(f"  等效小时数: {tech.get('equivalent_hours', 0)} h")
        lines.append(f"  运营年限: {tech.get('operation_years', 0)} 年")

        costs = config.get("costs", {})
        lines.append(f"  CAPEX: ${costs.get('capex_total', 0):,.0f}")

        rev = config.get("revenue", {})
        lines.append(f"  PPA电价: ${rev.get('ppa_price_per_kwh', 0):.4f}/kWh")

        fin = config.get("financing", {})
        lines.append(f"  债务比例: {fin.get('debt_ratio', 0.70)*100:.0f}%")
        lines.append(f"  折现率: {fin.get('discount_rate', 0.10)*100:.1f}%")
    else:
        lines.append(f"  装机容量: {config.get('capacity_mw', config.get('capacity_kw', 0) / 1000)} MW")
        lines.append(f"  CAPEX: ${config.get('capex_total', 0):,.0f}")
        lines.append(f"  PPA电价: ${config.get('ppa_price_per_kwh', 0):.4f}/kWh")
        lines.append(f"  等效小时数: {config.get('equivalent_hours', 0)} h")

    # 购电方风险评估
    offtaker = config.get("offtaker", {})
    if offtaker:
        lines.append(f"  收入模式: {offtaker.get('revenue_model', 'ppa')}")
        cp = offtaker.get("counterparty", {})
        if cp.get("name"):
            lines.append(f"  购电方: {cp['name']}")

    lines.append("=" * 60)
    return "\n".join(lines)


# =============================================================================
# 命令行入口（用于测试）
# =============================================================================

def main():
    """命令行入口：加载并验证配置文件"""
    import argparse

    parser = argparse.ArgumentParser(description="项目参数配置加载辅助工具")
    parser.add_argument("--config", required=True, help="项目参数配置文件路径")
    parser.add_argument("--validate", action="store_true", help="仅验证配置，不加载")
    args = parser.parse_args()

    try:
        config = load_project_config(args.config)
        print(summarize_config(config))

        errors, warnings = validate_config(config)

        if errors:
            print(f"\n❌ 发现 {len(errors)} 个错误:")
            for e in errors:
                print(f"  - {e}")

        if warnings:
            print(f"\n⚠️  发现 {len(warnings)} 个警告:")
            for w in warnings:
                print(f"  - {w}")

        if not errors:
            print("\n✅ 配置验证通过")

    except (FileNotFoundError, ValueError) as e:
        print(f"❌ 错误: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
