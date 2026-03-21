#!/usr/bin/env python3
"""
SpreadScope - Dashboard Entrypoint
Starts the Flask web dashboard.
"""

import argparse
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.utils import load_config, setup_logging

logger = setup_logging('dashboard')

def main():
    parser = argparse.ArgumentParser(description='SpreadScope Dashboard')
    parser.add_argument('--config', '-c', default=None,
                       help='Path to config.yaml')
    parser.add_argument('--host', default='0.0.0.0',
                       help='Host to bind to (default: 0.0.0.0)')
    parser.add_argument('--port', '-p', type=int, default=8050,
                       help='Port to listen on (default: 8050)')
    parser.add_argument('--debug', action='store_true',
                       help='Enable Flask debug mode')
    parser.add_argument('--no-db', action='store_true',
                       help='Run without database connection (placeholder mode)')

    args = parser.parse_args()

    # Load config
    try:
        config = load_config(args.config)
        dashboard_config = config.get('dashboard', {})
        host = args.host or dashboard_config.get('host', '0.0.0.0')
        port = args.port or dashboard_config.get('port', 8050)
        debug = args.debug or dashboard_config.get('debug', False)
    except FileNotFoundError:
        logger.warning("No config file found, using defaults")
        host = args.host
        port = args.port
        debug = args.debug
        config = {}

    # Check database connectivity using synchronous psycopg2
    db_available = not args.no_db
    if db_available:
        try:
            from src.dashboard.db_sync import init_sync_db, check_health
            init_sync_db(config)
            db_available = check_health()

            if db_available:
                logger.info("Database connection established (psycopg2)")
            else:
                logger.warning("Database health check failed — running in placeholder mode")
        except Exception as e:
            logger.warning(f"Database not available: {e} — running in placeholder mode")
            db_available = False
    else:
        logger.info("Running in no-database mode (placeholder data)")

    # Create Flask app
    from src.dashboard.app import create_app

    app_config = {
        'DB_AVAILABLE': db_available,
    }

    app = create_app(app_config)

    logger.info(f"Starting SpreadScope dashboard on http://{host}:{port}")
    logger.info(f"Database: {'Connected' if db_available else 'Not Available (placeholder mode)'}")

    app.run(host=host, port=port, debug=debug)

if __name__ == '__main__':
    main()
