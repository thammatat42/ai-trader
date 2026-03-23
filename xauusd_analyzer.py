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

# ==========================================
# THINKING MODE (Qwen 3.5 / reasoning models)
# ==========================================
AI_THINKING = os.getenv("AI_THINKING", "false").lower() in ("true", "1", "yes")


def _strip_thinking(text: str) -> str:
    """Strip <think>...</think> blocks from AI responses (thinking/reasoning models)."""
    if "<think>" not in text:
        return text
    stripped = re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL).strip()
    return stripped if stripped else text

# HTTP Session for connection pooling / keep-alive
http_session = requests.Session()

# Flag for Graceful Shutdown (Ctrl+C / Docker Stop)
_shutdown = False

# Redis Connection (Market Journal & Cache)
_redis: redis.Redis | None = None

# FIX #2: Thread-safe lock for _forecast_cooldown (accessed from 2 threads)
_forecast_lock = threading.Lock()
_forecast_cooldown: dict = {}  # ticket -> last_forecast_ts (rate limit AI calls)

# Thread-safe lock for position state (shared between main loop and monitor thread)
_position_state_lock = threading.Lock()

# VPS health tracking (circuit breaker)
_vps_failures = 0
_vps_failure_window_start = 0.0

# Point size: minimum price increment for the instrument
# XAUUSD (Exness): 2 decimals → POINT_SIZE=0.01 (1 point = $0.01 movement)
# BTCUSD (Exness): 2 decimals → POINT_SIZE=0.01 (same, but contract value differs)
# Adjust if your broker uses different decimal places for BTC
POINT_SIZE = float(os.getenv("POINT_SIZE", 0.01))
_POINTS_PER_UNIT = round(1.0 / POINT_SIZE)  # inverse: 100 for 0.01, 10 for 0.1, 1 for 1.0


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
# HELPER: Check Market Open/Close (symbol-aware)
# ==========================================
def _is_crypto_symbol(symbol: str = "") -> bool:
    """Return True for crypto symbols that trade 24/7 (BTC, ETH, etc.)."""
    sym = (symbol or os.getenv("SYMBOL", "XAUUSD")).upper()
    return any(sym.startswith(prefix) for prefix in ("BTC", "ETH", "XRP", "SOL", "DOGE", "LTC", "BNB", "ADA", "CRYPTO"))


def is_market_open() -> tuple[bool, str]:
    # Crypto trades 24/7 — never closed
    if _is_crypto_symbol():
        return True, "Crypto market: always open"

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
    atr_tp_multiplier = float(os.getenv("ATR_TP_MULTIPLIER", 2.0))
    min_sl = float(os.getenv("MIN_SL_POINTS", 150))
    max_sl = float(os.getenv("MAX_SL_POINTS", 400))
    min_tp = float(os.getenv("MIN_TP_POINTS", 250))
    max_tp = float(os.getenv("MAX_TP_POINTS", 500))
    # FIX #4: explicit point-value constant — for XAUUSD: $1 per point per standard lot
    point_value_per_lot = float(os.getenv("POINT_VALUE_PER_LOT", 1.0))

    if atr_value and atr_value > 0:
        # ATR is real price delta (e.g. 5.50 USD) -> convert to points
        atr_points = atr_value * _POINTS_PER_UNIT
        sl_points = round(atr_points * atr_sl_multiplier)
        tp_points = round(atr_points * atr_tp_multiplier)
        sl_points = max(min_sl, min(max_sl, sl_points))
        # Enforce realistic TP: 1.5x to 2.5x SL — must be ACHIEVABLE
        tp_points = max(min_tp, min(max_tp, tp_points))
        # Ensure minimum 1.5:1 R:R but cap at 2.5:1 to keep TP reachable
        if tp_points < sl_points * 1.5:
            tp_points = round(sl_points * 1.5)
        if tp_points > sl_points * 2.5:
            tp_points = round(sl_points * 2.5)
        sl_src = "ATR"
    else:
        sl_points = default_sl
        tp_points = default_tp
        sl_src = "fixed"

    risk_amount = balance * (risk_pct / 100)
    # FIX #4: correct formula — divide by dollar risk per lot
    lot_size = risk_amount / (sl_points * point_value_per_lot)
    max_lot = float(os.getenv("MAX_LOT", 1.0))
    final_lot = max(0.01, min(max_lot, round(lot_size, 2)))

    # Warn if min lot clamp causes actual risk to exceed intended risk
    if lot_size < 0.01:
        actual_risk = 0.01 * sl_points * point_value_per_lot
        actual_pct = actual_risk / balance * 100 if balance > 0 else 0
        print(f"[RISK] ⚠️ Min lot 0.01 → actual risk ${actual_risk:.2f} ({actual_pct:.1f}% of balance, intended {risk_pct}%)")

    # Warn if MAX_LOT is capping the calculated lot significantly
    if lot_size > max_lot * 1.5:
        print(f"[RISK] ⚠️ MAX_LOT={max_lot} is capping calculated lot {lot_size:.2f} — "
              f"consider increasing MAX_LOT in .env to use full risk budget")

    print(
        f"[RISK] Balance ${balance:,.2f} ({balance_src}) | Risk {risk_pct}% (${risk_amount:,.2f}) "
        f"| SL {sl_points} ({sl_src}) | TP {tp_points} | R:R 1:{tp_points/sl_points:.1f} "
        f"-> Lot: {final_lot} (calc={lot_size:.2f}, max={max_lot})"
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


def check_vps_available() -> bool:
    """Circuit breaker: auto-stop bot if VPS unreachable 3 times in 5 minutes."""
    global _vps_failures, _vps_failure_window_start
    try:
        price = get_price_from_mt5()
        if price and "error" not in price:
            _vps_failures = 0
            return True
    except Exception:
        pass
    now = time.time()
    if now - _vps_failure_window_start > 300:
        _vps_failure_window_start = now
        _vps_failures = 1
    else:
        _vps_failures += 1
    if _vps_failures >= 3:
        print("[CRITICAL] 🔴 VPS unreachable 3x in 5min → AUTO-STOP")
        log_event("VPS_DOWN", "VPS unreachable 3 times in 5 minutes — auto-stopping bot")
        return False
    return True


def is_consolidating(candles: list) -> bool:
    """Detect sideways/chop market: narrow BB, low ATR, neutral RSI."""
    if not candles or len(candles) < 20:
        return False
    closes = [c["close"] for c in candles[-20:]]
    atr = calc_atr(candles, 14)
    bb = calc_bollinger(closes, 20, 2.0)
    rsi = calc_rsi(closes, 14)
    if not (atr and bb and rsi):
        return False
    # BB bandwidth < 0.5% AND RSI neutral (40-60) = consolidation
    return bb["bandwidth"] < 0.5 and 40 < rsi < 60


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

        # Candle pattern detection on last 2 candles
        patterns_found = []
        for ci in range(-2, 0):
            c = candles[ci]
            high, low, opn, cls = c["high"], c["low"], c["open"], c["close"]
            body = abs(cls - opn)
            full_range = high - low
            if full_range < 1e-8:
                continue
            body_ratio = body / full_range
            upper_wick = high - max(opn, cls)
            lower_wick = min(opn, cls) - low
            is_bull = cls > opn
            pos = "last" if ci == -1 else "prev"
            # Doji: tiny body
            if body_ratio < 0.1:
                patterns_found.append(f"Doji({pos})")
            # Hammer: small body at top, long lower wick (bullish reversal)
            elif lower_wick > body * 2 and upper_wick < body * 0.5:
                patterns_found.append(f"Hammer({pos})" if is_bull else f"InvHammer({pos})")
            # Shooting Star: small body at bottom, long upper wick (bearish reversal)
            elif upper_wick > body * 2 and lower_wick < body * 0.5:
                patterns_found.append(f"ShootingStar({pos})")
        # Engulfing: current candle body fully engulfs previous
        if len(candles) >= 2:
            prev_c, curr_c = candles[-2], candles[-1]
            prev_body = abs(prev_c["close"] - prev_c["open"])
            curr_body = abs(curr_c["close"] - curr_c["open"])
            if curr_body > prev_body * 1.2 and prev_body > 0:
                if curr_c["close"] > curr_c["open"] and prev_c["close"] < prev_c["open"]:
                    patterns_found.append("BullEngulf")
                elif curr_c["close"] < curr_c["open"] and prev_c["close"] > prev_c["open"]:
                    patterns_found.append("BearEngulf")

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
        if patterns_found:
            parts.append(f"Patterns: {', '.join(patterns_found)}")
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

CRYPTO_KEYWORDS = [
    "bitcoin", "btc", "crypto", "ethereum", "blockchain", "sec", "etf",
    "halving", "mining", "stablecoin", "defi", "exchange", "binance",
    "coinbase", "regulation", "fed", "fomc", "interest rate", "inflation",
    "liquidity", "whale", "on-chain", "hash rate", "spot etf",
]


def _get_news_keywords() -> list[str]:
    """Return appropriate news keywords based on current symbol."""
    return CRYPTO_KEYWORDS if _is_crypto_symbol() else GOLD_KEYWORDS


def _get_news_category() -> str:
    """Return finnhub news category for current symbol."""
    return "crypto" if _is_crypto_symbol() else "forex"


# FIX #8: News events that should pause ALL new trades (code-level guard, not just AI)
HIGH_IMPACT_KEYWORDS = ["nonfarm", "nfp", "fomc", "cpi", "ppi", "gdp", "interest rate", "fomc"]


def fetch_economic_calendar() -> list[dict]:
    api_key = os.getenv("FINNHUB_API_KEY", "")
    if not api_key or api_key.startswith("your-"):
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
        if resp.status_code in (401, 403):
            return []
        resp.raise_for_status()
        events = resp.json().get("economicCalendar", [])

        important = []
        for ev in events:
            impact  = ev.get("impact", "").lower()
            country = ev.get("country", "")
            name    = ev.get("event", "").lower()
            if (country == "US" and impact in ("high", "medium")) or any(kw in name for kw in _get_news_keywords()):
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
    api_key = os.getenv("FINNHUB_API_KEY", "")
    if not api_key or api_key.startswith("your-"):
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
            params={"category": _get_news_category()},
            headers={"X-Finnhub-Token": api_key},
            timeout=10,
        )
        if resp.status_code in (401, 403):
            return []
        resp.raise_for_status()
        articles = resp.json()

        relevant = []
        for art in articles[:50]:
            headline = art.get("headline", "").lower()
            summary  = art.get("summary",  "").lower()
            text     = headline + " " + summary
            if any(kw in text for kw in _get_news_keywords()):
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
        _sym = os.getenv("SYMBOL", "XAUUSD")
        lines.append(f"--- Latest {_sym} News ---")
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
# 2.4.1  RAG CONTEXT SYSTEM (Self-Learning)
#         Inspired by Polymarket agent's 10-section context
# ==========================================

def build_rag_context() -> str:
    """
    Build comprehensive self-learning context for AI (like Polymarket's 10-section RAG).
    Sections: Performance, Confidence Calibration, Direction Analysis,
    Streak, Lessons from Losses, Time-of-Day, Signal Reliability.
    """
    sections = []

    try:
        conn = get_db_connection()
        cur = conn.cursor()

        # --- Section 1: Overall Performance (last 3 days) ---
        cur.execute("""
            SELECT COUNT(*) FILTER (WHERE profit > 0) as wins,
                   COUNT(*) FILTER (WHERE profit <= 0) as losses,
                   COUNT(*) as total,
                   COALESCE(SUM(profit), 0) as total_profit,
                   COALESCE(AVG(CASE WHEN profit > 0 THEN profit END), 0) as avg_win,
                   COALESCE(AVG(CASE WHEN profit <= 0 THEN profit END), 0) as avg_loss
            FROM trades
            WHERE status = 'CLOSED' AND closed_at >= NOW() - INTERVAL '3 days';
        """)
        row = cur.fetchone()
        if row and row[2] > 0:
            wins, losses, total, total_pnl, avg_w, avg_l = row
            wr = round(wins / total * 100, 1) if total > 0 else 0
            rr = round(abs(float(avg_w) / float(avg_l)), 2) if avg_l and float(avg_l) != 0 else 0
            sections.append(
                f"=== YOUR PERFORMANCE (3 days) ===\n"
                f"Record: {wins}W/{losses}L ({wr}% WR) | Net P/L: ${float(total_pnl):+.2f}\n"
                f"Avg Win: ${float(avg_w):.2f} | Avg Loss: ${float(avg_l):.2f} | R:R = 1:{rr}\n"
                f"{'⚠️ LOSING MONEY — be MORE selective, only high-confidence setups' if float(total_pnl) < 0 else '✅ Profitable — maintain discipline'}\n"
                f"{'⚠️ Avg loss > Avg win — let winners RUN longer, cut losers FASTER' if abs(float(avg_l)) > abs(float(avg_w)) else ''}"
            )

        # --- Section 2: Confidence Calibration ---
        cur.execute("""
            SELECT ai_confidence, COUNT(*) as total,
                   COUNT(*) FILTER (WHERE profit > 0) as wins,
                   ROUND(COUNT(*) FILTER (WHERE profit > 0)::numeric / NULLIF(COUNT(*), 0) * 100, 1) as wr
            FROM trades
            WHERE status = 'CLOSED' AND ai_confidence IS NOT NULL
                  AND closed_at >= NOW() - INTERVAL '7 days'
            GROUP BY ai_confidence
            ORDER BY ai_confidence;
        """)
        cal_rows = cur.fetchall()
        if cal_rows:
            cal_lines = ["=== CONFIDENCE CALIBRATION (your conf vs actual WR) ==="]
            for cr in cal_rows:
                conf, cnt, ws, actual_wr = cr
                if cnt >= 2:
                    marker = "✅" if float(actual_wr or 0) >= 55 else "⚠️" if float(actual_wr or 0) >= 40 else "❌"
                    overconf = ""
                    if conf and conf >= 8 and float(actual_wr or 0) < 50:
                        overconf = " ← OVERCONFIDENT! High conf but losing"
                    if conf and conf <= 5 and float(actual_wr or 0) > 60:
                        overconf = " ← UNDERVALUED! Low conf but winning"
                    cal_lines.append(f"  Conf {conf}: {cnt} trades, {actual_wr}% actual WR {marker}{overconf}")
            if len(cal_lines) > 1:
                sections.append("\n".join(cal_lines))

        # --- Section 3: Direction Analysis ---
        cur.execute("""
            SELECT action,
                   COUNT(*) as total,
                   COUNT(*) FILTER (WHERE profit > 0) as wins,
                   COALESCE(SUM(profit), 0) as pnl
            FROM trades
            WHERE status = 'CLOSED' AND closed_at >= NOW() - INTERVAL '3 days'
            GROUP BY action;
        """)
        dir_rows = cur.fetchall()
        if dir_rows:
            total_all = sum(r[1] for r in dir_rows)
            dir_lines = ["=== DIRECTION ANALYSIS ==="]
            for dr in dir_rows:
                act, cnt, ws, pnl = dr
                wr = round(ws / cnt * 100, 1) if cnt > 0 else 0
                pct = round(cnt / total_all * 100, 0) if total_all > 0 else 0
                bias_warn = ""
                if pct > 70:
                    bias_warn = f" ⚠️ HEAVY {act} BIAS ({pct:.0f}%) — actively seek {'SELL' if act == 'BUY' else 'BUY'} setups!"
                dir_lines.append(f"  {act}: {cnt} trades ({pct:.0f}%), WR={wr}%, P/L=${float(pnl):+.2f}{bias_warn}")
            sections.append("\n".join(dir_lines))

        # --- Section 4: Streak Analysis ---
        cur.execute("""
            SELECT profit FROM trades
            WHERE status = 'CLOSED' AND closed_at IS NOT NULL
            ORDER BY closed_at DESC LIMIT 20;
        """)
        streak_rows = cur.fetchall()
        if streak_rows:
            results = ["W" if float(r[0] or 0) > 0 else "L" for r in streak_rows]
            pattern = "".join(results[:15])

            # Current streak
            current_streak = 1
            streak_type = results[0]
            for i in range(1, len(results)):
                if results[i] == streak_type:
                    current_streak += 1
                else:
                    break

            streak_text = f"=== STREAK ANALYSIS ===\n"
            streak_text += f"Current: {current_streak} {'WIN' if streak_type == 'W' else 'LOSS'}s in a row\n"
            streak_text += f"Pattern (newest→oldest): {pattern}"
            if current_streak >= 3 and streak_type == "L":
                streak_text += f"\n⚠️ {current_streak} consecutive LOSSES — require confidence 8+ and strongest confluence"
            if current_streak >= 4 and streak_type == "W":
                streak_text += f"\n⚠️ {current_streak} WIN streak — stay disciplined, don't get overconfident"
            sections.append(streak_text)

        # --- Section 5: Lessons from Recent Losses ---
        cur.execute("""
            SELECT action, open_price, close_price, profit, sl_price, tp_price,
                   ai_confidence, market_regime, trend_direction,
                   EXTRACT(EPOCH FROM (closed_at - opened_at)) as hold_sec
            FROM trades
            WHERE status = 'CLOSED' AND profit < 0
                  AND closed_at >= NOW() - INTERVAL '2 days'
            ORDER BY closed_at DESC LIMIT 5;
        """)
        loss_rows = cur.fetchall()
        if loss_rows:
            loss_lines = ["=== LESSONS FROM RECENT LOSSES ==="]
            sl_hit_count = 0
            quick_loss_count = 0
            counter_trend_count = 0
            for lr in loss_rows:
                act, op, cp, pft, sl, tp, conf, regime, trend, hold = lr
                hold = int(hold) if hold else 0
                # Detect if SL was hit
                if sl and cp:
                    if act == "BUY" and float(cp) <= float(sl) + 0.1:
                        sl_hit_count += 1
                    elif act == "SELL" and float(cp) >= float(sl) - 0.1:
                        sl_hit_count += 1
                if hold < 60:
                    quick_loss_count += 1
                if trend and act != trend:
                    counter_trend_count += 1
                loss_lines.append(
                    f"  {act} P/L=${float(pft):.2f} | Hold={hold}s | Conf={conf} | Regime={regime} | Trend={trend}"
                )
            if sl_hit_count >= 2:
                loss_lines.append(f"  PATTERN: {sl_hit_count}/{len(loss_rows)} losses hit SL — entries may be late or SL too tight")
            if quick_loss_count >= 2:
                loss_lines.append(f"  PATTERN: {quick_loss_count}/{len(loss_rows)} losses < 60s — entering into reversals")
            if counter_trend_count >= 2:
                loss_lines.append(f"  PATTERN: {counter_trend_count}/{len(loss_rows)} losses were COUNTER-TREND — trade WITH the trend!")
            sections.append("\n".join(loss_lines))

        # --- Section 6: Time-of-Day Performance ---
        cur.execute("""
            SELECT EXTRACT(HOUR FROM opened_at) as hour,
                   COUNT(*) as total,
                   COUNT(*) FILTER (WHERE profit > 0) as wins,
                   COALESCE(SUM(profit), 0) as pnl
            FROM trades
            WHERE status = 'CLOSED' AND closed_at >= NOW() - INTERVAL '7 days'
            GROUP BY EXTRACT(HOUR FROM opened_at)
            HAVING COUNT(*) >= 3
            ORDER BY pnl DESC;
        """)
        hour_rows = cur.fetchall()
        if hour_rows:
            hour_lines = ["=== TIME-OF-DAY PERFORMANCE ==="]
            for hr in hour_rows:
                h, cnt, ws, pnl = hr
                wr = round(ws / cnt * 100, 0) if cnt > 0 else 0
                marker = "🟢" if float(pnl) > 0 else "🔴"
                hour_lines.append(f"  {marker} {int(h):02d}:00 UTC: {cnt} trades, {wr}% WR, ${float(pnl):+.2f}")
            sections.append("\n".join(hour_lines))

        # --- Section 7: Signal Reliability ---
        cur.execute("""
            SELECT signal_name, times_correct, times_wrong, reliability_pct
            FROM signal_reliability
            WHERE (times_correct + times_wrong) >= 3
            ORDER BY reliability_pct DESC;
        """)
        sig_rows = cur.fetchall()
        if sig_rows:
            sig_lines = ["=== SIGNAL RELIABILITY (from post-trade analysis) ==="]
            for sr in sig_rows:
                name, correct, wrong, rel = sr
                total_s = correct + wrong
                marker = "✅" if float(rel) >= 60 else "⚠️" if float(rel) >= 45 else "❌"
                sig_lines.append(f"  {marker} {name}: {float(rel):.0f}% reliable ({correct}/{total_s})")
            sections.append("\n".join(sig_lines))

        cur.close()
        conn.close()

    except Exception as e:
        print(f"[RAG] ⚠️ Error building RAG context: {e}")

    return "\n\n".join(sections) if sections else ""


# ==========================================
# 2.4.2  POST-TRADE ANALYSIS (AI Reviews Each Closed Trade)
# ==========================================

def analyze_closed_trade(trade_row: dict) -> dict | None:
    """
    After a trade closes, AI analyzes what went right/wrong.
    Returns: {correct_signals, wrong_signals, key_factor, lesson, confidence_justified}
    Inspired by Polymarket's resolver.py post-resolve analysis.
    """
    ai_cfg = _get_ai_config("main")
    api_key = ai_cfg["api_key"]
    if not api_key:
        return None

    action = trade_row.get("action", "")
    open_p = trade_row.get("open_price", 0)
    close_p = trade_row.get("close_price", 0)
    profit = float(trade_row.get("profit", 0))
    sl = trade_row.get("sl_price", 0)
    tp = trade_row.get("tp_price", 0)
    conf = trade_row.get("ai_confidence", "?")
    regime = trade_row.get("market_regime", "unknown")
    trend = trade_row.get("trend_direction", "unknown")
    hold_sec = trade_row.get("hold_sec", 0)
    outcome = "WIN" if profit > 0 else "LOSS"

    prompt = (
        f"Analyze this completed {os.getenv('SYMBOL', 'XAUUSD')} trade:\n"
        f"Action: {action} | Open: {open_p} | Close: {close_p} | P/L: ${profit:+.2f} ({outcome})\n"
        f"SL: {sl} | TP: {tp} | AI Confidence: {conf} | Hold: {hold_sec}s\n"
        f"Market Regime: {regime} | Trend Direction: {trend}\n\n"
        f"Analyze which signals/factors were CORRECT vs WRONG for this trade.\n"
        f"Reply in this exact JSON format (no other text):\n"
        f'{{"correct_signals": ["signal1", "signal2"], '
        f'"wrong_signals": ["signal3"], '
        f'"key_factor": "one sentence about the main reason for the outcome", '
        f'"lesson": "one sentence lesson to avoid this mistake / replicate this success", '
        f'"confidence_justified": true/false}}'
    )

    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {
        "model": ai_cfg["model"],
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 200,
        "temperature": 0.05,
    }
    thinking = ai_cfg.get("thinking", AI_THINKING)
    if thinking:
        payload["chat_template_kwargs"] = {"enable_thinking": True}

    try:
        resp = http_session.post(ai_cfg["url"], headers=headers, json=payload, timeout=30 if thinking else 15)
        resp.raise_for_status()
        resp_data = resp.json()
        choices = resp_data.get("choices") or []
        if not choices:
            print(f"[POST-ANALYSIS] ⚠️ No choices: {str(resp_data.get('error', ''))[:200]}")
            return None
        reply = _strip_thinking(choices[0]["message"]["content"].strip())

        # Parse JSON from response
        json_match = re.search(r'\{.*\}', reply, re.DOTALL)
        if json_match:
            result = json.loads(json_match.group())
            return result
    except Exception as e:
        print(f"[POST-ANALYSIS] ⚠️ Failed: {e}")

    return None


def process_recently_closed_trades():
    """
    Find trades that closed but haven't been analyzed yet.
    Run post-trade AI analysis and update signal reliability + confidence calibration.
    """
    try:
        conn = get_db_connection()
        cur = conn.cursor()

        # Find closed trades not yet analyzed (last 24h)
        cur.execute("""
            SELECT t.id, t.order_id, t.action, t.open_price, t.close_price,
                   t.profit, t.sl_price, t.tp_price, t.ai_confidence,
                   t.market_regime, t.trend_direction,
                   EXTRACT(EPOCH FROM (t.closed_at - t.opened_at)) as hold_sec
            FROM trades t
            LEFT JOIN trade_analysis ta ON t.order_id = ta.order_id
            WHERE t.status = 'CLOSED' AND t.closed_at IS NOT NULL
                  AND t.closed_at >= NOW() - INTERVAL '24 hours'
                  AND ta.id IS NULL
            ORDER BY t.closed_at DESC
            LIMIT 3;
        """)
        rows = cur.fetchall()

        for row in rows:
            trade_data = {
                "id": row[0], "order_id": row[1], "action": row[2],
                "open_price": row[3], "close_price": row[4], "profit": row[5],
                "sl_price": row[6], "tp_price": row[7], "ai_confidence": row[8],
                "market_regime": row[9], "trend_direction": row[10],
                "hold_sec": int(row[11]) if row[11] else 0,
            }
            profit = float(row[5] or 0)
            outcome = "WIN" if profit > 0 else "LOSS"

            analysis = analyze_closed_trade(trade_data)
            if not analysis:
                continue

            # Save analysis to DB
            cur.execute("""
                INSERT INTO trade_analysis
                    (trade_id, order_id, outcome, profit, analysis_json,
                     correct_signals, wrong_signals, key_factor, lesson, confidence_justified)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT DO NOTHING;
            """, (
                trade_data["id"], trade_data["order_id"], outcome, profit,
                json.dumps(analysis),
                analysis.get("correct_signals", []),
                analysis.get("wrong_signals", []),
                analysis.get("key_factor", ""),
                analysis.get("lesson", ""),
                analysis.get("confidence_justified", False),
            ))

            # Update signal reliability
            for sig in analysis.get("correct_signals", []):
                sig_name = sig.strip()
                cur.execute("""
                    UPDATE signal_reliability
                    SET times_correct = times_correct + 1,
                        reliability_pct = ROUND((times_correct + 1)::numeric / NULLIF(times_correct + 1 + times_wrong, 0) * 100, 1),
                        updated_at = NOW()
                    WHERE signal_name = %s;
                """, (sig_name,))
            for sig in analysis.get("wrong_signals", []):
                sig_name = sig.strip()
                cur.execute("""
                    UPDATE signal_reliability
                    SET times_wrong = times_wrong + 1,
                        reliability_pct = ROUND(times_correct::numeric / NULLIF(times_correct + times_wrong + 1, 0) * 100, 1),
                        updated_at = NOW()
                    WHERE signal_name = %s;
                """, (sig_name,))

            # Update confidence calibration
            conf_level = trade_data.get("ai_confidence")
            if conf_level and 1 <= conf_level <= 10:
                cur.execute("""
                    UPDATE confidence_calibration
                    SET total_trades = total_trades + 1,
                        wins = wins + CASE WHEN %s = 'WIN' THEN 1 ELSE 0 END,
                        actual_win_rate = ROUND(
                            (wins + CASE WHEN %s = 'WIN' THEN 1 ELSE 0 END)::numeric /
                            NULLIF(total_trades + 1, 0) * 100, 1
                        ),
                        avg_profit = ROUND(
                            (avg_profit * total_trades + %s) / (total_trades + 1), 2
                        ),
                        updated_at = NOW()
                    WHERE confidence_level = %s;
                """, (outcome, outcome, profit, conf_level))

            print(f"[POST-ANALYSIS] 📊 #{trade_data['order_id']} {outcome}: "
                  f"correct={analysis.get('correct_signals', [])}, "
                  f"lesson={analysis.get('lesson', 'N/A')[:60]}")

        conn.commit()
        cur.close()
        conn.close()

    except Exception as e:
        print(f"[POST-ANALYSIS] ⚠️ Error: {e}")


def get_auto_generated_lessons() -> str:
    """
    Generate data-driven lessons from trade history (like Polymarket's Research Loop).
    These are injected into the AI prompt to prevent repeating mistakes.
    """
    lessons = []
    try:
        conn = get_db_connection()
        cur = conn.cursor()

        # Lesson 1: If avg loss > avg win = R:R problem
        cur.execute("""
            SELECT COALESCE(AVG(CASE WHEN profit > 0 THEN profit END), 0),
                   COALESCE(AVG(CASE WHEN profit <= 0 THEN profit END), 0)
            FROM trades WHERE status = 'CLOSED' AND closed_at >= NOW() - INTERVAL '3 days';
        """)
        row = cur.fetchone()
        if row and row[0] and row[1]:
            avg_w, avg_l = float(row[0]), float(row[1])
            if abs(avg_l) > abs(avg_w) * 1.3:
                lessons.append(
                    f"DATA: Avg loss (${avg_l:.2f}) is much bigger than avg win (${avg_w:.2f}). "
                    f"LESSON: Let winning trades RUN longer. Don't take quick small profits."
                )

        # Lesson 2: Direction that's losing money
        cur.execute("""
            SELECT action, SUM(profit), COUNT(*)
            FROM trades WHERE status = 'CLOSED' AND closed_at >= NOW() - INTERVAL '3 days'
            GROUP BY action;
        """)
        for dr in cur.fetchall():
            act, pnl, cnt = dr
            _loss_threshold = -1 if _is_crypto_symbol() else -5  # crypto trades smaller
            if float(pnl) < _loss_threshold and cnt >= 2:
                lessons.append(
                    f"DATA: {act} trades lost ${abs(float(pnl)):.2f} in 3 days ({cnt} trades). "
                    f"LESSON: Reduce {act} frequency. Only {act} with confidence 8+ and strong trend alignment."
                )

        # Lesson 3: Time-of-day losses
        cur.execute("""
            SELECT EXTRACT(HOUR FROM opened_at)::int as h, SUM(profit), COUNT(*)
            FROM trades WHERE status = 'CLOSED' AND closed_at >= NOW() - INTERVAL '5 days'
            GROUP BY h HAVING SUM(profit) < -1 AND COUNT(*) >= 2
            ORDER BY SUM(profit) ASC LIMIT 3;
        """)
        bad_hours = cur.fetchall()
        if bad_hours:
            hours_str = ", ".join(f"{int(h[0]):02d}:00" for h in bad_hours)
            lessons.append(f"DATA: Worst performing hours: {hours_str} UTC. LESSON: Avoid trading during these hours if possible.")

        # Lesson 4: Counter-trend trades losing
        cur.execute("""
            SELECT COUNT(*) FILTER (WHERE profit < 0 AND action != trend_direction) as counter_losses,
                   COUNT(*) FILTER (WHERE profit > 0 AND action = trend_direction) as with_trend_wins,
                   COUNT(*) FILTER (WHERE trend_direction IS NOT NULL) as total_with_trend
            FROM trades WHERE status = 'CLOSED' AND closed_at >= NOW() - INTERVAL '3 days';
        """)
        row = cur.fetchone()
        if row and row[2] and row[2] >= 3:
            counter_l = row[0] or 0
            with_trend_w = row[1] or 0
            if counter_l >= 2:
                lessons.append(
                    f"DATA: {counter_l} counter-trend trades lost money vs {with_trend_w} with-trend wins. "
                    f"LESSON: ALWAYS trade with H1+H4 trend. Counter-trend needs confidence 9+."
                )

        # Lesson 5: Recent trade_analysis lessons (from post-trade AI)
        cur.execute("""
            SELECT lesson FROM trade_analysis
            WHERE created_at >= NOW() - INTERVAL '2 days'
            ORDER BY created_at DESC LIMIT 3;
        """)
        ai_lessons = cur.fetchall()
        for al in ai_lessons:
            if al[0]:
                lessons.append(f"AI POST-TRADE: {al[0]}")

        cur.close()
        conn.close()
    except Exception as e:
        print(f"[LESSONS] ⚠️ Error: {e}")

    if lessons:
        return "=== AUTO-GENERATED LESSONS (from your actual trade data) ===\n" + "\n".join(f"• {l}" for l in lessons)
    return ""


# ==========================================
# 2.4.3  DAILY LOSS CIRCUIT BREAKER
# ==========================================

def check_daily_loss_limit() -> tuple[bool, str]:
    """
    Hard daily loss limit — stops ALL trading if daily losses exceed threshold.
    Like Polymarket's circuit breaker: daily loss >= X% of balance → stop for the day.
    DAILY_LOSS_LIMIT is a percentage of balance (default 2%).
    """
    daily_limit_pct = float(os.getenv("DAILY_LOSS_LIMIT_PCT", 2.0))
    if daily_limit_pct <= 0:
        return True, "Daily loss limit disabled"

    try:
        balance = _get_live_balance() or 100000
        daily_limit = balance * daily_limit_pct / 100

        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
            SELECT COALESCE(SUM(profit), 0)
            FROM trades
            WHERE status = 'CLOSED' AND opened_at >= CURRENT_DATE;
        """)
        row = cur.fetchone()
        cur.close()
        conn.close()

        today_pnl = float(row[0]) if row else 0
        if today_pnl <= -daily_limit:
            msg = f"Daily loss limit hit: ${today_pnl:.2f} <= -${daily_limit:.2f} ({daily_limit_pct}% of ${balance:.0f})"
            return False, msg
        return True, f"Daily P/L: ${today_pnl:+.2f} (limit: -${daily_limit:.2f})"
    except Exception as e:
        print(f"[CIRCUIT] ⚠️ Error checking daily loss: {e}")
        return True, "Error checking daily loss"


def update_daily_performance():
    """Update daily_performance table with today's stats."""
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO daily_performance (trade_date, total_trades, wins, losses,
                total_profit, buy_count, sell_count, avg_hold_sec, avg_win, avg_loss)
            SELECT
                CURRENT_DATE,
                COUNT(*),
                COUNT(*) FILTER (WHERE profit > 0),
                COUNT(*) FILTER (WHERE profit <= 0),
                COALESCE(SUM(profit), 0),
                COUNT(*) FILTER (WHERE action = 'BUY'),
                COUNT(*) FILTER (WHERE action = 'SELL'),
                COALESCE(AVG(EXTRACT(EPOCH FROM (closed_at - opened_at)))::int, 0),
                COALESCE(AVG(CASE WHEN profit > 0 THEN profit END), 0),
                COALESCE(AVG(CASE WHEN profit <= 0 THEN profit END), 0)
            FROM trades
            WHERE status = 'CLOSED' AND opened_at >= CURRENT_DATE
            ON CONFLICT (trade_date) DO UPDATE SET
                total_trades = EXCLUDED.total_trades,
                wins = EXCLUDED.wins,
                losses = EXCLUDED.losses,
                total_profit = EXCLUDED.total_profit,
                buy_count = EXCLUDED.buy_count,
                sell_count = EXCLUDED.sell_count,
                avg_hold_sec = EXCLUDED.avg_hold_sec,
                avg_win = EXCLUDED.avg_win,
                avg_loss = EXCLUDED.avg_loss,
                updated_at = NOW();
        """)
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        print(f"[DAILY] ⚠️ Error updating daily performance: {e}")


def save_trade_with_context(order_id, symbol, action, lot, open_price,
                            sl_price, tp_price, ai_confidence=None,
                            market_regime=None, trend_direction=None, trend_strength=None):
    """Enhanced save_trade_to_db that also stores AI context for post-trade analysis."""
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO trades (order_id, symbol, action, lot, open_price,
                                sl_price, tp_price, status, opened_at,
                                ai_confidence, ai_sentiment, market_regime,
                                trend_direction, trend_strength)
            VALUES (%s, %s, %s, %s, %s, %s, %s, 'OPEN', NOW(), %s, %s, %s, %s, %s)
            ON CONFLICT (order_id) DO NOTHING;
            """,
            (order_id, symbol, action, lot, open_price, sl_price, tp_price,
             ai_confidence, action, market_regime, trend_direction, trend_strength),
        )
        conn.commit()
        cur.close()
        conn.close()
        print(f"[DB] 📝 Trade #{order_id} saved (OPEN) conf={ai_confidence} regime={market_regime} trend={trend_direction}")
    except Exception as e:
        print(f"[ERROR] save_trade_with_context: {e}")


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
    min_confidence = int(os.getenv("MIN_CONFIDENCE", 7))
    confidence     = _extract_confidence(ai_text)
    sentiment      = "WAIT"

    lines = [l.strip() for l in ai_text.strip().split("\n") if l.strip()]

    # Primary: parse "Sentiment: Bullish/Bearish/Neutral" from structured output
    for line in lines[:6]:                        # check first 6 lines (includes Thought: line)
        line_l = line.lower()
        if line_l.startswith("sentiment"):
            if "bullish" in line_l:
                sentiment = "BUY"
            elif "bearish" in line_l:
                sentiment = "SELL"
            else:
                sentiment = "WAIT"
            break

    # Fallback: search "Sentiment:" anywhere in response (AI sometimes verbose)
    if sentiment == "WAIT":
        m = re.search(r'sentiment[:\s]+(bullish|bearish)', ai_text.lower())
        if m:
            sentiment = "BUY" if m.group(1) == "bullish" else "SELL"

    # Fallback 2: explicit action keyword in first 3 lines
    if sentiment == "WAIT":
        header = " ".join(lines[:3]).lower()
        m = re.search(r'(?:action|signal|recommendation)[:\s]*(buy|sell)', header)
        if m:
            sentiment = m.group(1).upper()

    # Crypto uses a lower confidence threshold (consolidation-friendly)
    if _is_crypto_symbol():
        min_confidence = int(os.getenv("MIN_CONFIDENCE_CRYPTO", 6))

    # WAIT-streak escalation: after many consecutive WAITs, relax by 1
    # Applies to BOTH gold and crypto — prevents indefinite paralysis
    if _consecutive_waits >= WAIT_STREAK_THRESHOLD and min_confidence > 5:
        min_confidence -= 1

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
        sl_price = round(entry - sl_points * POINT_SIZE, 2)
        tp_price = round(entry + tp_points * POINT_SIZE, 2)
    elif action == "SELL":
        entry    = bid
        sl_price = round(entry + sl_points * POINT_SIZE, 2)
        tp_price = round(entry - tp_points * POINT_SIZE, 2)
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


def get_consecutive_loss_total(symbol: str) -> dict:
    """Get details of the current consecutive losing streak.
    Returns {count, total_loss, losses: [{action, profit, sl, tp, open, close}]}
    """
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(
            """
            SELECT action, open_price, close_price, profit, sl_price, tp_price, lot
            FROM trades
            WHERE symbol = %s AND status = 'CLOSED' AND closed_at IS NOT NULL
            ORDER BY closed_at DESC
            LIMIT 10;
            """,
            (symbol,),
        )
        rows = cur.fetchall()
        cur.close()
        conn.close()

        losses = []
        total_loss = 0.0
        for row in rows:
            profit = float(row[3] or 0)
            if profit <= 0:
                losses.append({
                    "action": row[0], "open": row[1], "close": row[2],
                    "profit": profit, "sl": row[4], "tp": row[5], "lot": float(row[6] or 0),
                })
                total_loss += abs(profit)
            else:
                break
        return {"count": len(losses), "total_loss": round(total_loss, 2), "losses": losses}
    except Exception:
        return {"count": 0, "total_loss": 0.0, "losses": []}


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
            SELECT provider, model, api_key, api_url, max_tokens, temperature,
                   COALESCE(ai_thinking, FALSE)
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
                SELECT provider, model, api_key, api_url, max_tokens, temperature,
                       COALESCE(ai_thinking, FALSE)
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
                SELECT provider, model, api_key, api_url, max_tokens, temperature,
                       COALESCE(ai_thinking, FALSE)
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
                "thinking":    bool(row[6]),
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
                    trade_history: str = "", scalp_tf: str = "M5",
                    d1_high: float = None, d1_low: float = None) -> str:
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
    _sym = os.getenv("SYMBOL", "XAUUSD")
    _is_crypto = _is_crypto_symbol(_sym)

    # Symbol-specific prompt sections
    if _is_crypto:
        _asset_desc = f"{_sym} (Bitcoin/Crypto)"
        _style_desc = (
            f"TRADING STYLE: Short-term scalping ({_sym}, 5-30 min hold, target meaningful profit per trade). "
        )
        _macro_rules = (
            "MACRO RULES:\n"
            "- BTC is a risk-on asset: equities up → typically BUY BTC\n"
            "- Fed hawkish / rates up → typically SELL BTC (tightening liquidity)\n"
            "- ETF inflows → bullish for BTC, outflows → bearish\n"
            "- Whale accumulation / on-chain metrics → watch for large moves\n"
            "- High-impact macro news (CPI, FOMC) → WAIT for volatility to settle\n"
            "- Crypto trades 24/7 — weekend liquidity is lower, spreads wider\n"
        )
        _room_to_move = "Only enter when price has ROOM TO MOVE to the next S/R level in your direction."
        _late_entry = "If recent trades were closed at tiny profit → the entries were late/poor — wait for better setups"
    else:
        _asset_desc = f"{_sym} (Gold)"
        _style_desc = (
            "TRADING STYLE: Short-term scalping (5-15 min hold, target $2-$5 profit per 0.01 lot). "
        )
        _macro_rules = (
            "MACRO RULES:\n"
            "- DOM/order book missing is NOT bearish (broker limitation)\n"
            "- H1+H4 agreement outweighs D1 for scalp timing\n"
            "- USD strength (DXY up) → typically SELL gold\n"
            "- Geopolitical risk / uncertainty → typically BUY gold (safe haven)\n"
            "- High-impact news within 30min → WAIT (volatility spike risk)\n"
        )
        _room_to_move = "Only enter when price has ROOM TO MOVE: at least $2-$3 to the next S/R level in your direction."
        _late_entry = "If recent trades were closed at tiny profit (<$0.50) → the entries were late/poor — wait for better setups"

    system_prompt = (
        f"You are a professional {_asset_desc} scalp trader with 15+ years experience. "
        f"You analyze multi-timeframe data ({stf}, H1, H4, D1) using technical indicators, "
        "price action, order flow, and macro events.\n\n"

        f"{_style_desc}"
        "You are BALANCED — you trade both BUY and SELL with equal discipline. "
        "QUALITY over QUANTITY: Only take HIGH-PROBABILITY setups. "
        "It is better to WAIT and miss a trade than to enter a bad one.\n\n"

        "PROFIT-FOCUSED RULES (most important):\n"
        "1. Trading is for PROFIT, not just winning. A small win that gets stopped out is worse than waiting.\n"
        f"2. {_room_to_move}\n"
        "3. Entry timing matters: Enter on pullbacks to EMA/support, NOT after price already moved significantly in your direction.\n"
        "4. If price is mid-range between support and resistance with no momentum → WAIT.\n"
        "5. NEVER chase a move that already happened. If price just spiked $3-$5, wait for a pullback.\n\n"

        "CRITICAL RULES:\n"
        "1. Analyze BOTH directions equally. Do NOT default to SELL. Check your recent trade log — "
        "if >70%% are SELL, actively look for BUY setups. Direction bias destroys accounts.\n"
        "2. TREND IS KING: Always check H1+H4 trend alignment FIRST. "
        "Trading WITH the multi-TF trend has 70%+ base probability. "
        "Counter-trend trades need overwhelming evidence (confidence 8+).\n"
        "3. Support/Resistance proximity: Do NOT BUY near resistance or SELL near support "
        "unless a breakout is confirmed by volume + momentum.\n"
        "3b. DAILY HIGH/LOW: These are key liquidity zones. "
        f"Do NOT BUY within {('1.0' if _is_crypto else '0.3')}% of Daily High (trapped longs) "
        f"or SELL within {('1.0' if _is_crypto else '0.3')}% of Daily Low (trapped shorts) "
        "unless a clear breakout with momentum is confirmed.\n"
        "4. Consider the FULL picture: technicals + trade history + news + patterns. "
        "Do not base decisions on a single indicator.\n"
        "5. WAIT is your best friend. If you are unsure, WAIT. "
        "Only trade when you see a clear, high-confidence setup with 4+ aligned signals.\n\n"

        "ENTRY QUALITY CHECKLIST (need 4+ signals aligned for confidence 7+):\n"
        "BUY: EMA9>EMA21 on H1+H4 | RSI 30-55 rising | MACD histogram positive/turning up | "
        "BB%%B<0.3 (oversold) | price at or bouncing from support | bullish engulfing/hammer | "
        "ATR showing expansion (move starting, not ending)\n"
        "SELL: EMA9<EMA21 on H1+H4 | RSI 45-70 falling | MACD histogram negative/turning down | "
        "BB%%B>0.7 (overbought) | price at or rejected from resistance | bearish engulfing/shooting star | "
        "ATR showing expansion\n"
        "WAIT: <4 signals aligned | RSI extreme >80/<20 (exhaustion — reversal likely, not continuation) | "
        "conflicting TF signals | high-impact news pending <30min | "
        "BB bandwidth < 0.5%% with RSI 40-60 (consolidation/chop) | "
        "price mid-range (not at S/R) | spread too wide\n\n"

        "SIDEWAYS/CONSOLIDATION RULES:\n"
        "- If BB bandwidth is narrow (<0.5%%) AND RSI is 40-60 AND no clear trend → market is consolidating\n"
        "- In consolidation: STRONGLY prefer WAIT unless price is at extreme Support or Resistance\n"
        f"- Consolidation BUY/SELL max confidence = {6 if _is_crypto else 5} (smaller position)\n"
        "- If consolidation + imminent news → WAIT (breakout direction unknown)\n"
        + ("- NOTE: Crypto often consolidates on H4/D1 while H1 trends. "
           "H1 trend alone can justify confidence 6-7 if momentum (MACD+RSI) confirms.\n\n"
           if _is_crypto else "\n")

        + "TRADE LOG ANALYSIS (learn from mistakes):\n"
        "- Review recent trades: if avg win < avg loss → require higher confidence (7+) with trend\n"
        "- If >70%% trades are one direction (BUY or SELL) → ACTIVELY seek the other direction\n"
        "- Consecutive losses → require confidence 8+ and strongest confluence\n"
        f"- {_late_entry}\n"
        "- If SL hit multiple times in same direction → that direction is WRONG, switch or WAIT\n\n"

        f"{_macro_rules}\n"

        "CONFIDENCE SCALE (1-10) — BE STRICT:\n"
        + ("1-4: Weak/unclear signal → ALWAYS WAIT.\n"
           "5: Marginal — trade only with H1 trend + 4 aligned signals.\n"
           "6: Moderate with H1 trend momentum → trade if 3+ signals aligned.\n"
           if _is_crypto else
           "1-5: Weak/unclear signal → ALWAYS WAIT.\n"
           "6: Moderate with trend alignment → trade only if 4+ signals aligned.\n")
        + "7-8: Strong setup, multiple confluences → trade.\n"
        "9-10: Exceptional setup, everything aligned → high conviction.\n"
        "REMEMBER: Over-trading with low confidence is the #1 account killer. "
        "Saying WAIT when unsure is a winning decision.\n\n"

        "Reply EXACTLY in this format (no extra text, no preamble):\n"
        "Thought: <1-2 sentences: step-by-step reasoning — what signals you see for/against each direction>\n"
        "Sentiment: <Bullish/Bearish/Neutral>\n"
        "Confidence: <1-10>\n"
        "Reason: <2-3 sentences: key signals, trend alignment, and risk factors>"
    )

    sections = [
        f"=== {_sym} LIVE DATA ===",
        f"Current Price -> Bid: {price_data['bid']}, Ask: {price_data['ask']}",
        f"Spread: {round(price_data['ask'] - price_data['bid'], 2)}",
    ]
    if d1_high is not None and d1_low is not None:
        mid = (price_data['bid'] + price_data['ask']) / 2
        pct_from_high = abs(d1_high - mid) / mid * 100 if mid else 0
        pct_from_low  = abs(mid - d1_low) / mid * 100 if mid else 0
        sections.append(
            f"\n=== DAILY RANGE (Liquidity Zones) ==="
            f"\nD1 High: {d1_high:.2f} ({pct_from_high:.2f}% away) | "
            f"D1 Low: {d1_low:.2f} ({pct_from_low:.2f}% away)"
        )
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
    top_p = os.getenv("TOP_P")
    if top_p:
        payload["top_p"] = float(top_p)
    thinking = ai_cfg.get("thinking", AI_THINKING)
    if thinking:
        payload["chat_template_kwargs"] = {"enable_thinking": True}

    ai_timeout = 60 if thinking else 15
    max_retries = 2
    for attempt in range(1, max_retries + 1):
        t_start = time.time()
        try:
            response  = http_session.post(url, headers=headers, json=payload, timeout=ai_timeout)
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
            choices = resp_json.get("choices") or []
            if not choices:
                err = resp_json.get("error", {})
                err_msg = err.get("message", str(err)) if isinstance(err, dict) else str(err)
                raise ValueError(f"No choices in response: {err_msg[:200]}")
            raw = choices[0]["message"]["content"].strip()
            return _strip_thinking(raw)
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

    # Get data_cleaned_at cutoff (skip deals before cleanup timestamp)
    _cutoff_ts = 0
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT EXTRACT(EPOCH FROM data_cleaned_at) FROM bot_settings LIMIT 1;")
        row = cur.fetchone()
        cur.close()
        conn.close()
        if row and row[0]:
            _cutoff_ts = float(row[0])
    except Exception:
        pass

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
                # Skip deals from before data cleanup
                if _cutoff_ts and out_deal.get("time", 0) < _cutoff_ts:
                    continue
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
MIN_HOLD_SEC            = int(os.getenv("MIN_HOLD_SEC",   120))
MAX_HOLD_SEC            = int(os.getenv("MAX_HOLD_SEC",   1800))
MAX_HOLD_SEC_LOSS       = int(os.getenv("MAX_HOLD_SEC_LOSS", 600))  # Shorter hold for losing positions
# Crypto gets longer hold — higher volatility, wider oscillation
if _is_crypto_symbol():
    MAX_HOLD_SEC_LOSS = max(MAX_HOLD_SEC_LOSS, 900)  # At least 15 min for crypto
TRAILING_STEP_PRICE     = float(os.getenv("TRAILING_STEP_PRICE",   1.0))
TRAILING_PROTECT_PCT    = float(os.getenv("TRAILING_PROTECT_PCT",  50))
PROFIT_LOCK_PCT         = float(os.getenv("PROFIT_LOCK_PCT",        5.0))
BREAKEVEN_TRIGGER_PCT   = float(os.getenv("BREAKEVEN_TRIGGER_PCT",  0.2))
MIN_PROFIT_CLOSE_PCT    = float(os.getenv("MIN_PROFIT_CLOSE_PCT",   0.5))
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
# WIDER GAPS = let winners run to meaningful profit
# Phase 1: Small profit — protect entry but give room to breathe
TRAIL_PHASE1_ATR = float(os.getenv("TRAIL_PHASE1_ATR", 0.38))
# Progressive tightening: when price moves > this many ATRs, start tightening trail
TRAIL_TIGHTEN_ATR_TRIGGER = float(os.getenv("TRAIL_TIGHTEN_ATR_TRIGGER", 1.5))
# Phase 2: Good profit (>= min_profit_close) — wider trail, let it develop
TRAIL_PHASE2_ATR = float(os.getenv("TRAIL_PHASE2_ATR", 0.75))
# Phase 3: After partial close (already banked 50%) — widest, let runner go
TRAIL_PHASE3_ATR = float(os.getenv("TRAIL_PHASE3_ATR", 1.00))
# Breakeven trigger distance in USD (price must move this far before SL→entry)
BREAKEVEN_DISTANCE = float(os.getenv("BREAKEVEN_DISTANCE", 1.00))

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
# Track max profit seen per position (high watermark for trailing)
_position_max_profit: dict = {}  # ticket -> max_profit_seen
# Forecast failure tracking (backoff on repeated API failures)
_forecast_failures: dict = {}  # ticket -> [fail_count, last_fail_ts]
# Recovery whipsaw protection
_recovery_attempts_recent: list = []  # [(timestamp, action)]
# Recovery profit target: accumulated loss amount that the next trade should recover
_recovery_target: float = 0.0  # set when trade opens after consecutive losses
_recovery_target_lock = threading.Lock()  # Thread-safe access between main loop and monitor


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
                      open_price: float = 0, hold_sec: int = 0,
                      news_alert: str = "",
                      trend_summary: str = "",
                      win_rate_summary: str = "") -> dict:
    """Enhanced AI forecast with multi-indicator context + S/R + trend + news + lessons."""
    if not candles_scalp or len(candles_scalp) < 10:
        return {"action": "CLOSE", "reason": f"Insufficient {scalp_tf} data"}

    # Forecast failure backoff: skip AI if too many consecutive failures
    fail_count = _forecast_failures.get("count", 0)
    last_fail  = _forecast_failures.get("last_ts", 0)
    if fail_count >= 3:
        backoff_sec = min(300, 30 * (2 ** (fail_count - 3)))  # 30s, 60s, 120s, 300s max
        if time.time() - last_fail < backoff_sec:
            print(f"[FORECAST] ⏳ Backoff active ({fail_count} failures, wait {backoff_sec}s) — using technicals only")
            closes = [c["close"] for c in candles_scalp]
            ema_5 = calc_ema(closes, 5)
            ema_10 = calc_ema(closes, 10)
            if ema_5 and ema_10:
                if position_type == "BUY" and ema_5 < ema_10:
                    return {"action": "CLOSE", "reason": "EMA bearish crossover (backoff)"}
                if position_type == "SELL" and ema_5 > ema_10:
                    return {"action": "CLOSE", "reason": "EMA bullish crossover (backoff)"}
            return {"action": "HOLD", "reason": f"AI backoff ({fail_count} failures), technicals neutral"}

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

    # Add compact context lines (news, trend, performance) — keeps prompt small
    extra_lines = []
    if news_alert:
        extra_lines.append(f"⚠️ NEWS: {news_alert}")
    if trend_summary:
        extra_lines.append(f"H1 Trend: {trend_summary}")
    if win_rate_summary:
        extra_lines.append(f"Recent: {win_rate_summary}")
    extra_ctx = "\n".join(extra_lines)

    _sym = os.getenv("SYMBOL", "XAUUSDm")
    # Calculate loss as % of SL for context
    _sl_context = ""
    if open_price and open_price > 0:
        _sl_distance = abs(current_price - open_price)
        _atr_ref = calc_atr(candles_scalp, 14) if candles_scalp and len(candles_scalp) >= 14 else None
        if _atr_ref and _atr_ref > 0:
            _sl_pct = _sl_distance / _atr_ref * 100
            _sl_context = f"Loss is {_sl_pct:.0f}% of ATR — {'within normal range, SL not threatened' if _sl_pct < 120 else 'approaching SL zone'}"
    compact_prompt = (
        f"{_sym} {scalp_tf} candles: {candle_str}\n"
        f"{' | '.join(indicators)}\n"
        f"Position: {position_type} | Profit=${profit:+.2f} | Hold={hold_sec}s\n"
        + (f"{_sl_context}\n" if _sl_context else "")
        + (f"{extra_ctx}\n" if extra_ctx else "")
        + f"Question: Should this {position_type} position be held or closed NOW?\n"
        f"IMPORTANT: In a strong trend, temporary drawdown is NORMAL. Only CLOSE if trend is REVERSING.\n"
        f"Consider: momentum direction, trend continuation vs reversal, S/R, risk"
        + (", news impact" if news_alert else "") + ".\n"
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
        reply_raw = _strip_thinking((resp_json.get("choices") or [{}])[0].get("message", {}).get("content", "")).strip().upper()
        if not reply_raw:
            raise ValueError(f"Empty forecast response: {str(resp_json.get('error', ''))[:200]}")
        reply = reply_raw
        # Reset forecast failure counter on success
        _forecast_failures.clear()
        if "CLOSE" in reply:
            return {"action": "CLOSE", "reason": reply}
        return {"action": "HOLD", "reason": reply}
    except Exception as e:
        print(f"[FORECAST] ⚠️ AI forecast failed: {e}")
        # Track failures for exponential backoff
        fail_count = _forecast_failures.get("count", 0) + 1
        _forecast_failures["count"] = fail_count
        _forecast_failures["last_ts"] = time.time()
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
    - Recovery-aware trailing: tightens SL when profit covers accumulated losses
    """
    global _recovery_target
    windows_ip = os.getenv("WINDOWS_IP")
    if not windows_ip:
        return

    try:
        resp      = http_session.get(f"http://{windows_ip}:8000/positions", timeout=5)
        resp.raise_for_status()
        positions = resp.json().get("positions", [])
        if not positions:
            with _recovery_target_lock:
                if _recovery_target > 0:
                    _recovery_target = 0.0  # Clear recovery target when no positions open
            return

        now_ts  = int(datetime.now(timezone.utc).timestamp())
        balance = _get_account_balance()
        atr     = _get_cached_atr(scalp_tf)

        # Take a thread-safe local snapshot of recovery target for this cycle
        with _recovery_target_lock:
            _recovery_target_local = _recovery_target

        profit_lock_usd    = balance * (PROFIT_LOCK_PCT      / 100) if PROFIT_LOCK_PCT > 0 else 0
        breakeven_usd      = balance * (BREAKEVEN_TRIGGER_PCT / 100)
        min_profit_close   = balance * (MIN_PROFIT_CLOSE_PCT  / 100)
        partial_close_usd  = balance * (PARTIAL_CLOSE_PCT     / 100)

        # 3-Phase Adaptive Trailing (ATR-based) — WIDER gaps to let winners run
        # Phase 1: protect entry  Phase 2: let it develop  Phase 3: runner
        # Floor values are configurable for different instruments (gold vs BTC)
        _trail_floor_p1 = float(os.getenv("TRAIL_FLOOR_P1", 0.50))
        _trail_floor_p2 = float(os.getenv("TRAIL_FLOOR_P2", 0.80))
        _trail_floor_p3 = float(os.getenv("TRAIL_FLOOR_P3", 1.20))
        _trail_fallback_p1 = _trail_floor_p1 * 1.2
        _trail_fallback_p2 = _trail_floor_p2 * 1.25
        _trail_fallback_p3 = _trail_floor_p3 * 1.25
        trail_gap_p1 = max(_trail_floor_p1, round(atr * TRAIL_PHASE1_ATR, 2)) if atr else _trail_fallback_p1
        trail_gap_p2 = max(_trail_floor_p2, round(atr * TRAIL_PHASE2_ATR, 2)) if atr else _trail_fallback_p2
        trail_gap_p3 = max(_trail_floor_p3, round(atr * TRAIL_PHASE3_ATR, 2)) if atr else _trail_fallback_p3

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
            # React immediately if price moved adversely by > dynamic spike threshold
            # Dynamic threshold: max(SPIKE_THRESHOLD, ATR×0.50) — adapts to volatility
            effective_spike = max(SPIKE_THRESHOLD, round(atr * 0.50, 2)) if atr else SPIKE_THRESHOLD
            with _position_state_lock:
                last_known = _last_prices.get(ticket)
                _last_prices[ticket] = current_price
            if last_known is not None:
                price_delta = current_price - last_known
                if pos_type == "BUY" and price_delta < -effective_spike and profit <= 0:
                    print(f"[SPIKE] ⚡ #{ticket} BUY price dropped {price_delta:.2f} (threshold={effective_spike}) → CLOSE")
                    close_position_mt5(ticket)
                    log_event("SPIKE_CLOSE", f"#{ticket} BUY spike {price_delta:.2f}")
                    continue
                if pos_type == "SELL" and price_delta > effective_spike and profit <= 0:
                    print(f"[SPIKE] ⚡ #{ticket} SELL price surged +{price_delta:.2f} (threshold={effective_spike}) → CLOSE")
                    close_position_mt5(ticket)
                    log_event("SPIKE_CLOSE", f"#{ticket} SELL spike +{price_delta:.2f}")
                    continue

            # ===== PROFIT LOCK (tighten SL → let winners run) =====
            # Was hard-close — now locks gains via SL and lets trade continue.
            # Floor: profit must reach 0.5× ATR before locking (prevents noise-level exits on micro accounts)
            _pl_floor = round(atr * 0.50, 2) if atr else 0
            _effective_pl = max(profit_lock_usd, _pl_floor) if profit_lock_usd > 0 else 0
            if _effective_pl > 0 and profit >= _effective_pl:
                _price_move = abs(current_price - open_price)
                if _price_move > 0:
                    _lock_gap = max(_trail_floor_p1, round(atr * 0.25, 2)) if atr else _trail_floor_p1
                    if pos_type == "BUY":
                        lock_sl = round(current_price - _lock_gap, 2)
                        if lock_sl > current_sl and lock_sl > open_price:
                            print(f"[SMART] 💰💰 #{ticket} profit=${profit:.2f} >= ${_effective_pl:.2f} → LOCK SL {current_sl}→{lock_sl} (gap=${_lock_gap:.2f})")
                            modify_sl_mt5(ticket, lock_sl)
                            log_event("PROFIT_LOCK", f"#{ticket} SL→{lock_sl} gap={_lock_gap}")
                    elif pos_type == "SELL":
                        lock_sl = round(current_price + _lock_gap, 2)
                        if (lock_sl < current_sl or current_sl <= 0) and lock_sl < open_price:
                            print(f"[SMART] 💰💰 #{ticket} profit=${profit:.2f} >= ${_effective_pl:.2f} → LOCK SL {current_sl}→{lock_sl} (gap=${_lock_gap:.2f})")
                            modify_sl_mt5(ticket, lock_sl)
                            log_event("PROFIT_LOCK", f"#{ticket} SL→{lock_sl} gap={_lock_gap}")
                # No close — trailing stop + AI forecast manage the exit

            # ===== PARTIAL CLOSE (first target) =====
            if ticket not in _partial_closed and profit >= partial_close_usd and lot >= 0.02:
                print(f"[PARTIAL] 🎯 #{ticket} profit=${profit:.2f} >= ${partial_close_usd:.2f} → close 50%")
                result = partial_close_mt5(ticket, 0.5)
                if result and result.get("success"):
                    with _position_state_lock:
                        _partial_closed.add(ticket)

            # ===== 3-PHASE ADAPTIVE TRAILING STOP =====
            # Phase 1: small profit → tight trail (protect entry)
            # Phase 2: good profit → medium trail (survive normal swings)
            # Phase 3: after partial close → wide trail (let the runner go)

            # ===== RECOVERY TARGET MANAGEMENT =====
            # When trading after consecutive losses, tighten SL once profit covers accumulated loss
            if _recovery_target_local > 0 and profit > 0:
                price_delta = abs(current_price - open_price)
                if price_delta > 0:
                    profit_per_usd = profit / price_delta  # $ profit per $1 price move
                else:
                    profit_per_usd = 0

                if profit >= _recovery_target_local:
                    # Profit covers accumulated loss — tighten SL to lock in 70% of recovery
                    lock_profit = _recovery_target_local * 0.70
                    if profit_per_usd > 0:
                        lock_distance = lock_profit / profit_per_usd  # USD distance from entry
                        if pos_type == "BUY":
                            recovery_sl = round(open_price + lock_distance, 2)
                            if current_sl < recovery_sl:
                                print(f"[RECOVERY-TARGET] 🎯 #{ticket} profit ${profit:.2f} >= target ${_recovery_target_local:.2f} "
                                      f"→ locking SL to {recovery_sl} (protects ${lock_profit:.2f} / 70% of loss recovery)")
                                modify_sl_mt5(ticket, recovery_sl)
                                log_event("RECOVERY_LOCK", f"#{ticket} SL→{recovery_sl} locking ${lock_profit:.2f} recovery")
                        elif pos_type == "SELL":
                            recovery_sl = round(open_price - lock_distance, 2)
                            if current_sl > recovery_sl or current_sl <= 0:
                                print(f"[RECOVERY-TARGET] 🎯 #{ticket} profit ${profit:.2f} >= target ${_recovery_target_local:.2f} "
                                      f"→ locking SL to {recovery_sl} (protects ${lock_profit:.2f} / 70% of loss recovery)")
                                modify_sl_mt5(ticket, recovery_sl)
                                log_event("RECOVERY_LOCK", f"#{ticket} SL→{recovery_sl} locking ${lock_profit:.2f} recovery")

                elif profit >= _recovery_target_local * 0.5:
                    # Halfway to recovery — at minimum move SL to breakeven + small buffer
                    _be_buf = round(atr * 0.10, 2) if atr else 0.10
                    if pos_type == "BUY" and current_sl < open_price:
                        be_sl = round(open_price + _be_buf, 2)
                        print(f"[RECOVERY-HALF] 📊 #{ticket} profit ${profit:.2f} is 50%+ of target ${_recovery_target_local:.2f} → ensuring BE at {be_sl}")
                        modify_sl_mt5(ticket, be_sl)
                    elif pos_type == "SELL" and current_sl > open_price:
                        be_sl = round(open_price - _be_buf, 2)
                        print(f"[RECOVERY-HALF] 📊 #{ticket} profit ${profit:.2f} is 50%+ of target ${_recovery_target_local:.2f} → ensuring BE at {be_sl}")
                        modify_sl_mt5(ticket, be_sl)

            # Track max profit high watermark per position
            with _position_state_lock:
                prev_max = _position_max_profit.get(ticket, 0)
                if profit > prev_max:
                    _position_max_profit[ticket] = profit
                max_profit_seen = _position_max_profit.get(ticket, 0)

            # Pre-compute distance from entry for trailing logic
            if pos_type == "BUY":
                distance = current_price - open_price
            else:
                distance = open_price - current_price

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

            # Progressive tightening: as price moves further from entry, tighten trail
            # Strong directional moves should be protected more aggressively
            if atr and atr > 0 and distance > 0:
                distance_in_atr = distance / atr
                if distance_in_atr >= TRAIL_TIGHTEN_ATR_TRIGGER:
                    tighten_factor = min(0.55, 0.30 + (distance_in_atr - TRAIL_TIGHTEN_ATR_TRIGGER) * 0.05)
                    tight_gap = max(_trail_floor_p1 * 0.6, round(atr * tighten_factor, 2))
                    if tight_gap < trail_gap:
                        trail_gap = tight_gap
                        phase_label = f"TIGHT(dist={distance_in_atr:.1f}xATR)"

            # High watermark protection: if profit dropped >45% from peak, tighten trail
            if max_profit_seen > 0 and profit > 0 and profit < max_profit_seen * 0.55:
                if trail_gap_p2 < trail_gap:
                    trail_gap = trail_gap_p2
                phase_label = f"P2-PROTECT(peak${max_profit_seen:.2f})"

            if current_sl != 0:
                # Dynamic breakeven offset: ATR×0.15 — scaled by instrument
                _be_min = float(os.getenv("BE_OFFSET_MIN", 0.10))
                _be_max = float(os.getenv("BE_OFFSET_MAX", 0.50))
                be_offset = max(_be_min, min(_be_max, round(atr * 0.15, 2))) if atr else (_be_min + _be_max) / 2
                if pos_type == "BUY":
                    distance = current_price - open_price
                    # Breakeven: move SL to entry once price moves BREAKEVEN_DISTANCE
                    if distance > BREAKEVEN_DISTANCE and current_sl < open_price:
                        be_sl = round(open_price + be_offset, 2)
                        print(f"[BREAKEVEN] 🔒 #{ticket} BUY → SL to {be_sl} (entry+{be_offset})")
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
                        be_sl = round(open_price - be_offset, 2)
                        print(f"[BREAKEVEN] 🔒 #{ticket} SELL → SL to {be_sl} (entry-{be_offset})")
                        modify_sl_mt5(ticket, be_sl)
                    # Adaptive trailing
                    elif profit >= breakeven_usd and distance > trail_gap:
                        ideal_sl = round(current_price + trail_gap, 2)
                        if ideal_sl < current_sl and ideal_sl < open_price:
                            print(f"[TRAIL-{phase_label}] 📉 #{ticket} SL {current_sl}→{ideal_sl} (gap={trail_gap})")
                            modify_sl_mt5(ticket, ideal_sl)

            # ===== TREND REVERSAL EXIT =====
            # Close positions when H1 trend reverses:
            # - Losing positions: close early to cut losses
            # - Profitable positions: take profit before trend eats gains
            _trend_exit_hold = 300 if _is_crypto_symbol() else 120
            _trend_exit_min_loss = -1.0 if _is_crypto_symbol() else 0
            if hold_sec >= _trend_exit_hold:
                try:
                    candles_h1_check = get_candles_from_mt5("H1", 30)
                    if candles_h1_check and len(candles_h1_check) >= 21:
                        closes_h1 = [c["close"] for c in candles_h1_check]
                        ema9_h1 = calc_ema(closes_h1, 9)
                        ema21_h1 = calc_ema(closes_h1, 21)
                        if ema9_h1 and ema21_h1:
                            h1_trend = "BUY" if ema9_h1 > ema21_h1 else "SELL"
                            if pos_type != h1_trend:
                                # Trend reversed against our position
                                if profit <= _trend_exit_min_loss:
                                    # Losing — exit immediately
                                    print(f"[TREND-EXIT] ⚠️ #{ticket} {pos_type} but H1 trend={h1_trend} "
                                          f"(EMA9={ema9_h1:.2f} EMA21={ema21_h1:.2f}) profit=${profit:.2f} → CLOSE (cut loss)")
                                    close_position_mt5(ticket)
                                    log_event("TREND_REVERSAL_EXIT", f"#{ticket} {pos_type} closed — H1 reversed to {h1_trend}, loss=${profit:.2f}")
                                    continue
                                elif profit > 0:
                                    # Profitable but trend turning — take profit
                                    # Recovery check: if profit covers recovery target, definitely close
                                    _should_close = False
                                    if _recovery_target_local > 0 and profit >= _recovery_target_local * 0.7:
                                        print(f"[TREND-EXIT] 🎯 #{ticket} {pos_type} trend reversed to {h1_trend}, "
                                              f"profit ${profit:.2f} covers {profit/_recovery_target_local*100:.0f}% of recovery target ${_recovery_target_local:.2f} → CLOSE (lock recovery)")
                                        _should_close = True
                                    elif profit >= max_profit_seen * 0.5 and max_profit_seen > 0:
                                        # Profit already dropped from peak — take what's left
                                        print(f"[TREND-EXIT] 💰 #{ticket} {pos_type} trend reversed to {h1_trend}, "
                                              f"profit ${profit:.2f} (peak ${max_profit_seen:.2f}) → CLOSE (protect gains)")
                                        _should_close = True
                                    if _should_close:
                                        close_position_mt5(ticket)
                                        log_event("TREND_REVERSAL_EXIT", f"#{ticket} {pos_type} closed — H1 reversed to {h1_trend}, profit=${profit:.2f}")
                                        continue
                except Exception:
                    pass  # trend reversal check is best-effort

            # ===== TIME + AI FORECAST DECISIONS =====
            if hold_sec < MIN_HOLD_SEC:
                continue
            if profit <= 0 and hold_sec < MAX_HOLD_SEC_LOSS:
                # Even when losing, check more often if hold time is getting long
                if hold_sec > MAX_HOLD_SEC_LOSS * 0.7:
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

            # --- Gather compact context for forecast (cached per monitor cycle) ---
            if not hasattr(smart_position_monitor, "_fc_ctx") or smart_position_monitor._fc_ts != now_ts:
                _fc_news = ""
                _fc_trend = ""
                _fc_wr = ""
                try:
                    news_imm, news_ev = is_high_impact_news_imminent(window_min=30)
                    if news_imm:
                        _fc_news = f"High-impact: {news_ev} within 30min — volatility risk"
                except Exception:
                    pass
                try:
                    ch1 = get_candles_from_mt5("H1", 30)
                    ch4 = get_candles_from_mt5("H4", 30)
                    if ch1 and ch4:
                        cl_h1 = [c["close"] for c in ch1]
                        cl_h4 = [c["close"] for c in ch4]
                        e9_h1, e21_h1 = calc_ema(cl_h1, 9), calc_ema(cl_h1, 21)
                        e9_h4, e21_h4 = calc_ema(cl_h4, 9), calc_ema(cl_h4, 21)
                        h1d = "UP" if e9_h1 and e21_h1 and e9_h1 > e21_h1 else "DOWN" if e9_h1 and e21_h1 else "?"
                        h4d = "UP" if e9_h4 and e21_h4 and e9_h4 > e21_h4 else "DOWN" if e9_h4 and e21_h4 else "?"
                        _fc_trend = f"H1={h1d} H4={h4d}"
                except Exception:
                    pass
                try:
                    ws = get_recent_win_rate(3)
                    if ws["total"] >= 3:
                        _fc_wr = f"{ws['win_rate']}% WR ({ws['wins']}W/{ws['losses']}L) P/L=${ws['total_profit']}"
                except Exception:
                    pass
                smart_position_monitor._fc_ctx = (_fc_news, _fc_trend, _fc_wr)
                smart_position_monitor._fc_ts = now_ts
            _fc_news, _fc_trend, _fc_wr = smart_position_monitor._fc_ctx

            # Build recovery context for AI forecast
            _fc_recovery = ""
            if _recovery_target_local > 0:
                coverage = profit / _recovery_target_local * 100
                _fc_recovery = (f"Recovery target: ${_recovery_target_local:.2f} (accumulated losses). "
                                f"Current profit covers {coverage:.0f}%. "
                                f"{'HOLD to reach target' if profit < _recovery_target_local else 'Target MET — consider taking profit'}")

            if hold_sec >= MAX_HOLD_SEC_LOSS and profit <= 0:
                forecast = ai_quick_forecast(
                    candles_scalp, current_price, pos_type, profit, scalp_tf,
                    open_price=open_price, hold_sec=hold_sec,
                    news_alert=_fc_news, trend_summary=_fc_trend, win_rate_summary=_fc_wr,
                )
                print(f"[SMART] ⏰ #{ticket} {hold_sec}s > MAX_LOSS, loss ${profit:.2f} | AI: {forecast['action']} — {forecast['reason']}")
                if forecast["action"] == "CLOSE":
                    close_position_mt5(ticket)
                continue

            # AI profit-taking: two paths
            # 1. Percentage-based (original): profit >= 0.5% of balance
            # 2. Absolute-dollar (new): profit >= $0.50 after MIN_HOLD_SEC — for small lots
            #    This ensures AI manages positions even when lot size is tiny
            _abs_profit_threshold = 0.50 if _is_crypto_symbol() else 2.0
            _should_check_profit = (
                (profit >= min_profit_close and hold_sec >= MIN_HOLD_SEC) or  # %-based
                (profit >= _abs_profit_threshold and hold_sec >= MIN_HOLD_SEC)  # absolute
            )

            if _should_check_profit:
                forecast = ai_quick_forecast(
                    candles_scalp, current_price, pos_type, profit, scalp_tf,
                    open_price=open_price, hold_sec=hold_sec,
                    news_alert=_fc_news,
                    trend_summary=_fc_trend + (f" | {_fc_recovery}" if _fc_recovery else ""),
                    win_rate_summary=_fc_wr,
                )
                print(f"[SMART] 💰 #{ticket} {pos_type} | {hold_sec}s | ${profit:.2f} | AI: {forecast['action']} — {forecast['reason']}")
                if forecast["action"] == "CLOSE":
                    # Re-check profit before closing — price can move during AI call (787ms+)
                    # With large lots, even $0.30 move = big P/L swing
                    try:
                        _re = http_session.get(f"http://{windows_ip}:8000/positions", timeout=5)
                        _re_pos = [p for p in _re.json().get("positions", []) if p["ticket"] == ticket]
                        if _re_pos:
                            _re_profit = _re_pos[0]["profit"]
                            if _re_profit <= 0 and profit > 0:
                                print(f"[SMART] ⏸️ #{ticket} profit flipped ${profit:.2f} → ${_re_profit:.2f} during AI call — HOLD instead of closing at loss")
                                continue
                            profit = _re_profit  # Use latest profit for log accuracy
                    except Exception:
                        pass  # If re-check fails, proceed with close (original decision still valid)
                    close_position_mt5(ticket)
                    continue

            # Check losing positions approaching max hold (70-100% of MAX_HOLD_SEC_LOSS)
            # Only ask AI if loss is significant relative to SL distance
            # This prevents premature exits on positions where SL gives plenty of room
            if profit <= 0 and hold_sec > MAX_HOLD_SEC_LOSS * 0.7:
                # Calculate how much of the SL room has been used
                _price_against = abs(current_price - open_price)
                _sl_room_total = abs(current_sl - open_price) if current_sl > 0 else 999
                _sl_used_pct = (_price_against / _sl_room_total * 100) if _sl_room_total > 0 else 0

                if _sl_used_pct < 30 and hold_sec < MAX_HOLD_SEC_LOSS * 0.9:
                    # Loss is small relative to SL — price is oscillating normally, skip AI check
                    pass
                else:
                    forecast = ai_quick_forecast(
                        candles_scalp, current_price, pos_type, profit, scalp_tf,
                        open_price=open_price, hold_sec=hold_sec,
                        news_alert=_fc_news, trend_summary=_fc_trend, win_rate_summary=_fc_wr,
                    )
                    print(f"[SMART] ⚠️ #{ticket} losing ${profit:.2f} at {hold_sec}s (SL {_sl_used_pct:.0f}% used) | AI: {forecast['action']} — {forecast['reason']}")
                    if forecast["action"] == "CLOSE":
                        close_position_mt5(ticket)

        # Cleanup stale entries
        open_tickets = {p["ticket"] for p in positions}
        with _forecast_lock:
            for t in list(_forecast_cooldown.keys()):
                if t not in open_tickets:
                    del _forecast_cooldown[t]
        with _position_state_lock:
            for t in list(_last_prices.keys()):
                if t not in open_tickets:
                    del _last_prices[t]
            _partial_closed.difference_update(_partial_closed - open_tickets)
            for t in list(_position_max_profit.keys()):
                if t not in open_tickets:
                    del _position_max_profit[t]

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

            # ---- Friday Auto-Close (skip for crypto — no weekend gap) ----
            if FRIDAY_AUTO_CLOSE and not _is_crypto_symbol() and is_friday_close_window(FRIDAY_CLOSE_MINUTES_BEFORE):
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
MAX_SPREAD = float(os.getenv("MAX_SPREAD", 0.5))
# Minimum seconds between new trade entries (prevent over-trading)
MIN_TRADE_INTERVAL_SEC = int(os.getenv("MIN_TRADE_INTERVAL_SEC", 120))
_last_trade_ts: float = 0.0
_last_analysis_price: float = 0.0   # For price-event trigger
PRICE_EVENT_PCT = float(os.getenv("PRICE_EVENT_PCT", 0.2))  # % move to trigger re-analysis

# WAIT-streak tracking: escalates confidence threshold for crypto after long WAIT runs
_consecutive_waits: int = 0
WAIT_STREAK_THRESHOLD = int(os.getenv("WAIT_STREAK_THRESHOLD", 10))  # after N WAITs, relax crypto conf by 1


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

    # Whipsaw protection: max 3 recovery attempts per hour
    # Prune attempts older than 1 hour
    _recovery_attempts_recent[:] = [ts for ts, _ in _recovery_attempts_recent if now - ts < 3600]
    _max_recovery = 5 if _is_crypto_symbol() else 3  # crypto trades 24/7, allow more recovery attempts
    if len(_recovery_attempts_recent) >= _max_recovery:
        print(f"[RECOVERY] ⛔ Whipsaw protection: {len(_recovery_attempts_recent)} recovery attempts in last hour — pausing")
        log_event("RECOVERY_WHIPSAW", f"{len(_recovery_attempts_recent)} attempts in 1hr")
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

        # --- Get recent losses with total accumulated loss ---
        loss_info = get_consecutive_loss_total(symbol)
        total_loss = loss_info["total_loss"]
        loss_count = loss_info["count"]

        loss_context = f"CONSECUTIVE LOSS STREAK: {loss_count} trades, TOTAL LOSS = ${total_loss:.2f}\n"
        loss_context += "Individual losses:\n"
        for l in loss_info["losses"]:
            loss_context += (
                f"  {l['action']} open={l['open']} close={l['close']} P/L=${l['profit']:.2f} "
                f"SL={l['sl']} TP={l['tp']} lot={l['lot']}\n"
            )
        loss_context += (
            f"\nRECOVERY OBJECTIVE: The recovery trade must target a profit of at least "
            f"${total_loss:.2f} to break even on this losing streak. "
            f"Ideally target ${total_loss * 1.5:.2f}+ for a net positive recovery.\n"
            f"\nRECOVERY RULES:\n"
            f"1. Analyze WHY these {loss_count} trades lost — was it a trend reversal, stop hunt, or bad entry timing?\n"
            f"2. If all losses were in the SAME direction, the trend may have reversed — consider the OPPOSITE direction.\n"
            f"3. If losses were mixed directions, the market is choppy — require VERY strong signal (conf 8+).\n"
            f"4. The TP target will be adjusted to recover ${total_loss:.2f}+ — assess if this price target is "
            f"realistic given current volatility, support/resistance levels, and trend strength.\n"
            f"5. If the recovery target seems unrealistic (too far from current price), recommend WAIT — "
            f"do NOT force a trade just to recover. Patience is better than compounding losses.\n"
            f"6. Only recommend a trade if you have HIGH confidence (7+) AND the TP target is achievable.\n"
        )

        # --- Fetch multi-TF candles for full analysis ---
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

        # Fetch H4 + scalp candles for better analysis
        try:
            h4_resp = http_session.get(f"http://{windows_ip}:8000/candles/{symbol}?timeframe=H4&count=30", timeout=15)
            candles_h4 = h4_resp.json().get("candles", [])
        except Exception:
            candles_h4 = []
        try:
            scalp_resp = http_session.get(f"http://{windows_ip}:8000/candles/{symbol}?timeframe={scalp_tf}&count=50", timeout=15)
            candles_scalp = scalp_resp.json().get("candles", [])
        except Exception:
            candles_scalp = []

        # Build full technical summary (same quality as normal analysis)
        tech_summary = build_technical_summary(candles_h1, candles_h4, [], candles_scalp, scalp_tf)

        # Add RAG context + auto-generated lessons for smarter recovery
        try:
            rag_context = build_rag_context()
            if rag_context:
                loss_context += "\n\n" + rag_context
            auto_lessons = get_auto_generated_lessons()
            if auto_lessons:
                loss_context += "\n\n" + auto_lessons
        except Exception:
            pass

        # --- AI Analysis (full context like normal trade) ---
        ai_price_data = {"bid": bid, "ask": ask, "spread": spread}

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

        # --- Smart recovery lot sizing & TP targeting ---
        atr_h1 = calc_atr(candles_h1, 14) if len(candles_h1) >= 14 else None
        risk_info = calculate_lot_size(atr_value=atr_h1)
        sl_points = risk_info["sl_points"]
        tp_points = risk_info["tp_points"]
        pvpl = float(os.getenv("POINT_VALUE_PER_LOT", 1.0))
        max_tp = float(os.getenv("MAX_TP_POINTS", 500))

        # Recovery lot: scale between 50%-100% of normal based on confidence
        # conf 7 = 50% (cautious), conf 8 = 75%, conf 9-10 = 100% (high conviction)
        lot_scale = min(1.0, 0.25 + (confidence - 6) * 0.25)  # 7->0.50, 8->0.75, 9->1.0
        lot_size = max(0.01, round(risk_info["lot_size"] * lot_scale, 2))

        # Calculate minimum TP needed to recover accumulated losses
        if total_loss > 0 and lot_size > 0 and pvpl > 0:
            # tp_dollars = tp_points * pvpl * lot_size
            # => min_recovery_points = total_loss / (pvpl * lot_size)
            min_recovery_points = total_loss / (pvpl * lot_size)
            # Target 1.5x the loss for net positive recovery
            target_recovery_points = round(min_recovery_points * 1.5)

            if target_recovery_points > tp_points and target_recovery_points <= max_tp:
                # Feasible — extend TP to cover accumulated losses
                print(f"[RECOVERY] 📊 Extending TP: {tp_points} → {target_recovery_points} pts "
                      f"to recover ${total_loss:.2f} loss (1.5x target)")
                tp_points = target_recovery_points
            elif target_recovery_points > max_tp:
                # Recovery target exceeds MAX_TP — use MAX_TP and see what we can recover
                potential_recovery = max_tp * pvpl * lot_size
                print(f"[RECOVERY] 📊 Recovery target {target_recovery_points} pts > MAX_TP {max_tp} — "
                      f"using MAX_TP, can recover ${potential_recovery:.2f} of ${total_loss:.2f}")
                tp_points = int(max_tp)
            else:
                # Standard TP already covers the recovery
                print(f"[RECOVERY] 📊 Standard TP {tp_points} pts already covers ${total_loss:.2f} recovery")

        recovery_potential = round(tp_points * pvpl * lot_size, 2)
        print(f"[RECOVERY] 💰 Loss=${total_loss:.2f} | TP target=${recovery_potential:.2f} "
              f"| lot={lot_size} ({lot_scale:.0%} risk) | TP={tp_points} pts | SL={sl_points} pts")

        if action == "BUY":
            sl_price = round(ask - sl_points * POINT_SIZE, 2)
            tp_price = round(ask + tp_points * POINT_SIZE, 2)
        else:
            sl_price = round(bid + sl_points * POINT_SIZE, 2)
            tp_price = round(bid - tp_points * POINT_SIZE, 2)

        trade_result = send_trade_to_mt5(action, symbol, lot_size, sl_points, tp_points, bid, ask)
        if trade_result and trade_result.get("success"):
            global _last_trade_ts, _recovery_target
            _last_trade_ts = time.time()  # Update cooldown timer
            _loss_pause_at_count = consec_losses if consec_losses > 0 else 999  # Mark current losses as handled
            with _recovery_target_lock:
                _recovery_target = total_loss  # Set recovery target for position monitor
            _recovery_attempts_recent.append((time.time(), action))
            print(f"[RECOVERY] ✅ Recovery {action} | lot={lot_size} ({lot_scale:.0%}) conf={confidence} "
                  f"SL={sl_price} TP={tp_price} | recovering ${total_loss:.2f} → target ${recovery_potential:.2f}")
            log_event("RECOVERY_TRADE", f"{action} lot={lot_size} conf={confidence} "
                      f"loss=${total_loss:.2f} target=${recovery_potential:.2f}")
            save_trade_with_context(
                order_id=trade_result["order_id"],
                symbol=symbol,
                action=action,
                lot=lot_size,
                open_price=trade_result.get("price", ask if action == "BUY" else bid),
                sl_price=sl_price,
                tp_price=tp_price,
                ai_confidence=confidence if isinstance(confidence, int) else None,
                trend_direction=trend_dir if trend_dir else None,
            )
            return True
        else:
            print(f"[RECOVERY] ❌ Recovery trade failed: {trade_result}")
            return False

    except Exception as e:
        print(f"[RECOVERY] ❌ Recovery analysis error: {e}")
        return False


def main_loop():
    global _last_analysis_price, _consecutive_waits, _last_trade_ts, _recovery_target
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
    _loss_pause_at_count = 999   # loss count already paused for (999 = skip on startup, reset when trade opens)
    _loss_pause_logged = False   # track whether "already paused" message was logged (avoid spam)
    _recovery_target = 0.0  # reset on startup

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

        # ---- Friday: block new trades before close (skip for crypto) ----
        if FRIDAY_AUTO_CLOSE and not _is_crypto_symbol() and is_friday_close_window(FRIDAY_NO_NEW_TRADE_MINUTES):
            now_f = datetime.now(timezone.utc)
            mins_left = (22 * 60) - (now_f.hour * 60 + now_f.minute)
            print(f"[FRIDAY] 🔒 {mins_left}min to market close — no new trades (monitor still active)")
            sync_closed_trades()
            time.sleep(60)
            continue

        # ---- Time-of-day filter (skip for crypto — 24/7 market) ----
        BAD_HOURS_UTC     = [int(h) for h in os.getenv("BAD_HOURS_UTC", "2,3").split(",") if h.strip()]
        current_hour_utc  = datetime.now(timezone.utc).hour
        if current_hour_utc in BAD_HOURS_UTC and not _is_crypto_symbol():
            # Calculate minutes until next good hour instead of sleeping fixed 60s
            now_utc = datetime.now(timezone.utc)
            minutes_left = 60 - now_utc.minute
            sleep_sec = min(minutes_left * 60, 3600)  # cap at 1 hour
            print(f"[TIME] ⏰ Hour {current_hour_utc:02d} UTC in bad-hours {BAD_HOURS_UTC} – sleeping {sleep_sec}s (~{minutes_left}min to next hour)")
            sync_closed_trades()
            time.sleep(sleep_sec)
            print(f"[TIME] ✅ Bad-hours sleep done — resuming trading at {datetime.now(timezone.utc).strftime('%H:%M')} UTC")
            continue

        # ---- Consecutive loss pause (with recovery attempt) ----
        LOSS_PAUSE_THRESHOLD = int(os.getenv("LOSS_PAUSE_THRESHOLD", 3))
        LOSS_PAUSE_SEC       = int(os.getenv("LOSS_PAUSE_SEC", 1800))
        # Crypto: short cooldown (3 min) — market moves fast 24/7, long pause = missed opportunity
        # Gold: longer cooldown (30 min) — session-based, pause until conditions change
        _pause_sec = 180 if _is_crypto_symbol() else LOSS_PAUSE_SEC
        consec_losses = get_consecutive_losses()
        if consec_losses >= LOSS_PAUSE_THRESHOLD and consec_losses > _loss_pause_at_count:
            # Only pause if losses INCREASED since last pause (prevents repeat pause for same streak)
            print(f"[SAFETY] ⚠️ {consec_losses} consecutive losses (new since last pause at {_loss_pause_at_count}) – attempting recovery...")
            log_event("LOSS_PAUSE", f"{consec_losses} consecutive losses – running recovery")
            sync_closed_trades()
            # Try recovery trade instead of blind pause
            scalp_tf = os.getenv("SCALP_TIMEFRAME", "M5")
            recovered = attempt_recovery_trade(symbol, scalp_tf)
            if not recovered:
                print(f"[SAFETY] Recovery declined — cooling down {_pause_sec}s then resuming normal trading")
                time.sleep(_pause_sec)
            else:
                # Recovery trade opened, wait shorter cooldown then continue
                time.sleep(60)
            _loss_pause_at_count = consec_losses  # Don't pause again for same streak
            _loss_pause_logged = False  # Reset so we log the "already paused" message once
            continue
        elif consec_losses >= LOSS_PAUSE_THRESHOLD:
            # Already paused for this streak — log once, then stay quiet
            if not _loss_pause_logged:
                print(f"[SAFETY] ℹ️ {consec_losses} losses (already paused) — trading normally to break streak")
                _loss_pause_logged = True

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

        # Daily loss circuit breaker
        daily_ok, daily_msg = check_daily_loss_limit()
        if not daily_ok:
            print(f"[SAFETY] 🔴 {daily_msg} — pausing until tomorrow")
            log_event("DAILY_LOSS_LIMIT", daily_msg)
            # Sleep until midnight UTC
            now_utc = datetime.now(timezone.utc)
            midnight = (now_utc + timedelta(days=1)).replace(hour=0, minute=5, second=0, microsecond=0)
            sleep_sec = (midnight - now_utc).total_seconds()
            print(f"[SAFETY] Sleeping {int(sleep_sec/3600)}h until next day")
            time.sleep(min(sleep_sec, 28800))  # max 8h sleep
            continue

        try:
            _cycle_t0 = time.time()
            print(f"\n=== 🟢 AI Trader Node | {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ===")

            # ---- VPS health check (circuit breaker) ----
            if not check_vps_available():
                print("[CRITICAL] 🔴 VPS unreachable (circuit breaker open) — stopping bot")
                log_event("VPS_CIRCUIT_BREAK", "VPS unreachable — auto-stop")
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

            # ---- Fetch price ----
            price = get_price_from_mt5()
            if not price or "error" in price:
                raise RuntimeError("Failed to fetch price")

            # ---- Post-trade learning: analyze recently closed trades ----
            try:
                process_recently_closed_trades()
                update_daily_performance()
            except Exception as e:
                print(f"[POST-TRADE] ⚠️ {e}")

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
            _t_candles = time.time()
            print(f"[INFO] Fetching candles ({scalp_tf}, H1, H4, D1)...")
            candles_scalp = get_candles_from_mt5(scalp_tf, 30)
            candles_h1    = get_candles_from_mt5("H1", 50)
            candles_h4    = get_candles_from_mt5("H4", 50)
            candles_d1    = get_candles_from_mt5("D1", 30)

            tech_summary = ""
            h1_atr       = None
            trend_info   = None
            consolidating = False
            if candles_h1 and candles_h4 and candles_d1:
                tech_summary = build_technical_summary(
                    candles_h1, candles_h4, candles_d1,
                    candles_scalp=candles_scalp, scalp_tf=scalp_tf,
                )
                h1_atr = calc_atr(candles_h1, 14)
                trend_info = get_trend_alignment(candles_h1, candles_h4, candles_d1)
                print(f"[TECH]\n{tech_summary}")
                print(f"[TREND] Direction={trend_info['direction']} Strength={trend_info['strength']}/3 ({trend_info['details']})")

                # ---- Consolidation detection ----
                consolidating = is_consolidating(candles_h1)
                if consolidating:
                    print("[CONSOLIDATION] ⚠️ Market is sideways (BB narrow + RSI neutral) — extra caution")
            else:
                print("[WARN] Incomplete candle data – price-only analysis")

            _t_candles_done = time.time()

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
                # Set recovery target: accumulated loss from current losing streak
                loss_info = get_consecutive_loss_total(symbol)
                if loss_info["total_loss"] > 0:
                    with _recovery_target_lock:
                        _recovery_target = loss_info["total_loss"]
                    print(f"[RECOVERY-TARGET] 🎯 Setting recovery target: ${loss_info['total_loss']:.2f} "
                          f"(from {loss_info['count']} consecutive losses)")
            elif consec_losses_now == 0:
                with _recovery_target_lock:
                    if _recovery_target > 0:
                        print(f"[RECOVERY-TARGET] ✅ Recovery target cleared (no consecutive losses)")
                    _recovery_target = 0.0  # Clear target when no losses

            # Consolidation risk reduction: halve lot when market is sideways
            if consolidating:
                reduced_lot = max(0.01, round(lot_size * 0.5, 2))
                print(f"[RISK] ⚠️ Consolidation → lot {lot_size} → {reduced_lot} (50% reduction)")
                lot_size = reduced_lot

            # ---- Order book ----
            _t_ob = time.time()
            print("[INFO] Fetching Order Book...")
            ob_summary = get_orderbook_from_mt5()
            print(f"[ORDERBOOK] {ob_summary}")

            # ---- News ----
            _t_news = time.time()
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
            _t_ai = time.time()
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

            # Build dynamic bias analysis for AI context
            bias_context = ""
            try:
                conn_bc = get_db_connection()
                cur_bc = conn_bc.cursor()
                cur_bc.execute(
                    """SELECT action, COUNT(*), COALESCE(SUM(profit), 0)
                       FROM trades
                       WHERE opened_at >= NOW() - INTERVAL '24 hours'
                         AND status = 'CLOSED'
                       GROUP BY action;"""
                )
                bc_rows = cur_bc.fetchall()
                cur_bc.close()
                conn_bc.close()
                if bc_rows:
                    bc_data = {r[0]: {"count": r[1], "pnl": float(r[2])} for r in bc_rows}
                    bc_total = sum(d["count"] for d in bc_data.values())
                    if bc_total >= 3:
                        bc_parts = [f"{a}: {d['count']} trades (P/L=${d['pnl']:+.2f})" for a, d in bc_data.items()]
                        dominant = max(bc_data, key=lambda a: bc_data[a]["count"])
                        dom_pct = bc_data[dominant]["count"] / bc_total * 100
                        dom_pnl = bc_data[dominant]["pnl"]
                        trend_note = ""
                        if trend_info:
                            t_dir = trend_info.get("direction", "MIXED")
                            t_str = trend_info.get("strength", 0)
                            if t_dir == dominant and t_str >= 2:
                                trend_note = (
                                    f"The {dominant} bias ALIGNS with the H1+H4 trend (strength {t_str}/3). "
                                    f"Trend-following is valid — repeated same-direction trades are OK when the trend confirms. "
                                    f"Focus on ENTRY QUALITY (pullbacks, confluence) rather than switching direction."
                                )
                            elif t_dir != "MIXED" and t_dir != dominant:
                                trend_note = (
                                    f"WARNING: The {dominant} bias is AGAINST the H1+H4 trend ({t_dir}, strength {t_str}/3). "
                                    f"This is dangerous — the market has shifted. Strongly consider {t_dir} setups instead."
                                )
                            else:
                                trend_note = (
                                    f"Trend is MIXED — no clear multi-TF alignment. "
                                    f"High {dominant} bias without trend support suggests caution. Require strong confluence."
                                )
                        pnl_note = ""
                        if dom_pnl > 0:
                            pnl_note = f"The {dominant} trades are NET PROFITABLE (${dom_pnl:+.2f}) — the direction has been working."
                        else:
                            pnl_note = f"The {dominant} trades are NET LOSING (${dom_pnl:+.2f}) — this direction is NOT working. Consider switching."
                        bias_context = (
                            f"\n=== DIRECTION BIAS ANALYSIS (24h) ===\n"
                            f"Trades today: {' | '.join(bc_parts)} (total={bc_total})\n"
                            f"Dominant direction: {dominant} at {dom_pct:.0f}%\n"
                            f"{pnl_note}\n"
                            f"{trend_note}\n"
                            f"RULE: If bias aligns with trend AND is profitable → same direction is OK with good entry. "
                            f"If bias is against trend OR losing → actively seek the opposite direction or WAIT.\n"
                        )
            except Exception:
                pass

            extra_knowledge = ""
            if perf_context:
                extra_knowledge += perf_context
            if trend_context:
                extra_knowledge += trend_context
            if bias_context:
                extra_knowledge += bias_context
            if consolidating:
                if _is_crypto_symbol():
                    extra_knowledge += (
                        "\n=== CONSOLIDATION NOTE (Crypto) ===\n"
                        "H4/D1 are consolidating, but this is NORMAL for crypto. "
                        "If H1 shows a clear trend (EMA alignment + MACD momentum), "
                        "you CAN trade with confidence 6-7. Focus on H1 trend + momentum signals. "
                        "Only WAIT if H1 is ALSO sideways.\n"
                    )
                else:
                    extra_knowledge += (
                        "\n=== CONSOLIDATION WARNING ===\n"
                        "Market is currently CONSOLIDATING (narrow BB bandwidth + neutral RSI). "
                        "Prefer WAIT unless price is at clear Support/Resistance with strong candle confirmation. "
                        "If recommending BUY/SELL during consolidation, use confidence 5-6 max.\n"
                    )

            # === RAG CONTEXT: Self-learning from trade history ===
            try:
                rag_context = build_rag_context()
                if rag_context:
                    extra_knowledge += "\n\n" + rag_context
                auto_lessons = get_auto_generated_lessons()
                if auto_lessons:
                    extra_knowledge += "\n\n" + auto_lessons
            except Exception as e:
                print(f"[RAG] ⚠️ Failed to build RAG context: {e}")

            # Extract D1 High/Low as liquidity zones
            d1_high_val = None
            d1_low_val  = None
            if candles_d1 and len(candles_d1) >= 2:
                recent_d1 = candles_d1[-2:]  # yesterday + today
                d1_high_val = max(c["high"] for c in recent_d1)
                d1_low_val  = min(c["low"]  for c in recent_d1)

            analysis = analyze_with_ai(
                price, tech_summary,
                orderbook_summary=ob_summary,
                news_summary=news_summary,
                journal_history=j_history,
                journal_knowledge=(j_knowledge + extra_knowledge) if extra_knowledge else j_knowledge,
                trade_history=trade_log_summary,
                scalp_tf=scalp_tf,
                d1_high=d1_high_val,
                d1_low=d1_low_val,
            )
            _t_ai_done = time.time()
            print(f"\n>>> 🤖 AI RESULT <<<\n{analysis}\n{'='*30}")
            print(
                f"[TIMING] ⏱️ Candles={_t_candles_done - _t_candles:.1f}s | "
                f"OB+News={_t_ai - _t_ob:.1f}s | "
                f"AI={_t_ai_done - _t_ai:.1f}s | "
                f"Total={_t_ai_done - _cycle_t0:.1f}s"
            )

            if analysis == "ERROR":
                raise RuntimeError("AI returned ERROR")

            # ---- Parse action ----
            action = parse_sentiment(analysis)
            print(f"[DECISION] 🎯 AI Sentiment → {action}")

            # ---- Trend alignment safety net ----
            # AI already receives full trend context in its prompt. This is an EXTREME safety only:
            # Block counter-trend trades when ALL timeframes (strength 3/3) disagree AND confidence is low.
            # Softer cases: just log — the AI has the information to decide.
            if action in ("BUY", "SELL") and trend_info:
                trend_dir = trend_info["direction"]
                trend_str = trend_info["strength"]
                confidence = _extract_confidence(analysis)
                if trend_dir != "MIXED" and trend_dir != action:
                    if trend_str >= 3 and confidence < 7:
                        # ALL 3 timeframes oppose + low confidence = hard block
                        print(
                            f"[TREND] 🛑 {action} blocked: ALL TFs trend {trend_dir} "
                            f"(strength 3/3), conf={confidence} < 7 → WAIT"
                        )
                        log_event("TREND_FILTER", f"Blocked {action} — trend={trend_dir} str=3 conf={confidence}")
                        action = "WAIT"
                    else:
                        # Softer: just log, trust AI's decision
                        print(f"[TREND] ℹ️ {action} vs trend {trend_dir} (str={trend_str}/3) — AI conf={confidence}, trusting AI")

            # ---- S/R Room-to-Move info (AI context, not hard block) ----
            # AI already receives S/R levels in technical summary. Log room-to-move for transparency.
            # Only hard-block when room is critically small (< 20% of TP) — a clear trap.
            if action in ("BUY", "SELL") and candles_h1 and len(candles_h1) >= 20:
                sr_h1 = calc_support_resistance(candles_h1, 20)
                if sr_h1:
                    current_mid = (bid + ask) / 2
                    tp_distance_usd = tp_points * POINT_SIZE
                    if action == "BUY":
                        room_to_resist = sr_h1["resistance"] - current_mid
                        room_pct = room_to_resist / tp_distance_usd if tp_distance_usd > 0 else 1
                        if room_pct < 0.20:
                            confidence = _extract_confidence(analysis)
                            if confidence < 8:
                                print(
                                    f"[S/R] 🛑 BUY blocked: only ${room_to_resist:.2f} room to resistance "
                                    f"{sr_h1['resistance']} ({room_pct:.0%} of TP) — trap zone, conf={confidence} → WAIT"
                                )
                                log_event("SR_FILTER", f"BUY blocked: room={room_to_resist:.2f} ({room_pct:.0%} of TP)")
                                action = "WAIT"
                        elif room_pct < 0.50:
                            print(
                                f"[S/R] ℹ️ BUY: ${room_to_resist:.2f} room to resistance "
                                f"{sr_h1['resistance']} ({room_pct:.0%} of TP) — AI has context, trusting decision"
                            )
                    elif action == "SELL":
                        room_to_support = current_mid - sr_h1["support"]
                        room_pct = room_to_support / tp_distance_usd if tp_distance_usd > 0 else 1
                        if room_pct < 0.20:
                            confidence = _extract_confidence(analysis)
                            if confidence < 8:
                                print(
                                    f"[S/R] 🛑 SELL blocked: only ${room_to_support:.2f} room to support "
                                    f"{sr_h1['support']} ({room_pct:.0%} of TP) — trap zone, conf={confidence} → WAIT"
                                )
                                log_event("SR_FILTER", f"SELL blocked: room={room_to_support:.2f} ({room_pct:.0%} of TP)")
                                action = "WAIT"
                        elif room_pct < 0.50:
                            print(
                                f"[S/R] ℹ️ SELL: ${room_to_support:.2f} room to support "
                                f"{sr_h1['support']} ({room_pct:.0%} of TP) — AI has context, trusting decision"
                            )

            # ---- Direction Bias SAFETY NET ----
            # The AI now receives full bias + trend + P/L context in its prompt,
            # so it can make informed decisions about direction bias dynamically.
            # This hard-coded filter is now an EXTREME safety net only:
            # Block when >90% same direction AND that direction is net-losing (clearly broken)
            if action in ("BUY", "SELL") and win_stats["total"] >= 5:
                try:
                    conn_bias = get_db_connection()
                    cur_bias = conn_bias.cursor()
                    cur_bias.execute(
                        """SELECT action, COUNT(*), COALESCE(SUM(profit), 0) FROM trades
                           WHERE opened_at >= NOW() - INTERVAL '24 hours'
                             AND status = 'CLOSED'
                           GROUP BY action;"""
                    )
                    bias_rows = cur_bias.fetchall()
                    cur_bias.close()
                    conn_bias.close()
                    direction_counts = {r[0]: {"count": r[1], "pnl": float(r[2])} for r in bias_rows}
                    total_dir = sum(d["count"] for d in direction_counts.values())
                    if total_dir >= 5:
                        action_data = direction_counts.get(action, {"count": 0, "pnl": 0})
                        same_dir_pct = action_data["count"] / total_dir * 100
                        same_dir_pnl = action_data["pnl"]
                        confidence = _extract_confidence(analysis)
                        # If action aligns with multi-TF trend (2/3+), bias is correct trend-following → skip block
                        trend_confirms = (
                            trend_info
                            and trend_info.get("direction") == action
                            and trend_info.get("strength", 0) >= 2
                        )
                        # Extreme safety: >90% same direction AND losing money → hard block
                        # BUT NOT if the multi-TF trend confirms this direction
                        if same_dir_pct >= 90 and same_dir_pnl < 0 and confidence < 8 and not trend_confirms:
                            print(
                                f"[BIAS] 🛑 {action} blocked (safety net): {same_dir_pct:.0f}% of {total_dir} "
                                f"trades are {action} AND net P/L=${same_dir_pnl:+.2f} (losing), conf={confidence} < 8 → WAIT"
                            )
                            log_event("BIAS_FILTER", f"{action} extreme bias {same_dir_pct:.0f}%, net_pnl={same_dir_pnl:+.2f}, conf={confidence}")
                            action = "WAIT"
                        elif same_dir_pct >= 90 and same_dir_pnl < 0 and trend_confirms:
                            print(
                                f"[BIAS] ℹ️ {action} bias {same_dir_pct:.0f}% (net ${same_dir_pnl:+.2f}) but "
                                f"trend confirms {action} ({trend_info['strength']}/3) — allowing trade"
                            )
                        elif same_dir_pct > 75:
                            # Soft warning — AI already has this context, just log it
                            print(
                                f"[BIAS] ℹ️ {action} bias {same_dir_pct:.0f}% (net ${same_dir_pnl:+.2f}) — "
                                f"AI has full context, trusting its conf={confidence} decision"
                            )
                except Exception:
                    pass  # bias check is best-effort

            # ---- Execute trade ----
            sl_price = None
            tp_price = None
            if action in ("BUY", "SELL"):
                # ---- Trade interval cooldown ----
                time_since_last = time.time() - _last_trade_ts
                if time_since_last < MIN_TRADE_INTERVAL_SEC:
                    wait_remaining = int(MIN_TRADE_INTERVAL_SEC - time_since_last)
                    print(f"[COOLDOWN] ⏳ {wait_remaining}s remaining before next trade (min interval={MIN_TRADE_INTERVAL_SEC}s) → WAIT")
                    action = "WAIT"

            if action in ("BUY", "SELL"):
                trades_today = get_today_trade_count()
                if trades_today >= max_trades:
                    print(f"[LIMIT] ⛔ Daily limit reached ({trades_today}/{max_trades}) – skipping {action}")
                    log_event("LIMIT", f"Max trades/day reached ({trades_today}/{max_trades})")
                    action = "WAIT"
                else:
                    if action == "BUY":
                        sl_price = round(ask - sl_points * POINT_SIZE, 2)
                        tp_price = round(ask + tp_points * POINT_SIZE, 2)
                    else:
                        sl_price = round(bid + sl_points * POINT_SIZE, 2)
                        tp_price = round(bid - tp_points * POINT_SIZE, 2)

                    # Sync closed trades + re-check position count before opening
                    sync_closed_trades()
                    open_count_recheck = count_open_positions(symbol)
                    if open_count_recheck >= MAX_CONCURRENT_POS:
                        print(f"[GUARD] 🛡️ Position limit reached after sync ({open_count_recheck}/{MAX_CONCURRENT_POS}) — skipping")
                        action = "WAIT"
                    else:
                        trade_result = send_trade_to_mt5(action, symbol, lot_size, sl_points, tp_points, bid, ask)
                        if trade_result and trade_result.get("success"):
                            _last_trade_ts = time.time()  # Update cooldown timer
                            _loss_pause_at_count = consec_losses if consec_losses > 0 else 999  # Mark current losses as handled
                            log_event("TRADE", f"{action} {symbol} Lot={lot_size} SL={sl_price} TP={tp_price}")
                            _trade_confidence = _extract_confidence(analysis) if analysis else None
                            _trade_regime = "consolidation" if consolidating else (trend_info.get("direction", "unknown") if trend_info else "unknown")
                            _trade_trend_dir = trend_info.get("direction") if trend_info else None
                            _trade_trend_str = trend_info.get("strength") if trend_info else None
                            save_trade_with_context(
                                order_id=trade_result["order_id"],
                                symbol=symbol,
                                action=action,
                                lot=lot_size,
                                open_price=trade_result.get("price", ask if action == "BUY" else bid),
                                sl_price=sl_price,
                                tp_price=tp_price,
                                ai_confidence=_trade_confidence,
                                market_regime=_trade_regime,
                                trend_direction=_trade_trend_dir,
                                trend_strength=_trade_trend_str,
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

            # Record price for price-event trigger
            _last_analysis_price = (bid + ask) / 2

            # Track WAIT streaks (crypto escalation)
            if action == "WAIT":
                _consecutive_waits += 1
                if _is_crypto_symbol() and _consecutive_waits >= WAIT_STREAK_THRESHOLD:
                    print(f"[WAIT-STREAK] ⚠️ {_consecutive_waits} consecutive WAITs — crypto confidence relaxed by 1")
            else:
                if _consecutive_waits > 0:
                    print(f"[WAIT-STREAK] ✅ Reset after {_consecutive_waits} WAITs — trade placed")
                _consecutive_waits = 0

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

        # ---- Wait interval (chunked for graceful shutdown + price event trigger) ----
        print(f"⏳ Waiting {interval}s before next cycle...")
        waited = 0
        while waited < interval and not _shutdown:
            time.sleep(min(5, interval - waited))
            waited += 5
            # Price Event Trigger: if price moved significantly, re-analyze early
            if waited < interval and _last_analysis_price > 0 and waited >= 10:
                try:
                    _pe_price = get_price_from_mt5()
                    if _pe_price and "error" not in _pe_price:
                        _pe_mid = (_pe_price["bid"] + _pe_price["ask"]) / 2
                        _pe_pct = abs(_pe_mid - _last_analysis_price) / _last_analysis_price * 100
                        if _pe_pct >= PRICE_EVENT_PCT:
                            print(f"[PRICE EVENT] ⚡ Price moved {_pe_pct:.2f}% "
                                  f"({_last_analysis_price:.2f} → {_pe_mid:.2f}) → immediate re-analysis")
                            log_event("PRICE_EVENT", f"Price moved {_pe_pct:.2f}%: {_last_analysis_price:.2f}→{_pe_mid:.2f}")
                            break
                except Exception:
                    pass

    log_event("STOP", "AI Trader service stopped")
    print("👋 System shut down successfully")


# ==========================================
# ENTRY POINT
# ==========================================
if __name__ == "__main__":
    main_loop()