#!/usr/bin/env bash
# Cron job: collect MSTR equity data daily at 01:00 UTC
cd /opt/data/home/projects/mstr-volatility-research
source venv/bin/activate
python scripts/collect_mstr_equity.py 2>> cron_collect_equity.log
echo "Exit code: $?" >> cron_collect_equity.log
date >> cron_collect_equity.log
