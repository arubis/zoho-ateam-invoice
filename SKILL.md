---
name: zoho-ateam-invoice
description: Use when creating Zoho Books invoices from contractor invoice PDFs and timesheet CSVs. Handles OAuth token refresh, idempotent invoice creation, marking as sent without emailing, and recording payment.
---

# Zoho Books — Contractor Invoice Pipeline

Creates backdated Zoho Books invoices from a contractor platform's bimonthly
timesheet and earnings-statement exports.

## Configuration

Everything account-specific comes from the environment — nothing is hardcoded.
Set these before running:

| Variable | Required | Description |
|----------|----------|-------------|
| `ZOHO_CLIENT_ID` | yes | OAuth client ID (Self Client app) |
| `ZOHO_CLIENT_SECRET` | yes | OAuth client secret |
| `ZOHO_REFRESH_TOKEN` | yes | OAuth refresh token |
| `ZOHO_ORG_ID` | yes | Zoho Books org ID |
| `ZOHO_CUSTOMER_ID` | yes | Customer being invoiced |
| `ZOHO_BANK_ACCOUNT_ID` | yes | Bank account payments are recorded against |
| `ZOHO_INVOICE_PREFIX` | no | Invoice number prefix (default `INV` → `INV-12345`) |
| `ZOHO_RATE` | no | Fallback hourly rate if the PDF omits one (default `90`) |

Lookup order: environment variables → `ZOHO_ENV_FILE` → `~/.env` → `~/.openclaw/.env`.
Files are merged, earliest wins; environment variables always win over files.

This repo is set up for **mise**: local values live in `.mise.local.toml`
(gitignored) under an `[env]` section, so `mise` exports them automatically in
the project directory. See `.env.example` for the variable list.

## Requirements

- Python 3.9+ (standard library only)
- `pdftotext` (`poppler-utils`)

## Inputs

Exports dropped in `~/Downloads/`:

- **Invoice PDF** (required) — platform → Mission → Invoices → Download
- **Timesheet CSV** (optional) — platform → Mission → Time Tracking → Export

## Reconciliation rules

Two different checks, two different outcomes:

- **CSV vs PDF** — if CSV hours × rate ≠ PDF total, warn and use the PDF. The
  invoice is what was actually paid; the timesheet is a working document.
- **PDF vs itself** — if the PDF's own hours × rate ≠ its stated total, **refuse**.
  The invoice raised and the payment recorded would be different numbers, which
  is a bookkeeping error rather than something to guess at. Fix the source or
  enter that invoice by hand.

The same guard catches a PDF with no `TOTAL HOURS` line, which would otherwise
book a $0 invoice with a full payment applied against it.

## Workflow

1. Parse CSV for billing period, hours, total
2. Parse PDF for statement number, date, hours, rate, amount
3. POST `/invoices` with backdated `date` and `ignore_auto_number_generation=true`
4. POST `/invoices/{id}/status/sent` — marks sent WITHOUT emailing the customer
5. POST `/customerpayments` — records payment against the bank account

Idempotent: an existing invoice with the same number is detected and skipped.

## Key API details

- Auth header is `Authorization: Zoho-oauthtoken {access_token}` — not `Bearer`
- Token refresh: `POST accounts.zoho.com/oauth/v2/token` with `grant_type=refresh_token`
- Custom invoice numbers need `&ignore_auto_number_generation=true` on POST `/invoices`
- `POST /invoices/{id}/status/sent` is safe — it marks sent without sending email
- The `invoice_number` filter on GET `/invoices` matches **substrings**, so
  lookups must compare exactly (`INV-812` otherwise matches `INV-81212`)

## OAuth scopes required

```
ZohoBooks.invoices.CREATE,READ,UPDATE
ZohoBooks.contacts.CREATE,READ
ZohoBooks.settings.READ
ZohoBooks.customerpayments.CREATE,READ,UPDATE
ZohoBooks.banking.READ
```

## Usage

```bash
# Whole folder — walks every PDF, pairs timesheet CSVs by billing period
zoho-ateam-invoice ~/Downloads --dry-run
zoho-ateam-invoice ~/Downloads

# One invoice, with an explicit CSV cross-check
zoho-ateam-invoice --csv timesheet.csv invoice.pdf --dry-run
zoho-ateam-invoice --csv timesheet.csv invoice.pdf

# List invoices already in Zoho Books for this customer
zoho-ateam-invoice --list
```

Directory mode:

- PDFs with none of the expected markers (bank statements, tax forms) are
  **ignored** and counted, not treated as failures. Naming such a file
  explicitly is still an error — you said you expected an invoice.
- Timesheet CSVs beside the PDFs are paired by billing period. Timesheet
  filenames carry no year, so if two PDFs claim the same month/day range the
  pairing is ambiguous and the cross-check is skipped for both, with a warning.
- One bad export does not strand the batch; the run continues and reports a
  tally. The pipeline is idempotent, so re-running after a fix is safe.
- Exit status is non-zero if anything was blocked or failed.

**Recommended flow:** always `--dry-run` first, then run for real. Use `--list`
to see what has already been processed — do not track that in this file.
