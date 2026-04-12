"""
マクロ予測ボット — データ収集モジュール

収集する情報:
  - マクロ先行指標（イールドカーブ・VIX・クレジット・ドル・金）
  - 地政学リスク（重み付きRSSスコアリング）
  - 経済サイクル判定
  - ファンダメンタルズ（サイクルに合った銘柄選択用）
"""
import sys
import math
import importlib.util
import yfinance as yf
import feedparser
from datetime import datetime
from pathlib import Path

# long/collector.py から get_fundamentals / score_fundamentals / WATCHLIST を明示的にロード
_long_collector_path = Path(__file__).parent.parent / "long" / "collector.py"
_spec = importlib.util.spec_from_file_location("long_collector", _long_collector_path)
_long_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_long_mod)

get_fundamentals   = _long_mod.get_fundamentals
score_fundamentals = _long_mod.score_fundamentals
WATCHLIST          = _long_mod.WATCHLIST

# ── 経済サイクル別・推奨セクターETF ──────────────────────────────────
CYCLE_SECTORS = {
    "EARLY_EXPANSION":    ["XLF", "XLK", "XLY"],
    "MID_EXPANSION":      ["XLK", "XLI", "XLB"],
    "LATE_EXPANSION":     ["XLE", "XLB", "XLV"],
    "CONTRACTION":        ["XLU", "XLP", "XLV"],
    "SEVERE_CONTRACTION": ["GLD", "TLT", "XLU"],
}

# ── ニュースソース ────────────────────────────────────────────────────
MACRO_RSS_SOURCES = [
    "https://feeds.reuters.com/reuters/businessNews",
    "https://feeds.reuters.com/reuters/technologyNews",
    "https://feeds.bbci.co.uk/news/business/rss.xml",
    "https://www.marketwatch.com/rss/marketpulse",
]

# 重み付きキーワード（カテゴリ別）
GEO_KEYWORDS = {
    "tariff":             -3,
    "trade war":          -4,
    "trade deal":         +3,
    "trade agreement":    +3,
    "sanction":           -2,
    "import ban":         -2,
    "export restriction": -2,
    "war":                -3,
    "invasion":           -4,
    "conflict":           -2,
    "ceasefire":          +2,
    "peace deal":         +3,
    "nuclear":            -4,
    "rate cut":           +3,
    "interest rate cut":  +3,
    "fed cut":            +3,
    "rate hike":          -2,
    "quantitative easing":+2,
    "stimulus":           +2,
    "taper":              -1,
    "recession":          -4,
    "gdp growth":         +2,
    "gdp contraction":    -3,
    "soft landing":       +3,
    "hard landing":       -3,
    "unemployment rise":  -2,
    "earnings beat":      +2,
    "earnings miss":      -2,
    "inflation":          -2,
    "stagflation":        -4,
    "ai regulation":      -1,
    "chip ban":           -3,
    "tech crackdown":     -2,
}


def get_macro_indicators() -> dict:
    """先行指標を収集する（6〜18ヶ月後を示す指標群）"""
    ind = {}

    # イールドカーブ（10年 - 3ヶ月）
    try:
        tnx = yf.Ticker("^TNX").history(period="3mo")["Close"]
        irx = yf.Ticker("^IRX").history(period="3mo")["Close"]
        if not tnx.empty and not irx.empty:
            y10 = float(tnx.iloc[-1]) / 100
            y3m = float(irx.iloc[-1]) / 100
            spread = round(y10 - y3m, 4)
            ind["yield_10y"]              = round(y10 * 100, 3)
            ind["yield_3m"]               = round(y3m * 100, 3)
            ind["yield_curve_spread"]     = spread
            ind["yield_curve_inverted"]   = spread < 0
            spread_3mo_ago = float(tnx.iloc[0]) / 100 - float(irx.iloc[0]) / 100
            ind["yield_curve_steepening"] = spread > spread_3mo_ago
            ind["yield_curve_trend"]      = "steepening" if spread > spread_3mo_ago else "flattening"
    except Exception as e:
        print(f"[macro/collector] イールドカーブ取得エラー: {e}")

    # VIX
    try:
        vix_hist = yf.Ticker("^VIX").history(period="1mo")["Close"]
        if not vix_hist.empty:
            vix_now = float(vix_hist.iloc[-1])
            vix_avg = float(vix_hist.mean())
            ind["vix"]         = round(vix_now, 2)
            ind["vix_avg_1mo"] = round(vix_avg, 2)
            ind["vix_rising"]  = vix_now > vix_avg
            if vix_now > 30:
                ind["vix_regime"] = "PANIC"
            elif vix_now > 20:
                ind["vix_regime"] = "HIGH"
            elif vix_now < 15:
                ind["vix_regime"] = "COMPLACENT"
            else:
                ind["vix_regime"] = "NORMAL"
    except Exception as e:
        print(f"[macro/collector] VIX取得エラー: {e}")

    # クレジットスプレッド（HYG vs LQD）
    try:
        hyg = yf.Ticker("HYG").history(period="3mo")["Close"]
        lqd = yf.Ticker("LQD").history(period="3mo")["Close"]
        if not hyg.empty and not lqd.empty:
            ratio_now = float(hyg.iloc[-1]) / float(lqd.iloc[-1])
            ratio_3mo = float(hyg.iloc[0])  / float(lqd.iloc[0])
            change    = (ratio_now - ratio_3mo) / ratio_3mo
            ind["credit_spread_change_pct"] = round(change * 100, 2)
            ind["credit_spread_tightening"] = change > 0.01
            ind["credit_stress"]            = change < -0.03
    except Exception as e:
        print(f"[macro/collector] クレジットスプレッド取得エラー: {e}")

    # ドル（UUP）
    try:
        uup = yf.Ticker("UUP").history(period="3mo")["Close"]
        if not uup.empty:
            uup_chg = (float(uup.iloc[-1]) - float(uup.iloc[0])) / float(uup.iloc[0]) * 100
            ind["dollar_change_pct"] = round(uup_chg, 2)
            ind["dollar_trend"] = "STRONG" if uup_chg > 2 else ("WEAK" if uup_chg < -2 else "NEUTRAL")
    except Exception as e:
        print(f"[macro/collector] ドル取得エラー: {e}")

    # 金（GLD）
    try:
        gld = yf.Ticker("GLD").history(period="3mo")["Close"]
        if not gld.empty:
            gld_chg = (float(gld.iloc[-1]) - float(gld.iloc[0])) / float(gld.iloc[0]) * 100
            ind["gold_change_pct"] = round(gld_chg, 2)
            if gld_chg > 5:
                ind["gold_trend"] = "SURGING"
            elif gld_chg > 2:
                ind["gold_trend"] = "UP"
            elif gld_chg < -2:
                ind["gold_trend"] = "DOWN"
            else:
                ind["gold_trend"] = "FLAT"
    except Exception as e:
        print(f"[macro/collector] 金取得エラー: {e}")

    # リスクオフシグナル（TLT vs SPY）
    try:
        spy = yf.Ticker("SPY").history(period="3mo")["Close"]
        tlt = yf.Ticker("TLT").history(period="3mo")["Close"]
        if not spy.empty and not tlt.empty:
            spy_chg = (float(spy.iloc[-1]) - float(spy.iloc[0])) / float(spy.iloc[0]) * 100
            tlt_chg = (float(tlt.iloc[-1]) - float(tlt.iloc[0])) / float(tlt.iloc[0]) * 100
            ind["spy_3mo_change_pct"] = round(spy_chg, 2)
            ind["tlt_3mo_change_pct"] = round(tlt_chg, 2)
            ind["risk_off_signal"]    = tlt_chg > 3 and spy_chg < -5
    except Exception as e:
        print(f"[macro/collector] SPY/TLT取得エラー: {e}")

    return ind


def get_geopolitical_score() -> dict:
    """重み付きキーワードで地政学・マクロリスクをスコアリング"""
    total_score = 0
    headlines   = []
    event_tags  = []

    for url in MACRO_RSS_SOURCES:
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries[:8]:
                title = entry.get("title", "").lower()
                raw   = entry.get("title", "")
                headlines.append(raw)
                for keyword, weight in GEO_KEYWORDS.items():
                    if keyword in title:
                        total_score += weight
                        if abs(weight) >= 3:
                            event_tags.append(f"[{'+' if weight>0 else ''}{weight}] {raw[:60]}")
        except Exception:
            pass

    return {
        "score":      total_score,
        "headlines":  headlines[:15],
        "event_tags": event_tags[:5],
        "label":      "positive" if total_score > 2 else ("negative" if total_score < -2 else "neutral"),
    }


def detect_economic_cycle(macro_ind: dict, geo_score: int) -> dict:
    """先行指標を合成して経済サイクルフェーズを推定する"""
    score   = 0
    signals = []

    if macro_ind.get("yield_curve_inverted"):
        spread = macro_ind.get("yield_curve_spread", 0)
        score -= 3
        signals.append(f"イールドカーブ逆転中 (スプレッド={spread:.3f}%) → 景気後退の先行シグナル")
    elif macro_ind.get("yield_curve_steepening"):
        score += 2
        signals.append("イールドカーブ スティープニング → 回復/拡張局面への移行")

    vix_regime = macro_ind.get("vix_regime", "NORMAL")
    vix        = macro_ind.get("vix", 20)
    if vix_regime == "PANIC":
        score -= 3
        signals.append(f"VIX={vix} パニック水準 → 強制売りリスク")
    elif vix_regime == "HIGH":
        score -= 1
        signals.append(f"VIX={vix} 高水準 → リスク回避傾向")
    elif vix_regime == "COMPLACENT":
        score -= 1
        signals.append(f"VIX={vix} 過度な楽観 → 相場の脆弱性")
    else:
        score += 1
        signals.append(f"VIX={vix} 正常水準 → 安定した投資環境")

    if macro_ind.get("credit_stress"):
        score -= 3
        chg = macro_ind.get("credit_spread_change_pct", 0)
        signals.append(f"クレジットスプレッド拡大 ({chg:+.1f}%) → リスクオフ加速の可能性")
    elif macro_ind.get("credit_spread_tightening"):
        score += 2
        signals.append("クレジットスプレッド縮小 → 機関投資家のリスク許容度上昇")

    dollar = macro_ind.get("dollar_trend", "NEUTRAL")
    dollar_chg = macro_ind.get("dollar_change_pct", 0)
    if dollar == "STRONG":
        score -= 1
        signals.append(f"ドル高 (+{dollar_chg:.1f}%) → 国際株・コモディティ逆風")
    elif dollar == "WEAK":
        score += 1
        signals.append(f"ドル安 ({dollar_chg:.1f}%) → 国際株・コモディティ追い風")

    gold_trend = macro_ind.get("gold_trend", "FLAT")
    gold_chg   = macro_ind.get("gold_change_pct", 0)
    if gold_trend == "SURGING":
        score -= 2
        signals.append(f"金急騰 (+{gold_chg:.1f}%) → 地政学リスク/スタグフレーション懸念")
    elif gold_trend == "UP":
        score -= 1
        signals.append(f"金上昇 (+{gold_chg:.1f}%) → 不確実性の高まり")

    if macro_ind.get("risk_off_signal"):
        score -= 2
        signals.append("TLT上昇・SPY下落 → 大規模リスクオフ進行中")

    if geo_score >= 4:
        score += 1
        signals.append(f"地政学・マクロニュース強気 (スコア={geo_score:+d})")
    elif geo_score <= -4:
        score -= 2
        signals.append(f"地政学リスク高 (スコア={geo_score:+d}) → 貿易・安全保障の不確実性")
    elif geo_score <= -2:
        score -= 1
        signals.append(f"マクロニュースやや悲観 (スコア={geo_score:+d})")

    if score >= 5:
        phase, label = "EARLY_EXPANSION", "回復・拡張初期"
        action = "株式全般・テック・金融に積極投資。景気敏感株の仕込み時。"
    elif score >= 2:
        phase, label = "MID_EXPANSION", "成長中期"
        action = "テック・工業株・素材が有利。継続保有・追加投資を検討。"
    elif score >= 0:
        phase, label = "LATE_EXPANSION", "成長後期（過熱注意）"
        action = "エネルギー・素材・ヘルスケアに比重移動。保有株の一部利確を検討。"
    elif score >= -3:
        phase, label = "CONTRACTION", "景気後退局面"
        action = "ディフェンシブ（XLU/XLP/XLV）・金・債券（TLT）へ退避。新規リスク投資を絞る。"
    else:
        phase, label = "SEVERE_CONTRACTION", "深刻な後退"
        action = "現金・金・短期債券を最優先。底打ちの兆候を待つ。"

    return {
        "phase":            phase,
        "label":            label,
        "score":            score,
        "action":           action,
        "recommended_etfs": CYCLE_SECTORS.get(phase, []),
        "signals":          signals,
    }


def collect_all() -> dict:
    """マクロ予測ボット用: 先行指標 + ファンダメンタルズを収集"""
    print("[1b] マクロ先行指標収集中...")
    macro_ind = get_macro_indicators()

    print("[1c] 地政学・ニューススコアリング中...")
    geo = get_geopolitical_score()

    cycle = detect_economic_cycle(macro_ind, geo["score"])
    print(f"     経済フェーズ: {cycle['label']} (スコア={cycle['score']:+d})")

    fundamentals = {}
    scores       = {}
    for ticker in WATCHLIST:
        f = get_fundamentals(ticker)
        fundamentals[ticker] = f
        scores[ticker]       = score_fundamentals(f)

    prices = {t: f.get("price", 0) for t, f in fundamentals.items() if f.get("price")}
    best_ticker = max(scores, key=lambda t: scores[t]) if scores else "AAPL"

    return {
        "collected_at":     datetime.utcnow().isoformat(),
        "mode":             "macro",
        "primary_ticker":   best_ticker,
        "fundamentals":     fundamentals,
        "scores":           scores,
        "prices":           prices,
        "macro_indicators": macro_ind,
        "geo_political":    geo,
        "economic_cycle":   cycle,
    }
