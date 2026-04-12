# 全自動投資システム

**APIキー不要・完全無料**で動く仮想通貨自動売買システム。
数値とルールだけで判断する。感情・推測は一切使わない。

## 判断ルール

| 指標 | BUY条件 | SELL条件 |
|------|--------|---------|
| RSI | < 30（売られすぎ） | > 70（買われすぎ） |
| MACD | MACDがシグナル上回る | MACDがシグナル下回る |
| ボリンジャー | 価格が下限以下 | 価格が上限以上 |
| Fear&Greed | < 25（極端な恐怖） | > 75（極端な強欲） |
| ニュース | ポジティブ単語+3以上 | ネガティブ単語-3以下 |

スコア合計 ≥ +2 → BUY / ≤ -2 → SELL / それ以外 → HOLD

## セットアップ

```bash
# 依存パッケージをインストール
pip install requests feedparser pandas ta

# 起動（APIキー不要）
cd saas-dev/projects/auto-invest/src
python main.py
```

## 使用API（全て無料・キーなし）

| API | 用途 |
|-----|------|
| CoinGecko | 価格・OHLCVデータ |
| alternative.me | Fear & Greed Index |
| RSSフィード | ニュース収集 |

## フェーズ

- **Phase 1（今）**: ペーパートレード（架空$10,000で学習）
- **Phase 2（資金調達後）**: ccxtで取引所と接続して本番運用
