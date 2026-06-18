"""Google Calendar tool — native CrewAI tool, no MCP subprocess needed.

Usage:
    from orgos.gcal_tool import create_gcal_tools
    role.tools.extend(create_gcal_tools())
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from typing import Any

from crewai.tools import BaseTool
from pydantic import BaseModel, Field


def _get_calendar_service():
    try:
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build
    except ImportError:
        return None

    token_path = os.path.expanduser("~/.orgos/google-token.json")
    if not os.path.exists(token_path):
        return None

    creds = Credentials.from_authorized_user_file(
        token_path, ["https://www.googleapis.com/auth/calendar"]
    )
    if not creds.valid:
        if creds.expired and creds.refresh_token:
            from google.auth.transport.requests import Request
            creds.refresh(Request())
        else:
            return None
    return build("calendar", "v3", credentials=creds)


def _normalize_date(d: str) -> str:
    if not d:
        return d
    if "T" not in d:
        d += "T00:00:00"
    if d[-1] not in "Zz" and "+" not in d[-6:]:
        d += "Z"
    return d


# ── List Events ──────────────────────────────────────────────────────────────

class _ListEventsInput(BaseModel):
    calendar_id: str = Field(default="primary", description="Calendar ID or 'primary'.")
    time_min: str = Field(default="", description="Start time ISO, e.g. 2026-06-15 or 2026-06-15T00:00:00.")
    time_max: str = Field(default="", description="End time ISO.")
    limit: int = Field(default=25, description="Max results.")


class ListEventsTool(BaseTool):
    name: str = "list_calendar_events"
    description: str = (
        "List events from a Google Calendar in a time range. "
        "Use calendar_id='primary' for the main calendar. "
        "time_min and time_max can be dates like '2026-06-15' or ISO datetimes."
    )
    args_schema: type[BaseModel] = _ListEventsInput
    tool_category: str = "read"

    def _run(self, calendar_id: str = "primary", time_min: str = "", time_max: str = "", limit: int = 25) -> str:
        service = _get_calendar_service()
        if service is None:
            return json.dumps({"error": "Google Calendar not configured. Run: python -m orgos.mcps.gcal_auth"})

        try:
            events = service.events().list(
                calendarId=calendar_id,
                timeMin=_normalize_date(time_min) or None,
                timeMax=_normalize_date(time_max) or None,
                maxResults=limit,
                singleEvents=True,
                orderBy="startTime",
            ).execute()
            result = []
            for e in events.get("items", []):
                result.append({
                    "id": e["id"],
                    "summary": e.get("summary", ""),
                    "start": e["start"].get("dateTime", e["start"].get("date")),
                    "end": e["end"].get("dateTime", e["end"].get("date")),
                    "description": (e.get("description", "") or "")[:300],
                })
            return json.dumps(result, indent=2)
        except Exception as exc:
            return json.dumps({"error": str(exc)})


# ── Create Event ─────────────────────────────────────────────────────────────

class _CreateEventInput(BaseModel):
    calendar_id: str = Field(default="primary", description="Calendar ID.")
    summary: str = Field(..., description="Event title.")
    start_time: str = Field(..., description="Start ISO datetime.")
    end_time: str = Field(..., description="End ISO datetime.")
    description: str = Field(default="", description="Event description.")
    attendees: str = Field(default="", description="Comma-separated emails.")


class CreateEventTool(BaseTool):
    name: str = "create_calendar_event"
    description: str = "Create a new event in Google Calendar. start_time and end_time should be ISO datetimes like '2026-06-15T14:00:00'."
    args_schema: type[BaseModel] = _CreateEventInput
    tool_category: str = "orchestrate"

    def _run(self, calendar_id: str = "primary", summary: str = "", start_time: str = "", end_time: str = "", description: str = "", attendees: str = "") -> str:
        service = _get_calendar_service()
        if service is None:
            return json.dumps({"error": "Google Calendar not configured."})

        try:
            body = {
                "summary": summary,
                "start": {"dateTime": _normalize_date(start_time), "timeZone": "UTC"},
                "end": {"dateTime": _normalize_date(end_time), "timeZone": "UTC"},
            }
            if description:
                body["description"] = description
            if attendees.strip():
                body["attendees"] = [{"email": a.strip()} for a in attendees.split(",")]

            event = service.events().insert(calendarId=calendar_id, body=body).execute()
            return json.dumps({"id": event["id"], "summary": event.get("summary"), "link": event.get("htmlLink"), "created": True}, indent=2)
        except Exception as exc:
            return json.dumps({"error": str(exc)})


# ── Find Free Slots ──────────────────────────────────────────────────────────

class _FreeSlotsInput(BaseModel):
    calendar_id: str = Field(default="primary", description="Calendar ID.")
    days: int = Field(default=7, description="Days to look ahead.")
    duration_min: int = Field(default=60, description="Minimum slot in minutes.")
    start_hour: int = Field(default=9, description="Earliest hour (0-23).")
    end_hour: int = Field(default=17, description="Latest hour (0-23).")


class FindFreeSlotsTool(BaseTool):
    name: str = "find_free_slots"
    description: str = "Find available time slots in a calendar for the next N days."
    args_schema: type[BaseModel] = _FreeSlotsInput
    tool_category: str = "read"

    def _run(self, calendar_id: str = "primary", days: int = 7, duration_min: int = 60, start_hour: int = 9, end_hour: int = 17) -> str:
        service = _get_calendar_service()
        if service is None:
            return json.dumps({"error": "Google Calendar not configured."})

        try:
            now = datetime.now(timezone.utc)
            time_min = now.isoformat()
            time_max = (now + timedelta(days=days)).isoformat()

            events = service.events().list(calendarId=calendar_id, timeMin=time_min, timeMax=time_max, singleEvents=True, orderBy="startTime").execute()

            busy = []
            for e in events.get("items", []):
                s = e["start"].get("dateTime", e["start"].get("date"))
                en = e["end"].get("dateTime", e["end"].get("date"))
                busy.append((s, en))

            free_slots = []
            cursor = now.replace(hour=start_hour, minute=0, second=0, microsecond=0)
            if cursor < now:
                cursor += timedelta(days=1)

            for _ in range(days * 48):
                slot_end = cursor + timedelta(minutes=duration_min)
                if cursor.hour < start_hour or slot_end.hour > end_hour:
                    cursor += timedelta(minutes=30)
                    continue
                if cursor.hour >= end_hour:
                    cursor = (cursor + timedelta(days=1)).replace(hour=start_hour)
                    continue
                overlaps = any(
                    cursor < datetime.fromisoformat(be) and slot_end > datetime.fromisoformat(bs)
                    for bs, be in busy
                )
                if not overlaps:
                    free_slots.append({"start": cursor.isoformat(), "end": slot_end.isoformat()})
                cursor += timedelta(minutes=30)

            return json.dumps(free_slots[:15], indent=2)
        except Exception as exc:
            return json.dumps({"error": str(exc)})


def create_gcal_tools() -> list[BaseTool]:
    """Return native CrewAI tools for Google Calendar access.

    Usage: role.tools.extend(create_gcal_tools())
    """
    return [ListEventsTool()]  # Keep minimal — add CreateEventTool/FindFreeSlotsTool as needed
