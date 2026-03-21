"""
SpreadScope - Opportunity Tracker

Tracks when spreads exceed thresholds, opening and closing
opportunity events with duration, peak, and average statistics.
"""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any

from ..db import insert_opportunity, update_opportunity, get_open_opportunities
from ..models import OpportunityEvent, Spread
from ..utils import setup_logging, now_utc

logger = setup_logging('calculator.opportunity_tracker')


class OpportunityTracker:
    """Tracks spread opportunities (when spreads exceed thresholds)."""
    
    def __init__(self, config: Dict[str, Any], dry_run: bool = False):
        self.config = config
        self.dry_run = dry_run
        
        # Default threshold
        self.default_threshold_pct = config.get('thresholds', {}).get('default_pct', 0.5)
        
        # In-memory state of open opportunities
        # Key: (asset, venue_pair) -> OpportunityEvent
        self.open_opportunities: Dict[tuple, OpportunityEvent] = {}
        
        # Spread accumulator for computing averages
        # Key: (asset, venue_pair) -> list of spread_pct values
        self.spread_history: Dict[tuple, List[float]] = {}
        
        # Flush counter (flush to DB every N observations)
        self.flush_interval = 10
        self.flush_counter = 0
    
    async def load_existing_opportunities(self):
        """Load any existing open opportunities from the database."""
        if self.dry_run:
            logger.info("DRY-RUN: Skipping opportunity load from database")
            return
        
        try:
            open_opps = await get_open_opportunities()
            for opp in open_opps:
                key = (opp.asset, opp.venue_pair)
                self.open_opportunities[key] = opp
                self.spread_history[key] = []
                logger.info(f"Loaded open opportunity: {opp.asset} {opp.venue_pair} "
                          f"(opened {opp.opened_at})")
            
            logger.info(f"Loaded {len(open_opps)} existing open opportunities")
        except Exception as e:
            logger.error(f"Failed to load existing opportunities: {e}")
    
    async def process_spread(self, spread: Spread, threshold_pct: float = None) -> Optional[str]:
        """
        Process a new spread calculation.
        
        Returns:
            'opened' if a new opportunity was opened
            'closed' if an existing opportunity was closed
            'updated' if an existing opportunity was updated
            None if no change
        """
        if threshold_pct is None:
            threshold_pct = self.default_threshold_pct
        
        key = (spread.asset, spread.venue_pair)
        abs_spread = abs(spread.spread_pct)
        
        # Check if there's an open opportunity for this pair
        existing_opp = self.open_opportunities.get(key)
        
        if existing_opp is not None:
            # We have an open opportunity
            if abs_spread < threshold_pct:
                # Spread dropped below threshold — close the opportunity
                result = await self._close_opportunity(key, spread)
                return 'closed'
            else:
                # Still above threshold — update
                self._update_opportunity(key, spread)
                return 'updated'
        else:
            # No open opportunity
            if abs_spread > threshold_pct:
                # Spread exceeds threshold — open new opportunity
                await self._open_opportunity(key, spread, threshold_pct)
                return 'opened'
        
        return None
    
    async def _open_opportunity(self, key: tuple, spread: Spread, threshold_pct: float):
        """Open a new opportunity event."""
        asset, venue_pair = key
        
        opp = OpportunityEvent(
            asset=asset,
            venue_pair=venue_pair,
            threshold_pct=threshold_pct,
            opened_at=now_utc(),
            entry_spread_pct=spread.spread_pct,
            peak_spread_pct=abs(spread.spread_pct),
            observations_count=1,
            metadata={
                'entry_real_price': spread.real_price,
                'entry_synthetic_price': spread.synthetic_price,
            }
        )
        
        # Insert into database
        try:
            opp_id = await insert_opportunity(opp)
            opp.id = opp_id
        except Exception as e:
            logger.error(f"Failed to insert opportunity: {e}")
        
        # Track in memory
        self.open_opportunities[key] = opp
        self.spread_history[key] = [spread.spread_pct]
        
        logger.info(
            f"🔔 OPPORTUNITY OPENED: {asset} {venue_pair} | "
            f"Spread: {spread.spread_pct:+.4f}% | "
            f"Threshold: {threshold_pct:.2f}%"
        )
    
    async def _close_opportunity(self, key: tuple, spread: Spread) -> OpportunityEvent:
        """Close an existing opportunity event."""
        opp = self.open_opportunities.pop(key)
        history = self.spread_history.pop(key, [])
        
        # Calculate statistics
        opp.closed_at = now_utc()
        opp.exit_spread_pct = spread.spread_pct
        opp.duration_seconds = int((opp.closed_at - opp.opened_at).total_seconds())
        opp.observations_count = len(history) + 1  # +1 for the closing observation
        
        if history:
            opp.avg_spread_pct = sum(abs(s) for s in history) / len(history)
        
        # Update in database
        try:
            await update_opportunity(opp)
        except Exception as e:
            logger.error(f"Failed to update opportunity on close: {e}")
        
        logger.info(
            f"🔕 OPPORTUNITY CLOSED: {opp.asset} {opp.venue_pair} | "
            f"Duration: {opp.duration_seconds}s | "
            f"Peak: {opp.peak_spread_pct:.4f}% | "
            f"Avg: {opp.avg_spread_pct:.4f}% | "
            f"Observations: {opp.observations_count}"
        )
        
        return opp
    
    def _update_opportunity(self, key: tuple, spread: Spread):
        """Update an existing open opportunity with new spread data."""
        opp = self.open_opportunities[key]
        
        # Update peak
        abs_spread = abs(spread.spread_pct)
        if opp.peak_spread_pct is None or abs_spread > opp.peak_spread_pct:
            opp.peak_spread_pct = abs_spread
        
        # Track spread history
        if key not in self.spread_history:
            self.spread_history[key] = []
        self.spread_history[key].append(spread.spread_pct)
        
        opp.observations_count = len(self.spread_history[key])
        
        # Periodic flush to database
        self.flush_counter += 1
        if self.flush_counter >= self.flush_interval:
            self.flush_counter = 0
            asyncio.create_task(self._flush_to_db())
    
    async def _flush_to_db(self):
        """Flush in-memory opportunity state to database."""
        for key, opp in self.open_opportunities.items():
            history = self.spread_history.get(key, [])
            if history:
                opp.avg_spread_pct = sum(abs(s) for s in history) / len(history)
            
            try:
                await update_opportunity(opp)
            except Exception as e:
                logger.error(f"Failed to flush opportunity {key}: {e}")
        
        logger.debug(f"Flushed {len(self.open_opportunities)} open opportunities to database")
    
    def get_open_opportunity_count(self) -> int:
        """Get count of currently open opportunities."""
        return len(self.open_opportunities)
    
    def get_open_opportunities_summary(self) -> List[Dict[str, Any]]:
        """Get summary of all open opportunities."""
        summaries = []
        
        for key, opp in self.open_opportunities.items():
            history = self.spread_history.get(key, [])
            duration = (now_utc() - opp.opened_at).total_seconds() if opp.opened_at else 0
            
            summaries.append({
                'asset': opp.asset,
                'venue_pair': opp.venue_pair,
                'opened_at': opp.opened_at.isoformat() if opp.opened_at else None,
                'duration_seconds': int(duration),
                'entry_spread_pct': opp.entry_spread_pct,
                'peak_spread_pct': opp.peak_spread_pct,
                'current_avg_spread_pct': sum(abs(s) for s in history) / len(history) if history else 0,
                'observations_count': len(history),
                'threshold_pct': opp.threshold_pct,
            })
        
        return summaries