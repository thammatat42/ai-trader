#!/usr/bin/env python3
"""
Trade Data Analysis Script
===========================
Run on the Ubuntu server where Docker is running:
  python3 analyze_trades.py

Or connect remotely by setting env vars:
  DB_HOST=<server-ip> DB_USER=admin DB_PASS=<password> DB_NAME=trading_log python3 analyze_trades.py
"""
import os
import sys
from datetime import datetime, timezone, timedelta

try:
    import psycopg2
    import psycopg2.extras
except ImportError:
    print("Installing psycopg2-binary...")
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "psycopg2-binary"])
    import psycopg2
    import psycopg2.extras


def get_conn():
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "localhost"),
        user=os.getenv("DB_USER", "admin"),
        password=os.getenv("DB_PASS", "secretpassword"),
        dbname=os.getenv("DB_NAME", "trading_log"),
        port=int(os.getenv("DB_PORT", 5432)),
    )


def query(sql, params=None):
    conn = get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute(sql, params or ())
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return rows


def query_one(sql, params=None):
    rows = query(sql, params)
    return rows[0] if rows else None


def hr(title=""):
    print(f"\n{'='*70}")
    if title:
        print(f"  {title}")
        print(f"{'='*70}")


def main():
    print("Trade Data Analysis Report")
    print(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    # ===========================================
    # 1. OVERVIEW
    # ===========================================
    hr("1. DATABASE OVERVIEW")

    counts = query_one("""
        SELECT
            (SELECT count(*) FROM trades) as total_trades,
            (SELECT count(*) FROM trades WHERE status='OPEN') as open_trades,
            (SELECT count(*) FROM trades WHERE status='CLOSED') as closed_trades,
            (SELECT count(*) FROM ai_analysis_log) as total_logs,
            (SELECT count(*) FROM bot_events) as total_events,
            (SELECT count(*) FROM api_usage_log) as total_api_calls
    """)
    if not counts:
        print("ERROR: Cannot query database. Check connection.")
        return

    print(f"  Trades:         {counts['total_trades']} (Open: {counts['open_trades']}, Closed: {counts['closed_trades']})")
    print(f"  AI Analysis:    {counts['total_logs']}")
    print(f"  Bot Events:     {counts['total_events']}")
    print(f"  API Calls:      {counts['total_api_calls']}")

    # ===========================================
    # 2. ALL TRADES (Detail)
    # ===========================================
    hr("2. ALL TRADES (ordered by time)")

    trades = query("""
        SELECT id, order_id, symbol, action, lot, open_price, close_price,
               sl_price, tp_price, profit, status, opened_at, closed_at
        FROM trades
        ORDER BY opened_at DESC
    """)

    if not trades:
        print("  No trades found.")
    else:
        for t in trades:
            duration = ""
            if t['opened_at'] and t['closed_at']:
                delta = t['closed_at'] - t['opened_at']
                mins = delta.total_seconds() / 60
                duration = f" ({mins:.1f}min)"
            result_emoji = ""
            if t['profit'] is not None:
                result_emoji = "WIN" if float(t['profit']) > 0 else "LOSS" if float(t['profit']) < 0 else "BREAK-EVEN"

            print(f"  #{t['order_id']} | {t['action']:4s} | Lot={t['lot']} | "
                  f"Open={t['open_price']} Close={t['close_price']} | "
                  f"SL={t['sl_price']} TP={t['tp_price']} | "
                  f"P/L=${float(t['profit'] or 0):.2f} [{result_emoji}] | "
                  f"{t['status']}{duration} | {t['opened_at']}")

    # ===========================================
    # 3. PROFIT/LOSS ANALYSIS
    # ===========================================
    hr("3. PROFIT/LOSS ANALYSIS")

    pnl = query_one("""
        SELECT
            count(*) as total,
            count(*) FILTER (WHERE profit > 0) as wins,
            count(*) FILTER (WHERE profit < 0) as losses,
            count(*) FILTER (WHERE profit = 0) as breakeven,
            COALESCE(SUM(profit), 0) as total_profit,
            COALESCE(AVG(profit), 0) as avg_profit,
            COALESCE(MAX(profit), 0) as best_trade,
            COALESCE(MIN(profit), 0) as worst_trade,
            COALESCE(AVG(CASE WHEN profit > 0 THEN profit END), 0) as avg_win,
            COALESCE(AVG(CASE WHEN profit < 0 THEN profit END), 0) as avg_loss,
            COALESCE(SUM(CASE WHEN profit > 0 THEN profit ELSE 0 END), 0) as gross_profit,
            COALESCE(SUM(CASE WHEN profit < 0 THEN profit ELSE 0 END), 0) as gross_loss
        FROM trades
        WHERE status = 'CLOSED'
    """)

    if pnl and pnl['total'] > 0:
        wr = round(pnl['wins'] / pnl['total'] * 100, 1) if pnl['total'] > 0 else 0
        profit_factor = abs(float(pnl['gross_profit']) / float(pnl['gross_loss'])) if float(pnl['gross_loss']) != 0 else float('inf')
        rr_ratio = abs(float(pnl['avg_win']) / float(pnl['avg_loss'])) if float(pnl['avg_loss']) != 0 else 0

        print(f"  Total Closed:     {pnl['total']}")
        print(f"  Wins / Losses:    {pnl['wins']}W / {pnl['losses']}L / {pnl['breakeven']}BE")
        print(f"  Win Rate:         {wr}%")
        print(f"  Net P/L:          ${float(pnl['total_profit']):,.2f}")
        print(f"  Avg P/L per trade:${float(pnl['avg_profit']):,.2f}")
        print(f"  Best Trade:       ${float(pnl['best_trade']):,.2f}")
        print(f"  Worst Trade:      ${float(pnl['worst_trade']):,.2f}")
        print(f"  Avg Win:          ${float(pnl['avg_win']):,.2f}")
        print(f"  Avg Loss:         ${float(pnl['avg_loss']):,.2f}")
        print(f"  Risk/Reward:      1:{rr_ratio:.2f}")
        print(f"  Profit Factor:    {profit_factor:.2f}")
        print(f"  Gross Profit:     ${float(pnl['gross_profit']):,.2f}")
        print(f"  Gross Loss:       ${float(pnl['gross_loss']):,.2f}")
    else:
        print("  No closed trades to analyze.")

    # ===========================================
    # 4. TRADE DURATION ANALYSIS
    # ===========================================
    hr("4. TRADE DURATION ANALYSIS")

    durations = query("""
        SELECT action, profit,
               EXTRACT(EPOCH FROM (closed_at - opened_at)) as duration_sec,
               opened_at, closed_at
        FROM trades
        WHERE status = 'CLOSED' AND closed_at IS NOT NULL AND opened_at IS NOT NULL
        ORDER BY closed_at DESC
    """)

    if durations:
        win_durations = [d['duration_sec'] for d in durations if float(d['profit'] or 0) > 0]
        loss_durations = [d['duration_sec'] for d in durations if float(d['profit'] or 0) < 0]

        very_short = [d for d in durations if d['duration_sec'] and d['duration_sec'] < 60]
        short = [d for d in durations if d['duration_sec'] and 60 <= d['duration_sec'] < 300]
        medium = [d for d in durations if d['duration_sec'] and 300 <= d['duration_sec'] < 600]
        long = [d for d in durations if d['duration_sec'] and d['duration_sec'] >= 600]

        print(f"  < 1 min:     {len(very_short)} trades")
        print(f"  1-5 min:     {len(short)} trades")
        print(f"  5-10 min:    {len(medium)} trades")
        print(f"  > 10 min:    {len(long)} trades")

        if win_durations:
            print(f"  Avg Win Duration:  {sum(win_durations)/len(win_durations)/60:.1f} min")
        if loss_durations:
            print(f"  Avg Loss Duration: {sum(loss_durations)/len(loss_durations)/60:.1f} min")

        # Flag: very short trades that lost money
        quick_losses = [d for d in very_short if float(d['profit'] or 0) < 0]
        if quick_losses:
            print(f"\n  ⚠️  ISSUE: {len(quick_losses)} trades closed < 1 min with losses (likely hit SL immediately)")
    else:
        print("  No closed trades with duration data.")

    # ===========================================
    # 5. SL/TP HIT ANALYSIS
    # ===========================================
    hr("5. SL/TP HIT PATTERN ANALYSIS")

    sl_tp_data = query("""
        SELECT action, open_price, close_price, sl_price, tp_price, profit,
               lot, opened_at
        FROM trades
        WHERE status = 'CLOSED' AND close_price IS NOT NULL
        ORDER BY opened_at DESC
    """)

    if sl_tp_data:
        sl_hits = 0
        tp_hits = 0
        smart_closes = 0
        for t in sl_tp_data:
            op = float(t['open_price'] or 0)
            cp = float(t['close_price'] or 0)
            sl = float(t['sl_price'] or 0)
            tp = float(t['tp_price'] or 0)

            # Check if close was near SL or TP (within 1.0 tolerance for gold)
            if sl and abs(cp - sl) < 1.0:
                sl_hits += 1
            elif tp and abs(cp - tp) < 1.0:
                tp_hits += 1
            else:
                smart_closes += 1

        print(f"  TP Hit (target reached): {tp_hits}")
        print(f"  SL Hit (stopped out):    {sl_hits}")
        print(f"  Smart/Manual Close:      {smart_closes}")

        if sl_hits > tp_hits and (sl_hits + tp_hits) > 0:
            print(f"\n  ⚠️  ISSUE: SL hits ({sl_hits}) > TP hits ({tp_hits}) → SL may be too tight or entries poorly timed")

    # ===========================================
    # 6. CONSECUTIVE STREAK ANALYSIS
    # ===========================================
    hr("6. CONSECUTIVE WIN/LOSS STREAKS")

    streak_data = query("""
        SELECT profit, opened_at
        FROM trades
        WHERE status = 'CLOSED'
        ORDER BY opened_at ASC
    """)

    if streak_data:
        max_win_streak = 0
        max_loss_streak = 0
        cur_streak = 0
        cur_type = None
        for t in streak_data:
            p = float(t['profit'] or 0)
            if p > 0:
                if cur_type == 'win':
                    cur_streak += 1
                else:
                    cur_streak = 1
                    cur_type = 'win'
                max_win_streak = max(max_win_streak, cur_streak)
            elif p < 0:
                if cur_type == 'loss':
                    cur_streak += 1
                else:
                    cur_streak = 1
                    cur_type = 'loss'
                max_loss_streak = max(max_loss_streak, cur_streak)

        print(f"  Max Win Streak:  {max_win_streak}")
        print(f"  Max Loss Streak: {max_loss_streak}")
        if max_loss_streak >= 3:
            print(f"  ⚠️  ISSUE: {max_loss_streak} consecutive losses detected → need better entry logic or pause after losses")

    # ===========================================
    # 7. AI DECISION ANALYSIS
    # ===========================================
    hr("7. AI DECISION ANALYSIS")

    ai_stats = query("""
        SELECT trade_action, count(*) as cnt
        FROM ai_analysis_log
        GROUP BY trade_action
        ORDER BY cnt DESC
    """)

    if ai_stats:
        total_decisions = sum(a['cnt'] for a in ai_stats)
        for a in ai_stats:
            pct = round(a['cnt'] / total_decisions * 100, 1)
            print(f"  {a['trade_action']:6s}: {a['cnt']:4d} ({pct}%)")

        # Check WAIT ratio
        wait_count = sum(a['cnt'] for a in ai_stats if a['trade_action'] == 'WAIT')
        wait_pct = round(wait_count / total_decisions * 100, 1) if total_decisions > 0 else 0
        if wait_pct > 80:
            print(f"\n  ⚠️  ISSUE: {wait_pct}% of decisions are WAIT → AI may be too conservative")
        elif wait_pct < 30:
            print(f"\n  ⚠️  ISSUE: Only {wait_pct}% WAIT → AI may be overtrading")

    # ===========================================
    # 8. AI CONFIDENCE DISTRIBUTION
    # ===========================================
    hr("8. AI CONFIDENCE vs TRADE RESULTS")

    # Extract confidence from AI recommendations
    conf_trades = query("""
        SELECT l.trade_action, l.ai_recommendation, l.bid, l.ask, l.created_at,
               t.profit, t.status
        FROM ai_analysis_log l
        LEFT JOIN trades t ON t.opened_at >= l.created_at - interval '5 seconds'
                           AND t.opened_at <= l.created_at + interval '60 seconds'
                           AND t.action = l.trade_action
        WHERE l.trade_action IN ('BUY', 'SELL')
        ORDER BY l.created_at DESC
    """)

    if conf_trades:
        import re
        conf_outcomes = []  # (confidence, profit)
        for row in conf_trades:
            ai_text = (row['ai_recommendation'] or "").lower()
            m = re.search(r'confidence[:\s]*([0-9]{1,2})', ai_text)
            if m:
                conf = int(m.group(1))
                profit = float(row['profit']) if row['profit'] is not None else None
                conf_outcomes.append((conf, profit, row['trade_action'], row['created_at']))

        if conf_outcomes:
            print(f"  Total BUY/SELL decisions with confidence: {len(conf_outcomes)}")
            # Group by confidence level
            for c_level in range(5, 11):
                trades_at = [(p, a) for (c, p, a, _) in conf_outcomes if c == c_level and p is not None]
                if trades_at:
                    wins_c = sum(1 for (p, _) in trades_at if p > 0)
                    wr_c = round(wins_c / len(trades_at) * 100, 1)
                    avg_p = sum(p for (p, _) in trades_at) / len(trades_at)
                    print(f"  Conf={c_level}: {len(trades_at)} trades, WR={wr_c}%, AvgP/L=${avg_p:.2f}")

            # Low confidence trades that were executed
            low_conf_executed = [(c, p) for (c, p, _, _) in conf_outcomes if c <= 5 and p is not None]
            if low_conf_executed:
                losses_low = sum(1 for (_, p) in low_conf_executed if p < 0)
                print(f"\n  ⚠️  ISSUE: {len(low_conf_executed)} trades executed at confidence ≤ 5, {losses_low} were losses")

    # ===========================================
    # 9. SPREAD AT ENTRY
    # ===========================================
    hr("9. SPREAD ANALYSIS AT ENTRY TIME")

    spread_data = query("""
        SELECT trade_action, bid, ask, (ask - bid) as spread, created_at,
               ai_recommendation
        FROM ai_analysis_log
        WHERE trade_action IN ('BUY', 'SELL')
        ORDER BY created_at DESC
    """)

    if spread_data:
        spreads = [float(s['spread'] or 0) for s in spread_data if s['spread']]
        if spreads:
            avg_spread = sum(spreads) / len(spreads)
            max_spread = max(spreads)
            min_spread = min(spreads)
            high_spread = [s for s in spreads if s > 3.0]
            print(f"  Avg Spread at entry:  {avg_spread:.2f}")
            print(f"  Min/Max Spread:       {min_spread:.2f} / {max_spread:.2f}")
            if high_spread:
                print(f"  ⚠️  ISSUE: {len(high_spread)} trades entered with spread > 3.0 (bad fills)")

    # ===========================================
    # 10. BOT EVENTS (Errors & Issues)
    # ===========================================
    hr("10. BOT EVENTS SUMMARY")

    events_by_type = query("""
        SELECT event_type, count(*) as cnt,
               max(created_at) as last_seen
        FROM bot_events
        GROUP BY event_type
        ORDER BY cnt DESC
    """)

    if events_by_type:
        for e in events_by_type:
            print(f"  {e['event_type']:20s}: {e['cnt']:4d} (last: {e['last_seen']})")

    # Recent errors
    recent_errors = query("""
        SELECT event_type, message, created_at
        FROM bot_events
        WHERE event_type IN ('ERROR', 'KILL_SWITCH', 'SHUTDOWN')
        ORDER BY created_at DESC
        LIMIT 20
    """)

    if recent_errors:
        print(f"\n  Recent Errors/Shutdowns:")
        for e in recent_errors:
            msg = (e['message'] or "")[:120]
            print(f"    [{e['created_at']}] {e['event_type']}: {msg}")

    # ===========================================
    # 11. API PERFORMANCE
    # ===========================================
    hr("11. API PERFORMANCE")

    api_stats = query("""
        SELECT provider, model, status,
               count(*) as calls,
               round(avg(response_time_ms)) as avg_ms,
               max(response_time_ms) as max_ms,
               sum(total_tokens) as total_tokens,
               round(avg(total_tokens)) as avg_tokens
        FROM api_usage_log
        GROUP BY provider, model, status
        ORDER BY calls DESC
    """)

    if api_stats:
        for a in api_stats:
            print(f"  {a['provider']}/{a['model']} [{a['status']}]: "
                  f"{a['calls']} calls, avg={a['avg_ms']}ms, max={a['max_ms']}ms, "
                  f"tokens={a['total_tokens']}")

        # Check slow API calls
        slow_calls = query_one("""
            SELECT count(*) as cnt
            FROM api_usage_log
            WHERE response_time_ms > 10000
        """)
        if slow_calls and slow_calls['cnt'] > 0:
            print(f"\n  ⚠️  ISSUE: {slow_calls['cnt']} API calls took > 10 seconds")

        error_calls = query_one("""
            SELECT count(*) as cnt
            FROM api_usage_log
            WHERE status = 'ERROR'
        """)
        if error_calls and error_calls['cnt'] > 0:
            total_calls = sum(a['calls'] for a in api_stats)
            err_pct = round(error_calls['cnt'] / total_calls * 100, 1) if total_calls > 0 else 0
            print(f"  ⚠️  ISSUE: {error_calls['cnt']} API errors ({err_pct}% failure rate)")

    # ===========================================
    # 12. DAILY P/L BREAKDOWN
    # ===========================================
    hr("12. DAILY P/L BREAKDOWN")

    daily = query("""
        SELECT DATE(closed_at) as day,
               count(*) as trades,
               count(*) FILTER (WHERE profit > 0) as wins,
               count(*) FILTER (WHERE profit < 0) as losses,
               COALESCE(SUM(profit), 0) as pnl,
               round(COALESCE(AVG(profit), 0)::numeric, 2) as avg_pnl
        FROM trades
        WHERE status = 'CLOSED' AND closed_at IS NOT NULL
        GROUP BY DATE(closed_at)
        ORDER BY day DESC
        LIMIT 30
    """)

    if daily:
        losing_days = 0
        for d in daily:
            wr = round(d['wins'] / d['trades'] * 100) if d['trades'] > 0 else 0
            emoji = "+" if float(d['pnl']) > 0 else "-" if float(d['pnl']) < 0 else " "
            print(f"  {d['day']} | {d['trades']:2d} trades | {d['wins']}W/{d['losses']}L ({wr}%) | "
                  f"P/L: {emoji}${abs(float(d['pnl'])):,.2f} | Avg: ${float(d['avg_pnl']):,.2f}")
            if float(d['pnl']) < 0:
                losing_days += 1

        if daily and losing_days > len(daily) * 0.6:
            print(f"\n  ⚠️  ISSUE: {losing_days}/{len(daily)} days are losing days ({round(losing_days/len(daily)*100)}%)")

    # ===========================================
    # 13. BUY vs SELL PERFORMANCE
    # ===========================================
    hr("13. BUY vs SELL PERFORMANCE")

    by_action = query("""
        SELECT action,
               count(*) as total,
               count(*) FILTER (WHERE profit > 0) as wins,
               count(*) FILTER (WHERE profit < 0) as losses,
               COALESCE(SUM(profit), 0) as pnl,
               COALESCE(AVG(profit), 0) as avg_pnl
        FROM trades
        WHERE status = 'CLOSED'
        GROUP BY action
    """)

    if by_action:
        for a in by_action:
            wr = round(a['wins'] / a['total'] * 100, 1) if a['total'] > 0 else 0
            print(f"  {a['action']:4s}: {a['total']} trades, {a['wins']}W/{a['losses']}L ({wr}%), "
                  f"P/L=${float(a['pnl']):,.2f}, Avg=${float(a['avg_pnl']):,.2f}")

        # Flag directional bias issues
        for a in by_action:
            wr = round(a['wins'] / a['total'] * 100, 1) if a['total'] > 0 else 0
            if a['total'] >= 3 and wr < 30:
                print(f"\n  ⚠️  ISSUE: {a['action']} win rate only {wr}% → consider disabling {a['action']} or improving entry conditions")

    # ===========================================
    # 14. TIME-OF-DAY ANALYSIS
    # ===========================================
    hr("14. TIME-OF-DAY PERFORMANCE (UTC)")

    hourly = query("""
        SELECT EXTRACT(HOUR FROM opened_at)::int as hour,
               count(*) as total,
               count(*) FILTER (WHERE profit > 0) as wins,
               COALESCE(SUM(profit), 0) as pnl
        FROM trades
        WHERE status = 'CLOSED'
        GROUP BY EXTRACT(HOUR FROM opened_at)::int
        ORDER BY hour
    """)

    if hourly:
        bad_hours = []
        for h in hourly:
            wr = round(h['wins'] / h['total'] * 100) if h['total'] > 0 else 0
            emoji = "+" if float(h['pnl']) > 0 else "-"
            bar = "█" * min(h['total'], 20)
            print(f"  {h['hour']:02d}:00 | {h['total']:3d} trades | WR={wr:3d}% | "
                  f"{emoji}${abs(float(h['pnl'])):>8,.2f} | {bar}")
            if h['total'] >= 3 and wr < 30:
                bad_hours.append(h['hour'])

        if bad_hours:
            print(f"\n  ⚠️  ISSUE: Poor performance at hours: {bad_hours} UTC → consider time filters")

    # ===========================================
    # 15. SMART CLOSE ANALYSIS
    # ===========================================
    hr("15. SMART POSITION MANAGER EVENTS")

    smart_events = query("""
        SELECT event_type, count(*) as cnt,
               COALESCE(SUM(
                   CASE WHEN message ~ 'profit=\$([0-9.-]+)' 
                   THEN CAST(substring(message FROM 'profit=\$([0-9.-]+)') AS numeric)
                   ELSE 0 END
               ), 0) as total_profit
        FROM bot_events
        WHERE event_type IN ('SMART_CLOSE', 'PROFIT_LOCK', 'BREAKEVEN', 'TRAILING_STOP')
        GROUP BY event_type
        ORDER BY cnt DESC
    """)

    if smart_events:
        for s in smart_events:
            print(f"  {s['event_type']:15s}: {s['cnt']} events, ~${float(s['total_profit']):,.2f}")
    else:
        print("  No smart position manager events found.")

    # ===========================================
    # 16. RECENT AI RECOMMENDATIONS (last 20)
    # ===========================================
    hr("16. RECENT AI RECOMMENDATIONS (last 20)")

    recent_ai = query("""
        SELECT id, symbol, bid, ask, trade_action, lot_size,
               sl_price, tp_price, created_at,
               LEFT(ai_recommendation, 200) as ai_short
        FROM ai_analysis_log
        ORDER BY created_at DESC
        LIMIT 20
    """)

    if recent_ai:
        for r in recent_ai:
            spread = float(r['ask'] or 0) - float(r['bid'] or 0)
            print(f"  [{r['created_at']}] {r['trade_action']:4s} | "
                  f"Bid={r['bid']} Ask={r['ask']} Spread={spread:.2f} | "
                  f"Lot={r['lot_size']} SL={r['sl_price']} TP={r['tp_price']}")
            # Show first line of AI reason
            ai_text = r['ai_short'] or ""
            for line in ai_text.split('\n'):
                if 'reason' in line.lower() or 'sentiment' in line.lower():
                    print(f"         {line.strip()}")

    # ===========================================
    # SUMMARY OF ISSUES FOUND
    # ===========================================
    hr("ISSUES SUMMARY & RECOMMENDATIONS")

    issues = []

    # Issue detection based on data
    if pnl and pnl['total'] > 0:
        wr = round(pnl['wins'] / pnl['total'] * 100, 1)
        if wr < 40:
            issues.append(f"[CRITICAL] Win rate is {wr}% (should be >45%) → AI entry signals need improvement")

        avg_win = abs(float(pnl['avg_win'])) if pnl['avg_win'] else 0
        avg_loss = abs(float(pnl['avg_loss'])) if pnl['avg_loss'] else 0
        if avg_loss > 0 and avg_win / avg_loss < 1.2:
            issues.append(f"[CRITICAL] Risk/Reward ratio {avg_win/avg_loss:.2f} is poor → TP is too tight or SL too wide")

        if float(pnl['total_profit']) < 0:
            issues.append(f"[CRITICAL] Overall P/L is negative: ${float(pnl['total_profit']):,.2f}")

    # Check SL vs TP hit ratio
    if sl_tp_data:
        sl_h = sum(1 for t in sl_tp_data if t['close_price'] and t['sl_price'] and abs(float(t['close_price']) - float(t['sl_price'])) < 1.0)
        tp_h = sum(1 for t in sl_tp_data if t['close_price'] and t['tp_price'] and abs(float(t['close_price']) - float(t['tp_price'])) < 1.0)
        if sl_h > tp_h * 1.5 and (sl_h + tp_h) > 3:
            issues.append(f"[HIGH] SL hit {sl_h}x vs TP hit {tp_h}x → SL too tight or entry timing off")

    # Check AI WAIT ratio
    if ai_stats:
        total_d = sum(a['cnt'] for a in ai_stats)
        wait_d = sum(a['cnt'] for a in ai_stats if a['trade_action'] == 'WAIT')
        wait_pct_d = round(wait_d / total_d * 100, 1) if total_d > 0 else 0
        if wait_pct_d > 80:
            issues.append(f"[HIGH] AI outputs WAIT {wait_pct_d}% of the time → prompt may be too restrictive")
        elif wait_pct_d < 30:
            issues.append(f"[MEDIUM] AI only WAITs {wait_pct_d}% → may be overtrading")

    # Check for duration issues
    if durations:
        very_short_losses = [d for d in durations if d['duration_sec'] and d['duration_sec'] < 60 and float(d['profit'] or 0) < 0]
        if len(very_short_losses) >= 3:
            issues.append(f"[HIGH] {len(very_short_losses)} trades lost money within 1 minute → likely bad entries hitting SL immediately")

    # Check for losing streaks
    if streak_data:
        if max_loss_streak >= 4:
            issues.append(f"[HIGH] Max loss streak of {max_loss_streak} → need pause-after-loss logic")

    # Check API errors
    if api_stats:
        err_count = sum(a['calls'] for a in api_stats if a['status'] == 'ERROR')
        total_api = sum(a['calls'] for a in api_stats)
        if err_count > 0 and total_api > 0:
            err_pct_api = round(err_count / total_api * 100, 1)
            if err_pct_api > 5:
                issues.append(f"[MEDIUM] API error rate {err_pct_api}% ({err_count}/{total_api}) → reliability concern")

    # Check directional bias
    if by_action:
        for a in by_action:
            if a['total'] >= 5:
                wr_a = round(a['wins'] / a['total'] * 100, 1)
                if wr_a < 30:
                    issues.append(f"[HIGH] {a['action']} direction has only {wr_a}% win rate → may need to avoid or improve")

    if not issues:
        print("  ✅ No critical issues detected from available data.")
    else:
        for i, issue in enumerate(issues, 1):
            print(f"  {i}. {issue}")

    print(f"\n{'='*70}")
    print("  End of Analysis Report")
    print(f"{'='*70}")


if __name__ == "__main__":
    try:
        main()
    except psycopg2.OperationalError as e:
        print(f"ERROR: Cannot connect to database: {e}")
        print("\nMake sure to set connection params:")
        print("  DB_HOST=localhost DB_USER=admin DB_PASS=<password> DB_NAME=trading_log python3 analyze_trades.py")
    except Exception as e:
        print(f"ERROR: {e}")
        import traceback
        traceback.print_exc()
