# ICT Trade Setup

ICT-based index analysis, signal generation, historical backtesting, and paper trading for Indian indices.

## Scope

**Active instruments**
- NIFTY 50
- BANKNIFTY
- SENSEX

**On hold**
- Individual NIFTY 50 stocks
- Index options

This repository is independent of the `Nifty50Orderblock` project. Do not import, modify, or couple code from that repository unless explicitly approved.

## Operating constraints

- India market timezone: Asia/Kolkata (IST).
- Initial trading window: 10:00–15:00 IST.
- Intraday only; no overnight positions in the initial model.
- One active paper position at a time.
- Research and paper trading only; no live orders or broker order placement.
- No forced trades: a missing setup is a valid no-trade outcome.
- Do not silently change locked strategy rules. Record proposed changes and obtain approval.

## Initial setup model

The first model to specify and test is:

**Liquidity sweep → Market Structure Shift (MSS) → displacement → Fair Value Gap (FVG) retracement → entry confirmation.**

Order Blocks may be recorded as contextual confluence, but should not become a mandatory filter until separately defined and tested. Other ICT concepts (OTE, breaker blocks, SMT divergence, etc.) are deferred until the base model has measurable results.

## Timeframe proposal

| Timeframe | Role |
|---|---|
| Daily / 1H | Higher-timeframe liquidity and context |
| 15m | Intraday structure and dealing range |
| 5m | Sweep, MSS, displacement and setup formation |
| 1m | Entry refinement and paper execution |

These are initial design proposals, not yet fully locked parameters. Exact swing definitions, sweep rules, displacement thresholds, session levels, FVG validity, stop placement, targets, expiry, and risk limits must be specified before coding.

## Development phases

1. Strategy specification and unambiguous event definitions.
2. Data contract, exchange calendar, timezone, and candle quality checks.
3. Deterministic, non-repainting signal engine.
4. Historical event replay and backtesting with realistic costs and execution assumptions.
5. Paper trading and forward validation.
6. Readiness review. Live execution is outside the initial scope.

## Safety and integrity

- Never treat an intrabar condition as confirmed until its required candle has closed.
- Prevent look-ahead bias and repainting.
- Preserve raw source data and record provenance.
- Avoid synthetic candles; missing data must remain missing and block affected signals.
- Backtests must include brokerage, taxes/fees, slippage, and realistic fill assumptions where applicable.
- Report sample size, expectancy, drawdown, win/loss distribution, and out-of-sample results. Do not optimize only for win rate.
- No claim of profitability or live readiness without evidence.

## Repository boundaries

This project is `ICT-Trade-Setup`. Keep all files, issues, experiments, and changes for this work inside this repository. The separate `Nifty50Orderblock` repository is frozen and out of scope.
