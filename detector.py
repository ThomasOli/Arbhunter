"""
Arbitrage opportunity detection and calculation.
"""
import uuid
from datetime import datetime
from typing import Dict, Any, Optional, List
from src.data.market_data import (
    ArbitrageOpportunity, StandardizedMarket, Platform
)
from src.utils.logger import app_logger


class ArbitrageDetector:
    """Detects and calculates arbitrage opportunities between market matches."""
    
    def __init__(self):
        self.min_profit_percentage = 2.0  # Minimum 2% profit to consider
        self.default_investment = 1000.0  # Default investment amount for calculations
    
    async def analyze_opportunity(self, match: Dict[str, Any]) -> Optional[ArbitrageOpportunity]:
        """Analyze a market match for arbitrage opportunity."""
        
        try:
            # Extract market data from match
            kalshi_market_data = match.get('kalshi_market', {})
            polymarket_market_data = match.get('polymarket_market', {})
            
            if not kalshi_market_data or not polymarket_market_data:
                app_logger.warning("Missing market data in match")
                return None
            
            # Convert to StandardizedMarket objects
            kalshi_market = StandardizedMarket(**kalshi_market_data)
            polymarket_market = StandardizedMarket(**polymarket_market_data)
            
            # Get prices
            kalshi_price = match.get('kalshi_price')
            polymarket_price = match.get('polymarket_price')
            
            if kalshi_price is None or polymarket_price is None:
                app_logger.warning("Missing price data for arbitrage calculation")
                return None
            
            # Calculate arbitrage opportunity
            arbitrage_calc = self._calculate_arbitrage(kalshi_price, polymarket_price)
            
            if not arbitrage_calc or arbitrage_calc['profit_percentage'] < self.min_profit_percentage:
                return None  # Not profitable enough
            
            # Create arbitrage opportunity object
            opportunity = ArbitrageOpportunity(
                id=str(uuid.uuid4()),
                market_1=kalshi_market,
                market_2=polymarket_market,
                profit_percentage=arbitrage_calc['profit_percentage'],
                required_investment=arbitrage_calc['required_investment'],
                potential_profit=arbitrage_calc['potential_profit'],
                risk_score=self._calculate_risk_score(match, kalshi_market, polymarket_market),
                confidence_score=match.get('similarity_score', 0.0),
                similarity_score=match.get('similarity_score', 0.0),
                price_difference=abs(kalshi_price - polymarket_price),
                llm_analysis=match.get('reasoning', ''),
                matching_rationale=match.get('reasoning', '')
            )
            
            app_logger.info(f"Found arbitrage opportunity: {opportunity.profit_percentage:.2f}% profit")
            return opportunity
            
        except Exception as e:
            app_logger.error(f"Error analyzing arbitrage opportunity: {e}")
            return None
    
    def _calculate_arbitrage(self, price1: float, price2: float) -> Optional[Dict[str, float]]:
        """Calculate arbitrage details for two market prices."""
        
        try:
            # Normalize prices to 0-1 range if needed
            price1 = self._normalize_price(price1)
            price2 = self._normalize_price(price2)
            
            # Determine which market to buy and which to sell
            if price1 < price2:
                buy_price = price1
                sell_price = price2
                buy_platform = "Market 1"
                sell_platform = "Market 2"
            else:
                buy_price = price2
                sell_price = price1
                buy_platform = "Market 2"
                sell_platform = "Market 1"
            
            # Calculate arbitrage profit
            # For binary markets: Buy YES at lower price, sell YES at higher price
            price_difference = sell_price - buy_price
            
            if price_difference <= 0:
                return None  # No arbitrage opportunity
            
            # Calculate required investment and profit
            # Simplified calculation assuming we can buy/sell equal amounts
            investment_per_share = buy_price
            profit_per_share = price_difference
            
            # Calculate for default investment amount
            shares_to_buy = self.default_investment / investment_per_share
            total_profit = shares_to_buy * profit_per_share
            profit_percentage = (total_profit / self.default_investment) * 100
            
            # Account for transaction costs (simplified - assume 1% total cost)
            transaction_cost = self.default_investment * 0.01
            net_profit = total_profit - transaction_cost
            net_profit_percentage = (net_profit / self.default_investment) * 100
            
            return {
                'profit_percentage': net_profit_percentage,
                'required_investment': self.default_investment,
                'potential_profit': net_profit,
                'buy_price': buy_price,
                'sell_price': sell_price,
                'buy_platform': buy_platform,
                'sell_platform': sell_platform,
                'shares': shares_to_buy,
                'gross_profit': total_profit,
                'transaction_cost': transaction_cost
            }
            
        except Exception as e:
            app_logger.error(f"Error calculating arbitrage: {e}")
            return None
    
    def _normalize_price(self, price: float) -> float:
        """Normalize price to 0-1 range."""
        if price <= 1.0:
            return price  # Already normalized
        elif price <= 100.0:
            return price / 100.0  # Convert from 0-100 to 0-1
        else:
            app_logger.warning(f"Unusual price value: {price}")
            return min(price / 100.0, 1.0)  # Cap at 1.0
    
    def _calculate_risk_score(
        self, 
        match: Dict[str, Any], 
        market1: StandardizedMarket, 
        market2: StandardizedMarket
    ) -> float:
        """Calculate risk score for the arbitrage opportunity (0 = low risk, 1 = high risk)."""
        
        risk_factors = []
        
        # Time-based risk
        if market1.close_date and market2.close_date:
            time_diff = abs((market1.close_date - market2.close_date).days)
            if time_diff > 7:  # More than a week difference
                risk_factors.append(0.3)
        
        # Liquidity risk
        total_volume_1 = market1.total_volume or 0
        total_volume_2 = market2.total_volume or 0
        
        if total_volume_1 < 1000 or total_volume_2 < 1000:  # Low volume
            risk_factors.append(0.2)
        
        # Platform risk (different resolution mechanisms)
        platform_risk = 0.1  # Base platform risk
        risk_factors.append(platform_risk)
        
        # Similarity risk (lower similarity = higher risk)
        similarity_score = match.get('similarity_score', 0.5)
        similarity_risk = 1.0 - similarity_score
        risk_factors.append(similarity_risk * 0.4)
        
        # Price volatility risk (very large price differences might indicate issues)
        price_diff = match.get('price_difference', 0)
        if price_diff > 0.3:  # More than 30% price difference
            risk_factors.append(0.3)
        
        # Calculate overall risk score
        total_risk = sum(risk_factors)
        return min(total_risk, 1.0)  # Cap at 1.0
    
    def calculate_optimal_bet_sizing(
        self, 
        opportunity: ArbitrageOpportunity, 
        available_capital: float,
        max_position_size: float = 0.1
    ) -> Dict[str, float]:
        """Calculate optimal bet sizing for an arbitrage opportunity."""
        
        try:
            # Kelly Criterion adapted for arbitrage
            # For arbitrage, we want to maximize return while managing risk
            
            win_probability = 1.0 - opportunity.risk_score  # Probability of successful arbitrage
            profit_ratio = opportunity.profit_percentage / 100.0
            
            # Modified Kelly fraction for arbitrage
            kelly_fraction = (win_probability * profit_ratio) / profit_ratio
            
            # Apply conservative factor and position limits
            conservative_factor = 0.5  # Be conservative
            kelly_fraction *= conservative_factor
            
            # Limit position size
            max_position = available_capital * max_position_size
            optimal_investment = min(
                kelly_fraction * available_capital,
                max_position,
                opportunity.required_investment
            )
            
            return {
                'optimal_investment': optimal_investment,
                'kelly_fraction': kelly_fraction,
                'position_percentage': (optimal_investment / available_capital) * 100,
                'expected_profit': optimal_investment * (profit_ratio * win_probability),
                'max_loss': optimal_investment * opportunity.risk_score
            }
            
        except Exception as e:
            app_logger.error(f"Error calculating optimal bet sizing: {e}")
            return {
                'optimal_investment': opportunity.required_investment,
                'kelly_fraction': 0.0,
                'position_percentage': 0.0,
                'expected_profit': 0.0,
                'max_loss': 0.0
            } 

    def detect_arbitrage_from_pairs(
        self, 
        pairs: List[Dict[str, str]], 
        kalshi_markets: List[StandardizedMarket], 
        polymarket_markets: List[StandardizedMarket]
    ) -> List[Dict[str, Any]]:
        """Detect arbitrage opportunities from matched market pairs."""
        
        opportunities = []
        
        # Create lookup dictionaries for quick access
        kalshi_lookup = {market.id: market for market in kalshi_markets}
        polymarket_lookup = {market.id: market for market in polymarket_markets}
        
        for pair in pairs:
            kalshi_id = pair.get('kalshi_id')
            polymarket_id = pair.get('polymarket_id')
            
            # Get the actual market objects
            kalshi_market = kalshi_lookup.get(kalshi_id)
            polymarket_market = polymarket_lookup.get(polymarket_id)
            
            if not kalshi_market or not polymarket_market:
                app_logger.warning(f"Could not find markets for pair: {kalshi_id}, {polymarket_id}")
                continue
            
            # Calculate arbitrage opportunity
            arbitrage = self._calculate_arbitrage_opportunity(kalshi_market, polymarket_market)
            
            if arbitrage:
                opportunities.append(arbitrage)
        
        app_logger.info(f"Found {len(opportunities)} arbitrage opportunities from {len(pairs)} pairs")
        return opportunities
    
    def _calculate_arbitrage_opportunity(
        self, 
        kalshi_market: StandardizedMarket, 
        polymarket_market: StandardizedMarket
    ) -> Optional[Dict[str, Any]]:
        """Calculate arbitrage opportunity between two markets."""
        
        try:
            # Get best prices for both markets
            kalshi_price = self._get_best_price(kalshi_market)
            polymarket_price = self._get_best_price(polymarket_market)
            
            if kalshi_price is None or polymarket_price is None:
                app_logger.debug(f"Missing price data for {kalshi_market.id} or {polymarket_market.id}")
                return None
            
            # Calculate spread
            spread = abs(kalshi_price - polymarket_price)
            
            # Determine if there's an arbitrage opportunity (minimum 2% spread)
            min_spread = 0.03
            if spread < min_spread:
                return None
            
            # Determine which market to buy and which to sell
            if kalshi_price < polymarket_price:
                buy_market = "kalshi"
                sell_market = "polymarket"
                buy_price = kalshi_price
                sell_price = polymarket_price
            else:
                buy_market = "polymarket"
                sell_market = "kalshi"
                buy_price = polymarket_price
                sell_price = kalshi_price
            
            # Calculate potential profit
            profit_per_dollar = sell_price - buy_price
            profit_percentage = profit_per_dollar * 100
            
            # Create arbitrage opportunity object
            opportunity = {
                "kalshi_market": kalshi_market,
                "polymarket_market": polymarket_market,
                "kalshi_price": kalshi_price,
                "polymarket_price": polymarket_price,
                "spread": spread,
                "profit_percentage": profit_percentage,
                "profit_per_dollar": profit_per_dollar,
                "buy_market": buy_market,
                "sell_market": sell_market,
                "buy_price": buy_price,
                "sell_price": sell_price,
                "kalshi_url": kalshi_market.source_url,
                "polymarket_url": polymarket_market.source_url,
                "detected_at": datetime.utcnow().isoformat()
            }
            
            return opportunity
            
        except Exception as e:
            app_logger.error(f"Error calculating arbitrage for {kalshi_market.id} and {polymarket_market.id}: {e}")
            return None
    
    def _get_best_price(self, market: StandardizedMarket) -> Optional[float]:
        """Get the best available price from a market (YES outcome price)."""
        if not market.outcomes:
            return None
        
        # Look for YES outcome price first
        for outcome in market.outcomes:
            if outcome.yes_price is not None:
                return outcome.yes_price
            if outcome.last_trade_price is not None:
                return outcome.last_trade_price
        
        # If no YES price, convert NO price to YES price
        for outcome in market.outcomes:
            if outcome.no_price is not None:
                return 1.0 - outcome.no_price
        
        return None
    
    def log_arbitrage_opportunities(self, opportunities: List[Dict[str, Any]]):
        """Log arbitrage opportunities to terminal with source URLs and spreads."""
        
        if not opportunities:
            print("No arbitrage opportunities found.")
            return
        
        print(f"\n{'='*80}")
        print(f"ARBITRAGE OPPORTUNITIES FOUND: {len(opportunities)}")
        print(f"{'='*80}")
        
        # Sort by profit percentage (highest first)
        sorted_opportunities = sorted(opportunities, key=lambda x: x['profit_percentage'], reverse=True)
        
        for i, opp in enumerate(sorted_opportunities, 1):
            kalshi_market = opp['kalshi_market']
            polymarket_market = opp['polymarket_market']
            
            print(f"\nOPPORTUNITY #{i}")
            print(f"{'─'*60}")
            print(f"Markets:")
            print(f"  Kalshi: {kalshi_market.title}")
            print(f"  Polymarket: {polymarket_market.title}")
            
            print(f"\nPricing:")
            print(f"  Kalshi Price: {opp['kalshi_price']:.3f}")
            print(f"  Polymarket Price: {opp['polymarket_price']:.3f}")
            print(f"  Spread: {opp['spread']:.3f} ({opp['profit_percentage']:.2f}%)")
            
            print(f"\nStrategy:")
            print(f"  Buy on: {opp['buy_market'].title()} at {opp['buy_price']:.3f}")
            print(f"  Sell on: {opp['sell_market'].title()} at {opp['sell_price']:.3f}")
            print(f"  Profit per $1: ${opp['profit_per_dollar']:.3f}")
            
            print(f"\nSource URLs:")
            print(f"  Kalshi: {opp['kalshi_url']}")
            print(f"  Polymarket: {opp['polymarket_url']}")
            
            print(f"\nDetected at: {opp['detected_at']}") 