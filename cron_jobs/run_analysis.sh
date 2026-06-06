#!/usr/bin/env bash
# Cron job: run full analysis weekly on Sunday at 02:00 UTC
cd /opt/data/home/projects/mstr-volatility-research
source venv/bin/activate
python scripts/timing_analysis.py 2>> cron_analysis.log
python scripts/sell_event_analysis.py 2>> cron_analysis.log
python scripts/convert_arb_analysis.py 2>> cron_analysis.log
python scripts/stabilization_model.py 2>> cron_analysis.log
echo "All analyses complete: $(date)" >> cron_analysis.log
