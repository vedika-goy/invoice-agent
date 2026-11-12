-- Money and quantities are stored as decimal text, never as floats.

CREATE TABLE IF NOT EXISTS vendors (
    vendor_id TEXT PRIMARY KEY,
    vendor_name TEXT NOT NULL,
    tax_id TEXT NOT NULL,
    status TEXT NOT NULL,
    currency TEXT NOT NULL,
    bank_account_last4 TEXT NOT NULL,
    payment_terms_days INTEGER NOT NULL,
    phone_on_file TEXT NOT NULL,
    remit_email TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS purchase_order_lines (
    po_number TEXT NOT NULL,
    po_line INTEGER NOT NULL,
    vendor_id TEXT NOT NULL,
    item_code TEXT NOT NULL,
    description TEXT NOT NULL,
    unit_of_measure TEXT NOT NULL,
    quantity_ordered TEXT NOT NULL,
    quantity_received TEXT NOT NULL,
    unit_price TEXT NOT NULL,
    currency TEXT NOT NULL,
    status TEXT NOT NULL,
    requested_by TEXT NOT NULL,
    po_date TEXT NOT NULL,
    PRIMARY KEY (po_number, po_line)
);

-- One row per approved or paid invoice. The unique key is what makes "record approval once" hold.
CREATE TABLE IF NOT EXISTS ledger_invoices (
    ledger_invoice_id INTEGER PRIMARY KEY AUTOINCREMENT,
    vendor_id TEXT NOT NULL,
    invoice_number TEXT NOT NULL,
    invoice_number_normalized TEXT NOT NULL,
    invoice_date TEXT NOT NULL,
    invoice_total TEXT NOT NULL,
    currency TEXT NOT NULL,
    source TEXT NOT NULL,
    run_id INTEGER,
    status_label TEXT NOT NULL,
    recorded_at TEXT NOT NULL,
    UNIQUE (vendor_id, invoice_number_normalized)
);

CREATE TABLE IF NOT EXISTS ledger_lines (
    ledger_invoice_id INTEGER NOT NULL REFERENCES ledger_invoices (ledger_invoice_id) ON DELETE CASCADE,
    po_number TEXT NOT NULL,
    po_line INTEGER NOT NULL,
    quantity TEXT NOT NULL,
    line_amount TEXT NOT NULL
);

-- Kept by "Reset demo data", so the demo never has to call the AI twice for the same file.
CREATE TABLE IF NOT EXISTS saved_readings (
    fingerprint TEXT PRIMARY KEY,
    reading_json TEXT NOT NULL,
    reading_report_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS runs (
    run_id INTEGER PRIMARY KEY AUTOINCREMENT,
    fingerprint TEXT NOT NULL UNIQUE,
    file_name TEXT NOT NULL,
    pdf_bytes BLOB NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS decisions (
    decision_id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL REFERENCES runs (run_id) ON DELETE CASCADE,
    trigger TEXT NOT NULL,
    outcome TEXT NOT NULL,
    policy_version TEXT NOT NULL,
    decision_record_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS reviewer_actions (
    action_id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL REFERENCES runs (run_id) ON DELETE CASCADE,
    decision_id INTEGER NOT NULL REFERENCES decisions (decision_id) ON DELETE CASCADE,
    action TEXT NOT NULL,
    system_outcome TEXT NOT NULL,
    reviewer_note TEXT NOT NULL,
    created_at TEXT NOT NULL
);
