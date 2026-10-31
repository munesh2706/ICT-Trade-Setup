# ICT Trade Setup — NIFTY 50 Stocks

**Purpose:** a source-backed ICT research, signal, paper-trading and visual-monitoring platform for the 50 individual NSE equity constituents of the NIFTY 50.

## Instrument universe

- Exactly 50 NIFTY 50 constituent stocks, using a dated NSE constituent snapshot.
- Each symbol is resolved against the Angel One SmartAPI instrument master before data acquisition.
- Equity tokens, NSE segment and per-stock tick size are sourced from Angel One's master.
- NIFTY index, BANKNIFTY index, SENSEX, index options and non-constituent stocks are out of scope.

Membership changes over time. Historical backtests must use membership effective on the historical date, not today's list retroactively.

## Market-data source policy

Angel One SmartAPI is the sole source for historical candles, live quotes and streaming ticks. NSE's official constituent file and official exchange circulars are used only for constituent membership and trading-session calendars; they are not price-data substitutes.

- Historical candles: Angel One Historical API.
- Live quotes: Angel One WebSocket V2 and SmartAPI quote API.
- Instrument identity and tick size: Angel One OpenAPIScripMaster.
- No other vendor's OHLCV, quotes or adjusted prices may fill gaps.
- No interpolation, forward-fill, synthetic candles or fabricated historical prices.
- A derived timeframe is permitted only when every constituent Angel One source candle is present and the aggregation retains source lineage.

## Pre-session and live data workflow

The system performs a full historical reconciliation before the scanner starts:

1. Load the dated NIFTY 50 constituent snapshot.
2. Resolve all 50 NSE EQ instruments and tokens from Angel One's instrument master.
3. Compare every required stock/timeframe timestamp with the explicit NSE trading calendar.
4. Identify gaps spanning minutes, hours or multiple trading sessions.
5. Fetch only missing ranges from Angel One, respecting interval-specific API limits.
6. Validate timestamp order, duplicates, OHLCV, session boundaries and exact expected-grid coverage.
7. Release only verified data to the ICT engine.

During the session, completed 1m, 5m and 15m candles are incrementally refreshed from Angel One Historical API. Each stock/timeframe has its own readiness gate. A stock with an unresolved current-session gap is excluded from scanning; other verified stocks may continue. WebSocket ticks are for live quote monitoring and are never used to invent OHLC candles.

The main process is scripts/run_nifty50_session.py. It authenticates once, performs pre-session reconciliation, starts the quote stream, refreshes completed candles, runs the scanner and paper engine, and writes timestamped JSON reports.

The local visual dashboard is served by dashboard/app.py and dashboard/index.html. Start it in a second terminal with:

~~~powershell
python -m uvicorn dashboard.app:app --host 127.0.0.1 --port 8000
~~~

It shows constituent readiness and candle counts, live quote age, explainable ICT setup stages, verified candlestick charts with FVG/liquidity/stop overlays, and open/closed paper positions. It is read-only and intended for localhost.

## ICT model scope

- ICT 2022 Mentorship Episode 6: liquidity raid → displacement/MSS → in-range FVG candidate.
- ICT Silver Bullet 2023: New York-local windows with DST-aware conversion and FVG/retest candidate detection.
- Context includes previous-day/week liquidity, optional explicit equal-high/low clustering, weekly dealing range and directional liquidity objectives.
- Model variants and engineering assumptions remain labelled. No universal bias is forced.
- Silver Bullet is currently alert-only in the paper engine; its live entry chronology must be completed before paper fills are enabled.

The model catalogue and source specifications are in docs/ICT_FRAMEWORK_REFERENCE.md, docs/ICT_2022_EPISODE6_RULE_SPEC.md and docs/ICT_SILVER_BULLET_2023_RULE_SPEC.md.

## Paper trading and historical replay

Paper trading is broker-free and restart-safe. It uses verified Angel One 1m candles, per-stock tick sizes, explicit entry/stop/target variants, configurable risk limits, and a persistent event journal. Entry bars are excluded from exit processing; same-bar entry/stop/target ambiguity is rejected rather than guessed. No live order placement, modification or cancellation exists in the project.

The historical replay CLI is scripts/backtest_nifty50_ict.py. It reconciles Angel One history before replay, runs one-minute event-driven scans and reports in-sample/out-of-sample metrics. It refuses to apply a current constituent snapshot to older dates unless the user explicitly opts into survivorship bias. See docs/BACKTEST_RUNBOOK.md.

Before starting either runner, copy config/paper_trading.example.json to config/paper_trading.json and enter the actual starting equity, round-trip fees per share and slippage assumptions. The flat per-share cost input is an explicit approximation, not a live Angel One charge calculator. Local capital/risk configuration is ignored by Git.

## Engineering principles

- No look-ahead, repainting or fabricated market data.
- Only completed candles are used for confirmed signals and paper execution.
- Missing data is actively backfilled before the data gate opens.
- All acquisitions retain immutable snapshots and raw provider responses.
- Backtests and paper results must identify data snapshots, rule versions, costs and assumptions.
- A no-trade result is valid; signals are never forced to meet a target count.
- No profitability claim is made until out-of-sample validation supports it.

## Operating instructions

See docs/PRE_SESSION_RUNBOOK.md, docs/STOCK_UNIVERSE_AND_RECONCILIATION.md and docs/BACKTEST_RUNBOOK.md.

## Project boundary

This repository is independent of Nifty50Orderblock. Do not access or modify that separate project as part of this work.
