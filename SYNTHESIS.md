# MSTR Volatility Stabilization Hypothesis — Research Synthesis

## Project: https://github.com/sfingali/mstr-volatility-research

## Executive Summary

The evidence for **some form of stabilization** is moderately strong — MSTR's BTC purchases are not random and show clear statistical signatures consistent with market support. However, the evidence points more toward **emergent stabilization from financial engineering** than deliberate market manipulation.

---

## Finding 1: MSTR Buys During Drawdowns, NOT Peaks (Strong Signal)

| Metric | Value |
|--------|-------|
| Mean drawdown at purchase | **-39.6%** from ATH |
| Purchases at >10% drawdown | **83.9%** (349/416) |
| Purchases at >20% drawdown | **73.6%** (306/416) |
| Purchases at >40% drawdown | **52.2%** (217/416) |

KS test confirms: BTC prices at purchase dates differ significantly from overall distribution (p≈0.0000). MSTR consistently accumulates during price dislocations.

## Finding 2: But Volatility at Purchase is HALF the Market Average (Contra-Intuitive)

| Metric | Purchase Days | All Days |
|--------|--------------|----------|
| Mean 30d realized vol | **0.59%** | **1.2%** |

Bootstrap test: significant at p=0.001. MSTR does NOT buy during panic vol spikes. They wait until volatility has normalized (typically 1-2 weeks after a crash) then deploy capital. This is consistent with minimizing market impact, not with "catching falling knives."

**HMM analysis**: 77.4% of purchases occur in Low vol regime (0.33% avg), 18.3% in Medium (0.77%), only 4.3% in High (10.0%). The 4.3% in High vol are the notable ones — these include the FTX bottom (Nov 2022), the COVID crash recovery (Mar 2020), and the Mar 2020 crash.

## Finding 3: The Convertible Debt Engine is the Core Mechanism (Strong Structural Signal)

| Metric | Value |
|--------|-------|
| Total convertible debt raised | **$11.3B** (11 issuances) |
| BTC bought within 30d of any issuance | **692,680 BTC** (24.3% of all-time) |
| Avg convert-to-buy latency | **13.7 days** |
| Correlation: issuance size → BTC bought 30d | **r=0.806, p=0.003** |
| Correlation: NAV premium → BTC bought 30d | **r=0.733, p=0.01** |
| Est. delta-hedged short interest | **~$9.0B** |

The NAV premium spike in 2024-2025 (from ~0.3x to 4.0x) correlates almost perfectly with the explosion in purchase size. This is the "infinite money glitch" — high premium → issue convert → buy BTC → BTC yield → higher premium → repeat.

**Critical finding**: Granger causality tests show NO significant directional causality between BTC returns and NAV premium changes. They move together (r=0.67 at 1d lag) but cannot be teased apart causally. This weakens the "intentional feedback loop" argument — the relationship is systemic, not a designed control system.

## Finding 4: The May 2026 Sell Event is a Non-Event (Confirmed)

| Aspect | Detail |
|--------|--------|
| Sell size | **32 BTC** / $2.48M |
| % of total holdings | **0.0011%** |
| % of total spend | **0.0011%** |
| Post-sell accumulation | **+45,191 BTC in 10 days** |

This is purely administrative — paying preferred dividends. Smaller than a typical weekly purchase variance. The thesis that MSTR has "started selling" is technically true but strategically meaningless at this scale. No regime change detected.

## Finding 5: Price Impact — Modest and Delayed (Weak Signal)

- No significant BTC price impact at 1h, 6h, 24h, or 72h post-purchase
- At 7 days: mean return of +0.92% (p=0.015 — weakly significant)
- Purchase size does NOT predict post-purchase return (R²≈0.0002, p>0.36)
- Counterfactual model: MSTR's ~14.6% of circulating supply could contribute ~14.6% to price floor under naive supply-demand model (~$60.5K actual vs ~$52.8K counterfactual)
- More realistic sqrt market impact model: ~0.15% contribution (negligible)

## Finding 6: Saylor's Rhetoric — Conditional on Market State (Mixed)

Of 28 curated statements, 26 are bullish, 2 neutral, 0 bearish. The most aggressive rhetoric ("Bitcoin is the exit," "Buy the dip") clusters around volatile drawdown periods — consistent with verbal floor-support. But the sample is too small for statistical testing. X/Twitter API access is needed for a comprehensive analysis.

---

## Verdict: Intentional vs. Emergent Stabilization

| Evidence | Favors Intentional | Favors Emergent |
|----------|-------------------|-----------------|
| Counter-cyclical timing (buy drawdowns) | ✓ | |
| Buying LOW vol, not during panic | | ✓ (operational efficiency, not design) |
| No Granger causality in feedback loop | | ✓ |
| Convertible debt bootstrap (NAV premium) | | ✓ (financial engineering artifact) |
| No detectable price impact at purchase times | | ✓ |
| Gov't-adjacent patterns (Monday clustering, systematic) | ✓ | |
| Saylor's rhetoric = floor-support | ✓ | |
| Sell event is negligible | | ✓ (not a two-way system) |
| HMM shows systematic low-vol accumulation | | ✓ |

**Assessment**: The weight of evidence favors **emergent stabilization** — the financial engineering of the MSTR convertible debt strategy produces stabilization as a systemic byproduct rather than a designed outcome. However, the **timing of drawdown purchases** and **Saylor's counter-cyclical rhetoric** leave room for intentional floor-support. The two hypotheses are not mutually exclusive: an emergent system can be exploited deliberately for stabilization effects.

The strongest falsification would be: MSTR selling meaningful amounts of BTC (>1,000 BTC) during rallies. If that happens, the "two-way stabilization" thesis becomes viable.

---

## Next Steps / Unresolved

1. **X/Twitter API**: Get bearer token for comprehensive Saylor sentiment analysis
2. **Deribit options data**: Compute implied vol skew at purchase dates (see if MSTR's buying affects vol surface)
3. **SEC filing text mining**: Automate 8-K text parsing for exact purchase language
4. **Shared-order-flow analysis**: If MSTR uses Coinbase Prime OTC, see if their trades correlate with BTC price reversals
5. **Update when/if**: MSTR sells >1,000 BTC in a single transaction
