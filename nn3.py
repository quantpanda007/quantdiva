# debug.py
import registry.bootstrap
from api.v1.helpers import build_instrument_from_request, build_market_env_from_request
from api.v1.schemas import InstrumentRequest, MarketDataRequest, UnderlyingData
from services.pricers.pricing_service import PricingService
from registry import engine_registry

req = InstrumentRequest(type="fx_forward", params={
    "ccy_pair": "USDINR", "strike": 86.0,
    "delivery_date": "2026-03-15", "notional": 1000000, "direction": "buy"
})
md = MarketDataRequest(
    pricing_date="2025-03-15",
    underlyings={"USDINR": UnderlyingData(spot=85.47, vol=0.0)},
    rate_curve=[{"tenor": "1Y", "rate": 0.065}],
    foreign_rate=0.045,
)
inst = build_instrument_from_request(req)
env  = build_market_env_from_request(md, underlying="USDINR")

engine_key = ("fx_forward", "analytic")
EngineClass = engine_registry.get(engine_key)
engine = EngineClass()
print(f"engine type:      {type(engine)}")
print(f"has price method: {hasattr(engine, 'price')}")
candidate = engine.price(inst, env)
print(f"candidate type:   {type(candidate)}")
print(f"forward_rate:     {candidate.forward_rate}")
print(f"disc_factor:      {candidate.disc_factor}")
