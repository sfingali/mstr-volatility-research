#!/usr/bin/env python3
"""
Convertible Arbitrage Analysis: MSTR Convertible Debt Issuances vs BTC Purchases

Analyses the 11 known MSTR convertible debt issuance events and their
relationship with subsequent BTC purchases, NAV premium dynamics, and
estimated arbitrage flow from delta hedging.

Outputs:
  - data/processed/convert_arb_analysis.json  (detailed per-issuance data)
  - reports/convert_issuances_vs_purchases.png (timeline chart)
  - stdout summary of key findings
"""

import json
import os
import warnings
from datetime import datetime, timedelta
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns
from scipy import stats

warnings.filterwarnings('ignore', category=FutureWarning)
warnings.filterwarnings('ignore', category=UserWarning)

# ── Paths ─────────────────────────────────────────────────────────────────────
BASE = Path('/opt/data/home/projects/mstr-volatility-research')
DATA_RAW = BASE / 'data' / 'raw'
DATA_PROC = BASE / 'data' / 'processed'
REPORTS = BASE / 'reports'
REPORTS.mkdir(parents=True, exist_ok=True)

sns.set_theme(style='whitegrid', palette='viridis')


# ── Data Loading ──────────────────────────────────────────────────────────────
def load_data():
    """Load all required datasets."""
    # 1. Convertible debt issuances
    debt = pd.read_csv(DATA_PROC / 'mstr_debt_issuances.csv',
                       parse_dates=['announce_date'])
    debt['announce_date'] = pd.to_datetime(debt['announce_date'], errors='coerce')
    # Drop the last row which has "terms TBD" — pending issuance
    debt = debt.dropna(subset=['announce_date']).sort_values('announce_date').reset_index(drop=True)
    print(f"  Debt issuances: {len(debt)} events")

    # 2. MSTR BTC holdings (purchase records)
    holdings = pd.read_csv(DATA_RAW / 'mstr_holdings.csv',
                           parse_dates=['date'], dayfirst=False)
    holdings['date'] = pd.to_datetime(holdings['date'], errors='coerce')

    # Only buy events
    buys = holdings[holdings['transaction_type'].str.lower().str.strip() == 'buy'].copy()
    buys = buys.dropna(subset=['date']).sort_values('date').reset_index(drop=True)
    print(f"  Holdings: {len(holdings)} rows, {len(buys)} buy events")

    # 3. BTC volatility data (daily with realised vol, close price)
    vol = pd.read_csv(DATA_PROC / 'btc_volatility.csv',
                      parse_dates=['datetime'])
    vol['date'] = pd.to_datetime(vol['datetime'].dt.date)
    vol = vol.drop_duplicates(subset='date').sort_values('date').reset_index(drop=True)
    print(f"  BTC vol data: {len(vol)} days ({vol['date'].min().date()} to {vol['date'].max().date()})")

    # 4. MSTR equity data (NAV premium, shares outstanding)
    eq = pd.read_csv(DATA_RAW / 'mstr_equity.csv', parse_dates=['Date'])
    eq = eq.sort_values('Date').reset_index(drop=True)
    print(f"  MSTR equity: {len(eq)} days")

    return debt, buys, vol, eq


# ── Lookup Helpers ────────────────────────────────────────────────────────────
def lookup_closest_value(df, date_col, value_col, target_date, lookback_days=5):
    """Find the closest value within lookback_days before target_date."""
    mask = (df[date_col] <= target_date) & \
           (df[date_col] >= target_date - timedelta(days=lookback_days))
    subset = df.loc[mask]
    if len(subset) == 0:
        return None
    # Return the closest date's value
    closest_idx = (subset[date_col] - target_date).abs().idxmin()
    return subset.loc[closest_idx, value_col]


def lookup_vol_on_date(vol, target_date):
    """Look up BTC close price and 30d vol for a given date (fwd-fill from last 5 days)."""
    vol_lookup = vol[['date', 'close', 'rv_30d']].copy().dropna(subset=['date']).set_index('date')
    all_dates = pd.date_range(vol['date'].min(), vol['date'].max(), freq='D')
    vol_filled = vol_lookup.reindex(all_dates).ffill(limit=5)

    if target_date not in vol_filled.index:
        return None, None
    row = vol_filled.loc[target_date]
    return row['close'], row['rv_30d']


def lookup_nav_premium(eq, target_date, lookback_days=5):
    """Look up NAV premium ratio for a given date."""
    return lookup_closest_value(eq, 'Date', 'nav_premium', target_date, lookback_days)


def classify_convert_purchase(source_str):
    """Classify whether a purchase was explicitly funded by convertible debt."""
    if pd.isna(source_str):
        return False
    source_lower = str(source_str).lower()
    keywords = ['convertible debt', 'convertible offering', 'convert']
    return any(kw in source_lower for kw in keywords)


# ── Core Analysis ──────────────────────────────────────────────────────────────
def analyze_issuance(debt_row, buys, vol, eq):
    """Analyze a single debt issuance event."""
    issue_date = debt_row['announce_date']
    principal = debt_row['principal_amount']
    coupon = debt_row['coupon_rate']
    maturity = debt_row['maturity_year']
    description = debt_row.get('description', '')

    # 1. BTC purchases within 30 days after issuance
    window_end = issue_date + timedelta(days=30)
    window_purchases = buys[(buys['date'] >= issue_date) & (buys['date'] <= window_end)].copy()

    total_btc_bought = window_purchases['btc_change'].sum() if len(window_purchases) > 0 else 0
    total_cost = window_purchases['total_cost_usd'].sum() if len(window_purchases) > 0 else 0
    convert_labeled = window_purchases[
        window_purchases['source'].apply(classify_convert_purchase)
    ] if len(window_purchases) > 0 else pd.DataFrame()

    btc_from_convert = convert_labeled['btc_change'].sum() if len(convert_labeled) > 0 else 0
    cost_from_convert = convert_labeled['total_cost_usd'].sum() if len(convert_labeled) > 0 else 0

    # 2. BTC price and 30d vol at issuance time
    btc_price, rv_30d = lookup_vol_on_date(vol, issue_date)

    # 3. NAV premium at issuance time
    nav_premium = lookup_nav_premium(eq, issue_date)

    # 4. Check for concurrent share buyback/ATM
    # Look in equity data for unusual changes in shares outstanding around issuance
    eq_window = eq[(eq['Date'] >= issue_date - timedelta(days=5)) &
                   (eq['Date'] <= issue_date + timedelta(days=10))].copy()
    if len(eq_window) > 1:
        shares_before = eq_window.iloc[0]['shares_outstanding']
        shares_after = eq_window.iloc[-1]['shares_outstanding']
        share_change_pct = (shares_after / shares_before - 1) * 100
    else:
        share_change_pct = None

    # Check total_debt change around issuance
    debt_col = 'total_debt'
    if debt_col in eq.columns and len(eq_window) > 1:
        debt_before = eq_window.iloc[0][debt_col]
        debt_after = eq_window.iloc[-1][debt_col]
    else:
        debt_before = None
        debt_after = None

    # 5. Purchase dates and latencies
    purchase_dates = []
    purchase_latencies = []
    if len(window_purchases) > 0:
        for _, p in window_purchases.iterrows():
            latency = (p['date'] - issue_date).days
            purchase_dates.append(p['date'].strftime('%Y-%m-%d'))
            purchase_latencies.append(latency)

    # 6. Count distinct purchase dates
    num_purchases = len(window_purchases)
    avg_latency = np.mean(purchase_latencies) if purchase_latencies else None
    min_latency = min(purchase_latencies) if purchase_latencies else None

    return {
        'issue_date': issue_date.strftime('%Y-%m-%d'),
        'principal_amount': float(principal),
        'coupon_rate': float(coupon) if pd.notna(coupon) else None,
        'maturity_year': int(maturity) if pd.notna(maturity) else None,
        'description': str(description) if pd.notna(description) else '',
        'btc_price_at_issuance': float(btc_price) if btc_price is not None else None,
        'rv_30d_at_issuance': float(rv_30d) if rv_30d is not None else None,
        'nav_premium_at_issuance': float(nav_premium) if nav_premium is not None else None,
        'total_btc_bought_30d': int(total_btc_bought),
        'total_cost_30d_usd': float(total_cost),
        'btc_bought_explicitly_from_convert': int(btc_from_convert),
        'cost_from_convert_usd': float(cost_from_convert),
        'num_purchases_within_30d': int(num_purchases),
        'purchase_dates': purchase_dates,
        'purchase_latencies_days': purchase_latencies,
        'avg_purchase_latency_days': float(round(avg_latency, 1)) if avg_latency is not None else None,
        'min_purchase_latency_days': int(min_latency) if min_latency is not None else None,
        'share_count_change_pct_around_issuance': float(round(share_change_pct, 4)) if share_change_pct is not None else None,
        'total_debt_before_issuance': float(debt_before) if debt_before is not None else None,
        'total_debt_after_issuance': float(debt_after) if debt_after is not None else None,
    }


def compute_arb_estimates(issuance_results, buys):
    """Estimate convertible arbitrage flow metrics.

    When hedge funds buy converts and short MSTR shares to delta-hedge,
    the delta hedging creates synthetic short interest.

    Basic approach:
      - Convert notional amount * delta (~0.7-0.9 for in-the-money converts)
      - That delta-hedged short position = estimated short interest added
    """
    total_convert_proceeds = sum(
        r['principal_amount'] for r in issuance_results
    )

    # Estimate: assume delta of 0.8 for in-the-money converts
    # (converts are typically issued with conversion premium ~20-40%)
    estimated_delta = 0.8
    total_short_interest_from_delta_hedging = total_convert_proceeds * estimated_delta

    # Total BTC bought overall
    total_btc_all = buys['btc_change'].sum()
    total_btc_convert_labeled = buys[
        buys['source'].apply(classify_convert_purchase)
    ]['btc_change'].sum()

    # Total cost from convert-labeled purchases
    total_cost_convert_labeled = buys[
        buys['source'].apply(classify_convert_purchase)
    ]['total_cost_usd'].sum()

    return {
        'total_convert_proceeds_usd': float(total_convert_proceeds),
        'estimated_delta_for_hedging': estimated_delta,
        'estimated_short_interest_from_delta_hedging_usd': float(total_short_interest_from_delta_hedging),
        'total_btc_purchased_all_time': float(total_btc_all),
        'total_btc_purchased_explicit_convert_source': float(total_btc_convert_labeled),
        'pct_btc_from_explicit_convert_sources': float(
            round(total_btc_convert_labeled / total_btc_all * 100, 2)
        ) if total_btc_all > 0 else 0,
        'total_convert_labeled_cost_usd': float(total_cost_convert_labeled),
    }


def compute_correlations(issuance_results, buys, vol):
    """Compute correlations between convert issuance timing and BTC purchase waves."""
    # Correlation: convert principal amount vs BTC bought within 30d
    principals = np.array([r['principal_amount'] for r in issuance_results if r['total_btc_bought_30d'] > 0])
    btc_bought = np.array([r['total_btc_bought_30d'] for r in issuance_results if r['total_btc_bought_30d'] > 0])

    corr_amount_vs_btc = None
    if len(principals) >= 3:
        r_val, p_val = stats.pearsonr(principals, btc_bought)
        corr_amount_vs_btc = {
            'pearson_r': float(round(r_val, 4)),
            'p_value': float(p_val),
            'n': int(len(principals)),
            'interpretation': (
                'Larger convert issuances significantly associated with more BTC bought within 30d'
                if (r_val > 0 and p_val < 0.05) else
                'No significant correlation between convert size and BTC bought within 30d'
            )
        }

    # Correlation: NAV premium at issuance vs subsequent BTC purchases
    navs = np.array([r['nav_premium_at_issuance'] for r in issuance_results
                     if r['nav_premium_at_issuance'] is not None and r['total_btc_bought_30d'] > 0])
    btc2 = np.array([r['total_btc_bought_30d'] for r in issuance_results
                     if r['nav_premium_at_issuance'] is not None and r['total_btc_bought_30d'] > 0])
    corr_nav_vs_btc = None
    if len(navs) >= 3:
        r_val, p_val = stats.pearsonr(navs, btc2)
        corr_nav_vs_btc = {
            'pearson_r': float(round(r_val, 4)),
            'p_value': float(p_val),
            'n': int(len(navs)),
            'interpretation': (
                'Higher NAV premium at issuance is significantly associated with more BTC buying'
                if (abs(r_val) > 0.3 and p_val < 0.05) else
                'No significant correlation between NAV premium at issuance and BTC buying'
            )
        }

    # Build time series of weekly BTC purchase volumes
    buys_ts = buys.copy()
    buys_ts['week'] = buys_ts['date'].dt.isocalendar().year.astype(str) + '-W' + \
                      buys_ts['date'].dt.isocalendar().week.astype(str).str.zfill(2)
    weekly_btc = buys_ts.groupby('week')['btc_change'].sum().reset_index()
    weekly_btc.columns = ['week', 'btc_bought']

    return {
        'corr_convert_amount_vs_btc_30d': corr_amount_vs_btc,
        'corr_nav_premium_vs_btc_30d': corr_nav_vs_btc,
    }


# ── Plotting ──────────────────────────────────────────────────────────────────
def plot_issuances_vs_purchases(debt, buys, eq, issuance_results, path):
    """Timeline: debt events, BTC purchases, and NAV premium."""
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(18, 12), sharex=True,
                                    gridspec_kw={'height_ratios': [2, 1]})

    # ── Top panel: BTC purchases vs debt events ──
    # Aggregate BTC purchases by week for cleaner display
    buys_plot = buys.copy()
    buys_plot['week_start'] = buys_plot['date'] - pd.to_timedelta(
        buys_plot['date'].dt.dayofweek, unit='D')
    weekly = buys_plot.groupby('week_start')['btc_change'].sum().reset_index()
    weekly = weekly.sort_values('week_start')

    ax1.bar(weekly['week_start'], weekly['btc_change'], width=5, color='steelblue',
            alpha=0.7, label='Weekly BTC Purchases', zorder=2)

    # Overlay debt issuance markers
    for i, r in enumerate(issuance_results):
        d = pd.to_datetime(r['issue_date'])
        principal_b = r['principal_amount'] / 1e9  # in billions
        # Scale marker size by principal
        marker_size = max(100, min(600, principal_b * 200))
        ax1.scatter(d, 0, marker='v', s=marker_size, color='red', zorder=5,
                    edgecolors='black', linewidth=0.5,
                    label='Convert Debt Issuance' if i == 0 else '')

        # Annotate with principal
        ax1.annotate(f'${principal_b:.1f}B', xy=(d, 0),
                     xytext=(0, -25 - principal_b * 15),
                     textcoords='offset points', ha='center', fontsize=7,
                     color='darkred', fontweight='bold',
                     arrowprops=dict(arrowstyle='->', color='darkred', lw=0.5))

    ax1.set_ylabel('BTC Purchases (weekly total)')
    ax1.set_title('MSTR Convertible Debt Issuances vs BTC Purchases Timeline',
                  fontsize=14, fontweight='bold')
    ax1.legend(loc='upper left')
    ax1.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, _: f'{x:,.0f}'))

    # ── Bottom panel: NAV Premium ──
    eq_clean = eq.dropna(subset=['Date', 'nav_premium'])
    ax2.plot(eq_clean['Date'], eq_clean['nav_premium'], color='forestgreen',
             lw=0.8, alpha=0.7, label='NAV Premium (ratio)')

    # Mark debt issuance dates on NAV premium
    for i, r in enumerate(issuance_results):
        d = pd.to_datetime(r['issue_date'])
        nav_val = r['nav_premium_at_issuance']
        if nav_val is not None:
            ax2.scatter(d, nav_val, marker='D', s=80, color='red', zorder=5,
                        edgecolors='black', linewidth=0.5)

            # Annotate with principal
            principal_b = r['principal_amount'] / 1e9
            ax2.annotate(f'${principal_b:.1f}B', xy=(d, nav_val),
                         xytext=(5, 10), textcoords='offset points',
                         fontsize=7, color='darkred', fontweight='bold',
                         arrowprops=dict(arrowstyle='->', color='darkred', lw=0.5))

    ax2.axhline(1.0, color='gray', ls='--', lw=0.5, alpha=0.5)
    ax2.set_ylabel('NAV Premium (ratio)')
    ax2.set_xlabel('Date')
    ax2.legend(loc='upper left')

    # X-axis formatting
    ax2.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m'))
    ax2.xaxis.set_major_locator(mdates.MonthLocator(interval=6))
    fig.autofmt_xdate()

    fig.tight_layout()
    fig.savefig(path, dpi=150, bbox_inches='tight')
    plt.close(fig)
    print(f"  Saved: {path}")


# ── Reporting ─────────────────────────────────────────────────────────────────
def print_summary(issuance_results, arb_estimates, correlations):
    """Print key findings to stdout."""
    print("\n" + "=" * 70)
    print("CONVERTIBLE ARBITRAGE ANALYSIS SUMMARY")
    print("=" * 70)

    print(f"\nTotal convertible debt issuances analyzed: {len(issuance_results)}")
    total_principal = sum(r['principal_amount'] for r in issuance_results)
    print(f"Total principal amount: ${total_principal:,.0f}")

    # Aggregate BTC purchased within 30 days of each issuance
    total_btc_30d = sum(r['total_btc_bought_30d'] for r in issuance_results)
    print(f"\n--- BTC Purchases Within 30 Days of Issuance ---")
    print(f"  Total BTC bought within 30d of any issuance: {total_btc_30d:,.0f}")
    print(f"  Of which explicitly labeled 'convert debt': "
          f"{sum(r['btc_bought_explicitly_from_convert'] for r in issuance_results):,.0f}")

    # Average latency
    latencies = [r['avg_purchase_latency_days'] for r in issuance_results
                 if r['avg_purchase_latency_days'] is not None]
    if latencies:
        print(f"\n--- Convert-to-Buy Latency ---")
        print(f"  Average latency across issuances: {np.mean(latencies):.1f} days")
        print(f"  Min average latency: {min(latencies):.1f} days")
        print(f"  Max average latency: {max(latencies):.1f} days")

    # NAV premium analysis
    navs = [r['nav_premium_at_issuance'] for r in issuance_results
            if r['nav_premium_at_issuance'] is not None]
    if navs:
        print(f"\n--- NAV Premium at Issuance ---")
        print(f"  Average NAV premium: {np.mean(navs):.4f}")
        print(f"  Range: {min(navs):.4f} — {max(navs):.4f}")

    print(f"\n--- Arbitrage Flow Estimates ---")
    print(f"  Total convert proceeds: ${arb_estimates['total_convert_proceeds_usd']:,.0f}")
    print(f"  Est. delta-hedged short interest (delta={arb_estimates['estimated_delta_for_hedging']}): "
          f"${arb_estimates['estimated_short_interest_from_delta_hedging_usd']:,.0f}")
    print(f"  Total BTC bought (all time): {arb_estimates['total_btc_purchased_all_time']:,.0f}")
    print(f"  Total BTC from explicit convert sources: "
          f"{arb_estimates['total_btc_purchased_explicit_convert_source']:,.0f}")
    print(f"  % BTC from convert debt: {arb_estimates['pct_btc_from_explicit_convert_sources']}%")

    print(f"\n--- Correlations ---")
    if correlations.get('corr_convert_amount_vs_btc_30d'):
        c = correlations['corr_convert_amount_vs_btc_30d']
        print(f"  Convert amount vs BTC bought 30d: r={c['pearson_r']:.4f}, "
              f"p={c['p_value']:.4f}, n={c['n']}")
        print(f"    → {c['interpretation']}")
    if correlations.get('corr_nav_premium_vs_btc_30d'):
        c = correlations['corr_nav_premium_vs_btc_30d']
        print(f"  NAV premium vs BTC bought 30d: r={c['pearson_r']:.4f}, "
              f"p={c['p_value']:.4f}, n={c['n']}")
        print(f"    → {c['interpretation']}")

    # Per-issuance summary
    print(f"\n--- Per-Issuance Detail ---")
    for r in issuance_results:
        print(f"\n  [{r['issue_date']}] ${r['principal_amount']:,.0f} "
              f"({r.get('description', '')[:50]})")
        print(f"    BTC bought 30d: {r['total_btc_bought_30d']:>8,}  |  "
              f"Latency: {str(r['avg_purchase_latency_days'])+'d' if r['avg_purchase_latency_days'] else 'N/A':>6}  |  "
              f"NAV premium: {r['nav_premium_at_issuance']:.4f}" 
              if r['nav_premium_at_issuance'] else f"    BTC bought 30d: {r['total_btc_bought_30d']:>8,}")
        if r['btc_price_at_issuance']:
            print(f"    BTC price: ${r['btc_price_at_issuance']:,.0f}  |  "
                  f"30d RV: {r['rv_30d_at_issuance']*100:.1f}%" 
                  if r['rv_30d_at_issuance'] else f"    BTC price: ${r['btc_price_at_issuance']:,.0f}")


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    print("=" * 70)
    print("MSTR Convertible Arbitrage Analysis")
    print("=" * 70)

    # Load data
    print("\nLoading data...")
    debt, buys, vol, eq = load_data()

    # Analyze each issuance
    print("\nAnalyzing each convertible debt issuance...")
    issuance_results = []
    for _, row in debt.iterrows():
        result = analyze_issuance(row, buys, vol, eq)
        issuance_results.append(result)
        issue_date = result['issue_date']
        principal_b = result['principal_amount'] / 1e9
        btc_30d = result['total_btc_bought_30d']
        print(f"  {issue_date}: ${principal_b:.2f}B → {btc_30d:>8,} BTC within 30d")

    # Compute aggregate estimates
    arb_estimates = compute_arb_estimates(issuance_results, buys)
    correlations = compute_correlations(issuance_results, buys, vol)

    # Build output JSON
    output = {
        'analysis_timestamp': datetime.now().isoformat(),
        'total_issuances_analyzed': len(issuance_results),
        'issuance_details': issuance_results,
        'aggregate_estimates': arb_estimates,
        'correlations': correlations,
    }

    # Save JSON
    json_path = DATA_PROC / 'convert_arb_analysis.json'
    with open(json_path, 'w') as f:
        json.dump(output, f, indent=2, default=str)
    print(f"\nSaved: {json_path}")

    # Generate plot
    print("\nGenerating plot...")
    plot_path = REPORTS / 'convert_issuances_vs_purchases.png'
    plot_issuances_vs_purchases(debt, buys, eq, issuance_results, plot_path)

    # Print summary
    print_summary(issuance_results, arb_estimates, correlations)

    print("\n" + "=" * 70)
    print("Analysis complete.")
    print("=" * 70)


if __name__ == '__main__':
    main()
