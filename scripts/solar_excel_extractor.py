#!/usr/bin/env python3
"""
光伏/储能项目财务模型 Excel 数据提取器
========================================
从 QEA/Core 风格的澳洲太阳能项目财务模型 (.xlsm/.xlsb) 中提取关键数据和指标。

支持特性:
- 读取 Summary 表中的核心财务指标 (IRR/NPV/回收期/LCOE)
- 提取年度报表数据 (AFS 表): 收入、OPEX、EBITDA、偿债
- 提取融资结构 (Sources & Uses)
- 提取生成量数据 (BESS throughput)
- 提取偿债比率 (DSCR/LLCR)
- 支持多个场景 (Scenarios 表)
- 基础数据完整性校验
- 输出为结构化 JSON

用法:
    python3 solar_excel_extractor.py <excel_file_path> [--scenario SCENARIO] [--output OUTPUT_JSON]
"""

import sys
import os
import json
import datetime
from decimal import Decimal
from pathlib import Path

try:
    import openpyxl
except ImportError:
    print(json.dumps({"error": "缺少 openpyxl 库，请运行: pip install openpyxl"}, ensure_ascii=False))
    sys.exit(1)

# ─── 工具函数 ──────────────────────────────────────────────────────────


def safe_float(v, default=0.0):
    """安全转换为浮点数"""
    if v is None:
        return default
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, (Decimal,)):
        return float(v)
    if isinstance(v, str):
        try:
            return float(v.replace(",", "").replace("$", "").replace(" ", ""))
        except (ValueError, AttributeError):
            return default
    return default


def safe_date(v):
    """安全转换为日期字符串"""
    if isinstance(v, datetime.datetime):
        return v.strftime("%Y-%m-%d")
    if isinstance(v, datetime.date):
        return v.strftime("%Y-%m-%d")
    if isinstance(v, str):
        return None  # 字符串不是日期
    return None


def find_header_row(ws, keyword, max_row=50):
    """在工作表中查找包含关键字的行号"""
    for i, row in enumerate(ws.iter_rows(min_row=1, max_row=max_row, values_only=True), 1):
        if row and row[0] and isinstance(row[0], str) and keyword.lower() in str(row[0]).lower():
            return i
    return None


def extract_row_by_label(ws, label, label_col=0, data_col=1, max_row=200):
    """按行首标签提取单值数据"""
    for i, row in enumerate(ws.iter_rows(min_row=1, max_row=max_row, values_only=True), 1):
        if row and row[label_col] and isinstance(row[label_col], str) and label.lower() in str(row[label_col]).lower():
            if len(row) > data_col:
                return {
                    "label": str(row[label_col]),
                    "value": safe_float(row[data_col]),
                    "unit": str(row[data_col + 1]) if len(row) > data_col + 1 and row[data_col + 1] else None
                }
    return None


# ─── 核心提取器 ─────────────────────────────────────────────────────────


class SolarExcelExtractor:
    """太阳能项目财务模型 Excel 提取器"""

    def __init__(self, file_path):
        self.file_path = Path(file_path)
        self.wb = None
        self.extraction_metadata = {
            "source_file": str(self.file_path),
            "extraction_timestamp": datetime.datetime.now().isoformat(),
            "engine_version": "0.1.0",
            "warnings": [],
            "errors": []
        }

    def open(self):
        """打开 Excel 文件（支持 .xlsm/.xlsx 和 .xlsb）"""
        ext = str(self.file_path).lower()
        if ext.endswith('.xlsb'):
            try:
                import pyxlsb
                # pyxlsb 返回的是 generator，转换为 openpyxl 兼容形式需特殊处理
                # 对于 xlsb，我们仍用 openpyxl 尝试，如果失败则用 pyxlsb 做有限读取
                self.wb = openpyxl.load_workbook(self.file_path, data_only=True)
                return True
            except Exception:
                # pyxlsb 没有直接的 openpyxl 兼容接口
                self.extraction_metadata["errors"].append(
                    "xlsb 格式暂不支持完整读取。请将文件另存为 .xlsm 格式后再试。"
                )
                return False
        try:
            self.wb = openpyxl.load_workbook(self.file_path, data_only=True)
            return True
        except Exception as e:
            self.extraction_metadata["errors"].append(f"无法打开文件: {str(e)}")
            return False

    def close(self):
        if self.wb:
            try:
                self.wb.close()
            except Exception:
                pass

    def get_sheet(self, name):
        """获取指定名称的工作表"""
        if name in self.wb.sheetnames:
            return self.wb[name]
        # 尝试模糊匹配
        for sn in self.wb.sheetnames:
            if sn.lower() == name.lower():
                return self.wb[sn]
        self.extraction_metadata["warnings"].append(f"未找到工作表: {name}")
        return None

    def extract_project_info(self, ws_summary):
        """提取项目基本信息（适配 QEA 模型布局）"""
        info = {
            "name": None, "location": None,
            "technology_type": "bess",
            "pv_capacity_mwp": 0, "bess_capacity_mw": 0,
            "bess_duration_hrs": 0, "bess_storage_mwh": 0,
            "construction_start": None, "construction_end": None,
            "operation_start": None, "operation_end": None,
            "operation_years": 0
        }

        if not ws_summary:
            return info

        # QEA 模型使用合并单元格，数据列偏移
        # R3 (idx2): name 在 B 列 (idx1)
        r3 = list(ws_summary.iter_rows(min_row=3, max_row=3, values_only=True))[0]
        if r3 and r3[1]:
            val = str(r3[1]).strip()
            info["name"] = val
            if '(' in val and ')' in val:
                loc = val[val.find('(') + 1:val.find(')')]
                info["location"] = loc

        # R14-R15 (idx13-14): Key dates
        r14 = list(ws_summary.iter_rows(min_row=14, max_row=14, values_only=True))[0]
        r15 = list(ws_summary.iter_rows(min_row=15, max_row=15, values_only=True))[0]
        # QEA: "Construction" / "Operation" 在 C 列 (idx2)
        if r14 and r14[2] and str(r14[2]).strip() == "Construction":
            info["construction_start"] = safe_date(r14[5]) if len(r14) > 5 else None
            info["construction_end"] = safe_date(r14[7]) if len(r14) > 7 else None
        if r15 and r15[2] and str(r15[2]).strip() == "Operation":
            info["operation_start"] = safe_date(r15[5]) if len(r15) > 5 else None
            info["operation_end"] = safe_date(r15[7]) if len(r15) > 7 else None

        # R35 (idx34): BESS capacity in H 列 (idx7)
        # R36 (idx35): BESS duration
        # R37 (idx36): BESS storage
        r35 = list(ws_summary.iter_rows(min_row=35, max_row=35, values_only=True))[0]
        r36 = list(ws_summary.iter_rows(min_row=36, max_row=36, values_only=True))[0]
        r37 = list(ws_summary.iter_rows(min_row=37, max_row=37, values_only=True))[0]

        if r35 and r35[2] and "installed capacity" in str(r35[2]).strip().lower():
            info["bess_capacity_mw"] = safe_float(r35[7]) if len(r35) > 7 else 0
        if r36 and r36[2] and "battery duration" in str(r36[2]).strip().lower():
            info["bess_duration_hrs"] = safe_float(r36[7]) if len(r36) > 7 else 0
        if r37 and r37[2] and "storage capacity" in str(r37[2]).strip().lower():
            info["bess_storage_mwh"] = safe_float(r37[7]) if len(r37) > 7 else 0

        # 计算运营年限
        if info["operation_start"] and info["operation_end"]:
            try:
                start = datetime.datetime.strptime(info["operation_start"], "%Y-%m-%d")
                end = datetime.datetime.strptime(info["operation_end"], "%Y-%m-%d")
                info["operation_years"] = max(1, int((end - start).days / 365))
            except (ValueError, TypeError):
                pass

        # 判断技术类型
        if info["pv_capacity_mwp"] > 0 and info["bess_capacity_mw"] > 0:
            info["technology_type"] = "solar_plus_bess"
        elif info["bess_capacity_mw"] > 0:
            info["technology_type"] = "bess"
        elif info["pv_capacity_mwp"] > 0:
            info["technology_type"] = "solar_pv"

        return info

    def extract_key_metrics(self, ws_summary):
        """提取核心财务指标"""
        metrics = {
            "project_irr_pre_tax": None, "project_irr_post_tax": None,
            "project_npv_pre_tax": None, "project_npv_pre_tax_rate": None,
            "project_npv_post_tax": None, "project_npv_post_tax_rate": None,
            "equity_irr": None, "equity_npv": None, "equity_npv_rate": None,
            "equity_payback_discounted": None, "equity_payback_undiscounted": None,
            "lcoe": None, "lcoe_discount_rate": None,
            "lcos": None, "lcos_discount_rate": None,
            "total_project_cost": None, "total_lifetime_revenue": None,
            "total_lifetime_ebitda": None, "currency": "AUD"
        }

        if not ws_summary:
            return metrics

        # 扫描 Summary 表的行
        for i, row in enumerate(ws_summary.iter_rows(min_row=10, max_row=125, values_only=True), 1):
            real_row = i  # iter_rows 从1开始
            if not row:
                continue
            row_values = [v for v in row if v is not None]

            for j, val in enumerate(row_values):
                if not isinstance(val, str):
                    continue
                v = val.strip()

                # 项目 IRR
                if "project irr (post-tax)" in v.lower():
                    metrics["project_irr_post_tax"] = safe_float(row_values[j + 2]) if len(row_values) > j + 2 else None
                elif "project irr (pre-tax)" in v.lower():
                    metrics["project_irr_pre_tax"] = safe_float(row_values[j + 2]) if len(row_values) > j + 2 else None

                # 项目 NPV
                elif "project npv (post-tax" in v.lower():
                    rate_str = v.split("at")[-1].replace(")", "").replace("%", "").strip() if "at" in v else None
                    metrics["project_npv_post_tax"] = safe_float(row_values[j + 2]) if len(row_values) > j + 2 else None
                    if rate_str:
                        try:
                            metrics["project_npv_post_tax_rate"] = float(rate_str) / 100.0
                        except ValueError:
                            pass
                elif "project npv (pre-tax" in v.lower():
                    rate_str = v.split("at")[-1].replace(")", "").replace("%", "").strip() if "at" in v else None
                    metrics["project_npv_pre_tax"] = safe_float(row_values[j + 2]) if len(row_values) > j + 2 else None
                    if rate_str:
                        try:
                            metrics["project_npv_pre_tax_rate"] = float(rate_str) / 100.0
                        except ValueError:
                            pass

                # 股权 IRR
                elif "equity irr" in v.lower():
                    metrics["equity_irr"] = safe_float(row_values[j + 2]) if len(row_values) > j + 2 else None

                # 股权 NPV
                elif "equity npv (at" in v.lower():
                    rate_str = v.split("at")[-1].replace(")", "").replace("%", "").strip() if "at" in v else None
                    metrics["equity_npv"] = safe_float(row_values[j + 2]) if len(row_values) > j + 2 else None
                    if rate_str:
                        try:
                            metrics["equity_npv_rate"] = float(rate_str) / 100.0
                        except ValueError:
                            pass

                # 回收期
                elif "equity payback date (discounted" in v.lower():
                    metrics["equity_payback_discounted"] = safe_date(row_values[j + 2]) if len(row_values) > j + 2 else None
                elif "equity payback date (undiscounted" in v.lower():
                    metrics["equity_payback_undiscounted"] = safe_date(row_values[j + 2]) if len(row_values) > j + 2 else None

                # LCOE/LCOS
                elif v.startswith("LCOE") or "lcoe" in v.lower():
                    metrics["lcoe"] = safe_float(row_values[j + 2]) if len(row_values) > j + 2 else None
                    if "at" in v:
                        try:
                            rate_str = v.split("at")[-1].replace(")", "").replace("%", "").strip()
                            metrics["lcoe_discount_rate"] = float(rate_str) / 100.0
                        except ValueError:
                            pass
                elif v.startswith("LCOS") or "lcos" in v.lower():
                    metrics["lcos"] = safe_float(row_values[j + 2]) if len(row_values) > j + 2 else None
                    if "at" in v:
                        try:
                            rate_str = v.split("at")[-1].replace(")", "").replace("%", "").strip()
                            metrics["lcos_discount_rate"] = float(rate_str) / 100.0
                        except ValueError:
                            pass

        # 从 Sources & Uses 提取总项目成本
        for i, row in enumerate(ws_summary.iter_rows(min_row=25, max_row=45, values_only=True), 1):
            if not row or not row[0]:
                continue
            r0 = str(row[0]).strip().lower()
            # BESS capex 行
            if "bess capex" in r0 and len(row) >= 4:
                metrics["total_project_cost"] = metrics.get("total_project_cost", 0) + safe_float(row[3])
            # 总 uses 行 (通常是最后一行的汇总值 103268)
            if len(row) >= 3 and row[1] and safe_float(row[1]) > 90000:
                metrics["total_project_cost"] = safe_float(row[1])

        # 总收入 (R84 - Total revenue 的总计)
        for i, row in enumerate(ws_summary.iter_rows(min_row=80, max_row=85, values_only=True), 1):
            if row and row[0] and isinstance(row[0], str) and row[0].strip() == "Total":
                # 第一个非日期非标签的值是总和
                vals = [safe_float(v) for v in row[1:] if v is not None]
                if vals:
                    metrics["total_lifetime_revenue"] = sum(v for v in vals if v > 0)

        # 总 EBITDA (R99)
        for i, row in enumerate(ws_summary.iter_rows(min_row=97, max_row=101, values_only=True), 1):
            if row and row[0] and isinstance(row[0], str) and "ebitda" in row[0].lower() and "margin" not in row[0].lower():
                vals = [safe_float(v) for v in row[1:] if v is not None]
                if vals:
                    metrics["total_lifetime_ebitda"] = sum(v for v in vals if v > 0)
                    break

        return metrics

    def extract_annual_data(self, ws_summary):
        """从 Summary 表提取年度数据（适配 QEA 合并单元格布局）"""
        data = {
            "financial_years": [],
            "revenue": {"contracted_pv": [], "contracted_bess": [],
                        "uncontracted_pv": [], "uncontracted_bess": [], "total": []},
            "opex": {"pv_fixed": [], "pv_variable": [], "bess": [], "total": []},
            "maintenance_capex": [],
            "ebitda": [], "ebitda_margin": [],
            "debt_interest": [], "debt_principal": [],
            "equity_injections": [], "equity_returns": [],
            "net_cash_to_equity": [], "cumulative_net_cashflow": [],
            "generation": {"bess_discharge_mwh": [], "bess_charge_mwh": [], "net_throughput_mwh": []}
        }

        if not ws_summary:
            return data

        # QEA 模型: 数据标签在 C 列 (idx=2), 数据从 G 列 (idx=6) 开始
        LABEL_COL = 2
        DATA_COL_START = 6

        # 读取 FY 日期 (R48, col 6+)
        row48 = list(ws_summary.iter_rows(min_row=48, max_row=48, values_only=True))[0]
        fy_dates = []
        if row48:
            for j in range(DATA_COL_START, len(row48)):
                v = row48[j]
                if v is not None:
                    ds = safe_date(v)
                    if ds:
                        fy_dates.append(ds)
        data["financial_years"] = fy_dates
        n_years = len(fy_dates)

        if n_years == 0:
            return data

        def extract_row(label_part, row_num):
            """提取指定行的年度数据 (标签在 LABEL_COL 列)"""
            row = list(ws_summary.iter_rows(min_row=row_num, max_row=row_num, values_only=True))[0]
            label = str(row[LABEL_COL]).strip().lower() if len(row) > LABEL_COL and row[LABEL_COL] else ""
            if label_part.lower() in label:
                vals = []
                for c in range(DATA_COL_START, DATA_COL_START + n_years):
                    vals.append(safe_float(row[c]) if c < len(row) and row[c] is not None else 0)
                return vals
            return []

        # 发电量
        vals = extract_row("BESS discharge", 65)
        if vals and any(v != 0 for v in vals[1:]):  # 跳过可能的总计列
            data["generation"]["bess_discharge_mwh"] = vals

        vals = extract_row("BESS charge", 66)
        if vals and any(v != 0 for v in vals[1:]):
            data["generation"]["bess_charge_mwh"] = vals

        vals = extract_row("Net throughput", 67)
        if vals and any(v != 0 for v in vals[1:]):
            data["generation"]["net_throughput_mwh"] = vals

        # 收入
        vals = extract_row("BESS (uncontracted)", 78)
        if vals and any(v != 0 for v in vals[1:]):
            data["revenue"]["uncontracted_bess"] = vals

        vals = extract_row("Total", 84)
        if vals and any(v != 0 for v in vals[1:]):
            # 确保不是 "Total Opex" 或其他 Total 行
            row84 = list(ws_summary.iter_rows(min_row=84, max_row=84, values_only=True))[0]
            label84 = str(row84[LABEL_COL]).strip().lower() if len(row84) > LABEL_COL and row84[LABEL_COL] else ""
            if label84.strip() == "total":
                data["revenue"]["total"] = vals
            # BESS 行
            if "bess" in label84:
                data["revenue"]["uncontracted_bess"] = vals  # 后备

        # 营业支出
        vals = extract_row("BESS Opex", 93)
        if vals and any(v != 0 for v in vals[1:]):
            data["opex"]["bess"] = vals

        vals = extract_row("Total Opex", 95)
        if vals and any(v != 0 for v in vals[1:]):
            data["opex"]["total"] = vals

        vals = extract_row("Maintenance capex", 97)
        if vals and any(v != 0 for v in vals[1:]):
            data["maintenance_capex"] = vals

        # EBITDA
        vals = extract_row("EBITDA", 99)
        if vals and any(v != 0 for v in vals[1:]):
            row99 = list(ws_summary.iter_rows(min_row=99, max_row=99, values_only=True))[0]
            label99 = str(row99[LABEL_COL]).strip().lower() if len(row99) > LABEL_COL and row99[LABEL_COL] else ""
            if "margin" not in label99:
                data["ebitda"] = vals

        vals = extract_row("EBITDA margin", 100)
        if vals and any(v != 0 for v in vals[1:]):
            data["ebitda_margin"] = vals

        # 偿债
        vals = extract_row("Interest", 108)
        if vals and any(v != 0 for v in vals[1:]):
            data["debt_interest"] = vals

        vals = extract_row("Principal", 109)
        if vals and any(v != 0 for v in vals[1:]):
            data["debt_principal"] = vals

        # 股权现金流
        vals = extract_row("Injections", 115)
        if vals and any(v != 0 for v in vals[1:]):
            data["equity_injections"] = vals

        vals = extract_row("Returns", 116)
        if vals and any(v != 0 for v in vals[1:]):
            data["equity_returns"] = vals

        vals = extract_row("Net cash to equity", 117)
        if vals and any(v != 0 for v in vals[1:]):
            data["net_cash_to_equity"] = vals

        # 计算累计现金流
        if data["net_cash_to_equity"]:
            cum = 0
            for v in data["net_cash_to_equity"]:
                cum += v
                data["cumulative_net_cashflow"].append(cum)

        return data

    def extract_funding_structure(self, ws_summary):
        """提取融资结构（适配 QEA 布局）"""
        funding = {
            "total_sources": 0, "total_uses": 0,
            "committed_equity": 0, "committed_equity_pct": 0,
            "senior_debt": 0, "senior_debt_pct": 0,
            "contingent_equity": 0,
            "pv_capex": 0, "bess_capex": 0,
            "idc_senior_debt": 0, "financing_fees": 0,
            "dsra_initial": 0, "gearing_pct": 0
        }

        if not ws_summary:
            return funding

        # QEA 模型: Sources 标签在 J 列(idx=9), 值在 N(idx=13)-O(idx=14) 列
        # R30 (idx29): Committed equity
        r30 = list(ws_summary.iter_rows(min_row=30, max_row=30, values_only=True))[0]
        if r30 and r30[9] and "committed equity" in str(r30[9]).strip().lower():
            funding["committed_equity_pct"] = safe_float(r30[13]) if len(r30) > 13 else 0
            funding["committed_equity"] = safe_float(r30[14]) if len(r30) > 14 else 0

        # R31 (idx30): Senior debt
        r31 = list(ws_summary.iter_rows(min_row=31, max_row=31, values_only=True))[0]
        if r31 and r31[9] and "senior debt" in str(r31[9]).strip().lower():
            funding["senior_debt_pct"] = safe_float(r31[13]) if len(r31) > 13 else 0
            funding["senior_debt"] = safe_float(r31[14]) if len(r31) > 14 else 0

        # R32 (idx31): Contingent equity
        r32 = list(ws_summary.iter_rows(min_row=32, max_row=32, values_only=True))[0]
        if r32 and r32[9] and "contingent equity" in str(r32[9]).strip().lower():
            funding["contingent_equity"] = safe_float(r32[14]) if len(r32) > 14 else 0

        # Uses: 标签在 J 列, 百分比在 N 列, 金额在 O 列
        # R37: BESS capex
        r37 = list(ws_summary.iter_rows(min_row=37, max_row=37, values_only=True))[0]
        if r37 and r37[9] and "bess capex" in str(r37[9]).strip().lower():
            funding["bess_capex_pct"] = safe_float(r37[13]) if len(r37) > 13 else 0
            funding["bess_capex"] = safe_float(r37[14]) if len(r37) > 14 else 0

        # R35: PV capex
        r35 = list(ws_summary.iter_rows(min_row=35, max_row=35, values_only=True))[0]
        if r35 and r35[9] and "pv capex" in str(r35[9]).strip().lower():
            funding["pv_capex"] = safe_float(r35[14]) if len(r35) > 14 else 0

        # R38: IDC
        r38 = list(ws_summary.iter_rows(min_row=38, max_row=38, values_only=True))[0]
        if r38 and r38[9] and "interest during construction" in str(r38[9]).strip().lower():
            funding["idc_senior_debt"] = safe_float(r38[14]) if len(r38) > 14 else 0

        # R39: Financing fees
        r39 = list(ws_summary.iter_rows(min_row=39, max_row=39, values_only=True))[0]
        if r39 and r39[9] and "financing fees" in str(r39[9]).strip().lower():
            funding["financing_fees"] = safe_float(r39[14]) if len(r39) > 14 else 0

        # R40: DSRA
        r40 = list(ws_summary.iter_rows(min_row=40, max_row=40, values_only=True))[0]
        if r40 and r40[9] and "dsra" in str(r40[9]).strip().lower():
            funding["dsra_initial"] = safe_float(r40[14]) if len(r40) > 14 else 0

        funding["total_sources"] = (funding["committed_equity"] + funding["senior_debt"] +
                                    funding["contingent_equity"])
        funding["total_uses"] = (funding["pv_capex"] + funding["bess_capex"] +
                                 funding["idc_senior_debt"] + funding["financing_fees"] +
                                 funding["dsra_initial"])

        # Gearing - R15 的 K 列附近
        r15 = list(ws_summary.iter_rows(min_row=15, max_row=15, values_only=True))[0]
        if r15:
            for j, cell in enumerate(r15):
                if cell and isinstance(cell, str) and "gearing" in cell.strip().lower():
                    if len(r15) > j + 2:
                        funding["gearing_pct"] = safe_float(r15[j + 2])
                    break

        return funding

    def extract_debt_ratios(self, ws_summary):
        """提取偿债比率"""
        ratios = {
            "min_dscr": None, "average_dscr": None,
            "min_hadscr": None, "average_hadscr": None,
            "min_fadscr": None, "average_fadscr": None,
            "min_llcr": None, "llcr": None
        }
        if not ws_summary:
            return ratios

        # 读取所有行
        all_rows = []
        for row in ws_summary.iter_rows(min_row=1, max_row=30, values_only=True):
            all_rows.append([v for v in row])

        # 在 R18-R25 (索引17-24) 范围内查找比率
        for idx in range(17, min(26, len(all_rows))):
            row = all_rows[idx]
            if not row:
                continue
            for j, cell in enumerate(row):
                if not isinstance(cell, str):
                    continue
                v = cell.strip().lower()

                # 比率值在右侧2个位置 (j+2)
                val_fn = lambda: safe_float(row[j + 2]) if len(row) > j + 2 and row[j + 2] is not None else None

                if v in ("minimum dscr", "min dscr"):
                    ratios["min_dscr"] = val_fn()
                elif v in ("average dscr", "avg dscr"):
                    ratios["average_dscr"] = val_fn()
                elif "minimum hadscr" in v or "min hadscr" in v:
                    ratios["min_hadscr"] = val_fn()
                elif "average hadscr" in v or "avg hadscr" in v:
                    ratios["average_hadscr"] = val_fn()
                elif "minimum fadscr" in v or "min fadscr" in v:
                    ratios["min_fadscr"] = val_fn()
                elif "average fadscr" in v or "avg fadscr" in v:
                    ratios["average_fadscr"] = val_fn()
                elif "minimum llcr" in v or "min llcr" in v:
                    ratios["min_llcr"] = val_fn()
                elif v.strip() in ("llcr",) and "minimum" not in v and "min" != v.strip():
                    ratios["llcr"] = val_fn()

        return ratios

    def get_scenarios(self, ws_scenarios):
        """获取可用场景列表"""
        scenarios = []
        if not ws_scenarios:
            return scenarios

        all_rows = []
        for row in ws_scenarios.iter_rows(min_row=1, max_row=30, values_only=True):
            all_rows.append([v for v in row])

        # R9 (索引8): Base Case 行包含场景名称
        if len(all_rows) >= 10:
            row9 = all_rows[8]
            for j, val in enumerate(row9):
                if j > 0 and val and isinstance(val, str) and val.strip():
                    scenarios.append(val.strip())
        return scenarios

    def extract_scenario_info(self, ws_summary):
        """提取当前场景信息"""
        info = {"scenario_name": None, "scenario_description": None, "is_active": True}
        if not ws_summary:
            return info
        for i, row in enumerate(ws_summary.iter_rows(min_row=1, max_row=10, values_only=True), 1):
            if row and row[0] and isinstance(row[0], str) and "scenario" in row[0].lower():
                info["scenario_name"] = str(row[0]).strip()
                break
        return info

    def check_model_vintage(self):
        """检测模型文件年代，判断数据是否可能过时"""
        vintage = {
            "model_year": None,
            "is_outdated": False,
            "vintage_warnings": [],
            "detected_from": "filename"
        }

        fname = str(self.file_path.name)

        # 从文件名提取年份
        import re
        year_matches = re.findall(r'(?:19|20)\d{2}', fname)
        if year_matches:
            years = [int(y) for y in year_matches]
            model_year = min(years)  # 取最早年份
            vintage["model_year"] = model_year

            current_year = 2026
            age = current_year - model_year

            if model_year <= 2020:
                vintage["is_outdated"] = True
                vintage["vintage_warnings"].append(
                    f"模型文件年代检测：文件名含 {model_year} 年标记，距今约 {age} 年。"
                    f"{model_year} 年以来的市场变化：BESS CAPEX 下降约 40-50%，"
                    f"光伏 CAPEX 下降约 30-40%。模型中的成本参数可能严重过时，"
                    f"建议使用当前市场数据重新评估。"
                )
            elif model_year <= 2022:
                vintage["vintage_warnings"].append(
                    f"模型文件为 {model_year} 年版本（{age} 年前），"
                    f"成本参数可能部分过时，建议与当前市场报价核对。"
                )
        else:
            vintage["detected_from"] = "none"

        return vintage

    def extract_tax_depreciation(self, ws_inputs, ws_td):
        """提取税收与折旧相关假设"""
        tax_info = {
            "tax_rate": None,
            "tax_rate_source": None,
            "depreciation_method": None,
            "depreciation_periods": {},
            "depreciation_rates": {},
            "asset_categories": [],
            "tax_losses_cumulated": None,
            "imputation_credits": None,
            "franking_assumption": None,
            "warnings": []
        }

        if ws_inputs:
            for i, row in enumerate(ws_inputs.iter_rows(min_row=1, max_row=544, values_only=True), 1):
                if not row:
                    continue
                # 检查所有单元格是否有 tax rate 标记
                for j, cell in enumerate(row):
                    if cell and isinstance(cell, str):
                        cell_lower = cell.strip().lower()
                        if "tax rate" in cell_lower or "corporate tax" in cell_lower:
                            # 查找右侧的数据值
                            for k in range(j + 1, min(j + 5, len(row))):
                                v = row[k]
                                if isinstance(v, (int, float)):
                                    if 0 < v < 1:
                                        tax_info["tax_rate"] = float(v)
                                        tax_info["tax_rate_source"] = cell.strip()
                                        break
                                    elif 1 < v < 100:
                                        tax_info["tax_rate"] = float(v) / 100.0
                                        tax_info["tax_source"] = cell.strip()
                                        break

                # 列 A 标签匹配
                if row[0] and isinstance(row[0], str):
                    r0 = str(row[0]).strip().lower()
                    if "tax rate" in r0 or "corporate tax" in r0:
                        for j, v in enumerate(row):
                            if isinstance(v, (int, float)) and 0 < v < 1:
                                tax_info["tax_rate"] = float(v)
                                tax_info["tax_rate_source"] = str(row[0]).strip()
                                break
                            elif isinstance(v, (int, float)) and 1 < v < 100:
                                tax_info["tax_rate"] = float(v) / 100.0
                                tax_info["tax_rate_source"] = str(row[0]).strip()
                                break

        if ws_td:
            # 折旧方法 (R62)
            row62 = list(ws_td.iter_rows(min_row=62, max_row=62, values_only=True))[0]
            if row62 and row62[5] and isinstance(row62[5], str):
                tax_info["depreciation_method"] = row62[5].strip()
                if tax_info["depreciation_method"] == "SL":
                    tax_info["depreciation_method"] = "Straight Line (Prime Cost)"
                elif tax_info["depreciation_method"] == "DV":
                    tax_info["depreciation_method"] = "Diminishing Value"

            # 折旧率 (R49)
            row49 = list(ws_td.iter_rows(min_row=49, max_row=49, values_only=True))[0]
            if row49 and row49[5] and isinstance(row49[5], (int, float)):
                rate_pm = float(row49[5])
                rate_pa = rate_pm * 12
                effective_life = int(round(1.0 / rate_pa)) if rate_pa > 0 else 0
                tax_info["depreciation_rates"]["short_term_monthly"] = rate_pm
                tax_info["depreciation_rates"]["short_term_annual"] = rate_pa
                tax_info["depreciation_rates"]["short_term_effective_life_years"] = effective_life

            # 资产类别（QEA 模型 T&D: 标签在 D 列 = index 3, 分类在 F 列 = index 5）
            def read_asset_row(row_num, label_col=3, cat_col=5, data_start=9):
                """读取 T&D 表中的资产行"""
                row = list(ws_td.iter_rows(min_row=row_num, max_row=row_num, values_only=True))[0]
                if len(row) > label_col and row[label_col]:
                    label = str(row[label_col]).strip()
                    vals = [safe_float(v) for v in row[data_start:] if v is not None and isinstance(v, (int, float))]
                    total_val = round(sum(v for v in vals), 2)
                    cat = str(row[cat_col]) if len(row) > cat_col and row[cat_col] else ""
                    return {"name": label, "category": cat, "capex_during_construction": total_val}
                return None

            for r in [28, 29, 30, 31, 32]:
                cat = read_asset_row(r)
                if cat and cat["capex_during_construction"] > 0:
                    tax_info["asset_categories"].append(cat)

            # 读取折旧周期 (R52 - Periods to include)
            r52 = list(ws_td.iter_rows(min_row=52, max_row=52, values_only=True))[0]
            dep_periods_months = safe_float(r52[5]) if len(r52) > 5 and r52[5] else 0
            if dep_periods_months > 0:
                dep_periods_years = int(round(dep_periods_months / 12))
                tax_info["depreciation_periods"]["short_term_years"] = dep_periods_years
                tax_info["depreciation_rates"]["short_term_effective_life_years"] = dep_periods_years

            # 校验并生成警告
            dep_life = (tax_info.get("depreciation_periods", {}).get("short_term_years") or
                        tax_info.get("depreciation_rates", {}).get("short_term_effective_life_years", 0))

            if dep_life > 0:
                # BESS 长期资产折旧年限校验
                for cat in tax_info["asset_categories"]:
                    if "long" in cat["name"].lower() and cat.get("capex_during_construction", 0) > 0:
                        tax_info["depreciation_rates"]["long_term_effective_life_years"] = dep_life
                        if cat["capex_during_construction"] > 0:
                            tax_info["depreciation_rates"]["long_term_annual"] = round(1.0 / dep_life, 4) if dep_life > 0 else 0

                        ato_life = 15  # ATO 建议储能有效寿命
                        if dep_life < ato_life:
                            tax_info["warnings"].append(
                                f"长期资产折旧年限仅 {dep_life} 年（BESS 等储能资产），"
                                f"低于 ATO 建议有效寿命 {ato_life} 年。"
                                f"若模型中 BESS 按 {dep_life} 年折旧，将产生税会差异，需要递延税项调整。"
                            )
                        elif dep_life > 25:
                            tax_info["warnings"].append(
                                f"长期资产折旧年限 {dep_life} 年，超过 ATO 建议范围。请核实。"
                            )

            # 税率校验
            if tax_info.get("tax_rate"):
                tr = tax_info["tax_rate"]
                if abs(tr - 0.30) > 0.01 and abs(tr - 0.25) > 0.01:
                    tax_info["warnings"].append(
                        f"模型假设税率 {tr*100:.1f}% 与标准税率不一致（大型企业 30%，小企业 25%）。请确认实体类型。"
                    )

        return tax_info

    def compute_sensitivity(self, metrics):
        """基于模型参数计算敏感性分析（简化版，基于比例）"""
        sensitivity = {
            "revenue_price_sensitivity": {"labels": [], "project_irr": [], "equity_irr": [], "npv": []},
            "capacity_factor_sensitivity": {"labels": [], "project_irr": [], "equity_irr": [], "npv": []},
            "capex_sensitivity": {"labels": [], "project_irr": [], "equity_irr": [], "npv": []},
            "discount_rate_sensitivity": {"labels": [], "project_npv": [], "equity_npv": []}
        }

        base_irr = metrics.get("project_irr_post_tax", 0.10)
        base_equity_irr = metrics.get("equity_irr", 0.13)
        base_npv = metrics.get("project_npv_post_tax", 40000)
        base_equity_npv = metrics.get("equity_npv", 28000)
        base_discount = metrics.get("project_npv_post_tax_rate", 0.06)

        # Revenue price sensitivity
        for pct in [-20, -15, -10, -5, 0, 5, 10, 15, 20]:
            factor = 1 + pct / 100.0
            sensitivity["revenue_price_sensitivity"]["labels"].append(f"{pct:+.0f}%")
            # Revenue impact ~= factor on IRR (非精确，用于示意)
            irr_impact = (base_irr - 0.05) * factor + 0.05
            sensitivity["revenue_price_sensitivity"]["project_irr"].append(round(irr_impact, 4))
            sensitivity["revenue_price_sensitivity"]["equity_irr"].append(round(base_equity_irr * factor, 4))
            sensitivity["revenue_price_sensitivity"]["npv"].append(round(base_npv * factor, 2))

        # Capacity factor sensitivity
        for pct in [-15, -10, -5, 0, 5, 10, 15]:
            factor = 1 + pct / 100.0
            sensitivity["capacity_factor_sensitivity"]["labels"].append(f"{pct:+.0f}%")
            sensitivity["capacity_factor_sensitivity"]["project_irr"].append(round(base_irr * (0.7 + 0.3 * factor), 4))
            sensitivity["capacity_factor_sensitivity"]["equity_irr"].append(round(base_equity_irr * (0.7 + 0.3 * factor), 4))
            sensitivity["capacity_factor_sensitivity"]["npv"].append(round(base_npv * (0.5 + 0.5 * factor), 2))

        # CAPEX sensitivity
        for pct in [-15, -10, -5, 0, 5, 10, 15]:
            factor = 1 + pct / 100.0
            sensitivity["capex_sensitivity"]["labels"].append(f"{pct:+.0f}%")
            # Higher CAPEX -> lower IRR
            sensitivity["capex_sensitivity"]["project_irr"].append(round(base_irr / factor, 4))
            sensitivity["capex_sensitivity"]["equity_irr"].append(round(base_equity_irr / factor, 4))
            sensitivity["capex_sensitivity"]["npv"].append(round(base_npv - base_npv * 0.3 * pct / 100.0, 2))

        # Discount rate sensitivity
        for rate_pct in [4, 5, 6, 7, 8, 9, 10]:
            label = f"{rate_pct}%"
            sensitivity["discount_rate_sensitivity"]["labels"].append(label)
            rate = rate_pct / 100.0
            # Simplified NPV impact: NPV decreases as discount rate increases
            base_rate = base_discount if base_discount else 0.06
            ratio = base_rate / rate if rate > 0 else 1
            adj_npv = base_npv * ratio
            adj_eq_npv = base_equity_npv * (base_rate / rate) if base_equity_npv else 0
            sensitivity["discount_rate_sensitivity"]["project_npv"].append(round(adj_npv, 2))
            sensitivity["discount_rate_sensitivity"]["equity_npv"].append(round(adj_eq_npv, 2))

        return sensitivity

    def run(self):
        """执行完整提取流程"""
        if not self.open():
            return {"error": "无法打开文件", "metadata": self.extraction_metadata}

        try:
            ws_summary = self.get_sheet("Summary")
            ws_scenarios = self.get_sheet("Scenarios")
            ws_inputs = self.get_sheet("Inputs")
            ws_td = self.get_sheet("T&D")

            result = {
                "run_id": f"solar_extract_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}",
                "workflow_id": "solar_financial_model",
                "project_info": self.extract_project_info(ws_summary),
                "scenario_info": self.extract_scenario_info(ws_summary),
                "key_metrics": self.extract_key_metrics(ws_summary),
                "annual_data": self.extract_annual_data(ws_summary),
                "funding_structure": self.extract_funding_structure(ws_summary),
                "debt_ratios": self.extract_debt_ratios(ws_summary),
                "tax_depreciation": self.extract_tax_depreciation(ws_inputs, ws_td),
                "model_vintage": self.check_model_vintage(),
                "sensitivity_results": {},
                "charts_generated": [],
                "extraction_metadata": self.extraction_metadata,
                "scenarios_available": self.get_scenarios(ws_scenarios)
            }

            # 税务折旧警告追加到 extraction_metadata
            td_warnings = result.get("tax_depreciation", {}).get("warnings", [])
            if td_warnings:
                self.extraction_metadata["warnings"].extend(td_warnings)

            # 模型年代警告追加
            mv = result.get("model_vintage", {})
            if mv.get("is_outdated"):
                for w in mv.get("vintage_warnings", []):
                    self.extraction_metadata["warnings"].append(f"📅 {w}")

            # 计算敏感性
            result["sensitivity_results"] = self.compute_sensitivity(result["key_metrics"])

            # 计算数据完整性
            total_fields = 0
            filled_fields = 0
            for key in ["project_irr_post_tax", "project_npv_post_tax", "equity_irr",
                         "equity_npv", "lcos", "total_project_cost"]:
                total_fields += 1
                if result["key_metrics"].get(key) is not None:
                    filled_fields += 1
            result["extraction_metadata"]["data_completeness_pct"] = round(
                filled_fields / total_fields * 100, 1) if total_fields > 0 else 0

            return result

        except Exception as e:
            self.extraction_metadata["errors"].append(f"提取异常: {str(e)}")
            return {"error": str(e), "metadata": self.extraction_metadata}
        finally:
            self.close()


# ─── 命令行接口 ──────────────────────────────────────────────────────────


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="光伏/储能项目财务模型 Excel 数据提取器",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
    python3 solar_excel_extractor.py input/MODEL2019.xlsb
    python3 solar_excel_extractor.py input/model.xlsm --output outputs/extracted_data.json
    python3 solar_excel_extractor.py input/model.xlsm --scenario "Case 2"
        """
    )
    parser.add_argument("excel_file", help="财务模型 Excel 文件路径 (.xlsm/.xlsb/.xlsx)")
    parser.add_argument("--scenario", "-s", help="要分析的场景名称（可选）")
    parser.add_argument("--output", "-o", help="输出 JSON 文件路径（可选，默认输出到 stdout）")

    args = parser.parse_args()

    if not os.path.exists(args.excel_file):
        print(json.dumps({"error": f"文件不存在: {args.excel_file}"}, ensure_ascii=False, indent=2))
        sys.exit(1)

    extractor = SolarExcelExtractor(args.excel_file)
    result = extractor.run()

    output_json = json.dumps(result, ensure_ascii=False, indent=2, default=str)

    if args.output:
        os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(output_json)
        print(f"数据已写入: {args.output}")
    else:
        print(output_json)


if __name__ == "__main__":
    main()
