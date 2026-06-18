"""Google Calendar MCP server — read/write your real calendar.

Requires Google Cloud credentials. Setup:
  1. Go to https://console.cloud.google.com
  2. Create a project, enable Calendar API
  3. Create OAuth 2.0 Client ID (Desktop app)
  4. Download credentials.json to ~/.orgos/google-credentials.json
  5. First run will open a browser for OAuth consent

Usage:
    from orgos.mcps.gcal import create_gcal_mcp
    dept.shared_mcps = [create_gcal_mcp()]

Run standalone:
    python -m orgos.mcps.gcal_mcp --creds ~/.orgos/google-credentials.json

Tools:
  - list_events(calendar_id, time_min, time_max, limit)
  - create_event(calendar_id, summary, start, end, description, attendees)
  - delete_event(calendar_id, event_id)
  - find_free_slots(calendar_id, days, duration_min, start_hour, end_hour)
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

_here = Path(__file__).resolve().parent.parent
if str(_here) not in sys.path:
    sys.path.insert(0, str(_here))

DEFAULT_CREDS = os.path.expanduser("~/.orgos/google-credentials.json")
DEFAULT_TOKEN = os.path.expanduser("~/.orgos/google-token.json")

_google_available = False
try:
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build
    _google_available = True
except ImportError:
    pass

SCOPES = ["https://www.googleapis.com/auth/calendar"]


def _get_service(creds_path: str, token_path: str):
    if not _google_available:
        return None

    creds = None
    if os.path.exists(token_path):
        creds = Credentials.from_authorized_user_file(token_path, SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            return None  # needs auth — run python -m orgos.mcps.gcal_auth first
    return build("calendar", "v3", credentials=creds)


async def serve(creds_path: str = DEFAULT_CREDS, token_path: str = DEFAULT_TOKEN) -> None:
    from mcp.server import Server
    from mcp.server.stdio import stdio_server
    from mcp.types import Tool, TextContent

    service = _get_service(creds_path, token_path) if _google_available else None

    server = Server(
        "orgos-gcal",
        version="1.0.0",
        instructions="Google Calendar: list, create, delete events. Find free slots.",
    )

    @server.list_tools()
    async def list_tools() -> list[Tool]:
        if not service:
            return [Tool(
                name="gcal_status",
                description="Google Calendar is not configured. Install google-api-python-client google-auth-oauthlib.",
                inputSchema={"type": "object", "properties": {}, "required": []},
            )]

        def _t(name, desc, props):
            return Tool(name=name, description=desc, inputSchema={
                "type": "object", "properties": props, "required": list(props.keys()),
            })

        return [
            _t("list_events", "List calendar events in a time range.",
                {"calendar_id": {"type": "string", "description": "Calendar ID or 'primary' for main calendar."},
                 "time_min": {"type": "string", "description": "Start time ISO format, e.g. 2026-06-15T00:00:00."},
                 "time_max": {"type": "string", "description": "End time ISO format."},
                 "limit": {"type": "integer", "description": "Max results, e.g. 25."}}),
            _t("create_event", "Create a calendar event.",
                {"calendar_id": {"type": "string", "description": "Calendar ID or 'primary'."},
                 "summary": {"type": "string", "description": "Event title."},
                 "start_time": {"type": "string", "description": "Start ISO datetime, e.g. 2026-06-15T14:00:00."},
                 "end_time": {"type": "string", "description": "End ISO datetime."},
                 "description": {"type": "string", "description": "Event description or empty string."},
                 "attendees": {"type": "string", "description": "Comma-separated email addresses or empty string."}}),
            _t("delete_event", "Delete a calendar event.",
                {"calendar_id": {"type": "string", "description": "Calendar ID or 'primary'."},
                 "event_id": {"type": "string", "description": "Event ID to delete."}}),
            _t("find_free_slots", "Find available time slots in the next N days.",
                {"calendar_id": {"type": "string", "description": "Calendar ID or 'primary'."},
                 "days": {"type": "integer", "description": "Number of days to look ahead, e.g. 7."},
                 "duration_min": {"type": "integer", "description": "Minimum slot duration in minutes, e.g. 60."},
                 "start_hour": {"type": "integer", "description": "Earliest hour for slots (0-23), e.g. 9."},
                 "end_hour": {"type": "integer", "description": "Latest hour for slots (0-23), e.g. 17."}}),
        ]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict) -> list[TextContent]:
        if not service:
            return [TextContent(type="text", text=json.dumps(
                {"error": "Google Calendar not configured. Install: pip install google-api-python-client google-auth-oauthlib"}))]

        try:
            if name == "list_events":
                cal = arguments.get("calendar_id", "primary")
                tmin = arguments.get("time_min", "")
                tmax = arguments.get("time_max", "")
                # Normalize date formats: add time + timezone if missing
                if tmin and "T" not in tmin:
                    tmin += "T00:00:00Z"
                if tmax and "T" not in tmax:
                    tmax += "T23:59:59Z"
                if tmin and tmin[-1] not in "Zz" and "+" not in tmin and len(tmin) < 25:
                    tmin += "Z"
                if tmax and tmax[-1] not in "Zz" and "+" not in tmax and len(tmax) < 25:
                    tmax += "Z"
                events = service.events().list(
                    calendarId=cal,
                    timeMin=tmin or None,
                    timeMax=tmax or None,
                    maxResults=arguments.get("limit", 25),
                    singleEvents=True,
                    orderBy="startTime",
                ).execute()
                result = [{
                    "id": e["id"], "summary": e.get("summary", ""),
                    "start": e["start"].get("dateTime", e["start"].get("date")),
                    "end": e["end"].get("dateTime", e["end"].get("date")),
                    "description": e.get("description", "")[:500],
                    "attendees": [a.get("email", "") for a in e.get("attendees", [])],
                } for e in events.get("items", [])]
                return [TextContent(type="text", text=json.dumps(result, indent=2))]

            elif name == "create_event":
                st = arguments.get("start_time", "")
                et = arguments.get("end_time", "")
                if st and "T" not in st: st += "T00:00:00Z"
                if et and "T" not in et: et += "T23:59:59Z"
                if st and st[-1] not in "Zz" and "+" not in st: st += "Z"
                if et and et[-1] not in "Zz" and "+" not in et: et += "Z"
                attendees = []
                if arguments.get("attendees", "").strip():
                    attendees = [{"email": e.strip()} for e in arguments["attendees"].split(",")]
                body = {
                    "summary": arguments["summary"],
                    "start": {"dateTime": arguments["start_time"], "timeZone": "UTC"},
                    "end": {"dateTime": arguments["end_time"], "timeZone": "UTC"},
                }
                if arguments.get("description"):
                    body["description"] = arguments["description"]
                if attendees:
                    body["attendees"] = attendees

                event = service.events().insert(
                    calendarId=arguments.get("calendar_id", "primary"), body=body,
                ).execute()
                return [TextContent(type="text", text=json.dumps({
                    "id": event["id"], "summary": event.get("summary"),
                    "link": event.get("htmlLink"), "created": True,
                }, indent=2))]

            elif name == "delete_event":
                service.events().delete(
                    calendarId=arguments.get("calendar_id", "primary"),
                    eventId=arguments["event_id"],
                ).execute()
                return [TextContent(type="text", text=json.dumps({"deleted": True}))]

            elif name == "find_free_slots":
                from datetime import datetime, timedelta, timezone
                cal = arguments.get("calendar_id", "primary")
                days = arguments.get("days", 7)
                duration = arguments.get("duration_min", 60)
                start_h = arguments.get("start_hour", 9)
                end_h = arguments.get("end_hour", 17)

                now = datetime.now(timezone.utc)
                time_min = now.isoformat()
                time_max = (now + timedelta(days=days)).isoformat()

                events = service.events().list(
                    calendarId=cal, timeMin=time_min, timeMax=time_max,
                    singleEvents=True, orderBy="startTime",
                ).execute()

                busy = []
                for e in events.get("items", []):
                    s = e["start"].get("dateTime", e["start"].get("date"))
                    en = e["end"].get("dateTime", e["end"].get("date"))
                    busy.append((s, en))

                free_slots = []
                cursor = now.replace(hour=start_h, minute=0, second=0, microsecond=0)
                if cursor < now:
                    cursor += timedelta(days=1)

                for _ in range(days * 24):
                    slot_end = cursor + timedelta(minutes=duration)
                    if cursor.hour < start_h or slot_end.hour > end_h:
                        cursor += timedelta(hours=1)
                        continue
                    if cursor.hour >= end_h:
                        cursor = (cursor + timedelta(days=1)).replace(hour=start_h)
                        continue

                    overlaps = False
                    for bs, be in busy:
                        bs_dt = datetime.fromisoformat(bs)
                        be_dt = datetime.fromisoformat(be)
                        if cursor < be_dt and slot_end > bs_dt:
                            overlaps = True
                            break

                    if not overlaps:
                        free_slots.append({
                            "start": cursor.isoformat(),
                            "end": slot_end.isoformat(),
                        })

                    cursor += timedelta(minutes=30)

                return [TextContent(type="text", text=json.dumps(free_slots[:10], indent=2))]

            else:
                return [TextContent(type="text", text=json.dumps({"error": f"Unknown tool: {name}"}))]

        except Exception as exc:
            return [TextContent(type="text", text=json.dumps({"error": str(exc)}))]

    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


def main():
    parser = argparse.ArgumentParser(description="orgos Google Calendar MCP Server")
    parser.add_argument("--creds", default=DEFAULT_CREDS, help="Path to Google OAuth credentials.json")
    parser.add_argument("--token", default=DEFAULT_TOKEN, help="Path to OAuth token storage")
    args = parser.parse_args()
    asyncio.run(serve(args.creds, args.token))


if __name__ == "__main__":
    main()
