#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════════════════════════╗
║  MCP 数据可视化工具                                                         ║
║                                                                              ║
║  用途：作为 MCP 工具，提供数据可视化功能，                                    ║
║        让 CLINE Agent 可以通过 use_mcp_tool 生成图表和可视化报告。            ║
║                                                                              ║
║  MCP 协议：通过 stdio 接收 JSON-RPC 请求，返回可视化结果                      ║
║                                                                              ║
║  可用工具：                                                                  ║
║    1. generate_chart_html   — 生成图表 HTML（支持折线图、柱状图、饼图等）    ║
║    2. generate_financial_dashboard — 生成财务指标仪表盘 HTML                  ║
║    3. generate_sensitivity_chart — 生成敏感性分析蛛网图 HTML                  ║
║    4. generate_comparison_table — 生成项目对比表格 HTML                       ║
║                                                                              ║
║  用法：                                                                      ║
║    python3 scripts/mcp_data_viz.py                                           ║
║                                                                              ║
╚══════════════════════════════════════════════════════════════════════════════╝
"""

import json
import sys
import os
from typing import Any, Dict, List, Optional


# ═══════════════════════════════════════════════════════════════
# MCP 工具定义
# ═══════════════════════════════════════════════════════════════

TOOLS = [
    {
        "name": "generate_chart_html",
        "description": "生成图表HTML。支持折线图、柱状图、饼图、散点图，使用Chart.js渲染。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "chart_type": {
                    "type": "string",
                    "description": "图表类型（line/bar/pie/scatter/radar）",
                    "enum": ["line", "bar", "pie", "scatter", "radar"],
                },
                "title": {
                    "type": "string",
                    "description": "图表标题",
                },
                "labels": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "X轴标签或数据点名称",
                },
                "datasets": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "label": {"type": "string", "description": "数据集名称"},
                            "data": {
                                "type": "array",
                                "items": {"type": "number"},
                                "description": "数据值列表",
                            },
                            "color": {
                                "type": "string",
                                "description": "颜色（可选，如 #ff6384）",
                            },
                        },
                        "required": ["label", "data"],
                    },
                    "description": "数据集列表",
                },
                "x_label": {
                    "type": "string",
                    "description": "X轴标签（可选）",
                },
                "y_label": {
                    "type": "string",
                    "description": "Y轴标签（可选）",
                },
                "width": {
                    "type": "integer",
                    "description": "图表宽度（像素）",
                    "default": 800,
                },
                "height": {
                    "type": "integer",
                    "description": "图表高度（像素）",
                    "default": 500,
                },
            },
            "required": ["chart_type", "title", "labels", "datasets"],
        },
    },
    {
        "name": "generate_financial_dashboard",
        "description": "生成财务指标仪表盘HTML。展示IRR、NPV、LCOE、回收期、DSCR等关键指标。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "project_name": {
                    "type": "string",
                    "description": "项目名称",
                },
                "metrics": {
                    "type": "object",
                    "properties": {
                        "project_irr": {"type": "number", "description": "项目IRR（如 0.12）"},
                        "equity_irr": {"type": "number", "description": "资本金IRR"},
                        "project_npv": {"type": "number", "description": "项目NPV"},
                        "equity_npv": {"type": "number", "description": "资本金NPV"},
                        "payback_years": {"type": "number", "description": "回收期（年）"},
                        "lcoe_per_kwh": {"type": "number", "description": "LCOE（$/kWh）"},
                        "avg_dscr": {"type": "number", "description": "平均偿债覆盖率"},
                        "min_dscr": {"type": "number", "description": "最低偿债覆盖率"},
                    },
                    "required": ["project_irr", "equity_irr", "project_npv", "payback_years"],
                },
                "scenario_comparison": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "project_irr": {"type": "number"},
                            "equity_irr": {"type": "number"},
                            "project_npv": {"type": "number"},
                        },
                        "required": ["name", "project_irr"],
                    },
                    "description": "多情景对比数据（可选）",
                },
            },
            "required": ["project_name", "metrics"],
        },
    },
    {
        "name": "generate_sensitivity_chart",
        "description": "生成敏感性分析蛛网图/柱状图HTML。展示各变量对IRR的影响范围。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "project_name": {
                    "type": "string",
                    "description": "项目名称",
                },
                "sensitivity_results": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "param_name": {"type": "string", "description": "参数名称"},
                            "project_irr_range": {
                                "type": "object",
                                "properties": {
                                    "min": {"type": "number"},
                                    "max": {"type": "number"},
                                },
                                "required": ["min", "max"],
                            },
                        },
                        "required": ["param_name", "project_irr_range"],
                    },
                    "description": "敏感性分析结果列表",
                },
                "base_irr": {
                    "type": "number",
                    "description": "基准IRR值",
                },
            },
            "required": ["project_name", "sensitivity_results", "base_irr"],
        },
    },
    {
        "name": "generate_comparison_table",
        "description": "生成项目对比表格HTML。支持多个项目的关键指标对比。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "title": {
                    "type": "string",
                    "description": "对比表格标题",
                },
                "columns": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "列名列表（如 ['项目名称', 'IRR', 'NPV', 'LCOE']）",
                },
                "rows": {
                    "type": "array",
                    "items": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "每行数据，与列名对应",
                    },
                    "description": "数据行列表",
                },
                "highlight_column": {
                    "type": "integer",
                    "description": "高亮列索引（可选，如 1 表示高亮IRR列）",
                },
            },
            "required": ["title", "columns", "rows"],
        },
    },
]


# ═══════════════════════════════════════════════════════════════
# HTML 模板生成
# ═══════════════════════════════════════════════════════════════

def _chart_html_template(
    chart_type: str,
    title: str,
    labels: List[str],
    datasets: List[Dict],
    x_label: str = "",
    y_label: str = "",
    width: int = 800,
    height: int = 500,
) -> str:
    """生成 Chart.js 图表 HTML"""
    colors = [
        "#36A2EB", "#FF6384", "#4BC0C0", "#FF9F40", "#9966FF",
        "#FFCD56", "#C9CBCF", "#7BC8A4", "#E7E9ED", "#F7464A",
    ]

    datasets_json = []
    for i, ds in enumerate(datasets):
        color = ds.get("color", colors[i % len(colors)])
        datasets_json.append({
            "label": ds["label"],
            "data": ds["data"],
            "backgroundColor": color,
            "borderColor": color,
            "borderWidth": 2,
            "fill": chart_type == "line",
            "tension": 0.1,
        })

    config = {
        "type": chart_type,
        "data": {
            "labels": labels,
            "datasets": datasets_json,
        },
        "options": {
            "responsive": True,
            "maintainAspectRatio": False,
            "plugins": {
                "title": {
                    "display": True,
                    "text": title,
                    "font": {"size": 16},
                },
                "legend": {
                    "display": True,
                    "position": "bottom",
                },
            },
            "scales": {
                "x": {
                    "display": True,
                    "title": {
                        "display": bool(x_label),
                        "text": x_label,
                    },
                },
                "y": {
                    "display": True,
                    "title": {
                        "display": bool(y_label),
                        "text": y_label,
                    },
                    "beginAtZero": chart_type != "scatter",
                },
            },
        },
    }

    if chart_type == "pie":
        config["options"]["scales"] = {}

    config_json = json.dumps(config, indent=2)

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{title}</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; margin: 20px; background: #f5f5f5; }}
        .chart-container {{ background: white; border-radius: 8px; padding: 20px; box-shadow: 0 2px 8px rgba(0,0,0,0.1); }}
        canvas {{ width: {width}px !important; height: {height}px !important; }}
    </style>
</head>
<body>
    <div class="chart-container">
        <canvas id="chart"></canvas>
    </div>
    <script>
        const ctx = document.getElementById('chart').getContext('2d');
        new Chart(ctx, {config_json});
    </script>
</body>
</html>"""


def _financial_dashboard_html(
    project_name: str,
    metrics: Dict[str, Any],
    scenario_comparison: Optional[List[Dict]] = None,
) -> str:
    """生成财务指标仪表盘 HTML"""
    irr = metrics.get("project_irr", 0)
    eirr = metrics.get("equity_irr", 0)
    npv = metrics.get("project_npv", 0)
    enpv = metrics.get("equity_npv", 0)
    payback = metrics.get("payback_years", 0)
    lcoe = metrics.get("lcoe_per_kwh", 0)
    dscr = metrics.get("avg_dscr", 0)
    min_dscr = metrics.get("min_dscr", 0)

    # 判断指标好坏
    irr_ok = irr > 0.10
    npv_ok = npv > 0
    payback_ok = payback < 10
    dscr_ok = dscr > 1.3

    # 情景对比图表数据
    scenario_chart_data = ""
    if scenario_comparison:
        scenario_names = json.dumps([s["name"] for s in scenario_comparison])
        scenario_irrs = json.dumps([s.get("project_irr", 0) * 100 for s in scenario_comparison])
        scenario_npvs = json.dumps([s.get("project_npv", 0) / 1e6 for s in scenario_comparison])
        scenario_chart_data = f"""
        <div class="section">
            <h2>多情景对比</h2>
            <div class="chart-container">
                <canvas id="scenarioChart"></canvas>
            </div>
        </div>
        <script>
            new Chart(document.getElementById('scenarioChart'), {{
                type: 'bar',
                data: {{
                    labels: {scenario_names},
                    datasets: [
                        {{ label: '项目IRR (%)', data: {scenario_irrs}, backgroundColor: '#36A2EB' }},
                        {{ label: '项目NPV ($M)', data: {scenario_npvs}, backgroundColor: '#FF6384' }}
                    ]
                }},
                options: {{
                    responsive: true,
                    plugins: {{ legend: {{ position: 'bottom' }} }},
                    scales: {{ y: {{ beginAtZero: true }} }}
                }}
            }});
        </script>"""

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{project_name} - 财务仪表盘</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #f0f2f5; padding: 20px; color: #333; }}
        .dashboard {{ max-width: 1200px; margin: 0 auto; }}
        .header {{ background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 30px; border-radius: 12px; margin-bottom: 24px; }}
        .header h1 {{ font-size: 24px; margin-bottom: 8px; }}
        .header p {{ opacity: 0.9; font-size: 14px; }}
        .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(250px, 1fr)); gap: 16px; margin-bottom: 24px; }}
        .card {{ background: white; border-radius: 10px; padding: 20px; box-shadow: 0 2px 8px rgba(0,0,0,0.08); }}
        .card .label {{ font-size: 12px; color: #888; text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 8px; }}
        .card .value {{ font-size: 28px; font-weight: 700; }}
        .card .status {{ font-size: 12px; margin-top: 8px; padding: 4px 8px; border-radius: 4px; display: inline-block; }}
        .status-ok {{ background: #d4edda; color: #155724; }}
        .status-warn {{ background: #fff3cd; color: #856404; }}
        .section {{ background: white; border-radius: 10px; padding: 20px; margin-bottom: 24px; box-shadow: 0 2px 8px rgba(0,0,0,0.08); }}
        .section h2 {{ font-size: 18px; margin-bottom: 16px; color: #444; }}
        .chart-container {{ height: 350px; }}
    </style>
</head>
<body>
    <div class="dashboard">
        <div class="header">
            <h1>📊 {project_name}</h1>
            <p>财务模型分析仪表盘</p>
        </div>

        <div class="grid">
            <div class="card">
                <div class="label">项目 IRR</div>
                <div class="value" style="color: {'#28a745' if irr_ok else '#dc3545'};">{irr*100:.2f}%</div>
                <div class="status {'status-ok' if irr_ok else 'status-warn'}">{'✅ 高于基准' if irr_ok else '⚠️ 低于基准'}</div>
            </div>
            <div class="card">
                <div class="label">资本金 IRR</div>
                <div class="value" style="color: {'#28a745' if eirr > 0.15 else '#dc3545'};">{eirr*100:.2f}%</div>
            </div>
            <div class="card">
                <div class="label">项目 NPV</div>
                <div class="value" style="color: {'#28a745' if npv_ok else '#dc3545'};">${npv:,.0f}</div>
                <div class="status {'status-ok' if npv_ok else 'status-warn'}">{'✅ 正NPV' if npv_ok else '❌ 负NPV'}</div>
            </div>
            <div class="card">
                <div class="label">资本金 NPV</div>
                <div class="value">${enpv:,.0f}</div>
            </div>
            <div class="card">
                <div class="label">投资回收期</div>
                <div class="value" style="color: {'#28a745' if payback_ok else '#dc3545'};">{payback:.1f} 年</div>
                <div class="status {'status-ok' if payback_ok else 'status-warn'}">{'✅ 回收期短' if payback_ok else '⚠️ 回收期长'}</div>
            </div>
            <div class="card">
                <div class="label">LCOE</div>
                <div class="value">${lcoe*1000:.2f}/MWh</div>
            </div>
            <div class="card">
                <div class="label">平均 DSCR</div>
                <div class="value" style="color: {'#28a745' if dscr_ok else '#dc3545'};">{dscr:.2f}x</div>
                <div class="status {'status-ok' if dscr_ok else 'status-warn'}">{'✅ 偿债能力充足' if dscr_ok else '⚠️ 偿债风险'}</div>
            </div>
            <div class="card">
                <div class="label">最低 DSCR</div>
                <div class="value">{min_dscr:.2f}x</div>
            </div>
        </div>

        <div class="section">
            <h2>年度现金流</h2>
            <div class="chart-container">
                <canvas id="cashflowChart"></canvas>
            </div>
        </div>

        {scenario_chart_data}
    </div>

    <script>
        // 年度现金流图表（示例数据）
        const ctx = document.getElementById('cashflowChart').getContext('2d');
        new Chart(ctx, {{
            type: 'bar',
            data: {{
                labels: Array.from({{length: 25}}, (_, i) => `Y${{i+1}}`),
                datasets: [
                    {{ label: 'FCF (Equity)', data: Array.from({{length: 25}}, () => Math.random() * 2 + 1), backgroundColor: '#36A2EB' }},
                    {{ label: '累计FCF', data: Array.from({{length: 25}}, (_, i) => (i + 1) * 1.5), backgroundColor: '#FF6384', type: 'line', borderColor: '#FF6384', fill: false }}
                ]
            }},
            options: {{
                responsive: true,
                maintainAspectRatio: false,
                plugins: {{ legend: {{ position: 'bottom' }} }},
                scales: {{ y: {{ beginAtZero: true, title: {{ display: true, text: '金额 ($M)' }} }} }}
            }}
        }});
    </script>
</body>
</html>"""


def _sensitivity_chart_html(
    project_name: str,
    sensitivity_results: List[Dict],
    base_irr: float,
) -> str:
    """生成敏感性分析图表 HTML"""
    labels = [s["param_name"] for s in sensitivity_results]
    mins = [s["project_irr_range"]["min"] * 100 for s in sensitivity_results]
    maxs = [s["project_irr_range"]["max"] * 100 for s in sensitivity_results]
    base = base_irr * 100

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{project_name} - 敏感性分析</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #f5f5f5; padding: 20px; }}
        .container {{ max-width: 900px; margin: 0 auto; }}
        .header {{ background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 20px 30px; border-radius: 12px; margin-bottom: 24px; }}
        .header h1 {{ font-size: 20px; }}
        .chart-box {{ background: white; border-radius: 10px; padding: 20px; box-shadow: 0 2px 8px rgba(0,0,0,0.08); margin-bottom: 20px; }}
        .chart-box h2 {{ font-size: 16px; margin-bottom: 16px; color: #444; }}
        canvas {{ max-height: 500px; }}
        .summary {{ background: white; border-radius: 10px; padding: 20px; box-shadow: 0 2px 8px rgba(0,0,0,0.08); }}
        .summary table {{ width: 100%; border-collapse: collapse; }}
        .summary th, .summary td {{ padding: 10px 12px; text-align: left; border-bottom: 1px solid #eee; font-size: 14px; }}
        .summary th {{ background: #f8f9fa; font-weight: 600; color: #555; }}
        .summary tr:hover {{ background: #f8f9fa; }}
        .bar-min {{ color: #dc3545; }}
        .bar-max {{ color: #28a745; }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>📈 {project_name} - 敏感性分析</h1>
            <p>基准 IRR: {base:.2f}%</p>
        </div>

        <div class="chart-box">
            <h2>各变量对 IRR 的影响范围</h2>
            <canvas id="sensitivityChart"></canvas>
        </div>

        <div class="summary">
            <h2>详细数据</h2>
            <table>
                <tr>
                    <th>参数</th>
                    <th>最低 IRR</th>
                    <th>最高 IRR</th>
                    <th>波动幅度</th>
                </tr>
                {"".join(f"<tr><td>{s['param_name']}</td><td class='bar-min'>{s['project_irr_range']['min']*100:.2f}%</td><td class='bar-max'>{s['project_irr_range']['max']*100:.2f}%</td><td>{(s['project_irr_range']['max']-s['project_irr_range']['min'])*100:.2f}%</td></tr>" for s in sensitivity_results)}
            </table>
        </div>
    </div>

    <script>
        new Chart(document.getElementById('sensitivityChart'), {{
            type: 'bar',
            data: {{
                labels: {json.dumps(labels)},
                datasets: [
                    {{ label: '最低 IRR', data: {json.dumps(mins)}, backgroundColor: '#dc3545' }},
                    {{ label: '最高 IRR', data: {json.dumps(maxs)}, backgroundColor: '#28a745' }},
                    {{ label: '基准 IRR', data: {json.dumps([base] * len(labels))}, type: 'line', borderColor: '#FF6384', borderWidth: 2, pointRadius: 0, fill: false }}
                ]
            }},
            options: {{
                responsive: true,
                plugins: {{ legend: {{ position: 'bottom' }} }},
                scales: {{
                    y: {{ beginAtZero: true, title: {{ display: true, text: 'IRR (%)' }} }}
                }}
            }}
        }});
    </script>
</body>
</html>"""


def _comparison_table_html(
    title: str,
    columns: List[str],
    rows: List[List[str]],
    highlight_column: Optional[int] = None,
) -> str:
    """生成项目对比表格 HTML"""
    # 构建表头
    header_cells = "".join(f"<th>{col}</th>" for col in columns)
    
    # 构建表体
    body_rows = []
    for row in rows:
        cells = []
        for i, cell in enumerate(row):
            if highlight_column is not None and i == highlight_column:
                cells.append(f'<td class="highlight">{cell}</td>')
            else:
                cells.append(f"<td>{cell}</td>")
        body_rows.append(f"<tr>{''.join(cells)}</tr>")
    body_html = "".join(body_rows)

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{title}</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #f5f5f5; padding: 20px; }}
        .container {{ max-width: 1000px; margin: 0 auto; }}
        .header {{ background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 20px 30px; border-radius: 12px; margin-bottom: 24px; }}
        .header h1 {{ font-size: 20px; }}
        .table-wrapper {{ background: white; border-radius: 10px; overflow: hidden; box-shadow: 0 2px 8px rgba(0,0,0,0.08); }}
        table {{ width: 100%; border-collapse: collapse; }}
        th {{ background: #f8f9fa; padding: 14px 16px; text-align: left; font-weight: 600; color: #555; font-size: 13px; text-transform: uppercase; letter-spacing: 0.5px; border-bottom: 2px solid #dee2e6; }}
        td {{ padding: 12px 16px; border-bottom: 1px solid #eee; font-size: 14px; }}
        tr:hover {{ background: #f8f9fa; }}
        tr:last-child td {{ border-bottom: none; }}
        .highlight {{ background: #fff3cd !important; font-weight: 600; }}
        .best {{ color: #28a745; font-weight: 600; }}
        .worst {{ color: #dc3545; }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>📋 {title}</h1>
        </div>
        <div class="table-wrapper">
            <table>
                <thead>
                    <tr>
                        {header_cells}
                    </tr>
                </thead>
                <tbody>
                    {body_html}
                </tbody>
            </table>
        </div>
    </div>
</body>
</html>"""


# ═══════════════════════════════════════════════════════════════
# 工具处理函数
# ═══════════════════════════════════════════════════════════════

def handle_generate_chart_html(params: Dict[str, Any]) -> Dict[str, Any]:
    chart_type = params["chart_type"]
    title = params["title"]
    labels = params["labels"]
    datasets = params["datasets"]
    x_label = params.get("x_label", "")
    y_label = params.get("y_label", "")
    width = params.get("width", 800)
    height = params.get("height", 500)

    html = _chart_html_template(chart_type, title, labels, datasets, x_label, y_label, width, height)

    return {
        "html": html,
        "chart_type": chart_type,
        "title": title,
        "data_points": sum(len(ds["data"]) for ds in datasets),
        "note": "将此HTML保存为 .html 文件并在浏览器中打开以查看图表",
    }


def handle_generate_financial_dashboard(params: Dict[str, Any]) -> Dict[str, Any]:
    project_name = params["project_name"]
    metrics = params["metrics"]
    scenario_comparison = params.get("scenario_comparison")

    html = _financial_dashboard_html(project_name, metrics, scenario_comparison)

    return {
        "html": html,
        "project_name": project_name,
        "metrics_summary": {
            "project_irr": f"{metrics.get('project_irr', 0) * 100:.2f}%",
            "equity_irr": f"{metrics.get('equity_irr', 0) * 100:.2f}%",
            "project_npv": f"${metrics.get('project_npv', 0):,.0f}",
            "payback_years": f"{metrics.get('payback_years', 0):.1f} 年",
        },
        "note": "将此HTML保存为 .html 文件并在浏览器中打开以查看仪表盘",
    }


def handle_generate_sensitivity_chart(params: Dict[str, Any]) -> Dict[str, Any]:
    project_name = params["project_name"]
    sensitivity_results = params["sensitivity_results"]
    base_irr = params["base_irr"]

    html = _sensitivity_chart_html(project_name, sensitivity_results, base_irr)

    return {
        "html": html,
        "project_name": project_name,
        "base_irr": f"{base_irr * 100:.2f}%",
        "parameters_analyzed": len(sensitivity_results),
        "note": "将此HTML保存为 .html 文件并在浏览器中打开以查看敏感性分析图表",
    }


def handle_generate_comparison_table(params: Dict[str, Any]) -> Dict[str, Any]:
    title = params["title"]
    columns = params["columns"]
    rows = params["rows"]
    highlight_column = params.get("highlight_column")

    html = _comparison_table_html(title, columns, rows, highlight_column)

    return {
        "html": html,
        "title": title,
        "columns": len(columns),
        "rows": len(rows),
        "note": "将此HTML保存为 .html 文件并在浏览器中打开以查看对比表格",
    }


# ═══════════════════════════════════════════════════════════════
# MCP 协议处理
# ═══════════════════════════════════════════════════════════════

HANDLERS = {
    "generate_chart_html": handle_generate_chart_html,
    "generate_financial_dashboard": handle_generate_financial_dashboard,
    "generate_sensitivity_chart": handle_generate_sensitivity_chart,
    "generate_comparison_table": handle_generate_comparison_table,
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
    sys.stderr.write("MCP Data Visualization Server running on stdio\n")
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
