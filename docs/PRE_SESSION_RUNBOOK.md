# Pre-session Data Gate Runbook (Windows PowerShell)

## One-time prerequisites

1. Install project dependencies in the repository virtual environment.
2. Configure the four Angel One SmartAPI values in the local .env file. Never paste them into chat or commit them.
3. Review the NSE calendar coverage. The bundled calendar currently ends on 2026-11-07. Add later sessions only from official NSE holiday/timing circulars before running on a later date.
4. Choose the earliest historical date required by the ICT models. The selected date must be within the calendar coverage and within the historical data Angel One actually returns.

## Paper-trading configuration

Create a local configuration file and fill in the required values before starting the session runner:

~~~powershell
Copy-Item config\paper_trading.example.json config\paper_trading.json
notepad config\paper_trading.json
~~~

Set starting equity, estimated all-in round-trip fees per share, and slippage per share from your actual Angel One costs and chosen execution assumptions. The engine uses a flat per-share cost input; it is not a live broker charge calculator. Risk fractions, stop reference, entry variant and target selection are explicit engineering settings in this file. Do not treat the defaults as validated profitability parameters.

## Before each trading session

Run the single-process session runner from the repository root:

~~~powershell
$env:ICT_HISTORY_START_DATE = "2026-01-01"
python scripts\run_nifty50_session.py --calendar data\calendars\nse_2026_through_2026-11-07.json --paper-config config\paper_trading.json
~~~

The runner authenticates once, downloads the current NSE constituent list and Angel One instrument master, performs full historical reconciliation, then starts the WebSocket quote stream and current-session candle refresh. It waits for market open when started pre-market, polls completed 1m candles every minute, 5m candles at 5-minute boundaries and 15m candles at 15-minute boundaries, runs the scanner, and writes JSON reports to data/reports. Each scan cycle also requests an Angel One FULL quote snapshot as fallback for missing/stale WebSocket quotes. Quote freshness is measured from the exchange timestamp; unresolved stale/missing quotes remain explicitly marked stale. The scanner and paper engine use completed verified historical candles, never stale LTPs. The first bootstrap may take several minutes because Angel One historical request limits apply. Later sessions request only gaps.

The runner:
- refreshes the official NSE NIFTY 50 constituent list;
- resolves all 50 symbols against the current Angel One instrument master;
- checks the complete expected candle grid for every configured stock/timeframe;
- downloads missing ranges from Angel One, including multi-day gaps;
- preserves raw provider responses and canonical candles in SQLite;
- exits 0 only when every requested series is complete.

Exit codes:
- 0: data gate passed; scanner startup may proceed.
- 1: fatal setup, calendar, authentication or acquisition failure.
- 2: one or more expected candles remain unavailable after bounded retries.

Do not start the scanner/dashboard when the exit code is non-zero. Do not modify the database to manufacture missing candles.

## Daily candles

If 1d is added to --timeframes, explicitly provide the provider timestamp convention only after confirming it from actual Angel One responses:

~~~powershell
python scripts\pre_session_gate.py --calendar data\calendars\nse_2026_through_2026-11-07.json --history-start 2026-01-01 --timeframes 1d --daily-anchor session_open
~~~

Use local_midnight instead only if verified against the provider's actual daily response timestamps. The software intentionally refuses to guess.


## Manual diagnostics

The individual `refresh_nifty50_live_session.py` and `scan_nifty50_stocks.py` commands are available for one-shot diagnostics. The normal live workflow is the long-running `run_nifty50_session.py` process above; do not launch a new Python process and re-authenticate for every minute.

A stock is eligible for scanning only when its completed current-session 1m, 5m and 15m grids are present in verified storage. The WebSocket V2 feed and FULL quote fallback are for live quote display/monitoring; neither is used to synthesize OHLCV. The scanner returns per-stock readiness and explainable ICT candidates. The local visual dashboard is available through dashboard/app.py; start it in a second terminal with the command below.


## Visual dashboard

Start the dashboard in a second PowerShell window after installing the updated requirements:

~~~powershell
python -m uvicorn dashboard.app:app --host 127.0.0.1 --port 8000
~~~

Open http://127.0.0.1:8000 in the browser. Keep it bound to 127.0.0.1; the dashboard has no remote-user authentication and is intended for local use only. It reads the latest session report and verified candle/paper-trade SQLite database. It does not connect to a second market-data vendor or place broker orders.


## CAS-aware session readiness

For cash equities with stock-futures contracts, NSE continuous trading ends at 15:15 IST and the separate Closing Auction Session follows until 15:35 IST. The scanner and paper engine must use only continuous-session candles. The 15:15 CAS boundary is distinct from the regular 15:30 close used for non-CAS securities.

Before a reconciliation run, verify that the Angel One instrument master has the expected NFO \`FUTSTK\` mappings. The system derives CAS eligibility from those rows; it does not infer it from NSE EQ symbols. The calendar's \`continuous_close_at\` is effective from 03-Aug-2026, based on SEBI circular HO/47/11/11(3)2025-MRD-POD2/I/2765/2026 and NSE circulars NSE/CMTR/72394 and NSE/CMTR/74466. See [NSE CAS](https://www.nseindia.com/static/products-services/closing-auction-session).

For a regular CAS-eligible session, expected completed bars are 360 × 1m, 72 × 5m and 24 × 15m. Auction-period timestamps must be excluded from ICT scanning and paper execution. A 15:30-based gap report for a CAS-eligible stock is a calendar-boundary error, not evidence of missing continuous-session data.
