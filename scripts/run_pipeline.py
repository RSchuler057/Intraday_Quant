#This is where code will be ran from the source folder. Keeps things organized and simple.
from src.config.load import load_settings
from src.data.bar_types import Bar
from src.data.fake import make_fake_bars
from src.backtest.simulate import simulate_positions
from src.backtest.strategy import alternating_strategy, always_in_strategy


def main():
    settings = load_settings()

    trading = settings["trading"]
    bar_minutes = trading["bar_minutes"]
    initial_capital = trading["initial_capital"]
    trade_cost = trading["trade_cost"]

    print(bar_minutes)
    print(initial_capital)
    print(trade_cost)
    print(Bar)
    bars = make_fake_bars(bar_minutes=bar_minutes, num_bars=20)
    print(bars[0])
    print(bars[-1])
    strategy1 = always_in_strategy(bars)
    strategy2 = alternating_strategy(bars)
    result1 = simulate_positions(bars, strategy1, initial_capital, trade_cost)
    result2 = simulate_positions(bars, strategy2, initial_capital, trade_cost)
    print(result1.equity[-1])
    print(result1.equity[-1] / result1.equity[0] - 1)
    print(result2.equity[-1])
    print(result2.equity[-1] / result2.equity[0] - 1)

    print(len(result1.timestamps), len(result1.equity), len(result1.returns))
    print(len(result2.timestamps), len(result2.equity), len(result2.returns))

if __name__ == "__main__":
    main()