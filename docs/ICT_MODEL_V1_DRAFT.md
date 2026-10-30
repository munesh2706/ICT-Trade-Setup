# ICT Model V1 — Draft for Review

**Status:** Draft. Not approved for coding or live use.

## Instruments

- NIFTY 50
- BANKNIFTY
- SENSEX

Signals are generated on the underlying selected for each index. Options and individual stocks are out of scope.

## Intended trading hours

10:00–15:00 IST, intraday only. Exact rules for setup formation cut-off, last entry time, and forced session exit remain to be approved.

## Timeframe roles (proposed)

- Daily / 1H: external liquidity, major swing context, prior day/week levels.
- 15m: dealing range and intraday structure.
- 5m: liquidity raid, MSS, displacement, FVG formation.
- 1m: retracement and entry refinement.

## Base sequence

### A. Liquidity map
Define relevant external and internal liquidity levels. Candidate references include prior day high/low, prior week high/low, confirmed swing highs/lows, and equal highs/lows. Exact lookback and equal-level tolerance are unresolved.

### B. Liquidity sweep
A sweep must be defined mechanically: which liquidity pool is eligible, how far price must trade through it, whether a candle close back inside is required, and how stale levels expire. Until defined, no automated sweep signal is permitted.

### C. Market Structure Shift
MSS must use a confirmed swing point and a completed candle close beyond that swing. Swing length, buffer, and relationship to the sweep are unresolved. Intrabar breaks do not count as confirmed MSS.

### D. Displacement
Require a completed impulse candle or sequence with objective body/range/ATR criteria and directional close. Thresholds and volume use are unresolved; visual labels alone are not accepted.

### E. Fair Value Gap
Use a three-candle imbalance definition with candle indexing and minimum size specified in ticks/points or volatility units. FVG invalidation, partial fills, and expiry require formal definitions.

### F. Entry
Wait for retracement into the qualifying FVG. Entry method (touch, midpoint, rejection close, or lower-timeframe structure confirmation) is unresolved. No assumed fill at a price that was not realistically tradable.

### G. Risk and exits
Stop placement, buffer, target liquidity, minimum reward:risk, time stop, daily loss limit, and position sizing are all unresolved. No trading implementation until these are specified.

## Required approval questions

1. Signal and execution data source: index spot or index futures for each of NIFTY, BANKNIFTY, and SENSEX?
2. Should the liquidity sweep require a wick through the level and close back inside, or is a close beyond the level allowed?
3. Which swing algorithm defines MSS (e.g., 2-left/2-right confirmed fractal, or another exact rule)?
4. What objective displacement threshold should be tested (ATR multiple, body-to-range, minimum points, or a combination)?
5. Should FVG entry be first touch, midpoint, or a 1m/3m confirmation after entering the gap?
6. Where is the stop anchored: sweep extreme, FVG boundary, or a structure point plus buffer?
7. Target policy: opposing liquidity, fixed R multiple, or partial at one and runner to the other?
8. What per-trade risk and daily loss cap should be used for paper evaluation?

## Current decision

Only the instrument scope (three indices), index-only focus, ICT base sequence, initial intraday window, and research/paper-only mode are carried forward from the planning discussion. All exact thresholds and risk rules remain unapproved.
