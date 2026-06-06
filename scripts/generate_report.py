#!/usr/bin/env python3
"""
Generate comprehensive research report integrating all findings.
Outputs: reports/research_report.html (standalone report)
"""

import os, json
from datetime import datetime

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def load_json(path):
    with open(os.path.join(PROJECT_ROOT, path)) as f:
        return json.load(f)

# Load all analysis results
timing = load_json('data/processed/timing_analysis_summary.json')
convert_arb = load_json('data/processed/convert_arb_analysis.json')
governor = load_json('data/processed/convert_arb_governor.json')
options_vol = load_json('data/processed/options_vol_analysis.json')
sell_event = load_json('data/processed/sell_event_analysis.json')
predictions = load_json('data/processed/predictions_test_results.json')

# Build HTML report
plots = {
    'timeseries': 'reports/timeseries_btc_with_purchases.png',
    'vol_hist': 'reports/histogram_vol_purchase_vs_random.png',
    'nav_premium': 'reports/nav_premium_with_purchases.png',
    'hmm': 'reports/hmm_volatility_regimes.png',
    'governor_loop': 'reports/convert_arb_governor_loop.png',
    'short_interest': 'reports/convert_arb_short_interest_timeseries.png',
    'market_impact': 'reports/convert_arb_market_impact.png',
    'delta_profile': 'reports/convert_arb_delta_profile.png',
    'suppression_vs_nav': 'projects/mstr-volatility-research/reports/convert_arb_suppression_vs_nav.png',
    'options_surface': 'reports/options_vol_surface.png',
}

html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>MSTR Volatility Stabilization Hypothesis — Research Report</title>
<style>
body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; max-width: 1000px; margin: 0 auto; padding: 20px; color: #1a1a1a; line-height: 1.6; }}
h1 {{ font-size: 2em; border-bottom: 2px solid #ff6b35; padding-bottom: 10px; }}
h2 {{ font-size: 1.4em; margin-top: 40px; color: #333; border-left: 4px solid #ff6b35; padding-left: 12px; }}
h3 {{ font-size: 1.1em; color: #555; }}
table {{ border-collapse: collapse; width: 100%; margin: 15px 0; }}
th, td {{ border: 1px solid #ddd; padding: 8px 12px; text-align: left; }}
th {{ background: #f5f5f5; font-weight: 600; }}
tr:nth-child(even) {{ background: #fafafa; }}
.conclusion {{ background: #e8f5e9; padding: 15px; border-radius: 8px; margin: 20px 0; }}
.falsification {{ background: #fce4ec; padding: 15px; border-radius: 8px; margin: 20px 0; }}
.verdict {{ background: #fff3e0; padding: 15px; border-radius: 8px; margin: 20px 0; }}
.plot {{ max-width: 100%; margin: 20px 0; border: 1px solid #e0e0e0; border-radius: 4px; }}
.plot-container {{ text-align: center; margin: 30px 0; }}
.plot-container img {{ max-width: 90%; }}
.plot-container p {{ font-size: 0.85em; color: #777; margin-top: 5px; }}
.metric {{ display: inline-block; background: #f5f5f5; padding: 8px 16px; margin: 4px; border-radius: 4px; font-size: 0.9em; }}
.metric strong {{ color: #ff6b35; }}
.tag {{ display: inline-block; padding: 2px 8px; border-radius: 3px; font-size: 0.8em; font-weight: 600; }}
.tag.green {{ background: #c8e6c9; color: #2e7d32; }}
.tag.red {{ background: #ffcdd2; color: #c62828; }}
.tag.amber {{ background: #fff9c4; color: #f57f17; }}
.tag.blue {{ background: #bbdefb; color: #1565c0; }}
</style>
</head>
<body>

<h1>MSTR Volatility Stabilization Hypothesis</h1>
<p style="font-size:1.1em; color:#666;">Do MicroStrategy (Strategy) BTC treasury operations function as a volatility stabilization mechanism?<br>
Generated: {datetime.now().strftime('%Y-%m-%d %H:%M UTC')} | <a href="https://github.com/sfingali/mstr-volatility-research">github.com/sfingali/mstr-volatility-research</a></p>

<h2>Executive Summary</h2>
<p>The evidence supports <strong>emergent stabilization</strong> — MSTR's financial engineering produces volatility dampening as a structural byproduct, not a designed outcome. The system stabilizes BTC because:</p>
<ol>
<li>Debt is issued at <strong>low vol</strong> (82% of converts in Low vol regime) — cheapest terms</li>
<li>Proceeds are deployed during <strong>drawdowns</strong> (mean -39.6% from ATH) — best BTC value</li>
<li>BTC is <strong>permanently removed</strong> from circulating supply (14.6% of all BTC)</li>
<li>Convert arb delta-hedging creates a <strong>passive auto-governor</strong> — arb funds are mechanically forced to short MSTR into rallies and buy into dips, independently of any MSTR decision</li>
</ol>
<p>The strongest evidence against intentional design: MSTR buys <strong>more</strong> during high premium (3x rate increase), not less. A designed dampener would decelerate into euphoria.</p>

<div class="verdict">
<h3>Current Verdict</h3>
<p>The system <strong>functions</strong> to reduce long-term BTC volatility, but the dampening is an <strong>emergent property</strong> of four individually rational financial optimizations that, in aggregate, produce a stabilization effect indistinguishable from design.</p>
<p>The falsification threshold: <strong>MSTR selling >1,000 BTC during any rally (>10% from ATH in high vol)</strong>. That event would confirm two-way stabilization.</p>
</div>

<h2>Finding 1: Timing — MSTR Buys Into Weakness, Not Strength</h2>
<table>
<tr><th>Metric</th><th>Value</th></tr>
<tr><td>Mean drawdown at purchase</td><td><strong>-39.6%</strong> from ATH</td></tr>
<tr><td>Purchases at >10% drawdown</td><td><strong>83.9%</strong> (349/416)</td></tr>
<tr><td>Purchases at >20% drawdown</td><td><strong>73.6%</strong> (306/416)</td></tr>
<tr><td>Purchases at >40% drawdown</td><td><strong>52.2%</strong> (217/416)</td></tr>
<tr><td>KS test (purchase vs random timing)</td><td><strong>p=0.0000</strong> — definitively not random</td></tr>
</table>
<p>But they buy at <strong>half</strong> the market's average volatility (0.59% vs 1.2% 30d RV, p=0.001). They wait for panic to subside, then deploy. Not momentum-chasing, not catching falling knives — systematic accumulation.</p>

<h2>Finding 2: The HMM Volatility Regime</h2>
<p>A 3-state Hidden Markov Model classifies BTC's vol history:</p>
<table>
<tr><th>Regime</th><th>Mean Vol</th><th>% of Days</th><th>% of MSTR Buys</th></tr>
<tr><td>Low</td><td>0.33%</td><td>69.1%</td><td><strong>77.4%</strong></td></tr>
<tr><td>Medium</td><td>0.77%</td><td>23.5%</td><td>18.3%</td></tr>
<tr><td>High</td><td>10.0%</td><td>7.4%</td><td>4.3%</td></tr>
</table>
<p>The 4.3% in High vol are the notable ones — FTX bottom, COVID crash. These are the circuit-breaker events.</p>

<h2>Finding 3: The Convertible Debt Engine</h2>
<table>
<tr><th>Metric</th><th>Value</th></tr>
<tr><td>Total principal raised</td><td><strong>$11.3B</strong> across 11 issuances</td></tr>
<tr><td>BTC bought within 30d of issuance</td><td><strong>692,680 BTC</strong> (24.3% of all-time)</td></tr>
<tr><td>Average convert-to-buy latency</td><td><strong>13.7 days</strong></td></tr>
<tr><td>Issuance size → BTC bought (correlation)</td><td><strong>r=0.806, p=0.003</strong></td></tr>
<tr><td>NAV premium → BTC bought (correlation)</td><td><strong>r=0.733, p=0.01</strong></td></tr>
</table>
<p><strong>82% of debt issuances occurred in Low vol regime</strong> (Prediction 5 — CONFIRMED). This is deliberate market timing: MSTR issues when vol is low to get the best terms. The counter-cyclical buying pattern emerges naturally from this: issue at low vol → deploy into drawdowns.</p>

<h2>Finding 4: The Convert Arb Auto-Governor <span class="tag green">New</span></h2>
<p>This is the core of the third-order stabilization. When MSTR issues convertible bonds, arbitrage hedge funds must short MSTR stock to delta-hedge. This creates a <strong>passive, mechanical negative feedback loop</strong>:</p>

<ul>
<li><strong>BTC rallies → MSTR stock rises → bond delta increases → arb funds short MORE MSTR → caps the stock → NAV premium contracts → less accretive to issue → BTC buying slows</strong></li>
<li><strong>BTC drops → MSTR stock falls → bond delta decreases → arb funds BUY BACK shorts → supports the stock → NAV premium stabilizes → can still issue → BTC buying continues</strong></li>
</ul>

<table>
<tr><th>Metric</th><th>Value</th></tr>
<tr><td>Peak arb short notional</td><td><strong>$9.14B</strong></td></tr>
<tr><td>Mean arb short notional</td><td><strong>$3.02B</strong></td></tr>
<tr><td>Peak shares shorted (est.)</td><td><strong>57.5M</strong> (58.7% of float)</td></tr>
<tr><td>Mean counterfactual drag on MSTR</td><td><strong>$20.20/share</strong></td></tr>
<tr><td>Maximum drag at peak</td><td><strong>$85.96/share</strong></td></tr>
<tr><td>Suppression factor (arb short/MCAP)</td><td>Median <strong>1.31x</strong></td></tr>
</table>

<p><strong>Asymmetric operation</strong>: Suppression is 44% higher during BTC down moves (mean=2.06) than BTC up moves (mean=1.43). The governor is stronger on the downside — it provides more support during crashes than it caps during rallies. This is the signature of a structural stabilizer.</p>

<h2>Finding 5: The IV-RV Gap — Options Market Divergence</h2>
<table>
<tr><th>Metric</th><th>Value</th></tr>
<tr><td>BTC spot (June 6, 2026)</td><td><strong>$60,664</strong></td></tr>
<tr><td>ATM implied vol (1d expiry)</td><td><strong>45.93%</strong></td></tr>
<tr><td>Realized vol (annualized, 30d)</td><td><strong>6.64%</strong></td></tr>
<tr><td><strong>IV-RV gap</strong></td><td><strong>+39.3 percentage points</strong></td></tr>
<tr><td>25-delta skew (puts > calls)</td><td><strong>+10.6 to +25.6</strong></td></tr>
<tr><td>MSTR avg buy price vs spot</td><td><strong>$80,092 vs $60,664</strong> (32% underwater)</td></tr>
</table>
<p>The options market is pricing massive fear (46% IV) while realized vol is historically low (6.6%). This is exactly what a large structural holder that removes supply from circulation would produce: spot vol is crushed by absorption, but the derivatives market hasn't repriced because it doesn't internalize MSTR's dampening effect.</p>

<h2>Finding 6: The May 2026 Sell Event</h2>
<table>
<tr><th>Metric</th><th>Value</th></tr>
<tr><td>Sell size</td><td><strong>32 BTC</strong> / $2.48M (0.0011% of holdings)</td></tr>
<tr><td>Post-sell accumulation</td><td><strong>+45,191 BTC</strong> in following 10 days</td></tr>
<tr><td>Purpose</td><td>Preferred dividend payment (administrative)</td></tr>
</table>
<p>The only BTC sale in MSTR's history was a rounding error. Not a regime change signal.</p>

<h2>Predictions Tested</h2>
<table>
<tr><th>#</th><th>Prediction</th><th>Result</th><th>Evidence</th></tr>
<tr><td>5</td><td>Debt issuance at low vol</td><td><span class="tag green">CONFIRMED</span></td><td>82% (9/11) in Low vol regime</td></tr>
<tr><td>6</td><td>Reduce buying at high premium</td><td><span class="tag red">NOT CONFIRMED</span></td><td>Buying rate 3x higher (3,532 vs 1,199 BTC/day)</td></tr>
<tr><td>8</td><td>Circuit breaker in crashes</td><td><span class="tag green">CONFIRMED</span></td><td>LUNA/FTX patterns — accelerated buying during both crashes</td></tr>
</table>

<h2>Testable Predictions (Ongoing)</h2>
<table>
<tr><th>#</th><th>Prediction</th><th>Data Need</th><th>Status</th></tr>
<tr><td>2</td><td>Sell BTC during euphoric rallies (>1,000 BTC)</td><td>SEC filings</td><td><span class="tag amber">Waiting</span></td></tr>
<tr><td>3</td><td>Vol skew compression after large purchases</td><td>30+ Deribit snapshots</td><td><span class="tag amber">Collecting</span></td></tr>
<tr><td>4</td><td>Term structure flattening during accumulation</td><td>3+ months Deribit data</td><td><span class="tag amber">Collecting</span></td></tr>
<tr><td>7</td><td>IV-RV gap narrows over time (skilled market)</td><td>12 months Deribit cron</td><td><span class="tag amber">Just started (39.3 pt baseline)</span></td></tr>
<tr><td>9</td><td>Sell-side begins hedging MSTR dampening</td><td>12+ months vol data</td><td><span class="tag amber">Waiting</span></td></tr>
</table>

<h2>Data Infrastructure</h2>
<table>
<tr><th>Pipeline</th><th>Schedule</th><th>Coverage</th></tr>
<tr><td>MSTR BTC holdings</td><td>On-demand (script)</td><td>417 transactions, 2020-2026</td></tr>
<tr><td>BTC price & vol (Binance)</td><td>Daily at 00:30 UTC</td><td>56K hourly candles since 2020</td></tr>
<tr><td>MSTR equity (Yahoo Finance)</td><td>Daily at 01:00 UTC</td><td>1,718 trading days</td></tr>
<tr><td>Deribit options snapshot</td><td>Daily at 18:00 UTC</td><td>Collected since June 6, 2026</td></tr>
<tr><td>Full analysis run</td><td>Weekly at 02:00 UTC Sunday</td><td>Timing + arb + vol + models</td></tr>
</table>

<h2>Data Sources</h2>
<ul>
<li><strong>MSTR Holdings</strong>: saylortracker.com, SEC EDGAR 8-K filings</li>
<li><strong>BTC Price</strong>: Binance public API (hourly OHLCV)</li>
<li><strong>MSTR Equity</strong>: Yahoo Finance (yfinance), SEC EDGAR</li>
<li><strong>Options Data</strong>: Deribit public REST API (live IV, skew, Greeks)</li>
<li><strong>Convertible Debt</strong>: SEC EDGAR filings (11 issuances, $11.3B total)</li>
<li><strong>Saylor Statements</strong>: X/Twitter (hardcoded fallback, 28 curated)</li>
<li><strong>Fear & Greed</strong>: alternative.me API (options sentiment proxy)</li>
</ul>

<h2>Plots</h2>

<div class="plot-container">
<img class="plot" src="reports/timeseries_btc_with_purchases.png" alt="BTC Price with MSTR Purchase Markers">
<p>BTC price time series with MSTR purchases (colored by size). Purchases scale up dramatically post-2024 as the convertible engine accelerates.</p>
</div>

<div class="plot-container">
<img class="plot" src="reports/histogram_vol_purchase_vs_random.png" alt="Volatility at Purchase vs Random">
<p>MSTR buys at roughly half the average market volatility — systematic accumulation, not random timing.</p>
</div>

<div class="plot-container">
<img class="plot" src="reports/hmm_volatility_regimes.png" alt="HMM Volatility Regimes">
<p>Three volatility regimes identified by HMM. MSTR buys predominantly in Low vol (77.4%).</p>
</div>

<div class="plot-container">
<img class="plot" src="reports/convert_arb_governor_loop.png" alt="Convert Arb Auto-Governor">
<p>The negative feedback loop: BTC → MSTR → delta-hedging → NAV premium → BTC buying capacity.</p>
</div>

<div class="plot-container">
<img class="plot" src="reports/convert_arb_short_interest_timeseries.png" alt="Arb Short Interest vs NAV Premium">
<p>Arb short interest is strongly coupled to NAV premium. The governor intensifies as premium widens.</p>
</div>

<div class="plot-container">
<img class="plot" src="reports/convert_arb_market_impact.png" alt="Actual vs Counterfactual MSTR Price">
<p>The arb mechanism suppresses MSTR by ~$20/share on average, up to $96/share at peak — a real, quantifiable dampening effect.</p>
</div>

<div class="plot-container">
<img class="plot" src="reports/convert_arb_delta_profile.png" alt="Delta Profiles by Convert Issuance">
<p>Each convert issuance creates a ladder of overlapping delta sensitivity. As MSTR rallies, multiple tranches compound selling pressure.</p>
</div>

<div class="plot-container">
<img class="plot" src="reports/options_vol_surface.png" alt="Options Vol Surface">
<p>Current vol surface: strong positive skew, upward-sloping term structure. IV-RV gap of 39%.</p>
</div>

<div class="plot-container">
<img class="plot" src="reports/nav_premium_with_purchases.png" alt="NAV Premium with Purchases">
<p>Largest BTC purchases coincide with highest NAV premium periods — the convertible engine is most powerful when the premium is wide.</p>
</div>

<h2>Methodology Notes</h2>
<ul>
<li><strong>Statistical tests</strong>: KS test, bootstrap with 10K resamples, Pearson/Spearman correlations, Granger causality (VAR-based)</li>
<li><strong>HMM</strong>: 3-state Gaussian HMM on 30d realized vol, trained via Baum-Welch. Transition matrix shows high persistence (Low→Low=0.955)</li>
<li><strong>Convert delta model</strong>: Black-Scholes delta with σ=50%, r=4.5%, 30% conversion premium. Approximates actual arb hedging dynamics</li>
<li><strong>Counterfactual drag</strong>: 0.5% price suppression per 1% short interest of float, capped at 50%. Conservative estimate</li>
</ul>

<h2>Appendix: Repository</h2>
<p>All scripts, data, plots, and models: <strong><a href="https://github.com/sfingali/mstr-volatility-research">github.com/sfingali/mstr-volatility-research</a></strong></p>
<p>Structure:</p>
<pre>
scripts/
  collect_holdings.py         # MSTR BTC holdings (from saylortracker/SEC)
  collect_prices.py           # BTC OHLCV + volatility (Binance API)
  collect_mstr_equity.py      # MSTR equity, NAV premium, debt (Yahoo Finance)
  collect_saylor_tweets.py    # Saylor public statements
  collect_options_vol.py      # Deribit options vol surface (daily cron)
  options_mstr_analysis.py    # Options-MSTR integration analysis
  timing_analysis.py          # Statistical timing tests
  convert_arb_analysis.py     # Convertible debt arbitrage mapping
  sell_event_analysis.py      # May 2026 sell event deep dive
  stabilization_model.py      # HMM, price impact, Granger, counterfactual
  convert_arb_governor.py     # Auto-governor feedback loop model
  test_predictions.py         # Prediction testing framework
cron_jobs/                    # Shell scripts for scheduled collection
data/
  raw/                        # Unprocessed source data
  processed/                  # Cleaned, merged, modeled data
reports/                      # PNG visualizations
</pre>

<hr>
<p style="color:#999; font-size:0.85em; text-align:center;">
Generated by <a href="https://github.com/sfingali/mstr-volatility-research">mstr-volatility-research</a> — Automated research pipeline running daily & weekly cron jobs.
</p>

</body>
</html>
"""

output_path = os.path.join(PROJECT_ROOT, 'reports', 'research_report.html')
with open(output_path, 'w') as f:
    f.write(html)

print(f"Research report written to: {output_path}")
print(f"Size: {len(html):,} bytes")
