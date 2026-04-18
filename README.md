# Intraday Quant

An early-stage intraday stock-market research project focused on building a
small, understandable quant pipeline from the ground up.

The project is being developed gradually so each piece can be explained,
tested, and improved before adding more realistic market data or modeling.

## Current Focus

The current focus is the backtesting foundation:

- generate deterministic fake intraday bars
- define simple example strategies
- simulate an equity curve from positions
- compare strategy behavior before adding real data

## Project Layout

- `scripts/` - runnable project entry points
- `src/data/` - data types, fake data, loading, and future downloads
- `src/backtest/` - strategy simulation and performance metrics
- `src/features/` - future feature engineering code
- `src/labels/` - future supervised-learning labels
- `src/models/` - future model training and prediction code
- `src/splits/` - future walk-forward validation logic
- `notebooks/` - exploratory notes and analysis
- `cpp/` - future C++ experiments

## Next Step

Clean up the backtester interface and add small tests that prove the equity
math is correct before moving on to real market data.
