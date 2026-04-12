"""
学習モジュール
ペーパートレードのログを分析し、どのルールが機能しているかを評価する。
蓄積されたデータをもとにルールの閾値を自動調整する。
"""

import sqlite3
import json
from pathlib import Path
from dataclasses import dataclass

DB_PATH = Path(__file__).parent.parent / "data" / "trades.db"
LEARNED_PATH = Path(__file__).parent.parent / "data" / "learned_thresholds.json"

# デフォルトの閾値
DEFAULT_THRESHOLDS = {
    "rsi_oversold":     30.0,   # これ以下でBUYシグナル
    "rsi_overbought":   70.0,   # これ以上でSELLシグナル
    "fear_greed_buy":   25,     # これ以下でBUYシグナル
    "fear_greed_sell":  75,     # これ以上でSELLシグナル
    "news_positive":     3,     # これ以上でBUYシグナル
    "news_negative":    -3,     # これ以下でSELLシグナル
    "buy_threshold":     2,     # 合計スコアがこれ以上でBUY
    "sell_threshold":   -2,     # 合計スコアがこれ以下でSELL
}


@dataclass
class LearningReport:
    total_sells: int
    win_rate: float
    avg_pnl: float
    best_rule: str
    worst_rule: str
    suggested_thresholds: dict
    summary: str


def load_thresholds() -> dict:
    """学習済み閾値を読み込む（なければデフォルト）"""
    if LEARNED_PATH.exists():
        return json.loads(LEARNED_PATH.read_text(encoding="utf-8"))
    return DEFAULT_THRESHOLDS.copy()


def save_thresholds(thresholds: dict):
    """学習済み閾値を保存"""
    LEARNED_PATH.parent.mkdir(parents=True, exist_ok=True)
    LEARNED_PATH.write_text(json.dumps(thresholds, indent=2, ensure_ascii=False), encoding="utf-8")


def analyze() -> LearningReport:
    """トレード履歴を分析してルール評価レポートを生成"""
    if not DB_PATH.exists():
        return LearningReport(
            total_sells=0, win_rate=0.0, avg_pnl=0.0,
            best_rule="データなし", worst_rule="データなし",
            suggested_thresholds=DEFAULT_THRESHOLDS,
            summary="まだ取引データがありません。ペーパートレードを続けてください。"
        )

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # SELL取引のみ分析（実際に決済した取引）
    cur.execute("SELECT * FROM trades WHERE action = 'SELL' ORDER BY timestamp")
    sells = [dict(r) for r in cur.fetchall()]

    # BUY取引のreasoning分析
    cur.execute("SELECT reasoning, pnl FROM trades WHERE action = 'SELL'")
    reasoning_rows = cur.fetchall()

    conn.close()

    total_sells = len(sells)
    if total_sells == 0:
        thresholds = load_thresholds()
        return LearningReport(
            total_sells=0, win_rate=0.0, avg_pnl=0.0,
            best_rule="データ蓄積中", worst_rule="データ蓄積中",
            suggested_thresholds=thresholds,
            summary=f"SELL取引がまだありません。現在のルールで継続学習中です。"
        )

    wins = [t for t in sells if t["pnl"] > 0]
    win_rate = len(wins) / total_sells * 100
    avg_pnl = sum(t["pnl"] for t in sells) / total_sells

    # ルール別勝率を分析（reasoningからルール名を抽出）
    rule_stats = {}
    for row in reasoning_rows:
        reasoning = row[0] or ""
        pnl = row[1] or 0
        # reasoningからルール名を抽出
        for rule in ["RSI", "MACD", "BB", "FearGreed", "News"]:
            if rule in reasoning:
                if rule not in rule_stats:
                    rule_stats[rule] = {"wins": 0, "total": 0, "pnl": 0}
                rule_stats[rule]["total"] += 1
                rule_stats[rule]["pnl"] += pnl
                if pnl > 0:
                    rule_stats[rule]["wins"] += 1

    best_rule = max(rule_stats, key=lambda r: rule_stats[r]["pnl"]) if rule_stats else "分析中"
    worst_rule = min(rule_stats, key=lambda r: rule_stats[r]["pnl"]) if rule_stats else "分析中"

    # 閾値の自動調整
    thresholds = load_thresholds()
    suggested = thresholds.copy()

    # 勝率が低い場合は閾値を厳しくする
    if win_rate < 50 and total_sells >= 10:
        suggested["buy_threshold"] = min(thresholds["buy_threshold"] + 1, 4)
        suggested["sell_threshold"] = max(thresholds["sell_threshold"] - 1, -4)

    # 勝率が高い場合は閾値を緩める（より多くの取引機会）
    elif win_rate > 70 and total_sells >= 10:
        suggested["buy_threshold"] = max(thresholds["buy_threshold"] - 1, 1)
        suggested["sell_threshold"] = min(thresholds["sell_threshold"] + 1, -1)

    # 学習結果を保存
    if suggested != thresholds and total_sells >= 10:
        save_thresholds(suggested)

    summary_lines = [
        f"取引回数: {total_sells}  勝率: {win_rate:.1f}%  平均損益: ${avg_pnl:,.2f}",
        f"最も効いたルール: {best_rule}",
        f"最も効かなかったルール: {worst_rule}",
    ]
    if suggested != thresholds:
        summary_lines.append(f"閾値を自動調整しました: BUY={suggested['buy_threshold']} SELL={suggested['sell_threshold']}")
    else:
        summary_lines.append("現在の閾値を継続使用")

    return LearningReport(
        total_sells=total_sells,
        win_rate=win_rate,
        avg_pnl=avg_pnl,
        best_rule=best_rule,
        worst_rule=worst_rule,
        suggested_thresholds=suggested,
        summary=" | ".join(summary_lines)
    )


def print_report():
    report = analyze()
    print("\n=== 学習レポート ===")
    print(f"  {report.summary}")
    print(f"  現在の閾値: {json.dumps(report.suggested_thresholds, ensure_ascii=False)}")
