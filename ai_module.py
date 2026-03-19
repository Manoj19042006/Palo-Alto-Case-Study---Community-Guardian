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

import google.generativeai as genai
from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

_API_KEY: Optional[str] = os.getenv("GEMINI_API_KEY")
_MODEL_NAME = "gemini-1.5-flash"
_CONFIGURED = False


def _configure():
    """Configure Gemini once; idempotent."""
    global _CONFIGURED
    if _CONFIGURED:
        return
    if _API_KEY:
        genai.configure(api_key=_API_KEY)
        _CONFIGURED = True


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
    Rule-based summarization when AI is unavailable.

    Strategy:
      1. Summary = first sentence (≤ 180 chars), cleaned up.
      2. Action steps derived from keyword matching on report_text + category.
    """
    # --- Summary: first sentence ---
    sentences = re.split(r"(?<=[.!?])\s+", report_text.strip())
    first = sentences[0] if sentences else report_text
    summary = textwrap.shorten(first, width=180, placeholder="…")

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
        "summary": summary,
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
    if not report_text or not report_text.strip():
        return {
            "summary": "No report text available.",
            "action_steps": ["Review the alert for more details."],
            "source": "fallback",
        }

    if _API_KEY:
        try:
            result = _call_gemini(report_text)

            # 🔥 FIX: validate AI output before accepting it
            if (
                not result.get("summary")
                or len(result.get("summary", "").strip()) < 10
                or not result.get("action_steps")
            ):
                raise ValueError("Weak AI response")

            result["source"] = "AI"
            return result

        except Exception:
            pass

    return _fallback_summarize(report_text, category)


def _call_gemini(report_text: str) -> dict:
    """
    Internal: call Gemini API and parse JSON response.
    Raises on any failure so caller can catch and fallback.
    """
    _configure()
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

    # Validate schema
    if "summary" not in parsed or "action_steps" not in parsed:
        raise ValueError("Gemini response missing required keys.")
    if not isinstance(parsed["action_steps"], list):
        raise ValueError("action_steps must be a list.")

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
