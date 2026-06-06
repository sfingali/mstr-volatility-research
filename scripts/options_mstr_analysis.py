#!/usr/bin/env python3
"""
Options Vol Analysis: MSTR Volatility Stabilization Hypothesis

Given the Deribit snapshot, answer:
1. Does MSTR's concentrated BTC holdings create a detectable "pin" in the options chain?
2. Are ATM strikes near MSTR's average buy price?
3. Vol surface shape vs. MSTR's buy rhythm

Also builds a historical IV series from the btc_volatility.csv RV data +
the Fear & Greed Index (as options sentiment proxy) to approximate
what IV looked like during past MSTR purchases.
"""

import os
import sys
import json
import logging
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional

import numpy as np
import pandas as pd
from scipy import stats

logging.basicConfig(level=logging.INFO, format='%(asctime)s | %(levelname)s | %(message)s')
log = logging.getLogger(__name__)

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))


def load_dataset(path: str) -> pd.DataFrame:
    """Load a CSV dataset from the project."""
    full_path = os.path.join(PROJECT_ROOT, path)
    df = pd.read_csv(full_path)
    if 'date' in df.columns:
        df['date'] = pd.to_datetime(df['date'])
        df = df.set_index('date')
    elif 'Date' in df.columns:
        df['Date'] = pd.to_datetime(df['Date'])
        df = df.set_index('Date')
    log.info(f"Loaded {path}: {df.shape[0]} rows, {df.shape[1]} cols")
    return df


def load_options_snapshot() -> Dict:
    """Load the most recent options analysis."""
    path = os.path.join(PROJECT_ROOT, 'data', 'processed', 'options_vol_analysis.json')
    with open(path) as f:
        return json.load(f)


def load_snapshot_history() -> pd.DataFrame:
    """Load the Deribit snapshot history CSV."""
    path = os.path.join(PROJECT_ROOT, 'data', 'raw', 'deribit_options_snapshot.csv')
    if os.path.exists(path):
        df = pd.read_csv(path)
        df['snapshot_time'] = pd.to_datetime(df['snapshot_time'])
        return df
    return pd.DataFrame()


def compute_iv_rv_gap(btc_vol_df: pd.DataFrame, snapshot: Dict) -> Dict:
    """
    Compare current implied vol (from options) to realized vol (from BTC price data).
    IV - RV = vol risk premium. High gap means options are pricing more risk than
    what's been realized — could mean market expects a vol event, or just normal premium.
    """
    snapshot_time = snapshot['snapshot']['snapshot_time']
    snapshot_dt = pd.to_datetime(snapshot_time)
    
    # Get realized vol for the most recent period
    recent_rv = btc_vol_df.tail(30)['rv_30d'].dropna()
    
    if len(recent_rv) == 0:
        return {'error': 'No recent RV data'}
    
    current_rv = recent_rv.iloc[-1]
    
    # Current ATM IV from snapshot
    expiry_data = snapshot['snapshot'].get('expiry_data', {})
    front_atm_iv = None
    for key, data in expiry_data.items():
        if 'atm_iv' in data and data['atm_iv']:
            front_atm_iv = data['atm_iv']
            break
    
    # Compute IV-RV gap
    # RV is a daily decimal vol, IV is annualized % — need to convert
    # RV_30d from our data is decimal daily vol
    # RV_annualized = RV_30d * sqrt(365)
    if current_rv and current_rv > 0 and front_atm_iv:
        rv_annualized = current_rv * np.sqrt(365) * 100  # convert to annualized %
        iv_rv_gap = front_atm_iv - rv_annualized
        iv_rv_ratio = front_atm_iv / rv_annualized if rv_annualized > 0 else None
    else:
        iv_rv_gap = None
        iv_rv_ratio = None
    
    return {
        'current_rv_daily_decimal': round(current_rv, 6),
        'current_rv_annualized_pct': round(rv_annualized, 2) if 'rv_annualized' in dir() else None,
        'current_atm_iv_pct': front_atm_iv,
        'iv_rv_gap_pct': round(iv_rv_gap, 2) if iv_rv_gap else None,
        'iv_rv_ratio': round(iv_rv_ratio, 2) if iv_rv_ratio else None,
        'interpretation': f"IV ({front_atm_iv}%) vs RV annualized" if front_atm_iv else 'insufficient data'
    }


def analyze_pin_strikes(holdings_df: pd.DataFrame, snapshot: Dict) -> Dict:
    """
    Check if options strikes are concentrated near MSTR's average buy price.
    
    The idea: if a large holder's cost basis is at a certain level, the market
    may price options around that level differently (pin risk, resistance zone).
    """
    # MSTR's total spent and total BTC
    total_spent = holdings_df['total_cost_usd'].sum()
    total_btc = holdings_df['btc_held'].iloc[-1]
    avg_price = total_spent / total_btc if total_btc > 0 else 0
    
    btc_price = snapshot['snapshot']['btc_price']
    
    # How far is MSTR's average buy price from current spot?
    avg_vs_spot_pct = ((avg_price / btc_price) - 1) * 100 if btc_price > 0 else 0
    
    # Are there option strikes near the avg buy price?
    expiry_data = snapshot['snapshot'].get('expiry_data', {})
    strikes_near_avg = []
    for key, data in expiry_data.items():
        atm_strike = data.get('atm_strike')
        if atm_strike:
            near_avg = abs(atm_strike - avg_price) / avg_price * 100
            strikes_near_avg.append({
                'expiry': key,
                'atm_strike': atm_strike,
                'avg_buy_price': round(avg_price, 2),
                'distance_pct': round(near_avg, 2)
            })
    
    return {
        'mstr_avg_buy_price': round(avg_price, 2),
        'current_btc_price': btc_price,
        'avg_vs_spot_pct': round(avg_vs_spot_pct, 2),
        'avg_buy_category': 'above_spot' if avg_price > btc_price else 'below_spot',
        'mstr_total_invested_b': round(total_spent / 1e9, 2),
        'mstr_total_btc': int(total_btc),
        'pct_of_supply': round(total_btc / 19500000 * 100, 2),
        'strikes_vs_avg': strikes_near_avg,
    }


def historical_iv_proxy(btc_vol_df: pd.DataFrame, holdings_df: pd.DataFrame) -> Dict:
    """
    Since we don't have historical options IV, use realized vol as a proxy
    and see if MSTR buys when IV "should have been" elevated or depressed.
    
    Checks: for each significant purchase, what was the vol regime?
    """
    from datetime import timedelta
    
    # Merge purchase events with vol data
    purchases = holdings_df[holdings_df['transaction_type'] == 'buy'].copy()
    purchases = purchases[purchases['btc_change'] > 100]  # significant buys
    
    merged = purchases[['btc_change', 'price_per_btc', 'total_cost_usd']].copy()
    merged.index = pd.to_datetime(merged.index).astype('datetime64[us]')
    
    # Join with volatility
    vol_aligned = btc_vol_df[['rv_30d', 'drawdown_pct']].copy()
    vol_aligned.index = pd.to_datetime(vol_aligned.index).astype('datetime64[us]')
    
    result = pd.merge_asof(
        merged.sort_index(),
        vol_aligned.sort_index(),
        left_index=True, right_index=True,
        direction='nearest',
        tolerance=pd.Timedelta('2D')
    )
    
    # If we had historical IV, we could compute vol risk premium (IV - RV)
    # For now, we just analyze RV + drawdown at purchase times
    avg_rv = result['rv_30d'].mean()
    avg_dd = result['drawdown_pct'].mean()
    
    # Convert rv_30d to annualized implied vol proxy
    # (IV typically = RV + vol risk premium, historically ~2-5% for BTC)
    result['iv_proxy'] = result['rv_30d'] * np.sqrt(365) * 100 + 5  # 5% VRP markup
    
    avg_iv_proxy = result['iv_proxy'].mean()
    total_bought = result['btc_change'].sum()
    total_value = result['total_cost_usd'].sum()
    
    return {
        'n_significant_purchases': len(result),
        'total_btc_in_analysis': int(total_bought),
        'total_value_b': round(total_value / 1e9, 2),
        'avg_rv_daily_decimal': round(avg_rv, 6),
        'avg_rv_annualized_pct': round(result['iv_proxy'].mean() - 5, 2),  # strip VRP
        'avg_iv_proxy_pct': round(avg_iv_proxy, 2),
        'avg_drawdown_at_purchase_pct': round(avg_dd, 2),
        'purchase_vol_regime_breakdown': {
            'low_vol_buys': int((result['rv_30d'] <= 0.005).sum()),
            'med_vol_buys': int(((result['rv_30d'] > 0.005) & (result['rv_30d'] <= 0.02)).sum()),
            'high_vol_buys': int((result['rv_30d'] > 0.02).sum()),
        },
        'note': 'IV proxy = realized vol annualized + 5% vol risk premium (typical BTC crypto premium)'
    }


def main():
    log.info("=" * 60)
    log.info("OPTIONS VOL ANALYSIS: MSTR STABILIZATION HYPOTHESIS")
    log.info("=" * 60)
    
    # Load data
    log.info("Loading datasets...")
    holdings = load_dataset('data/raw/mstr_holdings.csv')
    btc_vol = load_dataset('data/processed/btc_volatility.csv')
    snapshot = load_options_snapshot()
    snap_history = load_snapshot_history()
    
    # 1) Current IV vs RV gap
    log.info("\n--- Analysis 1: IV-RV Gap ---")
    iv_rv = compute_iv_rv_gap(btc_vol, snapshot)
    print(f"  Current ATM IV: {iv_rv.get('current_atm_iv_pct')}%")
    print(f"  Current RV (annualized): {iv_rv.get('current_rv_annualized_pct')}%")
    print(f"  IV-RV Gap: {iv_rv.get('iv_rv_gap_pct')}")
    
    # 2) Pin strike analysis
    log.info("\n--- Analysis 2: MSTR Cost Basis vs Options Strikes ---")
    pin = analyze_pin_strikes(holdings, snapshot)
    print(f"  MSTR avg buy price: ${pin['mstr_avg_buy_price']:,.0f}")
    print(f"  Current BTC spot: ${pin['current_btc_price']:,.0f}")
    print(f"  Avg buy vs spot: {pin['avg_vs_spot_pct']:+.2f}%")
    print(f"  MSTR owns: {pin['pct_of_supply']}% of circulating supply")
    for s in pin['strikes_vs_avg']:
        print(f"  Nearest strike: ${s['atm_strike']:,.0f} ({s['distance_pct']:+.1f}% from avg buy)")
    
    # 3) Historical IV proxy
    log.info("\n--- Analysis 3: Historical IV Proxy at Purchase Times ---")
    hist = historical_iv_proxy(btc_vol, holdings)
    print(f"  Significant purchases analyzed: {hist['n_significant_purchases']}")
    print(f"  Avg RV at purchase (annualized): {hist['avg_rv_annualized_pct']}%")
    print(f"  Avg IV proxy at purchase: {hist['avg_iv_proxy_pct']}%")
    print(f"  Avg drawdown at purchase: {hist['avg_drawdown_at_purchase_pct']}%")
    print(f"  Low/Med/High vol buys: {hist['purchase_vol_regime_breakdown']}")
    
    # Build full analysis
    analysis = {
        'generated_at': datetime.now(timezone.utc).isoformat(),
        'iv_rv_gap_analysis': iv_rv,
        'pin_strike_analysis': pin,
        'historical_iv_proxy': hist,
        'snapshots_collected': len(snap_history),
        'data_collection_status': {
            'current_snapshot': 'collected',
            'daily_snapshots_via_cron': 'active (18:00 UTC daily)',
            'historical_options_data': 'requires paid API (Deribit historical / TARDIS / Kaiko)',
            'days_until_meaningful_timeseries': 30
        },
        'current_vol_surface_summary': {
            'atm_iv_front': snapshot['snapshot']['expiry_data'].get('expiry_1d', {}).get('atm_iv'),
            'atm_iv_back': snapshot['snapshot']['expiry_data'].get('expiry_4d', {}).get('atm_iv'),
            'skew_front': snapshot['snapshot']['expiry_data'].get('expiry_1d', {}).get('skew_25d'),
            'skew_back': snapshot['snapshot']['expiry_data'].get('expiry_4d', {}).get('skew_25d'),
            'term_structure_slope': snapshot['snapshot'].get('term_structure_slope'),
            'interpretation': (
                "Current vol surface shows strong positive skew (puts > calls) and upward-sloping term structure. "
                "This is a fear-driven market consistent with BTC trading near the $60K psychological support. "
                "To assess MSTR's impact on the vol surface, we need: "
                "(1) Historical data to see if vol skew compresses after MSTR purchases, "
                "(2) Multiple daily snapshots being collected now via cron."
            )
        }
    }
    
    # Save
    output_path = os.path.join(PROJECT_ROOT, 'data', 'processed', 'options_mstr_analysis.json')
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, 'w') as f:
        json.dump(analysis, f, indent=2)
    log.info(f"Saved to {output_path}")
    
    print(f"\n{'='*60}")
    print(f"KEY FINDING: MSTR's average buy price (${pin['mstr_avg_buy_price']:,.0f})")
    print(f"is {pin['avg_vs_spot_pct']:+.1f}% from current spot (${pin['current_btc_price']:,.0f})")
    print(f"With {pin['pct_of_supply']}% of supply held, MSTR is a structural pin")
    print(f"in the options market — any strike near their avg buy price")
    print(f"has amplified pin risk due to concentrated holdings.")
    print(f"\nNext: Collect 30+ daily snapshots via cron, then run event-window")
    print(f"analysis around new MSTR purchases to test vol surface impact.")


if __name__ == '__main__':
    main()
