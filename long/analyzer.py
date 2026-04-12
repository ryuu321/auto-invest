"""
長期投資 分析モジュール
ファンダメンタルズ + 世界情勢で判断
バフェット流：良い企業を適正価格で買う
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
    score: int
    reason: str


class LongTermAnalyzer:
    """
    長期スコアリング（しきい値は学習により自動調整）

    BUY  : score >= +4 (default)（慎重に・確信が高いときだけ）
    SELL : score <= -4 (default)
    HOLD : -3 〜 +3

    長期なので閾値は最も高い
    """

    def __init__(self):
        t = load_thresholds("LONG")
        self.BUY_THRESHOLD  = t["buy_threshold"]
        self.SELL_THRESHOLD = t["sell_threshold"]

    def analyze(self, market_data: dict) -> dict:
        signals = []
        scores    = market_data.get("scores", {})
        funds     = market_data.get("fundamentals", {})
        macro     = market_data.get("macro_news", {})
        primary   = market_data.get("primary_ticker", "AAPL")
        f         = funds.get(primary, {})

        # ── ファンダメンタルズ（主指標）──────────────────────
        pe = f.get("pe_ratio")
        if pe:
            if pe < 15:
                signals.append(Signal("PE", +2, f"PER={pe:.1f} 割安（<15）→ 強買いシグナル"))
            elif pe < 25:
                signals.append(Signal("PE", +1, f"PER={pe:.1f} 適正（15〜25）"))
            elif pe > 40:
                signals.append(Signal("PE", -2, f"PER={pe:.1f} 割高（>40）→ 売りシグナル"))
            else:
                signals.append(Signal("PE",  0, f"PER={pe:.1f} やや高め"))

        # 売上成長率
        rg = f.get("revenue_growth")
        if rg is not None:
            if rg > 0.20:
                signals.append(Signal("Revenue", +2, f"売上成長率={rg*100:.1f}% 高成長（>20%）"))
            elif rg > 0.10:
                signals.append(Signal("Revenue", +1, f"売上成長率={rg*100:.1f}% 成長中"))
            elif rg < 0:
                signals.append(Signal("Revenue", -2, f"売上成長率={rg*100:.1f}% 減収 → 注意"))

        # 利益率
        margin = f.get("profit_margin")
        if margin and margin > 0.20:
            signals.append(Signal("Margin", +1, f"利益率={margin*100:.1f}% 高収益企業"))
        elif margin and margin < 0.05:
            signals.append(Signal("Margin", -1, f"利益率={margin*100:.1f}% 低収益"))

        # 負債比率
        dte = f.get("debt_to_equity")
        if dte is not None:
            if dte < 50:
                signals.append(Signal("Debt", +1, f"D/E={dte:.0f} 低負債 → 財務健全"))
            elif dte > 200:
                signals.append(Signal("Debt", -1, f"D/E={dte:.0f} 高負債 → リスク"))

        # 52週高値からの乖離
        from_high = f.get("from_52w_high")
        if from_high and from_high < -30:
            signals.append(Signal("Price", +1, f"高値から{from_high:.1f}% 下落 → 割安感あり"))

        # ── 世界情勢・マクロ ──────────────────────────────
        ms = macro.get("score", 0)
        if ms >= 3:
            signals.append(Signal("Macro", +2, f"マクロニュース強ポジティブ(+{ms}) → 投資環境良好"))
        elif ms >= 1:
            signals.append(Signal("Macro", +1, f"マクロニュースやや強気(+{ms})"))
        elif ms <= -3:
            signals.append(Signal("Macro", -2, f"マクロニュース強ネガティブ({ms}) → 投資環境悪化"))
        elif ms <= -1:
            signals.append(Signal("Macro", -1, f"マクロニュースやや弱気({ms})"))

        # ── 総合ファンダスコア ────────────────────────────
        fund_score = scores.get(primary, 0)
        if fund_score >= 5:
            signals.append(Signal("Overall", +2, f"{primary} 総合ファンダスコア={fund_score} 優良株"))
        elif fund_score >= 3:
            signals.append(Signal("Overall", +1, f"{primary} 総合ファンダスコア={fund_score} 良好"))
        elif fund_score <= 0:
            signals.append(Signal("Overall", -1, f"{primary} 総合ファンダスコア={fund_score} 要注意"))

        total = sum(s.score for s in signals)

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
        reasoning = f"合計スコア:{total:+d} → {decision} | " + " | ".join(s.reason for s in signals)

        return {
            "decision":     decision,
            "confidence":   round(confidence, 2),
            "reasoning":    reasoning,
            "risk_level":   risk,
            "total_score":  total,
            "signals":      [{"name": s.name, "score": s.score, "reason": s.reason} for s in signals],
            "recommended":  primary,
        }
