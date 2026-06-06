#!/usr/bin/env python3
"""
Timing Analysis: MSTR Bitcoin Purchase Timing vs BTC Market Conditions

Analyses when MicroStrategy buys Bitcoin — are purchases timed advantageously?
Tests: KS test, bootstrap vol comparison, drawdown analysis, autocorrelation,
seasonality.  Produces plots and a JSON summary.
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


# ── Helpers ───────────────────────────────────────────────────────────────────
def parse_date_or_nat(s):
    """Try parsing a variety of date formats, return NaT if all fail."""
    for fmt in ('%Y-%m-%d', '%Y-%m-%d %H:%M:%S%z', '%Y-%m-%d %H:%M:%S',
                '%Y-%m-%dT%H:%M:%S%z'):
        try:
            return pd.to_datetime(s, format=fmt)
        except (ValueError, TypeError):
            continue
    return pd.NaT


def percentile_ci(data, n_bootstrap=10_000, alpha=0.05):
    """Bootstrap 95 % CI for the mean of *data*."""
    rng = np.random.default_rng(2025)
    means = np.array([
        rng.choice(data, size=len(data), replace=True).mean()
        for _ in range(n_bootstrap)
    ])
    lo = np.percentile(means, 100 * alpha / 2)
    hi = np.percentile(means, 100 * (1 - alpha / 2))
    return lo, hi


# ── Data Loading ──────────────────────────────────────────────────────────────
def load_data():
    # 1. MSTR holdings
    holdings = pd.read_csv(DATA_RAW / 'mstr_holdings.csv',
                           parse_dates=['date'], dayfirst=False)
    holdings['date'] = pd.to_datetime(holdings['date'], errors='coerce')
    # Only buy events
    buys = holdings[holdings['transaction_type'].str.lower().str.strip() == 'buy'].copy()
    buys = buys.dropna(subset=['date']).sort_values('date').reset_index(drop=True)

    print(f"  Holdings: {len(holdings)} rows, {len(buys)} buy events")

    # 2. BTC volatility (daily with realised vol)
    vol = pd.read_csv(DATA_PROC / 'btc_volatility.csv',
                      parse_dates=['datetime'])
    vol['date'] = pd.to_datetime(vol['datetime'].dt.date)
    vol = vol.drop_duplicates(subset='date').sort_values('date').reset_index(drop=True)

    print(f"  BTC vol data: {len(vol)} days ({vol['date'].min().date()} to {vol['date'].max().date()})")

    # 3. MSTR equity
    eq = pd.read_csv(DATA_RAW / 'mstr_equity.csv',
                     parse_dates=['Date'])
    eq = eq.sort_values('Date').reset_index(drop=True)

    print(f"  MSTR equity: {len(eq)} days")

    return buys, vol, eq


# ── Core Analysis ─────────────────────────────────────────────────────────────
def merge_purchase_data(buys, vol):
    """For each purchase date, look up BTC close price + 30d realised vol.

    If the exact date is not in the vol data (e.g. weekend), we forward-fill
    from the last available trading day within the prior 5 days.
    """
    vol_lookup = vol[['date', 'close', 'rv_30d', 'drawdown_from_ath', 'drawdown_pct']].copy()
    vol_lookup = vol_lookup.dropna(subset=['date']).set_index('date')
    # Forward fill for missing dates (weekends / holidays)
    all_dates = pd.date_range(vol['date'].min(), vol['date'].max(), freq='D')
    vol_filled = vol_lookup.reindex(all_dates).ffill(limit=5)

    merged = buys[['date', 'btc_change', 'btc_held', 'price_per_btc',
                    'total_cost_usd', 'source']].copy()
    merged.columns = ['purchase_date', 'btc_change', 'btc_held',
                       'price_paid_per_btc', 'total_cost_usd', 'source']

    lookup = vol_filled.loc[merged['purchase_date']]
    merged['btc_price_at_purchase'] = lookup['close'].values
    merged['rv_30d_at_purchase'] = lookup['rv_30d'].values
    merged['drawdown_from_ath'] = lookup['drawdown_from_ath'].values
    merged['drawdown_pct'] = lookup['drawdown_pct'].values

    # Drop rows where lookup failed entirely
    before = len(merged)
    merged = merged.dropna(subset=['btc_price_at_purchase', 'rv_30d_at_purchase'])
    after = len(merged)
    if after < before:
        print(f"  Warning: {before - after} purchase(s) dropped due to missing vol data")
    return merged.reset_index(drop=True)


# ── Statistical Tests ─────────────────────────────────────────────────────────
def test_ks(merged, vol):
    """KS test: is BTC price at purchase dates from a different distribution?"""
    purchase_prices = merged['btc_price_at_purchase'].dropna().values
    overall_prices = vol['close'].dropna().values

    stat, pvalue = stats.ks_2samp(purchase_prices, overall_prices,
                                   alternative='two-sided')
    result = {
        'test': 'KS test (BTC price at purchase vs overall)',
        'n_purchase_dates': int(len(purchase_prices)),
        'n_overall_days': int(len(overall_prices)),
        'ks_statistic': float(round(stat, 4)),
        'p_value': float(pvalue),
        'significant_at_5pct': bool(pvalue < 0.05),
        'interpretation': (
            'Purchase-date BTC prices differ significantly from overall BTC price distribution'
            if pvalue < 0.05 else
            'No significant difference between purchase-date and overall BTC prices'
        ),
    }
    return result


def test_bootstrap_vol(merged, vol, n_bootstrap=10_000):
    """Bootstrap: is 30d vol at purchase dates higher than random dates?"""
    purchase_vols = merged['rv_30d_at_purchase'].dropna().values
    all_vols = vol['rv_30d'].dropna().values

    rng = np.random.default_rng(2025)
    n_purch = len(purchase_vols)
    random_means = np.array([
        rng.choice(all_vols, size=n_purch, replace=True).mean()
        for _ in range(n_bootstrap)
    ])

    observed_mean = purchase_vols.mean()
    # p-value: proportion of random means >= observed mean (one-tailed: higher vol)
    p_upper = (random_means >= observed_mean).mean()
    # Two-tailed
    p_two = 2 * min(p_upper, 1 - p_upper)

    result = {
        'test': 'Bootstrap test (30d vol at purchase dates vs random dates)',
        'n_purchase_dates': int(n_purch),
        'n_bootstrap_samples': n_bootstrap,
        'observed_mean_vol': float(round(observed_mean, 6)),
        'mean_of_random_means': float(round(random_means.mean(), 6)),
        'ci_random_mean_95pct': [float(round(x, 6)) for x in
                                 [np.percentile(random_means, 2.5),
                                  np.percentile(random_means, 97.5)]],
        'p_value_upper_tail': float(round(p_upper, 4)),
        'p_value_two_tailed': float(round(p_two, 4)),
        'significant_at_5pct': bool(p_two < 0.05),
        'interpretation': (
            'Volatility at purchase dates is significantly DIFFERENT from random dates'
            if p_two < 0.05 else
            'No significant difference in vol at purchase vs random dates'
        ),
    }
    return result


def test_drawdown(merged):
    """What % of purchases occur when BTC is in drawdown?

    NOTE: drawdown_pct in the data is already a percentage value (e.g. -3.27
    means -3.27 %), NOT a decimal fraction.
    """
    dd = merged['drawdown_pct'].dropna().values  # already in percent
    n_total = len(dd)

    levels = {
        'any_drawdown': dd < 0,
        'greater_than_10pct': dd < -10,
        'greater_than_20pct': dd < -20,
        'greater_than_30pct': dd < -30,
        'greater_than_40pct': dd < -40,
    }
    result = {'n_total_purchases': int(n_total)}
    for key, condition in levels.items():
        count = int(condition.sum())
        result[key] = {
            'count': count,
            'percentage': float(round(100 * count / n_total, 2)),
        }

    # Mean/median drawdown at purchase
    result['mean_drawdown_pct'] = float(round(dd.mean(), 2))
    result['median_drawdown_pct'] = float(round(np.median(dd), 2))
    return result


def test_autocorrelation(merged):
    """Are purchases clustered in time? Compare inter-purchase intervals."""
    dates = merged['purchase_date'].sort_values().values
    intervals = np.diff(dates.astype('datetime64[D]')).astype(int)

    result = {
        'n_purchases': int(len(dates)),
        'min_interval_days': int(intervals.min()) if len(intervals) > 0 else None,
        'max_interval_days': int(intervals.max()) if len(intervals) > 0 else None,
        'median_interval_days': float(round(np.median(intervals), 1)) if len(intervals) > 0 else None,
        'mean_interval_days': float(round(intervals.mean(), 1)) if len(intervals) > 0 else None,
        'std_interval_days': float(round(intervals.std(), 1)) if len(intervals) > 0 else None,
    }

    # Correlate interval duration with vol at the *start* of the interval
    vol_at_start = merged['rv_30d_at_purchase'].values[:-1]
    if len(intervals) > 1 and len(vol_at_start) > 1:
        r, p = stats.pearsonr(intervals, vol_at_start)
        result['correlation_interval_vs_vol'] = {
            'pearson_r': float(round(r, 4)),
            'p_value': float(p),
            'significant_at_5pct': bool(p < 0.05),
            'interpretation': (
                'Shorter inter-purchase intervals are significantly associated with higher vol'
                if (r < 0 and p < 0.05) else
                'Longer intervals significantly associated with higher vol'
                if (r > 0 and p < 0.05) else
                'No significant correlation between interval length and vol'
            ),
        }
    return result


def test_seasonality(merged):
    """Weekday clustering, end-of-month clustering."""
    dow = merged['purchase_date'].dt.dayofweek  # Mon=0
    day_names = ['Monday', 'Tuesday', 'Wednesday', 'Thursday',
                 'Friday', 'Saturday', 'Sunday']
    dow_counts = dow.value_counts().sort_index()
    dow_dist = {day_names[i]: int(dow_counts.get(i, 0))
                for i in range(7)}

    # Chi-squared test for uniform weekday distribution
    observed = np.array([dow_counts.get(i, 0) for i in range(7)])
    expected = np.full(7, observed.sum() / 7)
    # Mask days with 0 expected (shouldn't happen, but be safe)
    mask = expected > 0
    if mask.sum() >= 2:
        chi2, p_chi = stats.chisquare(observed[mask], expected[mask])
    else:
        chi2, p_chi = 0.0, 1.0

    # End-of-month: last 3 trading days
    eom = merged['purchase_date'].dt.is_month_end
    # Also check if it's within last 3 days of month
    days_in_month = merged['purchase_date'].dt.days_in_month
    day_of_month = merged['purchase_date'].dt.day
    last_3_days = (day_of_month >= (days_in_month - 2)).sum()

    result = {
        'weekday_distribution': dow_dist,
        'chi_square_weekday_uniform': {
            'chi2_stat': float(round(chi2, 4)),
            'p_value': float(p_chi),
            'significant_at_5pct': bool(p_chi < 0.05),
        },
        'end_of_month': {
            'exact_month_end_count': int(eom.sum()),
            'last_3_days_count': int(last_3_days),
            'total_purchases': int(len(merged)),
        },
    }
    return result


# ── Volume / Magnitude analysis ──────────────────────────────────────────────
def test_volume_vs_vol(merged):
    """Do larger purchases happen at higher/lower vol?"""
    valid = merged.dropna(subset=['total_cost_usd', 'rv_30d_at_purchase'])
    if len(valid) < 3:
        return {'error': 'insufficient data'}

    r, p = stats.pearsonr(valid['total_cost_usd'], valid['rv_30d_at_purchase'])
    result = {
        'test': 'Pearson correlation (purchase amount vs 30d vol)',
        'n': int(len(valid)),
        'pearson_r': float(round(r, 4)),
        'p_value': float(p),
        'significant_at_5pct': bool(p < 0.05),
    }
    return result


# ── Plotting ──────────────────────────────────────────────────────────────────
def plot_scatter(merged, path):
    """Scatter: BTC price at purchase vs purchase amount, coloured by vol regime."""
    fig, ax = plt.subplots(figsize=(10, 6))
    valid = merged.dropna(subset=['btc_price_at_purchase', 'total_cost_usd',
                                   'rv_30d_at_purchase'])

    # Vol regime bins
    vol_bins = [0, 0.3, 0.6, 1.0, 2.0, 10.0]
    labels = ['Low (<30%)', 'Moderate (30-60%)', 'High (60-100%)',
              'Very High (100-200%)', 'Extreme (>200%)']
    valid['vol_regime'] = pd.cut(valid['rv_30d_at_purchase'] * 100,
                                  bins=vol_bins, labels=labels)

    cmap = plt.cm.viridis
    for i, regime in enumerate(labels):
        subset = valid[valid['vol_regime'] == regime]
        if len(subset) > 0:
            ax.scatter(subset['btc_price_at_purchase'],
                       subset['total_cost_usd'] / 1e6,
                       label=regime, alpha=0.7, s=40, c=[cmap(i / len(labels))])

    ax.set_xlabel('BTC Price at Purchase (USD)')
    ax.set_ylabel('Purchase Amount (USD, Millions)')
    ax.set_title('MSTR BTC Purchases: Price vs Amount by Volatility Regime')
    ax.legend(title='30d Realised Vol (annualised)')
    ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, _: f'{x:.0f}'))
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)
    print(f"  Saved: {path}")


def plot_vol_histogram(merged, vol, path):
    """Histogram: 30d vol at purchase dates vs random dates."""
    fig, ax = plt.subplots(figsize=(10, 6))
    purchase_vols = merged['rv_30d_at_purchase'].dropna().values * 100
    all_vols = vol['rv_30d'].dropna().values * 100

    ax.hist(all_vols, bins=80, alpha=0.5, label='All Days',
            color='gray', density=True)
    ax.hist(purchase_vols, bins=30, alpha=0.7, label='Purchase Days',
            color='crimson', density=True)

    ax.axvline(all_vols.mean(), color='gray', ls='--', lw=1.5,
               label=f'All-days mean: {all_vols.mean():.1f}%')
    ax.axvline(purchase_vols.mean(), color='crimson', ls='--', lw=1.5,
               label=f'Purchase mean: {purchase_vols.mean():.1f}%')

    ax.set_xlabel('30-Day Realised Volatility (%, annualised)')
    ax.set_ylabel('Density')
    ax.set_title('30d BTC Volatility: Purchase Days vs All Days')
    ax.legend()
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)
    print(f"  Saved: {path}")


def plot_timeseries(merged, vol, path):
    """Time series: BTC price with purchase markers coloured by magnitude."""
    fig, ax1 = plt.subplots(figsize=(16, 7))
    vol_dates = vol['date']
    ax1.plot(vol_dates, vol['close'], color='steelblue', lw=1, alpha=0.7,
             label='BTC Close Price')

    # Normalize purchase amount for colour
    valid = merged.dropna(subset=['btc_price_at_purchase', 'total_cost_usd'])
    amounts = valid['total_cost_usd'].values
    norm = plt.Normalize(vmin=amounts.min(), vmax=amounts.max())
    sc = ax1.scatter(valid['purchase_date'], valid['btc_price_at_purchase'],
                     c=amounts, cmap='plasma', norm=norm,
                     s=np.clip(amounts / amounts.max() * 200, 20, 300),
                     alpha=0.8, edgecolors='black', linewidth=0.3,
                     zorder=5)

    ax1.set_ylabel('BTC Price (USD)')
    ax1.set_title('BTC Price with MSTR Purchase Events (coloured by $ amount)')
    ax1.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m'))
    ax1.xaxis.set_major_locator(mdates.MonthLocator(interval=6))
    fig.autofmt_xdate()

    cbar = fig.colorbar(sc, ax=ax1, label='Purchase Amount (USD)')
    cbar.ax.yaxis.set_major_formatter(
        plt.FuncFormatter(lambda x, _: f'${x/1e6:.0f}M'))

    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)
    print(f"  Saved: {path}")


def plot_nav_premium(merged, eq, path):
    """NAV premium over time with purchase markers."""
    fig, ax = plt.subplots(figsize=(16, 7))
    eq_clean = eq.dropna(subset=['Date', 'nav_premium'])
    ax.plot(eq_clean['Date'], eq_clean['nav_premium'], color='forestgreen',
            lw=0.8, alpha=0.7, label='NAV Premium')

    # Purchase markers
    valid = merged.dropna(subset=['purchase_date', 'total_cost_usd'])
    ax.scatter(valid['purchase_date'], np.full(len(valid), 1.0),
               c=valid['total_cost_usd'], cmap='plasma',
               s=np.clip(valid['total_cost_usd'] / valid['total_cost_usd'].max() * 150,
                         20, 250),
               alpha=0.7, edgecolors='black', linewidth=0.3, zorder=5,
               label='BTC Purchase (size → marker)')

    ax.axhline(1.0, color='gray', ls='--', lw=0.5, alpha=0.5)
    ax.set_ylabel('NAV Premium (ratio)')
    ax.set_title('MSTR NAV Premium Over Time with BTC Purchase Events')
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m'))
    ax.xaxis.set_major_locator(mdates.MonthLocator(interval=6))
    fig.autofmt_xdate()
    ax.legend(loc='upper left')

    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)
    print(f"  Saved: {path}")


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    print("=" * 70)
    print("MSTR Bitcoin Purchase Timing Analysis")
    print("=" * 70)

    # Load
    print("\nLoading data...")
    buys, vol, eq = load_data()

    # Merge
    print("\nMerging purchase data with BTC market conditions...")
    merged = merge_purchase_data(buys, vol)
    print(f"  Merged dataset: {len(merged)} purchases with market data")

    # ── Statistical Tests ─────────────────────────────────────────────────────
    print("\n" + "─" * 70)
    print("STATISTICAL TESTS")
    print("─" * 70)

    results = {}

    # 3a. KS test
    print("\n[3a] KS Test — BTC price distribution...")
    ks_result = test_ks(merged, vol)
    results['ks_test'] = ks_result
    print(f"      KS statistic: {ks_result['ks_statistic']:.4f}, "
          f"p-value: {ks_result['p_value']:.4f}")
    print(f"      → {ks_result['interpretation']}")

    # 3b. Bootstrap vol test
    print("\n[3b] Bootstrap Test — 30d vol at purchase vs random...")
    bt_result = test_bootstrap_vol(merged, vol)
    results['bootstrap_vol_test'] = bt_result
    print(f"      Observed mean vol: {bt_result['observed_mean_vol']*100:.2f}%")
    print(f"      Random mean vol CI: "
          f"[{bt_result['ci_random_mean_95pct'][0]*100:.2f}%, "
          f"{bt_result['ci_random_mean_95pct'][1]*100:.2f}%]")
    print(f"      p-value (two-tailed): {bt_result['p_value_two_tailed']:.4f}")
    print(f"      → {bt_result['interpretation']}")

    # 3c. Drawdown analysis
    print("\n[3c] Drawdown Analysis...")
    dd_result = test_drawdown(merged)
    results['drawdown_analysis'] = dd_result
    print(f"      Mean drawdown at purchase: {dd_result['mean_drawdown_pct']:.1f}%")
    print(f"      >10% drawdown: {dd_result['greater_than_10pct']['percentage']:.1f}% "
          f"({dd_result['greater_than_10pct']['count']}/{dd_result['n_total_purchases']})")
    print(f"      >20% drawdown: {dd_result['greater_than_20pct']['percentage']:.1f}% "
          f"({dd_result['greater_than_20pct']['count']}/{dd_result['n_total_purchases']})")
    print(f"      >30% drawdown: {dd_result['greater_than_30pct']['percentage']:.1f}% "
          f"({dd_result['greater_than_30pct']['count']}/{dd_result['n_total_purchases']})")

    # 3d. Autocorrelation
    print("\n[3d] Autocorrelation / Inter-purchase Intervals...")
    ac_result = test_autocorrelation(merged)
    results['autocorrelation'] = ac_result
    print(f"      Mean interval: {ac_result['mean_interval_days']:.1f} days")
    print(f"      Median interval: {ac_result['median_interval_days']:.1f} days")
    if 'correlation_interval_vs_vol' in ac_result:
        corr = ac_result['correlation_interval_vs_vol']
        print(f"      Interval vs vol correlation: r={corr['pearson_r']:.3f}, "
              f"p={corr['p_value']:.4f}")
        print(f"      → {corr['interpretation']}")

    # 3e. Seasonality
    print("\n[3e] Seasonality...")
    se_result = test_seasonality(merged)
    results['seasonality'] = se_result
    print(f"      Weekday distribution: {se_result['weekday_distribution']}")
    print(f"      Chi-square p-value (uniform weekdays): "
          f"{se_result['chi_square_weekday_uniform']['p_value']:.4f}")
    print(f"      End-of-month (last 3 days): "
          f"{se_result['end_of_month']['last_3_days_count']}/"
          f"{se_result['end_of_month']['total_purchases']}")

    # Bonus: volume vs volatility
    print("\n  [Bonus] Purchase amount vs volatility...")
    vol_corr = test_volume_vs_vol(merged)
    results['volume_vs_volatility'] = vol_corr
    if 'pearson_r' in vol_corr:
        print(f"      r = {vol_corr['pearson_r']:.3f}, p = {vol_corr['p_value']:.4f}")

    # ── Summary Statistics ────────────────────────────────────────────────────
    print("\n" + "─" * 70)
    print("SUMMARY STATISTICS")
    print("─" * 70)

    summary = {
        'total_purchases_analysed': int(len(merged)),
        'date_range': {
            'first_purchase': str(merged['purchase_date'].min().date()),
            'last_purchase': str(merged['purchase_date'].max().date()),
        },
        'purchase_amount_stats': {
            'total_spent_usd': float(merged['total_cost_usd'].sum()),
            'mean_per_purchase_usd': float(merged['total_cost_usd'].mean()),
            'median_per_purchase_usd': float(merged['total_cost_usd'].median()),
            'total_btc_acquired': float(merged['btc_change'].sum()),
        },
        'vol_at_purchase_stats': {
            'mean_vol': float(round(merged['rv_30d_at_purchase'].mean(), 6)),
            'median_vol': float(round(merged['rv_30d_at_purchase'].median(), 6)),
            'min_vol': float(round(merged['rv_30d_at_purchase'].min(), 6)),
            'max_vol': float(round(merged['rv_30d_at_purchase'].max(), 6)),
        },
    }
    print(f"  Purchases analysed: {summary['total_purchases_analysed']}")
    print(f"  Date range: {summary['date_range']['first_purchase']} → "
          f"{summary['date_range']['last_purchase']}")
    print(f"  Total spent: ${summary['purchase_amount_stats']['total_spent_usd']:,.0f}")
    print(f"  Total BTC acquired: {summary['purchase_amount_stats']['total_btc_acquired']:,.0f}")
    print(f"  Mean 30d vol at purchase: {summary['vol_at_purchase_stats']['mean_vol']*100:.1f}%")

    full_results = {
        'summary': summary,
        'statistical_tests': results,
    }

    # ── Visualizations ────────────────────────────────────────────────────────
    print("\n" + "─" * 70)
    print("PLOTS")
    print("─" * 70)

    print("\n[4a] Scatter: Price vs Amount by Vol Regime...")
    plot_scatter(merged, REPORTS / 'scatter_price_vs_amount.png')

    print("\n[4b] Histogram: 30d vol at purchase vs random...")
    plot_vol_histogram(merged, vol, REPORTS / 'histogram_vol_purchase_vs_random.png')

    print("\n[4c] Time series: BTC price with purchase markers...")
    plot_timeseries(merged, vol, REPORTS / 'timeseries_btc_with_purchases.png')

    print("\n[4d] NAV premium with purchase markers...")
    plot_nav_premium(merged, eq, REPORTS / 'nav_premium_with_purchases.png')

    # ── Write JSON output ─────────────────────────────────────────────────────
    json_path = DATA_PROC / 'timing_analysis_summary.json'
    with open(json_path, 'w') as f:
        json.dump(full_results, f, indent=2, default=str)
    print(f"\n  JSON summary written to: {json_path}")

    print("\n" + "=" * 70)
    print("TIMING ANALYSIS COMPLETE")
    print("=" * 70)


if __name__ == '__main__':
    main()
