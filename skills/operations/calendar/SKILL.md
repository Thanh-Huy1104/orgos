---
name: calendar-management
description: Personal calendar management — checking, scheduling, and briefing
license: MIT
allowed-tools: [list_calendar_events, create_calendar_event, find_free_slots, web_search, web_fetch]
---

# Calendar Management

## Purpose
Manage the owner's Google Calendar — check schedules, find availability, schedule events, and provide daily briefings.

## Available Tools
- `list_calendar_events` — fetch events from Google Calendar
- `create_calendar_event` — add new events
- `find_free_slots` — find open time slots
- `web_search` / `web_fetch` — research context for meetings

## Common Tasks

### Daily Briefing
1. Check calendar for today + next 2 days
2. Summarize events with times and titles
3. Flag scheduling conflicts (overlapping events)
4. Suggest preparation tasks for important meetings
5. Note any gaps or free time

### What's on [day]?
1. Identify the target date (use context clues: "Saturday" = next Saturday)
2. Call `list_calendar_events` with `calendar_id=primary`
3. Set `time_min` to target date at 00:00, `time_max` to next day at 00:00
4. List each event with time, title, and any details

### Scheduling
1. Find available slots with `find_free_slots`
2. Confirm with owner before creating
3. Use `create_calendar_event` with clear summary and time

## Important
- Always use `calendar_id=primary` for the main calendar
- Dates in ISO format: `YYYY-MM-DD` or `YYYY-MM-DDTHH:MM:SS`
- When in doubt, check the actual date — don't guess
- The owner is Thomas
