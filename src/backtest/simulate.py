#This is the predictive backtesting module for intraday quantitative trading strategies
from datetime import datetime
from dataclasses import dataclass
from src.data.bar_types import Bar

@dataclass
class BacktestResult:
    timestamps: list[datetime]
    equity: list[float]
    returns: list[float]
    positions: list[int]

def simulate_positions(bars: list[Bar], positions: list[int], initial_capital: float, trade_cost: float) -> BacktestResult:
    ts = bars[0].ts
    timestamps = [ts]
    equity_list = [initial_capital]
    returns_list = [0.0]
    
    for i in range(1, len(bars)):
        raw_return = (bars[i].close / bars[i-1].close) - 1
        ts = bars[i].ts

        if positions[i] == 1:
            if equity_list[-1] * (1 + raw_return) > 0:
                equity = equity_list[-1] * (1 + raw_return)
            else:
                equity = 0
        else:
            equity = equity_list[-1]

        if positions[i] != positions[i-1]:
            if equity - trade_cost >= 0:
                equity -= trade_cost
            else:
                equity = 0

        timestamps.append(ts)
        equity_list.append(equity)
        returns_list.append(raw_return)

    return BacktestResult(timestamps=timestamps, equity=equity_list, returns=returns_list, positions=positions)
