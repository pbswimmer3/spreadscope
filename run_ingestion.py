#!/usr/bin/env python3
"""
SpreadScope - Ingestion Entrypoint
Starts all enabled ingestion workers concurrently.
"""

import asyncio
import argparse
import signal
import sys
import os

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.db import init_db, close_db
from src.utils import load_config, setup_logging
from src.ingestion.coinbase_spot_worker import CoinbaseSpotWorker
from src.ingestion.hyperliquid_worker import HyperliquidWorker
from src.ingestion.dydx_worker import DydxWorker
from src.ingestion.polygon_worker import PolygonWorker
from src.ingestion.coinbase_perps_worker import CoinbasePerpsWorker
from src.ingestion.synthetix_worker import SynthetixWorker

logger = setup_logging('ingestion')

# Worker registry
WORKER_CLASSES = {
    'coinbase_spot': CoinbaseSpotWorker,
    'hyperliquid': HyperliquidWorker,
    'dydx': DydxWorker,
    'polygon': PolygonWorker,
    'coinbase_perps': CoinbasePerpsWorker,
    'synthetix': SynthetixWorker,
}

async def run_workers(config_path: str = None, dry_run: bool = False):
    """Start all enabled workers."""
    
    # Load config
    config = load_config(config_path)
    
    # Initialize database
    await init_db(config_path, dry_run=dry_run)
    
    # Create workers from config
    workers = []
    venues_config = config.get('venues', {})
    
    for venue_name, venue_config in venues_config.items():
        if not venue_config.get('enabled', True):
            logger.info(f"Skipping disabled venue: {venue_name}")
            continue
        
        worker_class = WORKER_CLASSES.get(venue_name)
        if worker_class is None:
            logger.warning(f"Unknown venue: {venue_name}, skipping")
            continue
        
        try:
            worker = worker_class(venue_config)
            workers.append(worker)
            logger.info(f"Created worker for {venue_name}")
        except Exception as e:
            logger.error(f"Failed to create worker for {venue_name}: {e}")
    
    if not workers:
        logger.error("No workers created! Check your configuration.")
        return
    
    logger.info(f"Starting {len(workers)} ingestion workers...")
    
    # Run all workers concurrently
    tasks = []
    for worker in workers:
        task = asyncio.create_task(worker.start())
        tasks.append(task)
    
    try:
        # Wait for all tasks (they run forever unless cancelled)
        await asyncio.gather(*tasks)
    except asyncio.CancelledError:
        logger.info("Workers cancelled, shutting down...")
    finally:
        # Cancel all tasks
        for task in tasks:
            task.cancel()
        
        # Wait for cancellation
        await asyncio.gather(*tasks, return_exceptions=True)
        
        # Close database connection
        await close_db()
        logger.info("Ingestion workers shut down cleanly")

def handle_shutdown(signum, frame):
    """Handle shutdown signals."""
    logger.info(f"Received signal {signum}, initiating shutdown...")
    # Cancel the main task
    for task in asyncio.all_tasks():
        task.cancel()

def main():
    parser = argparse.ArgumentParser(description='SpreadScope Ingestion Workers')
    parser.add_argument('--config', '-c', default=None,
                       help='Path to config.yaml')
    parser.add_argument('--dry-run', action='store_true',
                       help='Run without database writes (print to stdout)')
    parser.add_argument('--test', action='store_true',
                       help='Test all worker connections and exit')
    
    args = parser.parse_args()
    
    if args.test:
        # Run connection tests
        asyncio.run(test_all_workers(args.config))
        return
    
    # Set up signal handlers
    signal.signal(signal.SIGINT, handle_shutdown)
    signal.signal(signal.SIGTERM, handle_shutdown)
    
    # Run workers
    try:
        asyncio.run(run_workers(args.config, dry_run=args.dry_run))
    except KeyboardInterrupt:
        logger.info("Interrupted by user")

async def test_all_workers(config_path: str = None):
    """Test all worker connections."""
    config = load_config(config_path)
    venues_config = config.get('venues', {})
    
    logger.info("Testing all worker connections...")
    
    results = {}
    for venue_name, venue_config in venues_config.items():
        worker_class = WORKER_CLASSES.get(venue_name)
        if worker_class is None:
            continue
        
        try:
            worker = worker_class(venue_config)
            if not worker.is_enabled:
                results[venue_name] = '⏭️  Disabled (missing API key or config)'
                continue
            
            success = await worker.test_connection()
            results[venue_name] = '✅ Connected' if success else '❌ Failed'
        except Exception as e:
            results[venue_name] = f'❌ Error: {e}'
    
    print("\n" + "=" * 50)
    print("Connection Test Results")
    print("=" * 50)
    for venue, result in results.items():
        print(f"  {venue}: {result}")
    print("=" * 50)

if __name__ == '__main__':
    main()