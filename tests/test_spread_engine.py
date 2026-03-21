#!/usr/bin/env python3
"""Test the spread engine and opportunity tracker with mock data."""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime, timezone
from src.models import PriceObservation, Spread, TrackedPair
from src.calculator.spread_engine import SpreadEngine
from src.calculator.opportunity_tracker import OpportunityTracker

def test_spread_calculation():
    """Test basic spread calculation."""
    print("Test 1: Basic spread calculation")
    
    config = {'thresholds': {'default_pct': 0.5, 'staleness_max_seconds': 120}}
    engine = SpreadEngine(config, dry_run=True)
    
    # Manually set tracked pairs
    engine.tracked_pairs = [
        TrackedPair(asset='BTC', real_venue='coinbase_spot', 
                   synthetic_venue='hyperliquid_perps', threshold_pct=0.5),
    ]
    
    now = datetime.now(timezone.utc)
    
    # Add prices to cache
    engine.update_price_cache([
        PriceObservation(time=now, asset='BTC', venue='coinbase_spot', price=67000.0),
        PriceObservation(time=now, asset='BTC', venue='hyperliquid_perps', price=67335.0),
    ])
    
    # Get cached price
    real = engine.get_cached_price('BTC', 'coinbase_spot')
    synth = engine.get_cached_price('BTC', 'hyperliquid_perps')
    
    assert real is not None, "Real price should be cached"
    assert synth is not None, "Synthetic price should be cached"
    assert real.price == 67000.0
    assert synth.price == 67335.0
    
    # Calculate spread manually
    spread = Spread.from_prices(now, 'BTC', real, synth)
    assert abs(spread.spread_pct - 0.5) < 0.01, f"Expected ~0.5%, got {spread.spread_pct}"
    
    print(f"  ✅ Spread: {spread.spread_pct:.4f}% (expected ~0.5%)")
    print(f"  Real: ${spread.real_price:.2f}, Synth: ${spread.synthetic_price:.2f}")
    return True

def test_opportunity_tracking():
    """Test opportunity open/close logic."""
    print("\nTest 2: Opportunity tracking")
    
    config = {'thresholds': {'default_pct': 0.5}}
    tracker = OpportunityTracker(config, dry_run=True)
    
    now = datetime.now(timezone.utc)
    
    # Spread below threshold — should not open
    spread1 = Spread(
        time=now, asset='BTC', real_venue='coinbase_spot',
        synthetic_venue='hyperliquid_perps',
        real_price=67000, synthetic_price=67100,
        spread_abs=100, spread_pct=0.15,
        venue_pair='coinbase_spot:hyperliquid_perps'
    )
    
    import asyncio
    loop = asyncio.new_event_loop()
    
    result = loop.run_until_complete(tracker.process_spread(spread1, 0.5))
    assert result is None, f"Expected None (below threshold), got {result}"
    assert tracker.get_open_opportunity_count() == 0
    print("  ✅ Below threshold: no opportunity opened")
    
    # Spread above threshold — should open
    spread2 = Spread(
        time=now, asset='BTC', real_venue='coinbase_spot',
        synthetic_venue='hyperliquid_perps',
        real_price=67000, synthetic_price=67500,
        spread_abs=500, spread_pct=0.75,
        venue_pair='coinbase_spot:hyperliquid_perps'
    )
    
    result = loop.run_until_complete(tracker.process_spread(spread2, 0.5))
    assert result == 'opened', f"Expected 'opened', got {result}"
    assert tracker.get_open_opportunity_count() == 1
    print("  ✅ Above threshold: opportunity opened")
    
    # Still above threshold — should update
    spread3 = Spread(
        time=now, asset='BTC', real_venue='coinbase_spot',
        synthetic_venue='hyperliquid_perps',
        real_price=67000, synthetic_price=67600,
        spread_abs=600, spread_pct=0.90,
        venue_pair='coinbase_spot:hyperliquid_perps'
    )
    
    result = loop.run_until_complete(tracker.process_spread(spread3, 0.5))
    assert result == 'updated', f"Expected 'updated', got {result}"
    assert tracker.get_open_opportunity_count() == 1
    print("  ✅ Still above threshold: opportunity updated")
    
    # Check peak was updated
    summaries = tracker.get_open_opportunities_summary()
    assert len(summaries) == 1
    assert summaries[0]['peak_spread_pct'] == 0.90
    print(f"  ✅ Peak updated to {summaries[0]['peak_spread_pct']:.2f}%")
    
    # Back below threshold — should close
    spread4 = Spread(
        time=now, asset='BTC', real_venue='coinbase_spot',
        synthetic_venue='hyperliquid_perps',
        real_price=67000, synthetic_price=67100,
        spread_abs=100, spread_pct=0.15,
        venue_pair='coinbase_spot:hyperliquid_perps'
    )
    
    result = loop.run_until_complete(tracker.process_spread(spread4, 0.5))
    assert result == 'closed', f"Expected 'closed', got {result}"
    assert tracker.get_open_opportunity_count() == 0
    print("  ✅ Below threshold: opportunity closed")
    
    loop.close()
    return True

def test_multiple_pairs():
    """Test tracking multiple pairs simultaneously."""
    print("\nTest 3: Multiple pairs")
    
    config = {'thresholds': {'default_pct': 0.5, 'staleness_max_seconds': 120}}
    engine = SpreadEngine(config, dry_run=True)
    tracker = OpportunityTracker(config, dry_run=True)
    
    engine.tracked_pairs = [
        TrackedPair(asset='BTC', real_venue='coinbase_spot',
                   synthetic_venue='hyperliquid_perps', threshold_pct=0.5),
        TrackedPair(asset='ETH', real_venue='coinbase_spot',
                   synthetic_venue='hyperliquid_perps', threshold_pct=0.5),
    ]
    
    now = datetime.now(timezone.utc)
    
    # Both above threshold
    engine.update_price_cache([
        PriceObservation(time=now, asset='BTC', venue='coinbase_spot', price=67000),
        PriceObservation(time=now, asset='BTC', venue='hyperliquid_perps', price=67700),
        PriceObservation(time=now, asset='ETH', venue='coinbase_spot', price=1958),
        PriceObservation(time=now, asset='ETH', venue='hyperliquid_perps', price=1975),
    ])
    
    current = engine.get_all_current_spreads()
    assert len(current) == 2
    
    btc_spread = [c for c in current if c['asset'] == 'BTC'][0]
    eth_spread = [c for c in current if c['asset'] == 'ETH'][0]
    
    print(f"  BTC spread: {btc_spread['spread_pct']:.4f}% (opportunity: {btc_spread['is_opportunity']})")
    print(f"  ETH spread: {eth_spread['spread_pct']:.4f}% (opportunity: {eth_spread['is_opportunity']})")
    
    assert btc_spread['is_opportunity'] == True  # ~1.04%
    assert eth_spread['is_opportunity'] == True   # ~0.87%
    
    print("  ✅ Multiple pairs tracked correctly")
    return True

if __name__ == '__main__':
    all_passed = True
    
    print("=" * 60)
    print("SpreadScope — Spread Engine & Opportunity Tracker Tests")
    print("=" * 60)
    
    tests = [
        test_spread_calculation,
        test_opportunity_tracking,
        test_multiple_pairs,
    ]
    
    for test in tests:
        try:
            passed = test()
            if not passed:
                all_passed = False
        except Exception as e:
            print(f"  ❌ FAILED: {e}")
            import traceback
            traceback.print_exc()
            all_passed = False
    
    print("\n" + "=" * 60)
    if all_passed:
        print("✅ All tests passed!")
    else:
        print("❌ Some tests failed!")
    print("=" * 60)
    
    sys.exit(0 if all_passed else 1)