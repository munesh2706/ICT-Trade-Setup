# ICT Trade Setup

**Purpose:** ICT-based index analysis, signal generation, historical backtesting, and paper trading using established concepts and models taught by The Inner Circle Trader (Michael J. Huddleston).

## Core principle

This project is **not inventing a new trading setup or a proprietary hybrid strategy**. It will implement and evaluate established ICT concepts and named ICT models using their recognised terminology and rule logic.

Where ICT teachings contain multiple model variants or a rule is not stated consistently across source material, the implementation must document the source/version and preserve the distinction. It must not silently invent a threshold or combine incompatible variants and label the result “standard ICT”.

## Instruments

- NIFTY 50 index
- BANKNIFTY index
- SENSEX index

Individual stocks and index options are on hold.

## Functional scope

1. ICT market-context and liquidity analysis.
2. ICT concept and model recognition.
3. Signal generation with the exact conditions and invalidation logic of the selected ICT model.
4. Historical backtesting and performance analysis.
5. Paper trading and trade journaling.

No live broker orders or automated execution.

## Methodology

Use ICT learning material as the primary methodology reference, including the official ICT mentorship/core content. Concepts and models are to be implemented as taught, not replaced with generic technical-analysis proxies.

The project reference catalogue is in [docs/ICT_FRAMEWORK_REFERENCE.md](docs/ICT_FRAMEWORK_REFERENCE.md). The index data contract is documented in [docs/DATA_SOURCE_AND_STORAGE.md](docs/DATA_SOURCE_AND_STORAGE.md). Source-backed model specifications currently cover [ICT 2022 Mentorship Episode 6](docs/ICT_2022_EPISODE6_RULE_SPEC.md) and the [2023 ICT Silver Bullet](docs/ICT_SILVER_BULLET_2023_RULE_SPEC.md). The full architecture and edge-case matrix are in [docs/ENGINE_ARCHITECTURE_AND_SCENARIOS.md](docs/ENGINE_ARCHITECTURE_AND_SCENARIOS.md). The implementation scope and source hierarchy are in [docs/PROJECT_SCOPE.md](docs/PROJECT_SCOPE.md).

## Engineering principles

- Separate source-faithful ICT definitions from engineering choices needed to encode them.
- Record the source, lesson/model, and rule variant for each implemented concept.
- No look-ahead bias or repainting.
- Use completed candles wherever the source model requires confirmation.
- Preserve missing data as missing; do not fabricate candles.
- Make backtests reproducible and include realistic fees, slippage, and fill assumptions.
- Report sample size, expectancy, drawdown, trade distribution, and out-of-sample results.
- A no-trade result is valid; do not force signals.

## Project boundary

This repository is independent of Nifty50Orderblock. Do not access or modify that project as part of this work.

## Read-only historical data acquisition

After installing `requirements.txt` and configuring the four local Angel One variables in `.env`, historical spot-index candles can be acquired with:

```powershell
python scripts\fetch_index_history.py --start "2026-10-30 09:15" --end "2026-10-30 15:30" --timeframe 1m --instruments NIFTY BANKNIFTY SENSEX
```

The end timestamp is exclusive and uses India local time. The script verifies the instrument master, respects interval-specific historical request windows and API pacing, retains raw response batches, and writes an immutable SQLite snapshot. It performs no order operations.

**Important:** successful acquisition creates an `ACQUIRED` snapshot, not a `VERIFIED` dataset. The exchange-calendar coverage audit must pass before the data store will permit backtest reads. Do not treat an acquired snapshot as complete market history.
