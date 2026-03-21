"""
SpreadScope - Coinbase Spot Price Worker
"""

import asyncio
from datetime import datetime, timezone
from typing import List, Dict, Any

from .base_worker import BaseWorker
from ..models import PriceObservation
from ..utils import setup_logging

logger = setup_logging(__name__)

class CoinbaseSpotWorker(BaseWorker):
    """Worker for Coinbase spot prices."""
    
    def __init__(self, config: Dict[str, Any]):
        super().__init__('coinbase_spot', config)
        
        # Assets to track
        self.assets = ['BTC-USD', 'ETH-USD']
        
    async def fetch_prices(self) -> List[PriceObservation]:
        """Fetch spot prices from Coinbase."""
        observations = []
        
        for asset_pair in self.assets:
            try:
                price_data = await self._fetch_spot_price(asset_pair)
                if price_data:
                    observation = self._parse_spot_price(asset_pair, price_data)
                    if observation:
                        observations.append(observation)
            except Exception as e:
                logger.error(f"Error fetching {asset_pair} from Coinbase: {e}")
                continue
        
        return observations
    
    async def _fetch_spot_price(self, asset_pair: str) -> Dict[str, Any]:
        """Fetch spot price for a specific asset pair."""
        endpoint = f"v2/prices/{asset_pair}/spot"
        
        try:
            data = await self._make_request('GET', endpoint)
            return data
        except Exception as e:
            logger.error(f"Failed to fetch {asset_pair} spot price: {e}")
            return {}
    
    def _parse_spot_price(self, asset_pair: str, data: Dict[str, Any]) -> PriceObservation:
        """Parse Coinbase spot price response."""
        if 'data' not in data:
            logger.warning(f"No data in Coinbase response: {data}")
            return None
        
        price_data = data['data']
        
        # Extract price
        try:
            price = float(price_data['amount'])
        except (KeyError, ValueError) as e:
            logger.error(f"Failed to parse price from Coinbase data: {e}, data: {price_data}")
            return None
        
        # Extract base currency (e.g., BTC from BTC-USD)
        base_currency = price_data.get('base', asset_pair.split('-')[0])
        
        # Create observation
        observation = self._create_observation(
            asset=base_currency,
            price=price,
            timestamp=datetime.now(timezone.utc),
            extra_data={
                'source': 'coinbase_spot',
                'currency': price_data.get('currency', 'USD'),
                'pair': asset_pair,
            }
        )
        
        return observation
    
    async def test_connection(self) -> bool:
        """Test connection to Coinbase API."""
        try:
            # Try to fetch BTC price as a test
            data = await self._fetch_spot_price('BTC-USD')
            if data and 'data' in data:
                price = float(data['data']['amount'])
                logger.info(f"Coinbase connection test successful: BTC = ${price:.2f}")
                return True
            else:
                logger.warning("Coinbase connection test failed: no data returned")
                return False
        except Exception as e:
            logger.error(f"Coinbase connection test failed: {e}")
            return False