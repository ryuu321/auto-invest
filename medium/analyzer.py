"""
中期投資 分析モジュール
移動平均・トレンド・ゴールデンクロスで判断
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


class MediumTermAnalyzer:
    """
    中期スコアリング（しきい値は学習により自動調整）

    BUY  : score >= +3 (default)
    SELL : score <= -3 (default)
    HOLD : -2 〜 +2

    短期より閾値が高い（慎重に動く）
    """

    def __init__(self):
        t = load_thresholds("MEDIUM")
        self.BUY_THRESHOLD   = t["buy_threshold"]
        self.SELL_THRESHOLD  = t["sell_threshold"]
        self.SIGNAL_WEIGHTS  = t.get("signal_weights", {})

    def analyze(self, market_data: dict) -> dict:
        signals = []
        assets  = market_data.get("assets", {})
        primary = market_data.get("primary_ticker", "BTC-USD")
        tech    = assets.get(primary, {})
        fg      = market_data.get("fear_greed", {}) or {}
        news    = market_data.get("news_sentiment", {})

        # ── ゴールデンクロス / デスクロス（強シグナル）────────
        if tech.get("golden_cross"):
            signals.append(Signal("GoldenCross", +2, f"{primary}: 50MA が 200MA を上抜け → ゴールデンクロス（強買い）"))
        elif tech.get("death_cross"):
            signals.append(Signal("DeathCross", -2, f"{primary}: 50MA が 200MA を下抜け → デスクロス（強売り）"))

        # ── 価格と移動平均の位置 ──────────────────────────────
        if tech.get("above_ma200") is True:
            signals.append(Signal("AboveMA200", +1, f"価格が200MA上 → 長期上昇トレンド中"))
        elif tech.get("above_ma200") is False:
            signals.append(Signal("BelowMA200", -1, f"価格が200MA下 → 長期下降トレンド中"))

        if tech.get("above_ma50") is True:
            signals.append(Signal("AboveMA50", +1, f"価格が50MA上 → 中期上昇トレンド中"))
        elif tech.get("above_ma50") is False:
            signals.append(Signal("BelowMA50", -1, f"価格が50MA下 → 中期下降トレンド中"))

        # ── RSI（週足ベースなので閾値を少し緩める）───────────
        rsi = tech.get("rsi")
        if rsi is not None:
            if rsi < 35:
                signals.append(Signal("RSI", +1, f"RSI={rsi:.1f} 売られすぎ（中期基準<35）"))
            elif rsi > 65:
                signals.append(Signal("RSI", -1, f"RSI={rsi:.1f} 買われすぎ（中期基準>65）"))
            else:
                signals.append(Signal("RSI", 0, f"RSI={rsi:.1f} 中立"))

        # ── 株式市場のトレンド（SPY・QQQ）────────────────────
        spy = assets.get("SPY", {})
        if spy.get("above_ma50") is True:
            signals.append(Signal("SPY", +1, f"S&P500が50MA上 → 市場全体上昇トレンド"))
        elif spy.get("above_ma50") is False:
            signals.append(Signal("SPY", -1, f"S&P500が50MA下 → 市場全体下降トレンド"))

        # ── Fear & Greed ────────────────────────────────────
        fg_val = fg.get("value")
        if fg_val is not None:
            if fg_val <= 30:
                signals.append(Signal("FearGreed", +1, f"F&G={fg_val}（恐怖圏）→ 中期買い検討"))
            elif fg_val >= 70:
                signals.append(Signal("FearGreed", -1, f"F&G={fg_val}（強欲圏）→ 中期売り検討"))

        # ── ニュース ───────────────────────────────────────
        ns = news.get("score", 0)
        if ns >= 4:
            signals.append(Signal("News", +1, f"ニュース強ポジティブ(+{ns})"))
        elif ns <= -4:
            signals.append(Signal("News", -1, f"ニュース強ネガティブ({ns})"))

        total = sum(
            s.score * self.SIGNAL_WEIGHTS.get(s.name, 1.0)
            for s in signals
        )

        if total >= self.BUY_THRESHOLD:
            decision: Decision = "BUY"
            confidence = min(1.0, total / (len(signals) or 1))
        elif total <= self.SELL_THRESHOLD:
            decision = "SELL"
            confidence = min(1.0, abs(total) / (len(signals) or 1))
        else:
            decision = "HOLD"
            confidence = 0.5

        risk = "LOW" if abs(total) >= 5 else ("MEDIUM" if abs(total) >= 3 else "HIGH")
        reasoning = f"合計スコア:{total:+d} → {decision} | " + " | ".join(s.reason for s in signals)

        return {
            "decision":   decision,
            "confidence": round(confidence, 2),
            "reasoning":  reasoning,
            "risk_level": risk,
            "total_score": total,
            "signals":    [{"name": s.name, "score": s.score, "reason": s.reason} for s in signals],
        }
