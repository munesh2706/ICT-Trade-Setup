# ICT Model Catalogue — Implementation Status

**Status:** Methodology reference and model catalogue required. This is not a proprietary setup specification.

## Governing instruction

Do not design a new setup. Do not turn one convenient sequence into a supposedly universal ICT strategy. Implement the recognised ICT concepts and named models faithfully to the relevant ICT teaching/source.

The project should support separate ICT models as distinct signal families. A model's conditions must come from its source lesson/material. Do not require every ICT trade to follow one universal sequence such as “sweep → MSS → displacement → FVG”; that sequence may describe a particular model/context, but it is not a universal rule for every ICT model.

## Core ICT concept families to catalogue

### 1. Market structure and directional context
- Swing highs and swing lows
- Break of Structure (BOS)
- Change in State of Delivery (CISD)
- Market Structure Shift (MSS), where used in the relevant teaching
- Higher-timeframe and lower-timeframe structure
- Daily bias and draw on liquidity
- Dealing range, equilibrium, premium and discount

### 2. Liquidity
- Buy-side liquidity (BSL) and sell-side liquidity (SSL)
- Previous day/week highs and lows
- Relative equal highs and relative equal lows
- Old highs/lows and swing liquidity
- Session highs/lows and opening-range references where relevant
- Liquidity raid/sweep and liquidity purge concepts

### 3. PD Arrays
- Fair Value Gap (FVG) and consequent encroachment (CE)
- Inversion Fair Value Gap (IFVG)
- Order Block (OB)
- Breaker Block
- Mitigation Block
- Rejection Block
- Balanced Price Range (BPR)
- Volume imbalance and other documented opening gaps/arrays

### 4. Time and price
- ICT dealing sessions and Kill Zones
- Asian range
- London and New York session concepts
- Midnight Open and other daily/weekly opening references
- Judas Swing
- Power of Three / AMD (Accumulation, Manipulation, Distribution)
- Macro times, where the selected model uses them

### 5. Named ICT models
Catalogue and implement separately when their original rules have been sourced:
- 2022 ICT Mentorship model
- Silver Bullet
- Market Maker models (MMXM)
- ICT Unicorn model
- ICT Venom model
- ICT Judas Swing model
- Other named models found in the primary curriculum and explicitly selected for this project

This list is a research catalogue, not a claim that all models are interchangeable or should be active simultaneously.

## Required specification for each model

For every model implemented, record:
1. Exact model name and source lesson/video/document.
2. Source date, mentorship year/version, and timestamp/page where possible.
3. Required market context and directional bias.
4. Required liquidity references and event sequence.
5. Required structure confirmation, if any.
6. Applicable PD Array(s) and their source-faithful definitions.
7. Time/session restrictions, if the model specifies them.
8. Entry trigger and permitted entry variants.
9. Invalidation and stop logic as taught.
10. Target/draw-on-liquidity logic as taught.
11. Explicit exclusions, failure conditions, and examples.
12. Any unresolved ambiguity; do not fill it with an invented rule.

## Signal-engine rule

A signal must identify the exact ICT model and version that generated it. The engine must not output a generic “ICT BUY” or “ICT SELL” when the model identity and qualifying conditions are unknown.

## Next work

Build a source-backed ICT curriculum/model reference first. Then translate each selected model into testable rules with annotated examples. Only after source definitions are documented should implementation and backtesting begin.
