"""
Data models for market information from both Kalshi and Polymarket.
"""
from datetime import datetime
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field
from enum import Enum


class MarketStatus(str, Enum):
    """Market status enumeration."""
    ACTIVE = "active"
    CLOSED = "closed"
    SETTLED = "settled"
    PAUSED = "paused"


class MarketType(str, Enum):
    """Market type enumeration."""
    BINARY = "binary"
    CATEGORICAL = "categorical"
    SCALAR = "scalar"


class Platform(str, Enum):
    """Trading platform enumeration."""
    KALSHI = "kalshi"
    POLYMARKET = "polymarket"


class MarketOutcome(BaseModel):
    """Represents a specific outcome in a market."""
    id: str
    name: str
    yes_price: Optional[float] = None  # Price for YES (0-1 or 0-100 depending on platform)
    no_price: Optional[float] = None   # Price for NO
    volume: Optional[float] = None
    last_trade_price: Optional[float] = None
    bid: Optional[float] = None
    ask: Optional[float] = None
    is_winner: Optional[bool] = None  # Whether this outcome won (for resolved markets)


class StandardizedMarket(BaseModel):
    """Standardized market data structure for both platforms."""
    # Core identification
    id: str
    platform: Platform
    title: str
    description: str
    
    # Market properties
    market_type: MarketType = MarketType.BINARY
    status: MarketStatus
    category: Optional[str] = None
    subcategory: Optional[str] = None
    
    # Timing
    created_at: Optional[datetime] = None
    close_date: Optional[datetime] = None
    resolution_date: Optional[datetime] = None
    
    # Outcomes and pricing
    outcomes: List[MarketOutcome] = Field(default_factory=list)
    
    # Volume and liquidity
    total_volume: Optional[float] = None
    total_liquidity: Optional[float] = None
    
    # Metadata
    tags: List[str] = Field(default_factory=list)
    source_url: Optional[str] = None
    raw_data: Dict[str, Any] = Field(default_factory=dict)  # Original platform data
    
    # Standardized fields for arbitrage detection
    primary_question: str  # Simplified question for LLM matching
    confidence_score: Optional[float] = None  # How confident we are in this market
    
    class Config:
        use_enum_values = True


class ArbitrageOpportunity(BaseModel):
    """Represents a potential arbitrage opportunity between two markets."""
    id: str
    market_1: StandardizedMarket
    market_2: StandardizedMarket
    
    # Arbitrage details
    profit_percentage: float
    required_investment: float
    potential_profit: float
    
    # Risk assessment
    risk_score: float = Field(ge=0, le=1)  # 0 = low risk, 1 = high risk
    confidence_score: float = Field(ge=0, le=1)  # How sure we are these markets match
    
    # Market comparison
    similarity_score: float = Field(ge=0, le=1)  # How similar the markets are
    price_difference: float
    
    # Timing
    discovered_at: datetime = Field(default_factory=datetime.utcnow)
    expiry_estimate: Optional[datetime] = None
    
    # LLM analysis
    llm_analysis: Optional[str] = None
    matching_rationale: Optional[str] = None


class MarketMatchRequest(BaseModel):
    """Request structure for LLM market matching."""
    markets: List[StandardizedMarket]
    max_matches: int = 10
    min_similarity_threshold: float = 0.7


class MarketMatchResponse(BaseModel):
    """Response structure from LLM market matching."""
    matches: List[Dict[str, Any]]
    confidence_score: float
    reasoning: str


class ScanningSession(BaseModel):
    """Represents a complete scanning session."""
    session_id: str
    started_at: datetime = Field(default_factory=datetime.utcnow)
    completed_at: Optional[datetime] = None
    
    # Markets fetched
    kalshi_markets_count: int = 0
    polymarket_markets_count: int = 0
    
    # Opportunities found
    opportunities_found: int = 0
    opportunities: List[ArbitrageOpportunity] = Field(default_factory=list)
    
    # Session metadata
    vpn_connected: bool = False
    errors: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list) 