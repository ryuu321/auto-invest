"""
長期投資 情報収集モジュール — 先回り予測対応版

収集する情報:
  1. 企業ファンダメンタルズ（yfinance）
  2. マクロ先行指標
       - イールドカーブ（10年-3ヶ月金利差）: 景気後退の6〜18ヶ月先行指標
       - VIX（恐怖指数）: 市場の不確実性
       - クレジットスプレッド（HYG/LQD比率）: 信用リスクの先行指標
       - ドル指数（UUP）: 国際資本フロー
       - 金トレンド（GLD）: インフレ・有事の代替指標
  3. 地政学・マクロニュース（RSS多ソース・重み付きキーワード）
  4. 経済サイクル判定（先行指標の合成）
  5. セクターローテーション推奨
"""

import yfinance as yf
import feedparser
from datetime import datetime
from typing import Optional

# ── 長期投資ウォッチリスト ────────────────────────────────────────────
WATCHLIST = {
    "AAPL":  "Apple",
    "MSFT":  "Microsoft",
    "GOOGL": "Alphabet",
    "AMZN":  "Amazon",
    "NVDA":  "NVIDIA",
    "BRK-B": "Berkshire Hathaway",
    "SPY":   "S&P500 ETF",
    "QQQ":   "Nasdaq ETF",
    "VT":    "全世界株ETF",
}

# ── セクターETF ───────────────────────────────────────────────────────
SECTOR_ETFs = {
    "tech":        "XLK",
    "healthcare":  "XLV",
    "financials":  "XLF",
    "energy":      "XLE",
    "utilities":   "XLU",
    "staples":     "XLP",
    "industrials": "XLI",
    "materials":   "XLB",
}

# 経済サイクル別・推奨セクター
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
    "https://www.reutersagency.com/feed/?best-topics=business-finance&post_type=best",
    "https://feeds.bbci.co.uk/news/business/rss.xml",
    "https://www.marketwatch.com/rss/marketpulse",
]

# 重み付きキーワード（カテゴリ別）
GEO_KEYWORDS = {
    # 貿易・関税（長期投資に大きく影響）
    "tariff":           -3,
    "trade war":        -4,
    "trade deal":       +3,
    "trade agreement":  +3,
    "sanction":         -2,
    "import ban":       -2,
    "export restriction": -2,
    # 地政学リスク
    "war":              -3,
    "invasion":         -4,
    "conflict":         -2,
    "ceasefire":        +2,
    "peace deal":       +3,
    "nuclear":          -4,
    # 金融政策
    "rate cut":         +3,
    "interest rate cut": +3,
    "fed cut":          +3,
    "rate hike":        -2,
    "quantitative easing": +2,
    "stimulus":         +2,
    "taper":            -1,
    # 景気指標
    "recession":        -4,
    "gdp growth":       +2,
    "gdp contraction":  -3,
    "soft landing":     +3,
    "hard landing":     -3,
    "unemployment rise": -2,
    "jobs report":       0,
    "earnings beat":    +2,
    "earnings miss":    -2,
    "inflation":        -2,
    "deflation":        -2,
    "stagflation":      -4,
    # テクノロジー・AI
    "ai regulation":    -1,
    "chip ban":         -3,
    "semiconductor":     0,
    "tech crackdown":   -2,
}


# ── マクロ先行指標 ─────────────────────────────────────────────────────

def get_macro_indicators() -> dict:
    """
    先行指標を収集する。これらは「今」ではなく「6〜18ヶ月後」を示す。

    イールドカーブ逆転: 過去8回の米国景気後退のうち7回で事前に発生した
    クレジットスプレッド拡大: 企業の借入コスト上昇→投資減少→景気後退の先行
    VIX上昇: 市場参加者がリスクをヘッジし始めている＝悪化の予感
    """
    ind = {}

    # ── イールドカーブ（10年 - 3ヶ月金利差）──────────────────
    try:
        tnx = yf.Ticker("^TNX").history(period="3mo")["Close"]   # 10年
        irx = yf.Ticker("^IRX").history(period="3mo")["Close"]   # 13週(3ヶ月)
        if not tnx.empty and not irx.empty:
            y10 = float(tnx.iloc[-1]) / 100
            y3m = float(irx.iloc[-1]) / 100
            spread = round(y10 - y3m, 4)
            ind["yield_10y"]             = round(y10 * 100, 3)
            ind["yield_3m"]              = round(y3m * 100, 3)
            ind["yield_curve_spread"]    = spread
            ind["yield_curve_inverted"]  = spread < 0
            # 3ヶ月前との比較（スティープニング = 回復の先行）
            spread_3mo_ago = float(tnx.iloc[0]) / 100 - float(irx.iloc[0]) / 100
            ind["yield_curve_steepening"] = spread > spread_3mo_ago
            ind["yield_curve_trend"]      = "steepening" if spread > spread_3mo_ago else "flattening"
    except Exception as e:
        print(f"[long/collector] イールドカーブ取得エラー: {e}")

    # ── VIX（恐怖指数）────────────────────────────────────────
    try:
        vix_hist = yf.Ticker("^VIX").history(period="1mo")["Close"]
        if not vix_hist.empty:
            vix_now = float(vix_hist.iloc[-1])
            vix_avg = float(vix_hist.mean())
            ind["vix"]         = round(vix_now, 2)
            ind["vix_avg_1mo"] = round(vix_avg, 2)
            ind["vix_rising"]  = vix_now > vix_avg
            if vix_now > 30:
                ind["vix_regime"] = "PANIC"       # 30超 = パニック
            elif vix_now > 20:
                ind["vix_regime"] = "HIGH"
            elif vix_now < 15:
                ind["vix_regime"] = "COMPLACENT"  # 15未満 = 過度な楽観
            else:
                ind["vix_regime"] = "NORMAL"
    except Exception as e:
        print(f"[long/collector] VIX取得エラー: {e}")

    # ── クレジットスプレッド（HYG vs LQD）──────────────────────
    # HYG = ハイイールド社債ETF, LQD = 投資適格社債ETF
    # HYG/LQD比率が下がる = ハイイールドが売られている = 信用リスクの上昇
    try:
        hyg = yf.Ticker("HYG").history(period="3mo")["Close"]
        lqd = yf.Ticker("LQD").history(period="3mo")["Close"]
        if not hyg.empty and not lqd.empty:
            ratio_now = float(hyg.iloc[-1]) / float(lqd.iloc[-1])
            ratio_3mo = float(hyg.iloc[0])  / float(lqd.iloc[0])
            change    = (ratio_now - ratio_3mo) / ratio_3mo
            ind["credit_spread_change_pct"] = round(change * 100, 2)
            ind["credit_spread_tightening"] = change > 0.01   # 1%以上縮小 = リスクオン
            ind["credit_stress"]            = change < -0.03  # 3%以上拡大 = ストレス
    except Exception as e:
        print(f"[long/collector] クレジットスプレッド取得エラー: {e}")

    # ── ドル指数（UUP）────────────────────────────────────────
    # ドル高 → 国際株・コモディティ逆風、新興国債務リスク
    try:
        uup = yf.Ticker("UUP").history(period="3mo")["Close"]
        if not uup.empty:
            uup_now = float(uup.iloc[-1])
            uup_3mo = float(uup.iloc[0])
            uup_chg = (uup_now - uup_3mo) / uup_3mo * 100
            ind["dollar_change_pct"] = round(uup_chg, 2)
            if uup_chg > 2:
                ind["dollar_trend"] = "STRONG"
            elif uup_chg < -2:
                ind["dollar_trend"] = "WEAK"
            else:
                ind["dollar_trend"] = "NEUTRAL"
    except Exception as e:
        print(f"[long/collector] ドル取得エラー: {e}")

    # ── 金トレンド（GLD）──────────────────────────────────────
    # 金上昇 = インフレ期待 or 地政学リスク上昇の先行サイン
    try:
        gld = yf.Ticker("GLD").history(period="3mo")["Close"]
        if not gld.empty:
            gld_chg = (float(gld.iloc[-1]) - float(gld.iloc[0])) / float(gld.iloc[0]) * 100
            ind["gold_change_pct"] = round(gld_chg, 2)
            if gld_chg > 5:
                ind["gold_trend"] = "SURGING"   # 5%超 = 有事・インフレ本格化
            elif gld_chg > 2:
                ind["gold_trend"] = "UP"
            elif gld_chg < -2:
                ind["gold_trend"] = "DOWN"
            else:
                ind["gold_trend"] = "FLAT"
    except Exception as e:
        print(f"[long/collector] 金取得エラー: {e}")

    # ── 長期金利 vs SPYのモメンタム（グロース株への影響）─────
    try:
        spy = yf.Ticker("SPY").history(period="3mo")["Close"]
        tlt = yf.Ticker("TLT").history(period="3mo")["Close"]  # 20年債ETF
        if not spy.empty and not tlt.empty:
            spy_chg = (float(spy.iloc[-1]) - float(spy.iloc[0])) / float(spy.iloc[0]) * 100
            tlt_chg = (float(tlt.iloc[-1]) - float(tlt.iloc[0])) / float(tlt.iloc[0]) * 100
            ind["spy_3mo_change_pct"] = round(spy_chg, 2)
            ind["tlt_3mo_change_pct"] = round(tlt_chg, 2)
            # TLT上昇かつSPY下落 = リスクオフ（債券に逃避）
            ind["risk_off_signal"] = tlt_chg > 3 and spy_chg < -5
    except Exception as e:
        print(f"[long/collector] SPY/TLT取得エラー: {e}")

    return ind


def detect_economic_cycle(macro_ind: dict, geo_score: int) -> dict:
    """
    先行指標の合成スコアから経済サイクルのフェーズを推定する。

    フェーズ解説:
      EARLY_EXPANSION  : 回復初期。景気敏感株・テック・金融が有利。
      MID_EXPANSION    : 成長加速。テック・工業株・素材。
      LATE_EXPANSION   : 過熱気味。エネルギー・素材・ヘルスケア。利確検討。
      CONTRACTION      : 後退局面。ディフェンシブ・金・債券へ退避。
      SEVERE_CONTRACTION: 深刻な後退。現金比率を高める。
    """
    score = 0
    signals = []

    # ── イールドカーブ（最重要指標）──────────────────────────
    if macro_ind.get("yield_curve_inverted"):
        spread = macro_ind.get("yield_curve_spread", 0)
        score -= 3
        signals.append(f"イールドカーブ逆転中 (スプレッド={spread:.3f}) → 景気後退の6〜18ヶ月先行シグナル")
    elif macro_ind.get("yield_curve_steepening"):
        score += 2
        signals.append(f"イールドカーブ スティープニング → 景気拡張/回復局面へ移行中")
    else:
        signals.append(f"イールドカーブ フラット化 → 拡張終盤の可能性")

    # ── VIX ──────────────────────────────────────────────────
    vix_regime = macro_ind.get("vix_regime", "NORMAL")
    vix        = macro_ind.get("vix", 20)
    if vix_regime == "PANIC":
        score -= 3
        signals.append(f"VIX={vix} パニック水準 → 市場の極度な恐怖。短期底打ちの可能性も")
    elif vix_regime == "HIGH":
        score -= 1
        signals.append(f"VIX={vix} 高水準 → リスク回避傾向強まる")
    elif vix_regime == "COMPLACENT":
        score -= 1  # 過度な楽観 = 上昇余地限定
        signals.append(f"VIX={vix} 過度な楽観 → 相場の脆弱性に注意")
    else:
        score += 1
        signals.append(f"VIX={vix} 正常水準 → 安定した投資環境")

    # ── クレジットスプレッド ──────────────────────────────────
    if macro_ind.get("credit_stress"):
        score -= 3
        chg = macro_ind.get("credit_spread_change_pct", 0)
        signals.append(f"クレジットスプレッド拡大 ({chg:+.1f}%) → 信用リスク上昇・リスクオフ加速の可能性")
    elif macro_ind.get("credit_spread_tightening"):
        score += 2
        signals.append("クレジットスプレッド縮小 → 機関投資家のリスク許容度上昇")

    # ── ドル ─────────────────────────────────────────────────
    dollar = macro_ind.get("dollar_trend", "NEUTRAL")
    dollar_chg = macro_ind.get("dollar_change_pct", 0)
    if dollar == "STRONG":
        score -= 1
        signals.append(f"ドル高 (+{dollar_chg:.1f}%) → 新興国・国際株・コモディティに逆風")
    elif dollar == "WEAK":
        score += 1
        signals.append(f"ドル安 ({dollar_chg:.1f}%) → 国際分散投資・コモディティ追い風")

    # ── 金 ────────────────────────────────────────────────────
    gold_trend = macro_ind.get("gold_trend", "FLAT")
    gold_chg   = macro_ind.get("gold_change_pct", 0)
    if gold_trend == "SURGING":
        score -= 2
        signals.append(f"金価格急騰 (+{gold_chg:.1f}%) → 深刻な地政学リスクまたはインフレ懸念台頭")
    elif gold_trend == "UP":
        score -= 1
        signals.append(f"金価格上昇 (+{gold_chg:.1f}%) → 不確実性の高まり")

    # ── リスクオフシグナル ────────────────────────────────────
    if macro_ind.get("risk_off_signal"):
        score -= 2
        signals.append("TLT上昇・SPY下落 → 機関投資家が株から債券へ移動。リスクオフ進行中")

    # ── 地政学スコア ──────────────────────────────────────────
    if geo_score >= 4:
        score += 1
        signals.append(f"地政学・マクロニュース強気 (スコア={geo_score:+d})")
    elif geo_score <= -4:
        score -= 2
        signals.append(f"地政学リスク高 (スコア={geo_score:+d}) → 貿易・地政学の不確実性")
    elif geo_score <= -2:
        score -= 1
        signals.append(f"地政学・マクロニュースやや悲観 (スコア={geo_score:+d})")

    # ── フェーズ判定 ──────────────────────────────────────────
    if score >= 5:
        phase  = "EARLY_EXPANSION"
        label  = "回復・拡張初期"
        action = "株式全般・テック・金融に積極投資。景気敏感株の仕込み時。"
        rec_sectors = CYCLE_SECTORS["EARLY_EXPANSION"]
    elif score >= 2:
        phase  = "MID_EXPANSION"
        label  = "成長中期"
        action = "テック・工業株・素材が有利。継続保有・追加投資を検討。"
        rec_sectors = CYCLE_SECTORS["MID_EXPANSION"]
    elif score >= 0:
        phase  = "LATE_EXPANSION"
        label  = "成長後期（過熱注意）"
        action = "エネルギー・素材・ヘルスケアに比重移動。保有株の一部利確を検討。"
        rec_sectors = CYCLE_SECTORS["LATE_EXPANSION"]
    elif score >= -3:
        phase  = "CONTRACTION"
        label  = "景気後退局面"
        action = "ディフェンシブ（XLU/XLP/XLV）・金・債券（TLT）へ退避。新規リスク投資を絞る。"
        rec_sectors = CYCLE_SECTORS["CONTRACTION"]
    else:
        phase  = "SEVERE_CONTRACTION"
        label  = "深刻な後退"
        action = "現金・金・短期債券を最優先。底打ちの兆候を待つ。"
        rec_sectors = CYCLE_SECTORS["SEVERE_CONTRACTION"]

    return {
        "phase":            phase,
        "label":            label,
        "score":            score,
        "action":           action,
        "recommended_etfs": rec_sectors,
        "signals":          signals,
    }


# ── 地政学・マクロニュース ────────────────────────────────────────────

def get_geopolitical_score() -> dict:
    """
    複数RSSソースからマクロ・地政学ニュースを収集し、
    重み付きキーワードスコアリングを行う。
    """
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
                        if abs(weight) >= 3:  # 重大なイベントのみタグ付け
                            event_tags.append(f"[{'+' if weight>0 else ''}{weight}] {raw[:60]}")
        except Exception:
            pass

    return {
        "score":      total_score,
        "headlines":  headlines[:15],
        "event_tags": event_tags[:5],
        "label":      "positive" if total_score > 2 else ("negative" if total_score < -2 else "neutral"),
    }


# ── ファンダメンタルズ ────────────────────────────────────────────────

def get_fundamentals(ticker: str) -> dict:
    try:
        t    = yf.Ticker(ticker)
        info = t.info
        hist = t.history(period="1y")

        price = info.get("currentPrice") or info.get("regularMarketPrice")
        if not price and not hist.empty:
            price = float(hist["Close"].iloc[-1])

        week52_high = info.get("fiftyTwoWeekHigh")
        from_high   = ((price - week52_high) / week52_high * 100) if price and week52_high else None

        return {
            "ticker":         ticker,
            "name":           info.get("longName", ticker),
            "price":          round(price, 2) if price else None,
            "pe_ratio":       info.get("trailingPE"),
            "forward_pe":     info.get("forwardPE"),
            "revenue_growth": info.get("revenueGrowth"),
            "profit_margin":  info.get("profitMargins"),
            "debt_to_equity": info.get("debtToEquity"),
            "roe":            info.get("returnOnEquity"),
            "week52_high":    week52_high,
            "from_52w_high":  round(from_high, 1) if from_high else None,
            "market_cap":     info.get("marketCap"),
        }
    except Exception as e:
        print(f"[long/collector] {ticker} ファンダメンタルズ取得エラー: {e}")
        return {"ticker": ticker}


def score_fundamentals(f: dict) -> int:
    score = 0
    pe         = f.get("pe_ratio")
    fpe        = f.get("forward_pe")
    rev_growth = f.get("revenue_growth")
    margin     = f.get("profit_margin")
    dte        = f.get("debt_to_equity")
    roe        = f.get("roe")
    from_high  = f.get("from_52w_high")

    if pe:
        if pe < 15:    score += 2
        elif pe < 25:  score += 1
        elif pe > 40:  score -= 1

    if fpe and pe and fpe < pe:
        score += 1   # 将来的にPER改善 = 成長期待

    if rev_growth:
        if rev_growth > 0.15:  score += 2
        elif rev_growth > 0.05: score += 1
        elif rev_growth < 0:   score -= 1

    if margin and margin > 0.20:  score += 1
    if dte and dte < 50:          score += 1
    if roe and roe > 0.15:        score += 1

    if from_high and from_high < -30:
        score += 1  # 高値から30%超下落 = 割安感

    return score


# ── メイン収集 ────────────────────────────────────────────────────────

def collect_all(primary_ticker: str = "AAPL") -> dict:
    """全長期投資データを収集（先行指標を含む）"""

    # 1. ファンダメンタルズ
    fundamentals = {}
    scores       = {}
    for ticker in WATCHLIST:
        f = get_fundamentals(ticker)
        fundamentals[ticker] = f
        scores[ticker]       = score_fundamentals(f)

    # 2. マクロ先行指標
    print("[1b] マクロ先行指標収集中...")
    macro_ind = get_macro_indicators()

    # 3. 地政学・マクロニュース
    print("[1c] 地政学・ニューススコアリング中...")
    geo = get_geopolitical_score()

    # 4. 経済サイクル判定
    cycle = detect_economic_cycle(macro_ind, geo["score"])
    print(f"     経済フェーズ: {cycle['label']} (スコア={cycle['score']:+d})")

    # 最もファンダスコアが高い銘柄を推奨
    best_ticker = max(scores, key=lambda t: scores[t]) if scores else primary_ticker

    return {
        "collected_at":    datetime.utcnow().isoformat(),
        "mode":            "long",
        "primary_ticker":  best_ticker,
        "fundamentals":    fundamentals,
        "scores":          scores,
        "macro_news":      geo,           # 後方互換のため
        "geo_political":   geo,
        "macro_indicators":macro_ind,
        "economic_cycle":  cycle,
        "technicals":      fundamentals.get(best_ticker, {}),
    }
