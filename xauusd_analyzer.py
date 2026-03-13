import os
import sys
import requests
import psycopg2
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

# สร้าง HTTP Session ช่วยลด Latency (Connection Pooling / Keep-Alive)
http_session = requests.Session()

# ==========================================
# 1. RISK MANAGEMENT
# ==========================================
def calculate_lot_size() -> float:
    balance = float(os.getenv("ACCOUNT_BALANCE", 1000.0))
    risk_pct = float(os.getenv("RISK_PERCENT", 1.0))
    sl_points = float(os.getenv("SL_POINTS", 300))
    
    risk_amount = balance * (risk_pct / 100)
    lot_size = risk_amount / sl_points
    final_lot = max(0.01, round(lot_size, 2))
    
    print(f"[INFO] ทุน ${balance} | เสี่ยง {risk_pct}% (${risk_amount}) | SL {sl_points} จุด -> ใช้ Lot: {final_lot}")
    return final_lot

# ==========================================
# 2. FETCH PRICE FROM WINDOWS VPS
# ==========================================
def get_price_from_mt5():
    windows_ip = os.getenv("WINDOWS_IP")
    symbol = os.getenv("SYMBOL", "XAUUSD")
    url = f"http://{windows_ip}:8000/price/{symbol}"
    
    try:
        # ใช้ session เพื่อความเร็ว
        response = http_session.get(url, timeout=5)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        print(f"[ERROR] ไม่สามารถเชื่อมต่อ Windows VPS: {e}")
        return None

# ==========================================
# 3. AI ANALYSIS (OPTIMIZED LATENCY)
# ==========================================
def analyze_with_ai(price_data) -> str:
    api_key = os.getenv("OPENROUTER_API_KEY")
    url = os.getenv("OPENROUTER_URL")
    model = os.getenv("MODEL")
    
    # โหลดค่า Parameter จาก .env (พร้อมตั้งค่า Default ป้องกันพัง)
    max_tokens = int(os.getenv("MAX_TOKENS", 100))
    temperature = float(os.getenv("TEMPERATURE", 0.1))
    
    if not api_key:
        sys.exit("[ERROR] ไม่พบ OPENROUTER_API_KEY ใน .env")

    # Prompt สั้น กระชับ เพื่อลด Token ขาเข้า และเร่งความเร็วในการตอบสนอง
    system_prompt = (
        "Act as pro market analyst. "
        "Reply EXACTLY in this format:\n"
        "Sentiment: <Bullish/Bearish/Neutral>\n"
        "Reason: <1 short sentence>"
    )
    
    user_prompt = f"Current XAUUSD Price -> Bid: {price_data['bid']}, Ask: {price_data['ask']}. Analyze sentiment."

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "max_tokens": max_tokens,
        "temperature": temperature
    }

    try:
        # ใช้ session แบบ Keep-Alive
        response = http_session.post(url, headers=headers, json=payload, timeout=10)
        response.raise_for_status()
        return response.json()["choices"][0]["message"]["content"].strip()
    except Exception as e:
        print(f"[ERROR] AI API ล้มเหลว: {e}")
        return "ERROR"

# ==========================================
# 4. DATABASE LOGGING
# ==========================================
def save_log_to_db(symbol, bid, ask, ai_response, lot_size):
    try:
        conn = psycopg2.connect(
            host=os.getenv("DB_HOST"),
            user=os.getenv("DB_USER"),
            password=os.getenv("DB_PASS"),
            dbname=os.getenv("DB_NAME")
        )
        cursor = conn.cursor()
        
        insert_query = """
        INSERT INTO ai_analysis_log (symbol, bid, ask, ai_recommendation, lot_size)
        VALUES (%s, %s, %s, %s, %s)
        """
        cursor.execute(insert_query, (symbol, bid, ask, ai_response, lot_size))
        conn.commit()
        
        cursor.close()
        conn.close()
        print("[SUCCESS] 💾 บันทึก Log และ Lot Size ลง Database เรียบร้อยแล้ว")
    except Exception as e:
        print(f"[ERROR] Database Error: {e}")

# ==========================================
# MAIN ROUTINE
# ==========================================
def main():
    print(f"\n=== 🚀 XAUUSD AI Trader Node | {datetime.now().strftime('%H:%M:%S')} ===")
    
    price = get_price_from_mt5()
    if not price or "error" in price:
        sys.exit(1)
        
    print(f"[INFO] ดึงราคาสำเร็จ: Bid {price['bid']} / Ask {price['ask']}")
    lot_size = calculate_lot_size()

    print(f"[INFO] ส่งข้อมูลให้ AI ({os.getenv('MODEL')})...")
    analysis = analyze_with_ai(price)
    print("\n>>> 🤖 AI RESULT <<<")
    print(analysis)
    print("====================\n")

    save_log_to_db(os.getenv("SYMBOL"), price['bid'], price['ask'], analysis, lot_size)

if __name__ == "__main__":
    main()