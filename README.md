# ICT Trade Setup

**Purpose:** a source-backed ICT research, scanning, visual-analysis and paper-trading platform for the 50 individual NSE cash-equity constituents of NIFTY 50.

## Active scope

- Exactly the current 50 NIFTY 50 constituent stocks, from a dated NSE membership snapshot.
- NSE cash-equity (\`SYMBOL-EQ\`) instruments resolved against the Angel One instrument master.
- Angel One SmartAPI is the only permitted source for historical and live market prices.
- Index spot instruments, index options and non-constituent stocks are not scan targets.
- Paper trading and alerts only. No live order placement, modification or cancellation.

## Delivery priorities

1. **Stock universe and historical data reliability:** versioned constituent snapshots, exact Angel One token resolution, immutable raw response retention, multi-timeframe gap detection, bounded historical backfill and a strict pre-session verification gate.
2. **ICT scanner:** source-backed ICT concepts and named models, multi-timeframe context, explainable evidence and non-repainting signal lifecycle.
3. **Paper trading:** deterministic fills, realistic costs/slippage, risk controls, restart-safe journaling and reproducible backtests.
4. **Visual dashboard:** universe/data health, stock scanner, setup evidence, invalidation, paper positions, performance and audit trail.

## Data integrity rules

- No fabricated, interpolated, forward-filled or synthetic OHLCV candles.
- Missing expected timestamps are detected against an explicit NSE session calendar and repaired by downloading the exact historical ranges from Angel One.
- Data is not released to the strategy until the full requested grid is verified.
- Holidays, weekends and special sessions must be represented by an explicit calendar with provenance; the system does not assume all weekdays are normal sessions.
- A provider response that still omits expected bars after bounded retries keeps the pre-session gate closed.
- Historical constituent membership is point-in-time only when archived official snapshots exist. The current NSE list must not be projected backwards into historical backtests.

## First-stage implementation

See [Stock Universe and Historical Reconciliation](docs/STOCK_UNIVERSE_AND_RECONCILIATION.md).

Main modules:
- \`ict_engine/stock_universe.py\` — official NSE constituent snapshot and strict Angel One cash-equity token resolution.
- \`ict_engine/stock_feed.py\` — read-only Angel One SmartAPI historical feed for the 50 NSE EQ instruments.
- \`ict_engine/stock_storage.py\` — immutable SQLite candle snapshots and raw response batches.
- \`ict_engine/stock_reconciliation.py\` — expected-grid gap detection, Angel One backfill and verification gate.
- \`scripts/reconcile_nifty50_history.py\` — pre-session reconciliation CLI.

The required calendar is explicit and source-backed. An illustrative schema (not actual exchange dates) is documented in the stock reconciliation guide. The daily-candle timestamp convention must be explicitly selected when requesting \`1d\`; it is not guessed.

## ICT methodology

ICT learning material remains the methodology source. Source-faithful definitions must be separated from engineering choices. If a lesson contains variants or contradictory guidance, document the source/version and do not silently invent a universal rule. Current model references and detection primitives are being adapted to individual equities after the data layer is complete.

## Engineering constraints

- No look-ahead bias or repainting.
- Completed candles for confirmation-based rules.
- Explicit data provenance, timestamps, source, token and snapshot identity.
- Backtests only on verified datasets.
- Report sample size, expectancy, drawdown, fees, slippage and out-of-sample results.
- No-trade and data-unavailable are valid states; never force a signal.

## Project boundary

This repository is independent of \`Nifty50Orderblock\`. Do not access or modify that separate project as part of this work.
