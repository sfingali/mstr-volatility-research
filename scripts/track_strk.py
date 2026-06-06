#!/usr/bin/env python3
"""
STRK Preferred Share Tracker

Tracks STRK (MSTR preferred stock) issuance and the implied BTC sell obligation.
Alerts if the sell rate deviates from the 32 BTC/quarter baseline.

Output: data/processed/strk_tracker.json
"""

import os, json, logging
from datetime import datetime

logging.basicConfig(level=logging.INFO, format='%(asctime)s | %(message)s')
log = logging.getLogger(__name__)

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))

# STRK known data points (from public filings)
# format: (date, strk_shares_outstanding, strk_dividend_per_share_annual, btc_sold_for_dividends)
strk_snapshots = [
    ('2026-05-20', 0, 0.0, 0),        # Before STRK issuance
    ('2026-06-01', 800000, 8.00, 32),  # Initial STRK issuance, 32 BTC sold for first dividend
]

def main():
    print("=" * 60)
    print("STRK PREFERRED SHARE TRACKER")
    print("=" * 60)
    
    # Calculate current state
    current = strk_snapshots[-1]
    
    print(f"\nCurrent STRK data (as of {current[0]}):")
    print(f"  STRK shares outstanding: {current[1]:,.0f}")
    print(f"  Annual dividend/share: ${current[2]:.2f}")
    print(f"  BTC sold for dividends: {current[3]} BTC")
    
    # Annual dividend obligation
    annual_dividend_obligation = current[1] * current[2]
    # BTC price at snapshot (approximate from the sell event)
    btc_price_at_sell = 77521  # from the May 26 sell event
    annual_btc_needed = annual_dividend_obligation / btc_price_at_sell
    
    print(f"\n  Annual dividend obligation: ${annual_dividend_obligation:,.0f}")
    print(f"  Annual BTC needed at ${btc_price_at_sell:,}/BTC: {annual_btc_needed:.0f} BTC")
    print(f"  Per quarter BTC sell: {annual_btc_needed/4:.0f} BTC")
    print(f"  As % of MSTR holdings: {annual_btc_needed / 2845866 * 100:.6f}%")
    
    # Scenarios for STRK growth
    print(f"\n--- Scenarios ---")
    for strk_growth in [1.0, 2.0, 5.0, 10.0]:
        new_strk = current[1] * strk_growth
        new_dividend = new_strk * current[2]
        new_btc = new_dividend / btc_price_at_sell
        print(f"  {strk_growth:.0f}x STRK ({new_strk:,.0f} shares): ${new_dividend:,.0f}/yr = {new_btc:.0f} BTC/yr")
    
    # What if they issue STRK at 10% of total debt capacity?
    # Current debt capacity is ~$11.3B
    strk_at_10pct = 0.10 * 11.295e9 / 100  # ~$100/share notional
    print(f"\n  If STRK represents 10% of capital structure: ~${0.10*11.295e9:,.0f}")
    print(f"  Annual dividend at 8%: ${0.10*11.295e9*0.08:,.0f}")
    print(f"  BTC/yr at $77K: {0.10*11.295e9*0.08/77521:.0f} BTC")
    print(f"  BTC/quarter: {0.10*11.295e9*0.08/77521/4:.0f} BTC")
    
    # Save
    results = {
        'current_snapshot': {
            'date': current[0],
            'strk_shares': current[1],
            'annual_dividend_per_share': current[2],
            'btc_sold_to_date': current[3],
            'annual_dividend_obligation': round(annual_dividend_obligation, 0),
            'annual_btc_needed': round(annual_btc_needed, 0),
            'btc_per_quarter': round(annual_btc_needed / 4, 0),
            'btc_per_quarter_as_pct_of_holdings': round(annual_btc_needed / 2845866 * 100, 6),
        },
        'scenarios': {
            f'{g}x_strk': {
                'strk_shares': int(current[1] * g),
                'annual_dividend': round(current[1] * g * current[2], 0),
                'annual_btc_sell': round(current[1] * g * current[2] / btc_price_at_sell, 0),
            }
            for g in [1.0, 2.0, 5.0, 10.0]
        },
        'alert_thresholds': {
            'btc_per_quarter_baseline': 8,
            'yellow_alert': 25,   # >3x baseline
            'red_alert': 100,     # >12x baseline
            'regime_change': 1000, # >125x baseline
        },
        'tells_to_watch': [
            "STRK shares outstanding growth rate (quarter-over-quarter)",
            "BTC sold per dividend cycle (currently ~8 BTC/quarter)",
            "STRK as % of total capital structure",
            "Time gap between STRK issuance and BTC sell announcement",
        ],
        'generated_at': datetime.now().isoformat()
    }
    
    outpath = os.path.join(PROJECT_ROOT, 'data', 'processed', 'strk_tracker.json')
    with open(outpath, 'w') as f:
        json.dump(results, f, indent=2)
    
    print(f"\nResults saved to: {outpath}")
    
    # Alert if threshold crossed
    current_btcq = annual_btc_needed / 4
    if current_btcq >= 1000:
        print(f"\n⚠️  REGIME CHANGE: BTC/quarter ({current_btcq:.0f}) exceeds regime change threshold")
    elif current_btcq >= 100:
        print(f"\n🔴 RED ALERT: BTC/quarter ({current_btcq:.0f}) exceeds red alert threshold")
    elif current_btcq >= 25:
        print(f"\n🟡 YELLOW ALERT: BTC/quarter ({current_btcq:.0f}) exceeds yellow alert threshold")
    else:
        print(f"\n🟢 NORMAL: BTC/quarter ({current_btcq:.0f}) within baseline range")


if __name__ == '__main__':
    main()
