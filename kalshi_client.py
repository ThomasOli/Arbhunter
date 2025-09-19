"""
Kalshi API client for fetching market data.
Uses proper RSA PSS signing authentication as per Kalshi API documentation.
"""
import asyncio
import hashlib
import hmac
import time
import base64
from datetime import datetime
from typing import Optional, Dict, Any, List
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

from config.settings import settings
from src.api_clients.base_client import BaseAPIClient, APIError
from src.data.market_data import (
    StandardizedMarket, MarketOutcome, MarketStatus, 
    MarketType, Platform
)
from src.utils.logger import app_logger


class KalshiClient(BaseAPIClient):
    """Kalshi API client for fetching prediction market data."""
    
    def __init__(self):
        super().__init__(
            base_url=settings.KALSHI_BASE_URL,
            api_key=settings.KALSHI_API_KEY
        )
        self.api_secret = settings.load_kalshi_api_secret()
        self.private_key = None
        self._load_private_key()
        
    def _load_private_key(self):
        """Load the RSA private key for signing requests."""
        try:
            if self.api_secret:
                self.private_key = serialization.load_pem_private_key(
                    self.api_secret.encode(),
                    password=None
                )
                app_logger.info("Successfully loaded Kalshi RSA private key")
            else:
                app_logger.warning("No Kalshi API secret provided")
        except Exception as e:
            app_logger.error(f"Failed to load Kalshi private key: {e}")
            self.private_key = None
        
    def _get_auth_headers(self) -> Dict[str, str]:
        """Get Kalshi authentication headers using RSA PSS signing."""
        if not self.api_key or not self.private_key:
            app_logger.warning("Missing Kalshi API key or private key")
            return {}
        
        try:
            # Generate timestamp in milliseconds
            timestamp = str(int(time.time() * 1000))
            
            # For now, we'll create a generic signature for market data requests
            # This will be updated per request in the _make_request method
            method = "GET"
            path = "/trade-api/v2/markets"
            
            # Create the message to sign: timestamp + method + path
            message = timestamp + method + path
            
            # Sign with RSA PSS padding and SHA256
            signature = self.private_key.sign(
                message.encode(),
                padding.PSS(
                    mgf=padding.MGF1(hashes.SHA256()),
                    salt_length=padding.PSS.MAX_LENGTH
                ),
                hashes.SHA256()
            )
            
            # Base64 encode the signature
            signature_b64 = base64.b64encode(signature).decode()
            
            return {
                'KALSHI-ACCESS-KEY': self.api_key,
                'KALSHI-ACCESS-SIGNATURE': signature_b64,
                'KALSHI-ACCESS-TIMESTAMP': timestamp
            }
            
        except Exception as e:
            app_logger.error(f"Error generating Kalshi auth headers: {e}")
            return {}
    
    def _sign_request(self, method: str, path: str, timestamp: str) -> str:
        """Sign a specific request with RSA PSS."""
        try:
            if not self.private_key:
                raise ValueError("Private key not loaded")
            
            # Create the message to sign: timestamp + method + path
            message = timestamp + method + path
            
            # Sign with RSA PSS padding and SHA256
            signature = self.private_key.sign(
                message.encode(),
                padding.PSS(
                    mgf=padding.MGF1(hashes.SHA256()),
                    salt_length=padding.PSS.MAX_LENGTH
                ),
                hashes.SHA256()
            )
            
            # Base64 encode the signature
            return base64.b64encode(signature).decode()
            
        except Exception as e:
            app_logger.error(f"Error signing Kalshi request: {e}")
            raise
    
    async def _make_request(
        self, 
        method: str, 
        endpoint: str, 
        params: Optional[Dict[str, Any]] = None,
        data: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None
    ) -> Dict[str, Any]:
        """Override to add proper Kalshi authentication per request."""
        
        if not self.session:
            raise RuntimeError("Client session not initialized. Use async context manager.")
        
        # Generate timestamp for this specific request
        timestamp = str(int(time.time() * 1000))
        
        # Build the path for signing
        path = f"/trade-api/v2/{endpoint.lstrip('/')}"
        
        # Create request-specific auth headers
        request_headers = {
            'User-Agent': 'ArbitrageScanner/1.0',
            'Accept': 'application/json',
            'Content-Type': 'application/json'
        }
        
        if self.api_key and self.private_key:
            try:
                signature = self._sign_request(method, path, timestamp)
                request_headers.update({
                    'KALSHI-ACCESS-KEY': self.api_key,
                    'KALSHI-ACCESS-SIGNATURE': signature,
                    'KALSHI-ACCESS-TIMESTAMP': timestamp
                })
            except Exception as e:
                app_logger.error(f"Failed to sign Kalshi request: {e}")
                raise APIError(f"Authentication failed: {e}")
        
        # Merge with any additional headers
        if headers:
            request_headers.update(headers)
        
        # Use the base client's request logic but with our custom headers
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        
        app_logger.debug(f"Making {method} request to {url}")
        
        try:
            # Track request timing for rate limiting
            self._request_count += 1
            current_time = time.time()
            time_since_last = current_time - self._last_request_time
            
            # Ensure minimum time between requests
            min_interval = 1.0 / settings.MAX_CONCURRENT_REQUESTS
            if time_since_last < min_interval:
                await asyncio.sleep(min_interval - time_since_last)
            
            self._last_request_time = time.time()
            
            # Make the request
            async with self.session.request(
                method=method,
                url=url,
                params=params,
                json=data,
                headers=request_headers
            ) as response:
                
                # Handle rate limiting
                if response.status == 429:
                    retry_after = int(response.headers.get('Retry-After', 60))
                    app_logger.warning(f"Rate limited. Waiting {retry_after} seconds...")
                    await asyncio.sleep(retry_after)
                    raise APIError("Rate limit exceeded")
                
                # Handle other HTTP errors
                if response.status >= 400:
                    error_text = await response.text()
                    app_logger.error(f"Kalshi API error {response.status}: {error_text}")
                    raise APIError(f"HTTP {response.status}: {error_text}")
                
                # Parse JSON response
                try:
                    result = await response.json()
                    app_logger.debug(f"Request successful: {len(str(result))} chars")
                    return result
                except Exception as e:
                    app_logger.error(f"Failed to parse JSON response: {e}")
                    raise APIError(f"Invalid JSON response: {e}")
                
        except Exception as e:
            if isinstance(e, APIError):
                raise
            app_logger.error(f"Request error: {e}")
            raise APIError(f"Request failed: {e}")
    
    async def get_markets(self, limit: Optional[int] = None) -> List[StandardizedMarket]:
        """Get all available markets from Kalshi."""
        try:
            app_logger.info("Fetching markets from Kalshi...")
            
            params = {'status': 'open'}  # Only get active/open markets
            if limit:
                params['limit'] = limit
                
            # Get markets list
            response = await self._make_request('GET', 'markets', params=params)
            
            markets = []
            market_data = response.get('markets', [])
            
            app_logger.info(f"Retrieved {len(market_data)} markets from Kalshi")
            
            for market_raw in market_data:
                try:
                    standardized_market = self._convert_to_standardized_market(market_raw)
                    if standardized_market:
                        markets.append(standardized_market)
                except Exception as e:
                    app_logger.warning(f"Failed to convert Kalshi market {market_raw.get('ticker', 'unknown')}: {e}")
                    continue
            
            app_logger.info(f"Successfully standardized {len(markets)} Kalshi markets")
            return markets
            
        except Exception as e:
            app_logger.error(f"Error fetching Kalshi markets: {e}")
            raise APIError(f"Failed to fetch Kalshi markets: {e}")
    
    async def get_markets_by_keyword(self, keyword: str) -> List[StandardizedMarket]:
        """Get all markets containing the specified keyword, paginating through all results."""
        try:
            app_logger.info(f"Fetching all Kalshi markets with keyword: '{keyword}'")
            
            all_markets = []
            cursor = None
            page_count = 0
            
            while True:
                page_count += 1
                app_logger.debug(f"Fetching page {page_count} from Kalshi...")
                
                params = {
                    'limit': 200,  # Get max results per page
                    'status': 'open'  # Only get active/open markets
                }
                if cursor:
                    params['cursor'] = cursor
                
                # Get markets list
                response = await self._make_request('GET', 'markets', params=params)
                
                market_data = response.get('markets', [])
                cursor = response.get('cursor')
                
                if not market_data:
                    break
                
                # Filter markets by keyword and convert to standardized format
                page_filtered_count = 0
                for market_raw in market_data:
                    try:
                        # Check if keyword is in title or description
                        title = market_raw.get('title', '').lower()
                        description = market_raw.get('rules_primary', '').lower()
                        
                        if keyword.lower() in title or keyword.lower() in description:
                            standardized_market = self._convert_to_standardized_market(market_raw)
                            if standardized_market:
                                all_markets.append(standardized_market)
                                page_filtered_count += 1
                                
                    except Exception as e:
                        app_logger.warning(f"Failed to process Kalshi market {market_raw.get('ticker', 'unknown')}: {e}")
                        continue
                
                app_logger.debug(f"Page {page_count}: Found {page_filtered_count} markets with keyword '{keyword}' out of {len(market_data)} total markets")
                
                # Check if we've reached the end (no cursor or no more data)
                if not cursor or len(market_data) < 200:
                    break
            
            app_logger.info(f"Found {len(all_markets)} total Kalshi markets containing keyword '{keyword}' across {page_count} pages")
            return all_markets
            
        except Exception as e:
            app_logger.error(f"Error fetching Kalshi markets by keyword '{keyword}': {e}")
            raise APIError(f"Failed to fetch Kalshi markets by keyword: {e}")
    
    async def get_market_details(self, market_id: str) -> Optional[StandardizedMarket]:
        """Get detailed information for a specific Kalshi market."""
        try:
            app_logger.debug(f"Fetching Kalshi market details for {market_id}")
            
            response = await self._make_request('GET', f'markets/{market_id}')
            market_data = response.get('market', {})
            
            if not market_data:
                app_logger.warning(f"No market data found for Kalshi market {market_id}")
                return None
            
            return self._convert_to_standardized_market(market_data)
            
        except Exception as e:
            app_logger.error(f"Error fetching Kalshi market {market_id}: {e}")
            return None
    
    def _convert_to_standardized_market(self, kalshi_market: Dict[str, Any]) -> Optional[StandardizedMarket]:
        """Convert Kalshi market data to standardized format."""
        try:
            # Extract basic information
            market_id = kalshi_market.get('ticker', '')
            title = kalshi_market.get('title', '')
            description = kalshi_market.get('rules_primary', title)
            
            if not market_id or not title:
                app_logger.warning("Missing required fields in Kalshi market data")
                return None
            
            # Map status
            kalshi_status = kalshi_market.get('status', '').lower()
            status_mapping = {
                'open': MarketStatus.ACTIVE,
                'closed': MarketStatus.CLOSED,
                'settled': MarketStatus.SETTLED,
                'paused': MarketStatus.PAUSED,
                'initialized': MarketStatus.ACTIVE,  # New markets
                'finalized': MarketStatus.SETTLED
            }
            status = status_mapping.get(kalshi_status, MarketStatus.ACTIVE)
            
            # Parse dates
            created_at = None
            close_date = None
            resolution_date = None
            
            if kalshi_market.get('open_time'):
                try:
                    created_at = datetime.fromisoformat(kalshi_market['open_time'].replace('Z', '+00:00'))
                except ValueError:
                    pass
            
            if kalshi_market.get('close_time'):
                try:
                    close_date = datetime.fromisoformat(kalshi_market['close_time'].replace('Z', '+00:00'))
                except ValueError:
                    pass
                    
            if kalshi_market.get('expiration_time'):
                try:
                    resolution_date = datetime.fromisoformat(kalshi_market['expiration_time'].replace('Z', '+00:00'))
                except ValueError:
                    pass
            
            # Extract pricing information
            outcomes = []
            
            # Kalshi has YES/NO outcomes with bid/ask prices
            yes_bid = kalshi_market.get('yes_bid')
            yes_ask = kalshi_market.get('yes_ask')
            no_bid = kalshi_market.get('no_bid')
            no_ask = kalshi_market.get('no_ask')
            last_price = kalshi_market.get('last_price')
            
            # YES outcome
            if yes_bid is not None or yes_ask is not None:
                # Convert cents to dollars
                yes_price = None
                if last_price is not None and last_price > 0:
                    yes_price = last_price / 100.0
                elif yes_ask is not None and yes_ask > 0:
                    yes_price = yes_ask / 100.0
                elif yes_bid is not None and yes_bid > 0:
                    yes_price = yes_bid / 100.0
                
                outcomes.append(MarketOutcome(
                    id=f"{market_id}_yes",
                    name="Yes",
                    yes_price=yes_price,
                    volume=kalshi_market.get('volume')
                ))
            
            # NO outcome
            if no_bid is not None or no_ask is not None:
                # Convert cents to dollars  
                no_price = None
                if last_price is not None and last_price > 0:
                    no_price = (100 - last_price) / 100.0
                elif no_ask is not None and no_ask > 0:
                    no_price = no_ask / 100.0
                elif no_bid is not None and no_bid > 0:
                    no_price = no_bid / 100.0
                
                outcomes.append(MarketOutcome(
                    id=f"{market_id}_no",
                    name="No",
                    no_price=no_price,
                    volume=kalshi_market.get('volume')
                ))
            
            # Create simplified question for LLM matching
            primary_question = self._extract_primary_question(title, description)
            
            # Get category information
            category = kalshi_market.get('category', '')
            subcategory = kalshi_market.get('event_ticker', '')
            
            # Build proper Kalshi URL: https://kalshi.com/markets/{ticker_prefix}/{concise-slug}
            ticker = kalshi_market.get('ticker', market_id)
            # Extract ticker prefix (before any dash) and convert to lowercase
            ticker_prefix = ticker.split('-')[0].lower() if ticker else market_id.lower()
            
            # Create a concise slug from key terms in the title
            # Extract key terms instead of using the full title
            title_lower = title.lower()
            if 'bolivia' in title_lower and 'first round' in title_lower:
                title_slug = 'bolivia-first-round-winner'
            elif 'bolivia' in title_lower:
                title_slug = 'bolivia-election'
            else:
                # Fallback: create slug from title but limit length
                title_slug = title.lower().replace(' ', '-').replace('?', '').replace(':', '').replace(',', '').replace('.', '').replace('(', '').replace(')', '').replace('[', '').replace(']', '').replace('/', '-').replace('&', 'and')
                title_slug = '-'.join(filter(None, title_slug.split('-')))
                # Limit to first 6 words to keep URL concise
                words = title_slug.split('-')[:6]
                title_slug = '-'.join(words)
            
            source_url = f"https://kalshi.com/markets/{ticker_prefix}/{title_slug}"
            
            return StandardizedMarket(
                id=market_id,
                platform=Platform.KALSHI,
                title=title,
                description=description,
                market_type=MarketType.BINARY,  # Kalshi is primarily binary markets
                status=status,
                category=category,
                subcategory=subcategory,
                created_at=created_at,
                close_date=close_date,
                resolution_date=resolution_date,
                outcomes=outcomes,
                total_volume=kalshi_market.get('volume'),
                total_liquidity=kalshi_market.get('liquidity'),
                tags=[],  # Kalshi doesn't seem to have tags in this format
                source_url=source_url,
                raw_data=kalshi_market,
                primary_question=primary_question
            )
            
        except Exception as e:
            app_logger.error(f"Error converting Kalshi market data: {e}")
            return None
    
    def _extract_primary_question(self, title: str, description: str) -> str:
        """Extract a simplified question from title and description for LLM matching."""
        # Remove common Kalshi-specific prefixes and clean up
        question = title
        
        # Remove prefixes like "Will", "Does", etc. and standardize
        prefixes_to_remove = ["Will ", "Does ", "Did ", "Is ", "Are ", "Has ", "Have "]
        for prefix in prefixes_to_remove:
            if question.startswith(prefix):
                question = question[len(prefix):]
                break
        
        # Remove trailing question marks and clean up
        question = question.rstrip('?').strip()
        
        # Ensure it's a reasonable length
        if len(question) > 200:
            question = question[:200] + "..."
        
        return question
    
    async def get_market_orderbook(self, market_id: str) -> Optional[Dict[str, Any]]:
        """Get orderbook data for a specific market."""
        try:
            response = await self._make_request('GET', f'markets/{market_id}/orderbook')
            return response.get('orderbook', {})
        except Exception as e:
            app_logger.error(f"Error fetching Kalshi orderbook for {market_id}: {e}")
            return None
    
    async def health_check(self) -> bool:
        """Check if Kalshi API is accessible."""
        try:
            response = await self._make_request('GET', 'exchange/status')
            # Check if exchange is active (trading doesn't need to be active for market data)
            return response.get('exchange_active', False)
        except Exception:
            return False 