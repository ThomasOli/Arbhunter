"""
Polymarket API client using the CLOB API.
Requires VPN connection to access from restricted regions.
"""
import aiohttp
import asyncio
import time
from datetime import datetime
from typing import Optional, Dict, Any, List

from config.settings import settings
from src.data.market_data import (
    StandardizedMarket, MarketOutcome, MarketStatus, 
    MarketType, Platform
)
from src.vpn.nordvpn_manager import vpn_manager
from src.utils.logger import app_logger


class PolymarketClient:
    """Polymarket API client using CLOB API."""
    
    def __init__(self):
        self.session = None
        self.vpn_required = True
        self.clob_api_url = "https://clob.polymarket.com"
        self._request_count = 0
        self._last_request_time = 0
        
    async def __aenter__(self):
        """Async context manager entry."""
        # Configure session with DNS resolver and connector settings
        connector = aiohttp.TCPConnector(
            ttl_dns_cache=300,  # DNS cache for 5 minutes
            use_dns_cache=True,
            limit=10,
            limit_per_host=5
        )
        timeout = aiohttp.ClientTimeout(total=30, connect=10)
        self.session = aiohttp.ClientSession(connector=connector, timeout=timeout)
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        if self.session:
            await self.session.close()
    
    async def _make_request(self, endpoint: str, params: Optional[Dict[str, Any]] = None, max_retries: int = 3) -> Dict[str, Any]:
        """Make HTTP request to CLOB API with retry logic."""
        if not self.session:
            raise RuntimeError("Client session not initialized. Use async context manager.")
        
        # Check VPN connection but don't attempt to reconnect
        if self.vpn_required:
            is_connected, _ = vpn_manager.get_status()
            if not is_connected:
                raise RuntimeError("Cannot make API request: VPN connection required but not active")
        
        url = f"{self.clob_api_url}/{endpoint.lstrip('/')}"
        
        # Add headers for CLOB API
        headers = {
            'Accept': 'application/json',
            'User-Agent': 'ArbitrageScanner/1.0'
        }
        
        last_exception = None
        
        for attempt in range(1, max_retries + 1):
            try:
                # Rate limiting
                await asyncio.sleep(0.1)  # Simple rate limiting
                
                app_logger.debug(f"Making request to {url} (attempt {attempt}/{max_retries}) with params: {params}")
                
                # Make the actual request
                async with self.session.get(url, params=params, headers=headers) as response:
                    if response.status == 429:
                        retry_after = int(response.headers.get('Retry-After', 60))
                        app_logger.warning(f"Rate limited. Waiting {retry_after} seconds...")
                        await asyncio.sleep(retry_after)
                        raise Exception("Rate limit exceeded")
                    
                    if response.status >= 400:
                        error_text = await response.text()
                        app_logger.error(f"Polymarket CLOB API error {response.status}: {error_text}")
                        app_logger.error(f"Request URL: {url}")
                        if 'data' in locals():
                            app_logger.error(f"Request payload: {data}")
                        if 'params' in locals():
                            app_logger.error(f"Request params: {params}")
                        app_logger.error(f"Request headers: {headers}")
                        raise Exception(f"HTTP {response.status}: {error_text}")
                    
                    result = await response.json()
                    app_logger.debug(f"Request successful: {len(str(result))} chars")
                    return result
                    
            except Exception as e:
                last_exception = e
                app_logger.warning(f"Request attempt {attempt}/{max_retries} failed: {e}")
                
                if attempt < max_retries:
                    wait_time = 2 * attempt  # Progressive backoff: 2s, 4s
                    app_logger.info(f"Waiting {wait_time} seconds before retry...")
                    await asyncio.sleep(wait_time)
                else:
                    app_logger.error(f"All {max_retries} request attempts failed")
                    raise last_exception

    async def _make_post_request(self, endpoint: str, payload: Dict[str, Any], max_retries: int = 3) -> Dict[str, Any]:
        """Make HTTP POST request to CLOB API with retry logic."""
        if not self.session:
            raise RuntimeError("Client session not initialized. Use async context manager.")
        
        # Check VPN connection but don't attempt to reconnect
        if self.vpn_required:
            is_connected, _ = vpn_manager.get_status()
            if not is_connected:
                raise RuntimeError("Cannot make API request: VPN connection required but not active")
        
        url = f"{self.clob_api_url}/{endpoint.lstrip('/')}"
        
        headers = {
            'Accept': 'application/json',
            'Content-Type': 'application/json',
            'User-Agent': 'ArbitrageScanner/1.0'
        }
        
        last_exception = None
        
        for attempt in range(1, max_retries + 1):
            try:
                # Rate limiting
                await asyncio.sleep(0.1)
                
                app_logger.debug(f"Making POST request to {url} (attempt {attempt}/{max_retries})")
                
                async with self.session.post(url, json=payload, headers=headers) as response:
                    if response.status == 429:
                        retry_after = int(response.headers.get('Retry-After', 60))
                        app_logger.warning(f"Rate limited. Waiting {retry_after} seconds...")
                        await asyncio.sleep(retry_after)
                        raise Exception("Rate limit exceeded")
                    
                    if response.status >= 400:
                        error_text = await response.text()
                        app_logger.error(f"Polymarket CLOB API error {response.status}: {error_text}")
                        app_logger.error(f"Request URL: {url}")
                        if 'data' in locals():
                            app_logger.error(f"Request payload: {data}")
                        if 'params' in locals():
                            app_logger.error(f"Request params: {params}")
                        app_logger.error(f"Request headers: {headers}")
                        raise Exception(f"HTTP {response.status}: {error_text}")
                    
                    result = await response.json()
                    app_logger.debug(f"POST request successful")
                    return result
                    
            except Exception as e:
                last_exception = e
                app_logger.warning(f"POST request attempt {attempt}/{max_retries} failed: {e}")
                
                if attempt < max_retries:
                    wait_time = 2 * attempt  # Progressive backoff: 2s, 4s
                    app_logger.info(f"Waiting {wait_time} seconds before retry...")
                    await asyncio.sleep(wait_time)
                else:
                    app_logger.error(f"All {max_retries} POST request attempts failed")
                    raise last_exception

    async def _convert_markets_with_batch_pricing(self, markets_data: List[Dict[str, Any]]) -> List[StandardizedMarket]:
        """Convert multiple markets with batch pricing to avoid multiple API calls."""
        if not markets_data:
            return []
        
        app_logger.debug(f"Converting {len(markets_data)} markets with batch pricing")
        
        # Step 1: Collect all token IDs from all markets
        all_token_ids = []
        market_token_mapping = {}  # Map market_id -> list of token_ids
        
        for market_raw in markets_data:
            try:
                condition_id = market_raw.get('condition_id', '')
                if not condition_id:
                    continue
                    
                tokens = market_raw.get('tokens', [])
                market_token_ids = []
                
                app_logger.info(f"Market {condition_id} has {len(tokens)} tokens")
                
                for token in tokens:
                    token_id = token.get('token_id')
                    app_logger.info(f"Token data: {token}")
                    app_logger.info(f"Extracted token_id: {token_id} (type: {type(token_id)})")
                    
                    if token_id:
                        all_token_ids.append(token_id)
                        market_token_ids.append(token_id)
                
                if market_token_ids:
                    market_token_mapping[condition_id] = market_token_ids
                    app_logger.debug(f"Market {condition_id} token IDs: {market_token_ids}")
                    
            except Exception as e:
                app_logger.warning(f"Error collecting tokens from market: {e}")
                continue
        
        # Step 2: Make ONE batch price request for all tokens
        batch_prices = {}
        if all_token_ids:
            app_logger.debug(f"Making batch price request for {len(all_token_ids)} tokens")
            try:
                batch_prices = await self.get_market_prices(all_token_ids) or {}
                app_logger.debug(f"Received batch prices for {len(batch_prices)} tokens")
            except Exception as e:
                app_logger.error(f"Batch price request failed: {e}")
                app_logger.warning("Continuing without price data - will process markets without pricing")
        
        # Step 3: Convert each market using the batch price data
        converted_markets = []
        for market_raw in markets_data:
            try:
                condition_id = market_raw.get('condition_id', '')
                market_token_ids = market_token_mapping.get(condition_id, [])
                
                # Extract relevant prices for this market
                market_prices = {}
                for token_id in market_token_ids:
                    if str(token_id) in batch_prices:
                        market_prices[str(token_id)] = batch_prices[str(token_id)]
                    elif token_id in batch_prices:
                        market_prices[token_id] = batch_prices[token_id]
                
                # Convert market with its specific price data
                standardized_market = await self._convert_to_standardized_market_with_prices(market_raw, market_prices)
                if standardized_market:
                    converted_markets.append(standardized_market)
                    
            except Exception as e:
                market_id = market_raw.get('condition_id', 'unknown')
                app_logger.warning(f"Failed to convert Polymarket market {market_id}: {e}")
                continue
        
        return converted_markets

    # VPN connection now handled at startup - no longer needed during execution

    async def get_markets(self, limit: Optional[int] = None) -> List[StandardizedMarket]:
        """Get all available active markets from Polymarket using CLOB API."""
        try:
            app_logger.info("Fetching active markets from Polymarket CLOB API...")
            
            all_markets = []
            next_cursor = ""
            page_count = 0
            
            while True:
                page_count += 1
                app_logger.debug(f"Fetching page {page_count} from Polymarket CLOB API...")
                
                params = {}
                if next_cursor:
                    params['next_cursor'] = next_cursor
                
                # Get markets using CLOB API
                markets_response = await self._make_request('markets', params=params)
                
                if not markets_response:
                    app_logger.warning("No market data received from Polymarket CLOB API")
                    break
                
                markets_data = markets_response.get('data', [])
                next_cursor = markets_response.get('next_cursor', '')
                
                if not markets_data:
                    break
                
                # Filter for active markets and convert to standardized format
                markets_to_process = []
                for market_raw in markets_data:
                    try:
                        # Only include active markets
                        if market_raw.get('active', False) and not market_raw.get('closed', True):
                            markets_to_process.append(market_raw)
                    except Exception as e:
                        market_id = market_raw.get('condition_id', 'unknown')
                        app_logger.warning(f"Failed to filter Polymarket market {market_id}: {e}")
                        continue
                
                # Process markets with batch pricing
                if markets_to_process:
                    converted_markets = await self._convert_markets_with_batch_pricing(markets_to_process)
                    all_markets.extend(converted_markets)
                
                app_logger.debug(f"Page {page_count}: Processed {len(markets_data)} markets")
                
                # Check if we've reached the end or hit limit
                if next_cursor == "LTE=" or not next_cursor:  # LTE= means end
                    break
                if limit and len(all_markets) >= limit:
                    all_markets = all_markets[:limit]
                    break
            
            app_logger.info(f"Successfully fetched {len(all_markets)} active Polymarket markets")
            return all_markets
            
        except Exception as e:
            app_logger.error(f"Error fetching Polymarket markets: {e}")
            return []
    
    async def get_markets_by_keyword(self, keyword: str) -> List[StandardizedMarket]:
        """Get all active markets containing the specified keyword using CLOB API."""
        try:
            app_logger.info(f"Fetching all active Polymarket markets with keyword: '{keyword}' using CLOB API")
            
            all_markets = []
            next_cursor = ""
            page_count = 0
            
            while True:
                page_count += 1
                app_logger.debug(f"Fetching page {page_count} from Polymarket CLOB API...")
                
                params = {}
                if next_cursor:
                    params['next_cursor'] = next_cursor
                
                # Get markets using CLOB API
                markets_response = await self._make_request('markets', params=params)
                
                if not markets_response:
                    app_logger.warning("No market data received from Polymarket CLOB API")
                    break
                
                markets_data = markets_response.get('data', [])
                next_cursor = markets_response.get('next_cursor', '')
                
                if not markets_data:
                    break
                
                # Filter markets by keyword and convert to standardized format
                page_filtered_count = 0
                markets_to_process = []
                for market_raw in markets_data:
                    try:
                        # Only include active markets
                        if not (market_raw.get('active', False) and not market_raw.get('closed', True)):
                            continue
                        
                        # Check if keyword is in question (title/description filtering)
                        question = market_raw.get('question', '').lower()
                        
                        if keyword.lower() in question:
                            markets_to_process.append(market_raw)
                            page_filtered_count += 1
                                
                    except Exception as e:
                        market_id = market_raw.get('condition_id', 'unknown')
                        app_logger.warning(f"Failed to filter Polymarket market {market_id}: {e}")
                        continue
                
                # Process markets with batch pricing
                if markets_to_process:
                    converted_markets = await self._convert_markets_with_batch_pricing(markets_to_process)
                    all_markets.extend(converted_markets)
                
                app_logger.debug(f"Page {page_count}: Found {page_filtered_count} markets with keyword '{keyword}' out of {len(markets_data)} total markets")
                
                # Check if we've reached the end
                if next_cursor == "LTE=" or not next_cursor:  # LTE= means end
                    break
            
            app_logger.info(f"Found {len(all_markets)} total active Polymarket markets containing keyword '{keyword}' across {page_count} pages")
            return all_markets
            
        except Exception as e:
            app_logger.error(f"Error fetching Polymarket markets by keyword '{keyword}': {e}")
            return []
    
    async def get_market_details(self, market_id: str) -> Optional[StandardizedMarket]:
        """Get detailed information for a specific Polymarket market using CLOB API."""
        try:
            app_logger.debug(f"Fetching Polymarket market details for {market_id}")
            
            # Get market details using CLOB API
            market_data = await self._make_request(f'markets/{market_id}')
            
            if not market_data:
                app_logger.warning(f"No market data found for Polymarket market {market_id}")
                return None
            
            # Extract token IDs to fetch prices
            tokens = market_data.get('tokens', [])
            token_ids = []
            for token in tokens:
                token_id = token.get('token_id')
                if token_id:
                    token_ids.append(token_id)
            
            # Fetch prices if we have token IDs
            market_prices = {}
            if token_ids:
                app_logger.debug(f"Fetching prices for {len(token_ids)} tokens")
                prices_data = await self.get_market_prices(token_ids)
                if prices_data:
                    market_prices = prices_data
            
            return await self._convert_to_standardized_market_with_prices(market_data, market_prices)
            
        except Exception as e:
            app_logger.error(f"Error fetching Polymarket market {market_id}: {e}")
            return None

    async def _convert_to_standardized_market_with_prices(self, polymarket_data: Dict[str, Any], prices_data: Dict[str, Any]) -> Optional[StandardizedMarket]:
        """Convert Polymarket CLOB data to standardized format with pre-fetched pricing data."""
        try:
            app_logger.debug(f"Converting Polymarket CLOB data with keys: {list(polymarket_data.keys())}")
            
            # Extract basic market information from CLOB API Market object structure
            condition_id = polymarket_data.get('condition_id', '')
            question_id = polymarket_data.get('question_id', '')
            question = polymarket_data.get('question', '')
            market_slug = polymarket_data.get('market_slug', '')
            category = polymarket_data.get('category', 'General')
            
            if not condition_id or not question:
                app_logger.warning("Missing required condition_id or question in Polymarket data")
                return None
            
            # Map market status based on CLOB API fields
            active = polymarket_data.get('active', True)
            closed = polymarket_data.get('closed', False)
            
            if closed or not active:
                status = MarketStatus.CLOSED
            else:
                status = MarketStatus.ACTIVE
            
            # Parse dates from CLOB API
            created_at = None
            close_date = None
            resolution_date = None
            
            # Parse end_date_iso
            if polymarket_data.get('end_date_iso'):
                try:
                    close_date = datetime.fromisoformat(polymarket_data['end_date_iso'].replace('Z', '+00:00'))
                except ValueError:
                    pass
            
            # Parse game_start_time if available
            game_start_time = None
            if polymarket_data.get('game_start_time'):
                try:
                    game_start_time = datetime.fromisoformat(polymarket_data['game_start_time'].replace('Z', '+00:00'))
                except ValueError:
                    pass
            
            # Extract Token information and apply pricing
            tokens = polymarket_data.get('tokens', [])
            outcomes = []
            
            app_logger.debug(f"Processing {len(tokens)} tokens for market {condition_id}")
            
            for token in tokens:
                token_id = token.get('token_id')
                outcome_name = token.get('outcome', 'Unknown')
                
                if token_id:
                    outcome = MarketOutcome(
                        id=f"{condition_id}_{outcome_name.lower().replace(' ', '_')}",
                        name=outcome_name,
                        yes_price=None,
                        volume=None,
                        is_winner=None
                    )
                    
                    # Apply pricing data if available
                    if prices_data and (str(token_id) in prices_data or token_id in prices_data):
                        token_prices = prices_data.get(str(token_id)) or prices_data.get(token_id, {})
                        
                        buy_price = token_prices.get("BUY")
                        sell_price = token_prices.get("SELL")
                        
                        if buy_price is not None:
                            try:
                                price_value = float(buy_price)
                                # Assign to yes_price for "Yes" outcomes, no_price for others
                                if "yes" in outcome.name.lower():
                                    outcome.yes_price = price_value
                                else:
                                    outcome.no_price = price_value
                                
                                # Also set bid/ask if we have both prices
                                if sell_price is not None:
                                    outcome.bid = float(buy_price)
                                    outcome.ask = float(sell_price)
                                    
                                app_logger.debug(f"Set price for {outcome.name}: {price_value}")
                            except (ValueError, TypeError) as e:
                                app_logger.warning(f"Invalid price data for token {token_id}: {buy_price} - {e}")
                    
                    outcomes.append(outcome)
                    app_logger.debug(f"Added outcome: {outcome_name} with token_id: {token_id}")
            
            # Extract Rewards information if available
            rewards = polymarket_data.get('rewards', {})
            rewards_info = {}
            if rewards:
                rewards_info = {
                    'min_size': rewards.get('min_size'),
                    'max_spread': rewards.get('max_spread'),
                    'event_start_date': rewards.get('event_start_date'),
                    'event_end_date': rewards.get('event_end_date'),
                    'in_game_multiplier': rewards.get('in_game_multiplier'),
                    'reward_epoch': rewards.get('reward_epoch')
                }
            
            # Extract additional CLOB-specific fields
            minimum_order_size = polymarket_data.get('minimum_order_size')
            minimum_tick_size = polymarket_data.get('minimum_tick_size')
            seconds_delay = polymarket_data.get('seconds_delay', 0)
            fpmm = polymarket_data.get('fpmm')  # Fixed Product Market Maker address
            
            # Create simplified question for LLM matching
            primary_question = self._extract_primary_question(question, question)
            
            # Build source URL with token ID parameter
            # Get the first token ID for the URL parameter
            first_token_id = None
            if tokens and len(tokens) > 0:
                first_token_id = tokens[0].get('token_id')
            
            if market_slug:
                base_url = f"https://polymarket.com/event/{market_slug}"
            else:
                base_url = f"https://polymarket.com/event/{condition_id}"
            
            # Add token ID as query parameter if available
            if first_token_id:
                source_url = f"{base_url}?tid={first_token_id}"
            else:
                source_url = base_url
            
            # Prepare enhanced raw_data with parsed information
            enhanced_raw_data = {
                **polymarket_data,
                'parsed_rewards': rewards_info,
                'parsed_game_start_time': game_start_time,
                'token_count': len(tokens),
                'minimum_order_size': minimum_order_size,
                'minimum_tick_size': minimum_tick_size,
                'seconds_delay': seconds_delay,
                'fpmm_address': fpmm
            }
            
            standardized_market = StandardizedMarket(
                id=condition_id,
                platform=Platform.POLYMARKET,
                title=question,
                description=question,  # CLOB API uses question for both
                market_type=MarketType.BINARY,  # Polymarket is primarily binary
                status=status,
                category=category,
                subcategory=market_slug,
                created_at=created_at,
                close_date=close_date,
                resolution_date=resolution_date,
                outcomes=outcomes,
                total_volume=None,  # CLOB API doesn't provide this directly in market data
                total_liquidity=None,  # CLOB API doesn't provide this directly in market data
                tags=[],  # CLOB API doesn't provide tags directly
                source_url=source_url,
                raw_data=enhanced_raw_data,
                primary_question=primary_question
            )
            
            app_logger.debug(f"Successfully converted market {condition_id} with {len(outcomes)} outcomes")
            return standardized_market
            
        except Exception as e:
            app_logger.error(f"Error converting Polymarket CLOB data: {e}")
            app_logger.debug(f"Polymarket data that failed: {polymarket_data}")
            return None

    async def get_market_prices(self, token_ids: List[str]) -> Optional[Dict[str, Any]]:
        """Get prices for specific token IDs using CLOB API with chunking for large requests."""
        if not token_ids:
            return {}
        
        try:
            # DEBUG: Log the first few token IDs to see what we're working with
            app_logger.debug(f"get_market_prices called with {len(token_ids)} token IDs")
            app_logger.debug(f"First 5 token IDs: {token_ids[:5]}")
            app_logger.debug(f"Token ID types: {[type(tid) for tid in token_ids[:3]]}")
            
            # Log token IDs for debugging
            app_logger.info(f"First 3 token IDs: {token_ids[:3] if len(token_ids) > 3 else token_ids}")
            app_logger.info(f"Token ID types: {[type(tid) for tid in token_ids[:3]]}")
            
            # Chunk large requests to avoid API limits
            chunk_size = 10  # Reduce chunk size for testing
            all_prices = {}
            
            for i in range(0, len(token_ids), chunk_size):
                chunk = token_ids[i:i + chunk_size]
                app_logger.debug(f"Processing price chunk {i//chunk_size + 1}: {len(chunk)} tokens")
                
                            # Prepare params for price request - API expects direct array, not wrapped in "params"
            # The payload should be: [BookParams] (direct array)
            # BookParams: {"token_id": string, "side": "BUY" | "SELL"}
            payload = []
            for token_id in chunk:
                payload.append({"token_id": str(token_id), "side": "BUY"})
                payload.append({"token_id": str(token_id), "side": "SELL"})
                
                app_logger.debug(f"Requesting prices for {len(chunk)} tokens")
                app_logger.debug(f"Sample token IDs: {chunk[:3] if len(chunk) > 3 else chunk}")
                app_logger.debug(f"Total params in payload: {len(payload)}")
                
                # DEBUG: Log the actual payload being sent
                app_logger.debug(f"FULL PAYLOAD: {payload}")
                if len(payload) > 0:
                    app_logger.debug(f"First param sample: {payload[0]}")
                    app_logger.debug(f"Last param sample: {payload[-1]}")
                
                # Make POST request to get prices
                # Response format: {[asset_id]: {[side]: price}}
                try:
                    prices_response = await self._make_post_request('prices', payload)
                    
                    if not prices_response:
                        app_logger.warning(f"No price response received for chunk {i//chunk_size + 1}")
                        continue
                    
                    app_logger.debug(f"Raw prices response for chunk: {type(prices_response)} with {len(prices_response) if isinstance(prices_response, dict) else 'unknown'} items")
                    
                    # Handle the response format from the API
                    if isinstance(prices_response, dict):
                        for token_id in chunk:
                            token_id_str = str(token_id)
                            if token_id_str in prices_response:
                                all_prices[token_id_str] = prices_response[token_id_str]
                            elif token_id in prices_response:
                                all_prices[token_id] = prices_response[token_id]
                    
                    app_logger.debug(f"Processed prices for chunk {i//chunk_size + 1}: {len(prices_response) if isinstance(prices_response, dict) else 0} tokens")
                    
                except Exception as chunk_error:
                    app_logger.error(f"Error fetching prices for chunk {i//chunk_size + 1}: {chunk_error}")
                    # Continue with next chunk instead of failing completely
                    continue
                
                # Small delay between chunks to be respectful to the API
                if i + chunk_size < len(token_ids):
                    await asyncio.sleep(0.1)
            
            app_logger.debug(f"Total processed prices: {len(all_prices)} tokens")
            return all_prices if all_prices else None
            
        except Exception as e:
            app_logger.error(f"Error in batch price fetching: {e}")
            return None
    
    def _extract_primary_question(self, title: str, description: str) -> str:
        """Extract a simplified question from title and description for LLM matching."""
        question = title
        
        # Clean up common Polymarket formatting
        question = question.replace("?", "").strip()
        
        # Remove common prefixes
        prefixes_to_remove = ["Will ", "Does ", "Did ", "Is ", "Are ", "Has ", "Have "]
        for prefix in prefixes_to_remove:
            if question.startswith(prefix):
                question = question[len(prefix):]
                break
        
        # Ensure reasonable length
        if len(question) > 200:
            question = question[:200] + "..."
        
        return question

    async def health_check(self) -> bool:
        """Check if Polymarket CLOB API is accessible."""
        try:
            # Try to get a simple response from the CLOB API
            response = await self._make_request('markets')
            return response is not None
            
        except Exception as e:
            app_logger.error(f"Polymarket health check failed: {e}")
            return False
    
    def set_vpn_required(self, required: bool):
        """Set whether VPN is required (useful for testing)."""
        self.vpn_required = required
    
 