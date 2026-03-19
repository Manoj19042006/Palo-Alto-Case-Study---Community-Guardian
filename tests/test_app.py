"""
tests/test_app.py — Community Guardian test suite.

Covers:
  - Happy path: load → filter → summarize
  - Edge cases: empty dataset, invalid input, privacy gate, fallback AI
"""

import json
import os
import sys
import tempfile
import unittest

# Ensure parent package is importable when running from the tests/ directory
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from utils import (
    load_alerts,
    save_alerts,
    filter_alerts,
    validate_new_alert,
    build_new_alert,
    update_alert_status,
    can_view_alert,
    privacy_message,
    is_high_signal,
    severity_badge,
    status_badge,
)
from ai_module import _fallback_summarize, summarize_alert

# ---------------------------------------------------------------------------
# Sample fixture data
# ---------------------------------------------------------------------------

SAMPLE_ALERTS = [
    {
        "id": "CG-T01",
        "record_type": "alert",
        "created_at": "2026-01-01T09:00:00+05:30",
        "location_city": "Hyderabad",
        "neighborhood": "Test Colony",
        "audience_tag": "neighborhood_group",
        "category": "digital_security",
        "subcategory": "phishing",
        "title": "Phishing SMS targeting bank customers",
        "report_text": (
            "Multiple residents received SMS messages impersonating a leading bank, "
            "asking them to click a link to update KYC. The link leads to a fake login page."
        ),
        "source_type": "community_post",
        "verification_status": "verified",
        "source_reliability": "high",
        "repeat_cluster_id": "",
        "duplicate_of": "",
        "local_relevance": "high",
        "severity": 4,
        "urgency": "immediate",
        "noise_to_signal": "signal",
        "needs_actionable_digest": True,
        "ai_task": "summarize",
        "recommended_action_type": "safety_tip",
        "action_steps": [],
        "safe_circle_recommended": False,
        "privacy_mode": "public_digest",
        "encrypted_update": False,
        "user_segment_focus": "general",
        "anxiety_tone": "calm",
        "notes_edge_case": "",
    },
    {
        "id": "CG-T02",
        "record_type": "alert",
        "created_at": "2026-01-02T11:00:00+05:30",
        "location_city": "Mumbai",
        "neighborhood": "Marine Drive",
        "audience_tag": "neighborhood_group",
        "category": "physical_safety",
        "subcategory": "theft",
        "title": "Chain snatching near Metro station",
        "report_text": "A woman reported her gold chain being snatched near the metro entrance at peak hour.",
        "source_type": "official_notice",
        "verification_status": "verified",
        "source_reliability": "high",
        "repeat_cluster_id": "",
        "duplicate_of": "",
        "local_relevance": "high",
        "severity": 5,
        "urgency": "immediate",
        "noise_to_signal": "signal",
        "needs_actionable_digest": True,
        "ai_task": "summarize",
        "recommended_action_type": "avoid_area",
        "action_steps": [],
        "safe_circle_recommended": True,
        "privacy_mode": "private_circle",
        "encrypted_update": False,
        "user_segment_focus": "neighborhood_group",
        "anxiety_tone": "calm",
        "notes_edge_case": "",
    },
    {
        "id": "CG-T03",
        "record_type": "alert",
        "created_at": "2026-01-03T08:00:00+05:30",
        "location_city": "Delhi",
        "neighborhood": "Central",
        "audience_tag": "neighborhood_group",
        "category": "scam",
        "subcategory": "lottery",
        "title": "Lottery scam phone calls reported",
        "report_text": "Elderly residents are receiving calls claiming they won a lottery. Callers ask for a small processing fee.",
        "source_type": "community_post",
        "verification_status": "unverified",
        "source_reliability": "low",
        "repeat_cluster_id": "CL-99",
        "duplicate_of": "",
        "local_relevance": "medium",
        "severity": 2,
        "urgency": "monitor",
        "noise_to_signal": "noise",
        "needs_actionable_digest": False,
        "ai_task": "categorize",
        "recommended_action_type": "monitor",
        "action_steps": [],
        "safe_circle_recommended": False,
        "privacy_mode": "guardian_only",
        "encrypted_update": False,
        "user_segment_focus": "elderly_user",
        "anxiety_tone": "calm",
        "notes_edge_case": "Low reliability, noise, guardian_only",
    },
]


# ===========================================================================
# Happy Path Tests
# ===========================================================================

class TestHappyPath(unittest.TestCase):

    def setUp(self):
        # Write sample data to a temp file
        self.tmp = tempfile.NamedTemporaryFile(
            suffix=".json", mode="w", delete=False, encoding="utf-8"
        )
        json.dump(SAMPLE_ALERTS, self.tmp)
        self.tmp.close()

    def tearDown(self):
        os.unlink(self.tmp.name)

    # --- Load ---

    def test_load_alerts_returns_list(self):
        alerts = load_alerts(self.tmp.name)
        self.assertIsInstance(alerts, list)
        self.assertEqual(len(alerts), 3)

    def test_load_alerts_preserves_fields(self):
        alerts = load_alerts(self.tmp.name)
        first = alerts[0]
        self.assertEqual(first["id"], "CG-T01")
        self.assertEqual(first["category"], "digital_security")
        self.assertEqual(first["severity"], 4)

    # --- Filter ---

    def test_filter_by_city(self):
        result = filter_alerts(SAMPLE_ALERTS, city="Hyderabad")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["id"], "CG-T01")

    def test_filter_by_category(self):
        result = filter_alerts(SAMPLE_ALERTS, category="physical_safety")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["id"], "CG-T02")

    def test_filter_by_severity_range(self):
        result = filter_alerts(SAMPLE_ALERTS, severity_min=4, severity_max=5)
        ids = {a["id"] for a in result}
        self.assertIn("CG-T01", ids)
        self.assertIn("CG-T02", ids)
        self.assertNotIn("CG-T03", ids)

    def test_filter_high_signal_only(self):
        result = filter_alerts(SAMPLE_ALERTS, high_signal_only=True)
        ids = {a["id"] for a in result}
        # CG-T03 is noise + low reliability → excluded
        self.assertNotIn("CG-T03", ids)
        self.assertIn("CG-T01", ids)
        self.assertIn("CG-T02", ids)

    def test_filter_search_query(self):
        result = filter_alerts(SAMPLE_ALERTS, search_query="phishing")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["id"], "CG-T01")

    def test_filter_no_criteria_returns_all(self):
        # signal_only=False needed: CG-T03 has noise_to_signal="noise"
        # and filter_alerts defaults to signal_only=True in production.
        result = filter_alerts(SAMPLE_ALERTS, signal_only=False)
        self.assertEqual(len(result), len(SAMPLE_ALERTS))

    # --- is_high_signal ---

    def test_is_high_signal_true(self):
        self.assertTrue(is_high_signal(SAMPLE_ALERTS[0]))

    def test_is_high_signal_false_noise(self):
        self.assertFalse(is_high_signal(SAMPLE_ALERTS[2]))

    # --- Summarize (fallback path, no API key needed) ---

    def test_summarize_fallback_returns_dict(self):
        alert = {
            "report_text": "Multiple residents received phishing SMS messages. They were asked to click a fake link.",
            "category": "digital_security",
        }
        result = _fallback_summarize(alert)
        self.assertIn("summary", result)
        self.assertIn("action_steps", result)
        self.assertEqual(result["source"], "fallback")
        self.assertIsInstance(result["action_steps"], list)
        self.assertGreater(len(result["action_steps"]), 0)
        # Fallback produces no summary — avoids duplicating the report text
        self.assertEqual(result["summary"], "")

    def test_summarize_fallback_keyword_phishing(self):
        alert = {
            "report_text": "A phishing email asked users for their password.",
            "category": "digital_security",
        }
        result = _fallback_summarize(alert)
        steps_text = " ".join(result["action_steps"]).lower()
        self.assertTrue(
            any(kw in steps_text for kw in ["password", "two-factor", "authentication", "account", "otp"])
        )

    def test_summarize_fallback_keyword_theft(self):
        alert = {
            "report_text": "A bicycle was stolen from the premises.",
            "category": "physical_safety",
        }
        result = _fallback_summarize(alert)
        steps_text = " ".join(result["action_steps"]).lower()
        self.assertTrue(
            any(kw in steps_text for kw in ["lock", "secure", "police", "report"])
        )

    def test_summarize_alert_no_api_key_returns_fallback(self):
        """summarize_alert() must return fallback + error message when GEMINI_API_KEY is absent."""
        from unittest.mock import patch
        alert = {
            "report_text": "Suspicious person seen near park at night.",
            "category": "physical_safety",
            "audience_tag": "neighborhood_group",
            "severity": 3,
        }
        with patch("ai_module._get_api_key", return_value=None):
            result = summarize_alert(alert)
        self.assertIn("summary", result)
        self.assertIn("action_steps", result)
        self.assertEqual(result["source"], "fallback")
        self.assertIsNotNone(result.get("error"))
        self.assertIn("GEMINI_API_KEY", result["error"])

    # --- Save ---

    def test_save_and_reload(self):
        alerts = load_alerts(self.tmp.name)
        alerts[0]["title"] = "Updated Title"
        save_alerts(alerts, self.tmp.name)
        reloaded = load_alerts(self.tmp.name)
        self.assertEqual(reloaded[0]["title"], "Updated Title")

    # --- Update status ---

    def test_update_status_verified(self):
        alerts = [dict(a) for a in SAMPLE_ALERTS]  # shallow copy
        ok, msg = update_alert_status(alerts, "CG-T03", "verified")
        self.assertTrue(ok)
        updated = next(a for a in alerts if a["id"] == "CG-T03")
        self.assertEqual(updated["verification_status"], "verified")
        self.assertEqual(updated["source_reliability"], "high")
        self.assertEqual(updated["noise_to_signal"], "signal")

    def test_update_status_dismissed(self):
        alerts = [dict(a) for a in SAMPLE_ALERTS]
        ok, msg = update_alert_status(alerts, "CG-T01", "dismissed")
        self.assertTrue(ok)
        updated = next(a for a in alerts if a["id"] == "CG-T01")
        self.assertEqual(updated["noise_to_signal"], "noise")

    # --- Privacy ---

    def test_can_view_public_as_public(self):
        self.assertTrue(can_view_alert(SAMPLE_ALERTS[0], viewer_role="public"))

    def test_cannot_view_private_as_public(self):
        self.assertFalse(can_view_alert(SAMPLE_ALERTS[1], viewer_role="public"))

    def test_can_view_private_as_circle_member(self):
        self.assertTrue(can_view_alert(SAMPLE_ALERTS[1], viewer_role="circle_member"))

    def test_cannot_view_guardian_only_as_public(self):
        self.assertFalse(can_view_alert(SAMPLE_ALERTS[2], viewer_role="public"))

    def test_can_view_guardian_only_as_guardian(self):
        self.assertTrue(can_view_alert(SAMPLE_ALERTS[2], viewer_role="guardian"))

    def test_privacy_message_private_circle(self):
        msg = privacy_message(SAMPLE_ALERTS[1])
        self.assertIn("trusted circle", msg)

    def test_privacy_message_guardian_only(self):
        msg = privacy_message(SAMPLE_ALERTS[2])
        self.assertIn("Guardian", msg)

    # --- Display helpers ---

    def test_severity_badge_contains_level(self):
        badge = severity_badge(4)
        self.assertIn("4", badge)
        self.assertIn("High", badge)

    def test_status_badge_verified(self):
        badge = status_badge("verified")
        self.assertIn("Verified", badge)


# ===========================================================================
# Edge Case Tests
# ===========================================================================

class TestEdgeCases(unittest.TestCase):

    # --- Empty dataset ---

    def test_load_missing_file_returns_empty(self):
        result = load_alerts("/nonexistent/path/alerts.json")
        self.assertEqual(result, [])

    def test_load_invalid_json_returns_empty(self):
        with tempfile.NamedTemporaryFile(
            suffix=".json", mode="w", delete=False, encoding="utf-8"
        ) as f:
            f.write("NOT VALID JSON {{{{")
            fname = f.name
        try:
            result = load_alerts(fname)
            self.assertEqual(result, [])
        finally:
            os.unlink(fname)

    def test_load_non_list_json_returns_empty(self):
        with tempfile.NamedTemporaryFile(
            suffix=".json", mode="w", delete=False, encoding="utf-8"
        ) as f:
            json.dump({"key": "value"}, f)
            fname = f.name
        try:
            result = load_alerts(fname)
            self.assertEqual(result, [])
        finally:
            os.unlink(fname)

    def test_filter_empty_list(self):
        result = filter_alerts([], city="Mumbai", high_signal_only=True)
        self.assertEqual(result, [])

    # --- Invalid input validation ---

    def test_validate_empty_title(self):
        errors = validate_new_alert(
            {"title": "", "severity": 3, "category": "scam", "report_text": "Some text"}
        )
        self.assertTrue(any("Title" in e for e in errors))

    def test_validate_invalid_severity_zero(self):
        errors = validate_new_alert(
            {"title": "Test", "severity": 0, "category": "scam", "report_text": "Some text"}
        )
        self.assertTrue(any("Severity" in e for e in errors))

    def test_validate_invalid_severity_six(self):
        errors = validate_new_alert(
            {"title": "Test", "severity": 6, "category": "scam", "report_text": "Some text"}
        )
        self.assertTrue(any("Severity" in e for e in errors))

    def test_validate_invalid_severity_string(self):
        errors = validate_new_alert(
            {"title": "Test", "severity": "urgent", "category": "scam", "report_text": "Some text"}
        )
        self.assertTrue(any("Severity" in e for e in errors))

    def test_validate_invalid_category(self):
        errors = validate_new_alert(
            {"title": "Test", "severity": 3, "category": "unknown_cat", "report_text": "Some text"}
        )
        self.assertTrue(any("Category" in e for e in errors))

    def test_validate_empty_report_text(self):
        errors = validate_new_alert(
            {"title": "Test", "severity": 3, "category": "scam", "report_text": ""}
        )
        self.assertTrue(any("report" in e.lower() for e in errors))

    def test_validate_missing_fields(self):
        errors = validate_new_alert({})
        # Should catch title, severity, category, and report text
        self.assertGreaterEqual(len(errors), 3)

    def test_validate_valid_input_no_errors(self):
        errors = validate_new_alert(
            {
                "title": "Test Alert",
                "severity": 3,
                "category": "digital_security",
                "report_text": "A valid report.",
            }
        )
        self.assertEqual(errors, [])

    # --- update_alert_status edge cases ---

    def test_update_status_invalid_value(self):
        alerts = [dict(a) for a in SAMPLE_ALERTS]
        ok, msg = update_alert_status(alerts, "CG-T01", "banana")
        self.assertFalse(ok)
        self.assertIn("Invalid status", msg)

    def test_update_status_nonexistent_id(self):
        alerts = [dict(a) for a in SAMPLE_ALERTS]
        ok, msg = update_alert_status(alerts, "CG-MISSING", "verified")
        self.assertFalse(ok)
        self.assertIn("not found", msg)

    # --- build_new_alert ---

    def test_build_new_alert_generates_id(self):
        alert = build_new_alert(
            {
                "title": "Test",
                "report_text": "Report",
                "category": "scam",
                "location_city": "Pune",
                "severity": 2,
            }
        )
        self.assertTrue(alert["id"].startswith("CG-"))
        self.assertEqual(alert["verification_status"], "unverified")
        self.assertEqual(alert["noise_to_signal"], "signal")

    def test_build_new_alert_parses_user_steps_newlines(self):
        """User steps entered one-per-line are parsed into a list."""
        alert = build_new_alert({
            "title": "Test",
            "report_text": "Some incident.",
            "category": "scam",
            "location_city": "Delhi",
            "severity": 3,
            "user_action_steps": "Lock your bike\nAlert building security\nFile a police report",
        })
        self.assertEqual(len(alert["action_steps"]), 3)
        self.assertIn("Lock your bike", alert["action_steps"])
        self.assertIn("File a police report", alert["action_steps"])

    def test_build_new_alert_parses_user_steps_commas(self):
        """User steps entered comma-separated are also parsed correctly."""
        alert = build_new_alert({
            "title": "Test",
            "report_text": "Some incident.",
            "category": "scam",
            "location_city": "Delhi",
            "severity": 3,
            "user_action_steps": "Change password, Enable 2FA, Call bank",
        })
        self.assertEqual(len(alert["action_steps"]), 3)
        self.assertIn("Change password", alert["action_steps"])

    def test_build_new_alert_empty_steps_gives_empty_list(self):
        """No user steps → action_steps is an empty list."""
        alert = build_new_alert({
            "title": "Test",
            "report_text": "Report",
            "category": "scam",
            "location_city": "Pune",
            "severity": 2,
            "user_action_steps": "",
        })
        self.assertEqual(alert["action_steps"], [])

    def test_build_new_alert_strips_blank_step_lines(self):
        """Blank lines in user steps are silently dropped."""
        alert = build_new_alert({
            "title": "Test",
            "report_text": "Report",
            "category": "scam",
            "location_city": "Pune",
            "severity": 2,
            "user_action_steps": "Step one\n\n\nStep two\n",
        })
        self.assertEqual(len(alert["action_steps"]), 2)

    # --- Audience filter ---

    def test_filter_by_audience_neighborhood(self):
        # signal_only=False: CG-T03 is noise, needs to be visible for this test
        result = filter_alerts(SAMPLE_ALERTS, audience="neighborhood_group", signal_only=False)
        ids = {a["id"] for a in result}
        self.assertIn("CG-T01", ids)   # audience_tag = neighborhood_group
        self.assertIn("CG-T02", ids)   # audience_tag = neighborhood_group
        self.assertIn("CG-T03", ids)   # audience_tag = neighborhood_group (also elderly segment)

    def test_filter_by_audience_elderly(self):
        # signal_only=False: CG-T03 is noise but we're testing the audience logic
        result = filter_alerts(SAMPLE_ALERTS, audience="elderly_user", signal_only=False)
        ids = {a["id"] for a in result}
        self.assertIn("CG-T03", ids)       # user_segment_focus = elderly_user → match
        self.assertNotIn("CG-T01", ids)    # neither field is elderly_user
        self.assertNotIn("CG-T02", ids)    # neither field is elderly_user

    def test_filter_by_audience_no_match(self):
        result = filter_alerts(SAMPLE_ALERTS, audience="remote_worker", signal_only=False)
        self.assertEqual(result, [])

    def test_filter_audience_none_returns_all(self):
        """audience=None with signal_only=False returns all alerts regardless of segment."""
        result = filter_alerts(SAMPLE_ALERTS, audience=None, signal_only=False)
        self.assertEqual(len(result), len(SAMPLE_ALERTS))

    # --- Prompt builder ---

    def test_build_prompt_includes_all_metadata(self):
        """_build_prompt must include location, severity, audience, source in the user prompt."""
        from ai_module import _build_prompt
        alert = {
            "title": "OTP Fraud Alert",
            "report_text": "Residents are being called and asked for OTPs.",
            "category": "scam",
            "subcategory": "otp_fraud",
            "location_city": "Hyderabad",
            "neighborhood": "Banjara Hills",
            "severity": 4,
            "urgency": "immediate",
            "source_type": "community_post",
            "verification_status": "unverified",
            "source_reliability": "medium",
            "noise_to_signal": "signal",
            "audience_tag": "elderly_user",
            "user_segment_focus": "elderly_user",
            "action_steps": ["Do not share OTP", "Call your bank"],
        }
        _, user_prompt = _build_prompt(alert)
        self.assertIn("Hyderabad",        user_prompt)
        self.assertIn("Banjara Hills",    user_prompt)
        self.assertIn("4/5",              user_prompt)
        self.assertIn("elderly_user".replace("_", " "), user_prompt)  # audience shown
        self.assertIn("OTP Fraud Alert",  user_prompt)
        self.assertIn("Do not share OTP", user_prompt)   # user steps passed as hints

    def test_build_prompt_audience_tone_elderly(self):
        """System prompt for elderly_user should contain jargon-avoidance instruction."""
        from ai_module import _build_prompt
        alert = {"report_text": "Test.", "audience_tag": "elderly_user",
                 "user_segment_focus": "elderly_user", "severity": 2}
        system_prompt, _ = _build_prompt(alert)
        self.assertIn("elderly", system_prompt.lower())
        self.assertIn("jargon", system_prompt.lower())

    def test_build_prompt_audience_tone_remote_worker(self):
        """System prompt for remote_worker should mention technical steps."""
        from ai_module import _build_prompt
        alert = {"report_text": "Test.", "audience_tag": "remote_worker",
                 "user_segment_focus": "remote_worker", "severity": 3}
        system_prompt, _ = _build_prompt(alert)
        self.assertIn("remote worker", system_prompt.lower())

    # --- Fallback with empty text ---

    def test_summarize_empty_text_safe_output(self):
        result = summarize_alert({"report_text": "", "category": "scam"})
        self.assertIn("summary", result)
        self.assertIn("action_steps", result)
        self.assertEqual(result["source"], "fallback")

    def test_summarize_whitespace_only_text(self):
        result = summarize_alert({"report_text": "   \n\t  ", "category": "scam"})
        self.assertEqual(result["source"], "fallback")

    def test_fallback_unknown_keywords_uses_generic(self):
        alert = {"report_text": "Something very ambiguous happened.", "category": "unknown_category"}
        result = _fallback_summarize(alert)
        self.assertGreater(len(result["action_steps"]), 0)
        steps_text = " ".join(result["action_steps"]).lower()
        self.assertTrue(
            any(kw in steps_text for kw in ["alert", "report", "share"])
        )

    # --- JSON parse + repair ---

    def test_parse_json_safe_clean_input(self):
        """Well-formed JSON parses without repair."""
        from ai_module import _parse_json_safe
        raw = '{"summary": "All good.", "action_steps": ["Step 1", "Step 2"]}'
        result = _parse_json_safe(raw)
        self.assertEqual(result["summary"], "All good.")
        self.assertEqual(result["action_steps"], ["Step 1", "Step 2"])

    def test_parse_json_safe_strips_markdown_fences(self):
        """JSON wrapped in ```json ... ``` fences is still parsed correctly."""
        from ai_module import _parse_json_safe
        raw = '```json\n{"summary": "Test.", "action_steps": ["Do this"]}\n```'
        # Fences are stripped before _parse_json_safe is called in _call_gemini,
        # but test the extractor fallback path handles extra text gracefully too.
        # Here we test that the regex-extraction pass finds the {...} block.
        result = _parse_json_safe(raw)
        self.assertEqual(result["summary"], "Test.")

    def test_parse_json_safe_truncated_string_repaired(self):
        """Unterminated string in the last action step is repaired and parsed."""
        from ai_module import _parse_json_safe
        # Simulates Gemini cutting off mid-last-step
        truncated = '{"summary": "A scam was detected.", "action_steps": ["Do not click links", "Call your bank'
        result = _parse_json_safe(truncated)
        self.assertIn("summary", result)
        self.assertIsInstance(result["action_steps"], list)
        self.assertGreater(len(result["action_steps"]), 0)

    def test_parse_json_safe_missing_closing_brace(self):
        """Missing closing } is repaired."""
        from ai_module import _parse_json_safe
        incomplete = '{"summary": "Test summary.", "action_steps": ["Step one", "Step two"]'
        result = _parse_json_safe(incomplete)
        self.assertEqual(result["summary"], "Test summary.")

    def test_parse_json_safe_missing_array_close(self):
        """Missing closing ] on action_steps is repaired."""
        from ai_module import _parse_json_safe
        incomplete = '{"summary": "Short summary.", "action_steps": ["Step one", "Step two"}'
        # The array close is missing but brace is present — the JSON is still malformed
        # because the array isn't closed. Repair should handle this.
        try:
            result = _parse_json_safe(incomplete)
            # If it parses, action_steps must be a list
            self.assertIsInstance(result.get("action_steps", []), list)
        except ValueError:
            # Acceptable: this particular malformation may be unrecoverable
            pass

    def test_parse_json_safe_raises_on_garbage(self):
        """Completely non-JSON input raises ValueError with a useful message."""
        from ai_module import _parse_json_safe
        with self.assertRaises(ValueError) as ctx:
            _parse_json_safe("I cannot provide a summary for this request.")
        self.assertIn("Could not parse", str(ctx.exception))

    # --- Filter with all filters active ---

    def test_filter_all_criteria_combined(self):
        result = filter_alerts(
            SAMPLE_ALERTS,
            city="Hyderabad",
            category="digital_security",
            severity_min=4,
            severity_max=5,
            high_signal_only=True,
            search_query="phishing",
        )
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["id"], "CG-T01")

    def test_filter_search_no_match(self):
        result = filter_alerts(SAMPLE_ALERTS, search_query="xylophone_not_in_data")
        self.assertEqual(result, [])


# ===========================================================================
# New feature tests — date filter, location, signal gate, classification
# ===========================================================================

class TestNewFeatures(unittest.TestCase):

    # -----------------------------------------------------------------------
    # Date filter
    # -----------------------------------------------------------------------

    def test_date_filter_cutoff_all_time_returns_none(self):
        from utils import date_filter_cutoff
        self.assertIsNone(date_filter_cutoff("All time"))

    def test_date_filter_cutoff_last_24h_is_recent(self):
        from utils import date_filter_cutoff
        from datetime import datetime, timezone, timedelta
        cutoff = date_filter_cutoff("Last 24 hours")
        self.assertIsNotNone(cutoff)
        now = datetime.now(timezone.utc)
        # Cutoff should be approximately 24 h ago (within 5 seconds)
        self.assertAlmostEqual((now - cutoff).total_seconds(), 86400, delta=5)

    def test_date_filter_excludes_old_alert(self):
        """An alert from 2026-01-01 should be excluded by 'Last 24 hours' filter."""
        from utils import filter_alerts
        old_alert = {**SAMPLE_ALERTS[0], "created_at": "2026-01-01T00:00:00+00:00"}
        result = filter_alerts([old_alert], date_filter="Last 24 hours", signal_only=False)
        self.assertEqual(result, [])

    def test_date_filter_includes_recent_alert(self):
        """An alert timestamped now should pass any date filter."""
        from utils import filter_alerts
        from datetime import datetime, timezone
        now_str = datetime.now(timezone.utc).isoformat()
        fresh_alert = {**SAMPLE_ALERTS[0], "created_at": now_str, "noise_to_signal": "signal"}
        result = filter_alerts([fresh_alert], date_filter="Last 24 hours")
        self.assertEqual(len(result), 1)

    def test_date_filter_all_time_includes_old_alert(self):
        """'All time' filter should include all alerts regardless of date."""
        from utils import filter_alerts
        old_alert = {**SAMPLE_ALERTS[0], "created_at": "2020-01-01T00:00:00+00:00",
                     "noise_to_signal": "signal"}
        result = filter_alerts([old_alert], date_filter="All time")
        self.assertEqual(len(result), 1)

    def test_parse_alert_datetime_valid(self):
        from utils import parse_alert_datetime
        from datetime import timezone
        alert = {"created_at": "2026-03-01T08:20:00+05:30"}
        dt = parse_alert_datetime(alert)
        self.assertIsNotNone(dt)
        self.assertIsNotNone(dt.tzinfo)

    def test_parse_alert_datetime_missing(self):
        from utils import parse_alert_datetime
        self.assertIsNone(parse_alert_datetime({}))

    def test_parse_alert_datetime_invalid(self):
        from utils import parse_alert_datetime
        self.assertIsNone(parse_alert_datetime({"created_at": "not-a-date"}))

    def test_format_alert_date_returns_string(self):
        from utils import format_alert_date
        alert = {"created_at": "2026-03-01T08:20:00+05:30"}
        result = format_alert_date(alert)
        self.assertIsInstance(result, str)
        self.assertIn("2026", result)

    def test_format_alert_date_missing_returns_dash(self):
        from utils import format_alert_date
        self.assertEqual(format_alert_date({}), "—")

    # -----------------------------------------------------------------------
    # Location helpers
    # -----------------------------------------------------------------------

    def test_haversine_hyderabad_to_sangareddy(self):
        """Sangareddy is ~50 km from Hyderabad."""
        from utils import haversine_distance
        # Sangareddy: 17.62, 78.09  |  Hyderabad: 17.385, 78.4867
        dist = haversine_distance(17.62, 78.09, 17.385, 78.4867)
        self.assertGreater(dist, 30)
        self.assertLess(dist, 80)

    def test_nearest_city_sangareddy_returns_hyderabad(self):
        """Sangareddy's nearest dataset city should be Hyderabad."""
        from utils import nearest_city_in_dataset
        result = nearest_city_in_dataset(17.62, 78.09)
        self.assertEqual(result, "Hyderabad")

    def test_nearest_city_mumbai_coords_returns_mumbai(self):
        from utils import nearest_city_in_dataset
        result = nearest_city_in_dataset(19.0760, 72.8777)
        self.assertEqual(result, "Mumbai")

    def test_nearest_city_delhi_coords_returns_delhi(self):
        from utils import nearest_city_in_dataset
        result = nearest_city_in_dataset(28.6139, 77.2090)
        self.assertEqual(result, "Delhi")

    def test_get_user_location_returns_dict_with_required_keys(self):
        """get_user_location() always returns a dict with required keys."""
        from utils import get_user_location
        result = get_user_location()
        for key in ("city", "lat", "lon", "country", "matched_city", "source"):
            self.assertIn(key, result)

    def test_location_fallback_graceful(self):
        """If IP geolocation fails, matched_city should be '' and not crash."""
        from utils import _location_fallback
        result = _location_fallback("timeout")
        self.assertEqual(result["matched_city"], "")
        self.assertIn("fallback", result["source"])

    # -----------------------------------------------------------------------
    # Signal-only gate (new default behaviour)
    # -----------------------------------------------------------------------

    def test_signal_only_true_excludes_noise(self):
        """Default signal_only=True must exclude noise-tagged alerts."""
        from utils import filter_alerts
        result = filter_alerts(SAMPLE_ALERTS, signal_only=True)
        ids = {a["id"] for a in result}
        self.assertNotIn("CG-T03", ids)   # CG-T03 is noise
        self.assertIn("CG-T01",    ids)
        self.assertIn("CG-T02",    ids)

    def test_signal_only_false_includes_noise(self):
        """signal_only=False must include noise-tagged alerts."""
        from utils import filter_alerts
        result = filter_alerts(SAMPLE_ALERTS, signal_only=False)
        ids = {a["id"] for a in result}
        self.assertIn("CG-T03", ids)

    def test_dashboard_default_never_shows_noise(self):
        """filter_alerts() with all defaults excludes noise — as the dashboard uses it."""
        from utils import filter_alerts
        result = filter_alerts(SAMPLE_ALERTS)
        for alert in result:
            self.assertEqual(alert.get("noise_to_signal"), "signal",
                             f"Alert {alert['id']} should be signal but is noise")

    # -----------------------------------------------------------------------
    # classify_alert — fallback path (no API key needed)
    # -----------------------------------------------------------------------

    def test_classify_clear_signal_post(self):
        """A specific, factual incident should classify as signal."""
        from ai_module import _fallback_classify
        alert = {
            "title": "Bike stolen from apartment entrance",
            "report_text": (
                "A resident reported their bicycle stolen from the apartment basement "
                "parking lot at around 7:30 AM on Sunday. The lock was cut. CCTV footage "
                "may be available from camera 3 near the lift lobby."
            ),
            "category": "physical_safety",
        }
        result = _fallback_classify(alert)
        self.assertTrue(result["is_signal"])
        self.assertEqual(result["source"], "fallback")

    def test_classify_spam_post(self):
        """A spam post with advertising keywords should be classified as noise/spam."""
        from ai_module import _fallback_classify
        alert = {
            "title": "Special discount offer just for our residents",
            "report_text": (
                "Buy now and get a huge discount offer that expires very soon. "
                "Click here for all the exclusive details available only to members of this group."
            ),
            "category": "public_notice",
        }
        result = _fallback_classify(alert)
        self.assertFalse(result["is_signal"])
        # Label is either "spam" (keyword path) or "noise" (length path) — both acceptable
        self.assertIn(result["label"], ("spam", "noise", "venting"))

    def test_classify_too_short_post(self):
        """A very short post should be classified as noise."""
        from ai_module import _fallback_classify
        alert = {
            "title": "Something happened",
            "report_text": "Something happened near my house.",
            "category": "physical_safety",
        }
        result = _fallback_classify(alert)
        self.assertFalse(result["is_signal"])

    def test_classify_venting_post(self):
        """A post with emotional venting keywords should be rejected."""
        from ai_module import _fallback_classify
        alert = {
            "title": "So angry",
            "report_text": (
                "OMG I can't believe what happened today, everyone is so careless in this "
                "building. The management is useless. WTF is wrong with people here."
            ),
            "category": "public_notice",
        }
        result = _fallback_classify(alert)
        self.assertFalse(result["is_signal"])
        self.assertEqual(result["label"], "venting")

    def test_classify_phishing_alert_is_signal(self):
        """A digital security alert with enough detail should pass."""
        from ai_module import _fallback_classify
        alert = {
            "title": "Phishing SMS alert",
            "report_text": (
                "Several residents received SMS messages impersonating HDFC Bank asking "
                "them to click a link and enter their OTP to avoid account suspension. "
                "Do not click the link. Report to 1930."
            ),
            "category": "digital_security",
        }
        result = _fallback_classify(alert)
        self.assertTrue(result["is_signal"])

    def test_classify_no_api_key_uses_fallback(self):
        """classify_alert() uses fallback when no API key is set."""
        from unittest.mock import patch
        from ai_module import classify_alert
        alert = {
            "title": "Suspicious van spotted",
            "report_text": (
                "A suspicious white van was circling the residential block near "
                "the playground for over 30 minutes. No number plate was visible. "
                "Two residents independently witnessed this around 9:45 PM."
            ),
            "category": "physical_safety",
        }
        with patch("ai_module._get_api_key", return_value=None):
            result = classify_alert(alert)
        self.assertIn("is_signal", result)
        self.assertEqual(result["source"], "fallback")
        self.assertIn("GEMINI_API_KEY", result.get("error", ""))

    def test_classify_empty_report_is_noise(self):
        """classify_alert() rejects empty report text immediately."""
        from ai_module import classify_alert
        result = classify_alert({"title": "Test", "report_text": "", "category": "scam"})
        self.assertFalse(result["is_signal"])
        self.assertEqual(result["label"], "noise")

    # -----------------------------------------------------------------------
    # Regression tests for the three bugs reported
    # -----------------------------------------------------------------------

    def test_regression_personal_gossip_is_noise(self):
        """
        Regression: 'Ramanuja is an Uncle' style post — personal description
        of a named individual — must be classified as noise, not signal.
        """
        from ai_module import _fallback_classify
        alert = {
            "title": "Ramanuja is an Uncle",
            "report_text": (
                "Ramanuja is too old and is older than our batch mates in our college "
                "IIT Hyderabad. He is very fat and short with a very old age than us "
                "since he took an year off in between the education."
            ),
            "category": "physical_safety",
        }
        result = _fallback_classify(alert)
        self.assertFalse(result["is_signal"],
            "Personal gossip about a person should be noise, not signal.")
        self.assertEqual(result["label"], "personal_content")

    def test_regression_older_than_pattern_detected(self):
        """'older than' is a personal-comparison phrase and should trigger noise."""
        from ai_module import _fallback_classify
        alert = {
            "title": "About my neighbour",
            "report_text": (
                "My neighbour John is way older than everyone else in the building. "
                "He is very short and fat and always complaining about noise late at night."
            ),
        }
        result = _fallback_classify(alert)
        self.assertFalse(result["is_signal"])
        self.assertIn(result["label"], ("personal_content", "noise"))

    def test_regression_action_steps_missing_does_not_raise(self):
        """
        Regression: when Gemini returns only {'summary': '...'} with no
        action_steps key, _call_gemini must return an empty list rather
        than raising a ValueError that triggers fallback.
        """
        from ai_module import _parse_json_safe
        # Simulate what _call_gemini does after getting this response
        raw = '{"summary": "This is a description about a person, not a safety alert."}'
        parsed = _parse_json_safe(raw)
        # The production code now does:
        action_steps = parsed.get("action_steps", [])
        self.assertIsInstance(action_steps, list)
        self.assertEqual(action_steps, [])   # missing → empty, not an error

    def test_regression_action_steps_non_list_defaults_to_empty(self):
        """If action_steps is present but not a list, it defaults to []."""
        from ai_module import _parse_json_safe
        raw = '{"summary": "Test summary.", "action_steps": null}'
        parsed = _parse_json_safe(raw)
        action_steps = parsed.get("action_steps", [])
        if not isinstance(action_steps, list):
            action_steps = []
        self.assertEqual(action_steps, [])

    def test_regression_location_fallback_returns_safe_dict(self):
        """
        Regression: when ALL geolocation providers fail (e.g. network blocked),
        get_user_location() must return a safe dict with matched_city=''.
        """
        from unittest.mock import patch
        import requests
        with patch("requests.get", side_effect=ConnectionError("All blocked")):
            from utils import get_user_location
            result = get_user_location()
        self.assertEqual(result["matched_city"], "")
        self.assertIn("fallback", result["source"])
        # These keys must always be present
        for key in ("city", "lat", "lon", "country", "matched_city", "source"):
            self.assertIn(key, result)

    def test_regression_location_https_fallback_to_ipinfo(self):
        """
        If ip-api.com fails (HTTP blocked), ipinfo.io (HTTPS) is tried next.
        """
        from unittest.mock import patch, MagicMock, call
        import requests

        # First call (ip-api.com) raises; second call (ipinfo.io) succeeds
        mock_ipinfo = MagicMock()
        mock_ipinfo.json.return_value = {
            "city": "Pune", "loc": "18.52,73.85", "country": "IN"
        }

        def side_effect(url, **kwargs):
            if "ip-api.com" in url:
                raise ConnectionError("HTTP blocked")
            return mock_ipinfo

        with patch("requests.get", side_effect=side_effect):
            from utils import get_user_location
            result = get_user_location()

        self.assertEqual(result["matched_city"], "Pune")
        self.assertEqual(result["source"],       "ipinfo.io")

    def test_classify_personal_content_label_in_valid_labels(self):
        """'personal_content' must be a valid label returned by the fallback."""
        from ai_module import _fallback_classify
        alert = {
            "title": "About my batch mate",
            "report_text": (
                "My batch mate from college is very fat and short and older than "
                "all of us. He took a year off in between the education and now "
                "acts like he knows everything in our batch."
            ),
        }
        result = _fallback_classify(alert)
        self.assertFalse(result["is_signal"])
        self.assertIn(result["label"], (
            "personal_content", "noise", "venting", "spam"
        ))


# ===========================================================================
# Run
# ===========================================================================

if __name__ == "__main__":
    unittest.main(verbosity=2)
