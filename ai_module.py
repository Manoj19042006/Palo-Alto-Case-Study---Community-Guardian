"""
ai_module.py — Gemini API integration with rule-based fallback.

Provides:
    summarize_alert(report_text, category) -> dict
        {
            "summary": str,
            "action_steps": list[str],
            "source": "AI" | "fallback"
        }
"""

import json
import os
import re
import textwrap
from typing import Optional

from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

_MODEL_NAME = "gemini-2.5-flash"


def _get_api_key() -> Optional[str]:
    """
    Read the Gemini API key fresh on every call.
    Re-runs load_dotenv() so changes to .env are picked up without restarting.
    Returns None if the key is missing or blank.
    """
    load_dotenv(override=True)
    key = os.getenv("GEMINI_API_KEY", "").strip()
    return key if key else None


# ---------------------------------------------------------------------------
# Rule-based fallback
# ---------------------------------------------------------------------------

# Keyword → recommended action category
_KEYWORD_RULES: list[tuple[list[str], str]] = [
    (["phishing", "phish", "spoof", "fake link", "otp", "password"], "account safety"),
    (["scam", "fraud", "defraud", "cheated", "money transfer"], "financial safety"),
    (["theft", "stolen", "steal", "burglar", "robbery", "mugging"], "physical safety"),
    (["wifi", "wi-fi", "network", "router", "vpn", "hack"], "network security"),
    (["fire", "smoke", "flood", "earthquake", "storm", "cyclone"], "emergency response"),
    (["suspicious", "stranger", "loitering", "following"], "personal safety"),
]


def _fallback_summarize(report_text: str, category: str = "") -> dict:
    """
    Rule-based fallback when AI is unavailable.

    Does NOT generate a summary — extracting the first sentence would just
    duplicate what the user already sees in the report text, adding no value.
    Only produces keyword-matched action steps.
    """
    # --- Action steps: keyword matching ---
    text_lower = (report_text + " " + category).lower()
    matched_steps: list[str] = []

    for keywords, advice_label in _KEYWORD_RULES:
        if any(kw in text_lower for kw in keywords):
            steps = _rule_steps(advice_label)
            matched_steps.extend(steps)

    # Generic fallback if nothing matched
    if not matched_steps:
        matched_steps = [
            "Stay alert and monitor the situation.",
            "Report any suspicious activity to local authorities.",
            "Share verified information with your community circle.",
        ]

    # Deduplicate while preserving order
    seen: set[str] = set()
    unique_steps: list[str] = []
    for step in matched_steps:
        if step not in seen:
            seen.add(step)
            unique_steps.append(step)

    return {
        "summary": "",
        "action_steps": unique_steps[:5],
        "source": "fallback",
    }


def _rule_steps(label: str) -> list[str]:
    """Return canned action steps for a given risk label."""
    steps_map = {
        "account safety": [
            "Do not click on suspicious links or attachments.",
            "Enable two-factor authentication on all important accounts.",
            "Change your passwords immediately if credentials were shared.",
        ],
        "financial safety": [
            "Do not transfer money to unknown recipients.",
            "Verify payment requests through a separate trusted channel.",
            "Report the incident to your bank and cybercrime helpline (1930).",
        ],
        "physical safety": [
            "Avoid the affected area until the situation is resolved.",
            "Lock doors, windows, and secure valuables.",
            "Report confirmed details to building security or local police.",
        ],
        "network security": [
            "Disconnect from any untrusted Wi-Fi networks immediately.",
            "Use a VPN when connecting to public networks.",
            "Update router firmware and change default credentials.",
        ],
        "emergency response": [
            "Move to a safe location away from the hazard.",
            "Call emergency services (112) if life is at risk.",
            "Follow instructions from local authorities.",
        ],
        "personal safety": [
            "Avoid isolated areas, especially after dark.",
            "Travel with a trusted companion when possible.",
            "Report suspicious individuals to the local security desk.",
        ],
    }
    return steps_map.get(label, [])


# ---------------------------------------------------------------------------
# Gemini AI summarization
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = textwrap.dedent("""
    You are a calm, factual community safety assistant.
    Your job is to read a safety or security alert and produce:
    1. A concise, neutral summary (2–3 sentences, no speculation).
    2. Three to five concrete, actionable steps a regular person can take.

    Always respond with valid JSON only — no markdown, no code fences.
    Use this exact schema:
    {
      "summary": "<2–3 sentence neutral summary>",
      "action_steps": ["<step 1>", "<step 2>", "<step 3>"]
    }

    Tone: calm, reassuring, practical. Avoid alarmist language.
""").strip()


def summarize_alert(report_text: str, category: str = "") -> dict:
    """
    Summarize an alert using Gemini API, with automatic fallback.

    Returns:
        {
            "summary": str,
            "action_steps": list[str],
            "source": "AI" | "fallback",
            "error": str | None   ← real error message if AI failed
        }
    """
    if not report_text or not report_text.strip():
        return {
            "summary": "",
            "action_steps": ["Review the alert for more details."],
            "source": "fallback",
            "error": None,
        }

    api_key = _get_api_key()

    if not api_key:
        result = _fallback_summarize(report_text, category)
        result["error"] = "GEMINI_API_KEY is not set in your .env file."
        return result

    try:
        result = _call_gemini(report_text, api_key)
        result["source"] = "AI"
        result["error"] = None
        return result
    except Exception as exc:
        result = _fallback_summarize(report_text, category)
        result["error"] = str(exc)
        return result


def _call_gemini(report_text: str, api_key: str) -> dict:
    """
    Internal: call Gemini API and parse JSON response.
    Raises with a descriptive message on any failure.
    """
    import google.generativeai as genai  # imported here so missing package gives a clear error

    genai.configure(api_key=api_key)
    model = genai.GenerativeModel(
        model_name=_MODEL_NAME,
        system_instruction=_SYSTEM_PROMPT,
    )

    user_prompt = f"Alert text:\n{report_text.strip()}"
    response = model.generate_content(
        user_prompt,
        generation_config={"temperature": 0.3, "max_output_tokens": 512},
    )

    raw = response.text.strip()

    # Strip accidental markdown fences
    if raw.startswith("```"):
        raw = re.sub(r"^```[a-z]*\n?", "", raw)
        raw = re.sub(r"\n?```$", "", raw)

    parsed = json.loads(raw)

    if "summary" not in parsed or "action_steps" not in parsed:
        raise ValueError(f"Gemini returned unexpected JSON structure: {list(parsed.keys())}")
    if not isinstance(parsed["action_steps"], list):
        raise ValueError("Gemini 'action_steps' field is not a list.")

    return {
        "summary": str(parsed["summary"]),
        "action_steps": [str(s) for s in parsed["action_steps"]],
    }


# ---------------------------------------------------------------------------
# Batch helper (optional, used in tests)
# ---------------------------------------------------------------------------

def batch_summarize(alerts: list[dict]) -> list[dict]:
    """
    Enrich a list of alert dicts with AI summaries.
    Each alert dict gains: ai_summary, ai_action_steps, ai_source.
    """
    enriched = []
    for alert in alerts:
        result = summarize_alert(
            alert.get("report_text", ""),
            alert.get("category", ""),
        )
        enriched.append(
            {
                **alert,
                "ai_summary": result["summary"],
                "ai_action_steps": result["action_steps"],
                "ai_source": result["source"],
            }
        )
    return enriched