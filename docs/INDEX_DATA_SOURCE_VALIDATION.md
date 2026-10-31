# Index Market-Data Source Validation

**Review date:** 2026-10-30  
**Status:** API capability and instrument identifiers documented; a local read-only validation harness is implemented; authenticated end-to-end validation is still pending.

## 1. Scope

This validation covers only the three approved spot indices:

- NIFTY 50 — NSE
- BANKNIFTY — NSE
- SENSEX — BSE

No constituent stocks, futures, options, or order placement are in scope.

## 2. Findings from Angel One SmartAPI documentation

Angel One's SmartAPI documentation describes:

- Historical candle endpoint: `/rest/secure/angelbroking/historical/v1/getCandleData`
- Historical exchange values include `NSE` and `BSE`, and the documentation explicitly describes historical data for indices.
- Supported candle intervals include 1m, 3m, 5m, 10m, 15m, 30m, 1h and 1d.
- Live Market Data API supports exchange-token quote requests.
- SmartAPI WebSocket V2 supports NSE cash and BSE cash exchange types (exchangeType 1 and 3).

Official documentation:
- https://smartapi.angelone.in/docs
- https://smartapi.angelone.in/docs/Historical
- https://smartapi.angelone.in/docs/ResponseStructure

Angel One administrator's published index-token notice identifies these current index token values:

| Instrument | Exchange | Token | Evidence |
|---|---|---:|---|
| NIFTY 50 | NSE | `99926000` | Angel One administrator's index-token notice |
| BANKNIFTY | NSE | `99926009` | Angel One administrator's index-token notice |
| SENSEX | BSE | `99919000` | Angel One administrator's index-token notice |

Evidence: https://smartapi.angelone.in/smartapi/forum/user/admin (administrator post: “SmartAPI now provides real-time market data for 120 indices across NSE, BSE, and MCX”, including the NSE and BSE index tables).

These are documented identifiers, **not a substitute for runtime verification**. The instrument master is refreshed daily and must be checked at startup or on a scheduled refresh. Do not silently fall back to old tokens 26000, 26009 or 19000.

## 3. Capability assessment

| Capability | NIFTY 50 | BANKNIFTY | SENSEX | Assessment |
|---|---|---|---|---|
| Instrument identifier documented | Yes | Yes | Yes | Documented |
| Historical candle API exchange documented | NSE | NSE | BSE | Documented |
| Live quote API exchange documented | NSE | NSE | BSE | API supports all exchanges |
| WebSocket exchange type | 1 (NSE cash) | 1 (NSE cash) | 3 (BSE cash) | Exchange types documented |
| Actual authenticated historical request | Not yet run | Not yet run | Not yet run | Pending |
| Actual authenticated live quote response | Not yet run | Not yet run | Not yet run | Pending |
| Actual WebSocket subscription and ticks | Not yet run | Not yet run | Not yet run | Pending |
| OHLC parity / continuity audit | Not yet run | Not yet run | Not yet run | Pending |

**Conclusion:** Angel One documents a supported route for all three indices. It is reasonable to proceed with a small authenticated validation harness, but it is not yet accurate to call any of the three feeds operationally validated.

## 4. Important correction to the migrated reference code

The migrated collector is not directly reusable as-is. It assumes NSE cash instruments and a 50-stock mapping. Its exchange validation, token map, calendar, and session assumptions must be replaced with an index-aware design.

The ICT data layer must:

1. Resolve each index from the current Angel One instrument master, using exact exchange and index instrument type/name/token fields. Reject missing or ambiguous matches.
2. Treat NIFTY and BANKNIFTY as NSE index instruments, and SENSEX as a BSE index instrument.
3. Use `exchange=NSE` for NIFTY/BANKNIFTY historical candles and `exchange=BSE` for SENSEX historical candles.
4. Use WebSocket exchangeType 1 for NSE cash and 3 for BSE cash, with the current verified tokens.
5. Keep independent NSE and BSE session calendars. Do not reuse the migrated NSE-equities calendar as the SENSEX calendar.
6. Store source, exchange, token, interval, exchange timestamp, receipt timestamp and validation status with every candle.
7. Preserve missing candles as gaps. Never manufacture candles to make a timeframe complete.
8. Keep historical API candles authoritative for backfill and recovery. Do not promote sampled QUOTE packets into verified OHLCV candles.
9. Make no broker order API calls. This project is analysis and paper trading only.

## 5. Required authenticated validation

Run these tests from the user's local environment with their own Angel One SmartAPI credentials. Credentials must remain in local environment variables or an ignored `.env`; never paste them into chat or commit them.

### A. Instrument-master test
- Download the current official scrip master.
- Find each of the three instruments by exact token, exchange and index instrument type.
- Record the master file retrieval time and a hash.
- Fail closed if the master no longer contains the documented mapping or returns ambiguous rows.

### B. Historical candle test
For each index, request a completed recent session for 1m and 5m, then 15m:
- API response status is successful and returned data is non-empty.
- Timestamps are timezone-aware and session-aligned.
- OHLC values are valid; volume is nonnegative (index volume may be zero and must not be treated as a rejection by itself).
- No duplicate timestamps, unexpected future candles, or out-of-session rows.
- 5m and 15m provider candles are compared against aggregation from complete 1m candles. Differences must be reported, not silently overwritten.
- Verify 1m/5m/15m history depth and API request limits empirically for each index.

### C. Live quote test
- Request LTP/OHLC quote for all three indices using their exchange/token pairs.
- Require a successful response, correct exchange, exact token, plausible nonzero LTP, and fresh exchange-feed timestamp.
- Verify that SENSEX is returned from BSE, not NSE.

### D. WebSocket test
- Subscribe to NIFTY and BANKNIFTY using NSE cash exchangeType 1.
- Subscribe to SENSEX using BSE cash exchangeType 3.
- Confirm subscription acknowledgements and fresh packets during market hours.
- Validate packet token and exchange type against the requested instrument.
- Record disconnects, stale ticks, sequence regressions and timestamp regressions.
- Do not build verified OHLCV from sampled QUOTE packets unless a separately justified and validated trade-tick feed is available.

### E. Session/calendar test
- Verify current NSE and BSE normal trading hours, holidays, special sessions and any recent circular changes from official exchange notices.
- Do not assume that NSE and BSE calendars are interchangeable.
- Ensure aggregation buckets anchor to each exchange's verified session open.

## 6. Acceptance criteria

A data source is marked **VALIDATED** for an index only after all applicable authenticated tests A–E pass, with raw sanitized evidence and reproducible test output saved. If historical passes but WebSocket fails, mark historical and live separately. A successful quote endpoint does not establish candle history or continuous streaming.

No ICT strategy implementation should depend on a data source marked pending or failed.

## 7. Validation harness status

A local read-only harness is implemented at `scripts/validate_angel_index_data.py`; setup and execution instructions are in `docs/RUN_INDEX_DATA_VALIDATION.md`. It checks the current instrument master, performs authenticated historical requests for 1m/5m/15m for each index, compares provider OHLC with 1m-derived bars, requests FULL live quotes, and optionally performs a short WebSocket smoke test. It writes a sanitized JSON report under `data/reports/`.

The harness spaces historical requests by 0.4 seconds (below the documented 3 requests/second ceiling). Angel One's published rate-limit table lists 3 historical candle requests/second, but recent forum reports describe intermittent historical-endpoint rate-limit rejections even at low request volumes; treat a 403 as a provider-side failure to investigate, not proof that credentials or instrument tokens are wrong.

The harness has **not** been run with the user's authenticated local credentials. Therefore the actual feed remains unvalidated until its report is reviewed.

## 8. Current decision

**Run the local validation harness and review its report. Do not yet build the production collector or ICT signal engine on the assumption that the copied stock collector works unchanged.**
