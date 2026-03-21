"""
SpreadScope - Base worker class for price ingestion
"""

import asyncio
import aiohttp
import logging
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional

from ..db import insert_price_observations, insert_funding_rate_snapshot
from ..models import PriceObservation, FundingRateSnapshot
from ..utils import setup_logging, normalize_asset_name, validate_price, RateLimiter

class BaseWorker(ABC):
    """Base class for all price ingestion workers."""
    
    def __init__(self, venue: str, config: Dict[str, Any]):
        self.venue = venue
        self.config = config
        self.logger = setup_logging(f"ingestion.{venue}")
        self.session: Optional[aiohttp.ClientSession] = None
        self.rate_limiter: Optional[RateLimiter] = None
        
        # Get worker-specific config
        self.base_url = config.get('base_url', '')
        self.polling_interval = config.get('polling_interval_seconds', 30)
        self.is_enabled = config.get('enabled', True)
        self.api_key = config.get('api_key')
        
        # Rate limiting
        calls_per_minute = config.get('calls_per_minute', 60)
        self.rate_limiter = RateLimiter(calls_per_minute)
        
        # Track last fetch time to avoid duplicates
        self.last_fetch_time: Optional[datetime] = None
        
    async def start(self):
        """Start the worker loop."""
        if not self.is_enabled:
            self.logger.info(f"{self.venue} worker is disabled, skipping")
            return
        
        self.session = aiohttp.ClientSession()
        self.logger.info(f"Starting {self.venue} worker, polling every {self.polling_interval}s")
        
        try:
            while True:
                await self._poll_cycle()
                await asyncio.sleep(self.polling_interval)
        except asyncio.CancelledError:
            self.logger.info(f"{self.venue} worker cancelled")
        except Exception as e:
            self.logger.error(f"{self.venue} worker crashed: {e}", exc_info=True)
        finally:
            if self.session:
                await self.session.close()
    
    async def _poll_cycle(self):
        """Single poll cycle with error handling."""
        try:
            if self.rate_limiter:
                await self.rate_limiter.acquire()
            
            observations = await self.fetch_prices()

            if observations:
                valid_observations = []
                for obs in observations:
                    if self._validate_observation(obs):
                        valid_observations.append(obs)

                if valid_observations:
                    count = await insert_price_observations(valid_observations)
                    self.logger.debug(f"Wrote {count} observations to database")

                    # Log sample of what was fetched
                    if count > 0:
                        sample = valid_observations[0]
                        self.logger.info(f"Fetched {sample.asset}@{self.venue} = ${sample.price:.2f} (+{count-1} more)")

            # Collect funding rates if this worker supports them
            funding_snapshots = await self.fetch_funding_rates()
            for snap in funding_snapshots:
                try:
                    await insert_funding_rate_snapshot(snap)
                except Exception as e:
                    self.logger.error(f"Failed to insert funding rate snapshot: {e}")

            self.last_fetch_time = datetime.now(timezone.utc)
            
        except aiohttp.ClientError as e:
            self.logger.error(f"HTTP error in {self.venue} worker: {e}")
            await asyncio.sleep(5)  # Short backoff for network errors
        except Exception as e:
            self.logger.error(f"Error in {self.venue} worker: {e}", exc_info=True)
            await asyncio.sleep(30)  # Longer backoff for other errors
    
    def _validate_observation(self, observation: PriceObservation) -> bool:
        """Validate a price observation before insertion."""
        # Check if price is valid
        if not validate_price(observation.price, observation.asset):
            self.logger.warning(f"Invalid price for {observation.asset}: ${observation.price}")
            return False
        
        # Check if observation is too old (more than 5 minutes)
        age = (datetime.now(timezone.utc) - observation.time).total_seconds()
        if age > 300:  # 5 minutes
            self.logger.warning(f"Stale observation for {observation.asset}: {age:.0f}s old")
            return False
        
        # Check for duplicates (same asset, same time)
        if (self.last_fetch_time and 
            observation.time <= self.last_fetch_time):
            self.logger.debug(f"Skipping duplicate observation for {observation.asset}")
            return False
        
        return True
    
    @abstractmethod
    async def fetch_prices(self) -> List[PriceObservation]:
        """
        Fetch prices from the API.

        Returns:
            List of PriceObservation objects ready for database insertion.
        """
        pass

    async def fetch_funding_rates(self) -> List[FundingRateSnapshot]:
        """
        Fetch funding rates from the API. Override in perp venue workers.

        Returns:
            List of FundingRateSnapshot objects. Default: empty list.
        """
        return []
    
    async def _make_request(self, method: str, endpoint: str, **kwargs) -> Dict[str, Any]:
        """Make HTTP request with error handling."""
        if not self.session:
            raise RuntimeError("Session not initialized")
        
        url = f"{self.base_url.rstrip('/')}/{endpoint.lstrip('/')}"
        
        # Set default headers
        headers = kwargs.get('headers', {})
        if 'User-Agent' not in headers:
            headers['User-Agent'] = 'SpreadScope/1.0'
        if 'Accept' not in headers:
            headers['Accept'] = 'application/json'
        
        # Add API key if needed
        if self.api_key:
            if 'polygon' in self.venue:
                # Polygon API key as query parameter
                params = kwargs.get('params', {})
                params = params.copy() if params else {}
                params['apiKey'] = self.api_key
                kwargs['params'] = params
            else:
                # Most APIs use Authorization header
                headers['Authorization'] = f"Bearer {self.api_key}"
        
        kwargs['headers'] = headers
        
        try:
            async with self.session.request(method, url, **kwargs) as response:
                response.raise_for_status()
                content_type = response.headers.get('Content-Type', '')
                
                if 'application/json' in content_type:
                    return await response.json()
                else:
                    text = await response.text()
                    self.logger.warning(f"Non-JSON response from {self.venue}: {text[:100]}")
                    return {'text': text}
        
        except aiohttp.ClientResponseError as e:
            if e.status == 429:  # Rate limited
                self.logger.warning(f"Rate limited by {self.venue}, backing off...")
                await asyncio.sleep(60)  # Wait 1 minute
            elif e.status == 401:  # Unauthorized
                self.logger.error(f"API key invalid for {self.venue}")
                self.is_enabled = False  # Disable worker
            raise
        except aiohttp.ClientError as e:
            self.logger.error(f"HTTP error from {self.venue}: {e}")
            raise
    
    def _create_observation(self, asset: str, price: float, 
                           timestamp: Optional[datetime] = None,
                           volume_24h: Optional[float] = None,
                           funding_rate: Optional[float] = None,
                           open_interest: Optional[float] = None,
                           extra_data: Optional[Dict[str, Any]] = None) -> PriceObservation:
        """Create a PriceObservation object."""
        if timestamp is None:
            timestamp = datetime.now(timezone.utc)
        
        # Normalize asset name
        normalized_asset = normalize_asset_name(asset)
        
        return PriceObservation(
            time=timestamp,
            asset=normalized_asset,
            venue=self.venue,
            price=price,
            volume_24h=volume_24h,
            funding_rate=funding_rate,
            open_interest=open_interest,
            extra_data=extra_data or {}
        )