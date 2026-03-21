"""
SpreadScope - Utility functions and helpers
"""

import asyncio
import logging
import yaml
from datetime import datetime, timezone
from typing import Any, Dict, Optional
from pathlib import Path

# Configure logging
def setup_logging(name: str, level: str = "INFO") -> logging.Logger:
    """Set up logging for a module."""
    logger = logging.getLogger(name)
    
    if not logger.handlers:
        handler = logging.StreamHandler()
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)
    
    logger.setLevel(getattr(logging, level.upper()))
    return logger

# Configuration loading
def load_config(config_path: Optional[str] = None) -> Dict[str, Any]:
    """Load configuration from YAML file."""
    if config_path is None:
        # Try default locations
        default_paths = [
            "./config/config.yaml",
            "/opt/spreadscope/config/config.yaml",
            "./config.example.yaml"
        ]
        
        for path in default_paths:
            if Path(path).exists():
                config_path = path
                break
        
        if config_path is None:
            raise FileNotFoundError("No configuration file found")
    
    with open(config_path, 'r') as f:
        config = yaml.safe_load(f)
    
    return config

# Time utilities
def now_utc() -> datetime:
    """Get current UTC datetime with timezone."""
    return datetime.now(timezone.utc)

def parse_iso_timestamp(timestamp: str) -> datetime:
    """Parse ISO format timestamp to datetime."""
    if timestamp.endswith('Z'):
        timestamp = timestamp[:-1] + '+00:00'
    return datetime.fromisoformat(timestamp)

def format_iso_timestamp(dt: datetime) -> str:
    """Format datetime to ISO string."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()

# Data validation
def validate_price(price: float, asset: str) -> bool:
    """Validate price is within reasonable bounds."""
    if price <= 0:
        return False
    
    # Asset-specific sanity checks
    sane_ranges = {
        'BTC': (1000, 500000),      # $1K - $500K
        'ETH': (100, 50000),        # $100 - $50K
        'AAPL': (10, 1000),         # $10 - $1K
        'TSLA': (10, 5000),         # $10 - $5K
        'NVDA': (10, 2000),         # $10 - $2K
    }
    
    if asset in sane_ranges:
        min_price, max_price = sane_ranges[asset]
        return min_price <= price <= max_price
    
    # Default range for unknown assets
    return 0.0001 <= price <= 1000000

def normalize_asset_name(asset: str) -> str:
    """Normalize asset name to standard format."""
    # Remove common suffixes and prefixes
    asset = asset.upper()
    
    # Map common variations
    asset_map = {
        'BTC-USD': 'BTC',
        'ETH-USD': 'ETH',
        'BTC-PERP': 'BTC',
        'ETH-PERP': 'ETH',
        'X:BTCUSD': 'BTC',
        'X:ETHUSD': 'ETH',
        'SBTC': 'BTC',
        'SETH': 'ETH',
    }
    
    return asset_map.get(asset, asset)

# Async utilities
async def with_timeout(coro, timeout: float, default=None):
    """Run coroutine with timeout."""
    try:
        return await asyncio.wait_for(coro, timeout)
    except asyncio.TimeoutError:
        return default

async def exponential_backoff(retries: int, base_delay: float = 1.0):
    """Exponential backoff for retries."""
    delay = base_delay * (2 ** retries)
    await asyncio.sleep(min(delay, 60))  # Cap at 60 seconds

# Rate limiting
class RateLimiter:
    """Simple rate limiter for API calls."""
    
    def __init__(self, calls_per_minute: int):
        self.calls_per_minute = calls_per_minute
        self.call_times = []
        self.lock = asyncio.Lock()
    
    async def acquire(self):
        """Acquire permission to make a call."""
        while True:
            async with self.lock:
                now = asyncio.get_event_loop().time()

                # Remove calls older than 1 minute
                self.call_times = [t for t in self.call_times if now - t < 60]

                if len(self.call_times) < self.calls_per_minute:
                    self.call_times.append(now)
                    return

                # Calculate wait time but don't sleep under lock
                oldest_call = self.call_times[0]
                wait_time = 60 - (now - oldest_call) + 0.1

            # Sleep outside the lock
            if wait_time > 0:
                await asyncio.sleep(wait_time)