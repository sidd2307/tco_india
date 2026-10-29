import json
import streamlit as st
import pandas as pd
import numpy as np
import math
from datetime import date

st.set_page_config(page_title="India TCO Estimator", page_icon="📊", layout="wide")

# ----------------------------
# Helpers and calculation engine
# ----------------------------
def money(x):
    try:
        return f"₹{float(x):,.2f}"
    except (TypeError, ValueError):
        return "—"

def pct(x):
    return f"{float(x):,.2f}%"

def num(x, default=0.0):
    try:
        if x is None or x == "":
            return default
        return float(x)
    except (TypeError, ValueError):
        return default

def safe_div(a, b):
    return a / b if b not in (0, None) else 0.0

def calculate_alternative(a, shared, global_assumptions):
    """Returns an auditable cost ledger and summary. All rates are user inputs, not live legal data."""
    ledger = []
    warnings = []

    def add(category, amount, note="", classification="Economic cost"):
        amount = num(amount)
        ledger.append({
            "Category": category,
            "Amount (INR)": amount,
            "Classification": classification,
            "Calculation / note": note
        })

    volume = max(num(shared["annual_demand"]), 0.0)
    horizon = max(int(shared["horizon"]), 1)
    discount = max(num(shared["discount_rate"]), 0.0) / 100
    growth = num(shared["demand_growth"], 0.0) / 100
    fx = max(num(a["fx_rate"]), 0.0)
    quote = max(num(a["unit_price"]), 0.0)
    price_inr = quote * (fx if a["quote_currency"] != "INR" else 1.0)
    model = a["model"]

    # Purchase/manufacturing baseline
    if model == "In-house manufacturing":
        yield_rate = min(max(num(a["yield_rate"]) / 100, 0.0001), 1.0)
        gross_units = safe_div(volume, yield_rate)
        materials = max(num(a["material_cost_unit"]), 0.0) * gross_units
        labour = max(num(a["labour_cost_unit"]), 0.0) * gross_units
        energy = max(num(a["energy_cost_unit"]), 0.0) * gross_units
        variable_other = max(num(a["other_variable_unit"]), 0.0) * gross_units
        fixed_ops = max(num(a["annual_fixed_cost"]), 0.0)
        capex = max(num(a["capex"]), 0.0)
        residual = max(num(a["residual_value"]), 0.0)
        useful_life = max(int(a["asset_life"]), 1)
        capital_cost = capex
        if capex > 0 and discount > 0:
            crf = discount * (1 + discount) ** useful_life / ((1 + discount) ** useful_life - 1)
            annualized_capital = max(capex - residual / ((1 + discount) ** useful_life), 0) * crf
        elif capex > 0:
            annualized_capital = max(capex - residual, 0) / useful_life
        else:
            annualized_capital = 0.0
        add("Raw materials", materials, f"{gross_units:,.2f} gross units × {money(a['material_cost_unit'])}/unit")
        add("Direct labour", labour, f"{gross_units:,.2f} gross units × {money(a['labour_cost_unit'])}/unit")
        add("Energy", energy, f"{gross_units:,.2f} gross units × {money(a['energy_cost_unit'])}/unit")
        add("Other variable manufacturing", variable_other, f"{gross_units:,.2f} gross units × {money(a['other_variable_unit'])}/unit")
        add("Fixed operating costs", fixed_ops, "Annual fixed costs")
        add("Annualized capital cost", annualized_capital, f"Capex {money(capex)}, residual {money(residual)}, life {useful_life} years")
        base_economic = materials + labour + energy + variable_other + fixed_ops + annualized_capital
        if num(a["capacity"]) > 0 and gross_units > num(a["capacity"]):
            warnings.append("Required gross production exceeds the stated annual practical capacity.")
        if capex > 0:
            add("Initial capital expenditure (cash flow)", capex, "Period-zero cash requirement; excluded from annual economic cost when annualized capital cost is used", "Cash flow")
    else:
        purchase_cost = price_inr * volume
        add("Supplier purchase price", purchase_cost, f"{money(price_inr)} per unit × {volume:,.0f} units")
        base_economic = purchase_cost

    # Customs/import module
    customs_total = 0.0
    import_igst = 0.0
    import_igst_credit = 0.0
    if model in ("Import finished product", "Hybrid / imported components") or a["cross_border"]:
        assessable = max(num(a["customs_value"]), 0.0)
        if assessable == 0:
            assessable = price_inr * volume
            if model == "In-house manufacturing":
                assessable = max(num(a["imported_input_value"]), 0.0)
            if assessable > 0:
                warnings.append("Customs assessable value was estimated from entered price/value. Verify the legal assessable value.")
        bcd = assessable * max(num(a["bcd_rate"]), 0) / 100
        sws_base_choice = a["sws_base"]
        sws_base = bcd if sws_base_choice == "BCD" else assessable + bcd
        sws = sws_base * max(num(a["sws_rate"]), 0) / 100
        other_duty = max(num(a["other_customs_duty"]), 0)
        igst_base = assessable + bcd + sws + other_duty
        import_igst = igst_base * max(num(a["import_igst_rate"]), 0) / 100
        credit_pct = min(max(num(a["import_igst_recovery"]), 0), 100) / 100
        import_igst_credit = import_igst * credit_pct
        customs_total = bcd + sws + other_duty + import_igst
        add("Customs assessable value (reference only)", assessable, "Base used for duty calculations; not added again to cost ledger")
        add("Basic Customs Duty (BCD)", bcd, f"{money(assessable)} × {pct(a['bcd_rate'])}")
        add("Social Welfare Surcharge (SWS)", sws, f"User-selected base: {sws_base_choice}; verify statutory base")
        add("Other customs duties / levies", other_duty, "User-entered amount for applicable levies")
        add("Import IGST paid", import_igst, f"IGST base {money(igst_base)} × {pct(a['import_igst_rate'])}", "Tax cash flow")
        add("Recoverable import IGST", -import_igst_credit, f"{pct(credit_pct*100)} assumed recoverable; shown as an offset to economic tax cost", "Tax credit")
        add("Import IGST financing cost", import_igst_credit * max(num(a["itc_delay_days"]), 0) / 365 * max(num(global_assumptions["financing_rate"]), 0) / 100,
            "Eligible credit × financing rate × delay/365")
        # Duties are costs; recoverable IGST is excluded from permanent cost.
        duty_economic = bcd + sws + other_duty + (import_igst - import_igst_credit)
        base_economic += duty_economic + import_igst_credit * max(num(a["itc_delay_days"]), 0) / 365 * max(num(global_assumptions["financing_rate"]), 0) / 100

    # GST for domestic purchase or manufacturing inputs, simplified user-entered base
    gst_base = max(num(a["domestic_gst_base"]), 0)
    gst_rate = max(num(a["gst_rate"]), 0) / 100
    gst_paid = gst_base * gst_rate
    gst_recovery = min(max(num(a["gst_recovery"]), 0), 100) / 100
    gst_credit = gst_paid * gst_recovery
    gst_nonrecoverable = gst_paid - gst_credit
    gst_financing = gst_credit * max(num(a["gst_delay_days"]), 0) / 365 * max(num(global_assumptions["financing_rate"]), 0) / 100
    if gst_base > 0:
        add("Domestic GST paid", gst_paid, f"Entered GST base {money(gst_base)} × {pct(gst_rate*100)}", "Tax cash flow")
        add("Recoverable domestic ITC", -gst_credit, f"{pct(gst_recovery*100)} assumed recoverable", "Tax credit")
        add("Nonrecoverable domestic GST", gst_nonrecoverable, "GST paid less assumed recoverable credit")
        add("Domestic ITC financing cost", gst_financing, "Recoverable credit × financing rate × delay/365")
        base_economic += gst_nonrecoverable + gst_financing

    # Logistics
    logistics = sum(max(num(a[k]), 0) for k in ["international_freight", "insurance", "port_cost", "broker_cost", "demurrage", "inland_freight", "warehouse_cost", "handling_cost"])
    add("International freight", max(num(a["international_freight"]), 0), "Annual total")
    add("Insurance", max(num(a["insurance"]), 0), "Annual total")
    add("Port / terminal costs", max(num(a["port_cost"]), 0), "Annual total")
    add("Customs broker / clearance", max(num(a["broker_cost"]), 0), "Annual total")
    add("Demurrage / detention / storage", max(num(a["demurrage"]), 0), "Annual expected cost")
    add("Inland freight", max(num(a["inland_freight"]), 0), "Annual total")
    add("Warehousing", max(num(a["warehouse_cost"]), 0), "Annual total")
    add("Handling / other logistics", max(num(a["handling_cost"]), 0), "Annual total")
    base_economic += logistics

    # Inventory and working capital
    inventory_value = max(num(a["inventory_days"]), 0) / 365 * max(base_economic, 0)
    carrying_rate = max(num(a["carrying_rate"]), 0) / 100
    inventory_cost = inventory_value * carrying_rate
    add("Inventory carrying cost", inventory_cost, f"Average inventory estimate {money(inventory_value)} × {pct(carrying_rate*100)}")
    base_economic += inventory_cost

    # Quality and warranty
    quality = max(num(a["inspection_cost"]), 0) + max(num(a["scrap_rework_cost"]), 0) + max(num(a["returns_cost"]), 0)
    warranty = volume * min(max(num(a["warranty_rate"]), 0), 100) / 100 * max(num(a["warranty_cost_event"]), 0)
    add("Inspection and testing", max(num(a["inspection_cost"]), 0), "Annual total")
    add("Scrap and rework", max(num(a["scrap_rework_cost"]), 0), "Annual total; avoid duplicating manufacturing yield costs")
    add("Returns and reverse logistics", max(num(a["returns_cost"]), 0), "Annual total")
    add("Expected warranty cost", warranty, f"Annual demand × warranty probability × net cost/event")
    base_economic += quality + warranty

    # Compliance, supplier management, other costs
    compliance = max(num(a["compliance_cost"]), 0)
    supplier_cost = max(num(a["supplier_management_cost"]), 0)
    engineering = max(num(a["engineering_cost"]), 0)
    other_annual = max(num(a["other_annual_cost"]), 0)
    add("Regulatory / compliance costs", compliance, "Annual recurring cost; one-time costs should be annualized separately if appropriate")
    add("Supplier qualification / management", supplier_cost, "Annual total")
    add("Engineering / tooling / customization", engineering, "Annualized or annual total as entered")
    add("Other incremental costs", other_annual, "Annual total")
    base_economic += compliance + supplier_cost + engineering + other_annual

    # Risk
    disruption_prob = min(max(num(a["disruption_probability"]), 0), 100) / 100
    disruption_loss = max(num(a["disruption_loss"]), 0)
    risk_cost = disruption_prob * disruption_loss
    add("Expected disruption loss", risk_cost, f"{pct(disruption_prob*100)} probability × {money(disruption_loss)} loss")
    base_economic += risk_cost

    annual_cost = base_economic
    units = volume if volume > 0 else 0
    unit_cost = safe_div(annual_cost, units)

    # Lifecycle NPV: recurring annual cost grows with annual cost inflation and demand growth (simplified).
    inflation = max(num(a["annual_cost_inflation"]), 0) / 100
    lifecycle_npv = 0.0
    # Lifecycle NPV uses cash-flow logic: remove annualized capital allocation from recurring costs,
    # then include initial capex at period zero and residual value at the end of the horizon.
    recurring_for_npv = annual_cost
    if model == "In-house manufacturing":
        recurring_for_npv -= annualized_capital
    for year in range(1, horizon + 1):
        annual = recurring_for_npv * ((1 + growth) ** (year - 1)) * ((1 + inflation) ** (year - 1))
        lifecycle_npv += annual / ((1 + discount) ** year)
    if model == "In-house manufacturing":
        capex = max(num(a["capex"]), 0)
        residual = max(num(a["residual_value"]), 0)
        lifecycle_npv += capex
        lifecycle_npv -= residual / ((1 + discount) ** horizon)

    summary = {
        "Alternative": a["name"],
        "Model": model,
        "Annual economic cost": annual_cost,
        "Cost per unit": unit_cost,
        "Lifecycle NPV": lifecycle_npv,
        "Logistics cost": logistics,
        "Customs duties + nonrecoverable import IGST": customs_total - import_igst_credit,
        "Import IGST paid": import_igst,
        "Import IGST credit assumed": import_igst_credit,
        "Inventory carrying cost": inventory_cost,
        "Quality + warranty": quality + warranty,
        "Expected disruption loss": risk_cost,
        "Initial capex": max(num(a["capex"]), 0) if model == "In-house manufacturing" else 0,
        "Feasible": len(warnings) == 0
    }
    return summary, pd.DataFrame(ledger), warnings

# ----------------------------
# UI
# ----------------------------
st.title("🇮🇳 India TCO Estimator")
st.caption("A decision-tree-driven sourcing, manufacturing and landed-cost comparison tool.")
st.info("Important: This is a decision-support prototype. Tax and customs rates are user-entered assumptions unless you independently verify them against current official sources. It is not legal, tax or customs advice.")

with st.sidebar:
    st.header("Analysis setup")
    analysis_name = st.text_input("Analysis name", "India sourcing comparison")
    purpose = st.selectbox("Decision type", [
        "Domestic vs import", "Supplier comparison", "Make vs buy",
        "Manufacturing location", "Hybrid sourcing", "Custom comparison"
    ])
    mode = st.radio("Questionnaire mode", ["Basic", "Advanced"], horizontal=True)
    st.divider()
    st.subheader("Common assumptions")
    annual_demand = st.number_input("Annual demand (usable units)", min_value=0, value=10000, step=1000)
    horizon = st.number_input("Evaluation horizon (years)", min_value=1, max_value=30, value=5)
    demand_growth = st.number_input("Annual demand growth (%)", min_value=-50.0, max_value=200.0, value=0.0, step=1.0)
    discount_rate = st.number_input("Discount rate / WACC (%)", min_value=0.0, max_value=100.0, value=12.0, step=0.5)
    financing_rate = st.number_input("Working-capital financing rate (%)", min_value=0.0, max_value=100.0, value=12.0, step=0.5)
    valuation_date = st.date_input("Valuation date", value=date.today())
    st.caption("Use a consistent nominal/real discount-rate convention.")

shared = {
    "annual_demand": annual_demand,
    "horizon": horizon,
    "demand_growth": demand_growth,
    "discount_rate": discount_rate,
}
global_assumptions = {"financing_rate": financing_rate}

st.subheader("1. Define sourcing alternatives")
default_models = ["Domestic supplier", "Import finished product", "In-house manufacturing", "Outsourced manufacturing", "Hybrid / imported components"]
if "n_alts" not in st.session_state:
    st.session_state.n_alts = 2
n_alts = st.number_input("Number of alternatives", min_value=2, max_value=5, value=st.session_state.n_alts, step=1)
st.session_state.n_alts = n_alts

alternatives = []
tabs = st.tabs([f"Alternative {i+1}" for i in range(n_alts)])

for idx, tab in enumerate(tabs):
    with tab:
        st.markdown(f"### Alternative {idx+1}")
        c1, c2, c3 = st.columns(3)
        name = c1.text_input("Alternative name", ["Domestic supplier", "Import supplier", "In-house option", "Outsourced option", "Hybrid option"][idx], key=f"name_{idx}")
        model = c2.selectbox("Sourcing model", default_models, index=min(idx, len(default_models)-1), key=f"model_{idx}")
        cross_border = c3.checkbox("Cross-border goods / inputs involved?", value=(model in ("Import finished product", "Hybrid / imported components")), key=f"cross_{idx}")
        with st.expander("A. Price, supplier and currency", expanded=True):
            p1, p2, p3 = st.columns(3)
            quote_currency = p1.selectbox("Quote currency", ["INR", "USD", "EUR", "CNY", "JPY", "GBP", "Other"], key=f"currency_{idx}")
            unit_price = p2.number_input("Unit price (in quote currency)", min_value=0.0, value=100.0, step=10.0, key=f"price_{idx}")
            fx_rate = p3.number_input("INR per 1 unit of quote currency", min_value=0.0, value=(1.0 if quote_currency == "INR" else 83.0), step=0.5, key=f"fx_{idx}")
            p4, p5, p6 = st.columns(3)
            origin = p4.text_input("Country of origin", "India" if model == "Domestic supplier" else "", key=f"origin_{idx}")
            dispatch = p5.text_input("Country of dispatch", "India" if model == "Domestic supplier" else "", key=f"dispatch_{idx}")
            supplier_type = p6.selectbox("Supplier type", ["Manufacturer", "Distributor / trader", "Contract manufacturer", "Internal facility"], key=f"supplier_{idx}")
            inclusions = st.multiselect("Already included in quoted price", ["Packaging", "Freight", "Insurance", "Testing", "Tooling", "Installation", "Warehousing"], key=f"inclusions_{idx}")
        with st.expander("B. GST and domestic tax treatment"):
            g1, g2, g3 = st.columns(3)
            gst_rate = g1.number_input("GST rate (%)", min_value=0.0, max_value=100.0, value=18.0, step=0.5, key=f"gstrate_{idx}")
            domestic_gst_base = g2.number_input("Annual taxable base for domestic GST (INR)", min_value=0.0, value=0.0, step=1000.0, key=f"gstbase_{idx}")
            gst_recovery = g3.slider("Domestic GST recovery (%)", 0, 100, 100, key=f"gstrecovery_{idx}")
            g4, g5 = st.columns(2)
            gst_delay_days = g4.number_input("Expected domestic ITC utilization delay (days)", min_value=0, value=30, step=5, key=f"gst_delay_{idx}")
            gst_registration = g5.selectbox("Buyer GST status", ["Registered", "Unregistered", "Unknown"], key=f"gstreg_{idx}")
        with st.expander("C. Import and customs (conditional)", expanded=(cross_border or model in ("Import finished product", "Hybrid / imported components"))):
            if cross_border or model in ("Import finished product", "Hybrid / imported components"):
                i1, i2, i3 = st.columns(3)
                hs_code = i1.text_input("HS/CTH classification", "", key=f"hs_{idx}")
                customs_value = i2.number_input("Annual customs assessable value (INR)", min_value=0.0, value=0.0, step=1000.0, key=f"customsval_{idx}")
                bcd_rate = i3.number_input("BCD rate (%)", min_value=0.0, max_value=500.0, value=0.0, step=1.0, key=f"bcd_{idx}")
                i4, i5, i6 = st.columns(3)
                sws_rate = i4.number_input("SWS rate (%)", min_value=0.0, max_value=100.0, value=0.0, step=1.0, key=f"sws_{idx}")
                sws_base = i5.selectbox("SWS calculation base (verify legally)", ["BCD", "Assessable value + BCD"], key=f"swsbase_{idx}")
                import_igst_rate = i6.number_input("Import IGST rate (%)", min_value=0.0, max_value=100.0, value=0.0, step=1.0, key=f"igst_{idx}")
                i7, i8, i9 = st.columns(3)
                other_customs_duty = i7.number_input("Other customs duties / levies (annual INR)", min_value=0.0, value=0.0, step=1000.0, key=f"otherduty_{idx}")
                import_igst_recovery = i8.slider("Import IGST recovery (%)", 0, 100, 100, key=f"igstrec_{idx}")
                itc_delay_days = i9.number_input("Import ITC utilization delay (days)", min_value=0, value=30, step=5, key=f"itcdelay_{idx}")
                st.caption("Enter verified tariff rates and bases. The app does not fetch live customs rates.")
            else:
                hs_code, customs_value, bcd_rate, sws_rate, sws_base = "", 0.0, 0.0, 0.0, "BCD"
                import_igst_rate, other_customs_duty, import_igst_recovery, itc_delay_days = 0.0, 0.0, 100, 0
        with st.expander("D. In-house manufacturing (conditional)", expanded=(model == "In-house manufacturing")):
            if model == "In-house manufacturing":
                m1, m2, m3 = st.columns(3)
                capacity = m1.number_input("Practical annual capacity (units)", min_value=0.0, value=15000.0, step=1000.0, key=f"capacity_{idx}")
                yield_rate = m2.number_input("Usable yield (%)", min_value=0.1, max_value=100.0, value=95.0, step=0.5, key=f"yield_{idx}")
                capex = m3.number_input("Initial capital expenditure (INR)", min_value=0.0, value=0.0, step=100000.0, key=f"capex_{idx}")
                m4, m5, m6 = st.columns(3)
                material_cost_unit = m4.number_input("Material cost per gross unit (INR)", min_value=0.0, value=40.0, step=5.0, key=f"material_{idx}")
                labour_cost_unit = m5.number_input("Labour cost per gross unit (INR)", min_value=0.0, value=15.0, step=1.0, key=f"labour_{idx}")
                energy_cost_unit = m6.number_input("Energy cost per gross unit (INR)", min_value=0.0, value=5.0, step=1.0, key=f"energy_{idx}")
                m7, m8, m9 = st.columns(3)
                other_variable_unit = m7.number_input("Other variable cost per gross unit (INR)", min_value=0.0, value=5.0, step=1.0, key=f"othervar_{idx}")
                annual_fixed_cost = m8.number_input("Annual fixed operating costs (INR)", min_value=0.0, value=100000.0, step=10000.0, key=f"fixed_{idx}")
                residual_value = m9.number_input("Expected residual value (INR)", min_value=0.0, value=0.0, step=10000.0, key=f"residual_{idx}")
                asset_life = st.number_input("Asset useful life (years)", min_value=1, max_value=50, value=10, step=1, key=f"assetlife_{idx}")
                imported_input_value = st.number_input("Annual imported input customs value (INR)", min_value=0.0, value=0.0, step=1000.0, key=f"importinput_{idx}")
            else:
                capacity, yield_rate, capex, material_cost_unit, labour_cost_unit, energy_cost_unit = 0.0, 100.0, 0.0, 0.0, 0.0, 0.0
                other_variable_unit, annual_fixed_cost, residual_value, asset_life, imported_input_value = 0.0, 0.0, 0.0, 1, 0.0
        with st.expander("E. Logistics and warehousing"):
            l1, l2, l3, l4 = st.columns(4)
            international_freight = l1.number_input("International freight (annual INR)", min_value=0.0, value=0.0, step=1000.0, key=f"intl_{idx}")
            insurance = l2.number_input("Transport insurance (annual INR)", min_value=0.0, value=0.0, step=1000.0, key=f"ins_{idx}")
            port_cost = l3.number_input("Port / terminal charges (annual INR)", min_value=0.0, value=0.0, step=1000.0, key=f"port_{idx}")
            broker_cost = l4.number_input("Customs broker / clearance (annual INR)", min_value=0.0, value=0.0, step=1000.0, key=f"broker_{idx}")
            l5, l6, l7, l8 = st.columns(4)
            demurrage = l5.number_input("Demurrage / detention (annual INR)", min_value=0.0, value=0.0, step=1000.0, key=f"demurrage_{idx}")
            inland_freight = l6.number_input("Inland freight (annual INR)", min_value=0.0, value=0.0, step=1000.0, key=f"inland_{idx}")
            warehouse_cost = l7.number_input("Warehousing (annual INR)", min_value=0.0, value=0.0, step=1000.0, key=f"warehouse_{idx}")
            handling_cost = l8.number_input("Handling / other logistics (annual INR)", min_value=0.0, value=0.0, step=1000.0, key=f"handling_{idx}")
        with st.expander("F. Inventory and working capital"):
            w1, w2, w3 = st.columns(3)
            inventory_days = w1.number_input("Average inventory days", min_value=0.0, value=30.0, step=5.0, key=f"invdays_{idx}")
            carrying_rate = w2.number_input("Annual inventory carrying-cost rate (%)", min_value=0.0, max_value=100.0, value=20.0, step=1.0, key=f"carry_{idx}")
            payment_days = w3.number_input("Supplier payment days (reference only)", min_value=0, value=30, step=5, key=f"paydays_{idx}")
        with st.expander("G. Quality, warranty and operational risk"):
            q1, q2, q3 = st.columns(3)
            inspection_cost = q1.number_input("Inspection / testing cost (annual INR)", min_value=0.0, value=0.0, step=1000.0, key=f"inspection_{idx}")
            scrap_rework_cost = q2.number_input("Scrap / rework cost (annual INR)", min_value=0.0, value=0.0, step=1000.0, key=f"scrap_{idx}")
            returns_cost = q3.number_input("Returns / reverse logistics (annual INR)", min_value=0.0, value=0.0, step=1000.0, key=f"returns_{idx}")
            q4, q5 = st.columns(2)
            warranty_rate = q4.number_input("Warranty event probability per unit (%)", min_value=0.0, max_value=100.0, value=1.0, step=0.5, key=f"warrate_{idx}")
            warranty_cost_event = q5.number_input("Average net warranty cost per event (INR)", min_value=0.0, value=500.0, step=50.0, key=f"warcost_{idx}")
            q6, q7 = st.columns(2)
            disruption_probability = q6.number_input("Annual disruption probability (%)", min_value=0.0, max_value=100.0, value=5.0, step=1.0, key=f"disprob_{idx}")
            disruption_loss = q7.number_input("Financial loss if disruption occurs (annual INR)", min_value=0.0, value=0.0, step=10000.0, key=f"disloss_{idx}")
        with st.expander("H. Compliance, supplier management and lifecycle"):
            h1, h2, h3 = st.columns(3)
            compliance_cost = h1.number_input("Annual regulatory / compliance cost (INR)", min_value=0.0, value=0.0, step=1000.0, key=f"compliance_{idx}")
            supplier_management_cost = h2.number_input("Supplier qualification / management (annual INR)", min_value=0.0, value=0.0, step=1000.0, key=f"suppliercost_{idx}")
            engineering_cost = h3.number_input("Engineering / tooling / customization (annualized INR)", min_value=0.0, value=0.0, step=1000.0, key=f"engineering_{idx}")
            h4, h5 = st.columns(2)
            other_annual_cost = h4.number_input("Other incremental annual cost (INR)", min_value=0.0, value=0.0, step=1000.0, key=f"other_{idx}")
            annual_cost_inflation = h5.number_input("Annual cost inflation (%)", min_value=-50.0, max_value=200.0, value=4.0, step=1.0, key=f"inflation_{idx}")
            st.caption("For a real case, split one-time costs from recurring costs and document the source of each assumption.")

        a = {
            "name": name, "model": model, "cross_border": cross_border,
            "quote_currency": quote_currency, "unit_price": unit_price, "fx_rate": fx_rate,
            "origin": origin, "dispatch": dispatch, "supplier_type": supplier_type, "inclusions": inclusions,
            "gst_rate": gst_rate, "domestic_gst_base": domestic_gst_base, "gst_recovery": gst_recovery,
            "gst_delay_days": gst_delay_days, "gst_registration": gst_registration,
            "hs_code": hs_code, "customs_value": customs_value, "bcd_rate": bcd_rate,
            "sws_rate": sws_rate, "sws_base": sws_base, "import_igst_rate": import_igst_rate,
            "other_customs_duty": other_customs_duty, "import_igst_recovery": import_igst_recovery,
            "itc_delay_days": itc_delay_days, "capacity": capacity, "yield_rate": yield_rate,
            "capex": capex, "material_cost_unit": material_cost_unit, "labour_cost_unit": labour_cost_unit,
            "energy_cost_unit": energy_cost_unit, "other_variable_unit": other_variable_unit,
            "annual_fixed_cost": annual_fixed_cost, "residual_value": residual_value, "asset_life": asset_life,
            "imported_input_value": imported_input_value,
            "international_freight": international_freight, "insurance": insurance, "port_cost": port_cost,
            "broker_cost": broker_cost, "demurrage": demurrage, "inland_freight": inland_freight,
            "warehouse_cost": warehouse_cost, "handling_cost": handling_cost,
            "inventory_days": inventory_days, "carrying_rate": carrying_rate, "payment_days": payment_days,
            "inspection_cost": inspection_cost, "scrap_rework_cost": scrap_rework_cost, "returns_cost": returns_cost,
            "warranty_rate": warranty_rate, "warranty_cost_event": warranty_cost_event,
            "disruption_probability": disruption_probability, "disruption_loss": disruption_loss,
            "compliance_cost": compliance_cost, "supplier_management_cost": supplier_management_cost,
            "engineering_cost": engineering_cost, "other_annual_cost": other_annual_cost,
            "annual_cost_inflation": annual_cost_inflation
        }
        alternatives.append(a)

st.divider()
st.subheader("2. Review and calculate")
st.caption("Calculations use the assumptions entered above. Verify statutory rates, tax bases, eligibility and quote inclusions before relying on results.")
run = st.button("Calculate TCO", type="primary", use_container_width=True)

if run:
    results, ledgers, all_warnings = [], {}, {}
    for a in alternatives:
        summary, ledger, warnings = calculate_alternative(a, shared, global_assumptions)
        results.append(summary)
        ledgers[a["name"]] = ledger
        all_warnings[a["name"]] = warnings

    result_df = pd.DataFrame(results)
    st.session_state["results"] = result_df
    st.session_state["ledgers"] = ledgers
    st.session_state["warnings"] = all_warnings
    st.session_state["analysis_meta"] = {
        "analysis_name": analysis_name, "purpose": purpose, "mode": mode,
        "valuation_date": str(valuation_date), "annual_demand": annual_demand,
        "horizon": horizon, "discount_rate": discount_rate
    }

if "results" in st.session_state:
    result_df = st.session_state["results"]
    ledgers = st.session_state["ledgers"]
    all_warnings = st.session_state["warnings"]
    st.header("3. Results dashboard")
    feasible = result_df[result_df["Feasible"] == True]
    if not feasible.empty:
        winner = feasible.sort_values("Cost per unit").iloc[0]
        st.success(f"Lowest estimated annual cost per usable unit among alternatives without capacity warnings: {winner['Alternative']} — {money(winner['Cost per unit'])}/unit")
    else:
        st.warning("No alternative is currently marked feasible. Resolve the warnings before choosing a winner.")
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Annual demand", f"{annual_demand:,.0f} units")
    k2.metric("Evaluation horizon", f"{horizon} years")
    k3.metric("Lowest annual cost", money(feasible["Annual economic cost"].min()) if not feasible.empty else "—")
    k4.metric("Lowest lifecycle NPV", money(feasible["Lifecycle NPV"].min()) if not feasible.empty else "—")

    display_cols = ["Alternative", "Model", "Annual economic cost", "Cost per unit", "Lifecycle NPV", "Logistics cost",
                    "Customs duties + nonrecoverable import IGST", "Inventory carrying cost", "Quality + warranty",
                    "Expected disruption loss", "Initial capex", "Feasible"]
    st.subheader("Alternative comparison")
    st.dataframe(result_df[display_cols].style.format({
        "Annual economic cost": "₹{:,.2f}", "Cost per unit": "₹{:,.2f}", "Lifecycle NPV": "₹{:,.2f}",
        "Logistics cost": "₹{:,.2f}", "Customs duties + nonrecoverable import IGST": "₹{:,.2f}",
        "Inventory carrying cost": "₹{:,.2f}", "Quality + warranty": "₹{:,.2f}",
        "Expected disruption loss": "₹{:,.2f}", "Initial capex": "₹{:,.2f}"
    }), use_container_width=True, hide_index=True)

    st.subheader("Annual economic cost comparison")
    chart_df = result_df.set_index("Alternative")[["Annual economic cost"]]
    st.bar_chart(chart_df)

    st.subheader("Cost per usable unit")
    st.bar_chart(result_df.set_index("Alternative")[["Cost per unit"]])

    st.subheader("Detailed cost ledger")
    selected = st.selectbox("Choose alternative to inspect", result_df["Alternative"].tolist())
    st.dataframe(ledgers[selected].style.format({"Amount (INR)": "₹{:,.2f}"}), use_container_width=True, hide_index=True)
    for warning in all_warnings[selected]:
        st.warning(warning)
    if not all_warnings[selected]:
        st.caption("No capacity/estimation warnings were generated by the current prototype checks. This does not certify legal compliance or data accuracy.")

    st.subheader("Sensitivity: annual cost inflation")
    inflation_values = np.array([-2, 0, 2, 4, 6, 8, 10], dtype=float)
    sens_rows = []
    for _, row in result_df.iterrows():
        base = row["Annual economic cost"]
        for infl in inflation_values:
            npv = sum(base * ((1 + max(demand_growth, -99)/100) ** (year-1)) * ((1 + infl/100) ** (year-1)) /
                      ((1 + max(discount_rate, 0)/100) ** year) for year in range(1, int(horizon)+1))
            sens_rows.append({"Alternative": row["Alternative"], "Annual cost inflation (%)": infl, "Lifecycle NPV": npv})
    sens_df = pd.DataFrame(sens_rows)
    sens_pivot = sens_df.pivot(index="Annual cost inflation (%)", columns="Alternative", values="Lifecycle NPV")
    st.line_chart(sens_pivot)

    st.subheader("Export")
    csv = result_df.to_csv(index=False).encode("utf-8")
    st.download_button("Download comparison CSV", data=csv, file_name="india_tco_comparison.csv", mime="text/csv")
    ledger_all = []
    for alt_name, ledger in ledgers.items():
        temp = ledger.copy()
        temp.insert(0, "Alternative", alt_name)
        ledger_all.append(temp)
    ledger_csv = pd.concat(ledger_all, ignore_index=True).to_csv(index=False).encode("utf-8")
    st.download_button("Download detailed cost ledger CSV", data=ledger_csv, file_name="india_tco_cost_ledger.csv", mime="text/csv")
    meta = st.session_state.get("analysis_meta", {})
    st.download_button("Download analysis inputs (JSON)", data=json.dumps({"metadata": meta, "shared_inputs": shared, "alternatives": alternatives}, indent=2, default=str),
                       file_name="india_tco_inputs.json", mime="application/json")

st.divider()
with st.expander("Methodology, limitations and responsible use"):
    st.markdown("""
    - This is a prototype decision-support model, not an official tax/customs calculator.
    - All GST, customs, ITC, exchange-rate and compliance inputs must be verified for the actual product, transaction, jurisdiction and date.
    - The customs calculation is simplified and exposes the SWS base as an assumption. Actual statutory bases and applicable levies may differ.
    - Domestic GST is calculated only on the user-entered annual taxable base; the user must ensure the base and credit eligibility are correct.
    - Quote inclusions are captured for review, but the prototype does not automatically remove every selected inclusion from separate cost fields. Avoid entering the same cost twice.
    - Inventory carrying cost is an approximation based on annual cost and inventory days. For advanced use, model inventory value by SKU, stage and ownership timing.
    - Lifecycle NPV is a simplified scenario model. Tax shields, working-capital release, full payment timing and non-linear capacity economics require additional modelling.
    - Risk-adjusted cost depends on user-provided probabilities and loss estimates.
    - Verify applicable GST, customs, BIS/QCO, labour, factory, environmental, EPR and incentive requirements using official current sources or qualified advisers.
    """)
