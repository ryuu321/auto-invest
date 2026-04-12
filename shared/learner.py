"""
投資学習モジュール — 多角的データ分析でシグナル重みを継続改善する

分析軸：
  1. シグナル別有効性 — 各シグナル（RSI/MACD/BB等）の勝率・期待値・情報比率
  2. マーケットレジーム — 強気/弱気/横横/高ボラ の4状態を自動検出
  3. シグナル組み合わせ効果 — どの組み合わせが最も機能するか
  4. 直近パフォーマンスドリフト — 直近N件 vs 全体の乖離をモニタリング
"""
import json
import math
import sqlite3
from collections import defaultdict
from pathlib import Path

DATA_DIR = Path(__file__).parent.parent / "data"
DB_PATH  = DATA_DIR / "trades.db"

DEFAULTS = {
    "SHORT":  {"buy_threshold": 2,  "sell_threshold": -2,
               "min_buy": 1, "max_buy": 5, "min_sell": -5, "max_sell": -1,
               "signal_weights": {}},
    "MEDIUM": {"buy_threshold": 3,  "sell_threshold": -3,
               "min_buy": 2, "max_buy": 6, "min_sell": -6, "max_sell": -2,
               "signal_weights": {}},
    "LONG":   {"buy_threshold": 4,  "sell_threshold": -4,
               "min_buy": 3, "max_buy": 7, "min_sell": -7, "max_sell": -3,
               "signal_weights": {}},
}

MIN_TRADES_TO_LEARN = 5
WEIGHT_MIN  = 0.3
WEIGHT_MAX  = 2.5


# ── ファイル操作 ───────────────────────────────────────────────────────

def _threshold_file(bot_type: str) -> Path:
    return DATA_DIR / f"learned_thresholds_{bot_type.lower()}.json"


def load_thresholds(bot_type: str) -> dict:
    path = _threshold_file(bot_type)
    if path.exists():
        try:
            saved = json.loads(path.read_text(encoding="utf-8"))
            d = dict(DEFAULTS.get(bot_type, DEFAULTS["SHORT"]))
            d.update(saved)
            return d
        except Exception:
            pass
    return dict(DEFAULTS.get(bot_type, DEFAULTS["SHORT"]))


def save_thresholds(bot_type: str, thresholds: dict):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    _threshold_file(bot_type).write_text(
        json.dumps(thresholds, ensure_ascii=False, indent=2), encoding="utf-8"
    )


# ── マーケットレジーム検出 ─────────────────────────────────────────────

def detect_market_regime(bot_type: str = "SHORT") -> str:
    """
    直近の market_snapshots から市場状態を判定する。
    戻り値: "BULL" / "BEAR" / "SIDEWAYS" / "VOLATILE" / "UNKNOWN"
    """
    if not DB_PATH.exists():
        return "UNKNOWN"

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    try:
        cur.execute("""
            SELECT price, rsi, fear_greed_value
            FROM market_snapshots
            ORDER BY timestamp DESC LIMIT 20
        """)
        rows = cur.fetchall()
    except Exception:
        conn.close()
        return "UNKNOWN"
    conn.close()

    if len(rows) < 5:
        return "UNKNOWN"

    prices   = [r["price"] for r in rows if r["price"]]
    rsi_vals = [r["rsi"]   for r in rows if r["rsi"]]

    if not prices:
        return "UNKNOWN"

    mean_p   = sum(prices) / len(prices)
    variance = sum((p - mean_p) ** 2 for p in prices) / len(prices)
    cv       = math.sqrt(variance) / mean_p

    if cv > 0.05:
        return "VOLATILE"

    recent = sum(prices[:5])  / 5
    older  = sum(prices[-5:]) / 5
    trend  = (recent - older) / older

    avg_rsi = sum(rsi_vals) / len(rsi_vals) if rsi_vals else 50

    if trend > 0.02 and avg_rsi > 50:
        return "BULL"
    elif trend < -0.02 and avg_rsi < 50:
        return "BEAR"
    else:
        return "SIDEWAYS"


# ── BUY→SELLペア生成 ─────────────────────────────────────────────────

def _get_buy_sell_pairs(bot_type: str) -> list:
    if not DB_PATH.exists():
        return []

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    try:
        cur.execute("""
            SELECT id, timestamp, action, coin, pnl, signals_json, confidence
            FROM trades
            WHERE action IN ('BUY','SELL')
              AND COALESCE(bot_type,'SHORT') = ?
            ORDER BY timestamp ASC
        """, (bot_type,))
        rows = cur.fetchall()
    except Exception:
        conn.close()
        return []
    conn.close()

    pairs = []
    pending_buys = {}

    for row in rows:
        coin = row["coin"]
        if row["action"] == "BUY":
            pending_buys[coin] = dict(row)
        elif row["action"] == "SELL" and coin in pending_buys:
            buy = pending_buys.pop(coin)
            pairs.append({
                "buy_signals": buy.get("signals_json"),
                "pnl":         row["pnl"],
                "win":         row["pnl"] > 0,
            })

    return pairs


# ── シグナル別有効性分析 ──────────────────────────────────────────────

def analyze_signal_effectiveness(bot_type: str) -> dict:
    """
    各シグナルについて勝率・期待値・情報比率（IR）を計算する。

    IR = avg_pnl / std_pnl
    正のIRが高いシグナルほど「安定してリターンに貢献している」と判断する。
    """
    pairs = _get_buy_sell_pairs(bot_type)
    if not pairs:
        return {}

    signal_pnls: dict = defaultdict(list)

    for pair in pairs:
        raw = pair["buy_signals"]
        if not raw:
            continue
        try:
            signals = json.loads(raw) if isinstance(raw, str) else raw
        except Exception:
            continue

        for sig in signals:
            name  = sig.get("name", "Unknown")
            score = sig.get("score", 0)
            if score != 0:
                signal_pnls[name].append(pair["pnl"])

    result = {}
    for name, pnls in signal_pnls.items():
        n = len(pnls)
        if n == 0:
            continue
        avg  = sum(pnls) / n
        wins = sum(1 for p in pnls if p > 0)
        std  = math.sqrt(sum((p - avg) ** 2 for p in pnls) / n) if n > 1 else 1.0
        ir   = avg / std if std > 0 else 0.0

        result[name] = {
            "fire_count":        n,
            "win_rate":          round(wins / n, 3),
            "avg_pnl":           round(avg, 2),
            "std_pnl":           round(std, 2),
            "information_ratio": round(ir, 3),
        }

    return result


def _compute_signal_weights(effectiveness: dict, current: dict) -> dict:
    """
    シグナル有効性データ → 各シグナルの重み（0.3〜2.5）に変換する。

    計算ロジック:
      base_weight = 1.0 + IR * 0.5
      勝率補正: 勝率35%未満 → *0.7 / 65%超 → *1.2
      クリップ: [WEIGHT_MIN, WEIGHT_MAX]
    """
    weights = dict(current.get("signal_weights", {}))

    for name, stats in effectiveness.items():
        n  = stats["fire_count"]
        wr = stats["win_rate"]
        ir = stats["information_ratio"]

        if n < 3:
            weights.setdefault(name, 1.0)
            continue

        raw_weight = 1.0 + ir * 0.5

        if wr < 0.35:
            raw_weight *= 0.7
        elif wr > 0.65:
            raw_weight *= 1.2

        weights[name] = round(max(WEIGHT_MIN, min(WEIGHT_MAX, raw_weight)), 2)

    return weights


# ── シグナル組み合わせ分析 ────────────────────────────────────────────

def analyze_combination_effects(bot_type: str) -> dict:
    """
    どのシグナルの組み合わせが最も高い勝率・期待値をもたらすか分析する。
    """
    pairs = _get_buy_sell_pairs(bot_type)
    combo_stats: dict = defaultdict(list)

    for pair in pairs:
        raw = pair["buy_signals"]
        if not raw:
            continue
        try:
            signals = json.loads(raw) if isinstance(raw, str) else raw
        except Exception:
            continue

        active = sorted([s["name"] for s in signals if s.get("score", 0) != 0])
        if len(active) >= 2:
            key = "+".join(active)
            combo_stats[key].append(pair["pnl"])

    result = {}
    for combo, pnls in combo_stats.items():
        n    = len(pnls)
        wins = sum(1 for p in pnls if p > 0)
        avg  = sum(pnls) / n
        result[combo] = {
            "count":    n,
            "win_rate": round(wins / n, 3),
            "avg_pnl":  round(avg, 2),
        }

    return dict(sorted(result.items(), key=lambda x: -x[1]["count"])[:5])


# ── 直近ドリフト検出 ──────────────────────────────────────────────────

def analyze_recent_drift(bot_type: str, recent_n: int = 10) -> dict:
    """
    直近N件 vs 全体のパフォーマンス乖離を検出する。
    戦略が市場環境にアンマッチになってきた可能性を示す。
    """
    pairs = _get_buy_sell_pairs(bot_type)
    if len(pairs) < recent_n:
        return {"drift_detected": False, "message": "データ不足"}

    all_pnls    = [p["pnl"] for p in pairs]
    recent_pnls = [p["pnl"] for p in pairs[-recent_n:]]

    all_avg    = sum(all_pnls)    / len(all_pnls)
    recent_avg = sum(recent_pnls) / len(recent_pnls)
    all_wr     = sum(1 for p in all_pnls    if p > 0) / len(all_pnls)
    recent_wr  = sum(1 for p in recent_pnls if p > 0) / len(recent_pnls)

    pnl_drift = abs(recent_avg - all_avg) > max(abs(all_avg) * 0.5, 10)
    wr_drift  = abs(recent_wr - all_wr) > 0.2

    return {
        "drift_detected": pnl_drift or wr_drift,
        "all_avg_pnl":    round(all_avg, 2),
        "recent_avg_pnl": round(recent_avg, 2),
        "all_win_rate":   round(all_wr, 3),
        "recent_win_rate":round(recent_wr, 3),
        "message":        "パフォーマンスドリフト検出" if (pnl_drift or wr_drift) else "安定",
    }


# ── メイン学習関数 ────────────────────────────────────────────────────

def learn(bot_type: str) -> dict:
    """
    全分析を実行して学習済みパラメータを更新・保存する。
    """
    current  = load_thresholds(bot_type)
    defaults = DEFAULTS.get(bot_type, DEFAULTS["SHORT"])
    pairs    = _get_buy_sell_pairs(bot_type)

    if len(pairs) < MIN_TRADES_TO_LEARN:
        print(f"[LEARN/{bot_type}] トレード数不足 ({len(pairs)}/{MIN_TRADES_TO_LEARN})。学習スキップ。")
        return current

    print(f"\n[LEARN/{bot_type}] === 学習開始 (N={len(pairs)}) ===")

    # 1. マーケットレジーム検出
    regime = detect_market_regime(bot_type)
    print(f"  市場レジーム: {regime}")

    # 2. シグナル別有効性
    effectiveness = analyze_signal_effectiveness(bot_type)
    if effectiveness:
        print(f"  シグナル有効性 (IR=情報比率):")
        for name, s in sorted(effectiveness.items(), key=lambda x: -x[1]["information_ratio"]):
            print(f"    {name:15s} 勝率={s['win_rate']:.0%}  "
                  f"平均PnL=${s['avg_pnl']:+.2f}  "
                  f"IR={s['information_ratio']:+.2f}  "
                  f"(N={s['fire_count']})")

    # 3. シグナル重み更新
    new_weights = _compute_signal_weights(effectiveness, current)
    old_weights = current.get("signal_weights", {})
    changed     = {k: v for k, v in new_weights.items() if old_weights.get(k) != v}
    if changed:
        print(f"  重み更新: {changed}")

    # 4. 全体勝率で買い閾値を微調整
    all_pnls = [p["pnl"] for p in pairs]
    wins     = sum(1 for p in all_pnls if p > 0)
    win_rate = wins / len(all_pnls)
    buy_t    = current["buy_threshold"]

    if win_rate < 0.35:
        buy_t = min(buy_t + 1, defaults["max_buy"])
        print(f"  全体勝率低({win_rate:.0%}) → buy_threshold {current['buy_threshold']}→{buy_t}")
    elif win_rate > 0.70:
        buy_t = max(buy_t - 1, defaults["min_buy"])
        print(f"  全体勝率高({win_rate:.0%}) → buy_threshold {current['buy_threshold']}→{buy_t}")

    # 5. ドリフト検出 → 大きく乖離時はウェイトを保守的に戻す
    drift_info = analyze_recent_drift(bot_type)
    if drift_info.get("drift_detected"):
        print(f"  ドリフト検出: 全体平均${drift_info['all_avg_pnl']:+.2f} vs "
              f"直近${drift_info['recent_avg_pnl']:+.2f}")
        for name in new_weights:
            new_weights[name] = round((new_weights[name] + 1.0) / 2, 2)

    # 6. 組み合わせ効果サマリー
    combos = analyze_combination_effects(bot_type)
    if combos:
        print(f"  有効なシグナル組み合わせ Top3:")
        for combo, s in list(combos.items())[:3]:
            display = combo if len(combo) <= 50 else combo[:47] + "..."
            print(f"    {display:50s} 勝率={s['win_rate']:.0%} N={s['count']}")

    # 保存
    current["buy_threshold"]  = buy_t
    current["signal_weights"] = new_weights
    current["regime"]         = regime
    save_thresholds(bot_type, current)
    print(f"[LEARN/{bot_type}] 完了: buy_threshold={buy_t}  勝率={win_rate:.0%}")
    return current


def print_report(bot_type: str = "SHORT"):
    t = load_thresholds(bot_type)
    print(f"\n[学習パラメータ / {bot_type}]")
    print(f"  buy_threshold  : {t['buy_threshold']}")
    print(f"  sell_threshold : {t['sell_threshold']}")
    print(f"  regime         : {t.get('regime', 'N/A')}")
    weights = t.get("signal_weights", {})
    if weights:
        print(f"  signal_weights :")
        for name, w in sorted(weights.items()):
            bars = int(w * 4)
            bar = chr(9608) * bars
            print(f"    {name:15s} {w:.2f} {bar}")
