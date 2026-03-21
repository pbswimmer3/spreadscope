"""
SpreadScope - Hyperliquid Perpetual Futures Worker
"""

import asyncio
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional

from .base_worker import BaseWorker
from ..models import PriceObservation, FundingRateSnapshot
from ..utils import setup_logging

logger = setup_logging(__name__)

class HyperliquidWorker(BaseWorker):
    """Worker for Hyperliquid perpetual futures prices."""
    
    def __init__(self, config: Dict[str, Any]):
        super().__init__('hyperliquid_perps', config)

        # Tracked assets (will be populated from metadata)
        self.tracked_assets = ['BTC', 'ETH']
        # Cache parsed asset data for funding rate extraction
        self._last_asset_data: Dict[str, Dict[str, Any]] = {}
        
    async def fetch_prices(self) -> List[PriceObservation]:
        """Fetch perpetual futures prices from Hyperliquid."""
        observations = []
        
        try:
            # Get metadata and asset contexts
            metadata = await self._fetch_metadata()
            if not metadata:
                return observations
            
            # Parse all assets from metadata
            asset_data = self._parse_metadata(metadata)
            self._last_asset_data = asset_data

            for asset_name, asset_info in asset_data.items():
                # Only track specific assets
                if asset_name in self.tracked_assets:
                    observation = self._create_observation_from_asset(asset_name, asset_info)
                    if observation:
                        observations.append(observation)
            
            logger.debug(f"Fetched {len(observations)} assets from Hyperliquid")
            
        except Exception as e:
            logger.error(f"Error fetching Hyperliquid prices: {e}")
        
        return observations
    
    async def _fetch_metadata(self) -> Optional[Dict[str, Any]]:
        """Fetch metadata and asset contexts from Hyperliquid."""
        endpoint = "info"
        
        try:
            # Request metadata and asset contexts
            data = await self._make_request(
                'POST',
                endpoint,
                json={"type": "metaAndAssetCtxs"}
            )
            return data
        except Exception as e:
            logger.error(f"Failed to fetch Hyperliquid metadata: {e}")
            return None
    
    def _parse_metadata(self, metadata: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
        """Parse Hyperliquid metadata response."""
        asset_data = {}
        
        try:
            # Structure: [universe_metadata, asset_contexts]
            if isinstance(metadata, list) and len(metadata) >= 2:
                universe_data = metadata[0]
                contexts = metadata[1]

                # universe_data is {"universe": [...], ...}
                universe = universe_data.get('universe', []) if isinstance(universe_data, dict) else universe_data

                # Map asset indices to names
                asset_map = {}
                for i, asset in enumerate(universe):
                    if isinstance(asset, dict) and 'name' in asset:
                        asset_name = asset['name']
                        asset_map[i] = asset_name
                
                # Extract price data from contexts
                for i, context in enumerate(contexts):
                    asset_name = asset_map.get(i, f"ASSET_{i}")
                    
                    # Extract mid price
                    mid_px = context.get('midPx')
                    if mid_px is not None:
                        try:
                            price = float(mid_px)
                        except (ValueError, TypeError):
                            price = None
                    else:
                        price = None
                    
                    # Extract funding rate
                    funding = context.get('funding')
                    if funding is not None:
                        try:
                            funding_rate = float(funding)
                        except (ValueError, TypeError):
                            funding_rate = None
                    else:
                        funding_rate = None
                    
                    # Extract open interest
                    open_interest = context.get('openInterest')
                    if open_interest is not None:
                        try:
                            open_interest_val = float(open_interest)
                        except (ValueError, TypeError):
                            open_interest_val = None
                    else:
                        open_interest_val = None
                    
                    # Extract volume
                    daily_volume = context.get('dayNtlVlm')
                    if daily_volume is not None:
                        try:
                            volume_24h = float(daily_volume)
                        except (ValueError, TypeError):
                            volume_24h = None
                    else:
                        volume_24h = None
                    
                    asset_data[asset_name] = {
                        'price': price,
                        'funding_rate': funding_rate,
                        'open_interest': open_interest_val,
                        'volume_24h': volume_24h,
                        'raw_context': context
                    }
            
        except Exception as e:
            logger.error(f"Failed to parse Hyperliquid metadata: {e}")
        
        return asset_data
    
    def _create_observation_from_asset(self, asset_name: str, asset_info: Dict[str, Any]) -> Optional[PriceObservation]:
        """Create PriceObservation from asset info."""
        price = asset_info.get('price')
        if price is None:
            logger.debug(f"No price for {asset_name} on Hyperliquid")
            return None
        
        observation = self._create_observation(
            asset=asset_name,
            price=price,
            timestamp=datetime.now(timezone.utc),
            volume_24h=asset_info.get('volume_24h'),
            funding_rate=asset_info.get('funding_rate'),
            open_interest=asset_info.get('open_interest'),
            extra_data={
                'source': 'hyperliquid_perps',
            }
        )
        
        return observation
    
    async def fetch_funding_rates(self) -> List[FundingRateSnapshot]:
        """Extract funding rate snapshots from cached asset data."""
        snapshots = []
        now = datetime.now(timezone.utc)

        for asset_name in self.tracked_assets:
            info = self._last_asset_data.get(asset_name)
            if not info:
                continue

            funding_rate = info.get('funding_rate')
            price = info.get('price')
            if funding_rate is None or price is None:
                continue

            snapshot = FundingRateSnapshot.from_8h_rate(
                time=now,
                asset=asset_name,
                venue=self.venue,
                funding_rate_8h=funding_rate,
                mark_price=price,
                open_interest=info.get('open_interest'),
                volume_24h=info.get('volume_24h'),
            )
            snapshots.append(snapshot)

        return snapshots

    async def test_connection(self) -> bool:
        """Test connection to Hyperliquid API."""
        try:
            metadata = await self._fetch_metadata()
            if metadata and isinstance(metadata, list) and len(metadata) >= 2:
                asset_count = len(metadata[1])
                logger.info(f"Hyperliquid connection test successful: {asset_count} assets available")

                # Log sample prices
                asset_data = self._parse_metadata(metadata)
                for asset in ['BTC', 'ETH']:
                    if asset in asset_data and asset_data[asset].get('price'):
                        price = asset_data[asset]['price']
                        logger.info(f"  - {asset}: ${price:.2f}")

                return True
            else:
                logger.warning("Hyperliquid connection test failed: invalid response")
                return False
        except Exception as e:
            logger.error(f"Hyperliquid connection test failed: {e}")
            return False