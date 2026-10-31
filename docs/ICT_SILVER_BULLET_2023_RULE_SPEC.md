# ICT Silver Bullet — 2023 Model Rule Specification

**Model ID:** ICT_SILVER_BULLET_2023  
**Primary source:** The Inner Circle Trader, 2023 ICT Mentorship — ICT Silver Bullet Time Based Trading Model (published 14 May 2023).  
**Original video:** https://www.youtube.com/watch?v=tRq1hyGGtl4  
**Transcript cross-check:** https://info.quagmyre.com/xwiki/bin/view/Forex/The-Inner-Circle-Trader/ICT-Youtube-Series-2023/ICT-YT-2023-05-15-ICT-Mentorship-ICT-Silver-Bullet-Time-Based-Trading-Model/

## Source-derived time windows
The lesson specifies New York local time and identifies three separate 60-minute windows:
- 03:00–04:00 — London Open Silver Bullet.
- 10:00–11:00 — New York AM Silver Bullet.
- 14:00–15:00 — New York PM Silver Bullet.

The window governs setup/entry timing; it does not require the trade to exit within that same hour. A trade may remain open after the window closes.

## Source-derived setup principles
- This is a time-based model, not a generic all-day FVG strategy.
- Identify the most likely draw on liquidity before focusing on entry precision.
- The lesson gives possible draws including previous day high/low, previous session high/low, previous week high/low, New Week Opening Gap references, and inefficiencies/PD arrays in the direction of the draw.
- The lesson discusses the first FVG presented within the relevant time window and entry into that FVG.
- A setup is not valid merely because an FVG appears; it must be evaluated in relation to the draw on liquidity and the broader price narrative.
- The lesson includes bullish and bearish examples and describes the model as applicable across asset classes.

## Important source ambiguity
The lesson initially describes a minimum potential price framework of 10 points/40 ticks for indices, then later says the 10-handle objective is not required in the illustrated trade and discusses a five-handle partial objective. The implementation must preserve this nuance rather than silently hard-code a universal 10-point filter. Any numeric framework filter must remain a separately identified model variant/configuration and be tested against the original examples.

## India index applicability
The three windows are defined in New York local time, not IST. They must be converted with the America/New_York timezone database so daylight-saving transitions are respected.
- The 03:00–04:00 New York window overlaps the regular Indian cash-index session. It converts to 13:30–14:30 IST during New York standard time and 12:30–13:30 IST during New York daylight time.
- The 10:00–11:00 New York window converts to evening IST and does not overlap the regular Indian session.
- The 14:00–15:00 New York window converts to after midnight IST and does not overlap the regular Indian session.

This is a market-hours applicability constraint, not a modification of ICT's model. If the selected data series has different trading hours, reassess overlap using its actual exchange calendar.

## Engineering assumptions still requiring validation
- Exact algorithm for selecting the draw on liquidity when multiple candidate levels exist. The initial detector requires this level to be supplied by separate context analysis.
- What constitutes the first eligible FVG if several form in the same window. The initial detector selects the first direction-aligned FVG; this is an explicit engineering interpretation requiring source-example validation.
- Exact entry price within the FVG and whether the chosen variant uses consequent encroachment.
- Exact stop placement and target-taking sequence for each variant.
- How to handle an FVG that forms in-window but retraces after the window; the lesson says entry timing is within the window, so default behavior should not allow late entry unless a separate source variant supports it.
- Minimum framework should not be hard-coded until the source's internal nuance is resolved against full video examples.

The initial detector now identifies the first direction-aligned FVG formed wholly within one of the exact New York windows and requires a subsequent FVG-zone retest by a fully completed candle before the same window closes. It retains draw-on-liquidity evidence, window identity, timezone conversion, FVG completion time and retest candle. This is a candidate detector, not a fully specified order: it does not choose an exact entry price, stop variant, partial exits or final target-taking sequence. Those remain separate model/execution decisions and must be validated against the original lesson before performance claims.