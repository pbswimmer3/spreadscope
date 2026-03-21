"""
SpreadScope - Data models and dataclasses
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, Dict, Any, List
import json

@dataclass
class PriceObservation:
    """A single price observation from a venue."""
    time: datetime
    asset: str
    venue: str
    price: float
    volume_24h: Optional[float] = None
    funding_rate: Optional[float] = None
    open_interest: Optional[float] = None
    extra_data: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for database insertion."""
        return {
            'time': self.time,
            'asset': self.asset,
            'venue': self.venue,
            'price': self.price,
            'volume_24h': self.volume_24h,
            'funding_rate': self.funding_rate,
            'open_interest': self.open_interest,
            'extra_data': json.dumps(self.extra_data) if self.extra_data else None
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'PriceObservation':
        """Create from dictionary."""
        extra_data = data.get('extra_data')
        if isinstance(extra_data, str):
            extra_data = json.loads(extra_data)
        
        return cls(
            time=data['time'],
            asset=data['asset'],
            venue=data['venue'],
            price=data['price'],
            volume_24h=data.get('volume_24h'),
            funding_rate=data.get('funding_rate'),
            open_interest=data.get('open_interest'),
            extra_data=extra_data or {}
        )

@dataclass
class Spread:
    """Calculated spread between real and synthetic prices."""
    time: datetime
    asset: str
    real_venue: str
    synthetic_venue: str
    real_price: float
    synthetic_price: float
    spread_abs: float
    spread_pct: float
    venue_pair: str
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for database insertion."""
        return {
            'time': self.time,
            'asset': self.asset,
            'real_venue': self.real_venue,
            'synthetic_venue': self.synthetic_venue,
            'real_price': self.real_price,
            'synthetic_price': self.synthetic_price,
            'spread_abs': self.spread_abs,
            'spread_pct': self.spread_pct,
            'venue_pair': self.venue_pair
        }
    
    @classmethod
    def from_prices(cls, time: datetime, asset: str, 
                   real_price: PriceObservation, 
                   synthetic_price: PriceObservation) -> 'Spread':
        """Create spread from two price observations."""
        spread_abs = synthetic_price.price - real_price.price
        spread_pct = (spread_abs / real_price.price) * 100
        venue_pair = f"{real_price.venue}:{synthetic_price.venue}"
        
        return cls(
            time=time,
            asset=asset,
            real_venue=real_price.venue,
            synthetic_venue=synthetic_price.venue,
            real_price=real_price.price,
            synthetic_price=synthetic_price.price,
            spread_abs=spread_abs,
            spread_pct=spread_pct,
            venue_pair=venue_pair
        )

@dataclass
class OpportunityEvent:
    """An opportunity event when spread exceeds threshold."""
    id: Optional[int] = None
    asset: str = ""
    venue_pair: str = ""
    threshold_pct: float = 0.5
    opened_at: Optional[datetime] = None
    closed_at: Optional[datetime] = None
    duration_seconds: Optional[int] = None
    peak_spread_pct: Optional[float] = None
    avg_spread_pct: Optional[float] = None
    entry_spread_pct: Optional[float] = None
    exit_spread_pct: Optional[float] = None
    observations_count: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def is_open(self) -> bool:
        """Check if opportunity is still open."""
        return self.closed_at is None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for database insertion."""
        return {
            'id': self.id,
            'asset': self.asset,
            'venue_pair': self.venue_pair,
            'threshold_pct': self.threshold_pct,
            'opened_at': self.opened_at,
            'closed_at': self.closed_at,
            'duration_seconds': self.duration_seconds,
            'peak_spread_pct': self.peak_spread_pct,
            'avg_spread_pct': self.avg_spread_pct,
            'entry_spread_pct': self.entry_spread_pct,
            'exit_spread_pct': self.exit_spread_pct,
            'observations_count': self.observations_count,
            'metadata': json.dumps(self.metadata) if self.metadata else None
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'OpportunityEvent':
        """Create from dictionary."""
        metadata = data.get('metadata')
        if isinstance(metadata, str):
            metadata = json.loads(metadata)
        
        return cls(
            id=data.get('id'),
            asset=data['asset'],
            venue_pair=data['venue_pair'],
            threshold_pct=data['threshold_pct'],
            opened_at=data.get('opened_at'),
            closed_at=data.get('closed_at'),
            duration_seconds=data.get('duration_seconds'),
            peak_spread_pct=data.get('peak_spread_pct'),
            avg_spread_pct=data.get('avg_spread_pct'),
            entry_spread_pct=data.get('entry_spread_pct'),
            exit_spread_pct=data.get('exit_spread_pct'),
            observations_count=data.get('observations_count', 0),
            metadata=metadata or {}
        )

@dataclass
class VenueConfig:
    """Configuration for a price data source (venue)."""
    venue: str
    display_name: str
    venue_type: str  # 'spot', 'perps', 'synthetic'
    api_base_url: str
    polling_interval_seconds: int = 30
    is_enabled: bool = True
    supports_assets: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for database insertion."""
        return {
            'venue': self.venue,
            'display_name': self.display_name,
            'venue_type': self.venue_type,
            'api_base_url': self.api_base_url,
            'polling_interval_seconds': self.polling_interval_seconds,
            'is_enabled': self.is_enabled,
            'supports_assets': self.supports_assets
        }

@dataclass
class TrackedPair:
    """A pair to track for spread calculation."""
    id: Optional[int] = None
    asset: str = ""
    real_venue: str = ""
    synthetic_venue: str = ""
    threshold_pct: float = 0.5
    is_enabled: bool = True
    
    @property
    def venue_pair(self) -> str:
        """Get venue pair string."""
        return f"{self.real_venue}:{self.synthetic_venue}"
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for database insertion."""
        return {
            'id': self.id,
            'asset': self.asset,
            'real_venue': self.real_venue,
            'synthetic_venue': self.synthetic_venue,
            'threshold_pct': self.threshold_pct,
            'is_enabled': self.is_enabled
        }


@dataclass
class FundingRateSnapshot:
    """A funding rate observation from a perp venue."""
    time: datetime
    asset: str
    venue: str
    funding_rate: float
    annualized_rate: float
    next_funding_time: Optional[datetime] = None
    mark_price: Optional[float] = None
    index_price: Optional[float] = None
    open_interest: Optional[float] = None
    volume_24h: Optional[float] = None
    extra_data: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_8h_rate(cls, time: datetime, asset: str, venue: str,
                     funding_rate_8h: float, **kwargs) -> 'FundingRateSnapshot':
        """Create from an 8-hour funding rate (standard for most perp venues)."""
        # Annualize: rate_8h * 3 periods/day * 365 days
        annualized = funding_rate_8h * 3 * 365 * 100  # as percentage
        return cls(
            time=time,
            asset=asset,
            venue=venue,
            funding_rate=funding_rate_8h,
            annualized_rate=annualized,
            **kwargs,
        )


@dataclass
class CarrySignal:
    """A bot-readable carry trade signal."""
    id: Optional[int] = None
    asset: str = ""
    spot_venue: str = ""
    perp_venue: str = ""
    signal_type: str = "entry"  # 'entry', 'exit', 'update'
    status: str = "active"     # 'active', 'executed', 'expired', 'cancelled'

    # Funding rate data
    funding_rate_8h: float = 0.0
    annualized_rate: float = 0.0
    consecutive_positive_periods: int = 0

    # Price data
    spot_price: float = 0.0
    perp_price: float = 0.0
    entry_spread_pct: float = 0.0

    # Position sizing
    suggested_size_usd: float = 0.0
    suggested_leverage: float = 1.0
    portfolio_capital_usd: float = 5000.0

    # Expected returns
    expected_daily_return_usd: Optional[float] = None
    expected_annual_return_usd: Optional[float] = None
    expected_apy_pct: Optional[float] = None

    # Risk
    estimated_fees_usd: Optional[float] = None
    breakeven_hours: Optional[float] = None

    # Lifecycle
    created_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None
    executed_at: Optional[datetime] = None
    notes: Optional[str] = None
    parent_signal_id: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        d = {k: v for k, v in self.__dict__.items()}
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'CarrySignal':
        fields = {f.name for f in cls.__dataclass_fields__.values()}
        filtered = {k: v for k, v in data.items() if k in fields}
        return cls(**filtered)