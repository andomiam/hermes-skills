---
name: kaina24-price-lookup
description: "Look up product prices on Lithuania's price comparison site kaina24.lt using cloudscraper to bypass Cloudflare JS challenge."
version: 1.0.0
author: Hermes Agent
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [kaina24, lithuania, price-comparison, cloudscraper, scraping]
---

# kaina24.lt Price Lookup

Look up product prices on Lithuania's main price comparison site. Uses `cloudscraper` Python library to bypass Cloudflare JS challenge that blocks both curl and browser_navigate.

## When to use
- User asks for a product price from kaina24.lt or "kaina24"
- User wants Lithuanian market prices
- Product slug is known (e.g., `/p/amd-ryzen-9-5950x`)

## Prerequisites
```bash
pip3 install cloudscraper aiohttp  # one-time install
# On PEP 668 externally-managed environments (Pop!_OS 24.04+, Debian 12+):
pip3 install cloudscraper aiohttp --break-system-packages
```

## Primary: Reusable Python module

A full-featured module lives at `scripts/kaina24_lookup.py` with sync + async APIs, caching, and CLI interface. Import it directly:

```python
from scripts.kaina24_lookup import search_products, get_product_price, get_price_range, async_search_multiple
```

### Quick price range (fastest — no HTML parsing)
```python
from scripts.kaina24_lookup import get_price_range

low, high, count = get_price_range('asus oled laptop')
print(f'{low:.2f} € — {high:.2f} € ({count} sellers)')
# Output: 680.99 € — 4733.99 € (137 sellers)
```

### Search with individual product listings
Extracts per-product prices and seller names from search result cards:
```python
from scripts.kaina24_lookup import search_products

result = search_products('asus oled laptop')
print(f"Total results: {result['total_results']}")  # e.g., 137
agg = result['aggregate']
if agg.get('low_price'):
    print(f"Price range: {agg['low_price']:.2f} € — {agg['high_price']:.2f} € ({agg['offer_count']} sellers)")

# Individual products parsed from search cards (16+ per page)
for p in result['products']:
    print(f"{p['price']} € | {p.get('seller', '')[:40]}")
```

### Direct product page lookup
```python
from scripts.kaina24_lookup import get_product_price

result = get_product_price('/p/amd-ryzen-9-5950x')
print(f"Product: {result['product_name']}")
agg = result['aggregate']
if agg.get('low_price'):
    print(f"Range: {agg['low_price']:.2f} € — {agg['high_price']:.2f} € ({agg['offer_count']} sellers)")

# Individual seller prices (when available)
for p in result['prices']:
    print(f"{p['price']} € | {p['seller']}")
```

### Async concurrent multi-product lookup
For looking up multiple products simultaneously:
```python
import asyncio
from scripts.kaina24_lookup import async_search_multiple

async def main():
    results = await async_search_multiple([
        '/p/amd-ryzen-9-5950x',           # product slug
        'asus oled laptop',               # search query
        '/p/dji-osmo-action-6-standard-combo',
    ])
    
    for key, result in results.items():
        print(f"{key}: {result}")

asyncio.run(main())
```

### CLI interface
```bash
# Quick price range
python3 scripts/kaina24_lookup.py range "asus oled laptop"

# Search with product details
python3 scripts/kaina24_lookup.py search "amd ryzen 9 5950x"

# Single product page
python3 scripts/kaina24_lookup.py product /p/amd-ryzen-9-5950x
```

## Caching
All requests are cached in `~/.cache/kaina24_lookup/prices.db` for 1 hour. Subsequent lookups of the same query return instantly from cache. Disable with `use_cache=False`.

## Steps (legacy: raw cloudscraper snippets)

### Direct product page lookup (preferred)
If user provides or you know the product URL:

```python
import cloudscraper, re
scraper = cloudscraper.create_scraper()
resp = scraper.get('https://www.kaina24.lt/p/<product-slug>')

# Extract price — regex matches "315.20 €" pattern
price_match = re.search(r'([\d.,]+)\s*(€|Lt\.)', resp.text)
if price_match:
    print(f'Price: {price_match.group(1)} €')

# Check product exists
if 'Ryzen 9 5950X' in resp.text or '<MODEL>' in resp.text:
    print('Product page found!')
else:
    print('No product content found.')
```

### Search lookup (fallback) — aggregate pricing only
If only the product name is known and you want a quick price range:

```python
import cloudscraper, re
scraper = cloudscraper.create_scraper()
resp = scraper.get(f'https://www.kaina24.lt/search?q=<SEARCH+TERM>')

# Extract all product links — /search?q= works correctly (unlike /?s=)
products = re.findall(r'<a href="([^"]*p/[^"]*)"[^>]*>(.*?)</a>', resp.text)
for url, text in products[:15]:
    clean_text = ''.join(c for c in text if ord(c) < 128).strip()
    print(f'{url} | {clean_text}')

# Check meta description for price info
meta_desc = re.search(r'meta name="description" content="([^"]*)"', resp.text)
if meta_desc:
    # Often contains "nuo X €" format with lowest price and seller count
    print(meta_desc.group(1))
```

### Search lookup — extracting individual product listings from search results
Search results pages render product cards via AJAX (`product-item-h-wrap` divs). The initial HTML response already contains these blocks (they're server-rendered, not client-side JS), but they use a different structure than direct product pages:

```python
import cloudscraper, re
scraper = cloudscraper.create_scraper()
resp = scraper.get(f'https://www.kaina24.lt/search?q=<SEARCH+TERM>')

# Extract all /p/ links from the page (these are in the initial HTML)
product_links = re.findall(r'href="(/p/[^\"]*<KEYWORD>[^\"]*)"', resp.text)

# For each product, extract price and seller from the surrounding card block
cards = re.findall(r'<div class="product-item-h-wrap"[^>]*>(.*?)</div>\s*</div>\s*</div>', resp.text, re.DOTALL)
for card in cards:
    # Product URL
    url_match = re.search(r'href="(https://www\.kaina24\.lt/p/[^"]+)"', card)
    if not url_match: continue
    
    # Price — look for € pattern in the card
    prices = re.findall(r'([\d.,]+)\s*€', card)
    
    # Seller name — look for shop link or eshop-name class
    shop_link = re.search(r'href="https://www\.kaina24\.lt/ex/\d+/"[^>]*>([^<]*)</a>', card)
    seller = ''.join(c for c in (shop_link.group(1) if shop_link else '') if ord(c) < 128).strip()
    
    # Title from the compare link title attribute or nearby text
    title_match = re.search(r'title="([^"]*)"', card)
    title = ''
    if title_match:
        title = title_match.group(1).replace('&scaron;', 'š').replace('&nbsp;', ' ').replace('&amp;', '&')
    
    print(f'{url_match.group(1)} | {title} | {prices[0] if prices else "N/A"} € | {seller}')

# Also extract JSON-LD structured data for aggregate pricing on the search page:
json_ld = re.findall(r'<script type="application/ld\+json">(.*?)</script>', resp.text, re.DOTALL)
for j in json_ld:
    if 'AggregateOffer' in j or 'lowPrice' in j:
        low = re.search(r'"lowPrice":([\d.]+)', j)
        high = re.search(r'"highPrice":([\d.]+)', j)
        count = re.search(r'"offerCount":(\d+)', j)
        if low or high:
            print(f'Aggregate: low={low.group(1)}, high={high.group(1)}, offers={count.group(1)}')
```

**Key patterns for search result cards:**
- Cards are wrapped in `<div class="product-item-h-wrap ...">` — find these blocks to get per-product data.
- Each card contains a compare link (`/p/<slug>`) and a seller shop link (`/ex/<id>/`).
- Prices appear as `€` patterns within the card block; shipping costs also match this pattern (filter by context).
- The JSON-LD `<script type="application/ld+json">` on the search page gives aggregate low/high price across ALL sellers for that search term.

## Pitfalls
- **Search URL must be `/search?q=`, NOT `/?s=`** — the latter returns stale homepage products regardless of query term. Always use `/search?q=` for search lookups.
- **Cloudflare JS challenge blocks both curl and browser_navigate** — must use `cloudscraper` library, not plain requests or curl.
- **Product pages work fine with cloudscraper** — only search/results pages need the JS bypass.
- **Price format**: always `<number> €` (space before euro sign). The meta description often contains "nuo X €" (from X euros) which is the lowest price across sellers.
- **"X pardavėjas"** in meta description = number of sellers offering the product.
- **Search results use AJAX-rendered cards** — individual product listings are inside `product-item-h-wrap` divs, not simple `<a>` tags. The initial HTML contains these blocks (server-rendered), but they require parsing the full card structure to extract per-product prices and seller names. Simple regex on raw HTML will miss them.
- **Shipping costs also match € pattern** — when extracting prices from search cards, shipping lines like "Pristatymo kaina: 5.69" appear alongside product prices. Filter by context (product price is usually the first/largest price in the card).

## Lithuanian Keywords
- `nuo` = from (starting price)
- `pardavėjas/pardavjai` = seller(s)
- `nerasta` = not found
- `standart/standard` = standard edition
- `kombo/komplektas` = combo/package

## Reference files
See `references/` directory for known product slugs and prices to avoid repeated lookups.

### Available references
- `known-products.md` — curated price reference for CPUs, RAM, action cameras, drones (stable products)
- `asus-oled-laptops.md` — ASUS OLED laptop prices extracted via search-result card parsing (dynamic pricing, updated on lookup)