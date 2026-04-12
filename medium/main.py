"""中期投資ボット — 1日1回実行・マルチ銘柄ポートフォリオ"""
import sys, time
from pathlib import Path
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(1, str(Path(__file__).parent.parent / "shared"))
sys.path.insert(2, str(Path(__file__).parent.parent / "src"))

from collector import collect_all
from analyzer import MediumTermAnalyzer
from portfolio import Portfolio
from logger import init_db, save_trade, save_snapshot
from summary import write_summary
from learner import learn, print_report

INITIAL_BALANCE  = 10000.0
INTERVAL_SECONDS = 86400    # 24時間
SELL_SCORE       = -2        # このスコア以下で売り


def make_trade_record(rec, signals=None):
    class Compat: pass
    r = Compat()
    r.timestamp     = rec.timestamp
    r.action        = rec.action
    r.coin          = rec.ticker
    r.price         = rec.price
    r.amount        = rec.shares
    r.value_usd     = rec.value_usd
    r.balance_after = rec.balance_after
    r.pnl           = rec.pnl
    r.reasoning     = rec.reasoning
    r.confidence    = rec.confidence
    r.risk_level    = rec.risk_level
    r.bot_type      = "MEDIUM"
    r.signals_json  = signals
    return r


def run_cycle(portfolio: Portfolio, analyzer: MediumTermAnalyzer):
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    print(f"\n{'='*55}")
    print(f"[MEDIUM] {now}")
    print("[1] 日足データ収集中...")

    data = collect_all()
    save_snapshot(data)

    assets = data.get("assets", {})
    prices = {t: info.get("price", 0) for t, info in assets.items() if info.get("price")}

    print("    市場状況:")
    for ticker, info in assets.items():
        if info:
            gc = " [GOLDEN CROSS]" if info.get("golden_cross") else ""
            dc = " [DEATH CROSS]"  if info.get("death_cross")  else ""
            held = " ★保有中" if ticker in portfolio.positions else ""
            print(f"    {ticker}: ${info.get('price','N/A')} "
                  f"MA50={info.get('ma50','N/A')} "
                  f"RSI={info.get('rsi','N/A')}"
                  f"{gc}{dc}{held}")

    # ── 保有中ポジションの売り判断 ────────────────────────
    for ticker in list(portfolio.positions.keys()):
        price = prices.get(ticker)
        if not price:
            continue

        # 利確・損切り・トレーリングストップ（最優先）
        should_exit, exit_reason = portfolio.check_exits(ticker, price)
        if should_exit:
            rec = portfolio.sell(ticker, price, exit_reason, 0.9, "LOW")
            if rec:
                save_trade(make_trade_record(rec))
                sign = "+" if rec.pnl >= 0 else ""
                print(f"\n[SELL] {ticker} @ ${price:,.2f}  {exit_reason}  PnL={sign}${rec.pnl:,.2f}")
            continue

        # テクニカル悪化による売り
        info = assets.get(ticker, {})
        if info:
            should_sell = (
                info.get("death_cross") or
                info.get("above_ma50") is False and info.get("above_ma200") is False
            )
            if should_sell:
                rec = portfolio.sell(ticker, price, "デスクロスまたはMA50/200下抜け", 0.7, "MEDIUM")
                if rec:
                    save_trade(make_trade_record(rec))
                    sign = "+" if rec.pnl >= 0 else ""
                    print(f"\n[SELL] {ticker} @ ${price:,.2f}  PnL={sign}${rec.pnl:,.2f}")

    # ── 新規BUY判断 ───────────────────────────────────────
    analysis  = analyzer.analyze(data)
    decision  = analysis["decision"]
    primary   = data.get("primary_ticker", "BTC-USD")

    print(f"\n[2] シグナル分析 (対象: {primary}):")
    for s in analysis.get("signals", []):
        mark = "+" if s["score"] > 0 else ("-" if s["score"] < 0 else " ")
        print(f"    [{mark}] {s['reason']}")
    print(f"\n    判断: {decision}  スコア={analysis['total_score']:+d}  "
          f"確信度={analysis['confidence']:.0%}  リスク={analysis['risk_level']}")

    if decision == "BUY":
        price = prices.get(primary)
        if price:
            rec = portfolio.buy(primary, price, analysis["reasoning"],
                                analysis["confidence"], analysis["risk_level"])
            if rec:
                save_trade(make_trade_record(rec, signals=analysis.get("signals")))
                print(f"\n[BUY]  {primary} {rec.shares:.6f} @ ${price:,.2f}  (${rec.value_usd:,.2f}投資)")
            else:
                print(f"\n[SKIP] {primary} は既に保有中またはポジション上限")
    elif decision == "HOLD":
        print(f"\n[HOLD] 売買なし")

    # ── ポートフォリオサマリー ────────────────────────────
    summary = portfolio.summary(prices)
    print(f"\n[PF]  総資産: ${summary['portfolio_value']:,.2f} "
          f"({'+' if summary['total_return_pct'] >= 0 else ''}{summary['total_return_pct']}%)")
    print(f"      現金: ${summary['cash_balance']:,.2f}  "
          f"保有銘柄数: {summary['open_positions']}  "
          f"確定損益: ${summary['realized_pnl']:,.2f}  "
          f"勝率: {summary['win_rate']}%")
    if summary["positions"]:
        print("      保有中:")
        for p in summary["positions"]:
            print(f"        {p}")


def main():
    print("[START] 中期投資ボット起動（日足・ゴールデンクロス戦略）")
    print(f"  初期資金: ${INITIAL_BALANCE:,.2f}  最大5銘柄分散\n")
    init_db()
    portfolio = Portfolio(initial_balance=INITIAL_BALANCE, risk_per_trade=0.15, max_positions=5, state_file="portfolio_medium.json")
    analyzer  = MediumTermAnalyzer()

    try:
        run_cycle(portfolio, analyzer)
        learn("MEDIUM")
        print_report("MEDIUM")
    except Exception as e:
        import traceback
        print(f"[ERROR] {e}")
        traceback.print_exc()
    finally:
        write_summary()


if __name__ == "__main__":
    main()
