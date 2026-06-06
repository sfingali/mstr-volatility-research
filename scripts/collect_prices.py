#!/usr/bin/env python3
"""
collect_prices.py — BTC Price & Volatility Data Pipeline

Fetches hourly BTC/USDT OHLCV from Binance public API (primary data source,
no API key required, full history available). Attempts supplemental data from
CoinGecko free tier (daily OHLCV, market cap, BTC dominance) but gracefully
degrades if endpoints are unavailable.

Calculates realized volatility: 7-day, 14-day, 30-day rolling annualized
volatility from hourly returns. Also computes daily returns, max drawdown
from ATH, volume analysis, and (if available) BTC dominance.

Outputs:
    data/raw/btc_ohlcv_hourly.csv      — Raw hourly OHLCV from Binance
    data/raw/btc_ohlcv_daily.csv       — Daily OHLCV (resampled from hourly + CoinGecko if available)
    data/processed/btc_volatility.csv  — Computed volatility & derived metrics
"""

from __future__ import annotations

import logging
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from typing import Any

import numpy as np
import pandas as pd
import requests

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_RAW = os.path.join(PROJECT_ROOT, "data", "raw")
DATA_PROCESSED = os.path.join(PROJECT_ROOT, "data", "processed")

os.makedirs(DATA_RAW, exist_ok=True)
os.makedirs(DATA_PROCESSED, exist_ok=True)

OUTPUT_HOURLY = os.path.join(DATA_RAW, "btc_ohlcv_hourly.csv")
OUTPUT_DAILY = os.path.join(DATA_RAW, "btc_ohlcv_daily.csv")
OUTPUT_VOLATILITY = os.path.join(DATA_PROCESSED, "btc_volatility.csv")

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("collect_prices")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
START_DATE = datetime(2020, 1, 1, tzinfo=timezone.utc)

# CoinGecko free tier — limited, use 1.5 s spacing
CG_BASE = "https://api.coingecko.com/api/v3"
CG_DELAY = 1.5
CG_MAX_RETRIES = 3

# Binance public API (no key needed)
BINANCE_BASE = "https://api.binance.com"
BINANCE_MAX_CANDLES = 1000  # max per klines request

# Rolling volatility windows (in days)
VOL_WINDOWS = [7, 14, 30]

# ---------------------------------------------------------------------------
# 1. Binance hourly OHLCV fetcher
# ---------------------------------------------------------------------------


def binance_klines(
    symbol: str = "BTCUSDT",
    interval: str = "1h",
    start_time: datetime | None = None,
    end_time: datetime | None = None,
) -> list[dict[str, Any]]:
    """
    Fetch klines (candles) from Binance public API, paginating 1000 at a time.

    Returns list of dicts with keys: timestamp, open, high, low, close, volume,
    quote_volume, trades, taker_buy_volume, taker_buy_quote_volume, ignore.
    """
    if start_time is None:
        start_time = START_DATE

    records: list[dict[str, Any]] = []
    current_start = int(start_time.timestamp() * 1000)

    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    current_end = int(end_time.timestamp() * 1000) if end_time else now_ms

    while current_start < current_end:
        params = {
            "symbol": symbol,
            "interval": interval,
            "startTime": current_start,
            "limit": BINANCE_MAX_CANDLES,
        }

        try:
            resp = requests.get(
                f"{BINANCE_BASE}/api/v3/klines",
                params=params,
                timeout=30,
            )
            resp.raise_for_status()
            candles = resp.json()
        except requests.RequestException as e:
            log.error("Binance API error at startTime=%d: %s", current_start, e)
            break

        if not candles:
            break  # no more data

        for c in candles:
            records.append({
                "timestamp": int(c[0]),
                "open": float(c[1]),
                "high": float(c[2]),
                "low": float(c[3]),
                "close": float(c[4]),
                "volume": float(c[5]),
                "quote_volume": float(c[7]),
                "trades": int(c[8]),
                "taker_buy_volume": float(c[9]),
                "taker_buy_quote_volume": float(c[10]),
            })

        # Advance to the next batch (last candle's time + 1ms)
        last_ts = candles[-1][0]
        current_start = last_ts + 1

        log.info(
            "Binance: fetched %d hourly candles up to %s",
            len(candles),
            datetime.fromtimestamp(last_ts / 1000, tz=timezone.utc).isoformat(),
        )

        time.sleep(0.1)  # light pause to be gentle

    return records


# ---------------------------------------------------------------------------
# 2. CoinGecko supplemental data (gracefully degrading)
# ---------------------------------------------------------------------------


def _cg_request(
    endpoint: str,
    params: dict[str, Any] | None = None,
) -> dict[str, Any] | list[Any] | None:
    """Make a CoinGecko API request with rate limiting and retries.

    Returns parsed JSON on success, or None on failure (after retries).
    Never raises — always degrades gracefully.
    """
    url = f"{CG_BASE}{endpoint}"
    for attempt in range(1, CG_MAX_RETRIES + 1):
        try:
            resp = requests.get(url, params=params, timeout=30)
            if resp.status_code == 429:
                retry_after = int(resp.headers.get("Retry-After", "60"))
                log.warning(
                    "CoinGecko rate limited — waiting %ds (attempt %d/%d)",
                    retry_after, attempt, CG_MAX_RETRIES,
                )
                time.sleep(retry_after)
                continue
            if resp.status_code in (401, 403):
                log.warning(
                    "CoinGecko auth error %d on %s — endpoint may need API key",
                    resp.status_code, endpoint,
                )
                return None
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as e:
            log.warning(
                "CoinGecko error on %s (attempt %d/%d): %s",
                endpoint, attempt, CG_MAX_RETRIES, e,
            )
            if attempt < CG_MAX_RETRIES:
                time.sleep(CG_DELAY * attempt)
            return None
    return None


def fetch_coingecko_daily_supplement() -> pd.DataFrame | None:
    """Fetch daily BTC data from CoinGecko OHLC endpoint (free tier).

    The free tier's ohlc endpoint only returns ~90 days of data.
    This is supplemental — the main daily data comes from resampling hourly.

    Returns DataFrame with [datetime, open, high, low, close] or None.
    """
    log.info("Trying CoinGecko daily OHLC supplement (free tier)...")
    data = _cg_request("/coins/bitcoin/ohlc", {"vs_currency": "usd", "days": "90"})
    if data is None or not isinstance(data, list) or len(data) < 2:
        log.warning("CoinGecko daily OHLC unavailable (free tier limited) — will use Binance-only")
        return None

    df = pd.DataFrame(data, columns=["timestamp", "open", "high", "low", "close"])
    df["datetime"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
    df = df.sort_values("datetime").reset_index(drop=True)
    log.info("CoinGecko daily supplement: %d rows, %s -> %s",
             len(df), df["datetime"].min().isoformat(), df["datetime"].max().isoformat())
    return df


def fetch_coingecko_btc_dominance() -> float | None:
    """Fetch current BTC dominance from CoinGecko global data.

    Returns percentage (e.g., 42.5) or None if unavailable.
    """
    data = _cg_request("/global")
    if data is None:
        return None
    try:
        btc_d = data.get("data", {}).get("market_cap_percentage", {}).get("btc")
        return float(btc_d) if btc_d is not None else None
    except (TypeError, ValueError) as e:
        log.warning("Failed to parse BTC dominance: %s", e)
        return None


# ---------------------------------------------------------------------------
# 3. Volatility and derived-metric calculations
# ---------------------------------------------------------------------------


def calc_hourly_returns(hourly_df: pd.DataFrame, price_col: str = "close") -> pd.Series:
    """Calculate log hourly returns from close prices."""
    prices = hourly_df[price_col].sort_values()
    log_returns = np.log(prices / prices.shift(1))
    log_returns.name = "hourly_log_return"
    return log_returns


def calc_realized_volatility(
    hourly_returns: pd.Series,
    windows_days: list[int] | None = None,
) -> pd.DataFrame:
    """Calculate rolling realized volatility, annualized, from hourly returns.

    Parameters
    ----------
    hourly_returns : pd.Series with DatetimeIndex
    windows_days : list of int — rolling window lengths in days

    Returns
    -------
    pd.DataFrame with columns like rv_7d, rv_14d, rv_30d plus label columns.
    """
    if windows_days is None:
        windows_days = VOL_WINDOWS

    result = pd.DataFrame(index=hourly_returns.index)
    result["hourly_log_return"] = hourly_returns

    for w in windows_days:
        n_hours = w * 24
        min_periods = min(n_hours, 168)  # at least 1 week minimum for small windows
        rv = (
            hourly_returns.rolling(window=n_hours, min_periods=min_periods)
            .std(ddof=1)
            * np.sqrt(24 * 365)
        )
        result[f"rv_{w}d"] = rv
        result[f"rv_{w}d_label"] = rv.apply(
            lambda x: f"{x*100:.1f}%" if pd.notna(x) else ""
        )

    return result


def calc_daily_metrics(daily_ohlc: pd.DataFrame) -> pd.DataFrame:
    """Calculate daily returns, max drawdown from ATH from daily OHLCV data.

    Parameters
    ----------
    daily_ohlc : DataFrame with columns: datetime, open, high, low, close, volume

    Returns
    -------
    DataFrame with additional columns: daily_return, daily_return_pct,
    ath, drawdown_from_ath, drawdown_pct
    """
    df = daily_ohlc.sort_values("datetime").reset_index(drop=True)

    # Daily returns
    df["daily_return"] = df["close"].pct_change()
    df["daily_return_pct"] = df["daily_return"] * 100

    # Max drawdown from ATH
    df["cummax"] = df["close"].cummax()
    df["drawdown_from_ath"] = df["close"] - df["cummax"]
    df["drawdown_pct"] = (df["close"] / df["cummax"] - 1) * 100

    return df


def resample_hourly_to_daily(hourly_df: pd.DataFrame) -> pd.DataFrame:
    """Resample hourly OHLCV data to daily frequency.

    Parameters
    ----------
    hourly_df : DataFrame with columns: datetime, open, high, low, close, volume, ...

    Returns
    -------
    DataFrame with daily OHLCV (plus quote_volume, trades).
    """
    hourly = hourly_df.set_index("datetime").sort_index()
    daily = hourly.resample("D").agg({
        "open": "first",
        "high": "max",
        "low": "min",
        "close": "last",
        "volume": "sum",
        "quote_volume": "sum",
        "trades": "sum",
        "taker_buy_volume": "sum",
        "taker_buy_quote_volume": "sum",
    }).dropna(subset=["close"])

    daily = daily.reset_index()
    return daily


# ---------------------------------------------------------------------------
# 4. Data loading and saving helpers
# ---------------------------------------------------------------------------


def save_csv(df: pd.DataFrame, path: str, index: bool = False) -> None:
    """Save DataFrame to CSV with logging."""
    df.to_csv(path, index=index)
    log.info("Saved %d rows -> %s", len(df), path)


# ---------------------------------------------------------------------------
# 5. Main pipeline
# ---------------------------------------------------------------------------


def fetch_binance_hourly() -> pd.DataFrame:
    """Fetch and return hourly OHLCV from Binance."""
    log.info("Fetching hourly BTC/USDT from Binance...")
    records = binance_klines(
        symbol="BTCUSDT",
        interval="1h",
        start_time=START_DATE,
    )

    if not records:
        log.error("No data returned from Binance — check network/API availability")
        return pd.DataFrame()

    df = pd.DataFrame(records)
    df["datetime"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
    df = df.sort_values("datetime").reset_index(drop=True)
    df = df.drop_duplicates(subset="datetime")

    log.info("Binance hourly data: %d rows, %s -> %s",
             len(df),
             df["datetime"].min().isoformat(),
             df["datetime"].max().isoformat())
    return df


def compute_volatility_pipeline(
    hourly_df: pd.DataFrame,
    cg_daily_df: pd.DataFrame | None,
    btc_dominance: float | None,
) -> pd.DataFrame:
    """Compute realized volatility metrics merged with daily data.

    Parameters
    ----------
    hourly_df : DataFrame with hourly OHLCV from Binance
    cg_daily_df : Optional DataFrame with daily CoinGecko data (for market_cap)
    btc_dominance : Optional current BTC dominance percentage

    Returns
    -------
    DataFrame with daily frequency containing prices, returns, volatility,
    drawdown, volume, and ancillary data.
    """
    if hourly_df.empty:
        log.error("Cannot compute volatility — no hourly data")
        return pd.DataFrame()

    hourly_ts = hourly_df.set_index("datetime").sort_index()

    # --- Hourly returns & realized volatility ---
    log.info("Computing hourly returns...")
    hourly_returns = calc_hourly_returns(hourly_ts)
    log.info("Computing rolling realized volatility (7d, 14d, 30d)...")
    vol_df = calc_realized_volatility(hourly_returns)

    # Resample vol to daily (last observation each day)
    vol_cols = [f"rv_{w}d" for w in VOL_WINDOWS]
    vol_label_cols = [f"rv_{w}d_label" for w in VOL_WINDOWS]
    vol_daily = vol_df[vol_cols + vol_label_cols].resample("D").last()

    # --- Daily metrics from hourly OHLCV resampled ---
    log.info("Resampling hourly -> daily...")
    daily_ohlc = resample_hourly_to_daily(hourly_df)
    daily_metrics = calc_daily_metrics(daily_ohlc)

    daily_metrics["datetime"] = pd.to_datetime(daily_metrics["datetime"], utc=True)

    # --- Merge volatility into daily metrics ---
    vol_daily_reset = vol_daily.reset_index()
    vol_daily_reset["datetime"] = pd.to_datetime(vol_daily_reset["datetime"], utc=True)

    combined = daily_metrics.merge(vol_daily_reset, on="datetime", how="left")

    # --- Hourly observation count per day (data quality check) ---
    hourly_counts = hourly_ts.resample("D").size()
    combined = combined.merge(
        hourly_counts.rename("n_hourly_obs").reset_index(),
        on="datetime",
        how="left",
    )

    # --- CoinGecko supplemental: market cap ---
    combined["market_cap"] = np.nan
    if cg_daily_df is not None and not cg_daily_df.empty:
        cg = cg_daily_df[["datetime", "close"]].copy()
        cg = cg.rename(columns={"close": "cg_close"})
        cg["datetime"] = pd.to_datetime(cg["datetime"], utc=True)
        # Merge available days — they overlap recent period only
        combined = combined.merge(cg, on="datetime", how="left")
        # Market cap proxy: for rows where we have CG data, we could estimate
        # but mostly just flag availability
        log.info("CoinGecko supplement merged: %d overlapping days",
                 cg["datetime"].isin(combined["datetime"]).sum())

    # --- BTC dominance snapshot ---
    if btc_dominance is not None:
        combined["btc_dominance_pct"] = btc_dominance
        log.info("BTC dominance: %.1f%%", btc_dominance)
    else:
        combined["btc_dominance_pct"] = np.nan

    return combined


def main() -> int:
    """Main entry point for the data pipeline."""
    log.info("=" * 60)
    log.info("BTC Price & Volatility Data Pipeline")
    log.info("Start: %s", datetime.now(timezone.utc).isoformat())
    log.info("=" * 60)

    exit_code = 0

    # -------------------------------------------------------------------
    # Step 1: Fetch hourly OHLCV from Binance
    # -------------------------------------------------------------------
    log.info("\n--- Step 1: Binance Hourly OHLCV ---")
    hourly_df = fetch_binance_hourly()
    if not hourly_df.empty:
        save_csv(hourly_df, OUTPUT_HOURLY)
    else:
        log.error("No hourly data — pipeline cannot continue")
        return 1

    # -------------------------------------------------------------------
    # Step 2: Supplemental daily data from CoinGecko
    # -------------------------------------------------------------------
    log.info("\n--- Step 2: CoinGecko Supplemental Data ---")
    cg_daily = fetch_coingecko_daily_supplement()
    if cg_daily is not None:
        save_csv(cg_daily, OUTPUT_DAILY)
    else:
        log.warning("CoinGecko daily supplement unavailable — will use Binance-only for daily")
        # Write a placeholder daily derived from hourly later
        pass

    # -------------------------------------------------------------------
    # Step 3: BTC dominance snapshot
    # -------------------------------------------------------------------
    log.info("\n--- Step 3: BTC Dominance ---")
    btc_dom = fetch_coingecko_btc_dominance()

    # -------------------------------------------------------------------
    # Step 4: Compute volatility metrics
    # -------------------------------------------------------------------
    log.info("\n--- Step 4: Volatility Computation ---")
    vol_data = compute_volatility_pipeline(hourly_df, cg_daily, btc_dom)
    if not vol_data.empty:
        # Write daily OHLCV if CG wasn't available (resampled from hourly)
        if cg_daily is None:
            daily_cols = ["datetime", "open", "high", "low", "close", "volume",
                          "quote_volume", "trades"]
            daily_out = vol_data[[c for c in daily_cols if c in vol_data.columns]].copy()
            save_csv(daily_out, OUTPUT_DAILY)

        save_csv(vol_data, OUTPUT_VOLATILITY)

        # --- Summary statistics ---
        log.info("\n--- Summary ---")
        log.info("Date range: %s -> %s",
                 vol_data["datetime"].min(), vol_data["datetime"].max())
        log.info("Daily records: %d", len(vol_data))

        latest = vol_data.iloc[-1]
        log.info("Latest close: $%.2f", latest.get("close", 0))

        rv30 = latest.get("rv_30d")
        if pd.notna(rv30):
            log.info("Latest 30d realized vol: %.1f%% (annualized)", rv30 * 100)
        log.info("Max drawdown (all time): %.1f%%",
                 vol_data["drawdown_pct"].min())

        dom = latest.get("btc_dominance_pct")
        if pd.notna(dom):
            log.info("BTC dominance snapshot: %.1f%%", dom)

        for w in VOL_WINDOWS:
            col = f"rv_{w}d"
            if col in vol_data.columns:
                vals = vol_data[col].dropna()
                if not vals.empty:
                    log.info("%d-day realized vol: mean=%.1f%%, median=%.1f%%, max=%.1f%%",
                             w, vals.mean() * 100, vals.median() * 100, vals.max() * 100)

        # Check for missing hourly obs (days with < 24 candles)
        incomplete_days = vol_data[vol_data["n_hourly_obs"] < 12]
        if not incomplete_days.empty:
            log.warning("Days with <12 hourly observations: %d", len(incomplete_days))
    else:
        log.error("Volatility computation returned no data")
        exit_code = 1

    # -------------------------------------------------------------------
    # Final file listing
    # -------------------------------------------------------------------
    log.info("\n--- Output Files ---")
    for f in [OUTPUT_HOURLY, OUTPUT_DAILY, OUTPUT_VOLATILITY]:
        if os.path.exists(f):
            size_kb = os.path.getsize(f) / 1024
            log.info("  ✓ %s (%.1f KB)", f, size_kb)
        else:
            log.info("  ✗ %s (NOT WRITTEN)", f)

    log.info("\nPipeline complete (exit=%d)", exit_code)
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
