"""
FastAPI application entry point.

Sets up the application, registers routes, middleware,
and triggers auto-discovery of instruments/engines/models.
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from registry import auto_discover_modules


def create_app() -> FastAPI:
    app = FastAPI(
        title="QuantLib Pricing Platform",
        description="Full-stack quantitative finance pricing, risk & portfolio management",
        version="0.1.0",
        docs_url="/docs",
        redoc_url="/redoc",
    )

    # -- Middleware --
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],  # tighten in production
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # -- Auto-discover registered components --
    auto_discover_modules(
        "instruments.equity.vanilla_option",
        "engines.analytic.equity_engines",
        "models.equity.black_scholes",
    )

    # -- Register routes --
    from api.fastapi.routes.pricing import router as pricing_router
    app.include_router(pricing_router)

    @app.on_event("startup")
    async def startup():
        from registry import instrument_registry, engine_registry, model_registry
        print(f"Registered instruments: {instrument_registry.keys()}")
        print(f"Registered engines:     {engine_registry.keys()}")
        print(f"Registered models:      {model_registry.keys()}")

    return app


app = create_app()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("api.fastapi.app:app", host="0.0.0.0", port=8000, reload=True)
