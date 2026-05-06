#!/usr/bin/env python3
"""Debug Oxley scenario"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))

from solar_financial_engine import (
    ProjectInput, TimelineInput, TechnologyInput, CapexInput,
    OpexInput, RevenueInput, FinancingInput, TaxInput,
    MidLifeInput, GenerationProfile, ScenarioManager
)

project = ProjectInput(
    name="Oxley Solar Farm (Hybrid)",
    location="NSW, Australia",
    currency="AUD",
    scenario_name="Base Case",
    timeline=TimelineInput(
        construction_start="2026-07-01", construction_months=24, operation_years=30
    ),
    technology=TechnologyInput(
        pv_capacity_mwp=215, bess_capacity_mw=215, bess_duration_hrs=6,
        pv_degradation_pa=0.005, bess_degradation_pa=0.02, bess_rte=0.90, aux_consumption_pct=0.01
    ),
    capex=CapexInput(
        pv_capex_per_kwp=1250, bess_capex_per_kw=1200,
        bop_epc_pct=0.0, development_cost=45000, contingency_pct=0.05
    ),
    opex=OpexInput(
        pv_fixed_per_kwp_year=15, pv_variable_per_mwh=3,
        bess_fixed_per_kw_year=20, bess_variable_per_mwh=5, escalation_rate=0.02
    ),
    revenue=RevenueInput(
        ppa_price_aud_mwh=0, ppa_percentage=0.0,
        merchant_price_aud_mwh=75, solar_capture_price_aud_mwh=50,
        lgc_price_aud=37, lgc_rate_per_mwh=1.0,
        fcas_revenue_aud_kw_year=25, revenue_escalation=0.0,
        bess_charge_price_aud_mwh=30, bess_discharge_price_aud_mwh=110
    ),
    financing=FinancingInput(gearing_pct=0.0, interest_rate_pa=0.0, debt_tenor_years=0),
    tax=TaxInput(corporate_tax_rate=0.30, depreciation_method="SL",
                 pv_effective_life_years=20, bess_effective_life_years=15),
    mid_life=MidLifeInput(battery_replace_year=12, battery_replace_cost_pct=0.65,
                          inverter_replace_year=15, inverter_replace_cost_pct=0.12),
    generation=GenerationProfile(
        pv_cf_monthly=[0.20, 0.19, 0.20, 0.21, 0.22, 0.23, 0.22, 0.21, 0.20, 0.19, 0.18, 0.17],
        bess_cycles_per_day=1.0
    )
)

# Manual run for debug
from solar_financial_engine import MonthlyFinancialModel
model = MonthlyFinancialModel(project)
model._build_timeline()
cap = model._calc_capex()

print("=== CAPEX Debug ===")
for k, v in cap.items():
    print(f"  {k}: {v}")

print(f"\n=== Total Months ===")
print(f"  Construction: {model.construction_months}")
print(f"  Operation: {model.operation_months}")
print(f"  Total: {model.total_months}")

# Check revenue for first operation month
print(f"\n=== Revenue/OPEX/EBITDA (first 3 op months) ===")
for m in range(model.construction_months, min(model.construction_months + 6, model.total_months)):
    rev = model._calc_revenue(m, cap)
    opex = model._calc_opex(m)
    mc = model._calc_midlife_capex(m)
    ebitda = rev - opex
    print(f"  Month {m}: rev=${rev:.2f}k, opex=${opex:.2f}k, ebitda=${ebitda:.2f}k, maint=${mc:.2f}k")

# Full run
result = model.run()
km = result["key_metrics"]
print(f"\n=== Key Metrics ===")
for k, v in km.items():
    print(f"  {k}: {v}")

fd = result["funding_structure"]
print(f"\n=== Funding ===")
for k, v in fd.items():
    print(f"  {k}: {v}")

ad = result["annual_data"]
print(f"\n=== Annual Data Summary ===")
print(f"  Years: {ad.get('financial_years', [])[:5]}...")
print(f"  Revenue (yr1-3): {ad.get('revenue', [])[:3]}")
print(f"  EBITDA (yr1-3): {ad.get('ebitda', [])[:3]}")
print(f"  Tax (yr1-3): {ad.get('tax', [])[:3]}")
