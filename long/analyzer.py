"""
長期投資 分析モジュール — 先回り予測対応版

分析の優先順位:
  1. 経済サイクルフェーズ（最重要）— 先行指標が「6〜18ヶ月後」を示す
  2. マクロ環境（イールドカーブ・VIX・クレジット・ドル・金）
  3. 地政学リスク
  4. ファンダメンタルズ（銘柄選択の補助）

「今の数字」より「今のシグナルが示す未来」を重視する。
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
    長期スコアリング（先行指標ベース、学習済みウェイト適用）
    """

    def __init__(self):
        t = load_thresholds("LONG")
        self.BUY_THRESHOLD  = t["buy_threshold"]
        self.SELL_THRESHOLD = t["sell_threshold"]
        self.SIGNAL_WEIGHTS = t.get("signal_weights", {})

    def analyze(self, market_data: dict) -> dict:
        signals   = []
        funds     = market_data.get("fundamentals", {})
        scores    = market_data.get("scores", {})
        cycle     = market_data.get("economic_cycle", {})
        macro_ind = market_data.get("macro_indicators", {})
        geo       = market_data.get("geo_political", market_data.get("macro_news", {}))
        primary   = market_data.get("primary_ticker", "AAPL")

        # ══════════════════════════════════════════════════════════════
        # TIER 1: 経済サイクル（先行指標の合成・最重要）
        # ══════════════════════════════════════════════════════════════
        cycle_phase = cycle.get("phase", "UNKNOWN")
        cycle_score = cycle.get("score", 0)

        if cycle_phase == "EARLY_EXPANSION":
            signals.append(Signal("CyclePhase", +3, f"経済サイクル: {cycle.get('label')} → 株式積極投資フェーズ"))
        elif cycle_phase == "MID_EXPANSION":
            signals.append(Signal("CyclePhase", +2, f"経済サイクル: {cycle.get('label')} → テック・工業株が有利"))
        elif cycle_phase == "LATE_EXPANSION":
            signals.append(Signal("CyclePhase", +1, f"経済サイクル: {cycle.get('label')} → 過熱注意。セクター移動を検討"))
        elif cycle_phase == "CONTRACTION":
            signals.append(Signal("CyclePhase", -3, f"経済サイクル: {cycle.get('label')} → ディフェンシブ退避フェーズ"))
        elif cycle_phase == "SEVERE_CONTRACTION":
            signals.append(Signal("CyclePhase", -4, f"経済サイクル: {cycle.get('label')} → 現金保全。新規投資は見送り"))

        # 推奨セクター情報をシグナルに含める
        rec_etfs = cycle.get("recommended_etfs", [])
        if rec_etfs:
            signals.append(Signal("SectorRec", 0,
                f"推奨セクターETF: {', '.join(rec_etfs)} (現フェーズ={cycle_phase})"))

        # ══════════════════════════════════════════════════════════════
        # TIER 2: 個別マクロ先行指標
        # ══════════════════════════════════════════════════════════════

        # イールドカーブ（景気後退の最強先行シグナル）
        if macro_ind.get("yield_curve_inverted"):
            spread = macro_ind.get("yield_curve_spread", 0)
            signals.append(Signal("YieldCurve", -3,
                f"イールドカーブ逆転 (10Y-3M={spread:.3f}%) → 過去の逆転は全て景気後退に先行"))
        elif macro_ind.get("yield_curve_steepening"):
            signals.append(Signal("YieldCurve", +2,
                f"イールドカーブ スティープニング → 回復/拡張局面への移行シグナル"))
        else:
            signals.append(Signal("YieldCurve", 0, "イールドカーブ フラット化 → 拡張終盤の可能性"))

        # VIX
        vix_regime = macro_ind.get("vix_regime", "NORMAL")
        vix        = macro_ind.get("vix", 20)
        if vix_regime == "PANIC":
            signals.append(Signal("VIX", -2,
                f"VIX={vix} パニック水準 → 強制売りリスク。ただし逆張り底打ちの可能性も"))
        elif vix_regime == "HIGH":
            signals.append(Signal("VIX", -1, f"VIX={vix} 高水準 → リスク回避継続"))
        elif vix_regime == "COMPLACENT":
            signals.append(Signal("VIX", -1,
                f"VIX={vix} 過度な楽観水準 → 相場調整リスク高まる（バブル的兆候）"))
        else:
            signals.append(Signal("VIX", +1, f"VIX={vix} 正常水準 → 安定した投資環境"))

        # クレジットスプレッド
        if macro_ind.get("credit_stress"):
            chg = macro_ind.get("credit_spread_change_pct", 0)
            signals.append(Signal("CreditSpread", -3,
                f"クレジットスプレッド拡大 ({chg:+.1f}%) → 機関投資家がリスク資産を手放している"))
        elif macro_ind.get("credit_spread_tightening"):
            signals.append(Signal("CreditSpread", +2,
                "クレジットスプレッド縮小 → 機関投資家のリスク許容度上昇。強気相場継続"))

        # ドル動向
        dollar    = macro_ind.get("dollar_trend", "NEUTRAL")
        dollar_chg = macro_ind.get("dollar_change_pct", 0)
        if dollar == "STRONG":
            signals.append(Signal("Dollar", -1,
                f"ドル高 ({dollar_chg:+.1f}%) → 米国外株・コモディティ・新興国に逆風"))
        elif dollar == "WEAK":
            signals.append(Signal("Dollar", +1,
                f"ドル安 ({dollar_chg:+.1f}%) → 国際分散・コモディティ追い風"))

        # 金トレンド（インフレ・有事プレミアム）
        gold_trend = macro_ind.get("gold_trend", "FLAT")
        gold_chg   = macro_ind.get("gold_change_pct", 0)
        if gold_trend == "SURGING":
            signals.append(Signal("Gold", -2,
                f"金急騰 (+{gold_chg:.1f}%) → 深刻な地政学リスクまたはスタグフレーション懸念"))
        elif gold_trend == "UP":
            signals.append(Signal("Gold", -1,
                f"金上昇 (+{gold_chg:.1f}%) → 不確実性上昇中"))

        # リスクオフシグナル（TLT上昇・SPY下落）
        if macro_ind.get("risk_off_signal"):
            signals.append(Signal("RiskOff", -3,
                "TLT上昇・SPY下落 → 機関投資家が株から債券へ移動。大規模リスクオフ進行中"))

        # ══════════════════════════════════════════════════════════════
        # TIER 3: 地政学リスク
        # ══════════════════════════════════════════════════════════════
        geo_score = geo.get("score", 0)
        event_tags = geo.get("event_tags", [])
        if geo_score >= 5:
            signals.append(Signal("GeoRisk", +2, f"地政学・マクロニュース非常に強気 (スコア={geo_score:+d})"))
        elif geo_score >= 2:
            signals.append(Signal("GeoRisk", +1, f"地政学・マクロニュース強気 (スコア={geo_score:+d})"))
        elif geo_score <= -5:
            signals.append(Signal("GeoRisk", -3,
                f"地政学リスク非常に高 (スコア={geo_score:+d}) → 重大な貿易/安全保障リスク検出"))
        elif geo_score <= -2:
            signals.append(Signal("GeoRisk", -1, f"地政学リスク上昇中 (スコア={geo_score:+d})"))

        # ══════════════════════════════════════════════════════════════
        # TIER 4: ファンダメンタルズ（銘柄の質確認）
        # ══════════════════════════════════════════════════════════════
        f = funds.get(primary, {})

        pe  = f.get("pe_ratio")
        fpe = f.get("forward_pe")
        if pe:
            if pe < 15:
                signals.append(Signal("PE", +2, f"PER={pe:.1f} 割安（<15）→ バリュー投資機会"))
            elif pe < 25:
                signals.append(Signal("PE", +1, f"PER={pe:.1f} 適正（15〜25）"))
            elif pe > 40:
                signals.append(Signal("PE", -2, f"PER={pe:.1f} 割高（>40）→ 金利上昇局面でリスク大"))
            if fpe and pe and fpe < pe * 0.8:
                signals.append(Signal("ForwardPE", +1,
                    f"予想PER={fpe:.1f} < 実績{pe:.1f} → 利益成長加速の期待"))

        rg = f.get("revenue_growth")
        if rg is not None:
            if rg > 0.20:
                signals.append(Signal("Revenue", +2, f"売上成長率={rg*100:.1f}% 高成長（>20%）"))
            elif rg > 0.10:
                signals.append(Signal("Revenue", +1, f"売上成長率={rg*100:.1f}% 成長継続"))
            elif rg < 0:
                signals.append(Signal("Revenue", -2, f"売上成長率={rg*100:.1f}% 減収 → 警戒"))

        margin = f.get("profit_margin")
        if margin:
            if margin > 0.20:
                signals.append(Signal("Margin", +1, f"利益率={margin*100:.1f}% 高収益企業"))
            elif margin < 0.05:
                signals.append(Signal("Margin", -1, f"利益率={margin*100:.1f}% 低収益"))

        dte = f.get("debt_to_equity")
        if dte is not None:
            if dte < 50:
                signals.append(Signal("Debt", +1, f"D/E={dte:.0f} 財務健全（金利上昇に耐性あり）"))
            elif dte > 200:
                signals.append(Signal("Debt", -2,
                    f"D/E={dte:.0f} 高負債 → 金利上昇局面では特に危険"))

        fund_score = scores.get(primary, 0)
        if fund_score >= 5:
            signals.append(Signal("OverallFund", +2, f"{primary} 総合ファンダスコア={fund_score} 優良株"))
        elif fund_score >= 3:
            signals.append(Signal("OverallFund", +1, f"{primary} 総合ファンダスコア={fund_score} 良好"))
        elif fund_score <= 0:
            signals.append(Signal("OverallFund", -1,
                f"{primary} 総合ファンダスコア={fund_score} 改善が必要"))

        # ══════════════════════════════════════════════════════════════
        # スコア合算（学習済みウェイトを適用）
        # ══════════════════════════════════════════════════════════════
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

        # ── 推奨アクション文を付加 ──────────────────────────
        cycle_action = cycle.get("action", "")
        reasoning = (
            f"合計スコア:{total:+.1f} → {decision} | "
            f"経済フェーズ:{cycle_phase} | "
            f"推奨:{cycle_action} | " +
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
            "recommended_etfs": rec_etfs,
            "signals":          [{"name": s.name, "score": s.score, "reason": s.reason}
                                  for s in signals],
            "recommended":      primary,
        }
