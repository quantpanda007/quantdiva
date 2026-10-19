import json
import QuantLib as ql
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
finally:
    ql.Settings.instance().evaluationDate = previous   # restore QuantLib's global date

print(result.npv, legs)   # -7955.7262..., fixed -31978.763, floating 24023.037