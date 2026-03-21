"""
SpreadScope - Dashboard Routes
Uses synchronous psycopg2 for database queries (no async/event loop issues).
"""

from datetime import datetime, timezone
from flask import render_template, jsonify, request, current_app


def register_routes(app):
    """Register all dashboard routes."""

    @app.route('/')
    def dashboard():
        """Main dashboard overview."""
        return render_template('dashboard.html')

    @app.route('/pair/<asset>/<path:venue_pair>')
    def pair_detail(asset, venue_pair):
        """Detailed view for a specific asset/venue pair."""
        return render_template('pair_detail.html',
                             asset=asset, venue_pair=venue_pair)

    @app.route('/analytics')
    def analytics():
        """Historical analytics page."""
        return render_template('analytics.html')

    # ==========================================================================
    # JSON API Endpoints
    # ==========================================================================

    @app.route('/api/spreads/current')
    def api_current_spreads():
        """Get current spread data for all tracked pairs."""
        if not current_app.config.get('DB_AVAILABLE', False):
            return jsonify({
                'status': 'no_database',
                'message': 'Database not connected. Showing placeholder data.',
                'spreads': _get_placeholder_spreads(),
                'timestamp': datetime.now(timezone.utc).isoformat()
            })

        from .db_sync import get_current_spreads
        spreads = get_current_spreads()
        return jsonify({
            'status': 'ok',
            'spreads': spreads,
            'timestamp': datetime.now(timezone.utc).isoformat()
        })

    @app.route('/api/spreads/history')
    def api_spread_history():
        """Get historical spread data for charts."""
        asset = request.args.get('asset', 'BTC')
        pair = request.args.get('pair', 'coinbase_spot:hyperliquid_perps')
        hours = int(request.args.get('hours', 24))

        if not current_app.config.get('DB_AVAILABLE', False):
            return jsonify({
                'status': 'no_database',
                'data': [],
                'timestamp': datetime.now(timezone.utc).isoformat()
            })

        from .db_sync import get_spread_history
        data = get_spread_history(asset, pair, hours)
        # Serialize datetime objects
        for row in data:
            if 'time' in row and hasattr(row['time'], 'isoformat'):
                row['time'] = row['time'].isoformat()
        return jsonify({
            'status': 'ok',
            'data': data,
            'asset': asset,
            'pair': pair,
            'hours': hours,
            'timestamp': datetime.now(timezone.utc).isoformat()
        })

    # ==========================================================================
    # Funding Rate Endpoints
    # ==========================================================================

    @app.route('/api/funding/current')
    def api_current_funding():
        """Get latest funding rates for all tracked asset/venue combos."""
        if not current_app.config.get('DB_AVAILABLE', False):
            return jsonify({
                'status': 'no_database',
                'rates': [],
                'timestamp': datetime.now(timezone.utc).isoformat()
            })

        from .db_sync import get_latest_funding_rates
        rates = get_latest_funding_rates()
        return jsonify({
            'status': 'ok',
            'rates': rates,
            'timestamp': datetime.now(timezone.utc).isoformat()
        })

    @app.route('/api/funding/history')
    def api_funding_history():
        """Get funding rate history for charts."""
        asset = request.args.get('asset', 'BTC')
        venue = request.args.get('venue', 'hyperliquid_perps')
        hours = int(request.args.get('hours', 72))

        if not current_app.config.get('DB_AVAILABLE', False):
            return jsonify({'status': 'no_database', 'data': [],
                          'timestamp': datetime.now(timezone.utc).isoformat()})

        from .db_sync import get_funding_rate_history
        data = get_funding_rate_history(asset, venue, hours)
        for row in data:
            if 'time' in row and hasattr(row['time'], 'isoformat'):
                row['time'] = row['time'].isoformat()
        return jsonify({
            'status': 'ok',
            'data': data,
            'asset': asset,
            'venue': venue,
            'hours': hours,
            'timestamp': datetime.now(timezone.utc).isoformat()
        })

    # ==========================================================================
    # Carry Signal Endpoints (Bot-Readable)
    # ==========================================================================

    @app.route('/api/signals')
    def api_signals():
        """
        Get carry signals. This is the primary bot-readable endpoint.

        Query params:
          ?status=active  (default: active)
          ?status=all     (returns recent signals of all statuses)
          ?limit=50       (for status=all)
        """
        status_filter = request.args.get('status', 'active')

        if not current_app.config.get('DB_AVAILABLE', False):
            return jsonify({
                'status': 'no_database',
                'signals': [],
                'timestamp': datetime.now(timezone.utc).isoformat()
            })

        from .db_sync import get_active_signals, get_recent_signals

        if status_filter == 'active':
            signals = get_active_signals()
        else:
            limit = int(request.args.get('limit', 50))
            signals = get_recent_signals(limit)

        return jsonify({
            'status': 'ok',
            'signals': signals,
            'count': len(signals),
            'timestamp': datetime.now(timezone.utc).isoformat()
        })

    @app.route('/api/analytics')
    def api_analytics():
        """Get analytics data for the analytics page."""
        if not current_app.config.get('DB_AVAILABLE', False):
            return jsonify({'status': 'no_database', 'data': {},
                          'timestamp': datetime.now(timezone.utc).isoformat()})

        from .db_sync import get_funding_rate_stats
        stats = get_funding_rate_stats()
        return jsonify({
            'status': 'ok',
            'data': stats,
            'timestamp': datetime.now(timezone.utc).isoformat()
        })

    @app.route('/api/signals/stats')
    def api_signal_stats():
        """Get signal statistics."""
        days = int(request.args.get('days', 7))

        if not current_app.config.get('DB_AVAILABLE', False):
            return jsonify({'status': 'no_database', 'stats': {},
                          'timestamp': datetime.now(timezone.utc).isoformat()})

        from .db_sync import get_opportunity_stats
        stats = get_opportunity_stats(days)
        return jsonify({
            'status': 'ok',
            'stats': stats,
            'timestamp': datetime.now(timezone.utc).isoformat()
        })

    # ==========================================================================
    # Health
    # ==========================================================================

    @app.route('/api/health')
    def api_health():
        """Health check endpoint."""
        return jsonify({
            'status': 'ok',
            'db_available': current_app.config.get('DB_AVAILABLE', False),
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'version': '2.0.0'
        })


def _get_placeholder_spreads():
    """Placeholder data when DB is unavailable."""
    return [
        {'asset': 'BTC', 'venue_pair': 'coinbase_spot:hyperliquid_perps',
         'spread_pct': 0.0, 'real_price': 0.0, 'synthetic_price': 0.0,
         'seconds_ago': 0, 'placeholder': True},
        {'asset': 'ETH', 'venue_pair': 'coinbase_spot:hyperliquid_perps',
         'spread_pct': 0.0, 'real_price': 0.0, 'synthetic_price': 0.0,
         'seconds_ago': 0, 'placeholder': True},
    ]
