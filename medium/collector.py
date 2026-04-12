"""
中期投資 情報収集モジュール
- 日足データ（過去6ヶ月）
- 50MA / 200MA
- 仮想通貨 + 株（yfinance）
- マクロ指標（DXY・VIX）
"""

import requests
import feedparser
import pandas as pd
import ta
import yfinance as yf
from datetime import datetime
from typing import Optional

POSITIVE_WORDS = ["bullish","surge","rally","growth","gains","recovery","upgrade","adoption"]
NEGATIVE_WORDS = ["bearish","crash","ban","decline","risk","warning","recession","inflation"]

RSS_FEEDS = [
    "https://www.coindesk.com/arc/outboundfeeds/rss/",
    "https://decrypt.co/feed",
]

# 監視する資産
ASSETS = {
    "BTC-USD": "bitcoin",
    "ETH-USD": "ethereum",
    "SPY":     "S&P500 ETF",
    "QQQ":     "Nasdaq ETF",
}


def get_daily_data(ticker: str, period: str = "6mo") -> Optional[pd.DataFrame]:
    """日足データを取得してテクニカル指標を計算"""
    try:
        df = yf.Ticker(ticker).history(period=period)
        if df.empty:
            return None
        df["ma50"]  = df["Close"].rolling(50).mean()
        df["ma200"] = df["Close"].rolling(200).mean()
        df["rsi"]   = ta.momentum.RSIIndicator(df["Close"], window=14).rsi()
        macd = ta.trend.MACD(df["Close"])
        df["macd"]        = macd.macd()
        df["macd_signal"] = macd.macd_signal()
        return df
    except Exception as e:
        print(f"[medium/collector] {ticker} データ取得エラー: {e}")
        return None


def get_asset_signals(ticker: str) -> dict:
    """1銘柄のシグナルデータを返す"""
    df = get_daily_data(ticker)
    if df is None or len(df) < 5:
        return {}
    latest = df.iloc[-1]
    prev   = df.iloc[-2]
    price  = latest["Close"]
    ma50   = latest["ma50"]
    ma200  = latest["ma200"]

    golden_cross = (prev["ma50"] < prev["ma200"]) and (ma50 > ma200) if pd.notna(ma200) else None
    death_cross  = (prev["ma50"] > prev["ma200"]) and (ma50 < ma200) if pd.notna(ma200) else None

    return {
        "ticker":       ticker,
        "price":        round(price, 2),
        "ma50":         round(ma50, 2) if pd.notna(ma50) else None,
        "ma200":        round(ma200, 2) if pd.notna(ma200) else None,
        "rsi":          round(latest["rsi"], 2) if pd.notna(latest["rsi"]) else None,
        "macd":         round(latest["macd"], 4) if pd.notna(latest["macd"]) else None,
        "macd_signal":  round(latest["macd_signal"], 4) if pd.notna(latest["macd_signal"]) else None,
        "above_ma50":   price > ma50 if pd.notna(ma50) else None,
        "above_ma200":  price > ma200 if pd.notna(ma200) else None,
        "golden_cross": golden_cross,
        "death_cross":  death_cross,
    }


def get_news_sentiment() -> dict:
    articles, score = [], 0
    for url in RSS_FEEDS:
        try:
            feed = feedparser.parse(url)
            for e in feed.entries[:5]:
                text = (e.get("title","") + " " + e.get("summary","")).lower()
                for w in POSITIVE_WORDS: score += text.count(w)
                for w in NEGATIVE_WORDS: score -= text.count(w)
                articles.append(e.get("title",""))
        except Exception:
            pass
    return {"score": score, "count": len(articles),
            "label": "positive" if score > 0 else ("negative" if score < 0 else "neutral")}


def collect_all(primary_ticker: str = "BTC-USD") -> dict:
    signals = {}
    for ticker in ASSETS:
        s = get_asset_signals(ticker)
        if s:
            signals[ticker] = s

    news = get_news_sentiment()

    return {
        "collected_at":   datetime.utcnow().isoformat(),
        "mode":           "medium",
        "primary_ticker": primary_ticker,
        "assets":         signals,
        "technicals":     signals.get(primary_ticker, {}),
        "news_sentiment": news,
        "fear_greed":     _get_fear_greed(),
    }


def _get_fear_greed() -> Optional[dict]:
    try:
        res = requests.get("https://api.alternative.me/fng/", timeout=10)
        d = res.json()["data"][0]
        return {"value": int(d["value"]), "label": d["value_classification"]}
    except Exception:
        return None
