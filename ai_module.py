"""
ai_module.py — Gemini API integration with rule-based fallback.

Key design decisions
────────────────────
1. The LLM receives the full alert context (title, category, subcategory,
   location, severity, urgency, source credibility, audience, user-submitted
   steps) — not just report_text.  This lets it produce summaries that are
   contextually relevant and audience-appropriate, which are explicit evaluation
   criteria in the task.

2. The system prompt is audience-aware:
   - elderly_user    → plain language, warm tone, numbered steps, no jargon
   - remote_worker   → technical specifics, device/network angle
   - neighborhood_group → community coordination framing
   - general         → balanced, neutral

3. The fallback is keyword-rule based and explicitly labelled as such in the
   returned dict so the UI can communicate it honestly to the user.

Returns
───────
    {
        "summary":      str,          # empty string for fallback
        "action_steps": list[str],
        "source":       "AI" | "fallback",
        "error":        str | None    # real error message when AI failed
    }
"""

import json
import os
import re
import textwrap
from typing import Optional

from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

_MODEL_NAME = "gemini-2.5-flash"

# Audience → tone instructions injected into the system prompt
_AUDIENCE_TONE: dict[str, str] = {
    "elderly_user": (
        "The reader is an elderly person who may not be tech-savvy. "
        "Use very simple, warm, reassuring language. "
        "Avoid all technical jargon. "
        "Number each action step plainly (1. 2. 3.). "
        "Keep sentences short. Never use acronyms without explanation."
    ),
    "remote_worker": (
        "The reader is a remote worker concerned about home network and device security. "
        "Include specific, technical steps where relevant (e.g. router settings, VPN, "
        "two-factor authentication). Be concise and practical."
    ),
    "neighborhood_group": (
        "The reader is part of a neighbourhood safety group. "
        "Frame action steps around community coordination — what to check, "
        "who to notify (building security, local police, neighbours), "
        "and how to share verified information with the group."
    ),
    "general": (
        "Use a balanced, calm, factual tone suitable for a general adult audience."
    ),
}

_SEVERITY_CONTEXT: dict[int, str] = {
    1: "This is a very low severity event. Reassure the reader that no immediate action is needed.",
    2: "This is a low severity event. Recommend awareness steps only.",
    3: "This is a moderate severity event. Recommend precautionary steps.",
    4: "This is a high severity event. Recommend clear protective actions without causing alarm.",
    5: "This is a critical severity event. Recommend immediate protective actions calmly and clearly.",
}


def _get_api_key() -> Optional[str]:
    """
    Read the Gemini API key fresh on every call.
    Re-runs load_dotenv(override=True) so edits to .env are picked up
    without restarting the app.
    """
    load_dotenv(override=True)
    key = os.getenv("GEMINI_API_KEY", "").strip()
    return key if key else None


# ---------------------------------------------------------------------------
# Prompt builder
# ---------------------------------------------------------------------------

def _build_prompt(alert: dict) -> tuple[str, str]:
    """
    Build (system_prompt, user_prompt) for Gemini from the full alert dict.

    Including all metadata gives the model the context it needs to produce
    audience-specific, severity-calibrated, location-relevant output.
    """
    audience       = alert.get("user_segment_focus") or alert.get("audience_tag") or "general"
    severity       = int(alert.get("severity", 3))
    tone_instr     = _AUDIENCE_TONE.get(audience, _AUDIENCE_TONE["general"])
    severity_instr = _SEVERITY_CONTEXT.get(severity, _SEVERITY_CONTEXT[3])

    # User-submitted steps as optional hints to the model
    user_steps      = alert.get("action_steps", [])
    user_steps_hint = ""
    if user_steps:
        joined = "\n".join(f"  - {s}" for s in user_steps if s)
        user_steps_hint = (
            f"\nThe person who reported this alert also suggested these initial steps "
            f"(use as hints, not as final answers — improve and expand on them):\n{joined}\n"
        )

    system_prompt = textwrap.dedent(f"""
        You are Community Guardian, a calm and trustworthy safety assistant.
        Your job is to read a structured safety alert and produce:
          1. A concise, neutral summary (2-3 sentences). Stick strictly to what is
             known — do not speculate or add information not present in the report.
          2. Three to five concrete, actionable steps the reader can take right now.

        Audience guidance: {tone_instr}

        Severity guidance: {severity_instr}

        Overall tone principles:
        - Reduce anxiety, not increase it. Frame information as empowering.
        - Be specific to the location and alert type where possible.
        - Never exaggerate or dramatise.
        - If the source is unverified, acknowledge uncertainty briefly in the summary.

        Respond with valid JSON only — no markdown fences, no preamble.
        Use this exact schema:
        {{
          "summary": "<2-3 sentence neutral summary>",
          "action_steps": ["<step 1>", "<step 2>", "<step 3>"]
        }}
    """).strip()

    # Structured user prompt with all alert metadata
    verification  = alert.get("verification_status", "unknown")
    reliability   = alert.get("source_reliability", "unknown")
    source_type   = alert.get("source_type", "unknown")
    source_line   = f"{source_type} — {verification} (reliability: {reliability})"

    location_parts = [p for p in [alert.get("neighborhood", ""), alert.get("location_city", "")] if p]
    location_str   = ", ".join(location_parts) if location_parts else "Unknown location"

    category       = alert.get("category", "").replace("_", " ")
    subcategory    = alert.get("subcategory", "").replace("_", " ")
    category_str   = category + (f" / {subcategory}" if subcategory else "")

    urgency        = alert.get("urgency", "unknown")
    noise_signal   = alert.get("noise_to_signal", "unknown")

    user_prompt = textwrap.dedent(f"""
        ALERT DETAILS
        -------------
        Title       : {alert.get("title", "Untitled")}
        Category    : {category_str}
        Location    : {location_str}
        Severity    : {severity}/5
        Urgency     : {urgency}
        Source      : {source_line}
        Signal type : {noise_signal}
        Audience    : {audience.replace("_", " ")}
        {user_steps_hint}
        FULL REPORT
        -----------
        {alert.get("report_text", "").strip()}
    """).strip()

    return system_prompt, user_prompt


# ---------------------------------------------------------------------------
# Rule-based fallback
# ---------------------------------------------------------------------------

_KEYWORD_RULES: list[tuple[list[str], str]] = [
    (["phishing", "phish", "spoof", "fake link", "otp", "password"],  "account safety"),
    (["scam", "fraud", "defraud", "cheated", "money transfer"],        "financial safety"),
    (["theft", "stolen", "steal", "burglar", "robbery", "mugging"],    "physical safety"),
    (["wifi", "wi-fi", "network", "router", "vpn", "hack"],            "network security"),
    (["fire", "smoke", "flood", "earthquake", "storm", "cyclone"],     "emergency response"),
    (["suspicious", "stranger", "loitering", "following"],             "personal safety"),
    (["package", "delivery", "parcel", "courier"],                     "delivery safety"),
    (["data breach", "leak", "credentials", "account compromised"],    "account safety"),
]

_STEPS: dict[str, list[str]] = {
    "account safety": [
        "Do not click on suspicious links or share OTPs with anyone.",
        "Enable two-factor authentication on all important accounts.",
        "Change your passwords immediately if credentials may have been exposed.",
        "Report the incident to your bank or service provider directly.",
    ],
    "financial safety": [
        "Do not transfer money to unknown or unverified recipients.",
        "Verify all payment requests through a separate, trusted channel (call the person directly).",
        "Report the incident to your bank and the national cybercrime helpline (1930).",
    ],
    "physical safety": [
        "Avoid the affected area until the situation is confirmed resolved.",
        "Ensure doors, windows, and storage areas are locked and secure.",
        "Report confirmed details to your building security desk or local police.",
        "Alert neighbours and your community group with verified facts only.",
    ],
    "network security": [
        "Disconnect from any untrusted or public Wi-Fi network immediately.",
        "Use a VPN when working remotely or on public networks.",
        "Update your router firmware and change the default admin password.",
        "Scan devices for malware if you suspect a compromise.",
    ],
    "emergency response": [
        "Move to a safe location away from the hazard immediately.",
        "Call emergency services (112) if there is any risk to life.",
        "Follow instructions from local authorities and emergency services.",
        "Stay informed via official local government or disaster management channels.",
    ],
    "personal safety": [
        "Avoid isolated areas, particularly after dark.",
        "Travel with a trusted companion where possible.",
        "Report any suspicious individuals to your local security desk or police helpline.",
    ],
    "delivery safety": [
        "Use a secure delivery locker or ask a neighbour to receive parcels.",
        "Review camera footage near entry points if a theft is suspected.",
        "Report confirmed thefts to building management and local police.",
    ],
}


def _fallback_summarize(alert: dict) -> dict:
    """
    Rule-based fallback — no AI, no network required.

    Does NOT produce a summary (that would just repeat the report text).
    Produces keyword-matched action steps from alert text and category.
    """
    report_text = alert.get("report_text", "")
    category    = alert.get("category", "")
    text_lower  = (report_text + " " + category).lower()

    matched: list[str] = []
    for keywords, label in _KEYWORD_RULES:
        if any(kw in text_lower for kw in keywords):
            matched.extend(_STEPS[label])

    if not matched:
        matched = [
            "Stay alert and keep yourself informed about the situation.",
            "Report any suspicious activity to local authorities or building security.",
            "Share only verified information with your community group.",
        ]

    seen: set[str] = set()
    unique: list[str] = []
    for s in matched:
        if s not in seen:
            seen.add(s)
            unique.append(s)

    return {
        "summary":      "",
        "action_steps": unique[:5],
        "source":       "fallback",
        "error":        None,
    }


# ---------------------------------------------------------------------------
# Gemini call
# ---------------------------------------------------------------------------

def _call_gemini(alert: dict, api_key: str) -> dict:
    """
    Call Gemini with the full alert context dict.

    Three defences against malformed / truncated JSON:
      1. response_mime_type="application/json"  — tells Gemini to emit only
         valid JSON, prevents it stopping mid-string.
      2. max_output_tokens=1024  — enough headroom for a full response even
         after the large structured prompt is sent.
      3. _extract_json()  — last-resort repair that salvages partial JSON if
         the above two still somehow produce a truncated response.

    Raises descriptively on unrecoverable failure so the caller can surface
    the error in the UI.
    """
    import google.generativeai as genai

    system_prompt, user_prompt = _build_prompt(alert)

    genai.configure(api_key=api_key)
    model = genai.GenerativeModel(
        model_name=_MODEL_NAME,
        system_instruction=system_prompt,
    )
    response = model.generate_content(
        user_prompt,
        generation_config={
            "temperature": 0.3,
            "max_output_tokens": 1024,          # raised from 600 — prevents mid-string truncation
            "response_mime_type": "application/json",  # forces Gemini to emit only valid JSON
        },
    )

    raw = response.text.strip()

    # Strip accidental markdown fences (defensive — mime_type should prevent them)
    if raw.startswith("```"):
        raw = re.sub(r"^```[a-z]*\n?", "", raw)
        raw = re.sub(r"\n?```$",        "", raw)
        raw = raw.strip()

    parsed = _parse_json_safe(raw)

    if "summary" not in parsed or "action_steps" not in parsed:
        raise ValueError(
            f"Gemini returned unexpected JSON keys: {list(parsed.keys())}. "
            "Expected 'summary' and 'action_steps'."
        )
    if not isinstance(parsed["action_steps"], list):
        raise ValueError("Gemini 'action_steps' field is not a list.")

    return {
        "summary":      str(parsed["summary"]),
        "action_steps": [str(s) for s in parsed["action_steps"]],
    }


def _parse_json_safe(raw: str) -> dict:
    """
    Parse JSON from Gemini's response with a best-effort repair pass.

    Strategy:
      1. Try json.loads() directly — succeeds in the happy path.
      2. If that fails, try to extract the first {...} block with a regex —
         handles cases where extra text leaked outside the JSON object.
      3. If truncation is detected (unterminated string / missing closing
         bracket), attempt to close the structure and re-parse.
      4. Raise ValueError with the original error + raw snippet so the UI
         can show a meaningful message instead of a raw Python traceback.
    """
    # --- Pass 1: direct parse ---
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass

    # --- Pass 2: extract first {...} block ---
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if match:
        candidate = match.group(0)
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            raw = candidate  # continue with the extracted block

    # --- Pass 3: attempt to close truncated JSON ---
    repaired = _attempt_repair(raw)
    if repaired:
        try:
            return json.loads(repaired)
        except json.JSONDecodeError:
            pass

    # --- All passes failed ---
    snippet = raw[:120].replace("\n", " ")
    raise ValueError(
        f"Could not parse Gemini response as JSON. "
        f"Raw response starts with: '{snippet}…'"
    )


def _attempt_repair(raw: str) -> Optional[str]:
    """
    Heuristic repair for common Gemini truncation patterns.

    Covers:
    - Unterminated string in the last value  → close the string
    - Missing closing ] on action_steps array → add ]
    - Missing closing } on the root object   → add }
    """
    s = raw.rstrip()

    # If the last non-whitespace char is a letter/digit/comma, the string was cut
    if s and s[-1] not in ('"', ']', '}', ','):
        s += '"'   # close the unterminated string

    # Ensure array is closed
    if '"action_steps"' in s and s.count('[') > s.count(']'):
        s += ']'

    # Ensure object is closed
    if s.count('{') > s.count('}'):
        s += '}'

    return s if s != raw.rstrip() else None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def summarize_alert(alert: dict) -> dict:
    """
    Generate a summary and action steps for a given alert dict.

    Passes the FULL alert context to Gemini so the model can produce
    audience-specific, severity-calibrated, location-aware output.

    Falls back to keyword rules if the API key is missing or the call fails.

    Args:
        alert: the complete alert dict

    Returns:
        {
            "summary":      str,         # empty string for fallback
            "action_steps": list[str],
            "source":       "AI" | "fallback",
            "error":        str | None
        }
    """
    report_text = alert.get("report_text", "")
    if not report_text or not report_text.strip():
        return {
            "summary":      "",
            "action_steps": ["Review the alert for more details before taking action."],
            "source":       "fallback",
            "error":        None,
        }

    api_key = _get_api_key()

    if not api_key:
        result = _fallback_summarize(alert)
        result["error"] = "GEMINI_API_KEY is not set in your .env file."
        return result

    try:
        result           = _call_gemini(alert, api_key)
        result["source"] = "AI"
        result["error"]  = None
        return result
    except Exception as exc:
        result           = _fallback_summarize(alert)
        result["error"]  = str(exc)
        return result
