---
name: lidl
description: Fetch, resume, and parse Lidl UK digital receipts from lidl.co.uk purchase-history API responses. Use when a user asks to download Lidl receipt summaries, fetch receipt JSON details, parse htmlPrintedReceipt into structured articles/discounts/VAT/payment data, or create/update local Lidl receipt export files under ./data.
---

# Lidl

## Overview

Use this skill to export a user's Lidl UK receipt history into deterministic local JSON files:

- `./data/receipts_summaries.json` for paginated receipt summaries.
- `./data/receipts/{id}.json` for each raw receipt detail response.
- `./data/receipts_detail.json` for parsed receipt, article, discount, VAT, payment, and spend data.

Always ask the user for a fresh Lidl cookie copied from Chrome DevTools before making API requests. Do not hardcode or commit cookies.

## Workflow

1. Ask the user for the full request `Cookie` header from a logged-in `lidl.co.uk` Chrome session.
2. Run the helper script from the repository root. Prefer passing the cookie via `LIDL_COOKIE` so it does not appear in shell history.
3. Fetch summaries first. The script reads `totalCount` and page `size` to request every summary page.
4. Fetch detail JSON next. The script skips existing `./data/receipts/{id}.json` files, so interrupted runs can resume.
5. Parse the saved raw details into `./data/receipts_detail.json`.

## Commands

Use `scripts/lidl_receipts.py`:

```bash
LIDL_COOKIE='copy the full Cookie header here' python3 scripts/lidl_receipts.py all
```

Useful subcommands:

```bash
LIDL_COOKIE='...' python3 scripts/lidl_receipts.py summaries
LIDL_COOKIE='...' python3 scripts/lidl_receipts.py details
python3 scripts/lidl_receipts.py parse
```

When an agent already has the cookie in conversation context, prefer stdin to avoid putting the cookie on the process command line:

```bash
python3 scripts/lidl_receipts.py all --cookie-stdin
```

Default options:

- Data directory: `./data`
- Country: `GB`
- Language code: `en-GB`
- Rate limit: `3` requests/second
- Summary endpoint: `https://www.lidl.co.uk/mre/api/v1/tickets?country=GB&page={page}`
- Detail endpoint: `https://www.lidl.co.uk/mre/api/v1/tickets/{id}?country=GB&languageCode=en-GB`

Use `--data-dir`, `--country`, `--language-code`, or `--rate` only when the user asks or local context requires it.

Use `--insecure` only when the local Python TLS trust store rejects the connection with a certificate-chain error in a controlled environment.

## Output Contract

The parsed output should contain:

- `parsed_at`, `total_receipts`, `total_articles`, `total_discounts`, `total_spent`
- `receipts[]` entries with `id`, `date`, store fields, `total_amount`, `payment_method`, `card_last4`, `vat_breakdown`, `loyalty_points`, `articles`, `discounts`, `article_count`, and `discount_count`

Parsing notes:

- Parse article rows from `<span class="article">` elements and skip weight continuation rows whose visible text starts with whitespace.
- Parse discounts sequentially from `<span class="discount css_bold">` rows instead of grouping only by promotion id.
- Prefer computed totals from article line totals plus discounts when close to the displayed total, because some Lidl HTML total spans truncate.
- Extract payment method from `data-tender-description` and card last 4 from masked card patterns such as `***********0615`.
- Extract VAT from `data-tax-type`, `data-tax-percentage`, `data-tax-base-amount`, and `data-tax-amount`.

## Failure Handling

- If an API call returns `401` or `403`, ask for a fresh cookie.
- If detail fetching stops partway through, rerun `details` or `all`; existing receipt files are skipped.
- If parsing reports missing HTML receipts, keep the raw JSON files and summarize the affected receipt ids.
- Keep cookies out of files, commits, and final answers.
