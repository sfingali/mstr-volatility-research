#!/usr/bin/env bash
# Cron job: collect BTC price data daily at 00:30 UTC
cd /opt/data/home/projects/mstr-volatility-research
source venv/bin/activate
python scripts/collect_prices.py 2>> cron_collect_prices.log
echo "Exit code: $?" >> cron_collect_prices.log
date >> cron_collect_prices.log
