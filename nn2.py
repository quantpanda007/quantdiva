from services.pricers.pricing_service import PricingService
from api.v1.helpers import build_instrument_from_request, build_market_env_from_request
from api.v1.schemas import InstrumentRequest, MarketDataRequest, UnderlyingData

req = InstrumentRequest(type="fx_forward", params={
    "ccy_pair": "USDINR", "strike": 86.0, "delivery_date": "2026-03-15",
    "notional": 1_000_000, "direction": "buy"
})
md = MarketDataRequest(
    pricing_date="2025-03-15",
    underlyings={"USDINR": UnderlyingData(spot=85.47, vol=0.0)},
    rate_curve=[{"tenor": "1Y", "rate": 0.065}],
    foreign_rate=0.045,
)

ps = PricingService()
inst = build_instrument_from_request(req)
env = build_market_env_from_request(md, underlying="USDINR")

# What does PricingService produce?
result = ps.price(inst, env, model_type="black_scholes", engine_type="analytic")
print(f"Service NPV:      {result.npv}")
print(f"Direct build NPV: {inst.build(env).NPV()}")

# What QL instrument does build() return?
ql_inst = inst.build(env)
print(f"QL instrument type: {type(ql_inst)}")