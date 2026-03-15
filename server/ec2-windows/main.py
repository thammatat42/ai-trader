from fastapi import FastAPI, Query
from pydantic import BaseModel
from datetime import datetime, timedelta, timezone
import MetaTrader5 as mt5

app = FastAPI(title="MT5 Bridge API")


# ==========================================
# MT5 CONNECTION
# ==========================================
def ensure_mt5_connected() -> bool:
    """เช็ค + reconnect MT5 อัตโนมัติ"""
    info = mt5.terminal_info()
    if info is not None:
        return True
    print("[WARN] MT5 disconnected - reconnecting...")
    return mt5.initialize()


@app.on_event("startup")
def start_mt5():
    if not mt5.initialize():
        print("[ERROR] MT5 initialization failed")
    else:
        print("[OK] Connected to MT5 successfully!")


# ==========================================
# MODELS
# ==========================================
class TradeRequest(BaseModel):
    action: str      # "BUY" or "SELL"
    symbol: str      # e.g. "XAUUSD"
    lot: float       # e.g. 0.03
    sl: float        # Stop Loss price (e.g. 5012.50)
    tp: float        # Take Profit price (e.g. 5024.50)


# ==========================================
# ENDPOINTS
# ==========================================
@app.get("/")
def read_root():
    connected = ensure_mt5_connected()
    return {
        "status": "MT5 Bridge API is running on Windows!",
        "mt5_connected": connected,
    }


@app.get("/price/{symbol}")
def get_price(symbol: str):
    if not ensure_mt5_connected():
        return {"error": "MT5 is not connected"}

    tick = mt5.symbol_info_tick(symbol)
    if tick is None:
        return {"error": f"Symbol {symbol} not found or MT5 disconnected."}

    return {
        "symbol": symbol,
        "bid": tick.bid,
        "ask": tick.ask,
        "time": tick.time,
    }


# ==========================================
# CANDLE DATA (OHLC)
# ==========================================
TIMEFRAME_MAP = {
    "M1":  mt5.TIMEFRAME_M1,
    "M5":  mt5.TIMEFRAME_M5,
    "M15": mt5.TIMEFRAME_M15,
    "M30": mt5.TIMEFRAME_M30,
    "H1":  mt5.TIMEFRAME_H1,
    "H4":  mt5.TIMEFRAME_H4,
    "D1":  mt5.TIMEFRAME_D1,
}


@app.get("/candles/{symbol}")
def get_candles(
    symbol: str,
    timeframe: str = Query(default="H1", regex="^(M1|M5|M15|M30|H1|H4|D1)$"),
    count: int = Query(default=50, ge=1, le=500),
):
    """
    ดึง OHLCV candle data จาก MT5
    - timeframe: M1, M5, M15, M30, H1, H4, D1
    - count: จำนวนแท่งเทียน (1-500)
    """
    if not ensure_mt5_connected():
        return {"error": "MT5 is not connected"}

    tf = TIMEFRAME_MAP.get(timeframe)
    if tf is None:
        return {"error": f"Invalid timeframe: {timeframe}"}

    rates = mt5.copy_rates_from_pos(symbol, tf, 0, count)
    if rates is None or len(rates) == 0:
        return {"error": f"No candle data for {symbol} {timeframe}"}

    candles = []
    for r in rates:
        candles.append({
            "time": int(r["time"]),
            "open": float(r["open"]),
            "high": float(r["high"]),
            "low": float(r["low"]),
            "close": float(r["close"]),
            "volume": int(r["tick_volume"]),
        })

    return {
        "symbol": symbol,
        "timeframe": timeframe,
        "count": len(candles),
        "candles": candles,
    }


# ==========================================
# ORDER BOOK / DEPTH OF MARKET
# ==========================================
@app.get("/orderbook/{symbol}")
def get_orderbook(symbol: str, depth: int = Query(default=10, ge=1, le=50)):
    """
    ดึง Depth of Market (DOM) จาก MT5
    ต้องเปิด Market Depth ใน MT5 ก่อนใช้งาน
    """
    if not ensure_mt5_connected():
        return {"error": "MT5 is not connected"}

    # เปิด Market Depth สำหรับ symbol นี้
    if not mt5.market_book_add(symbol):
        # บาง broker ไม่รองรับ DOM → ส่ง spread-based fallback
        tick = mt5.symbol_info_tick(symbol)
        if tick is None:
            return {"error": f"Symbol {symbol} not found"}
        return {
            "symbol": symbol,
            "dom_available": False,
            "spread": round(tick.ask - tick.bid, 2),
            "bid": tick.bid,
            "ask": tick.ask,
            "bids": [],
            "asks": [],
        }

    book = mt5.market_book_get(symbol)
    mt5.market_book_release(symbol)

    if book is None or len(book) == 0:
        return {"symbol": symbol, "dom_available": False, "bids": [], "asks": []}

    bids = []
    asks = []
    for item in book:
        entry = {"price": item.price, "volume": item.volume}
        if item.type == mt5.BOOK_TYPE_SELL:
            asks.append(entry)
        elif item.type == mt5.BOOK_TYPE_BUY:
            bids.append(entry)

    # เรียงลำดับ: bids สูง→ต่ำ, asks ต่ำ→สูง
    bids.sort(key=lambda x: x["price"], reverse=True)
    asks.sort(key=lambda x: x["price"])

    return {
        "symbol": symbol,
        "dom_available": True,
        "bids": bids[:depth],
        "asks": asks[:depth],
        "bid_total_vol": sum(b["volume"] for b in bids[:depth]),
        "ask_total_vol": sum(a["volume"] for a in asks[:depth]),
    }


@app.post("/trade")
def execute_trade(req: TradeRequest):
    """
    รับคำสั่ง BUY/SELL จาก Linux AI Trader แล้วส่งเข้า MT5
    """
    if not ensure_mt5_connected():
        return {"error": "MT5 is not connected", "success": False}

    # ตรวจสอบว่า symbol พร้อมเทรดหรือไม่
    symbol_info = mt5.symbol_info(req.symbol)
    if symbol_info is None:
        return {"error": f"Symbol {req.symbol} not found", "success": False}
    if not symbol_info.visible:
        mt5.symbol_select(req.symbol, True)

    # กำหนด order type
    if req.action.upper() == "BUY":
        order_type = mt5.ORDER_TYPE_BUY
        price = mt5.symbol_info_tick(req.symbol).ask
    elif req.action.upper() == "SELL":
        order_type = mt5.ORDER_TYPE_SELL
        price = mt5.symbol_info_tick(req.symbol).bid
    else:
        return {"error": f"Invalid action: {req.action}. Use BUY or SELL.", "success": False}

    # สร้าง order request
    trade_request = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": req.symbol,
        "volume": req.lot,
        "type": order_type,
        "price": price,
        "sl": req.sl,
        "tp": req.tp,
        "deviation": 20,        # max slippage in points
        "magic": 888888,        # EA magic number (ใช้ระบุว่า order มาจาก AI Bot)
        "comment": "AI Trader",
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_IOC,
    }

    # ส่งคำสั่ง
    result = mt5.order_send(trade_request)

    if result is None:
        return {"error": "order_send returned None", "success": False}

    if result.retcode != mt5.TRADE_RETCODE_DONE:
        return {
            "error": f"Trade failed: {result.comment}",
            "retcode": result.retcode,
            "success": False,
        }

    return {
        "success": True,
        "order_id": result.order,
        "action": req.action,
        "symbol": req.symbol,
        "lot": req.lot,
        "price": result.price,
        "sl": req.sl,
        "tp": req.tp,
    }


# ==========================================
# OPEN POSITIONS
# ==========================================
@app.get("/positions")
def get_positions():
    """
    ดึง Open Positions ทั้งหมด (เฉพาะ magic=888888 ของ AI Bot)
    """
    if not ensure_mt5_connected():
        return {"error": "MT5 is not connected", "positions": []}

    positions = mt5.positions_get()
    if positions is None:
        return {"positions": []}

    result = []
    for p in positions:
        if p.magic != 888888:
            continue
        result.append({
            "ticket": p.ticket,
            "symbol": p.symbol,
            "type": "BUY" if p.type == mt5.ORDER_TYPE_BUY else "SELL",
            "lot": p.volume,
            "open_price": p.price_open,
            "current_price": p.price_current,
            "sl": p.sl,
            "tp": p.tp,
            "profit": p.profit,
            "swap": p.swap,
            "time": p.time,
        })

    return {"positions": result, "count": len(result)}


# ==========================================
# TRADE HISTORY (Closed deals)
# ==========================================
@app.get("/history")
def get_history(days: int = Query(default=7, ge=1, le=90)):
    """
    ดึง Trade History ย้อนหลัง (เฉพาะ magic=888888 ของ AI Bot)
    ส่งทั้ง entry deals (เปิด) และ exit deals (ปิด)
    """
    if not ensure_mt5_connected():
        return {"error": "MT5 is not connected", "deals": []}

    now = datetime.now(timezone.utc)
    from_date = now - timedelta(days=days)

    deals = mt5.history_deals_get(from_date, now)
    if deals is None:
        return {"deals": []}

    result = []
    for d in deals:
        if d.magic != 888888:
            continue
        # Include both IN (open) and OUT (close) deals
        entry_type = "IN" if d.entry == mt5.DEAL_ENTRY_IN else (
            "OUT" if d.entry == mt5.DEAL_ENTRY_OUT else "INOUT"
        )
        if d.entry not in (mt5.DEAL_ENTRY_IN, mt5.DEAL_ENTRY_OUT, mt5.DEAL_ENTRY_INOUT):
            continue
        result.append({
            "ticket": d.ticket,
            "order": d.order,
            "symbol": d.symbol,
            "type": "BUY" if d.type == mt5.DEAL_TYPE_BUY else "SELL",
            "entry": entry_type,
            "lot": d.volume,
            "price": d.price,
            "profit": d.profit,
            "swap": d.swap,
            "commission": d.commission,
            "time": d.time,
            "comment": d.comment,
        })

    return {"deals": result, "count": len(result)}


# ==========================================
# ACCOUNT INFO
# ==========================================
@app.get("/account")
def get_account():
    """ดึงข้อมูลบัญชี MT5"""
    if not ensure_mt5_connected():
        return {"error": "MT5 is not connected"}

    info = mt5.account_info()
    if info is None:
        return {"error": "Cannot get account info"}

    return {
        "balance": info.balance,
        "equity": info.equity,
        "margin": info.margin,
        "free_margin": info.margin_free,
        "profit": info.profit,
        "leverage": info.leverage,
        "currency": info.currency,
    }