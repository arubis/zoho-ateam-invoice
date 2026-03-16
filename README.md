# zoho-ateam-invoice

[![CI](https://github.com/arubis/zoho-ateam-invoice/actions/workflows/ci.yml/badge.svg)](https://github.com/arubis/zoho-ateam-invoice/actions/workflows/ci.yml)

An AI agent skill that automates creating [Zoho Books](https://www.zoho.com/books/) invoices from contractor timesheet exports. Works with any agent framework (Claude Code, Codex, OpenClaw, Cursor, or plain CLI). Includes a `SKILL.md` for [OpenClaw](https://openclaw.ai) auto-discovery.

Built for a contractor billing pipeline at Arboreal Studios — but the approach (OAuth token refresh, idempotent invoice creation, marking sent without emailing, recording payment) is generic enough to adapt.

## What it does

1. Parses an invoice PDF (statement number, date, hours, total)
2. Optionally cross-checks against a timesheet CSV — warns if totals disagree, uses PDF amount
3. Creates a backdated invoice in Zoho Books with a custom invoice number
4. Marks it as sent (without emailing the customer)
5. Records payment against a bank account (Bluevine in this case)

**Idempotent** — checks for an existing invoice by number before creating. Safe to re-run.

## Requirements

- Python 3.8+
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

Get OAuth credentials via the [Zoho API Console](https://api-console.zoho.com/) (Self Client app). Required scopes:

```
ZohoBooks.invoices.CREATE,READ,UPDATE
ZohoBooks.contacts.CREATE,READ
ZohoBooks.settings.READ
ZohoBooks.customerpayments.CREATE,READ,UPDATE
ZohoBooks.banking.READ
```

Update the customer ID, bank account ID, and rate constants at the top of the script to match your setup.

## Usage

```bash
# Dry run first — see what would happen without touching Zoho
scripts/zoho-ateam-invoice invoice.pdf --dry-run

# With CSV cross-check (warns if CSV hours × rate ≠ PDF total)
scripts/zoho-ateam-invoice --csv timesheet.csv invoice.pdf --dry-run

# Run for real
scripts/zoho-ateam-invoice invoice.pdf
scripts/zoho-ateam-invoice --csv timesheet.csv invoice.pdf

# List existing invoices
scripts/zoho-ateam-invoice --list
```

## Inputs

- **Invoice PDF** (required) — exported from your contractor platform
- **Timesheet CSV** (optional) — exported from your contractor platform

If both are provided and the totals disagree, the script warns and uses the PDF amount (the invoice = what was actually paid).

## Tests

```bash
uv run pytest tests/ -v
```

21 tests covering date parsing, CSV hour formats, PDF regex parsing, idempotency, discrepancy detection, env credential loading (precedence), API payload shape, org ID propagation, and payment routing.

## Notes on the Zoho API

A few things that aren't obvious from the docs:

- Auth header is `Authorization: Zoho-oauthtoken {token}` — not `Bearer`
- To use a custom invoice number: append `&ignore_auto_number_generation=true` to the POST
- `POST /invoices/{id}/status/sent` marks an invoice as sent **without** emailing the customer — safe to use for backdated bookkeeping

## License

MIT
