"""
学習モジュール — 過去のトレード結果からしきい値を自動調整する
SHORT/MEDIUM/LONG 全ボット共通
"""
import json
import sqlite3
from pathlib import Path

DATA_DIR = Path(__file__).parent.parent / "data"
DB_PATH  = DATA_DIR / "trades.db"

DEFAULTS = {
    "SHORT":  {"buy_threshold": 2,  "sell_threshold": -2, "min_buy": 1, "max_buy": 4,  "min_sell": -4,  "max_sell": -1},
    "MEDIUM": {"buy_threshold": 3,  "sell_threshold": -3, "min_buy": 2, "max_buy": 5,  "min_sell": -5,  "max_sell": -2},
    "LONG":   {"buy_threshold": 4,  "sell_threshold": -4, "min_buy": 3, "max_buy": 6,  "min_sell": -6,  "max_sell": -3},
}

MIN_TRADES_TO_LEARN = 5


def _threshold_file(bot_type: str) -> Path:
    return DATA_DIR / f"learned_thresholds_{bot_type.lower()}.json"


def load_thresholds(bot_type: str) -> dict:
    path = _threshold_file(bot_type)
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            pass
    return dict(DEFAULTS.get(bot_type, DEFAULTS["SHORT"]))


def save_thresholds(bot_type: str, thresholds: dict):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    _threshold_file(bot_type).write_text(
        json.dumps(thresholds, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def learn(bot_type: str) -> dict:
    current = load_thresholds(bot_type)
    defaults = DEFAULTS.get(bot_type, DEFAULTS["SHORT"])

    if not DB_PATH.exists():
        return current

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    try:
        cur.execute("""
            SELECT pnl, confidence
            FROM trades
            WHERE action='SELL'
              AND COALESCE(bot_type, 'SHORT') = ?
            ORDER BY timestamp DESC
            LIMIT 20
        """, (bot_type,))
        rows = cur.fetchall()
    except Exception:
        conn.close()
        return current
    finally:
        conn.close()

    if len(rows) < MIN_TRADES_TO_LEARN:
        print(f"[LEARN/{bot_type}] トレード数不足 ({len(rows)}/{MIN_TRADES_TO_LEARN})。学習スキップ。")
        return current

    wins  = sum(1 for r in rows if r["pnl"] > 0)
    total = len(rows)
    win_rate = wins / total

    avg_conf_loses = sum(r["confidence"] for r in rows if r["pnl"] <= 0) / max(total - wins, 1)

    buy_t  = current["buy_threshold"]
    sell_t = current["sell_threshold"]

    if win_rate < 0.4:
        buy_t = min(buy_t + 1, defaults["max_buy"])
        print(f"[LEARN/{bot_type}] 勝率低({win_rate:.0%}) → buy_threshold {current['buy_threshold']}→{buy_t}")
    elif win_rate > 0.65:
        buy_t = max(buy_t - 1, defaults["min_buy"])
        print(f"[LEARN/{bot_type}] 勝率高({win_rate:.0%}) → buy_threshold {current['buy_threshold']}→{buy_t}")

    if avg_conf_loses > 0.6 and win_rate < 0.5:
        buy_t = min(buy_t + 1, defaults["max_buy"])
        print(f"[LEARN/{bot_type}] 高確信度での負け多発 → buy_threshold さらに {buy_t}")

    current["buy_threshold"]  = buy_t
    current["sell_threshold"] = sell_t

    save_thresholds(bot_type, current)
    print(f"[LEARN/{bot_type}] 完了: buy={buy_t} sell={sell_t}  (勝率={win_rate:.0%} N={total})")
    return current


def print_report(bot_type: str = "SHORT"):
    t = load_thresholds(bot_type)
    print(f"\n[学習パラメータ / {bot_type}]")
    for k, v in t.items():
        print(f"  {k}: {v}")
