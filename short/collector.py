"""
情報収集モジュール
APIキー不要・完全無料
- 仮想通貨価格・テクニカル指標: CoinGecko（無料・キーなし）
- Fear & Greed Index: alternative.me（無料・キーなし）
- ニュース: RSSフィード（無料・キーなし）
"""

import requests
import feedparser
import pandas as pd
import ta
from datetime import datetime
from typing import Optional


# ポジティブ・ネガティブキーワード（ニュースセンチメント用）
POSITIVE_WORDS = [
    "bullish", "surge", "rally", "adoption", "breakout", "record",
    "growth", "gains", "high", "buy", "support", "recovery", "upgrade",
    "partnership", "launch", "approval", "etf", "institutional"
]
NEGATIVE_WORDS = [
    "bearish", "crash", "ban", "hack", "regulation", "lawsuit",
    "sell", "drop", "fall", "decline", "risk", "warning", "fraud",
    "scam", "exploit", "vulnerability", "liquidation", "fear"
]

# 無料RSSフィード（APIキー不要）
RSS_FEEDS = [
    "https://www.coindesk.com/arc/outboundfeeds/rss/",
    "https://decrypt.co/feed",
]


class MarketDataCollector:
    """仮想通貨価格・テクニカル指標の収集（CoinGecko無料API）"""

    COINGECKO_BASE = "https://api.coingecko.com/api/v3"

    def get_price(self, coin_id: str = "bitcoin") -> Optional[dict]:
        try:
            url = f"{self.COINGECKO_BASE}/simple/price"
            params = {
                "ids": coin_id,
                "vs_currencies": "usd,jpy",
                "include_24hr_change": "true",
                "include_market_cap": "true",
            }
            res = requests.get(url, params=params, timeout=10)
            res.raise_for_status()
            return res.json().get(coin_id)
        except Exception as e:
            print(f"[collector] 価格取得エラー: {e}")
            return None

    def get_ohlcv(self, coin_id: str = "bitcoin", days: int = 30) -> Optional[pd.DataFrame]:
        try:
            url = f"{self.COINGECKO_BASE}/coins/{coin_id}/ohlc"
            params = {"vs_currency": "usd", "days": days}
            res = requests.get(url, params=params, timeout=10)
            res.raise_for_status()
            data = res.json()

            df = pd.DataFrame(data, columns=["timestamp", "open", "high", "low", "close"])
            df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
            df = df.set_index("timestamp")

            df["rsi"] = ta.momentum.RSIIndicator(df["close"], window=14).rsi()
            macd = ta.trend.MACD(df["close"])
            df["macd"] = macd.macd()
            df["macd_signal"] = macd.macd_signal()
            bb = ta.volatility.BollingerBands(df["close"])
            df["bb_upper"] = bb.bollinger_hband()
            df["bb_lower"] = bb.bollinger_lband()

            return df
        except Exception as e:
            print(f"[collector] OHLCVデータ取得エラー: {e}")
            return None

    def get_fear_greed(self) -> Optional[dict]:
        try:
            res = requests.get("https://api.alternative.me/fng/", timeout=10)
            res.raise_for_status()
            data = res.json()["data"][0]
            return {
                "value": int(data["value"]),
                "label": data["value_classification"],
            }
        except Exception as e:
            print(f"[collector] Fear&Greed取得エラー: {e}")
            return None


class NewsCollector:
    """RSSフィードからニュースを収集（APIキー不要・無料）"""

    def get_news(self, max_items: int = 10) -> list[dict]:
        articles = []
        for feed_url in RSS_FEEDS:
            try:
                feed = feedparser.parse(feed_url)
                for entry in feed.entries[:max_items // len(RSS_FEEDS) + 1]:
                    articles.append({
                        "title": entry.get("title", ""),
                        "summary": entry.get("summary", ""),
                        "published": entry.get("published", ""),
                        "source": feed.feed.get("title", feed_url),
                    })
            except Exception as e:
                print(f"[collector] RSS取得エラー ({feed_url}): {e}")
        return articles[:max_items]

    def calc_sentiment(self, articles: list[dict]) -> dict:
        """キーワードベースのセンチメントスコアを計算（APIなし）"""
        score = 0
        for article in articles:
            text = (article.get("title", "") + " " + article.get("summary", "")).lower()
            for word in POSITIVE_WORDS:
                if word in text:
                    score += 1
            for word in NEGATIVE_WORDS:
                if word in text:
                    score -= 1
        return {
            "score": score,
            "count": len(articles),
            "label": "positive" if score > 0 else ("negative" if score < 0 else "neutral"),
        }


def collect_all(coin_id: str = "bitcoin") -> dict:
    """全情報を一括収集（APIキー不要）"""
    market = MarketDataCollector()
    news_collector = NewsCollector()

    price = market.get_price(coin_id)
    ohlcv = market.get_ohlcv(coin_id, days=30)
    fear_greed = market.get_fear_greed()
    articles = news_collector.get_news()
    news_sentiment = news_collector.calc_sentiment(articles)

    technicals = {}
    if ohlcv is not None and not ohlcv.empty:
        latest = ohlcv.iloc[-1]
        technicals = {
            "rsi": round(latest["rsi"], 2) if pd.notna(latest["rsi"]) else None,
            "macd": round(latest["macd"], 4) if pd.notna(latest["macd"]) else None,
            "macd_signal": round(latest["macd_signal"], 4) if pd.notna(latest["macd_signal"]) else None,
            "bb_upper": round(latest["bb_upper"], 2) if pd.notna(latest["bb_upper"]) else None,
            "bb_lower": round(latest["bb_lower"], 2) if pd.notna(latest["bb_lower"]) else None,
            "current_price": round(latest["close"], 2),
        }

    return {
        "collected_at": datetime.utcnow().isoformat(),
        "coin": coin_id,
        "price": price,
        "technicals": technicals,
        "fear_greed": fear_greed,
        "news_sentiment": news_sentiment,
        "articles": articles,
    }
