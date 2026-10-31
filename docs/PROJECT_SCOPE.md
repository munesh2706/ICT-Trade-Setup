# Project Scope and Methodology Guardrails

## Objective

Build a source-backed ICT research, signal-generation, historical-replay, broker-free paper-trading and visual-monitoring platform for the **50 individual NSE cash-equity constituents of the NIFTY 50**.

This is the authoritative current scope for the stock platform. Older index-focused modules and documents are legacy research assets; they do not expand the active instrument universe.

## Instruments

- Exactly the 50 NIFTY 50 constituent stocks represented by a dated, provenance-preserving NSE constituent snapshot.
- Each stock must resolve to its exact Angel One NSE EQ instrument/token and tick size before data acquisition or execution simulation.
- No NIFTY index, BANKNIFTY index, SENSEX, index options, futures, or non-constituent equities in the active stock scanner.
- Historical membership must be effective-dated. Today's constituent list must not be silently applied to historical periods.

## Included

- Source-backed, separately versioned ICT concepts and named models.
- Higher-timeframe context and liquidity mapping where the source model requires it.
- Liquidity-event, market-structure-shift, displacement and fair-value-gap evidence.
- Model-specific session/time windows with correct exchange and IANA timezone handling.
- Explainable signals with source candles, timestamps, model version, assumptions, entry references, invalidation references and liquidity targets.
- Angel One historical candle acquisition, reconciliation, verified storage and live quote monitoring.
- Event-driven historical replay, explicit costs/slippage assumptions, out-of-sample reporting and broker-free paper execution.
- A local visual dashboard for universe readiness, quote freshness, setup evidence, verified candles, paper positions and performance.

## Excluded

- Fabricating, interpolating, forward-filling or silently substituting missing OHLCV or quotes.
- Creating proprietary rules and presenting them as standard ICT.
- Arbitrary indicator filters substituted for ICT model definitions.
- Combining incompatible ICT model variants without explicit versioning and evidence.
- Index/option trading in the active stock platform.
- Live broker order placement, modification or cancellation.
- Changes to the separate Nifty50Orderblock repository.

## Source hierarchy

1. **Primary:** Michael J. Huddleston / The Inner Circle Trader's original mentorship lessons, official website and original teaching material.
2. **Secondary:** Reputable educational material used only to cross-check terminology or clarify source passages; it must not override primary teaching.
3. **Engineering specification:** A machine-readable interpretation of the source rule. Every choice not explicitly prescribed by the source must be labelled as an implementation assumption, independently configurable where appropriate, and tested against annotated source examples.

If two lessons or model variants differ, preserve them as separately named/versioned variants. Do not resolve a conflict by inventing a compromise.

## Model fidelity and signal evidence

- A named ICT model is not a generic label for any FVG or market-structure pattern.
- Each detector must implement only the conditions supported by its cited source lesson.
- A signal must be reproducible from completed, verified source candles and retain the relevant candle timestamps and evidence.
- No look-ahead, repainting, synthetic candles, retroactive fills or unverified data substitutions.
- A no-trade result is valid. The scanner must not force a minimum signal count.
- Engineering approximations (pivot widths, numerical displacement proxies, bar-count windows, fill policies, target selection and stop variants) must remain visibly distinguished from source-derived ICT rules.

## Data and validation

- Angel One SmartAPI is the sole price-data source for the active stock platform.
- NSE official constituent files and official exchange circulars provide membership/calendar provenance, not substitute price data.
- Preserve provider responses, acquisition metadata, instrument-master hash, candle snapshots and reconciliation outcomes.
- Validate timestamp order, duplicates, OHLCV consistency, exchange sessions and expected completed-candle grids.
- A stock with unresolved required candle gaps is not eligible for a confirmed signal or paper fill.
- Derived timeframes are allowed only when all source candles are present and source lineage is retained.
- Backtests must disclose survivorship bias, data coverage, model version, execution assumptions, costs and slippage.
- Report expectancy, drawdown, sample size and out-of-sample performance; win rate alone is insufficient.
- No profitability or production-readiness claim is permitted without evidence.

## Trading and operating constraints

- The active scanner operates on NSE cash-equity session hours and the explicit NSE trading calendar.
- New York-local ICT windows must be converted using the IANA `America/New_York` timezone database; do not hard-code a fixed IST offset.
- Paper risk limits, entry variants, stop references, target selection, quantity step, fees and slippage are platform execution settings, not ICT rules.
- The dashboard is read-only and intended for localhost unless authentication and deployment security are separately implemented.
- No live broker order endpoint may be called by the paper engine or dashboard.

## Change control

Any departure from a cited ICT lesson, addition of a custom filter, change to a model condition, or change to an execution assumption must be documented as a separate deviation/experiment. It must not silently replace the source-faithful model.
