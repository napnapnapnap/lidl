#!/usr/bin/env python3
"""Fetch and parse Lidl UK digital receipts."""

from __future__ import annotations

import argparse
import glob
import html
import json
import math
import os
import re
import sys
import time
import ssl
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

SUMMARY_URL = "https://www.lidl.co.uk/mre/api/v1/tickets"
DETAIL_URL = "https://www.lidl.co.uk/mre/api/v1/tickets/{ticket_id}"


class RateLimiter:
    def __init__(self, requests_per_second: float) -> None:
        self.min_interval = 1.0 / requests_per_second if requests_per_second > 0 else 0.0
        self.last_request = 0.0

    def wait(self) -> None:
        if self.min_interval <= 0:
            return
        now = time.monotonic()
        sleep_for = self.min_interval - (now - self.last_request)
        if sleep_for > 0:
            time.sleep(sleep_for)
        self.last_request = time.monotonic()


def utc_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def read_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    with tmp_path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")
    tmp_path.replace(path)


def require_cookie(args: argparse.Namespace) -> str:
    if args.cookie_stdin:
        cookie = sys.stdin.read().strip()
    else:
        cookie = args.cookie or os.environ.get("LIDL_COOKIE")
    if not cookie:
        raise SystemExit("Missing Lidl cookie. Provide --cookie or set LIDL_COOKIE to the full Cookie header.")
    return cookie


def make_headers(cookie: str) -> dict[str, str]:
    return {
        "accept": "application/json",
        "accept-language": "en-GB,en;q=0.9",
        "referer": "https://www.lidl.co.uk/mre/purchase-history",
        "user-agent": "Mozilla/5.0",
        "cookie": cookie,
    }


def get_json(
    headers: dict[str, str],
    url: str,
    params: dict[str, str | int],
    limiter: RateLimiter,
    insecure: bool = False,
) -> Any:
    limiter.wait()
    encoded_params = urllib.parse.urlencode(params)
    request = urllib.request.Request(f"{url}?{encoded_params}", headers=headers, method="GET")
    context = ssl._create_unverified_context() if insecure else None
    try:
        with urllib.request.urlopen(request, timeout=30, context=context) as response:
            body = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        if exc.code in {401, 403}:
            raise RuntimeError(f"HTTP {exc.code}: Lidl session cookie is expired or unauthorized") from exc
        raise RuntimeError(f"HTTP {exc.code}: {body[:200]}") from exc
    return json.loads(body)


def fetch_summaries(args: argparse.Namespace) -> dict[str, Any]:
    cookie = require_cookie(args)
    headers = make_headers(cookie)
    limiter = RateLimiter(args.rate)
    output_path = args.data_dir / "receipts_summaries.json"

    first_page = get_json(headers, SUMMARY_URL, {"country": args.country, "page": 1}, limiter, args.insecure)
    size = int(first_page.get("size") or len(first_page.get("items", [])) or 10)
    total_count = int(first_page.get("totalCount") or len(first_page.get("items", [])))
    total_pages = max(1, math.ceil(total_count / size))
    items = list(first_page.get("items", []))

    print(f"Summaries page 1/{total_pages}: {len(items)}/{total_count}")
    for page in range(2, total_pages + 1):
        data = get_json(headers, SUMMARY_URL, {"country": args.country, "page": page}, limiter, args.insecure)
        page_items = data.get("items", [])
        items.extend(page_items)
        print(f"Summaries page {page}/{total_pages}: {len(items)}/{total_count}", flush=True)

    export = {
        "fetched_at": utc_now(),
        "page": 1,
        "size": size,
        "totalCount": total_count,
        "items": items,
    }
    write_json(output_path, export)
    print(f"Saved {len(items)} summaries to {output_path}")
    return export


def load_summaries(data_dir: Path) -> dict[str, Any]:
    path = data_dir / "receipts_summaries.json"
    if not path.exists():
        raise SystemExit(f"Missing {path}. Run the summaries command first.")
    return read_json(path)


def fetch_details(args: argparse.Namespace) -> None:
    cookie = require_cookie(args)
    export = load_summaries(args.data_dir)
    receipt_ids = [item["id"] for item in export.get("items", []) if item.get("id")]
    raw_dir = args.data_dir / "receipts"
    raw_dir.mkdir(parents=True, exist_ok=True)
    existing = {p.stem for p in raw_dir.glob("*.json") if p.name != "_manifest.json"}
    to_fetch = [rid for rid in receipt_ids if rid not in existing]

    print(f"Total: {len(receipt_ids)}, already fetched: {len(existing)}, remaining: {len(to_fetch)}")
    if not to_fetch:
        return

    headers = make_headers(cookie)
    limiter = RateLimiter(args.rate)
    errors: list[dict[str, str]] = []
    success = 0
    start = time.time()

    for index, receipt_id in enumerate(to_fetch, start=1):
        try:
            data = get_json(
                headers,
                DETAIL_URL.format(ticket_id=receipt_id),
                {"country": args.country, "languageCode": args.language_code},
                limiter,
                args.insecure,
            )
            write_json(raw_dir / f"{receipt_id}.json", data)
            success += 1
        except Exception as exc:  # noqa: BLE001 - report and continue
            errors.append({"id": receipt_id, "error": f"{type(exc).__name__}: {exc}"})

        if index % 25 == 0 or index == len(to_fetch):
            elapsed = max(time.time() - start, 0.001)
            print(
                f"Details {index}/{len(to_fetch)} | OK:{success} ERR:{len(errors)} | {elapsed:.0f}s",
                flush=True,
            )

    manifest = {
        "fetched_at": utc_now(),
        "total_receipts": len(receipt_ids),
        "already_present_at_start": len(existing),
        "successfully_fetched_this_run": success,
        "errors": errors,
    }
    write_json(raw_dir / "_manifest.json", manifest)
    if errors:
        print("First errors:")
        for error in errors[:5]:
            print(f"  {error['id']}: {error['error']}")


def parse_float(value: str | None) -> float | None:
    if value in {None, ""}:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def parse_html_receipt(receipt_html: str) -> dict[str, Any]:
    h = html.unescape(receipt_html)
    articles: list[dict[str, Any]] = []

    article_pattern = re.compile(r'<span[^>]*class="[^"]*\barticle\b[^"]*"[^>]*>(.*?)</span>', re.DOTALL)
    for match in article_pattern.finditer(h):
        span_content = match.group(1)
        full_span = match.group(0)
        raw_visible = re.sub(r"<[^>]+>", "", span_content)
        visible = raw_visible.strip()

        if raw_visible and raw_visible[0].isspace():
            continue
        if visible in {"", "£"}:
            continue

        art_id = re.search(r'data-art-id="([^"]*)"', full_span)
        desc = re.search(r'data-art-description="([^"]*)"', full_span)
        unit_price = re.search(r'data-unit-price="([^"]*)"', full_span)
        tax_type = re.search(r'data-tax-type="([^"]*)"', full_span)
        quantity = re.search(r'data-art-quantity="([^"]*)"', full_span)
        total_match = re.search(r"(-?\d+\.\d{1,2})\s*(?:[A-Z])?\s*$", visible)

        articles.append(
            {
                "article_id": art_id.group(1) if art_id else None,
                "description": desc.group(1) if desc else None,
                "quantity": parse_float(quantity.group(1) if quantity else None) or 1.0,
                "unit_price": parse_float(unit_price.group(1) if unit_price else None),
                "line_total": parse_float(total_match.group(1) if total_match else None),
                "tax_type": tax_type.group(1) if tax_type else None,
            }
        )

    discounts: list[dict[str, Any]] = []
    discount_pattern = re.compile(
        r'<span[^>]*class="[^"]*\bdiscount\b[^"]*\bcss_bold\b[^"]*"[^>]*data-promotion-id="([^"]*)"[^>]*>'
        r"(.*?)</span>",
        re.DOTALL,
    )
    pending_labels: dict[str, str] = {}
    for discount in discount_pattern.finditer(h):
        promotion_id = discount.group(1)
        text = re.sub(r"<[^>]+>", "", discount.group(2)).strip()
        amount_text = text.replace("£", "")
        if re.fullmatch(r"-?\d+\.\d{1,2}", amount_text):
            discounts.append(
                {
                    "promotion_id": promotion_id,
                    "label": pending_labels.get(promotion_id),
                    "amount": float(amount_text),
                }
            )
        elif text:
            pending_labels[promotion_id] = text

    article_total = sum(a["line_total"] for a in articles if a["line_total"] is not None)
    discount_total = sum(d["amount"] for d in discounts if d["amount"] is not None)
    computed_total = round(article_total + discount_total, 2)
    summary_start = h.find("purchase_summary")
    summary_end = h.find("purchase_tender_information")
    summary_section = h[summary_start:summary_end] if summary_start != -1 and summary_end != -1 else h
    html_total_match = re.search(r"TOTAL.*?(\d+\.\d{1,2})", summary_section, re.DOTALL)
    html_total = parse_float(html_total_match.group(1) if html_total_match else None)
    total_amount = computed_total if html_total is None or abs(computed_total - html_total) <= 0.10 else html_total

    tender_match = re.search(r'data-tender-description="([^"]*)"', h)
    card_match = re.search(r"\*{6,}(\d{4})", h)
    vat_items = []
    for vat in re.finditer(
        r'data-tax-type="([^"]*)"[^>]*data-tax-percentage="([^"]*)"[^>]*'
        r'data-tax-base-amount="([^"]*)"[^>]*data-tax-amount="([^"]*)"',
        h,
    ):
        vat_items.append(
            {
                "tax_type": vat.group(1),
                "percentage": float(vat.group(2)),
                "base_amount": float(vat.group(3)),
                "tax_amount": float(vat.group(4)),
            }
        )

    return {
        "articles": articles,
        "discounts": discounts,
        "total_amount": total_amount,
        "payment_method": tender_match.group(1) if tender_match else None,
        "card_last4": card_match.group(1) if card_match else None,
        "vat_breakdown": vat_items,
        "article_count": len(articles),
        "discount_count": len(discounts),
    }


def parse_receipts(args: argparse.Namespace) -> None:
    export = load_summaries(args.data_dir)
    meta_lookup = {item["id"]: item for item in export.get("items", []) if item.get("id")}
    raw_files = sorted(
        Path(path)
        for path in glob.glob(str(args.data_dir / "receipts" / "*.json"))
        if not path.endswith("_manifest.json")
    )
    parsed = []
    errors = []

    for raw_file in raw_files:
        receipt_id = raw_file.stem
        meta = meta_lookup.get(receipt_id, {})
        try:
            data = read_json(raw_file)
            ticket = data.get("ticket", {})
            receipt_html = ticket.get("htmlPrintedReceipt") or ""
            store = ticket.get("store") or {}
            if not receipt_html:
                errors.append({"id": receipt_id, "error": "no htmlPrintedReceipt"})
                continue
            result = parse_html_receipt(receipt_html)
            parsed.append(
                {
                    "id": receipt_id,
                    "date": ticket.get("date") or meta.get("date"),
                    "store_name": store.get("name") or meta.get("store"),
                    "store_address": store.get("address"),
                    "store_postcode": store.get("postalCode"),
                    "locality": store.get("locality"),
                    "total_amount": result["total_amount"] if result["total_amount"] is not None else meta.get("totalAmount"),
                    "payment_method": result["payment_method"],
                    "card_last4": result["card_last4"],
                    "vat_breakdown": result["vat_breakdown"],
                    "loyalty_points": (data.get("collectingModel") or {}).get("points", 0),
                    "articles": result["articles"],
                    "discounts": result["discounts"],
                    "article_count": result["article_count"],
                    "discount_count": result["discount_count"],
                }
            )
        except Exception as exc:  # noqa: BLE001 - keep parsing remaining files
            errors.append({"id": receipt_id, "error": f"{type(exc).__name__}: {exc}"})

    total_articles = sum(r["article_count"] for r in parsed)
    total_discounts = sum(r["discount_count"] for r in parsed)
    total_spent = round(sum(r["total_amount"] or 0 for r in parsed), 2)
    output = {
        "parsed_at": utc_now(),
        "total_receipts": len(parsed),
        "total_articles": total_articles,
        "total_discounts": total_discounts,
        "total_spent": total_spent,
        "receipts": parsed,
    }
    write_json(args.data_dir / "receipts_detail.json", output)
    print(f"Parsed {len(parsed)} receipts to {args.data_dir / 'receipts_detail.json'}")
    print(f"Total articles: {total_articles}, discounts: {total_discounts}, spent: GBP {total_spent:.2f}")
    if errors:
        print("First parse errors:")
        for error in errors[:5]:
            print(f"  {error['id']}: {error['error']}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Fetch and parse Lidl UK digital receipts.")
    parser.add_argument("command", choices=["summaries", "details", "parse", "all"])
    parser.add_argument("--data-dir", type=Path, default=Path("data"))
    parser.add_argument("--country", default="GB")
    parser.add_argument("--language-code", default="en-GB")
    parser.add_argument("--cookie", help="Full Lidl Cookie header. Prefer LIDL_COOKIE instead.")
    parser.add_argument("--cookie-stdin", action="store_true", help="Read the full Lidl Cookie header from stdin.")
    parser.add_argument("--rate", type=float, default=3.0, help="Maximum API requests per second.")
    parser.add_argument("--insecure", action="store_true", help="Disable TLS certificate verification.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    args.data_dir = args.data_dir.expanduser().resolve()

    if args.command in {"summaries", "all"}:
        fetch_summaries(args)
    if args.command in {"details", "all"}:
        fetch_details(args)
    if args.command in {"parse", "all"}:
        parse_receipts(args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
