#Creates fake bars for testing purpoeses
import random
from datetime import datetime, timedelta
from src.data.bar_types import Bar

def make_fake_bars(bar_minutes: int, num_bars: int, seed: int = 0) -> list[Bar]:
    rng = random.Random(seed)
    bars = []
    ts = datetime(2026, 2, 4, 9, 30)
    last_close = 100.0
    
    for _ in range(num_bars): 
        open_price = last_close
        pct = rng.uniform(-0.002, 0.002)
        wiggle = rng.uniform(0, 0.001)

        close_price = open_price * (1 + pct)
        high = max(open_price, close_price) * (1 + wiggle)
        low = min(open_price, close_price) * (1 - wiggle)
        volume = rng.randint(100, 1000)
        bar = Bar(ts=ts, open=open_price, high=high, low=low, close=close_price, volume=volume)
        bars.append(bar)
        ts += timedelta(minutes=bar_minutes)
        last_close = close_price
    
    return bars
