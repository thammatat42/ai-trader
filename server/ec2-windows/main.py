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
        if d.entry == mt5.DEAL_ENTRY_OUT or d.entry == mt5.DEAL_ENTRY_INOUT:
            result.append({
                "ticket": d.ticket,
                "order": d.order,
                "symbol": d.symbol,
                "type": "BUY" if d.type == mt5.DEAL_TYPE_BUY else "SELL",
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