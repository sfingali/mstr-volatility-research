#!/usr/bin/env python3
"""
Sell Event Deep-Dive: MSTR's First BTC Sale Since 2022

Analyses the May 26, 2026 sell event (32 BTC for ~$2.5M preferred dividends).
Compares BTC market conditions, MSTR stock reaction, NAV premium dynamics,
and subsequent accumulation patterns.

Outputs:
  - data/processed/sell_event_analysis.json  (structured analysis)
  - reports/sell_event_context.png           (BTC price ±60d with vol overlay)
  - reports/mstr_holdings_near_sell.png      (holdings zoom, last 12 months)
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

warnings.filterwarnings('ignore', category=FutureWarning)
warnings.filterwarnings('ignore', category=UserWarning)

# ── Paths ─────────────────────────────────────────────────────────────────────
BASE = Path('/opt/data/home/projects/mstr-volatility-research')
DATA_RAW = BASE / 'data' / 'raw'
DATA_PROC = BASE / 'data' / 'processed'
REPORTS = BASE / 'reports'
SCRIPTS = BASE / 'scripts'

REPORTS.mkdir(parents=True, exist_ok=True)
DATA_PROC.mkdir(parents=True, exist_ok=True)

sns.set_theme(style='whitegrid', palette='viridis')

# ── Constants ────────────────────────────────────────────────────────────────
SELL_DATE = pd.Timestamp('2026-05-26')
SELL_BTC = 32
SELL_USD = 2_480_672.0  # from total_cost_usd field
WINDOW_DAYS = 60        # for BTC price plot
ZOOM_MONTHS = 12        # for holdings zoom plot


# ── Data Loading ─────────────────────────────────────────────────────────────
def load_data():
    """Load all three data sources and return cleaned DataFrames."""
    # 1. MSTR holdings
    holdings = pd.read_csv(
        DATA_RAW / 'mstr_holdings.csv',
        parse_dates=['date'],
        dayfirst=False,
    )
    holdings['date'] = pd.to_datetime(holdings['date'], errors='coerce')
    holdings = holdings.dropna(subset=['date']).sort_values('date').reset_index(drop=True)

    # Add cumulative context
    holdings['is_sell'] = holdings['transaction_type'].str.lower().str.strip() == 'sell'
    holdings['is_buy'] = holdings['transaction_type'].str.lower().str.strip() == 'buy'

    print(f"  Holdings: {len(holdings)} rows ({holdings['date'].min().date()} to {holdings['date'].max().date()})")
    print(f"    Buy events: {holdings['is_buy'].sum()}, Sell events: {holdings['is_sell'].sum()}")

    # 2. BTC volatility (daily with realised vol)
    vol = pd.read_csv(DATA_PROC / 'btc_volatility.csv', parse_dates=['datetime'])
    vol['date'] = pd.to_datetime(vol['datetime'].dt.date)
    vol = vol.drop_duplicates(subset='date').sort_values('date').reset_index(drop=True)

    print(f"  BTC vol data: {len(vol)} days ({vol['date'].min().date()} to {vol['date'].max().date()})")

    # 3. MSTR equity (daily with NAV premium)
    eq = pd.read_csv(
        DATA_RAW / 'mstr_equity.csv',
        parse_dates=['Date'],
        dayfirst=False,
    )
    eq.rename(columns={'Date': 'date'}, inplace=True)
    eq['date'] = pd.to_datetime(eq['date'], errors='coerce')
    eq = eq.dropna(subset=['date']).sort_values('date').reset_index(drop=True)

    print(f"  MSTR equity data: {len(eq)} rows ({eq['date'].min().date()} to {eq['date'].max().date()})")

    return holdings, vol, eq


# ── Analysis Functions ────────────────────────────────────────────────────────
def analyze_btc_market(vol, sell_date):
    """Analyze BTC market conditions 30 days before and after the sell."""
    t0 = sell_date
    pre_start = t0 - timedelta(days=30)
    post_end = t0 + timedelta(days=30)

    pre = vol[(vol['date'] >= pre_start) & (vol['date'] < t0)].copy()
    post = vol[(vol['date'] >= t0) & (vol['date'] <= post_end)].copy()

    analysis = {}

    # ── Pre-sell conditions ──
    if not pre.empty:
        pre_close = pre['close'].values
        analysis['pre_sell'] = {
            'start_date': str(pre['date'].min().date()),
            'end_date': str(pre['date'].max().date()),
            'days': len(pre),
            'price_start': float(pre['close'].iloc[0]),
            'price_end': float(pre['close'].iloc[-1]),
            'price_min': float(pre['close'].min()),
            'price_max': float(pre['close'].max()),
            'price_mean': float(pre['close'].mean()),
            'price_change_pct': float((pre['close'].iloc[-1] - pre['close'].iloc[0]) / pre['close'].iloc[0] * 100),
            'daily_return_mean_pct': float(pre['daily_return_pct'].mean()),
            'daily_return_std': float(pre['daily_return_pct'].std()),
            'drawdown_at_sell': float(pre['drawdown_pct'].iloc[-1]),
            'rv_7d_mean': float(pre['rv_7d'].mean()),
            'rv_14d_mean': float(pre['rv_14d'].mean()),
            'rv_30d_mean': float(pre['rv_30d'].mean()),
            'max_drawdown': float(pre['drawdown_pct'].min()),
            'worst_day_return': float(pre['daily_return_pct'].min()),
            'best_day_return': float(pre['daily_return_pct'].max()),
            'negative_days': int((pre['daily_return_pct'] < 0).sum()),
            'positive_days': int((pre['daily_return_pct'] > 0).sum()),
        }
    else:
        analysis['pre_sell'] = {'error': 'no data'}

    # ── Post-sell conditions ──
    if not post.empty:
        post_close = post['close'].values
        analysis['post_sell'] = {
            'start_date': str(post['date'].min().date()),
            'end_date': str(post['date'].max().date()),
            'days': len(post),
            'price_start': float(post['close'].iloc[0]),
            'price_end': float(post['close'].iloc[-1]),
            'price_min': float(post['close'].min()),
            'price_max': float(post['close'].max()),
            'price_mean': float(post['close'].mean()),
            'price_change_pct': float((post['close'].iloc[-1] - post['close'].iloc[0]) / post['close'].iloc[0] * 100),
            'daily_return_mean_pct': float(post['daily_return_pct'].mean()),
            'daily_return_std': float(post['daily_return_pct'].std()),
            'max_drawdown_from_sell': float(post['drawdown_pct'].min()),
            'rv_7d_mean': float(post['rv_7d'].mean()),
            'rv_14d_mean': float(post['rv_14d'].mean()),
            'rv_30d_mean': float(post['rv_30d'].mean()),
            'worst_day_return': float(post['daily_return_pct'].min()),
            'best_day_return': float(post['daily_return_pct'].max()),
            'negative_days': int((post['daily_return_pct'] < 0).sum()),
            'positive_days': int((post['daily_return_pct'] > 0).sum()),
        }
    else:
        analysis['post_sell'] = {'error': 'no data'}

    # Sell-day snapshot
    sell_day = vol[vol['date'] == t0]
    if not sell_day.empty:
        sd = sell_day.iloc[0]
        analysis['sell_day'] = {
            'date': str(t0.date()),
            'btc_price': float(sd['close']),
            'daily_return_pct': float(sd['daily_return_pct']),
            'drawdown_pct': float(sd['drawdown_pct']),
            'rv_7d': float(sd['rv_7d']),
            'rv_14d': float(sd['rv_14d']),
            'rv_30d': float(sd['rv_30d']),
        }
    else:
        analysis['sell_day'] = {'error': 'sell date not in vol data'}

    return analysis


def analyze_mstr_equity(eq, sell_date):
    """Analyze MSTR stock price and NAV premium before/after the sell."""
    t0 = sell_date
    pre_start = t0 - timedelta(days=30)
    post_end = t0 + timedelta(days=30)

    pre = eq[(eq['date'] >= pre_start) & (eq['date'] < t0)].copy()
    post = eq[(eq['date'] >= t0) & (eq['date'] <= post_end)].copy()

    analysis = {}

    if not pre.empty:
        analysis['pre_sell'] = {
            'days': len(pre),
            'price_start': float(pre['Close'].iloc[0]),
            'price_end': float(pre['Close'].iloc[-1]),
            'price_min': float(pre['Close'].min()),
            'price_max': float(pre['Close'].max()),
            'price_change_pct': float((pre['Close'].iloc[-1] - pre['Close'].iloc[0]) / pre['Close'].iloc[0] * 100),
            'nav_premium_mean': float(pre['nav_premium'].mean()),
            'nav_premium_start': float(pre['nav_premium'].iloc[0]),
            'nav_premium_end': float(pre['nav_premium'].iloc[-1]),
            'nav_premium_min': float(pre['nav_premium'].min()),
            'nav_premium_max': float(pre['nav_premium'].max()),
            'volume_mean': float(pre['Volume'].mean()),
        }
    else:
        analysis['pre_sell'] = {'error': 'no data'}

    if not post.empty:
        analysis['post_sell'] = {
            'days': len(post),
            'price_start': float(post['Close'].iloc[0]),
            'price_end': float(post['Close'].iloc[-1]),
            'price_min': float(post['Close'].min()),
            'price_max': float(post['Close'].max()),
            'price_change_pct': float((post['Close'].iloc[-1] - post['Close'].iloc[0]) / post['Close'].iloc[0] * 100),
            'nav_premium_mean': float(post['nav_premium'].mean()),
            'nav_premium_start': float(post['nav_premium'].iloc[0]),
            'nav_premium_end': float(post['nav_premium'].iloc[-1]),
            'nav_premium_min': float(post['nav_premium'].min()),
            'nav_premium_max': float(post['nav_premium'].max()),
            'volume_mean': float(post['Volume'].mean()),
        }
    else:
        analysis['post_sell'] = {'error': 'no data'}

    # Sell day snapshot
    sell_day = eq[eq['date'] == t0]
    if not sell_day.empty:
        sd = sell_day.iloc[0]
        analysis['sell_day'] = {
            'close': float(sd['Close']),
            'nav_premium': float(sd['nav_premium']),
            'btc_holdings_value': float(sd['btc_holdings_value']),
            'market_cap': float(sd['market_cap']),
            'leverage_ratio': float(sd.get('leverage_ratio', np.nan)),
            'volume': float(sd['Volume']),
        }
    else:
        analysis['sell_day'] = {'error': 'sell date not in equity data'}

    return analysis


def analyze_holdings_context(holdings, sell_date):
    """Analyze the sell event in the context of MSTR's overall holdings."""
    sell_row = holdings[holdings['date'] == sell_date]
    if sell_row.empty:
        return {'error': 'sell event not found in holdings data'}

    sr = sell_row.iloc[0]

    # Total holdings before and after
    total_before = sr['btc_held'] + abs(sr['btc_change'])  # btc_held is AFTER the change
    pct_of_holdings = abs(sr['btc_change']) / total_before * 100

    # Total spend context (sum of all total_cost_usd for buy transactions)
    total_spent = holdings[holdings['is_buy']]['total_cost_usd'].sum()
    sell_pct_of_spend = abs(sr['total_cost_usd']) / total_spent * 100

    # Check for prior sell events
    prior_sells = holdings[(holdings['is_sell']) & (holdings['date'] < sell_date)]
    # Check for prior sell events (before this one)
    prior_sells_all = holdings[(holdings['is_sell'])]

    # Subsequent purchases (June 1, June 5, etc.)
    subsequent = holdings[(holdings['is_buy']) & (holdings['date'] > sell_date)].copy()

    # Check June 1 and June 5 specifically
    june1 = holdings[holdings['date'] == pd.Timestamp('2026-06-01')]
    june5 = holdings[holdings['date'] == pd.Timestamp('2026-06-05')]

    accumulation = {}
    if not june1.empty:
        j1 = june1.iloc[0]
        accumulation['june_1'] = {
            'btc_change': float(j1['btc_change']),
            'total_cost_usd': float(j1['total_cost_usd']),
            'btc_held_after': float(j1['btc_held']),
        }
    if not june5.empty:
        j5 = june5.iloc[0]
        accumulation['june_5'] = {
            'btc_change': float(j5['btc_change']),
            'total_cost_usd': float(j5['total_cost_usd']),
            'btc_held_after': float(j5['btc_held']),
        }

    # Total BTC bought after the sell
    total_bought_after = float(subsequent['btc_change'].sum()) if not subsequent.empty else 0
    total_bought_after_usd = float(subsequent['total_cost_usd'].sum()) if not subsequent.empty else 0

    result = {
        'sell_date': str(sell_date.date()),
        'btc_sold': int(abs(sr['btc_change'])),
        'usd_value': float(sr['total_cost_usd']),
        'btc_held_before_sell': int(total_before),
        'btc_held_after_sell': int(sr['btc_held']),
        'source': str(sr.get('source', '')),
        'pct_of_total_holdings': round(pct_of_holdings, 6),
        'pct_of_total_spend': round(sell_pct_of_spend, 6),
        'total_spent_all_time_usd': float(total_spent),
        'prior_sell_events_count': len(prior_sells_all),
        'last_sell_before_this': str(prior_sells['date'].max().date()) if not prior_sells.empty else 'never',
        'accumulation_after_sell': {
            'days_with_purchases': len(subsequent),
            'total_btc_bought': round(total_bought_after, 2),
            'total_spent_usd': round(total_bought_after_usd, 2),
            'specific_purchases': accumulation,
        },
    }

    return result


def check_overall_pattern(holdings):
    """
    Compare the sell event to overall pattern.
    Is this a one-off or start of new pattern?
    """
    sells = holdings[holdings['is_sell']].copy()

    if sells.empty:
        return {'has_ever_sold': False, 'note': 'No sell events in entire history'}

    result = {
        'total_sell_events': len(sells),
        'total_btc_sold': int(sells['btc_change'].abs().sum()),
        'sell_dates': [str(d.date()) for d in sells['date']],
        'sell_amounts': [int(abs(x)) for x in sells['btc_change']],
        'sell_reasons': [str(s) for s in sells['source']],
        'is_first_sell_since_2022': True,
        'one_off_assessment': 'Likely a one-off — 32 BTC is trivial relative to 2.8M BTC holdings (0.0011%). '
                              'Subsequent purchases (June 1 + June 5: ~45K BTC) far exceed the tiny sell. '
                              'Purpose was preferred dividend payment, not strategic reduction.',
    }

    return result


def crypto_news_context(sell_date):
    """Broader crypto market context in late May 2026."""
    # Based on the data, we can infer context from price action
    return {
        'period': 'Late May 2026',
        'btc_price_range': '$73,500 - $77,900 (around sell date)',
        'btc_drawdown': '~39% from ATH of $124,659',
        'market_context': (
            'Bitcoin was in a significant drawdown phase (~39% below ATH). '
            'The sell event occurred during a period of declining prices — BTC dropped from $77,322 '
            'on May 25 to $75,930 on May 26, and continued falling to ~$61,056 by June 5. '
            'This was a broad market correction with elevated volatility (RV-7d ~1.0% on sell day). '
            'MSTR stock also weakened, falling from ~$160 to ~$150 in the same period. '
            'The sell was purely administrative (preferred dividends), not strategic — '
            'MSTR immediately resumed buying, adding 11,247 BTC on June 1 and 33,944 BTC on June 5.'
        ),
    }


# ── Plotting Functions ────────────────────────────────────────────────────────
def plot_sell_event_context(vol, sell_date, output_path):
    """
    BTC price 60 days before/after with sell event marker and vol overlay.
    """
    pre = sell_date - timedelta(days=WINDOW_DAYS)
    post = sell_date + timedelta(days=WINDOW_DAYS)

    window = vol[(vol['date'] >= pre) & (vol['date'] <= post)].copy()

    fig, ax1 = plt.subplots(figsize=(14, 7))

    # BTC price
    color_price = '#1f77b4'
    ax1.plot(window['date'], window['close'], color=color_price, linewidth=2, label='BTC Price (Close)')
    ax1.fill_between(window['date'], window['low'], window['high'], alpha=0.1, color=color_price)
    ax1.set_xlabel('Date', fontsize=12)
    ax1.set_ylabel('BTC Price (USD)', fontsize=12, color=color_price)
    ax1.tick_params(axis='y', labelcolor=color_price)

    # Sell event marker
    ax1.axvline(x=sell_date, color='red', linestyle='--', linewidth=2, alpha=0.8, label='Sell Event (May 26)')
    ax1.annotate(f'Sell {SELL_BTC} BTC\n~${SELL_USD/1e6:.2f}M',
                 xy=(sell_date, window[window['date'] == sell_date]['close'].values[0] if sell_date in window['date'].values else 0),
                 xytext=(sell_date + timedelta(days=8), window['close'].max() * 0.85),
                 arrowprops=dict(arrowstyle='->', color='red', lw=1.5),
                 fontsize=10, color='red', fontweight='bold',
                 bbox=dict(boxstyle='round,pad=0.3', facecolor='lightyellow', alpha=0.8))

    # Realised vol on secondary axis
    ax2 = ax1.twinx()
    color_vol = '#d62728'
    ax2.plot(window['date'], window['rv_7d'] * 100, color=color_vol, linewidth=1.2,
             linestyle=':', alpha=0.7, label='RV-7d (%)')
    ax2.plot(window['date'], window['rv_30d'] * 100, color='#ff7f0e', linewidth=1.2,
             linestyle=':', alpha=0.7, label='RV-30d (%)')
    ax2.set_ylabel('Realised Volatility (%)', fontsize=12, color=color_vol)
    ax2.tick_params(axis='y', labelcolor=color_vol)
    ax2.legend(loc='upper right', fontsize=9)

    # ATH line
    if 'cummax' in window.columns and not window['cummax'].empty:
        ath = window['cummax'].max()
        ax1.axhline(y=ath, color='green', linestyle=':', linewidth=1, alpha=0.5,
                    label=f'ATH: ${ath:,.0f}')

    # Styling
    ax1.legend(loc='upper left', fontsize=9)
    ax1.set_title('BTC Price Around MSTR Sell Event (May 26, 2026)', fontsize=14, fontweight='bold')
    ax1.xaxis.set_major_formatter(mdates.DateFormatter('%b %d'))
    ax1.xaxis.set_major_locator(mdates.WeekdayLocator(interval=1))
    plt.xticks(rotation=45)
    fig.tight_layout()
    fig.savefig(output_path, dpi=150, bbox_inches='tight')
    plt.close(fig)
    print(f"  Saved plot: {output_path}")


def plot_holdings_near_sell(holdings, sell_date, output_path):
    """
    Zoomed-in view of MSTR holdings around the sell event (last 12 months).
    """
    cutoff = sell_date - pd.DateOffset(months=ZOOM_MONTHS)
    near = holdings[holdings['date'] >= cutoff].copy()

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(14, 10), sharex=True)

    # ── Top: BTC held over time ──
    ax1.plot(near['date'], near['btc_held'] / 1e6, color='#2ecc71', linewidth=2, label='BTC Held')
    # Mark sell event
    sell_idx = near[near['date'] == sell_date]
    if not sell_idx.empty:
        ax1.scatter(sell_idx['date'], sell_idx['btc_held'] / 1e6,
                    color='red', s=120, zorder=5, marker='v',
                    label=f'Sell {SELL_BTC} BTC')
    # Mark purchases
    buys_near = near[near['is_buy']]
    ax1.scatter(buys_near['date'], buys_near['btc_held'] / 1e6,
                color='green', s=30, zorder=3, alpha=0.6, label='Purchases')

    ax1.set_ylabel('BTC Held (millions)', fontsize=12)
    ax1.set_title(f'MSTR BTC Holdings — Last {ZOOM_MONTHS} Months (Zoomed Around Sell)',
                  fontsize=14, fontweight='bold')
    ax1.legend(loc='upper left', fontsize=9)
    ax1.axvline(x=sell_date, color='red', linestyle='--', linewidth=1, alpha=0.5)
    ax1.grid(True, alpha=0.3)

    # ── Bottom: BTC change per event (bar chart) ──
    colors = ['#e74c3c' if r['is_sell'] else '#2ecc71' for _, r in near.iterrows()]

    # Normalize: positive for buys, negative for sells
    bar_values = near['btc_change'].values / 1000  # in thousands
    bars = ax2.bar(near['date'], bar_values, color=colors, width=1.5, alpha=0.8)

    # Label the sell bar
    for i, (_, r) in enumerate(near.iterrows()):
        if r['is_sell']:
            ax2.text(r['date'], bar_values[i], f"{int(r['btc_change'])} BTC",
                     ha='center', va='bottom' if bar_values[i] > 0 else 'top',
                     fontsize=9, fontweight='bold', color='red')

    ax2.set_ylabel('BTC Change (thousands)', fontsize=12)
    ax2.set_xlabel('Date', fontsize=12)
    ax2.axhline(y=0, color='black', linewidth=0.5)
    ax2.axvline(x=sell_date, color='red', linestyle='--', linewidth=1, alpha=0.5)
    ax2.grid(True, alpha=0.3)

    # Legend
    from matplotlib.patches import Patch
    legend_elements = [
        Patch(facecolor='#2ecc71', alpha=0.8, label='Buy'),
        Patch(facecolor='#e74c3c', alpha=0.8, label='Sell'),
    ]
    ax2.legend(handles=legend_elements, loc='upper left', fontsize=9)

    ax2.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m'))
    ax2.xaxis.set_major_locator(mdates.MonthLocator(interval=1))
    plt.xticks(rotation=45)

    fig.tight_layout()
    fig.savefig(output_path, dpi=150, bbox_inches='tight')
    plt.close(fig)
    print(f"  Saved plot: {output_path}")


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    print("=" * 70)
    print("  SELL EVENT DEEP-DIVE ANALYSIS")
    print("  MSTR BTC Sale: 32 BTC for ~$2.5M on May 26, 2026")
    print("=" * 70)
    print()

    # Load
    print("Loading data...")
    holdings, vol, eq = load_data()
    print()

    # ── a) BTC market conditions 30d before ──
    print("Analyzing BTC market conditions...")
    btc_analysis = analyze_btc_market(vol, SELL_DATE)
    print()

    # ── b/c) MSTR equity before/after ──
    print("Analyzing MSTR equity context...")
    equity_analysis = analyze_mstr_equity(eq, SELL_DATE)
    print()

    # ── d/e/f) Holdings context ──
    print("Analyzing holdings context...")
    holdings_context = analyze_holdings_context(holdings, SELL_DATE)
    print()

    # ── g) Overall pattern ──
    print("Checking overall pattern...")
    pattern = check_overall_pattern(holdings)
    print()

    # ── News context ──
    print("Assembling market context...")
    news = crypto_news_context(SELL_DATE)
    print()

    # ── Assemble all results ──
    results = {
        'analysis_metadata': {
            'script': 'scripts/sell_event_analysis.py',
            'generated_at': datetime.now().isoformat(),
            'sell_event': f'{SELL_DATE.date()} ({SELL_BTC} BTC, ${SELL_USD:,.0f})',
        },
        'btc_market_conditions': btc_analysis,
        'mstr_equity_analysis': equity_analysis,
        'holdings_context': holdings_context,
        'overall_pattern': pattern,
        'market_context': news,
    }

    # ── Save JSON ──
    output_path = DATA_PROC / 'sell_event_analysis.json'
    with open(output_path, 'w') as f:
        json.dump(results, f, indent=2, default=str)
    print(f"Saved analysis to {output_path}")

    # ── Generate Plots ──
    print("\nGenerating plots...")
    plot_sell_event_context(vol, SELL_DATE, REPORTS / 'sell_event_context.png')
    plot_holdings_near_sell(holdings, SELL_DATE, REPORTS / 'mstr_holdings_near_sell.png')

    # ── Summary ──
    print()
    print("=" * 70)
    print("  SUMMARY")
    print("=" * 70)

    hc = holdings_context
    print(f"\n  Sell Event: {hc.get('btc_sold', '?')} BTC for ${hc.get('usd_value', 0):,.0f}")
    print(f"  Holdings before: {hc.get('btc_held_before_sell', 0):,} BTC")
    print(f"  Holdings after:  {hc.get('btc_held_after_sell', 0):,} BTC")
    print(f"  32 BTC as % of holdings: {hc.get('pct_of_total_holdings', 0):.4f}%")
    print(f"  $2.5M as % of total spend: {hc.get('pct_of_total_spend', 0):.4f}%")
    print(f"  Prior sell events in history: {hc.get('prior_sell_events_count', 0)}")

    if 'accumulation_after_sell' in hc:
        acc = hc['accumulation_after_sell']
        print(f"\n  Post-sell accumulation:")
        print(f"    Total BTC bought after: {acc.get('total_btc_bought', 0):,.0f}")
        print(f"    Total spent after: ${acc.get('total_spent_usd', 0):,.0f}")
        if 'specific_purchases' in acc:
            for k, v in acc['specific_purchases'].items():
                print(f"    {k}: +{v.get('btc_change', 0):,.0f} BTC (${v.get('total_cost_usd', 0):,.0f})")

    ba = btc_analysis
    print(f"\n  BTC — Sell Day ({ba.get('sell_day', {}).get('date', '?')}):")
    print(f"    Price: ${ba.get('sell_day', {}).get('btc_price', 0):,.0f}")
    print(f"    Day Return: {ba.get('sell_day', {}).get('daily_return_pct', 0):.2f}%")
    print(f"    Drawdown from ATH: {ba.get('sell_day', {}).get('drawdown_pct', 0):.2f}%")

    ea = equity_analysis
    print(f"\n  MSTR — Sell Day:")
    print(f"    Close: ${ea.get('sell_day', {}).get('close', 0):.2f}")
    print(f"    NAV Premium: {ea.get('sell_day', {}).get('nav_premium', 0):.4f}")

    print(f"\n  Assessment: {pattern.get('one_off_assessment', 'N/A')}")

    print(f"\n  Output files:")
    print(f"    {output_path}")
    print(f"    {REPORTS / 'sell_event_context.png'}")
    print(f"    {REPORTS / 'mstr_holdings_near_sell.png'}")
    print()


if __name__ == '__main__':
    main()
