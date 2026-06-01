"""
ICS File Generator
Generates .ics (iCalendar) files for focus blocks and calendar changes.
"""

from datetime import datetime
from typing import Dict, List, Optional
import pytz
import uuid


def generate_ics_file(
    focus_block: Dict,
    user_timezone: str = "UTC",
    priority_text: Optional[str] = None
) -> str:
    """
    Generate .ics file content for a focus block.

    Args:
        focus_block: Focus block dict with start_time, end_time, reasoning
        user_timezone: User's timezone (e.g., "America/Los_Angeles")
        priority_text: User's priority text to include in description

    Returns:
        ICS file content as string
    """
    # Parse times
    start_dt = datetime.fromisoformat(focus_block["start_time"].replace('Z', '+00:00'))
    end_dt = datetime.fromisoformat(focus_block["end_time"].replace('Z', '+00:00'))

    # Convert to user timezone
    tz = pytz.timezone(user_timezone)
    start_local = start_dt.astimezone(tz)
    end_local = end_dt.astimezone(tz)

    # Format for ICS (YYYYMMDDTHHMMSS)
    start_ics = start_local.strftime("%Y%m%dT%H%M%S")
    end_ics = end_local.strftime("%Y%m%dT%H%M%S")

    # Generate unique UID
    event_uid = f"celesti-focus-{uuid.uuid4()}@celesti.life"

    # Build description
    description_parts = [
        "Protected time for your priority work.",
        "",
        f"Reason: {focus_block['reasoning']}"
    ]

    if priority_text:
        description_parts.insert(1, f"Priority: {priority_text}")
        description_parts.insert(2, "")

    description = "\\n".join(description_parts)

    # Create ICS content
    ics_content = f"""BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//CelestiOS//Burnout Prevention//EN
CALSCALE:GREGORIAN
METHOD:PUBLISH
BEGIN:VEVENT
UID:{event_uid}
DTSTAMP:{datetime.now(pytz.UTC).strftime("%Y%m%dT%H%M%SZ")}
DTSTART;TZID={user_timezone}:{start_ics}
DTEND;TZID={user_timezone}:{end_ics}
SUMMARY:🎯 Focus Block - Priority Work
DESCRIPTION:{description}
STATUS:CONFIRMED
TRANSP:OPAQUE
BEGIN:VALARM
ACTION:DISPLAY
DESCRIPTION:Focus Block starting in 15 minutes
TRIGGER:-PT15M
END:VALARM
END:VEVENT
END:VCALENDAR"""

    return ics_content


def generate_multi_event_ics(
    events: List[Dict],
    user_timezone: str = "UTC"
) -> str:
    """
    Generate .ics file with multiple events (focus block + moved meetings).

    Args:
        events: List of event dicts, each with:
            {
                "subject": str,
                "start_time": ISO datetime,
                "end_time": ISO datetime,
                "description": str (optional),
                "event_type": "focus_block" | "moved_meeting"
            }
        user_timezone: User's timezone

    Returns:
        ICS file content as string
    """
    tz = pytz.timezone(user_timezone)
    now_utc = datetime.now(pytz.UTC).strftime("%Y%m%dT%H%M%SZ")

    # Start ICS file
    ics_content = """BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//CelestiOS//Burnout Prevention//EN
CALSCALE:GREGORIAN
METHOD:PUBLISH
"""

    # Add each event
    for event in events:
        start_dt = datetime.fromisoformat(event["start_time"].replace('Z', '+00:00'))
        end_dt = datetime.fromisoformat(event["end_time"].replace('Z', '+00:00'))

        start_local = start_dt.astimezone(tz)
        end_local = end_dt.astimezone(tz)

        start_ics = start_local.strftime("%Y%m%dT%H%M%S")
        end_ics = end_local.strftime("%Y%m%dT%H%M%S")

        event_uid = f"celesti-{uuid.uuid4()}@celesti.life"

        # Add emoji based on event type
        if event.get("event_type") == "focus_block":
            subject = f"🎯 {event['subject']}"
        else:
            subject = event['subject']

        description = event.get("description", "").replace("\n", "\\n")

        ics_content += f"""BEGIN:VEVENT
UID:{event_uid}
DTSTAMP:{now_utc}
DTSTART;TZID={user_timezone}:{start_ics}
DTEND;TZID={user_timezone}:{end_ics}
SUMMARY:{subject}
DESCRIPTION:{description}
STATUS:CONFIRMED
TRANSP:OPAQUE
END:VEVENT
"""

    # Close ICS file
    ics_content += "END:VCALENDAR"

    return ics_content


def format_ics_filename(user_id: str, date_str: str) -> str:
    """
    Generate a clean filename for the ICS file.

    Args:
        user_id: User's google_id
        date_str: Date string (YYYY-MM-DD)

    Returns:
        Filename like "celesti-focus-block-2026-05-04.ics"
    """
    return f"celesti-focus-block-{date_str}.ics"
