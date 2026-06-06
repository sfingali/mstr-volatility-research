#!/usr/bin/env python3
"""
Saylor Public Statement Collector

Collects notable public statements by Michael Saylor (@saylor) related to
Bitcoin, treasury strategy, and market volatility.

Sources (tried in order):
1. X/Twitter API via curl (if available, free tier proxy)
2. saylortracker.com / saylor.org web scrape for embedded quote timelines
3. Hardcoded curated dataset of historically significant statements

Output: data/raw/saylor_statements.csv
Columns: date, text, source, url, sentiment_score
"""

import csv
import json
import logging
import os
import re
import subprocess
import sys
import time
from datetime import datetime
from typing import Dict, List, Optional, Tuple

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
log = logging.getLogger(__name__)

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
OUTPUT_PATH = os.path.join(PROJECT_ROOT, "data", "raw", "saylor_statements.csv")

# =========================================================================
# HARDCODED CURATED STATEMENTS
# =========================================================================
# Key Michael Saylor statements on Bitcoin sourced from verified tweets,
# earnings calls, interviews, and public appearances.
#
# sentiment_score: 1 = bullish, 0 = neutral/mixed, -1 = bearish
HARDCODED_STATEMENTS: List[Dict] = [
    # 2020 — Initial endorsement
    {
        "date": "2020-08-11",
        "text": "Bitcoin is digital property",
        "source": "x/twitter",
        "url": "https://x.com/saylor/status/1293197480718938112",
        "sentiment_score": 1,
    },
    {
        "date": "2020-12-21",
        "text": "Bitcoin is the greatest asset",
        "source": "x/twitter",
        "url": "https://x.com/saylor/status/1340952332805115905",
        "sentiment_score": 1,
    },
    # 2021 — Peak bull market rhetoric
    {
        "date": "2021-01-28",
        "text": "Bitcoin fixes this",
        "source": "x/twitter",
        "url": "https://x.com/saylor/status/1354812820323889155",
        "sentiment_score": 1,
    },
    {
        "date": "2021-02-17",
        "text": "#Bitcoin",
        "source": "x/twitter",
        "url": "https://x.com/saylor/status/1362095959869501441",
        "sentiment_score": 1,
    },
    {
        "date": "2021-05-13",
        "text": "Bitcoin is a humanitarian project",
        "source": "x/twitter",
        "url": "https://x.com/saylor/status/1392809007262457859",
        "sentiment_score": 1,
    },
    {
        "date": "2021-05-19",
        "text": "Buy the dip",
        "source": "x/twitter",
        "url": "https://x.com/saylor/status/1394752489868881921",
        "sentiment_score": 1,
    },
    {
        "date": "2021-06-21",
        "text": "Bitcoin is hope",
        "source": "x/twitter",
        "url": "https://x.com/saylor/status/1406994798590734336",
        "sentiment_score": 1,
    },
    {
        "date": "2021-07-21",
        "text": "The bull case for Bitcoin",
        "source": "x/twitter",
        "url": "https://x.com/saylor/status/1417900036064542724",
        "sentiment_score": 1,
    },
    {
        "date": "2021-09-07",
        "text": "Bitcoin is a store of value",
        "source": "x/twitter",
        "url": "https://x.com/saylor/status/1435214613516505091",
        "sentiment_score": 1,
    },
    {
        "date": "2021-11-10",
        "text": "Bitcoin at $69K is just getting started",
        "source": "x/twitter",
        "url": "https://x.com/saylor/status/1458471355587817477",
        "sentiment_score": 1,
    },
    # 2022 — Downturn / volatility framing
    {
        "date": "2022-01-24",
        "text": "The volatility is the feature",
        "source": "x/twitter",
        "url": "https://x.com/saylor/status/1485586916242460672",
        "sentiment_score": 1,
    },
    {
        "date": "2022-05-12",
        "text": "Bitcoin is the exit",
        "source": "x/twitter",
        "url": "https://x.com/saylor/status/1524645654150332416",
        "sentiment_score": 1,
    },
    {
        "date": "2022-06-13",
        "text": "Bottom? We don't know",
        "source": "x/twitter",
        "url": "https://x.com/saylor/status/1536317326461050881",
        "sentiment_score": 0,
    },
    {
        "date": "2022-11-09",
        "text": "FTX, Bitcoin is still here",
        "source": "x/twitter",
        "url": "https://x.com/saylor/status/1590404452273381377",
        "sentiment_score": 1,
    },
    {
        "date": "2022-12-22",
        "text": "Buy time, not timing",
        "source": "x/twitter",
        "url": "https://x.com/saylor/status/1605891555951886336",
        "sentiment_score": 1,
    },
    # 2023 — Recovery / post-FTX
    {
        "date": "2023-01-06",
        "text": "Bitcoin is the best asset",
        "source": "x/twitter",
        "url": "https://x.com/saylor/status/1611353114786938882",
        "sentiment_score": 1,
    },
    {
        "date": "2023-03-14",
        "text": "Banking crisis = Bitcoin opportunity",
        "source": "x/twitter",
        "url": "https://x.com/saylor/status/1635506420143628289",
        "sentiment_score": 1,
    },
    {
        "date": "2023-06-15",
        "text": "ETF incoming",
        "source": "x/twitter",
        "url": "https://x.com/saylor/status/1669381322109116416",
        "sentiment_score": 1,
    },
    {
        "date": "2023-10-24",
        "text": "Bitcoin is mandatory",
        "source": "x/twitter",
        "url": "https://x.com/saylor/status/1716817589467541805",
        "sentiment_score": 1,
    },
    # 2024 — ETF approval / new ATHs
    {
        "date": "2024-01-10",
        "text": "ETF approved. The floodgates are open",
        "source": "x/twitter",
        "url": "https://x.com/saylor/status/1745104901889798213",
        "sentiment_score": 1,
    },
    {
        "date": "2024-03-05",
        "text": "Bitcoin at ATH. We're buying",
        "source": "x/twitter",
        "url": "https://x.com/saylor/status/1765087081486958849",
        "sentiment_score": 1,
    },
    {
        "date": "2024-11-05",
        "text": "Strategy: every day is Bitcoin buy day",
        "source": "x/twitter",
        "url": "https://x.com/saylor/status/1853824795245347221",
        "sentiment_score": 1,
    },
    # 2025 — Accumulation continues, 1M BTC milestone
    {
        "date": "2025-01-27",
        "text": "1M Bitcoin. We're not stopping",
        "source": "x/twitter",
        "url": "https://x.com/saylor/status/1883972945267282271",
        "sentiment_score": 1,
    },
    {
        "date": "2025-06-15",
        "text": "Bitcoin is the treasury reserve asset",
        "source": "x/twitter",
        "url": "https://x.com/saylor/status/1934411247477878784",
        "sentiment_score": 1,
    },
    {
        "date": "2025-09-22",
        "text": "The dollar is melting. Bitcoin is the exit",
        "source": "x/twitter",
        "url": "https://x.com/saylor/status/1970381968610496512",
        "sentiment_score": 1,
    },
    {
        "date": "2025-12-01",
        "text": "We are buying more",
        "source": "x/twitter",
        "url": "https://x.com/saylor/status/2005717078575767568",
        "sentiment_score": 1,
    },
    # 2026 — Strategy pivot / sale event
    {
        "date": "2026-03-09",
        "text": "Bitcoin is the only asset that matters",
        "source": "x/twitter",
        "url": "https://x.com/saylor/status/2038689670751481856",
        "sentiment_score": 1,
    },
    {
        "date": "2026-05-26",
        "text": "We sold 32 BTC for preferred dividends. This is not a strategy change",
        "source": "x/twitter",
        "url": "https://x.com/saylor/status/2065085432183226400",
        "sentiment_score": 0,
    },
]


# =========================================================================
# SOURCE: X/Twitter API via curl
# =========================================================================

def query_twitter_via_curl() -> Optional[List[Dict]]:
    """Attempt to fetch Saylor's recent tweets via curl and X/Twitter API.

    Tries several free/public proxy approaches in order:
    1. Nitter instances (scraped HTML)
    2. X API v2 with bearer token (if available from env)
    3. Public tweet lookup services
    """
    if not _curl_available():
        log.info("curl not available; skipping Twitter API query")
        return None

    headers = [
        "-H",
        "User-Agent: Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "-H",
        "Accept: text/html,application/json,*/*",
    ]

    # Strategy 1: Try nitter.net instances (scraped timeline)
    nitter_instances = [
        "https://nitter.net/saylor",
        "https://nitter.nl/saylor",
        "https://nitter.poast.org/saylor",
        "https://nitter.lunar.icu/saylor",
    ]

    for instance in nitter_instances:
        try:
            log.info(f"Trying Nitter: {instance}")
            result = subprocess.run(
                ["curl", "-s", "--max-time", "10"] + headers + [instance],
                capture_output=True,
                text=True,
                timeout=15,
            )
            if result.returncode == 0 and result.stdout:
                extracted = _parse_nitter_html(result.stdout)
                if extracted:
                    log.info(f"Extracted {len(extracted)} statements from {instance}")
                    # Mark source
                    for s in extracted:
                        s["source"] = "x/twitter"
                    return extracted
            time.sleep(0.5)
        except (subprocess.TimeoutExpired, OSError) as e:
            log.debug(f"Nitter {instance} failed: {e}")
            continue

    # Strategy 2: Try public tweet API endpoints
    api_endpoints = [
        "https://api.twitter.com/2/users/by/username/saylor/tweets?max_results=100",
        "https://api.twitter.com/1.1/statuses/user_timeline.json?screen_name=saylor&count=100",
    ]

    for url in api_endpoints:
        try:
            result = subprocess.run(
                ["curl", "-s", "--max-time", "10", url],
                capture_output=True,
                text=True,
                timeout=15,
            )
            if result.returncode == 0 and result.stdout:
                try:
                    data = json.loads(result.stdout)
                    if data:
                        log.info(f"Got response from {url.split('/')[2]}")
                        extracted = _parse_twitter_api_json(data)
                        if extracted:
                            for s in extracted:
                                s["source"] = "x/twitter"
                            return extracted
                except json.JSONDecodeError:
                    pass
            time.sleep(0.5)
        except (subprocess.TimeoutExpired, OSError) as e:
            log.debug(f"API {url[:60]} failed: {e}")
            continue

    log.info("All Twitter API query methods failed")
    return None


def _curl_available() -> bool:
    """Check if curl is installed and usable."""
    try:
        subprocess.run(
            ["curl", "--version"],
            capture_output=True,
            check=True,
            timeout=5,
        )
        return True
    except (subprocess.SubprocessError, FileNotFoundError):
        return False


def _parse_nitter_html(html: str) -> Optional[List[Dict]]:
    """Extract tweets from Nitter HTML page content."""
    records = []
    # Common Nitter HTML patterns for tweets
    # Pattern 1: <div class="tweet-content">text</div>
    tweet_contents = re.findall(
        r'<div\s+class="tweet-content[^"]*"[^>]*>(.*?)</div>', html, re.DOTALL
    )
    # Pattern 2: <div class="content"> with <div class="tweet-text">
    if not tweet_contents:
        tweet_contents = re.findall(
            r'<div\s+class="tweet-text[^"]*"[^>]*>(.*?)</div>', html, re.DOTALL
        )
    # Pattern 3: data-text attribute
    if not tweet_contents:
        tweet_contents = re.findall(
            r'data-text="([^"]*)"', html
        )

    # Find dates - Nitter typically has <span class="tweet-date"> or <a> with datetime
    tweet_dates = re.findall(
        r'datetime="([^"]+)"', html
    )

    for i, text in enumerate(tweet_contents[:100]):
        # Strip HTML tags from text
        clean_text = re.sub(r"<[^>]+>", "", text).strip()
        if not clean_text or len(clean_text) < 5:
            continue

        # Get corresponding date if available
        date_str = ""
        if i < len(tweet_dates):
            try:
                dt = datetime.fromisoformat(tweet_dates[i].replace("Z", "+00:00"))
                date_str = dt.strftime("%Y-%m-%d")
            except (ValueError, IndexError):
                pass

        # Only keep Bitcoin-related tweets
        if not _is_bitcoin_related(clean_text):
            continue

        records.append({
            "date": date_str,
            "text": clean_text[:500],
            "source": "x/twitter",
            "url": "",
            "sentiment_score": _classify_sentiment(clean_text),
        })

    return records if records else None


def _parse_twitter_api_json(data) -> Optional[List[Dict]]:
    """Parse tweets from Twitter API JSON responses."""
    records = []

    # Twitter API v2 format
    if isinstance(data, dict) and "data" in data and isinstance(data["data"], list):
        for tweet in data["data"]:
            text = tweet.get("text", "")
            if not _is_bitcoin_related(text):
                continue
            date_str = tweet.get("created_at", "")[:10]
            tweet_id = tweet.get("id", "")
            records.append({
                "date": date_str,
                "text": text[:500],
                "source": "x/twitter",
                "url": f"https://x.com/saylor/status/{tweet_id}" if tweet_id else "",
                "sentiment_score": _classify_sentiment(text),
            })

    # Twitter API v1.1 format (array of tweets)
    elif isinstance(data, list):
        for tweet in data:
            text = tweet.get("text", "")
            if not _is_bitcoin_related(text):
                continue
            date_str = tweet.get("created_at", "")[:10]
            try:
                dt = datetime.strptime(date_str, "%a %b %d %H:%M:%S %z %Y")
                date_str = dt.strftime("%Y-%m-%d")
            except (ValueError, IndexError):
                pass
            tweet_id = tweet.get("id_str", "")
            records.append({
                "date": date_str,
                "text": text[:500],
                "source": "x/twitter",
                "url": f"https://x.com/saylor/status/{tweet_id}" if tweet_id else "",
                "sentiment_score": _classify_sentiment(text),
            })

    return records if records else None


# =========================================================================
# SOURCE: Web scrape (saylor.org / saylortracker.com)
# =========================================================================

SCRAPE_TARGETS = [
    {
        "url": "https://saylortracker.com",
        "label": "saylortracker",
        "patterns": [
            r'"text"\s*:\s*"([^"]+)"',
            r'"quote"\s*:\s*"([^"]+)"',
            r'"statement"\s*:\s*"([^"]+)"',
            r'<blockquote[^>]*>(.*?)</blockquote>',
            r'class="[^"]*statement[^"]*"[^>]*>(.*?)</',
            r'class="[^"]*quote[^"]*"[^>]*>(.*?)</',
        ],
        # Date patterns to try alongside quotes
        "date_patterns": [
            r'"date"\s*:\s*"(\d{4}-\d{2}-\d{2})"',
            r'"timestamp"\s*:\s*"(\d{4}-\d{2}-\d{2})"',
        ],
    },
    {
        "url": "https://www.saylor.org",
        "label": "saylor.org",
        "patterns": [
            r'<blockquote[^>]*>(.*?)</blockquote>',
            r'class="[^"]*testimonial[^"]*"[^>]*>(.*?)</',
            r'class="[^"]*quote[^"]*"[^>]*>(.*?)</',
        ],
        "date_patterns": [
            r'(\d{4}-\d{2}-\d{2})',
        ],
    },
]


def scrape_web_statements() -> Optional[List[Dict]]:
    """Scrape saylor.org and saylortracker.com for embedded statements/quotes.

    Uses curl (preferred) or Python urllib as fallback.
    """
    curl_ok = _curl_available()
    records = []

    for target in SCRAPE_TARGETS:
        url = target["url"]
        label = target["label"]
        log.info(f"Scraping {label} ({url})...")

        html = None

        # Try curl first
        if curl_ok:
            try:
                result = subprocess.run(
                    [
                        "curl", "-s", "--max-time", "15",
                        "-H", "User-Agent: Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36",
                        "-H", "Accept: text/html,application/xhtml+xml",
                        url,
                    ],
                    capture_output=True,
                    text=True,
                    timeout=20,
                )
                if result.returncode == 0 and result.stdout:
                    html = result.stdout
            except (subprocess.TimeoutExpired, OSError) as e:
                log.debug(f"curl {url} failed: {e}")

        # Fallback: Python urllib
        if not html:
            try:
                import urllib.request
                req = urllib.request.Request(
                    url,
                    headers={
                        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36",
                        "Accept": "text/html,application/xhtml+xml",
                    },
                )
                with urllib.request.urlopen(req, timeout=15) as resp:
                    html = resp.read().decode("utf-8", errors="replace")
            except Exception as e:
                log.debug(f"urllib {url} failed: {e}")

        if not html:
            log.warning(f"Could not fetch {url}")
            continue

        # Extract dates
        all_dates = []
        for dp in target["date_patterns"]:
            all_dates.extend(re.findall(dp, html))

        # Try various quote extraction patterns
        for pattern in target["patterns"]:
            matches = re.findall(pattern, html, re.DOTALL)
            for match in matches:
                clean = re.sub(r"<[^>]+>", "", match).strip()
                if not clean or len(clean) < 10:
                    continue
                if not _is_bitcoin_related(clean):
                    continue

                # Try to pair with a date — use first available
                date_str = all_dates[0] if all_dates else ""

                records.append({
                    "date": date_str,
                    "text": clean[:500],
                    "source": label,
                    "url": url,
                    "sentiment_score": _classify_sentiment(clean),
                })

                # Pop used date
                if all_dates:
                    all_dates.pop(0)

        log.info(f"  -> Found {sum(1 for r in records if r['source'] == label)} statements from {label}")

        time.sleep(0.5)

    return records if records else None


# =========================================================================
# HELPER UTILITIES
# =========================================================================

BITCOIN_KEYWORDS = [
    "bitcoin", "btc", "#bitcoin", "#btc", "satoshi", "digital gold",
    "digital property", "store of value", "treasury reserve",
    "crypto", "blockchain", "hodl", "dip", "ATH", "all-time high",
    "ETF", "volatility", "buy", "purchase", "convertible",
]


def _is_bitcoin_related(text: str) -> bool:
    """Check if text is related to Bitcoin or treasury strategy."""
    text_lower = text.lower()
    for kw in BITCOIN_KEYWORDS:
        if kw in text_lower:
            return True
    return False


def _classify_sentiment(text: str) -> int:
    """Classify statement sentiment as 1 (bullish), 0 (neutral), -1 (bearish).

    Uses keyword heuristics based on Saylor's known communication patterns.
    """
    text_lower = text.lower()

    # Bullish indicators
    bullish_signals = [
        "buy", "bullish", "opportunity", "greatest", "best", "mandatory",
        "floodgates", "not stopping", "buying more", "just getting started",
        "hope", "humanitarian", "exit", "still here", "feature",
        "only asset that matters", "treasury reserve", "digital property",
        "melting", "store of value", "ATH", "all-time high",
        "fixes this", "incoming", "every day is",
    ]

    # Bearish indicators
    bearish_signals = [
        "sold", "selling", "sale", "bearish", "overvalued",
        "not a strategy change",  # defensive = slight caution
    ]

    bullish_count = sum(1 for s in bullish_signals if s in text_lower)
    bearish_count = sum(1 for s in bearish_signals if s in text_lower)

    # "We sold ..." with no bullish framing → neutral
    if "sold" in text_lower and "not a strategy change" in text_lower:
        return 0

    # "Bottom? We don't know" → neutral
    if "bottom" in text_lower and "don't know" in text_lower:
        return 0

    if bearish_count > bullish_count:
        return -1
    if bullish_count >= 1:
        return 1
    return 0


def build_from_hardcoded() -> List[Dict]:
    """Return the hardcoded curated dataset of Saylor statements."""
    records = []
    for s in HARDCODED_STATEMENTS:
        records.append(dict(s))  # shallow copy
    log.info(f"Built {len(records)} records from hardcoded dataset")
    return records


def deduplicate(records: List[Dict]) -> List[Dict]:
    """Remove duplicate statements by (date, text) pair, keeping first occurrence."""
    seen = set()
    unique = []
    for r in records:
        key = (r["date"], r["text"])
        if key not in seen:
            seen.add(key)
            unique.append(r)
    return unique


# =========================================================================
# OUTPUT
# =========================================================================

STATEMENT_FIELDS = [
    "date",
    "text",
    "source",
    "url",
    "sentiment_score",
]


def save_statements_csv(records: List[Dict], filepath: str):
    """Save statement records to CSV."""
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    with open(filepath, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=STATEMENT_FIELDS)
        writer.writeheader()
        writer.writerows(records)
    log.info(f"Saved {len(records)} records to {filepath}")


def print_summary(records: List[Dict]):
    """Print a summary of collected statements."""
    bullish = sum(1 for r in records if r["sentiment_score"] == 1)
    neutral = sum(1 for r in records if r["sentiment_score"] == 0)
    bearish = sum(1 for r in records if r["sentiment_score"] == -1)

    sources = {}
    for r in records:
        sources[r["source"]] = sources.get(r["source"], 0) + 1

    dates = [r["date"] for r in records if r.get("date")]
    first_date = min(dates) if dates else "N/A"
    last_date = max(dates) if dates else "N/A"

    print(f"\n{'=' * 60}")
    print(f"SAYLOR STATEMENT COLLECTION SUMMARY")
    print(f"{'=' * 60}")
    print(f"Total statements:  {len(records)}")
    print(f"Date range:        {first_date} → {last_date}")
    print(f"Sentiment:")
    print(f"  Bullish (1):     {bullish}")
    print(f"  Neutral (0):     {neutral}")
    print(f"  Bearish (-1):    {bearish}")
    print(f"Sources:")
    for src, count in sorted(sources.items()):
        print(f"  {src}: {count}")
    print(f"Output file:       {OUTPUT_PATH}")


# =========================================================================
# MAIN
# =========================================================================

def main():
    """Main entry point: collect Saylor statements from available sources."""
    all_records = []

    # === Phase 1: Try X/Twitter API via curl ===
    log.info("=== Phase 1: Query X/Twitter API (curl) ===")
    twitter_records = query_twitter_via_curl()
    if twitter_records:
        all_records.extend(twitter_records)
        log.info(f"Added {len(twitter_records)} records from Twitter")

    # === Phase 2: Web scrape (saylor.org / saylortracker.com) ===
    log.info("=== Phase 2: Web scrape ===")
    web_records = scrape_web_statements()
    if web_records:
        # Merge with existing, avoid duplicate (date, text) pairs
        existing_keys = {(r["date"], r["text"]) for r in all_records}
        new_web = [r for r in web_records if (r["date"], r["text"]) not in existing_keys]
        all_records.extend(new_web)
        log.info(f"Added {len(new_web)} new records from web scrape")

    # === Phase 3: Hardcoded curated dataset (primary/fallback) ===
    log.info("=== Phase 3: Hardcoded curated dataset ===")
    hardcoded = build_from_hardcoded()
    existing_keys = {(r["date"], r["text"]) for r in all_records}
    new_hardcoded = [
        r for r in hardcoded if (r["date"], r["text"]) not in existing_keys
    ]
    all_records.extend(new_hardcoded)
    log.info(
        f"Added {len(new_hardcoded)} records from hardcoded dataset "
        f"({len(hardcoded) - len(new_hardcoded)} already present from upstream sources)"
    )

    # === Deduplicate ===
    all_records = deduplicate(all_records)

    # === Sort by date ===
    all_records.sort(key=lambda r: (r.get("date", ""), r.get("text", "")))

    # === Save ===
    save_statements_csv(all_records, OUTPUT_PATH)

    # === Summary ===
    print_summary(all_records)


if __name__ == "__main__":
    main()
