"""
投資ダッシュボード
短期・中期・長期ボットの損益・ポジション・シグナルをリアルタイム表示
起動: python dashboard/app.py
ブラウザ: http://localhost:5000
"""
import sqlite3
import json
import sys
import time
import requests
from pathlib import Path
from datetime import datetime, timezone
from flask import Flask, jsonify, render_template_string
import yfinance as yf

sys.path.insert(0, str(Path(__file__).parent.parent / "shared"))

DB_PATH  = Path(__file__).parent.parent / "data" / "trades.db"
DATA_DIR = Path(__file__).parent.parent / "data"

app = Flask(__name__)

# ── ライブ価格キャッシュ（過多リクエスト防止） ───────────────
_price_cache: dict = {}   # {ticker: (price, timestamp)}
CACHE_TTL = 30            # 秒


def fetch_live_price(ticker: str) -> float | None:
    """yfinance (株) / CoinGecko (BTC,ETH) でリアルタイム価格取得"""
    now = time.time()
    if ticker in _price_cache:
        price, ts = _price_cache[ticker]
        if now - ts < CACHE_TTL:
            return price

    price = None
    try:
        # 暗号資産は CoinGecko
        crypto_map = {"bitcoin": "bitcoin", "BTC-USD": "bitcoin", "ETH-USD": "ethereum"}
        if ticker in crypto_map:
            r = requests.get(
                "https://api.coingecko.com/api/v3/simple/price",
                params={"ids": crypto_map[ticker], "vs_currencies": "usd"},
                timeout=5,
            )
            data = r.json()
            price = data.get(crypto_map[ticker], {}).get("usd")
        else:
            # 株は yfinance
            info = yf.Ticker(ticker).fast_info
            price = float(info.last_price) if info.last_price else None
    except Exception:
        pass

    if price is not None:
        _price_cache[ticker] = (price, now)
    return price


def fetch_live_prices(tickers: list[str]) -> dict[str, float]:
    """複数銘柄を一括取得"""
    result = {}
    # 株をまとめて取得（効率化）
    stock_tickers = [t for t in tickers if t not in ("bitcoin", "BTC-USD", "ETH-USD")]
    crypto_tickers = [t for t in tickers if t in ("bitcoin", "BTC-USD", "ETH-USD")]

    if stock_tickers:
        try:
            now = time.time()
            uncached = [t for t in stock_tickers
                        if t not in _price_cache or now - _price_cache[t][1] >= CACHE_TTL]
            if uncached:
                data = yf.download(uncached, period="1d", progress=False, auto_adjust=True)
                if not data.empty:
                    close = data["Close"] if "Close" in data else data
                    for t in uncached:
                        try:
                            p = float(close[t].dropna().iloc[-1]) if t in close.columns else None
                            if p:
                                _price_cache[t] = (p, now)
                        except Exception:
                            pass
            for t in stock_tickers:
                if t in _price_cache:
                    result[t] = _price_cache[t][0]
        except Exception:
            pass

    for t in crypto_tickers:
        p = fetch_live_price(t)
        if p:
            result[t] = p

    return result


def fetch_history(ticker: str, days: int = 30) -> list[dict]:
    """過去N日の終値を返す"""
    try:
        crypto_map = {"bitcoin": "BTC-USD", "BTC-USD": "BTC-USD", "ETH-USD": "ETH-USD"}
        yf_ticker = crypto_map.get(ticker, ticker)
        df = yf.download(yf_ticker, period=f"{days}d", progress=False, auto_adjust=True)
        if df.empty:
            return []
        close = df["Close"] if "Close" in df.columns else df
        series = close[yf_ticker] if yf_ticker in close.columns else close.iloc[:, 0]
        return [
            {"date": str(idx.date()), "price": round(float(v), 4)}
            for idx, v in series.dropna().items()
        ]
    except Exception:
        return []


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


# ─────────────────────────────────────────────
# API エンドポイント
# ─────────────────────────────────────────────

def _extract_prices_from_snapshot(raw_data: dict) -> dict:
    """raw_data から銘柄→価格のマッピングを取り出す（short/medium/long 両対応）"""
    prices = {}
    # medium/long: raw_data.assets.{TICKER}.price
    for ticker, info in raw_data.get("assets", {}).items():
        if info and info.get("price"):
            prices[ticker] = info["price"]
    # long: raw_data.fundamentals.{TICKER}.price
    for ticker, info in raw_data.get("fundamentals", {}).items():
        if info and info.get("price") and ticker not in prices:
            prices[ticker] = info["price"]
    # short: raw_data.technicals.current_price
    if not prices:
        p = raw_data.get("technicals", {}).get("current_price")
        coin = raw_data.get("coin", "BTC")
        if p:
            prices[coin] = p
    return prices


@app.route("/api/stats")
def api_stats():
    if not DB_PATH.exists():
        return jsonify({"error": "DB not found — run a bot first"})
    conn = get_db()
    cur = conn.cursor()

    cur.execute("SELECT COUNT(*) FROM trades WHERE action='BUY'")
    total_buys = cur.fetchone()[0]

    cur.execute("SELECT COUNT(*) FROM trades WHERE action='SELL'")
    total_sells = cur.fetchone()[0]

    cur.execute("SELECT COALESCE(SUM(pnl), 0) FROM trades WHERE action='SELL'")
    realized_pnl = cur.fetchone()[0]

    cur.execute("SELECT COUNT(*) FROM trades WHERE action='SELL' AND pnl > 0")
    wins = cur.fetchone()[0]
    win_rate = round(wins / total_sells * 100, 1) if total_sells > 0 else 0.0

    # 最新スナップショットから価格取得（raw_data を使う）
    cur.execute("SELECT raw_data FROM market_snapshots ORDER BY timestamp DESC LIMIT 5")
    prices = {}
    for row in cur.fetchall():
        try:
            rd = json.loads(row["raw_data"] or "{}")
            for k, v in _extract_prices_from_snapshot(rd).items():
                if k not in prices:
                    prices[k] = v
        except Exception:
            pass

    conn.close()
    return jsonify({
        "total_buys":    total_buys,
        "total_sells":   total_sells,
        "realized_pnl":  round(realized_pnl, 2),
        "win_rate":      win_rate,
        "latest_prices": prices,
    })


@app.route("/api/live_prices")
def api_live_prices():
    """保有銘柄のリアルタイム価格"""
    tickers = []
    for fname in ["portfolio_long.json", "portfolio_medium.json", "portfolio_short.json"]:
        path = DATA_DIR / fname
        if path.exists():
            try:
                with open(path, encoding="utf-8") as f:
                    data = json.load(f)
                tickers += list(data.get("positions", {}).keys())
            except Exception:
                pass
    tickers = list(set(tickers))
    prices = fetch_live_prices(tickers)
    return jsonify({"prices": prices, "updated_at": datetime.now(timezone.utc).isoformat()})


@app.route("/api/history/<ticker>")
def api_history(ticker: str):
    """過去60日チャート + その銘柄のBUY/SELLマーカー（最近傍の取引日にスナップ）"""
    candles = fetch_history(ticker, days=60)
    candle_dates = [c["date"] for c in candles]

    def snap_to_nearest(date_str: str) -> str:
        """チャートにない日付（週末・祝日）を最も近い取引日に丸める"""
        if date_str in candle_dates:
            return date_str
        # 過去方向に最近傍を探す
        for c in reversed(candle_dates):
            if c <= date_str:
                return c
        return candle_dates[0] if candle_dates else date_str

    trades = []
    if DB_PATH.exists():
        conn = get_db()
        cur = conn.cursor()
        cur.execute("""
            SELECT action, price, timestamp
            FROM trades
            WHERE coin = ? AND action IN ('BUY','SELL')
            ORDER BY timestamp
        """, (ticker,))
        for r in cur.fetchall():
            snapped = snap_to_nearest(r["timestamp"][:10])
            trades.append({
                "action":    r["action"],
                "price":     round(r["price"], 4),
                "timestamp": snapped,
                "original_date": r["timestamp"][:10],
            })
        conn.close()
    return jsonify({"candles": candles, "trades": trades})


@app.route("/api/positions")
def api_positions():
    """全ボットの保有ポジション + 未実現損益"""
    DATA_DIR = Path(__file__).parent.parent / "data"
    result = []

    # 保有銘柄のライブ価格を取得
    all_tickers = []
    for fname in ["portfolio_long.json", "portfolio_medium.json", "portfolio_short.json"]:
        path = DATA_DIR / fname
        if path.exists():
            try:
                with open(path, encoding="utf-8") as f:
                    d = json.load(f)
                all_tickers += list(d.get("positions", {}).keys())
            except Exception:
                pass
    current_prices = fetch_live_prices(list(set(all_tickers)))

    for fname, label in [("portfolio_long.json", "長期"), ("portfolio_medium.json", "中期"), ("portfolio_short.json", "短期")]:
        path = DATA_DIR / fname
        if not path.exists():
            continue
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            balance = data.get("balance", 0)
            init    = data.get("initial_balance", 10000)
            positions = data.get("positions", {})
            stock_value = 0.0
            pos_list = []
            for ticker, p in positions.items():
                cur_price = current_prices.get(ticker, p["buy_price"])
                unrealized = (cur_price - p["buy_price"]) * p["shares"]
                unrealized_pct = (cur_price / p["buy_price"] - 1) * 100
                stock_value += cur_price * p["shares"]
                pos_list.append({
                    "ticker":        ticker,
                    "shares":        round(p["shares"], 6),
                    "buy_price":     round(p["buy_price"], 2),
                    "current_price": round(cur_price, 2),
                    "cost_basis":    round(p["cost_basis"], 2),
                    "unrealized":    round(unrealized, 2),
                    "unrealized_pct":round(unrealized_pct, 2),
                    "bought_at":     p.get("bought_at", ""),
                })
            total = balance + stock_value
            result.append({
                "bot":           label,
                "cash":          round(balance, 2),
                "stock_value":   round(stock_value, 2),
                "total_value":   round(total, 2),
                "initial":       init,
                "return_pct":    round((total / init - 1) * 100, 2),
                "positions":     pos_list,
            })
        except Exception as e:
            result.append({"bot": label, "error": str(e)})

    return jsonify(result)


@app.route("/api/trades")
def api_trades():
    if not DB_PATH.exists():
        return jsonify([])
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        SELECT timestamp, action, coin, price, amount, value_usd,
               balance_after, pnl, reasoning, confidence, risk_level,
               COALESCE(bot_type, 'SHORT') as bot_type
        FROM trades
        ORDER BY timestamp DESC
        LIMIT 100
    """)
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return jsonify(rows)


@app.route("/api/snapshots")
def api_snapshots():
    """各銘柄の最新データをフラットなリストで返す"""
    if not DB_PATH.exists():
        return jsonify([])
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        SELECT timestamp, raw_data, fear_greed_value, fear_greed_label
        FROM market_snapshots
        ORDER BY timestamp DESC
        LIMIT 10
    """)
    seen = {}
    for r in cur.fetchall():
        try:
            rd = json.loads(r["raw_data"] or "{}")
            fg_val   = r["fear_greed_value"]
            fg_label = r["fear_greed_label"]

            # medium/long: assets dict
            for ticker, info in rd.get("assets", {}).items():
                if info and ticker not in seen:
                    seen[ticker] = {
                        "coin":  ticker,
                        "price": info.get("price"),
                        "rsi":   info.get("rsi"),
                        "macd":  info.get("macd"),
                        "fear_greed_value": fg_val,
                        "fear_greed_label": fg_label,
                        "timestamp": r["timestamp"],
                    }
            # long: fundamentals dict
            for ticker, info in rd.get("fundamentals", {}).items():
                if info and ticker not in seen:
                    seen[ticker] = {
                        "coin":  ticker,
                        "price": info.get("price"),
                        "rsi":   None,
                        "macd":  None,
                        "pe":    info.get("pe_ratio"),
                        "fear_greed_value": None,
                        "fear_greed_label": None,
                        "timestamp": r["timestamp"],
                    }
            # short: technicals
            if rd.get("technicals") and rd.get("coin") and rd["coin"] not in seen:
                t = rd["technicals"]
                seen[rd["coin"]] = {
                    "coin":  rd["coin"],
                    "price": t.get("current_price"),
                    "rsi":   t.get("rsi"),
                    "macd":  t.get("macd"),
                    "fear_greed_value": fg_val,
                    "fear_greed_label": fg_label,
                    "timestamp": r["timestamp"],
                }
        except Exception:
            pass

    conn.close()
    return jsonify(list(seen.values()))


@app.route("/api/pnl_chart")
def api_pnl_chart():
    """累積損益チャート用データ"""
    if not DB_PATH.exists():
        return jsonify([])
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        SELECT timestamp, pnl, balance_after
        FROM trades
        WHERE action='SELL'
        ORDER BY timestamp ASC
    """)
    rows = []
    cumulative = 0.0
    for r in cur.fetchall():
        cumulative += r["pnl"]
        rows.append({
            "timestamp": r["timestamp"][:10],
            "pnl":       round(r["pnl"], 2),
            "cumulative": round(cumulative, 2),
            "balance":   round(r["balance_after"], 2),
        })
    conn.close()
    return jsonify(rows)


# ─────────────────────────────────────────────
# フロントエンド（シングルページ）
# ─────────────────────────────────────────────

HTML = """<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>AI Holdings — 投資ダッシュボード</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4/dist/chart.umd.min.js"></script>
<style>
  :root {
    --bg: #0f1117; --card: #1a1d27; --border: #2a2d3a;
    --text: #e0e0e0; --muted: #6b7280; --green: #22c55e;
    --red: #ef4444; --blue: #3b82f6; --yellow: #f59e0b;
    --accent: #6366f1;
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { background: var(--bg); color: var(--text); font-family: 'Segoe UI', sans-serif; font-size: 14px; }
  header { background: var(--card); border-bottom: 1px solid var(--border); padding: 16px 24px; display: flex; align-items: center; gap: 12px; }
  header h1 { font-size: 18px; font-weight: 700; color: var(--accent); }
  header span { color: var(--muted); font-size: 12px; }
  .container { max-width: 1200px; margin: 0 auto; padding: 24px 16px; }
  .grid { display: grid; gap: 16px; }
  .grid-4 { grid-template-columns: repeat(4, 1fr); }
  .grid-2 { grid-template-columns: repeat(2, 1fr); }
  .grid-3 { grid-template-columns: repeat(3, 1fr); }
  @media (max-width: 900px) { .grid-4, .grid-3 { grid-template-columns: repeat(2, 1fr); } }
  @media (max-width: 600px) { .grid-4, .grid-3, .grid-2 { grid-template-columns: 1fr; } }
  .card { background: var(--card); border: 1px solid var(--border); border-radius: 12px; padding: 20px; }
  .card h2 { font-size: 12px; color: var(--muted); text-transform: uppercase; letter-spacing: .05em; margin-bottom: 8px; }
  .stat { font-size: 28px; font-weight: 700; }
  .stat-sub { font-size: 12px; color: var(--muted); margin-top: 4px; }
  .green { color: var(--green); }
  .red   { color: var(--red); }
  .blue  { color: var(--blue); }
  .yellow { color: var(--yellow); }
  table { width: 100%; border-collapse: collapse; }
  th { text-align: left; color: var(--muted); font-size: 11px; text-transform: uppercase; padding: 6px 8px; border-bottom: 1px solid var(--border); }
  td { padding: 8px; border-bottom: 1px solid var(--border); font-size: 13px; }
  tr:last-child td { border-bottom: none; }
  tr:hover td { background: rgba(99,102,241,.05); }
  .badge { display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 11px; font-weight: 600; }
  .badge-buy  { background: rgba(34,197,94,.15); color: var(--green); }
  .badge-sell { background: rgba(239,68,68,.15);  color: var(--red); }
  .badge-hold { background: rgba(107,114,128,.15); color: var(--muted); }
  .section-title { font-size: 16px; font-weight: 600; margin: 24px 0 12px; }
  .refresh-btn { margin-left: auto; background: var(--accent); color: #fff; border: none; padding: 8px 16px; border-radius: 8px; cursor: pointer; font-size: 13px; }
  .refresh-btn:hover { opacity: .85; }
  .empty { color: var(--muted); text-align: center; padding: 32px; }
  .chart-wrap { position: relative; height: 220px; }
  .prices-row { display: flex; flex-wrap: wrap; gap: 12px; margin-bottom: 8px; }
  .price-tag { background: rgba(99,102,241,.1); border: 1px solid var(--border); border-radius: 8px; padding: 8px 14px; }
  .price-tag .label { font-size: 11px; color: var(--muted); }
  .price-tag .value { font-size: 16px; font-weight: 600; }
  .reasoning { font-size: 11px; color: var(--muted); max-width: 260px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .filter-btn { background: var(--border); color: var(--muted); border: none; padding: 4px 10px; border-radius: 6px; cursor: pointer; font-size: 12px; }
  .filter-btn.active { background: var(--accent); color: #fff; }
  .filter-btn:hover { opacity: .85; }
  .badge-short  { background: rgba(59,130,246,.15);  color: #60a5fa; }
  .badge-medium { background: rgba(245,158,11,.15);  color: #fbbf24; }
  .badge-long   { background: rgba(168,85,247,.15);  color: #c084fc; }
</style>
</head>
<body>
<header>
  <h1>AI Holdings — 投資ダッシュボード</h1>
  <span id="last-update">読み込み中...</span>
  <button class="refresh-btn" onclick="loadAll()">更新</button>
</header>
<div class="container">

  <!-- KPIカード -->
  <div class="grid grid-4" id="kpi-cards">
    <div class="card"><h2>実現損益</h2><div class="stat" id="kpi-pnl">--</div><div class="stat-sub">確定済み損益</div></div>
    <div class="card"><h2>勝率</h2><div class="stat" id="kpi-winrate">--</div><div class="stat-sub">SELL取引の勝率</div></div>
    <div class="card"><h2>総取引数</h2><div class="stat" id="kpi-trades">--</div><div class="stat-sub">BUY / SELL</div></div>
    <div class="card"><h2>ポートフォリオ</h2><div class="stat" id="kpi-status">稼働中</div><div class="stat-sub">3ボット並列運用</div></div>
  </div>

  <!-- 保有ポジション -->
  <p class="section-title">保有ポジション（未実現損益）</p>
  <div id="positions-section"></div>

  <!-- 最新価格 -->
  <p class="section-title">最新価格</p>
  <div class="card">
    <div class="prices-row" id="prices-row"><span class="empty">データ取得中...</span></div>
  </div>

  <!-- 累積損益チャート -->
  <p class="section-title">累積損益推移</p>
  <div class="card">
    <div class="chart-wrap"><canvas id="pnl-chart"></canvas></div>
  </div>

  <div class="grid grid-2">
    <!-- 直近トレード -->
    <div>
      <p class="section-title">直近トレード履歴</p>
      <div class="card">
        <!-- フィルター -->
        <div style="display:flex;gap:6px;flex-wrap:wrap;margin-bottom:12px">
          <button class="filter-btn active" data-filter="ALL"   onclick="setTradeFilter('ALL')">すべて</button>
          <button class="filter-btn"        data-filter="SHORT" onclick="setTradeFilter('SHORT')">短期</button>
          <button class="filter-btn"        data-filter="MEDIUM" onclick="setTradeFilter('MEDIUM')">中期</button>
          <button class="filter-btn"        data-filter="LONG"  onclick="setTradeFilter('LONG')">長期</button>
          <button class="filter-btn"        data-filter="BUY"   onclick="setTradeFilter('BUY')">BUYのみ</button>
          <button class="filter-btn"        data-filter="SELL"  onclick="setTradeFilter('SELL')">SELLのみ</button>
        </div>
        <table>
          <thead><tr><th>日時</th><th>ボット</th><th>種別</th><th>銘柄</th><th>価格</th><th>PnL</th></tr></thead>
          <tbody id="trades-body"><tr><td colspan="6" class="empty">読み込み中...</td></tr></tbody>
        </table>
      </div>
    </div>

    <!-- 市場スナップショット -->
    <div>
      <p class="section-title">市場スナップショット（最新）</p>
      <div class="card">
        <table>
          <thead><tr><th>銘柄</th><th>価格</th><th>RSI</th><th>MACD</th><th>F&G</th></tr></thead>
          <tbody id="snapshot-body"><tr><td colspan="5" class="empty">読み込み中...</td></tr></tbody>
        </table>
      </div>
    </div>
  </div>

</div>
<script>
let pnlChart = null;

function fmt(n, digits=2) {
  if (n == null || n === undefined) return '--';
  return Number(n).toLocaleString('en-US', { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

async function loadStats() {
  const r = await fetch('/api/stats').then(r => r.json());
  const pnl = r.realized_pnl || 0;
  const el = document.getElementById('kpi-pnl');
  el.textContent = (pnl >= 0 ? '+' : '') + '$' + fmt(pnl);
  el.className = 'stat ' + (pnl >= 0 ? 'green' : 'red');

  const wr = document.getElementById('kpi-winrate');
  wr.textContent = r.win_rate + '%';
  wr.className = 'stat ' + (r.win_rate >= 50 ? 'green' : 'red');

  document.getElementById('kpi-trades').textContent = r.total_buys + ' / ' + r.total_sells;

  // 価格タグ
  const row = document.getElementById('prices-row');
  const prices = r.latest_prices || {};
  const keys = Object.keys(prices);
  if (keys.length === 0) { row.innerHTML = '<span class="empty">スナップショットなし</span>'; return; }
  row.innerHTML = keys.map(k =>
    `<div class="price-tag"><div class="label">${k}</div><div class="value">$${fmt(prices[k])}</div></div>`
  ).join('');
}

let allTrades = [];
let tradeFilter = 'ALL';

function setTradeFilter(f) {
  tradeFilter = f;
  document.querySelectorAll('.filter-btn').forEach(b => {
    b.classList.toggle('active', b.dataset.filter === f);
  });
  renderTrades();
}

function renderTrades() {
  const tbody = document.getElementById('trades-body');
  let rows = allTrades;

  if (tradeFilter === 'SHORT')  rows = rows.filter(t => t.bot_type === 'SHORT');
  else if (tradeFilter === 'MEDIUM') rows = rows.filter(t => t.bot_type === 'MEDIUM');
  else if (tradeFilter === 'LONG')   rows = rows.filter(t => t.bot_type === 'LONG');
  else if (tradeFilter === 'BUY')    rows = rows.filter(t => t.action === 'BUY');
  else if (tradeFilter === 'SELL')   rows = rows.filter(t => t.action === 'SELL');

  if (!rows.length) { tbody.innerHTML = '<tr><td colspan="6" class="empty">該当なし</td></tr>'; return; }

  const botLabel = { SHORT: '短期', MEDIUM: '中期', LONG: '長期' };
  const botBadge = { SHORT: 'badge-short', MEDIUM: 'badge-medium', LONG: 'badge-long' };

  tbody.innerHTML = rows.map(t => {
    const actionBadge = t.action === 'BUY' ? 'badge-buy' : (t.action === 'SELL' ? 'badge-sell' : 'badge-hold');
    const pnlStr = t.action === 'SELL'
      ? `<span class="${t.pnl >= 0 ? 'green' : 'red'}">${t.pnl >= 0 ? '+' : ''}$${fmt(t.pnl)}</span>`
      : '--';
    const bot = t.bot_type || 'SHORT';
    return `<tr>
      <td style="font-size:11px">${t.timestamp ? t.timestamp.substring(0,16) : '--'}</td>
      <td><span class="badge ${botBadge[bot] || 'badge-hold'}">${botLabel[bot] || bot}</span></td>
      <td><span class="badge ${actionBadge}">${t.action}</span></td>
      <td>${t.coin}</td>
      <td>$${fmt(t.price)}</td>
      <td>${pnlStr}</td>
    </tr>`;
  }).join('');
}

async function loadTrades() {
  allTrades = await fetch('/api/trades').then(r => r.json());
  renderTrades();
}

async function loadSnapshots() {
  const rows = await fetch('/api/snapshots').then(r => r.json());
  const tbody = document.getElementById('snapshot-body');
  if (!rows.length) { tbody.innerHTML = '<tr><td colspan="5" class="empty">スナップショットなし</td></tr>'; return; }

  // 銘柄ごとの最新1件
  const seen = {};
  const filtered = rows.filter(r => {
    const key = r.coin;
    if (!seen[key]) { seen[key] = true; return true; }
    return false;
  });

  tbody.innerHTML = filtered.map(s => {
    const rsiColor = s.rsi ? (s.rsi > 70 ? 'red' : s.rsi < 30 ? 'green' : '') : '';
    const fg = s.fear_greed_value;
    const fgColor = fg ? (fg < 25 ? 'green' : fg > 75 ? 'red' : '') : '';
    return `<tr>
      <td>${s.coin}</td>
      <td>$${fmt(s.price)}</td>
      <td class="${rsiColor}">${s.rsi ? fmt(s.rsi, 1) : '--'}</td>
      <td>${s.macd ? fmt(s.macd, 2) : '--'}</td>
      <td class="${fgColor}">${fg != null ? fg + ' (' + (s.fear_greed_label || '') + ')' : '--'}</td>
    </tr>`;
  }).join('');
}

async function loadChart() {
  const data = await fetch('/api/pnl_chart').then(r => r.json());
  const ctx = document.getElementById('pnl-chart').getContext('2d');

  if (pnlChart) pnlChart.destroy();

  if (!data.length) {
    ctx.fillStyle = '#6b7280';
    ctx.textAlign = 'center';
    ctx.fillText('SELL 取引が発生すると損益グラフが表示されます', ctx.canvas.width/2, 110);
    return;
  }

  pnlChart = new Chart(ctx, {
    type: 'line',
    data: {
      labels: data.map(d => d.timestamp),
      datasets: [{
        label: '累積損益 ($)',
        data: data.map(d => d.cumulative),
        borderColor: '#6366f1',
        backgroundColor: 'rgba(99,102,241,.1)',
        fill: true,
        tension: .3,
        pointRadius: 4,
      }]
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: { legend: { display: false } },
      scales: {
        x: { ticks: { color: '#6b7280' }, grid: { color: '#2a2d3a' } },
        y: { ticks: { color: '#6b7280', callback: v => '$' + v }, grid: { color: '#2a2d3a' } }
      }
    }
  });
}

// 銘柄ごとの価格チャートインスタンス管理
const tickerCharts = {};

async function loadTickerChart(ticker) {
  const canvasId = 'chart-' + ticker.replace(/[^a-zA-Z0-9]/g, '_');
  const canvas = document.getElementById(canvasId);
  if (!canvas) return;

  const resp = await fetch('/api/history/' + encodeURIComponent(ticker)).then(r => r.json());
  const candles = resp.candles || [];
  const trades  = resp.trades  || [];
  if (!candles.length) return;

  // BUY/SELL を日付 → アクションのマップに
  const tradeMap = {};
  for (const t of trades) {
    if (!tradeMap[t.timestamp]) tradeMap[t.timestamp] = [];
    tradeMap[t.timestamp].push(t);
  }

  const labels = candles.map(d => d.date.slice(5));  // MM-DD
  const prices = candles.map(d => d.price);

  // マーカー用データセット（BUY=緑▲, SELL=赤▼）
  const buyPoints  = candles.map(d => tradeMap[d.date]?.find(t => t.action === 'BUY')  ? d.price : null);
  const sellPoints = candles.map(d => tradeMap[d.date]?.find(t => t.action === 'SELL') ? d.price : null);

  if (tickerCharts[ticker]) tickerCharts[ticker].destroy();
  tickerCharts[ticker] = new Chart(canvas.getContext('2d'), {
    type: 'line',
    data: {
      labels,
      datasets: [
        {
          label: '価格',
          data: prices,
          borderColor: '#6366f1',
          backgroundColor: 'rgba(99,102,241,0.07)',
          borderWidth: 1.5,
          pointRadius: 0,
          fill: true,
          tension: 0.3,
          order: 3,
        },
        {
          label: 'BUY',
          data: buyPoints,
          type: 'scatter',
          pointStyle: 'triangle',
          pointRadius: 10,
          pointBackgroundColor: '#22c55e',
          pointBorderColor: '#fff',
          pointBorderWidth: 1.5,
          showLine: false,
          order: 1,
        },
        {
          label: 'SELL',
          data: sellPoints,
          type: 'scatter',
          pointStyle: ctx => {
            // 下向き三角は rotation で表現
            return 'triangle';
          },
          rotation: 180,
          pointRadius: 10,
          pointBackgroundColor: '#ef4444',
          pointBorderColor: '#fff',
          pointBorderWidth: 1.5,
          showLine: false,
          order: 1,
        },
      ]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      interaction: { mode: 'index', intersect: false },
      plugins: {
        legend: {
          display: true,
          labels: { color: '#6b7280', boxWidth: 12, font: { size: 11 } }
        },
        tooltip: {
          callbacks: {
            label: ctx => {
              if (ctx.raw == null) return null;
              const prefix = ctx.dataset.label === 'BUY' ? '🟢 BUY' : ctx.dataset.label === 'SELL' ? '🔴 SELL' : '';
              return (prefix ? prefix + ' ' : '') + '$' + fmt(ctx.raw);
            }
          },
          filter: item => item.raw != null,
        }
      },
      scales: {
        x: {
          ticks: { color: '#6b7280', maxTicksLimit: 8, font: { size: 10 } },
          grid: { display: false }
        },
        y: {
          ticks: { color: '#6b7280', callback: v => '$' + v, font: { size: 10 } },
          grid: { color: '#2a2d3a' }
        }
      }
    }
  });
}

async function loadPositions() {
  const bots = await fetch('/api/positions').then(r => r.json());
  const sec = document.getElementById('positions-section');
  if (!bots.length || bots.every(b => !b.positions?.length)) {
    sec.innerHTML = '<div class="card"><p class="empty">保有ポジションなし</p></div>';
    return;
  }

  const html = bots.map(b => {
    if (b.error) return `<div class="card"><h2>${b.bot}</h2><p class="empty">エラー: ${b.error}</p></div>`;
    if (!b.positions?.length) return '';
    const retColor = b.return_pct >= 0 ? 'green' : 'red';

    const posCards = b.positions.map(p => {
      const c = p.unrealized >= 0 ? 'green' : 'red';
      const canvasId = 'chart-' + p.ticker.replace(/[^a-zA-Z0-9]/g, '_');
      return `
        <div style="background:var(--bg);border:1px solid var(--border);border-radius:8px;padding:16px;margin-top:12px">
          <div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:10px">
            <div>
              <span style="font-size:18px;font-weight:700">${p.ticker}</span>
              <span style="margin-left:10px;font-size:22px;font-weight:700">$${fmt(p.current_price)}</span>
              <span class="${c}" style="margin-left:8px;font-size:14px">
                ${p.unrealized >= 0 ? '+' : ''}$${fmt(p.unrealized)}
                (${p.unrealized_pct >= 0 ? '+' : ''}${fmt(p.unrealized_pct, 2)}%)
              </span>
            </div>
            <div style="text-align:right;font-size:12px;color:var(--muted)">
              <div>${p.shares} 株</div>
              <div>購入単価 $${fmt(p.buy_price)}</div>
              <div>投資額 $${fmt(p.cost_basis)}</div>
            </div>
          </div>
          <div style="height:160px"><canvas id="${canvasId}"></canvas></div>
        </div>`;
    }).join('');

    return `<div class="card" style="margin-bottom:12px">
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:4px">
        <h2>${b.bot}ボット</h2>
        <span style="font-size:13px">
          総資産 <strong>$${fmt(b.total_value)}</strong>
          <span class="${retColor}"> ${b.return_pct >= 0 ? '+' : ''}${b.return_pct}%</span>
          &nbsp;｜ 現金 $${fmt(b.cash)}
        </span>
      </div>
      ${posCards}
    </div>`;
  }).join('');

  sec.innerHTML = html;

  // チャート描画（DOM生成後）
  for (const b of bots) {
    for (const p of (b.positions || [])) {
      loadTickerChart(p.ticker);
    }
  }
}

// ── リアルタイム価格だけ30秒ごとに軽量更新 ──────────────
async function refreshLivePrices() {
  const data = await fetch('/api/live_prices').then(r => r.json());
  const prices = data.prices || {};
  // 表示中の price セルを直接更新（再レンダリングなし）
  document.querySelectorAll('[data-ticker]').forEach(el => {
    const t = el.getAttribute('data-ticker');
    if (prices[t] != null) el.textContent = '$' + fmt(prices[t]);
  });
}

async function loadAll() {
  await Promise.all([loadStats(), loadPositions(), loadTrades(), loadSnapshots(), loadChart()]);
  document.getElementById('last-update').textContent =
    '最終更新: ' + new Date().toLocaleTimeString('ja-JP');
}

loadAll();
setInterval(loadPositions, 30000);   // 保有ポジションは30秒ごと
setInterval(loadAll, 300000);        // 全体は5分ごと
</script>
</body>
</html>
"""

@app.route("/")
def index():
    return render_template_string(HTML)


if __name__ == "__main__":
    print("[DASHBOARD] http://localhost:5000 で起動します")
    app.run(host="0.0.0.0", port=5000, debug=False)
