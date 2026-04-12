"""
全自動投資システム — メインエントリーポイント
APIキー不要・完全無料
1時間ごとに実行してペーパートレードを積み重ねる
"""

import time
from datetime import datetime, timezone

from collector import collect_all
from analyzer import RuleBasedAnalyzer
from trader import PaperTrader
from logger import init_db, save_trade, save_snapshot, get_performance_stats
from learner import print_report
import sys
sys.path.insert(0, str(__import__('pathlib').Path(__file__).parent.parent / "shared"))
from summary import write_summary


# ── 設定 ────────────────────────────────────────────
COIN             = "bitcoin"
INITIAL_BALANCE  = 10000.0   # 架空の初期資金（USD）
INTERVAL_SECONDS = 3600      # 1時間ごとに実行
# ────────────────────────────────────────────────────


def run_cycle(trader: PaperTrader, analyzer: RuleBasedAnalyzer):
    """1サイクル（収集 → 分析 → 売買 → ログ）"""

    print(f"\n{'='*55}")
    print(f"[{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC]")

    # 1. 情報収集
    print("[1] データ収集中...")
    market_data = collect_all(COIN)
    save_snapshot(market_data)

    price = market_data.get("technicals", {}).get("current_price")
    if not price:
        print("[!] 価格データなし。スキップします。")
        return

    t = market_data.get("technicals", {})
    fg = market_data.get("fear_greed", {}) or {}
    ns = market_data.get("news_sentiment", {})

    print(f"    BTC価格: ${price:,.2f}")
    print(f"    RSI={t.get('rsi')} | MACD={t.get('macd')} | F&G={fg.get('value')}({fg.get('label')})")
    print(f"    ニュース: {ns.get('label')} (スコア={ns.get('score')})")

    # 2. ルールベース分析
    analysis = analyzer.analyze(market_data)
    decision   = analysis["decision"]
    confidence = analysis["confidence"]
    risk       = analysis["risk_level"]
    score      = analysis["total_score"]

    print(f"\n[2] シグナル分析:")
    for sig in analysis.get("signals", []):
        mark = "+" if sig["score"] > 0 else ("-" if sig["score"] < 0 else " ")
        print(f"    [{mark}] {sig['reason']}")

    print(f"\n    判断: {decision}  スコア={score:+d}  確信度={confidence:.0%}  リスク={risk}")

    # 3. ペーパートレード
    record = trader.execute(
        decision=decision,
        current_price=price,
        coin=COIN,
        reasoning=analysis["reasoning"],
        confidence=confidence,
        risk_level=risk,
    )
    record.bot_type = "SHORT"
    save_trade(record)

    if record.action == "BUY":
        print(f"\n[BUY]  {record.amount:.6f} BTC @ ${price:,.2f}  (${record.value_usd:,.2f}使用)")
    elif record.action == "SELL":
        sign = "+" if record.pnl >= 0 else ""
        print(f"\n[SELL] {record.amount:.6f} BTC @ ${price:,.2f}  PnL={sign}${record.pnl:,.2f}")
    else:
        print(f"\n[HOLD] 売買なし")

    # 4. パフォーマンス
    summary = trader.summary(price)
    stats   = get_performance_stats()
    print(f"\n[PF]  資産: ${summary['portfolio_value']:,.2f} "
          f"({'+' if summary['total_return_pct'] >= 0 else ''}{summary['total_return_pct']}%)")
    print(f"      勝率: {stats['win_rate_pct']}%  "
          f"累計損益: ${stats['total_pnl_usd']:,.2f}  "
          f"取引回数: {stats['total_trades']}")


def main():
    print("[SHORT] 短期ボット 1回実行")
    init_db()
    trader   = PaperTrader(initial_balance_usd=INITIAL_BALANCE)
    analyzer = RuleBasedAnalyzer()
    try:
        run_cycle(trader, analyzer)
    except Exception as e:
        import traceback
        print(f"[ERROR] {e}")
        traceback.print_exc()
    finally:
        write_summary()


if __name__ == "__main__":
    main()
