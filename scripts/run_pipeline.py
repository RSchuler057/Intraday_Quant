#This is where code will be ran from the source folder. Keeps things organized and simple.
from src.config.load import load_settings
#from src.data.fake import make_fake_bars
from src.data.load import load_processed_data
from src.backtest.simulate import simulate_positions
from src.backtest.strategy import alternating_strategy, always_in_strategy, momentum_strategy
from src.backtest.metrics import summarize
from src.utils.reporting import print_summary

def main():
    settings = load_settings()

    trading = settings["trading"]
    bar_minutes = trading["bar_minutes"]
    initial_capital = trading["initial_capital"]
    trade_cost = trading["trade_cost"]
    bars = load_processed_data("data/processed/AAPL2026_processed.csv")
    
    strategies = {
        "Alternating": alternating_strategy,
        "Always In": always_in_strategy,
        "Momentum Strategy": momentum_strategy
    }
    
    for name, strategy in strategies.items():
        positions = strategy(bars)
        result = simulate_positions(bars, positions, initial_capital, trade_cost)
        strategy_summary = summarize(result)
        print_summary(name, strategy_summary)

if __name__ == "__main__":
    main()