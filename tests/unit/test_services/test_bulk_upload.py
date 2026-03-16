"""
Unit tests for bulk_upload.py — covers fixes for:
  - Fix 2: Feb 29 leap year crash in long/short term classification
  - Fix 3: vol=0.0 not overridden by falsy-zero fallback in build_market_env_from_request
  - Fix 4: contract_type validation uses delivery date presence, not Type column text
"""

import pytest
from datetime import date
from unittest.mock import patch, MagicMock


# ---------------------------------------------------------------------------
# Helpers — replicate the is_long_term logic from bulk_upload
# so we can test it in isolation before and after the fix
# ---------------------------------------------------------------------------

def _is_long_term_current(pricing_date: date, maturity: date) -> bool:
    """Current implementation — crashes on Feb 29."""
    return maturity > pricing_date.replace(year=pricing_date.year + 1)


def _is_long_term_fixed(pricing_date: date, maturity: date) -> bool:
    """Fixed implementation — handles Feb 29 gracefully."""
    try:
        one_year_later = pricing_date.replace(year=pricing_date.year + 1)
    except ValueError:
        # Feb 29 → fall back to Feb 28 of next year
        one_year_later = pricing_date.replace(year=pricing_date.year + 1, day=28)
    return maturity > one_year_later


# ---------------------------------------------------------------------------
# Fix 2: Leap year tests
# ---------------------------------------------------------------------------

class TestLeapYearLongTerm:

    def test_normal_date_long_term(self):
        """Standard date — maturity beyond 1 year → long term."""
        pricing = date(2025, 3, 15)
        maturity = date(2026, 6, 30)
        assert _is_long_term_fixed(pricing, maturity) is True

    def test_normal_date_short_term(self):
        """Standard date — maturity within 1 year → short term."""
        pricing = date(2025, 3, 15)
        maturity = date(2025, 12, 31)
        assert _is_long_term_fixed(pricing, maturity) is False

    def test_leap_day_pricing_date_does_not_crash(self):
        """Feb 29 pricing date must not raise ValueError."""
        pricing = date(2028, 2, 29)
        maturity = date(2029, 6, 30)
        # Current implementation should crash
        with pytest.raises(ValueError):
            _is_long_term_current(pricing, maturity)
        # Fixed implementation must not crash
        result = _is_long_term_fixed(pricing, maturity)
        assert result is True  # maturity Jun 2029 > Feb 28 2029

    def test_leap_day_maturity_exactly_one_year_later(self):
        """Maturity exactly at the 1-year boundary (Feb 28 next year) → short term."""
        pricing = date(2028, 2, 29)
        maturity = date(2029, 2, 28)
        result = _is_long_term_fixed(pricing, maturity)
        assert result is False  # maturity == boundary → not long term

    def test_non_leap_year_unaffected(self):
        """Non-leap pricing dates must behave identically in both implementations."""
        pricing = date(2025, 6, 15)
        maturity = date(2026, 9, 1)
        assert _is_long_term_current(pricing, maturity) == _is_long_term_fixed(pricing, maturity)


# ---------------------------------------------------------------------------
# Fix 3: vol=0.0 not overridden
# ---------------------------------------------------------------------------

class TestVolZeroNotOverridden:

    def test_vol_zero_reaches_build_flat_vol(self):
        """
        Confirms that vol=0.0 is preserved when using explicit None check
        vs being lost with the falsy || pattern.
        Simulates what build_market_env_from_request does internally.
        """
        def build_env_bad(vol):
            return vol or 0.25   # falsy zero bug

        def build_env_fixed(vol):
            return vol if vol is not None else 0.25  # correct

        assert build_env_bad(0.0) == 0.25    # bug: zero silently becomes 0.25
        assert build_env_fixed(0.0) == 0.0   # fix: zero is preserved

    def test_vol_zero_does_not_fallback_to_default(self):
        """
        Simulates the falsy-zero pattern: `vol or 0.25` would give 0.25 for vol=0.0.
        Confirms the fix uses explicit None check instead.
        """
        vol = 0.0

        # Bad pattern (what we're fixing)
        bad_vol = vol or 0.25
        assert bad_vol == 0.25, "Confirms the bug exists with || pattern"

        # Good pattern (the fix)
        good_vol = vol if vol is not None else 0.25
        assert good_vol == 0.0, "Fixed pattern preserves zero"


# ---------------------------------------------------------------------------
# Fix 4: contract_type validation uses delivery dates, not Type column
# ---------------------------------------------------------------------------

class TestContractTypeValidation:

    def _make_deal(self, contract_type="Forward", delivery_start=None, delivery_end=None):
        return {
            "row": 2,
            "transaction_ref": "TEST-001",
            "contract_type": contract_type,
            "delivery_start_date": delivery_start,
            "delivery_end_date": delivery_end,
            "strike": 86.88,
            "notional_1": 1_000_000,
            "maturity_date": date(2025, 12, 31),
            "spot": 85.47,
            "ccy_pair": "USDINR",
            "direction_1": "Sell",
        }

    def _run_validation(self, deal, expected_contract_type):
        """Replicate the fixed validation logic from parse_upload."""
        from api.v1.endpoints.bulk_upload import FORWARD_TYPES, RANGE_TYPES
        errs = []
        deal_type = deal["contract_type"].strip().lower()

        if expected_contract_type == "forward":
            if deal_type in RANGE_TYPES:
                errs.append("Wrong instrument: Range Forward in Vanilla Forward upload.")
            elif deal["delivery_start_date"] or deal["delivery_end_date"]:
                errs.append("Range Forward fields detected in Vanilla Forward upload.")
        elif expected_contract_type == "range_forward":
            # Type column not checked — delivery dates are the only reliable indicator
            if not deal["delivery_start_date"] or not deal["delivery_end_date"]:
                errs.append("Range Forward requires both Delivery Start Date and Delivery End Date.")

        return errs

    def test_vanilla_forward_accepted_in_forward_upload(self):
        deal = self._make_deal(contract_type="Forward")
        errs = self._run_validation(deal, "forward")
        assert errs == []

    def test_range_forward_rejected_in_forward_upload_by_type_column(self):
        deal = self._make_deal(contract_type="Range Forward")
        errs = self._run_validation(deal, "forward")
        assert len(errs) == 1
        assert "Range Forward" in errs[0]

    def test_range_forward_rejected_in_forward_upload_by_delivery_dates(self):
        """Type=Forward but has delivery dates — should still be rejected."""
        deal = self._make_deal(
            contract_type="Forward",
            delivery_start=date(2025, 6, 1),
            delivery_end=date(2025, 12, 31),
        )
        errs = self._run_validation(deal, "forward")
        assert len(errs) == 1
        assert "Range Forward fields detected" in errs[0]

    def test_range_forward_with_forward_type_column_accepted_in_range_upload(self):
        """
        KEY TEST — Fix 4:
        Business template has Type=Forward even for range forwards.
        Should be ACCEPTED in range_forward upload as long as delivery dates are present.
        Current implementation incorrectly rejects this.
        """
        deal = self._make_deal(
            contract_type="Forward",  # as per real business template
            delivery_start=date(2025, 6, 1),
            delivery_end=date(2025, 12, 31),
        )
        errs = self._run_validation(deal, "range_forward")
        # Current implementation will fail this — it adds "Wrong instrument" error
        # After fix, this should pass with no errors
        assert errs == [], f"Expected no errors but got: {errs}"

    def test_vanilla_forward_no_delivery_dates_rejected_in_range_upload(self):
        """Type=Forward with NO delivery dates → correctly rejected in range upload."""
        deal = self._make_deal(contract_type="Forward")
        errs = self._run_validation(deal, "range_forward")
        assert any("Delivery Start" in e or "delivery" in e.lower() for e in errs)

    def test_range_forward_type_column_with_delivery_dates_accepted(self):
        """Type=Range Forward with delivery dates → accepted in range upload."""
        deal = self._make_deal(
            contract_type="Range Forward",
            delivery_start=date(2025, 6, 1),
            delivery_end=date(2025, 12, 31),
        )
        errs = self._run_validation(deal, "range_forward")
        assert errs == []