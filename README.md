# koddi-healthcheck

CLI tool that validates a Koddi Ads implementation end-to-end by hitting the real Koddi APIs in sequence and producing a clear pass/fail report.

## Install

```bash
pip install -r requirements.txt
```

## Usage

```bash
python koddi_healthcheck.py \
  --email bob@company.com \
  --password "secret" \
  --member-group-id 1234 \
  --advertiser-id 5678 \
  --client-name myretailer \
  --site-id homepage \
  --experience-name "Sponsored Products"
```

### Environment variables

All required flags can be set via environment variables instead:

| Flag | Environment Variable |
|---|---|
| `--email` | `KODDI_EMAIL` |
| `--password` | `KODDI_PASSWORD` |
| `--member-group-id` | `KODDI_MEMBER_GROUP_ID` |
| `--advertiser-id` | `KODDI_ADVERTISER_ID` |
| `--client-name` | `KODDI_CLIENT_NAME` |

CLI flags override environment variables when both are present.

```bash
export KODDI_EMAIL=bob@company.com
export KODDI_PASSWORD=secret
export KODDI_MEMBER_GROUP_ID=1234
export KODDI_ADVERTISER_ID=5678
export KODDI_CLIENT_NAME=myretailer

python koddi_healthcheck.py
```

### JSON output (for CI/CD)

```bash
python koddi_healthcheck.py --json-output \
  --email bob@company.com \
  --password "secret" \
  --member-group-id 1234 \
  --advertiser-id 5678 \
  --client-name myretailer
```

### Custom base URL and timeout

```bash
python koddi_healthcheck.py \
  --base-url https://staging.koddi.io/console/v1 \
  --timeout 60 \
  --email bob@company.com \
  --password "secret" \
  --member-group-id 1234 \
  --advertiser-id 5678 \
  --client-name myretailer
```

## What each check validates

| # | Check | What it does |
|---|---|---|
| 1 | **Authentication** | Logs in via `/session/login` and retrieves an `id_token`. All subsequent authenticated checks depend on this. |
| 2 | **Advertiser Exists** | Fetches the advertiser by ID and confirms it exists. Prints name, status, entity count, and currency. |
| 3 | **Campaigns Report** | Pulls the first page of campaigns for the advertiser. Warns if zero campaigns exist. |
| 4 | **Entity Registration Failures** | Checks for failed entity registrations. Pass = zero failures. Warns and shows details if failures exist. |
| 5 | **Active Bidders Cache** | Verifies the active bidders cache is populated. Empty = no ad groups are active (warning). |
| 6 | **Attributable Entities Cache** | Verifies attributable entities exist. Empty = conversions won't attribute (warning). |
| 7 | **Winning Ads (Test Auction)** | Sends a test auction request to `{clientName}.koddi.io`. Confirms the auction engine is reachable and responds. No auth required. |

## Exit codes

- `0` — All checks passed (warnings are OK)
- `1` — One or more checks failed

## Dependency chain

If a check fails, dependent checks are skipped rather than crashing:

- Check 1 (auth) failure → Checks 2–6 skipped
- Check 2 (advertiser) failure → Checks 3–4 skipped
- Check 7 is independent (no auth required)
