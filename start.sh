#!/bin/bash
# Start orgos API and Next.js dashboard as fully detached services
set -e
cd /home/th/orgos

echo "=== orgos startup ==="

# Kill any existing instances
pkill -f "uvicorn orgos.api" 2>/dev/null || true
pkill -f "next dev" 2>/dev/null || true
sleep 1

# Start API (fully detached)
source venv/bin/activate
setsid python -m uvicorn orgos.api:app --host 0.0.0.0 --port 8420 </dev/null > /tmp/orgos-api.log 2>&1 &
disown
echo "API: started on :8420 (PID $!)"

# Start Dashboard (fully detached)
cd dashboard
setsid npx next dev -p 3000 </dev/null > /tmp/orgos-dashboard.log 2>&1 &
disown
echo "Dashboard: started on :3000 (PID $!)"

echo ""
echo "API:    http://192.168.5.197:8420/health"
echo "Dashboard: http://192.168.5.197:3000"
echo ""
echo "You can close this terminal — processes persist."
