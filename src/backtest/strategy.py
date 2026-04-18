from src.data.bar_types import Bar

def alternating_strategy(bars: list[Bar]) -> list[int]:
    positions = [0]
    for i in range(1, len(bars)):
        if i % 2 == 0:
            positions.append(1)
        else:
            positions.append(0)
    return positions

def always_in_strategy(bars: list[Bar]) -> list[int]:
    positions = [0]
    for _ in range(1, len(bars)):
        positions.append(1)
    return positions