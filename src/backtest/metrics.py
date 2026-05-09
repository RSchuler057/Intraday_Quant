from backtest.simulate import BacktestResult
import math

def final_equity(result: BacktestResult):
    return result.equity[-1]

def total_return(result: BacktestResult):
    return (result.equity[-1] / result.equity[0] - 1) * 100

def max_drawdown(result: BacktestResult):
    peak = result.equity[0]
    max_dd = 0

    for equity in result.equity:
        peak = max(peak, equity)
        dd = (equity / peak) - 1
        max_dd = min(max_dd, dd)
    
    return max_dd * 100

def get_strategy_returns(result: BacktestResult):
    strategy_returns = []

    for i in range(1, len(result.equity)):
        if result.equity[i-1] > 0:
            step_return = (result.equity[i]/ result.equity[i-1]) - 1
        else:
            step_return = 0
        strategy_returns.append(step_return)
    
    return strategy_returns

def mean_return(result: BacktestResult):
    returns = get_strategy_returns(result)
    mean_return = sum(returns) / len(returns)
    return mean_return

def volatility(result: BacktestResult):
    returns = get_strategy_returns(result)
    mean = sum(returns) / len(returns)
    total = 0

    for r in returns:
        total += (r - mean) ** 2

    variance = total / len(returns)
    return math.sqrt(variance)

def num_trades(result: BacktestResult):
    positions = result.positions
    num_trades = 0

    for i in range(1, len(positions)):
        if positions[i] != positions[i-1]:
            num_trades += 1

    return num_trades

def exposure(result: BacktestResult):
    positions = result.positions
    return sum(positions[1:]) / (len(positions) - 1)

def sharpe_like(result):
    mean = mean_return(result)
    vol = volatility(result)
    return mean/vol

def summarize(result) -> dict:
    return {
        "Final Equity": final_equity(result),
        "Total Return (%)": total_return(result),
        "Drawdown (%)": max_drawdown(result),
        "Mean Return": mean_return(result),
        "Volatility": volatility(result),
        "Number of Trades": num_trades(result),
        "Exposure": exposure(result),
        "Sharpe-Like Ratio": sharpe_like(result)
    }