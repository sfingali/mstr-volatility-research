#!/usr/bin/env python3
"""
Convertible Arbitrage Auto-Governor Model
==========================================
Models the delta-hedging dynamics of MSTR's convertible bond issuances and
quantifies the auto-stabilizing feedback loop:

BTC price → MSTR stock → delta changes → arb shorting → NAV premium → BTC buying capacity

Generates 5 visualizations + a detailed quantitative report.
"""

import os
import sys
import json
import logging
import warnings
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
from scipy import stats as scipy_stats
from scipy.stats import norm

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import matplotlib.lines as mlines
import seaborn as sns

warnings.filterwarnings('ignore', category=FutureWarning)
sns.set_style('whitegrid')
plt.rcParams['figure.figsize'] = (14, 8)
plt.rcParams['font.size'] = 11

logging.basicConfig(level=logging.INFO, format='%(asctime)s | %(levelname)s | %(message)s')
log = logging.getLogger(__name__)

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
REPORTS_DIR = os.path.join(PROJECT_ROOT, 'reports')
DATA_DIR = os.path.join(PROJECT_ROOT, 'data')
PROCESSED_DIR = os.path.join(DATA_DIR, 'processed')
os.makedirs(REPORTS_DIR, exist_ok=True)
os.makedirs(PROCESSED_DIR, exist_ok=True)

# ── Model Constants ──────────────────────────────────────────────────────────
IMPLIED_VOL = 0.50           # 50% typical vol for MSTR/BTC
RISK_FREE_RATE = 0.045       # ~4.5% risk-free rate (approximate over period)
CONV_PREMIUM = 0.30          # 30% typical conversion premium at issuance
COUPON_RATE = 0.0            # For delta calc, coupon on convert (use 0% as baseline)


def load_dataset(path: str) -> pd.DataFrame:
    """Load a CSV dataset, standardizing date handling."""
    full_path = os.path.join(PROJECT_ROOT, path)
    df = pd.read_csv(full_path)
    # Find date column
    date_col = None
    for col in ['date', 'Date', 'datetime', 'announce_date']:
        if col in df.columns:
            date_col = col
            break
    if date_col:
        df[date_col] = pd.to_datetime(df[date_col])
        if date_col != 'announce_date':
            df = df.set_index(date_col)
    log.info(f"Loaded {path}: {df.shape[0]} rows, {df.shape[1]} cols")
    return df


def black_scholes_delta(S: float, K: float, T: float, r: float,
                        sigma: float, q: float = 0.0) -> float:
    """
    Black-Scholes delta for a call option (convertible bond proxy).
    delta = N(d1)

    Parameters
    ----------
    S : float — current stock price
    K : float — strike price (conversion price)
    T : float — time to maturity in years
    r : float — risk-free rate
    sigma : float — implied volatility
    q : float — dividend yield (0 for MSTR)
    """
    if T <= 0 or sigma <= 0 or K <= 0 or S <= 0:
        return 0.0
    d1 = (np.log(S / K) + (r - q + 0.5 * sigma ** 2) * T) / (sigma * np.sqrt(T))
    return norm.cdf(d1)


def estimate_conversion_params(principal: float, stock_price_at_issuance: float,
                               conv_premium: float = CONV_PREMIUM) -> Tuple[float, float]:
    """
    Estimate conversion ratio and strike price for a convert.
    conversion_ratio ≈ principal / (stock_price × 1.3)
    strike_price = principal / conversion_ratio = stock_price × 1.3
    """
    strike = stock_price_at_issuance * (1 + conv_premium)
    # conversion ratio = principal / strike
    conv_ratio = principal / strike if strike > 0 else 0
    return conv_ratio, strike


def delta_at_price_curve(S_base: float, K: float, T: float, r: float,
                         sigma: float, pct_changes: List[float]) -> Dict[float, float]:
    """
    Calculate delta at various percentage changes from base stock price.
    Returns dict of {pct_change: delta}
    """
    result = {}
    for pct in pct_changes:
        S = S_base * (1 + pct)
        d = black_scholes_delta(S, K, T, r, sigma)
        result[pct] = d
    return result


# ═══════════════════════════════════════════════════════════════════════════════
# 1. LOAD AND PREPARE DATA
# ═══════════════════════════════════════════════════════════════════════════════
def load_all_data() -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Load all datasets needed for the model."""
    log.info("=" * 60)
    log.info("CONVERTIBLE ARBITRAGE AUTO-GOVERNOR MODEL")
    log.info("=" * 60)

    # MSTR equity data (daily)
    log.info("\n--- Loading MSTR equity data ---")
    equity = load_dataset('data/raw/mstr_equity.csv')
    log.info(f"  Date range: {equity.index.min().date()} to {equity.index.max().date()}")
    log.info(f"  MSTR price: ${equity['Close'].min():.2f} - ${equity['Close'].max():.2f}")
    log.info(f"  NAV premium: {equity['nav_premium'].min():.3f} - {equity['nav_premium'].max():.3f}")

    # Debt issuances
    log.info("\n--- Loading debt issuances ---")
    issuances = load_dataset('data/processed/mstr_debt_issuances.csv')
    # Handle the last issuance with missing data
    mask_missing = issuances['maturity_year'].isna()
    if mask_missing.any():
        log.warning(f"  Found {mask_missing.sum()} issuance(s) with missing data:")
        for _, r in issuances[mask_missing].iterrows():
            log.warning(f"    {r['announce_date'].date()}: ${r['principal_amount']:,.0f} - terms TBD")
        # Drop the last one with missing data or estimate
        issuances = issuances[~mask_missing].copy()

    issuances['maturity_year'] = issuances['maturity_year'].astype(int)
    issuances['coupon_rate'] = issuances['coupon_rate'].fillna(0.0)
    log.info(f"  {len(issuances)} issuances with complete data")
    total_principal = issuances['principal_amount'].sum()
    log.info(f"  Total convertible principal: ${total_principal:,.0f}")

    # BTC holdings
    log.info("\n--- Loading BTC holdings data ---")
    holdings = load_dataset('data/raw/mstr_holdings.csv')
    log.info(f"  {len(holdings)} transactions, total BTC: {holdings['btc_held'].iloc[-1]:,.0f}")

    # BTC volatility
    log.info("\n--- Loading BTC volatility data ---")
    btc_vol = load_dataset('data/processed/btc_volatility.csv')
    log.info(f"  Date range: {btc_vol.index.min()} to {btc_vol.index.max()}")

    return equity, issuances, holdings, btc_vol


# ═══════════════════════════════════════════════════════════════════════════════
# 2. MODEL THE DELTA-HEDGING FOR EACH CONVERT ISSUANCE
# ═══════════════════════════════════════════════════════════════════════════════
def prepare_convert_profiles(issuances: pd.DataFrame,
                             equity: pd.DataFrame) -> pd.DataFrame:
    """
    For each convert issuance, estimate conversion parameters and compute
    delta profiles at various MSTR share price levels.
    """
    log.info("\n--- Preparing convertible bond profiles ---")

    profiles = []
    # Reference date for TTE calculation — use the last equity date if we're
    # computing current profiles, or each issuance date for historical.
    # We'll store both the issuance-date params and time-series params.

    for idx, row in issuances.iterrows():
        issue_date = row['announce_date']
        principal = float(row['principal_amount'])
        coupon = float(row['coupon_rate'])
        maturity_year = int(row['maturity_year'])

        # Find MSTR stock price at issuance (or nearest date after)
        later = equity.index[equity.index >= issue_date]
        if len(later) == 0:
            log.warning(f"  No equity data for {issue_date.date()}, skipping")
            continue
        close_date = later[0]
        stock_price = float(equity.loc[close_date, 'Close'])
        shares_out = float(equity.loc[close_date, 'shares_outstanding'])

        # Estimate conversion parameters
        conv_ratio, strike = estimate_conversion_params(principal, stock_price)

        # Time to maturity at issuance
        maturity_date = pd.Timestamp(year=maturity_year, month=1, day=1) + \
                        pd.DateOffset(years=1) - pd.DateOffset(days=1)
        if maturity_year == issue_date.year:
            maturity_date = issue_date + pd.DateOffset(years=1)

        tte_at_issuance = (maturity_date - issue_date).days / 365.25

        # Delta at issuance
        delta_at_issue = black_scholes_delta(
            stock_price, strike, tte_at_issuance, RISK_FREE_RATE, IMPLIED_VOL
        )

        # Principal delta (dollar equivalent)
        principal_delta = principal * delta_at_issue

        # Short interest as % of shares
        si_pct = (principal_delta / shares_out) if shares_out > 0 else 0
        # Note: actual shares shorted = principal_delta / stock_price

        # Delta curve at various MSTR price changes from issuance price
        pct_changes = [-0.30, -0.20, -0.10, 0.0, 0.10, 0.20, 0.30]
        delta_curve = {}
        short_shares_curve = {}
        for pct in pct_changes:
            S = stock_price * (1 + pct)
            d = black_scholes_delta(S, strike, tte_at_issuance, RISK_FREE_RATE, IMPLIED_VOL)
            delta_curve[pct] = d
            # shares shorted = principal * delta / stock_price
            short_shares_curve[pct] = (principal * d) / S if S > 0 else 0

        # Note: the shares shorted = (principal × delta) / stock_price
        # But the NOTIONAL short = principal × delta
        shares_shorted_at_issue = principal_delta / stock_price if stock_price > 0 else 0

        profiles.append({
            'issue_date': issue_date,
            'maturity_year': maturity_year,
            'maturity_date': maturity_date,
            'principal': principal,
            'coupon': coupon,
            'stock_price_at_issuance': stock_price,
            'conv_ratio': conv_ratio,
            'strike': strike,
            'tte_at_issuance': tte_at_issuance,
            'delta_at_issuance': delta_at_issue,
            'shares_shorted_at_issuance': shares_shorted_at_issue,
            'short_interest_pct': si_pct,
            'principal_delta': principal_delta,
            'delta_curve': delta_curve,
            'short_shares_curve': short_shares_curve,
        })

        log.info(f"  {issue_date.date()} | Principal: ${principal:,.0f} | "
                 f"Strike: ${strike:,.0f} | TTE: {tte_at_issuance:.1f}y | "
                 f"Delta: {delta_at_issue:.3f} | Short: {shares_shorted_at_issue:,.0f} sh")

    profiles_df = pd.DataFrame(profiles)
    log.info(f"\n  Total arb short interest at issuance: "
             f"${profiles_df['principal_delta'].sum()/1e9:.2f}B notional")
    log.info(f"  Total shares shorted at issuance: "
             f"{profiles_df['shares_shorted_at_issuance'].sum():,.0f}")
    return profiles_df


# ═══════════════════════════════════════════════════════════════════════════════
# 3. BUILD THE FEEDBACK LOOP MODEL (DAILY TIMESERIES)
# ═══════════════════════════════════════════════════════════════════════════════
def build_feedback_loop_timeseries(equity: pd.DataFrame,
                                   profiles: pd.DataFrame) -> pd.DataFrame:
    """
    For each trading day, compute:
    - Total arb short interest (sum of principal_i × delta_i for active converts)
    - Suppression factor = arb_short_interest / MSTR_market_cap
    - Governor intensity = suppression_factor × BTC_price_change_30d
    """
    log.info("\n--- Building feedback loop timeseries ---")

    results = []
    daily = equity.copy()

    # Track which converts are active on each date
    for date_idx, row in daily.iterrows():
        stock_price = float(row['Close'])
        market_cap = float(row['market_cap'])
        shares_out = float(row['shares_outstanding'])
        nav_premium = float(row['nav_premium'])
        btc_price = float(row['btc_price'])

        # Which converts are active (issued and not yet matured)
        total_short_notional = 0.0
        total_shares_shorted = 0.0
        active_converts = []
        total_active_principal = 0.0

        for _, p in profiles.iterrows():
            issue_date = p['issue_date']
            maturity_date = p['maturity_date']

            if issue_date <= date_idx <= maturity_date:
                tte = (maturity_date - date_idx).days / 365.25
                if tte <= 0:
                    continue

                strike = float(p['strike'])
                principal = float(p['principal'])
                coupon = float(p['coupon'])

                # Current delta given current stock price
                current_delta = black_scholes_delta(
                    stock_price, strike, tte, RISK_FREE_RATE, IMPLIED_VOL
                )

                notional_short = principal * current_delta
                shares_shorted = notional_short / stock_price if stock_price > 0 else 0

                total_short_notional += notional_short
                total_shares_shorted += shares_shorted
                total_active_principal += principal
                active_converts.append({
                    'issue_date': str(issue_date.date()),
                    'principal': principal,
                    'strike': strike,
                    'delta': current_delta,
                    'tte': tte,
                    'shares_shorted': shares_shorted,
                })

        # Suppression factor = arb short interest as fraction of market cap
        suppression_factor = total_short_notional / market_cap if market_cap > 0 else 0

        # Short interest as % of shares outstanding (realistically capped at 100%)
        si_pct_raw = (total_shares_shorted / shares_out * 100) if shares_out > 0 else 0
        si_pct_of_shares = min(si_pct_raw, 100.0)  # cap at 100% of float

        results.append({
            'date': date_idx,
            'stock_price': stock_price,
            'market_cap': market_cap,
            'shares_outstanding': shares_out,
            'nav_premium': nav_premium,
            'btc_price': btc_price,
            'total_active_principal': total_active_principal,
            'total_short_notional': total_short_notional,
            'total_shares_shorted': total_shares_shorted,
            'suppression_factor': suppression_factor,
            'si_pct_of_shares': si_pct_of_shares,
            'n_active_converts': len(active_converts),
            'active_converts': active_converts,
        })

    feedback_df = pd.DataFrame(results)
    feedback_df['date'] = pd.to_datetime(feedback_df['date'])
    feedback_df = feedback_df.set_index('date')

    # Compute governor intensity: 30d BTC change × suppression factor
    feedback_df['btc_price_30d_change'] = feedback_df['btc_price'].pct_change(periods=21)  # ~30 trading days
    # Actually let's use calendar 30d via the BTC vol data's RV approach
    # But we have daily data, so 21 trading days ≈ 30 calendar days
    feedback_df['btc_price_30d_change'] = feedback_df['btc_price'].pct_change(periods=21)

    feedback_df['governor_intensity'] = (
        feedback_df['suppression_factor'] * feedback_df['btc_price_30d_change'].abs()
    )

    # Next-day NAV premium change
    feedback_df['nav_premium_change_1d'] = feedback_df['nav_premium'].diff(1).shift(-1)
    feedback_df['nav_premium_change_5d'] = feedback_df['nav_premium'].diff(5).shift(-5)
    feedback_df['nav_premium_change_21d'] = feedback_df['nav_premium'].diff(21).shift(-21)

    # Lagged suppression for predictive analysis
    feedback_df['suppression_factor_lag1'] = feedback_df['suppression_factor'].shift(1)
    feedback_df['suppression_factor_lag5'] = feedback_df['suppression_factor'].shift(5)

    log.info(f"  Computed {len(feedback_df)} daily observations")
    log.info(f"  Date range: {feedback_df.index.min().date()} to {feedback_df.index.max().date()}")
    log.info(f"  Max short notional: ${feedback_df['total_short_notional'].max()/1e9:.2f}B")
    log.info(f"  Max suppression factor: {feedback_df['suppression_factor'].max():.4f}")
    log.info(f"  Mean suppression factor: {feedback_df['suppression_factor'].mean():.4f}")

    return feedback_df


# ═══════════════════════════════════════════════════════════════════════════════
# 4. QUANTIFY THE DAMPENING EFFECT — REGRESSION & CORRELATION
# ═══════════════════════════════════════════════════════════════════════════════
def analyze_dampening(feedback_df: pd.DataFrame) -> Dict:
    """Regression and correlation analysis of the arb dampening effect."""
    log.info("\n--- Quantifying dampening effect ---")

    analysis = {}

    # Drop NaNs for regression
    valid = feedback_df.dropna(subset=['suppression_factor', 'nav_premium_change_5d'])

    # 1) Correlation: suppression factor vs subsequent NAV premium change
    corr_1d = valid['suppression_factor'].corr(valid['nav_premium_change_1d'])
    corr_5d = valid['suppression_factor'].corr(valid['nav_premium_change_5d'])
    corr_21d = valid['suppression_factor'].corr(valid['nav_premium_change_21d'])

    log.info(f"  Correlation: suppression_factor vs NAV change +1d: {corr_1d:.4f}")
    log.info(f"  Correlation: suppression_factor vs NAV change +5d: {corr_5d:.4f}")
    log.info(f"  Correlation: suppression_factor vs NAV change +21d: {corr_21d:.4f}")

    analysis['correlation_suppression_vs_nav_change'] = {
        '1d': round(corr_1d, 4) if not np.isnan(corr_1d) else None,
        '5d': round(corr_5d, 4) if not np.isnan(corr_5d) else None,
        '21d': round(corr_21d, 4) if not np.isnan(corr_21d) else None,
    }

    # 2) OLS regression: NAV premium change ~ suppression factor
    valid_reg = valid.dropna(subset=['suppression_factor', 'nav_premium_change_5d'])
    if len(valid_reg) > 10:
        X = valid_reg['suppression_factor'].values
        y = valid_reg['nav_premium_change_5d'].values
        slope, intercept, r_value, p_value, std_err = scipy_stats.linregress(X, y)

        log.info(f"  OLS: NAV_5d_change = {intercept:.4f} + {slope:.4f} × suppression")
        log.info(f"  R²: {r_value**2:.4f}, p-value: {p_value:.6f}")

        analysis['ols_nav_change_vs_suppression'] = {
            'slope': round(slope, 4),
            'intercept': round(intercept, 4),
            'r_squared': round(r_value**2, 4),
            'p_value': round(p_value, 6),
            'std_err': round(std_err, 4),
            'n_observations': len(valid_reg),
        }
    else:
        analysis['ols_nav_change_vs_suppression'] = {'error': 'insufficient data'}

    # 3) Cross-correlation: BTC price changes vs arb short interest changes
    feedback_df['short_notional_change_21d'] = feedback_df['total_short_notional'].pct_change(periods=21)
    cc_valid = feedback_df.dropna(subset=['btc_price_30d_change', 'short_notional_change_21d'])

    if len(cc_valid) > 30:
        cc = cc_valid['btc_price_30d_change'].corr(cc_valid['short_notional_change_21d'])

        # Cross-correlation at various lags
        cc_lags = {}
        for lag in [-21, -10, -5, -1, 0, 1, 5, 10, 21]:
            shifted = cc_valid['short_notional_change_21d'].shift(lag)
            both_valid = cc_valid['btc_price_30d_change'].notna() & shifted.notna()
            if both_valid.sum() > 30:
                c = cc_valid.loc[both_valid, 'btc_price_30d_change'].corr(shifted[both_valid])
                if not np.isnan(c):
                    cc_lags[f'lag_{lag}d'] = round(c, 4)

        analysis['cross_correlation_btc_vs_short'] = {
            'contemporaneous': round(cc, 4) if not np.isnan(cc) else None,
            'by_lag_days': cc_lags,
        }
        log.info(f"  Cross-correlation by lag: {cc_lags}")

    # 4) Suppression factor in different BTC regimes
    if 'btc_price_30d_change' in feedback_df.columns:
        up = feedback_df[feedback_df['btc_price_30d_change'] > 0.05]['suppression_factor'].dropna()
        down = feedback_df[feedback_df['btc_price_30d_change'] < -0.05]['suppression_factor'].dropna()
        flat = feedback_df[feedback_df['btc_price_30d_change'].abs() <= 0.05]['suppression_factor'].dropna()

        analysis['suppression_by_btc_regime'] = {
            'btc_up_5pct': {
                'mean': round(up.mean(), 4) if len(up) > 0 else None,
                'median': round(up.median(), 4) if len(up) > 0 else None,
                'std': round(up.std(), 4) if len(up) > 0 else None,
                'n_days': len(up),
            },
            'btc_down_5pct': {
                'mean': round(down.mean(), 4) if len(down) > 0 else None,
                'median': round(down.median(), 4) if len(down) > 0 else None,
                'std': round(down.std(), 4) if len(down) > 0 else None,
                'n_days': len(down),
            },
            'btc_flat': {
                'mean': round(flat.mean(), 4) if len(flat) > 0 else None,
                'median': round(flat.median(), 4) if len(flat) > 0 else None,
                'std': round(flat.std(), 4) if len(flat) > 0 else None,
                'n_days': len(flat),
            },
        }
        log.info(f"  Suppression when BTC up >5%: mean={analysis['suppression_by_btc_regime']['btc_up_5pct']['mean']}, "
                 f"n={analysis['suppression_by_btc_regime']['btc_up_5pct']['n_days']}")
        log.info(f"  Suppression when BTC down <5%: mean={analysis['suppression_by_btc_regime']['btc_down_5pct']['mean']}, "
                 f"n={analysis['suppression_by_btc_regime']['btc_down_5pct']['n_days']}")

    # 5) Counterfactual: if arb shorting was removed, how much higher would MSTR be?
    # Use a conservative model: the "drag" is proportional to short interest
    # relative to typical market depth. Cap adjustment to avoid unrealistic values.
    # A reasonable assumption: each 1% of SI (of float) suppresses price by ~0.5%
    # (standard market microstructure estimate)
    feedback_df['implied_drag_per_share'] = np.minimum(
        feedback_df['si_pct_of_shares'] * 0.005 * feedback_df['stock_price'],
        feedback_df['stock_price'] * 0.50  # cap at 50% of current price
    )

    feedback_df['counterfactual_price'] = (
        feedback_df['stock_price'] + feedback_df['implied_drag_per_share']
    )

    analysis['counterfactual'] = {
        'mean_drag_per_share': round(feedback_df['implied_drag_per_share'].mean(), 2),
        'max_drag_per_share': round(feedback_df['implied_drag_per_share'].max(), 2),
        'actual_latest_price': round(float(feedback_df['stock_price'].iloc[-1]), 2),
        'counterfactual_latest_price': round(float(feedback_df['counterfactual_price'].iloc[-1]), 2),
        'mean_counterfactual_price': round(feedback_df['counterfactual_price'].mean(), 2),
        'max_counterfactual_increase_pct': round(
            (feedback_df['counterfactual_price'] / feedback_df['stock_price'] - 1).max() * 100, 2
        ),
    }
    log.info(f"  Mean price drag per share: ${analysis['counterfactual']['mean_drag_per_share']}")
    log.info(f"  Max counterfactual increase: {analysis['counterfactual']['max_counterfactual_increase_pct']}%")

    # Summary stats
    analysis['summary_stats'] = {
        'total_active_principal_max': round(feedback_df['total_active_principal'].max() / 1e9, 2),
        'total_short_notional_max': round(feedback_df['total_short_notional'].max() / 1e9, 2),
        'total_short_notional_mean': round(feedback_df['total_short_notional'].mean() / 1e9, 2),
        'total_shares_shorted_max': round(feedback_df['total_shares_shorted'].max(), 0),
        'total_shares_shorted_mean': round(feedback_df['total_shares_shorted'].mean(), 0),
        'suppression_factor_max': round(float(feedback_df['suppression_factor'].max()), 4),
        'suppression_factor_mean': round(float(feedback_df['suppression_factor'].mean()), 4),
        'suppression_factor_median': round(float(feedback_df['suppression_factor'].median()), 4),
        'suppression_factor_std': round(float(feedback_df['suppression_factor'].std()), 4),
        'si_pct_of_shares_max': round(float(feedback_df['si_pct_of_shares'].max()), 2),
        'si_pct_of_shares_mean': round(float(feedback_df['si_pct_of_shares'].mean()), 2),
        'n_trading_days': len(feedback_df),
    }

    return analysis, feedback_df


# ═══════════════════════════════════════════════════════════════════════════════
# 5. GENERATE PLOTS
# ═══════════════════════════════════════════════════════════════════════════════
def plot_delta_profiles(profiles: pd.DataFrame):
    """Plot 1: Delta as function of MSTR stock price for each major convert."""
    log.info("\n--- Generating plot: Convert Arb Delta Profile ---")
    fig, ax = plt.subplots(figsize=(14, 8))

    pct_changes = np.linspace(-0.4, 0.4, 50)

    # Color map for different issuances
    colors = plt.cm.viridis(np.linspace(0, 0.9, len(profiles)))

    for idx, (_, p) in enumerate(profiles.iterrows()):
        S_base = float(p['stock_price_at_issuance'])
        K = float(p['strike'])
        principal = float(p['principal'])
        T = float(p['tte_at_issuance'])

        prices = [S_base * (1 + pct) for pct in pct_changes]
        deltas = [black_scholes_delta(S, K, T, RISK_FREE_RATE, IMPLIED_VOL) for S in prices]
        short_values = [d * principal / 1e9 for d in deltas]  # $B short

        label = f"${principal/1e9:.1f}B @ {p['issue_date'].strftime('%b %Y')} (K=${K:,.0f})"
        ax.plot(prices, deltas, color=colors[idx], linewidth=2, label=label, alpha=0.8)

        # Mark delta at issuance
        ax.scatter([S_base], [p['delta_at_issuance']], color=colors[idx], s=80, zorder=5,
                   edgecolors='white', linewidth=1.5)

    ax.axhline(y=0.5, color='gray', linestyle='--', alpha=0.5, label='ATM (delta=0.5)')
    ax.axhline(y=0.0, color='black', linestyle=':', alpha=0.3)
    ax.axhline(y=1.0, color='black', linestyle=':', alpha=0.3)

    ax.set_xlabel('MSTR Stock Price ($)', fontsize=12)
    ax.set_ylabel('Call Option Delta (N(d1))', fontsize=12)
    ax.set_title('Convertible Bond Delta Profiles by Issuance\n(Higher MSTR Price → Higher Delta → More Arb Shorting)', fontsize=14)
    ax.legend(fontsize=9, loc='upper left', framealpha=0.9)
    ax.grid(True, alpha=0.3)

    # Annotate the mechanism
    ax.annotate('BTC Rallies →\nMSTR Rises →\nDelta Increases →\nMORE SHORTING',
                xy=(0.7, 0.3), xycoords='axes fraction', fontsize=10,
                bbox=dict(boxstyle='round,pad=0.3', facecolor='lightcoral', alpha=0.3))
    ax.annotate('BTC Drops →\nMSTR Falls →\nDelta Decreases →\nCOVER SHORTS',
                xy=(0.05, 0.7), xycoords='axes fraction', fontsize=10,
                bbox=dict(boxstyle='round,pad=0.3', facecolor='lightgreen', alpha=0.3))

    plt.tight_layout()
    path = os.path.join(REPORTS_DIR, 'convert_arb_delta_profile.png')
    fig.savefig(path, dpi=150, bbox_inches='tight')
    plt.close(fig)
    log.info(f"  Saved to {path}")


def plot_short_interest_timeseries(feedback_df: pd.DataFrame):
    """Plot 2: Total arb short interest over time with NAV premium overlay."""
    log.info("\n--- Generating plot: Convert Arb Short Interest Timeseries ---")
    fig, ax1 = plt.subplots(figsize=(16, 8))

    # Plot arb short interest (bar/area)
    color1 = '#d62728'
    color2 = '#1f77b4'

    ax1.fill_between(feedback_df.index, feedback_df['total_short_notional'] / 1e9,
                      0, alpha=0.3, color=color1)
    ax1.plot(feedback_df.index, feedback_df['total_short_notional'] / 1e9,
             color=color1, linewidth=1.5, label='Arb Short Interest ($B Notional)')
    ax1.set_ylabel('Arb Short Interest ($B Notional)', color=color1, fontsize=12)
    ax1.tick_params(axis='y', labelcolor=color1)

    # NAV premium on secondary axis
    ax2 = ax1.twinx()
    ax2.plot(feedback_df.index, feedback_df['nav_premium'], color=color2, linewidth=1.5,
             label='MSTR NAV Premium', alpha=0.8)
    ax2.set_ylabel('MSTR NAV Premium (×)', color=color2, fontsize=12)
    ax2.tick_params(axis='y', labelcolor=color2)
    ax2.axhline(y=1.0, color=color2, linestyle='--', alpha=0.3)

    # Mark convertible issuances with vertical lines
    ax1.axvline(x=pd.Timestamp('2024-09-17'), color='green', linestyle=':', alpha=0.5,
                label='$1B Convert (Sep 2024)')
    ax1.axvline(x=pd.Timestamp('2024-11-20'), color='green', linestyle=':', alpha=0.7,
                label='$3B Convert (Nov 2024)')
    ax1.axvline(x=pd.Timestamp('2025-03-03'), color='darkgreen', linestyle=':', alpha=0.7,
                label='$2.1B Convert (Mar 2025)')

    lines1, labels1 = ax1.get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()
    ax1.legend(lines1 + lines2, labels1 + labels2, loc='upper left', fontsize=10)

    ax1.set_title('Convertible Arbitrage Short Interest vs MSTR NAV Premium\n'
                  'The Auto-Governor in Action', fontsize=14)
    ax1.set_xlabel('Date', fontsize=12)
    ax1.grid(True, alpha=0.3)

    plt.tight_layout()
    path = os.path.join(REPORTS_DIR, 'convert_arb_short_interest_timeseries.png')
    fig.savefig(path, dpi=150, bbox_inches='tight')
    plt.close(fig)
    log.info(f"  Saved to {path}")


def plot_suppression_vs_nav(feedback_df: pd.DataFrame):
    """Plot 3: Scatter of suppression factor vs NAV premium change."""
    log.info("\n--- Generating plot: Suppression Factor vs NAV Premium Change ---")
    fig, axes = plt.subplots(1, 2, figsize=(16, 7))

    valid = feedback_df.dropna(subset=['suppression_factor', 'nav_premium_change_5d'])

    # Scatter: suppression factor vs NAV change
    ax = axes[0]
    sc = ax.scatter(valid['suppression_factor'], valid['nav_premium_change_5d'],
                    c=valid['btc_price_30d_change'].fillna(0), cmap='RdYlGn',
                    s=15, alpha=0.6, edgecolors='none')
    plt.colorbar(sc, ax=ax, label='BTC 30d Price Change')

    # Regression line
    X = valid['suppression_factor'].values
    y = valid['nav_premium_change_5d'].values
    slope, intercept, r_val, p_val, _ = scipy_stats.linregress(X, y)
    x_line = np.linspace(X.min(), X.max(), 100)
    y_line = slope * x_line + intercept
    ax.plot(x_line, y_line, 'r--', linewidth=2,
            label=f'OLS: slope={slope:.3f}, R²={r_val**2:.3f}')

    ax.axhline(y=0, color='gray', linestyle=':', alpha=0.5)
    ax.set_xlabel('Suppression Factor (Arb Short / Market Cap)', fontsize=12)
    ax.set_ylabel('NAV Premium Change (5d forward)', fontsize=12)
    ax.set_title('Does Arb Shorting Predict NAV Compression?', fontsize=13)
    ax.legend(fontsize=10)
    ax.grid(True, alpha=0.3)

    # Histogram: suppression factor distribution
    ax = axes[1]
    # Split by BTC regime
    up = feedback_df[feedback_df['btc_price_30d_change'] > 0.03]['suppression_factor'].dropna()
    down = feedback_df[feedback_df['btc_price_30d_change'] < -0.03]['suppression_factor'].dropna()
    flat = feedback_df[feedback_df['btc_price_30d_change'].abs() <= 0.03]['suppression_factor'].dropna()

    ax.hist(up, bins=30, alpha=0.5, label=f'BTC Up >3% (n={len(up)})', color='green')
    ax.hist(down, bins=30, alpha=0.5, label=f'BTC Down >3% (n={len(down)})', color='red')
    ax.hist(flat, bins=30, alpha=0.5, label=f'BTC Flat (n={len(flat)})', color='gray')
    ax.axvline(x=feedback_df['suppression_factor'].median(), color='black', linestyle='--',
               label=f'Median: {feedback_df["suppression_factor"].median():.4f}')
    ax.set_xlabel('Suppression Factor', fontsize=12)
    ax.set_ylabel('Frequency', fontsize=12)
    ax.set_title('Suppression Factor Distribution by BTC Regime', fontsize=13)
    ax.legend(fontsize=9)
    ax.grid(True, alpha=0.3)

    plt.suptitle('Convert Arb Suppression Analysis', fontsize=15, y=1.01)
    plt.tight_layout()
    path = os.path.join(REPORTS_DIR, 'convert_arb_suppression_vs_nav.png')
    fig.savefig(path, dpi=150, bbox_inches='tight')
    plt.close(fig)
    log.info(f"  Saved to {path}")


def plot_governor_loop():
    """Plot 4: Flowchart visualization of the feedback loop."""
    log.info("\n--- Generating plot: Governor Feedback Loop Diagram ---")
    fig, ax = plt.subplots(figsize=(16, 10))
    ax.set_xlim(0, 10)
    ax.set_ylim(0, 10)
    ax.axis('off')

    # Node positions (x, y)
    nodes = {
        'btc_price': (5, 9.2),
        'mstr_stock': (5, 7.4),
        'delta_change': (5, 5.6),
        'arb_shorting': (5, 3.8),
        'nav_premium': (1.5, 5.6),
        'btc_buying': (8.5, 5.6),
    }

    # Node styling
    box_style = dict(boxstyle='round,pad=0.8', facecolor='lightblue', edgecolor='navy', linewidth=2)
    box_style_red = dict(boxstyle='round,pad=0.8', facecolor='lightcoral', edgecolor='darkred', linewidth=2)
    box_style_green = dict(boxstyle='round,pad=0.8', facecolor='lightgreen', edgecolor='darkgreen', linewidth=2)
    box_style_orange = dict(boxstyle='round,pad=0.8', facecolor='#FFD700', edgecolor='#B8860B', linewidth=2)
    box_style_purple = dict(boxstyle='round,pad=0.8', facecolor='#DDA0DD', edgecolor='#8B008B', linewidth=2)

    # Draw nodes
    texts = {}
    texts['btc_price'] = ax.text(nodes['btc_price'][0], nodes['btc_price'][1],
                                  'BTC Price\nMoves', ha='center', va='center',
                                  fontsize=13, fontweight='bold', bbox=box_style_orange)

    texts['mstr_stock'] = ax.text(nodes['mstr_stock'][0], nodes['mstr_stock'][1],
                                   'MSTR Stock\nPrice Changes', ha='center', va='center',
                                   fontsize=13, fontweight='bold', bbox=box_style)

    texts['delta_change'] = ax.text(nodes['delta_change'][0], nodes['delta_change'][1],
                                     'Convert Delta\nChanges (N(d1))', ha='center', va='center',
                                     fontsize=13, fontweight='bold', bbox=box_style_purple)

    texts['arb_shorting'] = ax.text(nodes['arb_shorting'][0], nodes['arb_shorting'][1],
                                     'Arb Funds\nShort/Buy-Back MSTR', ha='center', va='center',
                                     fontsize=13, fontweight='bold', bbox=box_style_red)

    texts['nav_premium'] = ax.text(nodes['nav_premium'][0], nodes['nav_premium'][1],
                                    'NAV Premium\nContracts/Expands', ha='center', va='center',
                                    fontsize=13, fontweight='bold', bbox=box_style_green)

    texts['btc_buying'] = ax.text(nodes['btc_buying'][0], nodes['btc_buying'][1],
                                   'BTC Buying\nCapacity', ha='center', va='center',
                                   fontsize=13, fontweight='bold', bbox=box_style_green)

    # Draw arrows with labels
    def draw_arrow(x1, y1, x2, y2, label='', color='navy', style='->', lw=2.5):
        ax.annotate('', xy=(x2, y2), xytext=(x1, y1),
                    arrowprops=dict(arrowstyle=style, color=color, lw=lw,
                                    connectionstyle='arc3,rad=0.2'))
        if label:
            mid_x = (x1 + x2) / 2
            mid_y = (y1 + y2) / 2 + 0.15
            # Offset for curved arrows
            if abs(x2 - x1) < 2:
                mid_x = x1 + 0.7
            ax.text(mid_x, mid_y, label, ha='center', va='bottom',
                    fontsize=10, fontweight='bold', color=color,
                    bbox=dict(boxstyle='round,pad=0.2', facecolor='white', alpha=0.8))

    # Main loop: BTC → MSTR → Delta → Arb
    draw_arrow(5, 8.8, 5, 7.9, 'BTC rallies → MSTR up\nBTC drops → MSTR down', 'darkblue')
    draw_arrow(5, 7.0, 5, 6.1, 'Stock price change\nalters delta', 'darkblue')
    draw_arrow(5, 5.2, 5, 4.3, 'Δ↑ → short more\nΔ↓ → buy back', 'darkred')

    # Arb shorting → NAV premium (dampening)
    draw_arrow(4.2, 4.0, 2.3, 5.2, 'Shorting caps MSTR\n→ NAV premium compresses', 'darkgreen')

    # NAV premium → BTC buying (constraint)
    draw_arrow(2.3, 6.0, 4.0, 7.0, 'Low NAV → less accretive\n→ fewer converts issued', 'darkgreen',
               style='->', lw=2)

    # Arb shorting → BTC buying (direct)
    draw_arrow(5.8, 4.0, 7.7, 5.2, 'Suppression reduces\nconvert attractiveness', 'darkgreen')

    # BTC buying → BTC price
    draw_arrow(8.5, 6.0, 7.0, 8.5, 'Less BTC buying\n→ BTC price pressure', 'saddlebrown', style='->', lw=2)

    # Negative feedback annotation
    ax.text(5, 1.8, '⬇ NEGATIVE FEEDBACK LOOP ⬇',
            ha='center', va='center', fontsize=14, fontweight='bold',
            color='darkred',
            bbox=dict(boxstyle='round,pad=0.5', facecolor='mistyrose', edgecolor='darkred', linewidth=2))

    # Mechanism description
    mech_text = (
        "The Convertible Arb Auto-Governor:\n"
        "• BTC ↑ → MSTR ↑ → Delta ↑ → Arb Funds SHORT MORE → MSTR capped\n"
        "• BTC ↓ → MSTR ↓ → Delta ↓ → Arb Funds BUY BACK → MSTR supported\n"
        "• Result: MSTR volatility is passively dampened by the arb mechanism\n"
        "• This is NOT a prediction — it's a structural feature of the convertible market"
    )
    ax.text(5, 0.8, mech_text, ha='center', va='center', fontsize=11,
            bbox=dict(boxstyle='round,pad=0.5', facecolor='#FFF8DC', edgecolor='#DAA520', linewidth=1.5))

    ax.set_title('MSTR Convertible Arbitrage Auto-Governor: Feedback Loop',
                 fontsize=16, fontweight='bold', pad=20)

    plt.tight_layout()
    path = os.path.join(REPORTS_DIR, 'convert_arb_governor_loop.png')
    fig.savefig(path, dpi=150, bbox_inches='tight')
    plt.close(fig)
    log.info(f"  Saved to {path}")


def plot_counterfactual(feedback_df: pd.DataFrame):
    """Plot 5: Actual vs counterfactual MSTR price without arb suppression."""
    log.info("\n--- Generating plot: Market Impact Counterfactual ---")
    fig, ax = plt.subplots(figsize=(16, 8))

    # Focus on period when arb was active (2024+)
    mask = feedback_df.index >= pd.Timestamp('2024-01-01')
    plot_df = feedback_df[mask].copy()

    if len(plot_df) < 10:
        plot_df = feedback_df.copy()

    ax.plot(plot_df.index, plot_df['stock_price'], color='#1f77b4', linewidth=2,
            label='Actual MSTR Share Price')
    ax.plot(plot_df.index, plot_df['counterfactual_price'], color='#d62728', linewidth=2,
            linestyle='--', label='Counterfactual (no arb suppression)',
            alpha=0.8)

    # Fill between
    ax.fill_between(plot_df.index, plot_df['stock_price'], plot_df['counterfactual_price'],
                    alpha=0.15, color='green',
                    label='Estimated Arb Suppression Drag')

    # Annotate key issuance events
    events = [
        (pd.Timestamp('2024-09-17'), '$1.0B\nConvert'),
        (pd.Timestamp('2024-11-20'), '$3.0B\nConvert'),
        (pd.Timestamp('2025-03-03'), '$2.1B\nConvert'),
    ]
    for dt, label in events:
        if dt in plot_df.index or dt >= plot_df.index[0]:
            val = plot_df['stock_price'].loc[plot_df.index >= dt]
            y_val = val.iloc[0] if len(val) > 0 else 0
            ax.axvline(x=dt, color='green', linestyle=':', alpha=0.5, linewidth=1.5)
            ax.annotate(label, xy=(dt, y_val), xytext=(dt, y_val + plot_df['stock_price'].max() * 0.08),
                        ha='center', fontsize=9, fontweight='bold', color='green',
                        arrowprops=dict(arrowstyle='->', color='green', alpha=0.5))

    ax.set_xlabel('Date', fontsize=12)
    ax.set_ylabel('MSTR Share Price ($)', fontsize=12)
    ax.set_title('Convertible Arb Market Impact: Actual vs Counterfactual\n'
                 'Estimated price suppression from arb shorting', fontsize=14)
    ax.legend(fontsize=11, loc='upper left')
    ax.grid(True, alpha=0.3)

    # Stats box
    latest_drag = plot_df['implied_drag_per_share'].iloc[-1]
    mean_drag = plot_df['implied_drag_per_share'].mean()
    max_drag = plot_df['implied_drag_per_share'].max()
    stats_text = (f'Latest drag: ${latest_drag:.2f}/share\n'
                  f'Mean drag: ${mean_drag:.2f}/share\n'
                  f'Max drag: ${max_drag:.2f}/share')
    ax.text(0.02, 0.97, stats_text, transform=ax.transAxes, fontsize=11, va='top',
            bbox=dict(boxstyle='round,pad=0.5', facecolor='wheat', alpha=0.8))

    plt.tight_layout()
    path = os.path.join(REPORTS_DIR, 'convert_arb_market_impact.png')
    fig.savefig(path, dpi=150, bbox_inches='tight')
    plt.close(fig)
    log.info(f"  Saved to {path}")


def plot_all(profiles: pd.DataFrame, feedback_df: pd.DataFrame):
    """Generate all 5 plots."""
    plot_delta_profiles(profiles)
    plot_short_interest_timeseries(feedback_df)
    plot_suppression_vs_nav(feedback_df)
    plot_governor_loop()
    plot_counterfactual(feedback_df)


# ═══════════════════════════════════════════════════════════════════════════════
# 6. PRINT DETAILED SUMMARY
# ═══════════════════════════════════════════════════════════════════════════════
def print_summary(profiles: pd.DataFrame, feedback_df: pd.DataFrame,
                  analysis: Dict):
    """Print a detailed quantitative summary of the auto-governor model."""
    print("\n" + "=" * 72)
    print("  CONVERTIBLE ARBITRAGE AUTO-GOVERNOR MODEL — SUMMARY")
    print("=" * 72)

    s = analysis['summary_stats']

    print(f"\n  📊 DATA OVERVIEW")
    print(f"  {'Trading days analyzed:':40s} {s['n_trading_days']}")
    print(f"  {'Active convertible issuances:':40s} {len(profiles)}")
    print(f"  {'Total convertible principal:':40s} ${s['total_active_principal_max']:.2f}B")
    print(f"  {'Date range:':40s} {feedback_df.index.min().date()} → {feedback_df.index.max().date()}")

    print(f"\n  🏦 ARBITRAGE SHORT INTEREST")
    print(f"  {'Peak arb short notional:':40s} ${s['total_short_notional_max']:.2f}B")
    print(f"  {'Mean arb short notional:':40s} ${s['total_short_notional_mean']:.2f}B")
    print(f"  {'Peak shares shorted (est.):':40s} {s['total_shares_shorted_max']:,.0f}")
    print(f"  {'Mean shares shorted (est.):':40s} {s['total_shares_shorted_mean']:,.0f}")
    print(f"  {'Peak SI as % of outstanding:':40s} {s['si_pct_of_shares_max']:.2f}%")
    print(f"  {'Mean SI as % of outstanding:':40s} {s['si_pct_of_shares_mean']:.2f}%")

    print(f"\n  🔧 SUPPRESSION FACTOR (Arb Short / MSTR Market Cap)")
    print(f"  {'Maximum:':40s} {s['suppression_factor_max']:.4f} "
          f"({s['suppression_factor_max']*100:.2f}%)")
    print(f"  {'Mean:':40s} {s['suppression_factor_mean']:.4f} "
          f"({s['suppression_factor_mean']*100:.2f}%)")
    print(f"  {'Median:':40s} {s['suppression_factor_median']:.4f} "
          f"({s['suppression_factor_median']*100:.2f}%)")
    print(f"  {'Std Dev:':40s} {s['suppression_factor_std']:.4f}")

    print(f"\n  📈 REGIME ANALYSIS")
    if 'suppression_by_btc_regime' in analysis:
        reg = analysis['suppression_by_btc_regime']
        for regime, label in [('btc_up_5pct', 'BTC up >5%'),
                               ('btc_down_5pct', 'BTC down >5%'),
                               ('btc_flat', 'BTC flat (±5%)')]:
            if reg[regime]['mean'] is not None:
                print(f"  {'  Suppression when ' + label + ':':40s} "
                      f"mean={reg[regime]['mean']:.4f}, "
                      f"median={reg[regime]['median']:.4f}, "
                      f"n={reg[regime]['n_days']}d")

    print(f"\n  🔗 CORRELATION WITH NAV PREMIUM")
    corr = analysis['correlation_suppression_vs_nav_change']
    for k, v in corr.items():
        if v is not None:
            print(f"  {'  Suppression vs NAV change ' + k:40s} {v:+.4f}")

    print(f"\n  📐 REGRESSION: NAV Premium Change ~ Suppression Factor")
    if 'ols_nav_change_vs_suppression' in analysis:
        ols = analysis['ols_nav_change_vs_suppression']
        if 'error' not in ols:
            print(f"  {'Slope (β):':40s} {ols['slope']:.4f}")
            print(f"  {'Intercept (α):':40s} {ols['intercept']:.4f}")
            print(f"  {'R²:':40s} {ols['r_squared']:.4f}")
            print(f"  {'P-value:':40s} {ols['p_value']:.6f}")
            print(f"  {'N observations:':40s} {ols['n_observations']}")

    print(f"\n  🔄 CROSS-CORRELATION (BTC Change vs Short Change)")
    if 'cross_correlation_btc_vs_short' in analysis:
        cc = analysis['cross_correlation_btc_vs_short']
        if 'contemporaneous' in cc and cc['contemporaneous'] is not None:
            print(f"  {'Contemporaneous:':40s} {cc['contemporaneous']:+.4f}")
        if 'by_lag_days' in cc:
            for lag, val in sorted(cc['by_lag_days'].items()):
                print(f"  {'  ' + lag + ':':40s} {val:+.4f}")

    print(f"\n  🛡️ COUNTERFACTUAL: MSTR Without Arb Suppression")
    cf = analysis['counterfactual']
    print(f"  {'Mean price drag per share:':40s} ${cf['mean_drag_per_share']:.2f}")
    print(f"  {'Max price drag per share:':40s} ${cf['max_drag_per_share']:.2f}")
    print(f"  {'Latest actual price:':40s} ${cf['actual_latest_price']:.2f}")
    print(f"  {'Latest counterfactual price:':40s} ${cf['counterfactual_latest_price']:.2f}")
    print(f"  {'Mean counterfactual price:':40s} ${cf['mean_counterfactual_price']:.2f}")
    print(f"  {'Max counterfactual increase %:':40s} {cf['max_counterfactual_increase_pct']}%")

    print(f"\n  📋 INTERPRETATION")
    median_supp = s['suppression_factor_median']
    peak_supp = s['suppression_factor_max']

    if peak_supp > 0.05:
        ceiling_note = (
            f"  At peak suppression ({peak_supp*100:.1f}% of market cap), arb shorting\n"
            f"  represents a significant structural weight on MSTR's share price.\n"
            f"  This creates a de facto 'ceiling' — as MSTR rallies above its\n"
            f"  conversion strikes (~30% above issuance prices), delta rises,\n"
            f"  forcing more shorting that caps further upside."
        )
    else:
        ceiling_note = (
            f"  At median suppression ({median_supp*100:.2f}% of market cap), arb shorting\n"
            f"  is moderate but meaningful. The mechanism operates more as a stabilizer\n"
            f"  than a hard ceiling, dampening volatility on both sides."
        )

    print(ceiling_note)
    print()
    print(f"  The convertible arbitrage auto-governor is a passive, structural feature:\n"
          f"  it does NOT require active management or exogenous intervention.\n"
          f"  The arb funds are simply delta-hedging their convertible positions,\n"
          f"  and the byproduct is an automatic volatility dampener for MSTR stock.")

    print(f"\n  {'='*72}\n")


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════════
def main():
    """Run the full convertible arbitrage auto-governor model."""
    # Load all data
    equity, issuances, holdings, btc_vol = load_all_data()

    # Prepare convertible profiles
    profiles = prepare_convert_profiles(issuances, equity)
    if len(profiles) == 0:
        log.error("No valid convertible profiles could be created. Exiting.")
        return

    # Build feedback loop timeseries
    feedback_df = build_feedback_loop_timeseries(equity, profiles)

    # Analyze dampening effect
    analysis, feedback_df = analyze_dampening(feedback_df)

    # Generate all plots
    plot_all(profiles, feedback_df)

    # Print summary
    print_summary(profiles, feedback_df, analysis)

    # Save JSON output
    output = {
        'model_type': 'convertible_arb_auto_governor',
        'generated_at': datetime.now(timezone.utc).isoformat(),
        'parameters': {
            'implied_vol': IMPLIED_VOL,
            'risk_free_rate': RISK_FREE_RATE,
            'conversion_premium': CONV_PREMIUM,
        },
        'convert_profiles': [],
        'analysis': analysis,
    }

    for _, p in profiles.iterrows():
        output['convert_profiles'].append({
            'issue_date': str(p['issue_date'].date()),
            'maturity_year': int(p['maturity_year']),
            'principal': float(p['principal']),
            'coupon': float(p['coupon']),
            'stock_price_at_issuance': round(float(p['stock_price_at_issuance']), 2),
            'strike_price': round(float(p['strike']), 2),
            'conversion_ratio': round(float(p['conv_ratio']), 2),
            'tte_at_issuance_years': round(float(p['tte_at_issuance']), 2),
            'delta_at_issuance': round(float(p['delta_at_issuance']), 4),
            'shares_shorted_at_issuance': round(float(p['shares_shorted_at_issuance']), 0),
            'short_interest_pct': round(float(p['short_interest_pct'] * 100), 4),
        })

    output_path = os.path.join(PROCESSED_DIR, 'convert_arb_governor.json')
    with open(output_path, 'w') as f:
        json.dump(output, f, indent=2, default=str)
    log.info(f"Saved model results to {output_path}")

    print(f"\n  Reports saved to: {REPORTS_DIR}/")
    print(f"  Results saved to: {output_path}")
    print(f"\n{'='*72}")


if __name__ == '__main__':
    main()
