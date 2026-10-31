# Historical ICT Backtest — NIFTY 50 Stocks

## Purpose and limitations

The backtester replays the same stock scanner and broker-free paper engine used by the live session runner. It advances one completed exchange minute at a time, processes only candles available by that timestamp, and writes a separate paper journal.

Before replay it reconciles the requested 1m, 5m and 15m history from Angel One SmartAPI. If any expected stock/timeframe bars remain missing after the configured repair passes, the run aborts. No synthetic candles are generated.

**Membership warning:** the default NSE download is one current constituent snapshot. Applying that list to older dates creates survivorship/constituent-selection bias. The script refuses this by default when the backtest begins before the snapshot date. The opt-in flag is for exploratory research only, not point-in-time-valid performance claims. For valid historical membership, save official NSE constituent snapshots at every rebalance and split the replay into separate effective-membership periods. A single snapshot must not be applied across an unverified rebalance.

## Prepare the configuration

Use the same local paper configuration as the session runner:

~~~powershell
Copy-Item config\paper_trading.example.json config\paper_trading.json
notepad config\paper_trading.json
~~~

Set starting equity, all-in round-trip fees per share and slippage assumptions. These are required and are not guessed by the program.

## Run

Example exploratory run for October 2026:

~~~powershell
python scripts\backtest_nifty50_ict.py --start 2026-10-01 --end 2026-10-30 --calendar data\calendars\nse_2026_through_2026-11-07.json --paper-config config\paper_trading.json --source-db data\nifty50_stocks.sqlite --output-db data\backtests\october_2026_paper.sqlite --out-of-sample-start 2026-10-20 --allow-current-universe-survivorship-bias
~~~

The survivorship-bias opt-in is deliberate. Do not present that run as a point-in-time NIFTY 50 backtest.

For an in-sample/out-of-sample split, a trade opened before the cutoff and exited on/after it is excluded from both split metric sets and counted separately. This avoids using a post-cutoff outcome in in-sample performance.

The script:
1. Loads a dated constituent snapshot and resolves all 50 instruments through Angel One.
2. Reconciles warm-up plus requested history from Angel One Historical API.
3. Requires all 50 stocks to pass candle readiness at every replay timestamp.
4. Replays one minute at a time using the ICT scanner and paper engine.
5. Expires unfilled intraday signals at each NSE session close.
6. Reports net-of-configured-cost performance, drawdown, expectancy, profit factor, R-multiple, consecutive losses, open positions and the optional in-sample/out-of-sample split.

The output journal database is immutable per run; choose a new --output-db path for every run. The JSON report is written under data/reports unless --report is supplied.

## Interpretation

- A completed backtest is not evidence of profitability. Inspect trade count, sample period, drawdown, out-of-sample results and costs.
- The current paper cost model is a flat per-share round-trip estimate, not a complete statutory Angel One charge calculator.
- Silver Bullet candidates remain alert-only in paper execution.
- Open positions at the end of the replay are reported, not force-closed.
- If historical membership snapshots are unavailable, the backtester must be labelled survivorship-biased.
