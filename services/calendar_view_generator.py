"""
Optimized Calendar View Generator
Creates human-readable calendar view for manual copy-paste.
"""

from datetime import datetime
from typing import List, Dict, Optional
import pytz


def generate_optimized_view(
    burnout_result: Dict,
    user_timezone: str = "UTC"
) -> Dict:
    """
    Generate optimized calendar view showing before/after comparison.

    Args:
        burnout_result: Full burnout detection result
        user_timezone: User's timezone

    Returns:
        {
            "timeline": List[str],  # Text lines for display
            "instructions": List[str],  # Step-by-step what to do
            "summary": str  # One-line summary
        }
    """
    messages = burnout_result.get("messages", {})
    focus_block = burnout_result.get("focus_block")
    suggested_changes = burnout_result.get("suggested_changes", [])
    tier = burnout_result.get("tier", 0)

    timeline = []
    instructions = []

    # Header
    timeline.append("═" * 60)
    timeline.append("OPTIMIZED SCHEDULE")
    timeline.append("═" * 60)
    timeline.append("")

    # Summary
    headline = messages.get("headline", "Your day looks manageable")
    timeline.append(f"📊 {headline}")
    timeline.append("")

    # Before/After (Tier 3 only)
    if tier == 3:
        before = messages.get("before")
        after = messages.get("after")

        if before and after:
            timeline.append("BEFORE:")
            timeline.append(f"  {before}")
            timeline.append("")
            timeline.append("AFTER:")
            timeline.append(f"  {after}")
            timeline.append("")

    # Focus Block
    if focus_block:
        timeline.append("─" * 60)
        timeline.append("🎯 FOCUS BLOCK TO ADD")
        timeline.append("─" * 60)
        timeline.append(f"  Time: {focus_block['time_slot']}")
        timeline.append(f"  Duration: {focus_block['duration_minutes']} min")
        timeline.append(f"  Purpose: Protected time for your priority")
        timeline.append(f"  Reason: {focus_block['reasoning']}")
        timeline.append("")

        instructions.append(f"1. Block {focus_block['time_slot']} on your calendar")
        instructions.append("   - Title: \"🎯 Focus Block - Priority Work\"")
        instructions.append("   - Mark as busy")
        instructions.append("")

    # Suggested Meeting Changes (Tier 3)
    if suggested_changes:
        timeline.append("─" * 60)
        timeline.append("📅 MEETINGS TO MOVE")
        timeline.append("─" * 60)

        for i, change in enumerate(suggested_changes, 1):
            timeline.append(f"{i}. {change['meeting']}")
            timeline.append(f"   Current: {change['current_time']}")
            timeline.append(f"   Suggestion: {change['suggestion']}")
            timeline.append(f"   Why: {change['reason']}")
            timeline.append("")

            instructions.append(f"{len(instructions) // 2 + 1}. Move \"{change['meeting']}\"")
            instructions.append(f"   - From: {change['current_time']}")
            instructions.append(f"   - {change['suggestion']}")
            instructions.append("")

    # Action Summary
    action = messages.get("action", "Stay balanced")
    timeline.append("─" * 60)
    timeline.append(f"✅ ACTION: {action}")
    timeline.append("─" * 60)

    # Summary line
    summary = f"{headline} → {action}"

    return {
        "timeline": timeline,
        "instructions": instructions,
        "summary": summary
    }


def format_timeline_text(timeline: List[str]) -> str:
    """
    Convert timeline list to formatted text string.

    Args:
        timeline: List of timeline lines

    Returns:
        Formatted text string with newlines
    """
    return "\n".join(timeline)


def generate_simple_instructions(
    focus_block: Optional[Dict],
    suggested_changes: List[Dict]
) -> str:
    """
    Generate simple step-by-step instructions for manual application.

    Args:
        focus_block: Focus block dict (optional)
        suggested_changes: List of meeting change suggestions

    Returns:
        Simple instruction text
    """
    instructions = []

    if focus_block:
        instructions.append(f"1. Add Focus Block: {focus_block['time_slot']}")

    for i, change in enumerate(suggested_changes, 1):
        step_num = i + (1 if focus_block else 0)
        instructions.append(
            f"{step_num}. Move \"{change['meeting']}\" - {change['suggestion']}"
        )

    if not instructions:
        instructions.append("Your calendar looks good as-is.")

    return "\n".join(instructions)
