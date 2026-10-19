import json
from collections import defaultdict

import QuantLib as ql
from instruments.rates.irs.cashflows import irs_cashflow_rows          # NEW
from instruments.rates.irs.pricing_instrument import FreshOISInstrument
from market.curves.irs_market_snapshot import parse_market_snapshot, resolve_market_environment
from services.pricers.pricing_service import PricingService

trade = json.load(open("examples/irs/tc1_trade.json", encoding="utf-8"))
market = json.load(open("examples/irs/usd_sofr_2026-03-31.json", encoding="utf-8"))

instrument = FreshOISInstrument.from_dict(trade["params"])
env = resolve_market_environment(parse_market_snapshot(market)).environment

previous = ql.Settings.instance().evaluationDate
try:
    result = PricingService().price(instrument=instrument, market_env=env,
                                    model_type="analytical", engine_type="discounting")
    legs = instrument.leg_npvs()
    # NEW: read the cashflows while the pricing evaluation date is still set
    rows = irs_cashflow_rows(instrument.last_built, env.discount_curves[instrument.currency()])
finally:
    ql.Settings.instance().evaluationDate = previous

print(f"NPV {result.npv:,.4f} | fixed {legs['fixed']:,.4f} | floating {legs['floating']:,.4f}\n")

# 1. Cashflow statement: one row per coupon per leg (paid leg negative)
print(f"{'Leg':8} {'Side':7} {'Per':>3} {'Acc start':10} {'Acc end':10} {'Pay date':10} "
      f"{'Notional':>10} {'DCF':>9} {'Rate %':>9} {'Amount':>12} {'DF':>10} {'PV':>12}")
for r in rows:
    print(f"{r.leg:8} {r.side:7} {r.period:>3} {r.accrual_start} {r.accrual_end} "
          f"{r.payment_date} {r.notional:>10,.0f} {r.day_count_fraction:>9.6f} "
          f"{r.rate * 100:>9.6f} {r.amount:>12,.2f} {r.discount_factor:>10.7f} "
          f"{r.present_value:>12,.2f}")

# 2. Net cashflow per payment date (fixed + floating)
net = defaultdict(lambda: [0.0, 0.0])
for r in rows:
    net[r.payment_date][0] += r.amount
    net[r.payment_date][1] += r.present_value
print(f"\n{'Pay date':10} {'Net amount':>12} {'Net PV':>12}")
for d in sorted(net):
    print(f"{d} {net[d][0]:>12,.2f} {net[d][1]:>12,.2f}")
print(f"{'Total':10} {'':>12} {sum(v[1] for v in net.values()):>12,.4f}   (engine NPV {result.npv:,.4f})")