import requests
import json

WINDOWS_IP = "YOUR_WINDOWS_IP"
OPENROUTER_API_KEY = "YOUR_OPENROUTER_API_KEY"

def get_price_from_mt5():
    url = f"http://{WINDOWS_IP}:8000/price/XAUUSD"
    try:
        response = requests.get(url, timeout=5)
        return response.json()
    except Exception as e:
        print(f"❌ Error ดึงราคาจาก Windows: {e}")
        return None

def analyze_with_ai(price_data):
    url = "https://openrouter.ai/api/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json"
    }

    # สร้าง Prompt สั่งงาน AI
    prompt = f"คุณคือผู้เชี่ยวชาญการเทรดทองคำ ตอนนี้ราคา XAUUSD คือ Bid: {price_data['bid']}, Ask: {price_data['ask']} จงวิเคราะห์สั้นๆ ว่าควร BUY, SELL, หรือ                WAIT พร้อมเหตุผลประกอบ 1 บรรทัด"

    payload = {
        "model": "anthropic/claude-3-haiku", # ใช้ Haiku เพราะคิดเร็วและประหยัด
        "messages": [{"role": "user", "content": prompt}]
    }

    try:
        response = requests.post(url, headers=headers, json=payload)
        result = response.json()
        return result['choices'][0]['message']['content']
    except Exception as e:
        print(f"❌ Error ติดต่อ OpenRouter: {e}")
        return None

if __name__ == "__main__":
    print("🔄 1. กำลังดึงราคาทองจาก MT5 (Windows VPS)...")
    price = get_price_from_mt5()

    if price and "error" not in price:
        print(f"✅ ได้ราคาแล้ว: {price}")
        print("🧠 2. กำลังส่งข้อมูลให้ AI ประมวลผลผ่าน OpenRouter...")

        ai_decision = analyze_with_ai(price)

        print("\n=============================")
        print("🤖 คำแนะนำจาก AI:")
        print(ai_decision)
        print("=============================")
    else:
        print("⚠️ ไม่สามารถดึงราคาได้ ตรวจสอบ Windows VPS อีกครั้ง")