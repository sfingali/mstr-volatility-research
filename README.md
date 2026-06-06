# MSTR Volatility Stabilization Hypothesis Research

**Hypothesis**: MicroStrategy's (now "Strategy" / MSTR) Bitcoin treasury operations — purchases, convertible debt issuance, share buybacks, and now sales — function as a volatility stabilization mechanism for BTC, whether intentional or emergent.

## Research Questions

1. **Timing**: Do MSTR BTC purchases cluster in high-volatility drawdowns (counter-cyclical support)?
2. **Feedback Loop**: Is there tight temporal coupling between BTC buys, convertible debt issuances, and share buybacks?
3. **Two-Way Intervention**: Does the May 2026 sell event change the analysis from one-way accumulation to two-way dampening?
4. **Saylor Rhetoric**: Does public communication intensity correlate with volatility regimes?
5. **Emergent vs. Intentional**: Is any observed stabilization designed or a systemic byproduct of financial engineering?

## Structure

```
data/
  raw/              - Unprocessed source data (JSON, CSV)
  processed/        - Cleaned, merged datasets
  models/           - Statistical model outputs
scripts/
  collect_holdings.py    - MSTR BTC holdings from Saylortracker/SEC
  collect_prices.py      - BTC OHLCV + volatility data
  collect_mstr_equity.py - MSTR share data, buybacks, debt
  collect_saylor_tweets.py - Saylor public statements
  timing_analysis.py     - Purchase timing vs volatility
  convert_arb_analysis.py - Convertible debt arbitrage mapping
  sell_event_analysis.py - May 2026 sell event deep dive
  stabilization_model.py - Mathematical models
cron_jobs/         - Cron scripts for continuous collection
notebooks/         - Jupyter notebooks for analysis
reports/           - Generated reports
```

## Data Sources

- **Holdings**: https://saylortracker.com (SaylorTracker API / scraped data)
- **BTC Price**: Binance, Kraken, CoinGecko APIs
- **BTC Volatility**: Realized vol from hourly OHLCV, Deribit options data
- **MSTR Equity**: Yahoo Finance, SEC EDGAR (8-K, 10-Q, S-3 filings)
- **Convertible Debt**: SEC EDGAR filings, TRACE data
- **Saylor Statements**: X/Twitter API, YouTube transcripts
- **MSTR Share Buybacks**: SEC filings, company press releases
