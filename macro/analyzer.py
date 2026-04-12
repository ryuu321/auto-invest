"""
マクロ予測ボット — 分析モジュール

「今の相場」ではなく「6〜18ヶ月後の相場」を先行指標で推定し、
経済サイクルに乗る形でポジションを取る。

出口ルール（価格ベース）は持たない。
売るのは「マクロテーゼが崩れたとき」だけ。
  - 経済フェーズが CONTRACTION 以下になったとき
  - イールドカーブが深く逆転したとき（spread < -0.3%）
  - 地政学スコアが極端に悪化したとき（<= -12）
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "shared"))

from dataclasses import dataclass
from typing import Literal
from learner import load_thresholds

Decision = Literal["BUY", "SELL", "HOLD"]

# マクロテーゼ崩壊の閾値
THESIS_BREAK_PHASES  = {"CONTRACTION", "SEVERE_CONTRACTION"}
YIELD_INVERSION_DEEP = -0.003   # -0.3% を超える深い逆転
GEO_CATASTROPHE      = -12      # 地政学スコアがこれ以下 = 重大ショック


@dataclass
class Signal:
    name: str
    score: float
    reason: str


class MacroAnalyzer:
    """
    経済サイクルベースの買い判断 + テーゼ崩壊による売り判断。
    価格が上がっても売らない。テーゼが壊れたら売る。
    """

    def __init__(self):
        t = load_thresholds("MACRO")
        self.BUY_THRESHOLD  = t["buy_threshold"]
        self.SELL_THRESHOLD = t["sell_threshold"]
        self.SIGNAL_WEIGHTS = t.get("signal_weights", {})

    def check_thesis_breakdown(self, market_data: dict) -> tuple[bool, str]:
        """
        マクロテーゼが崩れているかチェックする。
        崩れている場合 → 全ポジション売り。
        価格がいくら下がっていても関係ない（それはノイズ）。
        テーゼが崩れた = 投資の前提が変わった = 撤退。
        """
        cycle     = market_data.get("economic_cycle", {})
        macro_ind = market_data.get("macro_indicators", {})
        geo       = market_data.get("geo_political", {})

        phase     = cycle.get("phase", "UNKNOWN")
        geo_score = geo.get("score", 0)
        spread    = macro_ind.get("yield_curve_spread", 0)

        reasons = []

        if phase in THESIS_BREAK_PHASES:
            reasons.append(f"経済フェーズ={phase}: 先行指標が景気後退を示す")

        if spread is not None and spread < YIELD_INVERSION_DEEP:
            reasons.append(f"イールドカーブ深い逆転 (spread={spread:.3f}%) → 景気後退確率が高い")

        if geo_score <= GEO_CATASTROPHE:
            reasons.append(f"地政学スコア極端悪化 ({geo_score}) → 重大ショック発生")

        if reasons:
            return True, " / ".join(reasons)

        return False, ""

    def analyze(self, market_data: dict) -> dict:
        signals   = []
        cycle     = market_data.get("economic_cycle", {})
        macro_ind = market_data.get("macro_indicators", {})
        geo       = market_data.get("geo_political", {})
        funds     = market_data.get("fundamentals", {})
        scores    = market_data.get("scores", {})
        primary   = market_data.get("primary_ticker", "AAPL")

        cycle_phase = cycle.get("phase", "UNKNOWN")

        # ── マクロテーゼ崩壊チェック（売り優先）─────────────
        thesis_broken, thesis_reason = self.check_thesis_breakdown(market_data)
        if thesis_broken:
            return {
                "decision":         "SELL",
                "confidence":       0.95,
                "reasoning":        f"マクロテーゼ崩壊: {thesis_reason}",
                "risk_level":       "LOW",
                "total_score":      -99,
                "cycle_phase":      cycle_phase,
                "cycle_action":     cycle.get("action", ""),
                "recommended_etfs": cycle.get("recommended_etfs", []),
                "thesis_broken":    True,
                "thesis_reason":    thesis_reason,
                "signals":          [{"name": "ThesisBreak", "score": -99, "reason": thesis_reason}],
                "recommended":      primary,
            }

        # ── 買い判断: 経済サイクルがいい局面か ─────────────
        if cycle_phase == "EARLY_EXPANSION":
            signals.append(Signal("CyclePhase", +4,
                f"経済サイクル: {cycle.get('label')} → 最も買いやすいフェーズ"))
        elif cycle_phase == "MID_EXPANSION":
            signals.append(Signal("CyclePhase", +3,
                f"経済サイクル: {cycle.get('label')} → 成長継続。保有継続・追加投資を検討"))
        elif cycle_phase == "LATE_EXPANSION":
            signals.append(Signal("CyclePhase", +1,
                f"経済サイクル: {cycle.get('label')} → 過熱注意。新規は慎重に"))
        elif cycle_phase == "CONTRACTION":
            signals.append(Signal("CyclePhase", -4,
                f"経済サイクル: {cycle.get('label')} → 退避フェーズ（テーゼ崩壊で別途判断）"))
        else:
            signals.append(Signal("CyclePhase", 0, f"経済サイクル: {cycle_phase} 判定不能"))

        # ── イールドカーブ ────────────────────────────────
        if macro_ind.get("yield_curve_steepening") and not macro_ind.get("yield_curve_inverted"):
            signals.append(Signal("YieldCurve", +2,
                "イールドカーブ スティープニング → 回復/拡張への移行シグナル"))
        elif macro_ind.get("yield_curve_inverted"):
            spread = macro_ind.get("yield_curve_spread", 0)
            signals.append(Signal("YieldCurve", -2,
                f"イールドカーブ逆転中 (spread={spread:.3f}%) → 後退リスク"))

        # ── VIX ──────────────────────────────────────────
        vix_regime = macro_ind.get("vix_regime", "NORMAL")
        vix        = macro_ind.get("vix", 20)
        if vix_regime == "PANIC":
            # パニック局面 = 逆張りの仕込み機会（ただしフェーズ次第）
            signals.append(Signal("VIX", +1,
                f"VIX={vix} パニック水準 → 長期投資家にとっての逆張り仕込みポイント"))
        elif vix_regime == "COMPLACENT":
            signals.append(Signal("VIX", -1,
                f"VIX={vix} 過度な楽観 → 相場の脆弱性に注意"))
        elif vix_regime == "NORMAL":
            signals.append(Signal("VIX", +1, f"VIX={vix} 正常水準 → 安定"))

        # ── クレジットスプレッド ──────────────────────────
        if macro_ind.get("credit_spread_tightening"):
            signals.append(Signal("CreditSpread", +2,
                "クレジットスプレッド縮小 → 機関投資家のリスク許容度上昇"))
        elif macro_ind.get("credit_stress"):
            signals.append(Signal("CreditSpread", -2,
                "クレジットスプレッド拡大 → 信用リスク上昇"))

        # ── 地政学リスク ──────────────────────────────────
        geo_score = geo.get("score", 0)
        if geo_score >= 5:
            signals.append(Signal("GeoRisk", +2,
                f"地政学・マクロニュース非常に強気 (スコア={geo_score:+d})"))
        elif geo_score >= 2:
            signals.append(Signal("GeoRisk", +1,
                f"地政学・マクロニュース強気 (スコア={geo_score:+d})"))
        elif geo_score <= -5:
            signals.append(Signal("GeoRisk", -2,
                f"地政学リスク高 (スコア={geo_score:+d}) → 重大な不確実性"))
        elif geo_score <= -2:
            signals.append(Signal("GeoRisk", -1,
                f"地政学リスク上昇中 (スコア={geo_score:+d})"))

        # ── ファンダメンタルズ（銘柄選択補助）───────────────
        f          = funds.get(primary, {})
        fund_score = scores.get(primary, 0)
        rg         = f.get("revenue_growth")

        if fund_score >= 5:
            signals.append(Signal("Fundamentals", +2,
                f"{primary} ファンダスコア={fund_score} 優良株 → 長期保有に値する"))
        elif fund_score >= 3:
            signals.append(Signal("Fundamentals", +1,
                f"{primary} ファンダスコア={fund_score} 良好"))
        elif fund_score <= 0:
            signals.append(Signal("Fundamentals", -1,
                f"{primary} ファンダスコア={fund_score} 改善が必要"))

        if rg and rg > 0.15:
            signals.append(Signal("Revenue", +1,
                f"売上成長率={rg*100:.1f}% → 長期保有中も事業は拡大中"))

        # ── スコア合算 ────────────────────────────────────
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

        risk = "LOW" if abs(total) >= 8 else ("MEDIUM" if abs(total) >= 5 else "HIGH")

        cycle_action = cycle.get("action", "")
        reasoning = (
            f"合計スコア:{total:+.1f} → {decision} | "
            f"フェーズ:{cycle_phase} | {cycle_action} | " +
            " | ".join(s.reason for s in signals if s.score != 0)
        )

        return {
            "decision":         decision,
            "confidence":       round(confidence, 2),
            "reasoning":        reasoning,
            "risk_level":       risk,
            "total_score":      round(total, 2),
            "cycle_phase":      cycle_phase,
            "cycle_action":     cycle_action,
            "recommended_etfs": cycle.get("recommended_etfs", []),
            "thesis_broken":    False,
            "thesis_reason":    "",
            "signals":          [{"name": s.name, "score": s.score, "reason": s.reason}
                                  for s in signals],
            "recommended":      primary,
        }
