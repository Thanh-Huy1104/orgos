"""One-time Google Calendar OAuth authorization.

Run once to authorize orgos:
    python -m orgos.mcps.gcal_auth

Opens a browser for OAuth consent. If you're on a headless server,
it prints the URL — open it on any machine with a browser.
The token is saved to ~/.orgos/.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

_here = Path(__file__).resolve().parent.parent
if str(_here) not in sys.path:
    sys.path.insert(0, str(_here))

CREDS_PATH = os.path.expanduser("~/.orgos/google-credentials.json")
TOKEN_PATH = os.path.expanduser("~/.orgos/google-token.json")
SCOPES = ["https://www.googleapis.com/auth/calendar"]


def main():
    try:
        from google_auth_oauthlib.flow import InstalledAppFlow
    except ImportError:
        print("Install: pip install google-auth-oauthlib")
        return 1

    if not os.path.exists(CREDS_PATH):
        print(f"Credentials not found at {CREDS_PATH}")
        print("Download OAuth 2.0 credentials from Google Cloud Console first.")
        print("Make sure to add http://localhost as an authorized redirect URI.")
        return 1

    # Use local server flow — prints URL if browser can't open
    flow = InstalledAppFlow.from_client_secrets_file(CREDS_PATH, SCOPES)
    creds = flow.run_local_server(
        port=0,
        open_browser=False,
        prompt="consent",
    )

    os.makedirs(os.path.dirname(TOKEN_PATH), exist_ok=True)
    with open(TOKEN_PATH, "w") as f:
        f.write(creds.to_json())

    print(f"\n✓ Token saved to {TOKEN_PATH}")
    print("Google Calendar is now authorized.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
