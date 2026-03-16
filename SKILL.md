---
name: zoho-ateam-invoice
description: Use when creating Zoho Books invoices from contractor invoice PDFs and timesheet CSVs. Handles OAuth token refresh, idempotent invoice creation, marking as sent without emailing, and recording payment.
---

# Zoho Books — A.Team Invoice Pipeline

Automates creation of backdated Zoho Books invoices from A.Team bimonthly timesheet exports.

## Context

- **Org:** Arboreal Studios, Inc. (`748222255`)
- **Customer:** Contractor (`2647379000002736001`)
- **Bank:** Bluevine (`2647379000000074181`)
- **Rate:** $90/hr
- **Cycle:** Bimonthly — 1st–15th and 16th–EOM
- **Invoice format:** `ATEAM-{statement_number}` (e.g. `ATEAM-79897`)

## Requirements

- Zoho Books OAuth credentials — set as environment variables or in a `.env` file:
  - `ZOHO_CLIENT_ID`, `ZOHO_CLIENT_SECRET`, `ZOHO_REFRESH_TOKEN`, `ZOHO_ORG_ID`
  - OpenClaw users: store in agenix as `openclaw-zoho-client-id` etc., synced to `~/.openclaw/.env`
- Python 3
- `pdftotext` (`poppler-utils`)

## Inputs

Dylan drops exports in `~/Downloads/`:
- **Timesheet CSV** — from A.Team platform → Mission → Time Tracking → Export
- **Invoice PDF** — from A.Team platform → Mission → Invoices → Download

## Data Discrepancy Rule

If timesheet CSV hours × $90 ≠ invoice PDF amount: **use invoice PDF amount**. The invoice = what was actually paid.

## Workflow

1. Parse CSV for billing period (date range), hours, total
2. Parse PDF invoice for statement number, amount (override CSV if different)
3. POST to Zoho Books `/invoices` with backdated `date` and `ignore_auto_number_generation=true`
4. POST `/invoices/{id}/status/sent` — marks sent WITHOUT emailing the customer
5. POST `/customerpayments` — records payment against Bluevine account

## Key API Details

- Auth header: `Authorization: Zoho-oauthtoken {access_token}` (NOT `Bearer`)
- Token refresh: `POST accounts.zoho.com/oauth/v2/token` with `grant_type=refresh_token`
- Custom invoice numbers: append `&ignore_auto_number_generation=true` to POST /invoices
- Mark sent (safe, no email): `POST /invoices/{id}/status/sent`
- Payment: `POST /customerpayments` with `account_id` = Bluevine bank account ID

## Agenix Scopes Required

`ZohoBooks.invoices.CREATE,READ,UPDATE` + `contacts.CREATE,READ` + `settings.READ` + `customerpayments.CREATE,READ,UPDATE` + `banking.READ`

## Invoices Created (reference)

| Number | Period | Hours | Total | Status |
|--------|--------|-------|-------|--------|
| ATEAM-79897 | Nov 1-15 2025 | 8h | $720 | paid |
| ATEAM-80962 | Nov 16-30 2025 | 76h | $6,840 | paid |
| ATEAM-81212 | Dec 1-15 2025 | 88h | $7,920 | paid |
| ATEAM-81706 | Dec 16-31 2025 | 70h | $6,300 | paid |
| ATEAM-82231 | Jan 1-15 2026 | 82h | $7,380 | paid |

Later periods (Jan 16+, Feb, Mar 2026) still to be processed.

## Usage

```bash
# PDF only (CSV not required — skips discrepancy check)
zoho-ateam-invoice invoice.pdf

# PDF + CSV (enables hours/total cross-check, warns on mismatch)
zoho-ateam-invoice --csv timesheet.csv invoice.pdf

# Dry run — parse and show what would happen, no API calls
zoho-ateam-invoice invoice.pdf --dry-run
zoho-ateam-invoice --csv timesheet.csv invoice.pdf --dry-run

# List existing ATEAM-* invoices in Zoho Books
zoho-ateam-invoice --list
```

**Recommended flow:** always `--dry-run` first, then run for real.
