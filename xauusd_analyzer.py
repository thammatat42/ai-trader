import os
import sys
import time
import signal
import traceback
import requests
import psycopg2
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv

load_dotenv()

# สร้าง HTTP Session ช่วยลด Latency (Connection Pooling / Keep-Alive)
http_session = requests.Session()

# Flag สำหรับ Graceful Shutdown (Ctrl+C / Docker Stop)
_shutdown = False


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
def calculate_lot_size() -> dict:
    """คำนวณ Lot Size, SL, TP  →  return dict พร้อมใช้"""
    balance = float(os.getenv("ACCOUNT_BALANCE", 1000.0))
    risk_pct = float(os.getenv("RISK_PERCENT", 1.0))
    sl_points = float(os.getenv("SL_POINTS", 300))
    tp_points = float(os.getenv("TP_POINTS", 600))   # TP default = 2x SL (Risk:Reward 1:2)

    risk_amount = balance * (risk_pct / 100)
    lot_size = risk_amount / sl_points
    final_lot = max(0.01, round(lot_size, 2))

    print(
        f"[INFO] ทุน ${balance} | เสี่ยง {risk_pct}% (${risk_amount}) "
        f"| SL {sl_points} จุด | TP {tp_points} จุด | R:R 1:{tp_points/sl_points:.1f} "
        f"-> ใช้ Lot: {final_lot}"
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


# ==========================================
# 2.5  PARSE AI SENTIMENT
# ==========================================
def parse_sentiment(ai_text: str) -> str:
    """
    แยก Sentiment จากข้อความ AI → return 'BUY' / 'SELL' / 'WAIT'
    Bullish  → BUY
    Bearish  → SELL
    Neutral / Unknown → WAIT
    """
    text_lower = ai_text.lower()
    if "bullish" in text_lower:
        return "BUY"
    elif "bearish" in text_lower:
        return "SELL"
    return "WAIT"


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
def analyze_with_ai(price_data) -> str:
    api_key = os.getenv("OPENROUTER_API_KEY")
    url = os.getenv("OPENROUTER_URL")
    model = os.getenv("MODEL")

    max_tokens = int(os.getenv("MAX_TOKENS", 100))
    temperature = float(os.getenv("TEMPERATURE", 0.1))

    if not api_key:
        print("[ERROR] ไม่พบ OPENROUTER_API_KEY ใน .env")
        return "ERROR"

    system_prompt = (
        "Act as pro market analyst. "
        "Reply EXACTLY in this format:\n"
        "Sentiment: <Bullish/Bearish/Neutral>\n"
        "Reason: <1 short sentence>"
    )

    user_prompt = (
        f"Current XAUUSD Price -> Bid: {price_data['bid']}, "
        f"Ask: {price_data['ask']}. Analyze sentiment."
    )

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

    try:
        response = http_session.post(url, headers=headers, json=payload, timeout=10)
        response.raise_for_status()
        return response.json()["choices"][0]["message"]["content"].strip()
    except Exception as e:
        print(f"[ERROR] AI API ล้มเหลว: {e}")
        return "ERROR"


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
    Return: (is_running, interval_seconds, pause_max_retries, pause_retry_sec)
    """
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(
            "SELECT is_running, interval_seconds, "
            "COALESCE(pause_max_retries, 5), COALESCE(pause_retry_sec, 10) "
            "FROM bot_settings LIMIT 1;"
        )
        row = cur.fetchone()
        cur.close()
        conn.close()
        if row:
            return bool(row[0]), int(row[1]), int(row[2]), int(row[3])
        return True, 300, 5, 10  # Defaults
    except Exception as e:
        print(f"[ERROR] เช็คสถานะ Bot ล้มเหลว: {e}")
        return False, 60, 5, 10  # DB พัง -> หยุดเทรดไว้ก่อนเพื่อความปลอดภัย


# ==========================================
# MAIN LOOP – รันแบบ Background Service
# ==========================================
MARKET_CLOSED_CHECK_SEC = 60  # เมื่อตลาดปิด เช็คซ้ำทุก 60 วินาที
CONSECUTIVE_ERR_LIMIT = 5     # ผิดพลาดติดต่อกัน 5 ครั้ง -> หยุดอัตโนมัติ


def main_loop():
    print("🚀 เริ่มระบบ AI Trader Background Service...")
    log_event("START", "AI Trader service started")

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
        is_running, interval, max_retries, retry_sec = check_bot_status()

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
            symbol = os.getenv("SYMBOL", "XAUUSD")
            print(f"[INFO] Bid {bid} / Ask {ask}")

            risk = calculate_lot_size()
            lot_size  = risk["lot_size"]
            sl_points = risk["sl_points"]
            tp_points = risk["tp_points"]

            # ---- 3. AI วิเคราะห์ ----
            print(f"[INFO] ส่งข้อมูลให้ AI ({os.getenv('MODEL')})...")
            analysis = analyze_with_ai(price)
            print(f"\n>>> 🤖 AI RESULT <<<\n{analysis}\n{'='*30}")

            if analysis == "ERROR":
                raise RuntimeError("AI ตอบกลับ ERROR")

            # ---- 4. แปลง Sentiment → Action ----
            action = parse_sentiment(analysis)
            print(f"[DECISION] 🎯 AI Sentiment → {action}")

            # ---- 5. ส่งคำสั่งเทรด (ถ้า BUY/SELL) ----
            sl_price = None
            tp_price = None
            if action in ("BUY", "SELL"):
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

            # ---- 6. บันทึก Log ----
            save_log_to_db(symbol, bid, ask, analysis, lot_size,
                           trade_action=action, sl_price=sl_price, tp_price=tp_price)

            # ---- 7. ซิงค์สถานะ Trade จาก MT5 ----
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

        # ---- 5. รอ Interval (แบ่งเป็นช่วงสั้นเพื่อ Graceful Shutdown) ----
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