#Load raw/interim/processed data into memory (pandas, polars, numpy).
from data.bar_types import Bar
from datetime import datetime

def load_processed_data(path: str) -> list[Bar]:
    bars = []

    with open(path, "r") as f:
        next(f) #Skip header

        for line in f:
            symbol, ts, open_, high, low, close, volume, interval = line.strip().split(",")

            bar = Bar(
                ts = datetime.fromisoformat(ts.rstrip("Z")),
                open=float(open_),
                high=float(high),
                low=float(low),
                close=float(close),
                volume=int(volume)
            )

            bars.append(bar)
    
    return bars