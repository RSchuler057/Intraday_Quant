#This is the predictive backtesting module for intraday quantitative trading strategies
from datetime import datetime
from dataclasses import dataclass
from data.types import Bar

@dataclass
class BacktestResult:
    timestamps: list[datetime]
    equity: list[float]
    returns: list[float]

def simulate_buy_and_hold(bars: list[Bar], initial_capital: float) -> BacktestResult:
    initial_capital = float(initial_capital)
    ts = bars[0].ts
    _return = 0.0
    equity = initial_capital

    timestamps = [ts]
    equity_list = [equity]
    returns = [_return]

    for i in range(1, len(bars)):
        _return = (bars[i].close / bars[i-1].close) - 1
        equity = equity * (1 + _return)
        ts = bars[i].ts

        timestamps.append(ts)
        equity_list.append(equity)
        returns.append(_return)

    return BacktestResult(timestamps=timestamps, equity=equity_list, returns=returns)