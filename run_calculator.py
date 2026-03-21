#!/usr/bin/env python3
"""
SpreadScope - Calculator Entrypoint
Runs the funding rate carry calculator loop.
Also computes spreads and tracks legacy spread-based opportunities.
"""

import asyncio
import argparse
import signal
import sys
import os
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.utils import load_config, setup_logging, now_utc

logger = setup_logging('calculator')


async def run_calculator(config_path: str = None, dry_run: bool = False,
                         interval: int = 30):
    """Run the carry calculator loop."""
    from src.db import init_db, close_db
    from src.calculator.carry_calculator import CarryCalculator

    config = load_config(config_path)

    # Initialize database
    await init_db(config_path, dry_run=dry_run)

    # Create carry calculator
    calc = CarryCalculator(config, dry_run=dry_run)

    capital = config.get('portfolio', {}).get('capital_usd', 5000)
    logger.info(f"Starting carry calculator (interval: {interval}s, capital: ${capital:,.0f})")
    logger.info(f"Assets: {calc.assets}")
    logger.info(f"Spot venues: {calc.spot_venues}")
    logger.info(f"Perp venues: {calc.perp_venues}")
    logger.info(f"Min APY threshold: {calc.min_annualized_rate}%")

    cycle_count = 0

    try:
        while True:
            try:
                summary = await calc.run_cycle()
                cycle_count += 1

                # Log summary every cycle
                if summary['signals_generated'] > 0:
                    for opp in summary['opportunities']:
                        logger.info(f"  Signal: {opp['type'].upper()} {opp['asset']}@{opp['venue']} "
                                   f"APY={opp['apy']:.1f}%")

                # Periodic status log (every 10 cycles)
                if cycle_count % 10 == 0:
                    logger.info(f"Cycle {cycle_count}: "
                               f"spreads={summary['spreads_computed']}, "
                               f"funding_checks={summary['funding_rates_checked']}, "
                               f"signals={summary['signals_generated']}, "
                               f"expired={summary['signals_expired']}")

            except Exception as e:
                logger.error(f"Error in calculator loop: {e}", exc_info=True)
                await asyncio.sleep(5)

            await asyncio.sleep(interval)

    except asyncio.CancelledError:
        logger.info("Calculator cancelled")
    finally:
        await close_db()
        logger.info("Calculator shut down")


async def run_mock_test(config_path: str = None):
    """Run carry calculator with synthetic mock data to verify logic.
    Uses the standalone test file to avoid requiring asyncpg."""
    import subprocess
    result = subprocess.run(
        [sys.executable, 'tests/test_carry_logic.py'],
        cwd=os.path.dirname(os.path.abspath(__file__)),
    )
    sys.exit(result.returncode)


def main():
    parser = argparse.ArgumentParser(description='SpreadScope Calculator')
    parser.add_argument('--config', '-c', default=None,
                       help='Path to config.yaml')
    parser.add_argument('--dry-run', action='store_true',
                       help='Run without database writes')
    parser.add_argument('--interval', '-i', type=int, default=30,
                       help='Calculation interval in seconds (default: 30)')
    parser.add_argument('--test', action='store_true',
                       help='Run mock data test and exit')

    args = parser.parse_args()

    if args.test:
        asyncio.run(run_mock_test(args.config))
        return

    signal.signal(signal.SIGINT, lambda s, f: sys.exit(0))
    signal.signal(signal.SIGTERM, lambda s, f: sys.exit(0))

    try:
        asyncio.run(run_calculator(args.config, dry_run=args.dry_run,
                                   interval=args.interval))
    except KeyboardInterrupt:
        logger.info("Interrupted by user")

if __name__ == '__main__':
    main()
