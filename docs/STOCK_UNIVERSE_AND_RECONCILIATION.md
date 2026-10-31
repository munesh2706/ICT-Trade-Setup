# NIFTY 50 Stock Universe and Historical Reconciliation

## Scope

The scan universe is the 50 individual NSE cash-equity constituents of NIFTY 50. Index spot instruments, index options and non-constituent equities are excluded.

## Source boundaries

- Membership: official NSE Indices NIFTY 50 constituent CSV. Each download is saved as an immutable dated JSON snapshot with SHA-256 provenance.
- Token/exchange identity: Angel One OpenAPI instrument master. Every constituent must resolve to exactly one NSE cash-equity row whose trading symbol is exactly \`SYMBOL-EQ\`. Cash EQ rows can have a blank \`instrumenttype\`; do not require the literal value \`EQ\`.
- Historical/live prices: Angel One SmartAPI only. No other price vendor, fallback price feed, synthetic OHLCV, forward-fill or interpolated candle is allowed.
- Angel One instrument master is refreshed on each run and its checksum is recorded in the run summary.

The official NSE constituent list is metadata only; it is not a source of market prices.

## Pre-session reconciliation

Configure `ICT_HISTORY_START_DATE` once (or pass `--history-start`) to define the earliest history required by the strategy. Run `python scripts/pre_session_gate.py --calendar path/to/nse_calendar.json` before the scanner/dashboard process. If the gate exits non-zero, do not start the scanner. The gate re-audits the entire configured date range each time; only missing bars cause Angel One requests.

\`scripts/reconcile_nifty50_history.py\` performs the pre-market historical repair gate:

1. Load a provenance-backed explicit NSE calendar. Unknown calendar dates fail closed.
2. Download and validate the official 50-member NSE universe snapshot.
3. Authenticate to Angel One using local environment variables / \`.env\`.
4. Download the Angel One instrument master and resolve all 50 NSE EQ tokens exactly.
5. For each stock/timeframe, compare stored verified/acquired timestamps with the expected session grid.
6. Identify every missing expected timestamp, including gaps spanning minutes, hours or multiple trading days.
7. Group adjacent missing bars and split requests to Angel One's documented historical API window limits.
8. Persist original provider responses and exact returned candles in an immutable SQLite acquisition snapshot.
9. Repeat the gap scan for a bounded number of passes.
10. Release the dataset to downstream strategy code only when every required series passes the complete grid audit.

An unresolved API error or missing candle leaves the new snapshot ACQUIRED and the pre-session gate closed. It is not treated as a successful repair. Existing verified history remains intact. The script exits 2 when gaps remain, 1 on a fatal setup/API error, and 0 only when all requested series are complete.

## Calendar contract

A source-backed NSE equity calendar for 2026-01-01 through 2026-11-07 is included at `data/calendars/nse_2026_through_2026-11-07.json`. It includes the official 2026 equity holidays and the special Sunday 01-Feb-2026 budget trading session. It intentionally stops on 07-Nov-2026; the 08-Nov-2026 Muhurat session is not guessed because NSE had not yet notified its session timings as of that cutoff. Extend the calendar only after the relevant official circular is available.

The calendar uses NSE's published regular equity hours (09:15–15:30) and official holiday list. Sources: [NSE Market Timings & Holidays](https://www.nseindia.com/resources/exchange-communication-holidays), [NSE circular FAOP72352 for 01-Feb-2026 special session](https://nsearchives.nseindia.com/content/circulars/FAOP72352.pdf).

For dates beyond the bundled coverage, the calendar JSON must explicitly define:
- exchange = NSE and timezone = Asia/Kolkata;
- coverage_start and coverage_end;
- every regular or special open session with exact open_at, close_at and source;
- every closed date with source provenance;
- a top-level source describing the official calendar/circular set.

Do not assume every weekday is an ordinary session. Do not omit special weekend sessions, shortened sessions or exchange holidays. A date inside coverage with neither a session nor a closed-date entry is invalid. A date outside coverage is invalid.

Example structure (illustrative schema only; not market calendar data):

\`\`\`json
{
  "exchange": "NSE",
  "timezone": "Asia/Kolkata",
  "coverage_start": "YYYY-MM-DD",
  "coverage_end": "YYYY-MM-DD",
  "source": "Official NSE holiday circulars and special-session circulars",
  "sessions": [
    {
      "date": "YYYY-MM-DD",
      "open_at": "YYYY-MM-DDTHH:MM:SS+05:30",
      "close_at": "YYYY-MM-DDTHH:MM:SS+05:30",
      "source": "NSE circular reference"
    }
  ],
  "closed_dates": ["YYYY-MM-DD"]
}
\`\`\`

The example deliberately contains placeholders, not invented dates or sessions.

## Live market data

`AngelOneStockFeed.start_stream()` starts one SmartAPI WebSocket V2 connection and subscribes all 50 NSE cash tokens in Quote mode by default. The callback normalizes Angel One's paise-scaled LTP to rupees, retains exchange timestamps, sequence number and cumulative day volume, and rejects unknown tokens or exchange types. The SDK reconnect policy is bounded. `stop_stream()` closes the connection.

**Stream ticks are not promoted to completed candles.** Sparse or interrupted tick updates cannot prove full minute OHLCV. The live stream is for current quote display and intraday monitoring; completed bars used by ICT detectors must still come from Angel One Historical API and pass the same expected-grid verification. A stream disconnect therefore does not create synthetic candles; the historical reconciliation path repairs missing completed bars.

## Live quote snapshots

`AngelOneStockFeed.fetch_full_quotes()` requests FULL market data for all 50 resolved NSE tokens in one SmartAPI market-data call. It validates token identity, duplicate/missing/unfetched rows, positive LTP and exchange feed timestamp. A quote without an exchange timestamp is treated as stale/unknown, not fresh. The default 90-second age threshold is an engineering setting and should be calibrated with live-session observations. A FULL quote is a point-in-time snapshot, not a replacement for candle history. The WebSocket V2 adapter is the continuous live display/monitoring path.

Angel One documents a maximum of 50 symbols in one market-data request, a one-request-per-second limit, and FULL quote fields including LTP and exchange feed time. See [SmartAPI documentation](https://smartapi.angelone.in/docs).

## Historical request constraints

The adapter uses Angel One's documented maximum request windows:
- 1m: 30 days
- 3m: 60 days
- 5m / 10m: 100 days
- 15m / 30m: 200 days
- 1h: 400 days
- 1d: 2000 days

Request pacing defaults to one request per second and refuses a rate faster than three requests per second. Each response is filtered to the exact expected timestamps. Extra rows are not inserted as expected bars. The raw response is retained for diagnosis.

## Important implementation limits

- A complete calendar file is a hard prerequisite; the code does not fabricate a weekday calendar.
- The NSE CSV represents current membership at capture time. It is not a historical point-in-time constituent archive. Backtests over past dates require archived official constituent snapshots and effective-date evidence.
- Angel One may not return all requested bars. The system retries a bounded number of times and then blocks the gate if any expected timestamp remains absent.
- This module is the first delivery layer. ICT scanning, paper trading, and dashboard integration follow only after the data gate is proven on authenticated local Angel One data.


## NSE Closing Auction Session (CAS) and candle-grid boundaries

NSE CAS Phase 1 applies to cash-market securities on which derivative contracts are available. For CAS-eligible stocks, continuous trading transitions to the separate CAS at **15:15 IST**; CAS runs from **15:15 to 15:35 IST**. Non-CAS cash securities retain continuous trading until 15:30 IST. See the [NSE CAS specification](https://www.nseindia.com/static/products-services/closing-auction-session), NSE circulars **NSE/CMTR/72394** and **NSE/CMTR/74466**, and SEBI circular **HO/47/11/11(3)2025-MRD-POD2/I/2765/2026**. SEBI circular HO/47/11/11(3)2025-MRD-POD2/I/2765/2026 specifies implementation from 03-Aug-2026; the NSE CAS page confirms the applicable session timings.

The exchange calendar therefore keeps the normal \`close_at\` and a separately sourced \`continuous_close_at\`. For each symbol, the Angel One instrument master is checked for an NFO \`FUTSTK\` row; only those symbols use the CAS continuous cutoff. This is not inferred from the NSE EQ cash row. The current NIFTY 50 snapshot was checked against the authenticated master and all 50 members had NFO stock-futures entries.

For a normal 09:15 session with a 15:15 continuous close, the expected completed-candle grid is:

- 1-minute: 360 bars (09:15 through 15:14)
- 5-minute: 72 bars (09:15 through 15:10)
- 15-minute: 24 bars (09:15 through 15:00)

The auction-period values returned by a provider are not appended to the continuous-trading ICT candle series. For example, a 1-minute timestamp around 15:28, a 5-minute timestamp around 15:25, or a 15-minute timestamp at 15:15 is outside the continuous-session grid. Those records must not be counted as missing continuous candles or used for ICT detection, paper entries, or exits.

The eligibility set is resolved from the current instrument-master snapshot and passed through historical reconciliation, live refresh, scanning, paper execution, and replay. If a security is not CAS-eligible, its expected grid continues to use the normal 15:30 close. The calendar coverage ends 07-Nov-2026; later exchange schedule changes require an explicit calendar update rather than extrapolation.
