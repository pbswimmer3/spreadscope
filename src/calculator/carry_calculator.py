"""
SpreadScope - Funding Rate Carry Calculator

Detects carry trade opportunities by analyzing funding rates across perp venues.
Generates bot-readable signals with position sizing based on portfolio config.

Strategy: When perpetual futures funding rate is consistently positive (longs pay shorts),
go long spot + short perp to collect funding payments as yield.
"""

import asyncio
import logging
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any, Optional, Tuple

from ..db import (
    get_latest_price, get_latest_funding_rate,
    get_consecutive_positive_funding_count,
    insert_carry_signal, get_active_carry_signals,
    expire_old_signals, cancel_active_signals_for_pair,
    insert_spread,
)
from ..models import (
    PriceObservation, FundingRateSnapshot, CarrySignal, Spread, TrackedPair,
)
from ..utils import setup_logging, now_utc

logger = setup_logging('calculator.carry')


class CarryCalculator:
    """Detects funding rate carry opportunities and generates trading signals."""

    def __init__(self, config: Dict[str, Any], dry_run: bool = False):
        self.config = config
        self.dry_run = dry_run

        # Portfolio config
        portfolio = config.get('portfolio', {})
        self.capital_usd = portfolio.get('capital_usd', 5000)
        self.max_position_pct = portfolio.get('max_position_pct', 50)
        self.min_position_usd = portfolio.get('min_position_usd', 100)
        self.fee_per_trade_pct = portfolio.get('fee_per_trade_pct', 0.06)

        # Carry config
        carry = config.get('carry', {})
        self.min_annualized_rate = carry.get('min_annualized_rate_pct', 10.0)
        self.min_funding_rate = carry.get('min_funding_rate_pct', 0.01)
        self.confirmation_periods = carry.get('confirmation_periods', 3)
        self.max_entry_spread = carry.get('max_entry_spread_pct', 0.15)
        self.exit_funding_rate = carry.get('exit_funding_rate_pct', 0.005)
        self.spot_venues = carry.get('spot_venues', ['coinbase_spot'])
        self.perp_venues = carry.get('perp_venues', ['hyperliquid_perps', 'dydx'])

        # Assets
        self.assets = config.get('assets', ['BTC', 'ETH'])

        # Staleness
        self.staleness_max = config.get('thresholds', {}).get('staleness_max_seconds', 120)

        # In-memory price cache (populated from DB each cycle)
        self.price_cache: Dict[Tuple[str, str], PriceObservation] = {}

        # Track which pairs have active entry signals to avoid duplicates
        self._active_pairs: set = set()

    async def run_cycle(self) -> Dict[str, Any]:
        """Run a single calculation cycle. Returns summary of actions taken."""
        summary = {
            'spreads_computed': 0,
            'funding_rates_checked': 0,
            'signals_generated': 0,
            'signals_expired': 0,
            'opportunities': [],
        }

        # Step 1: Expire old signals
        expired = await expire_old_signals(24)
        summary['signals_expired'] = expired

        # Step 2: Refresh active signals list
        active = await get_active_carry_signals()
        self._active_pairs = {(s.asset, s.perp_venue) for s in active if s.signal_type == 'entry'}

        # Step 3: Load latest prices from DB into cache
        await self._refresh_price_cache()

        # Step 4: For each asset / perp venue combo, check funding rate
        for asset in self.assets:
            for perp_venue in self.perp_venues:
                result = await self._evaluate_pair(asset, perp_venue)
                summary['funding_rates_checked'] += 1
                if result:
                    summary['opportunities'].append(result)
                    summary['signals_generated'] += 1

        # Step 5: Compute spreads (still useful for monitoring)
        for asset in self.assets:
            for spot_venue in self.spot_venues:
                for perp_venue in self.perp_venues:
                    spread = await self._compute_and_store_spread(asset, spot_venue, perp_venue)
                    if spread:
                        summary['spreads_computed'] += 1

        return summary

    async def _refresh_price_cache(self):
        """Load latest prices from DB into in-memory cache."""
        all_venues = set(self.spot_venues + self.perp_venues)
        for asset in self.assets:
            for venue in all_venues:
                obs = await get_latest_price(asset, venue, self.staleness_max)
                if obs:
                    self.price_cache[(asset, venue)] = obs

    async def _evaluate_pair(self, asset: str, perp_venue: str) -> Optional[Dict[str, Any]]:
        """Evaluate a single asset/perp_venue for carry opportunity."""
        # Get latest funding rate
        fr = await get_latest_funding_rate(asset, perp_venue)
        if fr is None:
            logger.debug(f"No funding rate data for {asset}@{perp_venue}")
            return None

        # Check if funding rate data is stale (>1 hour)
        age = (now_utc() - fr.time).total_seconds()
        if age > 3600:
            logger.debug(f"Stale funding rate for {asset}@{perp_venue}: {age:.0f}s old")
            return None

        funding_rate_8h = fr.funding_rate
        annualized = fr.annualized_rate

        # Check for exit condition on active positions
        pair_key = (asset, perp_venue)
        if pair_key in self._active_pairs:
            if funding_rate_8h < self.exit_funding_rate / 100:  # Config is in pct
                # Funding dropped — generate exit signal
                return await self._generate_exit_signal(asset, perp_venue, fr)
            else:
                logger.debug(f"{asset}@{perp_venue}: active carry, funding still good "
                            f"({funding_rate_8h*100:.4f}%)")
                return None

        # Check entry conditions
        # 1. Funding rate above minimum
        if funding_rate_8h < self.min_funding_rate / 100:
            return None

        # 2. Annualized rate above minimum
        if annualized < self.min_annualized_rate:
            return None

        # 3. Consecutive positive readings
        consecutive = await get_consecutive_positive_funding_count(asset, perp_venue)
        if consecutive < self.confirmation_periods:
            logger.debug(f"{asset}@{perp_venue}: only {consecutive}/{self.confirmation_periods} "
                        f"consecutive positive periods")
            return None

        # 4. Check spot-perp spread isn't too wide
        spot_venue = self.spot_venues[0] if self.spot_venues else None
        if spot_venue:
            spot_obs = self.price_cache.get((asset, spot_venue))
            perp_obs = self.price_cache.get((asset, perp_venue))
            if spot_obs and perp_obs:
                spread_pct = abs(perp_obs.price - spot_obs.price) / spot_obs.price * 100
                if spread_pct > self.max_entry_spread:
                    logger.debug(f"{asset}: entry spread too wide ({spread_pct:.3f}% > {self.max_entry_spread}%)")
                    return None

        # All conditions met — generate entry signal
        return await self._generate_entry_signal(asset, perp_venue, fr, consecutive)

    async def _generate_entry_signal(self, asset: str, perp_venue: str,
                                     fr: FundingRateSnapshot,
                                     consecutive: int) -> Dict[str, Any]:
        """Generate an entry signal for a carry trade."""
        spot_venue = self.spot_venues[0]
        spot_obs = self.price_cache.get((asset, spot_venue))
        perp_obs = self.price_cache.get((asset, perp_venue))

        spot_price = spot_obs.price if spot_obs else (fr.mark_price or 0)
        perp_price = perp_obs.price if perp_obs else (fr.mark_price or 0)
        spread_pct = (perp_price - spot_price) / spot_price * 100 if spot_price > 0 else 0

        # Position sizing
        max_position = self.capital_usd * (self.max_position_pct / 100)
        # Each leg uses half the position (spot + perp)
        suggested_size = min(max_position, self.capital_usd * 0.4)
        if suggested_size < self.min_position_usd:
            logger.debug(f"Position too small: ${suggested_size:.2f} < ${self.min_position_usd}")
            return None

        # Fee estimate: entry = 2 legs * fee
        entry_fees = suggested_size * 2 * (self.fee_per_trade_pct / 100)

        # Expected returns
        daily_rate = fr.funding_rate * 3  # 3 funding periods per day
        expected_daily = suggested_size * daily_rate
        expected_annual = expected_daily * 365
        expected_apy = fr.annualized_rate

        # Breakeven: how many hours of funding to recoup entry + exit fees
        total_fees = entry_fees * 2  # entry + eventual exit
        hourly_return = expected_daily / 24
        breakeven_hours = total_fees / hourly_return if hourly_return > 0 else float('inf')

        signal = CarrySignal(
            asset=asset,
            spot_venue=spot_venue,
            perp_venue=perp_venue,
            signal_type='entry',
            status='active',
            funding_rate_8h=fr.funding_rate,
            annualized_rate=fr.annualized_rate,
            consecutive_positive_periods=consecutive,
            spot_price=spot_price,
            perp_price=perp_price,
            entry_spread_pct=spread_pct,
            suggested_size_usd=round(suggested_size, 2),
            suggested_leverage=1.0,
            portfolio_capital_usd=self.capital_usd,
            expected_daily_return_usd=round(expected_daily, 4),
            expected_annual_return_usd=round(expected_annual, 2),
            expected_apy_pct=round(expected_apy, 2),
            estimated_fees_usd=round(entry_fees, 2),
            breakeven_hours=round(breakeven_hours, 1),
            expires_at=now_utc() + timedelta(hours=24),
            notes=f"Funding {fr.funding_rate*100:.4f}%/8h, {consecutive} consecutive positive periods",
        )

        signal_id = await insert_carry_signal(signal)
        signal.id = signal_id

        logger.info(
            f"ENTRY SIGNAL: {asset} via {perp_venue} | "
            f"Funding: {fr.funding_rate*100:.4f}%/8h ({fr.annualized_rate:.1f}% APY) | "
            f"Size: ${suggested_size:.0f} | "
            f"Expected: ${expected_daily:.2f}/day | "
            f"Breakeven: {breakeven_hours:.0f}h"
        )

        return {
            'type': 'entry',
            'asset': asset,
            'venue': perp_venue,
            'apy': fr.annualized_rate,
            'signal_id': signal_id,
        }

    async def _generate_exit_signal(self, asset: str, perp_venue: str,
                                    fr: FundingRateSnapshot) -> Dict[str, Any]:
        """Generate an exit signal when funding rate drops."""
        spot_venue = self.spot_venues[0]
        spot_obs = self.price_cache.get((asset, spot_venue))
        perp_obs = self.price_cache.get((asset, perp_venue))

        spot_price = spot_obs.price if spot_obs else (fr.mark_price or 0)
        perp_price = perp_obs.price if perp_obs else (fr.mark_price or 0)
        spread_pct = (perp_price - spot_price) / spot_price * 100 if spot_price > 0 else 0

        signal = CarrySignal(
            asset=asset,
            spot_venue=spot_venue,
            perp_venue=perp_venue,
            signal_type='exit',
            status='active',
            funding_rate_8h=fr.funding_rate,
            annualized_rate=fr.annualized_rate,
            consecutive_positive_periods=0,
            spot_price=spot_price,
            perp_price=perp_price,
            entry_spread_pct=spread_pct,
            suggested_size_usd=0,
            portfolio_capital_usd=self.capital_usd,
            expires_at=now_utc() + timedelta(hours=4),
            notes=f"Funding dropped to {fr.funding_rate*100:.4f}%/8h — below exit threshold",
        )

        signal_id = await insert_carry_signal(signal)

        # Cancel any active entry signals for this pair
        await cancel_active_signals_for_pair(asset, perp_venue)

        logger.info(
            f"EXIT SIGNAL: {asset} via {perp_venue} | "
            f"Funding dropped to {fr.funding_rate*100:.4f}%/8h ({fr.annualized_rate:.1f}% APY)"
        )

        return {
            'type': 'exit',
            'asset': asset,
            'venue': perp_venue,
            'apy': fr.annualized_rate,
            'signal_id': signal_id,
        }

    async def _compute_and_store_spread(self, asset: str, spot_venue: str,
                                        perp_venue: str) -> Optional[Spread]:
        """Compute and store spread between spot and perp."""
        spot_obs = self.price_cache.get((asset, spot_venue))
        perp_obs = self.price_cache.get((asset, perp_venue))

        if not spot_obs or not perp_obs:
            return None

        spread = Spread.from_prices(
            time=now_utc(),
            asset=asset,
            real_price=spot_obs,
            synthetic_price=perp_obs,
        )

        await insert_spread(spread)
        return spread

    def get_status_summary(self) -> Dict[str, Any]:
        """Get current calculator status for dashboard."""
        return {
            'capital_usd': self.capital_usd,
            'assets': self.assets,
            'spot_venues': self.spot_venues,
            'perp_venues': self.perp_venues,
            'active_pairs': len(self._active_pairs),
            'cache_size': len(self.price_cache),
            'min_apy_threshold': self.min_annualized_rate,
        }
