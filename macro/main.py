"""
マクロ予測ボット — 週1回実行・経済サイクル戦略・利確ルールなし

戦略:
  - 経済サイクルが良い局面（拡張期）でポジションを持つ
  - 価格が上がっても「テーゼが生きている限り」売らない
  - テーゼが崩れたら（サイクル悪化・深いイールド逆転・地政学ショック）全売り
  - 利確・損切り・トレーリングストップは使わない
"""
import sys
from pathlib import Path
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(1, str(Path(__file__).parent.parent / "shared"))
sys.path.insert(2, str(Path(__file__).parent.parent / "src"))

from collector import collect_all
from analyzer import MacroAnalyzer
from portfolio import Portfolio
from logger import init_db, save_trade, save_snapshot
from summary import write_summary
from learner import learn, print_report

INITIAL_BALANCE = 10000.0


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
    r.bot_type      = "MACRO"
    r.signals_json  = signals
    return r


def run_cycle(portfolio: Portfolio, analyzer: MacroAnalyzer):
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    print(f"\n{'='*55}")
    print(f"[MACRO] {now}  ※経済サイクル戦略（利確ルールなし）")

    print("[1] マクロ先行指標・ファンダメンタルズ収集中...")
    data = collect_all()
    save_snapshot(data)

    cycle     = data.get("economic_cycle", {})
    macro_ind = data.get("macro_indicators", {})
    geo       = data.get("geo_political", {})
    funds     = data.get("fundamentals", {})
    prices    = data.get("prices", {t: f.get("price", 0)
                                   for t, f in funds.items() if f.get("price")})

    # ── マクロ指標表示 ────────────────────────────────────
    print(f"\n[マクロ先行指標]")
    yc_spread = macro_ind.get("yield_curve_spread")
    if yc_spread is not None:
        inv = " ★逆転中" if macro_ind.get("yield_curve_inverted") else ""
        print(f"  イールドカーブ: 10Y={macro_ind.get('yield_10y','N/A')}%  "
              f"3M={macro_ind.get('yield_3m','N/A')}%  "
              f"スプレッド={yc_spread:.3f}%{inv}")
    if macro_ind.get("vix") is not None:
        rising = " ↑上昇中" if macro_ind.get("vix_rising") else ""
        print(f"  VIX: {macro_ind.get('vix')} ({macro_ind.get('vix_regime','?')}){rising}")
    if macro_ind.get("dollar_trend"):
        print(f"  ドル: {macro_ind.get('dollar_trend')} ({macro_ind.get('dollar_change_pct',0):+.1f}%)")
    if macro_ind.get("gold_trend"):
        print(f"  金:  {macro_ind.get('gold_trend')} ({macro_ind.get('gold_change_pct',0):+.1f}%)")
    if macro_ind.get("credit_stress"):
        print(f"  クレジット: ★スプレッド拡大 ({macro_ind.get('credit_spread_change_pct',0):+.1f}%)")
    elif macro_ind.get("credit_spread_tightening"):
        print(f"  クレジット: 縮小 → リスクオン")

    geo_score  = geo.get("score", 0)
    event_tags = geo.get("event_tags", [])
    print(f"  地政学スコア: {geo_score:+d} ({geo.get('label','?')})")
    for tag in event_tags[:3]:
        print(f"    {tag}")

    print(f"\n[経済サイクル] {cycle.get('label','?')} (スコア={cycle.get('score',0):+d})")
    print(f"  推奨行動: {cycle.get('action','')}")
    rec_etfs = cycle.get("recommended_etfs", [])
    if rec_etfs:
        print(f"  推奨ETF: {', '.join(rec_etfs)}")
    for sig in cycle.get("signals", []):
        print(f"  → {sig}")

    # ── テーゼ崩壊 = 全ポジション売り ──────────────────────
    analysis = analyzer.analyze(data)

    if analysis.get("thesis_broken"):
        print(f"\n⚠️  マクロテーゼ崩壊検出: {analysis['thesis_reason']}")
        for ticker in list(portfolio.positions.keys()):
            price = prices.get(ticker)
            if not price:
                continue
            rec = portfolio.sell(ticker, price, analysis["reasoning"],
                                 analysis["confidence"], "LOW")
            if rec:
                save_trade(make_trade_record(rec, signals=analysis.get("signals")))
                sign = "+" if rec.pnl >= 0 else ""
                print(f"[SELL] {ticker} @ ${price:,.2f}  テーゼ崩壊  PnL={sign}${rec.pnl:,.2f}")
        print(f"\n[2] 全ポジション整理完了（テーゼ回復まで様子見）")
    else:
        # ── 通常の新規BUY判断 ──────────────────────────────
        rec_ticker = analysis.get("recommended")
        decision   = analysis["decision"]

        print(f"\n[2] シグナル分析 (推奨銘柄: {rec_ticker}):")
        for s in analysis.get("signals", []):
            if s["score"] == 0:
                continue
            mark = "+" if s["score"] > 0 else "-"
            print(f"    [{mark}] {s['reason']}")
        if rec_etfs:
            print(f"    [→] フェーズ推奨ETF: {', '.join(rec_etfs)}")
        print(f"\n    判断: {decision}  スコア={analysis['total_score']:+.1f}  "
              f"確信度={analysis['confidence']:.0%}")

        if decision == "BUY" and rec_ticker:
            price = prices.get(rec_ticker)
            if price:
                rec = portfolio.buy(rec_ticker, price, analysis["reasoning"],
                                    analysis["confidence"], analysis["risk_level"])
                if rec:
                    save_trade(make_trade_record(rec, signals=analysis.get("signals")))
                    print(f"\n[BUY]  {rec_ticker} {rec.shares:.4f}株 @ ${price:,.2f}  "
                          f"(${rec.value_usd:,.2f}投資) ← テーゼ崩壊まで保持")
                else:
                    print(f"\n[SKIP] {rec_ticker} は既に保有中またはポジション上限")
            else:
                print(f"\n[!] {rec_ticker} の価格データなし")
        elif decision == "HOLD":
            print(f"\n[HOLD] テーゼ生存中・新規エントリーなし")

    # ── 保有ポジション表示（テーゼが崩れない限り保持）─────
    summary = portfolio.summary(prices)
    print(f"\n[PF]  総資産: ${summary['portfolio_value']:,.2f} "
          f"({'+' if summary['total_return_pct'] >= 0 else ''}{summary['total_return_pct']}%)")
    print(f"      現金: ${summary['cash_balance']:,.2f}  "
          f"保有銘柄数: {summary['open_positions']}  "
          f"確定損益: ${summary['realized_pnl']:,.2f}")
    if summary["positions"]:
        print("      保有中（テーゼ崩壊まで長期保持）:")
        for p in summary["positions"]:
            print(f"        {p}")


def main():
    print("[START] マクロ予測ボット（経済サイクル戦略）")
    print("  戦略: 先行指標でサイクルを読む → テーゼが崩れたら撤退（利確ルールなし）")
    print(f"  初期資金: ${INITIAL_BALANCE:,.2f}\n")

    init_db()
    portfolio = Portfolio(
        initial_balance=INITIAL_BALANCE,
        risk_per_trade=0.20,      # 1銘柄に20%（集中投資気味）
        max_positions=3,          # 最大3銘柄（厳選）
        state_file="portfolio_macro.json",
        disable_price_exits=True, # 価格ベース出口ルールなし
    )
    analyzer = MacroAnalyzer()

    try:
        run_cycle(portfolio, analyzer)
        learn("MACRO")
        print_report("MACRO")
    except Exception as e:
        import traceback
        print(f"[ERROR] {e}")
        traceback.print_exc()
    finally:
        write_summary()


if __name__ == "__main__":
    main()
