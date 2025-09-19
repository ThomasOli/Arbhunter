
"""
scanner_demo.py
A tiny async runner that:
  - Reads a --keyword (e.g., "Biden")
  - Fetches markets from Kalshi and Polymarket filtered by that keyword
  - Shows a few results from each
  - Prints naive arbitrage candidates when |yes_price difference| >= 3%
Usage:
  python scanner_demo.py --keyword "Biden"
"""
import argparse
import asyncio
from typing import Optional, List

from src.utils.logger import app_logger
from config.settings import settings
from kalshi_client import KalshiClient
from polymarket_client import PolymarketClient
from src.data.market_data import StandardizedMarket

def _best_yes_price(m: StandardizedMarket) -> Optional[float]:
    # Try yes_price, then last_trade_price, then convert from no_price if needed
    for o in m.outcomes:
        if o.yes_price is not None:
            return o.yes_price
        if o.last_trade_price is not None:
            return o.last_trade_price
    for o in m.outcomes:
        if o.no_price is not None:
            return 1.0 - o.no_price
    return None

def _fmt_price(x: Optional[float]) -> str:
    return f"{x:.3f}" if isinstance(x, (int, float)) and x is not None else "—"

def _short(s: str, n: int = 80) -> str:
    return s if len(s) <= n else s[:n-1] + "…"

async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--keyword", "-k", type=str, default="Biden", help="Keyword to filter markets by")
    parser.add_argument("--min-spread", type=float, default=0.03, help="Minimum abs(price_a - price_b) to print")
    parser.add_argument("--limit", type=int, default=50, help="Fetch up to N per exchange (after filter)")
    args = parser.parse_args()

    app_logger.info(f"Keyword: {args.keyword!r}, min_spread={args.min_spread:.3f}")

    kalshi_markets: List[StandardizedMarket] = []
    poly_markets: List[StandardizedMarket] = []

    # Init clients
    kalshi = KalshiClient()
    poly = PolymarketClient()
    try:
        poly.set_vpn_required(settings.POLYMARKET_VPN_REQUIRED)  # type: ignore[attr-defined]
    except Exception:
        pass

    # Fetch
    async with kalshi as kc, poly as pc:
        try:
            kalshi_markets = await kc.get_markets_by_keyword(args.keyword)
        except Exception as e:
            app_logger.error(f"Kalshi error: {e}")
        try:
            poly_markets = await pc.get_markets_by_keyword(args.keyword)
        except Exception as e:
            app_logger.error(f"Polymarket error: {e}")

    # Truncate if needed
    kalshi_markets = kalshi_markets[: args.limit]
    poly_markets = poly_markets[: args.limit]

    # Show samples
    app_logger.info(f"Kalshi matches: {len(kalshi_markets)} | Polymarket matches: {len(poly_markets)}")
    for m in kalshi_markets[:5]:
        app_logger.info(f"[Kalshi] {_short(m.title)}  (id={m.id})  price={_fmt_price(_best_yes_price(m))}")
    for m in poly_markets[:5]:
        app_logger.info(f"[Poly]   {_short(m.title)}  (id={m.id})  price={_fmt_price(_best_yes_price(m))}")

    # Naive cross compare
    print("\n=== Naive cross-exchange spreads (abs yes_price diff >= min_spread) ===\n")
    printed = 0
    for km in kalshi_markets:
        kp = _best_yes_price(km)
        if kp is None:
            continue
        for pm in poly_markets:
            pp = _best_yes_price(pm)
            if pp is None:
                continue
            spread = abs(kp - pp)
            if spread >= args.min_spread:
                printed += 1
                print(f"[{printed:03d}] spread={spread:.3f} | K={_fmt_price(kp)} vs P={_fmt_price(pp)}")
                print(f"      K: {_short(km.title)}  (id={km.id})")
                print(f"      P: {_short(pm.title)}  (id={pm.id})\n")
    if printed == 0:
        print("No candidates at the chosen threshold. Try a different --keyword or lower --min-spread.")

if __name__ == "__main__":
    asyncio.run(main())
