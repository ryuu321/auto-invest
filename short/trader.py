"""
ペーパートレードエンジン
架空資金で売買シミュレーションを行い、損益を記録する
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional


@dataclass
class Position:
    coin: str
    amount: float       # 保有枚数
    buy_price: float    # 購入価格
    bought_at: str      # 購入日時


@dataclass
class TradeRecord:
    timestamp: str
    action: str         # BUY / SELL / HOLD
    coin: str
    price: float
    amount: float
    value_usd: float
    balance_after: float
    pnl: float = 0.0
    reasoning: str = ""
    confidence: float = 0.0
    risk_level: str = "MEDIUM"
    signals_json: object = None   # 発火シグナルのリスト（学習用）


class PaperTrader:
    """架空資金でのトレードシミュレーター"""

    def __init__(self, initial_balance_usd: float = 10000.0, risk_per_trade: float = 0.10):
        self.balance = initial_balance_usd          # 保有現金（USD）
        self.initial_balance = initial_balance_usd
        self.risk_per_trade = risk_per_trade        # 1回のトレードで使う資金の割合
        self.position: Optional[Position] = None
        self.trade_history: list[TradeRecord] = []

    @property
    def total_pnl(self) -> float:
        return sum(t.pnl for t in self.trade_history)

    @property
    def win_rate(self) -> float:
        sells = [t for t in self.trade_history if t.action == "SELL"]
        if not sells:
            return 0.0
        wins = [t for t in sells if t.pnl > 0]
        return len(wins) / len(sells)

    # 利確・損切り設定
    TAKE_PROFIT  = 0.15   # +15%で利確
    STOP_LOSS    = 0.08   # -8%で損切り
    TRAILING     = 0.05   # 高値から-5%でトレーリングストップ

    def _check_exits(self, current_price: float) -> tuple[bool, str]:
        """利確・損切り・トレーリングストップチェック"""
        if not self.position:
            return False, ""
        change = (current_price - self.position.buy_price) / self.position.buy_price
        if change >= self.TAKE_PROFIT:
            return True, f"利確: +{change*100:.1f}%"
        if change <= -self.STOP_LOSS:
            return True, f"損切り: {change*100:.1f}%"
        peak = getattr(self.position, "peak_price", self.position.buy_price)
        if current_price > peak:
            self.position.peak_price = current_price
        else:
            drop = (current_price - peak) / peak
            if drop <= -self.TRAILING:
                return True, f"トレーリングストップ: 高値から{drop*100:.1f}%"
        return False, ""

    def execute(self, decision: str, current_price: float, coin: str,
                reasoning: str = "", confidence: float = 0.5,
                risk_level: str = "MEDIUM") -> TradeRecord:
        """売買判断を受け取って実行する（利確・損切り優先）"""

        # 保有中なら利確・損切りを最優先チェック
        if self.position:
            should_exit, exit_reason = self._check_exits(current_price)
            if should_exit:
                decision = "SELL"
                reasoning = exit_reason

        timestamp = datetime.now(timezone.utc).isoformat()
        pnl = 0.0

        if decision == "BUY" and self.position is None and self.balance > 0:
            # 購入
            invest_amount = self.balance * self.risk_per_trade
            coin_amount = invest_amount / current_price
            self.balance -= invest_amount
            self.position = Position(
                coin=coin,
                amount=coin_amount,
                buy_price=current_price,
                bought_at=timestamp,
            )
            self.position.peak_price = current_price
            record = TradeRecord(
                timestamp=timestamp,
                action="BUY",
                coin=coin,
                price=current_price,
                amount=coin_amount,
                value_usd=invest_amount,
                balance_after=self.balance,
                pnl=0.0,
                reasoning=reasoning,
                confidence=confidence,
                risk_level=risk_level,
            )

        elif decision == "SELL" and self.position is not None:
            # 売却
            sell_value = self.position.amount * current_price
            pnl = sell_value - (self.position.amount * self.position.buy_price)
            self.balance += sell_value
            record = TradeRecord(
                timestamp=timestamp,
                action="SELL",
                coin=coin,
                price=current_price,
                amount=self.position.amount,
                value_usd=sell_value,
                balance_after=self.balance,
                pnl=pnl,
                reasoning=reasoning,
                confidence=confidence,
                risk_level=risk_level,
            )
            self.position = None

        else:
            # HOLD または条件不成立
            record = TradeRecord(
                timestamp=timestamp,
                action="HOLD",
                coin=coin,
                price=current_price,
                amount=0.0,
                value_usd=0.0,
                balance_after=self.balance,
                pnl=0.0,
                reasoning=reasoning,
                confidence=confidence,
                risk_level=risk_level,
            )

        self.trade_history.append(record)
        return record

    def get_portfolio_value(self, current_price: float) -> float:
        """現在のポートフォリオ総額（現金 + 保有資産）"""
        position_value = self.position.amount * current_price if self.position else 0.0
        return self.balance + position_value

    def summary(self, current_price: float) -> dict:
        """パフォーマンスサマリー"""
        portfolio_value = self.get_portfolio_value(current_price)
        return {
            "initial_balance": self.initial_balance,
            "current_balance": round(self.balance, 2),
            "portfolio_value": round(portfolio_value, 2),
            "total_pnl": round(self.total_pnl, 2),
            "total_return_pct": round((portfolio_value / self.initial_balance - 1) * 100, 2),
            "win_rate": round(self.win_rate * 100, 1),
            "total_trades": len([t for t in self.trade_history if t.action != "HOLD"]),
            "has_position": self.position is not None,
        }
