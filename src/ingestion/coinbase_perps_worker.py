"""
SpreadScope - Coinbase Perpetual Futures Worker
Uses the Advanced Trade API (public endpoints, no auth needed for market data)
"""

import asyncio
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional

from .base_worker import BaseWorker
from ..models import PriceObservation
from ..utils import setup_logging

logger = setup_logging(__name__)

class CoinbasePerpsWorker(BaseWorker):
    """Worker for Coinbase perpetual futures prices."""
    
    def __init__(self, config: Dict[str, Any]):
        super().__init__('coinbase_perps', config)
        
        # NOTE: Coinbase Advanced Trade API products endpoint requires authentication.
        # The public exchange API doesn't expose perp prices.
        # This worker is STUBBED until auth is configured.
        # For now, disable by default.
        if not self.api_key or self.api_key == 'CHANGE_ME':
            logger.warning("Coinbase Perps worker disabled — requires API authentication. "
                         "The Advanced Trade API /products endpoint needs a valid API key + secret. "
                         "See: https://docs.cdp.coinbase.com/advanced-trade-api/")
            self.is_enabled = False
        
        # Coinbase perp product IDs (verify these exist on your account)
        self.products = ['BTC-PERP-INTX', 'ETH-PERP-INTX']
        
        # Asset name mapping
        self.product_to_asset = {
            'BTC-PERP-INTX': 'BTC',
            'ETH-PERP-INTX': 'ETH',
        }
    
    async def fetch_prices(self) -> List[PriceObservation]:
        """Fetch perpetual futures prices from Coinbase."""
        observations = []
        
        for product_id in self.products:
            try:
                product_data = await self._fetch_product(product_id)
                if product_data:
                    obs = self._parse_product(product_id, product_data)
                    if obs:
                        observations.append(obs)
            except Exception as e:
                logger.error(f"Error fetching {product_id} from Coinbase: {e}")
                continue
        
        return observations
    
    async def _fetch_product(self, product_id: str) -> Optional[Dict[str, Any]]:
        """Fetch product data from Coinbase Advanced Trade API."""
        endpoint = f"api/v3/brokerage/products/{product_id}"
        
        try:
            data = await self._make_request('GET', endpoint)
            return data
        except Exception as e:
            logger.error(f"Failed to fetch product {product_id}: {e}")
            return None
    
    def _parse_product(self, product_id: str, data: Dict[str, Any]) -> Optional[PriceObservation]:
        """Parse Coinbase product response into a PriceObservation."""
        try:
            price_str = data.get('price')
            if price_str is None:
                logger.debug(f"No price for {product_id}")
                return None
            
            price = float(price_str)
            asset = self.product_to_asset.get(product_id, product_id.split('-')[0])
            
            # Volume
            volume_24h = None
            vol = data.get('volume_24h')
            if vol is not None:
                try:
                    volume_24h = float(vol)
                except (ValueError, TypeError):
                    pass
            
            # Price change
            price_change_24h = data.get('price_percentage_change_24h')
            
            return self._create_observation(
                asset=asset,
                price=price,
                timestamp=datetime.now(timezone.utc),
                volume_24h=volume_24h,
                extra_data={
                    'source': 'coinbase_perps',
                    'product_id': product_id,
                    'display_name': data.get('display_name'),
                    'price_change_24h': price_change_24h,
                    'product_type': data.get('product_type'),
                }
            )
            
        except Exception as e:
            logger.error(f"Failed to parse Coinbase product {product_id}: {e}")
            return None
    
    async def test_connection(self) -> bool:
        """Test connection to Coinbase perps API."""
        try:
            data = await self._fetch_product('BTC-PERP-INTX')
            if data and data.get('price'):
                price = float(data['price'])
                logger.info(f"Coinbase perps connection test successful: BTC-PERP = ${price:.2f}")
                return True
            else:
                logger.warning("Coinbase perps connection test: no price data. "
                             "Product may not be available or product ID may have changed.")
                return False
        except Exception as e:
            logger.error(f"Coinbase perps connection test failed: {e}")
            return False