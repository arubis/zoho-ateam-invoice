---
name: zoho-ateam-invoice
description: Use when creating Zoho Books invoices from A.Team/BespokeLabs timesheet CSVs and invoice PDFs. Handles OAuth token refresh, invoice creation, marking as sent (without emailing client), and recording payment to Bluevine. Specific to Arboreal Studios / A.Team billing pipeline.
---

# Zoho Books — A.Team Invoice Pipeline

Automates creation of backdated Zoho Books invoices from A.Team bimonthly timesheet exports.

## Context

- **Org:** Arboreal Studios, Inc. (`748222255`)
- **Customer:** BespokeLabs / A.Team (`2647379000002736001`)
- **Bank:** Bluevine (`2647379000000074181`)
- **Rate:** $90/hr
- **Cycle:** Bimonthly — 1st–15th and 16th–EOM
- **Invoice format:** `ATEAM-{statement_number}` (e.g. `ATEAM-79897`)

## Requirements

- Zoho Books OAuth credentials in agenix:
  - `openclaw-zoho-client-id`
  - `openclaw-zoho-client-secret`
  - `openclaw-zoho-refresh-token`
- `ZOHO_ORG_ID=748222255` in `.env` (not secret)
- Python 3 + `requests` library

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

Drop CSVs and PDFs in ~/Downloads, then:

```bash
scripts/zoho-ateam-invoice
```

Script auto-detects the latest unprocessed export pair.
