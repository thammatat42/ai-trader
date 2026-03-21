.
🤖 Polymarket AI Agent — Technical Deep Dive (1/4)
.
━━━━━━━━━━━━━━━━━━━━━━
OVERVIEW
━━━━━━━━━━━━━━━━━━━━━━
.
Autonomous AI trading agent สำหรับ Polymarket prediction markets (ตลาดทำนาย crypto) ทำงาน 24/7 บน Apple Silicon Mac Studio โดยใช้ Qwen 3.5 35B (รันบนเครื่อง, ไม่มีค่า API) เป็นสมองหลัก ตัดสินใจซื้อ-ขายจากข้อมูล real-time 13 สัญญาณ + 10 sections RAG context จากฐานข้อมูลผลลัพธ์
.
Codebase: 18 Python files, 5,614 lines
Database: SQLite, 5 tables, 35 columns/trade
Runtime: Python 3.14 + asyncio, macOS launchd (auto-restart)
Trading: Polymarket CLOB API (on-chain orderbook)
Data: Binance Futures API (real-time market data)
AI: Ollama local inference (Qwen 3.5 35B + 9B)
Notifications: Telegram bot (real-time alerts)
.
━━━━━━━━━━━━━━━━━━━━━━
SCAN CYCLE (ทุก 2 นาที)
━━━━━━━━━━━━━━━━━━━━━━
.
Step 1 — Market Scanner market_scanner.py (250 lines)
• ดึงตลาดจาก Polymarket API (~300 markets)
• กรอง: active, มี volume, เหลือเวลา
• BTC-only filter (FOCUS_KEYWORDS=BTC,Bitcoin)
• ผลลัพธ์: 4-6 BTC markets ต่อ cycle
• ตลาด BTC มี 2 ประเภท:
— Up or Down 15 min: BTC ขึ้นหรือลงใน 15 นาที
— Price Level: BTC ถึงราคาเป้าหมายหรือไม่
.
Step 2 — Data Collection crypto_arb.py (917 lines)
Binance Futures API ดึงข้อมูล real-time ใน 1 วินาที:
.
📡 6 Trading Signals (แต่ละตัวให้ค่า -1.0 ถึง +1.0):
| Signal      | Weight | ข้อมูล                                                           |
| ----------- | ------ | ---------------------------------------------------------------- |
| Momentum    | 40%    | ราคาย้อนหลัง 3 แท่งเทียน, 3 timeframes (1m 50%, 5m 35%, 15m 15%) |
| Taker Buy   | 20%    | สัดส่วนผู้ซื้อ vs ผู้ขาย จริง (>0.55 = buyers dominant)          |
| Order Book  | 15%    | bid/ask imbalance, depth-weighted, dampened สำหรับ spoofing      |
| Funding     | 10%    | อัตราค่า funding (ลบ = shorts จ่าย longs = bullish)              |
| Volume      | 10%    | Volume spike × momentum direction (confirmation)                 |
| Mean Revert | 5%     | RSI extremes — overbought/oversold contrarian                    |
Signal weights ปรับอัตโนมัติ โดย Research Loop ตามผลลัพธ์จริง
.
📊 7 Technical Indicators (แนบทุกตัวให้ AI เห็น):
RSI (5m+1m), Bollinger Band position+width, EMA 9/21 crossover, MACD histogram, ATR (volatility), VWAP deviation
.
🌊 Market Regime Detection:
• Trending: momentum > 0.3 + volume confirms → follow trend
• Ranging: momentum < 0.15 → cautious, small signals
• Volatile: ATR spike → skip if low confidence
.
🤖 Deep Dive (2/4) — AI Decision + RAG
.
━━━━━━━━━━━━━━━━━━━━━━
RAG CONTEXT SYSTEM rag_context.py (319 lines)
━━━━━━━━━━━━━━━━━━━━━━
.
ทุกครั้งที่ AI ตัดสินใจ จะ query SQLite สร้าง context ~4,000 ตัวอักษร ประกอบด้วย 10 sections:
.
1. Overall Performance
สถิติรวม: WR, P&L, avg win/loss
→ AI รู้ว่าตัวเองเก่งแค่ไหน
.
2. Last 20 Trades (with signals)
แต่ละ trade: WIN/LOSS, side, P&L, AI confidence, edge, และ signal values ที่ใช้ตอนเปิด
→ AI เห็น pattern ล่าสุด
.
3. Signal Reliability
จาก post-resolve analysis: signal ไหน correct/wrong กี่ครั้ง
เช่น "momentum: 65% reliable ✅, orderbook: 35% unreliable ❌"
→ AI รู้ว่าควรเชื่อ signal ไหน
.
4. Market Type Performance
Up/Down 15min: 102 trades, 46% WR, -$26 ❌
Price Level: 13 trades, 69% WR, +$29 ✅
→ AI รู้ว่าตลาดไหนถนัด
.
5. Direction Analysis
YES (BTC Up): 87 trades, 49% WR
NO (BTC Down): 28 trades, 46% WR
→ AI เห็น direction bias
.
6. AI Confidence Calibration ⚠️
Very High (≥60%): 43% actual WR ← overconfident!
High (55-60%): 48% actual WR
Medium (50-55%): 46% actual WR
Low (<50%): 58% actual WR ← undervalued!
→ AI รู้ว่ามั่นใจเยอะ ≠ ถูกเยอะ
.
7. Regime Performance
เช่น "ranging: 43% WR — ระวัง"
→ AI ปรับตาม market condition
.
8. Time-of-Day Patterns
🟢 10-11AM ET: 62-80% WR (best)
🔴 15-17 ET: 25% WR (worst)
→ AI รู้ว่าเวลาไหนไม่ควรเทรด
.
9. Streak Analysis
"Current: 4 WINs in a row"
"Pattern: WLLLWWLWLWLLLLWLWWWW"
→ AI เห็น momentum
.
10. Lessons from Recent Losses
AI วิเคราะห์ loss ย้อนหลัง → สรุปเป็นบทเรียน
→ ไม่ทำผิดซ้ำ
.
━━━━━━━━━━━━━━━━━━━━━━
AI DECISION ENGINE
━━━━━━━━━━━━━━━━━━━━━━
.
Model: Qwen 3.5 35B (23.9 GB, local on Ollama)
Mode: Thinking ON — AI คิดก่อนตอบ
Time: 6-10 วินาที/ตลาด
Timeout: 120 วินาที (safety)
.
Input ที่ AI ได้รับ:
System: "You are a BTC price predictor"
User:
├─ BTC price, hours left, market price
├─ 6 signal values + directions
├─ 7 indicator values
├─ Market regime
├─ Quant score + weighted score
├─ RAG context (10 sections, ~4K chars)
└─ "Output JSON: probability, confidence,
    reasoning, data_requests"
Output จาก AI:
{
  "probability_up": 0.58,
  "confidence": 0.72,
  "reasoning": "Strong bullish momentum and
    order book dominance in trending regime
    outweigh slightly overbought RSI",
  "data_requests": "real-time order book
    depth at key support/resistance levels"
}
data_requests = AI บอกเองว่าอยากได้ข้อมูลอะไรเพิ่ม
→ เก็บใน DB → Research loop วิเคราะห์ว่า AI ขออะไรบ่อย → เพิ่มให้ในอนาคต
.
🤖 Deep Dive (3/4) — Risk + Execution + Resolution
.
━━━━━━━━━━━━━━━━━━━━━━
RISK MANAGEMENT executor.py (284 lines)
━━━━━━━━━━━━━━━━━━━━━━
.
Kelly Criterion Bet Sizing:
kelly = (b × p - q) / b
  b = odds (1/price - 1)
  p = AI probability
  q = 1 - p
.
bet = kelly × 0.08 × confidence × balance
ตัวอย่าง: AI 58% UP, market 50%, balance $200
→ kelly = 0.16, × 0.08 × 0.72 × $200 = $1.84
.
Safety Gates (ทุกอันต้องผ่านก่อนเทรด):
• AI confidence ≥ 65%
• Edge ≥ 1% (data-driven) / ≤ 25%
• Max bet: $3/trade
• Min bet: $0.25
• Daily loss limit: $20
• Max concurrent bets: 50
• NO direction: confidence ≥ 75% (research-adjusted)
• Regime gate: volatile + low signal = skip
• ไม่ซ้ำ market ที่มี active bet อยู่
.
Circuit Breaker: ถ้า daily loss ≥ $20 → หยุดเทรดทั้งวัน
.
━━━━━━━━━━━━━━━━━━━━━━
EXECUTION executor.py
━━━━━━━━━━━━━━━━━━━━━━
.
• Polymarket CLOB API (on-chain orderbook)
• ใช้ proxy สำหรับ geo-restriction
• MarketOrderArgs: token_id, amount, side
• Order tracking: order_id → SQLite
• Stale order cleanup (ตรวจทุก cycle)
.
Data Stored Per Trade (35 columns):
── Identity ──
id, timestamp, market_id, question, created_at
.
── Trade ──
side (YES/NO), shares, price, bet_usd,
order_id, end_date, source
.
── AI Decision ──
ai_probability, confidence, edge_pct,
reasoning, ai_reasoning_full,
ai_data_requests, calibrated_prob
.
── Quant Data ──
signals_json (6 signals as JSON)
indicators_json (7 indicators as JSON)
quant_score, signal_weights_used
.
── Market State ──
market_price, regime, btc_price,
hourly_vol, daily_vol, funding_rate,
entry_time_et, rag_context_hash
.
── Outcome ──
resolved, outcome, pnl, resolve_analysis
━━━━━━━━━━━━━━━━━━━━━━
RESOLUTION resolver.py (229 lines)
━━━━━━━━━━━━━━━━━━━━━━
.
ทุก cycle ตรวจ:
.
1. ดึง resolved markets จาก Polymarket API
2. Match outcome กับ trade (UP/DOWN/YES/NO/OVER/UNDER)
3. คำนวณ P&L: win = shares - bet, loss = -bet
4. Post-Resolve AI Analysis (Qwen 35B):
Input: trade details + outcome
Output JSON:
{
  "correct_signals": ["momentum", "taker"],
  "wrong_signals": ["orderbook"],
  "key_factor": "momentum aligned with trend",
  "lesson": "orderbook was spoofed, ignore in ranging",
  "confidence_justified": false
}
→ เก็บใน resolve_analysis column
→ RAG + Research Loop อ่านค่านี้
.
━━━━━━━━━━━━━━━━━━━━━━
NOTIFICATIONS notifier.py (119 lines)
━━━━━━━━━━━━━━━━━━━━━━
.
Telegram bot ส่ง 8 ประเภท:
.
1. 🟢 Trade Executed (side, amount, AI prob)
2. ✅❌ Trade Resolved + P&L
3. 📊 Cycle Report (skip 1/3 ถ้าไม่มี trade)
4. 💰 Portfolio (ทุก 3 cycles)
5. 🚨 Circuit Breaker (daily loss hit)
6. ❗ Error alerts
7. 🗑️ Stale Orders Cancelled
8. 🚀 Startup notification
.
🤖 Deep Dive (4/4) — Learning + Fine-tune + Stats
.
━━━━━━━━━━━━━━━━━━━━━━
RESEARCH LOOP research_loop.py (674 lines)
━━━━━━━━━━━━━━━━━━━━━━
.
Trigger: ทุก 50 BTC resolved trades (อัตโนมัติ)
.
วิเคราะห์:
• Win rate by direction, market type, regime
• Confidence calibration accuracy
• Signal effectiveness (จาก resolve_analysis)
• YES/NO bias detection
.
Auto-adjust 4 อย่าง:
.
1️⃣ Lessons → AI Prompt
สร้างบทเรียนจากข้อมูลจริง inject เข้า Qwen prompt:
- Up/Down 15min WR only 46% — ต้องระวัง
- Price Level WR 69% — ทำนายง่ายกว่า
- High conf กลับแพ้ > Low conf — overconfident
- Overall WR 46% — ต้อง selective มากขึ้น
2️⃣ Signal Weights
วิเคราะห์ resolve_analysis → signal ไหน correct/wrong
→ reliable signal ↑ weight, unreliable ↓ weight
→ normalize sum = 1.0
.
3️⃣ Market Type Decision
ถ้า Up/Down WR < 42% (20+ trades) → auto-block
.
4️⃣ Trading Parameters
AI (Qwen 35B) วิเคราะห์ผลลัพธ์ → แนะนำ:
confidence_threshold, kelly_fraction, max_bet,
min_edge, no_confidence_min, ai_prob_min
→ sanity bounds → save to best_params.json
.
Output files:
• research_config.json — lessons, weights, types
• best_params.json — trading parameters
• research_results.tsv — experiment log
.
━━━━━━━━━━━━━━━━━━━━━━
ML CLASSIFIER ml_classifier.py (279 lines)
━━━━━━━━━━━━━━━━━━━━━━
.
GradientBoosting (sklearn) trained on trade features:
Feature Importance:
prob_price_diff  40.2%  ← ราคา AI vs Market
side             37.7%  ← YES or NO
ai_probability    7.4%
price             5.6%
market_price      4.7%
edge_pct          1.2%
confidence        0.7%
Model: data/training/xgboost_model.pkl (112KB)
⚠️ จะ retrain หลังข้อมูลมีคุณภาพมากขึ้น
.
━━━━━━━━━━━━━━━━━━━━━━
FINE-TUNE PIPELINE finetuner.py (288 lines)
━━━━━━━━━━━━━━━━━━━━━━
.
3-Level Plan:
.
Level 1: Research Loop ✅ Active
→ Auto-adjust params + signal weights ทุก 50 trades
.
Level 2: ML Classifier ✅ Built
→ GradientBoosting model, retrain ทุก 50 trades
.
Level 3: LoRA Fine-tune ⏳ 200+ trades
→ Qwen 3.5 9B fine-tune on Apple Silicon (MLX)
→ Training data: trade features + outcome
→ Adapters: data/training/adapters/
→ Re-trigger: ทุก 50 trades ใหม่
.
Future Ensemble Architecture:
Market → Qwen 9B (fine-tuned, 2 วิ)
         "เทรดไหม?" → YES/NO pre-filter
              │
              ▼ (ถ้า YES)
         Qwen 35B + RAG (8 วิ)
         "ทิศไหน? เท่าไหร่?"
              │
              ▼
         ถ้า 9B + 35B เห็นตรงกัน
         → confidence สูง → เทรด
         ถ้าขัดแย้ง → skip
━━━━━━━━━━━━━━━━━━━━━━
OTHER MODULES
━━━━━━━━━━━━━━━━━━━━━━
.
• calibrator.py (248 lines) — Bayesian calibration, edge multiplier, category blocking
• learner.py (153 lines) — Lesson extraction from trade history
• predictor.py (244 lines) — General prediction framework
• sports_arb.py (337 lines) — Sports arbitrage (disabled, BTC-only mode)
• order_monitor.py (88 lines) — Stale order detection/cleanup
• tracker.py (175 lines) — SQLite trade tracker (35 cols)
• config.py (51 lines) — .env loader
• main.py (552 lines) — Main loop orchestrator
.
━━━━━━━━━━━━━━━━━━━━━━
CURRENT PERFORMANCE
━━━━━━━━━━━━━━━━━━━━━━
Total:     128 BTC trades (13 active)
Resolved:  115 trades
Win Rate:  48.7% (56W / 59L)
P&L:       +$2.09
Gross Win: +$171.88 (avg $3.07/win)
Gross Loss:-$169.79 (avg -$2.88/loss)
Total Bet: $378.91
ROI:       0.6%
Predictions scanned: 11,290
By Market Type:
Up/Down 15min: 102t, 46% WR, -$26 ❌
Price Level: 13t, 69% WR, +$29 ✅