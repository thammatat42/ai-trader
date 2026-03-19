import os
import sys
import re                    # FIX #1: was inline-imported inside functions
import time
import json
import signal
import threading             # FIX #1: was inline-imported inside main_loop
import traceback
import requests
import psycopg2
import redis
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv

load_dotenv()

# HTTP Session for connection pooling / keep-alive
http_session = requests.Session()

# Flag for Graceful Shutdown (Ctrl+C / Docker Stop)
_shutdown = False

# Redis Connection (Market Journal & Cache)
_redis: redis.Redis | None = None

# FIX #2: Thread-safe lock for _forecast_cooldown (accessed from 2 threads)
_forecast_lock = threading.Lock()
_forecast_cooldown: dict = {}  # ticket -> last_forecast_ts (rate limit AI calls)


def get_redis() -> redis.Redis | None:
    """Lazy-init Redis connection"""
    global _redis
    if _redis is not None:
        return _redis
    try:
        _redis = redis.Redis(
            host=os.getenv("REDIS_HOST", "redis"),
            port=int(os.getenv("REDIS_PORT", 6379)),
            db=0,
            decode_responses=True,
            socket_connect_timeout=3,
        )
        _redis.ping()
        print("[REDIS] ✅ Connected")
        return _redis
    except Exception as e:
        print(f"[REDIS] ⚠️ Connection failed: {e} – running without cache")
        _redis = None
        return None


def _handle_signal(signum, frame):
    global _shutdown
    print("\n🛑 [SHUTDOWN] Received stop signal - shutting down safely...")
    _shutdown = True
    http_session.close()     # FIX #3: properly close HTTP session on shutdown


signal.signal(signal.SIGINT, _handle_signal)
signal.signal(signal.SIGTERM, _handle_signal)


# ==========================================
# HELPER: Create DB Connection
# ==========================================
def get_db_connection():
    return psycopg2.connect(
        host=os.getenv("DB_HOST"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASS"),
        dbname=os.getenv("DB_NAME"),
    )


# ==========================================
# HELPER: Check Market Open/Close (XAUUSD)
# ==========================================
def is_market_open() -> tuple[bool, str]:
    now = datetime.now(timezone.utc)
    weekday = now.weekday()   # 0=Mon, 4=Fri, 5=Sat, 6=Sun
    hour = now.hour
    minute = now.minute

    if weekday == 5:
        return False, "Saturday - market closed"
    if weekday == 6 and hour < 23:
        return False, f"Sunday {hour:02d}:{minute:02d} UTC - market opens at 23:00 UTC"
    if weekday == 4 and hour >= 22:
        return False, f"Friday {hour:02d}:{minute:02d} UTC - market closed for weekend"
    if hour == 22:
        return False, f"Daily break {hour:02d}:{minute:02d} UTC - reopens at 23:00 UTC"

    return True, "Market is open"


# ==========================================
# 1. RISK MANAGEMENT
# ==========================================
def _get_live_balance() -> float | None:
    """Get live balance from MT5 /account endpoint"""
    windows_ip = os.getenv("WINDOWS_IP")
    if not windows_ip:
        return None
    try:
        resp = http_session.get(f"http://{windows_ip}:8000/account", timeout=5)
        resp.raise_for_status()
        data = resp.json()
        return float(data["balance"])
    except Exception as e:
        print(f"[WARN] Failed to get balance from MT5: {e}")
        return None


def calculate_lot_size(atr_value: float | None = None) -> dict:
    """
    Calculate Lot Size, SL, TP dynamically based on ATR.
    FIX #4: ATR points conversion now uses explicit POINT_VALUE env var.
             Lot formula verified: lot = risk_usd / (sl_points * point_value_per_lot)
             For XAUUSD default: 1 point (0.01 USD) * 100 oz/lot = $1/lot/point
    """
    live_balance = _get_live_balance()
    env_balance = float(os.getenv("ACCOUNT_BALANCE", 1000.0))
    balance = live_balance if live_balance is not None else env_balance
    balance_src = "MT5" if live_balance is not None else ".env"

    risk_pct = float(os.getenv("RISK_PERCENT", 1.0))
    default_sl = float(os.getenv("SL_POINTS", 300))
    default_tp = float(os.getenv("TP_POINTS", 600))
    atr_sl_multiplier = float(os.getenv("ATR_SL_MULTIPLIER", 1.5))
    atr_tp_multiplier = float(os.getenv("ATR_TP_MULTIPLIER", 2.5))
    min_sl = float(os.getenv("MIN_SL_POINTS", 100))
    max_sl = float(os.getenv("MAX_SL_POINTS", 500))
    max_tp = float(os.getenv("MAX_TP_POINTS", 600))
    # FIX #4: explicit point-value constant — for XAUUSD: $1 per point per standard lot
    point_value_per_lot = float(os.getenv("POINT_VALUE_PER_LOT", 1.0))

    if atr_value and atr_value > 0:
        # ATR is real price delta (e.g. 5.50 USD) -> convert to points (×100)
        atr_points = atr_value * 100
        sl_points = round(atr_points * atr_sl_multiplier)
        tp_points = round(atr_points * atr_tp_multiplier)
        sl_points = max(min_sl, min(max_sl, sl_points))
        tp_points = max(sl_points * 1.5, tp_points)
        tp_points = min(tp_points, max_tp)
        if tp_points < sl_points * 1.5:
            tp_points = round(sl_points * 1.5)
        sl_src = "ATR"
    else:
        sl_points = default_sl
        tp_points = default_tp
        sl_src = "fixed"

    risk_amount = balance * (risk_pct / 100)
    # FIX #4: correct formula — divide by dollar risk per lot
    lot_size = risk_amount / (sl_points * point_value_per_lot)
    final_lot = max(0.01, round(lot_size, 2))

    print(
        f"[RISK] Balance ${balance:,.2f} ({balance_src}) | Risk {risk_pct}% (${risk_amount:,.2f}) "
        f"| SL {sl_points} ({sl_src}) | TP {tp_points} | R:R 1:{tp_points/sl_points:.1f} "
        f"-> Lot: {final_lot}"
    )
    return {"lot_size": final_lot, "sl_points": sl_points, "tp_points": tp_points}


# ==========================================
# 2. FETCH PRICE FROM WINDOWS VPS
# ==========================================
def get_price_from_mt5():
    windows_ip = os.getenv("WINDOWS_IP")
    symbol = os.getenv("SYMBOL", "XAUUSD")
    url = f"http://{windows_ip}:8000/price/{symbol}"
    try:
        response = http_session.get(url, timeout=5)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        print(f"[ERROR] Cannot connect to Windows VPS: {e}")
        return None


def get_candles_from_mt5(timeframe: str = "H1", count: int = 50) -> list | None:
    """Fetch OHLCV candle data from MT5 via Windows VPS"""
    windows_ip = os.getenv("WINDOWS_IP")
    symbol = os.getenv("SYMBOL", "XAUUSD")
    url = f"http://{windows_ip}:8000/candles/{symbol}?timeframe={timeframe}&count={count}"
    try:
        response = http_session.get(url, timeout=10)
        response.raise_for_status()
        data = response.json()
        if "error" in data:
            print(f"[ERROR] Candle API: {data['error']}")
            return None
        candles = data.get("candles", [])
        # FIX #5: validate candle data — drop rows with zero/None OHLC
        valid = [
            c for c in candles
            if c.get("open") and c.get("high") and c.get("low") and c.get("close")
            and c["high"] >= c["low"]
            and c["high"] >= max(c["open"], c["close"])
            and c["low"] <= min(c["open"], c["close"])
        ]
        if len(valid) < len(candles):
            print(f"[WARN] Dropped {len(candles)-len(valid)} invalid candles in {timeframe}")
        return valid
    except Exception as e:
        print(f"[ERROR] Failed to fetch candle data: {e}")
        return None


# ==========================================
# 2.1  TECHNICAL INDICATORS
# ==========================================
def calc_sma(closes: list, period: int) -> float | None:
    if len(closes) < period:
        return None
    return sum(closes[-period:]) / period


def calc_ema(closes: list, period: int) -> float | None:
    if len(closes) < period:
        return None
    multiplier = 2 / (period + 1)
    ema = sum(closes[:period]) / period
    for price in closes[period:]:
        ema = (price - ema) * multiplier + ema
    return ema


def calc_rsi(closes: list, period: int = 14) -> float | None:
    if len(closes) < period + 1:
        return None
    deltas = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    gains = [d if d > 0 else 0 for d in deltas]
    losses = [-d if d < 0 else 0 for d in deltas]

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    for i in range(period, len(deltas)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period

    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return round(100 - (100 / (1 + rs)), 2)


def calc_atr(candles: list, period: int = 14) -> float | None:
    if len(candles) < period + 1:
        return None
    true_ranges = []
    for i in range(1, len(candles)):
        h = candles[i]["high"]
        l = candles[i]["low"]
        pc = candles[i - 1]["close"]
        tr = max(h - l, abs(h - pc), abs(l - pc))
        true_ranges.append(tr)
    if len(true_ranges) < period:
        return None
    atr = sum(true_ranges[:period]) / period
    for tr in true_ranges[period:]:
        atr = (atr * (period - 1) + tr) / period
    return round(atr, 2)


# FIX #6: MACD rewritten O(n) — was O(n²) because calc_ema was called inside a loop
#          rebuilding full EMA from scratch on every bar. Now uses single-pass incremental.
def calc_macd(closes: list, fast: int = 12, slow: int = 26, signal_period: int = 9) -> dict | None:
    """MACD computed in O(n) via incremental EMA — was previously O(n²)."""
    if len(closes) < slow + signal_period:
        return None

    k_fast = 2 / (fast + 1)
    k_slow = 2 / (slow + 1)
    k_sig  = 2 / (signal_period + 1)

    # Seed fast/slow EMAs from their first `period` bars
    ema_f = sum(closes[:fast]) / fast
    ema_s = sum(closes[:slow]) / slow

    # Bring fast EMA up to the same bar as slow EMA
    for price in closes[fast:slow]:
        ema_f = (price - ema_f) * k_fast + ema_f

    # Build MACD line incrementally from bar `slow` onward
    macd_vals: list[float] = []
    for price in closes[slow:]:
        ema_f = (price - ema_f) * k_fast + ema_f
        ema_s = (price - ema_s) * k_slow + ema_s
        macd_vals.append(ema_f - ema_s)

    if len(macd_vals) < signal_period:
        return None

    # Signal line = EMA of MACD values
    sig = sum(macd_vals[:signal_period]) / signal_period
    for v in macd_vals[signal_period:]:
        sig = (v - sig) * k_sig + sig

    macd_line = macd_vals[-1]
    histogram = macd_line - sig

    return {
        "macd": round(macd_line, 3),
        "signal": round(sig, 3),
        "histogram": round(histogram, 3),
        "cross": "bullish" if macd_line > sig else "bearish",
    }


def calc_bollinger(closes: list, period: int = 20, std_dev: float = 2.0) -> dict | None:
    if len(closes) < period:
        return None
    window = closes[-period:]
    sma = sum(window) / period
    variance = sum((c - sma) ** 2 for c in window) / period
    std = variance ** 0.5
    upper = sma + std_dev * std
    lower = sma - std_dev * std
    current = closes[-1]
    band_width = upper - lower
    pct_b = (current - lower) / band_width if band_width > 0 else 0.5
    return {
        "upper": round(upper, 2),
        "middle": round(sma, 2),
        "lower": round(lower, 2),
        "pct_b": round(pct_b, 3),
        "bandwidth": round(band_width / sma * 100, 3) if sma else 0,
    }


# FIX #7: Support/resistance now uses swing high/low detection (not just raw max/min).
#          Raw max/min is heavily influenced by single wicks; swing points are more reliable.
def calc_support_resistance(candles: list, lookback: int = 20) -> dict:
    """
    Swing-based support/resistance.
    A swing high = candle[i].high > candle[i-1].high and candle[i].high > candle[i+1].high
    Falls back to raw max/min when insufficient swing points.
    """
    recent = candles[-lookback:] if len(candles) >= lookback else candles
    swing_highs = []
    swing_lows  = []

    for i in range(1, len(recent) - 1):
        if recent[i]["high"] > recent[i-1]["high"] and recent[i]["high"] > recent[i+1]["high"]:
            swing_highs.append(recent[i]["high"])
        if recent[i]["low"] < recent[i-1]["low"] and recent[i]["low"] < recent[i+1]["low"]:
            swing_lows.append(recent[i]["low"])

    resistance = round(max(swing_highs), 2) if swing_highs else round(max(c["high"] for c in recent), 2)
    support    = round(min(swing_lows), 2)  if swing_lows  else round(min(c["low"]  for c in recent), 2)
    return {"resistance": resistance, "support": support}


def build_technical_summary(candles_h1: list, candles_h4: list, candles_d1: list,
                             candles_scalp: list = None, scalp_tf: str = "M5") -> str:
    lines = []
    tf_list = [(scalp_tf, candles_scalp), ("H1", candles_h1), ("H4", candles_h4), ("D1", candles_d1)]

    for label, candles in tf_list:
        if not candles or len(candles) < 20:
            if candles is not None:
                lines.append(f"[{label}] Insufficient data")
            continue

        closes = [c["close"] for c in candles]
        current = closes[-1]

        sma_20 = calc_sma(closes, 20)
        ema_9  = calc_ema(closes, 9)
        ema_21 = calc_ema(closes, 21)
        rsi    = calc_rsi(closes, 14)
        atr    = calc_atr(candles, 14)
        sr     = calc_support_resistance(candles, 20)
        macd   = calc_macd(closes)
        bb     = calc_bollinger(closes)

        trend = "Sideways"
        if ema_9 and ema_21:
            if ema_9 > ema_21 and current > ema_9:
                trend = "Uptrend"
            elif ema_9 < ema_21 and current < ema_9:
                trend = "Downtrend"

        last4 = candles[-4:]
        candle_summary = " ".join(
            f"{'Bull' if c['close']>c['open'] else 'Bear'}({abs(c['close']-c['open']):.1f})"
            for c in last4
        )

        parts = [
            f"[{label}] Close={current:.2f}",
            f"EMA9={ema_9:.2f} EMA21={ema_21:.2f} SMA20={sma_20:.2f}",
            f"RSI={rsi}",
            f"ATR={atr}",
        ]
        if macd:
            parts.append(f"MACD={macd['macd']} Sig={macd['signal']} Hist={macd['histogram']} ({macd['cross']})")
        if bb:
            parts.append(f"BB%B={bb['pct_b']} Upper={bb['upper']} Lower={bb['lower']} BW={bb['bandwidth']}%")
        parts.extend([
            f"Trend={trend}",
            f"Support={sr['support']} Resist={sr['resistance']}",
            f"Last4: {candle_summary}",
        ])
        lines.append(" | ".join(parts))

    return "\n".join(lines)


# ==========================================
# 2.2  ORDER BOOK / DEPTH OF MARKET
# ==========================================
def get_orderbook_from_mt5() -> str:
    windows_ip = os.getenv("WINDOWS_IP")
    symbol = os.getenv("SYMBOL", "XAUUSD")
    url = f"http://{windows_ip}:8000/orderbook/{symbol}?depth=10"
    try:
        response = http_session.get(url, timeout=5)
        response.raise_for_status()
        data = response.json()
        if "error" in data:
            return "Order book unavailable"
        if not data.get("dom_available", False):
            return f"DOM not available (broker limitation) | Spread={data.get('spread', 'N/A')}"

        bid_vol = data.get("bid_total_vol", 0)
        ask_vol = data.get("ask_total_vol", 0)
        total   = bid_vol + ask_vol
        bid_pct = round(bid_vol / total * 100, 1) if total > 0 else 50

        bids = data.get("bids", [])[:3]
        asks = data.get("asks", [])[:3]
        bid_str = ", ".join(f"{b['price']}({b['volume']})" for b in bids)
        ask_str = ", ".join(f"{a['price']}({a['volume']})" for a in asks)

        pressure = "Buyers dominate" if bid_pct > 60 else ("Sellers dominate" if bid_pct < 40 else "Balanced")
        return (
            f"Pressure: {pressure} (Bid {bid_pct}% / Ask {round(100-bid_pct,1)}%) | "
            f"Top Bids: [{bid_str}] | Top Asks: [{ask_str}]"
        )
    except Exception as e:
        print(f"[WARN] Order book fetch failed: {e}")
        return "Order book unavailable"


# ==========================================
# 2.3  NEWS & MACRO EVENTS
# ==========================================
FINNHUB_CALENDAR_URL = "https://finnhub.io/api/v1/calendar/economic"
FINNHUB_NEWS_URL     = "https://finnhub.io/api/v1/news"

GOLD_KEYWORDS = [
    "gold", "xau", "fed", "fomc", "interest rate", "inflation", "cpi",
    "ppi", "nonfarm", "nfp", "gdp", "unemployment", "treasury", "yields",
    "dollar", "dxy", "usd", "geopolitical", "war", "tariff", "sanctions",
    "central bank", "monetary policy", "quantitative", "recession",
]

# FIX #8: News events that should pause ALL new trades (code-level guard, not just AI)
HIGH_IMPACT_KEYWORDS = ["nonfarm", "nfp", "fomc", "cpi", "ppi", "gdp", "interest rate", "fomc"]


def fetch_economic_calendar() -> list[dict]:
    api_key = os.getenv("FINNHUB_API_KEY")
    if not api_key:
        return []

    r = get_redis()
    cache_key = "news:calendar"
    if r:
        cached = r.get(cache_key)
        if cached:
            return json.loads(cached)

    try:
        today    = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        tomorrow = (datetime.now(timezone.utc) + timedelta(days=1)).strftime("%Y-%m-%d")
        resp = http_session.get(
            FINNHUB_CALENDAR_URL,
            params={"from": today, "to": tomorrow},
            headers={"X-Finnhub-Token": api_key},
            timeout=10,
        )
        if resp.status_code == 403:
            print("[WARN] Finnhub calendar: 403 Forbidden")
            return []
        resp.raise_for_status()
        events = resp.json().get("economicCalendar", [])

        important = []
        for ev in events:
            impact  = ev.get("impact", "").lower()
            country = ev.get("country", "")
            name    = ev.get("event", "").lower()
            if (country == "US" and impact in ("high", "medium")) or any(kw in name for kw in GOLD_KEYWORDS):
                important.append({
                    "time":     ev.get("time", ""),
                    "country":  country,
                    "event":    ev.get("event", ""),
                    "impact":   impact,
                    "actual":   ev.get("actual", ""),
                    "estimate": ev.get("estimate", ""),
                    "prev":     ev.get("prev", ""),
                })

        if r and important:
            r.setex(cache_key, 1800, json.dumps(important))
        return important[:10]
    except Exception as e:
        print(f"[WARN] Economic calendar fetch failed: {e}")
        return []


def fetch_market_news() -> list[dict]:
    api_key = os.getenv("FINNHUB_API_KEY")
    if not api_key:
        return []

    r = get_redis()
    cache_key = "news:market"
    if r:
        cached = r.get(cache_key)
        if cached:
            return json.loads(cached)

    try:
        resp = http_session.get(
            FINNHUB_NEWS_URL,
            params={"category": "forex"},
            headers={"X-Finnhub-Token": api_key},
            timeout=10,
        )
        if resp.status_code == 403:
            print("[WARN] Finnhub news: 403 Forbidden")
            return []
        resp.raise_for_status()
        articles = resp.json()

        relevant = []
        for art in articles[:50]:
            headline = art.get("headline", "").lower()
            summary  = art.get("summary",  "").lower()
            text     = headline + " " + summary
            if any(kw in text for kw in GOLD_KEYWORDS):
                relevant.append({
                    "headline": art.get("headline", ""),
                    "summary":  art.get("summary",  "")[:200],
                    "datetime": art.get("datetime", 0),
                })

        if r and relevant:
            r.setex(cache_key, 900, json.dumps(relevant[:5]))
        return relevant[:5]
    except Exception as e:
        print(f"[WARN] Market news fetch failed: {e}")
        return []


def build_news_summary() -> str:
    lines = []
    events = fetch_economic_calendar()
    if events:
        lines.append("--- Economic Calendar (Today) ---")
        for ev in events:
            actual = f"Actual={ev['actual']}" if ev.get("actual") else "Pending"
            lines.append(
                f"  [{ev['impact'].upper()}] {ev['time']} {ev['country']} "
                f"{ev['event']} | Est={ev.get('estimate','N/A')} Prev={ev.get('prev','N/A')} {actual}"
            )

    news = fetch_market_news()
    if news:
        lines.append("--- Latest Gold/USD News ---")
        for n in news:
            lines.append(f"  • {n['headline']}")

    return "\n".join(lines) if lines else "No significant news or events found"


# FIX #8: Code-level high-impact news guard (do NOT rely solely on AI to pause for news)
def is_high_impact_news_imminent(window_min: int = 30) -> tuple[bool, str]:
    """
    Return (True, event_name) if a HIGH-impact pending event is within `window_min` minutes.
    This is a hard code-level block — AI alone is not reliable for this.
    """
    events = fetch_economic_calendar()
    now_utc = datetime.now(timezone.utc)

    for ev in events:
        if ev.get("impact") != "high":
            continue
        event_name = ev.get("event", "").lower()
        if not any(kw in event_name for kw in HIGH_IMPACT_KEYWORDS):
            continue
        if ev.get("actual"):          # Already released — safe to trade
            continue
        raw_time = ev.get("time", "")
        if not raw_time:
            continue
        try:
            # Finnhub returns ISO time string
            ev_dt = datetime.fromisoformat(raw_time.replace("Z", "+00:00"))
            diff_min = (ev_dt - now_utc).total_seconds() / 60
            if -5 <= diff_min <= window_min:    # within window (incl. 5 min after release)
                return True, ev.get("event", "HIGH IMPACT EVENT")
        except Exception:
            continue
    return False, ""


# ==========================================
# 2.4  REDIS MARKET JOURNAL
# ==========================================
JOURNAL_KEY           = "journal:analysis_history"
JOURNAL_MAX_ENTRIES   = 20
JOURNAL_KNOWLEDGE_KEY = "journal:knowledge"


def journal_save_analysis(action: str, analysis: str, confidence: str,
                          bid: float, ask: float, tech_summary: str):
    r = get_redis()
    if not r:
        return
    entry = json.dumps({
        "ts":           datetime.now(timezone.utc).isoformat(),
        "action":       action,
        "analysis":     analysis[:500],          # FIX #9: was 300 — too short, lost context
        "confidence":   confidence,
        "bid":          bid,
        "ask":          ask,
        "tech_summary": tech_summary[:600],
    })
    r.lpush(JOURNAL_KEY, entry)
    r.ltrim(JOURNAL_KEY, 0, JOURNAL_MAX_ENTRIES - 1)


def journal_get_recent(count: int = 5) -> str:
    r = get_redis()
    if not r:
        return ""
    entries = r.lrange(JOURNAL_KEY, 0, count - 1)
    if not entries:
        return "No previous analysis history"
    lines = ["--- Recent Analysis History (newest first) ---"]
    for raw in entries:
        e = json.loads(raw)
        lines.append(
            f"  [{e['ts'][:16]}] {e['action']} | Bid={e['bid']} Ask={e['ask']} | "
            f"Confidence={e.get('confidence','N/A')}"
        )
    return "\n".join(lines)


def journal_update_knowledge(key: str, value: str, ttl: int = 86400):
    r = get_redis()
    if not r:
        return
    r.hset(JOURNAL_KNOWLEDGE_KEY, key, value)
    r.expire(JOURNAL_KNOWLEDGE_KEY, ttl)


def journal_get_knowledge() -> str:
    r = get_redis()
    if not r:
        return ""
    knowledge = r.hgetall(JOURNAL_KNOWLEDGE_KEY)
    if not knowledge:
        return ""
    lines = ["--- Accumulated Market Knowledge ---"]
    for k, v in knowledge.items():
        lines.append(f"  {k}: {v}")
    return "\n".join(lines)


def journal_detect_patterns():
    r = get_redis()
    if not r:
        return
    entries = r.lrange(JOURNAL_KEY, 0, JOURNAL_MAX_ENTRIES - 1)
    if len(entries) < 3:
        return
    parsed  = [json.loads(e) for e in entries]
    actions = [e["action"] for e in parsed]

    if len(set(actions[:3])) == 1 and actions[0] != "WAIT":
        journal_update_knowledge(
            "streak", f"{actions[0]} streak x{len([a for a in actions if a == actions[0]])}"
        )
    if len(parsed) >= 2:
        latest_bid = parsed[0].get("bid", 0)
        prev_bid   = parsed[1].get("bid", 0)
        if latest_bid and prev_bid:
            move      = round(latest_bid - prev_bid, 2)
            direction = "up" if move > 0 else "down" if move < 0 else "flat"
            journal_update_knowledge("last_price_move", f"{direction} ${abs(move)}")
    if len(actions) >= 2 and actions[0] != actions[1] and "WAIT" not in (actions[0], actions[1]):
        journal_update_knowledge("recent_flip", f"Changed from {actions[1]} to {actions[0]}")


# ==========================================
# 2.5  PARSE AI SENTIMENT
# ==========================================
def _extract_confidence(ai_text: str) -> int:
    """
    FIX #10: More robust confidence extraction.
    Parses "Confidence: 8" from the structured first two lines, not full body.
    Avoids false matches like "confidence in this bearish signal: 3".
    """
    # Prefer the explicit "Confidence:" line from structured output
    for line in ai_text.split("\n"):
        line_l = line.lower().strip()
        if line_l.startswith("confidence"):
            m = re.search(r'(\d{1,2})', line_l)
            if m:
                return min(int(m.group(1)), 10)
    # Fallback: search anywhere
    m = re.search(r'confidence[:\s]+(\d{1,2})', ai_text.lower())
    return min(int(m.group(1)), 10) if m else 0


def parse_sentiment(ai_text: str) -> str:
    """
    FIX #11 — CRITICAL BUG: The old parser scanned the ENTIRE response for
    "bullish"/"bearish" which meant the reason text could flip the signal.
    e.g. AI says Sentiment: Bullish but Reason mentions "bearish pressure" →
    old code returned SELL.

    New parser reads ONLY the "Sentiment:" line (structured output).
    Falls back to keyword search on first 2 lines only if structured line missing.
    """
    min_confidence = int(os.getenv("MIN_CONFIDENCE", 5))
    confidence     = _extract_confidence(ai_text)
    sentiment      = "WAIT"

    lines = [l.strip() for l in ai_text.strip().split("\n") if l.strip()]

    # Primary: parse "Sentiment: Bullish/Bearish/Neutral" from structured output
    for line in lines[:4]:                        # check first 4 lines only
        line_l = line.lower()
        if line_l.startswith("sentiment"):
            if "bullish" in line_l:
                sentiment = "BUY"
            elif "bearish" in line_l:
                sentiment = "SELL"
            else:
                sentiment = "WAIT"
            break
    else:
        # Fallback: explicit action keyword in first 2 lines only
        header = " ".join(lines[:2]).lower()
        m = re.search(r'(?:action|signal|recommendation)[:\s]*(buy|sell)', header)
        if m:
            sentiment = m.group(1).upper()

    if sentiment in ("BUY", "SELL") and confidence < min_confidence:
        print(f"[DECISION] ⚠️ AI says {sentiment} but confidence {confidence} < {min_confidence} → WAIT")
        return "WAIT"

    return sentiment


# ==========================================
# 2.6  SEND TRADE ORDER TO WINDOWS VPS
# ==========================================
def send_trade_to_mt5(action: str, symbol: str, lot: float,
                      sl_points: float, tp_points: float,
                      bid: float, ask: float) -> dict | None:
    windows_ip = os.getenv("WINDOWS_IP")
    url = f"http://{windows_ip}:8000/trade"

    if action == "BUY":
        entry    = ask
        sl_price = round(entry - sl_points * 0.01, 2)
        tp_price = round(entry + tp_points * 0.01, 2)
    elif action == "SELL":
        entry    = bid
        sl_price = round(entry + sl_points * 0.01, 2)
        tp_price = round(entry - tp_points * 0.01, 2)
    else:
        print("[INFO] ⏸️  AI recommends WAIT - no trade order sent")
        return None

    payload = {"action": action, "symbol": symbol, "lot": lot, "sl": sl_price, "tp": tp_price}
    print(f"[TRADE] 📤 Sending {action} order | Lot {lot} | SL {sl_price} | TP {tp_price}")

    try:
        resp = http_session.post(url, json=payload, timeout=10)
        resp.raise_for_status()
        result = resp.json()
        print(f"[TRADE] ✅ Order executed: {result}")
        return result
    except Exception as e:
        print(f"[TRADE] ❌ Order failed: {e}")
        return None


# ==========================================
# 2.7  RECENT TRADE HISTORY FOR AI CONTEXT
# ==========================================
def get_recent_trade_summary(limit: int = 10) -> str:
    try:
        conn = get_db_connection()
        cur  = conn.cursor()
        cur.execute(
            """
            SELECT action, lot, open_price, close_price, profit, status,
                   opened_at, closed_at,
                   EXTRACT(EPOCH FROM (closed_at - opened_at)) as duration_sec
            FROM trades
            WHERE status = 'CLOSED' AND closed_at IS NOT NULL
            ORDER BY closed_at DESC
            LIMIT %s;
            """,
            (limit,),
        )
        rows = cur.fetchall()
        cur.close()
        conn.close()
        if not rows:
            return ""

        lines      = []
        total_pnl  = 0
        wins = losses = buy_count = sell_count = 0

        for row in rows:
            action, lot, open_px, close_px, profit, status, opened, closed, dur = row
            profit = float(profit) if profit else 0
            dur    = int(dur) if dur else 0
            total_pnl += profit
            if profit > 0:
                wins += 1
            else:
                losses += 1
            if action == "BUY":
                buy_count += 1
            else:
                sell_count += 1
            result = "WIN" if profit > 0 else "LOSS"
            lines.append(
                f"  {action} {lot}lot | Open={open_px} Close={close_px} | "
                f"P/L=${profit:+.2f} ({result}) | Hold={dur}s"
            )

        total    = wins + losses
        win_rate = round(wins / total * 100, 1) if total > 0 else 0
        header   = (
            f"Recent {total} trades: {wins}W/{losses}L (WR={win_rate}%) | "
            f"Net P/L=${total_pnl:+.2f} | BUY={buy_count} SELL={sell_count}"
        )

        consec_loss = 0
        for row in rows:
            if float(row[4] or 0) <= 0:
                consec_loss += 1
            else:
                break

        warnings = []
        if consec_loss >= 2:
            warnings.append(f"WARNING: {consec_loss} consecutive losses — be more selective")
        if total >= 5 and buy_count > 0 and sell_count > 0:
            ratio = buy_count / total * 100
            if ratio > 80:
                warnings.append(f"WARNING: Heavy BUY bias ({ratio:.0f}%) — consider SELL opportunities")
            elif ratio < 20:
                warnings.append(f"WARNING: Heavy SELL bias ({100-ratio:.0f}%) — consider BUY opportunities")
        if total >= 5 and win_rate < 40:
            warnings.append("WARNING: Low win rate — require stronger signal confluence")

        summary = header + "\n" + "\n".join(lines)
        if warnings:
            summary += "\n" + "\n".join(warnings)
        return summary
    except Exception as e:
        print(f"[WARN] get_recent_trade_summary: {e}")
        return ""


def get_consecutive_losses() -> int:
    try:
        conn = get_db_connection()
        cur  = conn.cursor()
        cur.execute(
            """
            SELECT profit FROM trades
            WHERE status = 'CLOSED' AND closed_at IS NOT NULL
            ORDER BY closed_at DESC
            LIMIT 10;
            """
        )
        rows = cur.fetchall()
        cur.close()
        conn.close()
        count = 0
        for row in rows:
            if float(row[0] or 0) <= 0:
                count += 1
            else:
                break
        return count
    except Exception:
        return 0


# FIX #12: Add max drawdown protection — stop trading if account drops > X% from peak
def check_max_drawdown() -> tuple[bool, str]:
    """
    Returns (is_safe, reason).
    Reads MAX_DRAWDOWN_PCT from env (default 10%).
    Compares current balance against peak balance stored in Redis.
    """
    max_dd_pct = float(os.getenv("MAX_DRAWDOWN_PCT", 10.0))
    if max_dd_pct <= 0:
        return True, "Drawdown check disabled"

    current = _get_live_balance()
    if current is None:
        return True, "Cannot get balance"

    r = get_redis()
    peak_key = "risk:peak_balance"

    if r:
        peak_raw = r.get(peak_key)
        peak = float(peak_raw) if peak_raw else current
        # Update peak if current is higher
        if current > peak:
            r.set(peak_key, str(current))
            peak = current
    else:
        # No Redis: fall back to env balance as a rough proxy
        peak = float(os.getenv("ACCOUNT_BALANCE", current))

    drawdown_pct = (peak - current) / peak * 100 if peak > 0 else 0

    if drawdown_pct >= max_dd_pct:
        msg = f"Max drawdown reached: {drawdown_pct:.1f}% >= {max_dd_pct}% (peak=${peak:,.2f} now=${current:,.2f})"
        return False, msg

    return True, f"Drawdown OK: {drawdown_pct:.1f}% / {max_dd_pct}%"


# ==========================================
# 3. AI ANALYSIS
# ==========================================
def _get_ai_config(role: str = "main") -> dict:
    """Get AI config for a specific role.

    Roles:
        main     - Full analysis (deeper, smarter model)
        forecast - Quick position forecast (fast, cheap model)

    Priority: DB (ai_model_config with model_role) → env vars
    """
    # --- Try DB first ---
    try:
        conn = get_db_connection()
        cur  = conn.cursor()
        # Try role-specific model first
        cur.execute(
            """
            SELECT provider, model, api_key, api_url, max_tokens, temperature
            FROM ai_model_config
            WHERE is_active = TRUE AND model_role = %s
            ORDER BY updated_at DESC
            LIMIT 1;
            """,
            (role,),
        )
        row = cur.fetchone()
        if not row and role != "main":
            # Fallback: if no specific forecast model, use main model
            cur.execute(
                """
                SELECT provider, model, api_key, api_url, max_tokens, temperature
                FROM ai_model_config
                WHERE is_active = TRUE AND model_role = 'main'
                ORDER BY updated_at DESC
                LIMIT 1;
                """
            )
            row = cur.fetchone()
        if not row:
            # Legacy fallback: any active model without role
            cur.execute(
                """
                SELECT provider, model, api_key, api_url, max_tokens, temperature
                FROM ai_model_config
                WHERE is_active = TRUE
                ORDER BY updated_at DESC
                LIMIT 1;
                """
            )
            row = cur.fetchone()
        cur.close()
        conn.close()
        if row:
            return {
                "provider":    row[0],
                "api_key":     row[2],
                "url":         row[3],
                "model":       row[1],
                "max_tokens":  int(row[4])   if row[4] else 400,
                "temperature": float(row[5]) if row[5] else 0.1,
            }
    except Exception:
        pass

    # --- Env var fallback ---
    provider = os.getenv("AI_PROVIDER", "openrouter").lower()

    # Forecast-specific env var override
    if role == "forecast":
        forecast_model = os.getenv("FORECAST_MODEL")
        if forecast_model:
            # Forecast uses OpenRouter with a separate model string
            return {
                "provider": "openrouter",
                "api_key":  os.getenv("OPENROUTER_API_KEY"),
                "url":      os.getenv("OPENROUTER_URL", "https://openrouter.ai/api/v1/chat/completions"),
                "model":    forecast_model,
            }
        # No separate forecast model → fall through to main model

    if provider == "nvidia":
        return {
            "provider": "nvidia",
            "api_key":  os.getenv("NVIDIA_API_KEY"),
            "url":      os.getenv("NVIDIA_URL", "https://integrate.api.nvidia.com/v1/chat/completions"),
            "model":    os.getenv("NVIDIA_MODEL", "meta/llama-3.1-70b-instruct"),
        }
    return {
        "provider": "openrouter",
        "api_key":  os.getenv("OPENROUTER_API_KEY"),
        "url":      os.getenv("OPENROUTER_URL", "https://openrouter.ai/api/v1/chat/completions"),
        "model":    os.getenv("MODEL", "deepseek/deepseek-v3.2"),
    }


def analyze_with_ai(price_data, technical_summary: str = "",
                    orderbook_summary: str = "", news_summary: str = "",
                    journal_history: str = "", journal_knowledge: str = "",
                    trade_history: str = "", scalp_tf: str = "M5") -> str:
    ai_cfg = _get_ai_config("main")
    api_key = ai_cfg["api_key"]
    url     = ai_cfg["url"]
    model   = ai_cfg["model"]

    max_tokens  = int(os.getenv("MAX_TOKENS",   400))
    temperature = float(os.getenv("TEMPERATURE", 0.1))

    if not api_key:
        print(f"[ERROR] No API Key found for provider '{ai_cfg['provider']}'")
        return "ERROR"

    stf = scalp_tf
    system_prompt = (
        "You are a professional XAUUSD (Gold) scalp trader with 15+ years experience. "
        f"You analyze multi-timeframe data ({stf}, H1, H4, D1) using technical indicators, "
        "price action, order flow, and macro events.\n\n"

        "TRADING STYLE: Short-term scalping (3-30 min hold). "
        "You are BALANCED — you trade both BUY and SELL with equal discipline.\n\n"

        "CRITICAL RULES:\n"
        "1. Analyze BOTH directions equally. Do NOT default to BUY.\n"
        "2. TREND IS KING: Always check H1+H4 trend alignment FIRST. "
        "Trading WITH the multi-TF trend has 70%+ base probability. "
        "Counter-trend trades need overwhelming evidence (confidence 8+).\n"
        "3. Support/Resistance proximity: Do NOT BUY near resistance or SELL near support "
        "unless a breakout is confirmed by volume + momentum.\n"
        "4. Consider the FULL picture: technicals + trade history + news + patterns. "
        "Do not base decisions on a single indicator.\n\n"

        "DECISION RULES (need 3+ signals aligned):\n"
        "BUY: EMA9>EMA21 on H1+H4 | RSI 30-60 rising | MACD histogram positive/turning up | "
        "BB%B<0.3 (oversold) | price bouncing at support | bullish candle pattern | buyer volume\n"
        "SELL: EMA9<EMA21 on H1+H4 | RSI 40-70 falling | MACD histogram negative/turning down | "
        "BB%B>0.7 (overbought) | price rejected at resistance | bearish candle | seller volume\n"
        "WAIT: <3 signals aligned | RSI extreme >80/<20 | conflicting TF signals | "
        "high-impact news pending <30min | price in tight range/chop\n\n"

        "TRADE LOG ANALYSIS:\n"
        "- Review recent trades for patterns (e.g. repeated SL hits at same level = wrong side)\n"
        "- Heavy BUY bias → actively look for SELL setups\n"
        "- Consecutive losses → require confidence 7+ and stronger confluence\n"
        "- If last trade hit SL quickly, check if current setup avoids the same mistake\n\n"

        "MACRO RULES:\n"
        "- DOM/order book missing is NOT bearish (broker limitation)\n"
        "- H1+H4 agreement outweighs D1 for scalp timing\n"
        "- USD strength (DXY up) → typically SELL gold\n"
        "- Geopolitical risk / uncertainty → typically BUY gold (safe haven)\n"
        "- High-impact news within 30min → WAIT (volatility spike risk)\n\n"

        "CONFIDENCE SCALE (1-10):\n"
        "1-4: Weak signal → WAIT. 5-6: Moderate → trade only with trend. "
        "7-8: Strong → trade. 9-10: Very strong → high conviction.\n\n"

        "Reply EXACTLY in this format (no extra text, no preamble):\n"
        "Sentiment: <Bullish/Bearish/Neutral>\n"
        "Confidence: <1-10>\n"
        "Reason: <2-3 sentences: key signals, trend alignment, and risk factors>"
    )

    sections = [
        "=== XAUUSD LIVE DATA ===",
        f"Current Price -> Bid: {price_data['bid']}, Ask: {price_data['ask']}",
        f"Spread: {round(price_data['ask'] - price_data['bid'], 2)}",
    ]
    if technical_summary:
        sections.append(f"\n=== TECHNICAL ANALYSIS (Multi-Timeframe) ===\n{technical_summary}")
    if orderbook_summary:
        sections.append(f"\n=== ORDER BOOK ===\n{orderbook_summary}")
    if news_summary:
        sections.append(f"\n=== NEWS & MACRO EVENTS ===\n{news_summary}")
    if trade_history:
        sections.append(f"\n=== RECENT TRADE LOG ===\n{trade_history}")
    if journal_history:
        sections.append(f"\n=== YOUR PREVIOUS ANALYSIS ===\n{journal_history}")
    if journal_knowledge:
        sections.append(f"\n=== OBSERVED PATTERNS ===\n{journal_knowledge}")
    sections.append(
        "\nBased on ALL the above data, provide your trading decision. "
        "Analyze BOTH bullish and bearish scenarios."
    )

    user_prompt = "\n".join(sections)
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user",   "content": user_prompt},
        ],
        "max_tokens":  max_tokens,
        "temperature": temperature,
    }

    max_retries = 2
    for attempt in range(1, max_retries + 1):
        t_start = time.time()
        try:
            response  = http_session.post(url, headers=headers, json=payload, timeout=15)
            response.raise_for_status()
            resp_json = response.json()
            elapsed   = int((time.time() - t_start) * 1000)
            usage     = resp_json.get("usage", {})
            save_api_usage(
                provider=ai_cfg["provider"], model=model,
                prompt_tokens=usage.get("prompt_tokens", 0),
                completion_tokens=usage.get("completion_tokens", 0),
                total_tokens=usage.get("total_tokens", 0),
                response_time_ms=elapsed, status="OK",
            )
            return resp_json["choices"][0]["message"]["content"].strip()
        except Exception as e:
            elapsed = int((time.time() - t_start) * 1000)
            save_api_usage(
                provider=ai_cfg["provider"], model=model,
                prompt_tokens=0, completion_tokens=0, total_tokens=0,
                response_time_ms=elapsed, status="ERROR",
            )
            if attempt < max_retries:
                print(f"[WARN] AI API attempt {attempt}/{max_retries} failed: {e} – retrying...")
                time.sleep(2)
            else:
                print(f"[ERROR] AI API failed after {max_retries} attempts: {e}")

    return "ERROR"


def save_api_usage(provider, model, prompt_tokens, completion_tokens,
                   total_tokens, response_time_ms, status):
    try:
        conn = get_db_connection()
        cur  = conn.cursor()
        cur.execute(
            """
            INSERT INTO api_usage_log
                (provider, model, prompt_tokens, completion_tokens,
                 total_tokens, response_time_ms, status)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            (provider, model, prompt_tokens, completion_tokens,
             total_tokens, response_time_ms, status),
        )
        conn.commit()
        cur.close()
        conn.close()
        print(f"[API] 📊 {provider}/{model} → {total_tokens} tokens, {response_time_ms}ms [{status}]")
    except Exception as e:
        print(f"[WARN] save_api_usage: {e}")


# ==========================================
# 4. DATABASE LOGGING
# ==========================================
def save_log_to_db(symbol, bid, ask, ai_response, lot_size,
                   trade_action="WAIT", sl_price=None, tp_price=None):
    try:
        conn   = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO ai_analysis_log
                (symbol, bid, ask, ai_recommendation, lot_size, trade_action, sl_price, tp_price)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (symbol, bid, ask, ai_response, lot_size, trade_action, sl_price, tp_price),
        )
        conn.commit()
        cursor.close()
        conn.close()
        print(f"[SUCCESS] 💾 Log saved to Database (Action: {trade_action})")
    except Exception as e:
        print(f"[ERROR] Database Error: {e}")


# ==========================================
# 4.5  TRADE TRACKING
# ==========================================
def save_trade_to_db(order_id, symbol, action, lot, open_price, sl_price, tp_price):
    try:
        conn = get_db_connection()
        cur  = conn.cursor()
        cur.execute(
            """
            INSERT INTO trades (order_id, symbol, action, lot, open_price,
                                sl_price, tp_price, status, opened_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, 'OPEN', NOW())
            ON CONFLICT (order_id) DO NOTHING;
            """,
            (order_id, symbol, action, lot, open_price, sl_price, tp_price),
        )
        conn.commit()
        cur.close()
        conn.close()
        print(f"[DB] 📝 Trade #{order_id} saved (OPEN)")
    except Exception as e:
        print(f"[ERROR] save_trade_to_db: {e}")


def sync_closed_trades():
    windows_ip = os.getenv("WINDOWS_IP")
    if not windows_ip:
        return

    try:
        resp  = http_session.get(f"http://{windows_ip}:8000/history?days=7", timeout=10)
        resp.raise_for_status()
        deals = resp.json().get("deals", [])

        if deals:
            in_deals  = {}
            out_deals = {}
            for deal in deals:
                pos_id = deal.get("position", deal["order"])
                if deal.get("entry") == "IN":
                    in_deals[pos_id] = deal
                elif deal.get("entry") in ("OUT", "INOUT"):
                    out_deals[pos_id] = deal

            conn    = get_db_connection()
            cur     = conn.cursor()
            updated = 0
            for pos_id, out_deal in out_deals.items():
                in_deal     = in_deals.get(pos_id)
                db_order_id = in_deal["order"] if in_deal else pos_id
                cur.execute(
                    """
                    UPDATE trades
                    SET close_price = %s, profit = %s, status = 'CLOSED',
                        closed_at = to_timestamp(%s)
                    WHERE order_id = %s AND (status = 'OPEN' OR close_price IS NULL);
                    """,
                    (out_deal["price"], out_deal["profit"], out_deal["time"], db_order_id),
                )
                if cur.rowcount > 0:
                    updated += 1
            conn.commit()
            cur.close()
            conn.close()
            if updated:
                print(f"[SYNC] 🔄 Updated {updated} closed trades from MT5")
    except Exception as e:
        print(f"[SYNC] ⚠️ sync closed deals error: {e}")

    try:
        resp      = http_session.get(f"http://{windows_ip}:8000/positions", timeout=10)
        resp.raise_for_status()
        positions = resp.json().get("positions", [])
        if positions:
            conn = get_db_connection()
            cur  = conn.cursor()
            for pos in positions:
                cur.execute(
                    "UPDATE trades SET profit = %s WHERE order_id = %s AND status = 'OPEN';",
                    (pos["profit"], pos["ticket"]),
                )
            conn.commit()
            cur.close()
            conn.close()
    except Exception as e:
        print(f"[SYNC] ⚠️ sync open positions error: {e}")


# ==========================================
# 4.6  SMART POSITION MANAGER
# ==========================================
POSITION_CHECK_INTERVAL = int(os.getenv("POSITION_CHECK_INTERVAL", 5))
MIN_HOLD_SEC            = int(os.getenv("MIN_HOLD_SEC",   60))
MAX_HOLD_SEC            = int(os.getenv("MAX_HOLD_SEC",   1800))
TRAILING_STEP_PRICE     = float(os.getenv("TRAILING_STEP_PRICE",   1.0))
TRAILING_PROTECT_PCT    = float(os.getenv("TRAILING_PROTECT_PCT",  50))
PROFIT_LOCK_PCT         = float(os.getenv("PROFIT_LOCK_PCT",        5.0))
BREAKEVEN_TRIGGER_PCT   = float(os.getenv("BREAKEVEN_TRIGGER_PCT",  0.2))
MIN_PROFIT_CLOSE_PCT    = float(os.getenv("MIN_PROFIT_CLOSE_PCT",   0.3))
AI_FORECAST_COOLDOWN    = int(os.getenv("AI_FORECAST_COOLDOWN",    20))
# Partial close — close half the position at this profit threshold (% of balance)
PARTIAL_CLOSE_PCT       = float(os.getenv("PARTIAL_CLOSE_PCT", 0.5))
# Rapid price spike detection threshold (USD move in single check)
SPIKE_THRESHOLD         = float(os.getenv("SPIKE_THRESHOLD", 2.0))
# Max concurrent positions allowed
MAX_CONCURRENT_POS      = int(os.getenv("MAX_CONCURRENT_POS", 1))

# Friday Auto-Close (weekend gap protection)
FRIDAY_AUTO_CLOSE           = os.getenv("FRIDAY_AUTO_CLOSE", "true").lower() in ("true", "1", "yes")
FRIDAY_CLOSE_MINUTES_BEFORE = int(os.getenv("FRIDAY_CLOSE_MINUTES_BEFORE", 30))
FRIDAY_NO_NEW_TRADE_MINUTES = int(os.getenv("FRIDAY_NO_NEW_TRADE_MINUTES", 60))

# 3-Phase Adaptive Trailing Stop (ATR multipliers)
# Phase 1: Small profit — tight trailing to protect entry
TRAIL_PHASE1_ATR = float(os.getenv("TRAIL_PHASE1_ATR", 0.30))
# Phase 2: Good profit (>= min_profit_close) — wider trail, let it breathe
TRAIL_PHASE2_ATR = float(os.getenv("TRAIL_PHASE2_ATR", 0.55))
# Phase 3: After partial close (already banked 50%) — widest, let runner go
TRAIL_PHASE3_ATR = float(os.getenv("TRAIL_PHASE3_ATR", 0.75))
# Breakeven trigger distance in USD (price must move this far before SL→entry)
BREAKEVEN_DISTANCE = float(os.getenv("BREAKEVEN_DISTANCE", 0.50))

_friday_closed: bool = False  # Flag to prevent repeated Friday close attempts

_cached_balance:    float | None = None
_cached_balance_ts: float        = 0
# Cache ATR for trailing stop (refreshed every 60s)
_cached_atr:    float | None = None
_cached_atr_ts: float        = 0
# Track last known prices for spike detection
_last_prices: dict = {}  # ticket -> last_known_price
# Track which positions already had partial close
_partial_closed: set = set()


def _get_account_balance() -> float:
    global _cached_balance, _cached_balance_ts
    now = time.time()
    if _cached_balance is not None and now - _cached_balance_ts < 60:
        return _cached_balance
    live = _get_live_balance()
    if live is not None:
        _cached_balance    = live
        _cached_balance_ts = now
        return live
    return float(os.getenv("ACCOUNT_BALANCE", 1000.0))


def _get_cached_atr(scalp_tf: str = "M15") -> float:
    """Get ATR from H1 candles, cached 60s. Used for dynamic trailing."""
    global _cached_atr, _cached_atr_ts
    now = time.time()
    if _cached_atr is not None and now - _cached_atr_ts < 60:
        return _cached_atr
    candles = get_candles_from_mt5("H1", 20)
    if candles:
        atr = calc_atr(candles, 14)
        if atr and atr > 0:
            _cached_atr    = atr
            _cached_atr_ts = now
            return atr
    return _cached_atr if _cached_atr else 3.0  # fallback $3 ATR


def partial_close_mt5(ticket: int, fraction: float = 0.5) -> dict | None:
    """Close a fraction of a position (e.g. 50%). Requires /partial_close endpoint on MT5 bridge."""
    windows_ip = os.getenv("WINDOWS_IP")
    url = f"http://{windows_ip}:8000/partial_close"
    try:
        resp = http_session.post(
            url, json={"ticket": ticket, "fraction": fraction}, timeout=10
        )
        resp.raise_for_status()
        result = resp.json()
        if result.get("success"):
            print(f"[PARTIAL] ✅ Closed {fraction*100:.0f}% of #{ticket} | Profit: ${result.get('profit', 0):.2f}")
            log_event("PARTIAL_CLOSE", f"#{ticket} {fraction*100:.0f}% closed, profit=${result.get('profit',0):.2f}")
            return result
        # If endpoint doesn't exist, fall back to full close
        if "not found" in str(result.get("error", "")).lower():
            print(f"[PARTIAL] ⚠️ /partial_close not available, skipping partial close for #{ticket}")
            return None
        print(f"[PARTIAL] ⚠️ Partial close failed #{ticket}: {result.get('error')}")
        return None
    except Exception as e:
        print(f"[PARTIAL] ⚠️ Partial close error #{ticket}: {e}")
        return None


def close_position_mt5(ticket: int, retries: int = 3) -> dict | None:
    """Close position with retry + exponential backoff."""
    windows_ip = os.getenv("WINDOWS_IP")
    url = f"http://{windows_ip}:8000/close"
    for attempt in range(1, retries + 1):
        try:
            resp   = http_session.post(url, json={"ticket": ticket}, timeout=10)
            resp.raise_for_status()
            result = resp.json()
            if result.get("success"):
                print(f"[SMART-CLOSE] ✅ Closed #{ticket} | Profit: ${result.get('profit', 0):.2f}")
                log_event("SMART_CLOSE", f"Closed #{ticket} profit=${result.get('profit',0):.2f}")
                return result
            # Broker returned error (e.g. invalid ticket = already closed)
            err = result.get('error', '')
            if 'not found' in str(err).lower() or 'invalid' in str(err).lower():
                print(f"[SMART-CLOSE] ⚠️ #{ticket} already closed or invalid — skipping retry")
                return result
            print(f"[SMART-CLOSE] ❌ Close failed #{ticket} (attempt {attempt}/{retries}): {err}")
        except Exception as e:
            print(f"[SMART-CLOSE] ❌ Error closing #{ticket} (attempt {attempt}/{retries}): {e}")
        if attempt < retries:
            wait = 2 ** attempt  # 2s, 4s
            print(f"[SMART-CLOSE] ⏳ Retrying in {wait}s...")
            time.sleep(wait)
    log_event("CLOSE_FAILED", f"#{ticket} failed after {retries} attempts")
    return None


def modify_sl_mt5(ticket: int, new_sl: float, new_tp: float = None) -> bool:
    windows_ip = os.getenv("WINDOWS_IP")
    url     = f"http://{windows_ip}:8000/modify_sl"
    payload = {"ticket": ticket, "sl": new_sl}
    if new_tp is not None:
        payload["tp"] = new_tp
    try:
        resp   = http_session.post(url, json=payload, timeout=10)
        resp.raise_for_status()
        result = resp.json()
        if result.get("success"):
            print(f"[TRAIL] 📐 SL updated #{ticket} → SL={new_sl}")
            return True
        print(f"[TRAIL] ⚠️ Modify failed #{ticket}: {result.get('error')}")
        return False
    except Exception as e:
        print(f"[TRAIL] ❌ Error: {e}")
        return False


def ai_quick_forecast(candles_scalp: list, current_price: float,
                      position_type: str, profit: float,
                      scalp_tf: str = "M15",
                      open_price: float = 0, hold_sec: int = 0) -> dict:
    """Enhanced AI forecast with multi-indicator context + S/R + trend."""
    if not candles_scalp or len(candles_scalp) < 10:
        return {"action": "CLOSE", "reason": f"Insufficient {scalp_tf} data"}

    closes    = [c["close"] for c in candles_scalp]
    ema_5     = calc_ema(closes, 5)
    ema_10    = calc_ema(closes, 10)
    ema_20    = calc_ema(closes, 20) if len(closes) >= 20 else ema_10
    rsi       = calc_rsi(closes, 14)
    atr       = calc_atr(candles_scalp, 14)
    sr        = calc_support_resistance(candles_scalp, min(20, len(candles_scalp)))
    macd      = calc_macd(closes) if len(closes) >= 35 else None
    bb        = calc_bollinger(closes) if len(closes) >= 20 else None

    # Quick momentum check — close immediately on fast adverse moves
    if len(closes) >= 3:
        recent_move = closes[-1] - closes[-3]
        if position_type == "BUY" and recent_move < -1.5:
            return {"action": "CLOSE", "reason": f"Rapid drop {recent_move:.2f} against BUY"}
        if position_type == "SELL" and recent_move > 1.5:
            return {"action": "CLOSE", "reason": f"Rapid rise +{recent_move:.2f} against SELL"}

    # Technical-only close signals (no AI call needed)
    if rsi is not None:
        if position_type == "BUY" and rsi > 78 and profit > 0:
            return {"action": "CLOSE", "reason": f"RSI overbought {rsi} — take profit on BUY"}
        if position_type == "SELL" and rsi < 22 and profit > 0:
            return {"action": "CLOSE", "reason": f"RSI oversold {rsi} — take profit on SELL"}

    # S/R proximity check
    if sr:
        dist_to_resist = sr["resistance"] - current_price
        dist_to_support = current_price - sr["support"]
        if position_type == "BUY" and dist_to_resist < 0.5 and profit > 0:
            return {"action": "CLOSE", "reason": f"Near resistance {sr['resistance']} — take profit"}
        if position_type == "SELL" and dist_to_support < 0.5 and profit > 0:
            return {"action": "CLOSE", "reason": f"Near support {sr['support']} — take profit"}

    last_10 = candles_scalp[-10:]
    candle_str = " ".join(
        f"{'U' if c['close']>c['open'] else 'D'}{abs(c['close']-c['open']):.1f}"
        for c in last_10
    )

    ai_cfg  = _get_ai_config("forecast")
    api_key = ai_cfg["api_key"]
    if not api_key:
        # Fallback: technical-only decision
        if ema_5 and ema_10:
            if position_type == "BUY" and ema_5 < ema_10:
                return {"action": "CLOSE", "reason": "EMA bearish crossover (no AI key)"}
            if position_type == "SELL" and ema_5 > ema_10:
                return {"action": "CLOSE", "reason": "EMA bullish crossover (no AI key)"}
        return {"action": "HOLD", "reason": "No AI key, technicals neutral"}

    # Build richer prompt with multi-indicator data
    indicators = [
        f"Price={current_price:.2f} Open={open_price:.2f}",
        f"EMA5={ema_5:.2f} EMA10={ema_10:.2f} EMA20={ema_20:.2f}" if ema_20 else f"EMA5={ema_5:.2f} EMA10={ema_10:.2f}",
        f"RSI={rsi}",
    ]
    if atr:
        indicators.append(f"ATR={atr:.2f}")
    if macd:
        indicators.append(f"MACD={macd['macd']:.3f} Sig={macd['signal']:.3f} ({macd['cross']})")
    if bb:
        indicators.append(f"BB%B={bb['pct_b']:.2f}")
    if sr:
        indicators.append(f"Support={sr['support']:.2f} Resist={sr['resistance']:.2f}")

    compact_prompt = (
        f"XAUUSD {scalp_tf} candles: {candle_str}\n"
        f"{' | '.join(indicators)}\n"
        f"Position: {position_type} | Profit=${profit:+.2f} | Hold={hold_sec}s\n"
        f"Question: Should this {position_type} position be held or closed NOW?\n"
        f"Consider: momentum direction, indicator alignment, S/R proximity, risk of reversal.\n"
        f"Reply format: HOLD or CLOSE — then max 10 words reason."
    )

    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {
        "model":       ai_cfg["model"],
        "messages":    [{"role": "user", "content": compact_prompt}],
        "max_tokens":  50,
        "temperature": 0.05,
    }

    try:
        t_start   = time.time()
        resp      = http_session.post(ai_cfg["url"], headers=headers, json=payload, timeout=10)
        resp.raise_for_status()
        resp_json = resp.json()
        elapsed   = int((time.time() - t_start) * 1000)
        usage     = resp_json.get("usage", {})
        save_api_usage(
            provider=ai_cfg["provider"], model=ai_cfg["model"],
            prompt_tokens=usage.get("prompt_tokens", 0),
            completion_tokens=usage.get("completion_tokens", 0),
            total_tokens=usage.get("total_tokens", 0),
            response_time_ms=elapsed, status="OK_FORECAST",
        )
        reply = resp_json["choices"][0]["message"]["content"].strip().upper()
        if "CLOSE" in reply:
            return {"action": "CLOSE", "reason": reply}
        return {"action": "HOLD", "reason": reply}
    except Exception as e:
        print(f"[FORECAST] ⚠️ AI forecast failed: {e}")
        # Technical fallback
        if ema_5 and ema_10:
            if position_type == "BUY"  and ema_5 < ema_10:
                return {"action": "CLOSE", "reason": "EMA bearish crossover (fallback)"}
            if position_type == "SELL" and ema_5 > ema_10:
                return {"action": "CLOSE", "reason": "EMA bullish crossover (fallback)"}
        return {"action": "HOLD", "reason": "AI unavailable, technicals neutral"}


def smart_position_monitor(scalp_tf: str = "M15"):
    """
    Enhanced position monitor with:
    - ATR-based dynamic trailing stop (adapts to volatility)
    - Faster breakeven (as soon as profit covers spread + small buffer)
    - Partial close at first profit target (lock 50% of gains)
    - Rapid price spike detection (immediate reaction to adverse moves)
    - Richer AI forecast with S/R + multi-indicator context
    """
    windows_ip = os.getenv("WINDOWS_IP")
    if not windows_ip:
        return

    try:
        resp      = http_session.get(f"http://{windows_ip}:8000/positions", timeout=5)
        resp.raise_for_status()
        positions = resp.json().get("positions", [])
        if not positions:
            return

        now_ts  = int(datetime.now(timezone.utc).timestamp())
        balance = _get_account_balance()
        atr     = _get_cached_atr(scalp_tf)

        profit_lock_usd    = balance * (PROFIT_LOCK_PCT      / 100) if PROFIT_LOCK_PCT > 0 else 0
        breakeven_usd      = balance * (BREAKEVEN_TRIGGER_PCT / 100)
        min_profit_close   = balance * (MIN_PROFIT_CLOSE_PCT  / 100)
        partial_close_usd  = balance * (PARTIAL_CLOSE_PCT     / 100)

        # 3-Phase Adaptive Trailing (ATR-based)
        # Phase 1: tight (protect entry)  Phase 2: medium (let it breathe)  Phase 3: wide (runner)
        trail_gap_p1 = max(0.20, round(atr * TRAIL_PHASE1_ATR, 2)) if atr else 0.30
        trail_gap_p2 = max(0.40, round(atr * TRAIL_PHASE2_ATR, 2)) if atr else 0.60
        trail_gap_p3 = max(0.60, round(atr * TRAIL_PHASE3_ATR, 2)) if atr else 0.90

        for pos in positions:
            ticket        = pos["ticket"]
            profit        = pos["profit"]
            open_time     = pos["time"]
            pos_type      = pos["type"]
            current_price = pos["current_price"]
            open_price    = pos["open_price"]
            current_sl    = pos["sl"]
            lot           = pos.get("lot", 0.01)
            hold_sec      = now_ts - open_time

            # ===== SPIKE DETECTION =====
            # React immediately if price moved adversely by > SPIKE_THRESHOLD since last check
            last_known = _last_prices.get(ticket)
            _last_prices[ticket] = current_price
            if last_known is not None:
                price_delta = current_price - last_known
                if pos_type == "BUY" and price_delta < -SPIKE_THRESHOLD and profit <= 0:
                    print(f"[SPIKE] ⚡ #{ticket} BUY price dropped {price_delta:.2f} → CLOSE")
                    close_position_mt5(ticket)
                    log_event("SPIKE_CLOSE", f"#{ticket} BUY spike {price_delta:.2f}")
                    continue
                if pos_type == "SELL" and price_delta > SPIKE_THRESHOLD and profit <= 0:
                    print(f"[SPIKE] ⚡ #{ticket} SELL price surged +{price_delta:.2f} → CLOSE")
                    close_position_mt5(ticket)
                    log_event("SPIKE_CLOSE", f"#{ticket} SELL spike +{price_delta:.2f}")
                    continue

            # ===== PROFIT LOCK (hard cap) =====
            if profit_lock_usd > 0 and profit >= profit_lock_usd:
                print(f"[SMART] 💰💰 #{ticket} profit=${profit:.2f} >= ${profit_lock_usd:.2f} → AUTO CLOSE")
                close_position_mt5(ticket)
                log_event("PROFIT_LOCK", f"#{ticket} closed at ${profit:.2f}")
                continue

            # ===== PARTIAL CLOSE (first target) =====
            if ticket not in _partial_closed and profit >= partial_close_usd and lot >= 0.02:
                print(f"[PARTIAL] 🎯 #{ticket} profit=${profit:.2f} >= ${partial_close_usd:.2f} → close 50%")
                result = partial_close_mt5(ticket, 0.5)
                if result and result.get("success"):
                    _partial_closed.add(ticket)

            # ===== 3-PHASE ADAPTIVE TRAILING STOP =====
            # Phase 1: small profit → tight trail (protect entry)
            # Phase 2: good profit → medium trail (survive normal swings)
            # Phase 3: after partial close → wide trail (let the runner go)
            is_partial = ticket in _partial_closed
            if is_partial:
                trail_gap = trail_gap_p3
                phase_label = "P3-RUNNER"
            elif profit >= min_profit_close:
                trail_gap = trail_gap_p2
                phase_label = "P2-BREATHE"
            else:
                trail_gap = trail_gap_p1
                phase_label = "P1-PROTECT"

            if current_sl != 0:
                if pos_type == "BUY":
                    distance = current_price - open_price
                    # Breakeven: move SL to entry once price moves BREAKEVEN_DISTANCE
                    if distance > BREAKEVEN_DISTANCE and current_sl < open_price:
                        be_sl = round(open_price + 0.05, 2)
                        print(f"[BREAKEVEN] 🔒 #{ticket} BUY → SL to {be_sl} (entry+0.05)")
                        modify_sl_mt5(ticket, be_sl)
                    # Adaptive trailing: gap depends on profit phase
                    elif profit >= breakeven_usd and distance > trail_gap:
                        ideal_sl = round(current_price - trail_gap, 2)
                        if ideal_sl > current_sl and ideal_sl > open_price:
                            print(f"[TRAIL-{phase_label}] 📈 #{ticket} SL {current_sl}→{ideal_sl} (gap={trail_gap})")
                            modify_sl_mt5(ticket, ideal_sl)

                elif pos_type == "SELL":
                    distance = open_price - current_price
                    # Breakeven
                    if distance > BREAKEVEN_DISTANCE and current_sl > open_price:
                        be_sl = round(open_price - 0.05, 2)
                        print(f"[BREAKEVEN] 🔒 #{ticket} SELL → SL to {be_sl} (entry-0.05)")
                        modify_sl_mt5(ticket, be_sl)
                    # Adaptive trailing
                    elif profit >= breakeven_usd and distance > trail_gap:
                        ideal_sl = round(current_price + trail_gap, 2)
                        if ideal_sl < current_sl and ideal_sl < open_price:
                            print(f"[TRAIL-{phase_label}] 📉 #{ticket} SL {current_sl}→{ideal_sl} (gap={trail_gap})")
                            modify_sl_mt5(ticket, ideal_sl)

            # ===== TIME + AI FORECAST DECISIONS =====
            if hold_sec < MIN_HOLD_SEC:
                continue
            if profit <= 0 and hold_sec < MAX_HOLD_SEC:
                # Even when losing, check more often if hold time is getting long
                if hold_sec > MAX_HOLD_SEC * 0.7:
                    pass  # fall through to AI forecast
                else:
                    continue

            # FIX #2: use lock when reading/writing _forecast_cooldown
            with _forecast_lock:
                last_call = _forecast_cooldown.get(ticket, 0)
                rate_ok   = (now_ts - last_call) >= AI_FORECAST_COOLDOWN
                if rate_ok:
                    _forecast_cooldown[ticket] = now_ts

            if hold_sec >= MAX_HOLD_SEC and profit > 0:
                print(f"[SMART] ⏰ #{ticket} {hold_sec}s > MAX | Profit ${profit:.2f} → CLOSE")
                close_position_mt5(ticket)
                continue

            if not rate_ok:
                continue

            candles_scalp = get_candles_from_mt5(scalp_tf, 30)

            if hold_sec >= MAX_HOLD_SEC and profit <= 0:
                forecast = ai_quick_forecast(
                    candles_scalp, current_price, pos_type, profit, scalp_tf,
                    open_price=open_price, hold_sec=hold_sec,
                )
                print(f"[SMART] ⏰ #{ticket} {hold_sec}s > MAX, loss ${profit:.2f} | AI: {forecast['action']} — {forecast['reason']}")
                if forecast["action"] == "CLOSE":
                    close_position_mt5(ticket)
                continue

            if profit >= min_profit_close and hold_sec >= MIN_HOLD_SEC:
                forecast = ai_quick_forecast(
                    candles_scalp, current_price, pos_type, profit, scalp_tf,
                    open_price=open_price, hold_sec=hold_sec,
                )
                print(f"[SMART] 💰 #{ticket} {pos_type} | {hold_sec}s | ${profit:.2f} | AI: {forecast['action']} — {forecast['reason']}")
                if forecast["action"] == "CLOSE":
                    close_position_mt5(ticket)

            # Check losing positions approaching max hold (70-100% of MAX_HOLD_SEC)
            if profit <= 0 and hold_sec > MAX_HOLD_SEC * 0.7:
                forecast = ai_quick_forecast(
                    candles_scalp, current_price, pos_type, profit, scalp_tf,
                    open_price=open_price, hold_sec=hold_sec,
                )
                print(f"[SMART] ⚠️ #{ticket} losing ${profit:.2f} at {hold_sec}s | AI: {forecast['action']}")
                if forecast["action"] == "CLOSE":
                    close_position_mt5(ticket)

        # Cleanup stale entries
        open_tickets = {p["ticket"] for p in positions}
        with _forecast_lock:
            for t in list(_forecast_cooldown.keys()):
                if t not in open_tickets:
                    del _forecast_cooldown[t]
        for t in list(_last_prices.keys()):
            if t not in open_tickets:
                del _last_prices[t]
        _partial_closed.difference_update(_partial_closed - open_tickets)

    except Exception as e:
        print(f"[SMART] ⚠️ Position monitor error: {e}")


# ==========================================
# 4.7  FRIDAY AUTO-CLOSE (Weekend Gap Protection)
# ==========================================
def is_friday_close_window(minutes_before: int = 30) -> bool:
    """Check if we are within N minutes of Friday market close (22:00 UTC)."""
    now = datetime.now(timezone.utc)
    if now.weekday() != 4:  # Not Friday
        return False
    # Friday close = 22:00 UTC → cutoff = 22:00 - minutes_before
    cutoff_hour = 22 - (minutes_before // 60)
    cutoff_min  = 0 - (minutes_before % 60)
    if cutoff_min < 0:
        cutoff_hour -= 1
        cutoff_min += 60
    cutoff = now.replace(hour=cutoff_hour, minute=cutoff_min, second=0, microsecond=0)
    return now >= cutoff


def friday_auto_close() -> int:
    """Close ALL open positions before Friday market close. Returns number of positions closed."""
    global _friday_closed
    if _friday_closed:
        return 0

    windows_ip = os.getenv("WINDOWS_IP")
    if not windows_ip:
        return 0

    try:
        resp = http_session.get(f"http://{windows_ip}:8000/positions", timeout=5)
        resp.raise_for_status()
        positions = resp.json().get("positions", [])
        if not positions:
            _friday_closed = True
            return 0

        closed_count = 0
        total_profit = 0.0
        for pos in positions:
            ticket = pos["ticket"]
            profit = pos["profit"]
            pos_type = pos["type"]
            total_profit += profit
            print(f"[FRIDAY-CLOSE] 🔒 #{ticket} {pos_type} profit=${profit:+.2f} → CLOSING")
            result = close_position_mt5(ticket)
            if result:
                closed_count += 1
                log_event("FRIDAY_CLOSE", f"#{ticket} {pos_type} closed at ${profit:+.2f}")
            else:
                print(f"[FRIDAY-CLOSE] ⚠️ #{ticket} close failed — will retry next cycle")

        if closed_count > 0:
            print(f"[FRIDAY-CLOSE] ✅ Closed {closed_count}/{len(positions)} positions | Total P/L: ${total_profit:+.2f}")
            log_event("FRIDAY_CLOSE_DONE", f"Closed {closed_count} positions, total P/L=${total_profit:+.2f}")

        if closed_count == len(positions):
            _friday_closed = True

        return closed_count
    except Exception as e:
        print(f"[FRIDAY-CLOSE] ❌ Error: {e}")
        return 0


_monitor_sync_counter = 0  # sync closed trades every N monitor cycles

def _position_monitor_thread():
    """Monitor thread with auto-restart, periodic sync, pre-news flatten, and Friday auto-close."""
    global _monitor_sync_counter, _friday_closed
    print(f"[SMART] 🔄 Position Monitor started (interval={POSITION_CHECK_INTERVAL}s)")
    log_event("MONITOR_START", f"Position Monitor started (interval={POSITION_CHECK_INTERVAL}s)")
    consecutive_monitor_errors = 0
    while not _shutdown:
        try:
            market_open, _ = is_market_open()

            # Reset Friday flag when it's no longer Friday (for next week)
            now_utc = datetime.now(timezone.utc)
            if now_utc.weekday() != 4:
                _friday_closed = False

            # ---- Friday Auto-Close (before market close check) ----
            if FRIDAY_AUTO_CLOSE and is_friday_close_window(FRIDAY_CLOSE_MINUTES_BEFORE):
                friday_auto_close()

            if market_open:
                _, _, _, _, _, scalp_tf = check_bot_status()
                smart_position_monitor(scalp_tf=scalp_tf)

                # Sync closed trades every ~12 cycles (~60s at 5s interval)
                _monitor_sync_counter += 1
                if _monitor_sync_counter >= 12:
                    _monitor_sync_counter = 0
                    sync_closed_trades()

                # Pre-news position flatten: if high-impact news in 5min,
                # close any position that isn't yet at breakeven
                try:
                    news_soon, news_evt = is_high_impact_news_imminent(window_min=5)
                    if news_soon:
                        windows_ip = os.getenv("WINDOWS_IP")
                        if windows_ip:
                            resp = http_session.get(f"http://{windows_ip}:8000/positions", timeout=5)
                            positions = resp.json().get("positions", [])
                            for pos in positions:
                                if pos["profit"] <= 0:
                                    print(f"[NEWS-FLATTEN] ⚠️ #{pos['ticket']} losing ${pos['profit']:.2f} — news '{news_evt}' in <5min → CLOSE")
                                    close_position_mt5(pos["ticket"])
                                    log_event("NEWS_FLATTEN", f"Closed #{pos['ticket']} before '{news_evt}'")
                except Exception:
                    pass  # news flatten is best-effort

            consecutive_monitor_errors = 0
        except Exception as e:
            consecutive_monitor_errors += 1
            print(f"[SMART] ⚠️ Monitor thread error ({consecutive_monitor_errors}): {e}")
            if consecutive_monitor_errors >= 10:
                print("[SMART] 🔴 Monitor thread: 10 consecutive errors — sleeping 60s before retry")
                log_event("MONITOR_ERROR", f"10 consecutive errors, last: {e}")
                time.sleep(60)
                consecutive_monitor_errors = 0
        time.sleep(POSITION_CHECK_INTERVAL)
    print("[SMART] Position Monitor stopped")


def _start_monitor_thread():
    """Start position monitor in a supervised thread that auto-restarts on crash."""
    def supervisor():
        while not _shutdown:
            try:
                _position_monitor_thread()
            except Exception as e:
                print(f"[SMART] 🔴 Monitor thread crashed: {e} — restarting in 10s")
                log_event("MONITOR_CRASH", str(e))
                time.sleep(10)
        print("[SMART] Monitor supervisor stopped")

    t = threading.Thread(target=supervisor, daemon=True)
    t.start()
    return t


def log_event(event_type: str, message: str):
    try:
        conn = get_db_connection()
        cur  = conn.cursor()
        cur.execute(
            "INSERT INTO bot_events (event_type, message) VALUES (%s, %s)",
            (event_type, message),
        )
        conn.commit()
        cur.close()
        conn.close()
    except Exception:
        pass


# ==========================================
# 5. BOT STATUS
# ==========================================
def check_bot_status():
    try:
        conn = get_db_connection()
        cur  = conn.cursor()
        cur.execute(
            "SELECT is_running, interval_seconds, "
            "COALESCE(pause_max_retries, 5), COALESCE(pause_retry_sec, 10), "
            "COALESCE(max_trades_per_day, 10), "
            "COALESCE(scalp_timeframe, 'M15') "
            "FROM bot_settings LIMIT 1;"
        )
        row = cur.fetchone()
        cur.close()
        conn.close()
        if row:
            return bool(row[0]), int(row[1]), int(row[2]), int(row[3]), int(row[4]), str(row[5])
        # No settings row → default STOPPED (must start via Dashboard)
        return False, 300, 5, 10, 10, "M15"
    except Exception as e:
        print(f"[ERROR] Failed to check Bot status: {e}")
        return False, 60, 5, 10, 10, "M15"


def get_today_trade_count() -> int:
    try:
        conn = get_db_connection()
        cur  = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM trades WHERE opened_at >= CURRENT_DATE;")
        row = cur.fetchone()
        cur.close()
        conn.close()
        return int(row[0]) if row else 0
    except Exception as e:
        print(f"[ERROR] Failed to count today trades: {e}")
        return 0


# ==========================================
# MAIN LOOP
# ==========================================
MARKET_CLOSED_CHECK_SEC = 300
CONSECUTIVE_ERR_LIMIT   = 5
MAX_SPREAD = float(os.getenv("MAX_SPREAD", 0.8))


def get_trend_alignment(candles_h1: list, candles_h4: list, candles_d1: list) -> dict:
    """
    Check if H1, H4, D1 trends are aligned.
    Returns: { 'direction': 'BUY'|'SELL'|'MIXED', 'strength': 0-3, 'details': str }
    Strength 3 = all aligned, 2 = H1+H4 agree, 1 = only one TF clear, 0 = conflicting.
    """
    trends = {}
    for label, candles in [("H1", candles_h1), ("H4", candles_h4), ("D1", candles_d1)]:
        if not candles or len(candles) < 21:
            trends[label] = "UNKNOWN"
            continue
        closes = [c["close"] for c in candles]
        ema_9  = calc_ema(closes, 9)
        ema_21 = calc_ema(closes, 21)
        current = closes[-1]
        if ema_9 and ema_21:
            if ema_9 > ema_21 and current > ema_9:
                trends[label] = "BUY"
            elif ema_9 < ema_21 and current < ema_9:
                trends[label] = "SELL"
            else:
                trends[label] = "NEUTRAL"
        else:
            trends[label] = "UNKNOWN"

    buy_count  = sum(1 for v in trends.values() if v == "BUY")
    sell_count = sum(1 for v in trends.values() if v == "SELL")

    if buy_count >= 2:
        direction = "BUY"
        strength  = buy_count
    elif sell_count >= 2:
        direction = "SELL"
        strength  = sell_count
    else:
        direction = "MIXED"
        strength  = max(buy_count, sell_count)

    details = " | ".join(f"{k}={v}" for k, v in trends.items())
    return {"direction": direction, "strength": strength, "details": details}


def count_open_positions(symbol: str = None) -> int:
    """Return number of currently open positions."""
    windows_ip = os.getenv("WINDOWS_IP")
    if not windows_ip:
        return 0
    try:
        resp = http_session.get(f"http://{windows_ip}:8000/positions", timeout=5)
        resp.raise_for_status()
        positions = resp.json().get("positions", [])
        if symbol:
            return sum(1 for p in positions if p["symbol"] == symbol)
        return len(positions)
    except Exception:
        return 0


def has_open_position(symbol: str = None) -> dict | None:
    windows_ip = os.getenv("WINDOWS_IP")
    if not windows_ip:
        return None
    try:
        resp      = http_session.get(f"http://{windows_ip}:8000/positions", timeout=5)
        resp.raise_for_status()
        positions = resp.json().get("positions", [])
        if not positions:
            return None
        if symbol:
            for p in positions:
                if p["symbol"] == symbol:
                    return p
        return positions[0] if positions else None
    except Exception:
        return None


def get_recent_win_rate(days: int = 3) -> dict:
    try:
        conn = get_db_connection()
        cur  = conn.cursor()
        cur.execute(
            """
            SELECT
                COUNT(*) FILTER (WHERE profit > 0) as wins,
                COUNT(*) FILTER (WHERE profit <= 0) as losses,
                COUNT(*) as total,
                COALESCE(SUM(profit), 0) as total_profit
            FROM trades
            WHERE status = 'CLOSED' AND closed_at >= NOW() - INTERVAL '%s days';
            """,
            (days,),
        )
        row = cur.fetchone()
        cur.close()
        conn.close()
        if row and row[2] > 0:
            return {
                "wins": row[0], "losses": row[1], "total": row[2],
                "win_rate":     round(row[0] / row[2] * 100, 1),
                "total_profit": round(float(row[3]), 2),
            }
        return {"wins": 0, "losses": 0, "total": 0, "win_rate": 0, "total_profit": 0}
    except Exception as e:
        print(f"[WARN] get_recent_win_rate: {e}")
        return {"wins": 0, "losses": 0, "total": 0, "win_rate": 0, "total_profit": 0}


# ==========================================
# 5.2  POST-LOSS RECOVERY ANALYSIS
# ==========================================
_last_recovery_ts = 0.0  # prevent rapid-fire recovery

def attempt_recovery_trade(symbol: str, scalp_tf: str):
    """After consecutive losses, do a rapid full AI re-analysis.

    Instead of blindly pausing 30 min, we:
    1. Wait a short cooldown (60s) for market to settle.
    2. Run full AI analysis with extra loss-recovery context.
    3. Only open a recovery trade if confidence >= 7 AND trend-aligned.
    4. If confidence < 7, return False → caller falls back to regular pause.

    Safety guards (same as normal trade path):
    - Position limit check
    - Spread check
    - News check
    - Daily trade limit check
    - Dynamic lot sizing via calculate_lot_size()
    - Reduced risk (half lot) for recovery
    """
    global _last_recovery_ts
    now = time.time()
    RECOVERY_COOLDOWN = int(os.getenv("RECOVERY_COOLDOWN_SEC", 60))

    if now - _last_recovery_ts < RECOVERY_COOLDOWN:
        print("[RECOVERY] ⏳ Recovery cooldown active, skipping")
        return False

    _last_recovery_ts = now
    print("[RECOVERY] 🔄 Running post-loss recovery analysis...")

    try:
        # --- Safety Guard 1: Position limit ---
        open_count = count_open_positions(symbol)
        if open_count >= MAX_CONCURRENT_POS:
            print(f"[RECOVERY] ⛔ {open_count}/{MAX_CONCURRENT_POS} positions open — skipping")
            return False

        # --- Fetch fresh price ---
        windows_ip = os.getenv("WINDOWS_IP")
        price_resp = http_session.get(f"http://{windows_ip}:8000/price/{symbol}", timeout=10)
        price_data = price_resp.json()
        bid, ask = price_data["bid"], price_data["ask"]
        spread = round(ask - bid, 2)

        # --- Safety Guard 2: Spread ---
        if spread > MAX_SPREAD:
            print(f"[RECOVERY] ⛔ Spread {spread} > MAX {MAX_SPREAD} — skipping")
            return False

        # --- Safety Guard 3: News ---
        news_blocked, news_event = is_high_impact_news_imminent(window_min=30)
        if news_blocked:
            print(f"[RECOVERY] ⛔ News imminent: '{news_event}' — skipping")
            return False

        # --- Safety Guard 4: Daily trade limit ---
        max_trades = 10
        try:
            conn = get_db_connection()
            cur = conn.cursor()
            cur.execute("SELECT max_trades_per_day FROM bot_settings LIMIT 1;")
            row = cur.fetchone()
            if row:
                max_trades = row[0]
            cur.close()
            conn.close()
        except Exception:
            pass
        trades_today = get_today_trade_count()
        if trades_today >= max_trades:
            print(f"[RECOVERY] ⛔ Daily limit reached ({trades_today}/{max_trades}) — skipping")
            return False

        # --- Get recent losses for AI context ---
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
            SELECT action, open_price, close_price, profit, sl_price, tp_price
            FROM trades
            WHERE symbol = %s AND status = 'CLOSED' AND profit < 0
            ORDER BY closed_at DESC LIMIT 3;
        """, (symbol,))
        recent_losses = cur.fetchall()
        cur.close()
        conn.close()

        loss_context = "RECENT LOSSES (recovery context):\n"
        for row in recent_losses:
            loss_context += (
                f"  {row[0]} open={row[1]} close={row[2]} P/L=${row[3]:.2f} "
                f"SL={row[4]} TP={row[5]}\n"
            )
        loss_context += (
            "RECOVERY RULE: Analyze if these losses indicate a trend reversal "
            "or were caused by noise. If trend reversed, consider trading the NEW direction. "
            "If losses were noise (e.g. stop hunts), the original direction may still be valid. "
            "Only recommend a trade if you have HIGH confidence (7+).\n"
        )

        # --- Fetch H1 candles for trend ---
        candle_resp = http_session.get(
            f"http://{windows_ip}:8000/candles/{symbol}?timeframe=H1&count=30", timeout=15
        )
        candles_h1 = candle_resp.json().get("candles", [])

        if not candles_h1 or len(candles_h1) < 10:
            print("[RECOVERY] ❌ Insufficient candle data")
            return False

        closes = [c["close"] for c in candles_h1[-20:]]
        ema9 = sum(closes[-9:]) / 9
        ema21 = sum(closes[-21:]) / 21 if len(closes) >= 21 else sum(closes) / len(closes)
        trend_dir = "BUY" if ema9 > ema21 else "SELL"

        # --- AI Analysis ---
        ai_price_data = {"bid": bid, "ask": ask, "spread": spread}
        tech_summary = f"Recovery check | H1 EMA9={ema9:.2f} EMA21={ema21:.2f} Trend={trend_dir}"

        analysis = analyze_with_ai(
            ai_price_data,
            technical_summary=tech_summary,
            journal_knowledge=loss_context,
            scalp_tf=scalp_tf,
        )

        if not analysis:
            print("[RECOVERY] ❌ AI analysis failed")
            return False

        # --- Parse AI result ---
        sentiment, confidence = "", 0
        for line in analysis.split("\n"):
            ll = line.lower().strip()
            if ll.startswith("sentiment:"):
                sentiment = line.split(":", 1)[1].strip().lower()
            elif ll.startswith("confidence:"):
                try:
                    confidence = int("".join(c for c in line.split(":", 1)[1] if c.isdigit())[:2])
                except (ValueError, IndexError):
                    confidence = 0

        action = "WAIT"
        if "bullish" in sentiment and confidence >= 7:
            action = "BUY"
        elif "bearish" in sentiment and confidence >= 7:
            action = "SELL"

        if action == "WAIT":
            print(f"[RECOVERY] ⏸️ AI says {sentiment} conf={confidence} — not confident enough, will pause")
            return False

        # --- Trend alignment (stricter for recovery) ---
        if action != trend_dir:
            if confidence < 9:
                print(f"[RECOVERY] ⏸️ {action} against H1 trend {trend_dir}, conf={confidence} < 9 — skipping")
                return False

        # --- Dynamic lot sizing (use calculate_lot_size, then halve for safety) ---
        atr_h1 = calc_atr(candles_h1, 14) if len(candles_h1) >= 14 else None
        risk_info = calculate_lot_size(atr_value=atr_h1)
        sl_points = risk_info["sl_points"]
        tp_points = risk_info["tp_points"]

        # Recovery uses HALF the normal lot size (reduced risk after losses)
        lot_size = max(0.01, round(risk_info["lot_size"] * 0.5, 2))

        if action == "BUY":
            sl_price = round(ask - sl_points * 0.01, 2)
            tp_price = round(ask + tp_points * 0.01, 2)
        else:
            sl_price = round(bid + sl_points * 0.01, 2)
            tp_price = round(bid - tp_points * 0.01, 2)

        trade_result = send_trade_to_mt5(action, symbol, lot_size, sl_points, tp_points, bid, ask)
        if trade_result and trade_result.get("success"):
            print(f"[RECOVERY] ✅ Recovery {action} | lot={lot_size} (half-risk) conf={confidence} SL={sl_price} TP={tp_price}")
            log_event("RECOVERY_TRADE", f"{action} lot={lot_size} conf={confidence} after losses")
            save_trade_to_db(
                order_id=trade_result["order_id"],
                symbol=symbol,
                action=action,
                lot=lot_size,
                open_price=trade_result.get("price", ask if action == "BUY" else bid),
                sl_price=sl_price,
                tp_price=tp_price,
            )
            return True
        else:
            print(f"[RECOVERY] ❌ Recovery trade failed: {trade_result}")
            return False

    except Exception as e:
        print(f"[RECOVERY] ❌ Recovery analysis error: {e}")
        return False


def main_loop():
    print("🚀 Starting AI Trader Background Service...")
    log_event("START", "AI Trader service started")

    # Force bot to STOPPED state on startup — user must press START on Dashboard
    try:
        conn = get_db_connection()
        cur  = conn.cursor()
        cur.execute("UPDATE bot_settings SET is_running = FALSE, updated_at = NOW();")
        conn.commit()
        cur.close()
        conn.close()
        print("⏸️  [STARTUP] Bot is STOPPED — press ▶️ START on Dashboard to begin trading")
        log_event("STARTUP_STOPPED", "Bot started in STOPPED state — waiting for Dashboard START")
    except Exception as e:
        print(f"[STARTUP] ⚠️ Could not set initial state: {e}")

    symbol = os.getenv("SYMBOL", "XAUUSD")  # Set once, available everywhere in loop

    monitor_thread = _start_monitor_thread()

    consecutive_errors = 0
    pause_retries      = 0
    _last_market_log   = None

    while not _shutdown:
        # ---- Market hours check ----
        market_open, market_reason = is_market_open()
        if not market_open:
            if _last_market_log != market_reason:
                print(f"🌙 [MARKET CLOSED] {market_reason}")
                _last_market_log = market_reason
            time.sleep(MARKET_CLOSED_CHECK_SEC)
            continue
        _last_market_log = None

        # ---- Dashboard kill switch ----
        is_running, interval, max_retries, retry_sec, max_trades, scalp_tf = check_bot_status()
        if not is_running:
            pause_retries += 1
            if max_retries > 0 and pause_retries >= max_retries:
                print(f"⏸️  [BREAKPOINT] Limit reached ({pause_retries}/{max_retries}) – sleeping 5min")
                log_event("BREAKPOINT_LIMIT", f"Limit {pause_retries}/{max_retries}")
                time.sleep(300)
                pause_retries = 0
                continue
            print(f"⏸️  [BREAKPOINT] Paused ({pause_retries}/{max_retries if max_retries>0 else '∞'}) – retry in {retry_sec}s")
            time.sleep(retry_sec)
            continue

        if pause_retries > 0:
            print(f"✅ [RESUMED] Bot resumed after {pause_retries} pause retries")
            log_event("RESUME", f"Resumed after {pause_retries} retries")
            pause_retries = 0

        # ---- Friday: block new trades before close ----
        if FRIDAY_AUTO_CLOSE and is_friday_close_window(FRIDAY_NO_NEW_TRADE_MINUTES):
            now_f = datetime.now(timezone.utc)
            mins_left = (22 * 60) - (now_f.hour * 60 + now_f.minute)
            print(f"[FRIDAY] 🔒 {mins_left}min to market close — no new trades (monitor still active)")
            sync_closed_trades()
            time.sleep(60)
            continue

        # ---- Time-of-day filter ----
        BAD_HOURS_UTC     = [int(h) for h in os.getenv("BAD_HOURS_UTC", "2,3,4,5,6").split(",") if h.strip()]
        current_hour_utc  = datetime.now(timezone.utc).hour
        if current_hour_utc in BAD_HOURS_UTC:
            print(f"[TIME] ⏰ Hour {current_hour_utc:02d} UTC in bad-hours {BAD_HOURS_UTC} – skipping")
            sync_closed_trades()
            time.sleep(60)
            continue

        # ---- Consecutive loss pause (with recovery attempt) ----
        LOSS_PAUSE_THRESHOLD = int(os.getenv("LOSS_PAUSE_THRESHOLD", 3))
        LOSS_PAUSE_SEC       = int(os.getenv("LOSS_PAUSE_SEC",    1800))
        consec_losses = get_consecutive_losses()
        if consec_losses >= LOSS_PAUSE_THRESHOLD:
            print(f"[SAFETY] ⚠️ {consec_losses} consecutive losses – attempting recovery analysis...")
            log_event("LOSS_PAUSE", f"{consec_losses} consecutive losses – running recovery")
            sync_closed_trades()
            # Try recovery trade instead of blind pause
            scalp_tf = os.getenv("SCALP_TIMEFRAME", "M5")
            recovered = attempt_recovery_trade(symbol, scalp_tf)
            if not recovered:
                print(f"[SAFETY] Recovery declined — pausing {LOSS_PAUSE_SEC}s")
                time.sleep(LOSS_PAUSE_SEC)
            else:
                # Recovery trade opened, wait shorter cooldown then continue
                time.sleep(60)
            continue

        # FIX #12: Drawdown protection check
        dd_safe, dd_reason = check_max_drawdown()
        if not dd_safe:
            print(f"[SAFETY] 🔴 {dd_reason} – stopping trading")
            log_event("DRAWDOWN_STOP", dd_reason)
            try:
                conn = get_db_connection()
                cur  = conn.cursor()
                cur.execute("UPDATE bot_settings SET is_running = FALSE, updated_at = NOW();")
                conn.commit()
                cur.close()
                conn.close()
            except Exception:
                pass
            break

        try:
            print(f"\n=== 🟢 AI Trader Node | {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ===")

            # ---- Fetch price ----
            price = get_price_from_mt5()
            if not price or "error" in price:
                raise RuntimeError("Failed to fetch price")

            bid    = price["bid"]
            ask    = price["ask"]
            spread = round(ask - bid, 2)
            symbol = os.getenv("SYMBOL", "XAUUSD")
            print(f"[INFO] Bid {bid} / Ask {ask} / Spread {spread}")

            # FIX #13: MAX_SPREAD default is now 0.8; log when close to limit
            if spread > MAX_SPREAD:
                print(f"[SPREAD] ⚠️ Spread {spread} > MAX {MAX_SPREAD} – skipping (poor conditions)")
                time.sleep(30)
                continue

            # ---- Position limit guard ----
            open_count = count_open_positions(symbol)
            if open_count >= MAX_CONCURRENT_POS:
                existing_pos = has_open_position(symbol)
                if existing_pos:
                    print(
                        f"[GUARD] 🛡️ {open_count}/{MAX_CONCURRENT_POS} positions open: "
                        f"#{existing_pos['ticket']} {existing_pos['type']} "
                        f"Profit=${existing_pos['profit']:.2f} → skipping"
                    )
                sync_closed_trades()
                time.sleep(min(30, interval))
                continue

            # FIX #8: Hard code-level news pause — do NOT rely only on AI for this
            news_blocked, news_event = is_high_impact_news_imminent(window_min=30)
            if news_blocked:
                print(f"[NEWS] 🚫 High-impact event imminent: '{news_event}' – no new trades for 30min")
                log_event("NEWS_PAUSE", f"Paused for: {news_event}")
                time.sleep(300)
                continue

            # ---- Fetch candles ----
            print(f"[INFO] Fetching candles ({scalp_tf}, H1, H4, D1)...")
            candles_scalp = get_candles_from_mt5(scalp_tf, 30)
            candles_h1    = get_candles_from_mt5("H1", 50)
            candles_h4    = get_candles_from_mt5("H4", 50)
            candles_d1    = get_candles_from_mt5("D1", 30)

            tech_summary = ""
            h1_atr       = None
            trend_info   = None
            if candles_h1 and candles_h4 and candles_d1:
                tech_summary = build_technical_summary(
                    candles_h1, candles_h4, candles_d1,
                    candles_scalp=candles_scalp, scalp_tf=scalp_tf,
                )
                h1_atr = calc_atr(candles_h1, 14)
                trend_info = get_trend_alignment(candles_h1, candles_h4, candles_d1)
                print(f"[TECH]\n{tech_summary}")
                print(f"[TREND] Direction={trend_info['direction']} Strength={trend_info['strength']}/3 ({trend_info['details']})")
            else:
                print("[WARN] Incomplete candle data – price-only analysis")

            risk      = calculate_lot_size(atr_value=h1_atr)
            lot_size  = risk["lot_size"]
            sl_points = risk["sl_points"]
            tp_points = risk["tp_points"]

            # Post-loss risk reduction: halve lot after 2+ consecutive losses
            consec_losses_now = get_consecutive_losses()
            if consec_losses_now >= 2:
                reduced_lot = max(0.01, round(lot_size * 0.5, 2))
                print(f"[RISK] ⚠️ {consec_losses_now} consecutive losses → lot {lot_size} → {reduced_lot} (50% reduction)")
                lot_size = reduced_lot

            # ---- Order book ----
            print("[INFO] Fetching Order Book...")
            ob_summary = get_orderbook_from_mt5()
            print(f"[ORDERBOOK] {ob_summary}")

            # ---- News ----
            print("[INFO] Fetching news & Macro Events...")
            news_summary = build_news_summary()
            if news_summary != "No significant news or events found":
                print(f"[NEWS]\n{news_summary}")
            else:
                print("[NEWS] No significant news")

            # ---- Journal & win rate ----
            j_history   = journal_get_recent(5)
            j_knowledge = journal_get_knowledge()
            win_stats   = get_recent_win_rate(3)
            if win_stats["total"] > 0:
                print(
                    f"[STATS] 📊 3-day: {win_stats['wins']}W/{win_stats['losses']}L "
                    f"({win_stats['win_rate']}%) | P/L: ${win_stats['total_profit']}"
                )

            trade_log_summary = get_recent_trade_summary(10)
            if trade_log_summary:
                print(f"[TRADE LOG]\n{trade_log_summary}")

            # ---- AI Analysis ----
            ai_cfg = _get_ai_config()
            print(f"[INFO] Sending to AI ({ai_cfg['provider']}: {ai_cfg['model']})...")

            perf_context = ""
            if win_stats["total"] >= 3:
                perf_context = (
                    f"\n=== BOT PERFORMANCE (Last 3 days) ===\n"
                    f"Win Rate: {win_stats['win_rate']}% ({win_stats['wins']}W/{win_stats['losses']}L) "
                    f"| Net P/L: ${win_stats['total_profit']}"
                )
                if win_stats["win_rate"] < 40:
                    perf_context += "\n⚠️ Low win rate — be more selective"

            # Add trend alignment context for AI
            trend_context = ""
            if trend_info:
                trend_context = (
                    f"\n=== MULTI-TF TREND ALIGNMENT ===\n"
                    f"Direction: {trend_info['direction']} | Strength: {trend_info['strength']}/3\n"
                    f"Details: {trend_info['details']}\n"
                    f"RULE: Trading WITH the trend (strength 2-3) has higher probability. "
                    f"Counter-trend trades need confidence 8+."
                )

            extra_knowledge = ""
            if perf_context:
                extra_knowledge += perf_context
            if trend_context:
                extra_knowledge += trend_context

            analysis = analyze_with_ai(
                price, tech_summary,
                orderbook_summary=ob_summary,
                news_summary=news_summary,
                journal_history=j_history,
                journal_knowledge=(j_knowledge + extra_knowledge) if extra_knowledge else j_knowledge,
                trade_history=trade_log_summary,
                scalp_tf=scalp_tf,
            )
            print(f"\n>>> 🤖 AI RESULT <<<\n{analysis}\n{'='*30}")

            if analysis == "ERROR":
                raise RuntimeError("AI returned ERROR")

            # ---- Parse action ----
            action = parse_sentiment(analysis)
            print(f"[DECISION] 🎯 AI Sentiment → {action}")

            # ---- Trend alignment filter ----
            # If AI says BUY/SELL but trend is opposite on H1+H4, require higher confidence
            if action in ("BUY", "SELL") and trend_info:
                trend_dir = trend_info["direction"]
                trend_str = trend_info["strength"]
                if trend_dir != "MIXED" and trend_dir != action and trend_str >= 2:
                    confidence = _extract_confidence(analysis)
                    if confidence < 8:
                        print(
                            f"[TREND] ⚠️ AI says {action} but trend is {trend_dir} "
                            f"(strength {trend_str}/3), confidence {confidence} < 8 → WAIT"
                        )
                        log_event("TREND_FILTER", f"Blocked {action} — trend={trend_dir} str={trend_str} conf={confidence}")
                        action = "WAIT"
                    else:
                        print(f"[TREND] AI {action} against trend {trend_dir} but confidence {confidence} >= 8 — allowing")

            # ---- Execute trade ----
            sl_price = None
            tp_price = None
            if action in ("BUY", "SELL"):
                trades_today = get_today_trade_count()
                if trades_today >= max_trades:
                    print(f"[LIMIT] ⛔ Daily limit reached ({trades_today}/{max_trades}) – skipping {action}")
                    log_event("LIMIT", f"Max trades/day reached ({trades_today}/{max_trades})")
                    action = "WAIT"
                else:
                    if action == "BUY":
                        sl_price = round(ask - sl_points * 0.01, 2)
                        tp_price = round(ask + tp_points * 0.01, 2)
                    else:
                        sl_price = round(bid + sl_points * 0.01, 2)
                        tp_price = round(bid - tp_points * 0.01, 2)

                    trade_result = send_trade_to_mt5(action, symbol, lot_size, sl_points, tp_points, bid, ask)
                    if trade_result and trade_result.get("success"):
                        log_event("TRADE", f"{action} {symbol} Lot={lot_size} SL={sl_price} TP={tp_price}")
                        save_trade_to_db(
                            order_id=trade_result["order_id"],
                            symbol=symbol,
                            action=action,
                            lot=lot_size,
                            open_price=trade_result.get("price", ask if action == "BUY" else bid),
                            sl_price=sl_price,
                            tp_price=tp_price,
                        )

            # ---- Save log ----
            save_log_to_db(symbol, bid, ask, analysis, lot_size,
                           trade_action=action, sl_price=sl_price, tp_price=tp_price)

            # ---- Journal ----
            confidence = ""
            for line in analysis.split("\n"):
                if "confidence" in line.lower():
                    confidence = line.split(":")[-1].strip() if ":" in line else ""
                    break
            journal_save_analysis(action, analysis, confidence, bid, ask, tech_summary)
            journal_detect_patterns()

            sync_closed_trades()
            consecutive_errors = 0

        except Exception as exc:
            consecutive_errors += 1
            err_msg = f"{exc}\n{traceback.format_exc()}"
            print(f"[ERROR] Cycle failed ({consecutive_errors}/{CONSECUTIVE_ERR_LIMIT}): {exc}")
            log_event("ERROR", err_msg)

            if consecutive_errors >= CONSECUTIVE_ERR_LIMIT:
                print("🔴 [SAFETY] Too many consecutive errors – auto-stopping!")
                log_event("KILL_SWITCH", f"Auto-stopped after {CONSECUTIVE_ERR_LIMIT} errors")
                try:
                    conn = get_db_connection()
                    cur  = conn.cursor()
                    cur.execute("UPDATE bot_settings SET is_running = FALSE, updated_at = NOW();")
                    conn.commit()
                    cur.close()
                    conn.close()
                except Exception:
                    pass
                break

        # ---- Wait interval (chunked for graceful shutdown) ----
        print(f"⏳ Waiting {interval}s before next cycle...")
        waited = 0
        while waited < interval and not _shutdown:
            time.sleep(min(5, interval - waited))
            waited += 5

    log_event("STOP", "AI Trader service stopped")
    print("👋 System shut down successfully")


# ==========================================
# ENTRY POINT
# ==========================================
if __name__ == "__main__":
    main_loop()