"""
SpreadScope - Synthetix / Pyth Network Oracle Worker

Synthetix V3 uses Pyth Network oracle feeds for pricing.
We query Pyth's Hermes REST API directly to get the same prices
Synthetix uses for its synthetic assets.
"""

import asyncio
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional

from .base_worker import BaseWorker
from ..models import PriceObservation
from ..utils import setup_logging

logger = setup_logging(__name__)

# Pyth Network price feed IDs for assets Synthetix supports
PYTH_FEED_IDS = {
    'BTC': '0xe62df6c8b4a85fe1a67db44dc12de5db330f7ac66b72dc658afedf0f4a415b43',
    'ETH': '0xff61491a931112ddf1bd8147cd1b641375f79f5825126d665480874634fd0ace',
}

class SynthetixWorker(BaseWorker):
    """Worker for Synthetix synthetic asset prices via Pyth Network oracle."""
    
    def __init__(self, config: Dict[str, Any]):
        # Override base_url to use Pyth Hermes
        config['base_url'] = 'https://hermes.pyth.network'
        super().__init__('synthetix', config)
        
        self.tracked_assets = ['BTC', 'ETH']
        
    async def fetch_prices(self) -> List[PriceObservation]:
        """Fetch synthetic asset prices from Pyth Network (Synthetix oracle)."""
        observations = []
        
        try:
            # Build query with all feed IDs
            feed_ids = []
            for asset in self.tracked_assets:
                feed_id = PYTH_FEED_IDS.get(asset)
                if feed_id:
                    feed_ids.append(feed_id)
            
            if not feed_ids:
                logger.warning("No feed IDs configured for Synthetix worker")
                return observations
            
            # Fetch latest prices from Pyth Hermes
            price_data = await self._fetch_pyth_prices(feed_ids)
            if not price_data:
                return observations
            
            # Parse response
            parsed = price_data.get('parsed', [])
            for price_entry in parsed:
                obs = self._parse_pyth_price(price_entry)
                if obs:
                    observations.append(obs)
            
            logger.debug(f"Fetched {len(observations)} Synthetix oracle prices")
            
        except Exception as e:
            logger.error(f"Error fetching Synthetix prices: {e}")
        
        return observations
    
    async def _fetch_pyth_prices(self, feed_ids: List[str]) -> Optional[Dict[str, Any]]:
        """Fetch latest prices from Pyth Hermes API."""
        # Build query parameters
        params_str = '&'.join([f'ids%5B%5D={fid}' for fid in feed_ids])
        endpoint = f"v2/updates/price/latest?{params_str}"
        
        try:
            data = await self._make_request('GET', endpoint)
            return data
        except Exception as e:
            logger.error(f"Failed to fetch Pyth prices: {e}")
            return None
    
    def _parse_pyth_price(self, price_entry: Dict[str, Any]) -> Optional[PriceObservation]:
        """Parse a Pyth price entry into a PriceObservation."""
        try:
            feed_id = price_entry.get('id', '')
            
            # Reverse lookup asset name from feed ID
            asset = None
            for asset_name, fid in PYTH_FEED_IDS.items():
                if fid.replace('0x', '') == feed_id.replace('0x', ''):
                    asset = asset_name
                    break
            
            if asset is None:
                logger.debug(f"Unknown Pyth feed ID: {feed_id}")
                return None
            
            # Extract price data
            price_data = price_entry.get('price', {})
            if not price_data:
                return None
            
            # Pyth returns price with exponent: actual_price = price * 10^expo
            raw_price = int(price_data.get('price', 0))
            expo = int(price_data.get('expo', 0))
            price = raw_price * (10 ** expo)
            
            # Confidence interval
            confidence = int(price_data.get('conf', 0)) * (10 ** expo)
            
            # Timestamp
            publish_time = price_data.get('publish_time')
            if publish_time:
                timestamp = datetime.fromtimestamp(int(publish_time), tz=timezone.utc)
            else:
                timestamp = datetime.now(timezone.utc)
            
            # EMA price (if available)
            ema_data = price_entry.get('ema_price', {})
            ema_price = None
            if ema_data:
                ema_raw = int(ema_data.get('price', 0))
                ema_expo = int(ema_data.get('expo', 0))
                ema_price = ema_raw * (10 ** ema_expo)
            
            return self._create_observation(
                asset=asset,
                price=price,
                timestamp=timestamp,
                extra_data={
                    'source': 'synthetix_pyth_oracle',
                    'feed_id': feed_id,
                    'confidence': confidence,
                    'ema_price': ema_price,
                    'publish_time': publish_time,
                }
            )
            
        except Exception as e:
            logger.error(f"Failed to parse Pyth price entry: {e}")
            return None
    
    async def test_connection(self) -> bool:
        """Test connection to Pyth Network Hermes API."""
        try:
            btc_feed = PYTH_FEED_IDS.get('BTC')
            if not btc_feed:
                logger.warning("No BTC feed ID configured")
                return False
            
            data = await self._fetch_pyth_prices([btc_feed])
            if data and 'parsed' in data and len(data['parsed']) > 0:
                entry = data['parsed'][0]
                price_data = entry.get('price', {})
                raw_price = int(price_data.get('price', 0))
                expo = int(price_data.get('expo', 0))
                price = raw_price * (10 ** expo)
                logger.info(f"Pyth/Synthetix connection test successful: BTC oracle = ${price:.2f}")
                return True
            else:
                logger.warning("Pyth connection test failed: no price data")
                return False
        except Exception as e:
            logger.error(f"Pyth/Synthetix connection test failed: {e}")
            return False