#This is where code will be ran from the source folder. Keeps things organized and simple.
from config.load import load_settings
from data.types import Bar
from data.fake import make_fake_bars
from backtest.simulate import simulate_buy_and_hold

def main():
    settings = load_settings()

    trading = settings["trading"]
    bar_minutes = trading["bar_minutes"]
    initial_capital = trading["initial_capital"]

    print(bar_minutes)
    print(initial_capital)
    print(Bar)
    bars = make_fake_bars(bar_minutes=bar_minutes, num_bars=20)
    print(bars[0])
    print(bars[-1])
    result = simulate_buy_and_hold(bars, initial_capital=initial_capital)
    print(result)


if __name__ == "__main__":
    main()