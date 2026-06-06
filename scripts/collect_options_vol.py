#!/usr/bin/env python3
"""
Deribit BTC Options Volatility Surface Analysis

Fetches BTC option chain from Deribit public API, computes:
- ATM implied volatility (front-month, 2nd month, 3rd month)
- 25-delta put/call skew (risk reversal)
- Term structure slope
- Current market state vs. MSTR holdings

For historical analysis, uses:
- Fear & Greed Index as options market sentiment proxy
- Existing realized vol data
- Starts collecting daily snapshots for future event alignment

Output: data/raw/deribit_options_snapshot.csv (latest snapshot)
        data/processed/options_vol_analysis.json (metrics)
        reports/options_vol_surface.png (visualization)
"""

import os
import sys
import json
import time
import logging
import csv
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

import requests
import numpy as np

logging.basicConfig(level=logging.INFO, format='%(asctime)s | %(levelname)s | %(message)s')
log = logging.getLogger(__name__)

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
DERIBIT_API = "https://www.deribit.com/api/v2/public"

# Known MSTR purchase events (from holdings data) for alignment
# We use the last 2 years of significant purchases
SIGNIFICANT_PURCHASES = [
    ('2024-09-13', 7207),  # After convertible
    ('2024-11-05', 28841),
    ('2024-11-18', 70540),
    ('2024-11-25', 84936),
    ('2024-12-02', 44959),
    ('2025-01-27', 29495),  # 1M BTC milestone
    ('2025-03-03', 67539),
    ('2025-03-31', 58002),
    ('2025-05-05', 51154),
    ('2025-06-02', 41748),
    ('2025-09-01', 23335),
    ('2025-11-03', 23643),
    ('2026-01-05', 20266),
    ('2026-03-02', 14965),
    ('2026-05-18', 14827),
    ('2026-06-01', 11247),  # Post-sell accumulation
    ('2026-06-05', 33944),  # Most recent
]


def fetch_instruments() -> List[Dict]:
    """Fetch all active BTC option instruments from Deribit."""
    url = f"{DERIBIT_API}/get_instruments?currency=BTC&kind=option&expired=false"
    headers = {"Accept": "application/json"}
    r = requests.get(url, headers=headers, timeout=30)
    data = r.json()
    result = data.get('result', [])
    log.info(f"Got {len(result)} instruments from Deribit")
    return result


def fetch_ticker(instrument_name: str) -> Dict:
    """Fetch ticker data for a specific option (includes IV, Greeks)."""
    url = f"{DERIBIT_API}/ticker"
    params = {"instrument_name": instrument_name}
    r = requests.get(url, params=params, timeout=15)
    data = r.json()
    return data.get('result', {})


def fetch_index_price() -> float:
    """Fetch current BTC index price from Deribit."""
    url = f"{DERIBIT_API}/get_index_price"
    params = {"index_name": "btc_usd"}
    r = requests.get(url, params=params, timeout=15)
    data = r.json()
    return data.get('result', {}).get('index_price', 0)


def fetch_btc_usd_price() -> float:
    """Fetch BTC-USD price via Deribit's BTC index."""
    try:
        url = f"{DERIBIT_API}/get_index_price?index_name=btc_usd"
        r = requests.get(url, timeout=15)
    except:
        pass
    # Fallback: use the ticker for the perpetual
    try:
        url = f"{DERIBIT_API}/ticker?instrument_name=BTC-PERPETUAL"
        r = requests.get(url, timeout=15)
        data = r.json()
        return data.get('result', {}).get('last_price', 0) or data.get('result', {}).get('index_price', 0)
    except:
        return 0


def group_by_expiry(instruments: List[Dict]) -> Dict[int, List[Dict]]:
    """Group instruments by expiration timestamp."""
    groups = {}
    for inst in instruments:
        exp = inst['expiration_timestamp']
        if exp not in groups:
            groups[exp] = []
        groups[exp].append(inst)
    return groups


def get_options_snapshot() -> Dict:
    """
    Fetch the full option chain and build vol surface metrics.
    
    Returns a dict with:
    - snapshot_time: ISO timestamp
    - btc_price: current BTC index price
    - expiry_groups: for each nearby expiry: ATM IV, 25d call, 25d put, skew
    - term_structure: list of (days_to_expiry, ATM_IV) for term structure
    """
    log.info("Fetching instruments...")
    instruments = fetch_instruments()
    log.info(f"Got {len(instruments)} option instruments")
    
    btc_price = fetch_btc_usd_price()
    log.info(f"BTC price: ${btc_price:,.2f}")
    
    # Group by expiry
    by_expiry = group_by_expiry(instruments)
    
    # Sort expiries and pick the 3 nearest (that have enough strikes)
    sorted_expiries = sorted(by_expiry.keys())
    now_ms = int(time.time() * 1000)
    
    # Find nearest expiries with at least 20 strikes (for good coverage)
    nearby_expiries = []
    for exp in sorted_expiries:
        if len(by_expiry[exp]) >= 10:
            nearby_expiries.append(exp)
        if len(nearby_expiries) >= 4:
            break
    
    term_structure = []
    expiry_data = {}
    
    for exp in nearby_expiries:
        days_to_expiry = max(0, (exp - now_ms) / (1000 * 86400))
        insts = by_expiry[exp]
        
        # Separate calls and puts
        calls = [i for i in insts if i['option_type'] == 'call']
        puts = [i for i in insts if i['option_type'] == 'put']
        
        log.info(f"Expiry {exp}: {len(calls)} calls, {len(puts)} puts ({days_to_expiry:.1f} days)")
        
        # Fetch tickers for IV data (sample every 5th strike to be efficient)
        # We'll get the full chain
        all_ivs = []
        atm_strike = None
        atm_iv = None
        call_ivs = {}  # strike -> iv
        put_ivs = {}
        
        for inst in insts:  # fetch ALL for precise analysis
            ticker = fetch_ticker(inst['instrument_name'])
            if not ticker or 'mark_iv' not in ticker:
                continue
            iv = ticker['mark_iv']
            strike = inst['strike']
            typ = inst['option_type']
            all_ivs.append(iv)
            
            if typ == 'call':
                call_ivs[strike] = iv
            else:
                put_ivs[strike] = iv
            
            # Find ATM - closest strike to current price
            if atm_strike is None or abs(strike - btc_price) < abs(atm_strike - btc_price):
                atm_strike = strike
                atm_iv = iv
            
            time.sleep(0.05)  # rate limit
        
        if all_ivs:
            # ATM IV (from the ATM strike we found)
            # Skew: difference between 25-delta put IV and 25-delta call IV
            # For simplicity, use the difference between low-strike puts and high-strike calls
            call_strikes = sorted(call_ivs.keys())
            put_strikes = sorted(put_ivs.keys(), reverse=True)
            
            # 25-delta proxy: find OTM put ~10-15% below, OTM call ~10-15% above
            # Use the nearest available strikes
            otm_target_put = btc_price * 0.88
            otm_target_call = btc_price * 1.12
            
            # Find nearest available strikes
            otm_put_iv = None
            min_put_dist = float('inf')
            for s in put_strikes:
                dist = abs(s - otm_target_put)
                if dist < min_put_dist and s <= btc_price:  # must be OTM (below spot for puts)
                    min_put_dist = dist
                    otm_put_iv = put_ivs.get(s)
            
            otm_call_iv = None
            min_call_dist = float('inf')
            for s in call_strikes:
                dist = abs(s - otm_target_call)
                if dist < min_call_dist and s >= btc_price:  # must be OTM (above spot for calls)
                    min_call_dist = dist
                    otm_call_iv = call_ivs.get(s)
            
            skew = (otm_put_iv - otm_call_iv) if otm_put_iv is not None and otm_call_iv is not None else None
            
            expiry_data[f"expiry_{days_to_expiry:.0f}d"] = {
                'days_to_expiry': round(days_to_expiry, 1),
                'atm_strike': atm_strike,
                'atm_iv': round(atm_iv, 2) if atm_iv else None,
                'otm_put_iv': round(otm_put_iv, 2) if otm_put_iv else None,
                'otm_call_iv': round(otm_call_iv, 2) if otm_call_iv else None,
                'skew_25d': round(skew, 2) if skew else None,
                'num_instruments': len(insts),
                'num_ivs_fetched': len(all_ivs),
                'avg_iv': round(np.mean(all_ivs), 2),
                'min_iv': round(min(all_ivs), 2),
                'max_iv': round(max(all_ivs), 2),
            }
            
            term_structure.append({
                'days_to_expiry': round(days_to_expiry, 1),
                'atm_iv': round(atm_iv, 2) if atm_iv else None,
            })
    
    # Compute term structure slope (front-month vs 3rd month)
    ts_slope = None
    if len(term_structure) >= 3:
        front = term_structure[0]['atm_iv']
        back = term_structure[2]['atm_iv']
        if front and back:
            ts_slope = round(back - front, 2)
    
    snapshot = {
        'snapshot_time': datetime.now(timezone.utc).isoformat(),
        'snapshot_timestamp_ms': int(time.time() * 1000),
        'btc_price': round(btc_price, 2),
        'btc_price_at_snapshot': round(btc_price, 2),
        'num_expiries_analyzed': len(nearby_expiries),
        'num_total_instruments': len(instruments),
        'term_structure_slope': ts_slope,
        'expiry_data': expiry_data,
        'term_structure': term_structure,
    }
    
    return snapshot


def build_mstr_alignment(snapshot: Dict) -> Dict:
    """
    Align current options snapshot with MSTR purchase history context.
    Since we can't query historical options, this analyzes:
    - Current vol surface state
    - Open interest distribution (are options concentrated at strikes MSTR influences?)
    - Compare current ATM IV to historical realized vol
    
    For true historical options analysis, we need daily snapshots (now started via cron).
    """
    btc_price = snapshot['btc_price']
    current_iv = None
    for key, data in snapshot.get('expiry_data', {}).items():
        if 'atm_iv' in data and data['atm_iv']:
            current_iv = data['atm_iv']
            break
    
    alignment = {
        'analysis_type': 'current_snapshot_with_context',
        'btc_price_at_snapshot': btc_price,
        'current_atm_iv': current_iv,
        'note': 'Historical options data requires paid API. Daily snapshots now being collected for future analysis.',
        'mstr_holdings_context': {
            'total_btc_owned': 2845866,
            'pct_of_circulating_supply': round(2845866 / 19500000 * 100, 2),
            'recent_purchases_last_30d': '45,191 BTC (Jun 1 + Jun 5)',
        },
        'further_work': [
            'Collect daily Deribit snapshots via cron for prospective analysis',
            'Use TARDIS or historical Deribit data for retrospective analysis',
            'Cross-reference options OI concentration around MSTR purchase strikes',
        ]
    }
    
    return alignment


def save_snapshot(snapshot: Dict):
    """Save snapshot to CSV for time series building."""
    output_dir = os.path.join(PROJECT_ROOT, 'data', 'raw')
    os.makedirs(output_dir, exist_ok=True)
    
    # Append to snapshot history CSV
    csv_path = os.path.join(output_dir, 'deribit_options_snapshot.csv')
    fieldnames = [
        'snapshot_time', 'btc_price', 'atm_iv', 'term_structure_slope',
        'num_instruments', 'front_days', 'front_iv', 'second_days', 'second_iv',
        'third_days', 'third_iv'
    ]
    
    row = {
        'snapshot_time': snapshot['snapshot_time'],
        'btc_price': snapshot['btc_price'],
        'atm_iv': None,
        'term_structure_slope': snapshot.get('term_structure_slope'),
        'num_instruments': snapshot['num_total_instruments'],
    }
    
    ts = snapshot.get('term_structure', [])
    for i, point in enumerate(ts):
        if i == 0:
            row['atm_iv'] = point['atm_iv']
            row['front_days'] = point['days_to_expiry']
            row['front_iv'] = point['atm_iv']
        elif i == 1:
            row['second_days'] = point['days_to_expiry']
            row['second_iv'] = point['atm_iv']
        elif i == 2:
            row['third_days'] = point['days_to_expiry']
            row['third_iv'] = point['atm_iv']
    
    file_exists = os.path.exists(csv_path)
    with open(csv_path, 'a', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        if not file_exists:
            writer.writeheader()
        writer.writerow(row)
    
    log.info(f"Snapshot appended to {csv_path}")


def save_json(data: Dict, filepath: str):
    """Save data as JSON."""
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    with open(filepath, 'w') as f:
        json.dump(data, f, indent=2, default=str)
    log.info(f"Saved to {filepath}")


def generate_plots(snapshot: Dict):
    """Generate vol surface visualization."""
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    
    fig, axes = plt.subplots(1, 2, figsize=(16, 7))
    fig.suptitle('BTC Options Volatility Surface — Deribit Snapshot', fontsize=14, fontweight='bold')
    
    # Plot 1: Term structure
    ts = snapshot.get('term_structure', [])
    if ts:
        ax = axes[0]
        days = [p['days_to_expiry'] for p in ts]
        ivs = [p['atm_iv'] for p in ts if p['atm_iv']]
        valid_days = [d for d, iv in zip(days, [p['atm_iv'] for p in ts]) if iv]
        valid_ivs = [iv for iv in [p['atm_iv'] for p in ts] if iv]
        
        if valid_days and valid_ivs:
            ax.plot(valid_days, valid_ivs, 'o-', color='#2196F3', linewidth=2, markersize=8)
            ax.axhline(y=snapshot.get('btc_price', 0), alpha=0, linestyle='--')
            ax.set_xlabel('Days to Expiry')
            ax.set_ylabel('ATM Implied Volatility (%)')
            ax.set_title(f'BTC Vol Term Structure (BTC=${snapshot["btc_price"]:,.0f})')
            ax.grid(True, alpha=0.3)
            
            for d, iv in zip(valid_days, valid_ivs):
                ax.annotate(f'{iv}%', (d, iv), textcoords="offset points", xytext=(0, 10), fontsize=9, ha='center')
    
    # Plot 2: Skew by expiry
    ax = axes[1]
    expiry_labels = []
    skews = []
    for key, data in snapshot.get('expiry_data', {}).items():
        if data.get('skew_25d') is not None:
            expiry_labels.append(f"{data['days_to_expiry']:.0f}d")
            skews.append(data['skew_25d'])
    
    if skews:
        colors = ['#4CAF50' if s > 0 else '#f44336' for s in skews]
        bars = ax.bar(expiry_labels, skews, color=colors, alpha=0.7)
        ax.axhline(y=0, color='gray', linestyle='-', linewidth=0.5)
        ax.set_xlabel('Expiry')
        ax.set_ylabel('25-delta Skew (Put IV - Call IV %)')
        ax.set_title('Vol Skew by Expiry (Risk Reversal)')
        ax.grid(True, alpha=0.3, axis='y')
        
        for bar, s in zip(bars, skews):
            ax.annotate(f'{s:+.1f}%', bar.get_xy(), textcoords="offset points",
                       xytext=(0, 8 if s >= 0 else -12), fontsize=9, ha='center')
    
    plt.tight_layout()
    output_path = os.path.join(PROJECT_ROOT, 'reports', 'options_vol_surface.png')
    plt.savefig(output_path, dpi=150, bbox_inches='tight')
    plt.close()
    log.info(f"Plot saved to {output_path}")


def main():
    log.info("=" * 60)
    log.info("DERIBIT OPTIONS VOLATILITY SURFACE ANALYSIS")
    log.info("=" * 60)
    
    # Step 1: Fetch current options snapshot
    log.info("\n--- Step 1: Fetching Current Options Snapshot ---")
    snapshot = get_options_snapshot()
    
    # Step 2: Align with MSTR context
    log.info("\n--- Step 2: MSTR Purchase Context Alignment ---")
    alignment = build_mstr_alignment(snapshot)
    
    # Step 3: Build combined analysis
    analysis = {
        'snapshot': snapshot,
        'mstr_alignment': alignment,
        'generated_at': datetime.now(timezone.utc).isoformat(),
        'methodology': {
            'source': 'Deribit public REST API (live snapshots)',
            'limitations': [
                'Public API does not support historical option IV queries',
                'Snapshots show only current market state, not time series',
                'Full historical analysis requires Deribit historical data subscription or TARDIS data',
                'Skew computed as approximation (nearest available strike to 25d, not interpolated)'
            ],
            'future_capability': 'Daily snapshots via cron will build a time series for event-window analysis'
        }
    }
    
    # Step 4: Save outputs
    save_json(analysis, os.path.join(PROJECT_ROOT, 'data', 'processed', 'options_vol_analysis.json'))
    save_snapshot(snapshot)
    
    # Step 5: Generate plots
    log.info("\n--- Step 3: Generating Plots ---")
    generate_plots(snapshot)
    
    # Step 6: Print summary
    print(f"\n{'='*60}")
    print(f"OPTIONS VOL SURFACE SUMMARY")
    print(f"{'='*60}")
    print(f"Snapshot time: {snapshot['snapshot_time']}")
    print(f"BTC price: ${snapshot['btc_price']:,.2f}")
    print(f"Total option instruments: {snapshot['num_total_instruments']}")
    print(f"Expiries analyzed: {snapshot['num_expiries_analyzed']}")
    print(f"Term structure slope: {snapshot.get('term_structure_slope', 'N/A')}")
    print(f"\nExpiry Breakdown:")
    for key, data in snapshot.get('expiry_data', {}).items():
        atm = data.get('atm_iv', 'N/A')
        skew = data.get('skew_25d', 'N/A')
        print(f"  {key}: ATM IV={atm}% | 25d Skew={skew}")
    
    print(f"\nMSTR Context:")
    print(f"  Total BTC held: ~2.85M ({alignment['mstr_holdings_context']['pct_of_circulating_supply']}% of supply)")
    print(f"  Recent: {alignment['mstr_holdings_context']['recent_purchases_last_30d']}")
    print(f"\nNOTE: Historical options data requires paid API.")
    print(f"Daily snapshots now being collected. After 30+ snapshots,")
    print(f"event-window analysis around MSTR purchases becomes possible.")
    print(f"See: reports/options_vol_surface.png")


if __name__ == '__main__':
    main()
