"""長期投資ボット — 週1回実行・ファンダメンタルズ特化・利確ルールあり"""
import sys
from pathlib import Path
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(1, str(Path(__file__).parent.parent / "shared"))
sys.path.insert(2, str(Path(__file__).parent.parent / "src"))

from collector import collect_all
from analyzer import LongTermAnalyzer
from portfolio import Portfolio
from logger import init_db, save_trade, save_snapshot
from summary import write_summary
from learner import learn, print_report

INITIAL_BALANCE = 10000.0
SELL_THRESHOLD  = -2


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
    r.bot_type      = "LONG"
    r.signals_json  = signals
    return r


def run_cycle(portfolio: Portfolio, analyzer: LongTermAnalyzer):
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    print(f"\n{'='*55}")
    print(f"[LONG] {now}  ※ファンダメンタルズ戦略（利確・損切りあり）")
    print("[1] ファンダメンタルズ収集中...")

    data   = collect_all()
    save_snapshot(data)

    scores = data.get("scores", {})
    funds  = data.get("fundamentals", {})
    prices = {t: f.get("price", 0) for t, f in funds.items() if f.get("price")}

    print("    銘柄スコアランキング:")
    for ticker, score in sorted(scores.items(), key=lambda x: -x[1])[:5]:
        f    = funds.get(ticker, {})
        held = "★保有中" if ticker in portfolio.positions else ""
        print(f"    [{score:+d}] {ticker} PE={f.get('pe_ratio','N/A')} "
              f"成長={f.get('revenue_growth','N/A')} {held}")

    # ── 保有中ポジションの売り判断 ────────────────────────
    for ticker in list(portfolio.positions.keys()):
        price = prices.get(ticker)
        if not price:
            continue

        should_exit, exit_reason = portfolio.check_exits(ticker, price)
        if should_exit:
            rec = portfolio.sell(ticker, price, exit_reason, 0.9, "LOW")
            if rec:
                save_trade(make_trade_record(rec))
                sign = "+" if rec.pnl >= 0 else ""
                print(f"[SELL] {ticker} @ ${price:,.2f}  {exit_reason}  PnL={sign}${rec.pnl:,.2f}")
            continue

        score = scores.get(ticker, 0)
        if score <= SELL_THRESHOLD:
            rec = portfolio.sell(ticker, price, f"ファンダスコア={score}→売却基準以下", 0.7, "MEDIUM")
            if rec:
                save_trade(make_trade_record(rec))
                sign = "+" if rec.pnl >= 0 else ""
                print(f"[SELL] {ticker} @ ${price:,.2f}  PnL={sign}${rec.pnl:,.2f}")

    # ── 新規BUY判断 ───────────────────────────────────────
    analysis   = analyzer.analyze(data)
    rec_ticker = analysis.get("recommended")
    decision   = analysis["decision"]

    print(f"\n[2] シグナル分析 (推奨: {rec_ticker}):")
    for s in analysis.get("signals", []):
        mark = "+" if s["score"] > 0 else ("-" if s["score"] < 0 else " ")
        print(f"    [{mark}] {s['reason']}")
    print(f"\n    判断: {decision}  スコア={analysis['total_score']:+.1f}  "
          f"確信度={analysis['confidence']:.0%}  リスク={analysis['risk_level']}")

    if decision == "BUY" and rec_ticker:
        price = prices.get(rec_ticker)
        if price:
            rec = portfolio.buy(rec_ticker, price, analysis["reasoning"],
                                analysis["confidence"], analysis["risk_level"])
            if rec:
                save_trade(make_trade_record(rec, signals=analysis.get("signals")))
                print(f"\n[BUY]  {rec_ticker} {rec.shares:.4f}株 @ ${price:,.2f}  (${rec.value_usd:,.2f}投資)")
            else:
                print(f"\n[SKIP] {rec_ticker} は既に保有中またはポジション上限")
        else:
            print(f"\n[!] {rec_ticker} の価格データなし")
    elif decision == "HOLD":
        print(f"\n[HOLD] 新規購入なし")

    # ── ポートフォリオサマリー ────────────────────────────
    summary = portfolio.summary(prices)
    print(f"\n[PF]  総資産: ${summary['portfolio_value']:,.2f} "
          f"({'+' if summary['total_return_pct'] >= 0 else ''}{summary['total_return_pct']}%)")
    print(f"      現金: ${summary['cash_balance']:,.2f}  "
          f"保有銘柄数: {summary['open_positions']}  "
          f"確定損益: ${summary['realized_pnl']:,.2f}")
    if summary["positions"]:
        print("      保有中:")
        for p in summary["positions"]:
            print(f"        {p}")


def main():
    print("[START] 長期投資ボット（ファンダメンタルズ戦略）")
    print("  戦略: 優良株をスコアリング → 利確+20% / 損切り-10%")
    print(f"  初期資金: ${INITIAL_BALANCE:,.2f}\n")

    init_db()
    portfolio = Portfolio(
        initial_balance=INITIAL_BALANCE,
        risk_per_trade=0.15,
        max_positions=5,
        state_file="portfolio_long.json",
        take_profit_pct=0.20,
        stop_loss_pct=0.10,
        trailing_stop_pct=0.07,
    )
    analyzer = LongTermAnalyzer()

    try:
        run_cycle(portfolio, analyzer)
        learn("LONG")
        print_report("LONG")
    except Exception as e:
        import traceback
        print(f"[ERROR] {e}")
        traceback.print_exc()
    finally:
        write_summary()


if __name__ == "__main__":
    main()
