"""
SpreadScope - Spread Calculator Engine

Computes price spreads between real and synthetic venues
for each tracked asset pair.
"""

import asyncio
import logging
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any, Optional, Tuple

from ..db import (
    get_tracked_pairs, insert_spread,
    insert_price_observations, get_open_opportunities
)
from ..models import PriceObservation, Spread, TrackedPair
from ..utils import setup_logging, now_utc

logger = setup_logging('calculator.spread_engine')


class SpreadEngine:
    """Computes spreads between real and synthetic price sources."""
    
    def __init__(self, config: Dict[str, Any], dry_run: bool = False):
        self.config = config
        self.dry_run = dry_run
        
        # Staleness threshold (seconds)
        self.staleness_max = config.get('thresholds', {}).get('staleness_max_seconds', 120)
        
        # In-memory price cache (for dry-run and fast lookups)
        # Structure: {(asset, venue): PriceObservation}
        self.price_cache: Dict[Tuple[str, str], PriceObservation] = {}
        
        # Tracked pairs (loaded from DB or config)
        self.tracked_pairs: List[TrackedPair] = []
    
    async def load_tracked_pairs(self):
        """Load tracked pairs from database or use defaults."""
        if self.dry_run:
            # Use default pairs for dry-run
            self.tracked_pairs = [
                TrackedPair(asset='BTC', real_venue='coinbase_spot', 
                          synthetic_venue='hyperliquid_perps', threshold_pct=0.5),
                TrackedPair(asset='ETH', real_venue='coinbase_spot', 
                          synthetic_venue='hyperliquid_perps', threshold_pct=0.5),
                TrackedPair(asset='BTC', real_venue='coinbase_spot', 
                          synthetic_venue='dydx', threshold_pct=0.5),
                TrackedPair(asset='ETH', real_venue='coinbase_spot', 
                          synthetic_venue='dydx', threshold_pct=0.5),
                TrackedPair(asset='BTC', real_venue='coinbase_spot', 
                          synthetic_venue='coinbase_perps', threshold_pct=0.5),
                TrackedPair(asset='ETH', real_venue='coinbase_spot', 
                          synthetic_venue='coinbase_perps', threshold_pct=0.5),
            ]
        else:
            self.tracked_pairs = await get_tracked_pairs()
        
        logger.info(f"Loaded {len(self.tracked_pairs)} tracked pairs")
    
    def update_price_cache(self, observations: List[PriceObservation]):
        """Update the in-memory price cache with new observations."""
        for obs in observations:
            key = (obs.asset, obs.venue)
            existing = self.price_cache.get(key)
            
            # Only update if newer
            if existing is None or obs.time > existing.time:
                self.price_cache[key] = obs
    
    def get_cached_price(self, asset: str, venue: str) -> Optional[PriceObservation]:
        """Get the latest cached price for an asset/venue."""
        key = (asset, venue)
        obs = self.price_cache.get(key)
        
        if obs is None:
            return None
        
        # Check staleness
        age = (now_utc() - obs.time).total_seconds()
        if age > self.staleness_max:
            logger.debug(f"Stale price for {asset}@{venue}: {age:.0f}s old (max: {self.staleness_max}s)")
            return None
        
        return obs
    
    async def calculate_spreads(self) -> List[Spread]:
        """Calculate spreads for all tracked pairs."""
        spreads = []
        
        for pair in self.tracked_pairs:
            if not pair.is_enabled:
                continue
            
            spread = await self._calculate_pair_spread(pair)
            if spread:
                spreads.append(spread)
                
                # Write to DB
                await insert_spread(spread)
                
                logger.debug(
                    f"Spread: {spread.asset} {spread.venue_pair} = "
                    f"{spread.spread_pct:+.4f}% "
                    f"(real: ${spread.real_price:.2f}, synth: ${spread.synthetic_price:.2f})"
                )
        
        return spreads
    
    async def _calculate_pair_spread(self, pair: TrackedPair) -> Optional[Spread]:
        """Calculate spread for a single tracked pair."""
        # Get latest prices from cache
        real_price = self.get_cached_price(pair.asset, pair.real_venue)
        synthetic_price = self.get_cached_price(pair.asset, pair.synthetic_venue)
        
        if real_price is None:
            logger.debug(f"No fresh price for {pair.asset}@{pair.real_venue}")
            return None
        
        if synthetic_price is None:
            logger.debug(f"No fresh price for {pair.asset}@{pair.synthetic_venue}")
            return None
        
        # Validate prices
        if real_price.price <= 0 or synthetic_price.price <= 0:
            logger.warning(f"Invalid price detected for {pair.asset}: "
                         f"real={real_price.price}, synthetic={synthetic_price.price}")
            return None
        
        # Calculate spread
        spread = Spread.from_prices(
            time=now_utc(),
            asset=pair.asset,
            real_price=real_price,
            synthetic_price=synthetic_price
        )
        
        return spread
    
    def get_all_current_spreads(self) -> List[Dict[str, Any]]:
        """Get current spread for each tracked pair (for dashboard)."""
        results = []
        
        for pair in self.tracked_pairs:
            real_price = self.get_cached_price(pair.asset, pair.real_venue)
            synthetic_price = self.get_cached_price(pair.asset, pair.synthetic_venue)
            
            if real_price and synthetic_price:
                spread_abs = synthetic_price.price - real_price.price
                spread_pct = (spread_abs / real_price.price) * 100
                
                results.append({
                    'asset': pair.asset,
                    'venue_pair': pair.venue_pair,
                    'real_venue': pair.real_venue,
                    'synthetic_venue': pair.synthetic_venue,
                    'real_price': real_price.price,
                    'synthetic_price': synthetic_price.price,
                    'spread_abs': spread_abs,
                    'spread_pct': spread_pct,
                    'threshold_pct': pair.threshold_pct,
                    'is_opportunity': abs(spread_pct) > pair.threshold_pct,
                    'real_price_age': (now_utc() - real_price.time).total_seconds(),
                    'synthetic_price_age': (now_utc() - synthetic_price.time).total_seconds(),
                })
        
        return results