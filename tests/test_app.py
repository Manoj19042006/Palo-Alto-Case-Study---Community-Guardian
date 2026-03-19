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
        result = filter_alerts(SAMPLE_ALERTS)
        self.assertEqual(len(result), len(SAMPLE_ALERTS))

    # --- is_high_signal ---

    def test_is_high_signal_true(self):
        self.assertTrue(is_high_signal(SAMPLE_ALERTS[0]))

    def test_is_high_signal_false_noise(self):
        self.assertFalse(is_high_signal(SAMPLE_ALERTS[2]))

    # --- Summarize (fallback path, no API key needed) ---

    def test_summarize_fallback_returns_dict(self):
        result = _fallback_summarize(
            "Multiple residents received phishing SMS messages. They were asked to click a fake link.",
            "digital_security",
        )
        self.assertIn("summary", result)
        self.assertIn("action_steps", result)
        self.assertEqual(result["source"], "fallback")
        self.assertIsInstance(result["action_steps"], list)
        self.assertGreater(len(result["action_steps"]), 0)

    def test_summarize_fallback_keyword_phishing(self):
        result = _fallback_summarize("A phishing email asked users for their password.", "digital_security")
        steps_text = " ".join(result["action_steps"]).lower()
        # Should contain account-safety advice
        self.assertTrue(
            any(kw in steps_text for kw in ["password", "two-factor", "authentication", "account"])
        )

    def test_summarize_fallback_keyword_theft(self):
        result = _fallback_summarize("A bicycle was stolen from the premises.", "physical_safety")
        steps_text = " ".join(result["action_steps"]).lower()
        self.assertTrue(
            any(kw in steps_text for kw in ["lock", "secure", "police", "report"])
        )

    def test_summarize_alert_no_api_key_returns_fallback(self):
        """summarize_alert() must return fallback when GEMINI_API_KEY is absent."""
        import ai_module
        original_key = ai_module._API_KEY
        try:
            ai_module._API_KEY = None  # Simulate missing key
            result = summarize_alert(
                "Suspicious person seen near park at night.", "physical_safety"
            )
            self.assertIn("summary", result)
            self.assertIn("action_steps", result)
            self.assertEqual(result["source"], "fallback")
        finally:
            ai_module._API_KEY = original_key

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

    # --- Fallback with empty text ---

    def test_summarize_empty_text_safe_output(self):
        result = summarize_alert("")
        self.assertIn("summary", result)
        self.assertIn("action_steps", result)
        self.assertEqual(result["source"], "fallback")

    def test_summarize_whitespace_only_text(self):
        result = summarize_alert("   \n\t  ")
        self.assertEqual(result["source"], "fallback")

    def test_fallback_unknown_keywords_uses_generic(self):
        result = _fallback_summarize("Something very ambiguous happened.", "unknown_category")
        self.assertGreater(len(result["action_steps"]), 0)
        # Generic steps should appear
        steps_text = " ".join(result["action_steps"]).lower()
        self.assertTrue(
            any(kw in steps_text for kw in ["alert", "report", "share"])
        )

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
# Run
# ===========================================================================

if __name__ == "__main__":
    unittest.main(verbosity=2)
