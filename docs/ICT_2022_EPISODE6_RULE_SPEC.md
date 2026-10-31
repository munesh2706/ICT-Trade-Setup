# ICT 2022 Mentorship — Episode 6 Model Rule Specification

**Model ID:** ICT_2022_Mentorship_Episode_6  
**Source lesson:** 4 February 2022, Episode 6 — *Market Efficiency Paradigm & Institutional Order Flow; Deep Dive into Fair Value Gaps & Market Structure Shifts*.  
**Original lesson:** https://www.youtube.com/watch?v=Bkt8B3kLATQ  
**Transcript cross-check:** https://info.quagmyre.com/xwiki/bin/view/Forex/The-Inner-Circle-Trader/ICT-Youtube-Series-2022/ICT-YT-2022-02-04-ICT-Mentorship-2022-Episode-6-srt/

This is one named model taught in a specific lesson. It is not a universal rule for every ICT model.

## Source-derived bearish sequence
1. Price trades above an old high or a pool of buy-side liquidity.
2. Price quickly shifts lower with energetic displacement.
3. The displacement closes below a relevant short-term low, confirming the bearish market-structure shift described in the lesson.
4. Search for a bearish three-candle FVG within the displacement range created by the liquidity-raid high and displacement low.
5. If no qualifying FVG forms in that displacement range, the lesson says there is no trade under this model.
6. The lesson discusses entry near the third candle's high and stops above candle one or candle two. These are execution variants; the engine exposes references but does not silently choose between them.
7. Targets are framed using internal range liquidity and external sell-side liquidity, with equilibrium of the displacement range used as context.

## Source-derived bullish mirror
1. Price trades below an old low or sell-side liquidity.
2. Price quickly shifts higher with energetic displacement.
3. The displacement closes above a relevant short-term high.
4. Search for a bullish three-candle FVG within the displacement range.
5. If no qualifying FVG forms in that range, there is no trade under this model.

## Exact FVG geometry
- Bearish: candle 1 low is above candle 3 high. Gap = [candle 3 high, candle 1 low].
- Bullish: candle 1 high is below candle 3 low. Gap = [candle 1 high, candle 3 low].
- Candle 2 is the middle candle of the three-candle formation.

## Engineering assumptions — not ICT-prescribed constants
The lesson does not prescribe a universal machine-readable pivot algorithm, pivot left/right widths, or numerical displacement threshold. The implementation therefore requires these as explicit configuration:
- pivot_left
- pivot_right
- displacement_min_body_to_range
- max_bars_after_sweep
- max_bars_after_mss

The current detector uses strict unique local pivots and candle body/range ratio as a measurable displacement proxy. It also requires explicit maximum bar counts between the liquidity raid and MSS, and between MSS and completion of the qualifying FVG, to prevent unrelated events much later in the dataset from being joined into one setup. These bar-count limits are engineering approximations because the lesson says the shift should occur quickly but does not specify a universal number of bars. All are configurable and must be validated against annotated lesson examples before any performance claim. They are not attributed to ICT.

## Non-repainting constraints
- Only completed candles may enter the detector.
- A pivot is available only after the configured right-side confirmation bars have completed.
- No future candle may be used to label an earlier signal.
- Missing candles remain missing; no synthetic bars.

## Not yet specified by this lesson alone
- Indian-index-specific timeframe mapping.
- Session filter and Indian market time mapping.
- Universal numerical displacement threshold.
- One mandatory stop variant or a single target allocation rule.
- Position sizing, daily risk limit, fees, slippage and paper-fill policy.

These are platform/execution decisions and must be documented separately from ICT methodology.
