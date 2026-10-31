# Engine Architecture and Scenario Coverage

## Architectural boundary

The platform is split into five independently testable layers:
1. **Market data:** raw broker responses, canonical OHLC candles, timestamps, instrument metadata, session calendar and provenance.
2. **ICT context:** dealing ranges, premium/discount, liquidity reference levels, swing structure and PD arrays.
3. **Named model detectors:** source-versioned rule sets. A detector returns evidence and candidate state; it does not place orders.
4. **Signal/risk layer:** validates entry variant, invalidation, target references, risk budget and operational constraints.
5. **Research execution:** historical simulation and broker-free paper trading, journals and reports.

No layer may silently repair missing data or change another layer's source rules.

## Data contract
- Instrument identity is explicit: NIFTY 50 index, BANKNIFTY index, or SENSEX index.
- Price series identity is explicit. Spot index and futures are different series and must never be concatenated or silently substituted.
- All stored timestamps are timezone-aware. Exchange-local presentation uses Asia/Kolkata.
- Candle intervals are anchored to the documented exchange session calendar, not to the machine's local timezone.
- Raw provider payloads are retained separately from normalized candles.
- Duplicate, out-of-order, malformed, missing and stale observations are surfaced as data-quality states.
- A candle is final only after its interval closes and the feed's finalization policy is satisfied.
- Missing candles remain missing. No forward-fill or synthetic OHLC bars enter model detection.
- Session holidays, special sessions, shortened sessions and exchange halts must come from an explicit calendar input.

## ICT context requirements
The context layer must be able to represent, without forcing all of them into every model:
- Prior day/week/month highs and lows.
- Multi-period liquidity map that lists draws above and below current price without forcing a directional bias.
- Confirmed swing highs/lows and relative equal highs/lows.
- Buy-side and sell-side liquidity references and observed raids.
- Source-defined dealing ranges and equilibrium.
- Premium/discount classification relative to the selected range.
- FVG boundaries and consequent encroachment.
- Other PD Arrays only after their individual source definitions and tests are documented.
- Daily/weekly narrative and draw-on-liquidity references as evidence, not as a forced directional label.

## Signal lifecycle
A model candidate follows an explicit lifecycle:

OBSERVING → LIQUIDITY_EVENT → STRUCTURE_CONFIRMED → PD_ARRAY_QUALIFIED → ENTRY_ARMED → FILLED → OPEN → CLOSED

Terminal or non-trade states include:
- NO_SETUP: required source condition did not occur.
- INVALIDATED: structural premise failed before entry.
- EXPIRED: model's source-defined time/validity window ended, if one exists.
- CANCELLED_DATA: data became unreliable before execution.
- MISSED: price never retraced to the selected entry.
- REJECTED_RISK: candidate exists but sizing or risk policy forbids it.

Not every model uses every state. Model-specific transitions must be explicit; no universal sequence is imposed.

## Failure and edge-case matrix
| Scenario | Required behavior |
|---|---|
| No qualifying liquidity reference | No candidate; explain missing prerequisite |
| Liquidity reference is crossed before it is confirmed | Do not use future confirmation to backdate the event |
| Equal highs/lows have ambiguous tolerance | Keep tolerance explicit; do not invent one |
| Sweep and MSS occur inside one OHLC candle | Mark intrabar order unknown; do not infer sequence from OHLC |
| MSS wick breaks but close does not | Apply the exact model rule; Episode 6 requires a convincing close through structure |
| Weak/slow displacement | Expose numeric proxy as an engineering assumption |
| FVG absent in required displacement range | No trade for Episode 6 |
| FVG exists elsewhere on chart but not in model range | Reject for Episode 6 |
| FVG only partially overlaps range | Reject unless source model explicitly allows overlap |
| FVG never retraces to entry | Mark MISSED; never fabricate a fill |
| Price gaps through stop | Simulate adverse opening fill, not ideal stop price |
| Stop and target both touched in same OHLC bar | Chronology unknown; conservative stop-first assumption and ambiguity flag |
| Duplicate/out-of-order candle | Quarantine or fail data window; never reorder silently inside detector |
| Missing candle in setup sequence | Mark sequence incomplete; do not synthesize a bar |
| Feed stale/disconnected | Suspend new signals and paper fills until data health recovers |
| Exchange holiday/special session | Use explicit calendar; do not assume ordinary 09:15–15:30 |
| Foreign-market session crosses DST | Convert source session timezone using timezone database; do not hardcode fixed IST offset |
| Multiple model candidates overlap | Keep separate model IDs; apply portfolio concurrency policy only after configured |
| Opposing model signals coexist | Preserve both evidence records; do not net into generic signal |
| Risk budget cannot fund minimum quantity step | Reject with REJECTED_RISK |
| Daily loss limit reached | Block new entries for configured risk day; continue managing open positions |
| Process restarts while paper trade is open | Restore state from journal and reconcile last processed candle ID |
| Same candle replayed twice | Idempotency key prevents duplicate events, fills and journal rows |
| Provider revises historical data | Version snapshots and rerun affected backtests |

## Backtesting requirements
- Event-driven processing: decisions use only information available at that timestamp.
- Model candidates and fills carry source IDs, data snapshot IDs and parameter/config hashes.
- Entry fill rules define touch vs close confirmation, limit-price improvement, gaps, partial fills and no-fill behavior.
- Stop/target collision inside one OHLC bar is ambiguous; use conservative resolution unless higher-resolution data resolves order.
- Include instrument-specific tick size, point value/multiplier, fees, taxes/charges and slippage as explicit configuration.
- Report gross/net P&L, expectancy, profit factor, max drawdown, average win/loss, MAE/MFE, exposure, holding time, trade count and missed setups.
- Split development, validation and untouched out-of-sample periods chronologically.
- Use walk-forward evaluation and parameter sensitivity. Do not optimize against the final test period.
- A zero-trade or negative-expectancy result is valid.

## Paper trading safeguards
- Paper-only adapter; no broker order endpoints or order-placement code.
- A paper position needs entry, invalidation, target plan, quantity, cost model and model evidence before opening.
- Risk limits are configuration, not hardcoded personal assumptions.
- Rejected signals remain in journal with rejection reason.
- Disconnected or stale feed blocks new simulated entries.
- Every event is idempotent and timestamped.
- Paper P&L is not evidence of live profitability.

## Current implementation status
Implemented in the current feature branch:
- Candle and event domain types.
- Read-only Angel One historical index adapter with documented interval request chunking and pacing.
- Immutable SQLite candle snapshots with ACQUIRED/VERIFIED/FAILED states.
- Exchange-calendar candle-grid audit; only VERIFIED snapshots are backtest-readable.
- Explicit index instrument registry for NIFTY, BANKNIFTY and SENSEX.
- Confirmed swing pivots with right-bar confirmation.
- Liquidity penetration events at confirmed swings.
- Bullish/bearish three-candle FVG geometry.
- Initial 2022 Mentorship Episode 6 detector.
- 2023 Silver Bullet candidate detector with exact New York windows, DST conversion, first directional FVG and same-window retest.
- Dealing range, equilibrium, premium/discount and prior-period liquidity references.
- Relative equal-high/low clustering with explicit tolerance.
- FVG consequent encroachment.
- Generic paper position sizing and conservative OHLC barrier resolution.
- Daily portfolio risk guardrails, filled-position P&L simulation and net-of-cost performance statistics.

Still required:
- Feed normalization and historical/live data repository.
- Exchange calendar and session/timezone engine.
- Multi-timeframe context engine and daily/weekly narrative.
- Source-backed PD Array catalogue beyond FVG.
- Additional separately versioned named ICT models.
- Model-independent signal lifecycle and persistence.
- Restart-safe persistence for signal and paper-trade event history.
- Event-driven backtester and walk-forward reports.
- Restart-safe paper trade journal and monitoring interface.