#!/usr/bin/env python
"""Orgos Monitor — start API server + Streamlit dashboard, verify both are alive.

Usage:
    py -3.12 run_monitor.py
    py -3.12 run_monitor.py --port-api 8420 --port-ui 8501
"""

import argparse
import subprocess
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path

REPO = Path(__file__).resolve().parent


def _ping(url: str, label: str, retries: int = 30, delay: float = 1.0) -> bool:
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "orgos-monitor"})
            with urllib.request.urlopen(req, timeout=3) as r:
                body = r.read().decode()[:100]
                print(f"  [{label}] OK -> {url}  ({body[:60].strip()})")
                return True
        except (urllib.error.URLError, ConnectionRefusedError, OSError):
            time.sleep(delay)
    print(f"  [{label}] FAILED -> {url} (not reachable after {retries}s)")
    return False


def main():
    parser = argparse.ArgumentParser(description="Orgos Monitor launcher")
    parser.add_argument("--port-api", type=int, default=8420)
    parser.add_argument("--port-ui", type=int, default=8501)
    args = parser.parse_args()

    api_url = f"http://localhost:{args.port_api}/health"
    ui_url = f"http://localhost:{args.port_ui}"

    print("=" * 60)
    print("Orgos Monitor")
    print(f"  API:  http://localhost:{args.port_api}")
    print(f"  UI:   http://localhost:{args.port_ui}")
    print("=" * 60)

    # Start API server
    print("\n[1/4] Starting API server...")
    api_proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "orgos.api:app",
         "--host", "0.0.0.0", "--port", str(args.port_api)],
        cwd=REPO,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    # Start Streamlit dashboard
    print("[2/4] Starting Streamlit dashboard...")
    ui_proc = subprocess.Popen(
        [sys.executable, "-m", "streamlit", "run", "monitor/app.py",
         "--server.port", str(args.port_ui), "--server.headless", "true"],
        cwd=REPO,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    # Verify API
    print("[3/4] Verifying API...")
    api_ok = _ping(api_url, "API")

    # Verify UI
    print("[4/4] Verifying Streamlit...")
    ui_ok = _ping(ui_url, "UI", retries=45, delay=2.0)

    print(f"\n{'=' * 60}")
    if api_ok and ui_ok:
        print("Both services running.")
        print(f"  Dashboard: http://localhost:{args.port_ui}")
        print(f"  API docs:  http://localhost:{args.port_api}/docs")
        print("\nPress Ctrl+C to stop both.")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            print("\nShutting down...")
    else:
        status = []
        if not api_ok:
            status.append("API OFFLINE")
        if not ui_ok:
            status.append("UI OFFLINE")
        print(f"ERROR: {', '.join(status)}")
    finally:
        for proc in [api_proc, ui_proc]:
            try:
                proc.terminate()
                proc.wait(timeout=5)
            except Exception:
                proc.kill()


if __name__ == "__main__":
    main()
