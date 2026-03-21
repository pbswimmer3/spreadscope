#!/usr/bin/env python3
"""
Test spread calculation and opportunity logic using pure Python (no external deps).
"""
import sys
import asyncio
from datetime import datetime, timezone

# Inline the models we need (avoiding the import chain that requires asyncpg)
from dataclasses import dataclass, field
from typing import Optional, Dict, Any, List

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
class TrackedPair:
    asset: str
    real_venue: str
    synthetic_venue: str
    threshold_pct: float = 0.5
    is_enabled: bool = True

    @property
    def venue_pair(self):
        return f"{self.real_venue}:{self.synthetic_venue}"

# ---- Minimal SpreadEngine (pure logic, no DB) ----
class SpreadEngine:
    def __init__(self, config):
        self.config = config
        self.staleness_max = config.get('thresholds', {}).get('staleness_max_seconds', 120)
        self.price_cache = {}
        self.tracked_pairs = []

    def update_price_cache(self, observations):
        for obs in observations:
            key = (obs.asset, obs.venue)
            existing = self.price_cache.get(key)
            if existing is None or obs.time > existing.time:
                self.price_cache[key] = obs

    def get_cached_price(self, asset, venue):
        key = (asset, venue)
        obs = self.price_cache.get(key)
        if obs is None:
            return None
        age = (datetime.now(timezone.utc) - obs.time).total_seconds()
        if age > self.staleness_max:
            return None
        return obs

    def calculate_all_spreads(self):
        spreads = []
        for pair in self.tracked_pairs:
            real = self.get_cached_price(pair.asset, pair.real_venue)
            synth = self.get_cached_price(pair.asset, pair.synthetic_venue)
            if real and synth and real.price > 0 and synth.price > 0:
                s = Spread.from_prices(datetime.now(timezone.utc), pair.asset, real, synth)
                spreads.append(s)
        return spreads

# ---- Minimal OpportunityTracker (pure logic, no DB) ----
class OpportunityTracker:
    def __init__(self, config):
        self.config = config
        self.default_threshold = config.get('thresholds', {}).get('default_pct', 0.5)
        self.open_opps = {}  # (asset, venue_pair) -> dict
        self.spread_history = {}

    def process_spread(self, spread, threshold=None):
        if threshold is None:
            threshold = self.default_threshold
        key = (spread.asset, spread.venue_pair)
        abs_spread = abs(spread.spread_pct)
        existing = self.open_opps.get(key)

        if existing is not None:
            if abs_spread < threshold:
                self.open_opps.pop(key)
                self.spread_history.pop(key, None)
                return 'closed'
            else:
                existing['peak'] = max(existing['peak'], abs_spread)
                self.spread_history.setdefault(key, []).append(spread.spread_pct)
                existing['observations'] = len(self.spread_history[key])
                return 'updated'
        else:
            if abs_spread > threshold:
                self.open_opps[key] = {'entry': spread.spread_pct, 'peak': abs_spread, 'observations': 1}
                self.spread_history[key] = [spread.spread_pct]
                return 'opened'
        return None

    def count_open(self):
        return len(self.open_opps)

# ============ TESTS ============
def test_spread_math():
    print("Test 1: Spread math")
    now = datetime.now(timezone.utc)
    real = PriceObservation(time=now, asset='BTC', venue='coinbase_spot', price=67000.0)
    synth = PriceObservation(time=now, asset='BTC', venue='hyperliquid_perps', price=67335.0)
    
    s = Spread.from_prices(now, 'BTC', real, synth)
    expected_pct = (67335 - 67000) / 67000 * 100  # 0.5%
    assert abs(s.spread_pct - expected_pct) < 0.001, f"Expected {expected_pct:.4f}%, got {s.spread_pct:.4f}%"
    assert s.spread_abs == 335.0
    assert s.venue_pair == 'coinbase_spot:hyperliquid_perps'
    print(f"  ✅ Spread: {s.spread_pct:.4f}% (${s.spread_abs:.2f} absolute)")

def test_price_cache():
    print("\nTest 2: Price cache (staleness)")
    config = {'thresholds': {'staleness_max_seconds': 120}}
    engine = SpreadEngine(config)
    now = datetime.now(timezone.utc)
    
    engine.update_price_cache([
        PriceObservation(time=now, asset='BTC', venue='coinbase_spot', price=67000),
        PriceObservation(time=now, asset='ETH', venue='coinbase_spot', price=1958),
    ])
    
    assert engine.get_cached_price('BTC', 'coinbase_spot') is not None
    assert engine.get_cached_price('ETH', 'coinbase_spot') is not None
    assert engine.get_cached_price('SOL', 'coinbase_spot') is None  # Not cached
    print("  ✅ Cache hit/miss works correctly")
    
    # Stale price
    from datetime import timedelta
    old = datetime.now(timezone.utc) - timedelta(seconds=200)
    engine.update_price_cache([PriceObservation(time=old, asset='OLD', venue='test', price=100)])
    # Won't be returned because old < now, so won't override — test directly
    engine.price_cache[('STALE', 'test')] = PriceObservation(time=old, asset='STALE', venue='test', price=99)
    assert engine.get_cached_price('STALE', 'test') is None  # Too old
    print("  ✅ Stale prices correctly rejected")

def test_opportunity_lifecycle():
    print("\nTest 3: Opportunity open/close/update lifecycle")
    config = {'thresholds': {'default_pct': 0.5}}
    tracker = OpportunityTracker(config)
    now = datetime.now(timezone.utc)
    
    def make_spread(pct):
        real_p = 67000
        synth_p = real_p * (1 + pct / 100)
        return Spread(time=now, asset='BTC', real_venue='coinbase_spot',
                     synthetic_venue='hyperliquid_perps',
                     real_price=real_p, synthetic_price=synth_p,
                     spread_abs=synth_p - real_p, spread_pct=pct,
                     venue_pair='coinbase_spot:hyperliquid_perps')
    
    # Below threshold → no event
    result = tracker.process_spread(make_spread(0.2), 0.5)
    assert result is None
    assert tracker.count_open() == 0
    print("  ✅ Below threshold: no opportunity")
    
    # Above threshold → open
    result = tracker.process_spread(make_spread(0.7), 0.5)
    assert result == 'opened'
    assert tracker.count_open() == 1
    print("  ✅ Above threshold: opportunity opened")
    
    # Still above → update, peak tracked
    result = tracker.process_spread(make_spread(1.2), 0.5)
    assert result == 'updated'
    key = ('BTC', 'coinbase_spot:hyperliquid_perps')
    assert tracker.open_opps[key]['peak'] == 1.2
    print(f"  ✅ Peak updated to {tracker.open_opps[key]['peak']:.2f}%")
    
    # Drop back below → close
    result = tracker.process_spread(make_spread(0.1), 0.5)
    assert result == 'closed'
    assert tracker.count_open() == 0
    print("  ✅ Below threshold: opportunity closed")

def test_multiple_pairs():
    print("\nTest 4: Multiple simultaneous opportunities")
    config = {'thresholds': {'default_pct': 0.5, 'staleness_max_seconds': 120}}
    engine = SpreadEngine(config)
    tracker = OpportunityTracker(config)
    
    engine.tracked_pairs = [
        TrackedPair(asset='BTC', real_venue='coinbase_spot', synthetic_venue='hyperliquid_perps'),
        TrackedPair(asset='ETH', real_venue='coinbase_spot', synthetic_venue='hyperliquid_perps'),
    ]
    
    now = datetime.now(timezone.utc)
    engine.update_price_cache([
        PriceObservation(time=now, asset='BTC', venue='coinbase_spot', price=67000),
        PriceObservation(time=now, asset='BTC', venue='hyperliquid_perps', price=67750),  # +1.12%
        PriceObservation(time=now, asset='ETH', venue='coinbase_spot', price=1958),
        PriceObservation(time=now, asset='ETH', venue='hyperliquid_perps', price=1968),  # +0.51%
    ])
    
    spreads = engine.calculate_all_spreads()
    assert len(spreads) == 2
    
    for s in spreads:
        result = tracker.process_spread(s, 0.5)
        print(f"  {s.asset}: {s.spread_pct:+.4f}% → {result}")
        assert result == 'opened'
    
    assert tracker.count_open() == 2
    print("  ✅ Both opportunities opened simultaneously")

if __name__ == '__main__':
    print("=" * 60)
    print("SpreadScope — Calculator Logic Tests")
    print("=" * 60)
    
    tests = [test_spread_math, test_price_cache, test_opportunity_lifecycle, test_multiple_pairs]
    passed = 0
    
    for t in tests:
        try:
            t()
            passed += 1
        except Exception as e:
            print(f"  ❌ FAILED: {e}")
            import traceback; traceback.print_exc()
    
    print(f"\n{'='*60}")
    print(f"{'✅ All tests passed!' if passed == len(tests) else f'❌ {passed}/{len(tests)} passed'}")
    print("=" * 60)
    sys.exit(0 if passed == len(tests) else 1)