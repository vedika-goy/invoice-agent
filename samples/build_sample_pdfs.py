"""Builds the sample PDFs in samples/invoices/ from samples/invoice_specs.json.

Run from the project root:  .venv/bin/python -m samples.build_sample_pdfs
Needs Google Chrome, used only here to print the HTML invoices to PDF. Rebuilding changes the files' bytes,
so their fingerprints and any saved readings no longer match: rebuild before the demo, not after.
"""
import html
import random
import subprocess
import sys
import tempfile
from datetime import date
from decimal import Decimal
from io import BytesIO
from pathlib import Path

import numpy
import pymupdf
from PIL import Image, ImageFilter

from invoice_engine.config import SAMPLE_INVOICES_FOLDER
from invoice_engine.decision.config import BUYER_COMPANY_NAME
from invoice_engine.utils.sample_invoices import (
    SIMPLE_LAYOUT,
    STATEMENT_LAYOUT,
    build_printed_vendor,
    compute_sample_amounts,
    format_printed_date,
    format_printed_line_money,
    format_printed_money,
    format_printed_quantity,
    load_sample_specs,
)

CHROME_PATH = Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
CHROME_TIMEOUT_S = 60
SCAN_RENDER_DPI = 110
SCAN_JPEG_QUALITY = 55
LETTER_PAGE_SIZE_POINTS = (612, 792)

BASE_CSS = """
@page { size: Letter; margin: 0; }
body { margin: 0; color: #222; }
.page { padding: 52px 60px; position: relative; min-height: 900px; }
.small { font-size: 9.5pt; color: #555; line-height: 1.5; }
table { border-collapse: collapse; }
.num { text-align: right; white-space: nowrap; }
.notice { margin-top: 22px; padding: 12px 16px; border: 2px solid #b03a2e; background: #fbeae8; font-weight: 600; font-size: 10pt; }
.stamp { position: absolute; top: 230px; left: 170px; transform: rotate(-14deg); color: #b03a2e; border: 5px solid #b03a2e;
         font-size: 34pt; font-weight: 800; padding: 6px 22px; letter-spacing: 3px; opacity: 0.85; }
"""
CLASSIC_CSS = """
body { font-family: "Helvetica Neue", Arial, sans-serif; font-size: 10.5pt; }
.header { display: flex; justify-content: space-between; border-bottom: 4px solid var(--accent); padding-bottom: 16px; }
.vendor-name { font-size: 21pt; font-weight: 700; color: var(--accent); margin-bottom: 4px; }
.title { font-size: 24pt; font-weight: 300; letter-spacing: 2px; text-align: right; }
.meta td { padding: 2px 0 2px 18px; font-size: 10pt; } .meta td:first-child { color: #777; }
.bill-to { margin-top: 26px; }
table.lines { width: 100%; margin-top: 26px; }
table.lines th { background: var(--accent); color: #fff; text-align: left; padding: 8px; font-size: 9.5pt; }
table.lines td { padding: 8px; border-bottom: 1px solid #ddd; }
table.totals { margin-left: auto; margin-top: 14px; } table.totals td { padding: 4px 8px; }
.grand td { font-weight: 700; font-size: 12pt; border-top: 2px solid #222; }
.payment { margin-top: 30px; font-size: 10pt; line-height: 1.6; }
"""
SIMPLE_CSS = """
body { font-family: Georgia, "Times New Roman", serif; font-size: 11.5pt; }
.header { text-align: center; border-bottom: 1px dashed #999; padding-bottom: 12px; }
.vendor-name { font-size: 24pt; font-style: italic; color: var(--accent); }
.meta { margin: 18px 0; } .meta td { padding: 2px 14px 2px 0; }
table.lines { width: 100%; margin-top: 10px; } table.lines th, table.lines td { border: 1px solid #aaa; padding: 7px; }
.total { text-align: right; font-size: 14pt; font-weight: 700; margin-top: 14px; }
.payment { margin-top: 26px; }
"""


def build_document_html(document: dict, vendors: dict) -> str:
    vendor = build_printed_vendor(document, vendors)
    layout = document["layout"]
    css = BASE_CSS + (SIMPLE_CSS if layout == SIMPLE_LAYOUT else CLASSIC_CSS)
    body = _build_simple_body(document, vendor) if layout == SIMPLE_LAYOUT else _build_classic_body(document, vendor)
    stamp = f'<div class="stamp">{_escape(document["stamp"])}</div>' if document.get("stamp") else ""
    return (f'<!doctype html><html><head><meta charset="utf-8"><style>{css}</style></head>'
            f'<body style="--accent: {vendor["accent_color"]}"><div class="page">{stamp}{body}</div></body></html>')


def _build_classic_body(document: dict, vendor: dict) -> str:
    layout = document["layout"]
    number_label = "Credit Note No." if document["document_type"] == "credit_note" else "Invoice No."
    meta_rows = [(number_label, document["invoice_number"]),
                 ("Statement Date" if layout == STATEMENT_LAYOUT else "Invoice Date", _printed_date(document["invoice_date"], layout)),
                 ("Due Date", _printed_date(document["due_date"], layout)),
                 ("PO Number", document["po_number"]),
                 ("Terms", None if layout == STATEMENT_LAYOUT else "Net, as agreed")]
    meta_html = "".join(f"<tr><td>{label}</td><td>{_escape(value)}</td></tr>" for label, value in meta_rows if value)
    header = (f'<div class="header"><div><div class="vendor-name">{_escape(vendor["printed_name"])}</div>'
              f'<div class="small">{"<br>".join(map(_escape, vendor["address_lines"]))}<br>{vendor["phone"]} · '
              f'{vendor["email"]}<br>Tax ID: {vendor["tax_id"]}</div></div>'
              f'<div><div class="title">{_escape(document["title"])}</div><table class="meta">{meta_html}</table></div></div>')
    bill_to = f'<div class="bill-to small"><b>Bill to</b><br>{BUYER_COMPANY_NAME}<br>{"<br>".join(_buyer_lines())}</div>'
    if layout == STATEMENT_LAYOUT:
        table, totals = _build_statement_table(document)
    else:
        table, totals = _build_classic_lines_table(document), _build_classic_totals(document)
    notice = f'<div class="notice">{_escape(document["notice"])}</div>' if document.get("notice") else ""
    return header + bill_to + table + totals + notice + _build_payment_details(document, vendor)


def _build_classic_lines_table(document: dict) -> str:
    amounts = compute_sample_amounts(document)
    rows = "".join(
        f'<tr><td>{_escape(line["item_code"])}</td><td>{_escape(line["description"])}</td>'
        f'<td class="num">{format_printed_quantity(Decimal(line["quantity"]))}</td>'
        f'<td class="num">{format_printed_line_money(Decimal(line["unit_price"]), document["layout"])}</td>'
        f'<td class="num">{format_printed_line_money(line_amount, document["layout"])}</td></tr>'
        for line, line_amount in zip(document["lines"], amounts.line_amounts, strict=True)
    )
    return ('<table class="lines"><tr><th>Item</th><th>Description</th><th class="num">Qty</th>'
            f'<th class="num">Unit price</th><th class="num">Amount</th></tr>{rows}</table>')


def _build_classic_totals(document: dict) -> str:
    amounts = compute_sample_amounts(document)
    rows = [("Subtotal", amounts.subtotal)]
    if amounts.tax is not None:
        rows.append((f"Sales tax ({document['tax_rate_percent']}%)", amounts.tax))
    if amounts.shipping is not None:
        rows.append((document.get("shipping_label", "Shipping"), amounts.shipping))
    rows_html = "".join(f'<tr><td>{label}</td><td class="num">{format_printed_money(amount)}</td></tr>' for label, amount in rows)
    total_label = "Total credit" if document["document_type"] == "credit_note" else "Total due (USD)"
    return (f'<table class="totals">{rows_html}<tr class="grand"><td>{total_label}</td>'
            f'<td class="num">{format_printed_money(amounts.total)}</td></tr></table>')


def _build_statement_table(document: dict) -> tuple[str, str]:
    rows = "".join(
        f'<tr><td>{_printed_date(entry["date"], STATEMENT_LAYOUT)}</td><td>{_escape(entry["reference"])}</td>'
        f'<td>{_escape(entry["description"])}</td><td class="num">{format_printed_money(Decimal(entry["amount"]))}</td></tr>'
        for entry in document["statement_entries"]
    )
    table = (f'<table class="lines"><tr><th>Date</th><th>Reference</th><th>Description</th><th class="num">Amount</th></tr>'
             f'{rows}</table>')
    balance = compute_sample_amounts(document).total
    totals = (f'<table class="totals"><tr class="grand"><td>Balance due</td>'
              f'<td class="num">{format_printed_money(balance)}</td></tr></table>'
              '<p class="small">This statement is for your records. Please pay against the individual invoices.</p>')
    return table, totals


def _build_simple_body(document: dict, vendor: dict) -> str:
    amounts = compute_sample_amounts(document)
    header = (f'<div class="header"><div class="vendor-name">{_escape(vendor["printed_name"])}</div>'
              f'<div class="small">{" · ".join(map(_escape, vendor["address_lines"]))} · {vendor["phone"]}<br>'
              f'Tax ID {vendor["tax_id"]}</div></div>')
    meta = (f'<table class="meta"><tr><td><b>{_escape(document["title"])} # {_escape(document["invoice_number"])}</b></td>'
            f'<td>Date: {_printed_date(document["invoice_date"], SIMPLE_LAYOUT)}</td>'
            f'<td>Due: {_printed_date(document["due_date"], SIMPLE_LAYOUT)}</td></tr></table>'
            f'<div>Sold to: {BUYER_COMPANY_NAME}, {", ".join(_buyer_lines()[1:])}</div>')
    rows = "".join(
        f'<tr><td>{_escape(line["description"])}</td><td class="num">{format_printed_quantity(Decimal(line["quantity"]))}</td>'
        f'<td class="num">{format_printed_line_money(Decimal(line["unit_price"]), SIMPLE_LAYOUT)}</td>'
        f'<td class="num">{format_printed_line_money(line_amount, SIMPLE_LAYOUT)}</td></tr>'
        for line, line_amount in zip(document["lines"], amounts.line_amounts, strict=True)
    )
    table = f'<table class="lines"><tr><th>Item</th><th>Qty</th><th>Price</th><th>Amount</th></tr>{rows}</table>'
    total = (f'<div class="total">Total {format_printed_money(amounts.total)}</div>'
             f'<div class="small" style="text-align:right">Prices include {document["tax_rate_percent"]}% sales tax '
             f'({format_printed_money(amounts.tax)}).</div>')
    return header + meta + table + total + _build_payment_details(document, vendor)


def _build_payment_details(document: dict, vendor: dict) -> str:
    if document.get("hide_bank_details"):
        return ""
    return (f'<div class="payment"><b>Payment details</b><br>Bank: {_escape(vendor["bank_name"])}<br>'
            f'Account no. {vendor["bank_account_number"]}<br>Questions? Call {vendor["phone"]}.</div>')


def _buyer_lines() -> list[str]:
    return load_sample_specs()["buyer_address_lines"]


def _printed_date(value: str | None, layout: str) -> str | None:
    return format_printed_date(date.fromisoformat(value), layout) if value else None


def _escape(value: str | None) -> str:
    return html.escape(value or "")


def print_html_to_pdf(html_text: str, working_folder: Path) -> bytes:
    html_path = working_folder / "document.html"
    pdf_path = working_folder / "document.pdf"
    html_path.write_text(html_text, encoding="utf-8")
    subprocess.run(
        [str(CHROME_PATH), "--headless=new", "--disable-gpu", "--no-pdf-header-footer",
         f"--user-data-dir={working_folder / 'chrome-profile'}", f"--print-to-pdf={pdf_path}", html_path.as_uri()],
        check=True, capture_output=True, timeout=CHROME_TIMEOUT_S,
    )
    return pdf_path.read_bytes()


def apply_scan_effect(pdf_bytes: bytes, random_seed: int) -> bytes:
    """Turns page 1 into a slightly rotated, noisy, compressed photo with no text layer, like a phone scan."""
    with pymupdf.open(stream=pdf_bytes, filetype="pdf") as document:
        pixmap = document[0].get_pixmap(dpi=SCAN_RENDER_DPI)
        image = Image.frombytes("RGB", (pixmap.width, pixmap.height), pixmap.samples)
    generator = random.Random(random_seed)
    image = image.rotate(generator.uniform(-1.2, 1.2), resample=Image.Resampling.BICUBIC, fillcolor=(245, 243, 236))
    pixels = numpy.asarray(image).astype(numpy.float32)
    pixels = pixels * numpy.array([0.97, 0.96, 0.92]) + numpy.random.default_rng(random_seed).normal(0, 7, pixels.shape)
    image = Image.fromarray(numpy.clip(pixels, 0, 255).astype(numpy.uint8)).filter(ImageFilter.GaussianBlur(0.6))
    jpeg_buffer = BytesIO()
    image.save(jpeg_buffer, format="JPEG", quality=SCAN_JPEG_QUALITY)
    scanned_document = pymupdf.open()
    page = scanned_document.new_page(width=LETTER_PAGE_SIZE_POINTS[0], height=LETTER_PAGE_SIZE_POINTS[1])
    page.insert_image(page.rect, stream=jpeg_buffer.getvalue())
    return scanned_document.tobytes(deflate=True, garbage=3)


def build_all_sample_pdfs(output_folder: Path = SAMPLE_INVOICES_FOLDER) -> list[Path]:
    if not CHROME_PATH.is_file():
        sys.exit(f"Google Chrome not found at {CHROME_PATH}; it is needed to print the sample invoices.")
    specs = load_sample_specs()
    output_folder.mkdir(parents=True, exist_ok=True)
    written_paths = []
    with tempfile.TemporaryDirectory() as working_folder_name:
        for document_index, document in enumerate(specs["documents"]):
            pdf_bytes = print_html_to_pdf(build_document_html(document, specs["vendors"]), Path(working_folder_name))
            if document["is_scan"]:
                pdf_bytes = apply_scan_effect(pdf_bytes, random_seed=document_index)
            output_path = output_folder / document["file_name"]
            output_path.write_bytes(pdf_bytes)
            written_paths.append(output_path)
            print(f"wrote {output_path.name} ({len(pdf_bytes) / 1024:.0f} KB){' [scan]' if document['is_scan'] else ''}")
    return written_paths


if __name__ == "__main__":
    build_all_sample_pdfs()
