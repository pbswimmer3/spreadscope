"""
SpreadScope - Polygon.io Spot Price Worker
"""

import asyncio
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional

from .base_worker import BaseWorker
from ..models import PriceObservation
from ..utils import setup_logging, RateLimiter

logger = setup_logging(__name__)

class PolygonWorker(BaseWorker):
    """Worker for Polygon.io spot prices (stocks + crypto)."""
    
    def __init__(self, config: Dict[str, Any]):
        super().__init__('polygon_spot', config)
        
        # Check for API key
        if not self.api_key or self.api_key == 'CHANGE_ME':
            logger.warning("Polygon worker disabled — no API key configured. "
                         "Sign up at https://polygon.io (free tier available)")
            self.is_enabled = False
        
        # Free tier: 5 API calls/min
        self.rate_limiter = RateLimiter(calls_per_minute=5)
        
        # Assets to track
        self.crypto_assets = ['BTC', 'ETH']
        self.equity_assets = []  # ['AAPL', 'TSLA', 'NVDA'] when ready
        
    async def fetch_prices(self) -> List[PriceObservation]:
        """Fetch spot prices from Polygon.io."""
        if not self.is_enabled:
            return []
        
        observations = []
        
        # Fetch crypto prices
        for asset in self.crypto_assets:
            try:
                await self.rate_limiter.acquire()
                obs = await self._fetch_crypto_price(asset)
                if obs:
                    observations.append(obs)
            except Exception as e:
                logger.error(f"Error fetching {asset} from Polygon: {e}")
        
        # Fetch equity prices (during market hours)
        for asset in self.equity_assets:
            try:
                await self.rate_limiter.acquire()
                obs = await self._fetch_equity_price(asset)
                if obs:
                    observations.append(obs)
            except Exception as e:
                logger.error(f"Error fetching {asset} from Polygon: {e}")
        
        return observations
    
    async def _fetch_crypto_price(self, asset: str) -> Optional[PriceObservation]:
        """Fetch previous day aggregate for a crypto asset (free tier compatible)."""
        # Polygon crypto ticker format: X:BTCUSD
        ticker = f"X:{asset}USD"
        endpoint = f"v2/aggs/ticker/{ticker}/prev"
        
        try:
            data = await self._make_request('GET', endpoint)
            
            if data.get('status') != 'OK':
                logger.warning(f"Polygon returned non-OK status for {ticker}: {data.get('status')}")
                return None
            
            results = data.get('results', [])
            if not results:
                logger.warning(f"No results for {ticker} from Polygon")
                return None
            
            result = results[0]
            # Use VWAP as the most representative price, fall back to close
            price = result.get('vw') or result.get('c')
            if price is None:
                logger.warning(f"No price in Polygon results for {ticker}")
                return None
            
            volume = result.get('v')
            
            # Parse timestamp (milliseconds since epoch)
            timestamp_ms = result.get('t')
            if timestamp_ms:
                timestamp = datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc)
            else:
                timestamp = datetime.now(timezone.utc)
            
            return self._create_observation(
                asset=asset,
                price=float(price),
                timestamp=timestamp,
                volume_24h=float(volume) if volume else None,
                extra_data={
                    'source': 'polygon_spot',
                    'ticker': ticker,
                    'open': result.get('o'),
                    'high': result.get('h'),
                    'low': result.get('l'),
                    'close': result.get('c'),
                    'vwap': result.get('vw'),
                    'num_transactions': result.get('n'),
                }
            )
            
        except Exception as e:
            logger.error(f"Failed to fetch crypto price for {asset}: {e}")
            return None
    
    async def _fetch_equity_price(self, ticker: str) -> Optional[PriceObservation]:
        """Fetch previous close for an equity asset."""
        endpoint = f"v2/aggs/ticker/{ticker}/prev"
        
        try:
            data = await self._make_request('GET', endpoint)
            
            if data.get('status') != 'OK':
                logger.warning(f"Polygon returned non-OK status for {ticker}: {data.get('status')}")
                return None
            
            results = data.get('results', [])
            if not results:
                logger.warning(f"No results for {ticker} from Polygon")
                return None
            
            result = results[0]
            close_price = result.get('c')
            if close_price is None:
                return None
            
            # Volume
            volume = result.get('v')
            
            # Timestamp (milliseconds since epoch)
            timestamp_ms = result.get('t')
            if timestamp_ms:
                timestamp = datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc)
            else:
                timestamp = datetime.now(timezone.utc)
            
            return self._create_observation(
                asset=ticker,
                price=float(close_price),
                timestamp=timestamp,
                volume_24h=float(volume) if volume else None,
                extra_data={
                    'source': 'polygon_spot',
                    'ticker': ticker,
                    'open': result.get('o'),
                    'high': result.get('h'),
                    'low': result.get('l'),
                    'vwap': result.get('vw'),
                    'num_transactions': result.get('n'),
                }
            )
            
        except Exception as e:
            logger.error(f"Failed to fetch equity price for {ticker}: {e}")
            return None
    
    async def test_connection(self) -> bool:
        """Test connection to Polygon.io API."""
        if not self.is_enabled:
            logger.warning("Polygon worker disabled (no API key)")
            return False
        
        try:
            obs = await self._fetch_crypto_price('BTC')
            if obs:
                logger.info(f"Polygon connection test successful: BTC = ${obs.price:.2f}")
                return True
            else:
                logger.warning("Polygon connection test failed: no data returned")
                return False
        except Exception as e:
            logger.error(f"Polygon connection test failed: {e}")
            return False