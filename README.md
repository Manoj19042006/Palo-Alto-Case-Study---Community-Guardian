# 🛡️ Community Guardian

> A calm, intelligent safety alert aggregator for neighbourhoods, remote workers, and elderly users.

---

## 1. Problem Understanding

Urban residents, remote workers, and elderly users are bombarded with unverified, repetitive, and anxiety-inducing safety alerts across WhatsApp groups, RWA boards, and social media. This creates **alert fatigue**: important warnings get lost in noise, and users either over-react or stop paying attention entirely.

**Community Guardian** solves this by:
- Aggregating alerts from multiple source types (community posts, official notices, digital security feeds)
- Filtering out duplicate, low-reliability, and unverified noise
- Using AI (Google Gemini) to produce calm, factual 2–3 sentence summaries
- Generating concrete, prioritised action steps for every alert
- Respecting privacy modes so sensitive alerts reach only the right audience

---

## 2. Features

| Feature | Description |
|---|---|
| **Alert Dashboard** | Filterable, searchable table of all alerts with severity colour-coding |
| **Noise-to-Signal Toggle** | One click to show only high-confidence, non-duplicate alerts |
| **Multi-filter** | Filter by city, category, and severity range simultaneously |
| **Full-text Search** | Searches both title and report text in real time |
| **AI Summarisation** | Gemini 1.5 Flash generates neutral summary + action steps on demand |
| **Rule-based Fallback** | Keyword-based fallback when AI is unavailable; always returns safe output |
| **Add Alert Form** | Validated form for community members to submit new incidents |
| **Status Management** | Update any alert to verified / pending / unverified / dismissed |
| **Privacy Modes** | `public_digest`, `private_circle`, `guardian_only` gate content display |
| **Input Validation** | Title, severity (1–5), category, and report text all validated |

---

## 3. Tech Stack

| Layer | Technology |
|---|---|
| Language | Python 3.11+ |
| UI | Streamlit |
| AI | Google Gemini 1.5 Flash (`google-generativeai`) |
| Data | JSON flat-file (synthetic dataset, 24 records) |
| Config | `python-dotenv` |
| Testing | `unittest` (stdlib) |

---

## 4. AI Integration & Fallback

### AI Path (Gemini)
When `GEMINI_API_KEY` is set and the API is reachable, clicking **"Generate Summary & Action Steps"** sends the alert's `report_text` to Gemini 1.5 Flash with a carefully crafted system prompt instructing calm, factual, JSON-only output:

```json
{
  "summary": "2–3 sentence neutral summary",
  "action_steps": ["step 1", "step 2", "step 3"]
}
```

The response is validated for schema correctness before display.

### Fallback Path (Rule-based)
If the API key is missing, the network fails, or the API returns malformed output, the system automatically falls back to a rule-based engine:

1. **Summary**: extracts and truncates the first sentence of `report_text` (≤ 180 chars).
2. **Action steps**: keyword matching on `report_text` + `category`:
   - `phishing`, `otp`, `password` → account safety steps
   - `scam`, `fraud` → financial safety steps
   - `theft`, `stolen` → physical safety steps
   - `wifi`, `network` → network security steps
   - `fire`, `flood` → emergency response steps
3. Falls back to three generic safety steps if no keywords match.

The UI always shows a badge: **🤖 Gemini AI** or **🔧 Rule-based Fallback**, so users know which path was used.

---

## 5. How to Run

### Prerequisites
- Python 3.11+
- (Optional) Google Gemini API key

### Setup

```bash
# 1. Clone / extract the project
cd community-guardian

# 2. Create a virtual environment
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Configure API key (optional — fallback works without it)
cp .env.example .env
# Edit .env and paste your GEMINI_API_KEY

# 5. Launch the app
streamlit run app.py
```

Open `http://localhost:8501` in your browser.

### Run Tests

```bash
# From the project root
python -m pytest tests/ -v
# or
python -m unittest discover -s tests -v
```

---

## 6. Example Usage

**Scenario: Elderly user worried about scam calls**

1. Open the app. The dashboard shows 24 alerts.
2. Toggle **"High-signal alerts only"** → 15 alerts remain (noise filtered out).
3. Set **Category = Scam** → 4 alerts shown.
4. Click alert `CG-019` ("OTP Fraud Targeting Senior Citizens").
5. Press **"✨ Generate Summary & Action Steps"**.
6. Gemini returns:
   - *Summary*: "Elderly residents in Pune are receiving fraudulent calls from individuals posing as bank officials requesting OTP codes. No money should be transferred or OTPs shared under any circumstances."
   - *Action Steps*: Never share OTP with anyone. Call your bank directly to verify. Report to cybercrime helpline 1930.

**Scenario: Guardian verifies a community alert**

1. Navigate to **🔧 Manage Alerts**.
2. Select alert `CG-001` (bike theft, currently *unverified*).
3. Change status to **verified** → reliability auto-upgrades to `high`, noise flag becomes `signal`.
4. Alert now appears in high-signal view.

---

## 7. Tradeoffs

| Decision | Tradeoff |
|---|---|
| Flat JSON file instead of a database | Simpler setup and portability; not suitable for concurrent writes or large datasets |
| On-demand AI (button click, not auto) | Reduces API costs and latency; users control when AI is invoked |
| Gemini 1.5 Flash | Fast and cheap; less capable than Pro for nuanced analysis |
| No authentication | Simpler prototype; in production, viewer roles (public/circle/guardian) must be enforced server-side |
| Streamlit (no React) | Fast iteration; limited component flexibility and stateful UI patterns |
| Fallback always available | Ensures the app is always useful, even offline or without an API key |

---

## 8. Future Improvements

- **Real-time ingestion**: WebSocket or polling connector to WhatsApp Business API, Twitter/X, or local police feeds.
- **Duplicate detection**: Semantic similarity (embeddings) to auto-cluster near-duplicate alerts.
- **Geospatial view**: Leaflet/Folium map with alert pins, heatmap of incident density.
- **Push notifications**: Alert digest email or SMS via Twilio for subscribed users.
- **Role-based access**: Proper auth (OAuth2 / magic link) to enforce `private_circle` and `guardian_only` privacy modes.
- **Trend analysis**: Time-series chart of alert volume by category to surface emerging threats.
- **Multi-language support**: Translate alerts and summaries for regional language users (Hindi, Telugu, Kannada, etc.).
- **Feedback loop**: Thumbs-up/down on AI summaries to improve prompt quality over time.
