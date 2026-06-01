"""
Burnout Detection Service
Analyzes calendar density, energy levels, and priorities to detect overload/stress.
Provides tiered interventions with specific focus block recommendations.
"""

from datetime import datetime, timedelta, time
from typing import List, Dict, Optional, Tuple
import pytz


# ═══════════════════════════════════════════════════════════════════════
# CONSTANTS
# ═══════════════════════════════════════════════════════════════════════

# Work hours configuration
WORK_START_HOUR = 9   # 9 AM
WORK_END_HOUR = 17    # 5 PM
END_OF_WORK_DAY = 17  # 5 PM - never move meetings past this on same day
WORK_HOURS_TOTAL = 8  # 8-hour workday

# Focus time configuration
PRIME_FOCUS_START = 10  # 10 AM
PRIME_FOCUS_END = 14    # 2 PM
MIN_FOCUS_BLOCK = 60    # minutes
IDEAL_FOCUS_BLOCK = 60  # minutes

# Break requirements
EXPECTED_BREAKS = 4      # 4 breaks in an 8-hour day (excluding lunch)
MIN_BREAK_DURATION = 15  # minutes
LUNCH_BREAK_MIN = 30     # Minimum duration to count as lunch
LUNCH_BREAK_MAX = 90     # Maximum duration for lunch break
LUNCH_HOUR_START = 11    # 11 AM - earliest lunch time
LUNCH_HOUR_END = 14      # 2 PM - latest lunch time

# Non-negotiable meeting keywords (never suggest moving)
NON_NEGOTIABLE_KEYWORDS = [
    "standup",
    "stand-up",
    "stand up",
    "daily sync",
    "daily scrum",
    "scrum",
    "all-hands",
    "all hands",
    "1:1",
    "one-on-one",
    "1-on-1",
    "performance review",
    "interview",
    "demo",
    "launch",
    "board meeting",
    "executive",
    "urgent",
    "critical",
    "gym",
    "workout",
    "exercise",
    "fitness"
]

# Low-priority meeting keywords (good candidates to move)
LOW_PRIORITY_KEYWORDS = [
    "sync",
    "catchup",
    "catch-up",
    "touch base",
    "check-in",
    "optional",
    "fyi",
    "social"
]

# Drain percentage weights
WEIGHT_MEETING_DENSITY = 0.4
WEIGHT_ENERGY_MISMATCH = 0.35
WEIGHT_BREAK_DEFICIT = 0.25


# ═══════════════════════════════════════════════════════════════════════
# HELPER FUNCTIONS
# ═══════════════════════════════════════════════════════════════════════

def parse_time(time_str: str, user_timezone: str = "UTC") -> datetime:
    """Parse ISO datetime string to timezone-aware datetime."""
    if isinstance(time_str, datetime):
        return time_str

    dt = datetime.fromisoformat(time_str.replace('Z', '+00:00'))

    # Convert to user timezone
    if dt.tzinfo is None:
        dt = pytz.UTC.localize(dt)

    tz = pytz.timezone(user_timezone)
    return dt.astimezone(tz)


def calculate_duration_minutes(start: datetime, end: datetime) -> int:
    """Calculate duration between two datetimes in minutes."""
    return int((end - start).total_seconds() / 60)


def is_within_work_hours(dt: datetime) -> bool:
    """Check if datetime falls within work hours (9 AM - 5 PM)."""
    hour = dt.hour
    return WORK_START_HOUR <= hour < WORK_END_HOUR


def is_within_prime_focus(dt: datetime) -> bool:
    """Check if datetime falls within prime focus hours (10 AM - 2 PM)."""
    hour = dt.hour
    return PRIME_FOCUS_START <= hour < PRIME_FOCUS_END


def is_non_negotiable(title: str) -> bool:
    """Check if meeting is non-negotiable (never suggest moving)."""
    title_lower = title.lower()
    return any(keyword in title_lower for keyword in NON_NEGOTIABLE_KEYWORDS)


def is_low_priority(title: str) -> bool:
    """Check if meeting appears to be low priority."""
    title_lower = title.lower()
    return any(keyword in title_lower for keyword in LOW_PRIORITY_KEYWORDS)


def get_work_hours_today(user_timezone: str = "UTC") -> Tuple[datetime, datetime]:
    """Get start and end of work hours for today in user's timezone."""
    tz = pytz.timezone(user_timezone)
    now = datetime.now(tz)

    work_start = now.replace(hour=WORK_START_HOUR, minute=0, second=0, microsecond=0)
    work_end = now.replace(hour=WORK_END_HOUR, minute=0, second=0, microsecond=0)

    return work_start, work_end


# ═══════════════════════════════════════════════════════════════════════
# SIGNAL DETECTION FUNCTIONS
# ═══════════════════════════════════════════════════════════════════════

def detect_overload(events: List[Dict], user_timezone: str = "UTC") -> Dict:
    """
    Detect calendar overload based on meeting density.

    Returns:
        {
            "triggered": bool,
            "meeting_hours": float,
            "meeting_density_percentage": int,
            "density_score": int (0-100),
            "back_to_back_hours": float,
            "longest_free_gap_minutes": int,
            "reasons": List[str]
        }
    """
    work_start, work_end = get_work_hours_today(user_timezone)

    # Filter events within work hours only
    work_events = []
    for event in events:
        start = parse_time(event['start_time'], user_timezone)
        end = parse_time(event['end_time'], user_timezone)

        if is_within_work_hours(start) or is_within_work_hours(end):
            work_events.append({
                'start': start,
                'end': end,
                'title': event.get('summary', 'Untitled')
            })

    # Sort by start time
    work_events.sort(key=lambda e: e['start'])

    # Calculate total meeting hours
    total_meeting_minutes = sum(
        calculate_duration_minutes(e['start'], e['end'])
        for e in work_events
    )
    meeting_hours = total_meeting_minutes / 60

    # Calculate meeting density percentage
    meeting_density_pct = int((meeting_hours / WORK_HOURS_TOTAL) * 100)

    # Calculate density score (0-100)
    # 0-3 hrs = 0-33, 3-5 hrs = 33-55, 5-7 hrs = 55-77, 7-8+ hrs = 77-100
    if meeting_hours <= 3:
        density_score = int((meeting_hours / 3) * 33)
    elif meeting_hours <= 5:
        density_score = 33 + int(((meeting_hours - 3) / 2) * 22)
    elif meeting_hours <= 7:
        density_score = 55 + int(((meeting_hours - 5) / 2) * 22)
    else:
        density_score = 77 + min(23, int(((meeting_hours - 7) / 1) * 23))

    # Find back-to-back stretches (no gap > 10 min)
    max_back_to_back_minutes = 0
    current_stretch_minutes = 0

    for i, event in enumerate(work_events):
        if i == 0:
            current_stretch_minutes = calculate_duration_minutes(event['start'], event['end'])
        else:
            prev_end = work_events[i-1]['end']
            gap_minutes = calculate_duration_minutes(prev_end, event['start'])

            if gap_minutes <= 10:
                # Continue back-to-back stretch
                current_stretch_minutes += calculate_duration_minutes(event['start'], event['end'])
            else:
                # Gap breaks the stretch
                max_back_to_back_minutes = max(max_back_to_back_minutes, current_stretch_minutes)
                current_stretch_minutes = calculate_duration_minutes(event['start'], event['end'])

    max_back_to_back_minutes = max(max_back_to_back_minutes, current_stretch_minutes)
    back_to_back_hours = max_back_to_back_minutes / 60

    # Find longest free gap
    gaps = []
    for i in range(len(work_events) - 1):
        gap_minutes = calculate_duration_minutes(work_events[i]['end'], work_events[i+1]['start'])
        gaps.append(gap_minutes)

    # Also check gap at start and end of day
    if work_events:
        start_gap = calculate_duration_minutes(work_start, work_events[0]['start'])
        end_gap = calculate_duration_minutes(work_events[-1]['end'], work_end)
        gaps.extend([start_gap, end_gap])

    longest_gap = max(gaps) if gaps else WORK_HOURS_TOTAL * 60

    # Determine if overload is triggered
    reasons = []
    triggered = False

    if meeting_hours >= 5:
        triggered = True
        reasons.append(f"{meeting_hours:.1f} hrs meetings ({meeting_density_pct}% of workday)")

    if back_to_back_hours >= 3:
        triggered = True
        reasons.append(f"Back-to-back for {back_to_back_hours:.1f} hrs")

    if longest_gap < 45:
        triggered = True
        reasons.append(f"Longest free gap is only {longest_gap} min")

    return {
        "triggered": triggered,
        "meeting_hours": round(meeting_hours, 1),
        "meeting_density_percentage": meeting_density_pct,
        "density_score": density_score,
        "back_to_back_hours": round(back_to_back_hours, 1),
        "longest_free_gap_minutes": longest_gap,
        "reasons": reasons
    }


def detect_energy_mismatch(
    events: List[Dict],
    wearable_data: Optional[Dict] = None,
    manual_energy: Optional[str] = None,
    manual_sleep: Optional[float] = None,
    user_timezone: str = "UTC"
) -> Dict:
    """
    Detect energy mismatch (low energy + heavy calendar).

    Args:
        events: Calendar events
        wearable_data: Oura/Fitbit data with readiness_score, sleep_duration_minutes
        manual_energy: "low", "medium", "high" (if no wearable)
        manual_sleep: Sleep hours (if no wearable)
        user_timezone: User's timezone

    Returns:
        {
            "triggered": bool,
            "energy_source": "wearable" | "manual",
            "readiness_score": int (0-100, if wearable),
            "sleep_hours": float,
            "mismatch_score": int (0-100),
            "heavy_blocks": List[Dict],
            "reasons": List[str]
        }
    """
    reasons = []
    triggered = False
    energy_source = "none"
    readiness_score = None
    sleep_hours = None
    mismatch_score = 0

    # Determine energy level
    if wearable_data:
        energy_source = "wearable"
        readiness_score = wearable_data.get("readiness_score")
        sleep_minutes = wearable_data.get("sleep_duration_minutes")
        sleep_hours = sleep_minutes / 60 if sleep_minutes else None

        if readiness_score is not None:
            # Inverse readiness as base mismatch
            energy_deficit = 100 - readiness_score
            mismatch_score = energy_deficit
        elif sleep_hours is not None:
            # Use sleep as proxy
            if sleep_hours < 6:
                mismatch_score = 75
            elif sleep_hours < 7:
                mismatch_score = 50
            else:
                mismatch_score = 25

    elif manual_energy or manual_sleep:
        energy_source = "manual"
        sleep_hours = manual_sleep

        if manual_energy == "low":
            mismatch_score = 75
        elif manual_energy == "medium":
            mismatch_score = 40
        else:  # high
            mismatch_score = 15

        # Adjust based on sleep if provided
        if manual_sleep and manual_sleep < 6:
            mismatch_score = max(mismatch_score, 70)

    # Find heavy meeting blocks (>90 min continuous or dense)
    heavy_blocks = []
    work_events = []

    for event in events:
        start = parse_time(event['start_time'], user_timezone)
        end = parse_time(event['end_time'], user_timezone)

        if is_within_work_hours(start):
            duration = calculate_duration_minutes(start, end)
            if duration >= 90:
                heavy_blocks.append({
                    "title": event.get('summary', 'Untitled'),
                    "start": start.strftime("%I:%M %p"),
                    "duration_minutes": duration
                })
            work_events.append({'start': start, 'end': end})

    # Check for dense meeting blocks (multiple meetings back-to-back = heavy)
    work_events.sort(key=lambda e: e['start'])
    continuous_minutes = 0
    block_start = None

    for i, event in enumerate(work_events):
        if i == 0:
            continuous_minutes = calculate_duration_minutes(event['start'], event['end'])
            block_start = event['start']
        else:
            prev_end = work_events[i-1]['end']
            gap = calculate_duration_minutes(prev_end, event['start'])

            if gap <= 10:
                continuous_minutes += calculate_duration_minutes(event['start'], event['end'])
            else:
                if continuous_minutes >= 90 and block_start:
                    heavy_blocks.append({
                        "title": f"Dense meeting block",
                        "start": block_start.strftime("%I:%M %p"),
                        "duration_minutes": continuous_minutes
                    })
                continuous_minutes = calculate_duration_minutes(event['start'], event['end'])
                block_start = event['start']

    # Check last block
    if continuous_minutes >= 90 and block_start:
        heavy_blocks.append({
            "title": f"Dense meeting block",
            "start": block_start.strftime("%I:%M %p"),
            "duration_minutes": continuous_minutes
        })

    # Amplify mismatch if heavy calendar
    total_meeting_hours = sum(
        calculate_duration_minutes(e['start'], e['end'])
        for e in work_events
    ) / 60

    if total_meeting_hours >= 5:
        mismatch_score = min(100, int(mismatch_score * 1.5))

    # Determine if triggered
    if energy_source != "none" and len(heavy_blocks) > 0:
        if readiness_score and readiness_score < 70:
            triggered = True
            reasons.append(f"{readiness_score}% readiness + {len(heavy_blocks)} heavy blocks")
        elif sleep_hours and sleep_hours < 6:
            triggered = True
            reasons.append(f"{sleep_hours:.1f} hrs sleep + {total_meeting_hours:.1f} hrs meetings")
        elif manual_energy == "low":
            triggered = True
            reasons.append(f"Low energy + {len(heavy_blocks)} heavy meeting blocks")

    return {
        "triggered": triggered,
        "energy_source": energy_source,
        "readiness_score": readiness_score,
        "sleep_hours": sleep_hours,
        "mismatch_score": int(mismatch_score),
        "heavy_blocks": heavy_blocks,
        "reasons": reasons
    }


def detect_no_breaks(events: List[Dict], user_timezone: str = "UTC") -> Dict:
    """
    Detect insufficient breaks (no 15-min gap in 4+ hour stretch).
    Distinguishes between lunch breaks and short breaks.

    Returns:
        {
            "triggered": bool,
            "expected_breaks": int,
            "actual_breaks": int,
            "has_lunch": bool,
            "break_deficit": int,
            "deficit_score": int (0-100),
            "longest_stretch_hours": float,
            "reasons": List[str]
        }
    """
    work_events = []

    for event in events:
        start = parse_time(event['start_time'], user_timezone)
        end = parse_time(event['end_time'], user_timezone)

        if is_within_work_hours(start):
            work_events.append({'start': start, 'end': end})

    work_events.sort(key=lambda e: e['start'])

    # Count actual breaks (gaps >= 15 min) and detect lunch
    actual_breaks = 0
    has_lunch = False

    for i in range(len(work_events) - 1):
        gap_start = work_events[i]['end']
        gap_end = work_events[i+1]['start']
        gap_minutes = calculate_duration_minutes(gap_start, gap_end)

        # Check if this gap is during lunch hours and long enough to be lunch
        gap_start_hour = gap_start.hour
        is_lunch_time = LUNCH_HOUR_START <= gap_start_hour < LUNCH_HOUR_END
        is_lunch_duration = LUNCH_BREAK_MIN <= gap_minutes <= LUNCH_BREAK_MAX

        if is_lunch_time and is_lunch_duration:
            has_lunch = True
        elif gap_minutes >= MIN_BREAK_DURATION:
            # Count as regular break (not lunch)
            actual_breaks += 1

    # Calculate break deficit
    break_deficit = max(0, EXPECTED_BREAKS - actual_breaks)
    deficit_score = int((break_deficit / EXPECTED_BREAKS) * 100)

    # Find longest continuous stretch without break
    max_stretch_minutes = 0
    current_stretch_start = None
    current_stretch_minutes = 0

    for i, event in enumerate(work_events):
        if i == 0:
            current_stretch_start = event['start']
            current_stretch_minutes = calculate_duration_minutes(event['start'], event['end'])
        else:
            prev_end = work_events[i-1]['end']
            gap = calculate_duration_minutes(prev_end, event['start'])

            if gap < MIN_BREAK_DURATION:
                # No break, continue stretch
                current_stretch_minutes = calculate_duration_minutes(current_stretch_start, event['end'])
            else:
                # Break found, reset stretch
                max_stretch_minutes = max(max_stretch_minutes, current_stretch_minutes)
                current_stretch_start = event['start']
                current_stretch_minutes = calculate_duration_minutes(event['start'], event['end'])

    max_stretch_minutes = max(max_stretch_minutes, current_stretch_minutes)
    longest_stretch_hours = max_stretch_minutes / 60

    # Determine if triggered (no 15-min break in 4+ hour stretch)
    reasons = []
    triggered = False

    if longest_stretch_hours >= 4:
        triggered = True
        reasons.append(f"{longest_stretch_hours:.1f} hrs straight, no 15-min break")

    if break_deficit >= 2:
        triggered = True
        reasons.append(f"Missing {break_deficit} breaks today")

    return {
        "triggered": triggered,
        "expected_breaks": EXPECTED_BREAKS,
        "actual_breaks": actual_breaks,
        "has_lunch": has_lunch,
        "break_deficit": break_deficit,
        "deficit_score": deficit_score,
        "longest_stretch_hours": round(longest_stretch_hours, 1),
        "reasons": reasons
    }


def detect_priority_no_space(
    events: List[Dict],
    priority: str,
    user_timezone: str = "UTC"
) -> Dict:
    """
    Detect if user's priority has no continuous 60-min slot available.

    Returns:
        {
            "triggered": bool,
            "longest_available_gap": int (minutes),
            "total_free_minutes": int,
            "reasons": List[str]
        }
    """
    work_start, work_end = get_work_hours_today(user_timezone)

    work_events = []
    for event in events:
        start = parse_time(event['start_time'], user_timezone)
        end = parse_time(event['end_time'], user_timezone)

        if is_within_work_hours(start) or is_within_work_hours(end):
            work_events.append({'start': start, 'end': end})

    work_events.sort(key=lambda e: e['start'])

    # Find all gaps
    gaps = []

    # Gap at start of day
    if work_events:
        start_gap = calculate_duration_minutes(work_start, work_events[0]['start'])
        if start_gap > 0:
            gaps.append(start_gap)

        # Gaps between meetings
        for i in range(len(work_events) - 1):
            gap = calculate_duration_minutes(work_events[i]['end'], work_events[i+1]['start'])
            if gap > 0:
                gaps.append(gap)

        # Gap at end of day
        end_gap = calculate_duration_minutes(work_events[-1]['end'], work_end)
        if end_gap > 0:
            gaps.append(end_gap)
    else:
        # No meetings = full day free
        gaps.append(WORK_HOURS_TOTAL * 60)

    longest_gap = max(gaps) if gaps else 0
    total_free = sum(gaps)

    # Determine if triggered
    triggered = longest_gap < MIN_FOCUS_BLOCK
    reasons = []

    if triggered:
        if longest_gap == 0:
            reasons.append("0 minutes free for deep work today")
        else:
            reasons.append(f"Your priority needs {MIN_FOCUS_BLOCK} min. You have {longest_gap}.")

    return {
        "triggered": triggered,
        "longest_available_gap": longest_gap,
        "total_free_minutes": total_free,
        "reasons": reasons
    }


# ═══════════════════════════════════════════════════════════════════════
# DRAIN PERCENTAGE CALCULATION
# ═══════════════════════════════════════════════════════════════════════

def calculate_drain_percentage(
    overload_result: Dict,
    energy_result: Dict,
    breaks_result: Dict
) -> int:
    """
    Calculate overall drain percentage (0-100).
    
    Formula: weighted combination of:
    - Meeting density score (40%)
    - Energy mismatch score (35%)
    - Break deficit score (25%)
    """
    density_score = overload_result.get("density_score", 0)
    energy_score = energy_result.get("mismatch_score", 0)
    break_score = breaks_result.get("deficit_score", 0)
    
    drain = int(
        density_score * WEIGHT_MEETING_DENSITY +
        energy_score * WEIGHT_ENERGY_MISMATCH +
        break_score * WEIGHT_BREAK_DEFICIT
    )
    
    return min(100, max(0, drain))


# ═══════════════════════════════════════════════════════════════════════
# TIER CLASSIFICATION
# ═══════════════════════════════════════════════════════════════════════

def classify_tier(
    overload: Dict,
    energy: Dict,
    breaks: Dict,
    priority: Dict
) -> Tuple[int, List[str]]:
    """
    Classify burnout tier (0-3) based on triggered signals.

    Tier 0 (Critical Energy): User is too drained to work - need rest, not optimization
    Tier 1 (Light): Priority has no space (alone)
    Tier 2 (Medium): Any ONE of: overload, energy mismatch, no breaks
    Tier 3 (Strong): Any TWO+ of: overload, energy mismatch, no breaks

    Returns:
        (tier_number, list_of_triggered_signals)
    """
    signals = []

    # Check for Tier 0: Critically low energy (rest needed, don't optimize)
    readiness = energy.get("readiness_score")
    sleep_hours = energy.get("sleep_hours")
    energy_source = energy.get("energy_source")

    is_critically_low_energy = False

    # Wearable shows critical readiness
    if readiness is not None and readiness < 40:
        is_critically_low_energy = True
        signals.append("critical_energy")

    # OR very low sleep (< 5 hrs) with explicit low energy
    elif sleep_hours is not None and sleep_hours < 5:
        # If from wearable or manual low energy
        if energy_source == "wearable" or energy.get("mismatch_score", 0) >= 75:
            is_critically_low_energy = True
            signals.append("critical_energy")

    # Tier 0: Too drained to work effectively - suggest rest
    if is_critically_low_energy:
        return 0, signals

    # Continue with normal tier classification
    if overload.get("triggered"):
        signals.append("overload")
    if energy.get("triggered"):
        signals.append("energy_mismatch")
    if breaks.get("triggered"):
        signals.append("no_breaks")
    if priority.get("triggered"):
        signals.append("priority_no_space")

    # Tier 3: 2+ signals (excluding priority-only)
    non_priority_signals = [s for s in signals if s != "priority_no_space"]
    if len(non_priority_signals) >= 2:
        return 3, signals

    # Tier 2: 1 signal (overload, energy, or breaks)
    if len(non_priority_signals) >= 1:
        return 2, signals

    # Tier 1: Only priority has no space
    if "priority_no_space" in signals:
        return 1, signals

    # No intervention needed
    return None, signals


# ═══════════════════════════════════════════════════════════════════════
# FOCUS BLOCK FINDER
# ═══════════════════════════════════════════════════════════════════════

def find_focus_block(
    events: List[Dict],
    user_timezone: str = "UTC",
    preferred_duration: int = IDEAL_FOCUS_BLOCK
) -> Optional[Dict]:
    """
    Find best time slot for focus block.

    Priority:
    1. Prime focus hours (10 AM - 2 PM)
    2. Morning (9-10 AM)
    3. Afternoon (2-5 PM)

    Returns:
        {
            "start_time": datetime,
            "end_time": datetime,
            "duration_minutes": int,
            "time_slot": str (e.g., "10:30 AM - 12:00 PM"),
            "reasoning": str
        }
    """
    print(f"[FocusBlock] Finding focus block for {len(events)} events in timezone {user_timezone}")
    work_start, work_end = get_work_hours_today(user_timezone)
    print(f"[FocusBlock] Work hours: {work_start} - {work_end}")
    
    work_events = []
    for event in events:
        start = parse_time(event['start_time'], user_timezone)
        end = parse_time(event['end_time'], user_timezone)

        if is_within_work_hours(start) or is_within_work_hours(end):
            work_events.append({'start': start, 'end': end})
            print(f"[FocusBlock] Event: {start.strftime('%I:%M %p')} - {end.strftime('%I:%M %p')}")

    work_events.sort(key=lambda e: e['start'])
    print(f"[FocusBlock] Total work events: {len(work_events)}")
    
    # Find all available gaps with their score
    gaps = []
    
    # Gap at start of day
    if work_events:
        gap_start = work_start
        gap_end = work_events[0]['start']
        gap_duration = calculate_duration_minutes(gap_start, gap_end)

        print(f"[FocusBlock] Gap at start: {gap_start.strftime('%I:%M %p')} - {gap_end.strftime('%I:%M %p')} = {gap_duration} min (MIN_FOCUS_BLOCK={MIN_FOCUS_BLOCK})")
        if gap_duration >= MIN_FOCUS_BLOCK:
            # Skip lunch time gaps
            if is_lunch_time(gap_start, gap_end):
                print(f"[FocusBlock] ✗ Skipped lunch time gap")
            else:
                gaps.append({
                    'start': gap_start,
                    'end': gap_end,
                    'duration': gap_duration,
                    'score': score_time_slot(gap_start)
                })
                print(f"[FocusBlock] ✓ Added start gap")
        
        # Gaps between meetings
        for i in range(len(work_events) - 1):
            gap_start = work_events[i]['end']
            gap_end = work_events[i+1]['start']
            gap_duration = calculate_duration_minutes(gap_start, gap_end)

            print(f"[FocusBlock] Gap between meetings: {gap_start.strftime('%I:%M %p')} - {gap_end.strftime('%I:%M %p')} = {gap_duration} min")
            if gap_duration >= MIN_FOCUS_BLOCK:
                # Skip lunch time gaps
                if is_lunch_time(gap_start, gap_end):
                    print(f"[FocusBlock] ✗ Skipped lunch time gap")
                else:
                    gaps.append({
                        'start': gap_start,
                        'end': gap_end,
                        'duration': gap_duration,
                        'score': score_time_slot(gap_start)
                    })
                    print(f"[FocusBlock] ✓ Added gap {i+1}")
        
        # Gap at end of day
        gap_start = work_events[-1]['end']
        gap_end = work_end
        gap_duration = calculate_duration_minutes(gap_start, gap_end)

        print(f"[FocusBlock] Gap at end: {gap_start.strftime('%I:%M %p')} - {gap_end.strftime('%I:%M %p')} = {gap_duration} min")
        if gap_duration >= MIN_FOCUS_BLOCK:
            # Skip lunch time gaps
            if is_lunch_time(gap_start, gap_end):
                print(f"[FocusBlock] ✗ Skipped lunch time gap")
            else:
                gaps.append({
                    'start': gap_start,
                    'end': gap_end,
                    'duration': gap_duration,
                    'score': score_time_slot(gap_start)
                })
                print(f"[FocusBlock] ✓ Added end gap")
    else:
        # Full day available
        gaps.append({
            'start': work_start,
            'end': work_end,
            'duration': WORK_HOURS_TOTAL * 60,
            'score': score_time_slot(work_start)
        })
    
    if not gaps:
        print(f"[FocusBlock] No gaps found - returning None")
        return None

    print(f"[FocusBlock] Found {len(gaps)} gaps")

    # Sort by score (highest first), then by duration
    gaps.sort(key=lambda g: (g['score'], g['duration']), reverse=True)

    best_gap = gaps[0]
    print(f"[FocusBlock] Best gap: {best_gap['start']} - {best_gap['end']} ({best_gap['duration']} min, score {best_gap['score']})")

    # Create focus block (use preferred duration if gap is large enough)
    block_duration = min(preferred_duration, best_gap['duration'])
    block_start = best_gap['start']
    block_end = block_start + timedelta(minutes=block_duration)

    # Format time slot
    time_slot = f"{block_start.strftime('%I:%M %p')} - {block_end.strftime('%I:%M %p')}"

    # Generate reasoning
    reasoning = get_focus_block_reasoning(block_start, block_duration)

    result = {
        "start_time": block_start.isoformat(),
        "end_time": block_end.isoformat(),
        "duration_minutes": block_duration,
        "time_slot": time_slot,
        "reasoning": reasoning
    }
    print(f"[FocusBlock] Created focus block: {time_slot}")
    return result


def is_lunch_time(start_time: datetime, end_time: datetime) -> bool:
    """
    Check if a time slot falls during typical lunch hours.

    Lunch hours: 11 AM - 12 PM or 12 PM - 1 PM
    Returns True if the slot overlaps with lunch time.
    """
    start_hour = start_time.hour
    end_hour = end_time.hour

    # Check if slot overlaps with 11 AM - 1 PM
    # Slot is lunch if it starts at 11 AM or 12 PM (noon)
    return start_hour == 11 or start_hour == 12


def score_time_slot(start_time: datetime) -> int:
    """
    Score a time slot based on how good it is for focus work.

    Prime focus hours (10 AM - 2 PM): 100
    Morning (9-10 AM): 80
    Afternoon (2-5 PM): 60
    """
    hour = start_time.hour

    if PRIME_FOCUS_START <= hour < PRIME_FOCUS_END:
        return 100  # Best time
    elif WORK_START_HOUR <= hour < PRIME_FOCUS_START:
        return 80   # Morning (good)
    else:
        return 60   # Afternoon (acceptable)


def get_focus_block_reasoning(start_time: datetime, duration: int) -> str:
    """Generate reasoning text for focus block placement."""
    hour = start_time.hour
    
    if PRIME_FOCUS_START <= hour < PRIME_FOCUS_END:
        return "Best gap in work hours for deep work"
    elif WORK_START_HOUR <= hour < PRIME_FOCUS_START:
        return "Early morning slot for focused work"
    else:
        return "Afternoon slot for wrapping up priority"


# ═══════════════════════════════════════════════════════════════════════
# MEETING CHANGE SUGGESTER
# ═══════════════════════════════════════════════════════════════════════

def suggest_meeting_changes(
    events: List[Dict],
    focus_block: Optional[Dict],
    user_timezone: str = "UTC",
    max_suggestions: int = 2  # Default, will adjust based on meeting count
) -> List[Dict]:
    """
    Suggest which meetings to move/decline (Tier 3 only).

    NEW LOGIC:
    1. Find meetings that overlap focus block (MUST move)
    2. Find additional meetings AFTER focus block to reduce density
    3. Don't touch meetings BEFORE focus block
    4. Adjust max_suggestions based on total meeting count:
       - 10+ meetings: suggest 3 moves
       - 8-9 meetings: suggest 2 moves
       - <8 meetings: suggest 2 moves
    5. Generate EXACT times for moves (e.g., "Today 3:00 PM", "Monday 9:00 AM")

    Scoring logic for additional meeting:
    - Not organizer: +4
    - Short (<=60 min): +3
    - Low priority keywords: +4
    - Microsoft event: +2

    Returns list of suggested changes sorted by move_score.
    """
    overlapping_suggestions = []
    after_focus_candidates = []

    print(f"[MeetingChanges] Analyzing {len(events)} events for possible moves")

    # Adjust max_suggestions based on meeting density
    meeting_count = len(events)
    if meeting_count >= 10:
        max_suggestions = 3  # Aggressive reduction for 10+ meetings
        print(f"[MeetingChanges] High density ({meeting_count} meetings) - increasing to {max_suggestions} suggestions")
    else:
        max_suggestions = 2  # Standard for normal days
        print(f"[MeetingChanges] Normal density ({meeting_count} meetings) - using {max_suggestions} suggestions")

    if not focus_block:
        print("[MeetingChanges] No focus block provided, skipping suggestions")
        return []

    tz = pytz.timezone(user_timezone)
    focus_start = parse_time(focus_block['start_time'], user_timezone)
    focus_end = parse_time(focus_block['end_time'], user_timezone)
    print(f"[MeetingChanges] Focus block: {focus_start.strftime('%I:%M %p')} - {focus_end.strftime('%I:%M %p')}")

    # FIRST PASS: Identify which meetings will be moved (to exclude from conflict checks)
    meetings_to_move = set()

    for event in events:
        title = event.get('summary', 'Untitled')
        start = parse_time(event['start_time'], user_timezone)
        end = parse_time(event['end_time'], user_timezone)

        # Skip if non-negotiable
        if is_non_negotiable(title):
            continue

        is_organizer = event.get('is_organizer', False)
        event_source = event.get('source', 'unknown')
        duration = calculate_duration_minutes(start, end)

        # Check for overlap with focus block
        overlaps = start < focus_end and end > focus_start

        if overlaps:
            # MUST move - overlaps focus block
            meetings_to_move.add(title)
        elif start >= focus_end:
            # Score for moveability
            score = 0
            if not is_organizer:
                score += 4
            if duration <= 60:
                score += 3
            if is_low_priority(title):
                score += 4
            if event_source == 'microsoft':
                score += 2

            hour = start.hour
            if hour >= 17:
                score += 5
            elif hour >= 15:
                score += 3
            elif hour >= 13:
                score += 2

            if score >= 8:
                # Good candidate to move
                meetings_to_move.add(title)

    print(f"[MeetingChanges] Identified {len(meetings_to_move)} meetings to move: {meetings_to_move}")

    # SECOND PASS: Generate move suggestions, excluding meetings-to-move from conflicts
    suggested_times = []

    for event in events:
        title = event.get('summary', 'Untitled')
        start = parse_time(event['start_time'], user_timezone)
        end = parse_time(event['end_time'], user_timezone)
        duration = calculate_duration_minutes(start, end)

        # Skip if not in move list
        if title not in meetings_to_move:
            continue

        is_organizer = event.get('is_organizer', False)
        event_source = event.get('source', 'unknown')

        # Check for overlap with focus block
        overlaps = start < focus_end and end > focus_start

        if overlaps:
            # This meeting MUST move (overlaps with focus block)
            print(f"[MeetingChanges] '{title}' OVERLAPS focus block - MUST move")
            print(f"  Meeting: {start.strftime('%I:%M %p')} - {end.strftime('%I:%M %p')}")

            suggestion_text = get_move_suggestion(start, duration, title, tz, suggested_times, focus_end, events, meetings_to_move)
            suggested_times.append(suggestion_text)

            overlapping_suggestions.append({
                "meeting": title,
                "duration_minutes": duration,
                "current_time": f"{start.strftime('%I:%M %p')} - {end.strftime('%I:%M %p')}",
                "suggestion": suggestion_text,
                "reason": "conflicts with focus block",
                "move_score": 100  # Highest priority
            })

        elif start >= focus_end:
            # Meeting is AFTER focus block - candidate for additional move
            # Score this meeting for moveability
            score = 0

            if not is_organizer:
                score += 4
            if duration <= 60:
                score += 3
            if is_low_priority(title):
                score += 4
            if event_source == 'microsoft':
                score += 2

            # BONUS: Prefer later-in-day meetings (reduces evening load)
            hour = start.hour
            if hour >= 17:  # 5 PM or later
                score += 5  # Strong preference for evening
                print(f"  [+5 bonus] Evening meeting ({hour}:00)")
            elif hour >= 15:  # 3 PM or later
                score += 3
                print(f"  [+3 bonus] Afternoon meeting ({hour}:00)")
            elif hour >= 13:  # 1 PM or later
                score += 2
                print(f"  [+2 bonus] Early afternoon ({hour}:00)")

            print(f"[MeetingChanges] '{title}' after focus block, score={score}")
            suggestion_text = get_move_suggestion(start, duration, title, tz, suggested_times, focus_end, events, meetings_to_move)
            suggested_times.append(suggestion_text)

            after_focus_candidates.append({
                "meeting": title,
                "duration_minutes": duration,
                "current_time": f"{start.strftime('%I:%M %p')} - {end.strftime('%I:%M %p')}",
                "suggestion": suggestion_text,
                "reason": "reduces calendar density",
                "move_score": score
            })

    # Combine: overlapping meetings + additional after-focus candidates
    final_suggestions = overlapping_suggestions

    if after_focus_candidates and len(overlapping_suggestions) < max_suggestions:
        # Sort after-focus candidates by score and take top N to fill up to max_suggestions
        after_focus_candidates.sort(key=lambda s: s['move_score'], reverse=True)
        additional_count = max_suggestions - len(overlapping_suggestions)
        final_suggestions.extend(after_focus_candidates[:additional_count])
        print(f"[MeetingChanges] Added {min(additional_count, len(after_focus_candidates))} additional meetings to reduce density")

    print(f"[MeetingChanges] Final suggestions: {len(final_suggestions)} meetings")
    return final_suggestions


def get_next_business_day(from_date: datetime.date) -> datetime.date:
    """
    Get the next business day (Monday-Friday), skipping weekends.

    Args:
        from_date: Starting date

    Returns:
        Next business day
    """
    next_day = from_date + timedelta(days=1)
    # If tomorrow is Saturday (5), move to Monday (+2 days)
    # If tomorrow is Sunday (6), move to Monday (+1 day)
    while next_day.weekday() >= 5:  # 5=Saturday, 6=Sunday
        next_day += timedelta(days=1)
    return next_day


def get_move_suggestion(start: datetime, duration: int, title: str, tz: pytz.timezone,
                        suggested_times: List[str], focus_end: datetime, all_events: List[Dict],
                        meetings_to_move: set) -> str:
    """
    Generate EXACT move time based on meeting time and work hours constraints.

    Rules:
    - Never move past 5 PM on same day
    - If can't fit before 5 PM, move to next business day 9:00 AM
    - Skip weekends - move to Monday if needed
    - Space multiple next-day moves 30 min apart
    - Check for conflicts with existing meetings (excluding the one being moved and other meetings-to-move)
    - Return exact times like "Today 3:00 PM" or "Monday 9:00 AM"
    """
    def has_conflict(proposed_time: datetime, duration_min: int) -> bool:
        """Check if proposed time conflicts with existing events (excluding meetings being moved)"""
        proposed_end = proposed_time + timedelta(minutes=duration_min)
        print(f"[Conflict Check] Checking {proposed_time.strftime('%I:%M %p')} for '{title}'")

        for event in all_events:
            evt_title = event.get('summary', 'Untitled')
            evt_start = parse_time(event['start_time'], tz.zone)
            evt_end = parse_time(event['end_time'], tz.zone)

            # Skip the meeting we're trying to move (compare by title and approximate time)
            time_diff = abs((evt_start - start).total_seconds())
            if evt_title == title and time_diff < 60:  # Within 1 minute
                print(f"  Skipping self: {evt_title}")
                continue

            # Skip Focus Block
            if 'Focus Block' in evt_title:
                continue

            # Skip other meetings that are also being moved
            if evt_title in meetings_to_move:
                print(f"  Skipping (also being moved): {evt_title}")
                continue

            # Check overlap: new meeting starts before event ends AND ends after event starts
            if proposed_time < evt_end and proposed_end > evt_start:
                print(f"  ✗ CONFLICT with '{evt_title}' at {evt_start.strftime('%I:%M %p')}")
                return True

        print(f"  ✓ No conflicts found")
        return False

    hour = start.hour
    today = start.date()

    # Get next business day (skipping weekends)
    next_business_day = get_next_business_day(today)

    # Count how many meetings already moving to next business day
    tomorrow_count = sum(1 for s in suggested_times if any(day in s for day in ["Tomorrow", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]))

    # Late night meetings (5 PM or later) - must move to next business day
    if hour >= END_OF_WORK_DAY:
        # Calculate next business day slot (9 AM + 30 min intervals, skip lunch 12-1 PM)
        next_day_time = tz.localize(datetime.combine(next_business_day, time(9, 0)))
        for _ in range(tomorrow_count):
            next_day_time += timedelta(minutes=30)
            # Skip lunch hour (12:00 PM - 1:00 PM)
            while next_day_time.hour == 12:
                next_day_time += timedelta(minutes=30)
        day_name = next_day_time.strftime('%A')  # Monday, Tuesday, etc.
        return f"{day_name} {next_day_time.strftime('%I:%M %p')}"

    # If in prime hours (10 AM - 2 PM) - try to move to afternoon
    if PRIME_FOCUS_START <= hour < PRIME_FOCUS_END:
        # Try afternoon slots: 2:00, 2:30, 3:00, 3:30, 4:00, 4:30 PM
        for hour_offset in [14, 14.5, 15, 15.5, 16, 16.5]:
            hour_int = int(hour_offset)
            minute_int = 30 if hour_offset % 1 else 0
            afternoon_time = tz.localize(datetime.combine(today, time(hour_int, minute_int)))

            # Check if slot + meeting duration fits before 5 PM
            meeting_end_hour = hour_offset + (duration / 60)

            if meeting_end_hour <= END_OF_WORK_DAY:
                afternoon_str = f"Today {afternoon_time.strftime('%I:%M %p')}"

                # Check if already suggested or conflicts with existing meeting
                if afternoon_str not in suggested_times and not has_conflict(afternoon_time, duration):
                    return afternoon_str

        # Can't fit today - move to next business day
        next_day_time = tz.localize(datetime.combine(next_business_day, time(9, 0)))
        for _ in range(tomorrow_count):
            next_day_time += timedelta(minutes=30)
            # Skip lunch hour (12:00 PM - 1:00 PM)
            while next_day_time.hour == 12:
                next_day_time += timedelta(minutes=30)
        day_name = next_day_time.strftime('%A')  # Monday, Tuesday, etc.
        return f"{day_name} {next_day_time.strftime('%I:%M %p')}"

    # Already in afternoon or evening - move to next business day
    next_day_time = tz.localize(datetime.combine(next_business_day, time(9, 0)))
    for _ in range(tomorrow_count):
        next_day_time += timedelta(minutes=30)
        # Skip lunch hour (12:00 PM - 1:00 PM)
        while next_day_time.hour == 12:
            next_day_time += timedelta(minutes=30)
    day_name = next_day_time.strftime('%A')  # Monday, Tuesday, etc.
    return f"{day_name} {next_day_time.strftime('%I:%M %p')}"


# ═══════════════════════════════════════════════════════════════════════
# INTERVENTION MESSAGE GENERATOR
# ═══════════════════════════════════════════════════════════════════════

def generate_intervention_message(
    tier: int,
    drain_percentage: int,
    signals: List[str],
    overload: Dict,
    energy: Dict,
    breaks: Dict,
    priority: Dict
) -> Dict:
    """
    Generate punchy, consequence-driven intervention messages.

    Returns:
        {
            "headline": str,
            "consequence": str (optional),
            "action": str,
            "before": str (optional),
            "after": str (optional)
        }
    """
    messages = {}

    if tier == 0:
        # Tier 0: Critical energy - rest needed, not optimization
        sleep_hours = energy.get("sleep_hours")

        # Build headline based on what's available (NEVER show internal readiness %)
        if sleep_hours and sleep_hours < 5:
            messages["headline"] = f"You slept {sleep_hours:.1f} hours — this work will fail right now."
        else:
            messages["headline"] = "You're low energy — this work will fail right now."

        messages["action"] = "Do something lighter or take a reset."

    elif tier == 1:
        # Tier 1: Just priority issue
        longest_gap = priority.get("longest_available_gap", 0)
        messages["headline"] = f"Your priority needs {MIN_FOCUS_BLOCK} min."
        messages["consequence"] = f"You have {longest_gap} min free."
    
    elif tier == 2:
        # Tier 2: Medium severity
        meeting_hours = overload.get("meeting_hours", 0)
        meeting_count = overload.get("meeting_count", 0)
        sleep_hours = energy.get("sleep_hours")
        readiness = energy.get("readiness_score")  # Keep for internal use
        longest_stretch = breaks.get("longest_stretch_hours", 0)
        has_lunch = breaks.get("has_lunch", False)

        # Build problem + consequence
        if "overload" in signals:
            if meeting_count >= 8:
                messages["headline"] = f"{meeting_count} meetings back-to-back."
                messages["consequence"] = "Your brain needs space to think."
            else:
                messages["headline"] = "You won't get meaningful work done like this."
                messages["consequence"] = "You have time, but no focus space."

        elif "energy_mismatch" in signals:
            if sleep_hours and sleep_hours < 6:
                messages["headline"] = f"You slept {sleep_hours:.1f} hours with {meeting_hours:.1f} hours of meetings."
                messages["consequence"] = "You'll crash before lunch."
            else:
                messages["headline"] = "You're low energy with a heavy schedule."
                messages["consequence"] = "You won't be effective like this."

        elif "no_breaks" in signals:
            messages["headline"] = "You have no real breaks today."
            messages["consequence"] = "You'll be drained by afternoon."

        else:
            messages["headline"] = "Today might get exhausting."
            messages["consequence"] = "Protect some focus time."

        # Action is the same for all Tier 2
        # Will be filled in later with actual focus block time
    
    elif tier == 3:
        # Tier 3: Strong intervention (multiple signals)
        meeting_hours = overload.get("meeting_hours", 0)
        free_minutes = priority.get("total_free_minutes", 0)
        sleep_hours = energy.get("sleep_hours")
        readiness = energy.get("readiness_score")  # Keep for internal use
        has_lunch = breaks.get("has_lunch", False)

        # Build problem statement (fact-based)
        problem_parts = []

        # Lead with energy if it's an issue (NEVER show internal readiness %)
        if "energy_mismatch" in signals:
            if sleep_hours and sleep_hours < 6:
                problem_parts.append(f"slept {sleep_hours:.1f} hours")
            else:
                problem_parts.append("low energy")

        # Add overload if present
        if "overload" in signals:
            problem_parts.append(f"{meeting_hours:.1f} hours of meetings")

        # Construct headline (CONSEQUENCE-DRIVEN, not stats)
        if "priority_no_space" in signals:
            messages["headline"] = "You can't get meaningful work done like this."
            messages["consequence"] = "You have time, but no focus space."
        elif "energy_mismatch" in signals and "overload" in signals:
            messages["headline"] = "You won't get meaningful work done like this."
            messages["consequence"] = "You have time, but no focus space."
        elif "no_breaks" in signals:
            messages["headline"] = "You'll be drained by afternoon."
            messages["consequence"] = "No breaks between meetings."
        else:
            messages["headline"] = "Your day is overloaded."
            messages["consequence"] = "Too many meetings, not enough focus time."

        # Before/After for Tier 3 (optional, can be used by UI)
        free_hours = free_minutes / 60
        messages["before"] = f"{meeting_hours:.1f} hrs meetings, {free_hours:.1f} hrs free, 0 focus time"

        # Estimate after (assume we free 2 hours by moving meetings)
        estimated_after_meetings = max(0, meeting_hours - 2)
        estimated_after_free = free_hours + 2
        messages["after"] = f"{estimated_after_meetings:.1f} hrs meetings, {estimated_after_free:.1f} hrs free, 60 min for your priority"
    
    else:
        # No intervention needed (tier is None)
        messages["headline"] = "Your day looks balanced"
        messages["action"] = "Keep it that way"

    return messages


# ═══════════════════════════════════════════════════════════════════════
# MAIN BURNOUT DETECTION FUNCTION
# ═══════════════════════════════════════════════════════════════════════

def detect_burnout(
    events: List[Dict],
    priority: str,
    wearable_data: Optional[Dict] = None,
    manual_energy: Optional[str] = None,
    manual_sleep: Optional[float] = None,
    user_timezone: str = "UTC"
) -> Dict:
    """
    Main burnout detection function.
    
    Args:
        events: List of calendar events (personal + work merged)
        priority: User's stated priority for today
        wearable_data: Oura/Fitbit data (readiness_score, sleep_duration_minutes, etc.)
        manual_energy: "low", "medium", "high" (if no wearable)
        manual_sleep: Sleep hours (if no wearable)
        user_timezone: User's timezone string (e.g., "America/Los_Angeles")
    
    Returns:
        {
            "tier": int (0-3),
            "drain_percentage": int (0-100),
            "signals_detected": List[str],
            "messages": {
                "headline": str,
                "before": str (optional),
                "after": str (optional),
                "insight": str (optional),
                "action": str
            },
            "focus_block": {
                "start_time": str (ISO),
                "end_time": str (ISO),
                "duration_minutes": int,
                "time_slot": str,
                "reasoning": str
            } (optional),
            "suggested_changes": List[Dict] (Tier 3 only),
            "details": {
                "overload": Dict,
                "energy_mismatch": Dict,
                "no_breaks": Dict,
                "priority_no_space": Dict
            }
        }
    """
    # Run all signal detections
    overload = detect_overload(events, user_timezone)
    energy = detect_energy_mismatch(events, wearable_data, manual_energy, manual_sleep, user_timezone)
    breaks = detect_no_breaks(events, user_timezone)
    priority_space = detect_priority_no_space(events, priority, user_timezone)
    
    # Calculate drain percentage
    drain_pct = calculate_drain_percentage(overload, energy, breaks)
    
    # Classify tier
    tier, signals = classify_tier(overload, energy, breaks, priority_space)
    
    # Find focus block (if needed)
    # Tier 0: No focus block (user needs rest, not optimization)
    # Tier 1-3: Create focus block
    focus_block = None
    suggested_changes = []

    if tier is not None and tier >= 1:
        focus_block = find_focus_block(events, user_timezone)
        print(f"[Burnout] Natural focus block: {focus_block}")

        # If no natural gaps exist AND it's Tier 3, create synthetic focus block by moving meetings
        if not focus_block and tier == 3:
            print(f"[Burnout] No natural gaps - analyzing meetings to create space")

            # Create a synthetic focus block in prime hours (10 AM - 11:00 AM) FIRST
            tz = pytz.timezone(user_timezone)
            today = datetime.now(tz).date()
            focus_start = tz.localize(datetime.combine(today, time(10, 0)))
            focus_end = tz.localize(datetime.combine(today, time(11, 0)))

            focus_block = {
                "start_time": focus_start.isoformat(),
                "end_time": focus_end.isoformat(),
                "duration_minutes": 60,
                "time_slot": f"{focus_start.strftime('%I:%M %p')} - {focus_end.strftime('%I:%M %p')}",
                "reasoning": "Best focus window based on your calendar"
            }
            print(f"[Burnout] Created synthetic focus block: {focus_block['time_slot']}")

            # NOW find meetings that conflict with this focus block
            suggested_changes = suggest_meeting_changes(events, focus_block, user_timezone)

            # Update reasoning with how many meetings we'll move
            if suggested_changes:
                focus_block["reasoning"] = f"Created by moving {len(suggested_changes)} meetings"

        # EVEN if there's a natural gap, check for any overlapping meetings
        # This ensures we show which meetings need to be moved for all tiers
        elif focus_block:
            print(f"[Burnout] Checking for meetings overlapping with natural gap: {focus_block['time_slot']}")
            suggested_changes = suggest_meeting_changes(events, focus_block, user_timezone)
            if suggested_changes:
                print(f"[Burnout] Found {len(suggested_changes)} meetings overlapping with focus block")
            else:
                print(f"[Burnout] No meetings overlap - natural gap is clear")

    # Generate intervention messages
    messages = generate_intervention_message(
        tier, drain_pct, signals,
        overload, energy, breaks, priority_space
    )

    # Add action field with focus block timing (if available)
    if focus_block and tier != 0:
        time_slot = focus_block.get("time_slot")
        duration = focus_block.get("duration_minutes")

        if tier == 3:
            messages["action"] = f"Fix this: free {duration} min at {time_slot.split(' - ')[0]}"
        elif tier == 2:
            messages["action"] = f"Fix this: free {duration} min at {time_slot.split(' - ')[0]}"
        elif tier == 1:
            messages["action"] = f"Fix this: free {duration} min at {time_slot.split(' - ')[0]}"

    # NOTE: suggested_changes already populated at line 1217 for Tier 3 synthetic focus blocks
    # No need to call suggest_meeting_changes again here

    # Calculate execution risk
    if tier == 3 or drain_pct >= 70:
        execution_risk = "HIGH"
    elif tier == 2 or drain_pct >= 40:
        execution_risk = "MEDIUM"
    else:
        execution_risk = "LOW"

    # Build response
    result = {
        "tier": tier,
        "drain_percentage": drain_pct,
        "execution_risk": execution_risk,
        "signals_detected": signals,
        "messages": messages,
        "details": {
            "overload": overload,
            "energy_mismatch": energy,
            "no_breaks": breaks,
            "priority_no_space": priority_space
        }
    }
    
    if focus_block:
        result["focus_block"] = focus_block
    
    if suggested_changes:
        result["suggested_changes"] = suggested_changes
    
    return result
