# Run index validation with GitHub Actions

The repository includes a manually triggered workflow:

`.github/workflows/angel-index-validation.yml`

## Configure repository secrets

In GitHub, open **Settings → Secrets and variables → Actions → New repository secret** and add these four secrets exactly:

- `ANGEL_API_KEY`
- `ANGEL_CLIENT_CODE`
- `ANGEL_PIN`
- `ANGEL_TOTP_SECRET`

Use the TOTP base32 secret from the authenticator setup, not the current six-digit OTP. Never put credentials in workflow YAML, repository files, issues, or logs.

## Run the workflow

1. Open the repository's **Actions** tab.
2. Select **Angel One Index Data Validation**.
3. Select **Run workflow**.
4. For `session_date`, enter a completed NSE/BSE trading date in `YYYY-MM-DD` format. A known trading day is preferable to relying on the previous-weekday default.
5. Leave `websocket_probe` disabled for historical + quote validation. Enable it only when NSE/BSE markets are open and you want the short live-feed probe.
6. Open the run and inspect the job result. Download the `angel-index-validation-report` artifact for the sanitized JSON report.

## Scope and limitations

- This workflow runs the existing read-only validation script. It does not place, modify, or cancel orders.
- It tests instrument-master matching, SmartAPI authentication, historical candles, live quotes, and optionally a short WebSocket probe.
- The script exits non-zero when any individual check is FAIL. WARN results are non-fatal, so inspect the report and warnings even when the workflow is green. A green run is a validation result for that run, not production approval.
- GitHub-hosted runners use cloud IP addresses. If Angel One API access is restricted by IP/device policy, authentication or market-data requests may fail even when the secrets are correct.
- WebSocket packet absence outside market hours is inconclusive.
- GitHub Actions secrets are not accessible to pull-request workflows from forks; this workflow is manual-dispatch only.
