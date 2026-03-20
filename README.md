# Community Guardian

**Candidate Name:** Manoj Thurupalli  
**Scenario Chosen:** 3 — Community Safety & Digital Wellness  
**Estimated Time Spent:** 5 hours

**Youtube Link:** https://youtu.be/58QV9HET8ug
---

## Quick Start

### Prerequisites

- Python 3.11+
- A Google Gemini API key — get one free at [https://aistudio.google.com/app/apikey](https://aistudio.google.com/app/apikey)

```
pip install -r requirements.txt
cp .env.example .env
# Open .env and paste your GEMINI_API_KEY
```

### Run Commands

```bash
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
streamlit run app.py
```

Open `http://localhost:8501` in your browser. The app auto-detects your city via IP geolocation and pre-filters alerts to your location.

### Test Commands

```bash
python -m unittest tests/test_app.py -v
```

No API key or internet connection required — all 96 tests run offline using mocks.

---

## AI Disclosure

**Did you use an AI assistant?** Yes — Claude (Anthropic) was used as a coding assistant throughout development.

**How did you verify the suggestions?**  
Every generated function was reviewed line-by-line before acceptance. Logic was verified by writing unit tests against it — if the test failed or the behaviour was subtly wrong, the code was corrected. For example, the `haversine_distance()` function was verified by manually computing the Hyderabad–Sangareddy distance (~50 km) and confirming the function returned the expected nearest city. The AI classification prompt was verified empirically by submitting test posts (including the  random "nekjnklnklfnlwmflkwkmflwm" post) and confirming the model's decision matched the expected label.

**One example of a suggestion rejected or changed:**  
The initial classification prompt used a permissive default — *"if in doubt, classify as signal"* — which caused personal gossip posts about named individuals to pass as signal. I rejected this default entirely and replaced it with an explicit personal-content criterion and a safety-officer decision test: *"Would a community safety officer act on this information to protect residents? If NO, it is noise."* The permissive default was retained only for genuinely ambiguous safety-related content, not for personal or off-topic posts.

---

## Tradeoffs & Prioritization

**What did you cut to stay within the 4–6 hour limit?**

- **Real-time data ingestion** — no live scraping or API connectors to WhatsApp / Twitter. The app uses a static 24-record synthetic JSON dataset. This was the right cut: the task explicitly says synthetic data only, and the filtering/AI logic works identically on live data once a connector is added.
- **Authentication and role enforcement** — the privacy hierarchy (`public_digest` / `private_circle` / `guardian_only`) is fully implemented in `utils.py` with `can_view_alert()`, but the viewer role is hardcoded to `"public"` in the UI. A login layer (JWT / OAuth2) would activate it without changing the underlying logic.
- **Geospatial map view** — a Leaflet or Folium pin map would improve contextual relevance but is pure UI polish. The city/neighbourhood filter covers the core use case within the time budget.
- **Persistent AI cache** — AI summaries are cached in Streamlit session state only. They are regenerated on page refresh. A Redis or SQLite-backed cache would make them durable across sessions.

**What would you build next if you had more time?**

1. **Browser Geolocation API** — replace IP geolocation (city-level, third-party) with a consent-based browser call for GPS accuracy and no data-egress privacy concern.
2. **Semantic duplicate detection** — use Gemini embeddings to cluster near-duplicate alert submissions (cosine similarity > 0.92) and auto-merge them, reducing dashboard volume without losing information.
3. **Daily digest email** — scheduled job that groups the day's signal alerts by city, generates a single-paragraph Gemini summary, and sends it to subscribed residents.
4. **On-device model** — replace Gemini API calls with Gemma 2B via Ollama for `private_circle` and `guardian_only` alerts, eliminating all data leaving the device.
5. **Multilingual summaries** — Hindi, Telugu, Kannada, and Tamil output for regional language users, using Gemini's multilingual capability.

**Known limitations:**

- **IP geolocation accuracy** — detection is city-level only (±50 km). Users in smaller towns see alerts from the nearest dataset city, not their exact location.
- **Flat JSON store** — not safe for concurrent writes. Last-write-wins if two users submit alerts simultaneously. Acceptable for a single-user prototype; requires SQLite or PostgreSQL for production.
- **No authentication** — all alerts are visible to all users in the current prototype. The privacy logic exists but is not enforced until a login layer is added.
