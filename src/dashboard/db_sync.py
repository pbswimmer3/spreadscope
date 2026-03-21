"""
SpreadScope - Synchronous database queries for Flask dashboard.
Uses psycopg2 instead of asyncpg to avoid event loop conflicts.
"""

import json
import logging
from typing import Optional, List, Dict, Any
from datetime import datetime, timezone

import psycopg2
import psycopg2.extras

from ..utils import setup_logging

logger = setup_logging('dashboard.db')

_conn_params: Optional[Dict[str, Any]] = None


def init_sync_db(config: Dict[str, Any]):
    """Store connection params for later use."""
    global _conn_params
    db = config.get('database', {})
    _conn_params = {
        'host': db.get('host', 'localhost'),
        'port': db.get('port', 5432),
        'dbname': db.get('name', 'spreadscope_db'),
        'user': db.get('user', 'spreadscope'),
        'password': db.get('password', ''),
    }


def _get_conn():
    """Get a fresh psycopg2 connection."""
    if _conn_params is None:
        raise RuntimeError("Sync DB not initialized")
    return psycopg2.connect(**_conn_params)


def check_health() -> bool:
    """Check database connectivity."""
    try:
        conn = _get_conn()
        cur = conn.cursor()
        cur.execute("SELECT 1")
        cur.close()
        conn.close()
        return True
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return False


def get_current_spreads(limit: int = 50) -> List[Dict[str, Any]]:
    """Get recent spread data."""
    try:
        conn = _get_conn()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("""
            SELECT asset, venue_pair, spread_pct, time, real_price, synthetic_price,
                   EXTRACT(EPOCH FROM (NOW() - time)) as seconds_ago
            FROM spreads
            WHERE time > NOW() - INTERVAL '5 minutes'
            ORDER BY ABS(spread_pct) DESC
            LIMIT %s
        """, (limit,))
        rows = cur.fetchall()
        cur.close()
        conn.close()
        return [dict(r) for r in rows]
    except Exception as e:
        logger.error(f"get_current_spreads failed: {e}")
        return []


def get_spread_history(asset: str, venue_pair: str, hours: int = 24) -> List[Dict[str, Any]]:
    """Get historical spread data."""
    try:
        conn = _get_conn()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("""
            SELECT time, spread_pct, real_price, synthetic_price
            FROM spreads
            WHERE asset = %s AND venue_pair = %s
              AND time > NOW() - make_interval(hours => %s)
            ORDER BY time DESC
        """, (asset, venue_pair, float(hours)))
        rows = cur.fetchall()
        cur.close()
        conn.close()
        return [dict(r) for r in rows]
    except Exception as e:
        logger.error(f"get_spread_history failed: {e}")
        return []


def get_latest_funding_rates() -> List[Dict[str, Any]]:
    """Get the latest funding rate for each asset/venue combo."""
    try:
        conn = _get_conn()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("""
            SELECT DISTINCT ON (asset, venue)
                   asset, venue, funding_rate, annualized_rate,
                   mark_price, open_interest, volume_24h, time,
                   EXTRACT(EPOCH FROM (NOW() - time)) as seconds_ago
            FROM funding_rate_snapshots
            WHERE time > NOW() - INTERVAL '1 hour'
            ORDER BY asset, venue, time DESC
        """)
        rows = cur.fetchall()
        cur.close()
        conn.close()
        return [dict(r) for r in rows]
    except Exception as e:
        logger.error(f"get_latest_funding_rates failed: {e}")
        return []


def get_funding_rate_history(asset: str, venue: str, hours: int = 72) -> List[Dict[str, Any]]:
    """Get funding rate history for charts."""
    try:
        conn = _get_conn()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("""
            SELECT time, funding_rate, annualized_rate, mark_price, open_interest
            FROM funding_rate_snapshots
            WHERE asset = %s AND venue = %s
              AND time > NOW() - make_interval(hours => %s)
            ORDER BY time ASC
        """, (asset, venue, float(hours)))
        rows = cur.fetchall()
        cur.close()
        conn.close()
        return [dict(r) for r in rows]
    except Exception as e:
        logger.error(f"get_funding_rate_history failed: {e}")
        return []


def get_active_signals() -> List[Dict[str, Any]]:
    """Get all active carry signals (bot-readable)."""
    try:
        conn = _get_conn()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("""
            SELECT id, asset, spot_venue, perp_venue, signal_type, status,
                   funding_rate_8h, annualized_rate, consecutive_positive_periods,
                   spot_price, perp_price, entry_spread_pct,
                   suggested_size_usd, suggested_leverage, portfolio_capital_usd,
                   expected_daily_return_usd, expected_annual_return_usd, expected_apy_pct,
                   estimated_fees_usd, breakeven_hours,
                   created_at, expires_at, notes
            FROM carry_signals
            WHERE status = 'active'
            ORDER BY created_at DESC
        """)
        rows = cur.fetchall()
        cur.close()
        conn.close()
        return [_serialize_row(r) for r in rows]
    except Exception as e:
        logger.error(f"get_active_signals failed: {e}")
        return []


def get_recent_signals(limit: int = 50) -> List[Dict[str, Any]]:
    """Get recent carry signals (all statuses)."""
    try:
        conn = _get_conn()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("""
            SELECT id, asset, spot_venue, perp_venue, signal_type, status,
                   funding_rate_8h, annualized_rate,
                   spot_price, perp_price,
                   suggested_size_usd, portfolio_capital_usd,
                   expected_apy_pct, estimated_fees_usd, breakeven_hours,
                   created_at, expires_at, notes
            FROM carry_signals
            ORDER BY created_at DESC
            LIMIT %s
        """, (limit,))
        rows = cur.fetchall()
        cur.close()
        conn.close()
        return [_serialize_row(r) for r in rows]
    except Exception as e:
        logger.error(f"get_recent_signals failed: {e}")
        return []


def get_opportunity_stats(days: int = 7) -> Dict[str, Any]:
    """Get opportunity/signal stats."""
    try:
        conn = _get_conn()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("""
            SELECT COUNT(*) as total_signals,
                   COUNT(CASE WHEN status = 'active' THEN 1 END) as active_signals,
                   COUNT(CASE WHEN signal_type = 'entry' THEN 1 END) as entry_signals,
                   COUNT(CASE WHEN signal_type = 'exit' THEN 1 END) as exit_signals,
                   AVG(expected_apy_pct) FILTER (WHERE signal_type = 'entry') as avg_entry_apy
            FROM carry_signals
            WHERE created_at > NOW() - make_interval(days => %s)
        """, (float(days),))
        row = cur.fetchone()
        cur.close()
        conn.close()
        if row:
            return _serialize_row(row)
        return {}
    except Exception as e:
        logger.error(f"get_opportunity_stats failed: {e}")
        return {}


def get_funding_rate_stats() -> Dict[str, Any]:
    """Get funding rate statistics for the analytics page."""
    try:
        conn = _get_conn()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        # Overall stats
        cur.execute("""
            SELECT COUNT(*) as total_snapshots,
                   MIN(time) as earliest,
                   MAX(time) as latest
            FROM funding_rate_snapshots
        """)
        overview = dict(cur.fetchone())

        # Per-asset stats
        cur.execute("""
            SELECT asset, venue,
                   COUNT(*) as readings,
                   AVG(annualized_rate) as avg_apy,
                   MIN(annualized_rate) as min_apy,
                   MAX(annualized_rate) as max_apy,
                   AVG(funding_rate) as avg_funding_rate,
                   AVG(open_interest) as avg_oi
            FROM funding_rate_snapshots
            GROUP BY asset, venue
            ORDER BY asset, venue
        """)
        per_asset = [dict(r) for r in cur.fetchall()]

        # Hourly averages for heatmap (by hour of day)
        cur.execute("""
            SELECT EXTRACT(HOUR FROM time AT TIME ZONE 'UTC') as hour_utc,
                   asset,
                   AVG(annualized_rate) as avg_apy,
                   COUNT(*) as readings
            FROM funding_rate_snapshots
            GROUP BY 1, 2
            ORDER BY 1
        """)
        hourly = [dict(r) for r in cur.fetchall()]

        # Recent trend (last 100 readings per asset)
        cur.execute("""
            SELECT time, asset, venue, annualized_rate, funding_rate
            FROM funding_rate_snapshots
            ORDER BY time DESC
            LIMIT 200
        """)
        recent = [dict(r) for r in cur.fetchall()]

        cur.close()
        conn.close()

        return {
            'overview': _serialize_row(overview),
            'per_asset': [_serialize_row(r) for r in per_asset],
            'hourly': hourly,
            'recent': [_serialize_row(r) for r in recent],
        }
    except Exception as e:
        logger.error(f"get_funding_rate_stats failed: {e}")
        return {}


def _serialize_row(row: Dict) -> Dict[str, Any]:
    """Convert psycopg2 row to JSON-serializable dict."""
    result = {}
    for k, v in dict(row).items():
        if isinstance(v, datetime):
            result[k] = v.isoformat()
        elif v is None:
            result[k] = None
        else:
            result[k] = v
    return result
