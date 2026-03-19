"""
app.py — Community Guardian: Streamlit UI
"""

import streamlit as st
import pandas as pd
from datetime import datetime

from utils import (
    load_alerts,
    save_alerts,
    filter_alerts,
    validate_new_alert,
    build_new_alert,
    update_alert_status,
    can_view_alert,
    privacy_message,
    severity_badge,
    status_badge,
    VALID_CATEGORIES,
    SEVERITY_LABELS,
    PRIVACY_LABELS,
)
from ai_module import summarize_alert

# ---------------------------------------------------------------------------
# Page config
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="Community Guardian",
    page_icon="🛡️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ---------------------------------------------------------------------------
# Custom CSS
# ---------------------------------------------------------------------------

st.markdown(
    """
    <style>
    /* Header bar */
    .cg-header {
        background: linear-gradient(135deg, #1a237e 0%, #283593 100%);
        padding: 1.2rem 2rem;
        border-radius: 12px;
        color: white;
        margin-bottom: 1.5rem;
    }
    .cg-header h1 { margin: 0; font-size: 2rem; }
    .cg-header p  { margin: 0.3rem 0 0 0; opacity: 0.85; font-size: 0.95rem; }

    /* Alert cards */
    .alert-card {
        border-left: 5px solid #1a237e;
        background: #f8f9ff;
        padding: 1rem 1.2rem;
        border-radius: 0 8px 8px 0;
        margin-bottom: 0.8rem;
    }
    .alert-card.sev-4, .alert-card.sev-5 { border-color: #c62828; background: #fff8f8; }
    .alert-card.sev-3                    { border-color: #e65100; background: #fff9f4; }
    .alert-card.sev-2                    { border-color: #f9a825; background: #fffdf0; }
    .alert-card.sev-1                    { border-color: #2e7d32; background: #f4fff4; }

    /* AI badge */
    .badge-ai       { background:#e3f2fd; color:#0d47a1; padding:2px 8px; border-radius:12px; font-size:0.75rem; }
    .badge-fallback { background:#fce4ec; color:#880e4f; padding:2px 8px; border-radius:12px; font-size:0.75rem; }

    /* Metric cards */
    div[data-testid="metric-container"] {
        background: #f0f2f8;
        border-radius: 8px;
        padding: 0.4rem 0.6rem;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# ---------------------------------------------------------------------------
# Session state
# ---------------------------------------------------------------------------

if "alerts" not in st.session_state:
    st.session_state.alerts = load_alerts()

if "ai_cache" not in st.session_state:
    st.session_state.ai_cache: dict[str, dict] = {}

# ---------------------------------------------------------------------------
# Sidebar — Filters
# ---------------------------------------------------------------------------

with st.sidebar:
    st.image(
        "https://img.icons8.com/fluency/96/shield.png",
        width=60,
    )
    st.title("🛡️ Community Guardian")
    st.caption("Your local safety intelligence hub")
    st.divider()

    # --- Noise filter toggle ---
    st.subheader("📡 Signal Quality")
    high_signal_only = st.toggle(
        "High-signal alerts only",
        value=False,
        help="Hides noisy, low-reliability, and unverified duplicates.",
    )
    st.divider()

    # --- Text search ---
    st.subheader("🔍 Search")
    search_query = st.text_input(
        "Search alerts",
        placeholder="e.g. phishing, bike theft…",
        label_visibility="collapsed",
    )
    st.divider()

    # --- Filters ---
    st.subheader("🎛️ Filters")

    cities = sorted(
        {a.get("location_city", "") for a in st.session_state.alerts if a.get("location_city")}
    )
    selected_city = st.selectbox("City", ["All cities"] + cities)
    if selected_city == "All cities":
        selected_city = None

    selected_category = st.selectbox(
        "Category",
        ["All categories"] + VALID_CATEGORIES,
        format_func=lambda x: x.replace("_", " ").title() if x != "All categories" else x,
    )
    if selected_category == "All categories":
        selected_category = None

    sev_range = st.slider("Severity range", min_value=1, max_value=5, value=(1, 5))
    st.divider()

    # --- Navigation ---
    st.subheader("📌 Navigation")
    page = st.radio(
        "Go to",
        ["📊 Dashboard", "➕ Add Alert", "🔧 Manage Alerts"],
        label_visibility="collapsed",
    )

# ---------------------------------------------------------------------------
# Header
# ---------------------------------------------------------------------------

st.markdown(
    """
    <div class="cg-header">
        <h1>🛡️ Community Guardian</h1>
        <p>Aggregated local safety & digital security alerts — filtered, calm, actionable.</p>
    </div>
    """,
    unsafe_allow_html=True,
)

# ---------------------------------------------------------------------------
# Apply filters
# ---------------------------------------------------------------------------

filtered = filter_alerts(
    st.session_state.alerts,
    category=selected_category,
    city=selected_city,
    severity_min=sev_range[0],
    severity_max=sev_range[1],
    high_signal_only=high_signal_only,
    search_query=search_query,
)

# ---------------------------------------------------------------------------
# Page: DASHBOARD
# ---------------------------------------------------------------------------

if page == "📊 Dashboard":

    # --- Top metrics ---
    total = len(st.session_state.alerts)
    visible = len(filtered)
    high_sev = sum(1 for a in filtered if int(a.get("severity", 1)) >= 4)
    signal_count = sum(1 for a in st.session_state.alerts if a.get("noise_to_signal") == "signal")

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Total Alerts", total)
    col2.metric("Showing", visible)
    col3.metric("High Severity (≥4)", high_sev)
    col4.metric("Signal Alerts", signal_count)

    st.divider()

    if not filtered:
        st.info("ℹ️ No alerts match your current filters. Try adjusting the sidebar options.")
        st.stop()

    # --- Alerts table (summary) ---
    st.subheader(f"📋 Alerts ({visible})")

    table_data = []
    for a in filtered:
        table_data.append(
            {
                "ID": a.get("id", ""),
                "Title": a.get("title", ""),
                "Category": a.get("category", "").replace("_", " ").title(),
                "City": a.get("location_city", ""),
                "Severity": a.get("severity", 1),
                "Status": a.get("verification_status", ""),
                "Signal": a.get("noise_to_signal", "").upper(),
                "Privacy": PRIVACY_LABELS.get(a.get("privacy_mode", ""), ""),
            }
        )

    df = pd.DataFrame(table_data)

    # Colour-map severity column
    def colour_severity(val):
        c = {1: "#d4edda", 2: "#fff3cd", 3: "#fde8d3", 4: "#f8d7da", 5: "#f5c6cb"}
        return f"background-color: {c.get(val, 'white')}"

    st.dataframe(
        df.style.applymap(colour_severity, subset=["Severity"]),
        use_container_width=True,
        hide_index=True,
    )

    st.divider()

    # --- Alert detail cards ---
    st.subheader("🔎 Alert Details")

    alert_ids = [a.get("id", "") for a in filtered]
    selected_id = st.selectbox("Select an alert to inspect", alert_ids)

    chosen = next((a for a in filtered if a.get("id") == selected_id), None)

    if chosen:
        sev = int(chosen.get("severity", 1))
        sev_cls = f"sev-{sev}"

        st.markdown(
            f"""
            <div class="alert-card {sev_cls}">
                <strong>{chosen.get('title', 'Untitled')}</strong><br/>
                <small>
                    🏙️ {chosen.get('location_city', '—')} &nbsp;|&nbsp;
                    📁 {chosen.get('category', '—').replace('_', ' ').title()} &nbsp;|&nbsp;
                    {severity_badge(sev)} &nbsp;|&nbsp;
                    {status_badge(chosen.get('verification_status', ''))} &nbsp;|&nbsp;
                    {PRIVACY_LABELS.get(chosen.get('privacy_mode', ''), '')}
                </small>
            </div>
            """,
            unsafe_allow_html=True,
        )

        # Privacy gate
        if not can_view_alert(chosen, viewer_role="public"):
            st.warning(privacy_message(chosen))
        else:
            with st.expander("📄 Full Report Text", expanded=True):
                st.write(chosen.get("report_text", "No text available."))

            # --- AI Summary ---
            st.subheader("🤖 AI Insights")
            alert_id = chosen.get("id", "")

            col_btn, col_src = st.columns([3, 1])
            with col_btn:
                run_ai = st.button(
                    "✨ Generate Summary & Action Steps",
                    key=f"ai_{alert_id}",
                )

            if run_ai or alert_id in st.session_state.ai_cache:
                if run_ai:
                    with st.spinner("Thinking…"):
                        result = summarize_alert(
                            chosen.get("report_text", ""),
                            chosen.get("category", ""),
                        )
                    st.session_state.ai_cache[alert_id] = result

                cached = st.session_state.ai_cache.get(alert_id, {})
                src = cached.get("source", "fallback")
                badge_cls = "badge-ai" if src == "AI" else "badge-fallback"
                badge_label = "🤖 Gemini AI" if src == "AI" else "🔧 Rule-based Fallback"

                st.markdown(
                    f'<span class="{badge_cls}">{badge_label}</span>',
                    unsafe_allow_html=True,
                )

                col_sum, col_act = st.columns(2)
                with col_sum:
                    st.markdown("**📝 Summary**")
                    st.info(cached.get("summary", "—"))

                with col_act:
                    st.markdown("**✅ Action Steps**")
                    for step in cached.get("action_steps", []):
                        st.markdown(f"- {step}")

            # Dataset-provided action steps
            if chosen.get("action_steps"):
                with st.expander("📋 Dataset Action Steps"):
                    for step in chosen.get("action_steps", []):
                        st.markdown(f"- {step}")

# ---------------------------------------------------------------------------
# Page: ADD ALERT
# ---------------------------------------------------------------------------

elif page == "➕ Add Alert":
    st.subheader("➕ Submit a New Alert")
    st.caption("All fields are validated before saving.")

    with st.form("add_alert_form", clear_on_submit=True):
        f_title = st.text_input("Title *", placeholder="Brief description of the incident")
        f_report = st.text_area(
            "Report Text *",
            placeholder="Describe what happened in detail…",
            height=150,
        )

        col1, col2 = st.columns(2)
        with col1:
            f_category = st.selectbox(
                "Category *",
                VALID_CATEGORIES,
                format_func=lambda x: x.replace("_", " ").title(),
            )
            f_city = st.text_input("City *", placeholder="e.g. Hyderabad")
            f_neighborhood = st.text_input("Neighborhood", placeholder="e.g. Banjara Hills")

        with col2:
            f_severity = st.slider("Severity *", min_value=1, max_value=5, value=3)
            f_privacy = st.selectbox(
                "Privacy Mode",
                list(PRIVACY_LABELS.keys()),
                format_func=lambda x: PRIVACY_LABELS[x],
            )
            f_audience = st.selectbox(
                "Audience",
                ["neighborhood_group", "remote_worker", "elderly_user", "general"],
                format_func=lambda x: x.replace("_", " ").title(),
            )

        submitted = st.form_submit_button("🚀 Submit Alert", type="primary")

    if submitted:
        form_data = {
            "title": f_title,
            "report_text": f_report,
            "category": f_category,
            "location_city": f_city,
            "neighborhood": f_neighborhood,
            "severity": f_severity,
            "privacy_mode": f_privacy,
            "audience_tag": f_audience,
        }

        errors = validate_new_alert(form_data)
        if errors:
            for err in errors:
                st.error(f"❌ {err}")
        else:
            new_alert = build_new_alert(form_data)
            st.session_state.alerts.append(new_alert)
            saved = save_alerts(st.session_state.alerts)
            if saved:
                st.success(f"✅ Alert **{new_alert['id']}** submitted successfully!")
                st.balloons()
            else:
                st.warning("⚠️ Alert added to session but could not be saved to disk.")

# ---------------------------------------------------------------------------
# Page: MANAGE ALERTS
# ---------------------------------------------------------------------------

elif page == "🔧 Manage Alerts":
    st.subheader("🔧 Manage Alert Statuses")
    st.caption("Update verification status for any alert in the dataset.")

    if not st.session_state.alerts:
        st.info("No alerts loaded.")
    else:
        all_ids = [a.get("id", "") for a in st.session_state.alerts]

        col1, col2, col3 = st.columns([2, 2, 1])
        with col1:
            target_id = st.selectbox("Select Alert ID", all_ids)
        with col2:
            new_status = st.selectbox(
                "New Status",
                ["verified", "pending", "unverified", "dismissed"],
            )
        with col3:
            st.write("")
            st.write("")
            update_btn = st.button("✏️ Update", type="primary")

        if update_btn:
            ok, msg = update_alert_status(st.session_state.alerts, target_id, new_status)
            if ok:
                save_alerts(st.session_state.alerts)
                st.success(f"✅ {msg}")
            else:
                st.error(f"❌ {msg}")

        st.divider()

        # Show current statuses
        st.subheader("📊 Current Status Overview")
        rows = [
            {
                "ID": a.get("id"),
                "Title": a.get("title", "")[:60],
                "Status": a.get("verification_status", ""),
                "Signal": a.get("noise_to_signal", "").upper(),
                "Severity": a.get("severity", 1),
            }
            for a in st.session_state.alerts
        ]
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
