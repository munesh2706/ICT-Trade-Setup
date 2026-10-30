# Phase 2 — Angel One SmartAPI market-data foundation

Status: DESIGN LOCKED; implementation and live validation pending.

## Scope
Data acquisition only. No OB algorithm modifications, no order placement, no paper trade rule changes, no selection scoring yet.

## Source and universe
- Angel One SmartAPI, NSE cash market.
- Resolve NIFTY 50 constituent list from a maintained authoritative dated snapshot, then map exact NSE symbols to current Angel instrument master and validate exchange/token.
- Maintain NIFTY 50 benchmark and available sector benchmark series separately.
- Persist instrument master provenance, timestamp and mappings; reject missing/ambiguous symbols. Do not assume instrument tokens remain stable.

## Credentials and isolation
- Python 3.12 within project-local .venv; secrets only in .env, never Git.
- Configuration validation before authentication; no secrets in logs or exceptions.
- Explicit connection diagnostics; do not perform trades or order calls.

## Candle pipeline
- Collect historical and live 1m and 5m OHLCV per instrument, IST timestamps and explicit session date.
- Use exchange-session-aligned intervals; candles become final only on interval close, with a configurable data-arrival grace window. Never synthesize missing market candles as real trades.
- Build 15m from exactly three complete contiguous session-aligned 5m candles, matching SETUP_SPEC.md. Incomplete buckets are discarded.
- Preserve raw input and canonical candles separately, with provenance and deterministic deduplication.
- Detect gaps, duplicates, stale ticks, invalid OHLC, nonmonotonic timestamps, and connection interruptions; log integrity events and recovery.
- Restore history and reconcile completed candles after reconnect; avoid silent gaps or look-ahead.
- Store SQLite timestamps in UTC with IST rendering; maintain source exchange timestamps and raw payload provenance.
- 20 prior complete trading sessions of same-time cumulative volume required for selector RVOL; ensure 60m intraday history for selector; OB engine warm-up determined only by original spec.

## Runtime
- One collector service independent of browser dashboard; no reliance on dashboard being open.
- Bounded retries/backoff, explicit rate-limit handling, graceful shutdown, structured health diagnostics.
- Read-only first: no order placement, no paper-trade activation.
- Tests must use deterministic fixtures; no authenticated network calls in unit tests.

## Acceptance tests
1. NSE constituent mapping and token lookup reject missing/ambiguous symbols.
2. 1m and 5m historical candles have correct session alignment and no future data.
3. 15m aggregation uses three complete contiguous 5m bars only.
4. Duplicate/out-of-order/gapped data handled deterministically and recorded.
5. Stale or disconnected feed is visible in health status.
6. Restart/reconnect resumes without duplicate final candles or missing history.
7. Historical and live candle reconciliation exposes discrepancies rather than overwriting silently.
8. Credentials never appear in Git or logs.
9. No order endpoints invoked.
10. Original docs/SETUP_SPEC.md byte-for-byte unchanged.

## Unresolved before live integration
- Inspect original spec and verify session schedule against current NSE trading hours, without modifying it.
- Confirm SmartAPI SDK and documented API response shapes against installed version.
- Confirm NSE constituent snapshot and sector mapping provenance.
- Resolve stock-specific BOS minimums and tick-size compatibility separately, prior to OB integration; not a Phase 2 data-layer change.
