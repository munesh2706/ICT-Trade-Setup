# Index Market Data Layer — Source and Operating Contract

## Scope and instruments

Only these spot index series are enabled:

| Instrument ID | Exchange | SmartAPI token | Segment type | WebSocket exchange type |
|---|---|---:|---|---:|
| NIFTY | NSE | 99926000 | AMXIDX | 1 |
| BANKNIFTY | NSE | 99926009 | AMXIDX | 1 |
| SENSEX | BSE | 99919000 | AMXIDX | 3 |

Every connection verifies the current Angel One instrument master by token, exchange segment and AMXIDX instrument type before using the mapping. The registry is not a substitute for instrument-master verification.

Price series are spot indices. Futures data is a separate instrument/series and cannot be substituted without a separate approved configuration and dataset identity.

## Angel One historical API contract

Official documentation: https://smartapi.angelone.in/docs/Historical

- Historical candle API supports NSE and BSE indices through the exchange field.
- Response rows are timestamp, open, high, low, close, volume.
- Supported intervals include 1m, 3m, 5m, 10m, 15m, 30m, 1h and 1d.
- Published maximum calendar days per request: 1m 30; 3m 60; 5m/10m 100; 15m/30m 200; 1h 400; 1d 2000.
- Published historical candle request rate: 3 requests per second. The adapter defaults to one request per second and refuses a configured pace faster than the documented ceiling.
- Long date ranges are split into non-overlapping windows at the interval-specific limit. No automatic retry is performed after a broker error.

These limits are provider API constraints, not guarantees that every requested candle exists or that the response is complete.

## Candle normalization

- All prices and volume are Decimal values; timestamps are timezone-aware.
- Naive provider timestamps are interpreted as Asia/Kolkata because the API response is an Indian exchange timestamp. This is an adapter assumption that must be revisited if the provider changes timestamp format.
- Malformed OHLCV, non-finite values, non-positive prices, duplicate timestamps, out-of-order rows and rows outside the requested time range are rejected.
- Provider order is preserved; the adapter never silently sorts a malformed response.
- A request's `fromdate` and `todate` are minute precision; callers must supply minute-aligned boundaries.
- API end-boundary semantics must be confirmed by integration evidence. The current adapter treats the requested end as exclusive and rejects a returned candle at or after it.

## Immutable dataset snapshots

`CandleStore` stores each dataset under an explicit `snapshot_id`. The same timestamp can exist in multiple snapshots if a provider later revises historical data. A conflicting row inside the same snapshot is rejected, not overwritten. Snapshots move through OPEN → ACQUIRED → VERIFIED, or to FAILED. Backtest reads are blocked until VERIFIED. Verification requires an explicit exchange calendar and a complete expected candle grid. Backtests must identify the snapshot they used.

## Exchange calendar

`ExchangeCalendar` requires explicit open sessions, closed dates, coverage bounds, timezone and source provenance. It does not infer that weekdays are trading days or that unlisted dates are holidays. Special/shortened sessions must be explicit. Incomplete final intervals are not fabricated.

Production use requires separately curated official NSE and BSE calendars for every historical period under study. The copied NSE equities calendar in the reference folder is not the production index calendar.

## Current implementation

- `ict_engine/instruments.py`: strict index-only instrument registry.
- `ict_engine/angelone_feed.py`: read-only Angel One historical adapter; no order/position endpoints.
- `ict_engine/storage.py`: immutable SQLite snapshots with acquisition and verification states.
- `ict_engine/data_audit.py`: exchange-calendar expected-grid audit; promotes a snapshot to VERIFIED only when all required series pass.
- `ict_engine/market_calendar.py`: explicit session calendar and expected candle grid.

## Remaining data-layer work

- Build and verify official multi-year NSE and BSE index calendars, including special sessions and any effective-date changes.
- Confirm timestamp/end-boundary semantics and interval-specific response completeness against actual local authenticated requests.
- Add restart-safe incremental sync, feed-health monitoring and historical gap recovery without synthetic bars.
- Add live feed integration only after confirming the correct index streaming mode and reconciling it against broker historical candles.