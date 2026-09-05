# zoho-ateam-invoice

[![CI](https://github.com/arubis/zoho-ateam-invoice/actions/workflows/ci.yml/badge.svg)](https://github.com/arubis/zoho-ateam-invoice/actions/workflows/ci.yml)

An AI agent skill that automates creating [Zoho Books](https://www.zoho.com/books/) invoices from contractor timesheet exports. Works with any agent framework (Claude Code, Codex, OpenClaw, Cursor, or plain CLI). Includes a `SKILL.md` for [OpenClaw](https://openclaw.ai) auto-discovery.

Built for a contractor billing pipeline at Arboreal Studios — but the approach (OAuth token refresh, idempotent invoice creation, marking sent without emailing, recording payment) is generic enough to adapt.

## What it does

1. Parses an invoice PDF (statement number, date, hours, total)
2. Optionally cross-checks against a timesheet CSV — warns if totals disagree, uses PDF amount
3. Refuses outright if the PDF disagrees with *itself* (hours × rate ≠ stated total), rather than raising an invoice for one amount and recording payment for another
4. Creates a backdated invoice in Zoho Books with a custom invoice number
5. Marks it as sent (without emailing the customer)
6. Records payment against a bank account

**Idempotent** — checks for an existing invoice by number before creating. Safe to re-run.

## Requirements

- Python 3.9+ (standard library only — no runtime dependencies)
- `pdftotext` (from `poppler-utils`)
- Zoho Books OAuth credentials (client ID, client secret, refresh token)

## Setup

Clone, install dev dependencies, and make the script executable:

```bash
git clone https://github.com/arubis/zoho-ateam-invoice
cd zoho-ateam-invoice
chmod +x scripts/zoho-ateam-invoice
uv sync   # installs pytest and dev deps into .venv
```

Requires [uv](https://docs.astral.sh/uv/) and [mise](https://mise.jdx.dev/) (optional, for Python version pinning).
Also requires `pdftotext` from `poppler-utils`:

```bash
# macOS
brew install poppler

# Debian/Ubuntu
sudo apt-get install poppler-utils
```

Add your Zoho credentials — the script checks these in order:

1. **Environment variables** (any framework, CI/CD, direnv, etc.)
2. **`ZOHO_ENV_FILE`** env var pointing to a custom `.env` path
3. **`~/.env`**
4. **`~/.openclaw/.env`** (OpenClaw default)

```bash
export ZOHO_CLIENT_ID=...
export ZOHO_CLIENT_SECRET=...
export ZOHO_REFRESH_TOKEN=...
export ZOHO_ORG_ID=...
```

Or in a `.env` file in any of the above locations:

```
ZOHO_CLIENT_ID=...
ZOHO_CLIENT_SECRET=...
ZOHO_REFRESH_TOKEN=...
ZOHO_ORG_ID=...
```

Using mise? Put the non-secret account values in a gitignored `.mise.local.toml`
and they're exported automatically inside the project directory:

```toml
[env]
ZOHO_ORG_ID = "..."
ZOHO_CUSTOMER_ID = "..."
ZOHO_BANK_ACCOUNT_ID = "..."
ZOHO_INVOICE_PREFIX = "ACME"
ZOHO_RATE = "90"
```

Keep the OAuth secrets out of that file — leave them in your secret store or
`~/.env`. Env files are merged in the order above, earliest wins, and real
environment variables beat all of them.

Get OAuth credentials via the [Zoho API Console](https://api-console.zoho.com/) (Self Client app). Required scopes:

```
ZohoBooks.invoices.CREATE,READ,UPDATE
ZohoBooks.contacts.CREATE,READ
ZohoBooks.settings.READ
ZohoBooks.customerpayments.CREATE,READ,UPDATE
ZohoBooks.banking.READ
```

Nothing is hardcoded — the customer ID, bank account ID, invoice prefix, and rate all come from the environment.

## Usage

```bash
# Dry run first — see what would happen without touching Zoho
scripts/zoho-ateam-invoice invoice.pdf --dry-run

# With CSV cross-check (warns if CSV hours × rate ≠ PDF total)
scripts/zoho-ateam-invoice --csv timesheet.csv invoice.pdf --dry-run

# A whole folder — every PDF in it, CSVs paired by billing period
scripts/zoho-ateam-invoice ~/Downloads --dry-run

# Run for real
scripts/zoho-ateam-invoice invoice.pdf
scripts/zoho-ateam-invoice ~/Downloads

# List existing invoices
scripts/zoho-ateam-invoice --list
```

Point it at a directory and it walks every PDF inside. Unrelated PDFs (bank
statements, tax forms) are ignored and counted rather than failing the run, and
timesheet CSVs sitting alongside are matched to invoices by billing period —
ambiguous matches are skipped with a warning rather than guessed at. A single
bad export is reported and the rest of the batch continues.

## Inputs

- **Invoice PDF** (required) — exported from your contractor platform
- **Timesheet CSV** (optional) — exported from your contractor platform

If both are provided and the totals disagree, the script warns and uses the PDF amount (the invoice = what was actually paid).

## Tests

```bash
uv run pytest tests/ -v
```

56 tests covering date parsing, CSV hour formats, PDF regex parsing, exact-match idempotency, discrepancy detection, the invoice-total guard, env credential loading (precedence and merging), API payload shape, org ID propagation, payment routing, filename period-pairing, and batch behavior.

## Notes on the Zoho API

A few things that aren't obvious from the docs:

- Auth header is `Authorization: Zoho-oauthtoken {token}` — not `Bearer`
- To use a custom invoice number: append `&ignore_auto_number_generation=true` to the POST
- `POST /invoices/{id}/status/sent` marks an invoice as sent **without** emailing the customer — safe to use for backdated bookkeeping

## License

MIT
