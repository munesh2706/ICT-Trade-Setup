# Project Scope and Methodology Guardrails

## Objective

Build an index-focused ICT analysis and research platform that recognises established ICT concepts and models, generates model-faithful signals, backtests them, and supports paper trading.

## Instruments

- NIFTY 50 index
- BANKNIFTY index
- SENSEX index

Individual stocks and index options are on hold.

## Included

- ICT higher-timeframe analysis and daily/weekly bias context.
- Liquidity mapping and liquidity-event recognition.
- Market structure and displacement analysis.
- ICT PD Arrays and consequent encroachment concepts.
- Recognition of established ICT trade models and session/time concepts.
- Signal records with model name, direction, context, evidence, entry logic, invalidation, and target logic.
- Historical backtesting, paper execution, journaling, and performance reporting.

## Excluded

- Creating a proprietary setup and presenting it as standard ICT.
- Arbitrary indicator-based filters or generic TA rules substituted for ICT definitions.
- Mixing unrelated ICT model variants without documenting the source and rationale.
- Individual stock scanning and index options.
- Live order placement and automated broker execution.
- Any changes to the separate Nifty50Orderblock repository.

## Source hierarchy

1. **Primary:** Michael J. Huddleston / The Inner Circle Trader's own mentorship lessons, official website, and original teaching material.
2. **Secondary:** Reputable educational material used only to cross-check terminology or clarify a point—not to override primary ICT teaching.
3. **Engineering specification:** Exact machine-readable interpretation of a source rule. Every engineering choice not explicitly stated in the source must be labelled as an implementation assumption, not attributed to ICT.

If two ICT lessons or model variants differ, preserve both as separately named/versioned variants until the user chooses which one to implement. Do not resolve a conflict by inventing a compromise.

## Important distinction

ICT is a broad methodology and curriculum containing multiple concepts and trade models, not one single universally fixed entry setup. “Widely accepted ICT rules” therefore means faithfully implementing established definitions and named models, while explicitly identifying which model and teaching/source version is being used.

## Trading and operating constraints

The previously discussed intraday window and paper-only operation are platform operating constraints, not ICT methodology rules. They must remain configurable and must never be represented as rules taught by ICT. The exact market session mapping for Indian indices must be documented separately; do not directly copy New York clock times into IST without deliberate session-time conversion and source rationale.

## Data and validation

- Select and document the price series used for each index (index spot or corresponding futures). Do not mix them silently.
- Preserve raw data and source provenance.
- Document exchange calendar, timezone, candle construction, and missing-bar handling.
- No look-ahead bias, repainting, or future-candle confirmation.
- Reproduce source rules in tests with annotated examples.
- Backtest with realistic fees, slippage, and fill assumptions.
- Use out-of-sample and walk-forward validation; report drawdown and expectancy, not just win rate.

## Change control

Any departure from a cited ICT teaching, addition of a custom filter, or change to a model's conditions must be explicitly labelled as a deviation/experiment and approved before inclusion in the standard model implementation.
