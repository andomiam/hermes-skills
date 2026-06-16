#!/usr/bin/env python3
"""kaina24.lt price lookup — reusable module with sync + async support.

Usage:
    from kaina24_lookup import search_products, get_product_price, cached_search
    
    # Sync — quick single product price
    print(get_product_price('/p/amd-ryzen-9-5950x'))
    
    # Async — concurrent multi-product lookup
    import asyncio
    results = asyncio.run(async_search_multiple(['/p/asus-vivobook-s14-oled/', '/p/dji-osmo-action-6-standard-combo']))

Dependencies: cloudscraper, aiohttp (for async), sqlite3 (stdlib)
Install: pip3 install cloudscraper aiohttp --break-system-packages
"""

import re
import json
import time
import asyncio
import sqlite3
import os
from pathlib import Path
from typing import Optional

try:
    import cloudscraper
except ImportError:
    raise ImportError("cloudscraper required — pip3 install cloudscraper")

# ── Cache setup ────────────────────────────────────────────────────────
CACHE_DIR = Path.home() / '.cache' / 'kaina24_lookup'
CACHE_DB = CACHE_DIR / 'prices.db'


def _get_cache_conn():
    """Lazy-init SQLite cache for search results."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(CACHE_DB))
    conn.execute("""CREATE TABLE IF NOT EXISTS price_cache (
        query TEXT PRIMARY KEY,
        html TEXT NOT NULL,
        fetched_at REAL NOT NULL,
        expires_at REAL NOT NULL
    )""")
    conn.commit()
    return conn


def _cache_get(query: str) -> Optional[str]:
    """Return cached HTML if still valid."""
    conn = _get_cache_conn()
    row = conn.execute(
        "SELECT html, expires_at FROM price_cache WHERE query=? AND expires_at > ?",
        (query, time.time())
    ).fetchone()
    return row[0] if row else None


def _cache_set(query: str, html: str):
    """Store HTML in cache for 1 hour."""
    conn = _get_cache_conn()
    now = time.time()
    conn.execute(
        "INSERT OR REPLACE INTO price_cache (query, html, fetched_at, expires_at) VALUES (?, ?, ?, ?)",
        (query, html, now, now + 3600)
    )
    conn.commit()


# ── Scraper singleton ──────────────────────────────────────────────────
_scraper = None


def _get_scraper():
    global _scraper
    if _scraper is None:
        _scraper = cloudscraper.create_scraper()
    return _scraper


# ── HTML parsing helpers ───────────────────────────────────────────────

def _clean_text(text: str) -> str:
    """Decode common Lithuanian HTML entities."""
    return (text.replace('&scaron;', 'š')
              .replace('&Scaron;', 'Š')
              .replace('&nbsp;', ' ')
              .replace('&amp;', '&')
              .replace('&lt;', '<')
              .replace('&gt;', '>'))


def _extract_price(text: str) -> Optional[str]:
    """Extract first product price (€) from text. Skips small shipping costs."""
    matches = re.findall(r'([\d.,]+)\s*€', text)
    for m in matches:
        val = float(m.replace(',', '.'))
        # Skip tiny values that are likely shipping costs (< 10 €)
        if val >= 10.0:
            return m
    return None


def _parse_search_page(html: str, query: str = '') -> dict:
    """Parse a kaina24 search results page into structured data.

    Returns dict with:
      - aggregate: {low_price, high_price, offer_count} from JSON-LD
      - meta_desc: raw meta description text
      - products: list of dicts with url, title, price, seller (from product cards)
      - total_results: count from page title or JSON-LD
    """
    result = {
        'aggregate': {},
        'meta_desc': '',
        'products': [],
        'total_results': 0,
    }

    # Meta description
    meta_m = re.search(r'meta name="description" content="([^"]*)"', html)
    if meta_m:
        result['meta_desc'] = _clean_text(meta_m.group(1))

    # JSON-LD structured data (aggregate pricing)
    json_lds = re.findall(r'<script type="application/ld\+json">(.*?)</script>', html, re.DOTALL)
    for j in json_lds:
        if 'AggregateOffer' in j or 'lowPrice' in j:
            low_m = re.search(r'"lowPrice":([\d.]+)', j)
            high_m = re.search(r'"highPrice":([\d.]+)', j)
            count_m = re.search(r'"offerCount":(\d+)', j)
            if low_m or high_m:
                result['aggregate'] = {
                    'low_price': float(low_m.group(1)) if low_m else None,
                    'high_price': float(high_m.group(1)) if high_m else None,
                    'offer_count': int(count_m.group(1)) if count_m else 0,
                }

    # Total results from page title: "X kainos nuo Y € (N)" or JSON-LD offerCount
    title_m = re.search(r'<title>(.*?)</title>', html, re.DOTALL)
    if title_m:
        total_m = re.search(r'\((\d+)\)\s*\|', title_m.group(1))
        if total_m:
            result['total_results'] = int(total_m.group(1))

    # Parse individual product cards from search results
    # Cards are in <div class="product-item-h-wrap ..."> blocks
    cards = re.findall(r'<div class="product-item-h-wrap[^"]*"[^>]*>(.*?)</div>\s*</div>\s*</div>', html, re.DOTALL)

    for card in cards:
        # Product URL
        url_m = re.search(r'href="(https://www\.kaina24\.lt/p/[^"]+)"', card)
        if not url_m:
            continue
        url = url_m.group(1)

        # Price — first substantial price in the card (>= 10 €)
        price = _extract_price(card)

        # Seller name from shop link text
        shop_link = re.search(r'href="https://www\.kaina24\.lt/ex/\d+/"[^>]*>([^<]*)</a>', card)
        seller = ''
        if shop_link:
            seller = _clean_text(shop_link.group(1))

        # Title — try the compare link title, or product name from nearby text
        title = ''
        # Look for a meaningful title (not "Palyginti kainas" / "Įtraukti į norų sąrašą")
        titles_in_card = re.findall(r'title="([^"]*)"', card)
        good_titles = [t for t in titles_in_card if t not in ('Palyginti kainas', 'Įtraukti į norų sąrašą')]
        if good_titles:
            title = _clean_text(good_titles[0])

        result['products'].append({
            'url': url,
            'title': title,
            'price': price,
            'seller': seller,
        })

    return result


def _parse_product_page(html: str) -> dict:
    """Parse a single product page. Returns structured pricing data."""
    result = {
        'product_name': '',
        'prices': [],  # list of dicts with price, seller, url
        'aggregate': {},
    }

    # Product name from title or JSON-LD
    title_m = re.search(r'<title>(.*?)</title>', html, re.DOTALL)
    if title_m:
        result['product_name'] = _clean_text(title_m.group(1))

    # JSON-LD aggregate offer
    json_lds = re.findall(r'<script type="application/ld\+json">(.*?)</script>', html, re.DOTALL)
    for j in json_lds:
        if 'AggregateOffer' in j or 'lowPrice' in j:
            low_m = re.search(r'"lowPrice":([\d.]+)', j)
            high_m = re.search(r'"highPrice":([\d.]+)', j)
            count_m = re.search(r'"offerCount":(\d+)', j)
            if low_m or high_m:
                result['aggregate'] = {
                    'low_price': float(low_m.group(1)) if low_m else None,
                    'high_price': float(high_m.group(1)) if high_m else None,
                    'offer_count': int(count_m.group(1)) if count_m else 0,
                }

    # Extract individual seller prices from the page
    # Look for shop links with prices nearby
    shop_links = re.findall(r'href="(https://www\.kaina24\.lt/ex/\d+/[^"]*)"[^>]*>([^<]*)</a>', html)
    for link, name in shop_links:
        clean_name = _clean_text(name).strip()
        if not clean_name or len(clean_name) < 3:
            continue

        # Find price near this seller link (within ~500 chars)
        idx = html.find(link)
        if idx > 0:
            context = html[max(0, idx - 200):idx + 400]
            price = _extract_price(context)
            if price:
                result['prices'].append({
                    'price': price,
                    'seller': clean_name,
                    'url': link,
                })

    # Sort prices ascending
    result['prices'].sort(key=lambda x: float(x['price'].replace(',', '.')))

    return result


# ── Sync API functions ────────────────────────────────────────────────

def search_products(query: str, use_cache: bool = True) -> dict:
    """Search kaina24.lt for a product query. Returns structured data.

    Args:
        query: Search term (e.g., 'asus oled laptop', 'amd ryzen 9 5950x')
        use_cache: If True, return cached results if available (< 1 hour old)

    Returns dict with keys: aggregate, meta_desc, products, total_results
    """
    url = f'https://www.kaina24.lt/search?q={query}'

    if use_cache:
        cached = _cache_get(url)
        if cached:
            return _parse_search_page(cached, query)

    scraper = _get_scraper()
    resp = scraper.get(url, timeout=15)

    if use_cache:
        _cache_set(url, resp.text)

    return _parse_search_page(resp.text, query)


def get_product_price(product_slug: str, use_cache: bool = True) -> dict:
    """Get pricing for a specific product page.

    Args:
        product_slug: Full path like '/p/amd-ryzen-9-5950x' or full URL
        use_cache: If True, return cached results if available (< 1 hour old)

    Returns dict with keys: product_name, prices (list), aggregate
    """
    url = product_slug if product_slug.startswith('http') else f'https://www.kaina24.lt{product_slug}'

    cache_key = url
    if use_cache:
        cached = _cache_get(cache_key)
        if cached:
            return _parse_product_page(cached)

    scraper = _get_scraper()
    resp = scraper.get(url, timeout=15)

    if use_cache:
        _cache_set(cache_key, resp.text)

    return _parse_product_page(resp.text)


def get_price_range(query: str) -> tuple:
    """Quick price range from meta description or JSON-LD.

    Returns (min_price, max_price, seller_count) or (None, None, 0).
    """
    url = f'https://www.kaina24.lt/search?q={query}'
    scraper = _get_scraper()
    resp = scraper.get(url, timeout=15)

    # Try JSON-LD first
    json_lds = re.findall(r'<script type="application/ld\+json">(.*?)</script>', resp.text, re.DOTALL)
    for j in json_lds:
        if 'AggregateOffer' in j:
            low_m = re.search(r'"lowPrice":([\d.]+)', j)
            high_m = re.search(r'"highPrice":([\d.]+)', j)
            count_m = re.search(r'"offerCount":(\d+)', j)
            if low_m and high_m:
                return (float(low_m.group(1)), float(high_m.group(1)), int(count_m.group(1)) if count_m else 0)

    # Fallback to meta description: "nuo X € ... iki Y €"
    meta_m = re.search(r'meta name="description" content="([^"]*)"', resp.text)
    if meta_m:
        text = meta_m.group(1)
        nuo_m = re.search(r'nuo\s+([\d.,]+)\s*€', text)
        iki_m = re.search(r'iki\s+([\d.,]+)\s*€', text)
        count_m = re.search(r'(\d+)\s*pardav(?:ėj|e)', text)
        if nuo_m and iki_m:
            return (float(nuo_m.group(1).replace(',', '.')),
                    float(iki_m.group(1).replace(',', '.')),
                    int(count_m.group(1)) if count_m else 0)

    return None, None, 0


# ── Async API functions ────────────────────────────────────────────────

async def async_search_products(query: str) -> dict:
    """Async version of search_products using aiohttp + cloudscraper session."""
    import aiohttp

    url = f'https://www.kaina24.lt/search?q={query}'

    # Use cached result if available
    cached = _cache_get(url)
    if cached:
        return _parse_search_page(cached, query)

    async with aiohttp.ClientSession() as session:
        # cloudscraper's CloudflareBypass can be used with aiohttp
        from cloudscraper import CloudScraper
        scraper = CloudScraper.create_scraper()

        # For true async, use the requests-based scraper in a thread
        loop = asyncio.get_event_loop()
        resp_text = await loop.run_in_executor(
            None, lambda: scraper.get(url, timeout=15).text
        )

    _cache_set(url, resp_text)
    return _parse_search_page(resp_text, query)


async def async_get_product_price(product_slug: str) -> dict:
    """Async version of get_product_price."""
    import aiohttp

    url = product_slug if product_slug.startswith('http') else f'https://www.kaina24.lt{product_slug}'
    cached = _cache_get(url)
    if cached:
        return _parse_product_page(cached)

    from cloudscraper import CloudScraper
    scraper = CloudScraper.create_scraper()
    loop = asyncio.get_event_loop()

    resp_text = await loop.run_in_executor(
        None, lambda: scraper.get(url, timeout=15).text
    )

    _cache_set(url, resp_text)
    return _parse_product_page(resp_text)


async def async_search_multiple(slugs_or_queries: list[str]) -> dict:
    """Concurrently look up multiple products. Returns dict keyed by slug/query.

    Args:
        slugs_or_queries: List of product slugs ('/p/...') or search queries ('asus laptop')

    Usage:
        results = await async_search_multiple([
            '/p/amd-ryzen-9-5950x',
            'asus oled laptop',
            '/p/dji-osmo-action-6-standard-combo'
        ])
    """
    tasks = {}
    for item in slugs_or_queries:
        key = item
        if item.startswith('/p/'):
            tasks[key] = async_get_product_price(item)
        else:
            tasks[key] = async_search_products(item)

    results = await asyncio.gather(*tasks.values(), return_exceptions=True)
    return {key: result for key, result in zip(tasks.keys(), results)}


# ── CLI interface ──────────────────────────────────────────────────────

if __name__ == '__main__':
    import sys

    if len(sys.argv) < 2:
        print("Usage:")
        print("  python3 kaina24_lookup.py search <query>")
        print("  python3 kaina24_lookup.py product /p/<slug>")
        print("  python3 kaina24_lookup.py range <query>")
        sys.exit(1)

    cmd = sys.argv[1]

    if cmd == 'search':
        query = ' '.join(sys.argv[2:])
        result = search_products(query)
        print(f"Query: {query}")
        print(f"Total results: {result['total_results']}")
        agg = result['aggregate']
        if agg.get('low_price'):
            print(f"Price range: {agg['low_price']:.2f} € — {agg['high_price']:.2f} € ({agg['offer_count']} sellers)")
        print()

        for i, p in enumerate(result['products'][:10], 1):
            price_str = f"{p['price']} €" if p['price'] else "N/A"
            seller_str = f"| {p['seller']}" if p['seller'] else ""
            title_str = f" | {p['title']}" if p['title'] else ""
            print(f"  {i}. {p['url']}")
            print(f"     Price: {price_str}{seller_str}{title_str}")

    elif cmd == 'product':
        slug = sys.argv[2]
        result = get_product_price(slug)
        print(f"Product: {result['product_name']}")
        agg = result['aggregate']
        if agg.get('low_price'):
            print(f"Price range: {agg['low_price']:.2f} € — {agg['high_price']:.2f} € ({agg['offer_count']} sellers)")
        print()
        for i, p in enumerate(result['prices'], 1):
            print(f"  {i}. {p['price']} € | {p['seller']}")

    elif cmd == 'range':
        query = ' '.join(sys.argv[2:])
        low, high, count = get_price_range(query)
        if low is not None:
            print(f"{query}: {low:.2f} € — {high:.2f} € ({count} sellers)")
        else:
            print(f"No price data found for: {query}")

    else:
        print(f"Unknown command: {cmd}")
        sys.exit(1)
