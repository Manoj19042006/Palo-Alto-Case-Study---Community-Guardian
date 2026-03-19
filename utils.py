"""
utils.py — Filtering, search, validation, and location logic for Community Guardian.
"""

import json
import os
import uuid
from datetime import datetime, timezone, timedelta
from math import radians, sin, cos, sqrt, atan2
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
    "guardian_only":  "🛡️ Guardian Only",
}

SEVERITY_LABELS = {1: "Very Low", 2: "Low", 3: "Medium", 4: "High", 5: "Critical"}

# Coordinates for all cities present in the dataset.
# Used for nearest-city fallback when the user's detected city has no alerts.
CITY_COORDS: dict[str, tuple[float, float]] = {
    "Hyderabad":  (17.3850, 78.4867),
    "Bengaluru":  (12.9716, 77.5946),
    "Mumbai":     (19.0760, 72.8777),
    "Delhi":      (28.6139, 77.2090),
    "Chennai":    (13.0827, 80.2707),
    "Pune":       (18.5204, 73.8567),
}

DATE_FILTER_OPTIONS = [
    "All time",
    "Last 24 hours",
    "Last 2 days",
    "Last week",
    "Last month",
]

DATA_PATH = os.path.join(os.path.dirname(__file__), "data", "alerts.json")


# ---------------------------------------------------------------------------
# Location helpers
# ---------------------------------------------------------------------------

def haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Return the great-circle distance in km between two lat/lon points."""
    R = 6371.0
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
    return R * 2 * atan2(sqrt(a), sqrt(1 - a))


def nearest_city_in_dataset(lat: float, lon: float) -> str:
    """
    Return the name of the nearest dataset city to the given coordinates.
    Example: Sangareddy (17.62, 78.09) → Hyderabad (distance ~50 km).
    """
    return min(
        CITY_COORDS,
        key=lambda city: haversine_distance(lat, lon, *CITY_COORDS[city]),
    )


def get_user_location() -> dict:
    """
    Detect the user's approximate location via IP geolocation.

    Tries three providers in order (all free, no API key required):
      1. https://ip-api.com/json       — most accurate for India, HTTP only*
      2. https://ipinfo.io/json        — HTTPS, reliable fallback
      3. https://ipapi.co/json/        — HTTPS, second fallback

    * ip-api.com only supports HTTP for free tier. If the network blocks HTTP,
      providers 2 and 3 (HTTPS) are tried automatically.

    Returns:
        city         str   — raw detected city name
        lat/lon      float — coordinates (0.0 if unavailable)
        country      str   — country name
        matched_city str   — closest city from CITY_COORDS; "" if detection failed
        source       str   — provider name | "fallback(<reason>)"

    Always returns a safe dict — never raises.
    """
    import requests

    providers = [
        ("ip-api.com",  _fetch_ipapi),
        ("ipinfo.io",   _fetch_ipinfo),
        ("ipapi.co",    _fetch_ipapiCo),
    ]

    last_error = ""
    for name, fetcher in providers:
        try:
            result = fetcher()
            if result and result.get("lat") and result.get("lon"):
                city    = result.get("city", "")
                lat     = float(result["lat"])
                lon     = float(result["lon"])
                country = result.get("country", "")
                matched = city if city in CITY_COORDS else (
                    nearest_city_in_dataset(lat, lon) if lat and lon else ""
                )
                return {
                    "city": city, "lat": lat, "lon": lon,
                    "country": country, "matched_city": matched,
                    "source": name,
                }
        except Exception as exc:
            last_error = f"{name}: {str(exc)[:50]}"
            continue

    return _location_fallback(last_error or "all providers failed")


def _fetch_ipapi() -> dict:
    """ip-api.com — HTTP only (free tier restriction)."""
    import requests
    resp = requests.get("http://ip-api.com/json", timeout=4)
    resp.raise_for_status()
    data = resp.json()
    if data.get("status") != "success":
        raise ValueError("non-success status")
    return {"city": data.get("city",""), "lat": data.get("lat",0),
            "lon": data.get("lon",0), "country": data.get("country","")}


def _fetch_ipinfo() -> dict:
    """ipinfo.io — HTTPS, returns 'loc' as 'lat,lon' string."""
    import requests
    resp = requests.get("https://ipinfo.io/json", timeout=4)
    resp.raise_for_status()
    data = resp.json()
    loc  = data.get("loc", "0,0").split(",")
    return {"city": data.get("city",""), "lat": float(loc[0]),
            "lon": float(loc[1]), "country": data.get("country","")}


def _fetch_ipapiCo() -> dict:
    """ipapi.co — HTTPS, straightforward JSON."""
    import requests
    resp = requests.get("https://ipapi.co/json/", timeout=4)
    resp.raise_for_status()
    data = resp.json()
    if data.get("error"):
        raise ValueError(data.get("reason", "error"))
    return {"city": data.get("city",""), "lat": data.get("latitude",0),
            "lon": data.get("longitude",0), "country": data.get("country_name","")}


def _location_fallback(reason: str = "") -> dict:
    return {"city": "", "lat": 0.0, "lon": 0.0, "country": "",
            "matched_city": "", "source": f"fallback ({reason})" if reason else "fallback"}


# ---------------------------------------------------------------------------
# Data I/O
# ---------------------------------------------------------------------------

def load_alerts(path: str = DATA_PATH) -> list[dict]:
    """Load alerts from JSON file. Returns empty list on failure."""
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError):
        return []


def save_alerts(alerts: list[dict], path: str = DATA_PATH) -> bool:
    """Persist alert list to JSON. Returns True on success."""
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(alerts, f, indent=2, ensure_ascii=False)
        return True
    except OSError:
        return False


def parse_alert_datetime(alert: dict) -> Optional[datetime]:
    """Parse created_at into a timezone-aware datetime; None on failure."""
    raw = alert.get("created_at", "")
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (ValueError, TypeError):
        return None


def date_filter_cutoff(option: str) -> Optional[datetime]:
    """Convert a DATE_FILTER_OPTIONS label to a UTC cutoff. None for 'All time'."""
    now = datetime.now(timezone.utc)
    return {
        "Last 24 hours": now - timedelta(days=1),
        "Last 2 days":   now - timedelta(days=2),
        "Last week":     now - timedelta(weeks=1),
        "Last month":    now - timedelta(days=30),
    }.get(option)


# ---------------------------------------------------------------------------
# Filtering
# ---------------------------------------------------------------------------

def is_high_signal(alert: dict) -> bool:
    """True if alert is signal AND has non-low reliability or is verified."""
    if alert.get("noise_to_signal", "noise") == "noise":
        return False
    if alert.get("source_reliability", "low") == "low" and \
       alert.get("verification_status", "unverified") == "unverified":
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
    signal_only: bool = True,
    high_signal_only: bool = False,
    date_filter: str = "All time",
    search_query: str = "",
) -> list[dict]:
    """
    Apply all active filters to the alert list.

    signal_only=True (default) means the dashboard always starts from the
    signal-only base — noise posts never appear in the table unless explicitly
    opted in.  high_signal_only additionally requires good reliability/verification.
    """
    cutoff      = date_filter_cutoff(date_filter)
    query_lower = search_query.strip().lower()
    result: list[dict] = []

    for alert in alerts:

        # Base signal gate
        if signal_only and alert.get("noise_to_signal", "noise") == "noise":
            continue

        # Stricter reliability gate
        if high_signal_only and not is_high_signal(alert):
            continue

        if category and alert.get("category") != category:
            continue

        if city and alert.get("location_city") != city:
            continue

        if audience:
            tag     = alert.get("audience_tag", "")
            segment = alert.get("user_segment_focus", "")
            if audience not in (tag, segment):
                continue

        sev = int(alert.get("severity", 1))
        if not (severity_min <= sev <= severity_max):
            continue

        if cutoff is not None:
            alert_dt = parse_alert_datetime(alert)
            if alert_dt is None or alert_dt < cutoff:
                continue

        if query_lower:
            haystack = (alert.get("title", "") + " " + alert.get("report_text", "")).lower()
            if query_lower not in haystack:
                continue

        result.append(alert)

    return result


# ---------------------------------------------------------------------------
# Privacy helpers
# ---------------------------------------------------------------------------

def can_view_alert(alert: dict, viewer_role: str = "public") -> bool:
    mode = alert.get("privacy_mode", "public_digest")
    if mode == "public_digest":  return True
    if mode == "private_circle": return viewer_role in ("circle_member", "guardian")
    if mode == "guardian_only":  return viewer_role == "guardian"
    return False


def privacy_message(alert: dict) -> str:
    return {
        "private_circle": "🔒 This alert is shared within a trusted circle only.",
        "guardian_only":  "🛡️ This alert is restricted to Community Guardians.",
    }.get(alert.get("privacy_mode", ""), "")


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def validate_new_alert(data: dict) -> list[str]:
    """Returns a list of error strings (empty = valid)."""
    errors = []
    if not str(data.get("title", "")).strip():
        errors.append("Title cannot be empty.")
    try:
        if not (1 <= int(data.get("severity", 0)) <= 5):
            errors.append("Severity must be between 1 and 5.")
    except (ValueError, TypeError):
        errors.append("Severity must be a number between 1 and 5.")
    if data.get("category", "") not in VALID_CATEGORIES:
        errors.append(f"Category must be one of: {', '.join(VALID_CATEGORIES)}.")
    if not str(data.get("report_text", "")).strip():
        errors.append("Report text cannot be empty.")
    return errors


# ---------------------------------------------------------------------------
# Alert CRUD helpers
# ---------------------------------------------------------------------------

def build_new_alert(data: dict) -> dict:
    """Build a complete alert dict from validated form data."""
    raw_steps = data.get("user_action_steps", "") or ""
    if isinstance(raw_steps, str):
        lines = [s.strip() for line in raw_steps.splitlines() for s in line.split(",")]
        parsed_steps = [s for s in lines if s]
    else:
        parsed_steps = list(raw_steps)

    return {
        "id":                    f"CG-{uuid.uuid4().hex[:6].upper()}",
        "record_type":           "alert",
        "created_at":            datetime.now(timezone.utc).isoformat(),
        "location_city":         data.get("location_city", "Unknown"),
        "neighborhood":          data.get("neighborhood", ""),
        "audience_tag":          data.get("audience_tag", "neighborhood_group"),
        "category":              data.get("category", "physical_safety"),
        "subcategory":           data.get("subcategory", ""),
        "title":                 data.get("title", "").strip(),
        "report_text":           data.get("report_text", "").strip(),
        "source_type":           "user_submitted",
        "verification_status":   "unverified",
        "source_reliability":    "medium",
        "repeat_cluster_id":     "",
        "duplicate_of":          "",
        "local_relevance":       "medium",
        "severity":              int(data.get("severity", 3)),
        "urgency":               data.get("urgency", "soon"),
        "noise_to_signal":       "signal",  # only set here after AI classification passes
        "needs_actionable_digest": True,
        "ai_task":               "summarize",
        "recommended_action_type": "safety_tip",
        "action_steps":          parsed_steps,
        "safe_circle_recommended": False,
        "privacy_mode":          data.get("privacy_mode", "public_digest"),
        "encrypted_update":      False,
        "user_segment_focus":    data.get("audience_tag", "neighborhood_group"),
        "anxiety_tone":          "calm",
        "notes_edge_case":       "",
    }


def update_alert_status(alerts: list[dict], alert_id: str, new_status: str) -> tuple[bool, str]:
    valid_statuses = {"verified", "unverified", "dismissed", "pending"}
    if new_status not in valid_statuses:
        return False, f"Invalid status '{new_status}'."
    for alert in alerts:
        if alert.get("id") == alert_id:
            alert["verification_status"] = new_status
            if new_status == "verified":
                alert["source_reliability"] = "high"
                alert["noise_to_signal"]    = "signal"
            elif new_status == "dismissed":
                alert["noise_to_signal"] = "noise"
            return True, f"Alert {alert_id} updated to '{new_status}'."
    return False, f"Alert '{alert_id}' not found."


# ---------------------------------------------------------------------------
# Display helpers
# ---------------------------------------------------------------------------

def format_alert_date(alert: dict) -> str:
    """Human-readable IST date string for the created_at field."""
    dt = parse_alert_datetime(alert)
    if dt is None:
        return "—"
    try:
        ist = timezone(timedelta(hours=5, minutes=30))
        return dt.astimezone(ist).strftime("%d %b %Y, %H:%M")
    except Exception:
        return dt.strftime("%d %b %Y, %H:%M")


def severity_badge(level: int) -> str:
    icon  = {1: "🟢", 2: "🟡", 3: "🟠", 4: "🔴", 5: "🚨"}.get(level, "⚪")
    label = SEVERITY_LABELS.get(level, "Unknown")
    return f"{icon} {level} — {label}"


def status_badge(status: str) -> str:
    return {
        "verified":   "✅ Verified",
        "unverified": "❓ Unverified",
        "pending":    "⏳ Pending",
        "dismissed":  "🚫 Dismissed",
    }.get(status, status)
