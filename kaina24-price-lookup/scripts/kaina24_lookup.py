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


def _extract_price(text: str, min_value: float = 10.0) -> Optional[float]:
    """Extract first product price (€) from text. Skips small shipping costs.

    Returns float (not string) so callers can sort numerically.
    Returns None if no price >= min_value found.
    """
    matches = re.findall(r'([\d.,]+)\s*€', text)
    for m in matches:
        try:
            val = float(m.replace(',', '.'))
        except ValueError:
            continue
        if val >= min_value:
            return val
    return None


def _extract_prices_all(text: str, min_value: float = 10.0) -> list[float]:
    """Extract ALL prices >= min_value from text, in order of appearance."""
    out = []
    for m in re.findall(r'([\d.,]+)\s*€', text):
        try:
            val = float(m.replace(',', '.'))
            if val >= min_value:
                out.append(val)
        except ValueError:
            continue
    return out


def _extract_seller_from_onclick(onclick: str) -> str:
    """Pull seller name out of an onclick/JS data attribute.

    kaina24 wraps seller info in inline GA tracking calls like:
      dataLayer.push({'event': 'GAEvent', 'eventCategory':  'Pigu.lt', ...})
    """
    m = re.search(r"eventCategory'\s*:\s*'([^']+)'", onclick)
    return _clean_text(m.group(1)).strip() if m else ''


def _extract_seller_from_img(card_html: str) -> str:
    """Pull seller name from the shop logo <img alt=...> within a card/row."""
    # Seller name is in the alt attribute of the shop logo image
    m = re.search(r'<img[^>]*alt="([^"]+)"[^>]*src="[^"]*logo/[^"]+\.svg"', card_html)
    if m:
        return _clean_text(m.group(1)).strip()
    # Fallback: any img with a /logo/ src near a /ex/ link
    m = re.search(r'<img[^>]*alt="([^"]+)"[^>]*data-src="[^"]*logo/', card_html)
    return _clean_text(m.group(1)).strip() if m else ''


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

    # Parse individual product cards from search results.
    #
    # Each card is <div class="product-item-h-wrap ... extended ">...</div>.
    # Cards are siblings, not nested, so a non-greedy match against the
    # *opening* tag and the *next* opening of the same class works.
    # We split on the opening tag to avoid the brittle closing-div count.
    card_starts = list(re.finditer(r'<div class="product-item-h-wrap[^"]*"[^>]*>', html))
    for i, m in enumerate(card_starts):
        start = m.end()
        end = card_starts[i + 1].start() if i + 1 < len(card_starts) else len(html)
        card = html[start:end]

        # Product page URL — on the search results page, the compare button
        # links to /p/<slug>/. That's the canonical product detail page.
        url_m = re.search(r'href="(https?://www\.kaina24\.lt/p/[^"]+)"', card)
        if not url_m:
            continue
        url = url_m.group(1)

        # Price — try Schema.org itemprop first (cleanest), then fall back
        # to scanning for the first € price.
        price = None
        price_m = re.search(r'<span itemprop="price">([\d.,]+)</span>', card)
        if price_m:
            try:
                price = float(price_m.group(1).replace(',', '.'))
            except ValueError:
                pass
        if price is None:
            price = _extract_price(card)

        # Seller name — prefer the shop-logo <img alt=...>; fall back to
        # parsing eventCategory out of the GA tracking onclick.
        seller = _extract_seller_from_img(card)
        if not seller:
            onclick_m = re.search(r'onClick="(dataLayer\.push[^"]+)"', card, re.DOTALL)
            if onclick_m:
                seller = _extract_seller_from_onclick(onclick_m.group(1))

        # Title — prefer the product link title attribute (e.g.
        # title="Honor Magic V5 5G (512 GB)"); skip generic UI labels.
        title = ''
        skip_titles = {
            'Palyginti kainas',
            'Įtraukti į norų sąrašą',
            'Pašalinti iš norų sąrašo',
        }
        for t_m in re.finditer(r'title="([^"]+)"', card):
            candidate = _clean_text(t_m.group(1)).strip()
            if candidate and candidate not in skip_titles and len(candidate) > 4:
                title = candidate
                break

        result['products'].append({
            'url': url,
            'title': title,
            'price': price,
            'seller': seller,
        })

    return result


def _parse_product_page(html: str) -> dict:
    """Parse a single product page. Returns structured pricing data.

    Schema.org markup on kaina24 product pages is the most reliable source:

      <div class="c-product-actions-price" itemprop="offers" itemscope
           itemtype="http://schema.org/AggregateOffer">
          <span itemprop="lowPrice">1090.00</span>
          <meta itemprop="highPrice" content="1519.00"/>
          <meta itemprop="priceCurrency" content="EUR"/>
          <span itemprop="offerCount">21</span>
      </div>

    And individual seller offers (in the sellers table at col-6):

      <a href="https://www.kaina24.lt/ex/<id>/..." ... onClick="...eventCategory: 'Pigu.lt'...">
          <div class="price">
              <span itemprop="price">1265.30</span>
              <span>&euro;</span>
          </div>
      </a>
    """
    result = {
        'product_name': '',
        'prices': [],  # list of dicts with price, seller, url
        'aggregate': {},
    }

    # Product name from title or meta tag
    title_m = re.search(r'<title>(.*?)</title>', html, re.DOTALL)
    if title_m:
        result['product_name'] = _clean_text(title_m.group(1))

    # Schema.org AggregateOffer (preferred over JSON-LD — it's always present
        # and well-formed on kaina24 product pages)
        #
        # The wrapper looks like:
        #   <div class="c-product-actions-price" itemprop="offers" itemscope
        #        itemtype="http://schema.org/AggregateOffer">
        #       ...
        #       <span itemprop="lowPrice">1090.00</span>
        #       <meta itemprop="highPrice" content="1519.00"/>
        #       <span itemprop="offerCount">21</span> pardavėjas
        #       ...
        #   </div>
        #
        # The wrapper is the *first* AggregateOffer div on the page. Inside it,
        # the three values we want can be in any order, possibly separated by
        # nested divs (the price <div> contains lowPrice, and a sibling <div>
        # contains offerCount). We track div depth starting from the wrapper to
        # capture all three.
        agg_open = re.search(
            r'<div[^>]*itemtype="http://schema\.org/AggregateOffer"[^>]*>',
            html)
        if agg_open:
            start = agg_open.start()
            window = html[start:start + 5000]
            depth = 0
            end = 0
            for div_m in re.finditer(r'</?div\b', window):
                if div_m.group(0).startswith('<div'):
                    depth += 1
                else:
                    depth -= 1
                    if depth == 0:
                        end = div_m.end()
                        break
            block = window[:end] if end else window[:3000]
            low_m = re.search(r'itemprop="lowPrice"[^>]*>([\d.,]+)</span>', block)
            high_m = re.search(r'itemprop="highPrice"[^>]*content="([\d.,]+)"', block)
            count_m = re.search(r'itemprop="offerCount"[^>]*>(\d+)</span>', block)
            result['aggregate'] = {
                'low_price': float(low_m.group(1).replace(',', '.')) if low_m else None,
                'high_price': float(high_m.group(1).replace(',', '.')) if high_m else None,
                'offer_count': int(count_m.group(1)) if count_m else 0,
            }

    # Fallback to JSON-LD if Schema.org markup missing
    if not result['aggregate']:
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
                    break

    # Extract individual seller offers from the sellers table.
    #
    # Pattern: <td class="col-6"><a href="...kaina24.lt/ex/<id>/..." ...>
    #                   <div class="price"><span itemprop="price">N.NN</span> €</div>
    #               </a></td>
    #
    # Seller name comes from either the <img alt=...> shop logo or the
    # onClick eventCategory. We anchor on the col-6 cell to avoid picking
    # up stray prices elsewhere on the page (sidebar, related items, etc).
    seller_pattern = re.compile(
        r'<td class="col-6">\s*'
        r'<a\s+href="(https?://www\.kaina24\.lt/ex/[^"]+)"[^>]*'
        r'onClick="([^"]+)"[^>]*>\s*'
        r'<div class="price">\s*'
        r'(?:<span itemprop="price">([\d.,]+)</span>|<div class="price">\s*([\d.,]+)\s*<span>&euro;)',
        re.DOTALL,
    )
    for m in seller_pattern.finditer(html):
        url = m.group(1)
        onclick = m.group(2)
        price_str = m.group(3) or m.group(4)
        try:
            price = float(price_str.replace(',', '.'))
        except (ValueError, AttributeError):
            continue
        if price < 10:
            continue

        # Seller name: try onClick eventCategory first (always present),
        # then fall back to shop-logo <img alt=...> in the surrounding row.
        seller = _extract_seller_from_onclick(onclick)
        if not seller:
            # Walk back to the enclosing <tr> to find the shop logo
            tr_start = html.rfind('<tr', 0, m.start())
            tr_end = html.find('</tr>', m.end())
            if tr_start > 0 and tr_end > tr_start:
                row = html[tr_start:tr_end]
                seller = _extract_seller_from_img(row)

        result['prices'].append({
            'price': price,
            'seller': seller,
            'url': url,
        })

    # Dedupe (same seller + same price appearing twice = rendering artifact)
    seen = set()
    deduped = []
    for p in result['prices']:
        key = (p['seller'], p['price'])
        if key in seen:
            continue
        seen.add(key)
        deduped.append(p)
    result['prices'] = deduped

    # Sort prices ascending (already float now, no string conversion needed)
    result['prices'].sort(key=lambda x: x['price'])

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

        for i, p in enumerate(result['products'][:25], 1):
            price_str = f"{p['price']:.2f} €" if p['price'] is not None else "N/A"
            seller_str = f" | {p['seller']}" if p['seller'] else ""
            title_str = f" | {p['title']}" if p['title'] else ""
            print(f"  {i}. {p['url']}")
            print(f"     {price_str}{seller_str}{title_str}")

    elif cmd == 'product':
        slug = sys.argv[2]
        result = get_product_price(slug)
        print(f"Product: {result['product_name']}")
        agg = result['aggregate']
        if agg.get('low_price'):
            print(f"Aggregate: {agg['low_price']:.2f} € — {agg['high_price']:.2f} € ({agg['offer_count']} sellers)")
        print()
        if not result['prices']:
            print("  No individual seller offers parsed.")
        for i, p in enumerate(result['prices'], 1):
            seller_str = p['seller'] or '(unknown seller)'
            print(f"  {i:2}. {p['price']:>8.2f} €  |  {seller_str}")

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
