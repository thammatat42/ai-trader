"""
🎛️  AI Trader – Admin Dashboard (Streamlit)
=============================================
ใช้ควบคุม Bot, ดู Reports, ดู Event Log และปรับ Settings
รันด้วย:  streamlit run dashboard.py --server.port 8501
"""

import os
import time
import psycopg2
import psycopg2.extras
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv()

# ==========================================
# PAGE CONFIG
# ==========================================
st.set_page_config(
    page_title="AI Trader Dashboard",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ==========================================
# DB HELPER
# ==========================================
@st.cache_resource
def get_conn():
    """Persistent DB connection (Streamlit cache)"""
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "db"),
        user=os.getenv("DB_USER", "admin"),
        password=os.getenv("DB_PASS", "secretpassword"),
        dbname=os.getenv("DB_NAME", "trading_log"),
    )


def run_query(sql, params=None, fetchall=True):
    conn = get_conn()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, params)
            if fetchall:
                return cur.fetchall()
            conn.commit()
            return None
    except psycopg2.OperationalError:
        # reconnect once
        conn = psycopg2.connect(
            host=os.getenv("DB_HOST", "db"),
            user=os.getenv("DB_USER", "admin"),
            password=os.getenv("DB_PASS", "secretpassword"),
            dbname=os.getenv("DB_NAME", "trading_log"),
        )
        st.cache_resource.clear()
        st.rerun()


def run_command(sql, params=None):
    """Execute INSERT / UPDATE / DELETE"""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params)
        conn.commit()
    except psycopg2.OperationalError:
        conn = psycopg2.connect(
            host=os.getenv("DB_HOST", "db"),
            user=os.getenv("DB_USER", "admin"),
            password=os.getenv("DB_PASS", "secretpassword"),
            dbname=os.getenv("DB_NAME", "trading_log"),
        )
        st.cache_resource.clear()
        st.rerun()


# ==========================================
# SIDEBAR – NAVIGATION
# ==========================================
st.sidebar.title("🧭 Navigation")
page = st.sidebar.radio(
    "เลือกหน้า",
    ["🏠 Overview", "📈 Analysis Log", "🎛️ Bot Control", "📋 Event Log"],
)

# Auto-refresh toggle
auto_refresh = st.sidebar.toggle("🔄 Auto-Refresh (10s)", value=False)
if auto_refresh:
    time.sleep(10)
    st.rerun()


# ==========================================
# PAGE: OVERVIEW
# ==========================================
if page == "🏠 Overview":
    st.title("🏠 AI Trader – Overview")

    # --- Bot Status ---
    settings = run_query("SELECT * FROM bot_settings LIMIT 1;")
    if settings:
        s = settings[0]
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Bot Status", "🟢 RUNNING" if s["is_running"] else "🔴 STOPPED")
        col2.metric("Interval", f"{s['interval_seconds']}s")
        col3.metric("Max Trades/Day", s["max_trades_per_day"])
        col4.metric("Last Updated", str(s["updated_at"])[:19])

    st.divider()

    # --- Quick Stats ---
    st.subheader("📊 Quick Stats (Last 24h)")

    rows = run_query(
        """
        SELECT COUNT(*) as total,
               COUNT(*) FILTER (WHERE ai_recommendation ILIKE '%%bullish%%') AS bullish,
               COUNT(*) FILTER (WHERE ai_recommendation ILIKE '%%bearish%%') AS bearish,
               COUNT(*) FILTER (WHERE ai_recommendation ILIKE '%%neutral%%') AS neutral,
               ROUND(AVG(bid)::numeric, 2) AS avg_bid,
               ROUND(AVG(ask)::numeric, 2) AS avg_ask,
               ROUND(AVG(lot_size)::numeric, 2) AS avg_lot
        FROM ai_analysis_log
        WHERE created_at >= NOW() - INTERVAL '24 hours';
        """
    )
    if rows and rows[0]:
        r = rows[0]
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Total Analyses", r["total"])
        c2.metric("🟢 Bullish", r["bullish"])
        c3.metric("🔴 Bearish", r["bearish"])
        c4.metric("⚪ Neutral", r["neutral"])

        c5, c6, c7 = st.columns(3)
        c5.metric("Avg Bid", r["avg_bid"])
        c6.metric("Avg Ask", r["avg_ask"])
        c7.metric("Avg Lot", r["avg_lot"])

    # --- Price Chart ---
    st.subheader("💹 Bid / Ask Price (Last 24h)")
    price_rows = run_query(
        """
        SELECT created_at, bid, ask
        FROM ai_analysis_log
        WHERE created_at >= NOW() - INTERVAL '24 hours'
        ORDER BY created_at;
        """
    )
    if price_rows:
        df = pd.DataFrame(price_rows)
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=df["created_at"], y=df["bid"], name="Bid", line=dict(color="#26a69a")))
        fig.add_trace(go.Scatter(x=df["created_at"], y=df["ask"], name="Ask", line=dict(color="#ef5350")))
        fig.update_layout(height=400, xaxis_title="Time", yaxis_title="Price", template="plotly_dark")
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("ยังไม่มีข้อมูลราคาใน 24 ชั่วโมงที่ผ่านมา")

    # --- Sentiment Pie ---
    if rows and rows[0] and rows[0]["total"] > 0:
        st.subheader("🧠 Sentiment Distribution (24h)")
        r = rows[0]
        fig_pie = px.pie(
            names=["Bullish", "Bearish", "Neutral"],
            values=[r["bullish"], r["bearish"], r["neutral"]],
            color_discrete_sequence=["#26a69a", "#ef5350", "#78909c"],
        )
        fig_pie.update_layout(template="plotly_dark", height=350)
        st.plotly_chart(fig_pie, use_container_width=True)


# ==========================================
# PAGE: ANALYSIS LOG
# ==========================================
elif page == "📈 Analysis Log":
    st.title("📈 Analysis Log")

    # Filters
    col_f1, col_f2 = st.columns(2)
    with col_f1:
        hours = st.slider("ดูย้อนหลัง (ชั่วโมง)", 1, 168, 24)
    with col_f2:
        limit = st.number_input("จำนวนแถวสูงสุด", 10, 5000, 200)

    log_rows = run_query(
        """
        SELECT id, symbol, bid, ask, ai_recommendation, lot_size, created_at
        FROM ai_analysis_log
        WHERE created_at >= NOW() - (%s * INTERVAL '1 hour')
        ORDER BY created_at DESC
        LIMIT %s;
        """,
        (hours, limit),
    )

    if log_rows:
        df = pd.DataFrame(log_rows)
        st.dataframe(df, use_container_width=True, height=500)

        csv = df.to_csv(index=False).encode("utf-8")
        st.download_button("📥 Export CSV", csv, "analysis_log.csv", "text/csv")
    else:
        st.info("ไม่พบข้อมูล")


# ==========================================
# PAGE: BOT CONTROL
# ==========================================
elif page == "🎛️ Bot Control":
    st.title("🎛️ Bot Control Panel")

    settings = run_query("SELECT * FROM bot_settings LIMIT 1;")
    if not settings:
        st.error("ไม่พบข้อมูลใน bot_settings – กรุณารัน db/init.sql ก่อน")
        st.stop()

    s = settings[0]

    # --- Kill Switch ---
    st.subheader("🔴 Kill Switch / Start-Stop")
    col_a, col_b = st.columns(2)

    with col_a:
        if s["is_running"]:
            st.success("Bot กำลังทำงาน 🟢")
            if st.button("⏹️  STOP BOT", type="primary", use_container_width=True):
                run_command("UPDATE bot_settings SET is_running = FALSE, updated_at = NOW();")
                run_command(
                    "INSERT INTO bot_events (event_type, message) VALUES (%s, %s);",
                    ("STOP", "Bot stopped from Dashboard"),
                )
                st.rerun()
        else:
            st.error("Bot หยุดทำงาน 🔴")
            if st.button("▶️  START BOT", type="primary", use_container_width=True):
                run_command("UPDATE bot_settings SET is_running = TRUE, updated_at = NOW();")
                run_command(
                    "INSERT INTO bot_events (event_type, message) VALUES (%s, %s);",
                    ("START", "Bot started from Dashboard"),
                )
                st.rerun()

    st.divider()

    # --- Settings ---
    st.subheader("⚙️ Bot Settings")

    with st.form("settings_form"):
        new_interval = st.selectbox(
            "Interval (วินาที)",
            options=[60, 120, 300, 600, 900, 1800, 3600],
            index=[60, 120, 300, 600, 900, 1800, 3600].index(s["interval_seconds"])
            if s["interval_seconds"] in [60, 120, 300, 600, 900, 1800, 3600]
            else 2,
            format_func=lambda x: {
                60: "1 นาที",
                120: "2 นาที",
                300: "5 นาที (แนะนำ M15)",
                600: "10 นาที",
                900: "15 นาที (แนะนำ H1)",
                1800: "30 นาที",
                3600: "1 ชั่วโมง (แนะนำ H1-H4)",
            }.get(x, f"{x}s"),
        )
        new_max_trades = st.number_input(
            "Max Trades / Day", min_value=1, max_value=100, value=s["max_trades_per_day"]
        )

        submitted = st.form_submit_button("💾 Save Settings")
        if submitted:
            run_command(
                """
                UPDATE bot_settings
                SET interval_seconds = %s, max_trades_per_day = %s, updated_at = NOW();
                """,
                (new_interval, new_max_trades),
            )
            run_command(
                "INSERT INTO bot_events (event_type, message) VALUES (%s, %s);",
                ("CONFIG_CHANGE", f"interval={new_interval}s, max_trades={new_max_trades}"),
            )
            st.success("✅ บันทึกสำเร็จ!")
            st.rerun()

    st.divider()
    st.subheader("💡 Interval Guide")
    st.markdown(
        """
        | Timeframe | Interval ที่เหมาะสม | เหตุผล |
        |-----------|---------------------|--------|
        | **M15 (Scalping)** | 5 นาที (300s) | เช็คก่อนแท่งเทียนปิด |
        | **H1** | 15 นาที (900s) | ลดค่า API, ลด Noise |
        | **H4** | 1 ชั่วโมง (3600s) | เหมาะกับ Swing |
        """
    )


# ==========================================
# PAGE: EVENT LOG
# ==========================================
elif page == "📋 Event Log":
    st.title("📋 Bot Event Log")

    events = run_query(
        """
        SELECT id, event_type, message, created_at
        FROM bot_events
        ORDER BY created_at DESC
        LIMIT 200;
        """
    )
    if events:
        df = pd.DataFrame(events)

        # Color-code event types
        def color_event(val):
            colors = {
                "START": "background-color: #1b5e20; color: white",
                "STOP": "background-color: #b71c1c; color: white",
                "ERROR": "background-color: #e65100; color: white",
                "KILL_SWITCH": "background-color: #880e4f; color: white",
                "CONFIG_CHANGE": "background-color: #0d47a1; color: white",
            }
            return colors.get(val, "")

        st.dataframe(
            df.style.map(color_event, subset=["event_type"]),
            use_container_width=True,
            height=600,
        )
    else:
        st.info("ยังไม่มี Event")


# ==========================================
# FOOTER
# ==========================================
st.sidebar.divider()
st.sidebar.caption(f"AI Trader Dashboard v1.0 • {datetime.now().strftime('%Y-%m-%d %H:%M')}")
