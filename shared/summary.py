"""
ボット実行後に data/summary.json を書き出す
ダッシュボードはこのJSONをGitHub raw URLから直接読む
"""
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

DATA_DIR = Path(__file__).parent.parent / "data"
DB_PATH  = DATA_DIR / "trades.db"


def write_summary():
    """全ボットの状態をまとめてsummary.jsonに書き出す"""
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    summary = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "portfolios": {},
        "recent_trades": [],
        "stats": {},
    }

    # ── ポートフォリオ状態 ────────────────────────────────
    for fname, label in [
        ("portfolio_long.json",   "LONG"),
        ("portfolio_medium.json", "MEDIUM"),
        ("portfolio_short.json",  "SHORT"),
    ]:
        path = DATA_DIR / fname
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                summary["portfolios"][label] = data
            except Exception:
                pass

    # ── 直近トレード ──────────────────────────────────────
    if DB_PATH.exists():
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        try:
            cur.execute("""
                SELECT timestamp, action, coin, price, amount, value_usd,
                       balance_after, pnl, reasoning, confidence, risk_level,
                       COALESCE(bot_type, 'SHORT') as bot_type
                FROM trades
                WHERE action IN ('BUY','SELL')
                ORDER BY timestamp DESC LIMIT 50
            """)
            summary["recent_trades"] = [dict(r) for r in cur.fetchall()]

            cur.execute("SELECT COUNT(*) FROM trades WHERE action='BUY'")
            total_buys = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM trades WHERE action='SELL'")
            total_sells = cur.fetchone()[0]
            cur.execute("SELECT COALESCE(SUM(pnl),0) FROM trades WHERE action='SELL'")
            realized_pnl = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM trades WHERE action='SELL' AND pnl>0")
            wins = cur.fetchone()[0]
            summary["stats"] = {
                "total_buys":   total_buys,
                "total_sells":  total_sells,
                "realized_pnl": round(realized_pnl, 2),
                "win_rate":     round(wins / total_sells * 100, 1) if total_sells else 0.0,
            }
        except Exception:
            pass
        finally:
            conn.close()

    out = DATA_DIR / "summary.json"
    out.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[SUMMARY] data/summary.json 書き出し完了")
