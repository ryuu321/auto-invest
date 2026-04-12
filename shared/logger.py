"""
ログ・学習データ管理モジュール
SQLite保存 + 人間が読めるテキストログも出力する
"""

import sqlite3
import json
from datetime import datetime, timezone
from pathlib import Path

DB_PATH   = Path(__file__).parent.parent / "data" / "trades.db"
LOG_PATH  = Path(__file__).parent.parent / "data" / "trades.log"


def init_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            action TEXT NOT NULL,
            coin TEXT NOT NULL,
            price REAL,
            amount REAL,
            value_usd REAL,
            balance_after REAL,
            pnl REAL,
            reasoning TEXT,
            confidence REAL,
            risk_level TEXT,
            bot_type TEXT DEFAULT 'SHORT',
            signals_json TEXT
        )
    """)
    # 既存DBに不足カラムがあれば追加
    for col, definition in [
        ("bot_type",     "TEXT DEFAULT 'SHORT'"),
        ("signals_json", "TEXT"),
    ]:
        try:
            cur.execute(f"ALTER TABLE trades ADD COLUMN {col} {definition}")
        except Exception:
            pass
    cur.execute("""
        CREATE TABLE IF NOT EXISTS market_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            coin TEXT NOT NULL,
            price REAL,
            rsi REAL,
            macd REAL,
            fear_greed_value INTEGER,
            fear_greed_label TEXT,
            raw_data TEXT
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS rule_performance (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            rule_name TEXT NOT NULL,
            signal TEXT NOT NULL,
            fired_at TEXT NOT NULL,
            trade_action TEXT,
            pnl REAL DEFAULT 0,
            was_correct INTEGER DEFAULT 0
        )
    """)
    conn.commit()
    conn.close()


class _SafeEncoder(json.JSONEncoder):
    """numpy/pandas の bool・数値型もシリアライズできるエンコーダー"""
    def default(self, obj):
        import numpy as np
        if isinstance(obj, (np.bool_,)):
            return bool(obj)
        if isinstance(obj, (np.integer,)):
            return int(obj)
        if isinstance(obj, (np.floating,)):
            return float(obj)
        if isinstance(obj, np.ndarray):
            return obj.tolist()
        return super().default(obj)


def save_trade(record) -> int:
    bot_type    = getattr(record, "bot_type",     "SHORT")
    signals_raw = getattr(record, "signals_json", None)
    signals_str = json.dumps(signals_raw, ensure_ascii=False, cls=_SafeEncoder) if signals_raw else None
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO trades
        (timestamp, action, coin, price, amount, value_usd, balance_after, pnl,
         reasoning, confidence, risk_level, bot_type, signals_json)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        record.timestamp, record.action, record.coin,
        record.price, record.amount, record.value_usd,
        record.balance_after, record.pnl, record.reasoning,
        record.confidence, record.risk_level, bot_type, signals_str,
    ))
    conn.commit()
    trade_id = cur.lastrowid
    conn.close()

    # テキストログにも追記
    _append_text_log(record)
    return trade_id


def _append_text_log(record):
    """人間が読めるテキストログに追記"""
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    sign = "+" if record.pnl >= 0 else ""
    line = (
        f"[{record.timestamp[:19]}] "
        f"{record.action:<4} | "
        f"{record.coin:<8} | "
        f"${record.price:>10,.2f} | "
        f"amt={record.amount:.6f} | "
        f"PnL={sign}${record.pnl:,.2f} | "
        f"bal=${record.balance_after:,.2f} | "
        f"conf={record.confidence:.0%} | "
        f"risk={record.risk_level}\n"
    )
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(line)


def save_snapshot(market_data: dict):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    technicals = market_data.get("technicals", {})
    fear_greed = market_data.get("fear_greed", {})
    cur.execute("""
        INSERT INTO market_snapshots
        (timestamp, coin, price, rsi, macd, fear_greed_value, fear_greed_label, raw_data)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        market_data.get("collected_at", datetime.now(timezone.utc).isoformat()),
        market_data.get("coin", "bitcoin"),
        technicals.get("current_price"),
        technicals.get("rsi"),
        technicals.get("macd"),
        fear_greed.get("value") if fear_greed else None,
        fear_greed.get("label") if fear_greed else None,
        json.dumps(market_data, ensure_ascii=False, cls=_SafeEncoder),
    ))
    conn.commit()
    conn.close()


def get_recent_trades(limit: int = 20) -> list[dict]:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("SELECT * FROM trades ORDER BY timestamp DESC LIMIT ?", (limit,))
    rows = [dict(row) for row in cur.fetchall()]
    conn.close()
    return rows


def get_performance_stats() -> dict:
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM trades WHERE action != 'HOLD'")
    total_trades = cur.fetchone()[0]
    cur.execute("SELECT SUM(pnl) FROM trades WHERE action = 'SELL'")
    total_pnl = cur.fetchone()[0] or 0.0
    cur.execute("SELECT COUNT(*) FROM trades WHERE action = 'SELL' AND pnl > 0")
    wins = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM trades WHERE action = 'SELL'")
    total_sells = cur.fetchone()[0]
    conn.close()
    win_rate = (wins / total_sells * 100) if total_sells > 0 else 0.0
    return {
        "total_trades": total_trades,
        "total_pnl_usd": round(total_pnl, 2),
        "win_rate_pct": round(win_rate, 1),
        "total_sells": total_sells,
    }
