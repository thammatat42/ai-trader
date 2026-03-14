# ==========================================
# AI Trader – Python Runtime
# ==========================================
FROM python:3.12-slim

WORKDIR /app

# ติดตั้ง dependencies (ไม่แสดง warning root)
COPY requirements.txt .
RUN pip install --no-cache-dir --root-user-action=ignore -r requirements.txt

# คัดลอก source code
COPY xauusd_analyzer.py .
COPY dashboard.py .
COPY env.example .env.example

# Default: รัน AI Trader (override ได้ใน docker-compose)
CMD ["python", "-u", "xauusd_analyzer.py"]
