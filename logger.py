"""
Logging configuration for the arbitrage scanner.
"""
import sys
from loguru import logger
from config.settings import settings

import json
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any
from src.data.market_data import StandardizedMarket


def setup_logger():
    """Configure the application logger."""
    # Remove default handler
    logger.remove()
    
    # Add console handler with custom format
    logger.add(
        sys.stdout,
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>",
        level=settings.LOG_LEVEL,
        colorize=True
    )
    
    # Add file handler for persistent logging
    logger.add(
        "logs/arbitrage_scanner.log",
        format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} - {message}",
        level=LOG_LEVEL,
        rotation="10 MB",
        retention="7 days",
        compression="zip"
    )
    
    return logger


# Initialize logger
app_logger = setup_logger() 


def log_markets_to_file(markets: List[StandardizedMarket], platform: str, keyword: str = None):
    """Log markets data to a JSON file."""
    try:
        # Create logs directory if it doesn't exist
        logs_dir = Path("logs")
        logs_dir.mkdir(exist_ok=True)
        
        # Create filename with timestamp
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        keyword_suffix = f"_{keyword}" if keyword else ""
        filename = f"{platform}_markets{keyword_suffix}_{timestamp}.json"
        filepath = logs_dir / filename
        
        # Convert markets to dictionaries for JSON serialization
        markets_data = []
        for market in markets:
            market_dict = {
                "id": market.id,
                "platform": market.platform.value if hasattr(market.platform, 'value') else str(market.platform),
                "title": market.title,
                "description": market.description,
                "category": market.category,
                "subcategory": market.subcategory,
                "market_type": market.market_type.value if hasattr(market.market_type, 'value') else str(market.market_type),
                "status": market.status.value if hasattr(market.status, 'value') else str(market.status),
                "created_at": market.created_at.isoformat() if market.created_at else None,
                "close_date": market.close_date.isoformat() if market.close_date else None,
                "resolution_date": market.resolution_date.isoformat() if market.resolution_date else None,
                "outcomes": [
                    {
                        "id": outcome.id,
                        "name": outcome.name,
                        "yes_price": outcome.yes_price,
                        "no_price": outcome.no_price,
                        "last_trade_price": outcome.last_trade_price,
                        "volume": outcome.volume,
                        "bid": outcome.bid,
                        "ask": outcome.ask,
                        "is_winner": outcome.is_winner
                    }
                    for outcome in market.outcomes
                ],
                "total_volume": market.total_volume,
                "total_liquidity": market.total_liquidity,
                "tags": market.tags,
                "source_url": market.source_url,
                "primary_question": market.primary_question,
                "confidence_score": market.confidence_score
            }
            markets_data.append(market_dict)
        
        # Create metadata
        log_data = {
            "metadata": {
                "platform": platform,
                "keyword": keyword,
                "timestamp": datetime.now().isoformat(),
                "total_markets": len(markets),
                "extraction_method": "keyword_search" if keyword else "general_fetch"
            },
            "markets": markets_data
        }
        
        # Write to file
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(log_data, f, indent=2, ensure_ascii=False)
        
        app_logger.info(f"Logged {len(markets)} {platform} markets to {filepath}")
        return str(filepath)
        
    except Exception as e:
        app_logger.error(f"Error logging {platform} markets to file: {e}")
        return None

def log_arbitrage_pairs_to_file(pairs: List[Dict[str, str]], arbitrage_opportunities: List[Dict[str, Any]], keyword: str = None):
    """Log matched pairs and arbitrage opportunities to a JSON file."""
    try:
        # Create logs directory if it doesn't exist
        logs_dir = Path("logs")
        logs_dir.mkdir(exist_ok=True)
        
        # Create filename with timestamp
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        keyword_suffix = f"_{keyword}" if keyword else ""
        filename = f"arbitrage_analysis{keyword_suffix}_{timestamp}.json"
        filepath = logs_dir / filename
        
        # Prepare arbitrage opportunities data (convert market objects to dicts)
        opportunities_data = []
        for opp in arbitrage_opportunities:
            opp_data = {
                "kalshi_market_id": opp["kalshi_market"].id,
                "kalshi_market_title": opp["kalshi_market"].title,
                "polymarket_market_id": opp["polymarket_market"].id,
                "polymarket_market_title": opp["polymarket_market"].title,
                "kalshi_price": opp["kalshi_price"],
                "polymarket_price": opp["polymarket_price"],
                "spread": opp["spread"],
                "profit_percentage": opp["profit_percentage"],
                "profit_per_dollar": opp["profit_per_dollar"],
                "buy_market": opp["buy_market"],
                "sell_market": opp["sell_market"],
                "buy_price": opp["buy_price"],
                "sell_price": opp["sell_price"],
                "kalshi_url": opp["kalshi_url"],
                "polymarket_url": opp["polymarket_url"],
                "detected_at": opp["detected_at"]
            }
            opportunities_data.append(opp_data)
        
        # Create log data
        log_data = {
            "metadata": {
                "keyword": keyword,
                "timestamp": datetime.now().isoformat(),
                "total_matched_pairs": len(pairs),
                "total_arbitrage_opportunities": len(arbitrage_opportunities),
                "analysis_type": "market_matching_and_arbitrage"
            },
            "matched_pairs": pairs,
            "arbitrage_opportunities": opportunities_data
        }
        
        # Write to file
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(log_data, f, indent=2, ensure_ascii=False)
        
        app_logger.info(f"Logged {len(pairs)} matched pairs and {len(arbitrage_opportunities)} arbitrage opportunities to {filepath}")
        return str(filepath)
        
    except Exception as e:
        app_logger.error(f"Error logging arbitrage analysis to file: {e}")
        return None 