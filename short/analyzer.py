"""
ルールベース市場分析モジュール
APIキー不要・完全無料
感情や推測は一切使わない。数値とルールだけで判断する。
"""

from dataclasses import dataclass
from typing import Literal

Decision = Literal["BUY", "SELL", "HOLD"]


@dataclass
class Signal:
    name: str
    value: float
    score: int       # +1=買いシグナル / -1=売りシグナル / 0=中立
    reason: str


class RuleBasedAnalyzer:
    """
    スコアリングシステム
    各指標がシグナルを出し、合計スコアで判断する
    learner.pyが蓄積したデータをもとに閾値を自動調整する
    """

    def __init__(self):
        import sys
        from pathlib import Path as _Path
        sys.path.insert(0, str(_Path(__file__).parent.parent / "shared"))
        try:
            from learner import load_thresholds
            t = load_thresholds("SHORT")
        except Exception:
            t = {}
        self.RSI_OVERSOLD    = t.get("rsi_oversold",   30.0)
        self.RSI_OVERBOUGHT  = t.get("rsi_overbought", 70.0)
        self.FG_BUY          = t.get("fear_greed_buy",  25)
        self.FG_SELL         = t.get("fear_greed_sell", 75)
        self.NEWS_POS        = t.get("news_positive",    3)
        self.NEWS_NEG        = t.get("news_negative",   -3)
        self.BUY_THRESHOLD   = t.get("buy_threshold",   2)
        self.SELL_THRESHOLD  = t.get("sell_threshold", -2)
        self.SIGNAL_WEIGHTS  = t.get("signal_weights", {})

    def analyze(self, market_data: dict) -> dict:
        technicals = market_data.get("technicals", {})
        fear_greed = market_data.get("fear_greed", {})
        news_sentiment = market_data.get("news_sentiment", {})

        signals = []

        # ── RSI ──────────────────────────────────────────
        rsi = technicals.get("rsi")
        if rsi is not None:
            if rsi < self.RSI_OVERSOLD:
                signals.append(Signal("RSI", rsi, +1, f"RSI={rsi:.1f} 売られすぎ（<{self.RSI_OVERSOLD}）→ 買いシグナル"))
            elif rsi > self.RSI_OVERBOUGHT:
                signals.append(Signal("RSI", rsi, -1, f"RSI={rsi:.1f} 買われすぎ（>{self.RSI_OVERBOUGHT}）→ 売りシグナル"))
            else:
                signals.append(Signal("RSI", rsi,  0, f"RSI={rsi:.1f} 中立ゾーン（{self.RSI_OVERSOLD}〜{self.RSI_OVERBOUGHT}）"))

        # ── MACD ─────────────────────────────────────────
        macd = technicals.get("macd")
        macd_signal = technicals.get("macd_signal")
        if macd is not None and macd_signal is not None:
            if macd > macd_signal:
                signals.append(Signal("MACD", macd, +1, f"MACD({macd:.4f}) > シグナル({macd_signal:.4f}) → 上昇トレンド"))
            else:
                signals.append(Signal("MACD", macd, -1, f"MACD({macd:.4f}) < シグナル({macd_signal:.4f}) → 下降トレンド"))

        # ── ボリンジャーバンド ────────────────────────────
        price   = technicals.get("current_price")
        bb_upper = technicals.get("bb_upper")
        bb_lower = technicals.get("bb_lower")
        if price and bb_upper and bb_lower:
            if price <= bb_lower:
                signals.append(Signal("BB", price, +1, f"価格(${price:,.0f}) ≤ 下限(${bb_lower:,.0f}) → 売られすぎ"))
            elif price >= bb_upper:
                signals.append(Signal("BB", price, -1, f"価格(${price:,.0f}) ≥ 上限(${bb_upper:,.0f}) → 買われすぎ"))
            else:
                signals.append(Signal("BB", price,  0, f"価格(${price:,.0f}) バンド内 → 中立"))

        # ── Fear & Greed Index ───────────────────────────
        fg_value = fear_greed.get("value") if fear_greed else None
        if fg_value is not None:
            if fg_value <= self.FG_BUY:
                signals.append(Signal("FearGreed", fg_value, +1, f"Fear&Greed={fg_value}（極端な恐怖）→ 歴史的に買い場"))
            elif fg_value >= self.FG_SELL:
                signals.append(Signal("FearGreed", fg_value, -1, f"Fear&Greed={fg_value}（極端な強欲）→ 過熱サイン"))
            else:
                signals.append(Signal("FearGreed", fg_value,  0, f"Fear&Greed={fg_value} 中立ゾーン"))

        # ── ニュースセンチメント（キーワードスコア）───────
        news_score = news_sentiment.get("score", 0)
        news_count = news_sentiment.get("count", 0)
        if news_count > 0:
            if news_score >= self.NEWS_POS:
                signals.append(Signal("News", news_score, +1, f"ニュース: ポジティブワード+{news_score}件"))
            elif news_score <= self.NEWS_NEG:
                signals.append(Signal("News", news_score, -1, f"ニュース: ネガティブワード{news_score}件"))
            else:
                signals.append(Signal("News", news_score,  0, f"ニュース: 中立（スコア={news_score}）"))

        # ── 合計スコアで判断（学習済み重みを適用）────────────
        total_score = sum(
            s.score * self.SIGNAL_WEIGHTS.get(s.name, 1.0)
            for s in signals
        )

        if total_score >= self.BUY_THRESHOLD:
            decision: Decision = "BUY"
            confidence = min(1.0, total_score / (len(signals) or 1))
        elif total_score <= self.SELL_THRESHOLD:
            decision = "SELL"
            confidence = min(1.0, abs(total_score) / (len(signals) or 1))
        else:
            decision = "HOLD"
            confidence = 0.5

        # リスクレベル（シグナルの一致度で判定）
        if abs(total_score) >= 4:
            risk_level = "LOW"      # シグナルが強く一致 → 確信高い
        elif abs(total_score) >= 2:
            risk_level = "MEDIUM"
        else:
            risk_level = "HIGH"     # シグナルが混在 → 不確実

        reasoning = self._build_reasoning(signals, total_score, decision)

        return {
            "decision": decision,
            "confidence": round(confidence, 2),
            "reasoning": reasoning,
            "risk_level": risk_level,
            "total_score": total_score,
            "signals": [{"name": s.name, "score": s.score, "reason": s.reason} for s in signals],
        }

    def _build_reasoning(self, signals: list[Signal], total_score: int, decision: Decision) -> str:
        lines = [f"合計スコア: {total_score:+d} → {decision}"]
        for s in signals:
            mark = "↑" if s.score > 0 else ("↓" if s.score < 0 else "→")
            lines.append(f"  {mark} {s.reason}")
        return " | ".join(lines)
