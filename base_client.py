"""
Base API client with common functionality for both Kalshi and Polymarket.
"""
import asyncio
import time
from typing import Optional, Dict, Any, List
from abc import ABC, abstractmethod
import aiohttp
import requests
from ratelimit import limits, sleep_and_retry
from config.settings import settings
from src.utils.logger import app_logger
from src.data.market_data import StandardizedMarket


class RateLimitError(Exception):
    """Raised when rate limit is exceeded."""
    pass


class APIError(Exception):
    """Raised when API returns an error."""
    pass


class BaseAPIClient(ABC):
    """Base class for API clients with common functionality."""
    
    def __init__(self, base_url: str, api_key: Optional[str] = None):
        self.base_url = base_url.rstrip('/')
        self.api_key = api_key
        self.session = None
        self._request_count = 0
        self._last_request_time = 0
        
    async def __aenter__(self):
        """Async context manager entry."""
        self.session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=30),
            headers=self._get_default_headers()
        )
        return self
        
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        if self.session:
            await self.session.close()
    
    def _get_default_headers(self) -> Dict[str, str]:
        """Get default headers for requests."""
        headers = {
            'User-Agent': 'ArbitrageScanner/1.0',
            'Accept': 'application/json',
            'Content-Type': 'application/json'
        }
        
        if self.api_key:
            headers.update(self._get_auth_headers())
            
        return headers
    
    @abstractmethod
    def _get_auth_headers(self) -> Dict[str, str]:
        """Get authentication headers (implemented by subclasses)."""
        pass
    
    @sleep_and_retry
    @limits(calls=settings.MAX_CONCURRENT_REQUESTS, period=1)
    async def _make_request(
        self, 
        method: str, 
        endpoint: str, 
        params: Optional[Dict[str, Any]] = None,
        data: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None
    ) -> Dict[str, Any]:
        """Make an HTTP request with rate limiting and error handling."""
        
        if not self.session:
            raise RuntimeError("Client session not initialized. Use async context manager.")
        
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        
        # Merge headers
        request_headers = self._get_default_headers()
        if headers:
            request_headers.update(headers)
        
        # Log request
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
                    raise RateLimitError("Rate limit exceeded")
                
                # Handle other HTTP errors
                if response.status >= 400:
                    error_text = await response.text()
                    app_logger.error(f"API error {response.status}: {error_text}")
                    raise APIError(f"HTTP {response.status}: {error_text}")
                
                # Parse JSON response
                try:
                    result = await response.json()
                    app_logger.debug(f"Request successful: {len(str(result))} chars")
                    return result
                except Exception as e:
                    app_logger.error(f"Failed to parse JSON response: {e}")
                    raise APIError(f"Invalid JSON response: {e}")
                
        except aiohttp.ClientError as e:
            app_logger.error(f"Client error during request: {e}")
            raise APIError(f"Client error: {e}")
        except asyncio.TimeoutError:
            app_logger.error("Request timed out")
            raise APIError("Request timeout")
        except Exception as e:
            app_logger.error(f"Unexpected error during request: {e}")
            raise APIError(f"Unexpected error: {e}")
    
    async def get(self, endpoint: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Make a GET request."""
        return await self._make_request('GET', endpoint, params=params)
    
    async def post(self, endpoint: str, data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Make a POST request."""
        return await self._make_request('POST', endpoint, data=data)
    
    # Synchronous fallback methods
    def _make_sync_request(
        self,
        method: str,
        endpoint: str,
        params: Optional[Dict[str, Any]] = None,
        data: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Synchronous request fallback."""
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        headers = self._get_default_headers()
        
        try:
            response = requests.request(
                method=method,
                url=url,
                params=params,
                json=data,
                headers=headers,
                timeout=30
            )
            
            response.raise_for_status()
            return response.json()
            
        except requests.exceptions.RequestException as e:
            app_logger.error(f"Sync request error: {e}")
            raise APIError(f"Request error: {e}")
    
    @abstractmethod
    async def get_markets(self, limit: Optional[int] = None) -> List[StandardizedMarket]:
        """Get all available markets (implemented by subclasses)."""
        pass
    
    @abstractmethod
    async def get_market_details(self, market_id: str) -> Optional[StandardizedMarket]:
        """Get detailed information for a specific market (implemented by subclasses)."""
        pass
    
    async def health_check(self) -> bool:
        """Check if the API is healthy."""
        try:
            # Most APIs have a simple endpoint for health checks
            await self.get('/')
            return True
        except Exception as e:
            app_logger.error(f"Health check failed: {e}")
            return False 