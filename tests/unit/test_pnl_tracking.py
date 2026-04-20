"""MTM math for the daily P&L snapshot.

``compute_mtm`` is pure: given qty, cost_basis, last_price, return the
derived row fields. The DB orchestration layer is exercised via live
runs against the scratch DB.
"""

from __future__ import annotations

from decimal import Decimal as D

from mef.pnl_tracking import compute_mtm


def test_mtm_all_values_present():
    out = compute_mtm(quantity=D("100"), cost_basis_per_share=D("100.00"), last_price=D("110.00"))
    assert out["market_value"] == 11000.00
    assert out["unrealized_pnl_usd"] == 1000.00
    # +10% move: 0.1 exactly with 6dp rounding
    assert out["unrealized_pnl_pct"] == 0.100000


def test_mtm_loss():
    out = compute_mtm(quantity=D("50"), cost_basis_per_share=D("200.00"), last_price=D("180.00"))
    assert out["market_value"] == 9000.00
    assert out["unrealized_pnl_usd"] == -1000.00
    assert out["unrealized_pnl_pct"] == -0.100000


def test_mtm_no_last_price_returns_nulls():
    out = compute_mtm(quantity=D("100"), cost_basis_per_share=D("100.00"), last_price=None)
    assert out == {"market_value": None, "unrealized_pnl_usd": None, "unrealized_pnl_pct": None}


def test_mtm_no_quantity_returns_nulls():
    out = compute_mtm(quantity=None, cost_basis_per_share=D("100.00"), last_price=D("110.00"))
    assert out == {"market_value": None, "unrealized_pnl_usd": None, "unrealized_pnl_pct": None}


def test_mtm_no_cost_basis_still_returns_market_value():
    # When we have price + qty but no cost basis (mart-only price source),
    # market_value is usable; unrealized P&L fields remain null.
    out = compute_mtm(quantity=D("100"), cost_basis_per_share=None, last_price=D("110.00"))
    assert out["market_value"] == 11000.00
    assert out["unrealized_pnl_usd"] is None
    assert out["unrealized_pnl_pct"] is None


def test_mtm_zero_cost_basis_avoids_divide_by_zero():
    out = compute_mtm(quantity=D("100"), cost_basis_per_share=D("0"), last_price=D("110.00"))
    assert out["market_value"] == 11000.00
    assert out["unrealized_pnl_usd"] is None
    assert out["unrealized_pnl_pct"] is None


def test_mtm_rounding_behaviour():
    # Fractional shares + fractional prices — verify the rounding doesn't drift.
    out = compute_mtm(
        quantity=D("37.1234"),
        cost_basis_per_share=D("42.5555"),
        last_price=D("44.8877"),
    )
    expected_mv = round(float(D("37.1234") * D("44.8877")), 2)
    expected_pnl = round(float((D("44.8877") - D("42.5555")) * D("37.1234")), 2)
    assert out["market_value"] == expected_mv
    assert out["unrealized_pnl_usd"] == expected_pnl
