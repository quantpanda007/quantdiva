"""
Payoff builders — factory for constructing QuantLib payoff objects.

Centralizes all payoff construction so instruments don't need to
know QuantLib payoff internals. Supports:
- PlainVanilla (standard Call/Put)
- CashOrNothing (digital: pays fixed amount)
- AssetOrNothing (digital: pays asset value)
- SuperShare (pays between lower and upper strike)
- Gap (pays S - K2 when S > K1)

Usage:
    from instruments.common.payoffs import PayoffBuilder

    payoff = PayoffBuilder.plain_vanilla("call", strike=100.0)
    payoff = PayoffBuilder.cash_or_nothing("put", strike=100.0, cashpayoff=1.0)
"""

from __future__ import annotations

from typing import Union

import QuantLib as ql

from core.enums.definitions import OptionType


class PayoffBuilder:
    """
    Factory for QuantLib payoff objects.

    All methods are static — no state needed.
    Every method accepts either OptionType enum or string ("call"/"put").
    """

    # -------------------------------------------------------------------
    # Internal helper
    # -------------------------------------------------------------------

    @staticmethod
    def _resolve_option_type(option_type: Union[OptionType, str]) -> int:
        """Convert our OptionType enum or string to QuantLib Option.Type."""
        if isinstance(option_type, OptionType):
            return ql.Option.Call if option_type == OptionType.CALL else ql.Option.Put
        if isinstance(option_type, str):
            normalized = option_type.strip().lower()
            if normalized in ("call", "c"):
                return ql.Option.Call
            elif normalized in ("put", "p"):
                return ql.Option.Put
        raise ValueError(f"Unknown option type: {option_type}. Use 'call'/'put' or OptionType enum.")

    # -------------------------------------------------------------------
    # Payoff types
    # -------------------------------------------------------------------

    @staticmethod
    def plain_vanilla(
        option_type: Union[OptionType, str],
        strike: float,
    ) -> ql.PlainVanillaPayoff:
        """
        Standard vanilla payoff.
            Call: max(S - K, 0)
            Put:  max(K - S, 0)
        """
        ql_type = PayoffBuilder._resolve_option_type(option_type)
        return ql.PlainVanillaPayoff(ql_type, strike)

    @staticmethod
    def cash_or_nothing(
        option_type: Union[OptionType, str],
        strike: float,
        cashpayoff: float,
    ) -> ql.CashOrNothingPayoff:
        """
        Digital (binary) cash-or-nothing payoff.
            Call: pays cashpayoff if S > K at expiry, else 0
            Put:  pays cashpayoff if S < K at expiry, else 0
        """
        ql_type = PayoffBuilder._resolve_option_type(option_type)
        return ql.CashOrNothingPayoff(ql_type, strike, cashpayoff)

    @staticmethod
    def asset_or_nothing(
        option_type: Union[OptionType, str],
        strike: float,
    ) -> ql.AssetOrNothingPayoff:
        """
        Digital asset-or-nothing payoff.
            Call: pays S if S > K at expiry, else 0
            Put:  pays S if S < K at expiry, else 0
        """
        ql_type = PayoffBuilder._resolve_option_type(option_type)
        return ql.AssetOrNothingPayoff(ql_type, strike)

    @staticmethod
    def super_share(
        strike_lower: float,
        strike_upper: float,
    ) -> ql.SuperSharePayoff:
        """
        Super-share payoff.
            Pays 1/K_lower if K_lower < S < K_upper, else 0.
            Used in some structured products.
        """
        return ql.SuperSharePayoff(strike_lower, strike_upper)

    @staticmethod
    def gap(
        option_type: Union[OptionType, str],
        strike: float,
        second_strike: float,
    ) -> ql.GapPayoff:
        """
        Gap payoff.
            Call: pays (S - K2) if S > K1
            Put:  pays (K2 - S) if S < K1
            K1 = trigger strike, K2 = payoff strike
        """
        ql_type = PayoffBuilder._resolve_option_type(option_type)
        return ql.GapPayoff(ql_type, strike, second_strike)

    # -------------------------------------------------------------------
    # Convenience: from dict (for API/config-driven construction)
    # -------------------------------------------------------------------

    @staticmethod
    def from_dict(config: dict) -> ql.Payoff:
        """
        Build a payoff from a configuration dictionary.

        Examples:
            {"type": "plain_vanilla", "option_type": "call", "strike": 100}
            {"type": "cash_or_nothing", "option_type": "put", "strike": 100, "cashpayoff": 1.0}
        """
        payoff_type = config.get("type", "plain_vanilla").lower()

        if payoff_type == "plain_vanilla":
            return PayoffBuilder.plain_vanilla(
                config["option_type"], config["strike"]
            )
        elif payoff_type == "cash_or_nothing":
            return PayoffBuilder.cash_or_nothing(
                config["option_type"], config["strike"], config["cashpayoff"]
            )
        elif payoff_type == "asset_or_nothing":
            return PayoffBuilder.asset_or_nothing(
                config["option_type"], config["strike"]
            )
        elif payoff_type == "super_share":
            return PayoffBuilder.super_share(
                config["strike_lower"], config["strike_upper"]
            )
        elif payoff_type == "gap":
            return PayoffBuilder.gap(
                config["option_type"], config["strike"], config["second_strike"]
            )
        else:
            raise ValueError(f"Unknown payoff type: {payoff_type}")
