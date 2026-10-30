# Orderblock Data-Foundation Migration Record

**Status:** Reference material copied; not approved for direct execution in the ICT project.

## Source and boundary

Source repository: `munesh2706/Nifty50Orderblock` (private, frozen by the user).
Destination repository: `munesh2706/ICT-Trade-Setup`.

Only market-data foundation material was copied. No source file in the Orderblock repository was modified. No Order Block strategy, stock selector, scanner, stock mapping, or paper-trading logic was copied.

## Copied reference files

| Destination | Original source | Intended reuse |
|---|---|---|
| `reference/orderblock_data_foundation/PHASE2_DATA_FOUNDATION.md` | `docs/PHASE2_DATA_FOUNDATION.md` | Design reference for historical/live candles, integrity, recovery, storage and credentials |
| `reference/orderblock_data_foundation/collect_historical_uploaded.py` | `scripts/collect_historical_uploaded.py` | Reference for Angel One authentication boundary, broker response parsing, OHLCV validation and SQLite persistence |
| `reference/orderblock_data_foundation/live_candle_builder.py` | `scripts/live_candle_builder.py` | Reference for tick validation and provisional candle construction |
| `reference/orderblock_data_foundation/live_feed_health.py` | `scripts/live_feed_health.py` | Reusable design for persisted feed-health states |
| `reference/orderblock_data_foundation/live_canonical_feed.py` | `scripts/live_canonical_feed.py` | Reference for completed-candle verification, rate pacing, canonical history and 1m/5m parity |
| `reference/orderblock_data_foundation/nse_equities_2026.json` | `data/calendars/nse_equities_2026.json` | Historical 2026 NSE equities holiday snapshot only |

These files are preserved as reference copies, not imported into the runtime or treated as ICT logic.

## Required adaptation before use

The source project was built around NIFTY 50 constituent stocks and NSE cash tokens. The ICT project has only three index instruments: NIFTY 50, BANKNIFTY and SENSEX. Consequently:

- Remove all dependence on a 50-stock constituent map and stock selector.
- Resolve and validate the correct index instrument identifiers/tokens independently for each exchange.
- NIFTY 50 and BANKNIFTY are NSE indices; SENSEX is a BSE index. Do not assume the NSE exchange/token/API path works for SENSEX.
- Verify Angel One's currently supported historical and streaming data access for each index before selecting the final feed.
- The copied collector/feed contain NSE-specific session assumptions and an effective-date change. Re-verify the current exchange calendars and session rules for both NSE and BSE.
- The copied calendar is an NSE equities 2026 snapshot, not a complete multi-year NSE+BSE index calendar. It must not be used as the production calendar for all three indices.
- Do not treat sampled WebSocket QUOTE-derived bars as authoritative OHLCV. Use verified broker historical candles or a properly validated trade feed.
- Keep credentials in local environment configuration only; never copy `.env`, tokens, or secrets into Git.
- Build a separate ICT project's own database/schema and instrument master. Do not share or mutate the Orderblock SQLite database.

## Data availability finding

The source repository's tracked Git tree contains scripts, documentation and a 2026 NSE equities calendar, but no committed historical OHLCV database or raw candle dataset. The source project's local SQLite database and ignored data files are not available through the Git repository and were not copied.

If historical candles are needed, they must be separately provided/exported or reacquired from the verified data provider. Do not assume the local Orderblock database has been transferred.

## Next safe step

Use this reference package to design a clean index-only ICT data layer. Reuse concepts and validated generic routines only after reviewing each dependency and removing stock/NSE-only assumptions. Keep the source repository frozen.
