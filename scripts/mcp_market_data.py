#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════════════════════════╗
║  MCP 市场数据查询                                                           ║
║                                                                              ║
║  用途：作为 MCP 工具，封装 data/ 目录中的市场参考数据，                       ║
║        让 CLINE Agent 可以通过 use_mcp_tool 直接查询市场数据。               ║
║                                                                              ║
║  MCP 协议：通过 stdio 接收 JSON-RPC 请求，返回查询结果                        ║
║                                                                              ║
║  可用工具：                                                                  ║
║    1. query_market_data     — 查询市场参考数据（PPA电价、CAPEX、MLF等）      ║
║    2. query_nem_statistics  — 查询NEM电力市场统计数据                        ║
║    3. query_region_data     — 查询特定区域的市场数据                          ║
║    4. query_connection_cost — 查询并网接入成本参考                            ║
║    5. query_bess_strategy   — 查询BESS调度策略与收益模型                      ║
║    6. query_ai_dc_demand    — 查询AI数据中心电力需求数据                      ║
║                                                                              ║
║  用法：                                                                      ║
║    python3 scripts/mcp_market_data.py                                        ║
║                                                                              ║
║  依赖：                                                                      ║
║    - PyYAML (pip install pyyaml)                                             ║
║                                                                              ║
╚══════════════════════════════════════════════════════════════════════════════╝
"""

import json
import sys
import os
from typing import Any, Dict, List, Optional

try:
    import yaml
except ImportError:
    yaml = None


# ═══════════════════════════════════════════════════════════════
# 数据加载
# ═══════════════════════════════════════════════════════════════

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
CONFIG_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config")

_cache: Dict[str, Any] = {}


def _load_yaml(path: str) -> Dict[str, Any]:
    """加载 YAML 文件，带缓存"""
    if path in _cache:
        return _cache[path]

    if not os.path.exists(path):
        return {"error": f"文件不存在: {path}"}

    if yaml is None:
        return {"error": "PyYAML 未安装，请运行: pip install pyyaml"}

    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    _cache[path] = data
    return data


def _load_au_market_data() -> Dict[str, Any]:
    """加载澳洲市场参考数据"""
    path = os.path.join(DATA_DIR, "market_reference_au.yaml")
    return _load_yaml(path)


def _load_cn_market_data() -> Dict[str, Any]:
    """加载中国市场参考数据"""
    path = os.path.join(DATA_DIR, "market_reference_cn.yaml")
    return _load_yaml(path)


# ═══════════════════════════════════════════════════════════════
# MCP 工具定义
# ═══════════════════════════════════════════════════════════════

TOOLS = [
    {
        "name": "query_market_data",
        "description": "查询市场参考数据。支持查询PPA电价、CAPEX、MLF、LGC价格等关键市场参数。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "region": {
                    "type": "string",
                    "description": "区域代码（au/nsw/vic/qld/sa/tas/cn）",
                    "default": "au",
                },
                "asset_type": {
                    "type": "string",
                    "description": "资产类型（solar/bess/solar_pv）",
                    "default": "solar",
                },
                "metric": {
                    "type": "string",
                    "description": "查询指标（ppa_price/capex/mlf/lgc_price/all）",
                    "default": "all",
                },
            },
            "required": [],
        },
    },
    {
        "name": "query_nem_statistics",
        "description": "查询NEM电力市场官方统计数据（来自AER State of the Energy Market 2025）。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "category": {
                    "type": "string",
                    "description": "统计类别（all/wholesale_prices/generation/capacity/new_entry/emissions/network）",
                    "default": "all",
                },
            },
            "required": [],
        },
    },
    {
        "name": "query_region_data",
        "description": "查询特定NEM区域的市场数据（CAPEX、PPA电价、MLF、容量因子等）。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "region": {
                    "type": "string",
                    "description": "区域代码（nsw/vic/qld/sa/tas）",
                    "enum": ["nsw", "vic", "qld", "sa", "tas"],
                },
            },
            "required": ["region"],
        },
    },
    {
        "name": "query_connection_cost",
        "description": "查询并网接入成本参考。按容量范围查询典型并网费用。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "capacity_mw": {
                    "type": "number",
                    "description": "项目装机容量（MW），用于匹配最接近的并网成本范围",
                },
            },
            "required": ["capacity_mw"],
        },
    },
    {
        "name": "query_bess_strategy",
        "description": "查询BESS调度策略与收益模型。返回不同调度策略下的等效充放电价格。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "strategy": {
                    "type": "string",
                    "description": "调度策略（all/simple_daily_cycle/negative_price_60pct/negative_price_80pct/dual_optimized）",
                    "default": "all",
                },
            },
            "required": [],
        },
    },
    {
        "name": "query_ai_dc_demand",
        "description": "查询AI数据中心电力需求数据。返回AI数据中心对NEM电力需求的影响分析。",
        "inputSchema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
]


# ═══════════════════════════════════════════════════════════════
# 工具处理函数
# ═══════════════════════════════════════════════════════════════

def handle_query_market_data(params: Dict[str, Any]) -> Dict[str, Any]:
    region = params.get("region", "au").lower()
    asset_type = params.get("asset_type", "solar").lower()
    metric = params.get("metric", "all").lower()

    data = _load_au_market_data()
    if "error" in data:
        return data

    # 获取区域数据
    regions = data.get("nem_regions", {})
    region_data = regions.get(region)

    if not region_data and region != "au":
        # 尝试匹配国家平均
        region_data = regions.get("national_average")
        if not region_data:
            return {"error": f"未找到区域 '{region}' 的数据。可用区域: {list(regions.keys())}"}

    if not region_data:
        region_data = regions.get("national_average", {})

    result = {
        "region": region,
        "region_name": region_data.get("full_name", region),
        "asset_type": asset_type,
    }

    # 根据指标类型返回数据
    if metric in ("capex", "all"):
        capex = region_data.get("capex", {})
        if asset_type == "solar" or asset_type == "solar_pv":
            result["solar_capex"] = capex.get("solar_pv_aud_kw", {})
        elif asset_type == "bess":
            result["bess_2hr_capex"] = capex.get("bess_2hr_aud_kw", {})
            result["bess_4hr_capex"] = capex.get("bess_4hr_aud_kw", {})

    if metric in ("ppa_price", "all"):
        revenue = region_data.get("revenue", {})
        if asset_type == "solar" or asset_type == "solar_pv":
            result["solar_ppa_price"] = revenue.get("solar_ppa_aud_mwh", {})
        elif asset_type == "bess":
            result["bess_tolling_price"] = revenue.get("bess_ppa_tolling_aud_mwh", {})
        result["lgc_price"] = revenue.get("lgc_price_aud", {})

    if metric in ("mlf", "all"):
        grid = region_data.get("grid", {})
        result["mlf_range"] = grid.get("mlf_range", {})

    if metric in ("capacity_factor", "all"):
        tech = region_data.get("technical", {})
        result["capacity_factor"] = tech.get("solar_capacity_factor_pct", {})

    # 添加关键参数
    if metric == "all":
        result["key_parameters"] = data.get("key_parameters", {})

    return result


def handle_query_nem_statistics(params: Dict[str, Any]) -> Dict[str, Any]:
    category = params.get("category", "all").lower()

    data = _load_au_market_data()
    if "error" in data:
        return data

    stats = data.get("official_aer_statistics_2025", {})
    if not stats:
        return {"error": "未找到NEM统计数据"}

    result = {
        "source": stats.get("source", ""),
        "data_period": stats.get("data_period", ""),
        "extraction_date": stats.get("extraction_date", ""),
    }

    if category in ("all", "wholesale_prices"):
        result["nem_key_statistics"] = stats.get("nem_key_statistics_2024", {})
        result["wholesale_prices"] = stats.get("wholesale_prices_annual_avg_2024", {})
        result["price_volatility"] = stats.get("price_volatility_2024", {})

    if category in ("all", "generation"):
        result["generation_capacity"] = stats.get("generation_capacity_by_fuel_dec_2024", {})
        result["generation_output"] = stats.get("generation_output_2024", {})

    if category in ("all", "new_entry"):
        result["new_entry_2024"] = stats.get("new_entry_2024", {})
        result["committed_projects"] = stats.get("committed_projects_by_end_2027", {})

    if category in ("all", "network"):
        result["network_statistics"] = stats.get("network_statistics_fy2024", {})

    if category in ("all", "emissions"):
        result["nem_key_statistics"] = stats.get("nem_key_statistics_2024", {})

    return result


def handle_query_region_data(params: Dict[str, Any]) -> Dict[str, Any]:
    region = params["region"].lower()

    data = _load_au_market_data()
    if "error" in data:
        return data

    regions = data.get("nem_regions", {})
    region_data = regions.get(region)

    if not region_data:
        return {"error": f"未找到区域 '{region}' 的数据。可用区域: nsw, vic, qld, sa, tas"}

    return {
        "region": region,
        "full_name": region_data.get("full_name", ""),
        "capex": region_data.get("capex", {}),
        "revenue": region_data.get("revenue", {}),
        "grid": region_data.get("grid", {}),
        "technical": region_data.get("technical", {}),
    }


def handle_query_connection_cost(params: Dict[str, Any]) -> Dict[str, Any]:
    capacity_mw = params["capacity_mw"]

    data = _load_au_market_data()
    if "error" in data:
        return data

    connection_ref = data.get("connection_cost_reference", {})
    levels = connection_ref.get("levels", [])

    # 找到匹配的容量范围
    matched_level = None
    for level in levels:
        cap_range = level.get("capacity_range", "")
        if "≤" in cap_range:
            max_cap = float(cap_range.replace("≤", "").replace("MW", "").strip())
            if capacity_mw <= max_cap:
                matched_level = level
                break
        elif "-" in cap_range:
            parts = cap_range.split("-")
            min_cap = float(parts[0].strip())
            max_part = parts[1].replace("MW", "").strip()
            if "≤" in max_part:
                max_cap = float(max_part.replace("≤", "").strip())
            else:
                max_cap = float(max_part)
            if min_cap <= capacity_mw <= max_cap:
                matched_level = level
                break
        elif ">" in cap_range:
            min_cap = float(cap_range.replace(">", "").replace("MW", "").strip())
            if capacity_mw > min_cap:
                matched_level = level
                break

    if not matched_level:
        # 返回最接近的范围
        matched_level = levels[-1] if levels else None

    result = {
        "project_capacity_mw": capacity_mw,
        "matched_range": matched_level.get("capacity_range", "") if matched_level else "未知",
        "suggested_voltage": matched_level.get("suggested_voltage", "") if matched_level else "",
        "unit_cost_per_km": matched_level.get("unit_cost_aud_km", {}) if matched_level else {},
        "total_connection_fee": matched_level.get("total_connection_fee_aud_m", {}) if matched_level else {},
        "notes": matched_level.get("notes", "") if matched_level else "",
        "disclaimer": connection_ref.get("disclaimer", ""),
        "cost_escalation_note": connection_ref.get("cost_escalation_note", ""),
    }

    return result


def handle_query_bess_strategy(params: Dict[str, Any]) -> Dict[str, Any]:
    strategy = params.get("strategy", "all").lower()

    data = _load_au_market_data()
    if "error" in data:
        return data

    strategies = data.get("bess_dispatch_strategies", {}).get("strategies", {})
    fcas = data.get("fcas_differentiation", {})
    lifecycle = data.get("battery_lifecycle", {})

    result = {}

    if strategy == "all":
        result["strategies"] = strategies
    elif strategy == "simple_daily_cycle":
        result["strategy"] = strategies.get("simple_daily_cycle", {})
    elif strategy == "negative_price_60pct":
        result["strategy"] = strategies.get("negative_price_60pct_capture", {})
    elif strategy == "negative_price_80pct":
        result["strategy"] = strategies.get("negative_price_80pct_capture", {})
    elif strategy == "dual_optimized":
        result["strategy"] = strategies.get("dual_optimized", {})

    result["fcas_differentiation"] = fcas
    result["battery_lifecycle"] = lifecycle

    return result


def handle_query_ai_dc_demand(params: Dict[str, Any]) -> Dict[str, Any]:
    data = _load_au_market_data()
    if "error" in data:
        return data

    ai_demand = data.get("ai_data_centre_demand", {})
    if not ai_demand:
        return {"error": "未找到AI数据中心需求数据"}

    return {
        "global_context": ai_demand.get("global_context", {}),
        "australia_context": ai_demand.get("australia_context", {}),
        "ai_dc_load_claims": ai_demand.get("ai_dc_load_claims", {}),
        "implications": ai_demand.get("implications", []),
    }


# ═══════════════════════════════════════════════════════════════
# MCP 协议处理
# ═══════════════════════════════════════════════════════════════

HANDLERS = {
    "query_market_data": handle_query_market_data,
    "query_nem_statistics": handle_query_nem_statistics,
    "query_region_data": handle_query_region_data,
    "query_connection_cost": handle_query_connection_cost,
    "query_bess_strategy": handle_query_bess_strategy,
    "query_ai_dc_demand": handle_query_ai_dc_demand,
}


def handle_request(request: Dict[str, Any]) -> Dict[str, Any]:
    """处理 MCP JSON-RPC 请求"""
    method = request.get("method", "")
    request_id = request.get("id")

    if method == "mcp.listTools":
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {"tools": TOOLS},
        }

    if method == "mcp.callTool":
        params = request.get("params", {})
        tool_name = params.get("name", "")
        tool_args = params.get("arguments", {})

        if tool_name in HANDLERS:
            try:
                result = HANDLERS[tool_name](tool_args)
                return {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": {
                        "content": [
                            {
                                "type": "text",
                                "text": json.dumps(result, indent=2, ensure_ascii=False, default=str),
                            }
                        ],
                    },
                }
            except Exception as e:
                return {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "error": {
                        "code": -32000,
                        "message": str(e),
                    },
                }
        else:
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {
                    "code": -32601,
                    "message": f"未知工具: {tool_name}",
                },
            }

    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": {
            "code": -32601,
            "message": f"未知方法: {method}",
        },
    }


def main():
    """MCP 服务器主循环 - 通过 stdio 接收 JSON-RPC 请求"""
    sys.stderr.write("MCP Market Data Server running on stdio\n")
    sys.stderr.flush()

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue

        try:
            request = json.loads(line)
            response = handle_request(request)
            sys.stdout.write(json.dumps(response) + "\n")
            sys.stdout.flush()
        except json.JSONDecodeError as e:
            sys.stderr.write(f"JSON 解析错误: {e}\n")
            sys.stderr.flush()
        except Exception as e:
            sys.stderr.write(f"处理请求时出错: {e}\n")
            sys.stderr.flush()


if __name__ == "__main__":
    main()
