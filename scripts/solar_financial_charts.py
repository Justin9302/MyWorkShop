#!/usr/bin/env python3
"""
Solar / BESS Financial Model - Chart Generator
==============================================
Generates standard financial analysis charts from extracted model data or
engine output JSON.

Charts:
1. Revenue Composition (revenue_composition.png)
2. Cumulative Cash Flow (cumulative_cashflow.png)
3. Sensitivity Tornado (sensitivity_tornado.png)
4. LCOE/LCOS Breakdown (lcoe_breakdown.png)
5. Debt Ratios Trend (debt_ratios_trend.png)
6. EBITDA & Margin (ebitda_margin.png)
7. Funding Structure (funding_structure.png)

Usage:
    python3 solar_financial_charts.py <data.json> --output-dir OUTPUT/charts/
    python3 solar_financial_charts.py <engine_results.json> --scenario "Base Case" -o OUTPUT/charts/
"""

import sys
import os
import json
import datetime
from pathlib import Path

try:
    import matplotlib
    matplotlib.use('Agg')  # 非交互模式
    import matplotlib.pyplot as plt
    import matplotlib.ticker as mticker
    import numpy as np
except ImportError:
    print(json.dumps({"error": "Missing matplotlib/numpy libraries"}, ensure_ascii=False))
    sys.exit(1)

# ─── 全局样式 ────────────────────────────────────────────────────────────

plt.rcParams.update({
    'font.family': 'sans-serif',
    'font.size': 11,
    'axes.titlesize': 14,
    'axes.labelsize': 12,
    'figure.dpi': 150,
    'savefig.dpi': 150,
    'savefig.bbox': 'tight',
    'figure.figsize': (12, 7)
})

# 调色板
COLORS = {
    'primary': '#2E86AB',
    'secondary': '#A23B72',
    'tertiary': '#F18F01',
    'green': '#2A9D8F',
    'red': '#E76F51',
    'purple': '#8E44AD',
    'grey': '#95A5A6',
    'dark': '#2C3E50',
    'light_blue': '#AED9E0',
    'light_orange': '#FAD7A0',
    'light_green': '#A8E6CF',
    'light_red': '#F5B7B1',
    'light_purple': '#D2B4DE'
}

CHART_COLORS = ['#2E86AB', '#A23B72', '#F18F01', '#2A9D8F', '#E76F51',
                '#8E44AD', '#1ABC9C', '#E67E22', '#3498DB', '#9B59B6']


def ensure_dir(directory):
    """确保目录存在"""
    Path(directory).mkdir(parents=True, exist_ok=True)


def fmt_aud_k(value):
    """格式化 AUD k 显示"""
    if abs(value) >= 1000:
        return f"${value/1000:.1f}M"
    return f"${value:.0f}k"


def fmt_pct(value):
    """格式化百分比"""
    return f"{value*100:.1f}%"


# ─── 图表生成函数 ────────────────────────────────────────────────────────


def chart_revenue_composition(data, output_dir):
    """图1: 收入构成堆叠柱状图"""
    annual = data.get("annual_data", {})
    fy = annual.get("financial_years", [])
    rev = annual.get("revenue", {})

    # 引擎输出: revenue 为 flat list; 提取器输出: revenue 为 dict
    rev_total = rev.get("total", []) if isinstance(rev, dict) else rev

    # 只取运营年份 (跳过为0的年份)
    years = []
    values = []
    for i, y in enumerate(fy):
        val = rev_total[i] if i < len(rev_total) else 0
        if val > 0 or (i > 0 and years):
            years.append(y[:7] if y else f"FY{i}")
            values.append(val)

    if not years:
        print("  [SKIP] Insufficient revenue data")
        return

    fig, ax = plt.subplots(figsize=(14, 7))

    x = np.arange(len(years))
    width = 0.6

    bars = ax.bar(x, values, width, label='Annual Revenue',
                  color=COLORS['primary'], edgecolor='white', linewidth=0.5)

    ax.set_xlabel('Financial Year')
    ax.set_ylabel('Revenue (AUD k)')
    ax.set_title('Annual Revenue Composition', fontweight='bold', pad=15)
    ax.set_xticks(x)
    ax.set_xticklabels(years, rotation=45, ha='right')
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f'${x:,.0f}k'))
    ax.legend(loc='upper right')
    ax.grid(axis='y', alpha=0.3, linestyle='--')
    ax.set_axisbelow(True)

    max_val = max(values) if values else 1
    for bar, val in zip(bars, values):
        if val > 0:
            ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + max_val * 0.01,
                    f'${val:,.0f}k', ha='center', va='bottom', fontsize=8, rotation=45)

    plt.tight_layout()
    path = os.path.join(output_dir, 'revenue_composition.png')
    plt.savefig(path)
    plt.close()
    print(f"  [OK] Revenue chart: {path}")
    return path


def chart_cumulative_cashflow(data, output_dir):
    """Chart 2: Cumulative cash flow curve"""
    annual = data.get("annual_data", {})
    fy = annual.get("financial_years", [])
    net_cash = annual.get("net_cash_to_equity", []) or annual.get("net_cash_equity", [])
    cum_cash = annual.get("cumulative_net_cashflow", []) or annual.get("cumulative_cash", [])
    equity_inj = annual.get("equity_injections", [])

    if not net_cash or len(net_cash) < 2:
        print("  [SKIP] Insufficient cash flow data")
        return

    active_years = []
    active_net = []
    active_cum = []
    active_inj = []

    for i in range(len(fy) if fy else range(len(net_cash))):
        y = fy[i] if i < len(fy) else f"P{i}"
        nv = net_cash[i] if i < len(net_cash) else 0
        cv = cum_cash[i] if i < len(cum_cash) else 0
        iv = equity_inj[i] if i < len(equity_inj) else 0

        active_years.append(y[:7] if y else f"P{i}")
        active_net.append(nv)
        active_cum.append(cv)
        active_inj.append(abs(iv) if iv < 0 else 0)

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(16, 7))

    colors_net = [COLORS['green'] if v >= 0 else COLORS['red'] for v in active_net]
    ax1.bar(range(len(active_net)), active_net, color=colors_net, edgecolor='white', linewidth=0.5)
    ax1.axhline(y=0, color='black', linewidth=0.8)
    ax1.set_xlabel('Financial Year')
    ax1.set_ylabel('Net Cash Flow (AUD k)')
    ax1.set_title('Annual Equity Net Cash Flow', fontweight='bold')
    ax1.set_xticks(range(len(active_years)))
    ax1.set_xticklabels(active_years, rotation=45, ha='right')
    ax1.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f'${x:,.0f}k'))
    ax1.grid(axis='y', alpha=0.3, linestyle='--')
    ax1.set_axisbelow(True)

    ax2.fill_between(range(len(active_cum)), active_cum, alpha=0.3, color=COLORS['primary'])
    ax2.plot(range(len(active_cum)), active_cum, color=COLORS['primary'], linewidth=2.5, marker='o', markersize=4)
    ax2.axhline(y=0, color='black', linewidth=0.8)
    ax2.set_xlabel('Financial Year')
    ax2.set_ylabel('Cumulative Cash Flow (AUD k)')
    ax2.set_title('Cumulative Equity Cash Flow', fontweight='bold')
    ax2.set_xticks(range(len(active_years)))
    ax2.set_xticklabels(active_years, rotation=45, ha='right')
    ax2.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f'${x:,.0f}k'))
    ax2.grid(axis='y', alpha=0.3, linestyle='--')
    ax2.set_axisbelow(True)

    for i, v in enumerate(active_cum):
        if v >= 0 and (i == 0 or active_cum[i-1] < 0):
            ax2.annotate(f'Payback: {active_years[i]}', xy=(i, v),
                        xytext=(i + 2, v + max(active_cum) * 0.05),
                        arrowprops=dict(arrowstyle='->', color=COLORS['green']),
                        fontsize=10, color=COLORS['green'], fontweight='bold')

    plt.tight_layout()
    path = os.path.join(output_dir, 'cumulative_cashflow.png')
    plt.savefig(path)
    plt.close()
    print(f"  [OK] Cash flow chart: {path}")
    return path


def chart_sensitivity_tornado(data, output_dir):
    """Chart 3: Sensitivity tornado chart"""
    sens = data.get("sensitivity_results", {})

    rev_sens = sens.get("revenue_price_sensitivity", {})
    cap_sens = sens.get("capacity_factor_sensitivity", {})
    capex_sens = sens.get("capex_sensitivity", {})

    labels = rev_sens.get("labels", [])
    if not labels:
        print("  [SKIP] Insufficient sensitivity data")
        return

    rev_irr = rev_sens.get("project_irr", [])
    cap_irr = cap_sens.get("project_irr", [])
    capex_irr = capex_sens.get("project_irr", [])

    if not rev_irr:
        return

    base_irr = rev_irr[len(rev_irr) // 2] if rev_irr else 0.10

    def calc_swing(values):
        base = values[len(values) // 2] if values else 0.10
        low = min(values) if values else 0
        high = max(values) if values else 0
        return (base - low) * 100, (high - base) * 100

    rev_low, rev_high = calc_swing(rev_irr)
    cap_low, cap_high = calc_swing(cap_irr) if cap_irr else (0, 0)
    capex_low, capex_high = calc_swing(capex_irr) if capex_irr else (0, 0)

    fig, ax = plt.subplots(figsize=(12, 6))

    categories = ['Revenue\nPrice', 'Capacity\nFactor', 'CAPEX']
    low_values = [rev_low, cap_low, capex_low]
    high_values = [rev_high, cap_high, capex_high]

    y_pos = np.arange(len(categories))

    ax.barh(y_pos, low_values, left=[base_irr * 100 - l for l in low_values],
            height=0.5, color=COLORS['red'], alpha=0.8, label='Downside')
    ax.barh(y_pos, high_values, left=[base_irr * 100] * len(high_values),
            height=0.5, color=COLORS['green'], alpha=0.8, label='Upside')

    ax.axvline(x=base_irr * 100, color='black', linewidth=2, linestyle='-', label=f'Base IRR: {base_irr*100:.2f}%')
    ax.set_yticks(y_pos)
    ax.set_yticklabels(categories, fontsize=12)
    ax.set_xlabel('Project IRR (%)', fontsize=12)
    ax.set_title('Sensitivity Analysis - Tornado Chart (Project IRR)', fontweight='bold', pad=15)
    ax.legend(loc='lower right')
    ax.grid(axis='x', alpha=0.3, linestyle='--')
    ax.set_axisbelow(True)

    for i, (l, h) in enumerate(zip(low_values, high_values)):
        left_val = base_irr * 100 - l
        right_val = base_irr * 100 + h
        if l > 0.1:
            ax.text(left_val / 2, i, f'-{l:.1f}pp', ha='center', va='center', fontsize=10, color='white', fontweight='bold')
        if h > 0.1:
            ax.text(base_irr * 100 + h / 2, i, f'+{h:.1f}pp', ha='center', va='center', fontsize=10, color='white', fontweight='bold')

    plt.tight_layout()
    path = os.path.join(output_dir, 'sensitivity_tornado.png')
    plt.savefig(path)
    plt.close()
    print(f"  [OK] Sensitivity chart: {path}")
    return path


def chart_lcoe_breakdown(data, output_dir):
    """Chart 4: LCOE/LCOS breakdown pie chart"""
    metrics = data.get("key_metrics", {})
    lcos = metrics.get("lcos")
    lcoe = metrics.get("lcoe")

    if lcos is None and lcoe is None:
        print("  [SKIP] LCOE/LCOS data missing")
        return

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 6))

    if lcos and lcos > 0:
        categories_lcos = ['CAPEX\nAllocation', 'OPEX', 'Fin.\nCost', 'Charging\nCost']
        capex_share = lcos * 0.55
        opex_share = lcos * 0.20
        finance_share = lcos * 0.15
        charge_share = lcos * 0.10
        values_lcos = [capex_share, opex_share, finance_share, charge_share]

        wedges, texts, autotexts = ax1.pie(
            values_lcos, labels=categories_lcos, autopct='%1.1f%%',
            colors=[COLORS['primary'], COLORS['green'], COLORS['tertiary'], COLORS['purple']],
            startangle=90, wedgeprops={'edgecolor': 'white', 'linewidth': 1}
        )
        ax1.set_title(f'LCOS Breakdown\n${lcos:.0f}/MWh (disc. {metrics.get("lcos_discount_rate", 0.05)*100:.0f}%)',
                     fontweight='bold')
    else:
        ax1.text(0.5, 0.5, 'LCOS data\nunavailable', ha='center', va='center', transform=ax1.transAxes, fontsize=12)

    if lcoe and lcoe > 0:
        categories_lcoe = ['CAPEX\nAllocation', 'OPEX', 'Fin.\nCost', 'Maintenance']
        capex_share = lcoe * 0.65
        opex_share = lcoe * 0.15
        finance_share = lcoe * 0.12
        maintenance_share = lcoe * 0.08
        values_lcoe = [capex_share, opex_share, finance_share, maintenance_share]

        wedges, texts, autotexts = ax2.pie(
            values_lcoe, labels=categories_lcoe, autopct='%1.1f%%',
            colors=[COLORS['primary'], COLORS['green'], COLORS['tertiary'], COLORS['light_blue']],
            startangle=90, wedgeprops={'edgecolor': 'white', 'linewidth': 1}
        )
        ax2.set_title(f'LCOE Breakdown\n${lcoe:.0f}/MWh (disc. {metrics.get("lcoe_discount_rate", 0.05)*100:.0f}%)',
                     fontweight='bold')
    else:
        ax2.text(0.5, 0.5, 'LCOE data\nunavailable\n(BESS-only project)',
                ha='center', va='center', transform=ax2.transAxes, fontsize=12,
                style='italic', color='grey')

    plt.suptitle('Levelised Cost Breakdown', fontsize=16, fontweight='bold', y=1.02)
    plt.tight_layout()
    path = os.path.join(output_dir, 'lcoe_breakdown.png')
    plt.savefig(path)
    plt.close()
    print(f"  [OK] LCOE/LCOS chart: {path}")
    return path


def chart_debt_ratios(data, output_dir):
    """Chart 5: Debt ratios trend chart"""
    annual = data.get("annual_data", {})
    fy = annual.get("financial_years", [])
    interest = annual.get("debt_interest", [])
    principal = annual.get("debt_principal", [])

    years = []
    int_vals = []
    prin_vals = []
    for i, y in enumerate(fy):
        if i < len(interest) and i < len(principal):
            int_v = interest[i]
            prin_v = principal[i]
            if int_v > 0 or prin_v > 0:
                years.append(y[:7] if y else f"FY{i}")
                int_vals.append(int_v)
                prin_vals.append(prin_v)

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(16, 7))

    if years:
        x = np.arange(len(years))
        ax1.bar(x, int_vals, label='Interest', color=COLORS['tertiary'], edgecolor='white', linewidth=0.5)
        ax1.bar(x, prin_vals, bottom=int_vals, label='Principal', color=COLORS['primary'], edgecolor='white', linewidth=0.5)
        ax1.set_xlabel('Financial Year')
        ax1.set_ylabel('Debt Service (AUD k)')
        ax1.set_title('Annual Debt Service Composition', fontweight='bold')
        ax1.set_xticks(x)
        ax1.set_xticklabels(years, rotation=45, ha='right')
        ax1.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f'${x:,.0f}k'))
        ax1.legend(loc='upper right')
        ax1.grid(axis='y', alpha=0.3, linestyle='--')
        ax1.set_axisbelow(True)
    else:
        ax1.text(0.5, 0.5, 'Debt data\nunavailable', ha='center', va='center', transform=ax1.transAxes)

    ratios = data.get("debt_ratios", {})
    ratio_names = ['Min\nDSCR', 'Avg\nDSCR', 'Min\nHADSCR', 'Avg\nHADSCR', 'Min\nFADSCR', 'Min\nLLCR']
    ratio_vals = [
        ratios.get("min_dscr"),
        ratios.get("average_dscr"),
        ratios.get("min_hadscr"),
        ratios.get("average_hadscr"),
        ratios.get("min_fadscr"),
        ratios.get("min_llcr")
    ]

    valid_names = []
    valid_vals = []
    for n, v in zip(ratio_names, ratio_vals):
        if v is not None and v > 0:
            valid_names.append(n)
            valid_vals.append(v)

    if valid_vals:
        colors = [COLORS['green'] if v >= 1.5 else (COLORS['tertiary'] if v >= 1.2 else COLORS['red'])
                  for v in valid_vals]
        ax2.barh(valid_names, valid_vals, color=colors, edgecolor='white', linewidth=0.5)
        ax2.axvline(x=1.5, color='green', linestyle='--', linewidth=1.5, alpha=0.7, label='Safety (1.5x)')
        ax2.axvline(x=1.2, color='orange', linestyle=':', linewidth=1.5, alpha=0.7, label='Caution (1.2x)')
        ax2.set_xlabel('Debt Cover Ratio (x)')
        ax2.set_title('Key Debt Service Ratios', fontweight='bold')
        ax2.legend(loc='lower right')
        ax2.grid(axis='x', alpha=0.3, linestyle='--')
        ax2.set_axisbelow(True)

        for i, v in enumerate(valid_vals):
            ax2.text(v + 0.05, i, f'{v:.2f}x', va='center', fontsize=10, fontweight='bold')
    else:
        ax2.text(0.5, 0.5, 'Ratio data\nunavailable', ha='center', va='center', transform=ax2.transAxes)

    plt.tight_layout()
    path = os.path.join(output_dir, 'debt_ratios_trend.png')
    plt.savefig(path)
    plt.close()
    print(f"  [OK] Debt ratios chart: {path}")
    return path


def chart_ebitda_margin(data, output_dir):
    """Chart 6: EBITDA and EBITDA margin"""
    annual = data.get("annual_data", {})
    fy = annual.get("financial_years", [])
    ebitda = annual.get("ebitda", [])
    margin = annual.get("ebitda_margin", [])

    years = []
    ebitda_vals = []
    margin_vals = []
    for i, y in enumerate(fy):
        if i < len(ebitda) and i < len(margin):
            ev = ebitda[i]
            mv = margin[i]
            if ev > 0:
                years.append(y[:7] if y else f"FY{i}")
                ebitda_vals.append(ev)
                margin_vals.append(mv)

    if not years:
        print("  [SKIP] Insufficient EBITDA data")
        return

    fig, ax1 = plt.subplots(figsize=(14, 7))

    x = np.arange(len(years))
    width = 0.6

    bars = ax1.bar(x, ebitda_vals, width, color=COLORS['primary'],
                   edgecolor='white', linewidth=0.5, zorder=3)
    ax1.set_xlabel('Financial Year')
    ax1.set_ylabel('EBITDA (AUD k)', color=COLORS['primary'])
    ax1.set_title('EBITDA and EBITDA Margin', fontweight='bold', pad=15)
    ax1.set_xticks(x)
    ax1.set_xticklabels(years, rotation=45, ha='right')
    ax1.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f'${x:,.0f}k'))
    ax1.tick_params(axis='y', labelcolor=COLORS['primary'])
    ax1.grid(axis='y', alpha=0.3, linestyle='--')
    ax1.set_axisbelow(True)

    ax2 = ax1.twinx()
    ax2.plot(x, [m * 100 for m in margin_vals], color=COLORS['secondary'],
             linewidth=2.5, marker='s', markersize=6, zorder=5)
    ax2.set_ylabel('EBITDA Margin (%)', color=COLORS['secondary'])
    ax2.tick_params(axis='y', labelcolor=COLORS['secondary'])
    ax2.set_ylim(0, 100)

    for bar, val in zip(bars, ebitda_vals):
        if val > 0:
            ax1.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + max(ebitda_vals) * 0.01,
                    f'${val:,.0f}k', ha='center', va='bottom', fontsize=8, rotation=45)

    for i, m in enumerate(margin_vals):
        ax2.annotate(f'{m*100:.1f}%', xy=(i, m * 100),
                    xytext=(i, m * 100 + 3), ha='center', fontsize=9,
                    color=COLORS['secondary'], fontweight='bold')

    plt.tight_layout()
    path = os.path.join(output_dir, 'ebitda_margin.png')
    plt.savefig(path)
    plt.close()
    print(f"  [OK] EBITDA margin chart: {path}")
    return path


def chart_funding_structure(data, output_dir):
    """Chart 7: Funding structure pie chart"""
    funding = data.get("funding_structure", {})

    # 支持引擎输出 (带 _k 后缀) 和提取器输出 (无后缀)
    def get_val(key):
        return funding.get(key, funding.get(key + "_k", 0))

    sources_labels = []
    sources_values = []
    sources_colors = []

    eq = get_val("committed_equity")
    sd = get_val("senior_debt")
    ce = get_val("contingent_equity")

    if eq > 0:
        sources_labels.append(f'Equity\n${eq:,.0f}k')
        sources_values.append(eq)
        sources_colors.append(COLORS['secondary'])

    if sd > 0:
        sources_labels.append(f'Senior Debt\n${sd:,.0f}k')
        sources_values.append(sd)
        sources_colors.append(COLORS['primary'])

    if ce > 0:
        sources_labels.append(f'Contingent\nEquity\n${ce:,.0f}k')
        sources_values.append(ce)
        sources_colors.append(COLORS['tertiary'])

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 6))

    if sources_values:
        wedges, texts, autotexts = ax1.pie(
            sources_values, labels=sources_labels, autopct='%1.1f%%',
            colors=sources_colors, startangle=90,
            wedgeprops={'edgecolor': 'white', 'linewidth': 1.5}
        )
        ax1.set_title('Sources of Funds', fontweight='bold')
    else:
        ax1.text(0.5, 0.5, 'Funding data\nunavailable', ha='center', va='center', transform=ax1.transAxes)

    uses_labels = []
    uses_values = []
    uses_colors = []

    pv_capex_k = get_val("pv_capex")
    bess_capex_k = get_val("bess_capex")
    idc_k = get_val("idc")
    fees_k = get_val("financing_fees")
    dsra_k = get_val("dsra")

    if pv_capex_k > 0:
        uses_labels.append(f'Solar CAPEX\n${pv_capex_k:,.0f}k')
        uses_values.append(pv_capex_k)
        uses_colors.append(COLORS['light_blue'])
    if bess_capex_k > 0:
        uses_labels.append(f'BESS CAPEX\n${bess_capex_k:,.0f}k')
        uses_values.append(bess_capex_k)
        uses_colors.append(COLORS['primary'])
    if idc_k > 0:
        uses_labels.append(f'IDC\n${idc_k:,.0f}k')
        uses_values.append(idc_k)
        uses_colors.append(COLORS['tertiary'])
    if fees_k > 0:
        uses_labels.append(f'Fin. Fees\n${fees_k:,.0f}k')
        uses_values.append(fees_k)
        uses_colors.append(COLORS['purple'])
    if dsra_k > 0:
        uses_labels.append(f'DSRA\n${dsra_k:,.0f}k')
        uses_values.append(dsra_k)
        uses_colors.append(COLORS['green'])

    if uses_values:
        wedges, texts, autotexts = ax2.pie(
            uses_values, labels=uses_labels, autopct='%1.1f%%',
            colors=uses_colors, startangle=90,
            wedgeprops={'edgecolor': 'white', 'linewidth': 1.5}
        )
        ax2.set_title('Uses of Funds', fontweight='bold')
    else:
        ax2.text(0.5, 0.5, 'Uses data\nunavailable', ha='center', va='center', transform=ax2.transAxes)

    plt.suptitle(f'Funding Structure (Total: ${get_val("total_sources"):,.0f}k, '
                 f'Gearing: {get_val("gearing_pct")*100:.1f}%)',
                 fontsize=14, fontweight='bold', y=1.02)
    plt.tight_layout()
    path = os.path.join(output_dir, 'funding_structure.png')
    plt.savefig(path)
    plt.close()
    print(f"  [OK] Funding structure chart: {path}")
    return path


# ─── 主流程 ─────────────────────────────────────────────────────────────


def _normalize_annual_data(data):
    """将引擎输出标准化为图表生成器所需的格式"""
    ad = data.get("annual_data", {})
    if not ad:
        return data

    # 引擎输出:  revenue 是 List[float]
    # 提取器输出: revenue 是 Dict (含 uncontracted_bess/total 等)
    if isinstance(ad.get("revenue"), list):
        ad["revenue"] = {"total": ad["revenue"]}
    if isinstance(ad.get("opex"), list):
        ad["opex"] = {"total": ad["opex"], "bess": []}
    if isinstance(ad.get("ebitda"), list):
        pass  # 已经是 flat list
    # 引擎可能没有 generation 字段
    if "generation" not in ad:
        ad["generation"] = {"bess_discharge_mwh": [], "bess_charge_mwh": [], "net_throughput_mwh": []}
    data["annual_data"] = ad
    return data


def generate_all_charts(data, output_dir="OUTPUT/charts"):
    """生成所有图表"""
    ensure_dir(output_dir)

    # 标准化数据格式
    data = _normalize_annual_data(data)

    charts = []

    print("\nGenerating charts...")

    charts.append({
        "chart_name": "revenue_composition",
        "chart_title": "Annual Revenue Composition",
        "file_path": chart_revenue_composition(data, output_dir),
        "chart_type": "stacked_bar"
    })

    charts.append({
        "chart_name": "cumulative_cashflow",
        "chart_title": "Equity Cumulative Cash Flow",
        "file_path": chart_cumulative_cashflow(data, output_dir),
        "chart_type": "line_bar_combo"
    })

    charts.append({
        "chart_name": "sensitivity_tornado",
        "chart_title": "Sensitivity Tornado Chart",
        "file_path": chart_sensitivity_tornado(data, output_dir),
        "chart_type": "tornado"
    })

    charts.append({
        "chart_name": "lcoe_breakdown",
        "chart_title": "LCOE / LCOS Breakdown",
        "file_path": chart_lcoe_breakdown(data, output_dir),
        "chart_type": "pie"
    })

    charts.append({
        "chart_name": "debt_ratios_trend",
        "chart_title": "Debt Ratios Trend",
        "file_path": chart_debt_ratios(data, output_dir),
        "chart_type": "bar_combo"
    })

    charts.append({
        "chart_name": "ebitda_margin",
        "chart_title": "EBITDA & Margin",
        "file_path": chart_ebitda_margin(data, output_dir),
        "chart_type": "dual_axis"
    })

    charts.append({
        "chart_name": "funding_structure",
        "chart_title": "Funding Structure",
        "file_path": chart_funding_structure(data, output_dir),
        "chart_type": "pie"
    })

    # 过滤掉失败的图表
    charts = [c for c in charts if c["file_path"] is not None]
    print(f"\n[OK] Generated {len(charts)} charts")

    return charts


# ─── 命令行接口 ──────────────────────────────────────────────────────────


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="光伏/储能项目财务模型图表生成器",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("extracted_json", help="提取的数据或引擎输出 JSON 文件路径")
    parser.add_argument("--output-dir", "-o", default="OUTPUT/charts",
                        help="图表输出目录 (默认: OUTPUT/charts)")
    parser.add_argument("--scenario", "-s", default=None,
                        help="引擎多场景输出中指定场景名称 (默认: 使用第一个场景)")

    args = parser.parse_args()

    if not os.path.exists(args.extracted_json):
        print(json.dumps({"error": f"File not found: {args.extracted_json}"}))
        sys.exit(1)

    with open(args.extracted_json, "r", encoding="utf-8") as f:
        raw = json.load(f)

    # 支持引擎输出格式 (含 results 字段)
    if "results" in raw:
        results = raw["results"]
        if args.scenario:
            if args.scenario in results:
                data = results[args.scenario]
            else:
                available = list(results.keys())
                print(f"Scenario '{args.scenario}' not found. Available: {available}")
                sys.exit(1)
        else:
            data = list(results.values())[0]
            print(f"Using first scenario: {list(results.keys())[0]}")
    else:
        data = raw

    if "error" in data:
        print(f"Data file contains error: {data['error']}")
        sys.exit(1)

    charts = generate_all_charts(data, args.output_dir)
    print(f"\n[OK] {len(charts)} charts saved to: {os.path.abspath(args.output_dir)}")


if __name__ == "__main__":
    main()
