"""
SpreadScope - dYdX v4 Perpetual Futures Worker
"""

import asyncio
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional

from .base_worker import BaseWorker
from ..models import PriceObservation, FundingRateSnapshot
from ..utils import setup_logging

logger = setup_logging(__name__)

class DydxWorker(BaseWorker):
    """Worker for dYdX v4 perpetual futures prices."""
    
    def __init__(self, config: Dict[str, Any]):
        super().__init__('dydx', config)

        # Assets to track (dYdX market tickers)
        self.tracked_assets = ['BTC', 'ETH']

        # dYdX market name mapping
        self.market_map = {
            'BTC-USD': 'BTC',
            'ETH-USD': 'ETH',
        }

        # Cache last markets data for funding rate extraction
        self._last_markets: Dict[str, Any] = {}
        
    async def fetch_prices(self) -> List[PriceObservation]:
        """Fetch perpetual futures prices from dYdX v4."""
        observations = []
        
        try:
            markets_data = await self._fetch_perpetual_markets()
            if not markets_data:
                return observations
            
            markets = markets_data.get('markets', {})
            self._last_markets = markets

            for market_ticker, market_info in markets.items():
                asset = self.market_map.get(market_ticker)
                if asset and asset in self.tracked_assets:
                    observation = self._parse_market(asset, market_ticker, market_info)
                    if observation:
                        observations.append(observation)
            
            logger.debug(f"Fetched {len(observations)} assets from dYdX")
            
        except Exception as e:
            logger.error(f"Error fetching dYdX prices: {e}")
        
        return observations
    
    async def _fetch_perpetual_markets(self) -> Optional[Dict[str, Any]]:
        """Fetch perpetual markets data from dYdX v4 indexer."""
        endpoint = "perpetualMarkets"
        
        try:
            data = await self._make_request('GET', endpoint)
            return data
        except Exception as e:
            logger.error(f"Failed to fetch dYdX perpetual markets: {e}")
            return None
    
    def _parse_market(self, asset: str, market_ticker: str, market_info: Dict[str, Any]) -> Optional[PriceObservation]:
        """Parse dYdX market data into a PriceObservation."""
        try:
            # Extract oracle price (most reliable price source)
            oracle_price = market_info.get('oraclePrice')
            if oracle_price is None:
                logger.debug(f"No oracle price for {market_ticker} on dYdX")
                return None
            
            price = float(oracle_price)
            
            # Extract funding rate
            funding_rate = None
            next_funding = market_info.get('nextFundingRate')
            if next_funding is not None:
                try:
                    funding_rate = float(next_funding)
                except (ValueError, TypeError):
                    pass
            
            # Extract open interest
            open_interest = None
            oi = market_info.get('openInterest')
            if oi is not None:
                try:
                    open_interest = float(oi)
                except (ValueError, TypeError):
                    pass
            
            # Extract 24h volume
            volume_24h = None
            vol = market_info.get('volume24H')
            if vol is not None:
                try:
                    volume_24h = float(vol)
                except (ValueError, TypeError):
                    pass
            
            observation = self._create_observation(
                asset=asset,
                price=price,
                timestamp=datetime.now(timezone.utc),
                volume_24h=volume_24h,
                funding_rate=funding_rate,
                open_interest=open_interest,
                extra_data={
                    'source': 'dydx_v4',
                    'market_ticker': market_ticker,
                    'price_change_24h': market_info.get('priceChange24H'),
                    'trades_24h': market_info.get('trades24H'),
                    'tick_size': market_info.get('tickSize'),
                    'step_size': market_info.get('stepSize'),
                    'initial_margin_fraction': market_info.get('initialMarginFraction'),
                }
            )
            
            return observation
            
        except Exception as e:
            logger.error(f"Failed to parse dYdX market {market_ticker}: {e}")
            return None
    
    async def fetch_funding_rates(self) -> List[FundingRateSnapshot]:
        """Extract funding rate snapshots from cached market data."""
        snapshots = []
        now = datetime.now(timezone.utc)

        for market_ticker, market_info in self._last_markets.items():
            asset = self.market_map.get(market_ticker)
            if not asset or asset not in self.tracked_assets:
                continue

            next_funding = market_info.get('nextFundingRate')
            oracle_price = market_info.get('oraclePrice')
            if next_funding is None or oracle_price is None:
                continue

            try:
                funding_rate = float(next_funding)
                price = float(oracle_price)
            except (ValueError, TypeError):
                continue

            oi = None
            if market_info.get('openInterest') is not None:
                try:
                    oi = float(market_info['openInterest'])
                except (ValueError, TypeError):
                    pass

            vol = None
            if market_info.get('volume24H') is not None:
                try:
                    vol = float(market_info['volume24H'])
                except (ValueError, TypeError):
                    pass

            snapshot = FundingRateSnapshot.from_8h_rate(
                time=now,
                asset=asset,
                venue=self.venue,
                funding_rate_8h=funding_rate,
                mark_price=price,
                index_price=price,
                open_interest=oi,
                volume_24h=vol,
            )
            snapshots.append(snapshot)

        return snapshots

    async def test_connection(self) -> bool:
        """Test connection to dYdX API."""
        try:
            data = await self._fetch_perpetual_markets()
            if data and 'markets' in data:
                market_count = len(data['markets'])
                logger.info(f"dYdX connection test successful: {market_count} markets available")
                
                for ticker, info in data['markets'].items():
                    asset = self.market_map.get(ticker)
                    if asset in self.tracked_assets:
                        price = info.get('oraclePrice', 'N/A')
                        logger.info(f"  - {ticker}: ${price}")
                
                return True
            else:
                logger.warning("dYdX connection test failed: no markets data")
                return False
        except Exception as e:
            logger.error(f"dYdX connection test failed: {e}")
            return False