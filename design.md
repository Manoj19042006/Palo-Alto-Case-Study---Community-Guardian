# Community Guardian — Design Document

---

## 1. Architecture Overview

```
┌──────────────────────────────────────────────────────────────────┐
│                         Streamlit UI (app.py)                    │
│  ┌────────────┐  ┌─────────────────┐  ┌────────────────────────┐│
│  │  Sidebar   │  │  Dashboard Page │  │  Add/Manage Pages      ││
│  │  Filters   │  │  Alert Table    │  │  Form + Status Update  ││
│  │  Toggle    │  │  Detail + AI    │  │                        ││
│  └─────┬──────┘  └────────┬────────┘  └────────────┬───────────┘│
└────────│─────────────────│───────────────────────────│────────────┘
         │                 │                           │
         ▼                 ▼                           ▼
┌──────────────────────────────────────────────────────────────────┐
│                          utils.py                                │
│  load_alerts()  filter_alerts()  validate_new_alert()            │
│  build_new_alert()  update_alert_status()  can_view_alert()      │
└─────────────────────────┬────────────────────────────────────────┘
                          │
           ┌──────────────┴──────────────┐
           │                             │
           ▼                             ▼
┌─────────────────────┐       ┌──────────────────────┐
│     ai_module.py    │       │    data/alerts.json   │
│                     │       │  (24 synthetic alerts)│
│  summarize_alert()  │       └──────────────────────┘
│   ┌─────────────┐   │
│   │  Gemini API │   │  ← GEMINI_API_KEY via .env
│   └──────┬──────┘   │
│          │ fail?    │
│          ▼          │
│   ┌─────────────┐   │
│   │ Rule-based  │   │
│   │  Fallback   │   │
│   └─────────────┘   │
└─────────────────────┘
```

The architecture is deliberately layered and thin:

- **`app.py`**: UI-only. Imports from `utils` and `ai_module`. No business logic inside Streamlit callbacks.
- **`utils.py`**: Pure Python. All filtering, validation, CRUD, and privacy logic. No UI imports, no AI imports.
- **`ai_module.py`**: AI-only. Handles Gemini calls and fallback. No UI, no file I/O.
- **`data/alerts.json`**: Single source of truth for the alert store.

This separation makes each layer independently testable and replaceable.

---

## 2. Data Flow

### Read Path (Dashboard)

```
User opens app
  └─► load_alerts(data/alerts.json)
        └─► Session state: st.session_state.alerts [list of 24 dicts]
              └─► filter_alerts(alerts, category, city, severity, signal_toggle, search)
                    └─► Filtered list → rendered as DataFrame + detail cards
```

### Write Path (Add Alert)

```
User fills form → clicks Submit
  └─► validate_new_alert(form_data) → errors?
        If errors: display red error messages, stop
        If valid:
          └─► build_new_alert(form_data) → new alert dict (UUID id, current timestamp)
                └─► st.session_state.alerts.append(new_alert)
                      └─► save_alerts(alerts, data/alerts.json)
```

### AI Path (Detail View)

```
User clicks "Generate Summary & Action Steps"
  └─► summarize_alert(report_text, category)
        └─► GEMINI_API_KEY present?
              Yes: _call_gemini(report_text)
                    └─► genai.GenerativeModel.generate_content(prompt)
                          └─► Parse JSON response
                                └─► Return { summary, action_steps, source: "AI" }
              No / API error: _fallback_summarize(report_text, category)
                    └─► Extract first sentence → summary
                          └─► Keyword scan → matched action steps
                                └─► Return { summary, action_steps, source: "fallback" }
        └─► Cache result in st.session_state.ai_cache[alert_id]
              └─► Render summary card + action steps list + source badge
```

### Status Update Path

```
User selects alert + new status → clicks Update
  └─► update_alert_status(alerts, id, new_status)
        └─► Mutate alert dict in place
              └─► save_alerts() → persist to JSON
                    └─► Success toast displayed
```

---

## 3. AI Design Decisions

### Model Choice: Gemini 1.5 Flash
- Low latency (< 2 s typical), low cost
- Sufficient quality for 2–3 sentence summaries
- Supports system instructions (used to enforce JSON-only output)

### Prompt Engineering
The system prompt enforces three constraints:
1. **Factual, neutral tone** — prevents the model from adding speculation or alarm
2. **JSON-only response** — enables reliable programmatic parsing
3. **Calm framing** — reduces anxiety for end users (elderly, worried residents)

Temperature is set to `0.3` (low) to reduce hallucination and keep output consistent.

### JSON Reliability
Gemini occasionally wraps JSON in markdown code fences (` ```json`). The response parser strips these with a regex before `json.loads()`, making parsing robust. If the schema (`summary`, `action_steps`) is missing or malformed, the call raises and triggers fallback.

---

## 4. Fallback Reasoning

The rule-based fallback exists for three reasons:

1. **Reliability**: The app must be usable without an internet connection or API key.
2. **Cost control**: New users / developers can evaluate the full system without incurring API charges.
3. **Degradation UX**: Users always get *something* useful, not a blank error screen.

The fallback is keyword-based and maps common safety categories to canned, verified action steps. It is intentionally conservative — it would rather give a generic step than a wrong specific one.

Source transparency (the "🤖 Gemini AI" vs "🔧 Rule-based Fallback" badge) ensures users know the quality of the insight they are seeing.

---

## 5. Noise Filtering Logic

The `is_high_signal()` function applies two rules (both must pass):

| Rule | Condition |
|---|---|
| Not noise | `noise_to_signal != "noise"` |
| Not low-confidence | NOT (`source_reliability == "low"` AND `verification_status == "unverified"`) |

This deliberately retains alerts that are `noise_to_signal = "signal"` even if unverified, because an official notice from police (`source_reliability = "high"`) may be newly posted and not yet marked verified.

When `high_signal_only = True`, duplicates (`duplicate_of` is non-empty) are naturally excluded because they are always tagged `noise` in the dataset.

---

## 6. Privacy Architecture

Three privacy modes are supported, forming a strict hierarchy:

```
public_digest      → visible to everyone (default)
private_circle     → visible to circle_member + guardian
guardian_only      → visible to guardian only
```

In the current prototype, the viewer role is hardcoded to `"public"` (no auth). The `can_view_alert()` helper is fully implemented and returns `False` for restricted alerts. The UI displays a friendly restriction message instead of the report text.

**Production path**: Replace the hardcoded `viewer_role="public"` in `app.py` with a role resolved from a session token (e.g. JWT claim) after a login step. The privacy logic in `utils.py` is already production-ready.

---

## 7. Input Validation Strategy

Validation is centralised in `validate_new_alert()` and returns a list of error strings. This makes it:
- **Testable**: unit tests can call the validator without Streamlit
- **Reusable**: the same function could validate API requests in a future REST layer

Validated fields:

| Field | Rule |
|---|---|
| `title` | Non-empty string after strip |
| `severity` | Integer in 1–5 (inclusive) |
| `category` | Must be in `VALID_CATEGORIES` whitelist |
| `report_text` | Non-empty string after strip |

Missing fields are caught via `.get()` defaults, preventing `KeyError` exceptions.

---

## 8. Data Storage

The JSON flat-file is appropriate for this prototype because:
- No concurrent write contention (single-user Streamlit app)
- Trivial to inspect and edit manually
- No infrastructure setup required

For production with multiple users, the natural migration path is:
- SQLite → for single-server deployments
- PostgreSQL → for multi-instance deployments
- Add a `last_modified` field for optimistic concurrency control

---

## 9. Security Considerations

| Concern | Mitigation |
|---|---|
| API key exposure | `python-dotenv`; key loaded from `.env`, never in source |
| `.env` in git | Add `.env` to `.gitignore` (`.env.example` committed instead) |
| XSS in `st.markdown` | Only trusted, server-controlled strings use `unsafe_allow_html=True` |
| User-submitted data | All form fields are plain text; no eval/exec; saved as JSON strings |
| Privacy gate bypass | `can_view_alert()` evaluated server-side before rendering content |

---

## 10. Testing Strategy

Tests are in `tests/test_app.py` and use Python's built-in `unittest` (no extra test dependencies).

**Happy Path Suite (`TestHappyPath`)**:
- Verifies load, filter (by city / category / severity / signal / search), save/reload cycle, AI fallback output, status update, privacy checks.

**Edge Case Suite (`TestEdgeCases`)**:
- Missing file, invalid JSON, non-list JSON, empty dataset, invalid severity values (0, 6, string), invalid category, missing all fields, nonexistent alert ID, fallback with empty text, keyword fallback coverage, combined multi-filter, no-match search.

The fallback AI tests do not require a Gemini key — they directly test `_fallback_summarize()` and mock `_API_KEY = None` for `summarize_alert()`.
