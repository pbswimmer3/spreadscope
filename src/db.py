"""
SpreadScope - Database connection and query helpers
"""

import asyncio
import logging
from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta

import asyncpg
from asyncpg.pool import Pool

from .models import (PriceObservation, Spread, OpportunityEvent, VenueConfig,
                     TrackedPair, FundingRateSnapshot, CarrySignal)
from .utils import setup_logging, load_config

logger = setup_logging(__name__)

# Global connection pool
_pool: Optional[Pool] = None
_config: Optional[Dict[str, Any]] = None
_dry_run: bool = False

async def init_db(config_path: Optional[str] = None, dry_run: bool = False) -> None:
    """Initialize database connection pool."""
    global _pool, _config, _dry_run
    
    _dry_run = dry_run
    
    if dry_run:
        logger.info("Running in DRY-RUN mode - no database operations will be performed")
        return
    
    try:
        _config = load_config(config_path)
        db_config = _config['database']
        
        logger.info(f"Connecting to database: {db_config['host']}:{db_config['port']}/{db_config['name']}")
        
        _pool = await asyncpg.create_pool(
            host=db_config['host'],
            port=db_config['port'],
            database=db_config['name'],
            user=db_config['user'],
            password=db_config['password'],
            min_size=5,
            max_size=20,
            command_timeout=60
        )
        
        logger.info("Database connection pool created successfully")
        
    except Exception as e:
        logger.error(f"Failed to initialize database: {e}")
        if dry_run:
            logger.warning("Continuing in dry-run mode despite error")
        else:
            raise

async def get_pool() -> Pool:
    """Get database connection pool."""
    if _dry_run:
        raise RuntimeError("Cannot get pool in dry-run mode")
    
    if _pool is None:
        await init_db()
    
    return _pool

async def close_db() -> None:
    """Close database connection pool."""
    global _pool
    
    if _pool:
        await _pool.close()
        _pool = None
        logger.info("Database connection pool closed")

# Price observation operations
async def insert_price_observations(observations: List[PriceObservation]) -> int:
    """Insert price observations into database."""
    if _dry_run:
        logger.info(f"DRY-RUN: Would insert {len(observations)} price observations")
        for obs in observations[:3]:  # Log first 3
            logger.debug(f"  - {obs.time}: {obs.asset}@{obs.venue} = ${obs.price}")
        if len(observations) > 3:
            logger.debug(f"  ... and {len(observations) - 3} more")
        return len(observations)
    
    pool = await get_pool()
    
    query = """
        INSERT INTO price_observations
        (time, asset, venue, price, volume_24h, funding_rate, open_interest, extra_data)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
    """
    
    records = []
    for obs in observations:
        # Serialize extra_data dict to JSON string for DB storage
        extra = obs.extra_data
        if isinstance(extra, dict):
            import json
            extra = json.dumps(extra)
        records.append((
            obs.time,
            obs.asset,
            obs.venue,
            obs.price,
            obs.volume_24h,
            obs.funding_rate,
            obs.open_interest,
            extra
        ))
    
    async with pool.acquire() as conn:
        result = await conn.executemany(query, records)
    
    logger.debug(f"Inserted {len(observations)} price observations")
    return len(observations)

async def get_latest_price(asset: str, venue: str, max_age_seconds: int = 120) -> Optional[PriceObservation]:
    """Get latest price observation for an asset/venue."""
    if _dry_run:
        logger.debug(f"DRY-RUN: Would get latest price for {asset}@{venue}")
        return None
    
    pool = await get_pool()
    
    query = """
        SELECT time, asset, venue, price, volume_24h, funding_rate, open_interest, extra_data
        FROM price_observations
        WHERE asset = $1 AND venue = $2 AND time > NOW() - make_interval(secs => $3)
        ORDER BY time DESC
        LIMIT 1
    """

    async with pool.acquire() as conn:
        row = await conn.fetchrow(query, asset, venue, float(max_age_seconds))
    
    if row:
        return PriceObservation.from_dict(dict(row))
    return None

async def get_recent_prices(asset: str, venue: str, hours: int = 24) -> List[PriceObservation]:
    """Get recent price observations for an asset/venue."""
    if _dry_run:
        logger.debug(f"DRY-RUN: Would get recent prices for {asset}@{venue} (last {hours}h)")
        return []
    
    pool = await get_pool()
    
    query = """
        SELECT time, asset, venue, price, volume_24h, funding_rate, open_interest, extra_data
        FROM price_observations
        WHERE asset = $1 AND venue = $2 AND time > NOW() - make_interval(hours => $3)
        ORDER BY time DESC
    """

    async with pool.acquire() as conn:
        rows = await conn.fetch(query, asset, venue, float(hours))
    
    return [PriceObservation.from_dict(dict(row)) for row in rows]

# Spread operations
async def insert_spread(spread: Spread) -> None:
    """Insert a calculated spread into database."""
    if _dry_run:
        logger.info(f"DRY-RUN: Would insert spread: {spread.asset} {spread.venue_pair} = {spread.spread_pct:.4f}%")
        return
    
    pool = await get_pool()
    
    query = """
        INSERT INTO spreads 
        (time, asset, real_venue, synthetic_venue, real_price, synthetic_price, spread_abs, spread_pct, venue_pair)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
    """
    
    async with pool.acquire() as conn:
        await conn.execute(
            query,
            spread.time,
            spread.asset,
            spread.real_venue,
            spread.synthetic_venue,
            spread.real_price,
            spread.synthetic_price,
            spread.spread_abs,
            spread.spread_pct,
            spread.venue_pair
        )
    
    logger.debug(f"Inserted spread: {spread.asset} {spread.venue_pair} = {spread.spread_pct:.4f}%")

async def get_recent_spreads(asset: str, venue_pair: str, hours: int = 24) -> List[Spread]:
    """Get recent spreads for an asset/venue pair."""
    if _dry_run:
        logger.debug(f"DRY-RUN: Would get recent spreads for {asset} {venue_pair} (last {hours}h)")
        return []
    
    pool = await get_pool()
    
    query = """
        SELECT time, asset, real_venue, synthetic_venue, real_price, synthetic_price, spread_abs, spread_pct, venue_pair
        FROM spreads
        WHERE asset = $1 AND venue_pair = $2 AND time > NOW() - make_interval(hours => $3)
        ORDER BY time DESC
    """

    async with pool.acquire() as conn:
        rows = await conn.fetch(query, asset, venue_pair, float(hours))
    
    spreads = []
    for row in rows:
        spreads.append(Spread(
            time=row['time'],
            asset=row['asset'],
            real_venue=row['real_venue'],
            synthetic_venue=row['synthetic_venue'],
            real_price=row['real_price'],
            synthetic_price=row['synthetic_price'],
            spread_abs=row['spread_abs'],
            spread_pct=row['spread_pct'],
            venue_pair=row['venue_pair']
        ))
    
    return spreads

# Opportunity operations
async def insert_opportunity(opportunity: OpportunityEvent) -> int:
    """Insert a new opportunity event and return its ID."""
    if _dry_run:
        logger.info(f"DRY-RUN: Would insert opportunity: {opportunity.asset} {opportunity.venue_pair}")
        return 0
    
    pool = await get_pool()
    
    query = """
        INSERT INTO opportunity_events 
        (asset, venue_pair, threshold_pct, opened_at, entry_spread_pct, metadata)
        VALUES ($1, $2, $3, $4, $5, $6)
        RETURNING id
    """
    
    async with pool.acquire() as conn:
        opportunity_id = await conn.fetchval(
            query,
            opportunity.asset,
            opportunity.venue_pair,
            opportunity.threshold_pct,
            opportunity.opened_at,
            opportunity.entry_spread_pct,
            opportunity.metadata
        )
    
    logger.info(f"Inserted opportunity #{opportunity_id}: {opportunity.asset} {opportunity.venue_pair}")
    return opportunity_id

async def update_opportunity(opportunity: OpportunityEvent) -> None:
    """Update an existing opportunity event."""
    if _dry_run:
        logger.info(f"DRY-RUN: Would update opportunity #{opportunity.id}")
        return
    
    if opportunity.id is None:
        raise ValueError("Opportunity ID is required for update")
    
    pool = await get_pool()
    
    query = """
        UPDATE opportunity_events 
        SET closed_at = $2, duration_seconds = $3, peak_spread_pct = $4, 
            avg_spread_pct = $5, exit_spread_pct = $6, observations_count = $7,
            metadata = $8, updated_at = NOW()
        WHERE id = $1
    """
    
    async with pool.acquire() as conn:
        await conn.execute(
            query,
            opportunity.id,
            opportunity.closed_at,
            opportunity.duration_seconds,
            opportunity.peak_spread_pct,
            opportunity.avg_spread_pct,
            opportunity.exit_spread_pct,
            opportunity.observations_count,
            opportunity.metadata
        )
    
    logger.debug(f"Updated opportunity #{opportunity.id}")

async def get_open_opportunities() -> List[OpportunityEvent]:
    """Get all open opportunity events."""
    if _dry_run:
        logger.debug("DRY-RUN: Would get open opportunities")
        return []
    
    pool = await get_pool()
    
    query = """
        SELECT id, asset, venue_pair, threshold_pct, opened_at, closed_at,
               duration_seconds, peak_spread_pct, avg_spread_pct, entry_spread_pct,
               exit_spread_pct, observations_count, metadata
        FROM opportunity_events
        WHERE closed_at IS NULL
        ORDER BY opened_at DESC
    """
    
    async with pool.acquire() as conn:
        rows = await conn.fetch(query)
    
    return [OpportunityEvent.from_dict(dict(row)) for row in rows]

async def get_opportunity_by_asset_pair(asset: str, venue_pair: str) -> Optional[OpportunityEvent]:
    """Get open opportunity for a specific asset/venue pair."""
    if _dry_run:
        logger.debug(f"DRY-RUN: Would get opportunity for {asset} {venue_pair}")
        return None
    
    pool = await get_pool()
    
    query = """
        SELECT id, asset, venue_pair, threshold_pct, opened_at, closed_at,
               duration_seconds, peak_spread_pct, avg_spread_pct, entry_spread_pct,
               exit_spread_pct, observations_count, metadata
        FROM opportunity_events
        WHERE asset = $1 AND venue_pair = $2 AND closed_at IS NULL
        LIMIT 1
    """
    
    async with pool.acquire() as conn:
        row = await conn.fetchrow(query, asset, venue_pair)
    
    if row:
        return OpportunityEvent.from_dict(dict(row))
    return None

# Configuration operations
async def get_venue_configs() -> List[VenueConfig]:
    """Get all venue configurations."""
    if _dry_run:
        logger.debug("DRY-RUN: Would get venue configs")
        return []
    
    pool = await get_pool()
    
    query = """
        SELECT venue, display_name, venue_type, api_base_url, 
               polling_interval_seconds, is_enabled, supports_assets
        FROM venue_config
        WHERE is_enabled = true
        ORDER BY venue
    """
    
    async with pool.acquire() as conn:
        rows = await conn.fetch(query)
    
    configs = []
    for row in rows:
        configs.append(VenueConfig(
            venue=row['venue'],
            display_name=row['display_name'],
            venue_type=row['venue_type'],
            api_base_url=row['api_base_url'],
            polling_interval_seconds=row['polling_interval_seconds'],
            is_enabled=row['is_enabled'],
            supports_assets=row['supports_assets']
        ))
    
    return configs

async def get_tracked_pairs() -> List[TrackedPair]:
    """Get all tracked pairs for spread calculation."""
    if _dry_run:
        logger.debug("DRY-RUN: Would get tracked pairs")
        return []
    
    pool = await get_pool()
    
    query = """
        SELECT id, asset, real_venue, synthetic_venue, threshold_pct, is_enabled
        FROM tracked_pairs
        WHERE is_enabled = true
        ORDER BY asset, real_venue, synthetic_venue
    """
    
    async with pool.acquire() as conn:
        rows = await conn.fetch(query)
    
    pairs = []
    for row in rows:
        pairs.append(TrackedPair(
            id=row['id'],
            asset=row['asset'],
            real_venue=row['real_venue'],
            synthetic_venue=row['synthetic_venue'],
            threshold_pct=row['threshold_pct'],
            is_enabled=row['is_enabled']
        ))
    
    return pairs

# Dashboard queries
async def get_current_spreads() -> List[Dict[str, Any]]:
    """Get current spreads for dashboard."""
    if _dry_run:
        logger.debug("DRY-RUN: Would get current spreads")
        return []
    
    pool = await get_pool()
    
    query = """
        SELECT asset, venue_pair, spread_pct, time, real_price, synthetic_price,
               EXTRACT(EPOCH FROM (NOW() - time)) as seconds_ago
        FROM spreads
        WHERE time > NOW() - INTERVAL '5 minutes'
        ORDER BY ABS(spread_pct) DESC
        LIMIT 50
    """
    
    async with pool.acquire() as conn:
        rows = await conn.fetch(query)
    
    return [dict(row) for row in rows]

async def get_opportunity_stats(days: int = 7) -> Dict[str, Any]:
    """Get opportunity statistics for dashboard."""
    if _dry_run:
        logger.debug(f"DRY-RUN: Would get opportunity stats (last {days} days)")
        return {}
    
    pool = await get_pool()
    
    # Total opportunities
    query_total = """
        SELECT COUNT(*) as total_count,
               COUNT(CASE WHEN closed_at IS NULL THEN 1 END) as open_count,
               AVG(duration_seconds) as avg_duration,
               AVG(peak_spread_pct) as avg_peak_spread
        FROM opportunity_events
        WHERE opened_at > NOW() - make_interval(days => $1)
    """

    # Opportunities by asset
    query_by_asset = """
        SELECT asset, COUNT(*) as count,
               AVG(duration_seconds) as avg_duration,
               AVG(peak_spread_pct) as avg_peak_spread
        FROM opportunity_events
        WHERE opened_at > NOW() - make_interval(days => $1)
        GROUP BY asset
        ORDER BY count DESC
    """

    async with pool.acquire() as conn:
        total_stats = await conn.fetchrow(query_total, float(days))
        asset_stats = await conn.fetch(query_by_asset, float(days))
    
    return {
        'total_count': total_stats['total_count'] if total_stats else 0,
        'open_count': total_stats['open_count'] if total_stats else 0,
        'avg_duration': float(total_stats['avg_duration']) if total_stats and total_stats['avg_duration'] else 0,
        'avg_peak_spread': float(total_stats['avg_peak_spread']) if total_stats and total_stats['avg_peak_spread'] else 0,
        'by_asset': [dict(row) for row in asset_stats]
    }

# ============================================================================
# Funding Rate Operations
# ============================================================================

async def insert_funding_rate_snapshot(snapshot: FundingRateSnapshot) -> None:
    """Insert a funding rate snapshot."""
    if _dry_run:
        logger.info(f"DRY-RUN: Would insert funding rate: {snapshot.asset}@{snapshot.venue} "
                    f"= {snapshot.funding_rate:.6f} ({snapshot.annualized_rate:.2f}% APY)")
        return

    pool = await get_pool()
    import json

    query = """
        INSERT INTO funding_rate_snapshots
        (time, asset, venue, funding_rate, annualized_rate, next_funding_time,
         mark_price, index_price, open_interest, volume_24h, extra_data)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
    """

    extra = json.dumps(snapshot.extra_data) if snapshot.extra_data else '{}'

    async with pool.acquire() as conn:
        await conn.execute(
            query,
            snapshot.time, snapshot.asset, snapshot.venue,
            snapshot.funding_rate, snapshot.annualized_rate,
            snapshot.next_funding_time, snapshot.mark_price,
            snapshot.index_price, snapshot.open_interest,
            snapshot.volume_24h, extra,
        )

async def get_recent_funding_rates(asset: str, venue: str, hours: int = 24) -> List[FundingRateSnapshot]:
    """Get recent funding rate snapshots."""
    if _dry_run:
        return []

    pool = await get_pool()

    query = """
        SELECT time, asset, venue, funding_rate, annualized_rate,
               next_funding_time, mark_price, index_price,
               open_interest, volume_24h, extra_data
        FROM funding_rate_snapshots
        WHERE asset = $1 AND venue = $2 AND time > NOW() - make_interval(hours => $3)
        ORDER BY time DESC
    """

    async with pool.acquire() as conn:
        rows = await conn.fetch(query, asset, venue, float(hours))

    results = []
    for row in rows:
        results.append(FundingRateSnapshot(
            time=row['time'], asset=row['asset'], venue=row['venue'],
            funding_rate=row['funding_rate'], annualized_rate=row['annualized_rate'],
            next_funding_time=row['next_funding_time'], mark_price=row['mark_price'],
            index_price=row['index_price'], open_interest=row['open_interest'],
            volume_24h=row['volume_24h'],
        ))
    return results

async def get_latest_funding_rate(asset: str, venue: str) -> Optional[FundingRateSnapshot]:
    """Get the most recent funding rate for an asset/venue."""
    if _dry_run:
        return None

    pool = await get_pool()

    query = """
        SELECT time, asset, venue, funding_rate, annualized_rate,
               next_funding_time, mark_price, index_price,
               open_interest, volume_24h
        FROM funding_rate_snapshots
        WHERE asset = $1 AND venue = $2
        ORDER BY time DESC
        LIMIT 1
    """

    async with pool.acquire() as conn:
        row = await conn.fetchrow(query, asset, venue)

    if row:
        return FundingRateSnapshot(
            time=row['time'], asset=row['asset'], venue=row['venue'],
            funding_rate=row['funding_rate'], annualized_rate=row['annualized_rate'],
            next_funding_time=row['next_funding_time'], mark_price=row['mark_price'],
            index_price=row['index_price'], open_interest=row['open_interest'],
            volume_24h=row['volume_24h'],
        )
    return None

async def get_consecutive_positive_funding_count(asset: str, venue: str) -> int:
    """Count consecutive recent positive funding rate readings."""
    if _dry_run:
        return 0

    pool = await get_pool()

    query = """
        SELECT funding_rate
        FROM funding_rate_snapshots
        WHERE asset = $1 AND venue = $2
        ORDER BY time DESC
        LIMIT 20
    """

    async with pool.acquire() as conn:
        rows = await conn.fetch(query, asset, venue)

    count = 0
    for row in rows:
        if row['funding_rate'] > 0:
            count += 1
        else:
            break
    return count


# ============================================================================
# Carry Signal Operations
# ============================================================================

async def insert_carry_signal(signal: CarrySignal) -> int:
    """Insert a carry signal and return its ID."""
    if _dry_run:
        logger.info(f"DRY-RUN: Would insert carry signal: {signal.signal_type} "
                    f"{signal.asset} {signal.perp_venue} APY={signal.expected_apy_pct:.1f}%")
        return 0

    pool = await get_pool()

    query = """
        INSERT INTO carry_signals
        (asset, spot_venue, perp_venue, signal_type, status,
         funding_rate_8h, annualized_rate, consecutive_positive_periods,
         spot_price, perp_price, entry_spread_pct,
         suggested_size_usd, suggested_leverage, portfolio_capital_usd,
         expected_daily_return_usd, expected_annual_return_usd, expected_apy_pct,
         estimated_fees_usd, breakeven_hours,
         expires_at, notes, parent_signal_id)
        VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18,$19,$20,$21,$22)
        RETURNING id
    """

    async with pool.acquire() as conn:
        signal_id = await conn.fetchval(
            query,
            signal.asset, signal.spot_venue, signal.perp_venue,
            signal.signal_type, signal.status,
            signal.funding_rate_8h, signal.annualized_rate,
            signal.consecutive_positive_periods,
            signal.spot_price, signal.perp_price, signal.entry_spread_pct,
            signal.suggested_size_usd, signal.suggested_leverage,
            signal.portfolio_capital_usd,
            signal.expected_daily_return_usd, signal.expected_annual_return_usd,
            signal.expected_apy_pct,
            signal.estimated_fees_usd, signal.breakeven_hours,
            signal.expires_at, signal.notes, signal.parent_signal_id,
        )

    logger.info(f"Inserted carry signal #{signal_id}: {signal.signal_type} "
               f"{signal.asset}@{signal.perp_venue}")
    return signal_id

async def get_active_carry_signals() -> List[CarrySignal]:
    """Get all active carry signals (for bot consumption)."""
    if _dry_run:
        return []

    pool = await get_pool()

    query = """
        SELECT id, asset, spot_venue, perp_venue, signal_type, status,
               funding_rate_8h, annualized_rate, consecutive_positive_periods,
               spot_price, perp_price, entry_spread_pct,
               suggested_size_usd, suggested_leverage, portfolio_capital_usd,
               expected_daily_return_usd, expected_annual_return_usd, expected_apy_pct,
               estimated_fees_usd, breakeven_hours,
               created_at, expires_at, executed_at, notes, parent_signal_id
        FROM carry_signals
        WHERE status = 'active'
        ORDER BY created_at DESC
    """

    async with pool.acquire() as conn:
        rows = await conn.fetch(query)

    return [CarrySignal.from_dict(dict(row)) for row in rows]

async def expire_old_signals(max_age_hours: int = 24) -> int:
    """Mark old active signals as expired."""
    if _dry_run:
        return 0

    pool = await get_pool()

    query = """
        UPDATE carry_signals
        SET status = 'expired'
        WHERE status = 'active'
          AND created_at < NOW() - make_interval(hours => $1)
    """

    async with pool.acquire() as conn:
        result = await conn.execute(query, float(max_age_hours))

    count = int(result.split()[-1]) if result else 0
    if count > 0:
        logger.info(f"Expired {count} old carry signals")
    return count

async def cancel_active_signals_for_pair(asset: str, perp_venue: str) -> int:
    """Cancel all active signals for a given asset/venue pair (e.g., on exit signal)."""
    if _dry_run:
        return 0

    pool = await get_pool()

    query = """
        UPDATE carry_signals
        SET status = 'cancelled'
        WHERE status = 'active' AND asset = $1 AND perp_venue = $2
              AND signal_type = 'entry'
    """

    async with pool.acquire() as conn:
        result = await conn.execute(query, asset, perp_venue)

    return int(result.split()[-1]) if result else 0


# ============================================================================
# Health check
# ============================================================================

async def check_db_health() -> bool:
    """Check if database is accessible."""
    if _dry_run:
        return True

    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            await conn.execute("SELECT 1")
        return True
    except Exception as e:
        logger.error(f"Database health check failed: {e}")
        return False