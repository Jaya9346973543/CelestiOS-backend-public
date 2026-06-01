from openai import AsyncOpenAI
from datetime import datetime, timedelta
from core.config import settings
from typing import Optional, Tuple

client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)


def _classify_day(events: list, checkin_data: dict = None) -> str:
    meeting_count = len(events)
    sleep_hours = None
    energy_level = None

    if checkin_data:
        # Convert sleep_hours from string to float (database stores as text)
        sleep_str = checkin_data.get("sleep_hours")
        if sleep_str:
            try:
                sleep_hours = float(sleep_str)
            except (ValueError, TypeError):
                sleep_hours = None
        energy_level = checkin_data.get("energy_level")

    low_sleep = sleep_hours is not None and sleep_hours < 6
    low_energy = energy_level == "low"
    many_meetings = meeting_count >= 4

    if low_sleep and many_meetings:
        return "burnout"
    if many_meetings:
        return "overloaded"
    if low_sleep or low_energy:
        return "recovery"
    if meeting_count >= 3:
        return "fragmented"
    return "normal"


def _format_time(iso_str: str, user_timezone: Optional[str] = None) -> str:
    """Convert UTC time to user's local timezone and format it."""
    if not iso_str:
        return "unknown"
    try:
        # Parse UTC time
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))

        # Convert to user's timezone if provided
        if user_timezone:
            try:
                import pytz
                user_tz = pytz.timezone(user_timezone)
                if dt.tzinfo is None:
                    dt = pytz.UTC.localize(dt)
                dt = dt.astimezone(user_tz)
            except Exception:
                pass  # Fall back to UTC if conversion fails

        return dt.strftime("%I:%M %p").lstrip("0")
    except Exception:
        try:
            dt = datetime.fromisoformat(iso_str)
            return dt.strftime("%I:%M %p").lstrip("0")
        except Exception:
            return iso_str


def _calculate_duration(start: str, end: str) -> str:
    try:
        start_dt = datetime.fromisoformat(start.replace("Z", "+00:00"))
        end_dt = datetime.fromisoformat(end.replace("Z", "+00:00"))
        diff = end_dt - start_dt
        minutes = int(diff.total_seconds() // 60)
        if minutes >= 60:
            hours = minutes // 60
            remaining = minutes % 60
            if remaining:
                return f"{hours}h {remaining}m"
            return f"{hours}h"
        return f"{minutes}m"
    except Exception:
        return "unknown duration"


def _format_events_for_prompt(events: list, user_timezone: Optional[str] = None) -> str:
    if not events:
        return "No events scheduled today."

    lines = []
    lines.append(f"TOTAL EVENTS: {len(events)}")
    lines.append("")

    for i, event in enumerate(events, 1):
        summary = event.get("summary", "Untitled")
        start_raw = event.get("start", "")
        end_raw = event.get("end", "")
        start = _format_time(start_raw, user_timezone)
        end = _format_time(end_raw, user_timezone)
        duration = _calculate_duration(start_raw, end_raw)
        lines.append(f"[{i}/{len(events)}] \"{summary}\" | {start} to {end} | Duration: {duration}")

    lines.append("")
    lines.append(f"TOTAL: {len(events)} separate events. Even if names are identical, each is a different event at a different time.")

    return "\n".join(lines)


def _build_context(user_context: dict = None, checkin_data: dict = None) -> tuple[str, str, str, str]:
    context_parts = []
    weekly_goal = "personal projects"
    priority = None
    retrospective = ""

    if user_context:
        if user_context.get("name"):
            context_parts.append(f"Name: {user_context['name']}")
        if user_context.get("profession"):
            context_parts.append(f"Profession: {user_context['profession']}")
        if user_context.get("short_term_goal"):
            weekly_goal = user_context["short_term_goal"]
            context_parts.append(f"Weekly goal: {weekly_goal}")
        if user_context.get("timezone"):
            context_parts.append(f"Timezone: {user_context['timezone']}")

        # Morning retrospective - check yesterday's data
        yesterday = user_context.get("yesterday")
        if yesterday:
            # User completed evening check-in yesterday - use that data
            completed = yesterday.get("completed_priority")
            disruption = yesterday.get("disruption")
            disruption_detail = yesterday.get("disruption_detail")

            retrospective = f"""
YESTERDAY'S FEEDBACK:
User completed evening check-in with the following:
- Priority completion: {completed if completed else 'Unknown'}
- Disruption level: {disruption if disruption else 'None'}
- Disruption details: {disruption_detail if disruption_detail else 'None'}

INSTRUCTION: If relevant to today's plan, briefly acknowledge patterns (1 sentence max).
Example: "Yesterday had disruptions with meetings, so protect today's focus window."
Only mention if it helps today's planning. Don't force it.
"""
        # Note: If yesterday is None, we don't have data to create retrospective
        # This could mean either no check-in yesterday, or it's the first day

    if checkin_data:
        if checkin_data.get("sleep_hours"):
            context_parts.append(f"Sleep last night: {checkin_data['sleep_hours']} hours")
        if checkin_data.get("energy_level"):
            context_parts.append(f"Energy level: {checkin_data['energy_level']}")
        if checkin_data.get("priority"):
            priority = checkin_data["priority"]
            context_parts.append(f"Today's priority: {priority}")
        else:
            context_parts.append(f"No priority set. Weekly goal: {weekly_goal}")

    context_str = "\n".join(context_parts) if context_parts else "No context available."
    return context_str, weekly_goal, priority, retrospective


def _calculate_focus_windows(events: list, current_time: Optional[str] = None, user_timezone: Optional[str] = None) -> Tuple[Optional[str], float, str]:
    """
    Calculate smart focus windows based on calendar gaps.

    Args:
        events: List of calendar events
        current_time: Current time in ISO format (UTC)
        user_timezone: User's timezone string (e.g., "America/Chicago")

    Returns:
        - focus_window_str: Human-readable focus window (e.g., "2:30 PM - 5:00 PM")
        - gap_hours: Duration of the gap in hours
        - recommendation_type: "deep_work" (2+ hours), "progress" (1-2 hours), or "fragmented" (<1 hour)
    """
    # Helper to convert UTC datetime to user's timezone for display
    def to_user_tz(dt):
        if not user_timezone:
            return dt
        try:
            import pytz
            user_tz = pytz.timezone(user_timezone)
            if dt.tzinfo is None:
                dt = pytz.UTC.localize(dt)
            return dt.astimezone(user_tz)
        except:
            return dt
    if not events:
        # No events today - rest of day is free
        return "rest of day", 4.0, "deep_work"

    # Parse current time
    now = None
    if current_time:
        try:
            now = datetime.fromisoformat(current_time.replace("Z", "+00:00"))
        except Exception:
            pass

    # Parse events and find gaps
    event_times = []
    for event in events:
        try:
            start = datetime.fromisoformat(event.get("start", "").replace("Z", "+00:00"))
            end = datetime.fromisoformat(event.get("end", "").replace("Z", "+00:00"))
            event_times.append((start, end))
        except Exception:
            continue

    if not event_times:
        return "rest of day", 4.0, "deep_work"

    # Sort events by start time
    event_times.sort(key=lambda x: x[0])

    # Find gaps between events (and after last event)
    gaps = []

    # Gap before first event (from now until first event)
    first_event_start = event_times[0][0]
    if now and now < first_event_start:
        gap_hours = (first_event_start - now).total_seconds() / 3600
        gaps.append((now, first_event_start, gap_hours, True))  # True = starts from now, use generic time

    # Gaps between events
    for i in range(len(event_times) - 1):
        gap_start = event_times[i][1]  # End of current event
        gap_end = event_times[i + 1][0]  # Start of next event

        # Only consider future gaps
        gap_starts_from_now = False
        if now and gap_start < now:
            gap_start = now
            gap_starts_from_now = True

        if gap_end > gap_start:
            gap_hours = (gap_end - gap_start).total_seconds() / 3600
            gaps.append((gap_start, gap_end, gap_hours, gap_starts_from_now))

    # Gap after last event (rest of day)
    last_event_end = event_times[-1][1]
    rest_of_day_gap = None

    if now and last_event_end < now:
        # All events are in the past - rest of day is free
        gap_hours = 3.0
        rest_of_day_gap = (now, now + timedelta(hours=3), gap_hours, True)  # True = is rest of day
    elif not now or last_event_end > now:
        # After last event
        gap_hours = 2.0
        rest_of_day_gap = (last_event_end, last_event_end + timedelta(hours=2), gap_hours, True)

    # Find best gap (longest gap that's in the future)
    if not gaps and not rest_of_day_gap:
        return "rest of day", 0.5, "fragmented"

    # Filter out past gaps (only include gaps that haven't ended yet)
    if now:
        gaps = [g for g in gaps if g[1] > now]

    # Add rest of day gap for comparison
    if rest_of_day_gap:
        gaps.append(rest_of_day_gap)

    if not gaps:
        return "rest of day", 0.5, "fragmented"

    # Sort by gap duration (longest first)
    gaps.sort(key=lambda x: x[2], reverse=True)
    best_gap = gaps[0]

    # Check if this gap starts from "now" (either rest of day or adjusted gap)
    is_generic_gap = len(best_gap) == 4 and best_gap[3] == True

    if is_generic_gap:
        # Use generic description instead of exact time
        gap_hours = best_gap[2]

        # Determine generic time period based on current hour
        if now:
            now_local = to_user_tz(now)
            hour = now_local.hour
            if hour < 12:
                period = "rest of morning"
            elif hour < 17:
                period = "rest of afternoon"
            else:
                period = "this evening"
        else:
            period = "rest of day"

        # Determine recommendation type
        if gap_hours >= 2:
            rec_type = "deep_work"
        elif gap_hours >= 1:
            rec_type = "progress"
        else:
            rec_type = "fragmented"

        return period, gap_hours, rec_type

    # Regular gap between meetings - show exact times
    # Validate gap (start must be before end)
    if best_gap[1] <= best_gap[0]:
        return "rest of day", 0.5, "fragmented"

    # Convert to user's timezone before formatting
    start_local = to_user_tz(best_gap[0])
    end_local = to_user_tz(best_gap[1])

    start_fmt = start_local.strftime("%I:%M %p").lstrip("0")
    end_fmt = end_local.strftime("%I:%M %p").lstrip("0")
    gap_hours = best_gap[2]

    # Determine recommendation type
    if gap_hours >= 2:
        rec_type = "deep_work"
    elif gap_hours >= 1:
        rec_type = "progress"
    else:
        rec_type = "fragmented"

    return f"{start_fmt} - {end_fmt}", gap_hours, rec_type


async def generate_schedule_insights(
    events: list,
    user_context: dict = None,
    checkin_data: dict = None,
    current_time: Optional[str] = None,
) -> Tuple[str, str, str]:
    day_type = _classify_day(events, checkin_data)
    meeting_count = len(events)

    # Get user timezone
    user_tz = user_context.get("timezone") if user_context else None

    # Calculate smart focus windows even for fallback
    focus_window, gap_hours, rec_type = _calculate_focus_windows(events, current_time, user_tz)

    if not settings.OPENAI_API_KEY:
        if rec_type == "deep_work":
            task_suggestion = f"Tackle your main priority during the {focus_window} window."
            quick_do = f"your top priority during {focus_window}"
        elif rec_type == "progress":
            task_suggestion = f"Make progress on your priority in the {gap_hours:.1f} hour available."
            quick_do = f"make progress on priority in {gap_hours:.1f}-hour gap"
        else:
            task_suggestion = "Fragmented day - focus on quick wins between meetings."
            quick_do = "quick wins between meetings"

        return (
            f"You have {meeting_count} event(s) today.\n"
            f"Your best focus window is {focus_window}.\n"
            f"{task_suggestion}\n"
            "Reserve lighter tasks for gaps between meetings.",
            f"• Meetings: {meeting_count}\n"
            f"• Focus window: {focus_window}\n"
            f"• Do: {quick_do}\n"
            "• Avoid: heavy tasks in small gaps\n"
            "• Execution over deep work today.",
            day_type,
        )

    context_str, weekly_goal, priority, retrospective = _build_context(user_context, checkin_data)
    formatted_events = _format_events_for_prompt(events, user_tz)

    # Calculate smart focus windows (use user timezone for display)
    focus_window, gap_hours, rec_type = _calculate_focus_windows(events, current_time, user_tz)

    # Build focus window guidance based on gap type
    # Determine if focus window is generic or specific time
    is_generic_window = focus_window and ("evening" in focus_window or "afternoon" in focus_window or "morning" in focus_window or "day" in focus_window)

    if rec_type == "deep_work":
        focus_guidance = f"Focus window: {focus_window} ({gap_hours:.1f} hours available for deep work)"
        if is_generic_window:
            task_guidance = f"focus {focus_window} on [priority task]"
        else:
            task_guidance = f"dedicate the {focus_window} block to [priority task]"
    elif rec_type == "progress":
        focus_guidance = f"Focus window: {focus_window} ({gap_hours:.1f} hour available)"
        if is_generic_window:
            task_guidance = f"make progress on [priority task] {focus_window}"
        else:
            task_guidance = f"make progress on [priority task] during the {gap_hours:.1f}-hour window"
    else:
        focus_guidance = f"Fragmented day with back-to-back meetings"
        task_guidance = f"make quick wins on [priority task] between meetings"

    current_time_str = ""
    time_of_day_context = ""
    if current_time:
        try:
            now = datetime.fromisoformat(current_time.replace("Z", "+00:00"))
            # Convert to user's timezone
            if user_tz:
                try:
                    import pytz
                    user_tz_obj = pytz.timezone(user_tz)
                    if now.tzinfo is None:
                        now = pytz.UTC.localize(now)
                    now = now.astimezone(user_tz_obj)
                except Exception:
                    pass

            hour = now.hour
            current_time_str = f"Current time: {now.strftime('%I:%M %p').lstrip('0')}"

            # Add time-of-day context for AI to adjust tone
            if hour < 10:
                time_of_day_context = "Time of day: Early morning (planning mode)"
            elif hour < 12:
                time_of_day_context = "Time of day: Late morning (planning mode)"
            elif hour < 14:
                time_of_day_context = "Time of day: Midday"
            elif hour < 17:
                time_of_day_context = "Time of day: Afternoon (execution mode)"
            elif hour < 20:
                time_of_day_context = "Time of day: Evening (wind-down mode - acknowledge if planned focus windows have passed)"
            else:
                time_of_day_context = "Time of day: Night (late work - keep expectations realistic)"
        except Exception:
            pass

    prompt = f"""
User Context:
{context_str}
{current_time_str}
{time_of_day_context}

{retrospective if retrospective else ""}

Today's Schedule:
{formatted_events}

Day classification: {day_type}

CALCULATED FOCUS WINDOW:
{focus_guidance}

ABSOLUTE RULES ABOUT EVENTS:
- The user has EXACTLY {meeting_count} event(s) today. Say "{meeting_count}" not any other number.
- Events with the SAME NAME are DIFFERENT events at DIFFERENT times. Count each one separately.
- Reference EVERY event by its actual time from the schedule above.
- NEVER suggest doing deep work "before" an event if there's less than 2 hours available.
- The calculated focus window above is based on REAL gaps in the calendar after current time.
- If focus window is AFTER meetings, say so explicitly (e.g., "in the afternoon after your 10 AM meeting").
- Identify free gaps BETWEEN and AFTER events for focus work.

FOCUS WINDOW GRAMMAR:
- If focus window is GENERIC (like "this evening", "rest of afternoon"), use it naturally without "the":
  * Good: "focus this evening on your priority"
  * Bad: "dedicate the this evening block to your priority"
- If focus window is SPECIFIC TIMES (like "2:00 PM - 4:00 PM"), you can use "the":
  * Good: "dedicate the 2:00 PM - 4:00 PM block to your priority"

PRODUCT PRINCIPLE - PLANS ARE STATIC, DECISIONS ARE DYNAMIC:
- Morning (before noon): Provide a PLAN for the day. Reference future focus windows confidently.
- Afternoon/Evening (after 2 PM): Acknowledge if earlier focus windows have passed. Shift to what's actionable NOW.
  * If checking late: "Your earlier focus window has passed. Now you have ~X hours left today."
  * Adjust recommendations: morning = deep work planning, evening = execution/quick wins
- NEVER pretend it's earlier than it is. Be honest about remaining time.
- If it's late and little time remains, keep expectations realistic.

You must return TWO sections separated by exactly this line:
---QUICK---

SECTION 1: DETAILED (morning view)
Plain sentences. One per line. 4-5 lines total. No bullets. No formatting.
Mention correct total number of events. Reference actual event names and times.
Use the calculated focus window above. Include one "not ideal for" line and one break suggestion.

SECTION 2: QUICK (glance view)
Return as a bulleted list. Each line MUST start with "• " (bullet character followed by a space).
Separate each bullet with a newline character.
Exactly 5 bullets. Ultra-concise.

THE FIRST BULLET MUST ALWAYS BE the meeting/event count. Format:
• Meetings: [exact number of events]

Remaining 4 bullets follow this format:
• Focus window: {focus_window if focus_window else "[time range]"}
• Do: {task_guidance}
• Avoid: [what to skip today]
• [One short sentence about the day type]

TONE — Calm, precise, context-aware. Use the day classification "{day_type}":
normal → balanced day.
overloaded → high meeting load. Execution mode.
recovery → low energy detected. Light tasks recommended.
fragmented → schedule fragmented. Use gaps efficiently.
burnout → minimal capacity. Protect energy.

Do not be motivational or conversational. State facts and recommendations directly.

Priority handling:
{"Priority is: " + priority + ". Mention it in both sections." if priority else "No priority set. Mention weekly goal: " + weekly_goal + " in both sections."}

RULES:
- DETAILED: plain text sentences, one per line. No bullets. No markdown. No emojis.
- QUICK: bulleted list using "• " prefix on every line. Separated by newlines. First bullet is always meeting count.
- Use ONLY real times from the schedule above.
- Be direct and factual. No motivational language. No filler words.

EXAMPLE 1 (Morning check-in at 8 AM - planning mode):
Sleep: 7 hours. Energy level: high.
Schedule: 2 meetings at 10:00 AM and 4:00 PM.
Focus window available: 11:00 AM to 4:00 PM (5 hours).
Use this block for applying to Google for review.
Avoid scheduling new meetings during this window.
---QUICK---
• Meetings: 2
• Focus window: 11:00 AM - 4:00 PM
• Do: dedicate 11:00 AM - 4:00 PM to apply to Google
• Avoid: new meetings in focus window
• 5-hour block for deep work

EXAMPLE 2 (Evening check-in at 5 PM - execution mode, focus window passed):
Sleep: 7 hours. Energy level: high.
Meetings completed: 10:00 AM and 2:00 PM.
Remaining time: approximately 2 hours before end of day.
Focus on execution tasks that can finish tonight.
Defer deep work and larger tasks to tomorrow.
---QUICK---
• Meetings: 2 (completed)
• Focus window: this evening (~2h left)
• Do: execution tasks that can finish tonight
• Avoid: starting deep work this late
• Limited time remaining, focus on completion

EXAMPLE 3 (Afternoon at 2 PM - gap before evening meeting):
Sleep: 7 hours. Energy level: high.
Meeting at 10:00 AM completed. Next meeting at 9:00 PM.
Evening window available for focused work (approximately 3 hours).
Use this time for applying to Google for review.
Avoid starting new tasks after 9 PM meeting.
---QUICK---
• Meetings: 2
• Focus window: this evening
• Do: focus this evening on applying to Google
• Avoid: new tasks after 9 PM
• 3-hour evening window available
"""

    try:
        response = await client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a calm, precise, and context-aware system that helps users decide how to approach their day. "
                        "Do not be motivational, conversational, or verbose. "
                        "Use short, direct sentences. "
                        "Always base your response on the user's energy, schedule, and priorities. "
                        "Provide clear recommendations on what to do and what to avoid. "
                        "Do not use emojis, filler words, or generic advice. "
                        "Write like a system interpreting real-world conditions, not like a chatbot. "
                        "\n\n"
                        "You return exactly two sections separated by ---QUICK--- on its own line. "
                        "Section 1 is detailed: 4-5 plain text sentences, one per line, no bullets. "
                        "Section 2 is quick: exactly 5 bullet points, each starting with '• ', separated by newlines. "
                        "The FIRST bullet in quick section MUST always be '• Meetings: [count]'. "
                        "No markdown. No bold. No emojis. "
                        "Avoid redundant phrasing between bullets - if you mention a time period in one bullet, don't repeat it in the next. "
                        "You MUST state the exact number of events. "
                        "Events with the same name at different times are SEPARATE events. Count each one. "
                        "You MUST reference actual event names and times from the schedule. "
                        "NEVER invent or assume event times."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            max_tokens=300,
            temperature=0.6,
        )

        raw = response.choices[0].message.content.strip()

        if "---QUICK---" in raw:
            parts = raw.split("---QUICK---", 1)
            detailed = parts[0].strip()
            quick = parts[1].strip()
        else:
            detailed = raw
            quick = "\n".join(raw.strip().split("\n")[:5])

        return detailed, quick, day_type

    except Exception as e:
        print(f"OpenAI Error: {e}")
        return (
            "Failed to generate insights. Try again later.",
            "• Failed to generate insights. Try again later.",
            day_type,
        )


async def generate_rest_of_day_plan(
    events: list,
    user_context: dict = None,
    started_at: str = None,
    current_time: str = None,
) -> Tuple[str, str]:
    """
    Generate AI-powered rest-of-day plan for users who arrive late (4+ PM).
    This provides a focused, achievable plan for the remaining hours.
    Handles both late afternoon (4-8 PM) and night work (8+ PM).
    Applies "plans are static, decisions are dynamic" principle.
    """
    # Determine actual current time and time-of-day context
    actual_hour = None
    time_of_day_context = ""
    if current_time:
        try:
            from datetime import datetime, timezone
            import pytz
            now = datetime.fromisoformat(current_time.replace("Z", "+00:00"))

            # Convert to user's timezone
            user_tz_str = user_context.get("timezone") if user_context else None
            if user_tz_str:
                try:
                    user_tz = pytz.timezone(user_tz_str)
                    if now.tzinfo is None:
                        now = pytz.UTC.localize(now)
                    now = now.astimezone(user_tz)
                except Exception:
                    pass

            actual_hour = now.hour

            # Time-of-day context
            if actual_hour < 18:
                time_of_day_context = "Late afternoon start (realistic expectations, 2-3 hours available)"
            elif actual_hour < 20:
                time_of_day_context = "Evening start (focus on quick wins, 1-2 hours available)"
            elif actual_hour < 22:
                time_of_day_context = "Night work (keep it minimal, 1-2 tasks max)"
            else:
                time_of_day_context = "Very late night (extremely limited time, 1 focused task only)"
        except Exception:
            pass

    # Determine if this is night work (8+ PM) or late afternoon
    is_night_work = False
    stated_hour = None
    if started_at:
        try:
            stated_hour = int(started_at.split(':')[0])
            is_night_work = stated_hour >= 20  # 8 PM or later
        except Exception:
            pass

    # Compare stated vs actual time
    time_mismatch = ""
    if actual_hour and stated_hour and actual_hour > stated_hour:
        time_mismatch = f"User said they'd start at {started_at}, but it's actually {actual_hour}:00. Acknowledge this delay briefly."

    if not settings.OPENAI_API_KEY:
        event_count = len(events)
        # Use focus if provided, otherwise use weekly goal
        focus_or_goal = user_context.get("focus") if user_context and user_context.get("focus") else weekly_goal
        if is_night_work:
            detailed_fallback = (
                f"Starting at {started_at}. Very limited time tonight.\n"
                f"Remaining events: {event_count}.\n"
                f"Keep it minimal: ONE task - {focus_or_goal}.\n"
                "Defer everything else to tomorrow.\n"
                "Wrap up by 1-2 AM."
            )
            quick_fallback = (
                f"• Meetings: {event_count}\n"
                "• Focus window: late night hours (1-2h max)\n"
                f"• Do: ONE task - {focus_or_goal}\n"
                "• Avoid: attempting multiple priorities tonight\n"
                "• Late night session, keep expectations minimal"
            )
        else:
            detailed_fallback = (
                f"Start time: {started_at}. Approximately 3-4 hours available.\n"
                f"Remaining events: {event_count}.\n"
                f"Priority: {focus_or_goal}.\n"
                "Defer non-urgent tasks to tomorrow.\n"
                "Recommended end time: 8-9 PM."
            )
            quick_fallback = (
                f"• Meetings: {event_count}\n"
                "• Focus window: rest of evening\n"
                f"• Do: make progress on {focus_or_goal}\n"
                "• Avoid: non-urgent tasks, defer to tomorrow\n"
                "• 3-4 hours available for focused work"
            )

        return detailed_fallback, quick_fallback

    # Build user context
    context_parts = []
    weekly_goal = "personal projects"

    if user_context:
        if user_context.get("name"):
            context_parts.append(f"Name: {user_context['name']}")
        if user_context.get("profession"):
            context_parts.append(f"Profession: {user_context['profession']}")
        if user_context.get("short_term_goal"):
            weekly_goal = user_context["short_term_goal"]
            context_parts.append(f"Weekly goal: {weekly_goal}")
        # Night work focus overrides weekly goal if provided
        if user_context.get("focus"):
            weekly_goal = user_context["focus"]
            context_parts.append(f"Tonight's focus: {weekly_goal}")
        if user_context.get("started_at"):
            context_parts.append(f"Starting work at: {user_context['started_at']}")

    context_str = "\n".join(context_parts) if context_parts else "No context available."
    user_tz = user_context.get("timezone") if user_context else None
    formatted_events = _format_events_for_prompt(events, user_tz)

    # Build appropriate messaging based on time of day
    event_count = len(events)
    if is_night_work:
        # Use user's stated focus if provided, otherwise fall back to weekly goal
        focus_description = f"Tonight's focus: {weekly_goal}" if user_context and user_context.get("focus") else f"Weekly goal: {weekly_goal}"
        situation = f"The user is working LATE AT NIGHT (starting at {started_at}). This is NOT regular work hours. {focus_description}"
        time_guidance = "Since it's night time (8+ PM), keep it MINIMAL. Suggest wrapping up by 1-2 AM. Use words like 'tonight', 'late night', '1-2 tasks max'. Use their stated focus EXACTLY as provided."
        example_detailed = f"""Starting at {started_at}. Very limited time tonight.
{event_count} event(s) remaining on calendar.
Keep it minimal: focus on ONE task - {weekly_goal}.
Defer everything else to tomorrow morning.
Wrap up by 1-2 AM to maintain rest."""
        example_quick = f"""• Meetings: {event_count}
• Focus window: late night hours (1-2h max)
• Do: ONE task - {weekly_goal}
• Avoid: attempting multiple priorities tonight
• Late night session, keep expectations minimal"""
    else:
        situation = f"The user is starting their work day LATE (at {started_at} in the afternoon)."
        time_guidance = "Suggest wrapping up by 8-9 PM to maintain work-life boundaries."
        example_detailed = f"""Start time: {started_at}. Approximately 3-4 hours available.
Remaining calendar: {event_count} event(s) scheduled.
Focus on {weekly_goal} during available time.
Attend scheduled events, then use remaining time for priority work.
Defer non-urgent tasks to tomorrow."""
        example_quick = f"""• Meetings: {event_count}
• Focus window: rest of evening
• Do: make progress on {weekly_goal}
• Avoid: non-urgent tasks outside of focus window
• Late afternoon start with 3-4 hours available"""

    prompt = f"""
User Context:
{context_str}

Remaining Events Today:
{formatted_events}

SITUATION:
{situation}
They did not complete a morning check-in because they're starting so late in the day.

TIME CONTEXT:
{time_of_day_context}
{time_mismatch}

YOUR TASK:
Generate a realistic, achievable rest-of-day plan. This is NOT a full day plan.

CRITICAL: The user is starting work at {started_at}. You MUST reference this time in your response.
Do NOT use the current actual time. Always use the user's stated start time: {started_at}.

PRODUCT PRINCIPLE - PLANS ARE STATIC, DECISIONS ARE DYNAMIC:
Since they're checking in LATE, this is DECISION mode, not planning mode.
Focus on what's actionable from {started_at} onwards with the time they actually have.

You must return TWO sections separated by exactly this line:
---QUICK---

SECTION 1: DETAILED (full sentences)
Plain sentences. One per line. 4-5 lines total. No bullets. No formatting.
Acknowledge they're starting late, mention actual remaining events count, recommend ONE focused priority,
mention what to defer, and provide realistic wrap-up time based on TIME CONTEXT.

SECTION 2: QUICK (bulleted)
Return as a bulleted list. Each line MUST start with "• " (bullet character followed by a space).
Separate each bullet with a newline character.
Exactly 5 bullets. Ultra-concise.

THE FIRST BULLET MUST ALWAYS BE the meeting/event count. Format:
• Meetings: [exact number of remaining events]

Remaining 4 bullets follow this format:
• Focus window: [time period - if night work, use "late night hours" or "tonight", NOT "this evening"]
• Do: [ONE focused priority - if time was mentioned in previous bullet, don't repeat it here]
• Avoid: [what to skip - use "outside of focus window" or similar pattern]
• [Short summary describing the session type and available hours]

CRITICAL FOR NIGHT WORK (8+ PM): Use distinctive language:
- Say "late night hours" or "tonight", NOT "this evening"
- Emphasize "ONE task", "keep it minimal", "1-2 hours max"
- Mention "wrap up by 1-2 AM"
- Last bullet should say "Late night session" NOT "Normal day"

CRITICAL: Do NOT repeat time references between bullets. If "Focus window" says "this evening", then "Do:" should say "make progress on [goal]", NOT "focus this evening on [goal]".

RULES:
- DETAILED: plain text sentences, one per line. No bullets. No markdown. No emojis.
- QUICK: bulleted list using "• " prefix on every line. Separated by newlines. First bullet is always meeting count.
- {time_guidance}
- Be direct and factual. No motivational language. No filler words.

TONE: Calm, precise, context-aware. State facts and recommendations directly. Do not be conversational or verbose.

EXAMPLE OUTPUT:

{example_detailed}
---QUICK---
{example_quick}
"""

    try:
        response = await client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a calm, precise, and context-aware system that helps users decide how to approach their day. "
                        "Do not be motivational, conversational, or verbose. "
                        "Use short, direct sentences. "
                        "Always base your response on the user's energy, schedule, and priorities. "
                        "Provide clear recommendations on what to do and what to avoid. "
                        "Do not use emojis, filler words, or generic advice. "
                        "Write like a system interpreting real-world conditions, not like a chatbot. "
                        "\n\n"
                        "You return exactly two sections separated by ---QUICK--- on its own line. "
                        "Section 1 is detailed: 4-5 plain text sentences, one per line, no bullets. "
                        "Section 2 is quick: exactly 5 bullet points, each starting with '• ', separated by newlines. "
                        "The FIRST bullet in quick section MUST always be '• Meetings: [count of remaining events]'. "
                        "No markdown. No bold. No emojis. "
                        "Avoid redundant phrasing between bullets - if you mention a time period in one bullet, don't repeat it in the next. "
                        "Keep expectations realistic - they're starting late, so suggest ONE focused priority."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            max_tokens=250,
            temperature=0.7,
        )

        raw = response.choices[0].message.content.strip()

        if "---QUICK---" in raw:
            parts = raw.split("---QUICK---", 1)
            detailed = parts[0].strip()
            quick = parts[1].strip()
        else:
            # Fallback if separator not found
            detailed = raw
            quick = "\n".join(raw.strip().split("\n")[:5])

        return detailed, quick

    except Exception as e:
        print(f"OpenAI Error: {e}")
        event_count = len(events)
        if is_night_work:
            detailed_fallback = (
                f"Start time: {started_at}. Limited time available tonight.\n"
                f"Remaining events: {event_count}.\n"
                f"Focus on one task: {weekly_goal}.\n"
                "Defer all other work to tomorrow.\n"
                "Recommended end time: 1-2 AM."
            )
            quick_fallback = (
                f"• Meetings: {event_count}\n"
                "• Focus window: this evening\n"
                f"• Do: focus on ONE task for {weekly_goal}\n"
                "• Avoid: attempting multiple tasks tonight\n"
                "• Limited time, single priority recommended"
            )
        else:
            detailed_fallback = (
                f"Start time: {started_at}. Approximately 3-4 hours available.\n"
                f"Remaining events: {event_count}.\n"
                f"Priority: {weekly_goal}.\n"
                "Defer non-urgent tasks to tomorrow.\n"
                "Recommended end time: 8-9 PM."
            )
            quick_fallback = (
                f"• Meetings: {event_count}\n"
                "• Focus window: rest of evening\n"
                f"• Do: make progress on {weekly_goal}\n"
                "• Avoid: non-urgent tasks, defer to tomorrow\n"
                "• 3-4 hours available for focused work"
            )

        return detailed_fallback, quick_fallback
