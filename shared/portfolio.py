"""
マルチ銘柄ポートフォリオ管理
長期・中期・短期ボット用
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional
import json
from pathlib import Path

STATE_DIR = Path(__file__).parent.parent / "data"


@dataclass
class Position:
    ticker: str
    shares: float
    buy_price: float
    bought_at: str
    cost_basis: float
    peak_price: float = 0.0   # トレーリングストップ用・最高値を追跡

    def __post_init__(self):
        if self.peak_price == 0.0:
            self.peak_price = self.buy_price


@dataclass
class TradeRecord:
    timestamp: str
    action: str
    ticker: str
    price: float
    shares: float
    value_usd: float
    balance_after: float
    pnl: float = 0.0
    reasoning: str = ""
    confidence: float = 0.0
    risk_level: str = "MEDIUM"
    signals_json: object = None   # 発火シグナルのリスト（学習用）


class Portfolio:
    """複数銘柄を管理するポートフォリオ（利確・損切り・トレーリングストップ付き）"""

    def __init__(self,
                 initial_balance: float = 10000.0,
                 risk_per_trade: float = 0.15,
                 max_positions: int = 5,
                 state_file: str = "portfolio.json",
                 take_profit_pct: float = 0.20,      # +20%で利確
                 stop_loss_pct: float = 0.10,         # -10%で損切り
                 trailing_stop_pct: float = 0.07,     # 高値から-7%でトレーリング
                 disable_price_exits: bool = False):  # Trueにすると価格ベース出口ルールを無効化
        self.initial_balance = initial_balance
        self.risk_per_trade = risk_per_trade
        self.max_positions = max_positions
        self.take_profit_pct = take_profit_pct
        self.stop_loss_pct = stop_loss_pct
        self.trailing_stop_pct = trailing_stop_pct
        self.disable_price_exits = disable_price_exits
        self._state_path = STATE_DIR / state_file

        self.balance = initial_balance
        self.positions: dict[str, Position] = {}
        self.trade_history: list[TradeRecord] = []
        self._load()

    # ── 利確・損切りチェック ──────────────────────────────
    def check_exits(self, ticker: str, current_price: float) -> tuple[bool, str]:
        """
        利確・損切り・トレーリングストップの判断
        disable_price_exits=True の場合は常に (False, "") を返す（長期マクロ保有用）
        戻り値: (売るべきか, 理由)
        """
        pos = self.positions.get(ticker)
        if not pos:
            return False, ""

        # 価格ベースの出口ルールが無効な場合（マクロ予測ボット用）
        if self.disable_price_exits:
            return False, ""

        change_pct = (current_price - pos.buy_price) / pos.buy_price

        # 1. 利確
        if change_pct >= self.take_profit_pct:
            return True, f"利確: +{change_pct*100:.1f}% (閾値+{self.take_profit_pct*100:.0f}%)"

        # 2. 損切り
        if change_pct <= -self.stop_loss_pct:
            return True, f"損切り: {change_pct*100:.1f}% (閾値-{self.stop_loss_pct*100:.0f}%)"

        # 3. トレーリングストップ（高値から一定以上落ちたら売り）
        if current_price > pos.peak_price:
            pos.peak_price = current_price
            self._save()
        drop_from_peak = (current_price - pos.peak_price) / pos.peak_price
        if drop_from_peak <= -self.trailing_stop_pct:
            return True, f"トレーリングストップ: 高値${pos.peak_price:,.2f}から{drop_from_peak*100:.1f}% (閾値-{self.trailing_stop_pct*100:.0f}%)"

        return False, ""

    # ── 永続化 ────────────────────────────────────────────
    def _save(self):
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        data = {
            "balance": self.balance,
            "initial_balance": self.initial_balance,
            "positions": {
                t: {
                    "ticker":     p.ticker,
                    "shares":     p.shares,
                    "buy_price":  p.buy_price,
                    "bought_at":  p.bought_at,
                    "cost_basis": p.cost_basis,
                    "peak_price": p.peak_price,
                }
                for t, p in self.positions.items()
            },
        }
        with open(self._state_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def _load(self):
        if not self._state_path.exists():
            return
        try:
            with open(self._state_path, encoding="utf-8") as f:
                data = json.load(f)
            self.balance = data.get("balance", self.balance)
            self.initial_balance = data.get("initial_balance", self.initial_balance)
            self.positions = {
                t: Position(**p)
                for t, p in data.get("positions", {}).items()
            }
            print(f"[PF] 状態ロード: 現金=${self.balance:,.2f}  保有={list(self.positions.keys())}")
        except Exception as e:
            print(f"[PF] 状態ロード失敗（新規スタート）: {e}")

    def buy(self, ticker: str, price: float, reasoning: str = "",
            confidence: float = 0.5, risk_level: str = "MEDIUM") -> Optional[TradeRecord]:
        if ticker in self.positions:
            return None
        if len(self.positions) >= self.max_positions:
            return None
        invest = self.balance * self.risk_per_trade
        if invest < 1:
            return None
        shares = invest / price
        self.balance -= invest
        self.positions[ticker] = Position(
            ticker=ticker, shares=shares, buy_price=price,
            bought_at=datetime.now(timezone.utc).isoformat(),
            cost_basis=invest, peak_price=price,
        )
        record = TradeRecord(
            timestamp=datetime.now(timezone.utc).isoformat(),
            action="BUY", ticker=ticker, price=price,
            shares=shares, value_usd=invest, balance_after=self.balance,
            reasoning=reasoning, confidence=confidence, risk_level=risk_level,
        )
        self.trade_history.append(record)
        self._save()
        return record

    def sell(self, ticker: str, price: float, reasoning: str = "",
             confidence: float = 0.5, risk_level: str = "MEDIUM") -> Optional[TradeRecord]:
        if ticker not in self.positions:
            return None
        pos = self.positions.pop(ticker)
        sell_value = pos.shares * price
        pnl = sell_value - pos.cost_basis
        self.balance += sell_value
        record = TradeRecord(
            timestamp=datetime.now(timezone.utc).isoformat(),
            action="SELL", ticker=ticker, price=price,
            shares=pos.shares, value_usd=sell_value, balance_after=self.balance,
            pnl=pnl, reasoning=reasoning, confidence=confidence, risk_level=risk_level,
        )
        self.trade_history.append(record)
        self._save()
        return record

    def portfolio_value(self, prices: dict[str, float]) -> float:
        return self.balance + sum(
            pos.shares * prices.get(pos.ticker, pos.buy_price)
            for pos in self.positions.values()
        )

    def summary(self, prices: dict[str, float]) -> dict:
        pv = self.portfolio_value(prices)
        sells = [t for t in self.trade_history if t.action == "SELL"]
        wins = [t for t in sells if t.pnl > 0]
        win_rate = len(wins) / len(sells) * 100 if sells else 0.0
        total_pnl = sum(t.pnl for t in sells)
        positions_info = []
        for ticker, pos in self.positions.items():
            current = prices.get(ticker, pos.buy_price)
            unrealized = (current - pos.buy_price) / pos.buy_price * 100
            positions_info.append(
                f"{ticker}: {pos.shares:.4f}株 @ ${pos.buy_price:,.2f} "
                f"-> ${current:,.2f} ({'+' if unrealized >= 0 else ''}{unrealized:.1f}%)"
            )
        return {
            "portfolio_value":  round(pv, 2),
            "cash_balance":     round(self.balance, 2),
            "initial_balance":  self.initial_balance,
            "total_return_pct": round((pv / self.initial_balance - 1) * 100, 2),
            "realized_pnl":     round(total_pnl, 2),
            "win_rate":         round(win_rate, 1),
            "total_trades":     len(sells),
            "open_positions":   len(self.positions),
            "positions":        positions_info,
        }
