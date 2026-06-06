#!/usr/bin/env python3
"""
Test Predictions 5 & 6 from the synthesis:

Prediction 5: Convertible debt issuance clusters at low BTC volatility
Prediction 6: MSTR reduces buying during euphoria (high NAV premium + high vol)
"""

import os, sys, json, logging
from datetime import datetime
import numpy as np
import pandas as pd

logging.basicConfig(level=logging.INFO, format='%(asctime)s | %(levelname)s | %(message)s')
log = logging.getLogger(__name__)

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))

def load(path):
    full = os.path.join(PROJECT_ROOT, path)
    df = pd.read_csv(full)
    return df

# === Load data ===
holdings = load('data/raw/mstr_holdings.csv')
vol = load('data/processed/btc_volatility.csv')
equity = load('data/raw/mstr_equity.csv')

# Convert dates
holdings['date'] = pd.to_datetime(holdings['date'])
vol['datetime'] = pd.to_datetime(vol['datetime'])
equity['Date'] = pd.to_datetime(equity['Date'])

# === Prediction 5: Debt issuance at low vol ===
# Hardcoded known debt issuances
debt_issuances = [
    ('2020-12-04', 650e6, '0.75% due 2025'),
    ('2021-02-17', 1050e6, '0% due 2027'),
    ('2021-06-08', 500e6, '6.125% due 2028'),
    ('2021-11-10', 500e6, '0% due 2028'),
    ('2022-03-10', 205e6, '0% due 2032'),
    ('2024-03-04', 800e6, '0.625% due 2030'),
    ('2024-06-10', 800e6, '2.25% due 2032'),
    ('2024-09-13', 1010e6, '0.875% due 2028'),
    ('2024-11-05', 3000e6, '0% due 2029'),
    ('2025-03-03', 2080e6, '0% due 2030'),
    ('2025-06-09', 700e6, 'convertible'),
]

print("=" * 70)
print("PREDICTION 5: Debt Issuance Timing vs BTC Vol Regime")
print("=" * 70)

results_p5 = []
for date_str, amount, note in debt_issuances:
    dt = pd.Timestamp(date_str, tz='UTC')
    # Find nearest vol data point within 3 days
    mask = (vol['datetime'] >= dt - pd.Timedelta('3D')) & (vol['datetime'] <= dt + pd.Timedelta('3D'))
    vol_rows = vol[mask].sort_values('datetime')
    
    if len(vol_rows) == 0:
        results_p5.append({'date': date_str, 'amount_b': amount/1e9, 'rv_30d': 'N/A', 'regime': 'N/A', 'drawdown': 'N/A'})
        continue
    
    nearest = vol_rows.iloc[0]
    rv = nearest['rv_30d']
    dd = nearest.get('drawdown_pct', 'N/A')
    
    if rv <= 0.005:
        regime = 'LOW'
    elif rv <= 0.02:
        regime = 'MED'
    else:
        regime = 'HIGH'
    
    results_p5.append({
        'date': date_str,
        'amount_b': round(amount/1e9, 2),
        'note': note,
        'rv_30d': round(rv, 6),
        'regime': regime,
        'drawdown_pct': f"{dd}%" if dd != 'N/A' else 'N/A',
        'btc_price': round(nearest.get('close', 0), 0) if 'close' in nearest else 'N/A'
    })

# Count regimes
regimes_p5 = [r['regime'] for r in results_p5]
low_count = regimes_p5.count('LOW')
med_count = regimes_p5.count('MED')
high_count = regimes_p5.count('HIGH')
total_p5 = len(results_p5)

for r in results_p5:
    regime_tag = f" [{r['regime']}]" if r['regime'] != 'N/A' else ''
    print(f"  {r['date']} | ${r['amount_b']:.1f}B | rv_30d={r['rv_30d']} | drawdown={r['drawdown_pct']}{regime_tag}")

print(f"\n  Low vol issuances: {low_count}/{total_p5} ({low_count/total_p5*100:.0f}%)")
print(f"  Med vol issuances: {med_count}/{total_p5} ({med_count/total_p5*100:.0f}%)")
print(f"  High vol issuances: {high_count}/{total_p5} ({high_count/total_p5*100:.0f}%)")

# Prediction 5 verdict
if low_count / total_p5 >= 0.6:
    pred5_result = "CONFIRMED"
    pred5_detail = f"{(low_count/total_p5*100):.0f}% of issuances occurred in Low vol regime — strong clustering"
elif low_count / total_p5 >= 0.4:
    pred5_result = "WEAKLY CONFIRMED"
    pred5_detail = f"{(low_count/total_p5*100):.0f}% in Low vol — moderate tendency"
elif low_count / total_p5 <= 0.25:
    pred5_result = "NOT CONFIRMED"
    pred5_detail = f"Only {(low_count/total_p5*100):.0f}% in Low vol — no systematic timing"
else:
    pred5_result = "INCONCLUSIVE"
    pred5_detail = f"{(low_count/total_p5*100):.0f}% in Low vol — inconclusive"

print(f"\n  PREDICTION 5: {pred5_result}")
print(f"  Detail: {pred5_detail}")

# === Prediction 6: MSTR buys less during high NAV premium ===
print("\n" + "=" * 70)
print("PREDICTION 6: Buying Rate vs NAV Premium & Vol Regime")
print("=" * 70)

# Merge holdings with equity data
h = holdings[holdings['transaction_type'] == 'buy'].copy()
h['date'] = pd.to_datetime(h['date'])
e = equity[['Date', 'nav_premium', 'leverage_ratio']].copy()
e.columns = ['date', 'nav_premium', 'leverage_ratio']

merged = pd.merge_asof(
    h.sort_values('date'),
    e.sort_values('date'),
    on='date',
    direction='nearest',
    tolerance=pd.Timedelta('5D')
)

# Filter out rows without nav_premium
merged = merged.dropna(subset=['nav_premium'])

# Define regimes
merged['vol_regime'] = pd.cut(merged['price_per_btc'], 
                               bins=[0, 30000, 60000, 200000],
                               labels=['low_price', 'mid_price', 'high_price'])

# High premium regime: nav_premium > 2.0
high_prem = merged[merged['nav_premium'] > 2.0]
low_prem = merged[merged['nav_premium'] <= 2.0]

# Calculate buying rate (BTC per day between purchases)
merged_sorted = merged.sort_values('date')
merged_sorted['days_since_last'] = merged_sorted['date'].diff().dt.days.fillna(1)
merged_sorted['btc_per_day'] = merged_sorted['btc_change'] / merged_sorted['days_since_last']

high_prem_rate = merged_sorted[merged_sorted['nav_premium'] > 2.0]['btc_per_day'].mean()
low_prem_rate = merged_sorted[merged_sorted['nav_premium'] <= 2.0]['btc_per_day'].mean()

high_prem_count = len(merged_sorted[merged_sorted['nav_premium'] > 2.0])
low_prem_count = len(merged_sorted[merged_sorted['nav_premium'] <= 2.0])

# Check the Nov 2024 peak specifically
nov2024 = merged_sorted[(merged_sorted['date'] >= '2024-11-01') & (merged_sorted['date'] <= '2024-12-31')]
nov_rate = nov2024['btc_per_day'].mean() if len(nov2024) > 0 else 0
overall_rate = merged_sorted['btc_per_day'].mean()

print(f"\n  High NAV premium (>2.0x): {high_prem_count} purchases")
print(f"    Avg BTC/day: {high_prem_rate:,.0f}")
print(f"  Low NAV premium (<=2.0x): {low_prem_count} purchases")
print(f"    Avg BTC/day: {low_prem_rate:,.0f}")
print(f"  Overall avg BTC/day: {overall_rate:,.0f}")
print(f"\n  Nov-Dec 2024 (peak NAV premium 4.0x):")
print(f"    Avg BTC/day: {nov_rate:,.0f}")
print(f"    Purchases: {len(nov2024)}")
if len(nov2024) > 0:
    print(f"    Total BTC bought: {nov2024['btc_change'].sum():,.0f}")
    print(f"    NAV premium range: {nov2024['nav_premium'].min():.2f}x - {nov2024['nav_premium'].max():.2f}x")

# Prediction 6 verdict
# If buying rate is lower during high premium, prediction is confirmed
if high_prem_rate < low_prem_rate * 0.8:  # 20%+ reduction
    pred6_result = "CONFIRMED"
    pred6_detail = f"Buying rate drops from {low_prem_rate:,.0f} to {high_prem_rate:,.0f} BTC/day during high premium"
elif high_prem_rate < low_prem_rate:
    pred6_result = "WEAKLY CONFIRMED"
    pred6_detail = f"Moderate reduction: {low_prem_rate:,.0f} → {high_prem_rate:,.0f} BTC/day"
else:
    pred6_result = "NOT CONFIRMED"
    pred6_detail = f"Buying rate increases or unchanged: {low_prem_rate:,.0f} → {high_prem_rate:,.0f} BTC/day"

print(f"\n  PREDICTION 6: {pred6_result}")
print(f"  Detail: {pred6_detail}")

# === Save to JSON ===
results = {
    'prediction_5_debt_timing': {
        'label': 'Convertible debt issuance clusters at low BTC volatility',
        'result': pred5_result,
        'detail': pred5_detail,
        'data': results_p5,
        'summary': {
            'low_vol_issuances': low_count,
            'med_vol_issuances': med_count,
            'high_vol_issuances': high_count,
            'total': total_p5
        }
    },
    'prediction_6_buying_rate': {
        'label': 'MSTR reduces buying during high NAV premium / euphoria',
        'result': pred6_result,
        'detail': pred6_detail,
        'data': {
            'high_premium_buys': high_prem_count,
            'high_premium_rate_btc_per_day': round(high_prem_rate, 0) if not np.isnan(high_prem_rate) else 0,
            'low_premium_buys': low_prem_count,
            'low_premium_rate_btc_per_day': round(low_prem_rate, 0) if not np.isnan(low_prem_rate) else 0,
            'overall_rate_btc_per_day': round(overall_rate, 0),
            'nov2024_peak_rate_btc_per_day': round(nov_rate, 0),
            'nov2024_total_btc': int(nov2024['btc_change'].sum()) if len(nov2024) > 0 else 0,
        }
    },
    'generated_at': datetime.now().isoformat()
}

outpath = os.path.join(PROJECT_ROOT, 'data', 'processed', 'predictions_test_results.json')
with open(outpath, 'w') as f:
    json.dump(results, f, indent=2)
log.info(f"Saved to {outpath}")

print(f"\n{'='*70}")
print(f"Results saved to data/processed/predictions_test_results.json")
print(f"{'='*70}")
