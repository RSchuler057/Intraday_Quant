from datetime import datetime
from dataclasses import dataclass

@dataclass
class Bar:
    ts: datetime
    open: float
    high: float
    low: float
    close: float
    volume: int
