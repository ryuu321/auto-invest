"""
長期投資 情報収集モジュール
- 企業ファンダメンタルズ（yfinance）
- 世界情勢・マクロ経済（RSSフィード）
- 週足チャート
"""

import yfinance as yf
import feedparser
import requests
from datetime import datetime
from typing import Optional

# 長期投資候補の優良株・ETF（世界情勢に左右されにくい企業）
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

MACRO_RSS = [
    "https://feeds.bloomberg.com/markets/news.rss",
    "https://www.reuters.com/finance/markets/rss",
    "https://www.coindesk.com/arc/outboundfeeds/rss/",
]

MACRO_POSITIVE = ["rate cut","stimulus","growth","recovery","gdp up","earnings beat","expansion"]
MACRO_NEGATIVE = ["rate hike","recession","inflation","gdp down","layoffs","crisis","war","sanctions"]


def get_fundamentals(ticker: str) -> dict:
    """企業のファンダメンタルズを取得"""
    try:
        t = yf.Ticker(ticker)
        info = t.info
        hist = t.history(period="1y")

        price = info.get("currentPrice") or info.get("regularMarketPrice")
        if not price and not hist.empty:
            price = hist["Close"].iloc[-1]

        # 52週高値からの乖離
        week52_high = info.get("fiftyTwoWeekHigh")
        from_high = ((price - week52_high) / week52_high * 100) if price and week52_high else None

        return {
            "ticker":          ticker,
            "name":            info.get("longName", ticker),
            "price":           round(price, 2) if price else None,
            "pe_ratio":        info.get("trailingPE"),
            "forward_pe":      info.get("forwardPE"),
            "revenue_growth":  info.get("revenueGrowth"),      # YoY成長率
            "profit_margin":   info.get("profitMargins"),
            "debt_to_equity":  info.get("debtToEquity"),
            "roe":             info.get("returnOnEquity"),
            "week52_high":     week52_high,
            "from_52w_high":   round(from_high, 1) if from_high else None,
            "market_cap":      info.get("marketCap"),
        }
    except Exception as e:
        print(f"[long/collector] {ticker} ファンダメンタルズ取得エラー: {e}")
        return {"ticker": ticker}


def get_macro_news() -> dict:
    """世界情勢・マクロニュースを収集してスコアリング"""
    score = 0
    headlines = []
    for url in MACRO_RSS:
        try:
            feed = feedparser.parse(url)
            for e in feed.entries[:5]:
                title = e.get("title", "").lower()
                headlines.append(e.get("title", ""))
                for w in MACRO_POSITIVE: score += title.count(w)
                for w in MACRO_NEGATIVE: score -= title.count(w)
        except Exception:
            pass
    return {
        "score":     score,
        "headlines": headlines[:10],
        "label":     "positive" if score > 0 else ("negative" if score < 0 else "neutral"),
    }


def score_fundamentals(f: dict) -> int:
    """ファンダメンタルズをスコアリング（+がBUY方向）"""
    score = 0
    pe = f.get("pe_ratio")
    fpe = f.get("forward_pe")
    rev_growth = f.get("revenue_growth")
    margin = f.get("profit_margin")
    dte = f.get("debt_to_equity")
    roe = f.get("roe")
    from_high = f.get("from_52w_high")

    if pe and pe < 15:      score += 2   # 割安
    elif pe and pe < 25:    score += 1   # 適正
    elif pe and pe > 40:    score -= 1   # 割高

    if fpe and fpe < pe if pe else False: score += 1  # 将来的に改善

    if rev_growth and rev_growth > 0.15:  score += 2  # 15%以上成長
    elif rev_growth and rev_growth > 0.05: score += 1
    elif rev_growth and rev_growth < 0:   score -= 1  # 減収

    if margin and margin > 0.20:  score += 1  # 高収益
    if dte and dte < 50:          score += 1  # 低負債
    if roe and roe > 0.15:        score += 1  # 高ROE

    if from_high and from_high < -30: score += 1  # 高値から30%以上下落＝割安感

    return score


def collect_all(primary_ticker: str = "AAPL") -> dict:
    """全長期投資データを収集"""
    fundamentals = {}
    scores = {}
    for ticker in WATCHLIST:
        f = get_fundamentals(ticker)
        fundamentals[ticker] = f
        scores[ticker] = score_fundamentals(f)

    macro = get_macro_news()

    # 最もスコアの高い銘柄を推奨
    best_ticker = max(scores, key=lambda t: scores[t]) if scores else primary_ticker

    return {
        "collected_at":   datetime.utcnow().isoformat(),
        "mode":           "long",
        "primary_ticker": best_ticker,
        "fundamentals":   fundamentals,
        "scores":         scores,
        "macro_news":     macro,
        "technicals":     fundamentals.get(best_ticker, {}),
    }
