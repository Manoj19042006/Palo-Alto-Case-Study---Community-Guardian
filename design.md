# Community Guardian — Design Documentation

> **Scenario:** Community Safety & Digital Wellness  
> **Stack:** Python · Streamlit · Google Gemini 2.5 Flash · JSON · unittest

---

## 1. Problem Statement

Residents receive safety alerts across fragmented channels — WhatsApp groups,
RWA notice boards, social media — but most of it is noise: emotional venting,
duplicate posts, personal gossip, and unverified rumours. The genuinely
important alerts (a phishing scam, a theft, a suspicious vehicle) get buried.

This creates two real problems:

- **Alert fatigue** — people stop paying attention entirely.
- **Undifferentiated anxiety** — unverified emotional posts cause worry without
  any actionable path forward.

**Community Guardian** solves this by acting as an intelligent curation layer:
it blocks noise before publishing, auto-detects the user's location, and
delivers calm, audience-specific summaries with concrete action steps.

---

## 2. Architecture

The system is split into three layers. No layer imports from a layer above it,
making each independently testable and replaceable.

```
┌──────────────────────────────────────────────────────────┐
│                  app.py  (Streamlit UI)                  │
│        Sidebar · Dashboard · Add Alert · Manage          │
└────────────────────┬─────────────────────────────────────┘
                     │
┌────────────────────▼─────────────────────────────────────┐
│                  utils.py  (Business Logic)               │
│   filter_alerts · validate · build · location · date     │
└──────────┬───────────────────────────────┬───────────────┘
           │                               │
┌──────────▼──────────┐       ┌────────────▼──────────────┐
│    ai_module.py     │       │     data/alerts.json       │
│  classify_alert()   │       │   100 synthetic records     │
│  summarize_alert()  │       └───────────────────────────┘
│  Rule-based fallback│
└──────────┬──────────┘
           │
┌──────────▼──────────┐     ┌─────────────────────────────┐
│  Google Gemini API  │     │   IP Geolocation Chain       │
│  Gemini 2.5 Flash   │     │  ip-api.com → ipinfo.io      │
│  (+ fallback rules) │     │  → ipapi.co  (HTTPS backup)  │
└─────────────────────┘     └─────────────────────────────┘
```

### Layer responsibilities

| File | Owns |
|---|---|
| `app.py` | UI only — three pages, session state, rendering |
| `utils.py` | Filtering, validation, CRUD, location detection, date helpers |
| `ai_module.py` | Both AI tasks (classify + summarise) and their fallbacks |
| `data/alerts.json` | Flat-file store — seed data and live write target |
| `tests/test_app.py` | 96 unit tests, all run offline with mocks |

---

## 3. Tech Stack

| Component | Technology | Rationale |
|---|---|---|
| Language | Python 3.11+ | Type hints, native timezone-aware datetime |
| UI | Streamlit 1.35+ | Rapid prototyping, session state and forms built-in |
| AI Model | Gemini 2.5 Flash | Low latency, enforces JSON output via `response_mime_type` |
| AI Client | `google-generativeai` | Official SDK, model name is a single swappable constant |
| Data Store | JSON flat-file | Zero infrastructure, human-readable, fits prototype scope |
| Config | `python-dotenv` | Key in `.env` only, re-read on every call (`override=True`) |
| Geolocation | ip-api.com / ipinfo.io / ipapi.co | Free, no API key, three-provider HTTPS fallback chain |
| Data frames | pandas | Alert table with severity colour-mapping |
| Testing | `unittest` (stdlib) | Zero extra dependencies, all network calls mocked |

```
# requirements.txt
streamlit>=1.35.0
google-generativeai>=0.7.0
python-dotenv>=1.0.0
pandas>=2.0.0
```

---

## 4. Data Flow

### Dashboard (read path)
```
get_user_location()        ← ip-api.com → ipinfo.io → ipapi.co
  └─► matched_city = "Hyderabad"  (or nearest city in dataset)

load_alerts(data/alerts.json)
  └─► st.session_state.alerts

filter_alerts(alerts,
  signal_only  = True,    ← noise always excluded from dashboard
  city         = auto-detected (user can override),
  date_filter  = "All time" | "Last 24h" | "Last week" | ...,
  category     = ...,
  audience     = ...,
  sev_range    = (1, 5),
  search_query = ""
)
  └─► Render: metrics row + table + detail card
```

### Submit alert (write path + AI noise gate)
```
validate_new_alert(form_data)     ← title, severity, category, report_text
  └─► errors? show banners and stop

build_new_alert(form_data)
  └─► new alert dict with UUID id + UTC timestamp

classify_alert(alert)             ← AI gate BEFORE saving
  ├─► Gemini (temp=0.1)  →  { is_signal, label, reason }
  └─► fallback: keyword rules + personal-content patterns

  is_signal = True?
    YES → save_alerts()  +  show success + label + reason
    NO  → discard        +  show rejection reason + prompt revision
```

### AI summarisation (on-demand)
```
User clicks "Generate Summary & Action Steps"
  └─► summarize_alert(full_alert_dict)
        └─► _build_prompt(alert)
              system_prompt: audience tone + severity guidance
              user_prompt:   title | category | location | severity
                             urgency | source | verification | audience
                             user-submitted steps | full report text

        └─► Gemini (temp=0.3, max_tokens=1024, mime=application/json)
              └─► _parse_json_safe(raw)
                    Pass 1: direct json.loads()
                    Pass 2: regex-extract first { } block
                    Pass 3: close unterminated strings / brackets
                    Missing action_steps → default to []

        └─► Cache in st.session_state.ai_cache[alert_id]
              └─► Render: source badge + summary + action steps
```

---

## 5. AI Design

### Two independent tasks

| | Classification | Summarisation |
|---|---|---|
| **When** | Every submission (gate) | On-demand button |
| **Input** | Full alert dict | Full alert dict |
| **Output** | `is_signal`, `label`, `reason` | `summary`, `action_steps` |
| **Temperature** | 0.1 (deterministic) | 0.3 (factual) |
| **Max tokens** | 256 | 1024 |
| **Fallback** | Keyword + personal-content rules | Keyword-matched canned steps |
| **Cached** | No (one-shot gate) | Yes |

### Classification prompt design
The noise criteria are more detailed than the signal criteria — the model needs
more guidance on what to reject. Key design decisions:

- **Personal-content criterion** — posts describing a named person's appearance,
  age, weight, education, or relationships are always noise, regardless of length.
  *(This catches gossip posts that passed a permissive default prompt.)*
- **Safety-officer test** — *"Would a community safety officer act on this
  to protect residents? If NO, it is noise."*
- **Rule-based fallback** — `_PERSONAL_CONTENT_PATTERNS` list checks phrases
  like "is too old", "older than", "batch mate", "took an year off" before any
  network call is made.

### Summarisation prompt design
The full alert dict — not just `report_text` — is passed so the model can
produce location-specific, severity-calibrated, audience-appropriate output.

**Audience tone** injected per `audience_tag`:
- `elderly_user` → plain language, short sentences, numbered steps, no jargon
- `remote_worker` → technical steps (VPN, 2FA, router firmware)
- `neighborhood_group` → community-coordination framing

**Severity calibration** injected per level 1–5:
- Level 1 → *"Reassure the reader, no immediate action needed"*
- Level 5 → *"Recommend immediate protective actions calmly and clearly"*

### Fallback transparency
Every AI response shows a clear source badge:
- 🤖 **Gemini AI** — model responded successfully
- 🔧 **Rule-based Fallback** — with the actual error reason shown, never a
  generic "something went wrong"

---

## 6. Key Features

| Feature | Description |
|---|---|
| Auto location detection | IP geolocation with three-provider HTTPS fallback chain |
| Nearest-city fallback | Haversine distance when detected city has no data (e.g. Sangareddy → Hyderabad) |
| Date filter | Last 24h / 2 days / week / month / All time |
| Signal-only dashboard | Noise posts never shown — blocked at submission and at filter level |
| AI noise gate | Classify every submission before saving — rejection shows label + reason |
| AI summarisation | On-demand Gemini summary + action steps from full alert context |
| Audience-aware summaries | Tone and language adapt to elderly / remote worker / neighbourhood group |
| Rule-based fallbacks | Both AI tasks have keyword-rule fallbacks; app works without API key |
| Status management | Verified / dismissed / pending with audit trail effect on signal tag |
| Input validation | Title, severity (1–5), category, report text — centralised, testable |
| 96 unit tests | All run offline — Gemini and network calls are mocked |

---

## 7. Security & Privacy

| Concern | Mitigation |
|---|---|
| API key exposure | In `.env` only; re-read on every call; never in source or logs |
| `.env` in git | `.env` in `.gitignore`; `.env.example` committed instead |
| User-submitted content | Rendered with `st.write()` (HTML-escaped); no `eval()`/`exec()` |
| XSS via `st.markdown` | `unsafe_allow_html=True` used only on server-controlled templates |
| Location data | City/neighbourhood sent to Gemini API — acknowledged tradeoff (see below) |
| Privacy modes | `can_view_alert()` hierarchy implemented; needs login layer to enforce |

---

## 8. Known Tradeoffs

| Decision | Tradeoff |
|---|---|
| Flat JSON store | No concurrent-write safety. Migrate to SQLite / PostgreSQL for production. |
| On-demand AI | User controls when Gemini is invoked — reduces cost but summaries aren't automatic |
| IP geolocation | City-level accuracy; user IP sent to third-party provider |
| Location in Gemini prompts | City/neighbourhood text sent to Google. Production fix: on-device model (Gemma via Ollama) |
| No authentication | Privacy hierarchy (`public_digest` / `private_circle` / `guardian_only`) is fully implemented in `utils.py` but viewer role is hardcoded to `"public"` — requires a login layer to activate |
| Classification is not perfect | Sufficiently detailed fictitious reports can still pass the AI gate. Human moderation via Manage Alerts provides the correction path. |

---

## 9. Testing Strategy

All 96 tests run offline — Gemini and geolocation calls are replaced with
`unittest.mock.patch` stubs. No API key or internet connection required.

| Class | Count | Covers |
|---|---|---|
| `TestHappyPath` | 22 | Load, filter (all dimensions), save/reload, status update, privacy checks, AI fallback, keyword steps |
| `TestEdgeCases` | 43 | Missing file, invalid JSON, severity OOB, invalid category, missing fields, JSON repair (truncated / missing brace / garbage), audience combinations, date cutoff math, user-step parsing |
| `TestNewFeatures` | 31 | Signal gate, date filter, haversine, nearest-city, geolocation chain, classify fallback (all rule paths), regression for gossip post, missing `action_steps` key, HTTPS location fallback |

```bash
python -m unittest tests/test_app.py -v
```

---

## 10. Future Enhancements

### Short-term
- **Browser Geolocation API** — consent-based, GPS-accurate, eliminates IP-to-third-party concern
- **Semantic duplicate detection** — Gemini embeddings to auto-merge near-identical alerts
- **Daily digest email** — scheduled Gemini summary of the day's signal alerts per city

### Medium-term
- **Role-based authentication** — JWT / OAuth2 to activate the existing privacy hierarchy
- **Geospatial heatmap** — Leaflet / Folium map with incident density overlay
- **Multilingual summaries** — Hindi, Telugu, Kannada, Tamil via Gemini's multilingual support
- **Trend detection** — time-series spike detection for emerging threats in a neighbourhood

### Long-term
- **On-device model** — Gemma 2B via Ollama eliminates all data leaving the device
- **Real-time ingestion** — WhatsApp Business API or local police bulletin RSS feeds
- **AI feedback loop** — thumbs-up/down on outputs feeds a fine-tuning dataset
- **DPDP Act 2023 compliance** — consent collection, data deletion on request, breach notification

---

## 11. File Structure

```
community-guardian/
├── app.py               # Streamlit UI — Dashboard, Add Alert, Manage Alerts
├── ai_module.py         # classify_alert(), summarize_alert(), rule-based fallbacks
├── utils.py             # filter_alerts(), location detection, validation, date helpers
├── data/
│   └── alerts.json      # 100 synthetic alerts — seed data and live write target
├── tests/
│   └── test_app.py      # 96 unit tests across 3 classes
├── requirements.txt     # 4 dependencies
├── .env.example         # API key template
├── README.md            # Setup, run, test, tradeoffs
└── DESIGN.md            # This document
```
