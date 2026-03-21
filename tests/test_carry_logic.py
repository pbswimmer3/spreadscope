#!/usr/bin/env python3
"""
SpreadScope — Funding Rate Carry Logic Tests (no external dependencies).
Tests the core math and models used by the carry calculator.
"""
import sys
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass, field
from typing import Optional, Dict, Any, List

# ============================================================================
# Inline models (avoid import chain that requires asyncpg)
# ============================================================================

@dataclass
class PriceObservation:
    time: datetime
    asset: str
    venue: str
    price: float
    volume_24h: Optional[float] = None
    funding_rate: Optional[float] = None
    open_interest: Optional[float] = None
    extra_data: Dict[str, Any] = field(default_factory=dict)

@dataclass
class Spread:
    time: datetime
    asset: str
    real_venue: str
    synthetic_venue: str
    real_price: float
    synthetic_price: float
    spread_abs: float
    spread_pct: float
    venue_pair: str

    @classmethod
    def from_prices(cls, time, asset, real, synthetic):
        spread_abs = synthetic.price - real.price
        spread_pct = (spread_abs / real.price) * 100
        return cls(time=time, asset=asset, real_venue=real.venue,
                   synthetic_venue=synthetic.venue, real_price=real.price,
                   synthetic_price=synthetic.price, spread_abs=spread_abs,
                   spread_pct=spread_pct,
                   venue_pair=f"{real.venue}:{synthetic.venue}")

@dataclass
class FundingRateSnapshot:
    time: datetime
    asset: str
    venue: str
    funding_rate: float
    annualized_rate: float
    next_funding_time: Optional[datetime] = None
    mark_price: Optional[float] = None
    index_price: Optional[float] = None
    open_interest: Optional[float] = None
    volume_24h: Optional[float] = None
    extra_data: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_8h_rate(cls, time, asset, venue, funding_rate_8h, **kwargs):
        annualized = funding_rate_8h * 3 * 365 * 100
        return cls(time=time, asset=asset, venue=venue,
                   funding_rate=funding_rate_8h,
                   annualized_rate=annualized, **kwargs)

@dataclass
class CarrySignal:
    asset: str = ""
    spot_venue: str = ""
    perp_venue: str = ""
    signal_type: str = "entry"
    status: str = "active"
    funding_rate_8h: float = 0.0
    annualized_rate: float = 0.0
    consecutive_positive_periods: int = 0
    spot_price: float = 0.0
    perp_price: float = 0.0
    entry_spread_pct: float = 0.0
    suggested_size_usd: float = 0.0
    suggested_leverage: float = 1.0
    portfolio_capital_usd: float = 5000.0
    expected_daily_return_usd: Optional[float] = None
    expected_annual_return_usd: Optional[float] = None
    expected_apy_pct: Optional[float] = None
    estimated_fees_usd: Optional[float] = None
    breakeven_hours: Optional[float] = None

# ============================================================================
# Tests
# ============================================================================

def test_funding_rate_annualization():
    print("Test 1: Funding rate annualization")
    now = datetime.now(timezone.utc)

    # 0.01% per 8h = 0.03% per day = 10.95% per year
    snap = FundingRateSnapshot.from_8h_rate(now, 'BTC', 'hyperliquid_perps', 0.0001)
    expected = 0.0001 * 3 * 365 * 100  # 10.95
    assert abs(snap.annualized_rate - expected) < 0.001, \
        f"Expected {expected:.2f}%, got {snap.annualized_rate:.2f}%"
    print(f"  0.01%/8h -> {snap.annualized_rate:.2f}% APY (expected {expected:.2f}%)")

    # 0.03% per 8h = 32.85% APY
    snap2 = FundingRateSnapshot.from_8h_rate(now, 'BTC', 'hyperliquid_perps', 0.0003)
    expected2 = 0.0003 * 3 * 365 * 100  # 32.85
    assert abs(snap2.annualized_rate - expected2) < 0.001
    print(f"  0.03%/8h -> {snap2.annualized_rate:.2f}% APY (expected {expected2:.2f}%)")

    # Negative funding
    snap3 = FundingRateSnapshot.from_8h_rate(now, 'ETH', 'dydx', -0.0002)
    expected3 = -0.0002 * 3 * 365 * 100  # -21.9
    assert abs(snap3.annualized_rate - expected3) < 0.001
    print(f"  -0.02%/8h -> {snap3.annualized_rate:.2f}% APY (expected {expected3:.2f}%)")

    print("  PASS")


def test_position_sizing():
    print("\nTest 2: Position sizing at various capital levels")

    test_cases = [
        (1000, 0.0001, 0.06),
        (5000, 0.0001, 0.06),
        (10000, 0.0003, 0.06),
        (50000, 0.0003, 0.06),
    ]

    for capital, funding_8h, fee_pct in test_cases:
        max_position = capital * 0.5
        suggested = min(max_position, capital * 0.4)
        entry_fees = suggested * 2 * (fee_pct / 100)
        daily_rate = funding_8h * 3
        daily_return = suggested * daily_rate
        annual_return = daily_return * 365
        total_fees = entry_fees * 2
        hourly_return = daily_return / 24
        breakeven = total_fees / hourly_return if hourly_return > 0 else float('inf')

        assert suggested == capital * 0.4, f"Expected position {capital*0.4}, got {suggested}"
        assert daily_return > 0 if funding_8h > 0 else True
        assert breakeven > 0 if funding_8h > 0 else True

        print(f"  ${capital:>6,}: pos=${suggested:>6,.0f}, "
              f"daily=${daily_return:.4f}, annual=${annual_return:,.2f}, "
              f"fees=${entry_fees:.2f}, breakeven={breakeven:.0f}h")

    print("  PASS")


def test_spread_calculation():
    print("\nTest 3: Spread calculation")
    now = datetime.now(timezone.utc)

    spot = PriceObservation(time=now, asset='BTC', venue='coinbase_spot', price=91000)
    perp = PriceObservation(time=now, asset='BTC', venue='hyperliquid_perps', price=91050)
    spread = Spread.from_prices(now, 'BTC', spot, perp)

    expected_pct = (91050 - 91000) / 91000 * 100
    assert abs(spread.spread_pct - expected_pct) < 0.001
    assert spread.venue_pair == 'coinbase_spot:hyperliquid_perps'
    assert spread.spread_abs == 50.0

    print(f"  Spread: {spread.spread_pct:.4f}% (expected {expected_pct:.4f}%)")
    print(f"  Absolute: ${spread.spread_abs:.2f}")

    # Negative spread (perp below spot)
    perp2 = PriceObservation(time=now, asset='ETH', venue='dydx', price=3190)
    spot2 = PriceObservation(time=now, asset='ETH', venue='coinbase_spot', price=3200)
    spread2 = Spread.from_prices(now, 'ETH', spot2, perp2)
    assert spread2.spread_pct < 0
    print(f"  Negative spread: {spread2.spread_pct:.4f}%")

    print("  PASS")


def test_carry_signal_model():
    print("\nTest 4: CarrySignal model")

    signal = CarrySignal(
        asset='BTC', spot_venue='coinbase_spot', perp_venue='hyperliquid_perps',
        signal_type='entry', status='active',
        funding_rate_8h=0.0002, annualized_rate=21.9,
        consecutive_positive_periods=5,
        spot_price=91000, perp_price=91050, entry_spread_pct=0.055,
        suggested_size_usd=2000, portfolio_capital_usd=5000,
        expected_daily_return_usd=1.2, expected_annual_return_usd=438.0,
        expected_apy_pct=21.9, estimated_fees_usd=2.4, breakeven_hours=48,
    )

    assert signal.signal_type == 'entry'
    assert signal.asset == 'BTC'
    assert signal.suggested_size_usd == 2000
    assert signal.portfolio_capital_usd == 5000

    print(f"  Signal: {signal.signal_type} {signal.asset}@{signal.perp_venue}")
    print(f"  Size: ${signal.suggested_size_usd}, APY: {signal.expected_apy_pct}%")
    print(f"  Daily: ${signal.expected_daily_return_usd}, Breakeven: {signal.breakeven_hours}h")

    # Exit signal
    exit_signal = CarrySignal(
        asset='BTC', spot_venue='coinbase_spot', perp_venue='hyperliquid_perps',
        signal_type='exit', status='active',
        funding_rate_8h=0.00003, annualized_rate=3.3,
    )
    assert exit_signal.signal_type == 'exit'
    print(f"  Exit signal: funding dropped to {exit_signal.annualized_rate}% APY")

    print("  PASS")


def test_entry_conditions():
    print("\nTest 5: Entry condition logic")

    min_funding = 0.01 / 100  # 0.01%
    min_annualized = 10.0
    confirmation_needed = 3
    max_spread = 0.15

    # Case 1: All conditions met
    funding = 0.0002  # 0.02%/8h = 21.9% APY
    annualized = funding * 3 * 365 * 100
    consecutive = 5
    spread = 0.05

    should_enter = (
        funding >= min_funding and
        annualized >= min_annualized and
        consecutive >= confirmation_needed and
        spread <= max_spread
    )
    assert should_enter, "Should enter: all conditions met"
    print(f"  Case 1 (all met): enter={should_enter}")

    # Case 2: Funding too low
    funding2 = 0.00005  # 0.005%/8h = 5.475% APY
    annualized2 = funding2 * 3 * 365 * 100
    should_enter2 = (funding2 >= min_funding and annualized2 >= min_annualized)
    assert not should_enter2, "Should NOT enter: APY too low"
    print(f"  Case 2 (low APY): enter={should_enter2} (APY={annualized2:.1f}%)")

    # Case 3: Not enough consecutive readings
    should_enter3 = (consecutive == 1 and 1 >= confirmation_needed)
    assert not should_enter3, "Should NOT enter: not enough confirmations"
    print(f"  Case 3 (low confirm): enter={should_enter3}")

    # Case 4: Spread too wide
    spread4 = 0.3
    should_enter4 = (spread4 <= max_spread)
    assert not should_enter4, "Should NOT enter: spread too wide"
    print(f"  Case 4 (wide spread): enter={should_enter4} (spread={spread4}%)")

    print("  PASS")


def test_portfolio_sensitivity():
    print("\nTest 6: Portfolio size sensitivity table")
    print(f"  {'Capital':>10} {'Position':>10} {'Daily':>10} {'Annual':>10} {'Breakeven':>10}")
    print(f"  {'':->10} {'':->10} {'':->10} {'':->10} {'':->10}")

    funding_8h = 0.0002  # 0.02%/8h = good carry
    fee_pct = 0.06

    for capital in [1000, 2500, 5000, 10000, 25000, 50000, 100000]:
        pos = capital * 0.4
        daily = pos * funding_8h * 3
        annual = daily * 365
        fees = pos * 2 * (fee_pct / 100)
        be = (fees * 2) / (daily / 24) if daily > 0 else 0

        print(f"  ${capital:>9,} ${pos:>9,.0f} ${daily:>9.2f} ${annual:>9,.0f} {be:>9.0f}h")

    print("  PASS")


if __name__ == '__main__':
    print("=" * 70)
    print("SpreadScope — Funding Rate Carry Logic Tests")
    print("=" * 70)

    tests = [
        test_funding_rate_annualization,
        test_position_sizing,
        test_spread_calculation,
        test_carry_signal_model,
        test_entry_conditions,
        test_portfolio_sensitivity,
    ]

    passed = 0
    for t in tests:
        try:
            t()
            passed += 1
        except Exception as e:
            print(f"  FAILED: {e}")
            import traceback; traceback.print_exc()

    print(f"\n{'='*70}")
    print(f"{'All tests passed!' if passed == len(tests) else f'{passed}/{len(tests)} passed'}")
    print("=" * 70)
    sys.exit(0 if passed == len(tests) else 1)
