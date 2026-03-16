import os
import sys
import time
import json
import signal
import traceback
import requests
import psycopg2
import redis
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv

load_dotenv()

# สร้าง HTTP Session ช่วยลด Latency (Connection Pooling / Keep-Alive)
http_session = requests.Session()

# Flag สำหรับ Graceful Shutdown (Ctrl+C / Docker Stop)
_shutdown = False

# Redis Connection (Market Journal & Cache)
_redis: redis.Redis | None = None


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
    print("\n🛑 [SHUTDOWN] ได้รับสัญญาณหยุด – กำลังปิดระบบอย่างปลอดภัย...")
    _shutdown = True


signal.signal(signal.SIGINT, _handle_signal)
signal.signal(signal.SIGTERM, _handle_signal)


# ==========================================
# HELPER: สร้าง DB Connection (ใช้ซ้ำได้)
# ==========================================
def get_db_connection():
    return psycopg2.connect(
        host=os.getenv("DB_HOST"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASS"),
        dbname=os.getenv("DB_NAME"),
    )


# ==========================================
# HELPER: เช็คตลาดเปิด/ปิด (XAUUSD)
# ==========================================
# XAUUSD Market Hours (UTC):
#   เปิด  : Sunday  23:00 UTC  (= Monday 06:00 ICT)
#   ปิด   : Friday  22:00 UTC  (= Saturday 05:00 ICT)
#   พัก   : Daily   22:00-23:00 UTC (บาง Broker มี daily break)
#   ปิด   : Saturday & Sunday (ยกเว้น Sunday 23:00+)
# ==========================================
def is_market_open() -> tuple[bool, str]:
    """
    เช็คว่าตลาด XAUUSD เปิดอยู่หรือไม่ (อิงเวลา UTC)
    Return: (is_open: bool, reason: str)
    """
    now = datetime.now(timezone.utc)
    weekday = now.weekday()   # 0=Mon, 4=Fri, 5=Sat, 6=Sun
    hour = now.hour
    minute = now.minute

    # Saturday ทั้งวัน -> ปิด
    if weekday == 5:
        return False, "Saturday - market closed"

    # Sunday ก่อน 23:00 UTC -> ปิด
    if weekday == 6 and hour < 23:
        return False, f"Sunday {hour:02d}:{minute:02d} UTC - market opens at 23:00 UTC"

    # Friday หลัง 22:00 UTC -> ปิด
    if weekday == 4 and hour >= 22:
        return False, f"Friday {hour:02d}:{minute:02d} UTC - market closed for weekend"

    # Daily break 22:00-23:00 UTC (Mon-Thu)
    if hour == 22:
        return False, f"Daily break {hour:02d}:{minute:02d} UTC - reopens at 23:00 UTC"

    return True, "Market is open"


# ==========================================
# 1. RISK MANAGEMENT
# ==========================================
def _get_live_balance() -> float | None:
    """ดึง balance จริงจาก MT5 /account endpoint"""
    windows_ip = os.getenv("WINDOWS_IP")
    if not windows_ip:
        return None
    try:
        resp = http_session.get(f"http://{windows_ip}:8000/account", timeout=5)
        resp.raise_for_status()
        data = resp.json()
        return float(data["balance"])
    except Exception as e:
        print(f"[WARN] ดึง balance จาก MT5 ไม่ได้: {e}")
        return None


def calculate_lot_size(atr_value: float | None = None) -> dict:
    """คำนวณ Lot Size, SL, TP แบบ Dynamic ตาม ATR"""
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

    # ATR-based dynamic SL/TP (pro trader approach)
    if atr_value and atr_value > 0:
        # ATR คือราคาจริง (e.g. 5.50) → แปลงเป็น points (*100)
        atr_points = atr_value * 100
        sl_points = round(atr_points * atr_sl_multiplier)
        tp_points = round(atr_points * atr_tp_multiplier)
        # Clamp SL within safe range
        sl_points = max(min_sl, min(max_sl, sl_points))
        tp_points = max(sl_points * 1.5, tp_points)  # TP ต้อง >= 1.5x SL เสมอ
        sl_src = "ATR"
    else:
        sl_points = default_sl
        tp_points = default_tp
        sl_src = "fixed"

    risk_amount = balance * (risk_pct / 100)
    lot_size = risk_amount / sl_points
    final_lot = max(0.01, round(lot_size, 2))

    print(
        f"[RISK] ทุน ${balance:,.2f} ({balance_src}) | เสี่ยง {risk_pct}% (${risk_amount:,.2f}) "
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
        print(f"[ERROR] ไม่สามารถเชื่อมต่อ Windows VPS: {e}")
        return None


def get_candles_from_mt5(timeframe: str = "H1", count: int = 50) -> list | None:
    """ดึง OHLCV candle data จาก MT5 ผ่าน Windows VPS"""
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
        return data.get("candles", [])
    except Exception as e:
        print(f"[ERROR] ดึง Candle data ล้มเหลว: {e}")
        return None


# ==========================================
# 2.1  TECHNICAL INDICATORS (คำนวณจาก candle data)
# ==========================================
def calc_sma(closes: list, period: int) -> float | None:
    """Simple Moving Average"""
    if len(closes) < period:
        return None
    return sum(closes[-period:]) / period


def calc_ema(closes: list, period: int) -> float | None:
    """Exponential Moving Average"""
    if len(closes) < period:
        return None
    multiplier = 2 / (period + 1)
    ema = sum(closes[:period]) / period
    for price in closes[period:]:
        ema = (price - ema) * multiplier + ema
    return ema


def calc_rsi(closes: list, period: int = 14) -> float | None:
    """Relative Strength Index"""
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
    """Average True Range (measures volatility)"""
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


def calc_macd(closes: list, fast: int = 12, slow: int = 26, signal_period: int = 9) -> dict | None:
    """MACD (Moving Average Convergence Divergence)"""
    if len(closes) < slow + signal_period:
        return None
    ema_fast = calc_ema(closes, fast)
    ema_slow = calc_ema(closes, slow)
    if ema_fast is None or ema_slow is None:
        return None

    # คำนวณ MACD line ทั้ง series เพื่อหา signal line
    macd_vals = []
    for i in range(slow, len(closes) + 1):
        ef = calc_ema(closes[:i], fast)
        es = calc_ema(closes[:i], slow)
        if ef is not None and es is not None:
            macd_vals.append(ef - es)

    if len(macd_vals) < signal_period:
        return None

    # Signal line = EMA of MACD values
    multiplier = 2 / (signal_period + 1)
    sig = sum(macd_vals[:signal_period]) / signal_period
    for v in macd_vals[signal_period:]:
        sig = (v - sig) * multiplier + sig

    macd_line = macd_vals[-1]
    histogram = macd_line - sig

    return {
        "macd": round(macd_line, 3),
        "signal": round(sig, 3),
        "histogram": round(histogram, 3),
        "cross": "bullish" if macd_line > sig else "bearish",
    }


def calc_bollinger(closes: list, period: int = 20, std_dev: float = 2.0) -> dict | None:
    """Bollinger Bands"""
    if len(closes) < period:
        return None
    sma = sum(closes[-period:]) / period
    variance = sum((c - sma) ** 2 for c in closes[-period:]) / period
    std = variance ** 0.5
    upper = sma + std_dev * std
    lower = sma - std_dev * std
    current = closes[-1]
    # %B = (price - lower) / (upper - lower)
    pct_b = (current - lower) / (upper - lower) if (upper - lower) > 0 else 0.5
    return {
        "upper": round(upper, 2),
        "middle": round(sma, 2),
        "lower": round(lower, 2),
        "pct_b": round(pct_b, 3),  # 0=lower band, 1=upper band
        "bandwidth": round((upper - lower) / sma * 100, 3),  # volatility %
    }


def calc_support_resistance(candles: list, lookback: int = 20) -> dict:
    """Simple support/resistance from recent highs and lows"""
    recent = candles[-lookback:] if len(candles) >= lookback else candles
    highs = [c["high"] for c in recent]
    lows = [c["low"] for c in recent]
    return {
        "resistance": round(max(highs), 2),
        "support": round(min(lows), 2),
    }


def build_technical_summary(candles_h1: list, candles_h4: list, candles_d1: list,
                           candles_scalp: list = None, scalp_tf: str = "M5") -> str:
    """สร้างสรุป Technical Indicators เพื่อส่งให้ AI"""
    lines = []

    tf_list = [(scalp_tf, candles_scalp), ("H1", candles_h1), ("H4", candles_h4), ("D1", candles_d1)]
    for label, candles in tf_list:
        if not candles or len(candles) < 20:
            if candles is not None:  # None = not requested
                lines.append(f"[{label}] Insufficient data")
            continue

        closes = [c["close"] for c in candles]
        current = closes[-1]

        sma_20 = calc_sma(closes, 20)
        ema_9 = calc_ema(closes, 9)
        ema_21 = calc_ema(closes, 21)
        rsi = calc_rsi(closes, 14)
        atr = calc_atr(candles, 14)
        sr = calc_support_resistance(candles, 20)
        macd = calc_macd(closes)
        bb = calc_bollinger(closes)

        # Trend detection
        trend = "Sideways"
        if ema_9 and ema_21:
            if ema_9 > ema_21 and current > ema_9:
                trend = "Uptrend"
            elif ema_9 < ema_21 and current < ema_9:
                trend = "Downtrend"

        # Last 5 candles summary
        last5 = candles[-5:]
        candle_summary = ""
        for c in last5:
            body = c["close"] - c["open"]
            direction = "Bull" if body > 0 else "Bear"
            candle_summary += f"{direction}({abs(body):.1f}) "

        # Build line
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
            f"Last5: {candle_summary.strip()}",
        ])

        lines.append(" | ".join(parts))

    return "\n".join(lines)


# ==========================================
# 2.2  ORDER BOOK / DEPTH OF MARKET
# ==========================================
def get_orderbook_from_mt5() -> str:
    """ดึง Order Book (DOM) จาก MT5 ผ่าน Windows VPS"""
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
            return (
                f"DOM not available (broker limitation) | "
                f"Spread={data.get('spread', 'N/A')}"
            )

        bid_vol = data.get("bid_total_vol", 0)
        ask_vol = data.get("ask_total_vol", 0)
        total = bid_vol + ask_vol
        bid_pct = round(bid_vol / total * 100, 1) if total > 0 else 50

        # สรุป top 3 levels
        bids = data.get("bids", [])[:3]
        asks = data.get("asks", [])[:3]
        bid_str = ", ".join(f"{b['price']}({b['volume']})" for b in bids)
        ask_str = ", ".join(f"{a['price']}({a['volume']})" for a in asks)

        pressure = "Buyers dominate" if bid_pct > 60 else (
            "Sellers dominate" if bid_pct < 40 else "Balanced"
        )

        return (
            f"Pressure: {pressure} (Bid {bid_pct}% / Ask {round(100 - bid_pct, 1)}%) | "
            f"Top Bids: [{bid_str}] | Top Asks: [{ask_str}]"
        )
    except Exception as e:
        print(f"[WARN] Order book fetch failed: {e}")
        return "Order book unavailable"


# ==========================================
# 2.3  NEWS & MACRO EVENTS (Economic Calendar)
# ==========================================
FINNHUB_CALENDAR_URL = "https://finnhub.io/api/v1/calendar/economic"
FINNHUB_NEWS_URL = "https://finnhub.io/api/v1/news"

# ข่าวที่มีผลต่อทอง
GOLD_KEYWORDS = [
    "gold", "xau", "fed", "fomc", "interest rate", "inflation", "cpi",
    "ppi", "nonfarm", "nfp", "gdp", "unemployment", "treasury", "yields",
    "dollar", "dxy", "usd", "geopolitical", "war", "tariff", "sanctions",
    "central bank", "monetary policy", "quantitative", "recession",
]


def fetch_economic_calendar() -> list[dict]:
    """ดึง Economic Calendar จาก Finnhub (free tier)"""
    api_key = os.getenv("FINNHUB_API_KEY")
    if not api_key:
        return []

    r = get_redis()
    cache_key = "news:calendar"

    # เช็ค cache ก่อน (cache 30 นาที)
    if r:
        cached = r.get(cache_key)
        if cached:
            return json.loads(cached)

    try:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        tomorrow = (datetime.now(timezone.utc) + timedelta(days=1)).strftime("%Y-%m-%d")

        resp = http_session.get(
            FINNHUB_CALENDAR_URL,
            params={"from": today, "to": tomorrow},
            headers={"X-Finnhub-Token": api_key},
            timeout=10,
        )
        if resp.status_code == 403:
            print("[WARN] Finnhub calendar: 403 Forbidden – API key อาจหมดอายุหรือ endpoint นี้ต้อง Premium plan")
            return []
        resp.raise_for_status()
        data = resp.json()
        events = data.get("economicCalendar", [])

        # กรอง high-impact events + เกี่ยวกับ USD/Gold
        important = []
        for ev in events:
            impact = ev.get("impact", "").lower()
            country = ev.get("country", "")
            event_name = ev.get("event", "").lower()

            # เฉพาะ high/medium impact ของ US หรือ global events ที่กระทบทอง
            is_relevant = (
                (country == "US" and impact in ("high", "medium"))
                or any(kw in event_name for kw in GOLD_KEYWORDS)
            )
            if is_relevant:
                important.append({
                    "time": ev.get("time", ""),
                    "country": country,
                    "event": ev.get("event", ""),
                    "impact": impact,
                    "actual": ev.get("actual", ""),
                    "estimate": ev.get("estimate", ""),
                    "prev": ev.get("prev", ""),
                })

        # Cache 30 นาที
        if r and important:
            r.setex(cache_key, 1800, json.dumps(important))

        return important[:10]  # จำกัด 10 events
    except Exception as e:
        print(f"[WARN] Economic calendar fetch failed: {e}")
        return []


def fetch_market_news() -> list[dict]:
    """ดึงข่าว Forex/General จาก Finnhub (free tier)"""
    api_key = os.getenv("FINNHUB_API_KEY")
    if not api_key:
        return []

    r = get_redis()
    cache_key = "news:market"

    # เช็ค cache ก่อน (cache 15 นาที)
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
            print("[WARN] Finnhub news: 403 Forbidden – API key อาจหมดอายุหรือ endpoint นี้ต้อง Premium plan")
            return []
        resp.raise_for_status()
        articles = resp.json()

        # กรองเฉพาะข่าวที่เกี่ยวกับทอง/USD
        relevant = []
        for art in articles[:50]:  # scan top 50
            headline = art.get("headline", "").lower()
            summary = art.get("summary", "").lower()
            text = headline + " " + summary

            if any(kw in text for kw in GOLD_KEYWORDS):
                relevant.append({
                    "headline": art.get("headline", ""),
                    "summary": art.get("summary", "")[:200],
                    "datetime": art.get("datetime", 0),
                })

        # Cache 15 นาที
        if r and relevant:
            r.setex(cache_key, 900, json.dumps(relevant[:5]))

        return relevant[:5]
    except Exception as e:
        print(f"[WARN] Market news fetch failed: {e}")
        return []


def build_news_summary() -> str:
    """สร้างสรุปข่าวและ Economic Events สำหรับส่งให้ AI"""
    lines = []

    # Economic Calendar
    events = fetch_economic_calendar()
    if events:
        lines.append("--- Economic Calendar (Today) ---")
        for ev in events:
            actual = f"Actual={ev['actual']}" if ev.get("actual") else "Pending"
            lines.append(
                f"  [{ev['impact'].upper()}] {ev['time']} {ev['country']} "
                f"{ev['event']} | Est={ev.get('estimate', 'N/A')} Prev={ev.get('prev', 'N/A')} {actual}"
            )

    # Market News
    news = fetch_market_news()
    if news:
        lines.append("--- Latest Gold/USD News ---")
        for n in news:
            lines.append(f"  • {n['headline']}")

    if not lines:
        return "No significant news or events found"

    return "\n".join(lines)


# ==========================================
# 2.4  REDIS MARKET JOURNAL (Knowledge Memory)
# ==========================================
JOURNAL_KEY = "journal:analysis_history"
JOURNAL_MAX_ENTRIES = 20    # เก็บ 20 analysis ล่าสุด
JOURNAL_KNOWLEDGE_KEY = "journal:knowledge"


def journal_save_analysis(action: str, analysis: str, confidence: str,
                          bid: float, ask: float, tech_summary: str):
    """บันทึกผลวิเคราะห์ล่าสุดลง Redis Journal"""
    r = get_redis()
    if not r:
        return

    entry = json.dumps({
        "ts": datetime.now(timezone.utc).isoformat(),
        "action": action,
        "analysis": analysis[:300],
        "confidence": confidence,
        "bid": bid,
        "ask": ask,
        "tech_summary": tech_summary[:500],
    })

    r.lpush(JOURNAL_KEY, entry)
    r.ltrim(JOURNAL_KEY, 0, JOURNAL_MAX_ENTRIES - 1)  # เก็บแค่ N entries


def journal_get_recent(count: int = 5) -> str:
    """ดึง analysis history ล่าสุดจาก Journal เพื่อให้ AI เห็น pattern"""
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
            f"Confidence={e.get('confidence', 'N/A')}"
        )

    return "\n".join(lines)


def journal_update_knowledge(key: str, value: str, ttl: int = 86400):
    """อัปเดต knowledge ใน Redis (เช่น observed patterns, trend shifts)"""
    r = get_redis()
    if not r:
        return
    r.hset(JOURNAL_KNOWLEDGE_KEY, key, value)
    r.expire(JOURNAL_KNOWLEDGE_KEY, ttl)


def journal_get_knowledge() -> str:
    """ดึง accumulated knowledge จาก Redis"""
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
    """วิเคราะห์ pattern จาก analysis history และอัปเดต knowledge"""
    r = get_redis()
    if not r:
        return

    entries = r.lrange(JOURNAL_KEY, 0, JOURNAL_MAX_ENTRIES - 1)
    if len(entries) < 3:
        return

    parsed = [json.loads(e) for e in entries]
    actions = [e["action"] for e in parsed]

    # ตรวจจับ consecutive same direction
    if len(set(actions[:3])) == 1 and actions[0] != "WAIT":
        journal_update_knowledge(
            "streak", f"{actions[0]} streak x{len([a for a in actions if a == actions[0]])}"
        )

    # ตรวจจับ price movement direction
    if len(parsed) >= 2:
        latest_bid = parsed[0].get("bid", 0)
        prev_bid = parsed[1].get("bid", 0)
        if latest_bid and prev_bid:
            move = round(latest_bid - prev_bid, 2)
            direction = "up" if move > 0 else "down" if move < 0 else "flat"
            journal_update_knowledge(
                "last_price_move", f"{direction} ${abs(move)}"
            )

    # ตรวจจับ flip (เปลี่ยนทิศ)
    if len(actions) >= 2 and actions[0] != actions[1] and "WAIT" not in (actions[0], actions[1]):
        journal_update_knowledge(
            "recent_flip", f"Changed from {actions[1]} to {actions[0]}"
        )


# ==========================================
# 2.5  PARSE AI SENTIMENT
# ==========================================
def _extract_confidence(ai_text: str) -> int:
    """ดึงค่า Confidence (1-10) จากข้อความ AI"""
    import re
    match = re.search(r'confidence[:\s]*([0-9]{1,2})', ai_text.lower())
    if match:
        val = int(match.group(1))
        return min(val, 10)
    return 0


def parse_sentiment(ai_text: str) -> str:
    """
    แยก Sentiment จากข้อความ AI → return 'BUY' / 'SELL' / 'WAIT'
    - Bullish → BUY (confidence ≥ 5)
    - Bearish → SELL (confidence ≥ 5)
    - SELL with keyword if AI says SELL explicitly
    - BUY with keyword if AI says BUY explicitly
    - Neutral → WAIT
    """
    text_lower = ai_text.lower()
    confidence = _extract_confidence(ai_text)
    min_confidence = int(os.getenv("MIN_CONFIDENCE", 5))

    # ดึง sentiment จาก AI response
    sentiment = "WAIT"
    if "bullish" in text_lower:
        sentiment = "BUY"
    elif "bearish" in text_lower:
        sentiment = "SELL"

    # ถ้า AI เขียน action ตรงๆ เช่น "Action: BUY" หรือ "→ SELL"
    import re
    action_match = re.search(r'(?:action|signal|recommendation)[:\s]*(buy|sell)', text_lower)
    if action_match:
        sentiment = action_match.group(1).upper()

    # เช็ค confidence threshold
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
    """
    ส่งคำสั่ง BUY/SELL ไปที่ Windows VPS
    Expected endpoint:  POST http://{WINDOWS_IP}:8000/trade
    Payload:  { action, symbol, lot, sl, tp }
    """
    windows_ip = os.getenv("WINDOWS_IP")
    url = f"http://{windows_ip}:8000/trade"

    # คำนวณราคา SL / TP จริง
    if action == "BUY":
        entry = ask
        sl_price = round(entry - sl_points * 0.01, 2)   # XAUUSD 1 point = 0.01
        tp_price = round(entry + tp_points * 0.01, 2)
    elif action == "SELL":
        entry = bid
        sl_price = round(entry + sl_points * 0.01, 2)
        tp_price = round(entry - tp_points * 0.01, 2)
    else:
        print("[INFO] ⏸️  AI แนะนำ WAIT – ไม่ส่งคำสั่งเทรด")
        return None

    payload = {
        "action": action,
        "symbol": symbol,
        "lot": lot,
        "sl": sl_price,
        "tp": tp_price,
    }

    print(f"[TRADE] 📤 ส่งคำสั่ง {action} | Lot {lot} | SL {sl_price} | TP {tp_price}")

    try:
        resp = http_session.post(url, json=payload, timeout=10)
        resp.raise_for_status()
        result = resp.json()
        print(f"[TRADE] ✅ คำสั่งสำเร็จ: {result}")
        return result
    except Exception as e:
        print(f"[TRADE] ❌ ส่งคำสั่งล้มเหลว: {e}")
        return None


# ==========================================
# 3. AI ANALYSIS (OPTIMIZED LATENCY)
# ==========================================
def _get_ai_config() -> dict:
    """Return API config based on AI_PROVIDER env var."""
    provider = os.getenv("AI_PROVIDER", "openrouter").lower()

    if provider == "nvidia":
        return {
            "provider": "nvidia",
            "api_key": os.getenv("NVIDIA_API_KEY"),
            "url": os.getenv("NVIDIA_URL", "https://integrate.api.nvidia.com/v1/chat/completions"),
            "model": os.getenv("NVIDIA_MODEL", "meta/llama-3.1-70b-instruct"),
        }
    else:
        return {
            "provider": "openrouter",
            "api_key": os.getenv("OPENROUTER_API_KEY"),
            "url": os.getenv("OPENROUTER_URL"),
            "model": os.getenv("MODEL"),
        }


def analyze_with_ai(price_data, technical_summary: str = "",
                    orderbook_summary: str = "", news_summary: str = "",
                    journal_history: str = "", journal_knowledge: str = "",
                    scalp_tf: str = "M5") -> str:
    ai_cfg = _get_ai_config()
    api_key = ai_cfg["api_key"]
    url = ai_cfg["url"]
    model = ai_cfg["model"]

    max_tokens = int(os.getenv("MAX_TOKENS", 400))
    temperature = float(os.getenv("TEMPERATURE", 0.1))

    if not api_key:
        print(f"[ERROR] ไม่พบ API Key สำหรับ provider '{ai_cfg['provider']}' ใน .env")
        return "ERROR"

    stf = scalp_tf  # short alias for string interpolation
    system_prompt = (
        "You are a professional XAUUSD (Gold) short-term scalp/swing trader with 15+ years experience. "
        f"You analyze multi-timeframe data ({stf}, H1, H4, D1) using EMA crossovers, RSI, MACD, "
        "Bollinger Bands, ATR, support/resistance, candlestick patterns, order flow, and macro events.\n\n"
        "TRADING STYLE: Short-term scalping & quick swing trades (3-15 min hold time). "
        "You are DECISIVE — you look for opportunities, not reasons to stay out.\n\n"
        "DECISION RULES (need 3+ signals aligned, NOT all):\n"
        "- BUY (Bullish): At least 3 of: EMA9>EMA21 on H1 OR H4, RSI 30-60, "
        "MACD histogram positive or bullish crossover, price near/below lower Bollinger Band (BB%B<0.3), "
        f"price bouncing off support, bullish candle pattern on {stf}/H1, "
        "geopolitical risk rising, buyers stronger in order book\n"
        "- SELL (Bearish): At least 3 of: EMA9<EMA21 on H1 OR H4, RSI 40-70, "
        "MACD histogram negative or bearish crossover, price near/above upper Bollinger Band (BB%B>0.7), "
        f"price rejected at resistance, bearish candle pattern on {stf}/H1, "
        "USD strengthening, sellers stronger in order book\n"
        "- WAIT (Neutral): ONLY when fewer than 2 signals align, "
        "RSI extreme (>75 or <25) without reversal confirmation, "
        "OR high-impact news (CPI/NFP/FOMC) pending within 30 minutes\n\n"
        f"{stf} SCALP RULES (use {stf} data for entry timing):\n"
        f"- If H1 trend is clear but {stf} shows pullback → good entry (trade WITH H1 trend)\n"
        f"- If {stf} RSI is oversold (<30) in an H1 uptrend → strong BUY signal\n"
        f"- If {stf} RSI is overbought (>70) in an H1 downtrend → strong SELL signal\n"
        f"- If {stf} MACD just crossed bullish/bearish → confirms entry direction\n\n"
        "IMPORTANT: If order book data is not available, IGNORE it — do NOT treat missing DOM as negative signal.\n\n"
        "BIAS RULES:\n"
        "- Geopolitical tension/war/sanctions → Gold bullish bias (lean BUY)\n"
        "- When H1 and H4 agree on direction → take the trade even if D1 is sideways\n"
        "- When recent candles show strong momentum in one direction → follow momentum\n"
        f"- Sideways D1 does NOT mean WAIT — use H1/{stf} for short-term scalps\n"
        "- Bollinger Band squeeze (low bandwidth) → expect breakout soon, prepare to trade the break\n\n"
        "CONFIDENCE: Rate 1-10. If confidence ≥ 5 with directional lean, declare Bullish or Bearish.\n\n"
        "Reply EXACTLY in this format (no extra text):\n"
        "Sentiment: <Bullish/Bearish/Neutral>\n"
        "Confidence: <1-10>\n"
        "Reason: <1-2 sentences explaining key signals>"
    )

    # สร้าง user prompt จากข้อมูลทั้งหมด
    sections = [
        f"=== XAUUSD LIVE DATA ===",
        f"Current Price -> Bid: {price_data['bid']}, Ask: {price_data['ask']}",
        f"Spread: {round(price_data['ask'] - price_data['bid'], 2)}",
    ]

    if technical_summary:
        sections.append(f"\n=== TECHNICAL ANALYSIS (Multi-Timeframe) ===\n{technical_summary}")

    if orderbook_summary:
        sections.append(f"\n=== ORDER BOOK ===\n{orderbook_summary}")

    if news_summary:
        sections.append(f"\n=== NEWS & MACRO EVENTS ===\n{news_summary}")

    if journal_history:
        sections.append(f"\n=== YOUR PREVIOUS ANALYSIS ===\n{journal_history}")

    if journal_knowledge:
        sections.append(f"\n=== OBSERVED PATTERNS ===\n{journal_knowledge}")

    sections.append(
        "\nBased on ALL the above data (technical, order flow, news, history), "
        "provide your trading decision."
    )

    user_prompt = "\n".join(sections)

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "max_tokens": max_tokens,
        "temperature": temperature,
    }

    import time as _time
    max_retries = 2
    last_error = None

    for attempt in range(1, max_retries + 1):
        t_start = _time.time()
        try:
            response = http_session.post(url, headers=headers, json=payload, timeout=15)
            response.raise_for_status()
            resp_json = response.json()
            elapsed_ms = int((_time.time() - t_start) * 1000)

            # บันทึก API usage
            usage = resp_json.get("usage", {})
            save_api_usage(
                provider=ai_cfg["provider"],
                model=model,
                prompt_tokens=usage.get("prompt_tokens", 0),
                completion_tokens=usage.get("completion_tokens", 0),
                total_tokens=usage.get("total_tokens", 0),
                response_time_ms=elapsed_ms,
                status="OK",
            )

            return resp_json["choices"][0]["message"]["content"].strip()
        except Exception as e:
            elapsed_ms = int((_time.time() - t_start) * 1000)
            last_error = e
            save_api_usage(
                provider=ai_cfg["provider"],
                model=model,
                prompt_tokens=0, completion_tokens=0, total_tokens=0,
                response_time_ms=elapsed_ms,
                status="ERROR",
            )
            if attempt < max_retries:
                print(f"[WARN] AI API attempt {attempt}/{max_retries} ล้มเหลว: {e} – retry...")
                _time.sleep(2)
            else:
                print(f"[ERROR] AI API ล้มเหลว (หลัง {max_retries} ครั้ง): {e}")

    return "ERROR"


def save_api_usage(provider, model, prompt_tokens, completion_tokens,
                   total_tokens, response_time_ms, status):
    """บันทึก API usage ลง api_usage_log table"""
    try:
        conn = get_db_connection()
        cur = conn.cursor()
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
        conn = get_db_connection()
        cursor = conn.cursor()

        insert_query = """
        INSERT INTO ai_analysis_log
            (symbol, bid, ask, ai_recommendation, lot_size, trade_action, sl_price, tp_price)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """
        cursor.execute(insert_query, (
            symbol, bid, ask, ai_response, lot_size,
            trade_action, sl_price, tp_price,
        ))
        conn.commit()

        cursor.close()
        conn.close()
        print(f"[SUCCESS] 💾 บันทึก Log ลง Database (Action: {trade_action})")
    except Exception as e:
        print(f"[ERROR] Database Error: {e}")


# ==========================================
# 4.5  TRADE TRACKING – บันทึก & ซิงค์ trades table
# ==========================================
def save_trade_to_db(order_id, symbol, action, lot, open_price,
                     sl_price, tp_price):
    """บันทึก trade ใหม่ที่เพิ่งเปิดลง trades table (status=OPEN)"""
    try:
        conn = get_db_connection()
        cur = conn.cursor()
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
        print(f"[DB] 📝 บันทึก Trade #{order_id} → trades table (OPEN)")
    except Exception as e:
        print(f"[ERROR] save_trade_to_db: {e}")


def sync_closed_trades():
    """
    ซิงค์สถานะ trade จาก MT5 (ผ่าน Windows VPS)
    - ดึง history จาก /history
    - อัปเดต trades ที่ปิดแล้ว (close_price, profit, status=CLOSED)
    - ดึง open positions จาก /positions อัปเดต profit แบบ real-time
    """
    windows_ip = os.getenv("WINDOWS_IP")
    if not windows_ip:
        return

    # --- ซิงค์ Closed Deals ---
    try:
        resp = http_session.get(f"http://{windows_ip}:8000/history?days=7", timeout=10)
        resp.raise_for_status()
        data = resp.json()
        deals = data.get("deals", [])

        if deals:
            conn = get_db_connection()
            cur = conn.cursor()
            for deal in deals:
                cur.execute(
                    """
                    UPDATE trades
                    SET close_price = %s,
                        profit = %s,
                        status = 'CLOSED',
                        closed_at = to_timestamp(%s)
                    WHERE order_id = %s AND status = 'OPEN';
                    """,
                    (deal["price"], deal["profit"], deal["time"], deal["order"]),
                )
            conn.commit()
            updated = sum(1 for d in deals)
            cur.close()
            conn.close()
            if updated:
                print(f"[SYNC] 🔄 ซิงค์ {len(deals)} closed deals จาก MT5")
    except Exception as e:
        print(f"[SYNC] ⚠️ sync closed deals error: {e}")

    # --- ซิงค์ Open Positions (อัปเดต unrealized P/L) ---
    try:
        resp = http_session.get(f"http://{windows_ip}:8000/positions", timeout=10)
        resp.raise_for_status()
        data = resp.json()
        positions = data.get("positions", [])

        if positions:
            conn = get_db_connection()
            cur = conn.cursor()
            for pos in positions:
                cur.execute(
                    """
                    UPDATE trades
                    SET profit = %s
                    WHERE order_id = %s AND status = 'OPEN';
                    """,
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
# ตรวจ position ที่เปิดอยู่ → ปิดอัตโนมัติถ้า:
#   - เปิดนาน > MIN_HOLD_SEC และได้กำไร แต่ไม่ถึง TP
#   - AI วิเคราะห์ M5 แล้วเห็น reversal signs
#   - เปิดนาน > MAX_HOLD_SEC → ปิดทุกกรณีถ้ายังกำไร
#   - Trailing stop: ขยับ SL ตามราคาเมื่อกำไร
#   - Breakeven: ย้าย SL ไป entry price เมื่อกำไรถึง threshold
# ==========================================
POSITION_CHECK_INTERVAL = int(os.getenv("POSITION_CHECK_INTERVAL", 10))   # วินาที
MIN_HOLD_SEC = int(os.getenv("MIN_HOLD_SEC", 180))    # 3 นาที
MAX_HOLD_SEC = int(os.getenv("MAX_HOLD_SEC", 600))    # 10 นาที
MIN_PROFIT_TO_CLOSE = float(os.getenv("MIN_PROFIT_TO_CLOSE", 0.50))  # $0.50 ขั้นต่ำ
BREAKEVEN_PROFIT_USD = float(os.getenv("BREAKEVEN_PROFIT_USD", 1.00))  # ย้าย SL เป็น breakeven เมื่อกำไร $1+
TRAILING_STEP_PRICE = float(os.getenv("TRAILING_STEP_PRICE", 1.0))   # ขยับ trailing stop ทุก $1 ราคาทอง
_forecast_cooldown: dict = {}  # ticket → last_forecast_ts (rate limit AI calls)
AI_FORECAST_COOLDOWN = int(os.getenv("AI_FORECAST_COOLDOWN", 30))  # เรียก AI ไม่บ่อยกว่า 30 วินาที/position


def close_position_mt5(ticket: int) -> dict | None:
    """ส่งคำสั่งปิด position ผ่าน Windows VPS"""
    windows_ip = os.getenv("WINDOWS_IP")
    url = f"http://{windows_ip}:8000/close"
    try:
        resp = http_session.post(url, json={"ticket": ticket}, timeout=10)
        resp.raise_for_status()
        result = resp.json()
        if result.get("success"):
            print(f"[SMART-CLOSE] ✅ ปิด Position #{ticket} สำเร็จ | Profit: ${result.get('profit', 0):.2f}")
            log_event("SMART_CLOSE", f"Closed #{ticket} profit=${result.get('profit', 0):.2f}")
        else:
            print(f"[SMART-CLOSE] ❌ ปิดไม่สำเร็จ #{ticket}: {result.get('error')}")
        return result
    except Exception as e:
        print(f"[SMART-CLOSE] ❌ Error closing #{ticket}: {e}")
        return None


def modify_sl_mt5(ticket: int, new_sl: float, new_tp: float = None) -> bool:
    """ส่งคำสั่งแก้ไข SL/TP ผ่าน Windows VPS (trailing stop / breakeven)"""
    windows_ip = os.getenv("WINDOWS_IP")
    url = f"http://{windows_ip}:8000/modify_sl"
    payload = {"ticket": ticket, "sl": new_sl}
    if new_tp is not None:
        payload["tp"] = new_tp
    try:
        resp = http_session.post(url, json=payload, timeout=10)
        resp.raise_for_status()
        result = resp.json()
        if result.get("success"):
            print(f"[TRAIL] 📐 SL updated #{ticket} → SL={new_sl}")
            return True
        else:
            print(f"[TRAIL] ⚠️ Modify failed #{ticket}: {result.get('error')}")
            return False
    except Exception as e:
        print(f"[TRAIL] ❌ Error: {e}")
        return False


def ai_quick_forecast(candles_scalp: list, current_price: float,
                      position_type: str, profit: float,
                      scalp_tf: str = "M15") -> dict:
    """
    AI วิเคราะห์แบบ lightweight (ใช้ token น้อย) เพื่อ forecast short-term
    Return: {"action": "CLOSE"/"HOLD", "reason": "..."}
    """
    if not candles_scalp or len(candles_scalp) < 10:
        return {"action": "CLOSE", "reason": f"Insufficient {scalp_tf} data, closing profitable trade"}

    # สร้าง compact summary (ประหยัด token)
    closes = [c["close"] for c in candles_scalp]
    last_10 = candles_scalp[-10:]

    ema_5 = calc_ema(closes, 5)
    ema_10 = calc_ema(closes, 10)
    rsi = calc_rsi(closes, 14)

    # Quick momentum check (ไม่ต้องเรียก AI ถ้าชัดเจน)
    if len(closes) >= 3:
        recent_move = closes[-1] - closes[-3]
        if position_type == "BUY" and recent_move < -1.0:
            return {"action": "CLOSE", "reason": f"Price dropping fast ({recent_move:.2f}), protect profit"}
        if position_type == "SELL" and recent_move > 1.0:
            return {"action": "CLOSE", "reason": f"Price rising fast (+{recent_move:.2f}), protect profit"}

    # ถ้า momentum ไม่ชัด → ใช้ AI (compact prompt, ~100 tokens)
    candle_str = " ".join(
        f"{'U' if c['close']>c['open'] else 'D'}{abs(c['close']-c['open']):.1f}"
        for c in last_10
    )

    ai_cfg = _get_ai_config()
    api_key = ai_cfg["api_key"]
    if not api_key:
        return {"action": "HOLD", "reason": "No AI key"}

    compact_prompt = (
        f"XAUUSD {scalp_tf} last 10 candles (U=up D=down): {candle_str}\n"
        f"Price={current_price:.2f} EMA5={ema_5:.2f} EMA10={ema_10:.2f} RSI={rsi}\n"
        f"Open {position_type} trade profit=${profit:.2f}\n"
        f"Will price go {'up' if position_type == 'BUY' else 'down'} in next 5 min?\n"
        f"Reply ONLY: HOLD or CLOSE and 5 words max reason."
    )

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": ai_cfg["model"],
        "messages": [{"role": "user", "content": compact_prompt}],
        "max_tokens": 30,
        "temperature": 0.0,
    }

    try:
        import time as _time
        t_start = _time.time()
        resp = http_session.post(ai_cfg["url"], headers=headers, json=payload, timeout=10)
        resp.raise_for_status()
        resp_json = resp.json()
        elapsed_ms = int((_time.time() - t_start) * 1000)

        usage = resp_json.get("usage", {})
        save_api_usage(
            provider=ai_cfg["provider"],
            model=ai_cfg["model"],
            prompt_tokens=usage.get("prompt_tokens", 0),
            completion_tokens=usage.get("completion_tokens", 0),
            total_tokens=usage.get("total_tokens", 0),
            response_time_ms=elapsed_ms,
            status="OK_FORECAST",
        )

        reply = resp_json["choices"][0]["message"]["content"].strip().upper()
        if "CLOSE" in reply:
            return {"action": "CLOSE", "reason": reply}
        return {"action": "HOLD", "reason": reply}
    except Exception as e:
        print(f"[FORECAST] ⚠️ AI forecast failed: {e}")
        # Fallback: ถ้า AI เรียกไม่ได้ ใช้ technical rule
        if ema_5 and ema_10:
            if position_type == "BUY" and ema_5 < ema_10:
                return {"action": "CLOSE", "reason": "EMA bearish crossover (fallback)"}
            if position_type == "SELL" and ema_5 > ema_10:
                return {"action": "CLOSE", "reason": "EMA bullish crossover (fallback)"}
        return {"action": "HOLD", "reason": "AI unavailable, hold"}


def smart_position_monitor(scalp_tf: str = "M15"):
    """
    ตรวจสอบ open positions และจัดการอัตโนมัติ:
    1. Breakeven: ย้าย SL ไป entry price เมื่อกำไรถึง threshold
    2. Trailing stop: ขยับ SL ตามกำไรที่เพิ่มขึ้น
    3. Time-based close: ปิดเมื่อเปิดนานเกินกำหนด
    4. AI forecast: วิเคราะห์ scalp TF เพื่อตัดสินใจ (rate-limited)
    """
    windows_ip = os.getenv("WINDOWS_IP")
    if not windows_ip:
        return

    try:
        resp = http_session.get(f"http://{windows_ip}:8000/positions", timeout=5)
        resp.raise_for_status()
        data = resp.json()
        positions = data.get("positions", [])

        if not positions:
            return

        now_ts = int(datetime.now(timezone.utc).timestamp())

        for pos in positions:
            ticket = pos["ticket"]
            profit = pos["profit"]
            open_time = pos["time"]
            pos_type = pos["type"]  # "BUY" or "SELL"
            current_price = pos["current_price"]
            open_price = pos["open_price"]
            current_sl = pos["sl"]
            hold_sec = now_ts - open_time

            # ---- Breakeven: ย้าย SL ไป entry price (+0.10 buffer) ----
            if profit >= BREAKEVEN_PROFIT_USD and current_sl != 0:
                breakeven_sl = round(open_price + (0.10 if pos_type == "BUY" else -0.10), 2)
                if pos_type == "BUY" and current_sl < breakeven_sl:
                    print(f"[BREAKEVEN] 🔒 #{ticket} profit=${profit:.2f} → SL to breakeven {breakeven_sl}")
                    modify_sl_mt5(ticket, breakeven_sl)
                elif pos_type == "SELL" and current_sl > breakeven_sl:
                    print(f"[BREAKEVEN] 🔒 #{ticket} profit=${profit:.2f} → SL to breakeven {breakeven_sl}")
                    modify_sl_mt5(ticket, breakeven_sl)

            # ---- Trailing Stop: ขยับ SL ตามกำไร ----
            if profit >= BREAKEVEN_PROFIT_USD * 2 and current_sl != 0:
                if pos_type == "BUY":
                    ideal_sl = round(current_price - TRAILING_STEP_PRICE * 2, 2)
                    if ideal_sl > current_sl and ideal_sl > open_price:
                        print(f"[TRAIL] 📈 #{ticket} trailing SL {current_sl} → {ideal_sl}")
                        modify_sl_mt5(ticket, ideal_sl)
                elif pos_type == "SELL":
                    ideal_sl = round(current_price + TRAILING_STEP_PRICE * 2, 2)
                    if ideal_sl < current_sl and ideal_sl < open_price:
                        print(f"[TRAIL] 📉 #{ticket} trailing SL {current_sl} → {ideal_sl}")
                        modify_sl_mt5(ticket, ideal_sl)

            # ยังไม่ถึงเวลาตรวจ time-based rules
            if hold_sec < MIN_HOLD_SEC:
                continue

            # ถ้าขาดทุน → ไม่ปิด (ให้ SL จัดการ ยกเว้นเกิน MAX_HOLD_SEC)
            if profit <= 0 and hold_sec < MAX_HOLD_SEC:
                continue

            # ---- กรณี 1: เปิดนานเกิน MAX_HOLD แต่ยังได้กำไร → ปิดเลย ----
            if hold_sec >= MAX_HOLD_SEC and profit > 0:
                print(
                    f"[SMART] ⏰ Position #{ticket} open {hold_sec}s > MAX {MAX_HOLD_SEC}s "
                    f"| Profit ${profit:.2f} → CLOSE"
                )
                close_position_mt5(ticket)
                continue

            # ---- กรณี 2: เปิดนานเกิน MAX_HOLD และขาดทุน → AI ตัดสินใจ (rate-limited) ----
            if hold_sec >= MAX_HOLD_SEC and profit <= 0:
                # Rate limit: ไม่เรียก AI บ่อยเกินไป
                last_call = _forecast_cooldown.get(ticket, 0)
                if now_ts - last_call < AI_FORECAST_COOLDOWN:
                    continue
                _forecast_cooldown[ticket] = now_ts

                candles_scalp = get_candles_from_mt5(scalp_tf, 20)
                forecast = ai_quick_forecast(candles_scalp, current_price, pos_type, profit, scalp_tf=scalp_tf)
                print(
                    f"[SMART] ⏰ Position #{ticket} open {hold_sec}s > MAX, "
                    f"loss ${profit:.2f} | AI: {forecast['action']} ({forecast['reason']})"
                )
                if forecast["action"] == "CLOSE":
                    close_position_mt5(ticket)
                continue

            # ---- กรณี 3: ได้กำไร > min profit, เปิด > MIN_HOLD → AI forecast (rate-limited) ----
            if profit >= MIN_PROFIT_TO_CLOSE and hold_sec >= MIN_HOLD_SEC:
                last_call = _forecast_cooldown.get(ticket, 0)
                if now_ts - last_call < AI_FORECAST_COOLDOWN:
                    continue
                _forecast_cooldown[ticket] = now_ts

                candles_scalp = get_candles_from_mt5(scalp_tf, 20)

                forecast = ai_quick_forecast(candles_scalp, current_price, pos_type, profit, scalp_tf=scalp_tf)
                print(
                    f"[SMART] 💰 Position #{ticket} | {pos_type} | "
                    f"Hold {hold_sec}s | Profit ${profit:.2f} | "
                    f"AI: {forecast['action']} ({forecast['reason']})"
                )

                if forecast["action"] == "CLOSE":
                    close_position_mt5(ticket)

        # Cleanup cooldown dict for closed positions
        open_tickets = {p["ticket"] for p in positions}
        for t in list(_forecast_cooldown.keys()):
            if t not in open_tickets:
                del _forecast_cooldown[t]

    except Exception as e:
        print(f"[SMART] ⚠️ Position monitor error: {e}")


def _position_monitor_thread():
    """Thread ที่รัน smart_position_monitor loop"""
    print(f"[SMART] 🔄 Position Monitor started (check every {POSITION_CHECK_INTERVAL}s)")
    log_event("MONITOR_START", f"Smart Position Monitor started (interval={POSITION_CHECK_INTERVAL}s)")

    while not _shutdown:
        try:
            # เช็คตลาดก่อน
            market_open, _ = is_market_open()
            if market_open:
                # ดึง scalp_tf จาก DB (dynamic, ไม่ต้อง restart)
                _, _, _, _, _, scalp_tf = check_bot_status()
                smart_position_monitor(scalp_tf=scalp_tf)
        except Exception as e:
            print(f"[SMART] ⚠️ Monitor thread error: {e}")
        time.sleep(POSITION_CHECK_INTERVAL)

    print("[SMART] Position Monitor stopped")


def log_event(event_type: str, message: str):
    """บันทึกเหตุการณ์สำคัญลง bot_events"""
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO bot_events (event_type, message) VALUES (%s, %s)",
            (event_type, message),
        )
        conn.commit()
        cur.close()
        conn.close()
    except Exception:
        pass  # ไม่ให้ event logging ทำให้ main loop พัง


# ==========================================
# 5. BOT STATUS – ดึงสถานะจาก Dashboard
# ==========================================
def check_bot_status():
    """
    ถาม Database ว่า Dashboard สั่ง RUN หรือ STOP อยู่
    Return: (is_running, interval_seconds, pause_max_retries, pause_retry_sec, max_trades_per_day, scalp_timeframe)
    """
    try:
        conn = get_db_connection()
        cur = conn.cursor()
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
        return True, 300, 5, 10, 10, "M15"  # Defaults
    except Exception as e:
        print(f"[ERROR] เช็คสถานะ Bot ล้มเหลว: {e}")
        return False, 60, 5, 10, 10, "M15"  # DB พัง -> หยุดเทรดไว้ก่อนเพื่อความปลอดภัย


def get_today_trade_count() -> int:
    """นับจำนวน trades ที่เปิดวันนี้ (UTC)"""
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(
            "SELECT COUNT(*) FROM trades "
            "WHERE opened_at >= CURRENT_DATE;"
        )
        row = cur.fetchone()
        cur.close()
        conn.close()
        return int(row[0]) if row else 0
    except Exception as e:
        print(f"[ERROR] นับ trades วันนี้ล้มเหลว: {e}")
        return 0


# ==========================================
# MAIN LOOP – รันแบบ Background Service
# ==========================================
MARKET_CLOSED_CHECK_SEC = 300  # เมื่อตลาดปิด เช็คซ้ำทุก 5 นาที (ลด resource usage)
CONSECUTIVE_ERR_LIMIT = 5     # ผิดพลาดติดต่อกัน 5 ครั้ง -> หยุดอัตโนมัติ
MAX_SPREAD = float(os.getenv("MAX_SPREAD", 5.0))  # Max spread allowed (in price)


def has_open_position(symbol: str = None) -> dict | None:
    """เช็คว่ามี position เปิดอยู่แล้วหรือไม่ (ป้องกันเปิดซ้ำ)"""
    windows_ip = os.getenv("WINDOWS_IP")
    if not windows_ip:
        return None
    try:
        resp = http_session.get(f"http://{windows_ip}:8000/positions", timeout=5)
        resp.raise_for_status()
        data = resp.json()
        positions = data.get("positions", [])
        if not positions:
            return None
        # ถ้ามี position ของ symbol ที่ต้องการ
        if symbol:
            for p in positions:
                if p["symbol"] == symbol:
                    return p
        return positions[0] if positions else None
    except Exception:
        return None


def get_recent_win_rate(days: int = 3) -> dict:
    """ดึง Win Rate ย้อนหลังเพื่อปรับ confidence"""
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(
            """
            SELECT
                COUNT(*) FILTER (WHERE profit > 0) as wins,
                COUNT(*) FILTER (WHERE profit <= 0) as losses,
                COUNT(*) as total,
                COALESCE(SUM(profit), 0) as total_profit
            FROM trades
            WHERE status = 'CLOSED'
              AND closed_at >= NOW() - INTERVAL '%s days';
            """,
            (days,),
        )
        row = cur.fetchone()
        cur.close()
        conn.close()
        if row and row[2] > 0:
            return {
                "wins": row[0], "losses": row[1], "total": row[2],
                "win_rate": round(row[0] / row[2] * 100, 1),
                "total_profit": round(float(row[3]), 2),
            }
        return {"wins": 0, "losses": 0, "total": 0, "win_rate": 0, "total_profit": 0}
    except Exception as e:
        print(f"[WARN] get_recent_win_rate: {e}")
        return {"wins": 0, "losses": 0, "total": 0, "win_rate": 0, "total_profit": 0}


import threading

def main_loop():
    print("🚀 เริ่มระบบ AI Trader Background Service...")
    log_event("START", "AI Trader service started")

    # ---- เริ่ม Smart Position Monitor Thread ----
    monitor_thread = threading.Thread(target=_position_monitor_thread, daemon=True)
    monitor_thread.start()

    consecutive_errors = 0
    pause_retries = 0             # นับจำนวน retry ขณะ BREAKPOINT
    _last_market_log = None       # ป้องกัน log spam ซ้ำทุกนาที

    while not _shutdown:
        # ---- 0. เช็คตลาดเปิด/ปิด (ประหยัดค่า API) ----
        market_open, market_reason = is_market_open()
        if not market_open:
            if _last_market_log != market_reason:
                print(f"🌙 [MARKET CLOSED] {market_reason}")
                _last_market_log = market_reason
            time.sleep(MARKET_CLOSED_CHECK_SEC)
            continue
        _last_market_log = None

        # ---- 1. เช็ค Kill Switch / Breakpoint จาก Dashboard ----
        is_running, interval, max_retries, retry_sec, max_trades, scalp_tf = check_bot_status()

        if not is_running:
            pause_retries += 1
            # max_retries = 0 หมายถึง retry ไม่จำกัด
            if max_retries > 0 and pause_retries >= max_retries:
                msg = f"Auto-shutdown: BREAKPOINT retry limit reached ({pause_retries}/{max_retries})"
                print(f"🔴 [SHUTDOWN] {msg}")
                log_event("SHUTDOWN", msg)
                break
            print(
                f"⏸️  [BREAKPOINT] ระบบถูกสั่งหยุดจาก Dashboard "
                f"({pause_retries}/{max_retries if max_retries > 0 else '∞'}) "
                f"– เช็คใหม่ใน {retry_sec} วิ"
            )
            time.sleep(retry_sec)
            continue

        # Bot กลับมา RUN → รีเซ็ต pause counter
        if pause_retries > 0:
            print(f"✅ [RESUMED] Bot กลับมาทำงาน (หลัง pause {pause_retries} ครั้ง)")
            log_event("RESUME", f"Bot resumed after {pause_retries} pause retries")
            pause_retries = 0

        # ---- 2. ดึงราคา ----
        try:
            print(f"\n=== 🟢 AI Trader Node | {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ===")

            price = get_price_from_mt5()
            if not price or "error" in price:
                raise RuntimeError("ดึงราคาไม่สำเร็จ")

            bid = price["bid"]
            ask = price["ask"]
            spread = round(ask - bid, 2)
            symbol = os.getenv("SYMBOL", "XAUUSD")
            print(f"[INFO] Bid {bid} / Ask {ask} / Spread {spread}")

            # ---- 2.1 Spread filter ----
            if spread > MAX_SPREAD:
                print(f"[SPREAD] ⚠️ Spread {spread} > MAX {MAX_SPREAD} → ข้ามรอบนี้ (สภาพตลาดไม่ดี)")
                time.sleep(30)
                continue

            # ---- 2.2 Duplicate position guard ----
            existing_pos = has_open_position(symbol)
            if existing_pos:
                print(
                    f"[GUARD] 🛡️ มี Position เปิดอยู่แล้ว: #{existing_pos['ticket']} "
                    f"{existing_pos['type']} Lot={existing_pos['lot']} "
                    f"Profit=${existing_pos['profit']:.2f} → ข้ามการเปิด Order ใหม่"
                )
                # ยังคง sync trades
                sync_closed_trades()
                time.sleep(min(30, interval))
                continue

            # ---- 3. ดึง Candle data + คำนวณ Technical Indicators ----
            print(f"[INFO] ดึง Candle data ({scalp_tf}, H1, H4, D1)...")
            candles_scalp = get_candles_from_mt5(scalp_tf, 30)
            candles_h1 = get_candles_from_mt5("H1", 50)
            candles_h4 = get_candles_from_mt5("H4", 50)
            candles_d1 = get_candles_from_mt5("D1", 30)

            tech_summary = ""
            # คำนวณ ATR จาก H1 สำหรับ dynamic SL/TP
            h1_atr = None
            if candles_h1 and candles_h4 and candles_d1:
                tech_summary = build_technical_summary(
                    candles_h1, candles_h4, candles_d1,
                    candles_scalp=candles_scalp, scalp_tf=scalp_tf,
                )
                h1_atr = calc_atr(candles_h1, 14)
                print(f"[TECH]\n{tech_summary}")
            else:
                print("[WARN] ไม่สามารถดึง candle data ได้ครบ – ใช้ price-only analysis")

            risk = calculate_lot_size(atr_value=h1_atr)
            lot_size  = risk["lot_size"]
            sl_points = risk["sl_points"]
            tp_points = risk["tp_points"]

            # ---- 3.5 ดึง Order Book ----
            print("[INFO] ดึง Order Book...")
            ob_summary = get_orderbook_from_mt5()
            print(f"[ORDERBOOK] {ob_summary}")

            # ---- 3.6 ดึงข่าว & Economic Calendar ----
            print("[INFO] ดึงข่าว & Macro Events...")
            news_summary = build_news_summary()
            if news_summary != "No significant news or events found":
                print(f"[NEWS]\n{news_summary}")
            else:
                print("[NEWS] ไม่มีข่าวสำคัญ")

            # ---- 3.7 ดึง Journal History & Knowledge ----
            j_history = journal_get_recent(5)
            j_knowledge = journal_get_knowledge()

            # ---- 3.8 Win Rate ----
            win_stats = get_recent_win_rate(3)
            if win_stats["total"] > 0:
                print(
                    f"[STATS] 📊 3-day: {win_stats['wins']}W/{win_stats['losses']}L "
                    f"({win_stats['win_rate']}%) | P/L: ${win_stats['total_profit']}"
                )

            # ---- 4. AI วิเคราะห์ ----
            ai_cfg = _get_ai_config()
            print(f"[INFO] ส่งข้อมูลให้ AI ({ai_cfg['provider']}: {ai_cfg['model']})...")

            # เพิ่ม win rate ลง journal knowledge
            perf_context = ""
            if win_stats["total"] >= 3:
                perf_context = (
                    f"\n=== BOT PERFORMANCE (Last 3 days) ===\n"
                    f"Win Rate: {win_stats['win_rate']}% ({win_stats['wins']}W/{win_stats['losses']}L) "
                    f"| Net P/L: ${win_stats['total_profit']}"
                )
                if win_stats["win_rate"] < 40:
                    perf_context += "\n⚠️ Low win rate — be more selective, require stronger signals"

            analysis = analyze_with_ai(
                price, tech_summary,
                orderbook_summary=ob_summary,
                news_summary=news_summary,
                journal_history=j_history,
                journal_knowledge=(j_knowledge + perf_context) if perf_context else j_knowledge,
                scalp_tf=scalp_tf,
            )
            print(f"\n>>> 🤖 AI RESULT <<<\n{analysis}\n{'='*30}")

            if analysis == "ERROR":
                raise RuntimeError("AI ตอบกลับ ERROR")

            # ---- 5. แปลง Sentiment → Action ----
            action = parse_sentiment(analysis)
            print(f"[DECISION] 🎯 AI Sentiment → {action}")

            # ---- 6. ส่งคำสั่งเทรด (ถ้า BUY/SELL) ----
            sl_price = None
            tp_price = None
            if action in ("BUY", "SELL"):
                # เช็ค Max Trades / Day
                trades_today = get_today_trade_count()
                if trades_today >= max_trades:
                    print(
                        f"[LIMIT] ⛔ ถึงลิมิตเทรดวันนี้แล้ว ({trades_today}/{max_trades}) "
                        f"– ข้าม {action}, AI แนะนำแต่ไม่เปิด order"
                    )
                    log_event("LIMIT", f"Max trades/day reached ({trades_today}/{max_trades}), skipped {action}")
                    action = "WAIT"  # override เป็น WAIT เพื่อไม่ให้เทรด
                else:
                    # คำนวณ SL/TP ราคาจริง
                    if action == "BUY":
                        sl_price = round(ask - sl_points * 0.01, 2)
                        tp_price = round(ask + tp_points * 0.01, 2)
                    else:
                        sl_price = round(bid + sl_points * 0.01, 2)
                        tp_price = round(bid - tp_points * 0.01, 2)

                    trade_result = send_trade_to_mt5(
                        action, symbol, lot_size, sl_points, tp_points, bid, ask
                    )
                    if trade_result and trade_result.get("success"):
                        log_event("TRADE", f"{action} {symbol} Lot={lot_size} SL={sl_price} TP={tp_price}")
                        # บันทึกลง trades table
                        save_trade_to_db(
                            order_id=trade_result["order_id"],
                            symbol=symbol,
                            action=action,
                            lot=lot_size,
                            open_price=trade_result.get("price", ask if action == "BUY" else bid),
                            sl_price=sl_price,
                            tp_price=tp_price,
                        )

            # ---- 7. บันทึก Log ----
            save_log_to_db(symbol, bid, ask, analysis, lot_size,
                           trade_action=action, sl_price=sl_price, tp_price=tp_price)

            # ---- 7.5 บันทึก Journal + ตรวจจับ Pattern ----
            # ดึง confidence จาก AI response
            confidence = ""
            for line in analysis.split("\n"):
                if "confidence" in line.lower():
                    confidence = line.split(":")[-1].strip() if ":" in line else ""
                    break
            journal_save_analysis(action, analysis, confidence, bid, ask, tech_summary)
            journal_detect_patterns()

            # ---- 8. ซิงค์สถานะ Trade จาก MT5 ----
            sync_closed_trades()

            consecutive_errors = 0  # รีเซ็ตเมื่อรอบนี้สำเร็จ

        except Exception as exc:
            consecutive_errors += 1
            err_msg = f"{exc}\n{traceback.format_exc()}"
            print(f"[ERROR] รอบนี้ล้มเหลว ({consecutive_errors}/{CONSECUTIVE_ERR_LIMIT}): {exc}")
            log_event("ERROR", err_msg)

            if consecutive_errors >= CONSECUTIVE_ERR_LIMIT:
                print("🔴 [SAFETY] ผิดพลาดติดต่อกันเกินกำหนด – หยุดระบบอัตโนมัติ!")
                log_event("KILL_SWITCH", f"Auto-stopped after {CONSECUTIVE_ERR_LIMIT} consecutive errors")
                # สั่งหยุดผ่าน Database เพื่อให้ Dashboard เห็นด้วย
                try:
                    conn = get_db_connection()
                    cur = conn.cursor()
                    cur.execute("UPDATE bot_settings SET is_running = FALSE, updated_at = NOW();")
                    conn.commit()
                    cur.close()
                    conn.close()
                except Exception:
                    pass
                break

        # ---- 9. รอ Interval (แบ่งเป็นช่วงสั้นเพื่อ Graceful Shutdown) ----
        print(f"⏳ รอ {interval} วินาทีก่อนรอบถัดไป...")
        waited = 0
        while waited < interval and not _shutdown:
            time.sleep(min(5, interval - waited))
            waited += 5

    log_event("STOP", "AI Trader service stopped")
    print("👋 ระบบปิดตัวเรียบร้อย")


# ==========================================
# ENTRY POINT
# ==========================================
if __name__ == "__main__":
    main_loop()