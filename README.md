# Lidl Receipt Skill

An agent skill for exporting and parsing Lidl UK digital receipts from the Lidl purchase-history API.

The skill downloads receipt summaries, resumes missing receipt detail downloads, and parses each receipt's `htmlPrintedReceipt` into structured JSON for analysis.

## What It Creates

- `data/receipts_summaries.json`: paginated receipt summaries from Lidl.
- `data/receipts/{id}.json`: raw JSON detail response for each receipt.
- `data/receipts_detail.json`: parsed receipt, article, discount, VAT, payment, and spend data.

The `data/` directory is ignored by git because it contains personal receipt data.

## Skill Layout

```text
.
├── SKILL.md
├── README.md
├── scripts/
│   └── lidl_receipts.py
└── .gitignore
```

`SKILL.md` is the portable agent skill entrypoint. `scripts/lidl_receipts.py` is the deterministic helper used by agents to fetch and parse the data.

## Requirements

- Python 3.10 or newer.
- A logged-in Lidl UK browser session.
- A fresh `Cookie` request header copied from Chrome DevTools.

The helper script uses only Python's standard library.

## Smoke Test

```bash
make smoke
```

## Usage

From the repo root:

```bash
LIDL_COOKIE='copy the full Cookie header here' python3 scripts/lidl_receipts.py all
```

Subcommands:

```bash
LIDL_COOKIE='...' python3 scripts/lidl_receipts.py summaries
LIDL_COOKIE='...' python3 scripts/lidl_receipts.py update --include-articles
LIDL_COOKIE='...' python3 scripts/lidl_receipts.py summaries-since
LIDL_COOKIE='...' python3 scripts/lidl_receipts.py details
python3 scripts/lidl_receipts.py parse
python3 scripts/lidl_receipts.py status
python3 scripts/lidl_receipts.py query --days 3 --include-articles
```

`update` is optimized for "since last time we checked" questions. It reads the current `data/receipts_summaries.json`, uses the newest saved summary date as the checkpoint, fetches only enough paginated summary pages to cover newer receipts, downloads details only for new ids, reparses, and prints the new receipts.

`query` is optimized for local date-range questions and does not call Lidl:

```bash
python3 scripts/lidl_receipts.py query --start 2026-05-09 --end 2026-05-10 --include-articles
```

If an agent already has the cookie in context, it can avoid putting the cookie on the process command line:

```bash
python3 scripts/lidl_receipts.py all --cookie-stdin
```

## Options

- `--data-dir`: output directory, default `data`.
- `--country`: country code, default `GB`.
- `--language-code`: receipt language, default `en-GB`.
- `--rate`: maximum API requests per second, default `3`.
- `--insecure`: disable TLS certificate verification only when the local Python trust store rejects the connection in a controlled environment.
- `--refresh-after-hours`: age threshold used by `status`, default `6`.
- `--start` / `--end`: inclusive start and exclusive end for `query`.
- `--days`: query receipts from the last N days.
- `--include-articles`: include article and discount lines in `query` or `update` output.

## Privacy And Safety

Do not commit cookies, access tokens, raw receipts, or parsed receipt data.

The script skips existing files under `data/receipts/`, so interrupted detail downloads can be resumed safely.

## Disclaimer

This project is unofficial and is not affiliated with, endorsed by, or supported by Lidl.
