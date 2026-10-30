# Project Scope and Guardrails

## Objective

Develop and validate one ICT-inspired intraday trading model for the underlying Indian indices NIFTY 50, BANKNIFTY, and SENSEX. The system will support market context, setup detection, historical backtesting, and paper trading.

## Included

- Index spot and/or index futures market data, with the chosen signal instrument explicitly specified.
- Higher-timeframe liquidity context.
- Previous day/week levels and intraday session liquidity references, subject to a finalized level specification.
- Liquidity sweep, MSS, displacement, and FVG retracement model.
- Deterministic signal records with reasons and invalidation.
- Historical event replay, performance reports, and paper-trade ledger.
- Data-quality gates, audit logs, and reproducible configuration.

## Excluded / on hold

- Individual stock scanning and stock execution.
- Index options, option-chain analytics, Greeks, premiums, and options execution.
- Live orders, automated broker order placement, and live capital deployment.
- Unapproved imports or code reuse from `Nifty50Orderblock`.

## Initial constraints

- Timezone: `Asia/Kolkata`.
- Trading window proposal: 10:00–15:00 IST.
- Intraday only.
- Maximum one concurrent paper position across this model initially.
- Flat at the end of the defined session; no overnight exposure.
- No trade is preferable to a low-quality or incomplete setup.

## Market representation decision still required

The indices may be represented using index spot candles or exchange-traded index futures candles. This must be decided per index before implementation. The system must not combine levels from one instrument with execution prices from another without an explicit, validated mapping.

## Strategy model (provisional)

1. Establish directional/contextual map from higher-timeframe price and liquidity.
2. Identify a defined buy-side or sell-side liquidity pool.
3. Require a completed-candle sweep under a precise, codified definition.
4. Require a confirmed MSS; the swing-point and close-through rules must be specified.
5. Require displacement under a measurable threshold, not visual judgement alone.
6. Identify a valid FVG from completed candles.
7. Wait for price to retrace into the FVG and apply a precisely defined entry trigger.
8. Define stop, target, timeout, cancellation, and session close rules before a paper trade can be opened.

No step may use future candles. Every event must have an immutable timestamp and reference the candle data that caused it.

## Deferred ICT concepts

OTE, breaker blocks, mitigation blocks, SMT divergence, Silver Bullet time windows, and additional confluences are deferred. They may be introduced only as separately versioned experiments, not silently mixed into the base model.

## Validation requirements

- Unit tests for every pattern and boundary condition.
- No-repainting tests using prefix replay.
- No-look-ahead tests.
- Missing-bar and conflicting-data fail-closed tests.
- Walk-forward and out-of-sample evaluation.
- Sensitivity analysis and realistic transaction-cost modelling.
- Paper trading before any discussion of live execution.

## Change control

Changes to instrument scope, timeframes, event definitions, risk limits, and execution rules require explicit approval and a documented version change.
