from instruments.fx.fx_forward import FXForward
from api.v1.helpers import build_instrument_from_request, build_market_env_from_request
from api.v1.schemas import InstrumentRequest, MarketDataRequest, UnderlyingData

req = InstrumentRequest(type="fx_forward", params={
    "ccy_pair": "USDINR", "strike": 86.0, "delivery_date": "2026-03-15",
    "notional": 1_000_000, "direction": "buy"
})

inst = build_instrument_from_request(req)
print(f"notional={inst.notional}")
print(f"strike={inst.strike}")
print(f"direction={inst.direction}")
print(f"has from_dict: {hasattr(FXForward, 'from_dict')}")

md = MarketDataRequest(
    pricing_date="2025-03-15",
    underlyings={"USDINR": UnderlyingData(spot=85.47, vol=0.0)},
    rate_curve=[{"tenor": "1Y", "rate": 0.065}],
    foreign_rate=0.045,
)
env = build_market_env_from_request(md, underlying="USDINR")
ql_inst = inst.build(env)
print(f"NPV from build: {ql_inst.NPV()}")