"""
長期投資 分析モジュール — ファンダメンタルズ特化版

バフェット流：良い企業を適正価格で買う。利確・損切りで利益を確定する。
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "shared"))

from dataclasses import dataclass
from typing import Literal
from learner import load_thresholds

Decision = Literal["BUY", "SELL", "HOLD"]


@dataclass
class Signal:
    name: str
    score: float
    reason: str


class LongTermAnalyzer:
    """
    長期スコアリング（ファンダメンタルズ + マクロニュース）
    学習済みウェイトを適用。
    """

    def __init__(self):
        t = load_thresholds("LONG")
        self.BUY_THRESHOLD  = t["buy_threshold"]
        self.SELL_THRESHOLD = t["sell_threshold"]
        self.SIGNAL_WEIGHTS = t.get("signal_weights", {})

    def analyze(self, market_data: dict) -> dict:
        signals = []
        scores  = market_data.get("scores", {})
        funds   = market_data.get("fundamentals", {})
        macro   = market_data.get("macro_news", {})
        primary = market_data.get("primary_ticker", "AAPL")
        f       = funds.get(primary, {})

        # ── P/E ──────────────────────────────────────────────
        pe  = f.get("pe_ratio")
        fpe = f.get("forward_pe")
        if pe:
            if pe < 15:
                signals.append(Signal("PE", +2, f"PER={pe:.1f} 割安（<15）→ バリュー投資機会"))
            elif pe < 25:
                signals.append(Signal("PE", +1, f"PER={pe:.1f} 適正（15〜25）"))
            elif pe > 40:
                signals.append(Signal("PE", -2, f"PER={pe:.1f} 割高（>40）→ 金利上昇に弱い"))
            else:
                signals.append(Signal("PE",  0, f"PER={pe:.1f} やや高め"))
            if fpe and fpe < pe * 0.8:
                signals.append(Signal("ForwardPE", +1,
                    f"予想PER={fpe:.1f} < 実績{pe:.1f} → 利益成長加速の期待"))

        # ── 売上成長率 ────────────────────────────────────────
        rg = f.get("revenue_growth")
        if rg is not None:
            if rg > 0.20:
                signals.append(Signal("Revenue", +2, f"売上成長率={rg*100:.1f}% 高成長（>20%）"))
            elif rg > 0.10:
                signals.append(Signal("Revenue", +1, f"売上成長率={rg*100:.1f}% 成長継続"))
            elif rg < 0:
                signals.append(Signal("Revenue", -2, f"売上成長率={rg*100:.1f}% 減収 → 注意"))

        # ── 利益率 ────────────────────────────────────────────
        margin = f.get("profit_margin")
        if margin:
            if margin > 0.20:
                signals.append(Signal("Margin", +1, f"利益率={margin*100:.1f}% 高収益企業"))
            elif margin < 0.05:
                signals.append(Signal("Margin", -1, f"利益率={margin*100:.1f}% 低収益"))

        # ── 負債比率 ──────────────────────────────────────────
        dte = f.get("debt_to_equity")
        if dte is not None:
            if dte < 50:
                signals.append(Signal("Debt", +1, f"D/E={dte:.0f} 低負債 → 財務健全"))
            elif dte > 200:
                signals.append(Signal("Debt", -1, f"D/E={dte:.0f} 高負債 → リスク"))

        # ── ROE ───────────────────────────────────────────────
        roe = f.get("roe")
        if roe and roe > 0.15:
            signals.append(Signal("ROE", +1, f"ROE={roe*100:.1f}% 資本効率が高い"))

        # ── 52週高値からの乖離 ────────────────────────────────
        from_high = f.get("from_52w_high")
        if from_high and from_high < -30:
            signals.append(Signal("Price", +1,
                f"高値から{from_high:.1f}% 下落 → 割安感あり（逆張り機会）"))

        # ── マクロニュース ────────────────────────────────────
        ms = macro.get("score", 0)
        if ms >= 3:
            signals.append(Signal("Macro", +2, f"マクロニュース強ポジティブ(+{ms})"))
        elif ms >= 1:
            signals.append(Signal("Macro", +1, f"マクロニュースやや強気(+{ms})"))
        elif ms <= -3:
            signals.append(Signal("Macro", -2, f"マクロニュース強ネガティブ({ms})"))
        elif ms <= -1:
            signals.append(Signal("Macro", -1, f"マクロニュースやや弱気({ms})"))

        # ── 総合ファンダスコア ────────────────────────────────
        fund_score = scores.get(primary, 0)
        if fund_score >= 5:
            signals.append(Signal("Overall", +2, f"{primary} 総合ファンダスコア={fund_score} 優良株"))
        elif fund_score >= 3:
            signals.append(Signal("Overall", +1, f"{primary} 総合ファンダスコア={fund_score} 良好"))
        elif fund_score <= 0:
            signals.append(Signal("Overall", -1, f"{primary} 総合ファンダスコア={fund_score} 要注意"))

        # ── スコア合算（学習済みウェイト適用）────────────────
        total = sum(
            s.score * self.SIGNAL_WEIGHTS.get(s.name, 1.0)
            for s in signals
        )

        if total >= self.BUY_THRESHOLD:
            decision: Decision = "BUY"
            confidence = min(1.0, total / max(len(signals), 1))
        elif total <= self.SELL_THRESHOLD:
            decision = "SELL"
            confidence = min(1.0, abs(total) / max(len(signals), 1))
        else:
            decision = "HOLD"
            confidence = 0.5

        risk = "LOW" if abs(total) >= 6 else ("MEDIUM" if abs(total) >= 4 else "HIGH")
        reasoning = f"合計スコア:{total:+.1f} → {decision} | " + " | ".join(s.reason for s in signals)

        return {
            "decision":    decision,
            "confidence":  round(confidence, 2),
            "reasoning":   reasoning,
            "risk_level":  risk,
            "total_score": round(total, 2),
            "signals":     [{"name": s.name, "score": s.score, "reason": s.reason}
                            for s in signals],
            "recommended": primary,
        }
