#!/usr/bin/env python3
"""
MSTR Equity Data Pipeline

Collects MSTR (MicroStrategy / Strategy) equity data:
  1. Daily OHLCV price data from Yahoo Finance (2020-01-01 → present)
  2. Historical shares outstanding (dilution from ATM programs)
  3. Hardcoded convertible debt issuance history with SEC filing URLs
  4. NAV premium calculation (MSTR market cap / BTC holdings value)
  5. Leverage ratio calculation

Outputs:
  - data/raw/mstr_equity.csv       — Daily OHLCV, shares, BTC price, calculated metrics
  - data/processed/mstr_debt_issuances.csv — Structured debt issuance records
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import os
import sys
from dataclasses import dataclass, field, asdict
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

import yfinance as yf

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_RAW = PROJECT_ROOT / "data" / "raw"
DATA_PROCESSED = PROJECT_ROOT / "data" / "processed"

# Ensure output directories exist
DATA_RAW.mkdir(parents=True, exist_ok=True)
DATA_PROCESSED.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
)
log = logging.getLogger("collect_mstr_equity")

# ---------------------------------------------------------------------------
# Known convertible debt issuances (hardcoded from SEC filings)
# Each entry = (announce_date, principal_usd, coupon_pct, maturity_year, sec_url)
# ---------------------------------------------------------------------------

DEBT_ISSUANCES: list[dict[str, Any]] = [
    {
        "announce_date": "2020-12-09",
        "principal_amount": 650_000_000,
        "coupon_rate": 0.0075,
        "maturity_year": 2025,
        "description": "0.75% Convertible Senior Notes due 2025",
        "sec_url": "https://www.sec.gov/Archives/edgar/data/1050446/000110465920140240/tm2034715d1_8k.htm",
    },
    {
        "announce_date": "2021-02-17",
        "principal_amount": 1_050_000_000,
        "coupon_rate": 0.0,
        "maturity_year": 2027,
        "description": "0% Convertible Senior Notes due 2027",
        "sec_url": "https://www.sec.gov/Archives/edgar/data/1050446/000110465921018198/tm215332d1_8k.htm",
    },
    {
        "announce_date": "2021-06-14",
        "principal_amount": 500_000_000,
        "coupon_rate": 0.06125,
        "maturity_year": 2028,
        "description": "6.125% Convertible Senior Notes due 2028",
        "sec_url": "https://www.sec.gov/Archives/edgar/data/1050446/000110465921081454/tm2119401d1_8k.htm",
    },
    {
        "announce_date": "2021-11-18",
        "principal_amount": 500_000_000,
        "coupon_rate": 0.0,
        "maturity_year": 2028,
        "description": "0% Convertible Senior Notes due 2028",
        "sec_url": "https://www.sec.gov/Archives/edgar/data/1050446/000110465921143047/tm2128768d1_8k.htm",
    },
    {
        "announce_date": "2022-03-15",
        "principal_amount": 205_000_000,
        "coupon_rate": 0.0,
        "maturity_year": 2032,
        "description": "0% Convertible Senior Notes due 2032",
        "sec_url": "https://www.sec.gov/Archives/edgar/data/1050446/000110465922036858/tm228127d1_8k.htm",
    },
    {
        "announce_date": "2024-03-08",
        "principal_amount": 800_000_000,
        "coupon_rate": 0.00625,
        "maturity_year": 2030,
        "description": "0.625% Convertible Senior Notes due 2030",
        "sec_url": "https://www.sec.gov/Archives/edgar/data/1050446/000110465924027144/tm246245d1_8k.htm",
    },
    {
        "announce_date": "2024-06-14",
        "principal_amount": 800_000_000,
        "coupon_rate": 0.0225,
        "maturity_year": 2032,
        "description": "2.25% Convertible Senior Notes due 2032",
        "sec_url": "https://www.sec.gov/Archives/edgar/data/1050446/000110465924065610/tm2414440d1_8k.htm",
    },
    {
        "announce_date": "2024-09-17",
        "principal_amount": 1_010_000_000,
        "coupon_rate": 0.00875,
        "maturity_year": 2028,
        "description": "0.875% Convertible Senior Notes due 2028",
        "sec_url": "https://www.sec.gov/Archives/edgar/data/1050446/000110465924103528/tm2422850d1_8k.htm",
    },
    {
        "announce_date": "2024-11-20",
        "principal_amount": 3_000_000_000,
        "coupon_rate": 0.0,
        "maturity_year": 2029,
        "description": "0% Convertible Senior Notes due 2029",
        "sec_url": "https://www.sec.gov/Archives/edgar/data/1050446/000110465924121082/tm2429283d1_8k.htm",
    },
    {
        "announce_date": "2025-03-03",
        "principal_amount": 2_080_000_000,
        "coupon_rate": 0.0,
        "maturity_year": 2030,
        "description": "0% Convertible Senior Notes due 2030",
        "sec_url": "https://www.sec.gov/Archives/edgar/data/1050446/000110465925023861/tm2510678d1_8k.htm",
    },
    {
        "announce_date": "2025-06-04",
        "principal_amount": 700_000_000,
        "coupon_rate": None,
        "maturity_year": None,
        "description": "Convertible Senior Notes due ~2032 (terms TBD at time of writing)",
        "sec_url": "https://www.sec.gov/Archives/edgar/data/1050446/000110465925062472/tm2516887d1_8k.htm",
    },
]

# ---------------------------------------------------------------------------
# BTC holdings snapshots (known public disclosures)
# These are the best-known data points; for full granularity use saylortracker.com
# ---------------------------------------------------------------------------

BTC_HOLDINGS_SNAPSHOTS: list[dict[str, Any]] = [
    {"date": "2020-08-11", "btc": 21454},
    {"date": "2020-09-15", "btc": 38250},
    {"date": "2020-12-21", "btc": 70470},
    {"date": "2021-02-18", "btc": 90253},
    {"date": "2021-03-01", "btc": 90859},
    {"date": "2021-06-15", "btc": 105085},
    {"date": "2021-06-29", "btc": 105085},
    {"date": "2021-11-30", "btc": 121044},
    {"date": "2022-03-31", "btc": 129218},
    {"date": "2022-06-30", "btc": 129699},
    {"date": "2022-12-31", "btc": 132500},
    {"date": "2023-03-31", "btc": 140000},
    {"date": "2023-06-30", "btc": 152333},
    {"date": "2023-09-30", "btc": 158245},
    {"date": "2023-12-31", "btc": 189150},
    {"date": "2024-03-11", "btc": 205000},
    {"date": "2024-03-31", "btc": 214246},
    {"date": "2024-06-14", "btc": 214400},
    {"date": "2024-09-13", "btc": 244100},
    {"date": "2024-09-30", "btc": 252220},
    {"date": "2024-11-11", "btc": 280000},
    {"date": "2024-12-09", "btc": 423650},
    {"date": "2024-12-31", "btc": 447470},
    {"date": "2025-01-31", "btc": 471107},
    {"date": "2025-02-24", "btc": 499096},
    {"date": "2025-03-31", "btc": 528615},
    {"date": "2025-04-30", "btc": 544809},
]


# ===================================================================
# Data Fetching Functions
# ===================================================================


def fetch_mstr_ohlcv(
    start_date: str = "2020-01-01",
    end_date: Optional[str] = None,
) -> yf.DataFrame:
    """
    Fetch daily OHLCV data for MSTR from Yahoo Finance.

    Parameters
    ----------
    start_date : str
        YYYY-MM-DD start date.
    end_date : str or None
        YYYY-MM-DD end date. Defaults to today.

    Returns
    -------
    pd.DataFrame with columns: Open, High, Low, Close, Volume
    """
    log.info("Fetching MSTR OHLCV from %s to %s", start_date, end_date or "today")
    ticker = yf.Ticker("MSTR")
    df = ticker.history(start=start_date, end=end_date, auto_adjust=False)
    if df.empty:
        log.warning("No MSTR price data returned from Yahoo Finance")
    else:
        log.info("Retrieved %d rows of MSTR price data", len(df))
    return df


def fetch_btc_price(
    start_date: str = "2020-01-01",
    end_date: Optional[str] = None,
) -> yf.DataFrame:
    """
    Fetch daily BTC-USD close prices from Yahoo Finance.

    Parameters
    ----------
    start_date : str
        YYYY-MM-DD start date.
    end_date : str or None
        YYYY-MM-DD end date. Defaults to today.

    Returns
    -------
    pd.Series of daily close prices indexed by date.
    """
    log.info("Fetching BTC-USD price from %s to %s", start_date, end_date or "today")
    ticker = yf.Ticker("BTC-USD")
    df = ticker.history(start=start_date, end=end_date, auto_adjust=False)
    if df.empty:
        log.warning("No BTC-USD price data returned from Yahoo Finance")
    else:
        log.info("Retrieved %d rows of BTC price data", len(df))
    return df


def fetch_historical_shares(ticker: yf.Ticker) -> pd.DataFrame:
    """
    Fetch historical shares outstanding from yfinance.

    yfinance provides shares outstanding via the 'shares' attribute which
    returns a DataFrame of share counts over time (quarterly updates from
    10-Q / 10-K filings).

    Parameters
    ----------
    ticker : yf.Ticker
        Pre-loaded ticker object.

    Returns
    -------
    pd.DataFrame with share count indexed by date.
    """
    log.info("Fetching historical shares outstanding")
    try:
        shares = ticker.get_shares_full(start="2020-01-01")
        if shares is not None and not shares.empty:
            log.info("Got %d share count data points", len(shares))
            return shares.to_frame(name="shares_outstanding")
        else:
            log.warning("No shares outstanding data available")
            return pd.DataFrame()
    except Exception as exc:
        log.warning("Could not fetch shares outstanding: %s", exc)
        return pd.DataFrame()


def load_btc_holdings_csv() -> Optional[pd.DataFrame]:
    """
    Try to load BTC holdings from data/raw/ if collect_holdings.py has run.
    """
    holdings_path = DATA_RAW / "mstr_btc_holdings.csv"
    if holdings_path.exists():
        log.info("Loading BTC holdings from %s", holdings_path)
        df = pd.read_csv(holdings_path, parse_dates=["date"])
        return df
    log.info("No BTC holdings file found at %s — will use hardcoded snapshots", holdings_path)
    return None


def build_btc_holdings_series(
    btc_snapshots: list[dict[str, Any]],
    price_index: pd.Index,
) -> pd.Series:
    """
    Build a daily BTC holdings series from known snapshot dates.
    Forward-fills between known data points, back-fills the first snapshot,
    and forward-fills the last snapshot to cover the entire date range.

    Parameters
    ----------
    btc_snapshots : list of dicts
        Each dict has keys 'date' (YYYY-MM-DD) and 'btc' (int).
    price_index : pd.Index
        Daily date index to align to.

    Returns
    -------
    pd.Series of daily BTC holdings, indexed by date.
    """
    import pandas as pd

    snap_df = pd.DataFrame(btc_snapshots)
    snap_df["date"] = pd.to_datetime(snap_df["date"])
    snap_df = snap_df.set_index("date").sort_index()
    snap_df["btc"] = snap_df["btc"].astype(float)

    # Reindex to daily, forward-fill, then back-fill for early dates
    holdings = snap_df["btc"].reindex(price_index, method="ffill")
    # If there are dates before the first snapshot, use the first snapshot value
    first_known = snap_df.index.min()
    holdings.loc[holdings.index < first_known] = snap_df.loc[first_known, "btc"]

    return holdings


# ===================================================================
# Calculation Functions
# ===================================================================


def compute_nav_premium(
    mstr_close: pd.Series,
    shares_outstanding: pd.Series,
    btc_price: pd.Series,
    btc_holdings: pd.Series,
) -> pd.Series:
    """
    Calculate MSTR NAV premium = (MSTR market cap) / (BTC holdings value).

    NAV premium > 1 means MSTR trades at a premium to its BTC holdings.
    NAV premium < 1 means MSTR trades at a discount.

    Parameters
    ----------
    mstr_close : pd.Series
        MSTR daily close price.
    shares_outstanding : pd.Series
        MSTR shares outstanding (diluted or basic).
    btc_price : pd.Series
        BTC-USD daily close price.
    btc_holdings : pd.Series
        MSTR BTC holdings count.

    Returns
    -------
    pd.Series of daily NAV premium ratio.
    """
    market_cap = mstr_close * shares_outstanding
    btc_value = btc_price * btc_holdings
    # Avoid division by zero
    btc_value = btc_value.replace(0, float("nan"))
    premium = market_cap / btc_value
    premium.name = "nav_premium"
    return premium


def compute_leverage_ratio(
    total_debt: float,
    market_cap: pd.Series,
) -> pd.Series:
    """
    Calculate leverage ratio as Total Debt / (Total Debt + Market Cap).

    This measures how much of the enterprise is funded by debt.
    Higher = more leveraged.

    Parameters
    ----------
    total_debt : float
        Total convertible debt outstanding (constant or time-varying).
    market_cap : pd.Series
        Daily MSTR market cap.

    Returns
    -------
    pd.Series of daily leverage ratio.
    """
    ratio = total_debt / (total_debt + market_cap)
    ratio.name = "leverage_ratio"
    return ratio


# ===================================================================
# Debt Issuance Helpers
# ===================================================================


def total_outstanding_debt(as_of_date: date) -> float:
    """
    Sum the principal of all convertible notes announced on or before as_of_date.
    """
    total = 0.0
    for iss in DEBT_ISSUANCES:
        ann_date = datetime.strptime(iss["announce_date"], "%Y-%m-%d").date()
        if ann_date <= as_of_date:
            total += iss["principal_amount"]
    return total


def debt_issuances_dataframe() -> "pd.DataFrame":
    """
    Return the hardcoded debt issuances as a clean DataFrame.
    """
    import pandas as pd

    df = pd.DataFrame(DEBT_ISSUANCES)
    df["announce_date"] = pd.to_datetime(df["announce_date"])
    df = df.sort_values("announce_date").reset_index(drop=True)
    return df


# ===================================================================
# Main Pipeline
# ===================================================================


def run_pipeline(
    start_date: str = "2020-01-01",
    end_date: Optional[str] = None,
    output_raw: Path = DATA_RAW / "mstr_equity.csv",
    output_debt: Path = DATA_PROCESSED / "mstr_debt_issuances.csv",
) -> None:
    """
    Run the full MSTR equity data pipeline.

    Steps:
      1. Fetch MSTR OHLCV
      2. Fetch BTC-USD price
      3. Fetch historical shares outstanding
      4. Build BTC holdings series (try CSV, fallback to hardcoded snapshots)
      5. Calculate NAV premium and leverage ratio
      6. Write output CSVs
    """
    import pandas as pd

    log.info("=" * 60)
    log.info("MSTR Equity Data Pipeline")
    log.info("=" * 60)

    # -- Step 1: MSTR OHLCV -------------------------------------------
    mstr_df = fetch_mstr_ohlcv(start_date, end_date)
    if mstr_df.empty:
        log.error("No MSTR price data — aborting pipeline")
        sys.exit(1)

    # Flatten MultiIndex columns if present (yfinance can return multi-level)
    if isinstance(mstr_df.columns, pd.MultiIndex):
        mstr_df.columns = mstr_df.columns.get_level_values(0)
    # Keep only OHLCV columns
    price_cols = ["Open", "High", "Low", "Close", "Volume"]
    for col in price_cols:
        if col not in mstr_df.columns:
            log.warning("Column '%s' not found in MSTR data", col)
    available_cols = [c for c in price_cols if c in mstr_df.columns]
    mstr_df = mstr_df[available_cols].copy()

    # -- Step 2: BTC price --------------------------------------------
    btc_df = fetch_btc_price(start_date, end_date)
    if not btc_df.empty:
        if isinstance(btc_df.columns, pd.MultiIndex):
            btc_df.columns = btc_df.columns.get_level_values(0)
        btc_close = btc_df["Close"].copy()
    else:
        log.warning("No BTC price data — NAV premium will be unavailable")
        btc_close = pd.Series(index=mstr_df.index, dtype=float)

    # Normalize index to just date (remove timezone)
    mstr_df.index = pd.to_datetime(mstr_df.index.date)
    mstr_df.index.name = "Date"
    btc_close.index = pd.to_datetime(btc_close.index.date)
    btc_close.index.name = "Date"

    # Align date ranges
    common_dates = mstr_df.index.intersection(btc_close.index)
    if len(common_dates) == 0 and not btc_close.empty:
        log.warning("No overlapping dates between MSTR and BTC data")
    mstr_df = mstr_df.loc[mstr_df.index.isin(common_dates)] if len(common_dates) > 0 else mstr_df

    # -- Step 3: Shares outstanding -----------------------------------
    ticker_mstr = yf.Ticker("MSTR")
    shares_df = fetch_historical_shares(ticker_mstr)

    if not shares_df.empty:
        shares_df.index = pd.to_datetime(shares_df.index.date)
        # Merge share counts into main dataframe (forward fill)
        mstr_df = mstr_df.join(shares_df, how="left")
        mstr_df["shares_outstanding"] = mstr_df["shares_outstanding"].ffill()
        # Some early dates may still be NaN — try to get current shares from info
        if mstr_df["shares_outstanding"].isna().all():
            try:
                info = ticker_mstr.info
                curr_shares = info.get("sharesOutstanding")
                if curr_shares:
                    mstr_df["shares_outstanding"] = curr_shares
                    log.info("Using current shares outstanding from info: %s", curr_shares)
            except Exception:
                pass
        # If still NaN, default to latest known value
        mstr_df["shares_outstanding"] = mstr_df["shares_outstanding"].ffill().bfill()
    else:
        # Fallback: try to get current shares outstanding
        try:
            info = ticker_mstr.info
            curr_shares = info.get("sharesOutstanding")
            if curr_shares:
                log.info("Using constant shares outstanding from Yahoo Finance info: %s", curr_shares)
                mstr_df["shares_outstanding"] = float(curr_shares)
            else:
                log.warning("No shares outstanding data available")
                mstr_df["shares_outstanding"] = float("nan")
        except Exception as exc:
            log.warning("Could not fetch shares info: %s", exc)
            mstr_df["shares_outstanding"] = float("nan")

    # -- Step 4: BTC holdings -----------------------------------------
    holdings_csv = load_btc_holdings_csv()
    if holdings_csv is not None and not holdings_csv.empty:
        holdings = build_btc_holdings_series(
            holdings_csv.to_dict("records"), mstr_df.index
        )
    else:
        holdings = build_btc_holdings_series(BTC_HOLDINGS_SNAPSHOTS, mstr_df.index)

    mstr_df["btc_holdings"] = holdings.reindex(mstr_df.index)

    # -- Step 5: BTC price joined -------------------------------------
    mstr_df["btc_price"] = btc_close.reindex(mstr_df.index)

    # -- Step 6: Calculated metrics -----------------------------------
    mstr_df["market_cap"] = mstr_df["Close"] * mstr_df["shares_outstanding"]

    # NAV premium
    mstr_df["btc_holdings_value"] = mstr_df["btc_holdings"] * mstr_df["btc_price"]
    mstr_df["nav_premium"] = mstr_df["market_cap"] / mstr_df["btc_holdings_value"].replace(
        0, float("nan")
    )

    # Leverage ratio (time-varying: debt increases as new notes are issued)
    debt_series = mstr_df.index.to_series().apply(
        lambda dt: total_outstanding_debt(dt.date())
    )
    mstr_df["total_debt"] = debt_series
    mstr_df["leverage_ratio"] = mstr_df["total_debt"] / (
        mstr_df["total_debt"] + mstr_df["market_cap"]
    )

    # -- Step 7: Write CSVs -------------------------------------------
    log.info("Writing MSTR equity data to %s", output_raw)
    mstr_df.to_csv(output_raw, float_format="%.6f")
    log.info("Wrote %d rows", len(mstr_df))

    debt_df = debt_issuances_dataframe()
    log.info("Writing debt issuances to %s", output_debt)
    debt_df.to_csv(output_debt, index=False, float_format="%.6f")
    log.info("Wrote %d debt issuance records", len(debt_df))

    log.info("Pipeline complete.")
    print(f"\n✓ MSTR equity data  -> {output_raw}")
    print(f"✓ Debt issuances    -> {output_debt}")
    print(f"  Total rows: {len(mstr_df)}")
    print(f"  Date range: {mstr_df.index[0].date()} → {mstr_df.index[-1].date()}")


# ===================================================================
# CLI
# ===================================================================


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="MSTR Equity Data Pipeline — collect price, shares, debt & calculate metrics",
    )
    parser.add_argument(
        "--start",
        default="2020-01-01",
        help="Start date YYYY-MM-DD (default: 2020-01-01)",
    )
    parser.add_argument(
        "--end",
        default=None,
        help="End date YYYY-MM-DD (default: today)",
    )
    parser.add_argument(
        "--output-raw",
        default=str(DATA_RAW / "mstr_equity.csv"),
        help=f"Output path for equity CSV (default: {DATA_RAW / 'mstr_equity.csv'})",
    )
    parser.add_argument(
        "--output-debt",
        default=str(DATA_PROCESSED / "mstr_debt_issuances.csv"),
        help=f"Output path for debt CSV (default: {DATA_PROCESSED / 'mstr_debt_issuances.csv'})",
    )
    parser.add_argument(
        "--list-debt",
        action="store_true",
        help="Print the hardcoded debt issuances table and exit",
    )
    return parser.parse_args(argv)


def main() -> None:
    args = parse_args()

    if args.list_debt:
        debt_df = debt_issuances_dataframe()
        print("\n=== MSTR Convertible Debt Issuances ===\n")
        print(debt_df.to_string(index=False))
        print()
        return

    run_pipeline(
        start_date=args.start,
        end_date=args.end,
        output_raw=Path(args.output_raw),
        output_debt=Path(args.output_debt),
    )


if __name__ == "__main__":
    # Late import so argparse and help don't require pandas
    import pandas as pd  # noqa: F811
    main()
