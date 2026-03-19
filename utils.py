"""
utils.py — Filtering, search, and validation logic for Community Guardian.
"""

import json
import os
import uuid
from datetime import datetime, timezone
from typing import Optional

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

VALID_CATEGORIES = [
    "physical_safety",
    "digital_security",
    "scam",
    "public_notice",
    "weather_hazard",
    "safe_circle",
]

VALID_AUDIENCES = [
    "neighborhood_group",
    "remote_worker",
    "elderly_user",
    "general",
]

AUDIENCE_LABELS = {
    "neighborhood_group": "🏘️ Neighborhood Group",
    "remote_worker":      "💻 Remote Worker",
    "elderly_user":       "👴 Elderly User",
    "general":            "👥 General",
}

PRIVACY_LABELS = {
    "public_digest": "🌐 Public",
    "private_circle": "🔒 Private Circle",
    "guardian_only": "🛡️ Guardian Only",
}

SEVERITY_LABELS = {1: "Very Low", 2: "Low", 3: "Medium", 4: "High", 5: "Critical"}

DATA_PATH = os.path.join(os.path.dirname(__file__), "data", "alerts.json")


# ---------------------------------------------------------------------------
# Data Loading
# ---------------------------------------------------------------------------

def load_alerts(path: str = DATA_PATH) -> list[dict]:
    """Load alerts from JSON file. Returns empty list on failure."""
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, list):
            return []
        return data
    except (json.JSONDecodeError, OSError):
        return []


def save_alerts(alerts: list[dict], path: str = DATA_PATH) -> bool:
    """Persist alerts list back to JSON. Returns True on success."""
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(alerts, f, indent=2, ensure_ascii=False)
        return True
    except OSError:
        return False


# ---------------------------------------------------------------------------
# Filtering
# ---------------------------------------------------------------------------

def is_high_signal(alert: dict) -> bool:
    """Return True if this alert qualifies as high-signal."""
    noise = alert.get("noise_to_signal", "noise")
    reliability = alert.get("source_reliability", "low")
    verified = alert.get("verification_status", "unverified")

    if noise == "noise":
        return False
    if reliability == "low" and verified == "unverified":
        return False
    return True


def filter_alerts(
    alerts: list[dict],
    *,
    category: Optional[str] = None,
    city: Optional[str] = None,
    audience: Optional[str] = None,
    severity_min: int = 1,
    severity_max: int = 5,
    high_signal_only: bool = False,
    search_query: str = "",
) -> list[dict]:
    """
    Apply all active filters to the alert list.

    Args:
        alerts: raw list of alert dicts
        category: exact category match (None = all)
        city: exact city match (None = all)
        audience: match against audience_tag or user_segment_focus (None = all)
        severity_min / severity_max: inclusive severity range 1–5
        high_signal_only: if True, exclude noise/low-reliability alerts
        search_query: case-insensitive substring search over title + report_text

    Returns:
        Filtered list of alert dicts.
    """
    result = []
    query_lower = search_query.strip().lower()

    for alert in alerts:
        # High-signal toggle
        if high_signal_only and not is_high_signal(alert):
            continue

        # Category filter
        if category and alert.get("category") != category:
            continue

        # City filter
        if city and alert.get("location_city") != city:
            continue

        # Audience filter — alert qualifies if either audience_tag OR user_segment_focus matches.
        # An alert can be posted in a neighborhood group (audience_tag) but specifically
        # focused on elderly users (user_segment_focus); it should appear under both filters.
        if audience:
            tag     = alert.get("audience_tag", "")
            segment = alert.get("user_segment_focus", "")
            if audience not in (tag, segment):
                continue

        # Severity range
        sev = int(alert.get("severity", 1))
        if not (severity_min <= sev <= severity_max):
            continue

        # Full-text search
        if query_lower:
            haystack = (
                alert.get("title", "").lower()
                + " "
                + alert.get("report_text", "").lower()
            )
            if query_lower not in haystack:
                continue

        result.append(alert)

    return result


# ---------------------------------------------------------------------------
# Privacy helpers
# ---------------------------------------------------------------------------

def can_view_alert(alert: dict, viewer_role: str = "public") -> bool:
    """
    Check whether viewer_role is permitted to see the full alert content.

    Roles hierarchy (least → most privileged):
        public < circle_member < guardian
    """
    mode = alert.get("privacy_mode", "public_digest")
    if mode == "public_digest":
        return True
    if mode == "private_circle":
        return viewer_role in ("circle_member", "guardian")
    if mode == "guardian_only":
        return viewer_role == "guardian"
    return False


def privacy_message(alert: dict) -> str:
    """Return a user-facing privacy restriction message."""
    mode = alert.get("privacy_mode", "public_digest")
    messages = {
        "private_circle": (
            "🔒 This alert is shared within a trusted circle only. "
            "Full details are not publicly visible."
        ),
        "guardian_only": (
            "🛡️ This alert is restricted to Community Guardians. "
            "Contact your local guardian for details."
        ),
    }
    return messages.get(mode, "")


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def validate_new_alert(data: dict) -> list[str]:
    """
    Validate a new alert submission.
    Returns a list of error strings (empty = valid).
    """
    errors = []

    title = str(data.get("title", "")).strip()
    if not title:
        errors.append("Title cannot be empty.")

    try:
        sev = int(data.get("severity", 0))
        if not (1 <= sev <= 5):
            errors.append("Severity must be between 1 and 5.")
    except (ValueError, TypeError):
        errors.append("Severity must be a number between 1 and 5.")

    category = data.get("category", "")
    if category not in VALID_CATEGORIES:
        errors.append(f"Category must be one of: {', '.join(VALID_CATEGORIES)}.")

    report_text = str(data.get("report_text", "")).strip()
    if not report_text:
        errors.append("Report text cannot be empty.")

    return errors


# ---------------------------------------------------------------------------
# Alert CRUD helpers
# ---------------------------------------------------------------------------

def build_new_alert(data: dict) -> dict:
    """Build a complete alert dict from validated form data."""
    # Parse user-submitted action steps: newline or comma separated string → list
    raw_steps = data.get("user_action_steps", "") or ""
    if isinstance(raw_steps, str):
        # Split on newlines first, then commas, strip and drop blanks
        lines = [s.strip() for line in raw_steps.splitlines() for s in line.split(",")]
        parsed_steps = [s for s in lines if s]
    else:
        parsed_steps = list(raw_steps)

    return {
        "id": f"CG-{uuid.uuid4().hex[:6].upper()}",
        "record_type": "alert",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "location_city": data.get("location_city", "Unknown"),
        "neighborhood": data.get("neighborhood", ""),
        "audience_tag": data.get("audience_tag", "neighborhood_group"),
        "category": data.get("category", "physical_safety"),
        "subcategory": data.get("subcategory", ""),
        "title": data.get("title", "").strip(),
        "report_text": data.get("report_text", "").strip(),
        "source_type": "user_submitted",
        "verification_status": "unverified",
        "source_reliability": "medium",
        "repeat_cluster_id": "",
        "duplicate_of": "",
        "local_relevance": "medium",
        "severity": int(data.get("severity", 3)),
        "urgency": data.get("urgency", "soon"),
        "noise_to_signal": "signal",
        "needs_actionable_digest": True,
        "ai_task": "summarize",
        "recommended_action_type": "safety_tip",
        "action_steps": parsed_steps,   # user-provided steps stored here
        "safe_circle_recommended": False,
        "privacy_mode": data.get("privacy_mode", "public_digest"),
        "encrypted_update": False,
        "user_segment_focus": data.get("audience_tag", "neighborhood_group"),
        "anxiety_tone": "calm",
        "notes_edge_case": "",
    }


def update_alert_status(
    alerts: list[dict], alert_id: str, new_status: str
) -> tuple[bool, str]:
    """
    Update verification_status of an alert.
    Returns (success, message).
    """
    valid_statuses = {"verified", "unverified", "dismissed", "pending"}
    if new_status not in valid_statuses:
        return False, f"Invalid status '{new_status}'. Must be one of {valid_statuses}."

    for alert in alerts:
        if alert.get("id") == alert_id:
            alert["verification_status"] = new_status
            if new_status == "verified":
                alert["source_reliability"] = "high"
                alert["noise_to_signal"] = "signal"
            elif new_status == "dismissed":
                alert["noise_to_signal"] = "noise"
            return True, f"Alert {alert_id} updated to '{new_status}'."

    return False, f"Alert '{alert_id}' not found."


# ---------------------------------------------------------------------------
# Display helpers
# ---------------------------------------------------------------------------

def severity_badge(level: int) -> str:
    colors = {1: "🟢", 2: "🟡", 3: "🟠", 4: "🔴", 5: "🚨"}
    label = SEVERITY_LABELS.get(level, "Unknown")
    icon = colors.get(level, "⚪")
    return f"{icon} {level} — {label}"


def status_badge(status: str) -> str:
    icons = {
        "verified": "✅ Verified",
        "unverified": "❓ Unverified",
        "pending": "⏳ Pending",
        "dismissed": "🚫 Dismissed",
    }
    return icons.get(status, status)
