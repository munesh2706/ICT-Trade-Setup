# Running the Angel One index-data validation harness

This utility is read-only. It does not call any order placement, modification, cancellation, holdings, positions, or trade APIs.

## 1. Requirements

Python 3.10+ (3.12 recommended). From the repository root in PowerShell:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
Copy-Item .env.example .env
notepad .env
```

Fill the four local values in `.env`: API key, client code, trading PIN/MPIN, and the TOTP **secret** (base32 secret used by your authenticator, not the six-digit rolling OTP). Do not paste credentials into chat or commit the file. The repository ignores `.env`.

## 2. Run

Use a known completed NSE/BSE trading day. The default is the previous weekday, which may be an exchange holiday; specify the date when necessary.

```powershell
python scripts\validate_angel_index_data.py --date 2026-10-30
```

During live market hours, the default run also performs a 15-second WebSocket probe. To test only instrument master, login, history and quote:

```powershell
python scripts\validate_angel_index_data.py --date 2026-10-30 --skip-websocket
```

To extend the WebSocket probe:

```powershell
python scripts\validate_angel_index_data.py --date 2026-10-30 --ws-seconds 45
```

## 3. Output

A sanitized JSON report is written under `data/reports/` (ignored by Git). Share that JSON report or its console output for review. It does not contain API key, PIN, TOTP secret, JWT, refresh token or feed token.

## 4. Interpretation and limitations

- The script fails closed if the current instrument master does not contain exactly one row matching each documented token, cash segment and `AMXIDX` type. It does not silently fall back to hard-coded identifiers.
- Historical requests are one completed session per instrument and interval (1m, 5m, 15m). A weekend/holiday date will likely return no candles. A previous weekday is not proof of a trading day.
- 1m-to-5m/15m OHLC comparisons are diagnostic. Mismatches are reported; no data is overwritten.
- Bar-count shortfall is a gap candidate, not conclusive missing data until exchange holidays, special sessions and trading halts are accounted for.
- Index volume may be zero. Negative volume is invalid; zero is not automatically rejected.
- The quote endpoint and WebSocket may return no fresh ticks outside market hours. A successful quote response does not prove a continuous feed.
- The WebSocket probe is a short smoke test, not a long-duration reliability test or a tick-to-candle certification.
- NSE and BSE holiday/session calendars still need independent official verification before production ingestion.
- SmartAPI SDK changes can affect the harness. If authentication or API calls fail, share the sanitized report and error text, never credentials.

## 5. Security

Do not enable shell transcript logging while entering secrets. Do not screenshot or share `.env`. If credentials were accidentally committed, rotate/revoke them in Angel One and remove the leaked commit from repository history.
