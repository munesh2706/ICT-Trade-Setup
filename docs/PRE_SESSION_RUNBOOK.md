# Pre-session Data Gate Runbook (Windows PowerShell)

## One-time prerequisites

1. Install project dependencies in the repository virtual environment.
2. Configure the four Angel One SmartAPI values in the local .env file. Never paste them into chat or commit them.
3. Review the NSE calendar coverage. The bundled calendar currently ends on 2026-10-31. Add later sessions only from official NSE holiday/timing circulars before running on a later date.
4. Choose the earliest historical date required by the ICT models. The selected date must be within the calendar coverage and within the historical data Angel One actually returns.

## Before each trading session

Run from the repository root:

~~~powershell
$env:ICT_HISTORY_START_DATE = "2026-01-01"
python scripts\pre_session_gate.py --calendar data\calendars\nse_2026_through_2026-10-31.json --timeframes 1m 5m 15m 1h
~~~

The first run may require many Angel One historical requests. Later runs compare the full configured date range to the local database and request only missing ranges.

The script:
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
python scripts\pre_session_gate.py --calendar data\calendars\nse_2026_through_2026-10-31.json --history-start 2026-01-01 --timeframes 1d --daily-anchor session_open
~~~

Use local_midnight instead only if verified against the provider's actual daily response timestamps. The software intentionally refuses to guess.
