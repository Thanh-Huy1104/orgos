#!/bin/bash
set -e
cd ~/orgos

echo "=== Pulling ==="
git pull

echo "=== Python deps ==="
source venv/bin/activate
pip install -r requirements.txt -q 2>/dev/null

echo "=== Building dashboard ==="
cd dashboard
npm install --silent 2>/dev/null
npm run build
cd ..

echo "=== Restarting services ==="
sudo systemctl restart orgos-api orgos-dashboard orgos-scheduler

sleep 3
echo "=== Health check ==="
curl -s http://localhost:8420/health
echo ""
echo "Deployed."
