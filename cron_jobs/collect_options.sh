#!/usr/bin/env bash
# Cron job: collect Deribit options snapshot daily at 18:00 UTC
cd /opt/data/home/projects/mstr-volatility-research
source venv/bin/activate
python scripts/collect_options_vol.py 2>> cron_options.log
echo "Exit code: $?" >> cron_options.log
date >> cron_options.log
