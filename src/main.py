"""
全自動投資システム — メインエントリーポイント
APIキー不要・完全無料
1時間ごとに実行してペーパートレードを積み重ねる
"""

import time
from datetime import datetime

from collector import collect_all
from analyzer import RuleBasedAnalyzer
from trader import PaperTrader
from logger import init_db, save_trade, save_snapshot, get_performance_stats
from learner import print_report


# ── 設定 ────────────────────────────────────────────
COIN             = "bitcoin"
INITIAL_BALANCE  = 10000.0   # 架空の初期資金（USD）
INTERVAL_SECONDS = 3600      # 1時間ごとに実行
# ────────────────────────────────────────────────────


def run_cycle(trader: PaperTrader, analyzer: RuleBasedAnalyzer):
    """1サイクル（収集 → 分析 → 売買 → ログ）"""

    print(f"\n{'='*55}")
    print(f"[{datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC]")

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
    print("[START] 全自動投資システム起動")
    print("  モード  : ペーパートレード（架空資金）")
    print("  分析    : ルールベース（APIキー不要・完全無料）")
    print(f"  対象    : {COIN}")
    print(f"  初期資金: ${INITIAL_BALANCE:,.2f}")
    print(f"  実行間隔: {INTERVAL_SECONDS // 60}分ごと\n")

    init_db()
    trader   = PaperTrader(initial_balance_usd=INITIAL_BALANCE)
    analyzer = RuleBasedAnalyzer()

    cycle = 0
    while True:
        try:
            run_cycle(trader, analyzer)
            cycle += 1
            # 10サイクルごとに学習レポート表示
            if cycle % 10 == 0:
                print_report()
        except KeyboardInterrupt:
            print("\n\n[STOP] 停止しました。")
            print_report()
            break
        except Exception as e:
            print(f"[ERROR] {e}")

        print(f"\n[WAIT] {INTERVAL_SECONDS // 60}分後に次のサイクルを実行...")
        time.sleep(INTERVAL_SECONDS)


if __name__ == "__main__":
    main()
