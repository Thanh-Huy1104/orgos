#!/bin/bash
# orgos scheduler — runs continuously via systemd
cd /home/th/orgos
source venv/bin/activate
export PYTHONPATH=/home/th/orgos
set -a; source .env; set +a
exec python -c "
import sys, time
sys.path.insert(0, '/home/th/orgos')
from orgos import load_org, Scheduler, notify_owner
org = load_org('config/org.yaml')
org.use_memory()
s = Scheduler(org)
notify_owner(org, 'scheduler', 'Scheduler starting — watching for due jobs')
s.run_loop(interval_sec=60)
"
